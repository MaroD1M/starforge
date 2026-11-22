"""星图：当前星系、行星、船池、扫描、银河索引与已发现星球。"""
from __future__ import annotations

import csv
import io
import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import zh as zh_mod
from ...discoveries import BIOMES as DISCOVERY_BIOMES
from ...glyphs import glyphs_for_ua
from ...services import get_services
from .. import notify
from ..dialogs.address import (
    PLANET_UNKNOWN,
    convert_address,
    parse_seed,
)
from ..widgets.feedback import EmptyState, ErrorBanner, LoadingOverlay
from ..widgets.galaxy_detail import GalaxyDetailDialog
from ..widgets.galaxy_flow import (
    GalaxyFlowBar,
    GalaxyGlyphLabel,
    GalaxyTable,
    GalaxyTablePane,
)
from ..widgets.page import PageSplitter, page_layout
from ..widgets.page_header import PageHeader
from ..widgets.ui import Card, muted, primary_button
from ..widgets.ux import FilterChips, FilterPanel, TaskFlow
from ..widgets.worker import run as run_worker

BIOMES = [("", "不限"), ("Lush", "茂盛"), ("Toxic", "剧毒"), ("Scorched", "焦土"),
          ("Frozen", "冰冻"), ("Barren", "荒芜"), ("Exotic", "异星"), ("Dead", "死寂")]
SENTS = [("", "不限"), ("none", "无"), ("low", "低"), ("high", "高"),
         ("aggressive", "敌对"), ("corrupted", "腐化")]
INDEX_BIOMES = BIOMES + [
    ("Radioactive", "辐射"), ("Mega Exotic", "巨型奇异"), ("Weird", "异象"),
    ("Swamp", "沼泽"), ("Volcanic", "火山"), ("Desert", "沙漠"), ("Ocean", "海洋"),
    ("Gas", "气态"), ("Infested", "虫蚀")]
RACES = [("", "不限"), ("Gek", "吉克"), ("Korvax", "科瓦克斯"), ("Vy'keen", "维金"),
         ("None", "无"), ("Abandoned", "废弃"), ("Traveller", "旅行者"), ("Atlas", "阿特拉斯")]
RACE_LABELS = dict(RACES)

# 传送失败时（E_BUILD_UNVERIFIED）给用户的下一步；不在这里代做设置预检，
# 统一以服务层返回的错误为准，避免界面和 agent 端两套判断互相打脸。
BUILD_UNVERIFIED_HINT = (
    "需要先开启实验写入开关（设置页 → 安全 → 允许未验证 build 的实验写入）")

# 「已发现」表格列：表格与 CSV 前 7 列共用同一组字段。
DISCOVERED_COLUMNS = ["行星", "星系", "群系", "虫蚀", "命名", "距离", "符文", "存档"]
DISCOVERED_SORT_ROLE = int(Qt.UserRole) + 1
DISCOVERED_SOURCE_LABELS = {"save": "存档", "save-pending": "待上传"}


class _DiscoveredSortItem(QTableWidgetItem):
    """QTableWidgetItem 默认按显示文本排序；距离/序号需要按数值排。"""

    def __lt__(self, other) -> bool:
        mine = self.data(DISCOVERED_SORT_ROLE)
        theirs = other.data(DISCOVERED_SORT_ROLE) if isinstance(other, QTableWidgetItem) else None
        if mine is not None and theirs is not None:
            try:
                return mine < theirs
            except TypeError:
                pass
        return super().__lt__(other)


def _discovered_distance_text(value) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number < 10:
        return f"{number:.1f} ly"
    return f"{number:,.0f} ly"


def _discovered_distance_csv(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return ""


def _discovered_timestamp_text(value) -> str:
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return "—"
    if stamp <= 0:
        return "—"
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))
    except (OSError, OverflowError, ValueError):
        return str(stamp)


def _discovered_source_text(row: dict) -> str:
    source = str(row.get("source") or "")
    if not source:
        return "索引"
    label = DISCOVERED_SOURCE_LABELS.get(source, source)
    return f"{label}（待上传）" if row.get("pending") and label != "待上传" else label


def _discovered_biome_text(value) -> str:
    return zh_mod.biome_label(value) if value else "未知"


def _discovered_flag_text(value, *, yes: str = "是", no: str = "否") -> str:
    if value is None:
        return "未知"
    return yes if value else no


def _discovered_cells(row: dict) -> list[str]:
    """表格与 CSV 共用的列值，顺序与 DISCOVERED_COLUMNS 一致。"""
    index = row.get("planet_index")
    system = (row.get("system_name") or row.get("coords")
              or row.get("system_ua") or "—")
    return [
        str(index) if index is not None else "—",
        str(system),
        _discovered_biome_text(row.get("biome")),
        _discovered_flag_text(row.get("infested")),
        str(row.get("name") or "未命名"),
        _discovered_distance_text(row.get("distance_ly")),
        str(row.get("glyphs") or "—"),
        str(row.get("save_name") or _discovered_source_text(row)),
    ]


def _discovered_sort_values(row: dict) -> list:
    index = row.get("planet_index")
    infested = row.get("infested")
    cells = _discovered_cells(row)
    return [
        999 if index is None else int(index),
        cells[1].casefold(),
        cells[2].casefold(),
        2 if infested is None else (0 if not infested else 1),
        0 if row.get("name") else 1,
        float("inf") if row.get("distance_ly") in (None, "") else float(row["distance_ly"]),
        str(row.get("glyphs") or "").casefold(),
        cells[7].casefold(),
    ]


def _valid_portal_glyphs(glyphs: str) -> bool:
    """与 agent 端 `_decode_glyphs` 的合法门地址规则保持一致（只校验，不编码）。"""
    text = str(glyphs or "").strip().upper()
    if len(text) != 12 or any(c not in "0123456789ABCDEF" for c in text):
        return False
    if not 1 <= int(text[0], 16) <= 6:
        return False
    if int(text[1:4], 16) in (0, 0xFFF):
        return False
    if int(text[4:6], 16) == 0x80:
        return False
    return not (int(text[6:9], 16) == 0x800 or int(text[9:12], 16) == 0x800)


