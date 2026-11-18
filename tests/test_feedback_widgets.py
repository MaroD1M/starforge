"""统一交互反馈组件的离屏冒烟测试（不依赖真实游戏）。"""
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


def test_app_context_publishes_signals(qapp):
    from starforge.app.context import AppContext
    from starforge.services import get_services

    ctx = AppContext()
    got: dict[str, object] = {}
    ctx.healthChanged.connect(lambda d: got.setdefault("health", d))
    ctx.toastRequested.connect(lambda t: got.setdefault("toast", t))
    ctx.navigateRequested.connect(lambda p: got.setdefault("nav", p))

    assert ctx.services is get_services()
    ctx.publish_health({"data_ready": True})
    ctx.toast("测试提示")
    ctx.navigate("settings")

    assert got["health"] == {"data_ready": True}
    assert got["toast"] == "测试提示"
    assert got["nav"] == "settings"


def test_toast_host_shows_kinds_and_auto_dismisses(qapp):
    from PySide6.QtTest import QTest

    from starforge.app.widgets.feedback import ToastHost

    host = ToastHost()
    assert host.objectName() == "toastHost"
    assert host.accessibleName() == "通知浮层"

    cards = [host.toast(f"消息 {kind}", kind=kind, duration=0)
             for kind in ("info", "success", "warn", "error")]
    assert [c.property("kind") for c in cards] == ["info", "success", "warn", "error"]
    assert len(host._cards) == 4
    assert all(c.objectName() == "toastCard" and c.accessibleName() for c in cards)

    expiring = host.toast("即将消失", kind="success", duration=10)
    assert expiring in host._cards
    QTest.qWait(80)
    qapp.processEvents()
    assert expiring not in host._cards

    host.clear()
    assert host._cards == []


def test_empty_state_title_description_and_button(qapp):
    from starforge.app.widgets.feedback import EmptyState

    state = EmptyState(title="没有找到飞船", description="换个条件再试试",
                       icon="?", button_text="重新搜索")
    clicked: list[int] = []
    state.actionTriggered.connect(lambda: clicked.append(1))

    assert state.objectName() == "emptyState"
    assert state.title_label.text() == "没有找到飞船"
    assert state.description_label.text() == "换个条件再试试"
    assert state.button.text() == "重新搜索"
    assert state.accessibleName().startswith("空状态")

    state.button.click()
    assert clicked == [1]


def test_loading_overlay_text_and_visibility(qapp):
    from starforge.app.widgets.feedback import LoadingOverlay

    overlay = LoadingOverlay(text="加载中…")
    assert overlay.objectName() == "loadingOverlay"
    assert overlay.isHidden()

    overlay.start("正在扫描星系")
    assert not overlay.isHidden()
    assert overlay.label.text() == "正在扫描星系"

    overlay.set_text("快要完成了")
    assert overlay.label.text() == "快要完成了"

    overlay.stop()
    assert overlay.isHidden()


def test_error_banner_reason_and_retry(qapp):
    from starforge.app.widgets.feedback import ErrorBanner

    banner = ErrorBanner("无法连接游戏内代理")
    retried: list[int] = []
    banner.retryRequested.connect(lambda: retried.append(1))

    assert banner.objectName() == "errorBanner"
    assert banner.accessibleName() == "错误提示"
    assert banner.message.text() == "无法连接游戏内代理"

    banner.retry.click()
    assert retried == [1]

    banner.clear()
    assert banner.isHidden()
    banner.show_error("磁盘写入失败")
    assert not banner.isHidden()
    assert banner.message.text() == "磁盘写入失败"


def test_main_window_toast_integration(qapp):
    from starforge.app.shell import MainWindow

    win = MainWindow()
    try:
        assert win.context.services is win.svc
        win.toast("壳层集成正常", "success")
        assert win.toast_host._cards
        assert win.toast_host._cards[-1].message.text() == "壳层集成正常"
    finally:
        win.close()
