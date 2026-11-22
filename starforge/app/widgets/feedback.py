"""统一交互反馈控件：ToastHost / EmptyState / LoadingOverlay / ErrorBanner。

纯 Qt Widgets，不引入新依赖；配色沿用 ``theme.QSS`` 的深色体系。
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import SPACE_L, SPACE_M, SPACE_S

KIND_ALIASES = {
    "info": "info",
    "success": "success",
    "ok": "success",
    "warn": "warn",
    "warning": "warn",
    "error": "error",
    "danger": "error",
    "critical": "error",
}

_KIND_STYLE = {
    "info": ("提示", "#5ad7ff", "#0e1a24", "#1e4055"),
    "success": ("成功", "#a8e8c9", "#0e1c17", "#1d4a38"),
    "warn": ("注意", "#f0cd9a", "#1c1710", "#4a3a1c"),
    "error": ("错误", "#f3b6a7", "#1d1210", "#4d2a22"),
}


def _kind(kind: str) -> str:
    return KIND_ALIASES.get(str(kind or "info").lower(), "info")


class _ToastCard(QFrame):
    def __init__(self, text: str, kind: str = "info", parent: QWidget | None = None):
        super().__init__(parent)
        kind = _kind(kind)
        label, accent, background, border = _KIND_STYLE[kind]
        self.setObjectName("toastCard")
        self.setProperty("kind", kind)
        self.setAccessibleName(f"{label}：{text}")
        self.setStyleSheet(f"""
            QFrame#toastCard {{
                background: {background};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            QLabel#toastBadge {{ color: {accent}; font-weight: 700; }}
            QLabel#toastText {{ color: #e2e7f0; }}
        """)
        h = QHBoxLayout(self)
        h.setContentsMargins(SPACE_M, SPACE_S, SPACE_M, SPACE_S)
        h.setSpacing(SPACE_S)
        badge = QLabel(label)
        badge.setObjectName("toastBadge")
        badge.setAccessibleName(f"提示类型：{label}")
        badge.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        h.addWidget(badge)
        message = QLabel(text)
        message.setObjectName("toastText")
        message.setAccessibleName(str(text))
        message.setWordWrap(True)
        message.setMinimumWidth(0)
        message.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        h.addWidget(message, 1)
        self.badge = badge
        self.message = message

    def resizeEvent(self, event) -> None:                   # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        # 换行文本在高 DPI 下可能按旧宽度估算高度，导致最后一行被裁。
        try:
            need = self.message.heightForWidth(max(1, self.message.width()))
            if need > self.message.minimumHeight():
                self.message.setMinimumHeight(need)
        except Exception:                                    # noqa: BLE001
            pass


class ToastHost(QWidget):
    """右下角浮层；可同时显示多条提示，并按持续时间自动消失。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("toastHost")
        self.setAccessibleName("通知浮层")
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("QWidget#toastHost { background: transparent; }")
        self._cards: list[_ToastCard] = []
        self._duration = 3200
        self._max_cards = 5
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SPACE_S)
        self._layout.addStretch(1)
        if parent is not None:
            parent.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parentWidget() and event.type() in (QEvent.Resize, QEvent.Show):
            self._reposition()
        return super().eventFilter(obj, event)

    def toast(self, text: str, kind: str = "info", duration: int | None = None) -> _ToastCard:
        card = _ToastCard(str(text), kind, self)
        self._layout.addWidget(card)
        self._cards.append(card)
        while len(self._cards) > self._max_cards:
            self._remove(self._cards[0])
        delay = self._duration if duration is None else int(duration)
        if delay > 0:
            timer = QTimer(card)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda c=card: self._remove(c))
            timer.start(delay)
            card._timer = timer                            # 保持计时器生命周期
        self._relayout()
        return card

    def clear(self) -> None:
        for card in list(self._cards):
            self._remove(card)

    def _remove(self, card: _ToastCard) -> None:
        if card not in self._cards:
            return
        self._cards.remove(card)
        self._layout.removeWidget(card)
        card.hide()
        card.deleteLater()
        self._relayout()

    def _relayout(self) -> None:
        parent = self.parentWidget()
        width = 380
        if parent is not None:
            width = max(240, min(380, parent.width() - 36))
        self.setFixedWidth(width)
        self.adjustSize()
        self._reposition()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        margin = 18
        width = max(240, min(380, parent.width() - margin * 2))
        self.setFixedWidth(width)
        self.adjustSize()
        height = self.sizeHint().height()
        self.resize(width, height)
        self.move(max(margin, parent.width() - width - margin),
                  max(margin, parent.height() - height - margin))
        self.raise_()


