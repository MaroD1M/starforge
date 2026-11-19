"""飞船实验室：搜索估算/worker 默认值与种子反查对话框（offscreen）。"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _hit(**kw) -> dict:
    row = {
        "ua": "0x1043FEE69929",
        "coords": "04E4:0070:01BC:0104",
        "glyphs": "1043FEE69929",
        "galaxy": 3,
        "where": "space station",
        "what": "fighter",
        "visited": True,
        "portal_hint": "传送门输入 1043FEE69929",
    }
    row.update(kw)
    return row


def test_default_workers_caps_at_four_and_never_zero():
    from starforge.app.pages.ship_lab import default_workers

    assert default_workers(1) == 1
    assert default_workers(2) == 2
    assert default_workers(4) == 4
    assert default_workers(16) == 4
    assert default_workers(0) == 1
    assert default_workers(None) >= 1


def test_format_estimate_shows_odds_seconds_and_workers():
    from starforge.app.pages.ship_lab import format_estimate

    text = format_estimate({"one_in": 128000, "estimate_seconds": 2.5}, workers=4)
    assert "1 in 128,000" in text
    assert "2.5" in text
    assert "4 线程" in text
    assert format_estimate({"one_in": 0, "estimate_seconds": None}) == ""
    assert format_estimate(None) == ""
    assert format_estimate({"ok": False, "one_in": 10}) == ""


def test_locate_rows_keep_where_what_and_visited():
    from starforge.app.dialogs.locate import locate_rows

    rows = locate_rows({"hits": [_hit(), _hit(glyphs="", coords="", visited=False)]})
    assert len(rows) == 2
    assert rows[0]["coords"] == "04E4:0070:01BC:0104"
    assert rows[0]["glyphs"] == "1043FEE69929"
    assert rows[0]["where_what"] == "space station / fighter"
    assert rows[0]["visited"] is True
    assert rows[1]["visited"] is False
    assert locate_rows(None) == []
    assert locate_rows({"hits": [None, "bad", {}]})[0]["where_what"] == ""


def test_locate_empty_text_states_underdetermined_without_faking_hits():
    from starforge.app.dialogs.locate import locate_empty_text

    assert "反查欠定" in locate_empty_text(None) or "反查" in locate_empty_text(None)
    text = locate_empty_text({"candidates": 7, "hits": [], "reason": "候选生成失败"})
    assert "反查欠定" in text
    assert "候选 7" in text
    assert "候选生成失败" in text
    assert locate_empty_text({"candidates": 1, "hits": [_hit()]}) == ""


def test_locate_dialog_shows_hits_and_copies_coords_and_glyphs(qapp):
    from PySide6.QtGui import QGuiApplication

    from starforge.app.dialogs.locate import LocateDialog

    dialog = LocateDialog("0x1043FEE69929", services=object(), auto_start=False)
    try:
        dialog.set_result({"seed": "0x1043FEE69929", "candidates": 3,
                           "known_systems": 12, "hits": [_hit()]})
        assert dialog.table.rowCount() == 1
        assert "候选：3" in dialog.summary.text()
        assert "已证实：1" in dialog.summary.text()
        assert dialog.table.item(0, 0).text() == "04E4:0070:01BC:0104"
        assert dialog.table.item(0, 1).text() == "1043FEE69929"
        assert dialog.table.item(0, 3).text() == "space station / fighter"
        assert dialog.table.item(0, 4).text() == "是"

        dialog._copy_coords()
        assert QGuiApplication.clipboard().text() == "04E4:0070:01BC:0104"
        dialog._copy_glyphs()
        assert QGuiApplication.clipboard().text() == "1043FEE69929"
    finally:
        dialog.close()


def test_locate_dialog_no_hits_does_not_invent_rows(qapp):
    from starforge.app.dialogs.locate import LocateDialog

    dialog = LocateDialog("0xBADC0DE", services=object(), auto_start=False)
    try:
        dialog.set_result({"seed": "0xBADC0DE", "candidates": 4, "hits": [],
                           "reason": "这个种子反解不出可信的星系统"})
        assert dialog.table.rowCount() == 0
        assert "反查欠定" in dialog.status.text()
        assert "已证实：0" in dialog.summary.text()
        assert not dialog.copy_coords_btn.isEnabled()
        assert not dialog.copy_glyphs_btn.isEnabled()
    finally:
        dialog.close()


def test_ship_card_accessibility_exposes_type_class_seed(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    from starforge.app.widgets.ship_card import card_accessibility, set_card_accessibility

    row = {"type": "fighter", "type_label": "战斗机", "ship_class": "S",
           "seed": "0xABC", "parts": ["_PIT_A", "_WING_B"]}
    text, desc = card_accessibility(row, in_compare=True)
    assert "战斗机" in text and "S 级" in text and "0xABC" in text
    assert "类型：" in desc and "等级：S" in desc and "种子：0xABC" in desc
    assert "已加入对比" in desc

    item = QListWidgetItem("0xABC")
    set_card_accessibility(item, row)
    assert "战斗机" in item.data(Qt.AccessibleTextRole)
    assert "0xABC" in item.data(Qt.AccessibleDescriptionRole)


def test_ship_lab_results_keep_keyboard_multi_select_and_locate_entry(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView, QListWidgetItem

    from starforge.app.pages import ship_lab as ship_lab_mod

    page = ship_lab_mod.ShipLabPage()
    try:
        assert page.results.selectionMode() == QAbstractItemView.ExtendedSelection
        assert page.results.focusPolicy() == Qt.StrongFocus
        assert page.workers.value() == ship_lab_mod.default_workers()
        assert page.locate_btn.text() == "查星系"

        for seed in ("0x1", "0x2"):
            item = QListWidgetItem(seed)
            item.setData(Qt.UserRole, {"type": "fighter", "seed": seed})
            page.results.addItem(item)
        page.results.item(0).setSelected(True)
        page.results.item(1).setSelected(True)
        assert len(page.results.selectedItems()) == 2

        calls: list[str] = []

        class FakeDialog:
            def __init__(self, seed, parent=None):
                calls.append(seed)

            def exec(self):
                return 0

        monkeypatch.setattr(ship_lab_mod, "LocateDialog", FakeDialog)
        page.results.setCurrentItem(page.results.item(0))
        page._locate_seed()
        assert calls == ["0x1"]
    finally:
        page.close()
