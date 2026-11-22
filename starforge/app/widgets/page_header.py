"""统一页面标题区：标题 + 说明 + 右侧操作。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ..theme import SPACE_S, SPACE_XS
from .ui import ElidedLabel


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        # 页头本身允许被压缩；标题用省略号、说明用换行，避免把主内容挤窄。
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, SPACE_XS)
        h.setSpacing(SPACE_S)
        left = QVBoxLayout()
        left.setSpacing(SPACE_XS)
        self.title = ElidedLabel(title)
        self.title.setObjectName("pageTitle")
        self.title.setAccessibleName("页面标题")
        left.addWidget(self.title)
        self.subtitle = ElidedLabel(subtitle)
        self.subtitle.setObjectName("pageSubtitle")
        self.subtitle.setAccessibleName("页面说明")
        self.subtitle.setToolTip(subtitle)
        self.subtitle.setVisible(bool(subtitle))
        self.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        left.addWidget(self.subtitle)
        h.addLayout(left, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(SPACE_S)
        self.actions.setAlignment(Qt.AlignTop)
        h.addLayout(self.actions)

    def set_title(self, title: str, subtitle: str = "") -> None:
        self.title.setText(title)
        self.title.setToolTip(str(title or ""))
        self.subtitle.setText(subtitle)
        self.subtitle.setToolTip(str(subtitle or ""))
        self.subtitle.setVisible(bool(subtitle))

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget)
        return widget
