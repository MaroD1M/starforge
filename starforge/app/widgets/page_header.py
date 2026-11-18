"""统一页面标题区：标题 + 说明 + 右侧操作。"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 4)
        left = QVBoxLayout()
        left.setSpacing(2)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-size:18px;font-weight:700;")
        left.addWidget(self.title)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("muted")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        left.addWidget(self.subtitle)
        h.addLayout(left, 1)
        self.actions = QHBoxLayout()
        h.addLayout(self.actions)

    def set_title(self, title: str, subtitle: str = "") -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget)
        return widget
