"""我的船队：存档 → 船只网格 → 3D 详情。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from ...services import get_services
from ..widgets.ship_viewer import ShipViewer
from ..widgets.ui import Card, icon_from_png, muted
from ..widgets.worker import run as run_worker


class FleetPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._loaded = False
        self._ships: list[dict] = []
        self._thumb_queue: list[QListWidgetItem] = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._next_thumb)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        left = Card("存档", "自动发现或手动选择")
        v = left.v
        self.path = QLineEdit()
        self.path.setPlaceholderText("save.hg")
        v.addWidget(self.path)
        row = QHBoxLayout()
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        self.load_btn = QPushButton("读取存档")
        self.load_btn.setObjectName("primary")
        self.load_btn.clicked.connect(self._load)
        row.addWidget(self.load_btn)
        v.addLayout(row)
        self.info = muted("选择存档后读取")
        v.addWidget(self.info)
        v.addStretch(1)
        backup = QPushButton("备份 / 恢复…")
        backup.setEnabled(False)
        backup.setToolTip("下一阶段接入")
        v.addWidget(backup)
        split.addWidget(left)

        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(8, 0, 8, 0)
        bar = QHBoxLayout()
        self.result_info = QLabel("还没有船")
        self.result_info.setObjectName("muted")
        bar.addWidget(self.result_info)
        bar.addStretch(1)
        self.view_mode = QComboBox()
        self.view_mode.addItem("卡片", "grid")
        self.view_mode.addItem("列表", "list")
        self.view_mode.currentIndexChanged.connect(self._apply_view_mode)
        bar.addWidget(self.view_mode)
        export = QPushButton("导出全部")
        export.setEnabled(False)
        bar.addWidget(export)
        mv.addLayout(bar)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setIconSize(QSize(160, 110))
        self.list.setSpacing(10)
        self.list.itemSelectionChanged.connect(self._select)
        mv.addWidget(self.list, 1)
        split.addWidget(mid)

        right = Card("Inspector")
        rv = right.v
        self.title = QLabel("未选择飞船")
        self.title.setStyleSheet("font-size:15px;font-weight:700;")
        rv.addWidget(self.title)
        self.viewer = ShipViewer()
        self.viewer.setMinimumHeight(300)
        rv.addWidget(self.viewer, 1)
        self.detail = muted("选中一艘船后在这里查看 3D、等级与属性。")
        rv.addWidget(self.detail)
        row2 = QHBoxLayout()
        copy = QPushButton("复制种子")
        copy.clicked.connect(self._copy_seed)
        row2.addWidget(copy)
        compare = QPushButton("加入对比")
        compare.setEnabled(False)
        row2.addWidget(compare)
        rv.addLayout(row2)
        split.addWidget(right)
        split.setSizes([300, 720, 420])

    # ---------------------------------------------------------------- 数据

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._auto()

    def _auto(self) -> None:
        if self.path.text().strip():
            self._load()
            return

        def done(res: dict) -> None:
            p = res.get("path") or ""
            if p:
                self.path.setText(p)
                self._load()
            else:
                self.info.setText("没有自动找到存档；请点「浏览…」选择 save.hg")

        def fail(msg: str) -> None:
            self.info.setText(f"没有自动找到存档：{msg}")

        run_worker(self.svc.default_save, done, fail)

    def _browse(self) -> None:
        start = self.path.text()
        if start and not Path(start).is_file():
            start = str(Path(start).parent) if Path(start).parent.exists() else ""
        p, _ = QFileDialog.getOpenFileName(self, "选择存档", start, "存档 (*.hg);;所有文件 (*)")
        if p:
            self.path.setText(p)
            self._load()

    def _load(self) -> None:
        self.load_btn.setEnabled(False)
        self.info.setText("读取存档…")
        self.list.clear()
        self._ships = []

        def done(res: dict) -> None:
            self._ships = res.get("ships") or []
            self.result_info.setText(f"{len(self._ships)} 艘  ·  {res.get('path')}")
            warns = res.get("warnings") or []
            self.info.setText(f"{len(self._ships)} 艘" + (f"  ·  {len(warns)} 条警告" if warns else ""))
            for s in self._ships:
                item = QListWidgetItem(s.get("seed") or "")
                item.setData(Qt.UserRole, s)
                item.setToolTip(f"{s.get('type_label') or s.get('type')}  {s.get('ship_class') or ''}")
                self.list.addItem(item)
                self._thumb_queue.append(item)
            self._thumb_timer.start(50)
            self.load_btn.setEnabled(True)

        def fail(msg: str) -> None:
            self.info.setText(f"读取失败：{msg}")
            self.load_btn.setEnabled(True)

        run_worker(self.svc.ships, done, fail, self.path.text().strip() or None)

    def _next_thumb(self) -> None:
        if not self._thumb_queue:
            return
        item = self._thumb_queue.pop(0)
        s = item.data(Qt.UserRole) or {}
        if not s.get("procedural", True):
            if self._thumb_queue:
                self._thumb_timer.start(20)
            return

        def done(data: bytes) -> None:
            try:
                item.setIcon(icon_from_png(data, 160))
            except Exception:                              # noqa: BLE001
                pass
            if self._thumb_queue:
                self._thumb_timer.start(30)

        def fail(_msg: str) -> None:
            if self._thumb_queue:
                self._thumb_timer.start(30)

        run_worker(self.svc.preview_png, done, fail,
                   s.get("type"), s.get("seed"), s.get("parts"), 240)

    def _apply_view_mode(self) -> None:
        grid = self.view_mode.currentData() == "grid"
        self.list.setViewMode(QListWidget.IconMode if grid else QListWidget.ListMode)
        self.list.setIconSize(QSize(160, 110) if grid else QSize(72, 50))

    # ---------------------------------------------------------------- Inspector

    def _select(self) -> None:
        items = self.list.selectedItems()
        if not items:
            return
        s = items[0].data(Qt.UserRole) or {}
        self.title.setText(f"{s.get('type_label') or s.get('type')}  {s.get('seed')}")
        self.detail.setText("生成 3D 几何…")

        def done(mesh: dict) -> None:
            self.viewer.set_mesh(mesh.get("groups") or {}, mesh.get("colours") or {})
            stats = s.get("stats") or {}
            st = "  ".join(f"{k}: {v}" for k, v in stats.items()) or "无属性数据"
            self.detail.setText(f"{st}\n{mesh.get('verts', 0):,} 顶点 / {mesh.get('tris', 0):,} 三角")

        def fail(msg: str) -> None:
            try:
                self.viewer.set_demo()
            except Exception:
                pass
            self.detail.setText(f"真实 3D 不可用（{msg}）")

        run_worker(self.svc.preview_mesh, done, fail,
                   s.get("type"), s.get("seed"), s.get("parts"))

    def _copy_seed(self) -> None:
        items = self.list.selectedItems()
        if items:
            s = items[0].data(Qt.UserRole) or {}
            QGuiApplication.clipboard().setText(s.get("seed") or "")
            self.info.setText("种子已复制")
