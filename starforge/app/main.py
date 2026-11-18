"""原生入口：``python -m starforge.app`` / ``starforge app``。"""
from __future__ import annotations

import multiprocessing
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QSurfaceFormat
from PySide6.QtWidgets import QApplication, QMessageBox

from ..core import log
from .shell import MainWindow
from .theme import apply as apply_theme

log = log.get("app")


def _excepthook(exc_type, exc, tb) -> None:
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    log.error("未捕获异常：%s", text)
    try:
        QMessageBox.critical(None, "starforge 出错了", f"{exc_type.__name__}: {exc}\n\n详细日志在 ~/.starforge/logs/")
    except Exception:                                        # noqa: BLE001
        pass


def run(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()                         # PyInstaller + 进程池必需
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    fmt.setVersion(2, 1)
    fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(list(sys.argv if argv is None else argv))
    app.setApplicationName("starforge")
    app.setOrganizationName("starforge")
    app.setApplicationDisplayName("无人深空 · 飞船猎人")
    apply_theme(app)
    sys.excepthook = _excepthook
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
