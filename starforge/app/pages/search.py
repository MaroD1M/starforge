"""搜飞船页：船型 → 部件 → 搜索 → 结果 → 原生 3D。"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...services import get_services
from ..widgets.ship_viewer import ShipViewer
from ..widgets.worker import run as run_worker

SHIPS = [("sentinel", "拦截机"), ("fighter", "战斗机"), ("hauler", "运输舰"),
         ("explorer", "探索舰"), ("shuttle", "穿梭机"), ("exotic", "异星"),
         ("living", "生物舰"), ("solar", "太阳帆")]


class SearchPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._job = None
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll_job)
        self._part_items: dict[str, str] = {}
        self._build_ui()
        self._load_parts()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        # 左：条件
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 12, 12)
        lv.addWidget(QLabel("船型"))
        self.ship = QComboBox()
        for key, label in SHIPS:
            self.ship.addItem(label, key)
        lv.addWidget(self.ship)
        self.ship.currentIndexChanged.connect(self._load_parts)

        lv.addWidget(QLabel("部件（勾选＝想要）"))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("过滤部件名，如 PIT / WING")
        self.filter.textChanged.connect(self._filter_parts)
        lv.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["部件", "组"])
        self.tree.setColumnWidth(0, 150)
        lv.addWidget(self.tree, 1)

        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("勾选＝想要", "want")
        self.mode.addItem("勾选＝不要", "avoid")
        row.addWidget(self.mode)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self._clear_checks)
        row.addWidget(self.clear_btn)
        lv.addLayout(row)

        row2 = QHBoxLayout()
        lv.addWidget(QLabel("搜索预算"))
        self.budget = QComboBox()
        self.budget.addItem("2000 万（1–2 秒）", 20_000_000)
        self.budget.addItem("2 亿（10–15 秒）", 200_000_000)
        self.budget.setCurrentIndex(1)
        self.budget.addItem("20 亿（2–3 分钟）", 2_000_000_000)
        row2.addWidget(self.budget)
        lv.addLayout(row2)

        self.search_btn = QPushButton("开始搜索")
        self.search_btn.setObjectName("primary")
        self.search_btn.clicked.connect(self._start_search)
        lv.addWidget(self.search_btn)
        self.status = QLabel("选几个部件，点开始搜索")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        lv.addWidget(self.status)
        split.addWidget(left)

        # 中：结果
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(12, 12, 12, 12)
        self.info = QLabel("还没有结果")
        self.info.setObjectName("muted")
        mv.addWidget(self.info)
        self.results = QListWidget()
        self.results.setViewMode(QListWidget.IconMode)
        self.results.setResizeMode(QListWidget.Adjust)
        self.results.setSpacing(8)
        self.results.setIconSize(self.results.iconSize().expandedTo(QSize(120, 90)))
        self.results.itemSelectionChanged.connect(self._select_result)
        mv.addWidget(self.results, 1)
        split.addWidget(mid)

        # 右：3D
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 12, 12, 12)
        self.title = QLabel("原生 3D 预览")
        rv.addWidget(self.title)
        self.viewer = ShipViewer()
        rv.addWidget(self.viewer, 1)
        self.detail = QLabel("选中结果后在这里查看；无游戏数据时会显示占位模型。")
        self.detail.setObjectName("muted")
        self.detail.setWordWrap(True)
        rv.addWidget(self.detail)
        row3 = QHBoxLayout()
        self.demo_btn = QPushButton("示例 3D")
        self.demo_btn.clicked.connect(self.viewer.set_demo)
        row3.addWidget(self.demo_btn)
        self.copy_btn = QPushButton("复制种子")
        self.copy_btn.clicked.connect(self._copy_seed)
        row3.addWidget(self.copy_btn)
        rv.addLayout(row3)
        split.addWidget(right)
        split.setSizes([300, 520, 420])

    # ---------------------------------------------------------------- 数据

    def _load_parts(self) -> None:
        ship = self.ship.currentData()
        self.tree.clear()
        self._part_items.clear()
        self.status.setText("读取部件表…")

        def done(res: dict) -> None:
            groups = res.get("groups") or []
            source = res.get("source") or ""
            for g in groups:
                top = QTreeWidgetItem([g.get("label") or g.get("group"), ""])
                top.setFlags(top.flags() & ~Qt.ItemIsSelectable)
                for opt in g.get("options") or []:
                    part = opt.get("part") or ""
                    child = QTreeWidgetItem([opt.get("label") or part, g.get("group") or ""])
                    child.setData(0, Qt.UserRole, part)
                    child.setToolTip(0, part)
                    child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                    child.setCheckState(0, Qt.Unchecked)
                    top.addChild(child)
                    self._part_items[part.upper()] = part
                self.tree.addTopLevelItem(top)
                top.setExpanded(True)
            self.status.setText(f"部件表已加载（{source or '未知来源'}）")

        def fail(msg: str) -> None:
            self.status.setText(f"读不到部件表：{msg}")

        run_worker(self.svc.catalog_ship, done, fail, ship)

    def _filter_parts(self, text: str) -> None:
        needle = text.strip().upper()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            visible = False
            for j in range(top.childCount()):
                child = top.child(j)
                show = not needle or needle in (child.data(0, Qt.UserRole) or "").upper()
                child.setHidden(not show)
                visible = visible or show
            top.setHidden(not visible)

    def _checked(self) -> tuple[list[str], list[str]]:
        want, avoid = [], []
        mode = self.mode.currentData()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                if child.checkState(0) == Qt.Checked:
                    part = child.data(0, Qt.UserRole)
                    (avoid if mode == "avoid" else want).append(part)
        return want, avoid

    def _clear_checks(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                top.child(j).setCheckState(0, Qt.Unchecked)

    # ---------------------------------------------------------------- 搜索

    def _start_search(self) -> None:
        want, avoid = self._checked()
        if not want and not avoid:
            self.status.setText("至少勾选一个部件")
            return
        self.search_btn.setEnabled(False)
        self.results.clear()
        self.status.setText("搜索中…")
        payload = {"ship": self.ship.currentData(), "want": want, "avoid": avoid,
                   "limit": 24, "max_seeds": int(self.budget.currentData()),
                   "time_limit": 180.0}
        try:
            self._job = self.svc.start_search(payload)
        except Exception as e:                              # noqa: BLE001
            self.search_btn.setEnabled(True)
            self.status.setText(f"无法开始搜索：{type(e).__name__}: {e}")
            return
        self._timer.start()

    def _poll_job(self) -> None:
        job = self._job
        if job is None:
            self._timer.stop()
            return
        p = job.progress or {}
        tested = p.get("tested") or 0
        rate = p.get("rate") or 0
        self.status.setText(f"搜索中… 已测 {tested:,} 个种子  {rate/1e6:.1f} M/s")
        if job.status == "running":
            return
        self._timer.stop()
        self.search_btn.setEnabled(True)
        if job.error:
            self.status.setText(f"搜索失败：{job.error}")
            return
        rows = job.result or []
        self.info.setText(f"命中 {len(rows)} 个（已测 {tested:,}）")
        for row in rows:
            item = QListWidgetItem(row.get("seed") or "")
            item.setData(Qt.UserRole, row)
            item.setToolTip(f"{row.get('type_label') or row.get('type')}  {row.get('seed')}")
            self.results.addItem(item)
        self.status.setText("搜索完成" if rows else "没有命中：条件可能太严")

    def _select_result(self) -> None:
        items = self.results.selectedItems()
        if not items:
            return
        row = items[0].data(Qt.UserRole) or {}
        seed = row.get("seed") or ""
        ship = row.get("type") or self.ship.currentData()
        parts = row.get("parts") or None
        self.title.setText(f"{row.get('type_label') or ship}  {seed}")
        self.detail.setText("生成 3D 几何…")

        def done(mesh: dict) -> None:
            self.viewer.set_mesh(mesh.get("groups") or {}, mesh.get("colours") or {})
            self.detail.setText(f"{mesh.get('verts', 0):,} 顶点 / {mesh.get('tris', 0):,} 三角  ·  拖动旋转，滚轮缩放")

        def fail(msg: str) -> None:
            self.viewer.set_demo()
            self.detail.setText(f"真实 3D 不可用（{msg}），已显示占位模型。")

        run_worker(self.svc.preview_mesh, done, fail, ship, seed, parts)

    def _copy_seed(self) -> None:
        items = self.results.selectedItems()
        if not items:
            return
        row = items[0].data(Qt.UserRole) or {}
        QGuiApplication.clipboard().setText(row.get("seed") or "")
        self.status.setText("种子已复制")
