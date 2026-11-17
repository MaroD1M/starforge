"""Live 模块里可离线验证的两块：AOB 扫描引擎 + 模板 Mod 生成器。"""
import os
import xml.etree.ElementTree as ET

import pytest

from starforge.live import exml, scan


# ---------------------------------------------------------------- AOB 扫描


def test_pattern_anchor_is_longest_run():
    p = scan.Pattern("00 ?? 01 02 03 04 ?? 05")
    assert p.anchor == bytes([1, 2, 3, 4]) and p.anchor_off == 2
    assert p.length == 8


def test_find_all_with_wildcards():
    buf = b"\x00" + bytes([0x01, 0x99, 0x02, 0x03]) + b"\x00" + bytes([0x01, 0xAA, 0x02, 0x03])
    pat = scan.Pattern("01 ?? 02 03")
    hits = scan.find_all(buf, pat)
    assert hits == [1, 6]


def test_find_all_respects_limit():
    buf = bytes([0x7E, 0x01] * 200)
    pat = scan.Pattern("7E 01")
    assert len(scan.find_all(buf, pat, limit=5)) == 5


def test_pick_best_requires_min_score():
    cands = [10, 20, 30]
    best, scored = scan.pick_best(cands, lambda a: {10: 0.2, 20: 0.9, 30: 0.4}[a])
    assert best == 20 and scored[0][0] == 20
    best2, _ = scan.pick_best(cands, lambda a: 0.1)
    assert best2 is None                      # 全不可信就别写


def test_pattern_rejects_empty():
    with pytest.raises(ValueError):
        scan.Pattern("?? ??")
    with pytest.raises(ValueError):
        scan.Pattern("")


def test_regex_fallback_matches():
    pat = scan.Pattern("?? ?? 0A")
    rx = scan.regex_for(pat)
    assert rx.search(b"\x00\x00\x0A") and not rx.search(b"\x00\x00\x0B")


def test_scan_plan_add():
    plan = scan.ScanPlan()
    p = plan.add("01 00", "t", offset=-8)
    assert plan.patterns == [p] and p.offset == -8


# ---------------------------------------------------------------- 模板 Mod


def test_manifest_has_eight_types():
    m = exml.manifest()
    assert len(m) == 8
    assert {x["type"] for x in m} == {"sentinel", "fighter", "hauler", "explorer",
                                      "shuttle", "exotic", "living", "solar"}
    # 关键：Slots 必须互不相同（否则 8 条签名会塌成一条 —— 上一轮审计的 P0-2）
    assert len({x["slots"] for x in m}) == 8
    assert len({x["factory_seed"] for x in m}) == 8


def test_factory_seed_is_ascii_tagged_and_fits_u64():
    b = exml.factory_seed(0).to_bytes(8, "little")
    assert b[:7] == b"STARFOR" and b[7] == 0xA0
    assert exml.factory_seed(7).to_bytes(8, "little")[7] == 0xA7
    assert len({exml.factory_seed(i) for i in range(8)}) == 8
    assert exml.factory_seed(0) < 2 ** 64                     # 必须能放进 int64/uint64 字段


def test_generated_xml_is_valid_and_has_all_slots():
    root = ET.fromstring(exml.rewardtable_xml())
    assert root.tag == "Data" and root.get("template") == "GcRewardTable"
    entries = [e for e in root.iter("Property") if e.get("value") == "GcGenericRewardTableEntry"]
    assert len(entries) == 8
    seeds = [int(p.get("value")) for p in root.iter("Property") if p.get("name") == "Seed"]
    assert exml.factory_seed(0) in seeds
    slots = [int(p.get("value")) for p in root.iter("Property") if p.get("name") == "Slots"]
    assert sorted(slots) == [120, 121, 122, 123, 124, 125, 126, 127]


def test_write_mod_creates_files(tmp_path):
    out = exml.write_mod(str(tmp_path))
    assert os.path.isdir(out["path"])
    rt = os.path.join(out["path"], "METADATA", "REALITY", "TABLES", "REWARDTABLE.EXML")
    assert os.path.exists(rt) and os.path.getsize(rt) > 1000
    assert b"GcRewardSpecificShip" in open(rt, "rb").read()
    assert len(out["entries"]) == 8


# ---------------------------------------------------------------- 定位与写入（合成内存）

from starforge.live import mem as mem_mod, writer           # noqa: E402


def _image(entries, base=0x10000000, size=0x8000):
    """造一块合成内存：把每个槽的出厂种子与 Slots 值放进去。"""
    buf = bytearray(size)
    import struct
    for i, e in enumerate(entries):
        off = 0x1000 + i * 0x200
        buf[off:off + 8] = struct.pack("<Q", e["factory_seed"])
        buf[off + 0x20:off + 0x24] = struct.pack("<I", e["slots"])
    return [(base, buf)], base


def test_locate_finds_slot_and_scores():
    entries = exml.manifest()
    images, base = _image(entries[:2])
    proc = mem_mod.FakeProcess(images)
    slot = writer.locate(proc, "sentinel", entries)
    assert slot.seed_addr == base + 0x1000
    assert slot.score >= 0.99 and slot.verified_slots


def test_locate_picks_the_right_type():
    entries = exml.manifest()
    images, base = _image(entries[:4])
    proc = mem_mod.FakeProcess(images)
    assert writer.locate(proc, "sentinel", entries).seed_addr == base + 0x1000
    assert writer.locate(proc, "fighter", entries).seed_addr == base + 0x1200


