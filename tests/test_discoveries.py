"""已发现星球数据层的合成测试。

全部使用手写 UA / VP / 发现记录，不读取真实存档，也不包含真实名字、种子或坐标。
"""
from __future__ import annotations

import pytest

from starforge import discoveries as disc

# 合成地址：galaxy=0, system=0x100, x=y=z=0，行星位由 helper 填。
SYSTEM_UA = 0x100 << 40


def _ua(*, planet: int = 1, x: int = 0, y: int = 0, z: int = 0,
        system: int = 0x100, galaxy: int = 0) -> int:
    return (x & 0xFFF) | ((z & 0xFFF) << 12) | ((y & 0xFF) << 24) \
        | ((galaxy & 0xFF) << 32) | ((system & 0xFFF) << 40) \
        | ((planet & 0xF) << disc.PLANET_SHIFT)


UA_P1 = _ua(planet=1)
UA_P2 = _ua(planet=2)
UA_P3 = _ua(planet=3)

_MISSING = object()


def _rec(*, ua=_MISSING, vp=("0x1", 0), name=None, ts=None, usn=None,
         dt: str = "Planet") -> dict:
    dd: dict = {"DT": dt}
    if ua is not _MISSING:
        dd["UA"] = ua
    if vp is not None:
        dd["VP"] = list(vp)
    rec: dict = {"DD": dd}
    if name is not None:
        rec["DM"] = {"CN": name}
    if ts is not None or usn is not None:
        rec["OWS"] = {"TS": ts or 0, "USN": usn or ""}
    return rec


def _tree(records: list, available: list | None = None) -> dict:
    return {
        "Version": 4746,
        "DiscoveryManagerData": {
            "DiscoveryData-v1": {
                "Store": {"Record": records},
                "Available": available or [],
            }
        },
    }


# ---------------------------------------------------------------- VP 解码


def test_decode_vp_biome_and_infested():
    lush = disc.decode_vp(["0xabc", 0])
    assert lush["biome_index"] == 0
    assert lush["biome"] == "Lush"
    assert lush["infested"] is False
    assert lush["vp0"] == "0xabc"
    assert lush["ok"] is True

    gas = disc.decode_vp(["0xabc", 0x10000 | 15])
    assert gas["biome"] == "Gas giant"
    assert gas["infested"] is True

    # flags 也可能是十进制字符串
    scorched = disc.decode_vp(["0xabc", "65538"])
    assert scorched["biome_index"] == 2
    assert scorched["biome"] == "Scorched"
    assert scorched["infested"] is True

    assert disc.decode_vp(["0xabc", 7])["biome"] == "Exotic"
    assert disc.decode_vp(["0xabc", 11])["biome"] == "Test"

    unknown = disc.decode_vp(["0xabc", 999])
    assert unknown["biome_index"] == 999
    assert unknown["biome"] is None
    assert unknown["ok"] is True


@pytest.mark.parametrize("vp", [None, [], ["0xabc"], ["0xabc", None], ["0xabc", "0xZZ"], 123])
def test_decode_vp_missing_or_invalid(vp):
    out = disc.decode_vp(vp)
    assert out["biome_index"] is None
    assert out["biome"] is None
    assert out["infested"] is None
    assert out["ok"] is False
    if isinstance(vp, list) and vp[:1] == ["0xabc"]:
        assert out["vp0"] == "0xabc"
    else:
        assert out["vp0"] is None


# ---------------------------------------------------------------- 单条记录


def test_planet_from_record_fields():
    rec = _rec(ua=f"0x{UA_P3:X}", vp=("0x1234", 0x10000 | 4),
               name="Synthetic Planet", ts=1700000000, usn="Synthetic Discoverer")
    row = disc.planet_from_record(rec, system_names={SYSTEM_UA: "Synthetic System"})
    assert row is not None
    assert row["ua"] == f"0x{UA_P3:X}"
    assert row["planet_ua"] == f"0x{UA_P3:X}"
    assert row["system_ua"] == f"0x{SYSTEM_UA:X}"
    assert row["system_key"] == f"0:0x{SYSTEM_UA:X}"
    assert row["planet_index"] == 3
    assert row["galaxy"] == 0
    assert row["biome"] == "Frozen"
    assert row["biome_index"] == 4
    assert row["infested"] is True
    assert row["named"] is True
    assert row["name"] == "Synthetic Planet"
    assert row["discoverer"] == "Synthetic Discoverer"
    assert row["discovered_at"] == 1700000000
    assert row["system_name"] == "Synthetic System"
    assert row["glyphs"] == "310000000000"
    assert row["coords"] == "07FF:007F:07FF:0100"
    assert row["vp0"] == "0x1234"
    assert row["vp"] == ["0x1234", 0x10004]
    assert row["source"] == "save"
    assert row["pending"] is False


