"""桌面外壳与配色：能在无图形环境下验证的部分。"""
import os

import pytest

from starforge import desktop, paint


def test_free_port_is_local_and_free():
    import socket
    p = desktop._free_port()
    assert 1024 < p < 65536
    with socket.socket() as s:                  # 端口应当可绑定
        s.bind(("127.0.0.1", p))


def test_available_reports_bool():
    assert isinstance(desktop.available(), bool)


def test_window_state_roundtrip(tmp_path, monkeypatch):
    from starforge.core import paths as paths_mod
    monkeypatch.setattr(paths_mod, "app_home", lambda: tmp_path)
    desktop._save_state({"w": 1600, "h": 900})
    assert desktop._load_state() == {"w": 1600, "h": 900}


def test_api_open_path_missing_returns_false():
    api = desktop._Api()
    assert api.open_path("/definitely/not/here") is False


def test_api_info_shape():
    info = desktop._Api().info()
    assert info["version"] and info["platform"] and info["home"]


def test_paint_look_without_game_is_empty_or_partial():
    cols = paint.look("0x992C8A47F60A6B10", "sentinel")
    assert isinstance(cols, dict)               # 有游戏时有值，没游戏时 {}


def test_paint_hexcol():
    assert paint.hexcol([1.0, 0.5, 0.0]) == "#ff8000"
    assert paint.hexcol([0, 0, 0]) == "#000000"


def test_paint_look_uses_game_colours(game_env):
    cols = paint.look("0x992C8A47F60A6B10", "sentinel")
    assert "paint" in cols and len(cols["paint"]) == 3
    assert all(0 <= c <= 1 for c in cols["paint"])


def test_probe_reports_reason_when_unavailable():
    info = desktop.probe()
    assert set(info) >= {"pywebview", "pythonnet", "available", "reason", "windows"}
    if not info["available"]:
        assert info["reason"]


def test_probe_api(client):
    j = client.get("/api/desktop").get_json()
    assert j["ok"] and "available" in j and "reason" in j


# ---------------------------------------------------------------- 找游戏目录

def test_looks_like_game(tmp_path):
    from starforge import locate_game
    fake = tmp_path / "No Man's Sky"
    (fake / "Binaries").mkdir(parents=True)
    (fake / "Binaries" / "NMS.exe").write_bytes(b"MZ")
    (fake / "GAMEDATA" / "PCBANKS").mkdir(parents=True)
    assert locate_game.looks_like_game(str(fake)) is True
    assert locate_game.looks_like_game(str(tmp_path)) is False
    assert locate_game.looks_like_game(None) is False


def test_library_paths_parses_vdf(tmp_path):
    from starforge import locate_game
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    other = tmp_path / "Library2"
    other.mkdir()
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n "1"\n {\n  "path"\t\t"%s"\n }\n}\n' % str(other).replace("\\", "\\\\"),
        encoding="utf-8")
    got = locate_game._library_paths(str(steam))
    assert str(steam) in got and str(other) in got


def test_find_prefers_env(tmp_path, monkeypatch):
    from starforge import locate_game
    fake = tmp_path / "nms"
    (fake / "Binaries").mkdir(parents=True)
    (fake / "Binaries" / "NMS.exe").write_bytes(b"MZ")
    (fake / "GAMEDATA" / "PCBANKS").mkdir(parents=True)
    monkeypatch.setenv("NMS_DIR", str(fake))
    assert locate_game.find() == str(fake)


def test_normalize_fixes_common_mistakes(tmp_path):
    from starforge import locate_game
    game = tmp_path / "No Man's Sky"
    (game / "Binaries").mkdir(parents=True)
    (game / "Binaries" / "NMS.exe").write_bytes(b"MZ")
    (game / "GAMEDATA" / "PCBANKS").mkdir(parents=True)
    steam = tmp_path / "Steam"
    (steam / "steamapps" / "common").mkdir(parents=True)
    (steam / "steamapps" / "common" / "No Man's Sky").symlink_to(game)

    assert locate_game.normalize(str(game)) == str(game)                  # 本来就对
    assert locate_game.normalize(str(game / "GAMEDATA")) == str(game)     # 选到了 GAMEDATA
    assert locate_game.normalize(str(game / "Binaries")) == str(game)     # 选到了 Binaries
    assert locate_game.normalize(str(steam)) == str(steam / "steamapps" / "common" / "No Man's Sky")
    assert locate_game.normalize(None) is None
