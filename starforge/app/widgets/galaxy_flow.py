"""星图页专用小部件：可换行布局 + 表格/空态叠放容器。

`FlowLayout` 让筛选控件在窄窗口下自动换行，而不是把 QLabel / QPushButton
压到比 sizeHint 更窄（那会直接截断中文）。`GalaxyTablePane` 让空态作为
表格上方的覆盖层，表格本身始终参与布局，避免空态在矮窗口里被压成一条。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QLayout,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


class GalaxyTable(QTableWidget):
    """列宽随视口等比收缩的表格：窄窗口不出现横向滚动条。

    传入的 widths 是"理想列宽"；视口更窄时按比例压缩（不低于 44px），
    视口更宽时保持理想列宽，由最后一列的 stretch 吃掉余量。
    """

    def __init__(self, rows: int = 0, columns: int = 1,
                 parent: QWidget | None = None):
        super().__init__(rows, columns, parent)
        self._base_widths: tuple[int, ...] = ()

    def set_base_widths(self, widths: tuple[int, ...] | list[int]) -> None:
        self._base_widths = tuple(int(w) for w in widths)
        self._fit_columns()

    def resizeEvent(self, event) -> None:               # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        self._fit_columns()

    def _fit_columns(self) -> None:
        widths = self._base_widths
        if not widths or self.viewport().width() <= 0:
            return
        count = min(len(widths), self.columnCount())
        total = sum(widths[:count])
        if total <= 0:
            return
        factor = min(1.0, self.viewport().width() / total)
        for column in range(count):
            self.setColumnWidth(column, max(44, int(widths[column] * factor)))


class GalaxyGlyphLabel(QLabel):
    """符文条标签：按可用宽度等比缩放，不把窄详情栏撑宽。"""

    def __init__(self, parent: QWidget | None = None, max_height: int = 40):
        super().__init__(parent)
        self._source: QPixmap | None = None
        self._max_height = int(max_height)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.setMinimumHeight(self._max_height)

    def set_glyph_pixmap(self, pix: QPixmap) -> None:      # noqa: N802 - 自定义 API
        self._source = None if pix.isNull() else QPixmap(pix)
        self._apply()

    def clear(self) -> None:
        self._source = None
        super().clear()

    def resizeEvent(self, event) -> None:                   # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        if self._source is None or self._source.isNull():
            return
        width = max(1, self.width() - 2)
        super().setPixmap(self._source.scaled(
            width, self._max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation))



class GalaxyFlowLayout(QLayout):
    """横向排列、空间不足时自动换行的布局。"""

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


class GalaxyFlowBar(QWidget):
    """把 FlowLayout 包成 QWidget：让父级 QVBoxLayout 能查询 heightForWidth。

    直接把自绘 FlowLayout 塞进 QVBoxLayout 时，部分平台只按 sizeHint（单行）
    分配高度，换行后的控件会画到下一行控件上；包一层 widget 可以稳定换行。
    """

    def __init__(self, parent: QWidget | None = None, h_spacing: int = 6,
                 v_spacing: int = 6):
        super().__init__(parent)
        self.flow = GalaxyFlowLayout(self, 0, h_spacing, v_spacing)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setMinimumHeight(0)

    def addWidget(self, widget: QWidget) -> None:       # noqa: N802 - 与 QLayout 同名
        self.flow.addWidget(widget)

    def hasHeightForWidth(self) -> bool:                # noqa: N802 - Qt 回调
        return True

    def heightForWidth(self, width: int) -> int:        # noqa: N802 - Qt 回调
        return self.flow.heightForWidth(width)

    def sizeHint(self) -> QSize:                        # noqa: N802 - Qt 回调
        width = max(240, self.width() or 600)
        return QSize(width, self.flow.heightForWidth(width) + 8)

    def resizeEvent(self, event) -> None:               # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        # 高度按当前宽度算出来的行数固定下来，随后请父布局重排一次，
        # 否则相邻行可能还停留在旧的行高上（会叠 3~7px）。
        need = self.flow.heightForWidth(max(1, self.width())) + 2
        if need > 0 and self.height() != need:
            self.setFixedHeight(need)
        QTimer.singleShot(0, self._relayout_parent)

    def _relayout_parent(self) -> None:
        parent = self.parentWidget()
        layout = parent.layout() if parent is not None else None
        if layout is not None:
            layout.invalidate()
            layout.activate()


class GalaxyTablePane(QWidget):
    """表格 + 空态覆盖层；空态不再和表格抢布局高度。"""

    def __init__(self, table: QWidget, empty: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.table = table
        self.empty = empty
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(table)
        empty.setParent(self)
        empty.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        # 结果区通常只剩下几十像素高；收紧空态内边距，避免图标/标题/说明叠在一起。
        inner = empty.layout()
        if inner is not None:
            inner.setContentsMargins(10, 6, 10, 6)
            inner.setSpacing(4)
        empty.hide()

    def set_empty(self, visible: bool) -> None:
        if visible:
            self.table.show()
            self.empty.show()
            self._sync_empty()
            self.empty.raise_()
        else:
            self.empty.hide()
            self.table.show()

    def _sync_empty(self) -> None:
        if self.empty.parentWidget() is self:
            self.empty.setGeometry(self.rect())
            # 矮结果区优先保留标题；图标和说明按可用高度收起，绝不叠字。
            height = self.height()
            icon = getattr(self.empty, "icon_label", None)
            desc = getattr(self.empty, "description_label", None)
            if icon is not None:
                icon.setVisible(height >= 110)
            if desc is not None:
                desc.setVisible(height >= 72 and bool(desc.text()))
            title = getattr(self.empty, "title_label", None)
            if title is not None:
                text = title.text()
                if desc is not None and desc.text():
                    text += "\n" + desc.text()
                self.empty.setToolTip(text)

    def resizeEvent(self, event) -> None:       # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        self._sync_empty()
