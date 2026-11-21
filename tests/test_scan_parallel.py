"""并行内存扫描：与串行逐项等价、截断语义、容错与粗粒度性能回归。"""
from __future__ import annotations

import random
import struct
import time

from starforge.live import exml, mem as mem_mod, writer


# ---------------------------------------------------------------- 合成内存工具


def _blank_images(n: int, size: int = 0x1000, base: int = 0x10000000):
    return [(base + i * size, bytearray(size)) for i in range(n)]


def _put_slot(images, region_index: int, off: int, entry: dict) -> int:
    """把一个模板槽的出厂种子 + Slots 佐证写进第 region_index 个区域。"""
    base, buf = images[region_index]
    buf[off:off + 8] = struct.pack("<Q", entry["factory_seed"])
    buf[off + 0x20:off + 0x24] = struct.pack("<I", entry["slots"])
    return base + off


def _scatter_process(n_regions: int = 220):
    """造一个 220+ 区域、含多个模板槽（含重复命中与 SSH 兼容种子）的假进程。"""
    entries = writer.all_entries()
    own = exml.manifest()
    ssh = [e for e in entries if e.get("source") == "super-ship-hunter"]
    images = _blank_images(n_regions)

    # 8 种自己的槽：分散到不同区域，且 sentinel 故意出现 3 次（测排序/去重逻辑）
    for i, e in enumerate(own):
        _put_slot(images, 5 + i * 11, 0x100, e)
    for idx in (150, 200):
        _put_slot(images, idx, 0x180, own[0])
    # SSH 兼容种子：每型也出现两次（兼容分支同样要按地址升序）
    for i, e in enumerate(ssh):
        _put_slot(images, 30 + i * 7, 0x140, e)
        _put_slot(images, 190 + i, 0x120, e)
    # 结构候选（ShipLayout{Slots, Seed=1, Level=1}）
    for i, e in enumerate(own[:2]):
        base, buf = images[90 + i]
        buf[0x300:0x30C] = struct.pack("<III", e["slots"], 1, 1)
    return mem_mod.FakeProcess(images), entries


class _SmallLimitProcess(mem_mod.FakeProcess):
    """regions() 默认就用很小的 max_regions，用来模拟"枚举被截断"。"""

    def __init__(self, images, limit: int):
        super().__init__(images)
        self.limit = int(limit)

    def regions(self, min_size: int = 0x1000,
                max_regions: int = mem_mod.DEFAULT_MAX_REGIONS):
        return super().regions(min_size=min_size, max_regions=self.limit)


class _FlakyProcess(mem_mod.FakeProcess):
    """指定基址的 read 会抛 LiveUnsupported（模拟并发读取时区域消失/权限不足）。"""

    def __init__(self, images, bad_bases):
        super().__init__(images)
        self.bad_bases = {int(b) for b in bad_bases}

    def read(self, addr: int, size: int) -> bytes:
        if addr in self.bad_bases:
            raise mem_mod.LiveUnsupported(f"模拟读取失败 0x{addr:X}")
        return super().read(addr, size)


# ---------------------------------------------------------------- 等价性


def test_parallel_scan_is_identical_to_serial():
    proc, entries = _scatter_process()
    serial = writer.scan_all(proc, entries, fresh=True, workers=1)
    proc2, _ = _scatter_process()
    parallel = writer.scan_all(proc2, entries, fresh=True, workers=8)

    assert parallel == serial                                   # entry_id / (addr, score) / 顺序全一致
    assert sum(len(v) for v in parallel.values()) >= 8
    for hits in parallel.values():
        addrs = [a for a, _sc in hits]
        assert addrs == sorted(addrs), "每个 entry 的候选必须按地址升序"
    # sentinel 有 3 处命中（含两个重复位置），并行也必须全收且有序
    sent_id = next(e["id"] for e in entries if e["type"] == "sentinel"
                   and e.get("source") == "starforge")
    assert len(parallel[sent_id]) == 3
    assert any(sc >= 0.99 for _a, sc in parallel[sent_id])


def test_parallel_structural_scan_is_identical_to_serial():
    proc, entries = _scatter_process()
    serial = writer.scan_structural(proc, entries, workers=1)
    proc2, _ = _scatter_process()
    parallel = writer.scan_structural(proc2, entries, workers=8)
    assert parallel == serial
    # 兼容条目（SSH）的 slots 也是 120，会和 sentinel 的结构签名重叠；
    # 这里只关心"找到的地址集合"与串行一致。
    assert len({a for addrs in parallel.values() for a in addrs}) == 2
    assert all(addrs == sorted(addrs) for addrs in parallel.values())


