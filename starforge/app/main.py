"""原生入口：``python -m starforge.app`` / ``starforge app``。"""
from __future__ import annotations

import faulthandler
import multiprocessing
import os
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon, QSurfaceFormat
from PySide6.QtWidgets import QApplication, QMessageBox

from ..core import log, paths
from .shell import MainWindow
from .theme import apply as apply_theme

log = log.get("app")
_CRASH_FILE = None


def _icon_path():
    from pathlib import Path
    import sys
    cands = []
    if getattr(sys, "_MEIPASS", ""):
        cands.append(Path(sys._MEIPASS) / "assets" / "starforge.png")
    cands.append(Path(__file__).resolve().parents[2] / "assets" / "starforge.png")
    exe = Path(sys.executable).resolve().parent
    cands += [exe / "assets" / "starforge.png", exe / "_internal" / "assets" / "starforge.png"]
    for c in cands:
        if c.exists():
            return c
    return None


def _enable_crash_log() -> None:
    """把原生崩溃（访问冲突/fail-fast）的栈写进 ~/.starforge/logs/。"""
    global _CRASH_FILE
    try:
        d = paths.app_home() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        _CRASH_FILE = open(d / "faulthandler.log", "a", buffering=1, encoding="utf-8")
        faulthandler.enable(file=_CRASH_FILE, all_threads=True)
        log.info("faulthandler 已启用：%s", d / "faulthandler.log")
    except Exception as e:                                    # noqa: BLE001
        log.warning("faulthandler 启用失败：%s", e)


def _excepthook(exc_type, exc, tb) -> None:
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    log.error("未捕获异常：%s", text)
    try:
        QMessageBox.critical(None, "starforge 出错了", f"{exc_type.__name__}: {exc}\n\n详细日志在 ~/.starforge/logs/")
    except Exception:                                        # noqa: BLE001
        pass


def run(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()                         # PyInstaller + 进程池必需
    _enable_crash_log()
    if os.environ.get("STARFORGE_SAFE") == "1":
        # 安全模式：软件 OpenGL，绕过部分显卡/远程桌面驱动崩溃
        QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
        log.info("安全模式：已请求软件 OpenGL")
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
    app.setApplicationDisplayName("Starforge · 无人深空情报台")
    icon = _icon_path()
    if icon:
        app.setWindowIcon(QIcon(str(icon)))
    apply_theme(app)
    sys.excepthook = _excepthook
    try:
        import numpy

        log.info("NumPy %s 可用：%s", numpy.__version__, numpy.__file__)
    except Exception as e:                                  # noqa: BLE001
        log.exception("NumPy 不可用：%s", e)
        QMessageBox.critical(
            None, "NumPy 不可用",
            "搜索 / 3D / 缩略图需要 NumPy，但当前进程加载 NumPy 失败：\n\n"
            f"{type(e).__name__}: {e}\n\n"
            "请重新解压完整安装包（不要覆盖旧目录），并把安装目录加入杀毒软件排除项。\n"
            "应用会继续启动，但相关功能会报错；诊断信息已写入 ~/.starforge/logs/。")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
