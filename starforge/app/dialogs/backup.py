"""存档备份：列出当前存档的备份，并支持二次确认后恢复。"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ...services import get_services
from ..widgets.worker import run as run_worker

_STAMP = re.compile(r"\.(\d{8})-(\d{6})-\d+(?:-\d+)?\.bak\Z")


def format_size(size: int) -> str:
    """把字节数变成人类可读的大小。"""
    n = max(0, int(size or 0))
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


def backup_time(backup_path: str, mtime: int) -> str:
    """优先用备份文件名里的时间戳；旧/外来备份退回文件 mtime。"""
    m = _STAMP.search(os.path.basename(str(backup_path)))
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").strftime(
                "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(mtime or 0)))
    except (OverflowError, OSError, ValueError):
        return ""


def backup_rows(backups: list[dict] | None) -> list[dict]:
    """把服务层的备份记录整理成表格行（纯数据，便于测试）。"""
    rows = []
    for item in backups or []:
        path = str(item.get("path") or "")
        rows.append({
            "path": path,
            "name": os.path.basename(path),
            "bytes": int(item.get("bytes") or 0),
            "size": format_size(item.get("bytes") or 0),
            "mtime": int(item.get("mtime") or 0),
            "time": backup_time(path, item.get("mtime") or 0),
        })
    return rows


class BackupDialog(QDialog):
    """当前存档的备份列表；恢复前会二次确认并提示覆盖原存档。"""

    def __init__(self, save_path: str, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self.save_path = str(save_path or "")
        self.restored = False
        self._rows: list[dict] = []
        self.setWindowTitle("备份 / 恢复")
        self.resize(860, 500)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        title = QLabel("存档备份")
        title.setStyleSheet("font-size:15px;font-weight:700;")
        root.addWidget(title)

        self.path_label = QLabel(self.save_path or "没有选中存档")
        self.path_label.setObjectName("muted")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.path_label)

        self.info = QLabel("恢复会用所选备份覆盖当前存档；恢复前会自动留一份当前快照。")
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        root.addWidget(self.info)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["时间", "文件名", "大小", "路径"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_actions)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        buttons.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        self.restore_btn = QPushButton("恢复所选")
        self.restore_btn.setObjectName("primary")
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self._restore)
        buttons.addWidget(self.restore_btn)
        root.addLayout(buttons)

    def refresh(self) -> None:
        self.table.setRowCount(0)
        self._rows = []
        self._update_actions()
        if not self.save_path:
            self.info.setText("没有选中存档，无法列出备份。")
            return
        self.info.setText("读取备份…")

        def done(res: dict) -> None:
            self._rows = backup_rows(res.get("backups") or [])
            self._fill()
            if self._rows:
                self.info.setText(
                    f"{len(self._rows)} 个备份 · 恢复会用所选备份覆盖当前存档（恢复前自动留快照）")
            else:
                self.info.setText("没有找到备份；写回存档时也会自动生成备份。")

        def fail(msg: str) -> None:
            self.info.setText(f"读取备份失败：{msg}")

        run_worker(self.svc.backups, done, fail, self.save_path)

    def _fill(self) -> None:
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            values = [row["time"], row["name"], row["size"], row["path"]]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                if j == 0:
                    item.setData(Qt.UserRole, row)
                item.setToolTip(row["path"])
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        self._update_actions()

    def _selected_backup(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.data(Qt.UserRole) if item else None

    def _update_actions(self) -> None:
        self.restore_btn.setEnabled(self._selected_backup() is not None)

    def _restore(self) -> None:
        target = self._selected_backup()
        if target is None or not self.save_path:
            return
        answer = QMessageBox.warning(
            self, "确认恢复备份",
            f"将用以下备份覆盖当前存档：\n{target['name']}\n\n"
            f"当前存档：{self.save_path}\n\n"
            "当前存档会被覆盖（恢复前会自动留一份快照）。确定继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.restore_btn.setEnabled(False)
        self.info.setText("正在恢复…")

        def done(res: dict) -> None:
            self.restored = True
            self.info.setText(f"恢复成功 · 来源 {res.get('restored_from') or target['path']}")
            QMessageBox.information(
                self, "恢复成功",
                f"已从备份恢复当前存档。\n\n来源：{res.get('restored_from') or target['path']}"
                f"\n恢复前快照：{res.get('safety_copy') or ''}")
            self.accept()

        def fail(msg: str) -> None:
            self.restore_btn.setEnabled(True)
            self.info.setText(f"恢复失败：{msg}")
            QMessageBox.warning(self, "恢复失败", msg)

        run_worker(self.svc.restore, done, fail, self.save_path, target["path"], True)
