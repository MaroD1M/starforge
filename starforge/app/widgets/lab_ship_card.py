"""搜船结果卡片（实验室专用）：只画缩略图、种子、等级与 1 个关键属性。

共享的 ``ship_card`` 会同时画类型与等级，在窄栏里信息偏多；实验室页改成
“一屏一个主操作”后，结果卡只保留挑船时真正要看的三行：

    缩略图
    0x992C8A47F60A6B00
    等级 S · 3 部件

类型、部件清单、涂装距离等详细内容放在详情区或 tooltip，不再挤在卡片上。
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import QListWidget, QStyle, QStyledItemDelegate


def grade_text(row: dict | None) -> str:
    """等级（S/A/B/C）；搜索结果没有存档等级时用「—」占位。"""
    data = row or {}
    value = str(data.get("ship_class") or data.get("class") or "").strip().upper()
    return value or "—"


def key_attribute(row: dict | None) -> str:
    """只挑一个关键属性：涂装距离 > 命中部件数 > 属性条数。"""
    data = row or {}
    match = data.get("look_match")
    if isinstance(match, dict) and match:
        values = []
        for value in match.values():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
        if values:
            return f"涂装 Δ{min(values):.2f}"
    parts = [str(part) for part in (data.get("parts") or []) if str(part).strip()]
    if parts:
        return f"{len(parts)} 部件"
    stats = data.get("stats")
    if isinstance(stats, dict) and stats:
        return f"{len(stats)} 项属性"
    return "—"


def card_facts(row: dict | None) -> tuple[str, str, str]:
    """返回 (种子, 等级, 关键属性)，方便测试与 delegate 共用同一套规则。"""
    data = row or {}
    seed = str(data.get("seed") or "")
    return seed, grade_text(data), key_attribute(data)


class LabShipCardDelegate(QStyledItemDelegate):
    """三行卡片：图标 / 种子 / 「等级 · 关键属性」。"""

    def __init__(self, parent=None, icon_size: int = 92):
        super().__init__(parent)
        self.icon_size = int(icon_size)
        self.size = QSize(168, 148)

    def sizeHint(self, option, index):                       # noqa: N802 - Qt 回调
        return self.size

    def paint(self, painter: QPainter, option, index) -> None:   # noqa: C901 - 绘制
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
        pad = 6
        top = rect.top() + pad
        if icon is not None and not icon.isNull():
            pix = icon.pixmap(self.icon_size, self.icon_size)
            if not pix.isNull():
                x = rect.left() + (rect.width() - pix.width()) // 2
                painter.drawPixmap(x, top, pix)

        seed, grade, attr = card_facts(row)
        if not seed:
            seed = str(index.data(Qt.DisplayRole) or "")

        text_top = top + self.icon_size + 4
        painter.setPen(QColor("#e6ecf5"))
        f = QFont(option.font)
        # 种子必须完整可读：字号比正文字小一档，靠 tooltip 补类型/部件详情。
        f.setPointSizeF(max(7.8, f.pointSizeF() - 1.5))
        f.setBold(True)
        painter.setFont(f)
        seed_rect = QRect(rect.left() + pad, text_top,
                          rect.width() - pad * 2, 19)
        painter.drawText(
            seed_rect, Qt.AlignHCenter | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(seed, Qt.ElideMiddle, seed_rect.width()))

        painter.setPen(QColor("#8b97aa"))
        f2 = QFont(option.font)
        f2.setPointSizeF(max(7.5, f2.pointSizeF() - 1.2))
        painter.setFont(f2)
        meta_rect = QRect(rect.left() + pad, text_top + 20,
                          rect.width() - pad * 2, 17)
        meta = f"等级 {grade} · {attr}"
        painter.drawText(
            meta_rect, Qt.AlignHCenter | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(meta, Qt.ElideRight, meta_rect.width()))
        painter.restore()


def install_lab_card_delegate(view: QListWidget, icon_size: int = 92) -> LabShipCardDelegate:
    view.setMouseTracking(True)
    view.setUniformItemSizes(True)
    view.setSpacing(8)
    view.setGridSize(QSize(172, 156))
    view.setIconSize(QSize(icon_size, icon_size))
    delegate = LabShipCardDelegate(view, icon_size=icon_size)
    view.setItemDelegate(delegate)
    view.setStyleSheet("QListWidget::item { background: transparent; border: none; }")
    return delegate


__all__ = ["LabShipCardDelegate", "card_facts", "grade_text", "install_lab_card_delegate",
           "key_attribute"]
