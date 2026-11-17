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
from . import exml, mem as mem_mod

log = log.get("live.writer")

WINDOW = 0x60          # 候选附近检查范围
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


def locate(proc, type_: str, entries: list[dict] | None = None, fresh: bool = False) -> Slot:
    """在进程内存里找到 type_ 对应模板槽的种子地址（优先用缓存）。"""
    entries = entries or exml.manifest()
    entry = next((e for e in entries if e["type"] == type_), None)
    if entry is None:
        raise LocateError(f"模板清单里没有船型 {type_}")

    cache = _cache(proc)
    if not fresh and type_ in cache and _still_valid(proc, cache[type_], entry):
        return cache[type_]

    pat = struct.pack("<Q", entry["factory_seed"])
    candidates: list[int] = []
    for region in proc.regions(min_size=MIN_REGION):
        try:
            buf = proc.read(region.base, region.size)
        except mem_mod.LiveUnsupported:
            continue
        start = 0
        while True:
            i = buf.find(pat, start)
            if i < 0:
                break
            candidates.append(region.base + i)
            start = i + 1
            if len(candidates) > 32:
                break
        if len(candidates) > 32:
            break

    scored = [(addr, _score(proc, addr, entry)) for addr in candidates]
    scored = [(a, s) for a, s in scored if s >= 0.6]          # 至少要有 Slots 佐证
    if not scored:
        raise LocateError(
            f"没找到 {type_} 的模板槽。可能原因：① 没装 starforge-templates 数据 Mod；"
            "② 游戏版本变了导致布局不同；③ 还没进过存档。")
    scored.sort(key=lambda x: (-x[1], x[0]))
    if len(scored) > 1 and abs(scored[0][1] - scored[1][1]) < 1e-9:
        raise LocateError(f"{type_} 的模板槽命中多个同样可信的候选（{len(scored)} 个），拒绝写入")
    addr, score = scored[0]
    log.info("定位 %s 模板槽：0x%X（score %.2f）", type_, addr, score)
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
