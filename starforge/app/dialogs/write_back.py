"""写回存档：同型槽位 → 备份/副本 → 读回校验。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ...services import get_services
from ..widgets.worker import run as run_worker


from ..dialogs.confirm import ask_write

class WriteBackDialog(QDialog):
    def __init__(self, source: dict, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self.source = source
        self.setWindowTitle("写回存档")
        self.resize(720, 500)
        self._build_ui()
        self._load_default()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        title = QLabel(f"把 {self.source.get('type_label') or self.source.get('type')} "
                       f"{self.source.get('seed')} 写入同型船槽")
        title.setStyleSheet("font-size:15px;font-weight:700;")
        root.addWidget(title)

        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("save.hg")
        row.addWidget(self.path, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        load = QPushButton("加载目标")
        load.clicked.connect(self._load)
        row.addWidget(load)
        root.addLayout(row)

        self.info = QLabel("只显示与源船同型的程序化船槽；跨型不可移植。")
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        root.addWidget(self.info)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["槽位", "类型", "等级", "种子", "名称"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table, 1)

        opts = QHBoxLayout()
        self.copy = QCheckBox("写入副本（save.edited.hg），不动原档")
        opts.addWidget(self.copy)
        opts.addStretch(1)
        root.addLayout(opts)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.ok = QPushButton("确认写回")
        self.ok.setObjectName("primary")
        self.ok.clicked.connect(self._apply)
        buttons.addWidget(self.ok)
        root.addLayout(buttons)

    def _load_default(self) -> None:
        def done(res: dict) -> None:
            p = res.get("path") or ""
            if p:
                self.path.setText(p)
                self._load()

        run_worker(self.svc.default_save, done, lambda m: self.info.setText(f"没有默认存档：{m}"))

    def _browse(self) -> None:
        start = self.path.text()
        if start and not Path(start).is_file():
            start = str(Path(start).parent) if Path(start).parent.exists() else ""
        p, _ = QFileDialog.getOpenFileName(self, "选择存档", start, "存档 (*.hg);;所有文件 (*)")
        if p:
            self.path.setText(p)
            self._load()

    def _load(self) -> None:
        self.info.setText("读取存档…")
        p = self.path.text().strip() or None

        def done(res: dict) -> None:
            ships = res.get("ships") or []
            typ = self.source.get("type")
            targets = [s for s in ships if s.get("type") == typ and s.get("procedural", True)]
            self.table.setRowCount(len(targets))
            for i, s in enumerate(targets):
                vals = [str(s.get("slot")), s.get("type_label") or s.get("type") or "",
                        s.get("ship_class") or "", s.get("seed") or "", s.get("name") or ""]
                for j, v in enumerate(vals):
                    item = QTableWidgetItem(v)
                    item.setData(Qt.UserRole, s)
                    self.table.setItem(i, j, item)
            self.table.resizeColumnsToContents()
            self.info.setText(f"{res.get('path')} · 同型槽位 {len(targets)} 个")

        def fail(msg: str) -> None:
            self.info.setText(f"读取失败：{msg}")

        run_worker(self.svc.ships, done, fail, p)

    def _apply(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "写回", "先选一个目标槽位")
            return
        item = self.table.item(rows[0].row(), 0)
        target = item.data(Qt.UserRole) if item else None
        if not target:
            return
        if not ask_write(self, "确认写入",
                f"将把 {self.source.get('seed')} 写入槽位 {target.get('slot')}。\n"
                "会先备份，写后读回校验；失败自动回滚。继续？",):
            return
        self.ok.setEnabled(False)
        self.info.setText("写入中…")

        def done(res: dict) -> None:
            self.info.setText(f"写入成功 · 备份 {res.get('backup')} · 读回 {res.get('after')}")
            QMessageBox.information(self, "写入成功",
                                    f"槽位 {res.get('slot')} 已写入。\n备份：{res.get('backup')}")
            self.accept()

        def fail(msg: str) -> None:
            self.ok.setEnabled(True)
            self.info.setText(f"写入失败：{msg}")
            QMessageBox.warning(self, "写入失败", msg)

        run_worker(self.svc.apply_seed, done, fail,
                   self.path.text().strip(), int(target.get("slot")), self.source,
                   True, self.copy.isChecked())
