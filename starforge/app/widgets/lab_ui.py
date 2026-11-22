"""飞船实验室 / 设计器专用的小组件：按实际宽度换行的标签、统一尺寸的按钮。

两页的栏宽会被 QSplitter 拖动或窗口最小化挤压；普通 ``QLabel`` 虽然设了
``wordWrap``，但 ``minimumSizeHint`` 仍按单行计算，父布局会把它压到只显示
一两行（文字底部被裁掉）。``WrapLabel`` 把最小高度改成"当前宽度下的实际
高度"，并在尺寸变化时重新上报几何。
"""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QWidget

BUTTON_MIN_HEIGHT = 30


class WrapLabel(QLabel):
    """自动换行、且高度不会被布局裁掉的 QLabel。"""

    _wrap_label = True

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

    def resizeEvent(self, event) -> None:                # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        self.updateGeometry()

    def _extra_height(self) -> int:
        """QSS 的 padding/border 不在 heightForWidth 里，需要额外补上。"""
        if self.height() > 0:
            return max(0, self.height() - self.contentsRect().height())
        margins = self.contentsMargins()
        return max(0, margins.top() + margins.bottom() + self.frameWidth() * 2)

    def _extra_width(self) -> int:
        if self.width() > 0:
            return max(0, self.width() - self.contentsRect().width())
        margins = self.contentsMargins()
        return max(0, margins.left() + margins.right() + self.frameWidth() * 2)

    def heightForWidth(self, width: int) -> int:         # noqa: N802 - Qt 回调
        # QLabel 把传入宽度当成文本可用宽度；但布局传的是控件总宽度，
        # 不扣掉 QSS padding 会少算一行，底部文字被裁。
        text_width = max(1, width - self._extra_width())
        height = super().heightForWidth(text_width)
        if height > 0 and self.wordWrap():
            return height + self._extra_height()
        return height

    def minimumSizeHint(self) -> QSize:                  # noqa: N802 - Qt 回调
        hint = super().minimumSizeHint()
        width = self.width()
        if self.wordWrap() and width > 0:
            need = self.heightForWidth(width)
            if need > 0:
                return QSize(0, need)
        return hint

    def sizeHint(self) -> QSize:                         # noqa: N802 - Qt 回调
        hint = super().sizeHint()
        width = self.width()
        if self.wordWrap() and width > 0:
            need = self.heightForWidth(width)
            if need > 0:
                return QSize(hint.width(), max(need, hint.height()))
        return hint


def fixed_height(button: QPushButton) -> QPushButton:
    """按钮统一最小高度（只设下限，跟随字体/高 DPI 自然增高）。"""
    button.setMinimumHeight(BUTTON_MIN_HEIGHT)
    return button


def stretch_button(button: QPushButton) -> QPushButton:
    """放进网格的按钮：横向可拉伸、纵向保持自然高度。"""
    fixed_height(button)
    button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return button


__all__ = ["BUTTON_MIN_HEIGHT", "WrapLabel", "fixed_height", "stretch_button"]
