"""存档自动选择：按最近写入时间挑当前游玩档，而不是死认 save.hg。

真实场景：玩家在 save3.hg（游戏刚保存），save.hg/save2.hg 是前一天的旧档。
这里只用临时文件与合成头，不解码真实存档。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from starforge.core import settings
from starforge.core.errors import SaveNotFound
from starforge.save import library


def _write_save(path, mtime_ns: int, *, player: bool = True):
    path.write_bytes(library.CHUNK_MAGIC + b"\x00" * 12 if player else b"not-a-save")
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def _use_saves_dir(monkeypatch, folder):
    monkeypatch.setattr(
        settings, "current",
        lambda: SimpleNamespace(saves_dir_resolved=lambda: folder))


def test_default_save_picks_most_recently_written_player(tmp_path, monkeypatch):
    _write_save(tmp_path / "save.hg", 1_000_000_000_000_000_000)
    _write_save(tmp_path / "save3.hg", 1_700_000_000_000_000_000)
    # 非玩家文件即使更新也不能被选中。
    _write_save(tmp_path / "save9.hg", 1_900_000_000_000_000_000, player=False)
    (tmp_path / "accountdata.hg").write_text("{}", encoding="utf-8")
    _use_saves_dir(monkeypatch, tmp_path)

    assert library.default_save_path().name == "save3.hg"

    rows = library.list_player_saves(tmp_path)
    assert [row["name"] for row in rows] == ["save3.hg", "save.hg"]
    assert rows[0]["path"].endswith("save3.hg")
    assert rows[0]["size"] == 16
    assert rows[0]["mtime"] > rows[1]["mtime"]


def test_list_player_saves_uses_normal_natural_order_on_same_mtime(tmp_path):
    stamp = 1_700_000_000_000_000_000
    _write_save(tmp_path / "save10.hg", stamp)
    _write_save(tmp_path / "save2.hg", stamp)
    _write_save(tmp_path / "save.hg", stamp)

    names = [row["name"] for row in library.list_player_saves(tmp_path)]
    assert names.index("save2.hg") < names.index("save10.hg")
    assert "save.hg" in names


def test_default_save_error_lists_found_files(tmp_path, monkeypatch):
    (tmp_path / "accountdata.hg").write_text("{}", encoding="utf-8")
    _write_save(tmp_path / "save7.hg", 1_700_000_000_000_000_000, player=False)
    _use_saves_dir(monkeypatch, tmp_path)

    with pytest.raises(SaveNotFound) as exc:
        library.default_save_path()
    message = str(exc.value)
    assert "accountdata.hg" in message
    assert "save7.hg" in message
    assert "找到的文件" in message


def test_list_player_saves_missing_dir_is_empty(tmp_path):
    assert library.list_player_saves(tmp_path / "missing") == []