def _planet_digit(value) -> int | None:
    """扫描结果里的行星序号 → 门地址第 1 位（1..6）；其他值不猜。

    注意：上游 `systemgen` 的行星 index 是 **1-based**（`{"index": i + 1}`），
    不要按 0-based 再加一。
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 6 else None


def _warp_glyphs_for(result: dict) -> str:
    """从扫描结果生成门地址：优先 UA + 行星位，退回结果里已有的符文串。"""
    if not isinstance(result, dict):
        return ""
    planet_value = result.get("planet_index")
    if planet_value in (None, ""):
        planet_value = result.get("index")
    planet = _planet_digit(planet_value)
    # 有明确行星序号但不在 1..6 时不能退化成"传送到 1 号行星"——宁可不给按钮。
    if planet_value not in (None, "") and planet is None:
        return ""

    ua = result.get("ua")
    if ua not in (None, "") and planet is not None:
        try:
            value = int(str(ua), 16) if isinstance(ua, str) else int(ua)
            glyphs = glyphs_for_ua(value, planet=planet)
        except (TypeError, ValueError):
            glyphs = ""
        if _valid_portal_glyphs(glyphs):
            return glyphs

    glyphs = str(result.get("glyphs") or "").strip().upper()
    if not _valid_portal_glyphs(glyphs):
        return ""
    # 只有星系级符文串（第 1 位通常是 1）时，按选中行星替换第一位。
    if planet is not None:
        candidate = f"{planet:X}{glyphs[1:]}"
        if _valid_portal_glyphs(candidate):
            return candidate
    return glyphs


def _warp_ua_value(result: dict) -> int | None:
    """结果里的 UA；解析不了就当作没有，不猜。"""
    ua = result.get("ua")
    if ua in (None, ""):
        return None
    try:
        return int(str(ua), 16) if isinstance(ua, str) else int(ua)
    except (TypeError, ValueError):
        return None


def _warp_glyphs_for_planet(result: dict, planet: int) -> str:
    """按用户选的行星位重新生成门地址（系统级结果没有行星 index 时用）。"""
    if not 1 <= int(planet) <= 6:
        return ""
    return _warp_glyphs_for({**result, "planet_index": int(planet), "index": int(planet)})


def _warp_target_for(result: dict, planet: int | None = None) -> dict | None:
    """把扫描/索引行变成传送目标；系统级行可以带 `needs_planet` 等用户选行星。"""
    if not isinstance(result, dict):
        return None
    row_planet = _planet_digit(result.get("planet_index") or result.get("index"))
    if row_planet is None and (result.get("planet_index") not in (None, "")
                               or result.get("index") not in (None, "")):
        # 明确给了行星序号但不在 1..6：不能退化成"传送到 1 号行星"。
        return None
    chosen = row_planet if row_planet is not None else _planet_digit(planet)
    glyphs = (_warp_glyphs_for({**result, "planet_index": chosen}) if chosen is not None
              else _warp_glyphs_for(result))
    galaxy = result.get("galaxy")
    if isinstance(galaxy, str) and galaxy.strip().lower().startswith("0x"):
        try:
            galaxy = int(galaxy, 16)
        except ValueError:
            galaxy = None
    elif galaxy is not None:
        try:
            galaxy = int(galaxy)
        except (TypeError, ValueError):
            galaxy = None
    needs_planet = chosen is None
    if not glyphs and not (needs_planet and _warp_ua_value(result) is not None):
        return None
    return {
        "glyphs": glyphs,
        "galaxy": galaxy,
        "planet": chosen,
        "planet_label": f"行星 #{chosen}" if chosen is not None else "行星（待选择）",
        "system": str(result.get("system_name") or result.get("name")
                      or result.get("coords") or glyphs or "未知星系"),
        "needs_planet": needs_planet,
    }



def _warp_confirm_text(target: dict) -> str:
    return (
        f"即将传送到 {target['system']}/{target['planet_label']}"
        f"（门地址 {target['glyphs']}）。\n\n"
        "会调用游戏内传送门机制，落到目标星球；失败可用「还原」回滚。\n"
        "这是高风险写操作，请确认游戏已就绪。是否继续？")


class GalaxyPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._loaded = False
        self._scan_job = None
        self._scan_rows: list[dict] = []
        self._index_rows: list[dict] = []
        self._addr_glyphs: str | None = None
        self._addr_coords: str | None = None
        self._addr_ua_text: str | None = None
        self._addr_teleportable = False
        self._teleport_glyphs: str | None = None
        self._addr_busy = False
        self._warp_target: dict | None = None
        self._warp_row: dict | None = None
        self._warp_tooltip = ""
        self._warp_busy = False
        self._panes: dict[int, GalaxyTablePane] = {}
        self._current_info: dict = {}
        self._selection: dict = {}
        self._last_scan_filters: dict = {}
        self._discovered_all: list[dict] = []
        self._discovered_rows: list[dict] = []
        self._discovered_meta: dict = {}
        self._discovered_stats: dict = {}
        self._discovered_warnings: list[str] = []
        self._discovered_origin_ua = None
        self._discovered_has_data = False
        self._discovered_loaded = False
        self._discovered_loading = False
        self._discovered_loaded_at = 0.0
        self._discovered_filter_seq = 0
        self._discovered_index_meta: dict = {}
        self._index_busy = False
        self._primary_mode = "scan"
        self._overlay = None
        self._detail_dialog = None
        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._poll_scan)
        self._build_ui()

    def _build_ui(self) -> None:
        root = page_layout(self)

        self.header = PageHeader(
            "星图",
            "查看当前星系、行星与船池；扫描、查询与传送都从顶部主操作开始。")
        # PageHeader 的 Minimum 垂直策略会把 sizeHint（完整副标题高度）
        # 当成最小高度；允许压缩后，矮窗口里主内容才有空间。
        self.header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.header.subtitle.setWordWrap(False)
        self.header.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.header.subtitle.setToolTip(self.header.subtitle.text())
        root.addWidget(self.header)

        # 一屏一个主操作：文字与动作随标签页变化，不并排摆多个 primary。
        self.primary_btn = primary_button("扫描", "扫描附近星系并写入银河索引")
        self.primary_btn.clicked.connect(self._on_primary)
        self.scan_btn = self.primary_btn          # 外壳「下一步」仍按这个名字聚焦
        self.scan_cancel_btn = QPushButton("取消扫描")
        self.scan_cancel_btn.setObjectName("ghostButton")
        self.scan_cancel_btn.setToolTip("请求取消正在进行的扫描；当前系统完成后停止")
        self.scan_cancel_btn.clicked.connect(self._cancel_scan)
        self.scan_cancel_btn.setVisible(False)
        self.more_btn = QPushButton("更多")
        self.more_btn.setObjectName("ghostButton")
        self.more_btn.setToolTip("刷新、导出、浮动符文与清空筛选")
        self.more_menu = QMenu(self)
        self.refresh_action = self.more_menu.addAction(
            "刷新当前星系", self._refresh_current_mode)
        self.export_action = self.more_menu.addAction(
            "导出 CSV", self._export_current_csv)
        self.overlay_action = self.more_menu.addAction(
            "浮窗显示选中符文", self._show_overlay)
        self.clear_filters_action = self.more_menu.addAction(
            "清空当前筛选", self._clear_current_filters)
        self.more_menu.addSeparator()
        self.seed_action = self.more_menu.addAction("种子反查…", self._seed_lookup)
        self.export_action.setEnabled(False)
        self.overlay_action.setEnabled(False)
        self.more_btn.setMenu(self.more_menu)
        for button in (self.primary_btn, self.scan_cancel_btn, self.more_btn):
            self.header.add_action(button)

        self.error_banner = ErrorBanner(parent=self)
        self.error_banner.set_retry_callback(self._load_current)
        root.addWidget(self.error_banner)

        hero = Card()
        self.hero = hero
        hv = hero.v
        self.badge = QLabel("—")
        self.badge.setStyleSheet("font-size:16px;font-weight:700;")
        self.badge.setWordWrap(True)
        hv.addWidget(self.badge)
        self.hero_info = muted("进入页面后自动读取；没有存档时请先在设置页配置。")
        self.glyph = GalaxyGlyphLabel(max_height=40)
        # 信息与符文条并排，省下一整行高度给下面的筛选/结果区。
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(self.hero_info, 1)
        bottom.addWidget(self.glyph, 0, Qt.AlignRight | Qt.AlignVCenter)
        hv.addLayout(bottom)
        self.current_empty = EmptyState(
            "没有当前星系数据",
            "没有读取到存档/游戏，或当前星系没有行星与船池；请在设置页配置后重试。",
            icon="◇", button_text="重新读取", parent=hero)
        self.current_empty.actionTriggered.connect(self._load_current)
        self._fix_empty_size(self.current_empty)
        self.current_empty.hide()
        hv.addWidget(self.current_empty)
        root.addWidget(hero)
        self.map_flow = TaskFlow(["当前星系", "扫描 / 查询", "选中后传送"])
        root.addWidget(self.map_flow)

        split = PageSplitter("galaxy-v2")
        root.addWidget(split, 1)

        mid = Card("行星与船池")
        self.mid_card = mid
        mid.setMinimumWidth(360)
        mv = mid.v
        mv.setContentsMargins(12, 8, 12, 8)
        mv.setSpacing(6)

        self.status = muted("就绪：可扫描附近星系，或先查看当前星系。")
        self.addr_status = self.status          # 地址工作台复用同一条状态行

        # 扫描条件只服务「行星 / 船池 / 扫描结果」，切到其它标签时整块收起。
        self.scan_filter_box = QWidget()
        sf = QVBoxLayout(self.scan_filter_box)
        sf.setContentsMargins(0, 0, 0, 0)
        sf.setSpacing(6)
        # 窄窗口下自动换行：每个标签和控件都保持自己的 sizeHint，
        # 不再被 QHBoxLayout 压到比中文文本还窄。
        self.scan_filter_flow = GalaxyFlowBar(h_spacing=6, v_spacing=6)
        self.biome = QComboBox()
        for k, v in BIOMES:
            self.biome.addItem(v, k)
        self.scan_filter_flow.addWidget(self._filter_field("群系", self.biome))
        self.sent = QComboBox()
        for k, v in SENTS:
            self.sent.addItem(v, k)
        self.scan_filter_flow.addWidget(self._filter_field("哨兵", self.sent))
        self.race = QComboBox()
        for k, v in RACES:
            self.race.addItem(v, k)
        self.scan_filter_flow.addWidget(self._filter_field("种族", self.race))
        self.interceptor = QComboBox()
        self.interceptor.addItem("不限", None)
        self.interceptor.addItem("有", True)
        self.scan_filter_flow.addWidget(self._filter_field("拦截机", self.interceptor))
        self.min_planets = QSpinBox()
        self.min_planets.setRange(0, 20)
        self.min_planets.setValue(0)
        self.min_planets.setSpecialValueText("不限")
        self.scan_filter_flow.addWidget(self._filter_field("最少行星", self.min_planets))
        self.moons = QComboBox()
        self.moons.addItem("不限", 0)
        self.moons.addItem("≥1", 1)
        self.moons.addItem("≥2", 2)
        self.moons.setToolTip("只保留至少拥有该数量卫星的星系")
        self.scan_filter_flow.addWidget(self._filter_field("卫星", self.moons))
        self.diss = QComboBox()
        self.diss.addItem("不限", None)
        self.diss.addItem("仅异常", True)
        self.scan_filter_flow.addWidget(self._filter_field("异常状态", self.diss))
        self.count = QSpinBox()
        self.count.setRange(20, 767)
        self.count.setValue(200)
        self.scan_filter_flow.addWidget(self._filter_field("扫描系统数", self.count))
        self.reset_filters_btn = QPushButton("重置条件")
        self.reset_filters_btn.setObjectName("ghostButton")
        self.reset_filters_btn.clicked.connect(self._reset_scan_filters)
        self.scan_filter_flow.addWidget(self.reset_filters_btn)
        sf.addWidget(self.scan_filter_flow)

        for widget in (self.biome, self.sent, self.race, self.interceptor,
                       self.moons, self.diss):
            widget.currentIndexChanged.connect(self._update_filter_summary)
        for widget in (self.min_planets, self.count):
            widget.valueChanged.connect(self._update_filter_summary)
        self.filter_summary = muted("筛选摘要：不限条件；扫描范围 200 个系统。")
        sf.addWidget(self.filter_summary)
        mv.addWidget(self.scan_filter_box)

        self.tabs = QTabWidget()
        self.planets = GalaxyTable(0, 5)
        self.planets.setHorizontalHeaderLabels(
            ["#", "生物群系", "哨兵", "资源", "异常"])
        self._configure_table(self.planets)
        self.planets.setSortingEnabled(True)
        self.planets.itemSelectionChanged.connect(self._select_planet)
        self.planets.cellDoubleClicked.connect(
            lambda row, _col: self._on_table_double_click(self.planets, row))
        self.planets_empty = EmptyState(
            "当前星系没有行星", "没有读到行星数据；请确认存档/游戏目录，或用「更多 → 刷新当前星系」。",
            icon="◇")
        self.planets_page = self._wrap_table(self.planets, self.planets_empty)
        self.tabs.addTab(self.planets_page, "行星")
        self.ships = GalaxyTable(0, 4)
        self.ships.setHorizontalHeaderLabels(["类型", "类别", "种子", "来源"])
        self._configure_table(self.ships)
        self.ships.setSortingEnabled(True)
        self.ships_empty = EmptyState(
            "当前星系没有船", "没有读到船池数据；请确认存档/游戏目录，或用「更多 → 刷新当前星系」。",
            icon="◇")
        self.ships_page = self._wrap_table(self.ships, self.ships_empty)
        self.tabs.addTab(self.ships_page, "本星系船池")
        self.scan_table = GalaxyTable(0, 6)
        self.scan_table.setHorizontalHeaderLabels(
            ["行星", "群系", "哨兵", "坐标", "符文串", "星系"])
        self._configure_table(self.scan_table)
        self.scan_table.setSortingEnabled(True)
        self.scan_table.itemSelectionChanged.connect(self._select_scan)
        self.scan_table.cellDoubleClicked.connect(
            lambda row, _col: self._on_table_double_click(self.scan_table, row))
        self.scan_empty = EmptyState(
            "还没有扫描结果", "点顶部「扫描」按当前条件扫描附近星系；结果会写入银河索引。",
            icon="◇")
        self.scan_page = self._build_scan_page()
        self.tabs.addTab(self.scan_page, "扫描结果")

        self.index_page = QWidget()
        iv = QVBoxLayout(self.index_page)
        iv.setContentsMargins(0, 4, 0, 0)
        iv.setSpacing(4)

        self.index_filter_flow = GalaxyFlowBar(h_spacing=6, v_spacing=6)
        self.idx_biome = QComboBox()
        for k, v in INDEX_BIOMES:
            self.idx_biome.addItem(v, k)
        self.index_filter_flow.addWidget(self._filter_field("群系", self.idx_biome))
        self.idx_sent = QComboBox()
        for k, v in SENTS:
            self.idx_sent.addItem(v, k)
        self.index_filter_flow.addWidget(self._filter_field("哨兵", self.idx_sent))
        self.idx_race = QComboBox()
        for k, v in RACES:
            self.idx_race.addItem(v, k)
        self.index_filter_flow.addWidget(self._filter_field("种族", self.idx_race))
        self.idx_diss = QComboBox()
        self.idx_diss.addItem("不限", None)
        self.idx_diss.addItem("是", True)
        self.idx_diss.addItem("否", False)
        self.index_filter_flow.addWidget(self._filter_field("异常状态", self.idx_diss))
        self.idx_min = QSpinBox()
        self.idx_min.setRange(0, 20)
        self.idx_min.setValue(0)
        self.idx_min.setSpecialValueText("不限")
        self.index_filter_flow.addWidget(self._filter_field("最少行星", self.idx_min))
        self.idx_moons = QComboBox()
        self.idx_moons.addItem("不限", 0)
        self.idx_moons.addItem("≥1", 1)
        self.idx_moons.addItem("≥2", 2)
        self.idx_moons.setToolTip("只保留至少拥有该数量卫星的星系")
        self.index_filter_flow.addWidget(self._filter_field("卫星", self.idx_moons))
        self.idx_interceptor = QComboBox()
        self.idx_interceptor.addItem("不限", None)
        self.idx_interceptor.addItem("有", True)
        self.index_filter_flow.addWidget(self._filter_field("拦截机", self.idx_interceptor))
        iv.addWidget(self.index_filter_flow)

        self.index_stats = muted("索引统计：读取中…")
        self.index_table = GalaxyTable(0, 7)
        self.index_table.setHorizontalHeaderLabels(
            ["坐标", "符文串", "行星数", "种族", "异常",
             "拦截机种子", "命中行星"])
        self._configure_table(self.index_table)
        self.index_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.index_table.setSortingEnabled(True)
        self.index_table.itemSelectionChanged.connect(self._select_index)
        self.index_table.cellDoubleClicked.connect(
            lambda row, _col: self._on_table_double_click(self.index_table, row))
        self.index_empty = EmptyState(
            "还没有银河索引结果", "按条件点顶部「查询」，或先扫描一片区域；索引会越扫越全。",
            icon="◇")
        self.index_pane = self._table_pane(self.index_table, self.index_empty)
        iv.addWidget(self.index_pane, 1)
        iv.addWidget(self.index_stats)
        self.tabs.addTab(self.index_page, "银河索引")

        # 「已发现」「符文」是独立视图，不是星图的内部分栏。
        # 用 QStackedWidget 承载，避免同一个页面里再叠一层标签条，
        # 也让每个视图可以拥有自己的标题/筛选条/主操作。
        self.discovered_page = self._build_discovered_page()
        self.address_page = self._build_address_page()
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.tabs)             # 0 星图
        self.view_stack.addWidget(self.discovered_page)  # 1 已发现
        self.view_stack.addWidget(self.address_page)     # 2 地址工作台
        self.view_stack.currentChanged.connect(self._on_section_changed)
        mv.addWidget(self.view_stack, 1)

        mv.addWidget(self.status)
        split.addWidget(mid)

        right = Card("详情")
        self.detail_card = right
        rv = right.v
        self.detail_title = QLabel("选择行星")
        self.detail_title.setStyleSheet("font-size:15px;font-weight:700;")
        detail_head = QHBoxLayout()
        detail_head.setSpacing(6)
        detail_head.addWidget(self.detail_title, 1)
        self.detail_close_btn = QPushButton("×")
        self.detail_close_btn.setObjectName("uxIconButton")
        self.detail_close_btn.setFixedSize(22, 22)
        self.detail_close_btn.setToolTip("关闭详情，把空间还给结果区")
        self.detail_close_btn.setAccessibleName("关闭详情")
        self.detail_close_btn.clicked.connect(self._close_detail)
        detail_head.addWidget(self.detail_close_btn)
        rv.addLayout(detail_head)
        self.detail = muted(
            "点表格里的行星、扫描结果、银河索引或已发现行星查看详情；双击打开详情窗。")
        rv.addWidget(self.detail)
        self.detail_glyph = GalaxyGlyphLabel(max_height=40)
        rv.addWidget(self.detail_glyph)
        row = QHBoxLayout()
        self.copy_selected_glyph_btn = QPushButton("复制符文串")
        self.copy_selected_glyph_btn.clicked.connect(self._copy_selected_glyph)
        row.addWidget(self.copy_selected_glyph_btn)
        self.copy_selected_coords_btn = QPushButton("复制坐标")
        self.copy_selected_coords_btn.clicked.connect(self._copy_selected_coords)
        row.addWidget(self.copy_selected_coords_btn)
        rv.addLayout(row)
        self.warp_btn = QPushButton("传送到此星球")
        self.warp_btn.setToolTip("调用游戏内传送门机制，传送到当前选中的星球")
        self.warp_btn.setEnabled(False)
        self.warp_btn.clicked.connect(self._warp_selected_planet)
        rv.addWidget(self.warp_btn)
        rv.addStretch(1)
        right.setMinimumWidth(300)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.set_default_sizes([680, 360])
        split.restore()

        self.loading = LoadingOverlay(self, "正在读取当前星系…")
        self._set_empty_state(self.planets, self.planets_empty, False)
        self._set_empty_state(self.ships, self.ships_empty, False)
        self._set_empty_state(self.scan_table, self.scan_empty, False)
        self._set_empty_state(self.index_table, self.index_empty, False)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._sync_primary_action()

    def _build_scan_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.scan_pane = self._table_pane(self.scan_table, self.scan_empty)
        v.addWidget(self.scan_pane, 1)
        return page

    def _build_discovered_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(6)

        # 一屏一个任务：① 筛选 → ② 选中 → ③ 传送。
        self.disc_flow = TaskFlow(["筛选", "选中一颗", "传送"])
        v.addWidget(self.disc_flow)

        toolbar = QFrame()
        toolbar.setObjectName("uxToolbar")
        th = QHBoxLayout(toolbar)
        th.setContentsMargins(10, 6, 10, 6)
        th.setSpacing(6)

        # 快速筛选：只放最常用的 3 个（存档 / 群系 / 距离）。
        self.disc_filter_flow = GalaxyFlowBar(h_spacing=6, v_spacing=6)

        self.disc_save = QComboBox()
        self.disc_save.addItem("全部存档", None)
        self.disc_save.setMinimumWidth(150)
        self.disc_save.setToolTip(
            "默认汇总存档目录下所有可读的 save*.hg；也可以只看某一个存档。")
        self.disc_filter_flow.addWidget(self._filter_field("存档", self.disc_save))

        self.disc_biome = QComboBox()
        self.disc_biome.addItem("不限", None)
        for name in DISCOVERY_BIOMES:
            self.disc_biome.addItem(zh_mod.biome_label(name), name)
        self.disc_filter_flow.addWidget(self._filter_field("群系", self.disc_biome))

        self.disc_distance = QDoubleSpinBox()
        self.disc_distance.setRange(0, 1_000_000)
        self.disc_distance.setDecimals(0)
        self.disc_distance.setSingleStep(100)
        self.disc_distance.setSuffix(" ly")
        self.disc_distance.setSpecialValueText("不限")
        self.disc_distance.setValue(0)
        self.disc_distance.setMinimumWidth(100)
        self.disc_distance.setEnabled(False)
        self.disc_distance.setToolTip("只显示距当前星系不超过该距离的已发现星球；需先点右侧按钮确定中心")
        self.disc_filter_flow.addWidget(self._filter_field("距离", self.disc_distance))

        self.disc_center_btn = QPushButton("设为中心")
        self.disc_center_btn.setObjectName("ghostButton")
        self.disc_center_btn.setCheckable(True)
        self.disc_center_btn.setToolTip(
            "把当前星系设为距离中心；再次点击可清除中心并关闭距离筛选")
        self.disc_center_btn.toggled.connect(self._toggle_discovered_origin)
        self.disc_filter_flow.addWidget(self.disc_center_btn)

        th.addWidget(self.disc_filter_flow, 1)

        self.disc_more_btn = QPushButton("筛选")
        self.disc_more_btn.setObjectName("ghostButton")
        self.disc_more_btn.setCheckable(True)
        self.disc_more_btn.setToolTip("更多筛选：关键词 / 虫蚀 / 命名 / 排序 / 上限")
        th.addWidget(self.disc_more_btn)
        v.addWidget(toolbar)

        self.disc_chips = FilterChips()
        self.disc_chips.removed.connect(self._remove_disc_filter)
        v.addWidget(self.disc_chips)

        # 次要筛选收进可展开面板，不占首屏。
        self.disc_filter_panel = FilterPanel()
        self.disc_more_flow = GalaxyFlowBar(h_spacing=6, v_spacing=6)

        self.disc_keyword = QLineEdit()
        self.disc_keyword.setPlaceholderText("行星名 / 星系 / 坐标 / 符文")
        self.disc_keyword.setClearButtonEnabled(True)
        self.disc_keyword.setMinimumWidth(190)
        self.disc_more_flow.addWidget(self._filter_field("关键词", self.disc_keyword))

        self.disc_infested = QComboBox()
        self.disc_infested.addItem("不限", None)
        self.disc_infested.addItem("虫蚀", True)
        self.disc_infested.addItem("非虫蚀", False)
        self.disc_more_flow.addWidget(self._filter_field("虫蚀", self.disc_infested))

        self.disc_named = QComboBox()
        self.disc_named.addItem("不限", None)
        self.disc_named.addItem("已命名", True)
        self.disc_named.addItem("未命名", False)
        self.disc_more_flow.addWidget(self._filter_field("命名", self.disc_named))

        self.disc_sort = QComboBox()
        for label, value in (("距离（银河中心）", "distance"), ("最近发现", "discovered"),
                             ("群系", "biome"), ("名称", "name")):
            self.disc_sort.addItem(label, value)
        self.disc_more_flow.addWidget(self._filter_field("排序", self.disc_sort))

        self.disc_limit = QComboBox()
        for label, value in (("500 条", 500), ("1000 条", 1000), ("全部", 0)):
            self.disc_limit.addItem(label, value)
        self.disc_limit.setToolTip("结果上限；筛选仍会作用在全部记录上")
        self.disc_more_flow.addWidget(self._filter_field("上限", self.disc_limit))

        self.disc_filter_panel.body.addWidget(self.disc_more_flow)
        self.disc_more_btn.toggled.connect(self.disc_filter_panel.setVisible)
        v.addWidget(self.disc_filter_panel)

        self.disc_origin_hint = muted("距离中心：未设置")
        v.addWidget(self.disc_origin_hint)

        self._disc_filter_timer = QTimer(self)
        self._disc_filter_timer.setSingleShot(True)
        self._disc_filter_timer.setInterval(260)
        self._disc_filter_timer.timeout.connect(self._apply_discovered_filters)

        self.disc_stats = muted("已发现：读取中…")
        v.addWidget(self.disc_stats)

        self.disc_table = GalaxyTable(0, len(DISCOVERED_COLUMNS))
        self.disc_table.setHorizontalHeaderLabels(DISCOVERED_COLUMNS)
        self._configure_table(self.disc_table)
        self.disc_table.setSortingEnabled(True)
        self.disc_table.itemSelectionChanged.connect(self._select_discovered)
        self.disc_table.cellDoubleClicked.connect(
            lambda row, _col: self._on_table_double_click(self.disc_table, row))
        self.disc_empty = EmptyState(
            "正在读取已发现星球…", "正在建立/读取本地发现索引，请稍候。",
            icon="◇")
        self.disc_pane = self._table_pane(self.disc_table, self.disc_empty)
        v.addWidget(self.disc_pane, 1)
        self._autosize_table(self.disc_table, (56, 168, 62, 44, 118, 80, 104, 148))
        self._set_empty_state(
            self.disc_table, self.disc_empty, False,
            "正在读取已发现星球…", "正在建立/读取本地发现索引，请稍候。")

        for widget in (self.disc_biome, self.disc_infested, self.disc_named,
                       self.disc_save, self.disc_sort, self.disc_limit):
            widget.currentIndexChanged.connect(self._apply_discovered_filters)
            widget.currentIndexChanged.connect(self._update_disc_chips)
        self.disc_distance.valueChanged.connect(self._apply_discovered_filters)
        self.disc_distance.valueChanged.connect(self._update_disc_chips)
        self.disc_keyword.textChanged.connect(
            lambda _text: self._disc_filter_timer.start())
        self.disc_keyword.textChanged.connect(self._update_disc_chips)
        self._update_disc_chips()
        self.discovered_page = page
        return page

    def _update_disc_chips(self, *_args) -> None:
        items: list[tuple[str, str]] = []
        save = self.disc_save.currentData()
        if save:
            items.append(("save", f"存档 {self.disc_save.currentText()}"))
        if self.disc_biome.currentData():
            items.append(("biome", f"群系 {self.disc_biome.currentText()}"))
        if self.disc_infested.currentData() is not None:
            items.append(("infested", "虫蚀" if self.disc_infested.currentData() else "非虫蚀"))
        if self.disc_named.currentData() is not None:
            items.append(("named", "已命名" if self.disc_named.currentData() else "未命名"))
        keyword = self.disc_keyword.text().strip()
        if keyword:
            items.append(("keyword", f"关键词 {keyword}"))
        if self.disc_distance.value() > 0:
            items.append(("distance", f"距离 ≤ {int(self.disc_distance.value())} ly"))
        if str(self.disc_sort.currentData() or "distance") != "distance":
            items.append(("sort", f"排序 {self.disc_sort.currentText()}"))
        self.disc_chips.set_filters(items)

    def _remove_disc_filter(self, key: str) -> None:
        key = str(key or "")
        if key == "save":
            self.disc_save.setCurrentIndex(0)
        elif key == "biome":
            self.disc_biome.setCurrentIndex(0)
        elif key == "infested":
            self.disc_infested.setCurrentIndex(0)
        elif key == "named":
            self.disc_named.setCurrentIndex(0)
        elif key == "keyword":
            self.disc_keyword.clear()
        elif key == "distance":
            self.disc_center_btn.setChecked(False)
            self.disc_distance.setValue(0)
        elif key == "sort":
            self.disc_sort.setCurrentIndex(0)
        self._update_disc_chips()
        self._apply_discovered_filters()

    # ---------------------------------------------------------------- 主操作

    def _tab_key(self) -> str:
        stack = getattr(self, "view_stack", None)
        if stack is not None:
            current = stack.currentWidget()
            if current is self.discovered_page:
                return "discovered"
            if current is self.address_page:
                return "address"
        widget = self.tabs.currentWidget()
        if widget is self.index_page:
            return "index"
        if widget is self.scan_page:
            return "scan"
        return "current"

    def show_section(self, key: str) -> None:
        """切到「星图 / 已发现 / 地址工作台」中的一块（外壳左栏调用）。

        星图内部仍是 4 个子标签；已发现与地址工作台是独立视图，没有标签条。
        """
        name = str(key or "").strip()
        if not name:
            return
        # 切视图先收掉旧选择，避免详情/传送目标跨视图残留。
        self._selection = {}
        self._update_warp_action(None)
        if name in ("已发现", "discovered", "discoveries"):
            self.view_stack.setCurrentWidget(self.discovered_page)
            if not self._discovered_loading:
                # 30 秒内重复进入不重建索引：避免“每点一次就重新加载”。
                # 超过窗口或点「更多 → 刷新发现索引」才走增量索引；
                # 存档没变时是毫秒级快路径，变了才会重新解析。
                fresh = (self._discovered_loaded
                         and time.monotonic() - self._discovered_loaded_at < 30)
                if fresh:
                    self._sync_primary_action()
                else:
                    self._load_discovered(rebuild=True)
            return
        if name in ("地址工作台", "address", "glyphs", "符文"):
            self.view_stack.setCurrentWidget(self.address_page)
            try:
                self.addr_input.setFocus(Qt.OtherFocusReason)
                self.addr_input.selectAll()
            except (AttributeError, RuntimeError):
                pass
            return
        # 其余都回到星图；按名字选中内部子标签（行星 / 扫描结果 / 银河索引）。
        self.view_stack.setCurrentWidget(self.tabs)
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == name:
                self.tabs.setCurrentIndex(index)
                break
        self._sync_primary_action()

    def _on_section_changed(self, _index: int) -> None:
        self._sync_primary_action()
        self.status.setText(self._ready_status())

    def _on_tab_changed(self, _index: int) -> None:
        for table in (self.planets, self.ships, self.scan_table,
                      self.index_table, self.disc_table):
            try:
                table.clearSelection()
            except RuntimeError:
                continue
        self._selection = {}
        self._update_warp_action(None)
        self.status.setText(self._ready_status())
        self._sync_primary_action()

    def _ready_status(self) -> str:
        return {
            "scan": "就绪：点顶部「扫描」按当前条件扫描附近星系。",
            "index": "就绪：按条件查询已扫描的银河索引。",
            "discovered": "就绪：选择一条已发现行星后可传送。",
            "address": "就绪：输入符文 / 坐标 / UA，点顶部「转换地址」。",
        }.get(self._primary_mode,
               "就绪：查看当前星系；点顶部「扫描」找附近星系。")

    def _sync_primary_action(self) -> None:
        """按当前视图决定唯一 primary 的语义、页头文案与可见筛选条。"""
        mode = self._tab_key()
        self._primary_mode = mode
        scanning = bool(self._scan_job is not None
                        and getattr(self._scan_job, "status", "") == "running")
        scanning = scanning or self.scan_cancel_btn.isVisible()
        has_target = self._warp_target is not None and not self._warp_busy

        titles = {
            "current": ("星图", "查看当前星系的行星与船池；扫描附近星系找乐土。"),
            "scan": ("星图 · 扫描结果", "按群系 / 哨兵 / 种族扫描附近星系，结果写入银河索引。"),
            "index": ("星图 · 银河索引", "查询已扫描的星系索引；选中后可传送。"),
            "discovered": ("已发现星球",
                           "全部存档的发现记录；跨档自动去重，选中后可传送。"),
            "address": ("地址工作台", "符文 / 坐标 / UA 三形态互转。"),
        }
        title, subtitle = titles.get(mode, titles["current"])
        try:
            if self.header.title.text() != title:
                self.header.title.setText(title)
                self.header.title.setToolTip(title)
            if self.header.subtitle.text() != subtitle:
                self.header.subtitle.setText(subtitle)
                self.header.subtitle.setToolTip(subtitle)
        except RuntimeError:
            pass

        if mode == "index":
            self.primary_btn.setText("查询中…" if self._index_busy else "查询")
            self.primary_btn.setToolTip("按条件查询已扫描的银河索引")
            self.primary_btn.setEnabled(not self._index_busy)
        elif mode == "discovered":
            self.primary_btn.setText("传送中…" if self._warp_busy else "传送到此星球")
            if has_target and self._warp_tooltip:
                self.primary_btn.setToolTip(self._warp_tooltip)
            else:
                self.primary_btn.setToolTip(
                    "调用游戏内传送门机制，传送到选中的已发现星球"
                    if has_target else "选择一条已发现行星后可传送")
            self.primary_btn.setEnabled(has_target)
        elif mode == "address":
            self.primary_btn.setText("转换地址")
            self.primary_btn.setToolTip(
                "把输入解析成「符文 / 坐标 / UA」三形态；非法输入会说明原因")
            self.primary_btn.setEnabled(not self._addr_busy)
        else:
            self.primary_btn.setText("扫描中…" if scanning else "扫描")
            self.primary_btn.setToolTip("扫描附近星系并写入银河索引")
            self.primary_btn.setEnabled(not scanning)

        # 扫描条件只服务扫描相关标签；其它标签各自有自己的筛选条。
        self.scan_filter_box.setVisible(mode in ("current", "scan"))
        # 「当前星系」大卡只在星图视图有意义；已发现/符文各自是独立视图。
        try:
            self.hero.setVisible(mode in ("current", "scan", "index"))
            card_title = {"discovered": "", "address": "地址转换"
                          }.get(mode, "行星与船池")
            if self.mid_card.title_label.text() != card_title:
                self.mid_card.title_label.setText(card_title)
            self.mid_card.title_label.setVisible(bool(card_title))
            # 结果优先：没选中时不占右侧空间，选中后才出现详情。
            self.detail_card.setVisible(mode != "address" and bool(self._selection))
            self.detail_close_btn.setVisible(mode != "address")
            if hasattr(self, "map_flow"):
                self.map_flow.setVisible(mode in ("current", "scan", "index"))
                if mode in ("current", "scan", "index"):
                    if self._selection:
                        self.map_flow.set_active(2, done=(0, 1))
                    elif scanning or self._index_busy:
                        self.map_flow.set_active(1, done=(0,))
                    else:
                        self.map_flow.set_active(1, done=(0,))
            if hasattr(self, "disc_flow"):
                if mode == "discovered":
                    if self._warp_busy:
                        self.disc_flow.set_active(2, done=(0, 1))
                    elif self._selection:
                        self.disc_flow.set_active(1, done=(0,))
                    else:
                        self.disc_flow.set_active(0)
            if not self._selection:
                hint = {
                    "discovered": "点表格里的已发现行星查看详情；双击打开详情窗口。",
                    "address": "",
                }.get(mode, "点表格里的行星、扫描结果、银河索引或已发现行星查看详情；双击打开详情窗口。")
                if hint and self.detail.text() != hint:
                    self.detail.setText(hint)
        except (AttributeError, RuntimeError):
            pass
        # 「已发现」的主操作就是传送，详情卡不再重复一个传送按钮。
        self.warp_btn.setVisible(mode != "discovered")
        if mode != "discovered":
            self.warp_btn.setEnabled(has_target and not self._warp_busy)
        self.refresh_action.setEnabled(mode != "address")
        self.refresh_action.setText("刷新发现索引" if mode == "discovered" else "刷新当前星系")
        self.export_action.setText("导出已发现 CSV" if mode == "discovered" else "导出 CSV")
        self.export_action.setEnabled(self._has_exportable_rows(mode))
        self.overlay_action.setEnabled(bool(self._selected_glyphs()))
        self.clear_filters_action.setEnabled(mode in ("current", "scan", "index", "discovered"))
        self.seed_action.setEnabled(mode == "address")

    def _refresh_current_mode(self) -> None:
        """「更多 → 刷新」按当前视图刷新对应数据。"""
        if self._tab_key() == "discovered":
            self._load_discovered(manual=True, rebuild=True)
        else:
            self._load_current(manual=True)

    def _on_primary(self) -> None:
        mode = self._primary_mode
        if mode == "index":
            self._query_index()
        elif mode == "discovered":
            self._warp_selected_planet()
        elif mode == "address":
            self._address_submit()
        else:
            self._scan()

    def _has_exportable_rows(self, mode: str) -> bool:
        if mode == "index":
            return bool(self._index_rows)
        if mode == "discovered":
            return bool(self._discovered_rows)
        return bool(self._scan_rows or self.planets.rowCount() or self.ships.rowCount())

    def _export_current_csv(self) -> None:
        mode = self._tab_key()
        if mode == "index":
            self._export_index_csv()
        elif mode == "discovered":
            self._export_discovered_csv()
        else:
            self._export_csv()

    def _clear_current_filters(self) -> None:
        mode = self._tab_key()
        if mode == "index":
            for widget in (self.idx_biome, self.idx_sent, self.idx_race,
                           self.idx_diss, self.idx_interceptor):
                widget.setCurrentIndex(0)
            self.idx_min.setValue(0)
            self.status.setText("已清空银河索引筛选条件。")
        elif mode == "discovered":
            self.disc_center_btn.setChecked(False)
            for widget in (self.disc_biome, self.disc_infested, self.disc_named):
                widget.setCurrentIndex(0)
            self.disc_distance.setValue(0)
            self.status.setText("已清空已发现筛选条件。")
        else:
            self._reset_scan_filters()

    def _on_table_double_click(self, table: QTableWidget, row: int) -> None:
        """双击 = 查看详情；选中仍然只负责启用传送。"""
        try:
            table.selectRow(row)
        except RuntimeError:
            return
        title = self.detail_title.text()
        body = self.detail.text()
        if not body:
            return
        self._show_detail_dialog(title, body, self._selected_glyphs())

    def _show_detail_dialog(self, title: str, body: str,
                            glyphs: str | None = None) -> None:
        try:
            if self._detail_dialog is not None:
                self._detail_dialog.close()
        except RuntimeError:
            pass
        try:
            dialog = GalaxyDetailDialog(title, body, glyphs=glyphs, parent=self)
            dialog.show()
            self._detail_dialog = dialog
        except Exception as e:                              # noqa: BLE001
            self.status.setText(f"详情窗打开失败：{type(e).__name__}: {e}")
            notify.error(f"详情窗打开失败：{type(e).__name__}: {e}")

    def _seed_lookup(self) -> None:
        """次要动作：0x… 种子反查，命中后把第一条候选填进地址工作台。"""
        seed_text, ok = QInputDialog.getText(
            self, "种子反查", "输入 0x… 十六进制种子（候选越多越慢）：")
        if not ok:
            return
        try:
            seed = parse_seed(seed_text)
        except ValueError as e:
            self.status.setText(f"种子校验失败：{e}")
            notify.error(f"种子校验失败：{e}")
            return
        text = f"0x{seed:016X}"
        self._addr_set_busy(True, f"正在反查种子 {text}…（候选越多越慢）")
        notify.toast(f"正在反查种子 {text}…（候选越多越慢）")

        def done(res: dict) -> None:
            self._addr_set_busy(False)
            hits = res.get("hits") or []
            if not hits:
                reason = res.get("reason") or "没有可信候选。"
                self.status.setText(f"种子反查无结果：{reason}")
                notify.warn(f"种子反查无结果：{reason}")
                return
            hit = hits[0]
            glyphs = str(hit.get("glyphs") or "").strip().upper()
            if not glyphs:
                self.status.setText("种子反查命中，但候选没有可用的符文串。")
                notify.warn("种子反查命中，但候选没有可用的符文串")
                return
            self.addr_input.setText(glyphs)
            self._address_submit()
            self.status.setText(
                f"种子反查命中 {len(hits)} 个；已填入第一个候选 {glyphs}。")
            notify.success(f"种子反查命中 {len(hits)} 个；已填入第一个候选")

        def fail(msg: str) -> None:
            self._addr_set_busy(False, f"种子反查失败：{msg}")
            notify.error(f"种子反查失败：{msg}")

        run_worker(self.svc.locate, done, fail, seed=text)


    def _table_pane(self, table: QTableWidget, empty: EmptyState) -> GalaxyTablePane:
        """空态叠在表格上方：矮窗口里不会再和表格抢高度、把文字压扁。"""
        self._fix_empty_size(empty)
        pane = GalaxyTablePane(table, empty)
        self._panes[id(table)] = pane
        return pane

    @staticmethod
    def _fix_empty_size(empty: EmptyState) -> None:
        # EmptyState 内部布局是居中对齐；若标题/说明被设成 Ignored 尺寸策略，
        # 宽度会缩成一个字符，所以这里显式恢复可伸展的策略。
        for label in (empty.title_label, empty.description_label):
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            label.setMinimumWidth(0)
        # 空态标题很短，强制换行只会把最后两个字挤到第二行。
        empty.title_label.setWordWrap(False)

    def _wrap_table(self, table: QTableWidget, empty: EmptyState) -> QWidget:
        return self._table_pane(table, empty)

    @staticmethod
    def _filter_field(label: str, widget: QWidget) -> QWidget:
        """把"标签 + 控件"绑成一个换行单元，避免标签和下拉框被拆到两行。"""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(QLabel(label))
        row.addWidget(widget)
        return box

    def _configure_table(self, table: QTableWidget) -> None:
        """列宽可调 + 内容自适应；最后一列占满剩余宽度，窄窗口横向滚动。"""
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setWordWrap(False)
        table.setMinimumHeight(64)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(26)
        header = table.horizontalHeader()
        header.setMinimumSectionSize(44)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)

    @staticmethod
    def _autosize_table(table: QTableWidget, widths: tuple[int, ...] = ()) -> None:
        if isinstance(table, GalaxyTable) and widths:
            table.set_base_widths(widths)
            return
        table.resizeColumnsToContents()
        for column in range(table.columnCount()):
            want = int(widths[column]) if column < len(widths) else table.columnWidth(column)
            table.setColumnWidth(column, max(44, min(260, want)))

    def _set_empty_state(self, table: QTableWidget, empty: EmptyState, has_rows: bool,
                         title: str | None = None,
                         description: str | None = None) -> None:
        if title is not None:
            empty.title_label.setText(title)
        if description is not None:
            empty.description_label.setText(description)
            empty.description_label.setVisible(bool(description))
        pane = self._panes.get(id(table))
        if pane is not None:
            pane.set_empty(not has_rows)
        elif has_rows:
            empty.hide()
            table.show()
        else:
            table.hide()
            empty.show()

    def sizeHint(self) -> QSize:                     # noqa: N802 - Qt 回调
        """避免把"表格内容期望高度"当成整页高度，让外层滚动区无谓滚动。

        最小高度仍由布局决定（内容多时照常滚动），这里只把过高的 sizeHint
        收敛到常见窗口内容区，页面本身不需要 700+px 才能用。
        """
        hint = super().sizeHint()
        floor = self.minimumSizeHint().height()
        return QSize(hint.width(), max(floor, min(hint.height(), 640)))

    # ---------------------------------------------------------------- 筛选条

    def _scan_filters(self) -> dict:
        filters: dict = {}
        if self.biome.currentData():
            filters["biome"] = self.biome.currentData()
        if self.sent.currentData():
            filters["sentinels"] = self.sent.currentData()
        if self.race.currentData():
            filters["race"] = self.race.currentData()
        if self.diss.currentData() is not None:
            filters["dissonant"] = True
        if self.min_planets.value() > 0:
            filters["min_planets"] = int(self.min_planets.value())
        if int(self.moons.currentData() or 0) > 0:
            filters["min_moons"] = int(self.moons.currentData())
        if self.interceptor.currentData():
            filters["has_interceptor"] = True
        return filters

    def _update_filter_summary(self) -> None:
        parts = []
        if self.biome.currentData():
            parts.append(f"群系 {self.biome.currentText()}")
        if self.sent.currentData():
            parts.append(f"哨兵 {self.sent.currentText()}")
        if self.race.currentData():
            parts.append(f"种族 {self.race.currentText()}")
        if self.diss.currentData() is not None:
            parts.append("仅异常")
        if self.min_planets.value() > 0:
            parts.append(f"行星不少于 {self.min_planets.value()} 颗")
        if int(self.moons.currentData() or 0) > 0:
            parts.append(f"卫星不少于 {self.moons.currentData()} 颗")
        if self.interceptor.currentData():
            parts.append("有拦截机")
        summary = " · ".join(parts) if parts else "不限条件"
        self.filter_summary.setText(
            f"筛选摘要：{summary}；扫描范围 {int(self.count.value())} 个系统。")

    def _reset_scan_filters(self) -> None:
        for widget in (self.biome, self.sent, self.race, self.interceptor,
                       self.moons, self.diss):
            widget.setCurrentIndex(0)
        self.min_planets.setValue(0)
        self.count.setValue(200)
        self._update_filter_summary()
        self.status.setText("筛选条件已重置：将扫描全部群系/种族。")

    # ---------------------------------------------------------------- 当前星系

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._load_current()
        self._refresh_index_stats()
        # 「已发现」按需加载：进入该视图时才索引全部存档（多存档会慢一些）。

    def _load_current(self, manual: bool = False) -> None:
        self.status.setText("加载中：正在读取当前星系…")
        self.error_banner.clear()
        self.current_empty.hide()
        self.loading.start("正在读取当前星系…")

        def done(res: dict) -> None:
            self.loading.stop()
            self._current_info = res
            name = res.get("name") or res.get("system_name") or "当前星系"
            self.badge.setText(f"{name}  ·  {res.get('glyphs') or '—'}  ·  {res.get('coords') or '—'}")
            self.hero_info.setText(
                f"种族：{res.get('race_zh') or res.get('race') or '—'}  ·  "
                f"行星：{res.get('planets', 0)}  ·  "
                f"异常：{'是' if res.get('dissonant') else '否'}")
            self._set_glyph(self.glyph, res.get("glyphs"))
            pls = res.get("planet_list") or []
            self.planets.setSortingEnabled(False)
            self.planets.setRowCount(len(pls))
            for i, p in enumerate(pls):
                vals = [str(p.get("index", "")), p.get("biome_zh") or p.get("biome_name") or "",
                        p.get("sentinels_zh") or p.get("sentinels") or "",
                        p.get("resources") or p.get("resource") or "",
                        "是" if res.get("dissonant") else "否"]
                for j, v in enumerate(vals):
                    item = QTableWidgetItem(str(v))
                    item.setData(Qt.UserRole, p)
                    self.planets.setItem(i, j, item)
            self.planets.setSortingEnabled(True)
            ships = res.get("ships") or []
            self.ships.setSortingEnabled(False)
            self.ships.setRowCount(len(ships))
            for i, s in enumerate(ships):
                vals = [s.get("type_label") or s.get("type") or "",
                        s.get("kind_zh") or s.get("kind") or "",
                        s.get("seed") or "", s.get("source") or ""]
                for j, v in enumerate(vals):
                    item = QTableWidgetItem(str(v))
                    item.setData(Qt.UserRole, s)
                    self.ships.setItem(i, j, item)
            self.ships.setSortingEnabled(True)
            self._autosize_table(self.planets, (48, 140, 120, 160, 72))
            self._autosize_table(self.ships, (150, 120, 160, 160))
            self._set_empty_state(
                self.planets, self.planets_empty, bool(pls),
                "当前星系没有行星",
                "没有读到行星数据；请确认存档/游戏目录，或用「更多 → 刷新当前星系」。")
            self._set_empty_state(
                self.ships, self.ships_empty, bool(ships),
                "当前星系没有船",
                "没有读到船池数据；请确认存档/游戏目录，或用「更多 → 刷新当前星系」。")
            if pls or ships:
                if self._tab_key() in ("current", "scan", "index"):
                    self.status.setText(f"当前星系：{len(pls)} 颗行星 / {len(ships)} 艘船")
                self.current_empty.hide()
                if manual:
                    notify.success("当前星系已刷新")
            else:
                if self._tab_key() in ("current", "scan", "index"):
                    self.status.setText("当前星系为空：没有读取到行星或船池数据。")
                self.current_empty.title_label.setText("当前星系没有结果")
                self.current_empty.description_label.setText(
                    "没有读到行星或船池数据；请确认存档/游戏目录，再用「更多 → 刷新当前星系」。")
                self.current_empty.description_label.show()
                self.current_empty.show()
                notify.warn("当前星系没有读取到行星或船池数据")
            self._sync_primary_action()

        def fail(msg: str) -> None:
            self.loading.stop()
            self._current_info = {}
            self.status.setText(f"当前星系不可用：{msg}")
            self.hero_info.setText("错误态：没有读到当前星系；请确认存档/游戏目录。")
            self.glyph.clear()
            self.error_banner.set_reason(f"当前星系加载失败：{msg}")
            self.error_banner.show()
            self.current_empty.title_label.setText("没有可用的当前星系")
            self.current_empty.description_label.setText(
                f"{msg}\n请先在设置页配置存档/游戏目录，再重试。")
            self.current_empty.description_label.show()
            self.current_empty.show()
            self._set_empty_state(
                self.planets, self.planets_empty, False, "没有当前星系的行星",
                "当前星系不可用；请先确认存档/游戏目录。")
            self._set_empty_state(
                self.ships, self.ships_empty, False, "没有当前星系的船池",
                "当前星系不可用；请先确认存档/游戏目录。")
            self._sync_primary_action()
            notify.error(f"当前星系加载失败：{msg}")

        run_worker(self.svc.system, done, fail)

    def _set_glyph(self, label: QLabel, text: str | None) -> None:
        if not text:
            label.clear()
            return
        def done(data: bytes) -> None:
            pix = QPixmap()
            pix.loadFromData(data, "PNG")
            if pix.isNull():
                return
            if hasattr(label, "set_glyph_pixmap"):
                label.set_glyph_pixmap(pix)
            else:
                label.setPixmap(pix)
            label.setToolTip(str(text))
        run_worker(self.svc.glyph_strip_png, done, lambda _m: None, text)

    def _copy_text(self, text: str | None, label: str, target: QLabel | None = None) -> bool:
        where = target or self.status
        if not text:
            where.setText(f"当前没有可复制的{label}。")
            notify.warn(f"当前没有可复制的{label}")
            return False
        QGuiApplication.clipboard().setText(str(text))
        where.setText(f"{label}已复制到剪贴板。")
        notify.success(f"{label}已复制到剪贴板")
        return True

    # ---------------------------------------------------------------- 地址工作台

    def _build_address_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("地址"))
        self.addr_input = QLineEdit()
        self.addr_input.setPlaceholderText(
            "12 位符文（如 3112F19BDCE5）/ 坐标 04E4:0070:01BC:0112 / 0x… UA")
        self.addr_input.setClearButtonEnabled(True)
        self.addr_input.setToolTip(
            "三种输入互转：12 位符文、X:Y:Z:SSSS 坐标、0x… UA；回车或点顶部主操作转换")
        self.addr_input.returnPressed.connect(self._address_submit)
        row.addWidget(self.addr_input, 1)
        row.addWidget(QLabel("行星位"))
        self.addr_planet = QComboBox()
        self.addr_planet.addItem("未知（0）", 0)
        for number in range(1, 7):
            self.addr_planet.addItem(str(number), number)
        self.addr_planet.setCurrentIndex(1)      # 坐标不含行星位时默认 1 号
        self.addr_planet.setToolTip(
            "坐标输入不含行星位时使用；符文/UA 自带行星位。未知（0）不可传送")
        row.addWidget(self.addr_planet)
        v.addLayout(row)

        v.addWidget(muted(
            "输入任一形态即可：12 位符文 / X:Y:Z:SSSS 坐标 / 0x… UA；"
            "另外两种会自动算出。行星位为 0 时标注“未知行星，不可传送”。"))

        examples = QHBoxLayout()
        examples.setSpacing(6)
        examples.addWidget(muted("示例："))
        for label, value in (("符文", "3112F19BDCE5"),
                             ("坐标", "04E4:0070:01BC:0112"),
                             ("UA", "0x10DEFF474570")):
            button = QPushButton(label)
            button.setObjectName("ghostButton")
            button.setToolTip(f"填入一个{label}示例并立即转换")
            button.clicked.connect(
                lambda _checked=False, v=value: self._fill_address_example(v))
            examples.addWidget(button)
        examples.addStretch(1)
        v.addLayout(examples)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        self.addr_glyphs_edit = self._addr_output_edit()
        self.addr_glyphs_copy = self._addr_copy_button("复制符文")
        self.addr_coords_edit = self._addr_output_edit()
        self.addr_coords_copy = self._addr_copy_button("复制坐标")
        self.addr_ua_edit = self._addr_output_edit()
        self.addr_ua_copy = self._addr_copy_button("复制 UA")
        for index, (label, edit, button) in enumerate((
                ("符文", self.addr_glyphs_edit, self.addr_glyphs_copy),
                ("坐标", self.addr_coords_edit, self.addr_coords_copy),
                ("UA", self.addr_ua_edit, self.addr_ua_copy))):
            grid.addWidget(QLabel(label), index, 0)
            grid.addWidget(edit, index, 1)
            grid.addWidget(button, index, 2)
        v.addLayout(grid)

        self.addr_note = muted("")
        self.addr_note.setVisible(False)
        v.addWidget(self.addr_note)

        self.addr_glyph = GalaxyGlyphLabel(max_height=40)
        v.addWidget(self.addr_glyph)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.addr_fill = QPushButton("填入游戏内传送输入")
        self.addr_fill.setObjectName("ghostButton")
        self.addr_fill.setToolTip("只把符文填进「联动 → 传送」的输入框，不直接执行传送")
        self.addr_fill.setEnabled(False)
        self.addr_fill.clicked.connect(self._fill_addr_teleport)
        actions.addWidget(self.addr_fill)
        actions.addStretch(1)
        v.addLayout(actions)
        v.addStretch(1)

        # 外壳的「符文」入口会聚焦 addr_lookup；这里指向页面唯一的主按钮。
        self.addr_lookup = self.primary_btn
        self.addr_copy = self.addr_glyphs_copy
        self.addr_glyphs_copy.clicked.connect(self._copy_addr_glyphs)
        self.addr_coords_copy.clicked.connect(self._copy_addr_coords)
        self.addr_ua_copy.clicked.connect(self._copy_addr_ua)
        self._addr_clear_glyph()
        self.address_page = page
        return page

    @staticmethod
    def _addr_output_edit() -> QLineEdit:
        edit = QLineEdit()
        edit.setReadOnly(True)
        edit.setPlaceholderText("—")
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return edit

    @staticmethod
    def _addr_copy_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("ghostButton")
        button.setEnabled(False)
        button.setToolTip(f"{text}（当前结果）")
        return button

    def _fill_address_example(self, value: str) -> None:
        """示例按钮：填入并立即转换；不触发传送，也不复制。"""
        self.addr_input.setText(str(value))
        self.addr_input.selectAll()
        self._address_submit()

    def _addr_set_busy(self, busy: bool, text: str | None = None) -> None:
        self._addr_busy = busy
        for widget in (self.addr_input, self.addr_planet, self.addr_fill,
                       self.addr_glyphs_copy, self.addr_coords_copy, self.addr_ua_copy):
            widget.setEnabled(not busy)
        if busy:
            self.addr_fill.setEnabled(False)
        else:
            self.addr_fill.setEnabled(bool(self._addr_glyphs and self._addr_teleportable))
            self.addr_glyphs_copy.setEnabled(bool(self._addr_glyphs))
            self.addr_coords_copy.setEnabled(bool(self._addr_coords))
            self.addr_ua_copy.setEnabled(bool(self._addr_ua_text))
        if text is not None:
            self.status.setText(text)
        self._sync_primary_action()

    def _addr_clear_glyph(self) -> None:
        self._addr_glyphs = None
        self._addr_coords = None
        self._addr_ua_text = None
        self._addr_teleportable = False
        for edit in (self.addr_glyphs_edit, self.addr_coords_edit, self.addr_ua_edit):
            edit.clear()
            edit.setText("")
        for button in (self.addr_glyphs_copy, self.addr_coords_copy, self.addr_ua_copy):
            button.setEnabled(False)
        self.addr_note.clear()
        self.addr_note.setVisible(False)
        self.addr_glyph.clear()
        self.addr_fill.setEnabled(False)

    def _address_submit(self) -> None:
        if self._addr_busy:
            return
        planet = int(self.addr_planet.currentData() or 0)
        result = convert_address(self.addr_input.text(), planet=planet)
        if not result.get("ok"):
            self._addr_clear_glyph()
            reason = result.get("message") or "无法识别输入。"
            self.status.setText(f"地址转换失败：{reason}")
            notify.error(f"地址转换失败：{reason}")
            self._sync_primary_action()
            return

        self._addr_glyphs = result.get("glyphs")
        self._addr_coords = result.get("coords")
        self._addr_ua_text = result.get("ua_text")
        self._addr_teleportable = bool(result.get("teleportable"))
        self.addr_glyphs_edit.setText(self._addr_glyphs or "—")
        self.addr_coords_edit.setText(self._addr_coords or "—")
        self.addr_ua_edit.setText(self._addr_ua_text or "—")
        for edit in (self.addr_glyphs_edit, self.addr_coords_edit, self.addr_ua_edit):
            edit.setCursorPosition(0)
        self.addr_glyphs_copy.setEnabled(bool(self._addr_glyphs))
        self.addr_coords_copy.setEnabled(bool(self._addr_coords))
        self.addr_ua_copy.setEnabled(bool(self._addr_ua_text))
        self.addr_fill.setEnabled(bool(self._addr_glyphs and self._addr_teleportable))

        if result.get("kind") in ("glyphs", "ua"):
            index = self.addr_planet.findData(result.get("planet"))
            if index >= 0:
                self.addr_planet.blockSignals(True)
                try:
                    self.addr_planet.setCurrentIndex(index)
                finally:
                    self.addr_planet.blockSignals(False)

        warning = str(result.get("warning") or "")
        self.addr_note.setText(warning)
        self.addr_note.setVisible(bool(warning))
        if self._addr_glyphs:
            self._set_glyph(self.addr_glyph, self._addr_glyphs)
        else:
            self.addr_glyph.clear()

        if warning:
            self.status.setText(
                f"转换完成：坐标 {self._addr_coords or '—'} · UA {self._addr_ua_text or '—'}"
                "；符文不可生成。")
            notify.warn(warning)
        else:
            self.status.setText(
                f"转换完成：符文 {self._addr_glyphs} · 坐标 {self._addr_coords}"
                f" · UA {self._addr_ua_text}；可分别复制。")
            notify.success("地址转换完成：符文 / 坐标 / UA 已生成")
        self._sync_primary_action()

    def _copy_addr_glyphs(self) -> None:
        self._copy_text(self._addr_glyphs, "符文串", self.status)

    def _copy_addr_coords(self) -> None:
        self._copy_text(self._addr_coords, "坐标", self.status)

    def _copy_addr_ua(self) -> None:
        self._copy_text(self._addr_ua_text, "UA", self.status)

    def _fill_teleport_input(self, glyphs: str | None, coords: str | None = None,
                             status_label=None) -> None:
        target_label = status_label or self.status
        if not glyphs:
            target_label.setText("定位/前往失败：当前没有可填入传送输入的符文串。")
            notify.warn("定位/前往失败：当前没有可填入传送的符文串")
            return
        self._teleport_glyphs = glyphs
        target = None
        pages = getattr(self.window(), "pages", None)
        if isinstance(pages, dict):
            target = getattr(pages.get("live"), "glyphs", None)
        if target is not None and hasattr(target, "setText"):
            target.setText(glyphs)
            if hasattr(target, "setFocus"):
                target.setFocus()
            target_label.setText(
                f"已填入游戏内传送输入：{glyphs}"
                f"{' · 坐标 ' + coords if coords else ''}（仅界面状态，未写入游戏）。")
            notify.success(f"已填入传送输入：{glyphs}（仅界面状态，未写入游戏）")
        else:
            target_label.setText(
                f"已暂存传送地址：{glyphs}（游戏内页面不可用；未写入游戏）。")
            notify.warn(f"已暂存传送地址：{glyphs}（游戏内页面不可用，未写入游戏）")

    def _fill_addr_teleport(self) -> None:
        if not self._addr_teleportable:
            self.status.setText(f"无法填入传送：{PLANET_UNKNOWN}。")
            notify.warn(f"无法填入传送：{PLANET_UNKNOWN}")
            return
        self._fill_teleport_input(self._addr_glyphs, self._addr_coords, self.status)

    # ---------------------------------------------------------------- 银河索引

    def _index_filters(self) -> dict:
        filters = {}
        if self.idx_biome.currentData():
            filters["biome"] = self.idx_biome.currentData()
        if self.idx_sent.currentData():
            filters["sentinels"] = self.idx_sent.currentData()
        if self.idx_race.currentData():
            filters["race"] = self.idx_race.currentData()
        if self.idx_diss.currentData() is not None:
            filters["dissonant"] = bool(self.idx_diss.currentData())
        if self.idx_min.value() > 0:
            filters["min_planets"] = int(self.idx_min.value())
        if int(self.idx_moons.currentData() or 0) > 0:
            filters["min_moons"] = int(self.idx_moons.currentData())
        if self.idx_interceptor.currentData():
            filters["has_interceptor"] = True
        return filters

    def _fill_index(self, rows: list[dict]) -> None:
        self._update_warp_action(None)
        self.index_table.clearSelection()
        self.index_table.setSortingEnabled(False)
        self.index_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            matched = r.get("matched_planets") or []
            planets = r.get("planets")
            if planets is None:
                planets = len(matched)
            race = r.get("race") or ""
            vals = [r.get("coords") or "—", r.get("glyphs") or "—", str(planets),
                    RACE_LABELS.get(race, race or "—"),
                    "是" if r.get("dissonant") else "否",
                    r.get("interceptor") or "—", f"{len(matched)} 颗"]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if j == 0:
                    item.setData(Qt.UserRole, r)
                self.index_table.setItem(i, j, item)
        self.index_table.setSortingEnabled(True)
        self._autosize_table(self.index_table, (154, 112, 52, 70, 48, 100, 72))

    def _query_index(self) -> None:
        if self._index_busy:
            return
        filters = self._index_filters()
        self._index_busy = True
        self.index_stats.setText("索引统计：查询中…")
        self.status.setText("查询中：正在查询银河索引…")
        self._sync_primary_action()
        notify.toast("正在查询银河索引…")

        def done(res: dict) -> None:
            self._index_busy = False
            rows = res.get("rows") or []
            stats = res.get("stats") or {}
            self._index_rows = rows
            self._fill_index(rows)
            self.index_stats.setText(
                f"索引库：{stats.get('systems', 0)} 个星系 / {stats.get('planets', 0)} 颗行星"
                f"  ·  命中 {len(rows)} 个星系")
            self._set_empty_state(
                self.index_table, self.index_empty, bool(rows),
                "没有匹配的星系", "请放宽条件，或先扫描一片区域；索引会越扫越全。")
            if rows:
                self.status.setText(f"查询完成：命中 {len(rows)} 个星系。")
                notify.success(f"银河索引查询完成：命中 {len(rows)} 个星系")
            else:
                self.status.setText("没有匹配的星系；请放宽条件，或先扫描一片区域。")
                notify.warn("银河索引没有匹配的星系；请放宽条件或先扫描")
            self._sync_primary_action()

        def fail(msg: str) -> None:
            self._index_busy = False
            self._index_rows = []
            self._fill_index([])
            self._set_empty_state(
                self.index_table, self.index_empty, False,
                "索引查询失败", "请检查索引数据库或稍后重试。")
            self.index_stats.setText("索引统计：不可用")
            self.status.setText(f"查询失败：{msg}")
            self._sync_primary_action()
            notify.error(f"银河索引查询失败：{msg}")

        run_worker(self.svc.galaxy_query, done, fail, filters=filters, limit=500)

    def _refresh_index_stats(self) -> None:
        self.index_stats.setText("索引统计：加载中…")

        def done(st: dict) -> None:
            self.index_stats.setText(
                f"索引库：{st.get('systems', 0)} 个星系 / {st.get('planets', 0)} 颗行星")

        def fail(msg: str) -> None:
            self.index_stats.setText(f"索引统计不可用：{msg}")

        run_worker(self.svc.galaxy_stats, done, fail)

    def _select_index(self) -> None:
        rows = self.index_table.selectionModel().selectedRows()
        if not rows:
            self._update_warp_action(None)
            return
        item = self.index_table.item(rows[0].row(), 0)
        r = item.data(Qt.UserRole) if item else None
        if not r:
            return
        matched = r.get("matched_planets") or []
        race = r.get("race") or ""
        lines = [
            f"种族：{RACE_LABELS.get(race, race or '—')}",
            f"行星：{r.get('planets', len(matched))}  ·  卫星：{r.get('moons', 0)}",
            f"异常：{'是' if r.get('dissonant') else '否'}",
            f"拦截机种子：{r.get('interceptor') or '—'}",
        ]
        if matched:
            names = [f"#{p.get('index', '?')} {p.get('biome') or '—'}"
                     f" / 哨兵 {p.get('sentinels') or '—'}" for p in matched[:8]]
            more = " …" if len(matched) > 8 else ""
            lines.append("命中行星：" + "；".join(names) + more)
        self.detail_title.setText(r.get("coords") or "银河索引结果")
        self.detail.setText("\n".join(lines))
        self._set_glyph(self.detail_glyph, r.get("glyphs"))
        self._selection = r
        self._update_warp_action(r)

    def _export_index_csv(self) -> None:
        try:
            data = self.svc.galaxy_export_csv(self._index_filters())
        except Exception as e:                              # noqa: BLE001
            self.status.setText(f"导出失败：{type(e).__name__}: {e}")
            notify.error(f"导出失败：{type(e).__name__}: {e}")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出银河索引（CSV 表格文件）", "galaxy-index.csv", "CSV 表格文件 (*.csv)")
        if not path:
            return
        try:
            Path(path).write_text(data, "utf-8")
        except Exception as e:                              # noqa: BLE001
            self.status.setText(f"写入失败：{type(e).__name__}: {e}")
            notify.error(f"写入失败：{type(e).__name__}: {e}")
            return
        self.status.setText(f"已导出：{path}")
        notify.success(f"已导出银河索引（CSV 表格文件）：{path}")

    # ---------------------------------------------------------------- 已发现

    def _discovered_filters(self) -> dict:
        filters: dict = {}
        if self.disc_biome.currentData():
            filters["biome"] = self.disc_biome.currentData()
        if self.disc_infested.currentData() is not None:
            filters["infested"] = bool(self.disc_infested.currentData())
        if self.disc_named.currentData() is not None:
            filters["named"] = bool(self.disc_named.currentData())
        if self._discovered_origin_ua not in (None, ""):
            filters["near_ua"] = self._discovered_origin_ua
            distance = float(self.disc_distance.value())
            if distance > 0:
                filters["max_distance"] = distance
        return filters

    def _discovered_query_kwargs(self) -> dict:
        """``Services.discoveries_query`` 接受的参数（索引不直接支持 max_distance）。"""
        query: dict = {}
        if self.disc_biome.currentData():
            query["biome"] = self.disc_biome.currentData()
        if self.disc_infested.currentData() is not None:
            query["infested"] = bool(self.disc_infested.currentData())
        if self.disc_named.currentData() is not None:
            query["named"] = bool(self.disc_named.currentData())
        save_id = self.disc_save.currentData()
        if save_id:
            query["save_ids"] = [str(save_id)]
        keyword = self.disc_keyword.text().strip()
        if keyword:
            query["keyword"] = keyword
        order = str(self.disc_sort.currentData() or "distance")
        limit = int(self.disc_limit.currentData() or 0)
        if self._discovered_origin_ua not in (None, ""):
            query["near_ua"] = self._discovered_origin_ua
            query["order"] = "distance"
            # 有距离上限时让服务层再筛一遍，索引层先多取一些
            query["limit"] = None if self.disc_distance.value() > 0 else (limit or None)
        else:
            query["order"] = order
            # 多存档会有重复行星：先取全量、去重后再按「上限」截断
            query["limit"] = (limit or None) if save_id else None
        return query

    def _toggle_discovered_origin(self, checked: bool) -> None:
        if not checked:
            self._discovered_origin_ua = None
            self.disc_origin_hint.setText("距离中心：未设置")
            self.disc_distance.blockSignals(True)
            try:
                self.disc_distance.setValue(0)
                self.disc_distance.setEnabled(False)
            finally:
                self.disc_distance.blockSignals(False)
            self.disc_distance.setToolTip(
                "只显示距当前星系不超过该距离的已发现星球；需先点右侧按钮确定中心")
            self._apply_discovered_filters()
            return

        current = self._current_info if isinstance(self._current_info, dict) else {}
        ua = current.get("ua")
        if ua in (None, ""):
            self.disc_center_btn.blockSignals(True)
            try:
                self.disc_center_btn.setChecked(False)
            finally:
                self.disc_center_btn.blockSignals(False)
            self.disc_origin_hint.setText("距离中心：当前星系不可用")
            self.disc_distance.setEnabled(False)
            self.disc_stats.setText("已发现：当前星系不可用，无法设置距离中心。")
            notify.warn("当前星系不可用，无法作为距离中心")
            return

        self._discovered_origin_ua = ua
        label = current.get("coords") or str(ua)
        self.disc_origin_hint.setText(f"距离中心：{label}")
        self.disc_distance.setEnabled(True)
        self.disc_distance.setToolTip(
            f"只显示距 {label} 不超过该距离的已发现星球；0 表示不限距离")
        self._apply_discovered_filters()

    def _render_discovered_stats(self, shown: int, *, total: int | None = None,
                                 available: bool = True, note: str = "") -> None:
        warnings = list(self._discovered_warnings or [])
        if not available:
            self.disc_stats.setText("已发现：不可用")
        else:
            total = int(total if total is not None else shown)
            parts = [f"已发现：{total} 颗", f"显示 {shown} 颗"]
            limit = int(self.disc_limit.currentData() or 0)
            if limit and shown >= limit:
                parts.append(f"已达上限 {limit}")
            if note:
                parts.append(note)
            self.disc_stats.setText(" · ".join(parts))
        self.disc_stats.setToolTip("\n".join(warnings))

    def _refresh_discovered_saves(self, saves: list[dict] | None = None) -> None:
        """用索引里的存档列表填充「存档」筛选；保留用户当前选择。"""
        rows = [item for item in (saves or [])
                if isinstance(item, dict) and item.get("save_id")]
        current = self.disc_save.currentData()
        self.disc_save.blockSignals(True)
        try:
            self.disc_save.clear()
            self.disc_save.addItem(f"全部存档（{len(rows)}）", None)
            for item in rows:
                name = str(item.get("name") or "save.hg")
                count = int(item.get("count") or 0)
                self.disc_save.addItem(f"{name}（{count}）", item.get("save_id"))
            index = self.disc_save.findData(current) if current else 0
            self.disc_save.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.disc_save.blockSignals(False)
        self._update_disc_chips()

    def _set_discovered_filter_enabled(self, enabled: bool) -> None:
        for widget in (self.disc_save, self.disc_keyword, self.disc_biome,
                       self.disc_infested, self.disc_named, self.disc_sort,
                       self.disc_limit, self.disc_center_btn):
            widget.setEnabled(enabled)
        self.disc_distance.setEnabled(enabled and self.disc_center_btn.isChecked())

    def _fill_discovered(self, rows: list[dict]) -> None:
        self._update_warp_action(None)
        self.disc_table.clearSelection()
        self.disc_table.setSortingEnabled(False)
        self.disc_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            cells = _discovered_cells(row)
            sort_values = _discovered_sort_values(row)
            for j, value in enumerate(cells):
                item = _DiscoveredSortItem(str(value))
                item.setData(DISCOVERED_SORT_ROLE, sort_values[j])
                if j == 0:
                    item.setData(Qt.UserRole, row)
                self.disc_table.setItem(i, j, item)
        # 默认保留服务层排序（距离/发现时间）；用户点表头仍可自行排序。
        self.disc_table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.disc_table.setSortingEnabled(True)
        self._autosize_table(self.disc_table, (56, 168, 62, 44, 118, 80, 104, 148))

    def _load_discovered(self, manual: bool = False, *, rebuild: bool = True) -> None:
        """首次/刷新时先建索引，再查索引；筛选变化只查索引。"""
        if self._discovered_loading:
            return
        if self.disc_distance.value() > 0 and self._discovered_origin_ua in (None, ""):
            self.disc_stats.setText("已发现：请先点「设为中心」确定距离中心。")
            return
        self._discovered_loading = True
        self.disc_stats.setText(
            "已发现：刷新中…" if rebuild and self._discovered_rows else
            ("已发现：建立索引…" if rebuild else "已发现：筛选中…"))
        self.disc_stats.setToolTip("")
        if rebuild and not self._discovered_rows:
            self._set_empty_state(
                self.disc_table, self.disc_empty, False,
                "正在建立发现索引…", "只读存档、只写本地缓存；首次会慢一些。")

        seq = self._discovered_filter_seq + 1
        self._discovered_filter_seq = seq
        query_kwargs = self._discovered_query_kwargs()
        filters = self._discovered_filters()
        fallback_filters = dict(filters)
        fallback_filters.update({"sort": "auto", "limit": 500})
        index_count = int((self._discovered_index_meta or {}).get("count") or 0)

        def load() -> dict:
            index_res = None
            if rebuild:
                index_res = self.svc.discoveries_index_all()
                if not index_res.get("ok"):
                    # 索引坏了也保留可用性：退回直接读取当前存档。
                    base = self.svc.discovered_planets()
                    if not base.get("ok"):
                        reason = ((base.get("warnings") or [])[:1]
                                  or [index_res.get("error") or "读取发现记录失败"])[0]
                        return {"ok": False, "warnings": [str(reason)]}
                    filtered = self.svc.discovered_filter(
                        planets=base.get("planets") or [], **fallback_filters)
                    return {
                        "ok": True,
                        "fallback": True,
                        "index": index_res,
                        "rows": filtered.get("planets") or [],
                        "total": int(base.get("count") or 0),
                        "warnings": list(base.get("warnings") or [])
                        + [f"索引不可用：{index_res.get('error') or '未知原因'}"],
                    }
            else:
                index_res = dict(self._discovered_index_meta or {})
                if not index_res.get("ok"):
                    # 之前索引就不可用：筛选变化继续走直接读取，避免二次失败。
                    base = self.svc.discovered_planets()
                    if not base.get("ok"):
                        reason = ((base.get("warnings") or [])[:1]
                                  or [index_res.get("error") or "读取发现记录失败"])[0]
                        return {"ok": False, "warnings": [str(reason)]}
                    filtered = self.svc.discovered_filter(
                        planets=base.get("planets") or [], **fallback_filters)
                    return {
                        "ok": True,
                        "fallback": True,
                        "index": index_res,
                        "rows": filtered.get("planets") or [],
                        "total": int(base.get("count") or 0),
                        "warnings": list(base.get("warnings") or [])
                        + [f"索引不可用：{index_res.get('error') or '未知原因'}"],
                    }

            query = dict(query_kwargs)
            queried = self.svc.discoveries_query(**query)
            rows = [row for row in (queried.get("planets") or []) if isinstance(row, dict)]
            if filters.get("max_distance"):
                # 索引查询没有 max_distance：这里仍交给服务层按距离再筛一次。
                filtered = self.svc.discovered_filter(
                    planets=rows,
                    near_ua=filters.get("near_ua"),
                    max_distance=filters.get("max_distance"),
                    limit=500,
                )
                rows = [row for row in (filtered.get("planets") or [])
                        if isinstance(row, dict)]
            rows = self._dedupe_discovered(rows)
            limit = int(self.disc_limit.currentData() or 0)
            if limit and len(rows) > limit:
                rows = rows[:limit]
            total = index_count
            if rebuild:
                total = int((index_res or {}).get("count") or 0)
            return {"ok": True, "index": index_res, "rows": rows,
                    "total": total, "warnings": []}

        def done(res) -> None:
            if seq != self._discovered_filter_seq:
                return
            self._discovered_loading = False
            self._discovered_loaded = True
            self._discovered_loaded_at = time.monotonic()
            res = res if isinstance(res, dict) else {}
            self._discovered_warnings = [
                str(w) for w in (res.get("warnings") or []) if str(w).strip()]
            index_meta = res.get("index") if isinstance(res.get("index"), dict) else {}
            self._discovered_index_meta = index_meta
            self._discovered_has_data = bool(res.get("ok"))
            rows = [row for row in (res.get("rows") or []) if isinstance(row, dict)]
            self._discovered_rows = rows
            self._discovered_all = rows
            total = int(res.get("total") or 0)
            self._discovered_meta = {
                "count": total,
                "cached": bool(index_meta.get("cached")),
                "rebuilt": bool(index_meta.get("rebuilt")),
            }
            self._fill_discovered(rows)
            if isinstance(index_meta.get("saves"), list):
                self._refresh_discovered_saves(index_meta["saves"])

            if not self._discovered_has_data:
                self._set_discovered_filter_enabled(False)
                reason = (self._discovered_warnings[0] if self._discovered_warnings
                          else "没有读取到当前存档的发现数据。")
                self._set_empty_state(
                    self.disc_table, self.disc_empty, False,
                    "没有可用的已发现数据",
                    f"{reason}\n请先在设置页配置存档/游戏目录，再刷新。")
                self._render_discovered_stats(0, available=False)
                self._sync_primary_action()
                if manual:
                    notify.warn(f"已发现星球不可用：{reason}")
                return

            self._set_discovered_filter_enabled(True)
            notes = []
            if res.get("fallback"):
                notes.append("直接读取")
            save_count = len(index_meta.get("saves") or [])
            if save_count > 1:
                notes.append(f"{save_count} 个存档")
            note = " · ".join(notes)
            if total <= 0:
                self._set_empty_state(
                    self.disc_table, self.disc_empty, False,
                    "没有已发现的星球",
                    "存档目录里没有 Planet 类型的发现记录；可先扫描或继续探索后刷新。")
                self._render_discovered_stats(0, total=0, note=note)
            elif not rows:
                self._set_empty_state(
                    self.disc_table, self.disc_empty, False,
                    "没有匹配的已发现星球",
                    "当前筛选条件下没有命中；请放宽群系/虫蚀/命名/距离条件。")
                self._render_discovered_stats(0, total=total, note=note)
            else:
                self._set_empty_state(self.disc_table, self.disc_empty, True)
                self._render_discovered_stats(len(rows), total=total, note=note)
            self._sync_primary_action()
            if manual:
                notify.success(f"已发现星球已刷新：索引 {total} 颗")

        def fail(msg: str) -> None:
            if seq != self._discovered_filter_seq:
                return
            self._discovered_loading = False
            self._discovered_loaded = True
            self._discovered_loaded_at = time.monotonic()
            if rebuild:
                self._discovered_has_data = False
                self._discovered_all = []
                self._discovered_rows = []
                self._discovered_meta = {}
                self._discovered_index_meta = {}
                self._discovered_warnings = [str(msg)]
                self._fill_discovered([])
                self._set_discovered_filter_enabled(False)
                self._set_empty_state(
                    self.disc_table, self.disc_empty, False,
                    "没有可用的已发现数据",
                    f"读取已发现星球失败：{msg}\n请先在设置页配置存档/游戏目录，再刷新。")
                self._render_discovered_stats(0, available=False)
                notify.warn(f"读取已发现星球失败：{msg}")
            else:
                self._discovered_rows = []
                self._fill_discovered([])
                self._set_empty_state(
                    self.disc_table, self.disc_empty, False,
                    "筛选已发现星球失败",
                    f"没有拿到筛选结果：{msg}\n请检查条件后重试。")
                self.disc_stats.setText(f"已发现：筛选失败（{msg}）")
                notify.warn(f"筛选已发现星球失败：{msg}")
            self._sync_primary_action()

        run_worker(load, done, fail)

    def _apply_discovered_filters(self, *_args) -> None:
        if not self._discovered_has_data:
            return
        self._load_discovered(rebuild=False)

    @staticmethod
    def _dedupe_discovered(rows: list[dict]) -> list[dict]:
        """同名行星/同一地址在多份存档里只显示一行，来源合并成「save.hg 等 N 个」。"""
        seen: dict[tuple, dict] = {}
        out: list[dict] = []
        for row in rows:
            key = (str(row.get("system_ua") or ""), row.get("planet_index"),
                   str(row.get("planet_ua") or ""))
            name = str(row.get("save_name") or "")
            if key in seen:
                item = seen[key]
                names = item.setdefault("_save_names", [])
                if name and name not in names:
                    names.append(name)
                if len(names) > 1:
                    ordered = sorted(names)
                    label = " + ".join(ordered[:2])
                    if len(ordered) > 2:
                        label += f" +{len(ordered) - 2}"
                    item["save_name"] = label
                continue
            item = dict(row)
            item["_save_names"] = [name] if name else []
            seen[key] = item
            out.append(item)
        return out

    def _close_detail(self) -> None:
        for table in (self.planets, self.ships, self.scan_table,
                      self.index_table, self.disc_table):
            try:
                table.clearSelection()
            except RuntimeError:
                continue
        self._selection = {}
        self._update_warp_action(None)

    def _select_discovered(self) -> None:
        rows = self.disc_table.selectionModel().selectedRows()
        if not rows:
            self._update_warp_action(None)
            return
        item = self.disc_table.item(rows[0].row(), 0)
        row = item.data(Qt.UserRole) if item else None
        if not isinstance(row, dict):
            self._update_warp_action(None)
            return
        self._selection = row
        index = row.get("planet_index")
        title = str(row.get("name") or (f"已发现行星 #{index}"
                                        if index is not None else "已发现行星"))
        lines = [
            (f"行星：{('#' + str(index)) if index is not None else '—'}"
             f" · 星系：{row.get('system_name') or row.get('coords') or '—'}"),
            (f"群系：{_discovered_biome_text(row.get('biome'))}"
             f" · 虫蚀：{_discovered_flag_text(row.get('infested'))}"),
            f"命名：{row.get('name') or '未命名'}",
            f"符文：{row.get('glyphs') or '—'}",
            f"坐标：{row.get('coords') or '—'}",
            f"发现者：{row.get('discoverer') or '—'}",
            (f"时间：{_discovered_timestamp_text(row.get('discovered_at'))}"
             f" · 来源：{row.get('save_name') or _discovered_source_text(row)}"),
        ]
        if row.get("distance_ly") not in (None, ""):
            lines.append(f"距离：{_discovered_distance_text(row.get('distance_ly'))}")
        self.detail_title.setText(title)
        self.detail.setText("\n".join(lines))
        self._set_glyph(self.detail_glyph, row.get("glyphs"))
        self._update_warp_action(self._discovered_warp_row(row))

    @staticmethod
    def _discovered_warp_row(row: dict) -> dict:
        """缺行星序号但仍有系统地址时，交给现有「选择行星 1-6」流程。"""
        warp = dict(row)
        if warp.get("ua") in (None, "") and warp.get("system_ua") not in (None, ""):
            warp["ua"] = warp["system_ua"]
        if not warp.get("system_name"):
            warp["system_name"] = warp.get("coords") or warp.get("system_ua") or ""
        return warp

    @staticmethod
    def _discovered_csv_text(rows: list[dict]) -> str:
        header = list(DISCOVERED_COLUMNS) + ["坐标", "发现者", "发现时间", "来源"]
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(header)
        for row in rows:
            cells = _discovered_cells(row)
            cells[5] = _discovered_distance_csv(row.get("distance_ly"))
            writer.writerow(cells + [
                row.get("coords") or "",
                row.get("discoverer") or "",
                _discovered_timestamp_text(row.get("discovered_at")),
                _discovered_source_text(row),
            ])
        return buffer.getvalue()

    def _export_discovered_csv(self) -> None:
        rows = [row for row in (self._discovered_rows or []) if isinstance(row, dict)]
        if not rows:
            self.disc_stats.setText("导出失败：当前没有可导出的已发现星球。")
            notify.warn("导出失败：当前没有可导出的已发现星球")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出已发现星球（CSV 表格文件）", "discovered-planets.csv",
            "CSV 表格文件 (*.csv)")
        if not path:
            return
        try:
            data = self._discovered_csv_text(rows)
            Path(path).write_text(data, "utf-8")
        except Exception as e:                              # noqa: BLE001
            self.disc_stats.setText(f"导出失败：{type(e).__name__}: {e}")
            notify.error(f"导出失败：{type(e).__name__}: {e}")
            return
        self.disc_stats.setText(f"已导出 {len(rows)} 颗已发现星球：{path}")
        notify.success(f"已导出已发现星球（CSV 表格文件）：{path}")

    # ---------------------------------------------------------------- 扫描

    @staticmethod
    def _scan_row_matches(system: dict, planet: dict, filters: dict) -> bool:
        if filters.get("dissonant") and not system.get("dissonant"):
            return False
        if filters.get("min_planets"):
            try:
                if int(system.get("planets") or 0) < int(filters["min_planets"]):
                    return False
            except (TypeError, ValueError):
                return False
        if filters.get("min_moons"):
            try:
                if int(system.get("moons") or 0) < int(filters["min_moons"]):
                    return False
            except (TypeError, ValueError):
                return False
        if filters.get("has_interceptor") and not system.get("interceptor"):
            return False
        race = str(system.get("race") or "").lower()
        if filters.get("race") and race != str(filters["race"]).lower():
            return False
        if filters.get("biome"):
            biome = str(planet.get("biome_name") or planet.get("biome") or "").lower()
            if biome != str(filters["biome"]).lower():
                return False
        if filters.get("sentinels"):
            sentinels = str(planet.get("sentinels") or "").lower()
            if sentinels != str(filters["sentinels"]).lower():
                return False
        return True

    def _scan(self) -> None:
        job = self._scan_job
        if job is not None and getattr(job, "status", "") == "running":
            notify.warn("扫描正在进行中；可点「取消扫描」请求停止")
            return
        filters = self._scan_filters()
        self._last_scan_filters = filters
        self._update_filter_summary()
        self._update_warp_action(None)
        self.scan_cancel_btn.setEnabled(True)
        self.scan_cancel_btn.setVisible(True)
        self._sync_primary_action()
        self.status.setText(
            f"加载中：正在扫描附近星系并写入银河索引（{self.filter_summary.text()}）…")
        notify.toast(f"开始扫描附近星系（目标 {int(self.count.value())} 个系统）…")
        try:
            self._scan_job = self.svc.start_galaxy_scan(
                radius=0, systems_per_region=int(self.count.value()), filters=filters, limit=200)
        except Exception as e:                              # noqa: BLE001
            self.scan_cancel_btn.setVisible(False)
            self._sync_primary_action()
            self.status.setText(f"扫描无法开始：{type(e).__name__}: {e}")
            notify.error(f"扫描无法开始：{type(e).__name__}: {e}")
            return
        self._timer.start()

    def _cancel_scan(self) -> None:
        job = self._scan_job
        if job is None or getattr(job, "status", "") != "running":
            notify.warn("当前没有正在进行的扫描")
            return
        try:
            job.cancel()
        except Exception as e:                              # noqa: BLE001
            notify.error(f"取消扫描失败：{type(e).__name__}: {e}")
            return
        self.scan_cancel_btn.setEnabled(False)
        self.status.setText("正在取消扫描…（当前系统完成后停止）")
        notify.warn("已请求取消扫描；当前系统完成后停止")

    def _poll_scan(self) -> None:
        job = self._scan_job
        if job is None:
            self._timer.stop()
            return
        p = job.progress or {}
        scanned = int(p.get("scanned") or p.get("tested") or 0)
        target = int(self.count.value())
        self.status.setText(
            f"扫描进行中：已扫 {scanned} / {target} 个系统 · 可点顶部「取消扫描」")
        if job.status == "running":
            return
        self._timer.stop()
        self.scan_cancel_btn.setVisible(False)
        self.scan_cancel_btn.setEnabled(True)
        self._sync_primary_action()
        if job.status == "cancelled":
            self._scan_rows = []
            self._fill_scan_rows([])
            self._set_empty_state(
                self.scan_table, self.scan_empty, False,
                "扫描已取消", "已停止扫描；可调整条件后重新点顶部「扫描」。")
            self.status.setText(f"扫描已取消：已扫 {scanned} 个系统。")
            notify.warn("扫描已取消")
            return
        if job.error:
            self.status.setText(f"扫描失败：{job.error}")
            notify.error(f"扫描失败：{job.error}")
            return
        res = job.result or {}
        if isinstance(res, dict):
            hits = res.get("hits")
            if hits is None:
                hits = res.get("results") or []
        elif isinstance(res, list):
            hits = res
        else:
            hits = []
        filters = self._last_scan_filters or {}
        rows = []
        for system in hits:
            if not isinstance(system, dict):
                continue
            planets = system.get("planet_list") or []
            if not planets and (system.get("biome_name") or system.get("biome")):
                planets = [system]
            for planet in planets:
                if not isinstance(planet, dict):
                    continue
                if not self._scan_row_matches(system, planet, filters):
                    continue
                rows.append({**system, **planet,
                             "system_name": system.get("name") or system.get("system_name") or "",
                             "glyphs": system.get("glyphs") or planet.get("glyphs"),
                             "coords": system.get("coords") or planet.get("coords")})
        self._scan_rows = rows
        self._fill_scan_rows(rows)
        self._set_empty_state(
            self.scan_table, self.scan_empty, bool(rows),
            "没有匹配的星球", "扫描完成但没有命中；请放宽筛选条件或扩大扫描范围。")
        self.tabs.setCurrentWidget(self.scan_page)
        if rows:
            self.status.setText(f"扫描完成：命中 {len(rows)} 条（已写入银河索引）。")
            notify.success(f"扫描完成：命中 {len(rows)} 条，已写入银河索引")
        else:
            self.status.setText("扫描完成：没有匹配的星球；请放宽筛选条件或扩大扫描范围。")
            notify.warn("扫描完成：没有匹配的星球；请放宽筛选条件或扩大扫描范围")
        self._sync_primary_action()
        self._refresh_index_stats()

    def _fill_scan_rows(self, rows: list[dict]) -> None:
        self._update_warp_action(None)
        self.scan_table.clearSelection()
        self.scan_table.setSortingEnabled(False)
        self.scan_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [str(r.get("index", "—")),
                    r.get("biome_zh") or r.get("biome_name") or r.get("biome") or "—",
                    r.get("sentinels_zh") or r.get("sentinels") or "—",
                    r.get("coords") or "—",
                    r.get("glyphs") or "—",
                    r.get("system_name") or r.get("galaxy_name") or r.get("galaxy") or "—"]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.UserRole, r)
                self.scan_table.setItem(i, j, item)
        self.scan_table.setSortingEnabled(True)
        self._autosize_table(self.scan_table, (48, 100, 80, 190, 140, 100))
        self._sync_primary_action()

    def _select_planet(self) -> None:
        rows = self.planets.selectionModel().selectedRows()
        if not rows:
            self._update_warp_action(None)
            return
        item = self.planets.item(rows[0].row(), 0)
        p = item.data(Qt.UserRole) if item else None
        if not p:
            return
        info = self._current_info or {}
        selected = {**info, **p,
                    "index": p.get("index"),
                    "glyphs": info.get("glyphs") or p.get("glyphs"),
                    "coords": info.get("coords") or p.get("coords"),
                    "system_name": info.get("name") or info.get("system_name") or ""}
        self._selection = selected
        self.detail_title.setText(f"行星 #{p.get('index', '?')}")
        self.detail.setText(
            f"群系：{p.get('biome_zh') or p.get('biome_name') or '—'}\n"
            f"哨兵：{p.get('sentinels_zh') or p.get('sentinels') or '—'}\n"
            f"资源：{p.get('resources') or '—'}\n"
            f"坐标：{selected.get('coords') or '—'}\n"
            f"符文串：{selected.get('glyphs') or '—'}")
        self._set_glyph(self.detail_glyph, selected.get("glyphs"))
        self._update_warp_action(selected)

    def _select_scan(self) -> None:
        rows = self.scan_table.selectionModel().selectedRows()
        if not rows:
            self._update_warp_action(None)
            return
        item = self.scan_table.item(rows[0].row(), 0)
        r = item.data(Qt.UserRole) if item else None
        if not r:
            return
        self._selection = r
        self.detail_title.setText(r.get("coords") or "扫描结果")
        self.detail.setText(
            f"行星：#{r.get('index', '?')}\n"
            f"群系：{r.get('biome_zh') or r.get('biome_name') or r.get('biome') or '—'}\n"
            f"哨兵：{r.get('sentinels_zh') or r.get('sentinels') or '—'}\n"
            f"坐标：{r.get('coords') or '—'}\n"
            f"符文串：{r.get('glyphs') or '—'}\n"
            f"星系：{r.get('system_name') or r.get('galaxy_name') or r.get('galaxy') or '—'}")
        self._set_glyph(self.detail_glyph, r.get("glyphs"))
        self._update_warp_action(r)

    def _set_warp_busy(self, busy: bool) -> None:
        self._warp_busy = busy
        self.warp_btn.setText("传送中…" if busy else "传送到此星球")
        self._sync_primary_action()

    def _update_warp_action(self, row: dict | None = None) -> None:
        """刷新传送入口；选中行后只更新可用性、tooltip 与状态行。"""
        target = _warp_target_for(row) if isinstance(row, dict) else None
        self._warp_target = target
        self._warp_row = row if isinstance(row, dict) and target else None
        self._warp_tooltip = ""

        if target:
            planet_note = ("系统级结果：传送时可选择行星（1-6，默认 #1）"
                           if target.get("needs_planet") else target["planet_label"])
            glyphs = target.get("glyphs") or ""
            tooltip = (f"调用游戏内传送门机制，传送到 {target['system']}/{planet_note}"
                       + (f"（门地址 {glyphs}）" if glyphs else "（选择行星后生成门地址）"))
            self._warp_tooltip = tooltip
            self.warp_btn.setToolTip(tooltip)
            hint = f"已选择：{target['system']}/{planet_note}"
            hint += f" · 门地址 {glyphs}" if glyphs else " · 选择行星后生成门地址"
            self.status.setText(hint)
        else:
            self.warp_btn.setToolTip("选中一条能生成合法门地址的结果后可传送")
            if isinstance(row, dict):
                self.status.setText("该结果没有可用的门地址，无法传送。")
        self._sync_primary_action()

    def _ask_warp_planet(self) -> int | None:
        """系统级结果没有行星序号：让用户选 1..6（默认 1），不替用户猜。"""
        planet, ok = QInputDialog.getInt(
            self, "选择行星",
            "这条结果只有星系地址，没有行星序号。\n"
            "请选择要传送的行星（1-6，默认 1）；之后会再确认一次：",
            1, 1, 6, 1)
        return int(planet) if ok else None

    def _warp_selected_planet(self) -> None:
        target = self._warp_target
        row = self._warp_row
        if not target or not isinstance(row, dict):
            self.status.setText("传送失败：当前结果没有可用的门地址。")
            notify.warn("传送失败：请先选择一条能生成合法门地址的结果")
            return

        if target.get("needs_planet"):
            planet = self._ask_warp_planet()
            if planet is None:
                self.status.setText("已取消传送（没有选择行星）。")
                return
            resolved = _warp_target_for(row, planet=planet)
            if not resolved or not resolved.get("glyphs"):
                self.status.setText("传送失败：选中的行星生成不出合法门地址。")
                notify.warn("传送失败：该行星生成不出合法门地址")
                return
            target = resolved

        answer = QMessageBox.warning(
            self, "确认传送到此星球", _warp_confirm_text(target),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            self.status.setText("已取消传送。")
            return

        glyphs = target["glyphs"]
        self._set_warp_busy(True)
        self.status.setText(
            f"传送中：正在调用游戏内传送门传送到 "
            f"{target['system']}/{target['planet_label']}（{glyphs}）…")
        notify.toast(
            f"正在传送到 {target['system']}/{target['planet_label']}（{glyphs}）…")

        def restore() -> None:
            self._set_warp_busy(False)
            self._update_warp_action(self._warp_row)

        def done(res: dict) -> None:
            restore()
            res = res if isinstance(res, dict) else {}
            if not res.get("ok"):
                code = str(res.get("code") or "").strip()
                error = str(res.get("error") or "").strip() or "未知错误"
                message = " · ".join(p for p in (code, error) if p)
                if code == "E_BUILD_UNVERIFIED":
                    message += "；" + BUILD_UNVERIFIED_HINT
                self.status.setText(f"传送失败：{message}")
                notify.error(f"传送失败：{message}")
                return
            if res.get("confirmed") is False:
                detail = str(res.get("confirm_error") or "40 秒内未读回目标位置")
                self.status.setText(
                    f"传送未确认：{detail}（命令已执行；失败可用「还原」回滚）")
                notify.warn(f"传送未确认：{detail}")
                return
            self.status.setText(
                f"已传送到 {target['system']}/{target['planet_label']}。")
            notify.success(f"已传送到 {target['system']}/{target['planet_label']}")

        def fail(msg: str) -> None:
            restore()
            self.status.setText(f"传送失败：{msg}")
            notify.error(f"传送失败：{msg}")

        run_worker(self.svc.warp_portal, done, fail,
                   glyphs=glyphs, galaxy=target.get("galaxy"))

    def _selected_glyphs(self) -> str:
        return str(self._selection.get("glyphs") or self._current_info.get("glyphs") or "").strip()

    def _selected_coords(self) -> str:
        return str(self._selection.get("coords") or self._current_info.get("coords") or "").strip()

    def _copy_selected_glyph(self) -> None:
        self._copy_text(self._selected_glyphs(), "符文串")

    def _copy_selected_coords(self) -> None:
        self._copy_text(self._selected_coords(), "坐标")

    def _show_overlay(self) -> None:
        glyphs = self._selected_glyphs()
        if not glyphs:
            self.status.setText(
                "浮窗显示失败：请先在行星表、扫描结果、银河索引或已发现中选择一个带符文串的星球。")
            notify.warn("浮窗显示失败：请先选择一个带符文串的星球")
            return
        self.status.setText(f"加载中：正在生成符文浮窗 {glyphs}…")
        notify.toast(f"正在生成符文浮窗 {glyphs}…")
        try:
            data = self.svc.glyph_strip_png(glyphs)
        except Exception as e:                              # noqa: BLE001
            self.status.setText(f"浮窗显示失败：{type(e).__name__}: {e}")
            notify.error(f"浮窗显示失败：{type(e).__name__}: {e}")
            return
        if not data:
            self.status.setText("浮窗显示失败：没有生成符文图（glyphs 可能无效）。")
            notify.error("浮窗显示失败：没有生成符文图（glyphs 可能无效）")
            return
        try:
            from ..overlay import GlyphOverlay

            if self._overlay is not None:
                try:
                    self._overlay.close()
                except Exception:                           # noqa: BLE001
                    pass
            win = GlyphOverlay(data, glyphs, alpha=0.94, click_through=False, scale=1.0)
            win.show()
            self._overlay = win
            self.status.setText(
                f"符文浮窗已打开：{glyphs}（置顶显示；Esc 关闭，拖动可移动）。")
            notify.success(f"符文浮窗已打开：{glyphs}")
        except Exception as e:                              # noqa: BLE001
            self._overlay = None
            self.status.setText(f"浮窗显示失败：{type(e).__name__}: {e}")
            notify.error(f"浮窗显示失败：{type(e).__name__}: {e}")

    def _export_csv(self) -> None:
        filters = self._scan_filters()
        try:
            data = self.svc.galaxy_export_csv(filters)
        except Exception as e:                              # noqa: BLE001
            self.status.setText(f"导出失败：{type(e).__name__}: {e}")
            notify.error(f"导出失败：{type(e).__name__}: {e}")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出银河索引（CSV 表格文件）", "galaxy.csv", "CSV 表格文件 (*.csv)")
        if not path:
            return
        try:
            Path(path).write_text(data, "utf-8")
        except Exception as e:                              # noqa: BLE001
            self.status.setText(f"写入失败：{type(e).__name__}: {e}")
            notify.error(f"写入失败：{type(e).__name__}: {e}")
            return
        self.status.setText(f"已导出：{path}")
        notify.success(f"已导出银河索引（CSV 表格文件）：{path}")
