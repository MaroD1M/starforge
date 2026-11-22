"""统一页面标题区：标题 + 说明 + 右侧操作。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..theme import SPACE_S, SPACE_XS
from .ui import ElidedLabel, fit_label


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        # 页头本身允许被压缩；标题用省略号、说明用换行，避免把主内容挤窄。
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, SPACE_XS)
        h.setSpacing(SPACE_S)
        left = QVBoxLayout()
        left.setSpacing(SPACE_XS)
        self.title = ElidedLabel(title)
        self.title.setObjectName("pageTitle")
        left.addWidget(self.title)
        self.subtitle = fit_label(QLabel(subtitle))
        self.subtitle.setObjectName("muted")
        self.subtitle.setVisible(bool(subtitle))
        left.addWidget(self.subtitle)
        h.addLayout(left, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(SPACE_S)
        self.actions.setAlignment(Qt.AlignTop)
        h.addLayout(self.actions)

    def set_title(self, title: str, subtitle: str = "") -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget)
        return widget

    def resizeEvent(self, event) -> None:                   # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        # 高 DPI / 窄窗口下 QLabel 的 wordWrap 可能按旧宽度估算高度，
        # 这里按实际宽度补足，防止说明文字底部被裁掉。
        try:
            need = self.subtitle.heightForWidth(max(1, self.subtitle.width()))
            if need > self.subtitle.minimumHeight():
                self.subtitle.setMinimumHeight(need)
        except Exception:                                    # noqa: BLE001
            pass
