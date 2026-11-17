"""网页与新增接口的契约测试（页面/静态资源/缩略图/系统/设置/诊断）。"""
import pytest

from starforge.core import settings as settings_mod


def test_index_page_has_four_tabs(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.data.decode("utf-8")
    for page in ("page-search", "page-mine", "page-systems", "page-settings"):
        assert page in html
    for tab in ('data-tab="search"', 'data-tab="mine"', 'data-tab="systems"', 'data-tab="settings"'):
        assert tab in html
    assert "/static/app.js" in html and "/static/viewer.js" in html


@pytest.mark.parametrize("name,mime", [("app.css", "text/css"), ("app.js", "text/javascript"),
                                       ("viewer.js", "text/javascript")])
def test_static_assets(client, name, mime):
    r = client.get(f"/static/{name}")
    assert r.status_code == 200 and r.mimetype == mime and len(r.data) > 500


def test_static_traversal_blocked(client):
    r = client.get("/static/../starforge/core/settings.py")
    assert r.status_code in (403, 404)


def test_capabilities(client):
    j = client.get("/api/capabilities").get_json()
    assert j["ok"] and j["preview_level"] in ("L0", "L1")
    assert "biomes" in j["system"] and "sentinels" in j["system"]


def test_settings_roundtrip(client):
    r = client.post("/api/settings", json={"saves_dir": "/tmp/xx", "write_enabled": False})
    assert r.get_json()["ok"]
    j = client.get("/api/settings").get_json()
    assert j["settings"]["saves_dir"] == "/tmp/xx"


def test_diagnostics_shape(client):
    j = client.get("/api/diagnostics").get_json()
    assert j["ok"] and "preview_level" in j and "shipwright" in j


def test_thumb_png(client, game_env):
    r = client.get("/api/thumb/sentinel/0x992C8A47F60A6B10.png?size=300")
    assert r.status_code == 200 and r.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_system_current(client, game_env, saves_dir):
    settings_mod.update(saves_dir=str(saves_dir))
    j = client.get("/api/system?current=1").get_json()
    assert j["ok"] and j["planets"] >= 1
    assert j["glyphs"] and len(j["glyphs"]) == 12
    assert "ships" in j and isinstance(j["ships"], list)


def test_autodetect_fills_save_dir(tmp_path, monkeypatch):
    from starforge.core import paths as paths_mod, settings as settings_mod
    fake = tmp_path / "st_123"
    fake.mkdir()
    (fake / "save.hg").write_bytes(b"{\"x\":1}")
    monkeypatch.setattr(paths_mod, "default_save_dirs", lambda: [fake])
    monkeypatch.delenv("NMS_DIR", raising=False)
    settings_mod.update(saves_dir="", gamedata_dir="", game_dir="")
    rep = settings_mod.autodetect(apply=True)
    assert rep["found"]["saves_dir"] == str(fake)
    assert settings_mod.current().saves_dir == str(fake)


def test_autodetect_readonly_mode(tmp_path, monkeypatch):
    from starforge.core import paths as paths_mod, settings as settings_mod
    fake = tmp_path / "st_x"
    fake.mkdir()
    (fake / "save.hg").write_bytes(b"{}")
    monkeypatch.setattr(paths_mod, "default_save_dirs", lambda: [fake])
    settings_mod.update(saves_dir="")
    rep = settings_mod.autodetect(apply=False)
    assert rep["found"]["saves_dir"] == str(fake)
    assert rep["applied"] is False
    assert settings_mod.current().saves_dir == ""       # 未写盘


def test_autodetect_api(client, monkeypatch, tmp_path):
    from starforge.core import paths as paths_mod
    fake = tmp_path / "st_api"
    fake.mkdir()
    (fake / "save.hg").write_bytes(b"{}")
    monkeypatch.setattr(paths_mod, "default_save_dirs", lambda: [fake])
    j = client.get("/api/autodetect").get_json()
    assert j["ok"] and j["found"]["saves_dir"] == str(fake)
