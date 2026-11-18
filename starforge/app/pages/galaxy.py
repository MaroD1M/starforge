"""星图：当前星系、行星、船池、扫描与银河索引。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget, QSplitter)

from ...services import get_services
from ..widgets.ui import Card, muted
from ..widgets.worker import run as run_worker

BIOMES = [("", "不限"), ("Lush", "茂盛"), ("Toxic", "剧毒"), ("Scorched", "焦土"),
          ("Frozen", "冰冻"), ("Barren", "荒芜"), ("Exotic", "异星"), ("Dead", "死寂")]
SENTS = [("", "不限"), ("none", "无"), ("low", "低"), ("high", "高"),
         ("aggressive", "敌对"), ("corrupted", "腐化")]


class GalaxyPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._loaded = False
        self._scan_job = None
        self._scan_rows: list[dict] = []
        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._poll_scan)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)

        hero = Card("当前星系")
        hv = hero.v
        line = QHBoxLayout()
        self.badge = QLabel("—")
        self.badge.setStyleSheet("font-size:16px;font-weight:700;")
        line.addWidget(self.badge, 1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._load_current)
        line.addWidget(refresh)
        self.copy_glyph = QPushButton("复制符文")
        self.copy_glyph.clicked.connect(self._copy_glyph)
        line.addWidget(self.copy_glyph)
        hv.addLayout(line)
        self.hero_info = muted("进入页面后自动读取；没有存档时请先在设置页配置。")
        hv.addWidget(self.hero_info)
        self.glyph = QLabel()
        self.glyph.setMinimumHeight(44)
        hv.addWidget(self.glyph)
        root.addWidget(hero)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        mid = Card("行星与船池")
        mv = mid.v
        self.tabs = QTabWidget()
        self.planets = QTableWidget(0, 5)
        self.planets.setHorizontalHeaderLabels(["#", "生物群系", "哨兵", "资源", "dissonant"])
        self.planets.horizontalHeader().setStretchLastSection(True)
        self.planets.setSelectionBehavior(QTableWidget.SelectRows)
        self.planets.itemSelectionChanged.connect(self._select_planet)
        self.tabs.addTab(self.planets, "行星")
        self.ships = QTableWidget(0, 4)
        self.ships.setHorizontalHeaderLabels(["类型", "类别", "种子", "来源"])
        self.ships.horizontalHeader().setStretchLastSection(True)
        self.ships.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabs.addTab(self.ships, "本星系船池")
        self.scan_table = QTableWidget(0, 4)
        self.scan_table.setHorizontalHeaderLabels(["坐标", "符文", "群系", "星系"])
        self.scan_table.horizontalHeader().setStretchLastSection(True)
        self.scan_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.scan_table.itemSelectionChanged.connect(self._select_scan)
        self.tabs.addTab(self.scan_table, "扫描结果")
        mv.addWidget(self.tabs, 1)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("群系"))
        self.biome = QComboBox()
        for k, v in BIOMES:
            self.biome.addItem(v, k)
        filters.addWidget(self.biome)
        filters.addWidget(QLabel("哨兵"))
        self.sent = QComboBox()
        for k, v in SENTS:
            self.sent.addItem(v, k)
        filters.addWidget(self.sent)
        self.diss = QComboBox()
        self.diss.addItem("不限", None)
        self.diss.addItem("只要 dissonant", True)
        filters.addWidget(self.diss)
        filters.addWidget(QLabel("系统数"))
        self.count = QSpinBox()
        self.count.setRange(20, 767)
        self.count.setValue(200)
        filters.addWidget(self.count)
        self.scan_btn = QPushButton("扫描")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.clicked.connect(self._scan)
        filters.addWidget(self.scan_btn)
        self.export_btn = QPushButton("导出 CSV")
        self.export_btn.clicked.connect(self._export_csv)
        filters.addWidget(self.export_btn)
        mv.addLayout(filters)
        self.status = muted("就绪")
        mv.addWidget(self.status)
        split.addWidget(mid)

        right = Card("Inspector")
        rv = right.v
        self.detail_title = QLabel("选择行星")
        self.detail_title.setStyleSheet("font-size:15px;font-weight:700;")
        rv.addWidget(self.detail_title)
        self.detail = muted("点表格里的行星或扫描结果查看详情。")
        rv.addWidget(self.detail)
        self.detail_glyph = QLabel()
        self.detail_glyph.setMinimumHeight(44)
        rv.addWidget(self.detail_glyph)
        row = QHBoxLayout()
        copy = QPushButton("复制选中符文")
        copy.clicked.connect(self._copy_selected_glyph)
        row.addWidget(copy)
        rv.addLayout(row)
        rv.addStretch(1)
        split.addWidget(right)
        split.setSizes([700, 360])

    # ---------------------------------------------------------------- 当前星系

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._load_current()

    def _load_current(self) -> None:
        self.status.setText("生成当前星系…")

        def done(res: dict) -> None:
            name = res.get("name") or res.get("system_name") or "当前星系"
            self.badge.setText(f"{name}  ·  {res.get('glyphs') or '—'}  ·  {res.get('coords') or '—'}")
            self.hero_info.setText(
                f"种族：{res.get('race_zh') or res.get('race') or '—'}  ·  "
                f"行星：{res.get('planets', 0)}  ·  "
                f"dissonant：{'是' if res.get('dissonant') else '否'}")
            self._set_glyph(self.glyph, res.get("glyphs"))
            pls = res.get("planet_list") or []
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
            ships = res.get("ships") or []
            self.ships.setRowCount(len(ships))
            for i, s in enumerate(ships):
                vals = [s.get("type_label") or s.get("type") or "",
                        s.get("kind_zh") or s.get("kind") or "",
                        s.get("seed") or "", s.get("source") or ""]
                for j, v in enumerate(vals):
                    item = QTableWidgetItem(str(v))
                    item.setData(Qt.UserRole, s)
                    self.ships.setItem(i, j, item)
            self.status.setText(f"当前星系：{len(pls)} 颗行星 / {len(ships)} 艘船")

        def fail(msg: str) -> None:
            self.status.setText(f"当前星系不可用：{msg}")
            self.hero_info.setText("没有读到当前星系；请确认存档/游戏目录。")

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

    def _copy_glyph(self) -> None:
        text = self.badge.text()
        # 没有单独保存 glyphs；从当前详情或标签里取
        if "·" in text:
            parts = [x.strip() for x in text.split("·")]
            if len(parts) >= 2:
                QGuiApplication.clipboard().setText(parts[1])
                self.status.setText("符文已复制")

    # ---------------------------------------------------------------- 扫描

    def _scan(self) -> None:
        filters = {}
        if self.biome.currentData():
            filters["biome"] = self.biome.currentData()
        if self.sent.currentData():
            filters["sentinels"] = self.sent.currentData()
        if self.diss.currentData() is not None:
            filters["dissonant"] = True
        self.scan_btn.setEnabled(False)
        self.status.setText("扫描中…")
        try:
            self._scan_job = self.svc.start_system_scan(
                radius=0, systems_per_region=int(self.count.value()), filters=filters, limit=200)
        except Exception as e:                              # noqa: BLE001
            self.scan_btn.setEnabled(True)
            self.status.setText(f"扫描无法开始：{type(e).__name__}: {e}")
            return
        self._timer.start()

    def _poll_scan(self) -> None:
        job = self._scan_job
        if job is None:
            self._timer.stop()
            return
        p = job.progress or {}
        self.status.setText(f"扫描中… {p.get('scanned') or 0} 个系统  ·  命中 {p.get('found') or 0}")
        if job.status == "running":
            return
        self._timer.stop()
        self.scan_btn.setEnabled(True)
        if job.error:
            self.status.setText(f"扫描失败：{job.error}")
            return
        rows = job.result or []
        self._scan_rows = rows
        self.scan_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r.get("coords") or "", r.get("glyphs") or "",
                    r.get("biome_name") or r.get("biome") or "",
                    r.get("system_name") or r.get("galaxy") or ""]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.UserRole, r)
                self.scan_table.setItem(i, j, item)
        self.tabs.setCurrentWidget(self.scan_table)
        self.status.setText(f"扫描完成：命中 {len(rows)} 条")

    def _select_planet(self) -> None:
        rows = self.planets.selectionModel().selectedRows()
        if not rows:
            return
        item = self.planets.item(rows[0].row(), 0)
        p = item.data(Qt.UserRole) if item else None
        if not p:
            return
        self.detail_title.setText(f"行星 #{p.get('index', '?')}")
        self.detail.setText(f"群系：{p.get('biome_zh') or p.get('biome_name') or '—'}\n"
                            f"哨兵：{p.get('sentinels_zh') or p.get('sentinels') or '—'}\n"
                            f"资源：{p.get('resources') or '—'}")

    def _select_scan(self) -> None:
        rows = self.scan_table.selectionModel().selectedRows()
        if not rows:
            return
        item = self.scan_table.item(rows[0].row(), 1)
        r = item.data(Qt.UserRole) if item else None
        if not r:
            return
        self.detail_title.setText(r.get("coords") or "扫描结果")
        self.detail.setText(f"群系：{r.get('biome_name') or r.get('biome') or '—'}\n"
                            f"符文：{r.get('glyphs') or '—'}")
        self._set_glyph(self.detail_glyph, r.get("glyphs"))

    def _copy_selected_glyph(self) -> None:
        rows = self.scan_table.selectionModel().selectedRows()
        if rows:
            item = self.scan_table.item(rows[0].row(), 1)
            if item:
                QGuiApplication.clipboard().setText(item.text())
                self.status.setText("符文已复制")
                return
        self._copy_glyph()

    def _export_csv(self) -> None:
        filters = {}
        if self.biome.currentData():
            filters["biome"] = self.biome.currentData()
        if self.sent.currentData():
            filters["sentinels"] = self.sent.currentData()
        if self.diss.currentData() is not None:
            filters["dissonant"] = True
        try:
            data = self.svc.galaxy_export_csv(filters)
        except Exception as e:                              # noqa: BLE001
            self.status.setText(f"导出失败：{type(e).__name__}: {e}")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出银河索引", "galaxy.csv", "CSV (*.csv)")
        if not path:
            return
        Path(path).write_text(data, "utf-8")
        self.status.setText(f"已导出：{path}")
