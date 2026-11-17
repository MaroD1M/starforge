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
import struct
import time

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
    return dst


# ---------------------------------------------------------------- 主操作


def apply_seed(save_path: str, slot: int, source: ShipRef, confirm: bool = False) -> dict:
    """把 source 的外观（seed）写到 save_path 的第 slot 艘船（必须同型）。"""
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
        return {"ok": True, "path": save_path, "slot": slot, "type": tgt_type,
                "before": before, "after": again[0].seed, "backup": backup,
                "bytes": len(data), "verified": True}
    except Exception as e:                                  # noqa: BLE001
        # 回滚：先原子写回原始字节，再保留备份
        try:
            _atomic_write(save_path, original)
            log.error("写入失败已回滚：%s（备份 %s）", e, backup)
        except Exception as e2:                             # noqa: BLE001
            log.error("回滚也失败！请手工把 %s 复制回 %s（%s）", backup, save_path, e2)
        raise WriteRefused(f"写入未完成，已回滚：{e}。备份保留在 {backup}") from e


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
