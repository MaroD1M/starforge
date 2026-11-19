"""设置字段与诊断 ZIP 的契约测试（无游戏/无存档也不能崩）。"""
from __future__ import annotations

import json
import os
import zipfile

import pytest


def test_settings_fields_persist_across_reload():
    from starforge.core import settings as settings_mod

    settings_mod.update(confirm_writes=False, backup_keep=7, workers=3)
    settings_mod._CURRENT = None
    loaded = settings_mod.current()
    assert loaded.confirm_writes is False
    assert loaded.backup_keep == 7
    assert loaded.workers == 3

    from starforge.services import Services

    snap = Services().settings_snapshot()["settings"]
    assert snap["confirm_writes"] is False
    assert snap["backup_keep"] == 7
    assert snap["workers"] == 3


def test_settings_page_controls_save_immediately(qapp):
    from starforge.app.pages.settings import SettingsPage
    from starforge.core import settings as settings_mod

    page = SettingsPage()
    try:
        page.confirm_writes.setChecked(False)
        page.backup_keep.setValue(4)
        page.workers.setValue(2)
        settings_mod._CURRENT = None
        saved = settings_mod.current()
        assert saved.confirm_writes is False
        assert saved.backup_keep == 4
        assert saved.workers == 2
        assert "未知" in page._format_build({"error": "没有配置游戏目录"})
        assert "未验证" in page._format_build({"build_id": "1-ABC", "status": "unknown"})
    finally:
        page.close()
        page.deleteLater()


def test_recent_logs_limits_count_and_size():
    from starforge.core import paths
    from starforge.services import Services

    log_dir = paths.app_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    for i in range(8):
        (log_dir / f"sample-{i}.log").write_text("x" * 200, encoding="utf-8")

    res = Services().recent_logs(limit=3, max_bytes=32)
    assert res["ok"]
    assert len(res["files"]) == 3
    assert all(f["truncated"] for f in res["files"])
    assert all(len(f["text"]) <= 32 for f in res["files"])


def test_diagnostics_zip_contains_required_files_and_redacts(monkeypatch, tmp_path):
    from starforge.core import paths
    from starforge.services import Services

    log_dir = paths.app_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "starforge.log").write_text(
        "启动完成\nAuthorization: Bearer SECRET_LOGGED\n", encoding="utf-8")
    agent_dir = paths.app_home() / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "launcher.log").write_text(
        "launcher ok\napi_token=SECRET_LAUNCHER\n", encoding="utf-8")

    svc = Services()
    monkeypatch.setattr(svc, "health", lambda: {"ok": True, "token": "SECRET_HEALTH"})
    monkeypatch.setattr(svc, "doctor", lambda: {"ok": True, "deps": {"numpy": "ok"}})
    monkeypatch.setattr(svc, "diagnostics", lambda: {
        "ok": True, "token": "SECRET_SELFCHECK", "steps": [{"name": "x", "ok": True}]})
    monkeypatch.setattr(svc, "build_status", lambda: {
        "ok": True, "build_id": "1-ABC", "status": "unknown",
        "verified": False, "write_allowed": False})
    monkeypatch.setattr(svc, "agent_status", lambda: {
        "ok": True, "supported": False, "reachable": False,
        "secret": "SECRET_AGENT"})
    monkeypatch.setattr(svc, "settings_snapshot", lambda: {
        "ok": True,
        "settings": {"write_enabled": True, "confirm_writes": False,
                     "backup_keep": 2, "workers": 4, "api_token": "SECRET_SETTINGS"},
        "resolved": {}})

    dest = tmp_path / "diag.zip"
    res = svc.export_diagnostics(str(dest))
    assert res["ok"] and dest.exists()

    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        required = {"manifest.json", "health.json", "doctor.json", "selfcheck.json",
                    "settings.json", "build.json", "agent.json",
                    "logs/starforge.log", "logs/launcher.log"}
        assert required <= names
        raw = "\n".join(zf.read(name).decode("utf-8", "replace") for name in names)
        assert "SECRET_" not in raw
        settings_doc = json.loads(zf.read("settings.json"))
        assert settings_doc["settings"]["api_token"] == "***"
        manifest = json.loads(zf.read("manifest.json"))
        assert required - {"manifest.json"} <= set(manifest["files"])


def test_diagnostics_zip_without_game_or_saves(monkeypatch, tmp_path):
    from starforge.core import settings as settings_mod
    from starforge.services import Services

    settings_mod.update(game_dir="", saves_dir="", gamedata_dir="")
    for name in ("NMS_DIR", "STARFORGE_GAMEDATA", "STARFORGE_SAVES"):
        monkeypatch.delenv(name, raising=False)

    dest = tmp_path / "no-game.zip"
    res = Services().export_diagnostics(str(dest), include_selfcheck=False)
    assert res["ok"] and dest.exists()
    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        assert {"manifest.json", "health.json", "doctor.json", "selfcheck.json",
                "settings.json", "build.json", "agent.json"} <= names
        build = json.loads(zf.read("build.json"))
        assert build.get("write_allowed") is False
        selfcheck = json.loads(zf.read("selfcheck.json"))
        assert selfcheck.get("skipped") is True


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
