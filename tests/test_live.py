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


def test_factory_seed_is_ascii_tagged():
    assert exml.factory_seed(0).to_bytes(9, "little") == b"STARFORGE"
    assert exml.factory_seed(3) - exml.factory_seed(0) == 3


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
