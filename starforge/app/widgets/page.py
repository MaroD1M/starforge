"""页面级布局约定：统一边距、间距和可记忆的分栏宽度。"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core import paths
from ..theme import PAGE_GAP, PAGE_MARGIN, SCROLL_MARGIN

PAGE_MARGINS = PAGE_MARGIN
PAGE_SPACING = PAGE_GAP
SCROLL_MARGINS = SCROLL_MARGIN


def page_layout(widget: QWidget, spacing: int = PAGE_SPACING) -> QVBoxLayout:
    """所有页面共用的根布局，避免各页边距/间距不一致。"""
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*PAGE_MARGINS)
    layout.setSpacing(spacing)
    return layout


def scroll_panel(widget: QWidget) -> QScrollArea:
    """把卡片/面板放进无边框滚动区，窗口较矮时不会把内部控件压扁。

    - 内容随视口自适应宽度（``setWidgetResizable``）；
    - 横向/纵向都按需出现滚动条，宁可滚动也不静默裁掉内容；
    - 内容控件不强制固定高度，避免高 DPI 下文字被切底。
    """
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    scroll.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
    scroll.viewport().setAutoFillBackground(False)
    widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    widget.setMinimumWidth(0)
    scroll.setWidget(widget)
    return scroll


class PageSplitter(QSplitter):
    """带持久化的页面分栏。

    调用顺序：创建 → addWidget → ``set_default_sizes()`` → ``restore()``。
    首次启动使用默认宽度；拖动后写入 native-window.ini，下次启动恢复。
    恢复出的分栏如果小于控件最小尺寸（例如换了大字体或窗口变窄），
    会自动从空间富余的分栏里借像素，避免内容被相邻分栏盖住。
    """

    def __init__(self, name: str, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._name = str(name or "page")
        self._defaults: list[int] = []
        self._pending_restore = False
        self._clamping = False
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

    def _minimum_extent(self, index: int) -> int:
        widget = self.widget(index)
        if widget is None:
            return 0
        hint = widget.minimumSizeHint()
        if self.orientation() == Qt.Horizontal:
            return max(widget.minimumWidth(), hint.width())
        return max(widget.minimumHeight(), hint.height())

    def _clamp_sizes(self) -> None:
        """把低于最小尺寸的分栏补足，从空间富余的分栏里扣回。"""
        count = self.count()
        if count <= 0 or self._clamping:
            return
        sizes = self.sizes()
        total = sum(sizes)
        if total <= 0:
            return
        mins = [self._minimum_extent(i) for i in range(count)]
        if sum(mins) > total:
            # 可用空间连最小尺寸都放不下：留给滚动区/页面处理，硬塞会溢出。
            return
        adjusted = [max(sizes[i], mins[i]) for i in range(count)]
        overflow = sum(adjusted) - total
        for i in sorted(range(count), key=lambda k: adjusted[k] - mins[k], reverse=True):
            if overflow <= 0:
                break
            take = min(overflow, adjusted[i] - mins[i])
            adjusted[i] -= take
            overflow -= take
        if adjusted != sizes:
            self._clamping = True
            try:
                self.setSizes(adjusted)
            finally:
                self._clamping = False

    def _apply_restore(self) -> None:
        state = self._settings.value(f"splitter/{self._name}")
        restored = False
        if state is not None:
            try:
                restored = bool(self.restoreState(state))
            except Exception:                                # noqa: BLE001
                restored = False
        if not restored and self._defaults:
            self.setSizes(self._defaults)
        self._clamp_sizes()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending_restore:
            self._pending_restore = False
            QTimer.singleShot(0, self._apply_restore)

    def resizeEvent(self, event) -> None:                   # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        # 页面内容（按钮文字/标签）会在运行期改变最小宽度；
        # 分栏尺寸变化后，等布局稳定再校正一次，避免内容被相邻分栏裁掉。
        if not self._pending_restore:
            QTimer.singleShot(0, self._clamp_sizes)

    def _save(self, *_args) -> None:
        if self._clamping:
            return
        try:
            self._settings.setValue(f"splitter/{self._name}", self.saveState())
            self._settings.sync()
        except Exception:                                    # noqa: BLE001
            pass
