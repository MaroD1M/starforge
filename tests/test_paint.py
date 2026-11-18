from starforge import paint


def test_paint_look_without_game_is_empty_or_partial():
    cols = paint.look("0x992C8A47F60A6B10", "sentinel")
    assert isinstance(cols, dict)


def test_paint_hexcol():
    assert paint.hexcol([1.0, 0.5, 0.0]) == "#ff8000"
    assert paint.hexcol([0, 0, 0]) == "#000000"


def test_paint_look_uses_game_colours(game_env):
    cols = paint.look("0x992C8A47F60A6B10", "sentinel")
    assert "paint" in cols and len(cols["paint"]) == 3
    assert all(0 <= c <= 1 for c in cols["paint"])
