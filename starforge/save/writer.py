"""写回存档：同型换种子（F05）。

四步铁律（手册 §2.9）：
  读 → 备份 → 原子写（.part + os.replace）→ 重新解码校验；任何一步失败都回滚。

为什么不用上游的 `OpenSave.write()`：它是非原子写（直接 open(path,'wb')），
写到一半断电/被杀就得到一个半截存档。这里自己编码 + 原子替换，并且写后重新解码核对。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from ..core import log, paths, settings
from ..core.errors import BadRequest, WriteRefused
from ..data.shipref import ShipRef

log = log.get("save.writer")


# ---------------------------------------------------------------- 运行检测（尽力而为）

def game_running() -> bool:
    """游戏在跑就别写（会被游戏覆盖）。检测不到就返回 False，不阻塞用户。"""
    try:
        import os as _os
        if _os.name == "nt":
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32
            TH32CS_SNAPPROCESS = 0x00000002

            class PE32(ctypes.Structure):
                _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                            ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]

            snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if snap in (0, -1):
                return False
            try:
                e = PE32()
                e.dwSize = ctypes.sizeof(PE32)
                ok = k32.Process32First(snap, ctypes.byref(e))
                while ok:
                    if e.szExeFile.decode("mbcs", "replace").lower() == "nms.exe":
                        return True
                    ok = k32.Process32Next(snap, ctypes.byref(e))
            finally:
                k32.CloseHandle(snap)
            return False
        # Linux / Proton
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/comm", "rb") as f:
                    name = f.read().decode("utf-8", "replace").strip().lower()
                if name in ("nms.exe", "no man's sky"):
                    return True
            except OSError:
                continue
    except Exception as e:                                  # noqa: BLE001
        log.debug("进程检测不可用：%s", e)
    return False


# ---------------------------------------------------------------- 编解码（复用上游的映射与容器）


def _nms():
    paths.ensure_shipwright_importable()
    from nms_save import codec, mapping, save as nms_save, ships as nms_ships
    return codec, mapping, nms_save, nms_ships


def _encode(opened) -> bytes:
    codec, mapping, _, _ = _nms()
    obf = mapping.obfuscate(opened.readable)
    text = json.dumps(obf, separators=(",", ":"))
    return codec.encode(text, getattr(opened, "_chunked", True), getattr(opened, "_trailing_nul", 1))


def _atomic_write(path: str, data: bytes) -> None:
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)          # 同目录内原子替换


def _backup(path: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-%06d" % (int(time.time() * 1e6) % 1_000_000)
    dst = f"{path}.{stamp}.bak"
    shutil.copy2(path, dst)
    keep = int(getattr(settings.current(), "backup_keep", 0) or 0)
    if keep > 0:
        try:
            backups = sorted(Path(path).parent.glob(Path(path).name + ".*.bak"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
            for old in backups[keep:]:
                old.unlink(missing_ok=True)
                log.info("按 backup_keep=%s 清理旧备份：%s", keep, old.name)
        except OSError as e:                                # noqa: BLE001
            log.warning("清理旧备份失败（不影响本次写入）：%s", e)
    return dst


# ---------------------------------------------------------------- 主操作


def apply_seed(save_path: str, slot: int, source: ShipRef, confirm: bool = False,
               copy: bool = False) -> dict:
    """把 source 的外观（seed）写到 save_path 的第 slot 艘船（必须同型）。

    copy=True 时不动原档：先复制一份 `<存档>.edited.hg`，改那份。
    想进游戏验证就把它改名成 save.hg / save2.hg（原档永远在）。
    """
    settings.require_write()                                # 写开关未开 -> 403 write_disabled
    if not confirm:
        raise BadRequest("缺少 confirm=true（写操作必须二次确认）")
    if game_running():
        raise WriteRefused("游戏正在运行，请先退出游戏再写入（否则会被游戏覆盖）")

    codec, mapping, nms_save, nms_ships = _nms()
    src = source.normalized()
    if not src.proc_model_matches():
        raise BadRequest(f"{src.type} 的模型不是 _PROC，改种子不会改变外观")
    if not os.path.exists(save_path):
        raise BadRequest(f"存档不存在：{save_path}")

    original_path = save_path
    if copy:
        if not save_path.endswith(".edited.hg"):
            base = save_path[:-3] if save_path.lower().endswith(".hg") else save_path
            save_path = base + ".edited.hg"          # save.hg → save.edited.hg
        shutil.copy2(original_path, save_path)
        log.info("写回使用副本：%s（原档 %s 不动）", save_path, original_path)

    opened = nms_save.open_save(save_path)
    ships = nms_ships.list_ships(opened.readable)
    target = next((s for s in ships if s.index == slot), None)
    if target is None:
        raise BadRequest(f"存档里没有第 {slot} 艘船（共 {len(ships)} 艘）")
    tgt_type = ShipRef.from_save_ship(target).normalized().type
    if tgt_type != src.type:
        raise BadRequest(
            f"跨型不可移植：目标槽位是 {tgt_type}，源是 {src.type}。"
            "不同船型的部件树不同，同一个 seed 会长成完全不同的船；请改用「按部件搜索」找一艘相近的。")

    before = target.seed
    original = open(save_path, "rb").read()
    backup = _backup(save_path)
    library_clear = None
    try:
        from . import library as _lib
        library_clear = _lib.clear_cache
    except Exception:                                      # noqa: BLE001
        pass
    log.info("写回：%s 槽位 %d（%s）%s → %s；备份 %s",
             os.path.basename(save_path), slot, tgt_type, before, src.seed, backup)

    try:
        nms_ships.set_ship_seed(opened.readable, slot, src.seed)
        data = _encode(opened)
        _atomic_write(save_path, data)

        # 写后重新解码核对（不信任自己的写入）
        reread = nms_save.open_save(save_path)
        again = [s for s in nms_ships.list_ships(reread.readable) if s.index == slot]
        if not again or again[0].seed.upper() != src.seed.upper():
            raise WriteRefused("写后校验失败：种子与预期不符")
        if library_clear:
            library_clear()
        return {"ok": True, "path": save_path, "original": original_path, "copy": bool(copy),
                "slot": slot, "type": tgt_type,
                "before": before, "after": again[0].seed, "backup": backup,
                "bytes": len(data), "verified": True}
    except Exception as e:                                  # noqa: BLE001
        # 回滚：先原子写回原始字节，再保留备份
        try:
            _atomic_write(save_path, original)
            if library_clear:
                library_clear()
            log.error("写入失败已回滚：%s（备份 %s）", e, backup)
        except Exception as e2:                             # noqa: BLE001
            log.error("回滚也失败！请手工把 %s 复制回 %s（%s）", backup, save_path, e2)
        raise WriteRefused(f"写入未完成，已回滚：{e}。备份保留在 {backup}") from e


def apply_class(save_path: str, slot: int, ship_class: str = "", values: dict | None = None,
                best: bool = False, confirm: bool = False, copy: bool = False) -> dict:
    """改船级与属性（F14）。

    与 `apply_seed` 完全同一套铁律：游戏在跑就不写 → 备份 → 原子写 → 重新解码核对 →
    任何一步失败立刻回滚原始字节。额外两条：
      · 属性值必须落在"这艘船这个等级游戏会给的区间"内，否则拒绝（不造不可能的船）；
      · 写完要核对**其它船的种子一个都没动**（写错槽位是最贵的 bug）。
    """
    settings.require_write()
    if not confirm:
        raise BadRequest("缺少 confirm=true（写操作必须二次确认）")
    if game_running():
        raise WriteRefused("游戏正在运行，请先退出游戏再写入（否则会被游戏覆盖）")
    ship_class = (ship_class or "").strip().upper()
    if ship_class and ship_class not in ("C", "B", "A", "S"):
        raise BadRequest(f"船级只能是 C/B/A/S，收到 {ship_class!r}")
    if not ship_class and not values and not best:
        raise BadRequest("没有要改的内容：至少给 ship_class、values 或 best=true 之一")

    codec, mapping, nms_save, nms_ships = _nms()
    if not os.path.exists(save_path):
        raise BadRequest(f"存档不存在：{save_path}")

    original_path = save_path
    if copy:
        save_path = _copy_path(save_path)
        shutil.copy2(original_path, save_path)
        log.info("改级使用副本：%s（原档 %s 不动）", save_path, original_path)

    opened = nms_save.open_save(save_path)
    all_ships_before = {s.index: s.seed for s in nms_ships.list_ships(opened.readable)}
    if slot not in all_ships_before:
        raise BadRequest(f"存档里没有第 {slot} 艘船（共 {len(all_ships_before)} 艘）")
    before = nms_ships.ship_stats(opened.readable, slot)

    original = open(save_path, "rb").read()
    backup = _backup(save_path)
    try:
        from . import library as _lib
        library_clear = _lib.clear_cache
    except Exception:                                       # noqa: BLE001
        library_clear = None

    try:
        nms_ships.set_ship_stats(opened.readable, slot,
                                 values={k: float(v) for k, v in (values or {}).items()} or None,
                                 ship_class=ship_class or None, best=bool(best))
        data = _encode(opened)
        _atomic_write(save_path, data)

        reread = nms_save.open_save(save_path)
        after = nms_ships.ship_stats(reread.readable, slot)
        if ship_class and after["class"] != ship_class:
            raise WriteRefused(f"写后校验失败：等级读到 {after['class']}，预期 {ship_class}")
        changed = {s.index: s.seed for s in nms_ships.list_ships(reread.readable)}
        if changed != all_ships_before:
            raise WriteRefused("写后校验失败：其它船的种子被改动了（写错槽位）")
        if library_clear:
            library_clear()
        log.info("改级：%s 槽位 %d %s → %s（备份 %s）", os.path.basename(save_path), slot,
                 before["class"], after["class"], backup)
        return {"ok": True, "path": save_path, "original": original_path, "copy": bool(copy),
                "slot": slot, "backup": backup, "bytes": len(data),
                "before": before, "after": after, "ships_untouched": True, "verified": True}
    except Exception as e:                                  # noqa: BLE001
        try:
            _atomic_write(save_path, original)
            if library_clear:
                library_clear()
            log.error("改级失败已回滚：%s（备份 %s）", e, backup)
        except Exception as e2:                             # noqa: BLE001
            log.error("回滚也失败！请手工把 %s 复制回 %s（%s）", backup, save_path, e2)
        raise WriteRefused(f"改级未完成，已回滚：{e}。备份保留在 {backup}") from e


def _copy_path(save_path: str) -> str:
    """`save.hg` → `save.edited.hg`（已经带 .edited.hg 就原样）。"""
    if save_path.endswith(".edited.hg"):
        return save_path
    base = save_path[:-3] if save_path.lower().endswith(".hg") else save_path
    return base + ".edited.hg"


def restore(save_path: str, backup_path: str, confirm: bool = False) -> dict:
    """从备份恢复（手册 F13 诊断里的"一键恢复"）。"""
    settings.require_write()
    if not confirm:
        raise BadRequest("缺少 confirm=true")
    if not os.path.exists(backup_path):
        raise BadRequest(f"备份不存在：{backup_path}")
    if not os.path.basename(backup_path).startswith(os.path.basename(save_path) + "."):
        raise BadRequest("备份文件名与存档不匹配，拒绝覆盖")
    if game_running():
        raise WriteRefused("游戏正在运行，请先退出")
    safety = _backup(save_path)                             # 恢复前也留一份当前状态
    data = open(backup_path, "rb").read()
    _atomic_write(save_path, data)
    try:
        from . import library as _lib
        _lib.clear_cache()
    except Exception:                                      # noqa: BLE001
        pass
    nms_save = _nms()[2]
    nms_save.open_save(save_path)                           # 能打开就算恢复成功
    log.info("已从备份恢复 %s（恢复前快照 %s）", backup_path, safety)
    return {"ok": True, "path": save_path, "restored_from": backup_path, "safety_copy": safety}


def backups(save_path: str) -> list[dict]:
    _, _, nms_save, _ = _nms()
    out = []
    for p in nms_save.backups_of(save_path):
        st = os.stat(p)
        out.append({"path": p, "bytes": st.st_size, "mtime": int(st.st_mtime)})
    return out
