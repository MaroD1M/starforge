"""原生界面无障碍/键盘交互测试；使用 offscreen，不依赖游戏数据。"""
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


def _labels(palette) -> list[str]:
    return [palette.list.item(i).text() for i in range(palette.list.count())]


def test_command_palette_groups_filters_and_keyboard(qapp):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    from starforge.app.widgets.command_palette import CommandPalette

    calls: list[str] = []
    palette = CommandPalette([
        ("页面", "概览", lambda: calls.append("home")),
        ("页面", "设置", lambda: calls.append("settings")),
        ("操作", "刷新状态", lambda: calls.append("refresh")),
    ])
    try:
        assert palette.accessibleName() == "命令面板"
        assert palette.edit.accessibleName() == "命令搜索框"
        assert palette.list.accessibleName() == "命令列表"
        labels = _labels(palette)
        assert "页面" in labels and "操作" in labels
        assert palette.list.currentItem().text() == "概览"

        # 上下键应跳过“操作”分组标题并循环到另一组命令。
        assert palette.eventFilter(
            palette.edit, QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier))
        assert palette.list.currentItem().text() == "设置"
        assert palette.eventFilter(
            palette.edit, QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier))
        assert palette.list.currentItem().text() == "刷新状态"
        assert palette.eventFilter(
            palette.edit, QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier))
        assert palette.list.currentItem().text() == "概览"
        assert palette.eventFilter(
            palette.edit, QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier))
        assert palette.list.currentItem().text() == "刷新状态"

        palette.edit.setText("刷新")
        assert _labels(palette) == ["操作", "刷新状态"]
        assert palette.list.currentItem().text() == "刷新状态"

        assert palette.eventFilter(
            palette.edit, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
        assert calls == ["refresh"]
    finally:
        palette.close()


def test_command_palette_empty_state(qapp):
    from PySide6.QtCore import Qt

    from starforge.app.widgets.command_palette import EMPTY_TEXT, CommandPalette

    palette = CommandPalette([("页面", "概览", lambda: None)])
    try:
        palette.edit.setText("绝对不存在的命令")
        assert _labels(palette) == [EMPTY_TEXT]
        assert palette.list.currentItem() is None
        assert palette.list.item(0).flags() & Qt.ItemIsEnabled
    finally:
        palette.close()


def test_focus_first_input_skips_disabled(qapp):
    from PySide6.QtWidgets import QComboBox, QLineEdit, QTreeWidget, QVBoxLayout, QWidget

    from starforge.app.widgets.ui import focus_first_input

    host = QWidget()
    layout = QVBoxLayout(host)
    combo = QComboBox()
    tree = QTreeWidget()
    edit = QLineEdit()
    for widget in (combo, tree, edit):
        layout.addWidget(widget)
    host.show()
    qapp.processEvents()
    try:
        assert focus_first_input(host) is edit
        assert edit.hasFocus()
        edit.setEnabled(False)
        assert focus_first_input(host) is combo
        combo.setEnabled(False)
        tree.setEnabled(False)
        assert focus_first_input(host) is None
    finally:
        host.close()


def test_all_pages_share_header_pattern(qapp):
    from starforge.app.shell import NAV, MainWindow
    from starforge.app.widgets.page_header import PageHeader

    win = MainWindow()
    try:
        for key, _label in NAV:
            page = win.pages[key]
            headers = page.findChildren(PageHeader)
            assert len(headers) == 1, f"{key} 应只有一个统一页面标题"
            assert headers[0].title.text().strip()
    finally:
        win.close()


def test_ship_card_item_exposes_accessible_text(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidget, QListWidgetItem

    from starforge.app.widgets.ship_card import install_card_delegate, set_card_accessibility

    view = QListWidget()
    view.setAccessibleName("搜索结果")
    try:
        install_card_delegate(view, 110)
        item = QListWidgetItem("0xABC")
        set_card_accessibility(item, {"type_label": "战斗机", "ship_class": "S",
                                      "seed": "0xABC"})
        view.addItem(item)
        index = view.model().index(0, 0)
        assert "战斗机" in index.data(Qt.AccessibleTextRole)
        assert "S 级" in index.data(Qt.AccessibleTextRole)
        assert "种子：0xABC" in index.data(Qt.AccessibleDescriptionRole)
        assert view.accessibleName() == "搜索结果"
    finally:
        view.close()


def test_navigation_and_page_header_accessibility(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFrame

    from starforge.app.shell import NAV, SHORTCUT_INDEX, MainWindow
    from starforge.app.widgets.page_header import PageHeader

    win = MainWindow()
    try:
        rail = win.findChild(QFrame, "navRail")
        assert rail is not None and rail.accessibleName() == "主导航"
        for key, label in NAV:
            button = win._buttons[key]
            assert label in button.accessibleName()
            assert f"Ctrl+{SHORTCUT_INDEX[key]}" in button.toolTip()
            assert button.focusPolicy() == Qt.StrongFocus

        assert win.palette_btn.accessibleName() == "打开命令面板"
        assert "Ctrl+K" in win.palette_btn.toolTip()
        assert win.breadcrumb.accessibleName() == "当前页面：概览"
        assert "Ctrl+Shift+T" in win.dock.toggle.toolTip()

        headers = win.pages["home"].findChildren(PageHeader)
        assert headers and headers[0].accessibleName().startswith("概览")
        assert headers[0].title.accessibleName() == "页面标题"
    finally:
        win.close()
