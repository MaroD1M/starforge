"""星图表格双击后的只读详情窗。

只做展示与复制，不触发传送或写入；关闭后不保留状态。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class GalaxyDetailDialog(QDialog):
    def __init__(self, title: str, body: str, *, glyphs: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("galaxyDetailDialog")
        self.setWindowTitle(f"详情 · {title or '未命名'}")
        self.setModal(False)
        self.resize(560, 380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        heading = QLabel(title or "未命名")
        heading.setObjectName("galaxyDetailTitle")
        heading.setWordWrap(True)
        heading.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(heading)

        if glyphs:
            glyph_label = QLabel(str(glyphs))
            glyph_label.setObjectName("muted")
            glyph_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            glyph_label.setToolTip("此行的门地址（符文串）")
            layout.addWidget(glyph_label)

        self.body = QPlainTextEdit(body or "")
        self.body.setObjectName("galaxyDetailBody")
        self.body.setReadOnly(True)
        self.body.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        layout.addWidget(self.body, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.copy_btn = QPushButton("复制全部")
        self.copy_btn.setObjectName("ghostButton")
        self.copy_btn.setToolTip("把标题与详情一起复制到剪贴板")
        self.copy_btn.clicked.connect(self._copy_all)
        actions.addWidget(self.copy_btn)
        actions.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setToolTip("关闭详情窗（不会执行任何操作）")
        close_btn.clicked.connect(self.close)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self._title = title or ""
        self._body = body or ""

    def _copy_all(self) -> None:
        text = self._title
        if self._body:
            text = f"{text}\n\n{self._body}" if text else self._body
        QGuiApplication.clipboard().setText(text)
        self.copy_btn.setText("已复制")
        self.copy_btn.setToolTip("已复制到剪贴板")


__all__ = ["GalaxyDetailDialog"]
