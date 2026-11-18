"""我的船页：读存档 → 表格 → 原生 3D / 写回入口。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...services import get_services
from ..widgets.ship_viewer import ShipViewer
from ..widgets.worker import run as run_worker


class MinePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._ships: list[dict] = []
        self._build_ui()
        self._auto_path()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 12, 12)
        lv.addWidget(QLabel("存档"))
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("自动检测到的 save.hg")
        row.addWidget(self.path, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        lv.addLayout(row)
        self.load_btn = QPushButton("读取")
        self.load_btn.setObjectName("primary")
        self.load_btn.clicked.connect(self._load)
        lv.addWidget(self.load_btn)
        self.status = QLabel("选择存档后读取")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        lv.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["槽位", "类型", "等级", "种子", "名称"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._select)
        lv.addWidget(self.table, 1)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 12, 12, 12)
        self.title = QLabel("选中一艘船")
        rv.addWidget(self.title)
        self.viewer = ShipViewer()
        rv.addWidget(self.viewer, 1)
        self.detail = QLabel("这里会显示 3D 与属性。")
        self.detail.setObjectName("muted")
        self.detail.setWordWrap(True)
        rv.addWidget(self.detail)
        split.addWidget(right)
        split.setSizes([420, 620])

    def _auto_path(self) -> None:
        def done(res: dict) -> None:
            resolved = (res.get("resolved") or {}).get("saves_dir") or ""
            if resolved and not self.path.text():
                self.path.setText(resolved)
                self._load()

        run_worker(self.svc.settings_snapshot, done, lambda _m: None)

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "选择存档", self.path.text(), "存档 (*.hg);;所有文件 (*)")
        if p:
            self.path.setText(p)

    def _load(self) -> None:
        self.status.setText("读取存档…")
        self.load_btn.setEnabled(False)

        def done(res: dict) -> None:
            self._ships = res.get("ships") or []
            warns = res.get("warnings") or []
            self.table.setRowCount(len(self._ships))
            for i, s in enumerate(self._ships):
                values = [str(s.get("slot")), s.get("type_label") or s.get("type") or "",
                          s.get("ship_class") or "", s.get("seed") or "", s.get("name") or ""]
                for j, v in enumerate(values):
                    item = QTableWidgetItem(v)
                    item.setData(Qt.UserRole, s)
                    self.table.setItem(i, j, item)
            self.table.resizeColumnsToContents()
            self.status.setText(f"{res.get('path')}  ·  {len(self._ships)} 艘"
                                + (f"  ·  {len(warns)} 条警告" if warns else ""))
            self.load_btn.setEnabled(True)

        def fail(msg: str) -> None:
            self.status.setText(f"读取失败：{msg}")
            self.load_btn.setEnabled(True)

        run_worker(self.svc.ships, done, fail, self.path.text().strip() or None)

    def _select(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item = self.table.item(rows[0].row(), 0)
        ship = item.data(Qt.UserRole) if item else None
        if not ship:
            return
        self.title.setText(f"{ship.get('type_label') or ship.get('type')}  {ship.get('seed')}")
        self.detail.setText("生成 3D 几何…")

        def done(mesh: dict) -> None:
            self.viewer.set_mesh(mesh.get("groups") or {}, mesh.get("colours") or {})
            stats = ship.get("stats") or {}
            st = "  ".join(f"{k}: {v}" for k, v in stats.items()) or "无属性数据"
            self.detail.setText(f"{st}\n{mesh.get('verts', 0):,} 顶点 / {mesh.get('tris', 0):,} 三角")

        def fail(msg: str) -> None:
            self.viewer.set_demo()
            self.detail.setText(f"真实 3D 不可用（{msg}）")

        run_worker(self.svc.preview_mesh, done, fail,
                   ship.get("type"), ship.get("seed"), ship.get("parts"))
