"""飞船实验室：条件构建 → 结果网格 → 3D Inspector。"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from ...services import get_services
from ..widgets.ship_viewer import ShipViewer
from ..widgets.ui import Card, icon_from_png, muted
from ..widgets.worker import run as run_worker

SHIPS = [("sentinel", "拦截机"), ("fighter", "战斗机"), ("hauler", "运输舰"),
         ("explorer", "探索舰"), ("shuttle", "穿梭机"), ("exotic", "异星"),
         ("living", "生物舰"), ("solar", "太阳帆")]


class ShipLabPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._job = None
        self._loaded = False
        self._results: list[dict] = []
        self._thumb_queue: list[QListWidgetItem] = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._next_thumb)
        self._job_timer = QTimer(self)
        self._job_timer.setInterval(250)
        self._job_timer.timeout.connect(self._poll_job)
        self._build_ui()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        split.addWidget(self._build_filters())
        split.addWidget(self._build_results())
        split.addWidget(self._build_inspector())
        split.setSizes([300, 700, 420])

    def _build_filters(self) -> QWidget:
        wrap = Card("条件", "点部件 = 加入当前模式")
        v = wrap.v

        v.addWidget(QLabel("船型"))
        self.ship = QComboBox()
        for key, label in SHIPS:
            self.ship.addItem(label, key)
        self.ship.currentIndexChanged.connect(self._load_parts)
        v.addWidget(self.ship)

        row = QHBoxLayout()
        row.addWidget(QLabel("模式"))
        self.mode = QComboBox()
        self.mode.addItem("想要", "want")
        self.mode.addItem("不要", "avoid")
        row.addWidget(self.mode)
        row.addStretch(1)
        clear = QPushButton("清空")
        clear.clicked.connect(self._clear_checks)
        row.addWidget(clear)
        v.addLayout(row)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("过滤部件名，如 PIT / WING")
        self.filter.textChanged.connect(self._filter_parts)
        v.addWidget(self.filter)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["部件", "组"])
        self.tree.setColumnWidth(0, 160)
        self.tree.itemChanged.connect(self._update_chips)
        v.addWidget(self.tree, 1)

        self.chips = QLabel("未选择条件")
        self.chips.setObjectName("muted")
        self.chips.setWordWrap(True)
        v.addWidget(self.chips)

        paint = QHBoxLayout()
        self.look_on = QCheckBox("按涂装筛")
        paint.addWidget(self.look_on)
        self.primary = QPushButton("主色")
        self.primary.setStyleSheet("border-color:#8a6a2f;")
        self.primary.clicked.connect(lambda: self._pick_color("primary"))
        paint.addWidget(self.primary)
        self.secondary = QPushButton("副色")
        self.secondary.clicked.connect(lambda: self._pick_color("secondary"))
        paint.addWidget(self.secondary)
        v.addLayout(paint)
        self._colors = {"primary": QColor("#f2c744"), "secondary": QColor("#1c1c22")}
        self._paint_buttons()

        v.addWidget(QLabel("搜索预算"))
        self.budget = QComboBox()
        self.budget.addItem("2000 万（约 1–2 秒）", 20_000_000)
        self.budget.addItem("2 亿（约 10–15 秒）", 200_000_000)
        self.budget.setCurrentIndex(1)
        self.budget.addItem("20 亿（约 2–3 分钟）", 2_000_000_000)
        v.addWidget(self.budget)

        row2 = QHBoxLayout()
        self.search_btn = QPushButton("开始搜索")
        self.search_btn.setObjectName("primary")
        self.search_btn.clicked.connect(self._start_search)
        row2.addWidget(self.search_btn, 1)
        demo = QPushButton("示例")
        demo.clicked.connect(self._demo)
        row2.addWidget(demo)
        v.addLayout(row2)
        self.status = muted("选几个部件，点开始搜索")
        v.addWidget(self.status)
        return wrap

    def _build_results(self) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 0, 8, 0)
        bar = QHBoxLayout()
        self.result_info = QLabel("还没有结果")
        self.result_info.setObjectName("muted")
        bar.addWidget(self.result_info)
        bar.addStretch(1)
        self.view_mode = QComboBox()
        self.view_mode.addItem("网格", "grid")
        self.view_mode.addItem("列表", "list")
        self.view_mode.currentIndexChanged.connect(self._apply_view_mode)
        bar.addWidget(self.view_mode)
        v.addLayout(bar)
        self.results = QListWidget()
        self.results.setViewMode(QListWidget.IconMode)
        self.results.setResizeMode(QListWidget.Adjust)
        self.results.setIconSize(QSize(160, 110))
        self.results.setSpacing(10)
        self.results.setMovement(QListWidget.Static)
        self.results.itemSelectionChanged.connect(self._select_result)
        self.results.itemDoubleClicked.connect(lambda _i: self._copy_seed())
        v.addWidget(self.results, 1)
        self.empty = muted("选几个部件，点「开始搜索」。结果会显示在这里，右侧可旋转 3D。")
        v.addWidget(self.empty)
        return box

    def _build_inspector(self) -> QWidget:
        wrap = Card("Inspector")
        v = wrap.v
        self.title = QLabel("未选择飞船")
        self.title.setStyleSheet("font-size:15px;font-weight:700;")
        v.addWidget(self.title)
        self.viewer = ShipViewer()
        self.viewer.setMinimumHeight(300)
        v.addWidget(self.viewer, 1)
        self.detail = muted("选中结果后在这里查看 3D 与操作。")
        v.addWidget(self.detail)
        row = QHBoxLayout()
        self.copy_btn = QPushButton("复制种子")
        self.copy_btn.clicked.connect(self._copy_seed)
        row.addWidget(self.copy_btn)
        self.fav_btn = QPushButton("收藏")
        self.fav_btn.clicked.connect(self._toggle_fav)
        row.addWidget(self.fav_btn)
        self.glb_btn = QPushButton("导出 glb")
        self.glb_btn.clicked.connect(self._export_glb)
        row.addWidget(self.glb_btn)
        v.addLayout(row)
        row2 = QHBoxLayout()
        self.write_btn = QPushButton("写回存档…")
        self.write_btn.setEnabled(False)
        self.write_btn.setToolTip("下一阶段接入写回对话框")
        row2.addWidget(self.write_btn)
        self.more_btn = QPushButton("更多")
        self.more_btn.setEnabled(False)
        row2.addWidget(self.more_btn)
        v.addLayout(row2)
        return wrap

    # ---------------------------------------------------------------- 数据

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._load_parts()

    def _load_parts(self) -> None:
        ship = self.ship.currentData()
        self.tree.clear()
        self.status.setText("读取部件表…")

        def done(res: dict) -> None:
            for g in res.get("groups") or []:
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
                self.tree.addTopLevelItem(top)
                top.setExpanded(True)
            self.status.setText(f"部件表已加载（{res.get('source') or '未知来源'}）")

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
        avoid_mode = self.mode.currentData() == "avoid"
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                if child.checkState(0) == Qt.Checked:
                    (avoid if avoid_mode else want).append(child.data(0, Qt.UserRole))
        return want, avoid

    def _update_chips(self, *_args) -> None:
        want, avoid = self._checked()
        bits = []
        if want:
            bits.append("要: " + " ".join(want[:6]) + ("…" if len(want) > 6 else ""))
        if avoid:
            bits.append("不要: " + " ".join(avoid[:6]) + ("…" if len(avoid) > 6 else ""))
        self.chips.setText("  ·  ".join(bits) or "未选择条件")

    def _clear_checks(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                top.child(j).setCheckState(0, Qt.Unchecked)
        self._update_chips()

    def _pick_color(self, role: str) -> None:
        c = QColorDialog.getColor(self._colors[role], self, "选择颜色")
        if c.isValid():
            self._colors[role] = c
            self._paint_buttons()

    def _paint_buttons(self) -> None:
        for role, btn in (("primary", self.primary), ("secondary", self.secondary)):
            c = self._colors[role]
            btn.setText(role + " " + c.name())
            btn.setStyleSheet(f"border:1px solid {c.name()}; color:{c.name()};")

    def _demo(self) -> None:
        if not self.tree.topLevelItemCount():
            return
        # 选第一组第一个部件作为示例
        top = self.tree.topLevelItem(0)
        if top and top.childCount():
            top.child(0).setCheckState(0, Qt.Checked)
        self._update_chips()

    # ---------------------------------------------------------------- 搜索

    def _start_search(self) -> None:
        want, avoid = self._checked()
        if not want and not avoid:
            self.status.setText("至少勾选一个部件")
            return
        look = None
        if self.look_on.isChecked():
            c = self._colors["primary"]
            look = {"primary": [c.redF(), c.greenF(), c.blueF()], "tol": 0.18}
        payload = {"ship": self.ship.currentData(), "want": want, "avoid": avoid,
                   "look": look, "limit": 24, "max_seeds": int(self.budget.currentData()),
                   "time_limit": 180.0}
        self.search_btn.setEnabled(False)
        self.results.clear()
        self._results = []
        self.empty.hide()
        self.status.setText("搜索中…")
        try:
            self._job = self.svc.start_search(payload)
        except Exception as e:                              # noqa: BLE001
            self.search_btn.setEnabled(True)
            self.status.setText(f"无法开始搜索：{type(e).__name__}: {e}")
            return
        self._job_timer.start()

    def _poll_job(self) -> None:
        job = self._job
        if job is None:
            self._job_timer.stop()
            return
        p = job.progress or {}
        tested = p.get("tested") or 0
        rate = p.get("rate") or 0
        self.status.setText(f"搜索中… 已测 {tested:,} seeds  {rate/1e6:.1f} M/s")
        if job.status == "running":
            return
        self._job_timer.stop()
        self.search_btn.setEnabled(True)
        if job.error:
            self.status.setText(f"搜索失败：{job.error}")
            return
        self._results = job.result or []
        self.result_info.setText(f"命中 {len(self._results)} 个（已测 {tested:,}）")
        for row in self._results:
            item = QListWidgetItem(row.get("seed") or "")
            item.setData(Qt.UserRole, row)
            item.setToolTip(f"{row.get('type_label') or row.get('type')}  {row.get('seed')}")
            self.results.addItem(item)
            self._thumb_queue.append(item)
        self.status.setText("搜索完成" if self._results else "没有命中：条件可能太严")
        self._thumb_timer.start(50)

    def _next_thumb(self) -> None:
        if not self._thumb_queue:
            return
        item = self._thumb_queue.pop(0)
        row = item.data(Qt.UserRole) or {}
        ship = row.get("type") or self.ship.currentData()
        seed = row.get("seed") or ""
        parts = row.get("parts") or None

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

        run_worker(self.svc.preview_png, done, fail, ship, seed, parts, 240)

    def _apply_view_mode(self) -> None:
        grid = self.view_mode.currentData() == "grid"
        self.results.setViewMode(QListWidget.IconMode if grid else QListWidget.ListMode)
        self.results.setIconSize(QSize(160, 110) if grid else QSize(72, 50))
        self.results.setGridSize(QSize() if grid else QSize())

    # ---------------------------------------------------------------- Inspector

    def _select_result(self) -> None:
        items = self.results.selectedItems()
        if not items:
            return
        row = items[0].data(Qt.UserRole) or {}
        self.title.setText(f"{row.get('type_label') or row.get('type')}  {row.get('seed')}")
        self.detail.setText("生成 3D 几何…")
        self.write_btn.setEnabled(bool(row))

        def done(mesh: dict) -> None:
            self.viewer.set_mesh(mesh.get("groups") or {}, mesh.get("colours") or {})
            self.detail.setText(f"{mesh.get('verts', 0):,} 顶点 / {mesh.get('tris', 0):,} 三角"
                                "\n拖动旋转 · 滚轮缩放 · 双击复位")

        def fail(msg: str) -> None:
            try:
                self.viewer.set_demo()
            except Exception:
                pass
            self.detail.setText(f"真实 3D 不可用（{msg}），已切换占位模型。")

        run_worker(self.svc.preview_mesh, done, fail,
                   row.get("type"), row.get("seed"), row.get("parts"))

    def _current_row(self) -> dict | None:
        items = self.results.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _copy_seed(self) -> None:
        row = self._current_row()
        if row:
            QGuiApplication.clipboard().setText(row.get("seed") or "")
            self.status.setText("种子已复制")

    def _toggle_fav(self) -> None:
        row = self._current_row()
        if row:
            self.status.setText("收藏功能将在下一批接入")

    def _export_glb(self) -> None:
        row = self._current_row()
        if not row:
            return
        self.status.setText("导出 glb…")

        def done(path: str) -> None:
            self.status.setText(f"glb 已生成：{path}")

        def fail(msg: str) -> None:
            self.status.setText(f"导出失败：{msg}")

        run_worker(self.svc.glb_path, done, fail,
                   row.get("type"), row.get("seed"), row.get("parts"))
