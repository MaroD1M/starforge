"""星图：当前星系、行星、船池、扫描与银河索引。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget, QSplitter)

from ...services import get_services
from .. import notify
from ..dialogs.address import (COORD_UNSUPPORTED, classify_address_input, normalize_glyphs,
                               parse_seed)
from ..widgets.feedback import EmptyState, ErrorBanner, LoadingOverlay
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
        self._current_info: dict = {}
        self._selection: dict = {}
        self._last_scan_filters: dict = {}
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
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)

        self.header = PageHeader("星图", "")
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
        self.export_btn = QPushButton("导出 CSV（表格文件）")
        self.export_btn.setToolTip("按当前筛选条件导出银河索引表格文件")
        self.export_btn.clicked.connect(self._export_csv)
        for button in (self.refresh_btn, self.scan_btn, self.scan_cancel_btn, self.export_btn):
            self.header.add_action(button)

        self.error_banner = ErrorBanner(parent=self)
        self.error_banner.set_retry_callback(self._load_current)
        root.addWidget(self.error_banner)

        hero = Card("当前星系")
        hv = hero.v
        line = QHBoxLayout()
        self.badge = QLabel("—")
        self.badge.setStyleSheet("font-size:16px;font-weight:700;")
        line.addWidget(self.badge, 1)
        self.copy_glyph = QPushButton("复制符文")
        self.copy_glyph.clicked.connect(self._copy_glyph)
        line.addWidget(self.copy_glyph)
        hv.addLayout(line)
        self.hero_info = muted("进入页面后自动读取；没有存档时请先在设置页配置。")
        hv.addWidget(self.hero_info)
        self.glyph = QLabel()
        self.glyph.setMinimumHeight(44)
        hv.addWidget(self.glyph)
        self.current_empty = EmptyState(
            "没有当前星系数据",
            "没有读取到存档/游戏，或当前星系没有行星与船池；请在设置页配置后重试。",
            icon="◇", button_text="重新读取", parent=hero)
        self.current_empty.actionTriggered.connect(self._load_current)
        self.current_empty.hide()
        hv.addWidget(self.current_empty)
        root.addWidget(hero)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        mid = Card("行星与船池")
        mv = mid.v

        filter_row1 = QHBoxLayout()
        filter_row1.setSpacing(6)
        filter_row1.addWidget(QLabel("群系"))
        self.biome = QComboBox()
        for k, v in BIOMES:
            self.biome.addItem(v, k)
        filter_row1.addWidget(self.biome)
        filter_row1.addWidget(QLabel("哨兵"))
        self.sent = QComboBox()
        for k, v in SENTS:
            self.sent.addItem(v, k)
        filter_row1.addWidget(self.sent)
        filter_row1.addWidget(QLabel("种族"))
        self.race = QComboBox()
        for k, v in RACES:
            self.race.addItem(v, k)
        filter_row1.addWidget(self.race, 1)
        filter_row1.addWidget(QLabel("拦截机"))
        self.interceptor = QComboBox()
        self.interceptor.addItem("不限", None)
        self.interceptor.addItem("有", True)
        filter_row1.addWidget(self.interceptor)
        filter_row1.addWidget(QLabel("恒星类型"))
        self.star_type = QComboBox()
        self.star_type.addItem("后端暂不提供", "")
        self.star_type.setEnabled(False)
        self.star_type.setToolTip("当前后端未返回恒星类型字段；有数据后会启用此筛选。")
        filter_row1.addWidget(self.star_type)
        mv.addLayout(filter_row1)

        filter_row2 = QHBoxLayout()
        filter_row2.setSpacing(6)
        filter_row2.addWidget(QLabel("最少行星"))
        self.min_planets = QSpinBox()
        self.min_planets.setRange(0, 20)
        self.min_planets.setValue(0)
        self.min_planets.setSpecialValueText("不限")
        filter_row2.addWidget(self.min_planets)
        filter_row2.addWidget(QLabel("异常状态（dissonant）"))
        self.diss = QComboBox()
        self.diss.addItem("不限", None)
        self.diss.addItem("仅异常（dissonant）", True)
        filter_row2.addWidget(self.diss)
        filter_row2.addWidget(QLabel("扫描系统数"))
        self.count = QSpinBox()
        self.count.setRange(20, 767)
        self.count.setValue(200)
        filter_row2.addWidget(self.count)
        self.reset_filters_btn = QPushButton("重置条件")
        self.reset_filters_btn.clicked.connect(self._reset_scan_filters)
        filter_row2.addWidget(self.reset_filters_btn)
        filter_row2.addStretch(1)
        mv.addLayout(filter_row2)

        for widget in (self.biome, self.sent, self.race, self.interceptor, self.diss):
            widget.currentIndexChanged.connect(self._update_filter_summary)
        for widget in (self.min_planets, self.count):
            widget.valueChanged.connect(self._update_filter_summary)
        self.filter_summary = muted("筛选摘要：不限条件；扫描范围 200 个系统。")
        mv.addWidget(self.filter_summary)

        self.tabs = QTabWidget()
        self.planets = QTableWidget(0, 5)
        self.planets.setHorizontalHeaderLabels(
            ["#", "生物群系", "哨兵", "资源", "异常（dissonant）"])
        self.planets.horizontalHeader().setStretchLastSection(True)
        self.planets.setSelectionBehavior(QTableWidget.SelectRows)
        self.planets.setSortingEnabled(True)
        self.planets.itemSelectionChanged.connect(self._select_planet)
        self.planets_empty = EmptyState(
            "当前星系没有行星", "没有读到行星数据；请确认存档/游戏目录，或点右上角刷新。",
            icon="◇")
        self.planets_page = self._wrap_table(self.planets, self.planets_empty)
        self.tabs.addTab(self.planets_page, "行星")
        self.ships = QTableWidget(0, 4)
        self.ships.setHorizontalHeaderLabels(["类型", "类别", "种子", "来源"])
        self.ships.horizontalHeader().setStretchLastSection(True)
        self.ships.setSelectionBehavior(QTableWidget.SelectRows)
        self.ships.setSortingEnabled(True)
        self.ships_empty = EmptyState(
            "当前星系没有船", "没有读到船池数据；请确认存档/游戏目录，或点右上角刷新。",
            icon="◇")
        self.ships_page = self._wrap_table(self.ships, self.ships_empty)
        self.tabs.addTab(self.ships_page, "本星系船池")
        self.scan_table = QTableWidget(0, 6)
        self.scan_table.setHorizontalHeaderLabels(
            ["行星", "群系", "哨兵", "坐标", "符文串（glyphs）", "星系"])
        self.scan_table.horizontalHeader().setStretchLastSection(True)
        self.scan_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.scan_table.setSortingEnabled(True)
        self.scan_table.itemSelectionChanged.connect(self._select_scan)
        self.scan_empty = EmptyState(
            "还没有扫描结果", "点右上角「扫描」按当前条件扫描附近星系；结果会写入银河索引。",
            icon="◇")
        self.scan_page = self._wrap_table(self.scan_table, self.scan_empty)
        self.tabs.addTab(self.scan_page, "扫描结果")

        self.index_page = QWidget()
        iv = QVBoxLayout(self.index_page)
        iv.setContentsMargins(0, 4, 0, 0)
        iv.setSpacing(6)

        index_row1 = QHBoxLayout()
        index_row1.addWidget(QLabel("群系"))
        self.idx_biome = QComboBox()
        for k, v in INDEX_BIOMES:
            self.idx_biome.addItem(v, k)
        index_row1.addWidget(self.idx_biome)
        index_row1.addWidget(QLabel("哨兵"))
        self.idx_sent = QComboBox()
        for k, v in SENTS:
            self.idx_sent.addItem(v, k)
        index_row1.addWidget(self.idx_sent)
        index_row1.addWidget(QLabel("种族"))
        self.idx_race = QComboBox()
        for k, v in RACES:
            self.idx_race.addItem(v, k)
        index_row1.addWidget(self.idx_race, 1)
        iv.addLayout(index_row1)

        index_row2 = QHBoxLayout()
        index_row2.addWidget(QLabel("异常状态（dissonant）"))
        self.idx_diss = QComboBox()
        self.idx_diss.addItem("不限", None)
        self.idx_diss.addItem("是", True)
        self.idx_diss.addItem("否", False)
        index_row2.addWidget(self.idx_diss)
        index_row2.addWidget(QLabel("最少行星"))
        self.idx_min = QSpinBox()
        self.idx_min.setRange(0, 20)
        self.idx_min.setValue(0)
        self.idx_min.setSpecialValueText("不限")
        index_row2.addWidget(self.idx_min)
        index_row2.addWidget(QLabel("拦截机"))
        self.idx_interceptor = QComboBox()
        self.idx_interceptor.addItem("不限", None)
        self.idx_interceptor.addItem("有", True)
        index_row2.addWidget(self.idx_interceptor)
        self.idx_query = QPushButton("查询")
        self.idx_query.setObjectName("primary")
        self.idx_query.clicked.connect(self._query_index)
        index_row2.addWidget(self.idx_query)
        self.idx_export = QPushButton("导出结果")
        self.idx_export.clicked.connect(self._export_index_csv)
        index_row2.addWidget(self.idx_export)
        self.idx_copy = QPushButton("复制 glyphs（符文串）")
        self.idx_copy.clicked.connect(self._copy_index_glyph)
        index_row2.addWidget(self.idx_copy)
        self.idx_stats_btn = QPushButton("刷新统计")
        self.idx_stats_btn.clicked.connect(self._refresh_index_stats)
        index_row2.addWidget(self.idx_stats_btn)
        iv.addLayout(index_row2)

        self.index_stats = muted("索引统计：读取中…")
        iv.addWidget(self.index_stats)
        self.index_table = QTableWidget(0, 7)
        self.index_table.setHorizontalHeaderLabels(
            ["坐标", "符文串（glyphs）", "行星数", "种族", "异常（dissonant）",
             "拦截机种子", "命中行星"])
        self.index_table.horizontalHeader().setStretchLastSection(True)
        self.index_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.index_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.index_table.setSortingEnabled(True)
        self.index_table.itemSelectionChanged.connect(self._select_index)
        self.index_empty = EmptyState(
            "还没有银河索引结果", "按条件点「查询」，或先扫描一片区域；索引会越扫越全。",
            icon="◇")
        iv.addWidget(self.index_empty, 1)
        iv.addWidget(self.index_table, 1)
        self.index_status = muted("就绪：按条件查询已扫描的银河索引。")
        iv.addWidget(self.index_status)
        self.tabs.addTab(self.index_page, "银河索引")
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
        self.detail_glyph = QLabel()
        self.detail_glyph.setMinimumHeight(44)
        rv.addWidget(self.detail_glyph)
        self.selection_hint = muted("未选择：选中一行后可复制地址、显示浮窗或填入传送。")
        rv.addWidget(self.selection_hint)
        row = QHBoxLayout()
        self.copy_selected_glyph_btn = QPushButton("复制 glyphs（符文串）")
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
        self.travel_btn = QPushButton("定位/前往（填入传送）")
        self.travel_btn.clicked.connect(self._prepare_travel)
        row2.addWidget(self.travel_btn)
        rv.addLayout(row2)
        rv.addStretch(1)
        split.addWidget(right)
        split.setSizes([700, 360])

        self.loading = LoadingOverlay(self, "正在读取当前星系…")
        self._set_empty_state(self.planets, self.planets_empty, False)
        self._set_empty_state(self.ships, self.ships_empty, False)
        self._set_empty_state(self.scan_table, self.scan_empty, False)
        self._set_empty_state(self.index_table, self.index_empty, False)
        self._update_subtitle()

    def _wrap_table(self, table: QTableWidget, empty: EmptyState) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(table, 1)
        v.addWidget(empty, 1)
        empty.hide()
        return page

    @staticmethod
    def _set_empty_state(table: QTableWidget, empty: EmptyState, has_rows: bool,
                         title: str | None = None,
                         description: str | None = None) -> None:
        if title is not None:
            empty.title_label.setText(title)
        if description is not None:
            empty.description_label.setText(description)
            empty.description_label.setVisible(bool(description))
        if has_rows:
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
        if self.star_type.isEnabled() and self.star_type.currentData():
            filters["star_type"] = self.star_type.currentData()
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
            parts.append("仅异常（dissonant）")
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
                f"异常（dissonant）：{'是' if res.get('dissonant') else '否'}")
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
            label.setPixmap(pix)
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
        self._copy_text(self._current_info.get("glyphs"), "符文串（glyphs）")

    # ---------------------------------------------------------------- 地址工作台

    def _build_address_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("地址/种子"))
        self.addr_input = QLineEdit()
        self.addr_input.setPlaceholderText(
            "12 位符文串（glyphs），例如 1043FEE69929；或种子 0x0123456789ABCDEF")
        self.addr_input.returnPressed.connect(self._address_submit)
        row.addWidget(self.addr_input, 1)
        self.addr_lookup = QPushButton("解析 glyphs（符文串）")
        self.addr_lookup.setObjectName("primary")
        self.addr_lookup.clicked.connect(self._address_glyphs)
        row.addWidget(self.addr_lookup)
        self.addr_seed = QPushButton("种子反查")
        self.addr_seed.clicked.connect(self._address_seed)
        row.addWidget(self.addr_seed)
        v.addLayout(row)

        self.addr_status = muted(
            "空态：输入 12 位符文串（glyphs）或 0x… 种子；坐标文本暂不支持直接解析。")
        v.addWidget(self.addr_status)

        self.addr_summary = QLabel("尚未查询。")
        self.addr_summary.setWordWrap(True)
        self.addr_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.addr_summary)

        self.addr_glyph = QLabel()
        self.addr_glyph.setMinimumHeight(44)
        v.addWidget(self.addr_glyph)

        actions = QHBoxLayout()
        self.addr_copy = QPushButton("复制 glyphs（符文串）")
        self.addr_copy.setEnabled(False)
        self.addr_copy.clicked.connect(self._copy_addr_glyph)
        actions.addWidget(self.addr_copy)
        self.addr_fill = QPushButton("定位/前往（填入传送）")
        self.addr_fill.setEnabled(False)
        self.addr_fill.clicked.connect(self._fill_addr_teleport)
        actions.addWidget(self.addr_fill)
        actions.addStretch(1)
        v.addLayout(actions)

        self.addr_seed_table = QTableWidget(0, 5)
        self.addr_seed_table.setHorizontalHeaderLabels(
            ["匹配", "坐标", "符文串（glyphs）", "星系", "位置/船"])
        self.addr_seed_table.horizontalHeader().setStretchLastSection(True)
        self.addr_seed_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.addr_seed_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.addr_seed_table.itemSelectionChanged.connect(self._select_addr_seed)
        self.addr_seed_empty = EmptyState(
            "还没有种子反查结果",
            "输入 0x… 十六进制种子并点「种子反查」；候选越多越慢。",
            icon="◇")
        v.addWidget(self.addr_seed_empty, 1)
        v.addWidget(self.addr_seed_table, 1)
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
            self.addr_summary.setText("坐标文本暂不支持直接解析；请使用符文串（glyphs）或种子。")
            self._sub_address = "坐标文本暂不支持"
            self._update_subtitle()
            notify.warn("坐标文本暂不支持直接解析；请使用符文串（glyphs）或种子")
        elif kind == "empty":
            self.addr_status.setText(result["message"])
            self.addr_summary.setText("空态：等待输入地址或种子。")
            self._sub_address = "等待输入"
            self._update_subtitle()
            notify.toast("请输入符文串（glyphs）或种子")
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
            self.addr_summary.setText("符文串（glyphs）校验失败；请输入 12 位十六进制。")
            self._sub_address = "符文串校验失败"
            self._update_subtitle()
            notify.error(f"符文串（glyphs）校验失败：{e}")
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
        self._addr_set_busy(True, f"正在解析符文串（glyphs）{glyphs}…")
        self.addr_summary.setText("加载中：正在生成星系信息…")
        self.addr_seed_table.setRowCount(0)
        self._set_empty_state(self.addr_seed_table, self.addr_seed_empty, False,
                              "还没有种子反查结果",
                              "输入 0x… 十六进制种子并点「种子反查」；候选越多越慢。")
        self._sub_address = f"解析中 {glyphs}"
        self._update_subtitle()
        notify.toast(f"正在解析符文串（glyphs）{glyphs}…")

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
                f"异常（dissonant）：{dissonant}",
                f"符文串（glyphs）：{got}",
            ]
            self.addr_summary.setText("\n".join(lines))
            self._set_glyph(self.addr_glyph, got)
            self.addr_copy.setEnabled(True)
            self.addr_fill.setEnabled(True)
            self.addr_status.setText(f"解析完成：{res.get('name') or got} · 可复制或填入传送输入。")
            self._sub_address = f"{got} 已解析"
            self._update_subtitle()
            notify.success(f"符文串（glyphs）解析完成：{res.get('name') or got}")

        def fail(msg: str) -> None:
            self._addr_set_busy(False, f"解析失败：{msg}")
            self.addr_summary.setText(
                "解析失败：没有生成星系信息；请检查符文串（glyphs）或游戏目录。")
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

    def _select_addr_seed(self) -> None:
        rows = self.addr_seed_table.selectionModel().selectedRows()
        if not rows:
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
            f"符文串（glyphs）：{glyphs or '—'}  ·  位置/船：{where}\n"
            f"匹配：{'已确认（已知星系）' if hit.get('visited') else '已确认'}")
        self.addr_status.setText(f"已选择 {hit.get('coords') or glyphs or '候选星系'}。")
        self._sub_address = f"已选择 {glyphs or hit.get('coords') or '候选星系'}"
        self._update_subtitle()

    def _copy_addr_glyph(self) -> None:
        self._copy_text(self._addr_glyphs, "符文串（glyphs）", self.addr_status)

    def _fill_teleport_input(self, glyphs: str | None, coords: str | None = None,
                             status_label=None) -> None:
        target_label = status_label or self.status
        if not glyphs:
            target_label.setText("定位/前往失败：当前没有可填入传送输入的符文串（glyphs）。")
            notify.warn("定位/前往失败：当前没有可填入传送的符文串（glyphs）")
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
            f"异常（dissonant）：{'是' if r.get('dissonant') else '否'}",
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
            f"已选择星系 {r.get('coords') or r.get('ua') or '—'}；可复制地址、显示浮窗或填入传送。")
        self.index_status.setText(
            f"已选择 {r.get('coords') or r.get('ua') or '星系'} · 可复制符文串（glyphs）。")
        self._sub_index = f"已选择 {r.get('coords') or r.get('ua') or '星系'}"
        self._update_subtitle()

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
            self.index_status.setText("该星系没有可复制的符文串（glyphs）。")
            notify.warn("该星系没有可复制的符文串（glyphs）")
            return
        QGuiApplication.clipboard().setText(text)
        self.index_status.setText("符文串（glyphs）已复制到剪贴板。")
        notify.success(f"符文串（glyphs）已复制：{text}")

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

    def _select_planet(self) -> None:
        rows = self.planets.selectionModel().selectedRows()
        if not rows:
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
            f"符文串（glyphs）：{selected.get('glyphs') or '—'}")
        self.selection_hint.setText(
            f"已选择行星 #{p.get('index', '?')}；可复制地址、显示浮窗或填入传送。")
        self._set_glyph(self.detail_glyph, selected.get("glyphs"))

    def _select_scan(self) -> None:
        rows = self.scan_table.selectionModel().selectedRows()
        if not rows:
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
            f"符文串（glyphs）：{r.get('glyphs') or '—'}\n"
            f"星系：{r.get('system_name') or r.get('galaxy_name') or r.get('galaxy') or '—'}")
        self.selection_hint.setText(
            f"已选择扫描结果 {r.get('coords') or r.get('glyphs') or '—'}；"
            "可复制地址、显示浮窗或填入传送。")
        self._set_glyph(self.detail_glyph, r.get("glyphs"))

    def _selected_glyphs(self) -> str:
        return str(self._selection.get("glyphs") or self._current_info.get("glyphs") or "").strip()

    def _selected_coords(self) -> str:
        return str(self._selection.get("coords") or self._current_info.get("coords") or "").strip()

    def _copy_selected_glyph(self) -> None:
        self._copy_text(self._selected_glyphs(), "符文串（glyphs）")

    def _copy_selected_coords(self) -> None:
        self._copy_text(self._selected_coords(), "坐标")

    def _show_overlay(self) -> None:
        glyphs = self._selected_glyphs()
        if not glyphs:
            self.status.setText(
                "浮窗显示失败：请先在行星表、扫描结果或银河索引中选择一个带符文串（glyphs）的星球。")
            notify.warn("浮窗显示失败：请先选择一个带符文串（glyphs）的星球")
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