class EmptyState(QFrame):
    """空状态占位：图标 + 标题 + 说明 + 可选操作按钮。"""

    actionTriggered = Signal()

    def __init__(self, title: str = "暂无内容", description: str = "", icon="",
                 button_text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("emptyState")
        self.setAccessibleName(f"空状态：{title or '暂无内容'}")
        self.setStyleSheet("""
            QFrame#emptyState {
                background: #0f141d;
                border: 1px solid #1e2432;
                border-radius: 12px;
            }
            QLabel#emptyIcon { color: #5ad7ff; font-size: 28px; }
            QLabel#emptyTitle { color: #e6ecf5; font-size: 15px; font-weight: 700; }
            QLabel#emptyDescription { color: #8b95a7; font-size: 11.5px; }
        """)
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE_L, SPACE_M, SPACE_L, SPACE_M)
        v.setSpacing(SPACE_S)
        v.setAlignment(Qt.AlignCenter)
        self.icon_label = QLabel()
        self.icon_label.setObjectName("emptyIcon")
        self.icon_label.setAccessibleName("空状态图标")
        self.icon_label.setAlignment(Qt.AlignCenter)
        if isinstance(icon, QIcon):
            self.icon_label.setPixmap(icon.pixmap(40, 40))
        else:
            self.icon_label.setText(str(icon or "◇"))
        v.addWidget(self.icon_label)
        self.title_label = QLabel(title or "暂无内容")
        self.title_label.setObjectName("emptyTitle")
        self.title_label.setAccessibleName("空状态标题")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        v.addWidget(self.title_label)
        self.description_label = QLabel(description)
        self.description_label.setObjectName("emptyDescription")
        self.description_label.setAccessibleName("空状态说明")
        self.description_label.setAlignment(Qt.AlignCenter)
        self.description_label.setWordWrap(True)
        self.description_label.setMinimumWidth(0)
        self.description_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.description_label.setVisible(bool(description))
        v.addWidget(self.description_label)
        # 先按初始宽度写入一个保守高度，避免父布局在首次排布时
        # 用 wordWrap 的单行最小高度把图标/说明压扁。
        for label in (self.title_label, self.description_label):
            label.setMinimumHeight(max(label.sizeHint().height(),
                                       label.heightForWidth(max(1, label.width()))))
        self.button = QPushButton(button_text or "操作")
        self.button.setObjectName("emptyAction")
        self.button.setAccessibleName(button_text or "操作")
        self.button.setVisible(bool(button_text))
        self.button.clicked.connect(self.actionTriggered)
        v.addWidget(self.button, 0, Qt.AlignCenter)

    def resizeEvent(self, event) -> None:       # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        # QLabel 的 wordWrap 在 150%/200% 缩放下可能按未受限宽度计算高度，
        # 导致标题/说明底部被裁掉；这里按实际宽度同步最小高度（可增可减）。
        changed = False
        for label in (self.title_label, self.description_label):
            if not label.isVisible():
                continue
            try:
                need = label.heightForWidth(max(1, label.width()))
                if need != label.minimumHeight():
                    label.setMinimumHeight(need)
                    changed = True
            except Exception:                                # noqa: BLE001
                pass
        if changed:
            # 换行高度变化后必须让父布局重新计算，否则卡片仍按旧高度裁切。
            self.updateGeometry()

    def _content_height(self) -> int:
        """按当前宽度计算内容所需高度（含图标、换行文本、间距与边距）。"""
        layout = self.layout()
        if layout is None:
            return 0
        margins = layout.contentsMargins()
        height = margins.top() + margins.bottom()
        first = True
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget is None or widget.isHidden():
                continue
            need = max(widget.minimumHeight(), widget.minimumSizeHint().height())
            if isinstance(widget, QLabel) and widget.wordWrap() and widget.width() > 0:
                need = max(need, widget.heightForWidth(widget.width()))
            if not first:
                height += layout.spacing()
            height += need
            first = False
        return height

    def minimumSizeHint(self) -> QSize:                      # noqa: N802 - Qt API
        base = super().minimumSizeHint()
        return QSize(base.width(), max(base.height(), self._content_height()))

    def sizeHint(self) -> QSize:                             # noqa: N802 - Qt API
        base = super().sizeHint()
        return QSize(base.width(), max(base.height(), self._content_height()))

    def set_action(self, text: str, callback=None) -> None:
        self.button.setText(text or "操作")
        self.button.setAccessibleName(text or "操作")
        self.button.setVisible(bool(text))
        if callback is not None:
            self.button.clicked.connect(callback)


