"""星球/星系页：当前星系、行星表、船池、批量扫描、种子定位。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...services import get_services
from ..widgets.worker import run as run_worker

BIOMES = [("", "不限"), ("Lush", "茂盛"), ("Toxic", "剧毒"), ("Scorched", "焦土"),
          ("Frozen", "冰冻"), ("Barren", "荒芜"), ("Exotic", "异星"), ("Dead", "死寂")]
SENTS = [("", "不限"), ("none", "无"), ("low", "低"), ("high", "高"),
         ("aggressive", "敌对"), ("corrupted", "腐化")]


class SystemsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._scan_job = None
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll_scan)
        self._build_ui()
        self._load_current()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("当前星系"))
        self.badge = QLabel("—")
        self.badge.setObjectName("muted")
        bar.addWidget(self.badge, 1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._load_current)
        bar.addWidget(refresh)
        root.addLayout(bar)

        row = QHBoxLayout()
        row.addWidget(QLabel("定位飞船种子"))
        self.seed = QLineEdit()
        self.seed.setPlaceholderText("0x... 或十进制")
        row.addWidget(self.seed, 1)
        locate = QPushButton("定位")
        locate.clicked.connect(self._locate)
        row.addWidget(locate)
        root.addLayout(row)

        self.tabs = QTabWidget()
        self.planets = QTableWidget(0, 4)
        self.planets.setHorizontalHeaderLabels(["#", "生物群系", "哨兵", "dissonant"])
        self.planets.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.planets, "行星")
        self.ships = QTableWidget(0, 4)
        self.ships.setHorizontalHeaderLabels(["类型", "类别", "种子", "来源"])
        self.ships.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.ships, "本星系船池")
        self.locate_table = QTableWidget(0, 4)
        self.locate_table.setHorizontalHeaderLabels(["坐标", "符文", "星系", "匹配"])
        self.locate_table.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.locate_table, "种子定位")
        root.addWidget(self.tabs, 1)

        scan_box = QHBoxLayout()
        scan_box.addWidget(QLabel("生物群系"))
        self.biome = QComboBox()
        for key, label in BIOMES:
            self.biome.addItem(label, key)
        scan_box.addWidget(self.biome)
        scan_box.addWidget(QLabel("哨兵"))
        self.sent = QComboBox()
        for key, label in SENTS:
            self.sent.addItem(label, key)
        scan_box.addWidget(self.sent)
        self.diss = QComboBox()
        self.diss.addItem("不限 dissonant", None)
        self.diss.addItem("只要 dissonant", True)
        scan_box.addWidget(self.diss)
        scan_box.addWidget(QLabel("扫描系统数"))
        self.count = QSpinBox()
        self.count.setRange(20, 767)
        self.count.setValue(200)
        scan_box.addWidget(self.count)
        self.scan_btn = QPushButton("扫描")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.clicked.connect(self._scan)
        scan_box.addWidget(self.scan_btn)
        self.glyph_btn = QPushButton("复制符文")
        self.glyph_btn.clicked.connect(self._copy_glyph)
        scan_box.addWidget(self.glyph_btn)
        root.addLayout(scan_box)

        self.status = QLabel("就绪")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    # ---------------------------------------------------------------- 当前星系

    def _load_current(self) -> None:
        self.status.setText("生成当前星系…")

        def done(res: dict) -> None:
            self.badge.setText(
                f"{res.get('glyphs') or '—'}  ·  {res.get('coords') or '—'}"
                f"  ·  {res.get('race_zh') or res.get('race') or '—'}"
                f"  ·  {res.get('planets', 0)} 行星"
                + ("  ·  dissonant" if res.get("dissonant") else ""))
            pls = res.get("planet_list") or []
            self.planets.setRowCount(len(pls))
            for i, p in enumerate(pls):
                vals = [str(p.get("index")), p.get("biome_zh") or p.get("biome_name") or "",
                        p.get("sentinels_zh") or p.get("sentinels") or "",
                        "是" if res.get("dissonant") else "否"]
                for j, v in enumerate(vals):
                    self.planets.setItem(i, j, QTableWidgetItem(v))
            ships = res.get("ships") or []
            self.ships.setRowCount(len(ships))
            for i, s in enumerate(ships):
                vals = [s.get("type_label") or s.get("type") or "", s.get("kind_zh") or s.get("kind") or "",
                        s.get("seed") or "", s.get("source") or ""]
                for j, v in enumerate(vals):
                    item = QTableWidgetItem(v)
                    item.setData(Qt.UserRole, s)
                    self.ships.setItem(i, j, item)
            self.status.setText(f"当前星系已加载：{len(pls)} 颗行星 / {len(ships)} 艘船")

        def fail(msg: str) -> None:
            self.status.setText(f"当前星系不可用：{msg}")

        run_worker(self.svc.system, done, fail)

    # ---------------------------------------------------------------- 定位

    def _locate(self) -> None:
        seed = self.seed.text().strip()
        if not seed:
            self.status.setText("先填一个种子")
            return
        self.status.setText("反查星系…")

        def done(res: dict) -> None:
            rows = res.get("hits") or []
            self.locate_table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                vals = [r.get("coords") or "", r.get("glyphs") or "",
                        r.get("galaxy") or "", r.get("where") or r.get("what") or "命中"]
                for j, v in enumerate(vals):
                    item = QTableWidgetItem(str(v))
                    item.setData(Qt.UserRole, r)
                    self.locate_table.setItem(i, j, item)
            self.tabs.setCurrentWidget(self.locate_table)
            self.status.setText(f"定位完成：候选 {res.get('candidates', 0)} 个，命中 {len(rows)} 个")

        def fail(msg: str) -> None:
            self.status.setText(f"定位失败：{msg}")

        run_worker(self.svc.locate, done, fail, seed)

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
                radius=0, systems_per_region=int(self.count.value()),
                filters=filters, limit=200)
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
        self.status.setText(f"扫描中… {p.get('scanned') or p.get('tested') or 0} 个系统  "
                            f"命中 {p.get('found') or 0}")
        if job.status == "running":
            return
        self._timer.stop()
        self.scan_btn.setEnabled(True)
        if job.error:
            self.status.setText(f"扫描失败：{job.error}")
            return
        rows = job.result or []
        self.planets.setRowCount(len(rows))
        self._scan_rows = rows
        for i, r in enumerate(rows):
            vals = [str(r.get("index", "")), r.get("biome_name") or r.get("biome") or "",
                    r.get("sentinels") or "", "是" if r.get("dissonant") else "否"]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.UserRole, r)
                self.planets.setItem(i, j, item)
        self.tabs.setCurrentWidget(self.planets)
        self.status.setText(f"扫描完成：命中 {len(rows)} 条")

    def _copy_glyph(self) -> None:
        cur = self.tabs.currentWidget()
        if cur is self.planets:
            rows = self.planets.selectionModel().selectedRows()
            if rows:
                item = self.planets.item(rows[0].row(), 0)
                row = item.data(Qt.UserRole) if item else None
                if row and row.get("glyphs"):
                    QGuiApplication.clipboard().setText(row["glyphs"])
                    self.status.setText("符文已复制")
        elif cur is self.locate_table:
            rows = self.locate_table.selectionModel().selectedRows()
            if rows:
                item = self.locate_table.item(rows[0].row(), 1)
                if item:
                    QGuiApplication.clipboard().setText(item.text())
                    self.status.setText("符文已复制")
