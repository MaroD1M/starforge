"""我的船队：存档 → 船只网格 → 3D 详情。"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...export import export_zip
from ...services import get_services
from .. import notify
from ..dialogs.backup import BackupDialog
from ..dialogs.class_editor import ClassEditorDialog
from ..dialogs.save_edit import SaveEditDialog
from ..dialogs.save_extras import SaveExtrasDialog
from ..widgets.feedback import EmptyState, ErrorBanner, LoadingOverlay
from ..widgets.fleet_companion import FleetCompanionPanel
from ..widgets.fleet_flow import FleetFlowBar
from ..widgets.game_push import GamePushButton
from ..widgets.page import PageSplitter, page_layout
from ..widgets.page_header import PageHeader
from ..widgets.pets_view import PetsView
from ..widgets.ship_card import install_card_delegate
from ..widgets.ship_viewer import ShipViewer
from ..widgets.ui import (
    Card,
    ElidedLabel,
    danger_button,
    ghost_button,
    icon_from_png,
    muted,
)
from ..widgets.ux import TaskFlow
from ..widgets.worker import run as run_worker

STAT_LABELS = {"damage": "伤害", "shield": "护盾", "hyperdrive": "超空间驱动",
               "agility": "机动性"}
FRIGATE_HEADERS = ("名称", "类型", "等级", "伤害", "探索", "采矿", "外交",
                   "燃料消耗", "速度", "远征次数", "状态", "种子")
MULTITOOL_HEADERS = ("名称", "等级", "型号", "槽位", "种子", "当前使用")
FREIGHTER_HEADERS = ("字段", "值")
EMPTY_WRITE_PREVIEW = "写回预览：选中一艘有槽位的飞船后，在这里查看 before / after。"


class _FitPixmapLabel(QLabel):
    """按可用宽度缩放预览图，且不把图片原始宽度当成最小宽度。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = QPixmap()
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

    def setPixmap(self, pix: QPixmap) -> None:
        self._source = QPixmap(pix) if pix is not None and not pix.isNull() else QPixmap()
        self._apply()

    def _apply(self) -> None:
        if self._source.isNull():
            # 没有图片时保留现有文字（固定模型说明）；setPixmap 会清空 QLabel 文本。
            if not self.text().strip():
                QLabel.setPixmap(self, QPixmap())
            return
        width = max(160, self.width() - 8)
        pix = self._source
        if pix.width() > width:
            pix = pix.scaledToWidth(width, Qt.SmoothTransformation)
        QLabel.setPixmap(self, pix)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply()

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)


def _text(value, fallback: str = "—") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _stat_text(values: dict | None) -> str:
    data = values or {}
    bits = [f"{STAT_LABELS.get(key, key)} {value}"
            for key, value in data.items() if value is not None]
    return " · ".join(bits) or "无属性数据"


def _write_snapshot(data: dict | None) -> tuple[str, str]:
    """存档摘要 / writer.apply_class 的 before/after →（等级, 属性摘要）。"""
    data = data or {}
    ship_class = _text(data.get("class") or data.get("ship_class"), "未知")
    stats = data.get("stats")
    if isinstance(stats, list):
        from ...data.shipref import stats_summary

        stats = stats_summary(data)
    return ship_class, _stat_text(stats if isinstance(stats, dict) else None)


def write_preview_lines(ship: dict | None, result: dict | None = None) -> list[str]:
    """写回/改级的 before/after 预览（纯文本，便于测试同一口径）。"""
    before_class, before_stats = _write_snapshot(ship)
    lines = ["写回预览（先自动备份；可写入副本，原档不动）",
             f"写回前：{before_class} 级 · {before_stats}"]
    after = (result or {}).get("after") if isinstance(result, dict) else None
    if isinstance(after, dict):
        after_class, after_stats = _write_snapshot(after)
        lines.append(f"写回后：{after_class} 级 · {after_stats}")
    else:
        lines.append("写回后：在「船级/属性…」对话框里确认 before → after")
    return lines


def primary_action(ship: dict | None, can_write: bool, can_push: bool,
                   busy: bool = False) -> str:
    """详情区唯一主操作的上下文选择：写回存档 / 送进游戏 / 无。"""
    if busy or not isinstance(ship, dict) or not ship:
        return "none"
    if can_write:
        return "write"
    if can_push:
        return "push"
    return "none"


def frigate_rows(items: list[dict] | None) -> list[list[str]]:
    rows = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        stats = item.get("stats") or {}
        rows.append([
            _text(item.get("name"), "(未命名)"),
            _text(item.get("type")),
            _text(item.get("class")),
            _text(stats.get("Combat"), "0"),
            _text(stats.get("Exploration"), "0"),
            _text(stats.get("Mining"), "0"),
            _text(stats.get("Diplomacy"), "0"),
            _text(stats.get("Fuel burn rate"), "0"),
            _text(stats.get("Speed"), "0"),
            _text(item.get("expeditions"), "0"),
            "受损" if item.get("damaged") else "正常",
            _text(item.get("seed")),
        ])
    return rows


def multitool_rows(items: list[dict] | None) -> list[list[str]]:
    rows = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        rows.append([
            _text(item.get("name"), "(未命名)"),
            _text(item.get("class")),
            _text(item.get("model")),
            _text(item.get("slots"), "0"),
            _text(item.get("seed")),
            "是" if item.get("active") else "",
        ])
    return rows


def freighter_rows(freighter: dict | None) -> list[list[str]]:
    data = freighter or {}
    filename = _text(data.get("filename"), "")
    return [
        ["型号", filename.rsplit("/", 1)[-1] if filename else "—"],
        ["完整路径", filename or "—"],
        ["种子", _text(data.get("seed"))],
        ["母星系种子", _text(data.get("home"))],
    ]


