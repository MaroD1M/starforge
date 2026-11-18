"""Ctrl+K 命令面板。"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QVBoxLayout)


class CommandPalette(QDialog):
    def __init__(self, actions: list[tuple[str, Callable[[], None]]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("命令")
        self.setModal(True)
        self.resize(520, 360)
        self._actions = actions
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        hint = QLabel("输入命令，Enter 执行，Esc 关闭")
        hint.setObjectName("muted")
        v.addWidget(hint)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("例如：找船 / 游戏内 / 设置 / 刷新")
        self.edit.textChanged.connect(self._filter)
        self.edit.returnPressed.connect(self._run_current)
        v.addWidget(self.edit)
        self.list = QListWidget()
        self.list.itemActivated.connect(lambda _i: self._run_current())
        v.addWidget(self.list)
        self._refresh()
        self.edit.setFocus()

    def _refresh(self) -> None:
        needle = self.edit.text().strip().lower()
        self.list.clear()
        for label, fn in self._actions:
            if needle and needle not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, fn)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _filter(self, _text: str) -> None:
        self._refresh()

    def _run_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        fn = item.data(Qt.UserRole)
        self.accept()
        if callable(fn):
            fn()