def test_max_per_entry_truncation_unchanged_by_parallelism():
    """每个 template 最多 max_per_entry 个候选，取地址最小的那些。"""
    entries = exml.manifest()[:1]
    images = _blank_images(40)
    expected = [_put_slot(images, i, 0x100, entries[0]) for i in range(40)]

    serial = writer.scan_all(mem_mod.FakeProcess(images), entries, fresh=True,
                             max_per_entry=7, workers=1)
    parallel = writer.scan_all(mem_mod.FakeProcess(images), entries, fresh=True,
                               max_per_entry=7, workers=8)
    assert parallel == serial
    addrs = [a for a, _sc in parallel[entries[0]["id"]]]
    assert addrs == expected[:7]


def test_scan_info_is_published_with_coverage():
    proc, entries = _scatter_process()
    writer.scan_all(proc, entries, fresh=True, workers=4)
    info = proc._sf_scan_info
    assert set(info) == {"regions", "truncated", "max_regions",
                         "bytes", "seconds", "workers"}
    assert info["regions"] == len(proc.images) == 220
    assert info["bytes"] == 220 * 0x1000
    assert info["truncated"] is False
    assert info["max_regions"] == mem_mod.DEFAULT_MAX_REGIONS
    assert 1 <= info["workers"] <= 4
    assert info["seconds"] >= 0.0
    # 旧缓存语义不能破坏
    assert proc._sf_scan_key and proc._sf_scan
    assert writer.scan_all(proc, entries) is proc._sf_scan


# ---------------------------------------------------------------- 截断提示


def test_probe_reason_mentions_truncation_when_zero_hits():
    images = _blank_images(60)
    proc = _SmallLimitProcess(images, limit=12)                 # 只枚举前 12 个区域
    rep = writer.probe(proc, exml.manifest())
    assert rep["scan"]["truncated"] is True
    assert rep["scan"]["regions"] == 12
    assert rep["scan"]["max_regions"] == 12
    for row in rep["types"]:
        assert row["chosen"] is None
        assert "截断" in row["reason"] and "可能漏扫" in row["reason"]


def test_probe_reason_has_no_truncation_hint_when_complete():
    proc, entries = _scatter_process()
    rep = writer.probe(proc, entries)
    assert rep["scan"]["truncated"] is False
    miss = next(t for t in rep["types"] if t["type"] == "solar")
    assert "截断" not in miss["reason"]


# ---------------------------------------------------------------- 容错


def test_unreadable_region_does_not_abort_scan():
    entries = exml.manifest()
    images = _blank_images(80)
    good = _put_slot(images, 50, 0x100, entries[0])
    ssh = next(e for e in writer.all_entries() if e.get("source") == "super-ship-hunter")
    good_ssh = _put_slot(images, 70, 0x140, ssh)
    bad = [images[i][0] for i in (0, 3, 7, 20, 51, 79)]
    proc = _FlakyProcess(images, bad)

    found = writer.scan_all(proc, writer.all_entries(), fresh=True, workers=8)
    assert good in [a for a, _sc in found[entries[0]["id"]]]
    assert good_ssh in [a for a, _sc in found[ssh["id"]]]
    assert proc._sf_scan_info["regions"] == 80                 # 统计仍覆盖全部区域
    assert proc.writes == []                                  # 只读


# ---------------------------------------------------------------- 粗粒度性能回归


def test_parallel_is_not_dramatically_slower_than_serial():
    """纯 Python 假内存下并行不会提速，但也绝不能慢到 3 倍以上（防线程池用法退化）。"""
    rng = random.Random(20261121)
    n, size = 300, 0x8000
    images = [(0x20000000 + i * size, bytearray(rng.randbytes(size))) for i in range(n)]
    entries = exml.manifest()[:2]
    _put_slot(images, 10, 0x200, entries[0])
    _put_slot(images, 290, 0x200, entries[1])

    proc = mem_mod.FakeProcess(images)
    t0 = time.perf_counter()
    writer.scan_all(proc, entries, fresh=True, workers=1)
    serial = time.perf_counter() - t0

    proc2 = mem_mod.FakeProcess(images)
    t0 = time.perf_counter()
    writer.scan_all(proc2, entries, fresh=True, workers=8)
    parallel = time.perf_counter() - t0

    assert parallel <= serial * 3 + 0.5, (serial, parallel)
