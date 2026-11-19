"""统一的写入确认入口。

``confirm_writes`` 默认开启；关闭后写操作仍受 ``settings.require_write`` 与
备份/读回/回滚保护，只是不再重复弹确认框。所有写对话框都走这里，避免每个
文件各写一套 QMessageBox 逻辑。
"""
from __future__ import annotations


def ask_write(parent, title: str, text: str) -> bool:
    from ...core import settings as settings_core

    if not bool(settings_core.current().confirm_writes):
        return True
    from PySide6.QtWidgets import QMessageBox

    return QMessageBox.warning(
        parent, title, text,
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
