"""飞船实验室：条件构建 → 结果网格 → 3D Inspector。"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox,
                               QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ...services import favorites, get_services
from .. import notify
from ..dialogs.compare import MAX_COMPARE, CompareDialog, merge_compare, ship_key
from ..dialogs.favorites import FavoritesDialog
from ..dialogs.write_back import WriteBackDialog
from ..widgets.feedback import EmptyState, ErrorBanner, LoadingOverlay
from ..widgets.page_header import PageHeader
from ..widgets.ship_card import install_card_delegate
from ..widgets.ship_viewer import ShipViewer
from ..widgets.ui import Card, icon_from_png, muted, placeholder_icon
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
        self._compare_rows: list[dict] = []
        self._thumb_queue: list[QListWidgetItem] = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._next_thumb)
        self._part_icon_queue: list[tuple[QTreeWidgetItem, str, str, bool]] = []
        self._part_icon_timer = QTimer(self)
        self._part_icon_timer.setSingleShot(True)
        self._part_icon_timer.setInterval(10)
        self._part_icon_timer.timeout.connect(self._next_part_icon)
        self._job_timer = QTimer(self)
        self._job_timer.setInterval(250)
        self._job_timer.timeout.connect(self._poll_job)
        self._build_ui()
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self._start_search)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._focus_filter)
        esc = QShortcut(QKeySequence("Esc"), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self._clear_result_selection)
        for key, delta in (("J", 1), ("K", -1)):
            sc = QShortcut(QKeySequence(key), self.results)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(lambda d=delta: self._move_selection(d))

    def _move_selection(self, delta: int) -> None:
        if not self.results.count():
            return
        row = self.results.currentRow()
        row = max(0, min(self.results.count() - 1, (row if row >= 0 else 0) + delta))
        self.results.setCurrentRow(row)

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        self.header = PageHeader(
            "飞船实验室",
            "条件 → 结果 → 3D：在左侧勾选部件，搜索并挑选飞船，再在右侧查看模型与操作。")
        refresh = QPushButton("刷新部件")
        refresh.setToolTip("重新读取当前船型的部件表")
        refresh.clicked.connect(self._refresh_parts)
        self.header.add_action(refresh)
        favorites_btn = QPushButton("收藏夹")
        favorites_btn.setToolTip("管理已收藏飞船，可载入到实验室")
        favorites_btn.clicked.connect(self._open_favorites)
        self.header.add_action(favorites_btn)
        root.addWidget(self.header)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

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
        clear.clicked.connect(lambda: self._clear_checks(announce=True))
        row.addWidget(clear)
        v.addLayout(row)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("筛选部件名（如 PIT / WING）")
        self.filter.textChanged.connect(self._filter_parts)
        v.addWidget(self.filter)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["部件", "组"])
        self.tree.setColumnWidth(0, 200)
        self.tree.setIconSize(QSize(40, 40))
        self.tree.setStyleSheet("QTreeWidget::item { height: 38px; }")
        self.tree.itemChanged.connect(self._update_chips)
        self.tree.itemClicked.connect(self._lazy_part_icon)
        v.addWidget(self.tree, 1)

        panel = QFrame()
        panel.setObjectName("card")
        ph = QHBoxLayout(panel)
        ph.setContentsMargins(8, 8, 8, 8)
        self.part_thumb = QLabel()
        self.part_thumb.setFixedSize(72, 72)
        self.part_thumb.setAlignment(Qt.AlignCenter)
        ph.addWidget(self.part_thumb)
        self.part_text = QLabel("点击部件查看预览与详情")
        self.part_text.setObjectName("muted")
        self.part_text.setWordWrap(True)
        ph.addWidget(self.part_text, 1)
        v.addWidget(panel)

        self.chips = QPushButton("未选择条件")
        self.chips.setFlat(True)
        self.chips.setCursor(Qt.PointingHandCursor)
        self.chips.setToolTip("点击清除已选条件")
        self.chips.setStyleSheet(
            "QPushButton { border:none; background:transparent; color:#8b95a7;"
            " text-align:left; padding:0; }"
            "QPushButton:hover { color:#e6ecf5; }")
        self.chips.clicked.connect(lambda: self._clear_checks(announce=True))
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
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_search)
        row2.addWidget(self.cancel_btn)
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
        self.add_compare_btn = QPushButton("加入对比")
        self.add_compare_btn.setToolTip("把选中的 1–3 艘飞船加入对比（Ctrl / Shift 可多选）")
        self.add_compare_btn.clicked.connect(self._add_selected_to_compare)
        bar.addWidget(self.add_compare_btn)
        self.compare_btn = QPushButton("对比 (0)")
        self.compare_btn.setToolTip("并排对比 2–3 艘飞船")
        self.compare_btn.setEnabled(False)
        self.compare_btn.clicked.connect(self._open_compare)
        bar.addWidget(self.compare_btn)
        self.clear_compare_btn = QPushButton("清空对比")
        self.clear_compare_btn.setEnabled(False)
        self.clear_compare_btn.clicked.connect(self._clear_compare)
        bar.addWidget(self.clear_compare_btn)
        self.clear_results_btn = QPushButton("清空结果")
        self.clear_results_btn.setToolTip("清空当前结果列表（不影响对比）")
        self.clear_results_btn.clicked.connect(self._clear_results)
        bar.addWidget(self.clear_results_btn)
        self.reset_conditions_btn = QPushButton("重置条件")
        self.reset_conditions_btn.setToolTip("清除部件选择、涂装筛选与搜索预算")
        self.reset_conditions_btn.clicked.connect(self._reset_conditions)
        bar.addWidget(self.reset_conditions_btn)
        self.view_mode = QComboBox()
        self.view_mode.addItem("网格", "grid")
        self.view_mode.addItem("列表", "list")
        self.view_mode.currentIndexChanged.connect(self._apply_view_mode)
        bar.addWidget(self.view_mode)
        v.addLayout(bar)
        self.error_banner = ErrorBanner("", box)
        self.error_banner.set_retry_callback(self._start_search)
        v.addWidget(self.error_banner)
        self.results = QListWidget()
        self.results.setViewMode(QListWidget.IconMode)
        self.results.setResizeMode(QListWidget.Adjust)
        self.results.setMovement(QListWidget.Static)
        self.results.setWordWrap(False)
        self.results.setFocusPolicy(Qt.StrongFocus)
        self.results.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._card_delegate = install_card_delegate(self.results, 110)
        self.results.itemSelectionChanged.connect(self._select_result)
        self.results.itemDoubleClicked.connect(lambda _i: self._copy_seed())
        self.empty = EmptyState(
            "还没有搜索结果",
            "在左侧勾选部件条件，然后点「开始搜索」；结果会显示在这里，"
            "右侧可查看 3D 模型与操作。",
            icon="◇", button_text="试试示例", parent=box)
        self._empty_action = "demo"
        self.empty.actionTriggered.connect(self._on_empty_action)
        self.result_stack = QStackedWidget()
        self.result_stack.addWidget(self.results)
        self.result_stack.addWidget(self.empty)
        v.addWidget(self.result_stack, 1)
        self.loading = LoadingOverlay(box, "正在搜索飞船…")
        self.result_stack.setCurrentWidget(self.empty)
        return box

    def _build_inspector(self) -> QWidget:
        wrap = Card("飞船详情")
        v = wrap.v
        self.title = QLabel("未选择飞船")
        self.title.setStyleSheet("font-size:15px;font-weight:700;")
        v.addWidget(self.title)
        self.viewer = ShipViewer()
        self.viewer.setMinimumHeight(300)
        v.addWidget(self.viewer, 1)
        self.fallback = QLabel()
        self.fallback.setAlignment(Qt.AlignCenter)
        self.fallback.setMinimumHeight(300)
        self.fallback.hide()
        v.addWidget(self.fallback, 1)
        view_row = QHBoxLayout()
        for text, mode in (("等轴", "iso"), ("俯视", "top"), ("侧视", "side"), ("正视", "front")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, m=mode: self.viewer.set_view(m))
            view_row.addWidget(b)
        spin = QPushButton("自转")
        spin.setCheckable(True)
        spin.toggled.connect(self.viewer.set_spin)
        view_row.addWidget(spin)
        shot = QPushButton("截图")
        shot.clicked.connect(self._save_snapshot)
        view_row.addWidget(shot)
        v.addLayout(view_row)
        self.detail = muted("选中结果后在这里查看 3D 模型与操作。")
        v.addWidget(self.detail)
        row = QHBoxLayout()
        self.copy_btn = QPushButton("复制种子")
        self.copy_btn.clicked.connect(self._copy_seed)
        row.addWidget(self.copy_btn)
        self.fav_btn = QPushButton("收藏")
        self.fav_btn.clicked.connect(self._toggle_fav)
        row.addWidget(self.fav_btn)
        self.favs_btn = QPushButton("收藏夹")
        self.favs_btn.setToolTip("管理已收藏飞船，可载入到实验室")
        self.favs_btn.clicked.connect(self._open_favorites)
        row.addWidget(self.favs_btn)
        self.share_btn = QPushButton("分享码")
        self.share_btn.setToolTip("复制当前飞船的 nsh1: 分享码")
        self.share_btn.clicked.connect(self._copy_share)
        row.addWidget(self.share_btn)
        self.glb_btn = QPushButton("导出模型（glb）")
        self.glb_btn.clicked.connect(self._export_glb)
        row.addWidget(self.glb_btn)
        self.raster_btn = QPushButton("渲染图")
        self.raster_btn.clicked.connect(self._show_current_raster)
        row.addWidget(self.raster_btn)
        v.addLayout(row)
        row2 = QHBoxLayout()
        self.write_btn = QPushButton("写入存档…")
        self.write_btn.setEnabled(False)
        self.write_btn.setToolTip("写入同型号槽位；先备份，写入后读回校验")
        self.write_btn.clicked.connect(self._open_write)
        row2.addWidget(self.write_btn)
        self.import_btn = QPushButton("导入分享码…")
        self.import_btn.setToolTip("粘贴他人分享的 nsh1: 分享码")
        self.import_btn.clicked.connect(self._import_share)
        row2.addWidget(self.import_btn)
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

    def _refresh_parts(self) -> None:
        self._loaded = True
        self._load_parts(announce=True)

    def _load_parts(self, announce: bool = False) -> None:
        ship = self.ship.currentData()
        self.tree.clear()
        self.status.setText("读取部件表…")

        def done(res: dict) -> None:
            self._part_icon_queue.clear()
            total = 0
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
                    child.setIcon(0, placeholder_icon(part))
                    top.addChild(child)
                    if total < 16:
                        self._part_icon_queue.append((child, ship, part, True))
                    total += 1
                self.tree.addTopLevelItem(top)
                top.setExpanded(True)
            self.status.setText(f"部件表已加载（{self._source_label(res.get('source'))}）")
            if announce:
                notify.success(f"部件表已刷新（{self._source_label(res.get('source'))}）")
            if self._part_icon_queue:
                self._part_icon_timer.start(30)

        def fail(msg: str) -> None:
            self.status.setText(f"读不到部件表：{msg}")
            if announce:
                notify.error(f"读取部件表失败：{msg}")

        run_worker(self.svc.catalog_ship, done, fail, ship)

    @staticmethod
    def _source_label(source: str | None) -> str:
        return {"game": "游戏资源", "gagarin": "Gagarin 数据表"}.get(source or "", "未知来源")

    def _lazy_part_icon(self, item: QTreeWidgetItem, _column: int) -> None:
        part = item.data(0, Qt.UserRole)
        if not part:
            return
        gid = item.data(0, Qt.UserRole + 1) or item.text(1)
        self.part_text.setText(f"{part}  ·  组 {gid}\n读取预览…")
        ship = self.ship.currentData()

        def done(data: bytes | None) -> None:
            if data:
                pix = QPixmap()
                pix.loadFromData(data, "PNG")
                if not pix.isNull():
                    self.part_thumb.setPixmap(pix)
                    self.part_text.setText(f"{part}  ·  组 {gid}")
                    return
            self.part_text.setText(f"{part}  ·  组 {gid}\n该部件没有可渲染的几何（结构件/空槽）")

        run_worker(self.svc.part_icon, done, lambda m: self.part_text.setText(f"{part} 预览失败：{m}"),
                   ship, part, 96)
        self._load_part_3d_icon(item, ship, part)

    def _next_part_icon(self) -> None:
        if not self._part_icon_queue:
            return
        item, ship, part, _allow_3d = self._part_icon_queue.pop(0)

        def done(data: bytes | None) -> None:
            try:
                if data:
                    item.setIcon(0, icon_from_png(data, 40))
            except Exception:                              # noqa: BLE001
                pass
            if self._part_icon_queue:
                self._part_icon_timer.start(20)

        def fail(_msg: str) -> None:
            if self._part_icon_queue:
                self._part_icon_timer.start(20)

        run_worker(self.svc.part_icon, done, fail, ship, part, 48)

    def _load_part_3d_icon(self, item: QTreeWidgetItem, ship: str, part: str) -> None:
        def done(data: bytes | None) -> None:
            try:
                if data:
                    item.setIcon(0, icon_from_png(data, 40))
            except Exception:                              # noqa: BLE001
                pass

        run_worker(self.svc.part_icon, done, lambda _m: None, ship, part, 48)

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
            bits.append("要：" + " ".join(want[:6]) + ("…" if len(want) > 6 else ""))
        if avoid:
            bits.append("不要：" + " ".join(avoid[:6]) + ("…" if len(avoid) > 6 else ""))
        summary = "  ·  ".join(bits)
        self.chips.setText(f"{summary}  ·  点击清除" if summary else "未选择条件")
        self.chips.setToolTip("点击清除已选条件" if summary else "还没有选择条件")

    def _clear_checks(self, announce: bool = False) -> None:
        want, avoid = self._checked()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                top.child(j).setCheckState(0, Qt.Unchecked)
        self._update_chips()
        if announce:
            if want or avoid:
                self.status.setText("已清除已选条件")
                notify.success("已清除已选条件")
            else:
                notify.warn("还没有选择条件")

    def _reset_conditions(self) -> None:
        self._clear_checks()
        self.mode.setCurrentIndex(0)
        self.filter.clear()
        self.look_on.setChecked(False)
        self._colors = {"primary": QColor("#f2c744"), "secondary": QColor("#1c1c22")}
        self._paint_buttons()
        self.budget.setCurrentIndex(1)
        if self.ship.currentIndex() != 0:
            self.ship.setCurrentIndex(0)
        self._update_chips()
        self.status.setText("条件已重置")
        notify.success("条件已重置")

    def _show_empty(self, title: str, description: str,
                    action_text: str, action: str) -> None:
        self.empty.title_label.setText(title)
        self.empty.description_label.setText(description)
        self.empty.description_label.setVisible(bool(description))
        self.empty.set_action(action_text)
        self._empty_action = action
        self.result_stack.setCurrentWidget(self.empty)

    def _on_empty_action(self) -> None:
        if self._empty_action == "search":
            self._start_search()
        elif self._empty_action == "reset":
            self._reset_conditions()
        else:
            self._demo()

    def _focus_filter(self) -> None:
        self.filter.setFocus(Qt.ShortcutFocusReason)
        self.filter.selectAll()

    def _reset_inspector(self) -> None:
        self.title.setText("未选择飞船")
        self.detail.setText("选中结果后在这里查看 3D 模型与操作。")
        self.write_btn.setEnabled(False)
        self.fav_btn.setText("收藏")
        self.fallback.hide()
        self.viewer.show()

    def _clear_result_selection(self) -> None:
        if not self.results.selectedItems():
            return
        self.results.clearSelection()
        self.results.setCurrentRow(-1)
        self._reset_inspector()
        self.status.setText("已清除结果选择")

    def _clear_results(self) -> None:
        if self._job is not None and self._job.status == "running":
            try:
                self._job.cancel()
            except Exception:                              # noqa: BLE001
                pass
        self._job_timer.stop()
        self._job = None
        self.loading.stop()
        self._thumb_queue.clear()
        self.results.clear()
        self._results = []
        self.result_info.setText("还没有结果")
        self.error_banner.clear()
        self.search_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._reset_inspector()
        self._show_empty(
            "还没有搜索结果",
            "在左侧勾选部件条件，然后点「开始搜索」；结果会显示在这里，"
            "右侧可查看 3D 模型与操作。",
            "试试示例", "demo")
        self.status.setText("结果已清空")
        notify.success("结果已清空")

    def _pick_color(self, role: str) -> None:
        c = QColorDialog.getColor(self._colors[role], self, "选择颜色")
        if c.isValid():
            self._colors[role] = c
            self._paint_buttons()

    def _paint_buttons(self) -> None:
        labels = {"primary": "主色", "secondary": "副色"}
        for role, btn in (("primary", self.primary), ("secondary", self.secondary)):
            c = self._colors[role]
            btn.setText(f"{labels[role]} {c.name()}")
            btn.setStyleSheet(f"border:1px solid {c.name()}; color:{c.name()};")

    def _demo(self) -> None:
        if not self.tree.topLevelItemCount():
            notify.warn("部件表尚未加载完成，请稍后再试")
            return
        # 选第一组第一个部件作为示例
        top = self.tree.topLevelItem(0)
        if top and top.childCount():
            top.child(0).setCheckState(0, Qt.Checked)
        self._update_chips()
        self.status.setText("已填入示例条件")
        notify.success("已填入示例条件")

    # ---------------------------------------------------------------- 搜索

    def _start_search(self) -> None:
        want, avoid = self._checked()
        if not want and not avoid:
            self.status.setText("至少勾选一个部件")
            notify.warn("至少勾选一个部件再搜索")
            return
        look = None
        if self.look_on.isChecked():
            c = self._colors["primary"]
            look = {"primary": [c.redF(), c.greenF(), c.blueF()], "tol": 0.18}
        payload = {"ship": self.ship.currentData(), "want": want, "avoid": avoid,
                   "look": look, "limit": 24, "max_seeds": int(self.budget.currentData()),
                   "time_limit": 180.0, "workers": 1}
        self.search_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._thumb_timer.stop()
        self._thumb_queue.clear()
        self.results.clear()
        self._results = []
        self.error_banner.clear()
        self.result_info.setText("搜索中…")
        self.result_stack.setCurrentWidget(self.results)
        self.loading.start("正在搜索飞船…")
        self.status.setText("搜索中…")
        try:
            self._job = self.svc.start_search(payload)
        except Exception as e:                              # noqa: BLE001
            self._job = None
            self.search_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.loading.stop()
            reason = f"无法开始搜索：{type(e).__name__}: {e}"
            self.status.setText(reason)
            self.error_banner.show_error(reason)
            self.result_info.setText("搜索未开始")
            self._show_empty("搜索未开始", "请检查条件后重试，或点错误条上的「重试」。",
                             "重试", "search")
            notify.error(reason)
            return
        self._job_timer.start()

    def _cancel_search(self) -> None:
        if self._job and self._job.status == "running":
            self._job.cancel()
            self.status.setText("正在取消…")
            notify.toast("正在取消搜索…", "warn")
        else:
            notify.warn("当前没有正在进行的搜索")

    def _poll_job(self) -> None:
        job = self._job
        if job is None:
            self._job_timer.stop()
            return
        p = job.progress or {}
        tested = p.get("tested") or 0
        rate = p.get("rate") or 0
        self.status.setText(f"搜索中… 已测 {tested:,} 个种子  {rate/1e6:.1f} 百万/秒")
        self.loading.set_text(f"正在搜索… 已测 {tested:,} 个种子")
        if job.status == "running":
            return
        self._job_timer.stop()
        self._job = None
        self.search_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.loading.stop()
        if job.error:
            reason = f"搜索失败：{job.error}"
            self.status.setText(reason)
            self.result_info.setText("搜索失败")
            self.error_banner.show_error(reason)
            self._show_empty("搜索失败", "可以点错误条上的「重试」，或调整条件后再搜索。",
                             "重试", "search")
            notify.error(reason)
            return
        if job.status == "cancelled":
            self.status.setText("搜索已取消")
            self.result_info.setText("搜索已取消")
            self._show_empty("搜索已取消", "调整条件后可以重新搜索。", "重新搜索", "search")
            notify.warn("搜索已取消")
            return
        self._results = job.result or []
        if self._results:
            self.result_info.setText(f"命中 {len(self._results)} 个（已测 {tested:,}）")
            for row in self._results:
                item = QListWidgetItem(row.get("seed") or "")
                item.setData(Qt.UserRole, row)
                item.setToolTip(f"{row.get('type_label') or row.get('type')}  {row.get('seed')}")
                self.results.addItem(item)
                self._thumb_queue.append(item)
            self._mark_compare_items()
            self.result_stack.setCurrentWidget(self.results)
            self.status.setText("搜索完成")
            self._thumb_timer.start(50)
            notify.success(f"搜索完成：命中 {len(self._results)} 艘飞船")
            return
        self.result_info.setText(f"命中 0 个（已测 {tested:,}）")
        self.status.setText("没有命中：条件可能太严")
        self._show_empty(
            "没有命中飞船",
            "条件可能太严：减少「不要」条件、放宽涂装筛选，或提高搜索预算。",
            "重置条件", "reset")
        notify.warn("搜索完成：没有命中飞船")

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
        if grid:
            self._card_delegate = install_card_delegate(self.results, 110)
        else:
            from PySide6.QtWidgets import QStyledItemDelegate
            self.results.setItemDelegate(QStyledItemDelegate(self.results))
            self.results.setIconSize(QSize(72, 50))
            self.results.setGridSize(QSize())

    # ---------------------------------------------------------------- 多选对比

    def _selected_rows(self) -> list[dict]:
        rows = []
        for item in self.results.selectedItems():
            row = item.data(Qt.UserRole)
            if isinstance(row, dict):
                rows.append(row)
        return [dict(row) for row in rows]

    def _add_selected_to_compare(self) -> None:
        rows = self._selected_rows()
        if not rows:
            row = self._current_row()
            if row:
                rows = [dict(row)]
        if not rows:
            self.status.setText("先在结果里选中 1–3 艘飞船")
            return
        before = len(self._compare_rows)
        self._compare_rows = merge_compare(self._compare_rows, rows)
        added = len(self._compare_rows) - before
        self._update_compare_buttons()
        self._mark_compare_items()
        total = len(self._compare_rows)
        if added:
            self.status.setText(f"已加入 {added} 艘到对比（{total}/{MAX_COMPARE}）")
        elif total >= MAX_COMPARE:
            self.status.setText(f"对比已满（最多 {MAX_COMPARE} 艘），可先清空或移除")
        else:
            self.status.setText("选中的飞船已在对比中")

    def _clear_compare(self) -> None:
        self._compare_rows = []
        self._update_compare_buttons()
        self._mark_compare_items()
        self.status.setText("对比已清空")

    def _update_compare_buttons(self) -> None:
        count = len(self._compare_rows)
        self.compare_btn.setText(f"对比 ({count})")
        self.compare_btn.setEnabled(count >= 2)
        self.add_compare_btn.setEnabled(count < MAX_COMPARE)
        self.clear_compare_btn.setEnabled(count > 0)
        if count:
            names = "、".join(
                f"{row.get('type_label') or row.get('type')} {row.get('seed')}"
                for row in self._compare_rows)
            self.compare_btn.setToolTip(f"对比 {count} 艘：{names}")
        else:
            self.compare_btn.setToolTip("并排对比 2–3 艘飞船")

    def _mark_compare_items(self) -> None:
        keys = {ship_key(row) for row in self._compare_rows}
        for i in range(self.results.count()):
            item = self.results.item(i)
            row = item.data(Qt.UserRole) or {}
            key = ship_key(row)
            base = f"{row.get('type_label') or row.get('type')}  {row.get('seed')}"
            item.setData(Qt.UserRole + 1, key in keys)
            item.setToolTip(base + ("\n已加入对比" if key in keys else ""))

    def _open_compare(self) -> None:
        if len(self._compare_rows) < 2:
            self.status.setText("至少需要 2 艘飞船才能对比")
            return
        dialog = CompareDialog(self._compare_rows, self)
        dialog.shipSelected.connect(self._load_compare_selection)
        dialog.exec()

    def _load_compare_selection(self, row: dict) -> None:
        if not row:
            return
        self._append_result(dict(row))
        self._update_fav_button(row)
        self.status.setText(f"已把 {row.get('seed') or ''} 设为 Inspector 当前船")

    # ---------------------------------------------------------------- Inspector

    def _select_result(self) -> None:
        items = self.results.selectedItems()
        if not items:
            return
        item = self.results.currentItem()
        if item is None or not item.isSelected():
            item = items[0]
        row = item.data(Qt.UserRole) or {}
        self.title.setText(f"{row.get('type_label') or row.get('type')}  {row.get('seed')}")
        self.detail.setText("生成 3D 几何…")
        self.write_btn.setEnabled(bool(row))
        self._update_fav_button(row)
        self.fallback.hide()
        self.viewer.show()

        def done(mesh: dict) -> None:
            self.viewer.set_mesh(mesh.get("groups") or {}, mesh.get("colours") or {})
            self.detail.setText(f"{mesh.get('verts', 0):,} 顶点 / {mesh.get('tris', 0):,} 三角"
                                "\n拖动旋转 · 滚轮缩放 · 双击复位")

        def fail(msg: str) -> None:
            self._show_fallback(row, msg)

        run_worker(self.svc.preview_mesh, done, fail,
                   row.get("type"), row.get("seed"), row.get("parts"))
        QTimer.singleShot(1500, lambda: self._check_viewer(row))

    def _check_viewer(self, row: dict) -> None:
        if self._current_row() is not row:
            return
        if getattr(self.viewer, "_failed", False) or getattr(self.viewer, "_error", ""):
            self._show_fallback(row, getattr(self.viewer, "_error", "") or "3D 初始化失败")

    def _show_current_raster(self) -> None:
        row = self._current_row()
        if row:
            self._show_fallback(row, "手动切换为渲染图")

    def _show_fallback(self, row: dict, msg: str) -> None:
        self.detail.setText(f"实时 3D 不可用（{msg}），显示服务端渲染。")

        def done(data: bytes) -> None:
            pix = QPixmap()
            pix.loadFromData(data, "PNG")
            self.fallback.setPixmap(pix)
            self.viewer.hide()
            self.fallback.show()

        def fail2(m: str) -> None:
            self.detail.setText(f"3D 与缩略图都不可用（{m}）")

        run_worker(self.svc.preview_png, done, fail2,
                   row.get("type"), row.get("seed"), row.get("parts"), 420)

    def _current_row(self) -> dict | None:
        items = self.results.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _save_snapshot(self) -> None:
        data = self.viewer.snapshot_png()
        if not data:
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存截图", "starforge-ship.png", "PNG (*.png)")
        if path:
            from pathlib import Path as _Path
            _Path(path).write_bytes(data)
            self.status.setText(f"截图已保存：{path}")

    def _copy_seed(self) -> None:
        row = self._current_row()
        if row:
            QGuiApplication.clipboard().setText(row.get("seed") or "")
            self.status.setText("种子已复制")

    def _open_write(self) -> None:
        row = self._current_row()
        if not row:
            notify.warn("先选中一艘飞船再写入存档")
            return
        dialog = WriteBackDialog(row, self)
        if dialog.exec() == QDialog.Accepted:
            self.status.setText("写入存档成功")
            notify.success("写入存档成功，已通过读回校验")

    def _update_fav_button(self, row: dict | None = None) -> None:
        row = row if row is not None else self._current_row()
        if not row:
            self.fav_btn.setText("收藏")
            return
        try:
            on = favorites.is_fav(row)
        except Exception:                                  # noqa: BLE001
            on = False
        self.fav_btn.setText("★ 已收藏" if on else "☆ 收藏")

    def _toggle_fav(self) -> None:
        row = self._current_row()
        if not row:
            self.status.setText("先选中一艘飞船再收藏")
            notify.warn("先选中一艘飞船再收藏")
            return
        try:
            now = favorites.toggle(row)
        except Exception as e:                             # noqa: BLE001
            self.status.setText(f"收藏失败：{e}")
            notify.error(f"收藏失败：{e}")
            return
        self._update_fav_button(row)
        if now:
            self.status.setText("已收藏")
            notify.success("已收藏")
        else:
            self.status.setText("已取消收藏")
            notify.warn("已取消收藏")

    def _open_favorites(self) -> None:
        dialog = FavoritesDialog(self)
        dialog.shipSelected.connect(self._load_favorite)
        dialog.exec()

    def _load_favorite(self, row: dict) -> None:
        if not row:
            return
        self._append_result(dict(row))
        self.status.setText(f"已从收藏夹载入 {row.get('seed') or ''}")
        self._update_fav_button(row)
        notify.success(f"已从收藏夹载入 {row.get('seed') or ''}")

    def _copy_share(self) -> None:
        row = self._current_row()
        if not row:
            self.status.setText("先选中一艘飞船再分享")
            notify.warn("先选中一艘飞船再分享")
            return
        try:
            code = favorites.encode_share(row)
        except Exception as e:                             # noqa: BLE001
            self.status.setText(f"无法生成分享码：{e}")
            notify.error(f"无法生成分享码：{e}")
            return
        QGuiApplication.clipboard().setText(code)
        self.status.setText("分享码已复制")
        notify.success("分享码已复制")

    def _import_share(self) -> None:
        text, ok = QInputDialog.getMultiLineText(
            self, "导入分享码", "粘贴他人分享码（nsh1:）：", "")
        if not ok:
            return
        if not text.strip():
            self.status.setText("分享码为空")
            notify.warn("分享码为空")
            return
        try:
            ref = favorites.decode_share(text)
        except Exception as e:                             # noqa: BLE001
            self.status.setText(f"分享码无效：{e}")
            notify.error(f"分享码无效：{e}")
            return
        self._append_result({"type": ref.type, "seed": ref.seed,
                             "parts": ref.parts or [], "name": ref.name,
                             "type_label": ref.type_label, "source": "share"})
        self.status.setText("分享码已载入")
        notify.success("分享码已载入")

    def _append_result(self, row: dict) -> None:
        key = ship_key(row)
        for i in range(self.results.count()):
            item = self.results.item(i)
            old = item.data(Qt.UserRole) or {}
            if ship_key(old) == key:
                self.results.clearSelection()
                self.results.setCurrentItem(item)
                item.setSelected(True)
                self.result_stack.setCurrentWidget(self.results)
                self._mark_compare_items()
                return
        item = QListWidgetItem(row.get("seed") or "")
        item.setData(Qt.UserRole, row)
        item.setToolTip(f"{row.get('type_label') or row.get('type')}  {row.get('seed')}")
        self.results.addItem(item)
        self.results.clearSelection()
        self.results.setCurrentItem(item)
        item.setSelected(True)
        self._results.append(row)
        self._thumb_queue.append(item)
        self._thumb_timer.start(50)
        self._mark_compare_items()
        self.error_banner.clear()
        self.result_stack.setCurrentWidget(self.results)
        self.result_info.setText(f"结果 {len(self._results)} 艘")

    def _export_glb(self) -> None:
        row = self._current_row()
        if not row:
            notify.warn("先选中一艘飞船再导出")
            return
        self.status.setText("正在导出 3D 模型（glb）…")

        def done(path: str) -> None:
            self.status.setText(f"3D 模型（glb）已生成：{path}")
            notify.success(f"3D 模型已导出：{path}")

        def fail(msg: str) -> None:
            self.status.setText(f"导出失败：{msg}")
            notify.error(f"导出失败：{msg}")

        run_worker(self.svc.glb_path, done, fail,
                   row.get("type"), row.get("seed"), row.get("parts"))
