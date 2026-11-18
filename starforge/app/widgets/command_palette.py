"""Ctrl+K 命令面板：按“页面 / 操作”分组，支持键盘选择与即时筛选。"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

ACTION_ROLE = Qt.UserRole
HEADER_ROLE = Qt.UserRole + 1
LABEL_ROLE = Qt.UserRole + 2
EMPTY_TEXT = "没有匹配命令"
GROUP_ORDER = ["页面", "操作"]


class _CommandList(QListWidget):
    """上下键跳过分组标题；Enter 由 itemActivated 执行当前命令。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAccessibleName("命令列表")
        self.setToolTip("上下键选择命令，Enter 执行")

    def keyPressEvent(self, event) -> None:                  # noqa: N802 - Qt 回调
        if event.key() in (Qt.Key_Down, Qt.Key_Up):
            self.move_selection(1 if event.key() == Qt.Key_Down else -1)
            event.accept()
            return
        super().keyPressEvent(event)

    def move_selection(self, delta: int) -> None:
        count = self.count()
        if count <= 0:
            return
        row = self.currentRow()
        if row < 0:
            row = -1 if delta > 0 else 0
        row = (row + delta) % count
        for _ in range(count):
            item = self.item(row)
            if item is not None and callable(item.data(ACTION_ROLE)):
                self.setCurrentRow(row)
                return
            row = (row + delta) % count


class CommandPalette(QDialog):
    def __init__(self, actions: list[tuple], parent=None):
        super().__init__(parent)
        self.setWindowTitle("命令面板")
        self.setAccessibleName("命令面板")
        self.setToolTip("搜索并执行页面跳转或操作命令（Ctrl+K）")
        self.setModal(True)
        self.resize(520, 360)
        self._actions = self._normalize(actions)
        self._visible_actions = 0

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        hint = QLabel("输入命令筛选；↑/↓ 选择，Enter 执行，Esc 关闭")
        hint.setObjectName("muted")
        hint.setAccessibleName("命令面板提示")
        hint.setToolTip("输入关键词筛选命令；上下键选择，Enter 执行，Esc 关闭")
        v.addWidget(hint)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText("例如：找船 / 游戏内 / 设置 / 刷新")
        self.edit.setAccessibleName("命令搜索框")
        self.edit.setToolTip("输入关键词筛选命令；↑/↓ 选择，Enter 执行，Esc 关闭")
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(self._filter)
        self.edit.returnPressed.connect(self._run_current)
        self.edit.installEventFilter(self)
        v.addWidget(self.edit)

        self.list = _CommandList()
        self.list.itemActivated.connect(lambda _i: self._run_current())
        v.addWidget(self.list, 1)
        QWidget.setTabOrder(self.edit, self.list)

        self._refresh()
        self.edit.setFocus(Qt.PopupFocusReason)

    @staticmethod
    def _normalize(actions: list[tuple]) -> list[tuple[str, str, Callable[[], None]]]:
        """兼容 (label, fn) 与 (group, label, fn) 两种写法。"""
        out: list[tuple[str, str, Callable[[], None]]] = []
        for action in actions:
            group, label, fn = "操作", "", None
            if len(action) == 2:
                label, fn = action
            elif len(action) >= 3:
                first, second, third = action[:3]
                if callable(third):
                    group, label, fn = str(first or "操作"), str(second), third
                elif callable(second):
                    label, fn, group = str(first), second, str(third or "操作")
            if label and callable(fn):
                out.append((group or "操作", label, fn))
        return out

    def eventFilter(self, obj, event) -> bool:              # noqa: N802 - Qt 回调
        if obj is self.edit and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Down:
                self.list.move_selection(1)
                return True
            if key == Qt.Key_Up:
                self.list.move_selection(-1)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._run_current()
                return True
            if key == Qt.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    def _grouped(self) -> dict[str, list[tuple[str, Callable[[], None]]]]:
        groups: dict[str, list[tuple[str, Callable[[], None]]]] = {}
        for group, label, fn in self._actions:
            groups.setdefault(group, []).append((label, fn))
        return groups

    def _refresh(self) -> None:
        needle = self.edit.text().strip().lower()
        self.list.clear()
        self._visible_actions = 0
        groups = self._grouped()
        ordered = [g for g in GROUP_ORDER if g in groups]
        ordered.extend(g for g in groups if g not in GROUP_ORDER)
        for group in ordered:
            matches = [
                (label, fn) for label, fn in groups[group]
                if not needle or needle in label.lower() or needle in group.lower()
            ]
            if not matches:
                continue
            header = QListWidgetItem(group)
            header.setFlags(Qt.ItemIsEnabled)
            header.setData(HEADER_ROLE, group)
            header.setForeground(QColor("#8b95a7"))
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setToolTip(f"{group}命令")
            self.list.addItem(header)
            for label, fn in matches:
                item = QListWidgetItem(label)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setData(ACTION_ROLE, fn)
                item.setData(LABEL_ROLE, label)
                item.setToolTip(f"{group}：{label}")
                item.setData(Qt.AccessibleTextRole, f"{group}：{label}")
                self.list.addItem(item)
                self._visible_actions += 1

        if not self._visible_actions:
            empty = QListWidgetItem(EMPTY_TEXT)
            empty.setFlags(Qt.ItemIsEnabled)
            empty.setData(HEADER_ROLE, EMPTY_TEXT)
            empty.setForeground(QColor("#8b95a7"))
            empty.setTextAlignment(Qt.AlignCenter)
            self.list.addItem(empty)
            self.list.setCurrentRow(-1)
            return
        self.list.move_selection(1)

    def _filter(self, _text: str) -> None:
        self._refresh()

    def _run_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        fn = item.data(ACTION_ROLE)
        if not callable(fn):
            return
        self.accept()
        fn()
