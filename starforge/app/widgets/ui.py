"""通用 UI 小组件：卡片、标题、工具栏、缩略图、布局辅助。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from ..theme import (
    CARD_PADDING,
    CARD_SPACING,
    SPACE_S,
    SPACE_XS,
    icon_size,
)


class ElidedLabel(QLabel):
    """单行文本标签：宽度不够时用省略号截断，完整内容保留在 tooltip。

    QLabel 原生只会硬裁切；这里按实际可用宽度绘制 elide，避免最小宽度
    把父布局撑大（例如页头标题、卡片标题）。
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self._sync_tooltip(text)
        self.setMinimumWidth(0)

    def _sync_tooltip(self, text: str) -> None:
        self.setToolTip(text or "")

    def setText(self, text: str) -> None:
        super().setText(text)
        self._sync_tooltip(text)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        rect = self.contentsRect()
        elided = self.fontMetrics().elidedText(
            self.text(), Qt.ElideRight, max(1, rect.width()))
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(rect, int(self.alignment()), elided)


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.v = QVBoxLayout(self)
        # 所有卡片共用同一套间距 token，页面不再各自写 16/14/12。
        self.v.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        self.v.setSpacing(CARD_SPACING)
        if title:
            head = QVBoxLayout()
            head.setSpacing(SPACE_XS)
            t = ElidedLabel(title)
            t.setObjectName("cardTitle")
            self.title_label = t
            head.addWidget(t)
            if subtitle:
                s = fit_label(QLabel(subtitle))
                s.setObjectName("muted")
                self.subtitle_label = s
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

    def set_spotlight(self, on: bool = True) -> None:
        """被“下一页/下一步”定位时短暂高亮，不改变卡片内容。"""
        if bool(self.property("spotlight")) == bool(on):
            return
        self.setProperty("spotlight", bool(on))
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.update()


def section(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, SPACE_S, 0, 0)
    h.setSpacing(SPACE_S)
    t = ElidedLabel(title)
    t.setObjectName("sectionTitle")
    t.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    h.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("sectionHint")
        s.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        s.setToolTip(subtitle)
        h.addWidget(s, 1)
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


# ---------------------------------------------------------------- 布局辅助
# 只新增函数：现有调用方无需改动，新代码用它们即可保证间距/边距一致。


def hbox(*widgets: QWidget, spacing: int = SPACE_S,
         margins: tuple[int, int, int, int] | None = None) -> QHBoxLayout:
    """水平布局：统一间距与边距，可一次传入多个控件。"""
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    if margins is not None:
        layout.setContentsMargins(*margins)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        else:
            layout.addWidget(widget)
    return layout


def vbox(*widgets: QWidget, spacing: int = SPACE_S,
         margins: tuple[int, int, int, int] | None = None) -> QVBoxLayout:
    """垂直布局：统一间距与边距，可一次传入多个控件。"""
    layout = QVBoxLayout()
    layout.setSpacing(spacing)
    if margins is not None:
        layout.setContentsMargins(*margins)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        else:
            layout.addWidget(widget)
    return layout


def grid(widgets, columns: int = 2, spacing: int = SPACE_S,
         margins: tuple[int, int, int, int] | None = None) -> QGridLayout:
    """网格布局：按列数自动换行，避免手写重复的 addWidget 坐标。"""
    layout = QGridLayout()
    layout.setSpacing(spacing)
    if margins is not None:
        layout.setContentsMargins(*margins)
    cols = max(1, int(columns or 1))
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, index // cols, index % cols)
    return layout


def fit_label(label: QLabel, max_width: int | None = None) -> QLabel:
    """让标签按可用宽度换行，而不是用长文本撑宽父布局。"""
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    if max_width is not None:
        label.setMaximumWidth(max_width)
    return label


def elide_label(text: str = "", max_width: int | None = None) -> ElidedLabel:
    """单行省略标签：完整文本放进 tooltip，避免硬裁切。"""
    label = ElidedLabel(text)
    if max_width is not None:
        label.setMaximumWidth(max_width)
    return label


def icon_px(widget: QWidget, base: int = 16) -> int:
    """按控件 DPI 计算图标像素尺寸，供自定义绘制使用。"""
    return icon_size(widget, base)


def _role_button(text: str, role: str, tooltip: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(role)
    if tooltip:
        button.setToolTip(tooltip)
        button.setStatusTip(tooltip)
    button.setFocusPolicy(Qt.StrongFocus)
    return button


def primary_button(text: str, tooltip: str = "") -> QPushButton:
    """页面的唯一主操作。主题里对应 ``QPushButton#primaryButton``。"""
    return _role_button(text, "primaryButton", tooltip)


def danger_button(text: str, tooltip: str = "") -> QPushButton:
    """高风险操作（写存档、取消任务等）。主题里对应 ``QPushButton#dangerButton``。"""
    return _role_button(text, "dangerButton", tooltip)


def ghost_button(text: str, tooltip: str = "") -> QPushButton:
    """次要/工具栏操作，不抢主操作的视觉权重。"""
    return _role_button(text, "ghostButton", tooltip)


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


__all__ = [
    "Card", "ElidedLabel", "danger_button", "elide_label", "fit_label",
    "focus_first_input", "ghost_button", "grid", "hbox", "icon_from_png",
    "icon_px", "muted", "placeholder_icon", "primary_button", "section", "vbox",
]
