"""通用 UI 小组件：卡片、标题、工具栏、缩略图。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(16, 14, 16, 14)
        self.v.setSpacing(8)
        if title:
            head = QVBoxLayout()
            head.setSpacing(2)
            t = QLabel(title)
            t.setStyleSheet("font-size:14px;font-weight:700;")
            self.title_label = t
            head.addWidget(t)
            if subtitle:
                s = QLabel(subtitle)
                s.setObjectName("muted")
                s.setWordWrap(True)
                head.addWidget(s)
            self.v.addLayout(head)

    def set_title(self, title: str) -> None:
        label = getattr(self, "title_label", None)
        if label is not None:
            label.setText(str(title or ""))

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


def placeholder_icon(text: str = "?", size: int = 28) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(QColor("#1a2231"))
    p = QPainter(pix)
    p.setPen(QColor("#8b97aa"))
    f = QFont()
    f.setPointSize(max(7, size // 3))
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignCenter, (text or "?")[:2])
    p.end()
    return QIcon(pix)


def muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab


def focus_first_input(widget: QWidget | None) -> QWidget | None:
    """聚焦页面里第一个可用的过滤/搜索控件。

    依次查找 QLineEdit、QComboBox、QTreeWidget，跳过禁用或隐藏的控件。
    返回被聚焦的控件；没有候选时返回 None，由调用方给出明确提示。
    """
    if widget is None:
        return None
    candidates: list[QWidget] = []
    if isinstance(widget, (QLineEdit, QComboBox, QTreeWidget)):
        candidates.append(widget)
    for cls in (QLineEdit, QComboBox, QTreeWidget):
        candidates.extend(widget.findChildren(cls))
    for child in candidates:
        try:
            if not child.isEnabled() or child.isHidden():
                continue
            if child.focusPolicy() == Qt.NoFocus:
                continue
            child.setFocus(Qt.ShortcutFocusReason)
            if isinstance(child, QLineEdit):
                child.selectAll()
            return child
        except RuntimeError:
            continue
    return None
