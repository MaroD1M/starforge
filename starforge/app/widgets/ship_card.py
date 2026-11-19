"""飞船卡片 delegate：圆角卡片、缩略图、种子、类型/等级、悬停/选中态。"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import QListWidget, QStyle, QStyledItemDelegate


def card_accessibility(row: dict | None, fallback_seed: str = "",
                       in_compare: bool = False) -> tuple[str, str]:
    """卡片给屏幕阅读器的名称/描述：类型、等级、种子与命中部件。"""
    data = row or {}
    type_label = str(data.get("type_label") or data.get("type") or "未知类型")
    ship_class = str(data.get("ship_class") or "").strip()
    seed = str(data.get("seed") or fallback_seed or "")
    name = str(data.get("name") or "").strip()
    parts = [str(part) for part in (data.get("parts") or []) if str(part).strip()]

    bits = [type_label]
    if ship_class:
        bits.append(f"{ship_class} 级")
    if seed:
        bits.append(f"种子 {seed}")
    text = "，".join(bits)
    if name:
        text = f"{name}，{text}"

    desc = [f"类型：{type_label}"]
    if ship_class:
        desc.append(f"等级：{ship_class}")
    if seed:
        desc.append(f"种子：{seed}")
    if parts:
        desc.append("部件：" + " ".join(parts))
    if in_compare:
        desc.append("已加入对比")
    return text, "；".join(desc)


def set_card_accessibility(item, row: dict | None, fallback_seed: str = "",
                           in_compare: bool = False) -> None:
    """把可访问文本写到 item 的 AccessibleText/Description 角色。"""
    text, desc = card_accessibility(row, fallback_seed, in_compare)
    item.setData(Qt.AccessibleTextRole, text)
    item.setData(Qt.AccessibleDescriptionRole, desc)


class ShipCardDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, icon_size: int = 110):
        super().__init__(parent)
        self.icon_size = icon_size
        self.size = QSize(208, 172)

    def sizeHint(self, option, index):                      # noqa: N802 - Qt 回调
        return self.size

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802 - Qt 回调
        row = index.data(Qt.UserRole) or {}
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        rect = option.rect.adjusted(2, 2, -2, -2)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        bg = QColor("#14233a") if selected else (QColor("#111826") if hover else QColor("#0f141d"))
        border = QColor("#5ad7ff") if selected else (QColor("#3a4a66") if hover else QColor("#1e2633"))
        painter.setPen(QPen(border, 1.2 if selected else 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 10, 10)

        icon: QIcon = index.data(Qt.DecorationRole)
        pad = 10
        top = rect.top() + pad
        if icon is not None and not icon.isNull():
            pix = icon.pixmap(self.icon_size, self.icon_size)
            if not pix.isNull():
                x = rect.left() + (rect.width() - pix.width()) // 2
                painter.drawPixmap(x, top, pix)

        text_top = top + self.icon_size + 6
        seed = str(row.get("seed") or index.data(Qt.DisplayRole) or "")
        type_label = row.get("type_label") or row.get("type") or ""
        cls = row.get("ship_class") or ""
        if type_label or cls:
            type_label = f"{type_label}  {cls}".strip()

        painter.setPen(QColor("#e6ecf5"))
        f = QFont(option.font)
        f.setPointSizeF(max(8.5, f.pointSizeF()))
        f.setBold(True)
        painter.setFont(f)
        seed_rect = QRect(rect.left() + pad, text_top, rect.width() - pad * 2, 20)
        painter.drawText(seed_rect, Qt.AlignHCenter | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(seed, Qt.ElideMiddle, seed_rect.width()))

        if type_label:
            painter.setPen(QColor("#8b97aa"))
            f2 = QFont(option.font)
            f2.setPointSizeF(max(8, f2.pointSizeF() - 0.5))
            painter.setFont(f2)
            meta_rect = QRect(rect.left() + pad, text_top + 22, rect.width() - pad * 2, 18)
            painter.drawText(meta_rect, Qt.AlignHCenter | Qt.AlignVCenter,
                             painter.fontMetrics().elidedText(type_label, Qt.ElideRight, meta_rect.width()))
        painter.restore()


def install_card_delegate(view: QListWidget, icon_size: int = 110) -> ShipCardDelegate:
    view.setMouseTracking(True)
    view.setUniformItemSizes(True)
    view.setSpacing(6)
    view.setGridSize(QSize(212, 176))
    view.setIconSize(QSize(icon_size, icon_size))
    d = ShipCardDelegate(view, icon_size=icon_size)
    view.setItemDelegate(d)
    view.setStyleSheet("QListWidget::item { background: transparent; border: none; }")
    return d
