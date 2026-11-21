"""GAMEDATA 有效性判据：目录存在不代表可用（Steam 原版也有 GAMEDATA）。"""
from __future__ import annotations

import json
import types


def _make_gamedata(root):
    """构造一个含 Gagarin/ships/catalog.txt 的最小 GAMEDATA。"""
    d = root / "GAMEDATA"
    (d / "Gagarin" / "ships").mkdir(parents=True)
    (d / "Gagarin" / "ships" / "catalog.txt").write_text("", encoding="utf-8")
    return d


def test_explicit_gamedata_used_only_when_valid(tmp_path, monkeypatch):
    from starforge.core import paths
    from starforge.core.settings import Settings

    good = _make_gamedata(tmp_path / "good")
    monkeypatch.setattr(paths, "gagarin_gamedata", lambda: None)

    assert Settings(gamedata_dir=str(good)).gamedata_resolved() == good

    bad = tmp_path / "steam" / "GAMEDATA"
    (bad / "PCBANKS").mkdir(parents=True)
    assert Settings(gamedata_dir=str(bad)).gamedata_resolved() is None


def test_invalid_explicit_falls_back_to_discovered(tmp_path, monkeypatch):
    from starforge.core.settings import Settings

    bad = tmp_path / "steam" / "GAMEDATA"
    (bad / "PCBANKS").mkdir(parents=True)
    good = _make_gamedata(tmp_path / "gagarin")
    monkeypatch.setenv("STARFORGE_GAMEDATA", str(good))

    assert Settings(gamedata_dir=str(bad)).gamedata_resolved() == good


def test_no_valid_gamedata_resolves_to_none(tmp_path, monkeypatch):
    from starforge.core.settings import Settings

    bad = tmp_path / "steam" / "GAMEDATA"
    (bad / "PCBANKS").mkdir(parents=True)
    auto_bad = tmp_path / "auto" / "GAMEDATA"
    (auto_bad / "INPUT").mkdir(parents=True)
    monkeypatch.setenv("STARFORGE_GAMEDATA", str(auto_bad))

    assert Settings(gamedata_dir=str(bad)).gamedata_resolved() is None


def test_autodetect_heals_invalid_configured_gamedata(tmp_path, monkeypatch):
    from starforge.core import paths, settings as settings_mod

    bad = tmp_path / "steam" / "GAMEDATA"
    (bad / "PCBANKS").mkdir(parents=True)
    good = _make_gamedata(tmp_path / "gagarin")
    monkeypatch.setattr(paths, "gagarin_gamedata", lambda: good)
    monkeypatch.setattr(paths, "default_save_dirs", lambda: [])
    monkeypatch.setattr("starforge.locate_game.find", lambda: None)
    settings_mod.update(gamedata_dir=str(bad), game_dir="", saves_dir="")

    rep = settings_mod.autodetect(apply=True)

    assert rep["found"]["gamedata_dir"] == str(good)
    assert settings_mod.current().gamedata_dir == str(good)


def test_doctor_flags_invalid_gamedata(capsys, tmp_path, monkeypatch):
    """doctor 必须把无效 GAMEDATA 变成可读提示，并让 ok/退出码失败。"""
    from starforge.__main__ import cmd_doctor
    from starforge.core import settings as settings_mod

    bad = tmp_path / "steam" / "GAMEDATA"
    (bad / "PCBANKS").mkdir(parents=True)
    monkeypatch.setenv("STARFORGE_GAMEDATA", str(bad))
    settings_mod.update(gamedata_dir=str(bad))

    rc = cmd_doctor(types.SimpleNamespace())
    out = json.loads(capsys.readouterr().out)

    assert out["gamedata"]["valid"] is False
    assert out["gamedata"]["path"] == str(bad)
    assert any("GAMEDATA" in n and "catalog.txt" in n for n in out["notes"])
    assert rc == 7
