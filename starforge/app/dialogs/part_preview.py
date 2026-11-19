"""选中部件的独立小窗 3D 预览。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from ...services import get_services
from ..widgets.ship_viewer import ShipViewer
from ..widgets.ui import muted
from ..widgets.worker import run as run_worker


class PartPreviewDialog(QDialog):
    def __init__(self, ship: str, part: str, parent=None, services=None):
        super().__init__(parent)
        self.svc = services or get_services()
        self.ship = str(ship or "")
        self.part = str(part or "")
        self.setWindowTitle(f"部件 3D 预览 · {self.part}")
        self.resize(620, 520)
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)
        title = QLabel(f"{self.part}  ·  {self.ship}")
        title.setStyleSheet("font-size:15px;font-weight:700;")
        root.addWidget(title)
        self.status = muted("正在生成部件 3D…")
        root.addWidget(self.status)

        self.viewer = ShipViewer()
        self.viewer.setMinimumHeight(360)
        root.addWidget(self.viewer, 1)
        self.fallback = QLabel()
        self.fallback.setAlignment(Qt.AlignCenter)
        self.fallback.setWordWrap(True)
        self.fallback.setMinimumHeight(360)
        self.fallback.hide()
        root.addWidget(self.fallback, 1)

        row = QHBoxLayout()
        for text, mode in (("等轴", "iso"), ("俯视", "top"),
                           ("侧视", "side"), ("正视", "front")):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, m=mode: self.viewer.set_view(m))
            row.addWidget(button)
        spin = QPushButton("自转")
        spin.setCheckable(True)
        spin.toggled.connect(self.viewer.set_spin)
        row.addWidget(spin)
        row.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        root.addLayout(row)

    def _load(self) -> None:
        if not self.part:
            self._failed("没有选中部件")
            return

        def done(mesh: dict) -> None:
            groups = (mesh or {}).get("groups") or {}
            if not groups:
                self._image_fallback("该部件没有可渲染的 3D 几何")
                return
            self.viewer.set_mesh(groups, {})
            self.status.setText("拖动旋转 · 滚轮缩放 · 双击复位")
            self.fallback.hide()
            self.viewer.show()

        def fail(msg: str) -> None:
            self._image_fallback(f"部件 3D 不可用：{msg}")

        run_worker(self.svc.part_mesh, done, fail, self.ship, self.part)

    def _image_fallback(self, text: str) -> None:
        self.viewer.hide()
        self.fallback.show()
        self.fallback.setText(text + "\n正在尝试静态预览…")

        def done(data: bytes | None) -> None:
            if not data:
                self.fallback.setText(text)
                return
            pix = QPixmap()
            pix.loadFromData(data, "PNG")
            if pix.isNull():
                self.fallback.setText(text)
                return
            self.fallback.setPixmap(pix)
            self.fallback.setToolTip(text)

        def fail(_msg: str) -> None:
            self.fallback.setText(text)

        run_worker(self.svc.part_icon, done, fail, self.ship, self.part, 320)

    def _failed(self, text: str) -> None:
        self.viewer.hide()
        self.fallback.show()
        self.fallback.setText(text)


__all__ = ["PartPreviewDialog"]