def test_planet_from_record_missing_fields_are_none():
    row = disc.planet_from_record({"DD": {"DT": "Planet"}})
    assert row is not None
    for key in ("ua", "planet_ua", "system_ua", "system_key", "planet_index",
                "galaxy", "biome", "biome_index", "infested", "name",
                "discoverer", "discovered_at", "system_name", "glyphs",
                "coords", "vp0", "vp"):
        assert row[key] is None, key
    assert row["named"] is False

    short_vp = disc.planet_from_record({"DD": {"DT": "Planet", "UA": UA_P1,
                                               "VP": ["0x1"]}})
    assert short_vp is not None
    assert short_vp["vp0"] == "0x1"
    assert short_vp["biome"] is None
    assert short_vp["infested"] is None

    assert disc.planet_from_record({"DD": {"DT": "Animal"}}) is None
    assert disc.planet_from_record({}) is None
    assert disc.planet_from_record(None) is None


@pytest.mark.parametrize("raw", [None, "", 0, -1, "0xZZ", "bad", True, 2 ** 64])
def test_planet_from_record_invalid_ua_keeps_other_fields(raw):
    rec = {"DD": {"DT": "Planet", "UA": raw, "VP": ["0x1", 0]}}
    row = disc.planet_from_record(rec)
    assert row is not None
    assert row["ua"] is None
    assert row["planet_ua"] is None
    assert row["system_ua"] is None
    assert row["planet_index"] is None
    assert row["galaxy"] is None
    assert row["biome"] == "Lush"          # VP 仍然可解，不因 UA 坏掉而丢
    assert row["glyphs"] is None
    assert row["coords"] is None


def test_ua_fallback_from_system_and_planet_index():
    # 记录没有 UA，但有系统地址和行星序号：可以推导出行星地址。
    rec = {
        "DD": {"DT": "Planet", "VP": ["0x1", 0]},
        "system_ua": f"0x{SYSTEM_UA:X}",
        "planet_index": 4,
    }
    row = disc.planet_from_record(rec)
    assert row is not None
    assert row["ua"] == f"0x{_ua(planet=4):X}"
    assert row["planet_index"] == 4
    assert row["system_ua"] == f"0x{SYSTEM_UA:X}"

    # UA 只有系统地址（行星位为 0），行星序号另存：补上行星位。
    rec2 = {"DD": {"DT": "Planet", "UA": f"0x{SYSTEM_UA:X}", "VP": ["0x1", 0]},
            "planet_index": 2}
    row2 = disc.planet_from_record(rec2)
    assert row2 is not None
    assert row2["ua"] == f"0x{_ua(planet=2):X}"
    assert row2["planet_index"] == 2

    # 只有系统地址、没有行星序号：保留系统信息，但不编造行星位。
    rec3 = {"DD": {"DT": "Planet", "UA": f"0x{SYSTEM_UA:X}", "VP": ["0x1", 0]}}
    row3 = disc.planet_from_record(rec3)
    assert row3 is not None
    assert row3["ua"] == f"0x{SYSTEM_UA:X}"
    assert row3["planet_index"] == 0
    assert row3["glyphs"] is None


# ---------------------------------------------------------------- 存档树


def test_planets_from_tree_merges_duplicates_and_sources():
    system_rec = {
        "DD": {"DT": "SolarSystem", "UA": f"0x{SYSTEM_UA:X}", "VP": ["0x1"]},
        "DM": {"CN": "Synthetic System"},
        "OWS": {"USN": "System Discoverer"},
    }
    store = [
        _rec(ua=UA_P1, vp=("0x1", 0), name="Synthetic Alpha", ts=100, usn="Tester"),
        _rec(ua=UA_P2, vp=("0x1", 4), ts=200),
        _rec(ua=UA_P3, vp=("0x1", 0), name="Synthetic Gamma", ts=300),
        system_rec,
        _rec(ua="0xZZ", vp=("0x1", 0)),
        _rec(ua=UA_P1, vp=("0x1", 0), dt="Animal"),
    ]
    available = [
        _rec(ua=UA_P1, vp=("0x1", 0), ts=400),          # Store 的重复记录
        _rec(ua=_ua(planet=4), vp=("0x1", 1), ts=500),  # 新的待上传记录
    ]
    parsed = disc.planets_from_tree(_tree(store, available))
    assert parsed["found"] is True
    assert parsed["records"] == 6                    # 4 条 Store Planet + 2 条 Available Planet
    assert parsed["duplicates"] == 1
    assert len(parsed["planets"]) == 5
    assert any("重复" in text for text in parsed["warnings"])
    assert any("没有可用地址" in text for text in parsed["warnings"])

    by_index = {}
    for row in parsed["planets"]:
        by_index.setdefault(row["planet_index"], []).append(row)

    alpha = by_index[1][0]
    assert alpha["source"] == "save"
    assert alpha["pending"] is False
    assert alpha["discovered_at"] == 100             # Store 优先于 Available
    assert alpha["name"] == "Synthetic Alpha"
    assert alpha["system_name"] == "Synthetic System"

    # 行星自己没有发现者时，回退到同系统 SolarSystem 的 OWS.USN。
    assert by_index[2][0]["discoverer"] == "System Discoverer"

    pending = by_index[4][0]
    assert pending["source"] == "save-pending"
    assert pending["pending"] is True
    assert pending["discovered_at"] == 500
    assert pending["biome"] == "Toxic"

    invalid = next(row for row in parsed["planets"] if row["ua"] is None)
    assert invalid["biome"] == "Lush"                # 地址坏了，VP 仍然保留


