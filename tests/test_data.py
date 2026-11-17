"""数据层：catalog / icons / gshi 的回归测试（用真实 Gagarin 数据）。"""
import pytest

from starforge.data import gshi, load_catalog, load_icons


def test_catalog_totals(gamedata):
    cat = load_catalog(gamedata)
    assert cat.stats["ship"] == 8
    assert cat.stats["L"] == 543
    assert cat.stats["O"] == 1430
    assert cat.stats["C"] == cat.stats["E"] == 225
    assert cat.stats["palette"] == 66
    assert cat.opens_at_eof > 0          # L 无显式闭合，EOF 时留下作用域


def test_catalog_ship_set(gamedata):
    cat = load_catalog(gamedata)
    assert set(cat.ships) == {"sentinel", "fighter", "hauler", "shuttle",
                              "explorer", "exotic", "living", "solar"}


def test_catalog_locate_part(gamedata):
    cat = load_catalog(gamedata)
    got = cat.locate("_PIT_A")
    assert got and got[0][1] == "_PIT_"
    assert {t for t, _, _ in got} >= {"sentinel"}


def test_catalog_options_have_weights(gamedata):
    cat = load_catalog(gamedata)
    weights = {w for opts in cat.ships["fighter"]["groups"].values() for _, w in opts}
    assert weights <= {0, 1, 20}


def test_icons_load_all(gamedata):
    ics = load_icons(gamedata)
    assert ics.counts["ships"] == 1039
    assert ics.counts["parts"] == 867
    assert ics.versions["ships"] == 1 and ics.versions["parts"] == 2


def test_icon_is_png(gamedata):
    ics = load_icons(gamedata)
    png = ics.png("_PIT_A", "sentinel")
    assert png and png[:8] == b"\x89PNG\r\n\x1a\n"


def test_icon_unknown_part(gamedata):
    assert load_icons(gamedata).png("_NO_SUCH_PART_") is None


@pytest.mark.parametrize("path_name", ["ships/icons.bin", "parts/icons.bin"])
def test_gshi_container_exact(gamedata, path_name):
    p = gamedata / "Gagarin" / path_name
    if not p.exists():
        pytest.skip("缺 icons.bin")
    ver, ents = gshi.parse_container(p)
    assert ver in (1, 2) and len(ents) > 0
    name, w, h, data = ents[0]
    assert gshi.decode(ver, w, h, data)      # 能解出正确像素数
    with pytest.raises(ValueError):
        gshi.decode(ver, w, h, data[:-4])    # 截断必须报错，不能静默


def test_gshi_bad_magic():
    with pytest.raises(ValueError):
        gshi.parse_container_bytes(b"NOPE" + b"\0" * 20)


def test_parts_fall_back_to_game_assets(nms_dir, monkeypatch):
    """没有 Gagarin 的 catalog 时，部件树必须能从游戏资源推导出来。"""
    from starforge.core import settings as settings_mod
    from starforge import parts
    settings_mod.update(game_dir=str(nms_dir))
    monkeypatch.setattr(parts, "load_catalog",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no catalog")))
    tree = parts.tree("sentinel")
    assert len(tree) >= 20 and sum(len(g["options"]) for g in tree) >= 100
    assert parts.source() == "game"
