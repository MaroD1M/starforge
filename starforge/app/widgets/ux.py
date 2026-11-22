"""交互骨架组件：把“先做什么、下一步做什么”变成可见的结构。

设计参照（只借交互，不复制代码）：
- IBM Carbon：一个页面一个主操作、渐进披露、数据表优先；
- GitHub Primer / Shopify Polaris：筛选 chips、空态给下一步；
- Material 3：步骤/分段/状态层级；
- Fluent 2 / Vercel Geist：8px 网格、紧凑桌面密度、少装饰。

这些组件只负责布局与状态，不碰业务逻辑，页面可以逐步替换。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import SPACE_M, SPACE_S, SPACE_XS


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


class TaskFlow(QWidget):
    """一行任务步骤：① 选条件 → ② 看结果 → ③ 执行。

    只表达“现在在哪一步”，不阻止用户点任何控件；高风险操作仍在页面里确认。
    """

    def __init__(self, steps: list[str], parent=None):
        super().__init__(parent)
        self.setObjectName("uxFlow")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACE_XS)
        self._items: list[tuple[QFrame, QLabel, QLabel]] = []
        for index, text in enumerate(steps):
            if index:
                arrow = QLabel("›")
                arrow.setObjectName("uxFlowArrow")
                h.addWidget(arrow)
            wrap = QFrame()
            wrap.setObjectName("uxFlowStep")
            wrap.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            wl = QHBoxLayout(wrap)
            wl.setContentsMargins(8, 2, 10, 2)
            wl.setSpacing(6)
            number = QLabel(str(index + 1))
            number.setObjectName("uxFlowNum")
            number.setFixedWidth(14)
            number.setAlignment(Qt.AlignCenter)
            label = QLabel(text)
            label.setObjectName("uxFlowLabel")
            wl.addWidget(number)
            wl.addWidget(label)
            h.addWidget(wrap)
            self._items.append((wrap, number, label))
        h.addStretch(1)
        self.set_active(0)

    def set_active(self, index: int, done: tuple[int, ...] | list[int] = ()) -> None:
        done_set = {int(i) for i in (done or ())}
        for i, (wrap, number, _label) in enumerate(self._items):
            if i in done_set:
                state = "done"
            elif i == index:
                state = "active"
            else:
                state = "pending"
            wrap.setProperty("state", state)
            number.setText("✓" if state == "done" else str(i + 1))
            _repolish(wrap)
            _repolish(number)


class FilterChips(QWidget):
    """已生效筛选的可删除 chips；为空时自动隐藏。"""

    removed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("uxChips")
        self._h = QHBoxLayout(self)
        self._h.setContentsMargins(0, 0, 0, 0)
        self._h.setSpacing(SPACE_XS)
        self._h.addStretch(1)
        self.hide()

    def set_filters(self, items: list[tuple[str, str]]) -> None:
        while self._h.count():
            item = self._h.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._h.addStretch(1)
        rows = [(k, v) for k, v in (items or []) if str(v or "").strip()]
        if not rows:
            self.hide()
            return
        lead = QLabel("筛选：")
        lead.setObjectName("muted")
        self._h.insertWidget(0, lead)
        for key, label in rows:
            chip = QPushButton(f"{label}  ×")
            chip.setObjectName("uxChip")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setToolTip(f"移除筛选：{label}")
            chip.setAccessibleName(f"移除筛选：{label}")
            chip.clicked.connect(lambda _c=False, k=key: self.removed.emit(str(k)))
            self._h.insertWidget(self._h.count() - 1, chip)
        self.show()


class FilterPanel(QFrame):
    """渐进披露的筛选面板：默认收起，点「筛选」才展开。"""

    def __init__(self, toggle_text: str = "筛选", parent=None):
        super().__init__(parent)
        self.setObjectName("uxFilterPanel")
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE_M, SPACE_S, SPACE_M, SPACE_S)
        v.setSpacing(SPACE_S)
        self.body = v
        self.setVisible(False)

    def toggle(self) -> None:
        self.setVisible(not self.isVisible())
        if self.isVisible():
            self.raise_()


class DetailPanel(QFrame):
    """按需出现的详情面板；关闭时把空间还给结果区。"""

    closed = Signal()

    def __init__(self, title: str = "详情", parent=None):
        super().__init__(parent)
        self.setObjectName("uxDrawer")
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE_M, SPACE_S, SPACE_M, SPACE_M)
        v.setSpacing(SPACE_S)
        head = QHBoxLayout()
        head.setSpacing(SPACE_S)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("uxDrawerTitle")
        self.title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        head.addWidget(self.title_label, 1)
        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("uxIconButton")
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setToolTip("关闭详情（Esc）")
        self.close_btn.setAccessibleName("关闭详情")
        self.close_btn.clicked.connect(self.closed.emit)
        head.addWidget(self.close_btn)
        v.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(SPACE_S)
        v.addLayout(self.body, 1)

    def set_title(self, text: str) -> None:
        self.title_label.setText(str(text or "详情"))
