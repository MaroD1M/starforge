"""备份对话框的纯逻辑测试：不依赖真实游戏/存档。"""
from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from starforge.app.dialogs import backup as backup_mod


def test_format_size():
    assert backup_mod.format_size(0) == "0 B"
    assert backup_mod.format_size(512) == "512 B"
    assert backup_mod.format_size(1024) == "1.0 KB"
    assert backup_mod.format_size(1536) == "1.5 KB"
    assert backup_mod.format_size(5 * 1024 * 1024) == "5.0 MB"


def test_backup_rows_use_timestamp_from_filename():
    path = "/tmp/save.hg.20240102-030405-123456.bak"
    rows = backup_mod.backup_rows([{"path": path, "bytes": 2048, "mtime": 0}])
    assert len(rows) == 1
    assert rows[0]["name"] == "save.hg.20240102-030405-123456.bak"
    assert rows[0]["time"] == "2024-01-02 03:04:05"
    assert rows[0]["size"] == "2.0 KB"
    assert rows[0]["path"] == path


def test_backup_rows_fall_back_to_mtime():
    stamp = int(time.mktime((2020, 1, 2, 3, 4, 5, 0, 0, -1)))
    rows = backup_mod.backup_rows([{"path": "/tmp/other.bak", "bytes": 1, "mtime": stamp}])
    expected = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stamp))
    assert rows[0]["time"] == expected


def test_backup_dialog_is_importable():
    assert backup_mod.BackupDialog.__name__ == "BackupDialog"