class LoadingOverlay(QWidget):
    """半透明遮罩 + 加载文字，用于耗时任务期间阻止误操作。"""

    def __init__(self, parent: QWidget | None = None, text: str = "加载中…"):
        super().__init__(parent)
        self.setObjectName("loadingOverlay")
        self.setAccessibleName("加载遮罩")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            QWidget#loadingOverlay { background: rgba(10, 12, 17, 190); }
            QFrame#loadingCard {
                background: #0f141d;
                border: 1px solid #28303f;
                border-radius: 12px;
            }
            QLabel#loadingText { color: #e6ecf5; font-size: 13px; font-weight: 600; }
            QProgressBar#loadingBar {
                border: 1px solid #28303f;
                border-radius: 4px;
                background: #0c1119;
            }
            QProgressBar#loadingBar::chunk { background: #2f6fd0; border-radius: 3px; }
        """)
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE_L, SPACE_L, SPACE_L, SPACE_L)
        v.setAlignment(Qt.AlignCenter)
        card = QFrame()
        card.setObjectName("loadingCard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(SPACE_L, SPACE_M, SPACE_L, SPACE_M)
        cv.setSpacing(SPACE_S)
        self.label = QLabel(text)
        self.label.setObjectName("loadingText")
        self.label.setAccessibleName("加载提示")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(0)
        cv.addWidget(self.label)
        self.progress = QProgressBar()
        self.progress.setObjectName("loadingBar")
        self.progress.setAccessibleName("加载进度")
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(220)
        # 进度条只做视觉提示、不显示文字；固定高度避免被压缩成细线。
        self.progress.setFixedHeight(8)
        self.progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.progress.setTextVisible(False)
        cv.addWidget(self.progress, 0, Qt.AlignCenter)
        v.addWidget(card, 0, Qt.AlignCenter)
        self.hide()
        if parent is not None:
            parent.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self._cover_parent()
        return super().eventFilter(obj, event)

    def set_text(self, text: str) -> None:
        self.label.setText(str(text or "加载中…"))
        self.label.setAccessibleName(self.label.text())

    def start(self, text: str | None = None) -> None:
        if text is not None:
            self.set_text(text)
        self._cover_parent()
        self.show()
        self.raise_()

    def stop(self) -> None:
        self.hide()

    def show_overlay(self, text: str | None = None) -> None:
        self.start(text)

    def hide_overlay(self) -> None:
        self.stop()

    def _cover_parent(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())


class ErrorBanner(QFrame):
    """错误横幅：展示原因，并提供重试入口。"""

    retryRequested = Signal()

    def __init__(self, reason: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("errorBanner")
        self.setAccessibleName("错误提示")
        self.setStyleSheet("""
            QFrame#errorBanner {
                background: #1d1210;
                border: 1px solid #4d2a22;
                border-radius: 8px;
            }
            QLabel#errorMessage { color: #f3b6a7; }
        """)
        h = QHBoxLayout(self)
        h.setContentsMargins(SPACE_M, SPACE_S, SPACE_M, SPACE_S)
        h.setSpacing(SPACE_S)
        self.message = QLabel(str(reason or ""))
        self.message.setObjectName("errorMessage")
        self.message.setAccessibleName("错误原因")
        self.message.setWordWrap(True)
        self.message.setMinimumWidth(0)
        self.message.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        h.addWidget(self.message, 1)
        self.retry = QPushButton("重试")
        self.retry.setObjectName("retryButton")
        self.retry.setAccessibleName("重试")
        self.retry.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.retry.clicked.connect(self._retry)
        h.addWidget(self.retry)
        self._retry_callback = None
        self.set_reason(reason)

    def set_reason(self, reason: str) -> None:
        self.message.setText(str(reason or ""))
        self.message.setAccessibleName(self.message.text() or "错误原因")
        self.setVisible(bool(str(reason or "").strip()))

    def show_error(self, reason: str | None = None) -> None:
        if reason is not None:
            self.set_reason(reason)
        self.show()

    def clear(self) -> None:
        self.message.clear()
        self.hide()

    def set_retry_callback(self, callback) -> None:
        self._retry_callback = callback

    def _retry(self) -> None:
        self.retryRequested.emit()
        if callable(self._retry_callback):
            self._retry_callback()


__all__ = ["EmptyState", "ErrorBanner", "LoadingOverlay", "ToastHost"]
