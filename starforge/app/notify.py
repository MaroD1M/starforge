"""全局轻量通知：页面无需持有 MainWindow 引用。"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication


def toast(text: str, kind: str = "info", duration: int | None = None) -> None:
    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        fn = getattr(w, "toast", None)
        if callable(fn):
            try:
                fn(text, kind=kind, duration=duration)
                return
            except Exception:                              # noqa: BLE001
                continue


def success(text: str) -> None:
    toast(text, "success")


def warn(text: str) -> None:
    toast(text, "warn")


def error(text: str) -> None:
    toast(text, "error")
