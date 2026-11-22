"""飞船实验室：条件构建 → 结果网格 → 3D Inspector。"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox,
                               QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
                               QSpinBox, QStackedWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ...core import settings as settings_core
from ...services import favorites, get_services
from .. import notify
from ..dialogs.compare import MAX_COMPARE, CompareDialog, merge_compare, ship_key
from ..dialogs.favorites import FavoritesDialog
from ..dialogs.locate import LocateDialog
from ..dialogs.part_preview import PartPreviewDialog
from ..dialogs.write_back import WriteBackDialog
from ..widgets.feedback import EmptyState, ErrorBanner, LoadingOverlay
from ..widgets.game_push import GamePushButton
from ..widgets.lab_ui import WrapLabel, fixed_height, stretch_button
from ..widgets.page import PageSplitter, page_layout, scroll_panel
from ..widgets.page_header import PageHeader
from ..widgets.ship_card import install_card_delegate, set_card_accessibility
from ..widgets.ship_viewer import ShipViewer
from ..widgets.ui import Card, icon_from_png, placeholder_icon
from ..widgets.worker import run as run_worker

SHIPS = [("sentinel", "拦截机"), ("fighter", "战斗机"), ("hauler", "运输舰"),
         ("explorer", "探索舰"), ("shuttle", "穿梭机"), ("exotic", "异星"),
         ("living", "生物舰"), ("solar", "太阳帆")]

MAX_DEFAULT_WORKERS = 4

# 三栏最小宽度（含卡片内边距）；用 QSplitter 的最小尺寸保证 1180×760 下不重叠。
LAB_MIN_LEFT = 278
LAB_MIN_MIDDLE = 318
LAB_MIN_RIGHT = 336
# 结果网格：卡片宽度在 138–236 之间自适应，最多 4 列。
GRID_MIN_WIDTH = 138
GRID_MAX_WIDTH = 236
GRID_MAX_COLS = 4
GRID_GAP = 8


def default_workers(cpu_count: int | None = None) -> int:
    """搜索线程数：冻结版默认 1，避免 Windows spawn 子进程卡在 0 种子。"""
    if getattr(sys, "frozen", False):
        return 1
    try:
        total = int(cpu_count) if cpu_count is not None else int(os.cpu_count() or 1)
    except (TypeError, ValueError):
        total = 1
    return max(1, min(MAX_DEFAULT_WORKERS, total))


def format_estimate(estimate: dict | None, workers: int = 1) -> str:
    """把 ``search_estimate`` 的结果变成状态栏文案；无数据时返回空串。"""
    if not isinstance(estimate, dict) or estimate.get("ok") is False:
        return ""
    bits = []
    one_in = estimate.get("one_in")
    try:
        odds = int(round(float(one_in))) if one_in else 0
    except (TypeError, ValueError):
        odds = 0
    if odds > 0:
        bits.append(f"约 1 in {odds:,} 个种子命中")
    seconds = estimate.get("estimate_seconds")
    try:
        secs = float(seconds) if seconds is not None else None
    except (TypeError, ValueError):
        secs = None
    if secs is not None:
        bits.append(f"预计 {secs:g} 秒（单核）")
    if not bits:
        return ""
    text = "估算：" + "，".join(bits)
    workers = max(1, int(workers or 1))
    if workers > 1:
        text += f" · {workers} 线程"
    return text


class ShipLabPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._job = None
        self._loaded = False
        self._want: set[str] = set()
        self._avoid: set[str] = set()
        self._updating_checks = False
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
        self._part_preview_item: QTreeWidgetItem | None = None
        self._part_preview_timer = QTimer(self)
        self._part_preview_timer.setSingleShot(True)
        self._part_preview_timer.setInterval(120)
        self._part_preview_timer.timeout.connect(self._refresh_part_preview)
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
        root = page_layout(self)
        self.header = PageHeader(
            "飞船实验室",
            "条件 → 结果 → 3D：在左侧勾选部件，搜索并挑选飞船，再在右侧查看模型与操作。")
        # 换行副标题会让 PageHeader 的 sizeHint 偏高；改为可收缩，避免把整页最小高度撑大。
        self.header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        refresh = fixed_height(QPushButton("刷新部件"))
        refresh.setToolTip("重新读取当前船型的部件表")
        refresh.clicked.connect(self._refresh_parts)
        self.header.add_action(refresh)
        favorites_btn = fixed_height(QPushButton("收藏夹"))
        favorites_btn.setToolTip("管理已收藏飞船，可载入到实验室")
        favorites_btn.clicked.connect(self._open_favorites)
        self.header.add_action(favorites_btn)
        root.addWidget(self.header)

        split = PageSplitter("ship_lab")
        root.addWidget(split, 1)

        filters = self._build_filters()
        filters.setMinimumWidth(LAB_MIN_LEFT)
        results = self._build_results()
        results.setMinimumWidth(LAB_MIN_MIDDLE)
        inspector = scroll_panel(self._build_inspector())
        inspector.setMinimumWidth(LAB_MIN_RIGHT)

        split.addWidget(filters)
        split.addWidget(results)
        split.addWidget(inspector)
        # 只有中间结果区吸收多余宽度：拖动分栏时左右两侧保持稳定。
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.set_default_sizes([300, 540, 400])
        split.restore()
        split.splitterMoved.connect(lambda *_: self._fit_result_grid())
        QTimer.singleShot(0, self._fit_result_grid)

    def _build_filters(self) -> QWidget:
        """左侧筛选：上部条件卡片可滚动，底部搜索按钮固定可见。"""
        pane = QWidget()
        pv = QVBoxLayout(pane)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(8)

        wrap = Card("条件", "点部件 = 加入当前模式")
        v = wrap.v

        v.addWidget(QLabel("船型"))
        self.ship = QComboBox()
        for key, label in SHIPS:
            self.ship.addItem(label, key)
        self.ship.currentIndexChanged.connect(self._load_parts)
        v.addWidget(self.ship)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("模式"))
        self.mode = QComboBox()
        self.mode.addItem("想要", "want")
        self.mode.addItem("不要", "avoid")
        row.addWidget(self.mode, 1)
        clear = fixed_height(QPushButton("清空"))
        clear.clicked.connect(lambda: self._clear_checks(announce=True))
        row.addWidget(clear)
        v.addLayout(row)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("筛选部件名（如 PIT / WING）")
        self.filter.textChanged.connect(self._filter_parts)
        v.addWidget(self.filter)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["部件"])
        self.tree.setColumnCount(1)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setIconSize(QSize(40, 40))
        self.tree.setStyleSheet("QTreeWidget::item { height: 38px; }")
        self.tree.setMouseTracking(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumHeight(260)      # 至少 6 行，而不是被压成 3 行
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemClicked.connect(self._lazy_part_icon)
        self.tree.currentItemChanged.connect(self._on_part_current)
        v.addWidget(self.tree, 1)

        panel = QFrame()
        panel.setObjectName("card")
        ph = QHBoxLayout(panel)
        ph.setContentsMargins(8, 8, 8, 8)
        ph.setSpacing(8)
        self.part_thumb = QLabel()
        self.part_thumb.setFixedSize(72, 72)
        self.part_thumb.setAlignment(Qt.AlignCenter)
        ph.addWidget(self.part_thumb, 0, Qt.AlignTop)
        self.part_text = WrapLabel("悬停或点击部件查看预览与详情")
        self.part_text.setObjectName("muted")
        ph.addWidget(self.part_text, 1)
        self.part_3d_btn = fixed_height(QPushButton("3D"))
        self.part_3d_btn.setToolTip("在独立小窗中 3D 预览当前部件")
        self.part_3d_btn.clicked.connect(self._open_part_preview)
        ph.addWidget(self.part_3d_btn, 0, Qt.AlignTop)
        v.addWidget(panel)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(6)
        self.chips_detail = WrapLabel("未选择条件")
        self.chips_detail.setObjectName("muted")
        chips_row.addWidget(self.chips_detail, 1)
        self.chips = fixed_height(QPushButton("清除"))
        self.chips.setFlat(True)
        self.chips.setCursor(Qt.PointingHandCursor)
        self.chips.setToolTip("清除已选条件")
        self.chips.setStyleSheet(
            "QPushButton { border:none; background:transparent; color:#8b95a7;"
            " text-align:left; padding:0 2px; }"
            "QPushButton:hover { color:#e6ecf5; }"
            "QPushButton:disabled { color:#4f5a6b; }")
        self.chips.clicked.connect(lambda: self._clear_checks(announce=True))
        chips_row.addWidget(self.chips, 0, Qt.AlignTop)
        v.addLayout(chips_row)

        paint = QHBoxLayout()
        paint.setSpacing(6)
        self.look_on = QCheckBox("按涂装筛")
        paint.addWidget(self.look_on)
        paint.addStretch(1)
        v.addLayout(paint)

        paint_colors = QHBoxLayout()
        paint_colors.setSpacing(6)
        self.primary = fixed_height(QPushButton("主色"))
        self.primary.setStyleSheet("border-color:#8a6a2f;")
        self.primary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.primary.clicked.connect(lambda: self._pick_color("primary"))
        paint_colors.addWidget(self.primary, 1)
        self.secondary = fixed_height(QPushButton("副色"))
        self.secondary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.secondary.clicked.connect(lambda: self._pick_color("secondary"))
        paint_colors.addWidget(self.secondary, 1)
        v.addLayout(paint_colors)

        paint2 = QHBoxLayout()
        paint2.setSpacing(6)
        self.secondary_on = QCheckBox("副色也接近")
        paint2.addWidget(self.secondary_on)
        paint2.addWidget(QLabel("容差"))
        self.tol = QComboBox()
        for text, value in (("很接近 0.10", 0.10), ("接近 0.18", 0.18),
                            ("宽松 0.28", 0.28), ("很宽松 0.40", 0.40)):
            self.tol.addItem(text, value)
        self.tol.setCurrentIndex(1)
        self.tol.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        paint2.addWidget(self.tol, 1)
        v.addLayout(paint2)
        self._colors = {"primary": QColor("#f2c744"), "secondary": QColor("#1c1c22")}
        self._paint_buttons()

        budget_label = QLabel("搜索预算")
        budget_label.setToolTip("按百万种子计；越大越慢，但更容易命中稀有组合")
        v.addWidget(budget_label)
        self.budget = QSpinBox()
        self.budget.setRange(1, 2000)
        self.budget.setValue(200)
        self.budget.setSingleStep(10)
        self.budget.setSuffix(" 百万")
        v.addWidget(self.budget)

        workers_row = QHBoxLayout()
        workers_row.addWidget(QLabel("并行线程"))
        self.workers = QSpinBox()
        cpu_total = max(1, int(os.cpu_count() or 1))
        max_workers = 1 if getattr(sys, "frozen", False) else max(1, min(8, cpu_total))
        self.workers.setRange(1, max_workers)
        preferred = int(getattr(settings_core.current(), "workers", 0) or 0)
        self.workers.setValue(
            preferred if 1 <= preferred <= max_workers else default_workers(cpu_total))
        self.workers.setToolTip(
            "Windows 发布包默认 1；多进程搜索在部分机器会卡在 0 种子，稳定优先")
        workers_row.addWidget(self.workers, 1)
        v.addLayout(workers_row)

        pv.addWidget(scroll_panel(wrap), 1)

        # 底部固定操作区：窗口再矮也能直接点「开始搜索」。
        foot = QFrame()
        foot.setObjectName("card")
        fv = QVBoxLayout(foot)
        fv.setContentsMargins(12, 10, 12, 10)
        fv.setSpacing(6)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.search_btn = stretch_button(QPushButton("开始搜索"))
        self.search_btn.setObjectName("primary")
        self.search_btn.clicked.connect(self._start_search)
        row2.addWidget(self.search_btn, 1)
        self.cancel_btn = fixed_height(QPushButton("取消"))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_search)
        row2.addWidget(self.cancel_btn)
        demo = fixed_height(QPushButton("示例"))
        demo.clicked.connect(self._demo)
        row2.addWidget(demo)
        fv.addLayout(row2)
        self.estimate = WrapLabel("")
        self.estimate.setObjectName("muted")
        self.estimate.setAccessibleName("搜索估算")
        fv.addWidget(self.estimate)
        self.status = WrapLabel("选几个部件，点开始搜索")
        self.status.setObjectName("muted")
        fv.addWidget(self.status)
        pv.addWidget(foot)
        return pane

    def _build_results(self) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 0, 8, 0)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.result_info = WrapLabel("还没有结果")
        self.result_info.setObjectName("muted")
        bar.addWidget(self.result_info, 1)
        self.view_mode = QComboBox()
        self.view_mode.addItem("网格", "grid")
        self.view_mode.addItem("列表", "list")
        self.view_mode.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.view_mode.setMinimumWidth(76)
        self.view_mode.currentIndexChanged.connect(self._apply_view_mode)
        bar.addWidget(self.view_mode, 0)
        v.addLayout(bar)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.add_compare_btn = fixed_height(QPushButton("加入对比"))
        self.add_compare_btn.setToolTip("把选中的 1–3 艘飞船加入对比（Ctrl / Shift 可多选）")
        self.add_compare_btn.clicked.connect(self._add_selected_to_compare)
        actions.addWidget(self.add_compare_btn)
        self.compare_btn = fixed_height(QPushButton("对比 (0)"))
        self.compare_btn.setToolTip("并排对比 2–3 艘飞船")
        self.compare_btn.setEnabled(False)
        self.compare_btn.clicked.connect(self._open_compare)
        actions.addWidget(self.compare_btn)
        self.clear_compare_btn = fixed_height(QPushButton("清空对比"))
        self.clear_compare_btn.setEnabled(False)
        self.clear_compare_btn.clicked.connect(self._clear_compare)
        actions.addWidget(self.clear_compare_btn)
        actions.addStretch(1)
        v.addLayout(actions)

        actions2 = QHBoxLayout()
        actions2.setSpacing(6)
        self.clear_results_btn = fixed_height(QPushButton("清空结果"))
        self.clear_results_btn.setToolTip("清空当前结果列表（不影响对比）")
        self.clear_results_btn.clicked.connect(self._clear_results)
        actions2.addWidget(self.clear_results_btn)
        self.reset_conditions_btn = fixed_height(QPushButton("重置条件"))
        self.reset_conditions_btn.setToolTip("清除部件选择、涂装筛选与搜索预算")
        self.reset_conditions_btn.clicked.connect(self._reset_conditions)
        actions2.addWidget(self.reset_conditions_btn)
        actions2.addStretch(1)
        v.addLayout(actions2)
        self.error_banner = ErrorBanner("", box)
        self.error_banner.set_retry_callback(self._start_search)
        v.addWidget(self.error_banner)
        self.results = QListWidget()
        self.results.setViewMode(QListWidget.IconMode)
        self.results.setResizeMode(QListWidget.Adjust)
        self.results.setMovement(QListWidget.Static)
        self.results.setWordWrap(False)
        self.results.setMinimumHeight(240)
        self.results.setFocusPolicy(Qt.StrongFocus)
        self.results.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results.setAccessibleName("搜索结果")
        self.results.setAccessibleDescription("飞船卡片列表；Ctrl 或 Shift 可多选")
        self._card_delegate = install_card_delegate(self.results, 110)
        # 结果区宽度变化（拖分栏/窗口缩放）时重算列数与卡片尺寸。
        self.results.viewport().installEventFilter(self)
        self.results.itemSelectionChanged.connect(self._select_result)
        self.results.itemDoubleClicked.connect(lambda _i: self._copy_seed())
        self.empty = EmptyState(
            "还没有搜索结果",
            "选好部件后点「开始搜索」；结果会显示在这里。",
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
        self.title = WrapLabel("未选择飞船")
        self.title.setStyleSheet("font-size:15px;font-weight:700;")
        v.addWidget(self.title)
        self.viewer = ShipViewer()
        self.viewer.setMinimumHeight(280)
        v.addWidget(self.viewer, 1)
        self.fallback = QLabel()
        self.fallback.setAlignment(Qt.AlignCenter)
        self.fallback.setWordWrap(True)
        self.fallback.setMinimumHeight(280)
        self.fallback.hide()
        v.addWidget(self.fallback, 1)

        # 视角按钮 3 列 2 行：窄栏不挤压、不用固定宽度。
        view_grid = QGridLayout()
        view_grid.setHorizontalSpacing(6)
        view_grid.setVerticalSpacing(6)
        view_buttons = [(text, mode) for text, mode in
                        (("等轴", "iso"), ("俯视", "top"), ("侧视", "side"),
                         ("正视", "front"))]
        for index, (text, mode) in enumerate(view_buttons):
            b = stretch_button(QPushButton(text))
            b.clicked.connect(lambda _=False, m=mode: self.viewer.set_view(m))
            view_grid.addWidget(b, index // 3, index % 3)
        spin = stretch_button(QPushButton("自转"))
        spin.setCheckable(True)
        spin.toggled.connect(self.viewer.set_spin)
        view_grid.addWidget(spin, 1, 1)
        shot = stretch_button(QPushButton("截图"))
        shot.clicked.connect(self._save_snapshot)
        view_grid.addWidget(shot, 1, 2)
        for column in range(3):
            view_grid.setColumnStretch(column, 1)
        v.addLayout(view_grid)

        self.detail = WrapLabel("选中结果后在这里查看 3D 模型与操作。")
        self.detail.setObjectName("muted")
        v.addWidget(self.detail)

        # 动作 3 列网格：窄栏不会把最右按钮挤出卡片，也给 3D 区留出高度。
        actions = QGridLayout()
        actions.setHorizontalSpacing(6)
        actions.setVerticalSpacing(6)
        self.copy_btn = stretch_button(QPushButton("复制种子"))
        self.copy_btn.clicked.connect(self._copy_seed)
        self.fav_btn = stretch_button(QPushButton("收藏"))
        self.fav_btn.clicked.connect(self._toggle_fav)
        self.share_btn = stretch_button(QPushButton("分享码"))
        self.share_btn.setToolTip("复制当前飞船的 nsh1: 分享码")
        self.share_btn.clicked.connect(self._copy_share)
        self.raster_btn = stretch_button(QPushButton("渲染图"))
        self.raster_btn.clicked.connect(self._show_current_raster)
        self.locate_btn = stretch_button(QPushButton("查星系"))
        self.locate_btn.setToolTip("反查该种子可能来自的星系；候选需生成器证实，可能欠定")
        self.locate_btn.clicked.connect(self._locate_seed)
        self.glb_btn = stretch_button(QPushButton("导出 glb"))
        self.glb_btn.clicked.connect(self._export_glb)
        self.write_btn = stretch_button(QPushButton("写入存档"))
        self.write_btn.setEnabled(False)
        self.write_btn.setToolTip("写入同型号槽位；先备份，写入后读回校验")
        self.write_btn.clicked.connect(self._open_write)
        self.push_btn = stretch_button(GamePushButton(self.svc, self))
        self.import_btn = stretch_button(QPushButton("导入分享"))
        self.import_btn.setToolTip("粘贴他人分享的 nsh1: 分享码")
        self.import_btn.clicked.connect(self._import_share)
        for index, button in enumerate((self.copy_btn, self.fav_btn,
                                        self.share_btn, self.raster_btn,
                                        self.locate_btn, self.glb_btn,
                                        self.write_btn, self.push_btn,
                                        self.import_btn)):
            actions.addWidget(button, index // 3, index % 3)
        for column in range(3):
            actions.setColumnStretch(column, 1)
        v.addLayout(actions)
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
            self._want.clear()
            self._avoid.clear()
            self._updating_checks = True
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
            self._updating_checks = False
            self._update_chips()
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

    def _on_part_current(self, item: QTreeWidgetItem | None, *_args) -> None:
        if item is None:
            return
        self._part_preview_item = item
        self._part_preview_timer.start()

    def _refresh_part_preview(self) -> None:
        item = self._part_preview_item
        if item is None:
            return
        part = item.data(0, Qt.UserRole)
        if not part:
            return
        gid = item.data(0, Qt.UserRole + 1) or item.text(1)
        ship = self.ship.currentData()
        self.part_text.setText(f"{part}  ·  组 {gid}\n读取预览…")

        def done(data: bytes | None) -> None:
            if data:
                pix = QPixmap()
                pix.loadFromData(data, "PNG")
                if not pix.isNull():
                    self.part_thumb.setPixmap(pix)
                    self.part_text.setText(f"{part}  ·  组 {gid}")
                    return
            self.part_text.setText(f"{part}  ·  组 {gid}\n该部件没有可渲染的几何（结构件/空槽）")

        run_worker(self.svc.part_icon, done,
                   lambda m: self.part_text.setText(f"{part} 预览失败：{m}"),
                   ship, part, 96)

    def _lazy_part_icon(self, item: QTreeWidgetItem, _column: int) -> None:
        self._on_part_current(item)
        self._refresh_part_preview()
        part = item.data(0, Qt.UserRole)
        ship = self.ship.currentData()
        if part and ship:
            self._load_part_3d_icon(item, ship, part)

    def _open_part_preview(self) -> None:
        item = self.tree.currentItem() or self._part_preview_item
        if item is None:
            notify.warn("先选择一个部件")
            return
        part = str(item.data(0, Qt.UserRole) or "")
        if not part:
            notify.warn("先选择一个部件")
            return
        PartPreviewDialog(str(self.ship.currentData() or ""), part, self).exec()

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
        # 条件独立于当前模式：切换“想要/不要”不会改写已选条件。
        return sorted(self._want), sorted(self._avoid)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating_checks or column != 0:
            return
        part = item.data(0, Qt.UserRole)
        if not part:
            return
        checked = item.checkState(0) == Qt.Checked
        if checked:
            if self.mode.currentData() == "avoid":
                self._avoid.add(part)
                self._want.discard(part)
                item.setForeground(0, QBrush(QColor("#f2765c")))
            else:
                self._want.add(part)
                self._avoid.discard(part)
                item.setForeground(0, QBrush(QColor("#49d19a")))
        else:
            self._want.discard(part)
            self._avoid.discard(part)
            item.setForeground(0, QBrush(QColor("#e2e7f0")))
        self._update_chips()

    def _update_chips(self, *_args) -> None:
        want, avoid = self._checked()
        bits = []
        if want:
            bits.append("要：" + " ".join(want[:6]) + ("…" if len(want) > 6 else ""))
        if avoid:
            bits.append("不要：" + " ".join(avoid[:6]) + ("…" if len(avoid) > 6 else ""))
        summary = "  ·  ".join(bits)
        self.chips_detail.setText(summary or "未选择条件")
        self.chips.setEnabled(bool(summary))
        self.chips.setToolTip("清除已选条件" if summary else "还没有选择条件")

    def _clear_checks(self, announce: bool = False) -> None:
        want, avoid = self._checked()
        self._updating_checks = True
        try:
            for i in range(self.tree.topLevelItemCount()):
                top = self.tree.topLevelItem(i)
                for j in range(top.childCount()):
                    top.child(j).setCheckState(0, Qt.Unchecked)
        finally:
            self._updating_checks = False
        self._want.clear()
        self._avoid.clear()
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
        self.secondary_on.setChecked(False)
        self.tol.setCurrentIndex(1)
        self._colors = {"primary": QColor("#f2c744"), "secondary": QColor("#1c1c22")}
        self._paint_buttons()
        self.budget.setValue(200)
        self.workers.setValue(default_workers())
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
        self.push_btn.set_ship(None)
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
            "选好部件后点「开始搜索」；结果会显示在这里。",
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
            text = "#0a0c11" if c.lightness() > 145 else "#e2e7f0"
            btn.setText(f"{labels[role]} {c.name()}")
            btn.setStyleSheet(
                f"border:1px solid {c.name()}; border-radius:6px;"
                f" background:{c.name()}; color:{text}; padding:5px 8px;")

    def _demo(self) -> None:
        if not self.tree.topLevelItemCount():
            notify.warn("部件表尚未加载完成，请稍后再试")
            return
        # 选第一组第一个部件作为示例
        top = self.tree.topLevelItem(0)
        if top and top.childCount():
            self.mode.setCurrentIndex(0)
            top.child(0).setCheckState(0, Qt.Checked)
        self._update_chips()
        self.status.setText("已填入示例条件")
        notify.success("已填入示例条件")

    # ---------------------------------------------------------------- 搜索

    def _show_estimate(self, payload: dict, workers: int) -> None:
        """后台估算 1 in N / 预计秒数；绝不在 UI 线程跑目录/生成器查询。"""
        fn = getattr(self.svc, "search_estimate", None)
        if not callable(fn):
            self.estimate.setText("")
            return
        self.estimate.setText("估算中…")

        def done(res: dict) -> None:
            self.estimate.setText(format_estimate(res, workers))

        def fail(_msg: str) -> None:
            self.estimate.setText("")

        run_worker(fn, done, fail, dict(payload))

    def _start_search(self) -> None:
        want, avoid = self._checked()
        if not want and not avoid:
            self.status.setText("至少勾选一个部件")
            notify.warn("至少勾选一个部件再搜索")
            return
        look = None
        if self.look_on.isChecked():
            c = self._colors["primary"]
            look = {"primary": [c.redF(), c.greenF(), c.blueF()],
                    "tol": float(self.tol.currentData() or 0.18)}
            if self.secondary_on.isChecked():
                c2 = self._colors["secondary"]
                look["secondary"] = [c2.redF(), c2.greenF(), c2.blueF()]
        workers = max(1, int(self.workers.value() or 1))
        payload = {"ship": self.ship.currentData(), "want": want, "avoid": avoid,
                   "look": look, "limit": 24,
                   "max_seeds": int(self.budget.value()) * 1_000_000,
                   "time_limit": 180.0, "workers": workers}
        self._show_estimate(payload, workers)
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
                set_card_accessibility(item, row)
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
            self._fit_result_grid()
        else:
            from PySide6.QtWidgets import QStyledItemDelegate
            self.results.setItemDelegate(QStyledItemDelegate(self.results))
            self.results.setIconSize(QSize(72, 50))
            self.results.setGridSize(QSize())
            self.results.setSpacing(4)

    def _fit_result_grid(self) -> None:
        """按结果区实际宽度决定列数与卡片尺寸，避免窄栏只挤下一列。"""
        if self.results.viewMode() != QListWidget.IconMode or not hasattr(self, "_card_delegate"):
            return
        viewport = self.results.viewport().width()
        if viewport <= 0:
            return
        cols = max(1, min(GRID_MAX_COLS,
                          (viewport + GRID_GAP) // (GRID_MIN_WIDTH + GRID_GAP)))
        while cols > 1 and (viewport - GRID_GAP * (cols - 1)) // cols < GRID_MIN_WIDTH:
            cols -= 1
        cell = max(GRID_MIN_WIDTH,
                   min(GRID_MAX_WIDTH, (viewport - GRID_GAP * (cols - 1)) // cols))
        icon = max(64, min(110, cell - 40))
        card_h = icon + 68
        self._card_delegate.icon_size = icon
        self._card_delegate.size = QSize(cell - GRID_GAP, card_h)
        self.results.setSpacing(GRID_GAP)
        self.results.setIconSize(QSize(icon, icon))
        self.results.setGridSize(QSize(cell, card_h + GRID_GAP))

    def eventFilter(self, obj, event) -> bool:           # noqa: N802 - Qt 回调
        results = getattr(self, "results", None)
        if results is not None and obj is results.viewport() and \
                event.type() in (QEvent.Resize, QEvent.Show):
            self._fit_result_grid()
        return super().eventFilter(obj, event)

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
            in_compare = key in keys
            item.setData(Qt.UserRole + 1, in_compare)
            item.setToolTip(base + ("\n已加入对比" if in_compare else ""))
            set_card_accessibility(item, row, in_compare=in_compare)

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
        self.push_btn.set_ship(row)
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
            pix.loadFromData(data or b"", "PNG")
            if not pix.isNull():
                pix = pix.scaled(360, 360, Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation)
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

    def _locate_seed(self) -> None:
        row = self._current_row()
        seed = str((row or {}).get("seed") or "").strip()
        if not seed:
            self.status.setText("先选中一艘飞船再反查星系")
            notify.warn("先选中一艘飞船再反查星系")
            return
        self.status.setText(f"正在反查 {seed} 所在星系…")
        dialog = LocateDialog(seed, self)
        dialog.exec()

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

    def open_favorites(self) -> None:
        self._open_favorites()

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
        set_card_accessibility(item, row)
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
