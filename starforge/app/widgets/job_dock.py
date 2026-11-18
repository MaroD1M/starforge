"""底部任务/日志 Dock：显示 services.jobs() 里的任务，可折叠。"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from ...services import get_services


class JobDock(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self.setObjectName("jobDock")
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 6, 12, 8)
        head = QHBoxLayout()
        title = QLabel("任务")
        title.setObjectName("muted")
        head.addWidget(title)
        self.summary = QLabel("空闲")
        self.summary.setObjectName("muted")
        head.addWidget(self.summary)
        head.addStretch(1)
        self.toggle = QPushButton("收起")
        self.toggle.setFixedHeight(22)
        self.toggle.clicked.connect(self.toggle_body)
        head.addWidget(self.toggle)
        v.addLayout(head)
        self.list = QListWidget()
        self.list.setMaximumHeight(110)
        self.list.setMinimumHeight(70)
        v.addWidget(self.list)

    def toggle_body(self) -> None:
        visible = not self.list.isVisible()
        self.list.setVisible(visible)
        self.toggle.setText("收起" if visible else "展开")

    def refresh(self) -> None:
        try:
            jobs = (self.svc.jobs().get("jobs") or [])[:8]
        except Exception as e:                              # noqa: BLE001
            self.summary.setText(f"任务读取失败：{type(e).__name__}")
            return
        running = [j for j in jobs if j.get("status") == "running"]
        self.summary.setText(f"{len(running)} 个进行中" if running else "空闲")
        self.list.clear()
        for j in jobs:
            p = j.get("progress") or {}
            bits = [j.get("kind") or "任务", j.get("status") or ""]
            if p.get("tested"):
                bits.append(f"{p['tested']:,} seeds")
            if p.get("rate"):
                bits.append(f"{p['rate']/1e6:.1f} M/s")
            if p.get("found") is not None:
                bits.append(f"命中 {p['found']}")
            if p.get("eta"):
                bits.append(f"ETA {p['eta']:.0f}s")
            item = QListWidgetItem("  ·  ".join(bits))
            item.setData(Qt.UserRole, j.get("id"))
            self.list.addItem(item)