def test_locate_refuses_without_structural_evidence():
    """只有出厂种子、没有 Slots 佐证 → 不可信，必须拒绝。"""
    import struct
    entries = exml.manifest()
    buf = bytearray(0x4000)
    buf[0x1000:0x1008] = struct.pack("<Q", entries[0]["factory_seed"])   # 只放种子
    proc = mem_mod.FakeProcess([(0x10000000, buf)])
    with pytest.raises(writer.LocateError) as e:
        writer.locate(proc, "sentinel", entries)
    assert "模板槽" in str(e.value)


def test_locate_refuses_when_ambiguous():
    import struct
    entries = exml.manifest()
    buf = bytearray(0x8000)
    for off in (0x1000, 0x2000):                                        # 两处一模一样
        buf[off:off + 8] = struct.pack("<Q", entries[0]["factory_seed"])
        buf[off + 0x20:off + 0x24] = struct.pack("<I", entries[0]["slots"])
    proc = mem_mod.FakeProcess([(0x10000000, buf)])
    with pytest.raises(writer.LocateError) as e:
        writer.locate(proc, "sentinel", entries)
    assert "多个" in str(e.value)


def test_locate_empty_memory_gives_actionable_message():
    proc = mem_mod.FakeProcess([(0x10000000, bytearray(0x4000))])
    with pytest.raises(writer.LocateError) as e:
        writer.locate(proc, "sentinel")
    assert "templates" in str(e.value)                                  # 指向"没装模板 Mod"


def test_push_writes_and_verifies():
    entries = exml.manifest()
    images, base = _image(entries[:1])
    proc = mem_mod.FakeProcess(images)
    res = writer.push(proc, "sentinel", "0x1111222233334444", entries)
    assert res["ok"] and res["after"] == 0x1111222233334444
    assert proc.read_u64(base + 0x1000) == 0x1111222233334444
    assert len(proc.writes) == 1 and len(proc.writes[0][1]) == 8        # 只写 8 字节


def test_push_is_idempotent():
    entries = exml.manifest()
    images, base = _image(entries[:1])
    proc = mem_mod.FakeProcess(images)
    writer.push(proc, "sentinel", "0xABC", entries)
    res = writer.push(proc, "sentinel", "0xABC", entries)
    assert res.get("unchanged") is True and len(proc.writes) == 1


def test_push_detects_failed_readback(monkeypatch):
    entries = exml.manifest()
    images, base = _image(entries[:1])
    proc = mem_mod.FakeProcess(images)
    real_write = proc.write_u64
    monkeypatch.setattr(proc, "write_u64", lambda a, v: (real_write(a, v ^ 0xFF), True)[1])
    with pytest.raises(writer.LocateError) as e:
        writer.push(proc, "sentinel", "0x1234", entries)
    assert "回读校验失败" in str(e.value)


def test_status_on_this_platform():
    st = writer.status()
    assert st["platform"] in ("windows", "other")
    assert st["supported"] == (st["platform"] == "windows")


# ---------------------------------------------------------------- Web 契约

def test_live_status_api(client):
    j = client.get("/api/live/status").get_json()
    assert j["ok"] and "supported" in j


def test_live_push_needs_write_enabled(client):
    r = client.post("/api/live/push", json={"type": "sentinel", "seed": "0x1", "confirm": True})
    assert r.status_code == 403 and r.get_json()["error"]["kind"] == "write_disabled"


def test_live_push_needs_confirm(client):
    from starforge.core import settings as settings_mod
    settings_mod.update(write_enabled=True)
    r = client.post("/api/live/push", json={"type": "sentinel", "seed": "0x1"})
    assert r.status_code == 400


def test_live_push_unsupported_platform(client):
    from starforge.core import settings as settings_mod
    from starforge.live import mem as mem_mod
    settings_mod.update(write_enabled=True)
    if mem_mod.IS_WINDOWS:
        pytest.skip("本机是 Windows")
    r = client.post("/api/live/push", json={"type": "sentinel", "seed": "0x1", "confirm": True})
    assert r.status_code == 503


def test_template_mod_endpoint(client, tmp_path):
    r = client.post("/api/live/template-mod", json={"dest": str(tmp_path)})
    j = r.get_json()
    assert j["ok"] and j["entries"] and len(j["entries"]) == 8


# ---------------------------------------------------------------- 符文置顶窗口（不依赖图形环境）

def test_overlay_panel_spec():
    from starforge import overlay
    spec = overlay.panel_spec("1043FEE69929", tile=64, gap=8)
    assert len(spec["digits"]) == 12
    assert spec["width"] == 12 * 64 + 11 * 8 + 24
    assert spec["height"] == 64 + 56


def test_overlay_rejects_empty():
    from starforge import overlay
    with pytest.raises(ValueError):
        overlay.panel_spec("   ")


def test_overlay_without_display_degrades_cleanly():
    from starforge import glyphs, overlay
    png = glyphs.panel_png("1043FEE69929", tile=32)
    try:
        overlay.show("1043FEE69929", png)
    except overlay.OverlayUnsupported as e:
        assert "tkinter" in str(e) or "图形" in str(e)
    else:                                    # 有显示环境时不该抛错（测试机上一般走不到）
        pytest.skip("当前环境有可用显示")
