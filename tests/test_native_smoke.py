"""原生壳冒烟：没有 PySide6 的机器跳过。"""
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


def test_native_main_window_builds(qapp):
    from starforge.app.shell import MainWindow

    win = MainWindow()
    try:
        assert win.windowTitle()
        assert set(win.pages) == {"home", "search", "mine", "systems", "live", "settings"}
        assert win.stack.count() == 6
        win.goto("settings")
        assert win.stack.currentWidget() is win.pages["settings"]
    finally:
        win.close()


def test_ship_viewer_demo_mesh(qapp):
    from starforge.app.widgets.ship_viewer import ShipViewer

    viewer = ShipViewer()
    viewer.set_demo()
    assert viewer._groups
    assert viewer._radius > 0.5