def test_planets_from_tree_duplicate_within_store_prefers_newer_ts():
    first = _rec(ua=UA_P1, vp=("0x1", 0), name="Synthetic Old", ts=100)
    second = _rec(ua=UA_P1, vp=("0x1", 0), name="Synthetic New", ts=200)
    parsed = disc.planets_from_tree(_tree([first, second]))
    assert parsed["records"] == 2
    assert parsed["duplicates"] == 1
    assert len(parsed["planets"]) == 1
    row = parsed["planets"][0]
    assert row["discovered_at"] == 200
    assert row["name"] == "Synthetic New"


def test_planets_from_tree_empty_and_missing_container():
    empty = disc.planets_from_tree(_tree([]))
    assert empty["found"] is True
    assert empty["planets"] == []
    assert empty["records"] == 0
    assert empty["warnings"] == []

    missing = disc.planets_from_tree({})
    assert missing["found"] is False
    assert missing["planets"] == []
    assert missing["warnings"]

    bad_rows = disc.planets_from_tree({
        "DiscoveryManagerData": {"DiscoveryData-v1": {"Store": {"Record": "bad"}}}
    })
    assert bad_rows["found"] is True
    assert bad_rows["records"] == 0
    assert any("不是数组" in text for text in bad_rows["warnings"])


def test_discovered_planets_contract(monkeypatch, tmp_path):
    tree = _tree([
        _rec(ua=UA_P1, vp=("0x1", 0), name="Synthetic Alpha", ts=100),
        _rec(ua=UA_P2, vp=("0x1", 4), ts=200),
    ])
    monkeypatch.setattr(disc, "_open_tree", lambda path=None: (tmp_path / "save.hg", tree))
    res = disc.discovered_planets()
    assert res["ok"] is True
    assert res["count"] == 2
    assert res["records"] == 2
    assert res["version"] == 4746
    assert res["path"].endswith("save.hg")
    assert {"ok", "count", "planets", "warnings"} <= set(res)
    assert res["stats"]["named"] == 1
    assert res["stats"]["infested"] == 0


def test_discovered_planets_read_error_is_reported(monkeypatch):
    def boom(path=None):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(disc, "_open_tree", boom)
    res = disc.discovered_planets("synthetic.hg")
    assert res["ok"] is False
    assert res["count"] == 0
    assert res["planets"] == []
    assert "读取存档失败" in res["warnings"][0]


# ---------------------------------------------------------------- 距离 / 过滤


def test_distance_ly_rules():
    assert disc.distance_ly(UA_P1, UA_P3) == 0.0
    assert disc.distance_ly(UA_P1, _ua(planet=1, system=0x101)) == \
        pytest.approx(disc.VOXEL_UNCERTAINTY)
    assert disc.distance_ly(UA_P1, _ua(planet=1, x=3, z=4)) == pytest.approx(2000.0)
    assert disc.distance_ly(UA_P1, _ua(planet=1, galaxy=1)) is None
    for bad in (None, "", 0, -1, "not-a-ua"):
        assert disc.distance_ly(bad, UA_P1) is None


def _rows() -> list[dict]:
    return [
        disc.planet_from_record(_rec(ua=UA_P1, vp=("0x1", 0x10000),
                                     name="Synthetic Alpha", ts=100)),
        disc.planet_from_record(_rec(ua=UA_P2, vp=("0x1", 4), ts=300)),
        disc.planet_from_record(_rec(ua=_ua(planet=3, system=0x101), vp=("0x1", 0),
                                     name="Synthetic Gamma", ts=200)),
        disc.planet_from_record(_rec(ua=_ua(planet=4, x=3, z=4), vp=("0x1", 13))),
        disc.planet_from_record(_rec(ua=_ua(planet=5), vp=("0x1", 7), ts=150)),
    ]


