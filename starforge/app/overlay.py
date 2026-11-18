"""原生 Qt 符文置顶浮窗（替代 tkinter）。"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


def panel_spec(glyphs: str, tile: int = 64, gap: int = 8) -> dict:
    digits = [c for c in str(glyphs).upper() if c.strip()]
    if not digits:
        raise ValueError("空符文串")
    width = len(digits) * tile + (len(digits) - 1) * gap + 24
    height = tile + 56
    return {"digits": digits, "width": width, "height": height, "tile": tile, "gap": gap}


def _set_click_through(win_id: int) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x80000
        WS_EX_TRANSPARENT = 0x20
        WS_EX_NOACTIVATE = 0x8000000
        WS_EX_TOOLWINDOW = 0x80
        u = ctypes.windll.user32
        style = u.GetWindowLongW(win_id, GWL_EXSTYLE)
        u.SetWindowLongW(win_id, GWL_EXSTYLE,
                         style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    except Exception:                                      # noqa: BLE001
        pass


class GlyphOverlay(QWidget):
    def __init__(self, png: bytes, text: str, alpha: float = 0.94,
                 click_through: bool = False, scale: float = 1.0):
        super().__init__()
        self._drag = False
        self._last = QPoint()
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        if click_through:
            flags |= Qt.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowOpacity(max(0.3, min(1.0, alpha)))

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(2)
        img = QPixmap()
        img.loadFromData(png, "PNG")
        if scale != 1.0 and not img.isNull():
            img = img.scaled(max(1, int(img.width() * scale)), max(1, int(img.height() * scale)),
                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pic = QLabel()
        pic.setPixmap(img)
        pic.setAlignment(Qt.AlignCenter)
        root.addWidget(pic)
        hint = QLabel(f"{text}    Esc 关闭 · 拖动可移动")
        hint.setStyleSheet("color:#8b97aa;font-size:11px;")
        hint.setAlignment(Qt.AlignCenter)
        root.addWidget(hint)
        self.setStyleSheet("background:#05070c;border:1px solid #28303f;border-radius:10px;")
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(max(0, (screen.width() - self.width()) // 2), 40)
        if click_through:
            QTimer.singleShot(0, lambda: _set_click_through(int(self.winId())))

    def keyPressEvent(self, e) -> None:                    # noqa: N802 - Qt 回调
        if e.key() == Qt.Key_Escape:
            self.close()

    def mousePressEvent(self, e) -> None:                  # noqa: N802 - Qt 回调
        if e.button() == Qt.LeftButton:
            self._drag = True
            self._last = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e) -> None:                   # noqa: N802 - Qt 回调
        if self._drag:
            p = e.globalPosition().toPoint()
            self.move(self.pos() + p - self._last)
            self._last = p

    def mouseReleaseEvent(self, e) -> None:                # noqa: N802 - Qt 回调
        self._drag = False


def show(glyphs: str, png: bytes, *, alpha: float = 0.94, click_through: bool = False,
         scale: float = 1.0) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    win = GlyphOverlay(png, glyphs, alpha=alpha, click_through=click_through, scale=scale)
    win.show()
    app.exec()
