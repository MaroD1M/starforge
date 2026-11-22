"""交互骨架组件的最小契约：步骤状态、筛选 chips、筛选面板、详情关闭。"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_task_flow_states(qapp):
    from starforge.app.widgets.ux import TaskFlow

    flow = TaskFlow(["选条件", "搜索", "送进游戏"])
    assert [item[0].property("state") for item in flow._items] == [
        "active", "pending", "pending"]
    flow.set_active(1, done=(0,))
    assert [item[0].property("state") for item in flow._items] == [
        "done", "active", "pending"]
    assert flow._items[0][1].text() == "✓"
    flow.set_active(2, done=(0, 1))
    assert [item[1].text() for item in flow._items] == ["✓", "✓", "3"]


def test_filter_chips_emit_removed_and_hide_when_empty(qapp):
    from starforge.app.widgets.ux import FilterChips

    chips = FilterChips()
    seen: list[str] = []
    chips.removed.connect(seen.append)
    chips.set_filters([("biome", "群系 茂盛"), ("named", "已命名")])
    # 直接按文本找 chip，避免依赖内部布局顺序。
    from PySide6.QtWidgets import QPushButton
    labels = [b.text() for b in chips.findChildren(QPushButton)]
    assert any("群系 茂盛" in text for text in labels)
    target = next(b for b in chips.findChildren(QPushButton) if "群系" in b.text())
    target.click()
    assert seen == ["biome"]

    chips.set_filters([])
    assert chips.isHidden() is True


def test_filter_panel_toggles(qapp):
    from PySide6.QtWidgets import QLabel

    from starforge.app.widgets.ux import FilterPanel

    panel = FilterPanel()
    assert panel.isHidden() is True
    panel.body.addWidget(QLabel("关键词"))
    panel.toggle()
    assert panel.isHidden() is False
    panel.toggle()
    assert panel.isHidden() is True


def test_detail_panel_close_signal(qapp):
    from starforge.app.widgets.ux import DetailPanel

    panel = DetailPanel("详情")
    seen: list[bool] = []
    panel.closed.connect(lambda: seen.append(True))
    panel.close_btn.click()
    assert seen == [True]
    panel.set_title("Rosalia Prime")
    assert panel.title_label.text() == "Rosalia Prime"
