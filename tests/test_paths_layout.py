"""开发布局解析：与仓库并列的 Gagarin_Titov 也要能自动找到。

背景：`shipwright_root()` 早就有 `..\\NMS-Shipwright`（与仓库并列）的候选，
但 `gagarin_gamedata()` 只认“仓库内”的 `Gagarin_Titov`、发布包的 `vendor/gamedata`
和 Linux 工作区，导致 Windows 开发机上必须手设 STARFORGE_GAMEDATA 才能跑数据类测试。
"""
from __future__ import annotations

from pathlib import Path

from starforge.core import paths


def _fake_repo(tmp_path: Path) -> Path:
    """造一个 `tmp/starforge/starforge/core/paths.py` 的假仓库布局。"""
    repo = tmp_path / "starforge"
    fake = repo / "starforge" / "core" / "paths.py"
    fake.parent.mkdir(parents=True)
    fake.write_text("", encoding="utf-8")
    return fake


def _make_gamedata(root: Path) -> Path:
    gd = root / "Gagarin_Titov" / "GAMEDATA"
    ships = gd / "Gagarin" / "ships"
    ships.mkdir(parents=True)
    (ships / "catalog.txt").write_text("", encoding="utf-8")
    return gd


def test_sibling_gamedata_is_discovered(tmp_path, monkeypatch):
    """`..\\Gagarin_Titov\\GAMEDATA`（与仓库并列）应被自动发现。"""
    fake = _fake_repo(tmp_path)
    want = _make_gamedata(tmp_path)                      # tmp/Gagarin_Titov/GAMEDATA
    monkeypatch.delenv("STARFORGE_GAMEDATA", raising=False)
    monkeypatch.setattr(paths, "__file__", str(fake))
    assert paths.gagarin_gamedata() == want


def test_in_repo_gamedata_wins_over_sibling(tmp_path, monkeypatch):
    """仓库内的那份优先于并列目录（保持原有优先级）。"""
    fake = _fake_repo(tmp_path)
    inside = _make_gamedata(tmp_path / "starforge")      # tmp/starforge/Gagarin_Titov/GAMEDATA
    _make_gamedata(tmp_path)                             # 并列的那份
    monkeypatch.delenv("STARFORGE_GAMEDATA", raising=False)
    monkeypatch.setattr(paths, "__file__", str(fake))
    assert paths.gagarin_gamedata() == inside


def test_env_var_still_wins(tmp_path, monkeypatch):
    """环境变量始终是第一优先级。"""
    fake = _fake_repo(tmp_path)
    _make_gamedata(tmp_path)
    env_dir = _make_gamedata(tmp_path / "elsewhere")
    monkeypatch.setenv("STARFORGE_GAMEDATA", str(env_dir))
    monkeypatch.setattr(paths, "__file__", str(fake))
    assert paths.gagarin_gamedata() == env_dir