def _write_export(path: str, items: list[dict]) -> dict:
    """后台线程：生成 zip 并落盘，返回纯数据给 UI。"""
    data, stats = export_zip(items)
    Path(path).write_bytes(data)
    return {"path": path, **stats}


class FleetPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._loaded = False
        self._save_path = ""
        self._loaded_path = ""
        self._exporting = False
        self._loading = False
        self._editing = False
        self._restoring = False
        self._watched_path = ""
        self._watch_ignore_until = 0.0
        self._ships: list[dict] = []
        self._write_result: dict | None = None
        self._extras: dict = {}
        self._extras_loaded = False
        self._extras_loading = False
        self._sort_key = "type"
        self._sort_desc = False
        self._thumb_queue: list[QListWidgetItem] = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._next_thumb)
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.timeout.connect(self._on_watch_timeout)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_save_file_changed)
        self._build_ui()
        self.loading_overlay = LoadingOverlay(self, "正在读取存档…")
        self.loading = self.loading_overlay
        self.overlay = self.loading_overlay
        self.empty = self.empty_state
        self.error = self.error_banner
        self._update_ship_empty()

    def _build_ui(self) -> None:
        root = page_layout(self)

        self.header = PageHeader(
            "我的船队", "读存档 → 选一项 → 执行；写回会先自动备份。")
        # PageHeader 默认垂直策略是 Minimum（sizeHint 即最小高度），
        # 会把整页最小高度抬到页头 sizeHint；这里允许压缩，矮窗口才不被裁。
        self.header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.header.subtitle.setWordWrap(False)
        self.header.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.header.subtitle.setToolTip(self.header.subtitle.text())
        root.addWidget(self.header)

        # 一屏一条路径：① 读存档 → ② 选一项 → ③ 执行。
        self.flow = TaskFlow(["读存档", "选一项", "执行"])
        root.addWidget(self.flow)

        root.addWidget(self._build_toolbar())

        # 主从表：左边列表/标签页，右边详情；详情默认收起，选中行后才出现。
        split = PageSplitter("fleet-main-v2")
        self.split = split
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)

        mid = QWidget()
        mid.setMinimumWidth(340)
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(8, 0, 8, 0)
        self.tabs = QTabWidget()
        mv.addWidget(self.tabs, 1)

        ship_tab = QWidget()
        sv = QVBoxLayout(ship_tab)
        sv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.result_info = ElidedLabel("还没有飞船")
        self.result_info.setObjectName("muted")
        self.result_info.setToolTip("读取存档后显示飞船数量")
        bar.addWidget(self.result_info, 1)

        self.sort_mode = QComboBox()
        self.sort_mode.addItem("按类型", "type")
        self.sort_mode.addItem("按等级", "class")
        self.sort_mode.addItem("按种子", "seed")
        self.sort_mode.setToolTip("排序方式")
        self.sort_mode.currentIndexChanged.connect(self._apply_sort)
        bar.addWidget(self.sort_mode)

        self.sort_order = QComboBox()
        self.sort_order.addItem("升序", False)
        self.sort_order.addItem("降序", True)
        self.sort_order.setToolTip("排序方向")
        self.sort_order.currentIndexChanged.connect(self._apply_sort)
        bar.addWidget(self.sort_order)

        self.view_mode = QComboBox()
        self.view_mode.addItem("卡片", "grid")
        self.view_mode.addItem("列表", "list")
        self.view_mode.setToolTip("卡片或列表；列表一屏能看更多")
        self.view_mode.currentIndexChanged.connect(self._apply_view_mode)
        bar.addWidget(self.view_mode)

        sv.addLayout(bar)

        self.error_banner = ErrorBanner()
        self.error_banner.set_retry_callback(self._load)
        sv.addWidget(self.error_banner)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setWordWrap(False)
        self._card_delegate = install_card_delegate(self.list, 110)
        self.list.itemSelectionChanged.connect(self._select)
        sv.addWidget(self.list, 1)

        self.empty_state = EmptyState(
            "没有存档", "先选择 save.hg，再点「读取存档」。",
            icon="◇", button_text="读取存档")
        self.empty_state.set_action("读取存档", self._load)
        for label in (self.empty_state.title_label, self.empty_state.description_label):
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            label.setMinimumWidth(0)
        sv.addWidget(self.empty_state, 1)
        self.tabs.addTab(ship_tab, "飞船")

        # 同伴详情统一放到右侧详情区（来源、符文、动物联查与动作）。
        self.pets = PetsView(self.svc, inline_detail=False, auto_select=False)
        self.tabs.addTab(self.pets, "同伴")

        self.frigates_table = self._extra_table(FRIGATE_HEADERS)
        self.frigates_page = self._extra_page(self.frigates_table)
        self.tabs.addTab(self.frigates_page, "护卫舰")
        self.tabs.setTabToolTip(self.tabs.count() - 1, "护卫舰（只读）")
        self.multitools_table = self._extra_table(MULTITOOL_HEADERS)
        self.multitools_page = self._extra_page(self.multitools_table)
        self.tabs.addTab(self.multitools_page, "工具")
        self.tabs.setTabToolTip(self.tabs.count() - 1, "多用途工具（只读）")
        self.freighter_table = self._extra_table(FREIGHTER_HEADERS)
        self.freighter_page = self._extra_page(self.freighter_table)
        self.tabs.addTab(self.freighter_page, "货船")
        self.tabs.setTabToolTip(self.tabs.count() - 1, "货船（只读）")
        for table in (self.frigates_table, self.multitools_table, self.freighter_table):
            table.itemSelectionChanged.connect(self._extra_selected)
        self.tabs.currentChanged.connect(self._tab_changed)
        split.addWidget(mid)

        # 详情卡没有常驻标题：标题行就是选中项名称 + 右上角收起按钮。
        right = Card()
        self.detail_card = right
        right.setMinimumWidth(320)
        rv = right.v
        head = QHBoxLayout()
        head.setSpacing(6)
        self.title = QLabel("未选择飞船")
        self.title.setStyleSheet("font-size:15px;font-weight:700;")
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        self.detail_close = QPushButton("×")
        self.detail_close.setObjectName("uxIconButton")
        self.detail_close.setFixedSize(24, 24)
        self.detail_close.setToolTip("收起详情，把空间还给列表")
        self.detail_close.setAccessibleName("收起详情")
        self.detail_close.clicked.connect(self._close_detail)
        head.addWidget(self.detail_close, 0, Qt.AlignTop)
        rv.addLayout(head)

        # 预览区（3D / 静态图 / 固定模型说明）单独成块并保留最小高度，
        # 矮窗口时优先压缩下方属性文字，不把预览压扁。
        preview = QWidget()
        pv = QVBoxLayout(preview)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(4)
        self.viewer = ShipViewer()
        self.viewer.setMinimumHeight(240)
        pv.addWidget(self.viewer, 1)
        self.fallback = _FitPixmapLabel()
        self.fallback.setAlignment(Qt.AlignCenter)
        self.fallback.setWordWrap(True)
        self.fallback.setMinimumHeight(240)
        self.fallback.hide()
        pv.addWidget(self.fallback, 1)
        self.pets_note = QLabel(
            "同伴：可从存档 UA 解出来源星球的 12 位符文并复制；3D 预览仍需要生物生成器。")
        self.pets_note.setWordWrap(True)
        self.pets_note.setAlignment(Qt.AlignCenter)
        self.pets_note.setMinimumHeight(240)
        self.pets_note.hide()
        pv.addWidget(self.pets_note, 1)
        preview.setMinimumHeight(240)
        self.preview_pane = preview
        rv.addWidget(preview, 1)

        # 同伴选中后，右栏整体切换为来源行星 + 符文 + 动物联查。
        self.companion = FleetCompanionPanel(self.svc)
        self.companion.bind_pets(self.pets)
        self.companion.hide()
        rv.addWidget(self.companion, 1)
        self.pets.selectionChanged.connect(self._companion_selected)

        self.detail = muted("选中一艘飞船后在这里查看 3D 模型、等级与属性。")
        self.detail.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        rv.addWidget(self.detail)
        self.write_preview = muted(EMPTY_WRITE_PREVIEW)
        rv.addWidget(self.write_preview)
        self.action_note = muted("")
        rv.addWidget(self.action_note)
        buttons = FleetFlowBar()
        self.copy_btn = ghost_button("复制种子", "复制选中飞船的种子")
        self.copy_btn.clicked.connect(self._copy_seed)
        buttons.addWidget(self.copy_btn)
        self.write_btn = danger_button(
            "写回存档…", "修改选中飞船的等级/属性并写回存档；先自动备份，可写入副本")
        self.write_btn.setEnabled(False)
        self.write_btn.clicked.connect(self._open_class_editor)
        self.edit_btn = self.write_btn              # 兼容旧调用名
        buttons.addWidget(self.write_btn)
        self.push_btn = GamePushButton(self.svc, self)
        self.push_btn.setObjectName("ghostButton")
        buttons.addWidget(self.push_btn)
        rv.addWidget(buttons)
        # 只读扩展没有预览/动作时，用一个弹性空白把标题与内容顶到上方，
        # 避免 QVBoxLayout 把标题行和正文拉开。
        self.card_spacer = QWidget()
        self.card_spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.card_spacer.hide()
        rv.addWidget(self.card_spacer, 1)
        split.addWidget(right)
        split.set_default_sizes([760, 360])
        split.restore()
        right.setVisible(False)

        root.addWidget(split, 1)

        # 状态消息只在窗口状态栏显示；没有状态栏时（单独构造页面）写到这里，
        # 不占页面高度。
        self.info = muted("")
        self.info.setParent(self)
        self.info.hide()
        self._update_actions()
        self._sync_flow()

    def _build_toolbar(self) -> QWidget:
        """顶部只回答两件事：当前是哪个存档、怎么换一个文件。"""
        bar = QFrame()
        bar.setObjectName("uxToolbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(8)

        self.save_current = ElidedLabel("尚未读取存档")
        self.save_current.setObjectName("muted")
        self.save_current.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.save_current.setToolTip("点「浏览…」选择 save.hg")
        self.save_current.setAccessibleName("当前存档：未选择")
        h.addWidget(self.save_current, 1)

        self.load_btn = QPushButton("读取存档")
        self.load_btn.setObjectName("primary")
        self.load_btn.setToolTip("读取当前存档中的飞船与同伴")
        self.load_btn.clicked.connect(self._load)
        h.addWidget(self.load_btn)

        self.browse_btn = QPushButton("浏览…")
        self.browse_btn.setObjectName("ghostButton")
        self.browse_btn.setToolTip("选择另一个 save.hg 并读取（不改存档内容）")
        self.browse_btn.clicked.connect(self._browse)
        h.addWidget(self.browse_btn)

        self.more_btn = QPushButton("更多 ▾")
        self.more_btn.setObjectName("ghostButton")
        self.more_btn.setToolTip("备份恢复、存档编辑、扩展编辑与批量导出")
        self.more_menu = QMenu(self.more_btn)
        self.backup_btn = QAction("备份恢复…", self)
        self.backup_btn.triggered.connect(self._open_backups)
        self.more_menu.addAction(self.backup_btn)
        self.save_edit_btn = QAction("存档编辑…", self)
        self.save_edit_btn.setEnabled(False)
        self.save_edit_btn.setToolTip("修改存档中的货币与飞船名称/涂装；先备份，可写入副本")
        self.save_edit_btn.triggered.connect(self._open_save_edit)
        self.more_menu.addAction(self.save_edit_btn)
        self.extras_btn = QAction("扩展编辑…", self)
        self.extras_btn.setEnabled(False)
        self.extras_btn.setToolTip("编辑库存、词语/知识、任务与奖励；先备份，可写入副本")
        self.extras_btn.triggered.connect(self._open_save_extras)
        self.more_menu.addAction(self.extras_btn)
        self.more_menu.addSeparator()
        self.export_btn = QAction("批量导出…", self)
        self.export_btn.setEnabled(False)
        self.export_btn.setToolTip(
            "把当前存档中的飞船导出为 ZIP（含 3D glb、预览图与清单）")
        self.export_btn.triggered.connect(self._export_all)
        self.more_menu.addAction(self.export_btn)
        self.more_btn.setMenu(self.more_menu)
        h.addWidget(self.more_btn)
        return bar

    # ---------------------------------------------------------------- 数据

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._auto()

    def _set_save_path(self, path: str) -> None:
        """工具栏只显示文件名；完整路径放在 tooltip。"""
        self._save_path = str(path or "").strip()
        name = Path(self._save_path).name if self._save_path else ""
        self.save_current.setText(name or "尚未读取存档")
        self.save_current.setToolTip(self._save_path or "点「浏览…」选择 save.hg")
        self.save_current.setAccessibleName(f"当前存档：{name or '未选择'}")

    # ---------------------------------------------------------------- 任务步骤

    def _current_extra_table(self) -> QTableWidget | None:
        widget = self.tabs.currentWidget()
        for page, table in ((self.frigates_page, self.frigates_table),
                            (self.multitools_page, self.multitools_table),
                            (self.freighter_page, self.freighter_table)):
            if widget is page:
                return table
        return None

    def _has_selection(self) -> bool:
        if self.tabs.currentWidget() is self.pets:
            return bool(self.pets.selected_creature())
        table = self._current_extra_table()
        if table is not None:
            return bool(table.selectionModel().selectedRows())
        return bool(self.list.selectedItems())

    def _sync_flow(self) -> None:
        """① 读存档 → ② 选一项 → ③ 执行；只表达当前位置。"""
        if not self._loaded_path:
            self.flow.set_active(0)
        elif self._has_selection():
            self.flow.set_active(2, done=(0, 1))
        else:
            self.flow.set_active(1, done=(0,))

    def _show_detail_card(self) -> None:
        # 详情默认隐藏；展开时把分栏宽度还给右栏，列表仍然可读。
        if not self.detail_card.isVisible():
            total = max(1, self.split.width() - self.split.handleWidth())
            right = min(400, max(320, total // 3))
            self.detail_card.setVisible(True)
            self.split.setSizes([max(320, total - right), right])

    def _hide_detail_card(self) -> None:
        self.detail_card.setVisible(False)

    def _close_detail(self) -> None:
        if self.tabs.currentWidget() is self.pets:
            self.pets.clear_selection()
            self.companion.set_creature({})
            self.companion.hide()
        else:
            table = self._current_extra_table()
            if table is not None:
                table.clearSelection()
            else:
                self.list.clearSelection()
                self.list.setCurrentItem(None)
        self._hide_detail_card()
        self._sync_flow()

    def _auto(self) -> None:
        if self._save_path:
            self._load()
            return

        def done(res: dict) -> None:
            p = res.get("path") or ""
            if p:
                self._set_save_path(p)
                self._load()
            else:
                self._set_save_path("")
                text = "没有自动找到存档；点「浏览…」选择 save.hg。"
                self._status(text)
                self._show_ship_empty("没有存档", text)

        def fail(msg: str) -> None:
            text = "未自动找到存档；点「浏览…」选择 save.hg。"
            self._set_save_path("")
            self._status(text)
            self.info.setToolTip(msg)
            self._show_ship_empty("没有存档", text)

        run_worker(self.svc.default_save, done, fail)

    def _browse(self) -> None:
        start = self._save_path
        if start and not Path(start).is_file():
            start = str(Path(start).parent) if Path(start).parent.exists() else ""
        p, _ = QFileDialog.getOpenFileName(self, "选择存档", start, "存档 (*.hg);;所有文件 (*)")
        if p:
            self._set_save_path(p)
            self._load()

    def open_backups(self) -> None:
        self._open_backups()

    def _open_backups(self) -> None:
        path = self._save_path or self._loaded_path
        if not path:
            self._status("请先选择或读取存档，再查看备份")
            self._show_ship_empty("没有存档", "先选择 save.hg，再查看备份。")
            notify.warn("请先选择或读取存档")
            return
        dlg = BackupDialog(path, self)
        self._restoring = True
        try:
            dlg.exec()
        finally:
            self._restoring = False
        if dlg.restored:
            self._watch_ignore_until = time.monotonic() + 2.0
            notify.success("存档恢复成功，正在刷新")
            self._load()

    # ---------------------------------------------------------------- 存档监视

    def _watch_save(self, path: str) -> None:
        path = str(path or "").strip()
        if path == self._watched_path and (not path or path in self._watcher.files()):
            return
        for old in list(self._watcher.files()):
            self._watcher.removePath(old)
        self._watched_path = path
        if path and Path(path).is_file() and path not in self._watcher.files():
            self._watcher.addPath(path)

    def _on_save_file_changed(self, path: str) -> None:
        path = str(path)
        if self._watched_path and path != self._watched_path:
            return
        if path and Path(path).is_file() and path not in self._watcher.files():
            self._watcher.addPath(path)
        if self._is_busy():
            return
        self._watch_timer.start(1000)

    def _on_watch_timeout(self) -> None:
        if self._is_busy() or time.monotonic() < self._watch_ignore_until:
            return
        path = self._save_path or self._loaded_path
        if not path or not Path(path).is_file():
            return
        self._load(notice="存档已变化，已刷新")

    def _is_busy(self) -> bool:
        return self._exporting or self._editing or self._restoring or self._loading

    def _extra_table(self, headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(list(headers))
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    @staticmethod
    def _extra_page(table: QTableWidget) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(table, 1)
        return page

    def _is_extras_tab(self, index: int) -> bool:
        return self.tabs.widget(index) in {
            self.frigates_page, self.multitools_page, self.freighter_page}

    def _set_ship_actions_visible(self, visible: bool) -> None:
        for widget in (self.copy_btn, self.write_btn, self.push_btn,
                       self.write_preview, self.action_note):
            widget.setVisible(visible)

    def _tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is self.pets:
            self.title.setText("同伴详情")
            self._set_ship_actions_visible(False)
            self.detail.hide()
            self.viewer.hide()
            self.fallback.hide()
            self.preview_pane.hide()
            self.pets_note.hide()
            self.card_spacer.hide()
            self.companion.set_path(self._loaded_path)
            if self._loaded_path:
                self.pets.set_save_path(self._loaded_path)
                self.pets.ensure_loaded()
            selected = self.pets.selected_creature()
            self.companion.set_creature(selected or {})
            self.companion.setVisible(bool(selected))
            if selected:
                name = _text(selected.get("name") or selected.get("creature"), "同伴")
                self.title.setText(f"同伴  {name}")
                self._show_detail_card()
            else:
                self._hide_detail_card()
            self._sync_flow()
            return
        self.companion.hide()
        if self._is_extras_tab(index):
            self.title.setText(self.tabs.tabText(index))
            self._set_ship_actions_visible(False)
            self.preview_pane.hide()
            self.viewer.hide()
            self.fallback.hide()
            self.pets_note.hide()
            self.detail.hide()
            self.card_spacer.show()
            if self._loaded_path:
                self._load_extras()
            self._extra_selected()
            return
        self.title.setText("飞船详情")
        self._set_ship_actions_visible(True)
        self.detail.show()
        self.pets_note.hide()
        self.card_spacer.hide()
        self.preview_pane.show()
        self.fallback.hide()
        self.viewer.show()
        self.detail.setText("选中一艘飞船后在这里查看 3D 模型、等级与属性。")
        self._select()

    def _extra_selected(self) -> None:
        """只读扩展表格：选中行后展开详情，未选时不占右侧空间。"""
        table = self._current_extra_table()
        if table is None:
            return
        rows = table.selectionModel().selectedRows()
        if not rows:
            self._hide_detail_card()
            self._sync_flow()
            return
        row = rows[0].row()
        lines = []
        for column in range(table.columnCount()):
            head = table.horizontalHeaderItem(column)
            item = table.item(row, column)
            if head is not None and item is not None:
                lines.append(f"{head.text()}：{item.text()}")
        self.title.setText(self.tabs.tabText(self.tabs.currentIndex()))
        self.detail.setText("\n".join(lines) or "这一行没有可显示的字段。")
        self.detail.show()
        self.card_spacer.show()
        self._show_detail_card()
        self._sync_flow()

    def _companion_selected(self, creature: dict) -> None:
        data = creature if isinstance(creature, dict) else {}
        self.companion.set_creature(data)
        if self.tabs.currentWidget() is not self.pets:
            return
        if data:
            name = _text(data.get("name") or data.get("creature"), "同伴")
            self.title.setText(f"同伴  {name}")
            self.companion.show()
            self._show_detail_card()
        else:
            self.title.setText("同伴详情")
            self.companion.hide()
            self._hide_detail_card()
        self._sync_flow()

    def _status(self, text: str) -> None:
        window = self.window()
        status = getattr(window, "statusBar", None)
        if callable(status):
            try:
                status().showMessage(text, 4000)
                return
            except Exception:                          # noqa: BLE001
                pass
        self.info.setText(text)

    def _load(self, notice: str = "") -> None:
        keep_seed = self._selected_seed()
        self._loading = True
        self._thumb_timer.stop()
        self._thumb_queue.clear()
        self.load_btn.setEnabled(False)
        self.error_banner.clear()
        self._status("正在读取存档…")
        self.result_info.setText("正在读取…")
        self.list.clear()
        self.list.hide()
        self.empty_state.hide()
        self.pets.clear()
        self.companion.set_creature({})
        self.companion.hide()
        self._clear_extras()
        self._ships = []
        self._loaded_path = ""
        self._hide_detail_card()
        self._update_actions()
        self._sync_flow()
        self.loading_overlay.start("正在读取存档…")

        def done(res: dict) -> None:
            self._loading = False
            self.loading_overlay.stop()
            self.error_banner.clear()
            self._loaded_path = str(res.get("path") or "")
            self._ships = res.get("ships") or []
            self._set_save_path(self._loaded_path or self._save_path)
            self.result_info.setText(f"{len(self._ships)} 艘")
            self.result_info.setToolTip(self._loaded_path or "尚未读取存档")
            warns = res.get("warnings") or []
            self._status(f"已读取 {len(self._ships)} 艘"
                         + (f" · {len(warns)} 条警告" if warns else ""))
            self._rebuild_ship_list()
            if keep_seed:
                for row in range(self.list.count()):
                    item = self.list.item(row)
                    if str((item.data(Qt.UserRole) or {}).get("seed") or "") == keep_seed:
                        self.list.setCurrentItem(item)
                        break
            self.load_btn.setEnabled(True)
            self._watch_save(self._loaded_path)
            self.companion.set_path(self._loaded_path)
            self.pets.set_save_path(self._loaded_path, invalidate=True)
            self._clear_extras()
            if self._is_extras_tab(self.tabs.currentIndex()):
                self._load_extras()
            self._update_actions()
            self._update_ship_empty()
            self._sync_flow()
            if notice:
                notify.toast(notice, "info")

        def fail(msg: str) -> None:
            self._loading = False
            self.loading_overlay.stop()
            text = f"读取存档失败：{msg}"
            self._status(text)
            self.result_info.setText("读取失败")
            self._ships = []
            self._loaded_path = ""
            self.list.clear()
            self.pets.clear()
            self.companion.set_creature({})
            self.companion.set_path("")
            self.companion.hide()
            self._clear_extras()
            self._hide_detail_card()
            self.load_btn.setEnabled(True)
            self.error_banner.show_error(text)
            self._show_ship_empty("读取失败", "请检查路径后重试。")
            self._update_actions()
            self._sync_flow()
            notify.error(text)

        run_worker(self.svc.ships, done, fail, self._save_path or None)

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
        if grid:
            self._card_delegate = install_card_delegate(self.list, 110)
        else:
            self.list.setItemDelegate(QStyledItemDelegate(self.list))
            self.list.setIconSize(QSize(72, 50))
            self.list.setGridSize(QSize())

    # ---------------------------------------------------------------- 排序/空态

    def _sorted_ships(self) -> list[dict]:
        key = self._sort_key

        def value(ship: dict):
            if key == "class":
                primary = ship.get("ship_class") or ""
            elif key == "seed":
                primary = ship.get("seed") or ""
            else:
                primary = ship.get("type_label") or ship.get("type") or ""
            return (str(primary).casefold(), str(ship.get("seed") or "").casefold())

        return sorted(self._ships, key=value, reverse=self._sort_desc)

    def _selected_seed(self) -> str:
        items = self.list.selectedItems()
        if not items:
            return ""
        return str((items[0].data(Qt.UserRole) or {}).get("seed") or "")

    def _apply_sort(self) -> None:
        self._sort_key = str(self.sort_mode.currentData() or "type")
        self._sort_desc = bool(self.sort_order.currentData())
        if self._ships:
            self._rebuild_ship_list()

    def _rebuild_ship_list(self) -> None:
        selected = self._selected_seed()
        self.list.clear()
        self._thumb_queue.clear()
        for s in self._sorted_ships():
            item = QListWidgetItem(s.get("seed") or "")
            item.setData(Qt.UserRole, s)
            item.setToolTip(f"{s.get('type_label') or s.get('type')}  {s.get('ship_class') or ''}")
            self.list.addItem(item)
            self._thumb_queue.append(item)
            if selected and str(s.get("seed") or "") == selected:
                item.setSelected(True)
        if self._thumb_queue:
            self._thumb_timer.start(50)

    def _show_ship_empty(self, title: str, description: str = "") -> None:
        self.list.hide()
        self.empty_state.title_label.setText(title)
        self.empty_state.description_label.setText(description)
        self.empty_state.description_label.setVisible(bool(description))
        self.empty_state.title_label.setToolTip(title)
        self.empty_state.description_label.setToolTip(description)
        self.empty_state.show()

    def _update_ship_empty(self) -> None:
        if self._loading:
            self.list.hide()
            self.empty_state.hide()
            return
        if self._ships:
            self.list.show()
            self.empty_state.hide()
            return
        if self._loaded_path:
            self._show_ship_empty("这个存档里没有飞船", "可以换个存档，或重新读取。")
        else:
            self._show_ship_empty("没有存档", "先选择 save.hg，再点「读取存档」。")

    # ---------------------------------------------------------------- Inspector

    def _select(self) -> None:
        self._update_actions()
        items = self.list.selectedItems()
        if not items:
            self.write_preview.setText(EMPTY_WRITE_PREVIEW)
            self._hide_detail_card()
            self._sync_flow()
            return
        s = items[0].data(Qt.UserRole) or {}
        self.title.setText(f"{s.get('type_label') or s.get('type')}  {s.get('seed')}")
        self.detail.show()
        self._show_detail_card()
        self._sync_flow()
        result = self._write_result
        if not (isinstance(result, dict) and result.get("slot") == s.get("slot")):
            result = None
        self.write_preview.setText("\n".join(write_preview_lines(s, result)))

        # 固定模型（护卫舰/货船/部分拦截机等）没有程序化外观：不进入 3D 管线，
        # 否则 model3d 会去找 gamedata/<type>，在日志里刷 BadRequest/FileNotFoundError。
        from ...data.shipref import PROC_MODELS

        if not s.get("procedural") or str(s.get("type") or "") not in PROC_MODELS:
            self.pets_note.hide()
            self.viewer.hide()
            self.fallback.show()
            self.fallback.setPixmap(QPixmap())
            self.fallback.setText("固定模型：没有程序化 3D 预览\n（种子不会改变它的外观）")
            self.detail.hide()
            return

        self.pets_note.hide()
        self.detail.setText("生成 3D 几何…")

        stats = s.get("stats") or {}
        stat_text = "  ".join(
            f"{STAT_LABELS.get(k, k)}: {v}" for k, v in stats.items()) or "无属性数据"

        def done(mesh: dict) -> None:
            self.viewer.set_mesh(mesh.get("groups") or {}, mesh.get("colours") or {})
            valid = True
            try:
                valid = bool(self.viewer.isValid())
            except Exception:                              # noqa: BLE001
                valid = True
            if not valid:
                # 无 OpenGL（远程桌面/离屏）时不要把空白画布当预览。
                image_fallback("当前环境没有可用的 OpenGL")
                return
            self.fallback.hide()
            self.viewer.show()
            self.detail.setText(
                f"{stat_text}\n{mesh.get('verts', 0):,} 顶点 / {mesh.get('tris', 0):,} 三角")

        def image_fallback(msg: str) -> None:
            self.viewer.hide()
            self.fallback.show()
            self.fallback.setPixmap(QPixmap())
            self.fallback.setText(f"{stat_text}\n\n实时 3D 不可用（{msg}）\n正在尝试静态渲染…")

            def got(data: bytes | None) -> None:
                if not data:
                    self.fallback.setText(f"{stat_text}\n\n实时 3D 不可用（{msg}）")
                    return
                pix = QPixmap()
                pix.loadFromData(data, "PNG")
                if pix.isNull():
                    self.fallback.setText(f"{stat_text}\n\n实时 3D 不可用（{msg}）")
                    return
                # 预览区可能比 420px 窄：按实际宽度缩放，避免右侧和底部裁切。
                width = max(220, (self.fallback.width() or 420) - 8)
                if pix.width() > width:
                    pix = pix.scaledToWidth(width, Qt.SmoothTransformation)
                self.fallback.setPixmap(pix)
                self.fallback.setToolTip(msg)
                self.detail.setText(f"{stat_text}\n静态预览 · {msg}")

            def bad(_m: str) -> None:
                self.fallback.setText(f"{stat_text}\n\n实时 3D 不可用（{msg}）")

            run_worker(self.svc.preview_png, got, bad,
                       s.get("type"), s.get("seed"), s.get("parts"), 420)

        def fail(msg: str) -> None:
            image_fallback(msg)

        run_worker(self.svc.preview_mesh, done, fail,
                   s.get("type"), s.get("seed"), s.get("parts"))

    @staticmethod
    def _set_role(button: QPushButton, role: str) -> None:
        if button.objectName() == role:
            return
        button.setObjectName(role)
        style = button.style()
        if style is not None:
            style.unpolish(button)
            style.polish(button)
        button.update()

    def _update_actions(self) -> None:
        items = self.list.selectedItems()
        ship = items[0].data(Qt.UserRole) if items else None
        busy = self._is_busy()
        self.save_edit_btn.setEnabled(bool(self._loaded_path) and not busy)
        self.extras_btn.setEnabled(bool(self._loaded_path) and not busy)
        self.export_btn.setEnabled(bool(self._ships) and not self._exporting)
        can_write = (bool(ship) and ship.get("slot") is not None
                     and bool(self._loaded_path) and not busy)
        self.write_btn.setEnabled(can_write)
        if isinstance(ship, dict) and ship and ship.get("slot") is None:
            self.write_btn.setToolTip("这艘飞船没有可写入的槽位，不能写回存档")
        else:
            self.write_btn.setToolTip(
                "修改选中飞船的等级/属性并写回存档；先自动备份，可写入副本")
        self.push_btn.set_ship(ship)
        can_push = self.push_btn.isEnabled() and not busy

        primary = primary_action(ship, can_write, can_push, busy)
        if primary == "write":
            self._set_role(self.write_btn, "dangerButton")
            self._set_role(self.push_btn, "ghostButton")
            note = ""
        elif primary == "push":
            self._set_role(self.write_btn, "ghostButton")
            self._set_role(self.push_btn, "primaryButton")
            note = ""
        else:
            self._set_role(self.write_btn, "dangerButton")
            self._set_role(self.push_btn, "ghostButton")
            note = "选中飞船后可写回存档；有模板槽的船型可送进游戏。"
        self.action_note.setText(note)
        self.action_note.setToolTip(note)
        self.action_note.setVisible(bool(note))
        self._sync_flow()

    def _export_all(self) -> None:
        if not self._ships:
            self._status("还没有飞船可导出：请先读取存档")
            notify.warn("还没有飞船可导出，请先读取存档")
            return
        start = "starforge-fleet.zip"
        if self._loaded_path:
            p = Path(self._loaded_path)
            start = str(p.with_name(f"{p.stem}-ships.zip"))
        path, _ = QFileDialog.getSaveFileName(
            self, "导出全部飞船", start, "ZIP 压缩包 (*.zip);;所有文件 (*)")
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        items = [{k: s.get(k) for k in ("type", "seed", "parts", "name") if k in s}
                 for s in self._ships]
        self._exporting = True
        self._update_actions()
        self._status(f"导出 {len(items)} 艘到 {path}…")

        def done(res: dict) -> None:
            self._exporting = False
            self._update_actions()
            failed = int(res.get("failed") or 0)
            exported = int(res.get("exported") or 0)
            count = int(res.get("count") or len(items))
            tail = f" · 失败 {failed}" if failed else ""
            self._status(f"导出完成 {exported}/{count} 艘{tail} · {res.get('path')}")
            if failed:
                notify.warn(f"导出完成 {exported}/{count} 艘，失败 {failed} 艘；详情见压缩包内的清单")
            else:
                notify.success(f"导出成功：{exported}/{count} 艘飞船")

        def fail(msg: str) -> None:
            self._exporting = False
            self._update_actions()
            self._status(f"导出失败：{msg}")
            notify.error(f"导出失败：{msg}")

        run_worker(_write_export, done, fail, path, items)

    def _open_class_editor(self) -> None:
        items = self.list.selectedItems()
        if not items:
            self._status("先选中一艘飞船再修改船级/属性")
            notify.warn("先选中一艘飞船")
            return
        ship = items[0].data(Qt.UserRole) or {}
        path = self._loaded_path or self._save_path
        if not path:
            self._status("请先读取存档，再修改船级/属性")
            notify.warn("请先读取存档")
            return
        if ship.get("slot") is None:
            self._status("这艘飞船没有可写入的槽位")
            notify.warn("这艘飞船没有可写入的槽位")
            return
        dlg = ClassEditorDialog(path, ship, self)
        self._editing = True
        try:
            accepted = dlg.exec() == QDialog.Accepted
        finally:
            self._editing = False
        if not accepted:
            return
        self._watch_ignore_until = time.monotonic() + 2.0
        res = dlg.result or {}
        self._write_result = dict(res)
        target = str(res.get("path") or "")
        if res.get("copy") and target:
            self._set_save_path(target)
        # 写回后立刻在详情区给出真实的 before → after，而不是只弹一次提示。
        self.write_preview.setText("\n".join(write_preview_lines(ship, res)))
        summary = f"船级/属性写入成功 · 槽位 {res.get('slot', ship.get('slot'))}"
        self._status(summary)
        notify.success(summary)
        self._load()

    def _clear_extras(self) -> None:
        self._extras = {}
        self._extras_loaded = False
        self._extras_loading = False
        for table in (self.frigates_table, self.multitools_table, self.freighter_table):
            table.setRowCount(0)

    @staticmethod
    def _fill_extra_table(table: QTableWidget, rows: list[list[str]]) -> None:
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                table.setItem(i, j, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()

    def _load_extras(self, force: bool = False) -> None:
        path = self._loaded_path or self._save_path
        if not path:
            return
        if self._extras_loaded and not force:
            self._render_extras(self._extras)
            return
        if self._extras_loading:
            return
        self._extras_loading = True
        self.detail.setText("正在读取货船/护卫舰/多用途工具…")

        def done(payload: dict) -> None:
            self._extras_loading = False
            self._extras_loaded = True
            self._extras = payload or {}
            self._render_extras(self._extras)

        def fail(msg: str) -> None:
            self._extras_loading = False
            self._extras_loaded = False
            self._clear_extras()
            self.detail.setText(f"读取船队扩展失败：{msg}")

        run_worker(self.svc.fleet_extras, done, fail, path)

    def _render_extras(self, payload: dict) -> None:
        payload = payload or {}
        self._fill_extra_table(self.frigates_table,
                               frigate_rows(payload.get("frigates") or []))
        self._fill_extra_table(self.multitools_table,
                               multitool_rows(payload.get("multitools") or []))
        self._fill_extra_table(self.freighter_table,
                               freighter_rows(payload.get("freighter")))
        errors = payload.get("errors") or {}
        bits = [f"{len(payload.get('frigates') or [])} 艘护卫舰",
                f"{len(payload.get('multitools') or [])} 把多用途工具"]
        if payload.get("freighter"):
            bits.append("货船已读取")
        if errors:
            bits.append("不可用：" + "、".join(sorted(errors)))
        self.detail.setText(" · ".join(bits))

    def _open_save_extras(self) -> None:
        if not self._loaded_path:
            self._status("请先读取存档，再编辑库存/知识/任务/奖励")
            notify.warn("请先读取存档")
            return
        dlg = SaveExtrasDialog(self._loaded_path, self)
        self._editing = True
        try:
            accepted = dlg.exec() == QDialog.Accepted
        finally:
            self._editing = False
        self._update_actions()
        if not accepted:
            return
        res = dlg.result or {}
        target = str(res.get("path") or "")
        if res.get("copy") and target:
            self._set_save_path(target)
        self._status("存档扩展编辑写入成功")
        notify.success("存档扩展编辑写入成功，已通过读回校验")
        self._watch_ignore_until = time.monotonic() + 2.0
        self._load()

    def _open_save_edit(self) -> None:
        if not self._loaded_path:
            self._status("请先读取存档，再编辑货币与飞船")
            notify.warn("请先读取存档")
            return
        items = self.list.selectedItems()
        ship = (items[0].data(Qt.UserRole) or {}) if items else {}
        dlg = SaveEditDialog(self._loaded_path, self._ships, ship, self)
        self._editing = True
        try:
            accepted = dlg.exec() == QDialog.Accepted
        finally:
            self._editing = False
        self._update_actions()
        if not accepted:
            return
        res = dlg.result or {}
        target = str(res.get("path") or "")
        if res.get("copy") and target:
            self._set_save_path(target)
        changed = set(res.get("changed") or [])
        bits = []
        if "currencies" in changed:
            bits.append("货币")
        if {"name", "paint"} & changed:
            bits.append(f"飞船槽位 {res.get('slot', ship.get('slot', '?'))}")
        summary = "存档编辑写入成功" + (f" · {' / '.join(bits)}" if bits else "")
        if res.get("copy"):
            summary += "（副本）"
        self._status(summary)
        notify.success(summary)
        self._watch_ignore_until = time.monotonic() + 2.0
        self._load()

    def _copy_seed(self) -> None:
        items = self.list.selectedItems()
        if items:
            s = items[0].data(Qt.UserRole) or {}
            QGuiApplication.clipboard().setText(s.get("seed") or "")
            self._status("种子已复制")
            notify.success("种子已复制")
