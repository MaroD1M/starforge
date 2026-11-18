"""船级/属性编辑的纯逻辑测试：不读存档、不写盘。"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from starforge.app.dialogs import class_editor as ce


def test_stat_rows_follow_known_order_and_labels():
    rows = ce.stat_rows({"agility": 44.5, "damage": 78.7, "shield": "30.5"})
    assert [r["key"] for r in rows] == ["damage", "shield", "agility"]
    assert rows[0]["label"] == "伤害" and rows[0]["value"] == 78.7
    assert rows[1]["value"] == 30.5


def test_stat_rows_without_data_show_all_fields():
    rows = ce.stat_rows(None)
    assert [r["key"] for r in rows] == list(ce.STAT_ORDER)
    assert all(r["value"] == 0.0 for r in rows)


def test_changed_values_only_submits_edits():
    current = {"damage": 10.0, "shield": 20.0}
    edited = {"damage": 10.0, "shield": 25.5, "agility": 8}
    assert ce.changed_values(current, edited) == {"shield": 25.5, "agility": 8.0}
    assert ce.changed_values(current, {"damage": 10.0}) == {}


def test_changed_values_ignores_bad_numbers():
    assert ce.changed_values({"damage": 1.0}, {"damage": "nope", "shield": None}) == {}


def test_stat_summary_is_stable():
    assert ce.stat_summary({"damage": 78.7, "hyperdrive": 8.7}) == "伤害 78.7 · 超光速 8.7"
    assert ce.stat_summary(None) == "无"


def test_class_editor_dialog_is_importable():
    assert ce.ClassEditorDialog.__name__ == "ClassEditorDialog"
