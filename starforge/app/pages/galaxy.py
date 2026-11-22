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
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import zh as zh_mod
from ...discoveries import BIOMES as DISCOVERY_BIOMES
from ...glyphs import glyphs_for_ua
from ...services import get_services
from .. import notify
from ..dialogs.address import classify_address_input, normalize_glyphs, parse_seed
from ..widgets.feedback import EmptyState, ErrorBanner, LoadingOverlay
from ..widgets.galaxy_flow import (
    GalaxyFlowBar,
    GalaxyGlyphLabel,
    GalaxyTable,
    GalaxyTablePane,
)
from ..widgets.page import PageSplitter, page_layout
from ..widgets.page_header import PageHeader
from ..widgets.ui import Card, muted
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
DISCOVERED_COLUMNS = ["行星序号", "星系", "群系", "虫蚀", "命名", "距离", "符文"]
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
    label = DISCOVERED_SOURCE_LABELS.get(source, source or "—")
    return f"{label}（待上传）" if row.get("pending") and label != "待上传" else label


def _discovered_biome_text(value) -> str:
    return zh_mod.biome_label(value) if value else "未知"


def _discovered_flag_text(value, *, yes: str = "是", no: str = "否") -> str:
    if value is None:
        return "未知"
    return yes if value else no


def _discovered_cells(row: dict) -> list[str]:
    """表格前 7 列（也是 CSV 的前 7 列），顺序与 DISCOVERED_COLUMNS 一致。"""
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
        self._teleport_glyphs: str | None = None
        self._addr_busy = False
        self._warp_target: dict | None = None
        self._warp_row: dict | None = None
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
        self._discovered_filter_seq = 0
        self._overlay = None
        self._sub_current = "读取中…"
        self._sub_scan = "未开始"
        self._sub_index = "读取中…"
        self._sub_address = "未查询"
        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._poll_scan)
        self._build_ui()

    def _build_ui(self) -> None:
        root = page_layout(self)

        self.header = PageHeader(
            "星图",
            "查看当前星系、行星与船池，扫描附近星系并写入银河索引。")
        # PageHeader 的 Minimum 垂直策略会把 sizeHint（完整副标题高度）
        # 当成最小高度；允许压缩后，矮窗口里主内容才有空间。
        self.header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.header.subtitle.setWordWrap(False)
        self.header.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.header.subtitle.setToolTip(self.header.subtitle.text())
        root.addWidget(self.header)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setToolTip("重新读取当前星系、行星与船池")
        self.refresh_btn.clicked.connect(lambda: self._load_current(manual=True))
        self.scan_btn = QPushButton("扫描")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.setToolTip("扫描附近星系并写入银河索引")
        self.scan_btn.clicked.connect(self._scan)
        self.scan_cancel_btn = QPushButton("取消扫描")
        self.scan_cancel_btn.setToolTip("请求取消正在进行的扫描；当前系统完成后停止")
        self.scan_cancel_btn.clicked.connect(self._cancel_scan)
        self.scan_cancel_btn.setVisible(False)
        self.export_btn = QPushButton("导出 CSV")
        self.export_btn.setToolTip("按当前筛选条件导出银河索引表格文件")
        self.export_btn.clicked.connect(self._export_csv)
        for button in (self.refresh_btn, self.scan_btn, self.scan_cancel_btn, self.export_btn):
            self.header.add_action(button)

        self.error_banner = ErrorBanner(parent=self)
        self.error_banner.set_retry_callback(self._load_current)
        root.addWidget(self.error_banner)

        hero = Card()
        hv = hero.v
        line = QHBoxLayout()
        self.badge = QLabel("—")
        self.badge.setStyleSheet("font-size:16px;font-weight:700;")
        self.badge.setWordWrap(True)
        line.addWidget(self.badge, 1)
        self.copy_glyph = QPushButton("复制符文")
        self.copy_glyph.clicked.connect(self._copy_glyph)
        line.addWidget(self.copy_glyph)
        hv.addLayout(line)
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

        split = PageSplitter("galaxy-v2")
        root.addWidget(split, 1)

        mid = Card("行星与船池")
        mid.setMinimumWidth(360)
        mv = mid.v
        mv.setContentsMargins(12, 8, 12, 8)
        mv.setSpacing(6)

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
        self.diss = QComboBox()
        self.diss.addItem("不限", None)
        self.diss.addItem("仅异常", True)
        self.scan_filter_flow.addWidget(self._filter_field("异常状态", self.diss))
        self.count = QSpinBox()
        self.count.setRange(20, 767)
        self.count.setValue(200)
        self.scan_filter_flow.addWidget(self._filter_field("扫描系统数", self.count))
        self.reset_filters_btn = QPushButton("重置条件")
        self.reset_filters_btn.clicked.connect(self._reset_scan_filters)
        self.scan_filter_flow.addWidget(self.reset_filters_btn)
        mv.addWidget(self.scan_filter_flow)

        for widget in (self.biome, self.sent, self.race, self.interceptor, self.diss):
            widget.currentIndexChanged.connect(self._update_filter_summary)
        for widget in (self.min_planets, self.count):
            widget.valueChanged.connect(self._update_filter_summary)
        self.filter_summary = muted("筛选摘要：不限条件；扫描范围 200 个系统。")
        mv.addWidget(self.filter_summary)

        self.tabs = QTabWidget()
        self.planets = GalaxyTable(0, 5)
        self.planets.setHorizontalHeaderLabels(
            ["#", "生物群系", "哨兵", "资源", "异常"])
        self._configure_table(self.planets)
        self.planets.setSortingEnabled(True)
        self.planets.itemSelectionChanged.connect(self._select_planet)
        self.planets_empty = EmptyState(
            "当前星系没有行星", "没有读到行星数据；请确认存档/游戏目录，或点右上角刷新。",
            icon="◇")
        self.planets_page = self._wrap_table(self.planets, self.planets_empty)
        self.tabs.addTab(self.planets_page, "行星")
        self.ships = GalaxyTable(0, 4)
        self.ships.setHorizontalHeaderLabels(["类型", "类别", "种子", "来源"])
        self._configure_table(self.ships)
        self.ships.setSortingEnabled(True)
        self.ships_empty = EmptyState(
            "当前星系没有船", "没有读到船池数据；请确认存档/游戏目录，或点右上角刷新。",
            icon="◇")
        self.ships_page = self._wrap_table(self.ships, self.ships_empty)
        self.tabs.addTab(self.ships_page, "本星系船池")
        self.scan_table = GalaxyTable(0, 6)
        self.scan_table.setHorizontalHeaderLabels(
            ["行星", "群系", "哨兵", "坐标", "符文串", "星系"])
        self._configure_table(self.scan_table)
        self.scan_table.setSortingEnabled(True)
        self.scan_table.itemSelectionChanged.connect(self._select_scan)
        self.scan_empty = EmptyState(
            "还没有扫描结果", "点右上角「扫描」按当前条件扫描附近星系；结果会写入银河索引。",
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
        self.idx_interceptor = QComboBox()
        self.idx_interceptor.addItem("不限", None)
        self.idx_interceptor.addItem("有", True)
        self.index_filter_flow.addWidget(self._filter_field("拦截机", self.idx_interceptor))
        iv.addWidget(self.index_filter_flow)

        # 银河索引也是系统级结果：传送入口和扫描结果页一致，都会先问行星。
        self.index_action_flow = GalaxyFlowBar(h_spacing=6, v_spacing=6)
        self.idx_query = QPushButton("查询")
        self.idx_query.setObjectName("primary")
        self.idx_query.clicked.connect(self._query_index)
        self.index_action_flow.addWidget(self.idx_query)
        self.idx_export = QPushButton("导出结果")
        self.idx_export.clicked.connect(self._export_index_csv)
        self.index_action_flow.addWidget(self.idx_export)
        self.idx_copy = QPushButton("复制符文")
        self.idx_copy.clicked.connect(self._copy_index_glyph)
        self.index_action_flow.addWidget(self.idx_copy)
        self.idx_stats_btn = QPushButton("刷新统计")
        self.idx_stats_btn.clicked.connect(self._refresh_index_stats)
        self.index_action_flow.addWidget(self.idx_stats_btn)
        self.index_warp_btn = QPushButton("传送到此星球")
        self.index_warp_btn.setToolTip("调用游戏内传送门机制，传送到银河索引中选中的星系/行星")
        self.index_warp_btn.setEnabled(False)
        self.index_warp_btn.clicked.connect(self._warp_selected_planet)
        self.index_action_flow.addWidget(self.index_warp_btn)
        iv.addWidget(self.index_action_flow)
        self.index_warp_hint = muted("选择一条银河索引结果后可传送；系统级结果会先让你选行星。")
        self.index_status = muted("就绪：按条件查询已扫描的银河索引。")
        # 传送提示与查询状态共用一行：两者都很短，分开会多占一整行。
        index_info = QHBoxLayout()
        index_info.setSpacing(8)
        index_info.addWidget(self.index_warp_hint, 1)
        index_info.addWidget(self.index_status, 1)
        iv.addLayout(index_info)

        self.index_stats = muted("索引统计：读取中…")
        self.index_table = GalaxyTable(0, 7)
        self.index_table.setHorizontalHeaderLabels(
            ["坐标", "符文串", "行星数", "种族", "异常",
             "拦截机种子", "命中行星"])
        self._configure_table(self.index_table)
        self.index_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.index_table.setSortingEnabled(True)
        self.index_table.itemSelectionChanged.connect(self._select_index)
        self.index_empty = EmptyState(
            "还没有银河索引结果", "按条件点「查询」，或先扫描一片区域；索引会越扫越全。",
            icon="◇")
        self.index_pane = self._table_pane(self.index_table, self.index_empty)
        iv.addWidget(self.index_pane, 1)
        iv.addWidget(self.index_stats)
        self.tabs.addTab(self.index_page, "银河索引")
        self.tabs.addTab(self._build_discovered_page(), "已发现")
        self.tabs.addTab(self._build_address_page(), "地址工作台")
        mv.addWidget(self.tabs, 1)

        self.status = muted("就绪：可扫描附近星系，或先查看当前星系。")
        mv.addWidget(self.status)
        split.addWidget(mid)

        right = Card("详情")
        rv = right.v
        self.detail_title = QLabel("选择行星")
        self.detail_title.setStyleSheet("font-size:15px;font-weight:700;")
        rv.addWidget(self.detail_title)
        self.detail = muted("空态：点表格里的行星、扫描结果或银河索引查看详情。")
        rv.addWidget(self.detail)
        self.detail_glyph = GalaxyGlyphLabel(max_height=40)
        rv.addWidget(self.detail_glyph)
        self.selection_hint = muted("未选择：选中一行后可复制地址、显示浮窗或填入传送。")
        rv.addWidget(self.selection_hint)
        row = QHBoxLayout()
        self.copy_selected_glyph_btn = QPushButton("复制 符文串")
        self.copy_selected_glyph_btn.clicked.connect(self._copy_selected_glyph)
        row.addWidget(self.copy_selected_glyph_btn)
        self.copy_selected_coords_btn = QPushButton("复制坐标")
        self.copy_selected_coords_btn.clicked.connect(self._copy_selected_coords)
        row.addWidget(self.copy_selected_coords_btn)
        rv.addLayout(row)
        row2 = QHBoxLayout()
        self.overlay_btn = QPushButton("浮窗显示符文")
        self.overlay_btn.clicked.connect(self._show_overlay)
        row2.addWidget(self.overlay_btn)
        self.travel_btn = QPushButton("定位并填入传送")
        self.travel_btn.clicked.connect(self._prepare_travel)
        row2.addWidget(self.travel_btn)
        rv.addLayout(row2)
        # 常驻入口：无论当前在哪个标签页，选中行后都能直接传送。
        self.detail_warp_btn = QPushButton("传送到此星球")
        self.detail_warp_btn.setToolTip("调用游戏内传送门机制，传送到当前选中的星球")
        self.detail_warp_btn.setEnabled(False)
        self.detail_warp_btn.clicked.connect(self._warp_selected_planet)
        rv.addWidget(self.detail_warp_btn)
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
        self._update_subtitle()

    def _build_scan_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.warp_btn = QPushButton("传送到此星球")
        self.warp_btn.setToolTip("调用游戏内传送门机制，传送到选中的扫描结果行星")
        self.warp_btn.setEnabled(False)
        self.warp_btn.clicked.connect(self._warp_selected_planet)
        row.addWidget(self.warp_btn)
        self.warp_hint = muted("选择一条扫描结果后可传送到该星球。")
        row.addWidget(self.warp_hint, 1)
        v.addLayout(row)
        self.scan_pane = self._table_pane(self.scan_table, self.scan_empty)
        v.addWidget(self.scan_pane, 1)
        return page

    def _build_discovered_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(4)

        self.disc_filter_flow = GalaxyFlowBar(h_spacing=6, v_spacing=6)
        self.disc_biome = QComboBox()
        self.disc_biome.addItem("不限", None)
        for name in DISCOVERY_BIOMES:
            self.disc_biome.addItem(zh_mod.biome_label(name), name)
        self.disc_filter_flow.addWidget(self._filter_field("群系", self.disc_biome))

        self.disc_infested = QComboBox()
        self.disc_infested.addItem("不限", None)
        self.disc_infested.addItem("虫蚀", True)
        self.disc_infested.addItem("非虫蚀", False)
        self.disc_filter_flow.addWidget(self._filter_field("虫蚀", self.disc_infested))

        self.disc_named = QComboBox()
        self.disc_named.addItem("不限", None)
        self.disc_named.addItem("已命名", True)
        self.disc_named.addItem("未命名", False)
        self.disc_filter_flow.addWidget(self._filter_field("命名", self.disc_named))

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

        self.disc_center_btn = QPushButton("以当前星系为中心")
        self.disc_center_btn.setCheckable(True)
        self.disc_center_btn.setToolTip(
            "把当前星系设为距离中心；再次点击可清除中心并关闭距离筛选")
        self.disc_center_btn.toggled.connect(self._toggle_discovered_origin)
        self.disc_filter_flow.addWidget(self.disc_center_btn)

        self.disc_origin_hint = muted("距离中心：未设置")
        self.disc_filter_flow.addWidget(self.disc_origin_hint)
        v.addWidget(self.disc_filter_flow)

        self.disc_action_flow = GalaxyFlowBar(h_spacing=6, v_spacing=6)
        self.disc_refresh_btn = QPushButton("刷新")
        self.disc_refresh_btn.setToolTip("重新读取当前存档里的已发现星球")
        self.disc_refresh_btn.clicked.connect(lambda: self._load_discovered(manual=True))
        self.disc_action_flow.addWidget(self.disc_refresh_btn)
        self.disc_export_btn = QPushButton("导出 CSV")
        self.disc_export_btn.setToolTip("按当前筛选/表格内容导出已发现星球（含符文与坐标）")
        self.disc_export_btn.setEnabled(False)
        self.disc_export_btn.clicked.connect(self._export_discovered_csv)
        self.disc_action_flow.addWidget(self.disc_export_btn)
        self.disc_warp_btn = QPushButton("传送到此星球")
        self.disc_warp_btn.setToolTip("调用游戏内传送门机制，传送到选中的已发现星球")
        self.disc_warp_btn.setEnabled(False)
        self.disc_warp_btn.clicked.connect(self._warp_selected_planet)
        self.disc_action_flow.addWidget(self.disc_warp_btn)
        self.disc_warp_hint = muted("选择一条已发现行星后可传送到该星球。")
        self.disc_action_flow.addWidget(self.disc_warp_hint)
        v.addWidget(self.disc_action_flow)

        self.disc_stats = muted("已发现：读取中…")
        v.addWidget(self.disc_stats)

        self.disc_table = GalaxyTable(0, len(DISCOVERED_COLUMNS))
        self.disc_table.setHorizontalHeaderLabels(DISCOVERED_COLUMNS)
        self._configure_table(self.disc_table)
        self.disc_table.setSortingEnabled(True)
        self.disc_table.itemSelectionChanged.connect(self._select_discovered)
        self.disc_empty = EmptyState(
            "正在读取已发现星球…", "正在读取当前存档的发现记录，请稍候。",
            icon="◇")
        self.disc_pane = self._table_pane(self.disc_table, self.disc_empty)
        v.addWidget(self.disc_pane, 1)
        self._autosize_table(self.disc_table, (68, 140, 70, 48, 78, 74, 104))
        self._set_empty_state(
            self.disc_table, self.disc_empty, False,
            "正在读取已发现星球…", "正在读取当前存档的发现记录，请稍候。")

        self.disc_biome.currentIndexChanged.connect(self._apply_discovered_filters)
        self.disc_infested.currentIndexChanged.connect(self._apply_discovered_filters)
        self.disc_named.currentIndexChanged.connect(self._apply_discovered_filters)
        self.disc_distance.valueChanged.connect(self._apply_discovered_filters)
        self.discovered_page = page
        return page


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

    def _update_subtitle(self) -> None:
        self.header.set_title(
            "星图",
            f"当前星系：{self._sub_current} · 扫描：{self._sub_scan}"
            f" · 索引：{self._sub_index} · 地址：{self._sub_address}")
        self.header.subtitle.setToolTip(self.header.subtitle.text())

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
        if self.interceptor.currentData():
            parts.append("有拦截机")
        summary = " · ".join(parts) if parts else "不限条件"
        self.filter_summary.setText(
            f"筛选摘要：{summary}；扫描范围 {int(self.count.value())} 个系统。")

    def _reset_scan_filters(self) -> None:
        for widget in (self.biome, self.sent, self.race, self.interceptor, self.diss):
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
        self._load_discovered()

    def _load_current(self, manual: bool = False) -> None:
        self.status.setText("加载中：正在读取当前星系…")
        self._sub_current = "读取中…"
        self._update_subtitle()
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
            self._sub_current = f"{name} · {res.get('glyphs') or '—'}"
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
                "当前星系没有行星", "没有读到行星数据；请确认存档/游戏目录，或点右上角刷新。")
            self._set_empty_state(
                self.ships, self.ships_empty, bool(ships),
                "当前星系没有船", "没有读到船池数据；请确认存档/游戏目录，或点右上角刷新。")
            if pls or ships:
                self.status.setText(f"当前星系：{len(pls)} 颗行星 / {len(ships)} 艘船")
                self.current_empty.hide()
                if manual:
                    notify.success("当前星系已刷新")
            else:
                self.status.setText("当前星系为空：没有读取到行星或船池数据。")
                self.current_empty.title_label.setText("当前星系没有结果")
                self.current_empty.description_label.setText(
                    "没有读到行星或船池数据；请确认存档/游戏目录，或点右上角刷新。")
                self.current_empty.description_label.show()
                self.current_empty.show()
                notify.warn("当前星系没有读取到行星或船池数据")
            self._update_subtitle()

        def fail(msg: str) -> None:
            self.loading.stop()
            self._current_info = {}
            self._sub_current = "不可用"
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
            self._update_subtitle()
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

    def _copy_glyph(self) -> None:
        self._copy_text(self._current_info.get("glyphs"), "符文串")

    # ---------------------------------------------------------------- 地址工作台

    def _build_address_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("地址/种子"))
        self.addr_input = QLineEdit()
        self.addr_input.setPlaceholderText(
            "12 位符文串，例如 1043FEE69929；或种子 0x0123456789ABCDEF")
        self.addr_input.returnPressed.connect(self._address_submit)
        row.addWidget(self.addr_input, 1)
        self.addr_lookup = QPushButton("解析 符文串")
        self.addr_lookup.setObjectName("primary")
        self.addr_lookup.clicked.connect(self._address_glyphs)
        row.addWidget(self.addr_lookup)
        self.addr_seed = QPushButton("种子反查")
        self.addr_seed.clicked.connect(self._address_seed)
        row.addWidget(self.addr_seed)
        v.addLayout(row)

        self.addr_status = muted(
            "空态：输入 12 位符文串或 0x… 种子；坐标文本暂不支持直接解析。")
        v.addWidget(self.addr_status)

        self.addr_summary = QLabel("尚未查询。")
        self.addr_summary.setWordWrap(True)
        self.addr_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.addr_summary)

        self.addr_glyph = GalaxyGlyphLabel(max_height=40)
        v.addWidget(self.addr_glyph)

        actions = QHBoxLayout()
        self.addr_copy = QPushButton("复制 符文串")
        self.addr_copy.setEnabled(False)
        self.addr_copy.clicked.connect(self._copy_addr_glyph)
        actions.addWidget(self.addr_copy)
        self.addr_fill = QPushButton("定位并填入传送")
        self.addr_fill.setEnabled(False)
        self.addr_fill.clicked.connect(self._fill_addr_teleport)
        actions.addWidget(self.addr_fill)
        actions.addStretch(1)
        v.addLayout(actions)

        self.addr_seed_table = GalaxyTable(0, 5)
        self.addr_seed_table.setHorizontalHeaderLabels(
            ["匹配", "坐标", "符文串", "星系", "位置/船"])
        self._configure_table(self.addr_seed_table)
        self.addr_seed_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.addr_seed_table.itemSelectionChanged.connect(self._select_addr_seed)
        self.addr_seed_empty = EmptyState(
            "还没有种子反查结果",
            "输入 0x… 十六进制种子并点「种子反查」；候选越多越慢。",
            icon="◇")
        self.addr_seed_pane = self._table_pane(self.addr_seed_table, self.addr_seed_empty)
        v.addWidget(self.addr_seed_pane, 1)
        self._set_empty_state(self.addr_seed_table, self.addr_seed_empty, False)
        return page

    def _addr_set_busy(self, busy: bool, text: str | None = None) -> None:
        self._addr_busy = busy
        for widget in (self.addr_input, self.addr_lookup, self.addr_seed):
            widget.setEnabled(not busy)
        if busy:
            self.addr_copy.setEnabled(False)
            self.addr_fill.setEnabled(False)
        else:
            self.addr_copy.setEnabled(bool(self._addr_glyphs))
            self.addr_fill.setEnabled(bool(self._addr_glyphs))
        if text is not None:
            self.addr_status.setText(text)

    def _addr_clear_glyph(self) -> None:
        self._addr_glyphs = None
        self._addr_coords = None
        self.addr_glyph.clear()
        self.addr_copy.setEnabled(False)
        self.addr_fill.setEnabled(False)

    def _address_submit(self) -> None:
        result = classify_address_input(self.addr_input.text())
        kind = result["kind"]
        if kind == "glyphs":
            self._lookup_glyphs(result["value"])
        elif kind == "seed":
            self._lookup_seed(result["value"])
        elif kind == "coords":
            self.addr_status.setText(result["message"])
            self.addr_summary.setText("坐标文本暂不支持直接解析；请使用符文串或种子。")
            self._sub_address = "坐标文本暂不支持"
            self._update_subtitle()
            notify.warn("坐标文本暂不支持直接解析；请使用符文串或种子")
        elif kind == "empty":
            self.addr_status.setText(result["message"])
            self.addr_summary.setText("空态：等待输入地址或种子。")
            self._sub_address = "等待输入"
            self._update_subtitle()
            notify.toast("请输入符文串或种子")
        else:
            self.addr_status.setText(result.get("message") or "输入不合法。")
            self.addr_summary.setText("无法识别输入；请检查格式。")
            self._sub_address = "输入不合法"
            self._update_subtitle()
            notify.error(result.get("message") or "无法识别输入；请检查格式")

    def _address_glyphs(self) -> None:
        try:
            glyphs = normalize_glyphs(self.addr_input.text())
        except ValueError as e:
            self.addr_status.setText(str(e))
            self.addr_summary.setText("符文串校验失败；请输入 12 位十六进制。")
            self._sub_address = "符文串校验失败"
            self._update_subtitle()
            notify.error(f"符文串校验失败：{e}")
            return
        self.addr_input.setText(glyphs)
        self._lookup_glyphs(glyphs)

    def _address_seed(self) -> None:
        try:
            seed = parse_seed(self.addr_input.text())
        except ValueError as e:
            self.addr_status.setText(str(e))
            self.addr_summary.setText("种子校验失败；请输入 0x… 十六进制。")
            self._sub_address = "种子校验失败"
            self._update_subtitle()
            notify.error(f"种子校验失败：{e}")
            return
        self._lookup_seed(seed)

    def _lookup_glyphs(self, glyphs: str) -> None:
        if self._addr_busy:
            return
        self._addr_clear_glyph()
        self._addr_set_busy(True, f"正在解析符文串{glyphs}…")
        self.addr_summary.setText("加载中：正在生成星系信息…")
        self.addr_seed_table.setRowCount(0)
        self._set_empty_state(self.addr_seed_table, self.addr_seed_empty, False,
                              "还没有种子反查结果",
                              "输入 0x… 十六进制种子并点「种子反查」；候选越多越慢。")
        self._sub_address = f"解析中 {glyphs}"
        self._update_subtitle()
        notify.toast(f"正在解析符文串{glyphs}…")

        def done(res: dict) -> None:
            self._addr_set_busy(False)
            got = res.get("glyphs") or glyphs
            self._addr_glyphs = got
            self._addr_coords = res.get("coords")
            galaxy = res.get("galaxy")
            dissonant = "是" if res.get("dissonant") else "否"
            lines = [
                f"星系：{res.get('name') or res.get('system_name') or '—'}",
                f"坐标：{res.get('coords') or '—'}  ·  宇宙地址（UA）：{res.get('ua') or '—'}",
                f"银河：{galaxy if galaxy is not None else '—'}  ·  行星：{res.get('planets', 0)}"
                f"  ·  卫星：{res.get('moons', 0)}",
                f"种族：{res.get('race_zh') or res.get('race') or '—'}  ·  "
                f"异常：{dissonant}",
                f"符文串：{got}",
            ]
            self.addr_summary.setText("\n".join(lines))
            self._set_glyph(self.addr_glyph, got)
            self.addr_copy.setEnabled(True)
            self.addr_fill.setEnabled(True)
            self.addr_status.setText(f"解析完成：{res.get('name') or got} · 可复制或填入传送输入。")
            self._sub_address = f"{got} 已解析"
            self._update_subtitle()
            notify.success(f"符文串解析完成：{res.get('name') or got}")

        def fail(msg: str) -> None:
            self._addr_set_busy(False, f"解析失败：{msg}")
            self.addr_summary.setText(
                "解析失败：没有生成星系信息；请检查符文串或游戏目录。")
            self._addr_clear_glyph()
            self._sub_address = "解析失败"
            self._update_subtitle()
            notify.error(f"符文串解析失败：{msg}")

        run_worker(self.svc.system, done, fail, glyphs=glyphs)

    def _lookup_seed(self, seed: int) -> None:
        if self._addr_busy:
            return
        seed_text = f"0x{seed:016X}"
        self._addr_clear_glyph()
        self._addr_set_busy(True, f"正在反查种子 {seed_text}…（候选越多越慢）")
        self.addr_summary.setText(f"加载中：种子 {seed_text} 反查中…")
        self.addr_seed_table.setRowCount(0)
        self._set_empty_state(self.addr_seed_table, self.addr_seed_empty, False,
                              "种子反查中…", "正在生成候选；候选越多越慢，请稍候。")
        self._sub_address = f"种子反查中 {seed_text}"
        self._update_subtitle()
        notify.toast(f"正在反查种子 {seed_text}…（候选越多越慢）")

        def done(res: dict) -> None:
            self._addr_set_busy(False)
            hits = res.get("hits") or []
            candidates = int(res.get("candidates") or 0)
            self._fill_addr_seed(hits)
            self._set_empty_state(
                self.addr_seed_table, self.addr_seed_empty, bool(hits),
                "未找到匹配星系", "没有可信候选；请放宽限制或换一个种子。")
            info = (f"种子：{res.get('seed') or seed_text}  ·  候选：{candidates}"
                    f"  ·  确认：{len(hits)}")
            if res.get("known_systems"):
                info += f"  ·  已知星系：{res.get('known_systems')}"
            self.addr_summary.setText(info)
            if hits:
                self.addr_status.setText(
                    f"反查完成：{candidates} 个候选，确认 {len(hits)} 个星系。")
                self.addr_seed_table.selectRow(0)
                self._sub_address = f"种子反查命中 {len(hits)} 个"
                notify.success(f"种子反查完成：确认 {len(hits)} 个星系")
            else:
                reason = res.get("reason") or "没有可信候选。"
                self.addr_status.setText(f"未找到匹配星系（候选 {candidates}）：{reason}")
                self._sub_address = "种子反查无结果"
                notify.warn(f"未找到匹配星系（候选 {candidates}）：{reason}")
            self._update_subtitle()

        def fail(msg: str) -> None:
            self._addr_set_busy(False, f"种子反查失败：{msg}")
            self.addr_seed_table.setRowCount(0)
            self._set_empty_state(
                self.addr_seed_table, self.addr_seed_empty, False,
                "种子反查失败", "没有拿到候选星系；请检查种子或游戏目录后重试。")
            self.addr_summary.setText("反查失败：没有拿到候选星系。")
            self._addr_clear_glyph()
            self._sub_address = "种子反查失败"
            self._update_subtitle()
            notify.error(f"种子反查失败：{msg}")

        run_worker(self.svc.locate, done, fail, seed=seed_text)

    def _fill_addr_seed(self, hits: list[dict]) -> None:
        self._update_warp_action(None)
        self.addr_seed_table.clearSelection()
        self.addr_seed_table.setRowCount(len(hits))
        for i, hit in enumerate(hits):
            where = " / ".join(str(x) for x in (hit.get("where"), hit.get("what")) if x)
            if not where and hit.get("steps") is not None:
                where = f"往回第 {hit.get('steps')} 步"
            vals = [
                "已确认（已知星系）" if hit.get("visited") else "已确认",
                hit.get("coords") or "—",
                hit.get("glyphs") or "—",
                str(hit.get("galaxy")) if hit.get("galaxy") is not None else "—",
                where or "—",
            ]
            for j, value in enumerate(vals):
                item = QTableWidgetItem(str(value))
                if j == 0:
                    item.setData(Qt.UserRole, hit)
                self.addr_seed_table.setItem(i, j, item)
        self._autosize_table(self.addr_seed_table, (120, 220, 160, 70, 200))

    def _select_addr_seed(self) -> None:
        rows = self.addr_seed_table.selectionModel().selectedRows()
        if not rows:
            self._update_warp_action(None)
            return
        item = self.addr_seed_table.item(rows[0].row(), 0)
        hit = item.data(Qt.UserRole) if item else None
        if not hit:
            return
        glyphs = hit.get("glyphs")
        self._addr_glyphs = glyphs
        self._addr_coords = hit.get("coords")
        self._selection = hit
        self._set_glyph(self.addr_glyph, glyphs)
        self.addr_copy.setEnabled(bool(glyphs))
        self.addr_fill.setEnabled(bool(glyphs))
        where = " / ".join(str(x) for x in (hit.get("where"), hit.get("what")) if x) or "—"
        self.addr_summary.setText(
            f"候选星系：{hit.get('ua') or '—'}\n"
            f"坐标：{hit.get('coords') or '—'}  ·  银河：{hit.get('galaxy', '—')}\n"
            f"符文串：{glyphs or '—'}  ·  位置/船：{where}\n"
            f"匹配：{'已确认（已知星系）' if hit.get('visited') else '已确认'}")
        self.addr_status.setText(f"已选择 {hit.get('coords') or glyphs or '候选星系'}。")
        self._sub_address = f"已选择 {glyphs or hit.get('coords') or '候选星系'}"
        self._update_subtitle()
        self._update_warp_action(hit)

    def _copy_addr_glyph(self) -> None:
        self._copy_text(self._addr_glyphs, "符文串", self.addr_status)

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
        self._sub_address = f"传送输入 {glyphs}"
        self._update_subtitle()

    def _fill_addr_teleport(self) -> None:
        self._fill_teleport_input(self._addr_glyphs, self._addr_coords, self.addr_status)

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
        self._autosize_table(self.index_table, (154, 108, 46, 48, 40, 92, 64))

    def _query_index(self) -> None:
        filters = self._index_filters()
        self.idx_query.setEnabled(False)
        self.index_status.setText("加载中：正在查询银河索引…")
        self.index_stats.setText("索引统计：查询中…")
        self._sub_index = "查询中…"
        self._update_subtitle()
        notify.toast("正在查询银河索引…")

        def done(res: dict) -> None:
            self.idx_query.setEnabled(True)
            rows = res.get("rows") or []
            stats = res.get("stats") or {}
            self._index_rows = rows
            self._fill_index(rows)
            self.index_stats.setText(
                f"索引库：{stats.get('systems', 0)} 个星系 / {stats.get('planets', 0)} 颗行星"
                f"  ·  本次命中 {len(rows)} 个星系")
            self._set_empty_state(
                self.index_table, self.index_empty, bool(rows),
                "没有匹配的星系", "请放宽条件，或先扫描一片区域；索引会越扫越全。")
            if rows:
                self.index_status.setText(f"查询完成：命中 {len(rows)} 个星系。")
                self._sub_index = f"命中 {len(rows)} 个星系"
                notify.success(f"银河索引查询完成：命中 {len(rows)} 个星系")
            else:
                self.index_status.setText("没有匹配的星系；请放宽条件，或先扫描一片区域。")
                self._sub_index = "无结果"
                notify.warn("银河索引没有匹配的星系；请放宽条件或先扫描")
            self._update_subtitle()

        def fail(msg: str) -> None:
            self.idx_query.setEnabled(True)
            self._index_rows = []
            self._fill_index([])
            self._set_empty_state(
                self.index_table, self.index_empty, False,
                "索引查询失败", "请检查索引数据库或稍后重试。")
            self.index_stats.setText("索引统计：不可用")
            self.index_status.setText(f"查询失败：{msg}")
            self._sub_index = "查询失败"
            self._update_subtitle()
            notify.error(f"银河索引查询失败：{msg}")

        run_worker(self.svc.galaxy_query, done, fail, filters=filters, limit=500)

    def _refresh_index_stats(self) -> None:
        self.index_stats.setText("索引统计：加载中…")

        def done(st: dict) -> None:
            self.index_stats.setText(
                f"索引库：{st.get('systems', 0)} 个星系 / {st.get('planets', 0)} 颗行星")
            self._sub_index = (
                f"{st.get('systems', 0)} 个星系 / {st.get('planets', 0)} 颗行星")
            self._update_subtitle()

        def fail(msg: str) -> None:
            self.index_stats.setText(f"索引统计不可用：{msg}")
            self._sub_index = "统计不可用"
            self._update_subtitle()

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
        self.selection_hint.setText(
            f"已选择星系 {r.get('coords') or r.get('ua') or '—'}；可复制地址、显示浮窗或直接传送。")
        self.index_status.setText(
            f"已选择 {r.get('coords') or r.get('ua') or '星系'} · 可复制符文串或传送。")
        self._sub_index = f"已选择 {r.get('coords') or r.get('ua') or '星系'}"
        self._update_subtitle()
        self._update_warp_action(r)

    def _copy_index_glyph(self) -> None:
        rows = self.index_table.selectionModel().selectedRows()
        if not rows:
            self.index_status.setText("请先选择一个星系。")
            notify.warn("请先在银河索引里选择一个星系")
            return
        item = self.index_table.item(rows[0].row(), 0)
        r = item.data(Qt.UserRole) if item else None
        text = (r or {}).get("glyphs")
        if not text:
            self.index_status.setText("该星系没有可复制的符文串。")
            notify.warn("该星系没有可复制的符文串")
            return
        QGuiApplication.clipboard().setText(text)
        self.index_status.setText("符文串已复制到剪贴板。")
        notify.success(f"符文串已复制：{text}")

    def _export_index_csv(self) -> None:
        try:
            data = self.svc.galaxy_export_csv(self._index_filters())
        except Exception as e:                              # noqa: BLE001
            self.index_status.setText(f"导出失败：{type(e).__name__}: {e}")
            notify.error(f"导出失败：{type(e).__name__}: {e}")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出银河索引（CSV 表格文件）", "galaxy-index.csv", "CSV 表格文件 (*.csv)")
        if not path:
            return
        try:
            Path(path).write_text(data, "utf-8")
        except Exception as e:                              # noqa: BLE001
            self.index_status.setText(f"写入失败：{type(e).__name__}: {e}")
            notify.error(f"写入失败：{type(e).__name__}: {e}")
            return
        self.index_status.setText(f"已导出：{path}")
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

    def _discovered_filters_active(self) -> bool:
        return bool(self._discovered_filters())

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
            self.disc_stats.setText(
                "已发现：当前星系不可用，无法设置距离中心；请先在右上角刷新当前星系。")
            notify.warn("当前星系不可用，无法作为距离中心")
            return

        self._discovered_origin_ua = ua
        label = current.get("coords") or str(ua)
        self.disc_origin_hint.setText(f"距离中心：{label}")
        self.disc_distance.setEnabled(True)
        self.disc_distance.setToolTip(
            f"只显示距 {label} 不超过该距离的已发现星球；0 表示不限距离")
        self._apply_discovered_filters()

    def _render_discovered_stats(self, shown: int, *, available: bool = True) -> None:
        warnings = list(self._discovered_warnings or [])
        if not available:
            self.disc_stats.setText("已发现：不可用")
        else:
            meta = self._discovered_meta or {}
            stats = self._discovered_stats or {}
            total = int(meta.get("count") or len(self._discovered_all) or 0)
            parts = [f"已发现：{total} 颗"]
            try:
                records = int(meta.get("records") or 0)
            except (TypeError, ValueError):
                records = 0
            if records and records != total:
                parts.append(f"原始记录 {records} 条")
            try:
                duplicates = int(meta.get("duplicates") or 0)
            except (TypeError, ValueError):
                duplicates = 0
            if duplicates:
                parts.append(f"重复 {duplicates} 条")
            parts.append(f"当前显示 {shown} 颗")
            if shown >= 500:
                parts.append("已达列表上限 500 条")
            for key, label in (("pending", "待上传"), ("named", "已命名"),
                               ("infested", "虫蚀"), ("unknown_biome", "群系未知")):
                try:
                    count = int(stats.get(key) or 0)
                except (TypeError, ValueError):
                    count = 0
                if count:
                    parts.append(f"{label} {count} 颗")
            if warnings:
                parts.append(f"提示 {len(warnings)} 条")
            self.disc_stats.setText(" · ".join(parts))
        self.disc_stats.setToolTip("\n".join(warnings))

    def _set_discovered_filter_enabled(self, enabled: bool) -> None:
        for widget in (self.disc_biome, self.disc_infested, self.disc_named,
                       self.disc_center_btn):
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
        # 默认保留服务层排序（auto → 距离/发现时间）；用户点表头仍可自行排序。
        self.disc_table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.disc_table.setSortingEnabled(True)
        self._autosize_table(self.disc_table, (68, 140, 70, 48, 78, 74, 104))

    def _load_discovered(self, manual: bool = False) -> None:
        if self._discovered_loading:
            return
        self._discovered_loading = True
        self.disc_refresh_btn.setEnabled(False)
        self.disc_stats.setText("已发现：读取中…")
        self.disc_stats.setToolTip("")
        self._set_empty_state(
            self.disc_table, self.disc_empty, False,
            "正在读取已发现星球…", "正在读取当前存档的发现记录，请稍候。")

        def done(res) -> None:
            self._discovered_loading = False
            self.disc_refresh_btn.setEnabled(True)
            self._discovered_loaded = True
            res = res if isinstance(res, dict) else {}
            self._discovered_meta = res
            self._discovered_warnings = [
                str(w) for w in (res.get("warnings") or []) if str(w).strip()]
            self._discovered_stats = res.get("stats") if isinstance(res.get("stats"), dict) else {}
            self._discovered_has_data = bool(res.get("ok"))
            raw_rows = res.get("planets") or []
            self._discovered_all = (
                [row for row in raw_rows if isinstance(row, dict)]
                if self._discovered_has_data else [])
            self._discovered_filter_seq += 1

            if not self._discovered_has_data:
                self._discovered_rows = []
                self._fill_discovered([])
                self.disc_export_btn.setEnabled(False)
                self._set_discovered_filter_enabled(False)
                reason = (self._discovered_warnings[0] if self._discovered_warnings
                          else "没有读取到当前存档的发现数据。")
                self._set_empty_state(
                    self.disc_table, self.disc_empty, False,
                    "没有可用的已发现数据",
                    f"{reason}\n请先在设置页配置存档/游戏目录，再点「刷新」。")
                self._render_discovered_stats(0, available=False)
                self.disc_warp_hint.setText("当前没有可用的已发现星球数据。")
                if manual:
                    notify.warn(f"已发现星球不可用：{reason}")
                return

            self._set_discovered_filter_enabled(True)
            if not self._discovered_all:
                self._discovered_rows = []
                self._fill_discovered([])
                self.disc_export_btn.setEnabled(False)
                self._set_empty_state(
                    self.disc_table, self.disc_empty, False,
                    "没有已发现的星球",
                    "当前存档里没有 Planet 类型的发现记录；可先扫描或继续探索后刷新。")
                self._render_discovered_stats(0)
                self.disc_warp_hint.setText("当前存档没有已发现的星球。")
                if manual:
                    notify.warn("当前存档没有已发现的星球")
                return

            if self._discovered_filters_active():
                # 已选筛选条件时，刷新后仍按同一组条件取数（过滤仍由服务层完成）。
                self._apply_discovered_filters()
            else:
                self._discovered_rows = list(self._discovered_all)
                self._fill_discovered(self._discovered_rows)
                self.disc_export_btn.setEnabled(True)
                self._set_empty_state(
                    self.disc_table, self.disc_empty, True,
                    "没有已发现的星球", "")
                self._render_discovered_stats(len(self._discovered_rows))
            if manual:
                notify.success(f"已发现星球已刷新：{len(self._discovered_all)} 颗")

        def fail(msg: str) -> None:
            self._discovered_loading = False
            self.disc_refresh_btn.setEnabled(True)
            self._discovered_loaded = True
            self._discovered_has_data = False
            self._discovered_all = []
            self._discovered_rows = []
            self._discovered_meta = {}
            self._discovered_stats = {}
            self._discovered_warnings = [str(msg)]
            self._fill_discovered([])
            self.disc_export_btn.setEnabled(False)
            self._set_discovered_filter_enabled(False)
            self._set_empty_state(
                self.disc_table, self.disc_empty, False,
                "没有可用的已发现数据",
                f"读取已发现星球失败：{msg}\n请先在设置页配置存档/游戏目录，再点「刷新」。")
            self._render_discovered_stats(0, available=False)
            self.disc_warp_hint.setText("当前没有可用的已发现星球数据。")
            notify.warn(f"读取已发现星球失败：{msg}")

        run_worker(self.svc.discovered_planets, done, fail)

    def _apply_discovered_filters(self, *_args) -> None:
        if not self._discovered_has_data or not self._discovered_all:
            return
        if self.disc_distance.value() > 0 and self._discovered_origin_ua in (None, ""):
            self.disc_stats.setText(
                "已发现：请先点「以当前星系为中心」确定距离中心，再按距离筛选。")
            return
        filters = self._discovered_filters()
        filters.setdefault("sort", "auto")
        filters.setdefault("limit", 500)
        seq = self._discovered_filter_seq + 1
        self._discovered_filter_seq = seq
        self.disc_stats.setText("已发现：筛选中…")

        def done(res) -> None:
            if seq != self._discovered_filter_seq:
                return
            res = res if isinstance(res, dict) else {}
            if not res.get("ok"):
                reason = ((res.get("warnings") or ["筛选没有返回数据"])[0])
                self._discovered_rows = []
                self._fill_discovered([])
                self.disc_export_btn.setEnabled(False)
                self._set_empty_state(
                    self.disc_table, self.disc_empty, False,
                    "筛选已发现星球失败",
                    f"{reason}\n请检查筛选条件后重试。")
                self.disc_stats.setText(f"已发现：筛选失败（{reason}）")
                notify.warn(f"筛选已发现星球失败：{reason}")
                return
            rows = [row for row in (res.get("planets") or []) if isinstance(row, dict)]
            self._discovered_rows = rows
            self._fill_discovered(rows)
            self.disc_export_btn.setEnabled(bool(rows))
            self._set_empty_state(
                self.disc_table, self.disc_empty, bool(rows),
                "没有匹配的已发现星球",
                "当前筛选条件下没有命中；请放宽群系/虫蚀/命名/距离条件。")
            self._render_discovered_stats(len(rows))

        def fail(msg: str) -> None:
            if seq != self._discovered_filter_seq:
                return
            self._discovered_rows = []
            self._fill_discovered([])
            self.disc_export_btn.setEnabled(False)
            self._set_empty_state(
                self.disc_table, self.disc_empty, False,
                "筛选已发现星球失败",
                f"没有拿到筛选结果：{msg}\n请检查条件后重试。")
            self.disc_stats.setText(f"已发现：筛选失败（{msg}）")
            notify.warn(f"筛选已发现星球失败：{msg}")

        run_worker(self.svc.discovered_filter, done, fail,
                   planets=list(self._discovered_all), **filters)

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
             f" · 来源：{_discovered_source_text(row)}"),
        ]
        if row.get("distance_ly") not in (None, ""):
            lines.append(f"距离：{_discovered_distance_text(row.get('distance_ly'))}")
        self.detail_title.setText(title)
        self.detail.setText("\n".join(lines))
        self._set_glyph(self.detail_glyph, row.get("glyphs"))
        self.selection_hint.setText(
            f"已选择 {title}；可复制地址、显示浮窗或直接传送。")
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
        self.scan_btn.setEnabled(False)
        self.scan_cancel_btn.setEnabled(True)
        self.scan_cancel_btn.setVisible(True)
        self._sub_scan = "扫描中…"
        self._update_subtitle()
        self.status.setText(
            f"加载中：正在扫描附近星系并写入银河索引（{self.filter_summary.text()}）…")
        notify.toast(f"开始扫描附近星系（目标 {int(self.count.value())} 个系统）…")
        try:
            self._scan_job = self.svc.start_galaxy_scan(
                radius=0, systems_per_region=int(self.count.value()), filters=filters, limit=200)
        except Exception as e:                              # noqa: BLE001
            self.scan_btn.setEnabled(True)
            self.scan_cancel_btn.setVisible(False)
            self._sub_scan = "无法开始"
            self._update_subtitle()
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
        self._sub_scan = "正在取消…"
        self._update_subtitle()
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
            f"扫描进行中：已扫 {scanned} / {target} 个系统 · 可点右上角「取消扫描」")
        self._sub_scan = f"扫描中，已扫 {scanned} 个系统"
        self._update_subtitle()
        if job.status == "running":
            return
        self._timer.stop()
        self.scan_btn.setEnabled(True)
        self.scan_cancel_btn.setVisible(False)
        self.scan_cancel_btn.setEnabled(True)
        if job.status == "cancelled":
            self._scan_rows = []
            self._fill_scan_rows([])
            self._set_empty_state(
                self.scan_table, self.scan_empty, False,
                "扫描已取消", "已停止扫描；可调整条件后重新点「扫描」。")
            self._sub_scan = f"已取消，已扫 {scanned} 个系统"
            self._update_subtitle()
            self.status.setText(f"扫描已取消：已扫 {scanned} 个系统。")
            notify.warn("扫描已取消")
            return
        if job.error:
            self._sub_scan = "扫描失败"
            self._update_subtitle()
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
            self._sub_scan = f"完成，命中 {len(rows)} 条"
            notify.success(f"扫描完成：命中 {len(rows)} 条，已写入银河索引")
        else:
            self.status.setText("扫描完成：没有匹配的星球；请放宽筛选条件或扩大扫描范围。")
            self._sub_scan = "完成，无结果"
            notify.warn("扫描完成：没有匹配的星球；请放宽筛选条件或扩大扫描范围")
        self._update_subtitle()
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
        self.selection_hint.setText(
            f"已选择行星 #{p.get('index', '?')}；可复制地址、显示浮窗或直接传送。")
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
        self.selection_hint.setText(
            f"已选择扫描结果 {r.get('coords') or r.get('glyphs') or '—'}；"
            "可复制地址、显示浮窗或直接传送。")
        self._set_glyph(self.detail_glyph, r.get("glyphs"))
        self._update_warp_action(r)

    def _warp_buttons(self) -> list[QPushButton]:
        return [b for b in (getattr(self, "warp_btn", None),
                            getattr(self, "index_warp_btn", None),
                            getattr(self, "detail_warp_btn", None),
                            getattr(self, "disc_warp_btn", None)) if b is not None]

    def _set_warp_busy(self, busy: bool) -> None:
        self._warp_busy = busy
        for button in self._warp_buttons():
            button.setText("传送中…" if busy else "传送到此星球")
            button.setEnabled(False if busy else self._warp_target is not None)

    def _update_warp_action(self, row: dict | None = None) -> None:
        """刷新所有「传送到此星球」入口；选中行后立即更新可用性与提示。"""
        target = _warp_target_for(row) if isinstance(row, dict) else None
        self._warp_target = target
        self._warp_row = row if isinstance(row, dict) and target else None
        enabled = target is not None and not self._warp_busy
        for button in self._warp_buttons():
            button.setEnabled(enabled)

        if target:
            planet_note = ("系统级结果：传送时可选择行星（1-6，默认 #1）"
                           if target.get("needs_planet") else target["planet_label"])
            glyphs = target.get("glyphs") or ""
            tooltip = (f"调用游戏内传送门机制，传送到 {target['system']}/{planet_note}"
                       + (f"（门地址 {glyphs}）" if glyphs else "（选择行星后生成门地址）"))
            for button in self._warp_buttons():
                button.setToolTip(tooltip)
            hint = f"可传送：{target['system']}/{planet_note}"
            hint += f" · 门地址 {glyphs}" if glyphs else " · 选择行星后生成门地址"
            self.warp_hint.setText(hint)
            self.index_warp_hint.setText(hint)
            if hasattr(self, "disc_warp_hint"):
                self.disc_warp_hint.setText(hint)
        else:
            no_address = "该结果没有可用的门地址，无法传送。" if isinstance(row, dict) \
                else "选择一条结果后可传送到该星球。"
            for button in self._warp_buttons():
                button.setToolTip("选中一条能生成合法门地址的结果后可传送")
            self.warp_hint.setText(no_address)
            self.index_warp_hint.setText(no_address)
            if hasattr(self, "disc_warp_hint"):
                self.disc_warp_hint.setText(
                    "选择一条已发现行星后可传送到该星球。"
                    if not isinstance(row, dict) else no_address)

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
                "浮窗显示失败：请先在行星表、扫描结果或银河索引中选择一个带符文串的星球。")
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

    def _prepare_travel(self) -> None:
        self._fill_teleport_input(self._selected_glyphs(), self._selected_coords(), self.status)

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
