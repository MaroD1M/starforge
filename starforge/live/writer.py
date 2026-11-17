"""实时通道写入器：在游戏内存里定位"模板槽的种子字段"，写进去，读回校验。

定位思路（对应上一轮审计 P0-2 的整改）：
  模板 Mod 给每个槽的出厂种子是 ASCII `STARFORGE<i>`（8 字节，**每槽唯一**），
  且 `ShipLayout.Slots` 取 120+i（不会被游戏归一化）。
  所以：
    1. 全内存扫出厂种子 → 得到若干候选；
    2. 读候选附近 ±0x60 的窗口，检查是否出现对应的 Slots 值（u32）→ 结构自洽；
    3. 只有"命中唯一且自洽"才写；多个候选都自洽则拒绝（宁可不写，也不写错船）。

写入后立刻回读比对；不符就当失败（调用方不再信任该地址）。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from ..core import log
from . import compat, exml, mem as mem_mod

log = log.get("live.writer")

WINDOW = 0x60          # 候选附近检查范围


def all_entries() -> list[dict]:
    """我们自己的 8 槽 + 兼容 SSH 的 2 槽（后者只在用户装了 SSH 时才会命中）。"""
    own = [{**e, "source": "starforge"} for e in exml.manifest()]
    return own + compat.manifest()
MIN_REGION = 0x1000


class LocateError(RuntimeError):
    pass


@dataclass
class Slot:
    index: int
    type: str
    seed_addr: int
    score: float
    verified_slots: bool
    factory_seed: int
    slots: int


def _score(proc, addr: int, entry: dict) -> float:
    """结构自洽打分：附近出现该槽的 Slots 值 + 出厂种子仍在原位。"""
    score = 0.0
    try:
        win = proc.read(max(0, addr - WINDOW), WINDOW * 2)
    except mem_mod.LiveUnsupported:
        return 0.0
    target = struct.pack("<I", entry["slots"])
    if target in win:
        score += 0.6
    if struct.pack("<Q", entry["factory_seed"]) in win:
        score += 0.4
    return score


def _cache(proc) -> dict:
    """按进程对象缓存已定位的槽地址（出厂种子一旦被写掉，就无法再靠它定位）。"""
    c = getattr(proc, "_sf_slots", None)
    if c is None:
        c = {}
        setattr(proc, "_sf_slots", c)
    return c


def _still_valid(proc, slot: Slot, entry: dict) -> bool:
    """缓存地址是否还指向同一个槽：附近仍能看到该槽的 Slots 值。"""
    try:
        win = proc.read(max(0, slot.seed_addr - WINDOW), WINDOW * 2)
    except mem_mod.LiveUnsupported:
        return False
    return struct.pack("<I", entry["slots"]) in win


def scan_all(proc, entries: list[dict] | None = None, fresh: bool = False,
             max_per_entry: int = 32) -> dict[str, list[tuple[int, float]]]:
    """**只读**、单次遍历内存，返回 {entry_id: [(addr, score), ...]}。

    对我们的 8 槽，8 个出厂种子共享 7 字节前缀 `STARFOR`，先按前缀粗筛再按第 8 字节分类；
    对兼容条目（SSH 的种子互不相同）则逐个种子搜索。两种都只读。
    """
    entries = entries if entries is not None else all_entries()
    cache = getattr(proc, "_sf_scan", None)
    cache_key = tuple(e["id"] for e in entries)
    if cache is not None and not fresh and getattr(proc, "_sf_scan_key", None) == cache_key:
        return cache

    found: dict[str, list[tuple[int, float]]] = {e["id"]: [] for e in entries}
    def _is_own(e: dict) -> bool:                     # 缺省视为我们自己的槽
        return e.get("source", "starforge") == "starforge"

    own = [e for e in entries if _is_own(e)]
    by_index = {e["index"]: e for e in own}

    for region in proc.regions(min_size=MIN_REGION):
        try:
            buf = proc.read(region.base, region.size)
        except mem_mod.LiveUnsupported:
            continue
        # (a) 我们的 8 槽：一次 find 覆盖全部
        if own:
            start = 0
            while True:
                i = buf.find(exml.TAG, start)
                if i < 0 or i + 8 > len(buf):
                    break
                start = i + 1
                idx = buf[i + 7]
                entry = by_index.get(idx - 0xA0) if 0xA0 <= idx <= 0xAF else None
                if entry is None:
                    continue
                addr = region.base + i
                bucket = found[entry["id"]]
                if len(bucket) < max_per_entry:
                    bucket.append((addr, _score(proc, addr, entry)))
        # (b) 兼容条目：逐个种子搜（它们的种子彼此不同，不会串味）
        for e in entries:
            if _is_own(e):
                continue
            pat = struct.pack("<Q", e["factory_seed"])
            start = 0
            while True:
                i = buf.find(pat, start)
                if i < 0:
                    break
                start = i + 1
                addr = region.base + i
                bucket = found[e["id"]]
                if len(bucket) < max_per_entry:
                    bucket.append((addr, _score(proc, addr, e)))

    try:
        setattr(proc, "_sf_scan", found)
        setattr(proc, "_sf_scan_key", cache_key)
    except Exception:                                       # noqa: BLE001
        pass
    hits = sum(len(v) for v in found.values())
    log.info("模板槽扫描：%d 处命中，覆盖 %d 条模板", hits, sum(1 for v in found.values() if v))
    return found


def locate(proc, type_: str, entries: list[dict] | None = None, fresh: bool = False) -> Slot:
    """在进程内存里找到 type_ 对应模板槽的种子地址（优先用缓存）。"""
    entries = entries if entries is not None else all_entries()
    matches = [e for e in entries if e["type"] == type_]
    if not matches:
        raise LocateError(f"模板清单里没有船型 {type_}")
    entry = matches[0]                                   # 自己的模板优先；没有则用兼容槽

    cache = _cache(proc)
    if not fresh and type_ in cache and _still_valid(proc, cache[type_], entry):
        return cache[type_]

    scanned = scan_all(proc, entries, fresh=fresh)
    # 同一船型可能既有我们的槽、也有 SSH 的槽：全收，按得分排序；
    # 得分并列时优先"自己的模板"（更可控），再按地址稳定排序。
    scored = []
    for e in matches:
        prefer = 0 if e.get("source", "starforge") == "starforge" else 1
        for a, sc in scanned.get(e["id"], []):
            if sc >= 0.6:
                scored.append((prefer, a, sc, e))
    if not scored:
        raise LocateError(
            f"没找到 {type_} 的模板槽。可能原因：① 没装 starforge-templates 数据 Mod；"
            "② 游戏版本变了导致布局不同；③ 还没进过存档。")
    scored.sort(key=lambda x: (x[0], -x[2], x[1]))
    if len(scored) > 1 and scored[0][0] == scored[1][0] and abs(scored[0][2] - scored[1][2]) < 1e-9:
        raise LocateError(f"{type_} 的模板槽命中多个同样可信的候选（{len(scored)} 个），拒绝写入")
    _prefer, addr, score, entry = scored[0]
    log.info("定位 %s 模板槽：0x%X（score %.2f，来源 %s）", type_, addr, score,
             entry.get("source", "starforge"))
    slot = Slot(index=entry["index"], type=type_, seed_addr=addr, score=score,
                verified_slots=True, factory_seed=entry["factory_seed"], slots=entry["slots"])
    cache[type_] = slot
    return slot


def push(proc, type_: str, seed: str | int, entries: list[dict] | None = None) -> dict:
    """把外观种子写进模板槽并回读校验（只写 8 字节）。"""
    value = int(seed, 16) if isinstance(seed, str) else int(seed)
    slot = locate(proc, type_, entries)
    before = proc.read_u64(slot.seed_addr)
    if before == value:
        return {"ok": True, "unchanged": True, "address": slot.seed_addr, "seed": value}
    if not proc.write_u64(slot.seed_addr, value):
        raise LocateError(f"写入失败：0x{slot.seed_addr:X} 不可写（权限或页保护）")
    after = proc.read_u64(slot.seed_addr)
    if after != value:
        raise LocateError(f"回读校验失败：期望 0x{value:016X}，实际 0x{after:016X}")
    log.info("写入 %s 模板槽：0x%X 0x%016X → 0x%016X", type_, slot.seed_addr, before, after)
    return {"ok": True, "address": slot.seed_addr, "type": type_,
            "before": before, "after": after, "seed": value, "score": slot.score}


def scan_structural(proc, entries: list[dict] | None = None,
                    max_hits: int = 8) -> dict[str, list[int]]:
    """**只读**兜底策略：按 `ShipLayout{Slots, Seed=1, Level=1}` 的整数三联找候选。

    用途：如果游戏把出厂种子归一化了（审计里的 P0-2 场景），靠种子就找不到槽。
    这里只**报告**候选地址，不参与写入——避免在不确定布局时写错对象。
    """
    entries = entries if entries is not None else all_entries()
    out: dict[str, list[int]] = {}
    targets = {e["id"]: e["slots"] for e in entries}
    for region in proc.regions(min_size=MIN_REGION):
        try:
            buf = proc.read(region.base, region.size)
        except mem_mod.LiveUnsupported:
            continue
        for eid, slots in targets.items():
            pat = struct.pack("<III", int(slots), 1, 1)
            start = 0
            while True:
                i = buf.find(pat, start)
                if i < 0:
                    break
                start = i + 1
                bucket = out.setdefault(eid, [])
                if len(bucket) < max_hits:
                    bucket.append(region.base + i)
    return out


def probe(proc, entries: list[dict] | None = None) -> dict:
    """**只读**诊断：每种船型找到几个候选、哪个最可信、为什么不可信。绝不写入。

    用途：你在 Windows 上跑 E 段失败时，把这份 JSON 发我，我就能判断是
    模板没装、内存被归一化、还是多份模板冲突。
    """
    entries = entries if entries is not None else all_entries()
    scanned = scan_all(proc, entries, fresh=True)
    out = []
    for e in entries:
        cands = sorted(scanned.get(e["id"], []), key=lambda x: (-x[1], x[0]))
        good = [c for c in cands if c[1] >= 0.6]
        if not cands:
            reason = "没有命中：模板 Mod 可能没装/没生效"
        elif not good:
            reason = f"命中 {len(cands)} 处但都缺少 Slots 佐证（得分最高 {cands[0][1]:.2f}）"
        elif len(good) > 1 and abs(good[0][1] - good[1][1]) < 1e-9:
            reason = f"命中 {len(good)} 处同样可信的候选，写入会被拒绝（保护机制）"
        else:
            reason = "可写入"
        ambiguous = len(good) > 1 and abs(good[0][1] - good[1][1]) < 1e-9
        out.append({"type": e["type"], "id": e["id"], "source": e.get("source", "starforge"),
                    "label": e["label"], "slots": e["slots"],
                    "factory_seed": hex(e["factory_seed"]),
                    "candidates": [{"addr": hex(a), "score": round(sc, 3)} for a, sc in cands[:8]],
                    "chosen": (hex(good[0][0]) if (good and not ambiguous) else None),
                    "confidence": round(good[0][1], 3) if good and not ambiguous else 0.0,
                    "reason": reason})
    structural = scan_structural(proc, entries)
    for row in out:
        row["structural"] = [hex(a) for a in structural.get(row["id"], [])][:4]
        if not row["chosen"] and row["structural"]:
            row["reason"] += "；但找到结构候选（可能出厂种子已被游戏归一化）"
    return {"ok": True, "platform": "windows" if mem_mod.IS_WINDOWS else "other",
            "types": out, "hint": "本接口只读：不写任何内存；structural 仅用于排障，不参与写入"}


def status() -> dict:
    """给 UI 用：平台是否支持、游戏是否在跑。"""
    info = {"platform": "windows" if mem_mod.IS_WINDOWS else "other",
            "supported": mem_mod.IS_WINDOWS, "running": False, "pid": None}
    if mem_mod.IS_WINDOWS:
        try:
            pid = mem_mod.find_pid("NMS.exe")
            info.update(running=bool(pid), pid=pid)
        except Exception as e:                     # noqa: BLE001
            info["error"] = str(e)
    else:
        info["note"] = "实时通道仅支持 Windows"
    return info
