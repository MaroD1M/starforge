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
