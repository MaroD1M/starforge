"""通用 UI 小组件：卡片、标题、工具栏、缩略图。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(16, 14, 16, 14)
        self.v.setSpacing(8)
        if title:
            head = QHBoxLayout()
            t = QLabel(title)
            t.setStyleSheet("font-size:14px;font-weight:700;")
            head.addWidget(t)
            if subtitle:
                s = QLabel(subtitle)
                s.setObjectName("muted")
                head.addWidget(s)
            head.addStretch(1)
            self.v.addLayout(head)

    def add(self, widget: QWidget) -> QWidget:
        self.v.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self.v.addLayout(layout)


def section(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 8, 0, 0)
    t = QLabel(title)
    t.setStyleSheet("font-size:15px;font-weight:700;")
    h.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("muted")
        h.addWidget(s)
    h.addStretch(1)
    return w


def icon_from_png(data: bytes, size: int = 96) -> QIcon:
    pix = QPixmap()
    if data:
        pix.loadFromData(data, "PNG")
    if pix.isNull():
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
    return QIcon(pix)


def muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab
