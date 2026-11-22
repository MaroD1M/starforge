"""发现索引（discoveries.db）与行星动物联查的合成测试。

不读取真实存档：存档文件只是几字节占位，发现记录由手写 JSON 树生成。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from starforge import address
from starforge import discoveries as disc
from starforge import discoveries_index as di

SYSTEM_UA = 0x100 << 40


def _sys_ua(system: int = 0x100, galaxy: int = 0) -> int:
    return (galaxy & 0xFF) << 32 | (system & 0xFFF) << 40


def _ua(*, planet: int = 1, system: int = 0x100, galaxy: int = 0,
        x: int = 0, y: int = 0, z: int = 0) -> int:
    return address.ua_from_parts(galaxy, system, x, y, z, planet) or 0


def _planet(planet: int = 1, *, vp=(0, 0), name: str | None = None,
            system: int = 0x100, galaxy: int = 0,
            x: int = 0, y: int = 0, z: int = 0, ua=None, ts=None) -> dict:
    dd: dict = {"DT": "Planet",
                "UA": ua if ua is not None else f"0x{_ua(planet=planet, system=system, galaxy=galaxy, x=x, y=y, z=z):X}",
                "VP": list(vp)}
    rec: dict = {"DD": dd}
    if name is not None:
        rec["DM"] = {"CN": name}
    if ts is not None:
        rec["OWS"] = {"TS": ts}
    return rec


def _animal(planet: int = 1, *, seeds=(1, 2, 3, 4, 5), name: str | None = None,
            system: int = 0x100, ua=None, ts=None) -> dict:
    dd: dict = {"DT": "Animal",
                "UA": ua if ua is not None else f"0x{_ua(planet=planet, system=system):X}",
                "VP": list(seeds)}
    rec: dict = {"DD": dd}
    if name is not None:
        rec["DM"] = {"CN": name}
    if ts is not None:
        rec["OWS"] = {"TS": ts}
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


def _rows(tree: dict) -> list[dict]:
    parsed = disc.planets_from_tree(tree)
    assert parsed["found"] is True
    return parsed["planets"]


def _fake_discovered(monkeypatch, save_path, planets, calls=None):
    def fake(path=None):
        if calls is not None:
            calls.append(path)
        return {"ok": True, "path": str(save_path), "count": len(planets),
                "planets": planets, "records": len(planets), "duplicates": 0,
                "warnings": []}
    monkeypatch.setattr(disc, "discovered_planets", fake)


# ---------------------------------------------------------------- 建库/复用/重建


def test_index_build_reuse_rebuild_paths(tmp_path, monkeypatch):
    records = [
        _planet(1, vp=(0x11, 0), name="Synthetic Alpha", ts=100),
        _planet(2, vp=(0x22, 4), ts=200),
        _planet(3, vp=(0x33, 0x10000 | 15), name="Synthetic Gamma", ts=300),
        {"DD": {"DT": "Planet", "UA": "0xZZ", "VP": [0, 0]}},   # 坏 UA → 跳过
    ]
    planets = _rows(_tree(records))
    save = tmp_path / "save.hg"
    save.write_bytes(b"synthetic save v1")
    db = tmp_path / "discoveries.db"
    calls: list = []
    _fake_discovered(monkeypatch, save, planets, calls)

    first = di.index_save(str(save), db_file=str(db))
    assert first["ok"] is True
    assert first["rebuilt"] is True and first["cached"] is False
    assert first["count"] == 3
    assert first["skipped"] == 1
    assert len(calls) == 1

    # 路径：size+mtime 不变 → 完全不解析、不读文件。
    second = di.index_save(str(save), db_file=str(db))
    assert second["cached"] is True and second["rebuilt"] is False
    assert second["count"] == 3 and second["reason"] == "size+mtime"
    assert len(calls) == 1

    # 路径：内容不变但 mtime 变化 → 走 sha256，仍然复用。
    st = save.stat()
    import os
    os.utime(save, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    third = di.index_save(str(save), db_file=str(db))
    assert third["cached"] is True and third["rebuilt"] is False
    assert third["reason"] == "sha256"
    assert len(calls) == 1

    # 路径：内容变化 → 重新解析并替换。
    save.write_bytes(b"synthetic save v2 with extra bytes")
    _fake_discovered(monkeypatch, save,
                     planets + _rows(_tree([_planet(4, vp=(0x44, 2), ts=400)])),
                     calls)
    fourth = di.index_save(str(save), db_file=str(db))
    assert fourth["rebuilt"] is True and fourth["cached"] is False
    assert fourth["count"] == 4
    assert len(calls) == 2

    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT path, size, mtime_ns, sha256, extractor_ver "
                           "FROM saves").fetchone()
        assert row[0] == str(save)
        assert row[1] == save.stat().st_size
        assert row[3] and len(row[3]) == 64
        assert row[4] == di.EXTRACTOR_VER
        assert conn.execute("SELECT COUNT(*) FROM planets").fetchone()[0] == 4
    finally:
        conn.close()


def test_index_extractor_version_forces_rebuild(tmp_path, monkeypatch):
    planets = _rows(_tree([_planet(1, vp=(0, 0))]))
    save = tmp_path / "save.hg"
    save.write_bytes(b"same bytes")
    db = tmp_path / "discoveries.db"
    calls: list = []
    _fake_discovered(monkeypatch, save, planets, calls)

    assert di.index_save(str(save), db_file=str(db))["rebuilt"] is True
    monkeypatch.setattr(di, "EXTRACTOR_VER", di.EXTRACTOR_VER + 1)
    again = di.index_save(str(save), db_file=str(db))
    assert again["rebuilt"] is True and again["cached"] is False
    assert len(calls) == 2
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT extractor_ver FROM saves").fetchone()[0] == \
            di.EXTRACTOR_VER
    finally:
        conn.close()


def test_index_wal_busy_timeout_and_single_transaction(tmp_path, monkeypatch):
    planets = _rows(_tree([_planet(1, vp=(0, 0))]))
    save = tmp_path / "save.hg"
    save.write_bytes(b"x")
    db = tmp_path / "discoveries.db"
    _fake_discovered(monkeypatch, save, planets)
    di.index_save(str(save), db_file=str(db))

    conn = sqlite3.connect(db)
    try:
        assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("SELECT COUNT(*) FROM planets").fetchone()[0] == 1
    finally:
        conn.close()


def test_index_missing_or_unreadable_save_is_reported(tmp_path, monkeypatch):
    missing = di.index_save(str(tmp_path / "nope.hg"),
                            db_file=str(tmp_path / "d.db"))
    assert missing["ok"] is False
    assert missing["count"] == 0 and missing["rebuilt"] is False

    save = tmp_path / "save.hg"
    save.write_bytes(b"x")
    monkeypatch.setattr(disc, "discovered_planets", lambda path=None: {
        "ok": False, "warnings": ["synthetic read failure"], "planets": [],
    })
    failed = di.index_save(str(save), db_file=str(tmp_path / "d.db"))
    assert failed["ok"] is False
    assert "synthetic read failure" in failed["error"]


def test_index_skips_bad_rows_and_counts_them(tmp_path, monkeypatch):
    planets = [
        disc.planet_from_record(_planet(1, vp=(0, 0))),
        {"system_ua": "0xZZ", "planet_index": 2},          # 系统地址坏
        {"system_ua": f"0x{SYSTEM_UA:X}", "planet_index": 99},  # 行星序号越界
        {"system_ua": f"0x{SYSTEM_UA:X}"},                 # 缺行星序号
        "not-a-dict",
    ]
    save = tmp_path / "save.hg"
    save.write_bytes(b"x")
    _fake_discovered(monkeypatch, save, planets)
    res = di.index_save(str(save), db_file=str(tmp_path / "d.db"))
    assert res["ok"] is True
    assert res["count"] == 1
    assert res["skipped"] == 4


# ---------------------------------------------------------------- 查询/统计


def _query_planets() -> list[dict]:
    tree = _tree([
        _planet(1, vp=(0, 0x10000), name="Synthetic Alpha", ts=100),
        _planet(2, vp=(0, 4), ts=300),
        _planet(3, vp=(0, 0), name="Synthetic Gamma",
                system=0x101, ts=200),
        _planet(4, vp=(0, 13), x=3, z=4, ts=None),
        _planet(5, vp=(0, 7), ts=150),
        {"DD": {"DT": "SolarSystem", "UA": f"0x{SYSTEM_UA:X}", "VP": [0]},
         "DM": {"CN": "Synthetic System"}},
    ])
    return _rows(tree)


def test_query_matches_filter_discovered(tmp_path, monkeypatch):
    planets = _query_planets()
    save = tmp_path / "save.hg"
    save.write_bytes(b"x")
    db = str(tmp_path / "d.db")
    _fake_discovered(monkeypatch, save, planets)
    assert di.index_save(str(save), db_file=db)["count"] == 5

    for filters in (
        {"biome": "Lush"},
        {"biome": "Weird"},
        {"biome": 4},
        {"infested": True},
        {"infested": False},
        {"named": True},
        {"named": False},
        {"biome": "Lush", "infested": True, "named": True},
        {"biome": ""},
    ):
        got = di.query(order="biome", db_file=db, **filters)
        want = disc.filter_discovered(planets, sort="biome", **filters)
        assert {(r["system_ua"], r["planet_index"], r["planet_ua"]) for r in got} == \
            {(r["system_ua"], r["planet_index"], r["planet_ua"]) for r in want}

    got = di.query(near_ua=SYSTEM_UA, order="distance", db_file=db)
    want = disc.filter_discovered(planets, near_ua=SYSTEM_UA, sort="distance")
    assert [r["planet_index"] for r in got] == [r["planet_index"] for r in want]
    assert all(r["distance_ly"] is not None for r in got)

    # 不提供 near_ua 时按到银河中心的距离排序，距离单调不减。
    center = di.query(order="distance", db_file=db)
    distances = [r["distance_ly"] for r in center]
    assert distances == sorted(distances)

    assert di.query(limit=2, db_file=db, order="biome") is not None
    assert len(di.query(limit=2, db_file=db, order="biome")) == 2
    with pytest.raises(ValueError):
        di.query(order="unknown", db_file=db)
    with pytest.raises(ValueError):
        di.query(near_ua="not-a-ua", db_file=db)


def test_query_fields_and_system_name(tmp_path, monkeypatch):
    planets = _query_planets()
    save = tmp_path / "save.hg"
    save.write_bytes(b"x")
    db = str(tmp_path / "d.db")
    _fake_discovered(monkeypatch, save, planets)
    di.index_save(str(save), db_file=db)

    rows = di.query(order="order", db_file=db)
    alpha = next(r for r in rows if r["planet_index"] == 1)
    assert alpha["system_name"] == "Synthetic System"
    assert alpha["biome"] == "Lush" and alpha["infested"] is True
    assert alpha["named"] is True and alpha["name"] == "Synthetic Alpha"
    assert alpha["glyphs"] == "110000000000"
    assert alpha["coords"] == "07FF:007F:07FF:0100"
    assert alpha["planet_ua"] == f"0x{_ua(planet=1):X}"

    # 缺 VP 的行 infested 必须是 None，不能被当成 False 参与筛选。
    no_vp = disc.planet_from_record({"DD": {"DT": "Planet", "UA": _ua(planet=1)}})
    assert no_vp is not None
    _fake_discovered(monkeypatch, save, [no_vp])
    save.write_bytes(b"y")
    di.index_save(str(save), db_file=db)
    row = di.query(order="order", db_file=db)[0]
    assert row["infested"] is None
    assert di.query(infested=False, db_file=db) == []


def test_stats(tmp_path, monkeypatch):
    planets = _query_planets()
    save = tmp_path / "save.hg"
    save.write_bytes(b"x")
    db = str(tmp_path / "d.db")
    _fake_discovered(monkeypatch, save, planets)
    di.index_save(str(save), db_file=db)

    out = di.stats(db_file=db)
    assert out["ok"] is True and out["saves"] == 1 and out["planets"] == 5
    assert out["named"] == 2 and out["infested"] == 1
    assert out["biomes"]["Lush"] == 2 and out["biomes"]["Frozen"] == 1
    assert out["extractor_ver"] == di.EXTRACTOR_VER
    assert json.dumps(out)  # 只包含可序列化字段


# ---------------------------------------------------------------- 动物发现 / 行星联查


def _fauna_tree() -> dict:
    return _tree([
        _planet(1, vp=(0, 0)),
        _planet(2, vp=(0, 0)),
        _animal(1, seeds=(0x11, 0x22, 0x33, 0x44, 0x55), ts=100),
        _animal(1, seeds=(0x11, 0x22, 0x33, 0x44, 0x55), ts=100),  # 同种子重复
        _animal(1, seeds=(0xAA, 0xBB), name="Synthetic Fauna", ts=200),
        _animal(2, seeds=(0x99, 0x88)),
        {"DD": {"DT": "Animal", "UA": "0xZZ", "VP": [1]}},          # 坏 UA
        {"DD": {"DT": "Animal", "VP": [2]}},                        # 无地址
        _planet(3, vp=(0, 4)),
    ])


def test_fauna_from_tree_filters_and_dedups():
    tree = _fauna_tree()
    parsed = di.fauna_from_tree(tree, system_ua=SYSTEM_UA, planet_index=1)
    assert parsed["count"] == 2
    assert parsed["skipped"] == 2
    assert {r["creature_seed"] for r in parsed["fauna"]} == {"0x11", "0xAA"}
    first = next(r for r in parsed["fauna"] if r["creature_seed"] == "0x11")
    assert first["planet_ua"] == f"0x{_ua(planet=1):X}"
    assert first["species_seed"] == "0x33"
    assert first["genus_seed"] == "0x44"
    assert first["variant_seed"] == "0x55"

    only_planet2 = di.fauna_from_tree(tree, system_ua=SYSTEM_UA, planet_index=2)
    assert [r["creature_seed"] for r in only_planet2["fauna"]] == ["0x99"]

    other_system = di.fauna_from_tree(tree, system_ua=0x200 << 40, planet_index=1)
    assert other_system["fauna"] == []


def test_planet_fauna_reads_save_tree(tmp_path, monkeypatch):
    tree = _fauna_tree()
    save = tmp_path / "save.hg"
    save.write_bytes(b"x")
    monkeypatch.setattr(disc, "_open_tree", lambda path=None: (save, tree))

    res = di.planet_fauna(SYSTEM_UA, 1)
    assert res["ok"] is True
    assert res["count"] == 2 and res["reason"] is None
    assert res["planet_ua"] == f"0x{_ua(planet=1):X}"

    empty = di.planet_fauna(SYSTEM_UA, 3)
    assert empty["ok"] is True and empty["count"] == 0
    assert "没有找到" in empty["reason"]

    bad_system = di.planet_fauna("not-a-ua", 1)
    assert bad_system["ok"] is False and bad_system["fauna"] == []
    for bad_index in (0, 7):
        bad = di.planet_fauna(SYSTEM_UA, bad_index)
        assert bad["ok"] is False and "1..6" in bad["reason"]

    def boom(path=None):
        raise RuntimeError("synthetic open failure")

    monkeypatch.setattr(disc, "_open_tree", boom)
    failed = di.planet_fauna(SYSTEM_UA, 1)
    assert failed["ok"] is False and failed["fauna"] == []
    assert "synthetic open failure" in failed["reason"]

# ---------------------------------------------------------------- 多存档 / 关键词 / 排序


def test_index_saves_merges_all_and_dedupes(tmp_path, monkeypatch):
    planets = _rows(_tree([
        _planet(1, vp=(0x11, 0), name="Alpha Prime", ts=100),
        _planet(2, vp=(0x22, 4), ts=200),
    ]))
    save1 = tmp_path / "save.hg"
    save1.write_bytes(b"synthetic save a")
    save2 = tmp_path / "save3.hg"
    save2.write_bytes(b"synthetic save b")
    db = tmp_path / "discoveries.db"
    calls: list = []
    _fake_discovered(monkeypatch, save1, planets, calls)

    res = di.index_saves([save1, save2], db_file=str(db))
    assert res["ok"] is True
    assert [item["name"] for item in res["saves"]] == ["save.hg", "save3.hg"]
    assert res["raw_count"] == 4          # 两份存档各 2 行
    assert res["count"] == 2              # 按行星地址去重
    st = di.stats(db_file=str(db))
    assert st["planets"] == 4 and st["unique_planets"] == 2
    assert [f["name"] for f in st["save_files"]] == ["save.hg", "save3.hg"]


def test_query_keyword_and_save_ids(tmp_path, monkeypatch):
    planets = _rows(_tree([
        _planet(1, vp=(0x11, 0), name="Alpha Prime", ts=100),
        _planet(2, vp=(0x22, 4), name="Beta World", ts=200),
    ]))
    save1 = tmp_path / "save.hg"
    save1.write_bytes(b"synthetic save a")
    save2 = tmp_path / "save3.hg"
    save2.write_bytes(b"synthetic save b")
    db = tmp_path / "discoveries.db"
    _fake_discovered(monkeypatch, save1, planets)
    di.index_saves([save1, save2], db_file=str(db))

    rows = di.query(keyword="alpha", db_file=str(db))
    assert len(rows) == 2 and {r["name"] for r in rows} == {"Alpha Prime"}
    # 关键词也匹配星系/坐标/符文文本
    assert di.query(keyword="no-such-thing", db_file=str(db)) == []

    saves = di.stats(db_file=str(db))["save_files"]
    only = di.query(save_ids=[saves[-1]["save_id"]], db_file=str(db))
    assert len(only) == 2
    assert {row["save_name"] for row in only} == {"save3.hg"}


def test_query_order_name(tmp_path, monkeypatch):
    planets = _rows(_tree([
        _planet(1, vp=(0x11, 0), name="Zulu", ts=100),
        _planet(2, vp=(0x22, 4), name="Alpha", ts=200),
        _planet(3, vp=(0x33, 0), name=None, ts=300),
    ]))
    save = tmp_path / "save.hg"
    save.write_bytes(b"synthetic save")
    db = tmp_path / "discoveries.db"
    _fake_discovered(monkeypatch, save, planets)
    di.index_save(str(save), db_file=str(db))

    names = [r.get("name") for r in di.query(order="name", db_file=str(db))]
    assert names == [None, "Alpha", "Zulu"]
