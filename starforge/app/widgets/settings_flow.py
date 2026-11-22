"""设置页的折叠分组：标题 + 状态 chip + 一行摘要，默认收起。

用户反馈「设置一屏全是说明，找不到要改哪一项」，所以设置页按问题分成
路径 / 安全 / 运行时 / 诊断四组；每组只露标题和状态，展开后再看细节。
外壳的「设置 → 安全」等入口仍通过 ``Card.title_label`` 定位卡片，
因此这里继续沿用 ``ui.Card``，只是把标题行换成可点击的折叠头。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import CARD_SPACING, SPACE_S, SPACE_XS
from .ui import Card, ElidedLabel, muted


def _refresh(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


class FoldSection(Card):
    """可折叠的分组卡片（设置页分组 / 联动页高级区共用）。

    - 标题行：展开按钮 + 标题 + 状态 chip；
    - 收起时显示一行摘要（长文本省略，完整内容放 tooltip）；
    - 默认收起；被外壳「下一步/子导航」定位（``set_spotlight``）时自动展开，
      这样旧入口 ``anchor="安全与性能"`` 仍能把用户带到正确分组。
    """

    toggled = Signal(bool)

    def __init__(self, title: str = "", subtitle: str = "", summary: str = "",
                 expanded: bool = False, parent: QWidget | None = None):
        super().__init__("", "", parent)
        self._title = str(title or "")
        self._expanded = False
        self._subtitle = str(subtitle or "")

        head = QHBoxLayout()
        head.setSpacing(SPACE_S)
        self.toggle = QPushButton("展开")
        self.toggle.setObjectName("ghostButton")
        self.toggle.setFocusPolicy(Qt.StrongFocus)
        self.toggle.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.toggle.clicked.connect(self.toggle_expanded)
        head.addWidget(self.toggle, 0, Qt.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(SPACE_XS)
        self.title_label = ElidedLabel(self._title)
        self.title_label.setObjectName("cardTitle")
        self.title_label.setAccessibleName(f"分组：{self._title}")
        text.addWidget(self.title_label)
        if self._subtitle:
            self.subtitle_label = muted(self._subtitle)
            text.addWidget(self.subtitle_label)
        head.addLayout(text, 1)

        self.chip = QLabel("")
        self.chip.setObjectName("chip")
        self.chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.chip.setVisible(False)
        head.addWidget(self.chip, 0, Qt.AlignTop)
        self.v.addLayout(head)

        self.summary_label = ElidedLabel(summary)
        self.summary_label.setObjectName("muted")
        self.summary_label.setMinimumWidth(0)
        self.summary_label.setVisible(bool(summary))
        self.v.addWidget(self.summary_label)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(CARD_SPACING)
        self.body.setVisible(False)
        self.v.addWidget(self.body)

        self.toggle.setAccessibleName(f"展开分组：{self._title}")
        self.toggle.setToolTip(f"展开/收起：{self._title}")
        self.set_expanded(bool(expanded), emit=False)

    # ---------------------------------------------------------------- 状态

    def set_chip(self, text: str, state: str = "") -> None:
        text = str(text or "")
        self.chip.setText(text)
        self.chip.setVisible(bool(text))
        if state in ("ok", "warn", "bad"):
            self.chip.setProperty("state", state)
        else:
            self.chip.setProperty("state", "")
        self.chip.setToolTip(text)
        _refresh(self.chip)

    def set_summary(self, text: str) -> None:
        self.summary_label.setText(str(text or ""))
        self.summary_label.setVisible(bool(text) and not self._expanded)

    def set_subtitle(self, text: str) -> None:
        label = getattr(self, "subtitle_label", None)
        if label is not None:
            label.setText(str(text or ""))

    # ---------------------------------------------------------------- 折叠

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, emit: bool = True) -> None:
        expanded = bool(expanded)
        changed = expanded != self._expanded
        self._expanded = expanded
        self.body.setVisible(expanded)
        self.summary_label.setVisible(
            bool(self.summary_label.text()) and not expanded)
        self._sync_toggle_text()
        if emit and changed:
            self.toggled.emit(expanded)
        if changed:
            self.updateGeometry()

    def toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    def _sync_toggle_text(self) -> None:
        self.toggle.setText("收起" if self._expanded else "展开")
        action = "收起" if self._expanded else "展开"
        self.toggle.setAccessibleName(f"{action}分组：{self._title}")
        self.toggle.setToolTip(f"{action}分组：{self._title}")

    # ---------------------------------------------------------------- 添加

    def add_body(self, widget: QWidget) -> QWidget:
        self.body_layout.addWidget(widget)
        return widget

    def add_body_layout(self, layout) -> None:
        self.body_layout.addLayout(layout)

    # ---------------------------------------------------------------- 定位

    def set_spotlight(self, on: bool = True) -> None:
        """外壳定位到本组时先展开，避免“高亮了却看不到内容”。"""
        if on and not self._expanded:
            self.set_expanded(True)
        super().set_spotlight(on)


__all__ = ["FoldSection"]
