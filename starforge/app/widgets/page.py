"""页面级布局约定：统一边距、间距和可记忆的分栏宽度。"""
from __future__ import annotations

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QSplitter, QVBoxLayout, QWidget

from ...core import paths

PAGE_MARGINS = (12, 12, 12, 12)
PAGE_SPACING = 8
SCROLL_MARGINS = (12, 12, 12, 16)


def page_layout(widget: QWidget, spacing: int = PAGE_SPACING) -> QVBoxLayout:
    """所有页面共用的根布局，避免各页边距/间距不一致。"""
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*PAGE_MARGINS)
    layout.setSpacing(spacing)
    return layout


def scroll_panel(widget: QWidget) -> QScrollArea:
    """把卡片/面板放进无边框滚动区，窗口较矮时不会把内部控件压扁。"""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(widget)
    return scroll


class PageSplitter(QSplitter):
    """带持久化的页面分栏。

    调用顺序：创建 → addWidget → ``set_default_sizes()`` → ``restore()``。
    首次启动使用默认宽度；拖动后写入 native-window.ini，下次启动恢复。
    """

    def __init__(self, name: str, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._name = str(name or "page")
        self._defaults: list[int] = []
        self._pending_restore = False
        self._settings = QSettings(str(paths.app_home() / "native-window.ini"),
                                   QSettings.IniFormat)
        self.setObjectName("pageSplitter")
        self.setChildrenCollapsible(False)
        self.setHandleWidth(8)
        self.splitterMoved.connect(self._save)

    def set_default_sizes(self, sizes: list[int]) -> None:
        self._defaults = [int(x) for x in sizes]

    def restore(self) -> None:
        # 页面首次显示前 QSplitter 宽度为 0，立即 setSizes 会被布局重新均分；
        # 因此延迟到 showEvent 后再应用一次。
        self._pending_restore = True
        if self.isVisible():
            self._apply_restore()

    def _apply_restore(self) -> None:
        state = self._settings.value(f"splitter/{self._name}")
        if state is not None:
            try:
                if self.restoreState(state):
                    return
            except Exception:                                # noqa: BLE001
                pass
        if self._defaults:
            self.setSizes(self._defaults)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending_restore:
            self._pending_restore = False
            QTimer.singleShot(0, self._apply_restore)

    def _save(self, *_args) -> None:
        try:
            self._settings.setValue(f"splitter/{self._name}", self.saveState())
            self._settings.sync()
        except Exception:                                    # noqa: BLE001
            pass
