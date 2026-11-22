"""船队页专用小部件：按钮/徽标在窄详情栏里自动换行，避免文字被挤断。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy, QWidget


class FleetFlowLayout(QLayout):
    """横向排列、空间不足时换行的布局（与详情栏里的按钮组配套）。"""

    def __init__(self, parent: QWidget | None = None, margin: int = 0,
                 h_spacing: int = 6, v_spacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item) -> None:            # noqa: N802 - Qt 回调
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):               # noqa: N802 - Qt 回调
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):               # noqa: N802 - Qt 回调
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):              # noqa: N802 - Qt 回调
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:        # noqa: N802 - Qt 回调
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt 回调
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:   # noqa: N802 - Qt 回调
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:                  # noqa: N802 - Qt 回调
        return self.minimumSize()

    def minimumSize(self) -> QSize:               # noqa: N802 - Qt 回调
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(),
                             -margins.right(), -margins.bottom())
        x, y = area.x(), area.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > area.right() and line_height > 0:
                x = area.x()
                y += line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()

class FleetFlowBar(QWidget):
    """把 FlowLayout 包成 QWidget，保证父布局按换行后的高度分配空间。"""

    def __init__(self, parent: QWidget | None = None, h_spacing: int = 6,
                 v_spacing: int = 6):
        super().__init__(parent)
        self.flow = FleetFlowLayout(self, 0, h_spacing, v_spacing)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setMinimumHeight(0)

    def addWidget(self, widget: QWidget) -> None:       # noqa: N802 - 与 QLayout 同名
        self.flow.addWidget(widget)

    def hasHeightForWidth(self) -> bool:                # noqa: N802 - Qt 回调
        return True

    def heightForWidth(self, width: int) -> int:        # noqa: N802 - Qt 回调
        return self.flow.heightForWidth(width)

    def sizeHint(self) -> QSize:                        # noqa: N802 - Qt 回调
        width = max(180, self.width() or 400)
        return QSize(width, self.flow.heightForWidth(width) + 2)

    def resizeEvent(self, event) -> None:               # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        need = self.flow.heightForWidth(max(1, self.width())) + 2
        if need and self.minimumHeight() != need:
            self.setMinimumHeight(need)
        self.updateGeometry()