def test_filter_biome_infested_named():
    rows = _rows()
    def indexes(**kw):
        return {r["planet_index"] for r in disc.filter_discovered(rows, **kw)}

    assert indexes(biome="Lush") == {1, 3}
    assert indexes(biome="Weird") == {5}
    assert indexes(biome=4) == {2}
    assert indexes(biome="Volcanic") == {4}
    assert indexes(biome="火山") == {4}
    assert indexes(biome="Unknown") == set()

    assert indexes(infested=True) == {1}
    assert indexes(infested=False) == {2, 3, 4, 5}
    assert indexes(named=True) == {1, 3}
    assert indexes(named=False) == {2, 4, 5}

    # 缺 VP 时 infested 是 None：不能被当成 False 混进结果。
    no_vp = disc.planet_from_record({"DD": {"DT": "Planet", "UA": UA_P1}})
    assert no_vp is not None
    assert disc.filter_discovered([no_vp], infested=False) == []


def test_filter_unset_sentinels_are_not_real_filters():
    """现有 UI 的下拉框会用 "" 表示「全部」；不能当成真的筛选值。"""
    rows = _rows()
    assert len(disc.filter_discovered(rows, biome="")) == len(rows)
    assert len(disc.filter_discovered(rows, biome="全部")) == len(rows)
    assert len(disc.filter_discovered(rows, infested="", named="")) == len(rows)
    assert len(disc.filter_discovered(rows, infested="不限")) == len(rows)
    assert len(disc.filter_discovered(rows, near_ua="")) == len(rows)
    assert len(disc.filter_discovered(rows, max_distance="")) == len(rows)


def test_filter_distance_sort_and_limit():
    rows = _rows()
    by_distance = disc.filter_discovered(rows, near_ua=SYSTEM_UA, sort="distance")
    assert [r["planet_index"] for r in by_distance] == [1, 2, 5, 3, 4]
    assert by_distance[0]["distance_ly"] == 0.0
    assert by_distance[-1]["distance_ly"] == pytest.approx(2000.0)

    assert [r["planet_index"] for r in disc.filter_discovered(
        rows, near_ua=SYSTEM_UA, max_distance=0)] == [1, 2, 5]
    assert [r["planet_index"] for r in disc.filter_discovered(
        rows, near_ua=SYSTEM_UA, max_distance=300)] == [1, 2, 5, 3]

    by_biome = disc.filter_discovered(rows, sort="biome")
    assert [r["biome"] for r in by_biome] == ["Exotic", "Frozen", "Lava", "Lush", "Lush"]

    by_time = disc.filter_discovered(rows, sort="discovered")
    assert [r["planet_index"] for r in by_time] == [2, 3, 5, 1, 4]

    assert [r["planet_index"] for r in disc.filter_discovered(rows, sort="order")] == [1, 2, 3, 4, 5]
    assert [r["planet_index"] for r in disc.filter_discovered(rows, limit=2)] == [2, 3]

    # 输入行不应被 filter 写入 distance_ly。
    assert all("distance_ly" not in row for row in rows)


def test_filter_errors_and_limit_cap():
    rows = _rows()
    with pytest.raises(ValueError):
        disc.filter_discovered(rows, sort="distance")
    with pytest.raises(ValueError):
        disc.filter_discovered(rows, max_distance=10)
    with pytest.raises(ValueError):
        disc.filter_discovered(rows, near_ua="not-a-ua")
    with pytest.raises(ValueError):
        disc.filter_discovered(rows, limit="many")

    many = [{"biome": "Lush", "biome_index": 0, "named": False,
             "infested": False, "discovered_at": 1} for _ in range(600)]
    assert len(disc.filter_discovered(many, limit=9999)) == disc.MAX_LIMIT == 500
    assert disc.filter_discovered(many, limit=0) == []
    assert len(disc.filter_discovered(many, limit=None)) == 600


# ---------------------------------------------------------------- 服务封装


def test_services_discoveries_wrappers(monkeypatch, tmp_path):
    from starforge.core.errors import BadRequest
    from starforge.services import Services

    tree = _tree([
        _rec(ua=UA_P1, vp=("0x1", 0), name="Synthetic Alpha", ts=100),
        _rec(ua=UA_P2, vp=("0x1", 4), ts=200),
    ])
    monkeypatch.setattr(disc, "_open_tree", lambda path=None: (tmp_path / "save.hg", tree))
    svc = Services()

    res = svc.discovered_planets()
    assert res["ok"] is True
    assert res["count"] == 2

    filtered = svc.discovered_filter(biome="Lush")
    assert filtered["ok"] is True
    assert filtered["count"] == 1
    assert filtered["planets"][0]["planet_index"] == 1

    with pytest.raises(BadRequest):
        svc.discovered_filter(planets=res["planets"], max_distance=10)
