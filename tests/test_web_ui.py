"""API-only 服务与新增接口的契约测试。"""
from __future__ import annotations


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
    from starforge.core import settings as settings_mod
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
    assert settings_mod.current().saves_dir == ""


def test_autodetect_api(client, monkeypatch, tmp_path):
    from starforge.core import paths as paths_mod
    fake = tmp_path / "st_api"
    fake.mkdir()
    (fake / "save.hg").write_bytes(b"{}")
    monkeypatch.setattr(paths_mod, "default_save_dirs", lambda: [fake])
    j = client.get("/api/autodetect").get_json()
    assert j["ok"] and j["found"]["saves_dir"] == str(fake)


def test_settings_reports_path_checks(client, game_env, saves_dir):
    from starforge.core import settings as settings_mod
    settings_mod.update(saves_dir=str(saves_dir))
    j = client.get("/api/settings").get_json()
    assert "checks" in j
    assert j["checks"]["game_dir"]["ok"] is True
    assert j["checks"]["saves_dir"]["ok"] is True
    assert "detail" in j["checks"]["gamedata_dir"]


def test_ships_include_class_and_stats(client, game_env, saves_dir):
    from starforge.core import settings as settings_mod
    settings_mod.update(saves_dir=str(saves_dir))
    j = client.get("/api/ships").get_json()
    rows = j["ships"]
    assert any(r.get("ship_class") for r in rows)
    with_stats = [r for r in rows if r.get("stats")]
    assert with_stats and "damage" in with_stats[0]["stats"]
    assert all("type_label" in r and "can_preview" in r for r in rows)


def test_webcheck_command_passes(monkeypatch, tmp_path):
    """打包后用它验证 API-only 服务：进程内跑，不依赖端口。"""
    import io
    import sys
    from starforge.__main__ import cmd_webcheck
    monkeypatch.setenv("STARFORGE_NO_WARM", "1")
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    rc = cmd_webcheck(None)
    out = buf.getvalue()
    assert rc == 0
    assert "接口自检通过" in out


def test_gui_launcher_hides_console():
    from pathlib import Path
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/release.yml").read_text("utf-8")
    assert "--name starforge-cli" in wf
    assert "packaging/launcher.py" in wf
    assert wf.count("pyinstaller --noconfirm") == 2
    assert "--windowed" in wf
    assert 'Copy-Item "dist/launcher/starforge.exe"' in wf
