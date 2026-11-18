"""游戏内页：一键安装/注入/读取/传送/扫描，全部在应用内完成。"""
from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...services import get_services
from ..widgets.worker import run as run_worker


class LivePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._busy = False
        self._loaded = False
        self._build_ui()

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self.refresh()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(16, 16, 16, 16)

        title = QLabel("游戏内控制台")
        title.setStyleSheet("font-size:16px;font-weight:700;")
        root.addWidget(title)
        self.status = QLabel("检查中…")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        # 安装/连接
        box = QGroupBox("组件与连接")
        bv = QVBoxLayout(box)
        row = QHBoxLayout()
        self.runtime_btn = QPushButton("准备游戏内运行时")
        self.runtime_btn.setToolTip("下载 Python embeddable 到 ~/.starforge/agent/runtime；只需一次")
        self.runtime_btn.clicked.connect(self._bootstrap_runtime)
        row.addWidget(self.runtime_btn)
        self.deps_btn = QPushButton("安装/更新游戏内组件")
        self.deps_btn.setToolTip("在应用内安装 NMSpy（按游戏 build）+ pymhf[http_api]，需要网络")
        self.deps_btn.clicked.connect(self._install_deps)
        row.addWidget(self.deps_btn)
        self.install_btn = QPushButton("安装 Mod")
        self.install_btn.clicked.connect(self._install_mod)
        row.addWidget(self.install_btn)
        self.inject_btn = QPushButton("注入并连接")
        self.inject_btn.setObjectName("primary")
        self.inject_btn.clicked.connect(lambda: self._launch(True))
        row.addWidget(self.inject_btn)
        self.start_btn = QPushButton("启动游戏并注入")
        self.start_btn.clicked.connect(lambda: self._launch(False))
        row.addWidget(self.start_btn)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._stop)
        row.addWidget(self.stop_btn)
        self.refresh_btn = QPushButton("刷新状态")
        self.refresh_btn.clicked.connect(self.refresh)
        row.addWidget(self.refresh_btn)
        bv.addLayout(row)
        row_probe = QHBoxLayout()
        self.probe_btn = QPushButton("外部内存只读探测（无需 agent）")
        self.probe_btn.setToolTip("只读扫描模板槽，验证游戏进程/内存通道；不写任何内存")
        self.probe_btn.clicked.connect(self._external_probe)
        row_probe.addWidget(self.probe_btn)
        row_probe.addStretch(1)
        bv.addLayout(row_probe)
        self.auto_chk = QCheckBox("游戏没运行时，允许「注入并连接」自动启动游戏")
        bv.addWidget(self.auto_chk)
        root.addWidget(box)

        # 能力
        cap_box = QGroupBox("能力")
        cv = QVBoxLayout(cap_box)
        self.caps = QTableWidget(0, 4)
        self.caps.setHorizontalHeaderLabels(["能力", "可用", "风险", "说明"])
        self.caps.horizontalHeader().setStretchLastSection(True)
        self.caps.setEditTriggers(QTableWidget.NoEditTriggers)
        self.caps.setMaximumHeight(230)
        cv.addWidget(self.caps)
        root.addWidget(cap_box)

        # 读取
        read_box = QGroupBox("实时读取")
        rv = QVBoxLayout(read_box)
        row2 = QHBoxLayout()
        for text, cmd in (("玩家位置", "player"), ("当前星系", "system"),
                          ("当前行星", "planet"), ("游戏内船槽", "ships")):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, c=cmd: self._read(c))
            row2.addWidget(btn)
        rv.addLayout(row2)
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setMinimumHeight(220)
        rv.addWidget(self.out)
        root.addWidget(read_box)

        # 传送
        tp_box = QGroupBox("传送（高风险，先备份存档）")
        tv = QFormLayout(tp_box)
        self.glyphs = QLineEdit()
        self.glyphs.setPlaceholderText("12 位传送门地址，例如 1043FEE69929")
        tv.addRow("符文地址", self.glyphs)
        row3 = QHBoxLayout()
        self.galaxy_mode = QComboBox()
        self.galaxy_mode.addItem("保持当前星系", None)
        self.galaxy_mode.addItem("指定星系编号", "custom")
        row3.addWidget(self.galaxy_mode)
        self.galaxy = QSpinBox()
        self.galaxy.setRange(0, 254)
        self.galaxy.setEnabled(False)
        self.galaxy_mode.currentIndexChanged.connect(
            lambda: self.galaxy.setEnabled(self.galaxy_mode.currentData() == "custom"))
        row3.addWidget(self.galaxy)
        self.teleport_btn = QPushButton("传送到此地址")
        self.teleport_btn.setObjectName("primary")
        self.teleport_btn.clicked.connect(self._teleport)
        row3.addWidget(self.teleport_btn)
        self.restore_btn = QPushButton("还原上一次传送")
        self.restore_btn.clicked.connect(self._restore)
        row3.addWidget(self.restore_btn)
        tv.addRow("", row3)
        tv.addRow("", QLabel("只有单人模式可用；失败会自动提示 restore。传送前请手动备份存档。"))
        root.addWidget(tp_box)

        # 扫描
        scan_box = QGroupBox("行星扫描")
        sv = QVBoxLayout(scan_box)
        row4 = QHBoxLayout()
        read_scan = QPushButton("读取当前行星扫描数据")
        read_scan.clicked.connect(lambda: self._scan("read"))
        row4.addWidget(read_scan)
        self.instant_chk = QCheckBox("游戏内扫描即时完成")
        self.instant_chk.toggled.connect(self._toggle_instant_scan)
        row4.addWidget(self.instant_chk)
        self.scan_note = QLabel("discover（写入发现列表）暂未开放；read 返回实时天气/资源/动植物。")
        self.scan_note.setObjectName("muted")
        row4.addWidget(self.scan_note, 1)
        sv.addLayout(row4)
        root.addWidget(scan_box)

        root.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll)

    # ---------------------------------------------------------------- 状态

    def refresh(self) -> None:
        def done(st: dict) -> None:
            self._apply_status(st)

        def fail(msg: str) -> None:
            self.status.setText(f"状态读取失败：{msg}")

        run_worker(self.svc.agent_status, done, fail)

    def _apply_status(self, st: dict) -> None:
        hello = st.get("hello") or {}
        parts = [
            f"游戏：{'运行中' if st.get('game_running') else '未运行'}",
            f"Mod：{'已安装' if st.get('mod_installed') else '未安装'}",
            f"NMSpy：{st.get('nmspy_version') or '缺失'} / 期望 {st.get('expected_nmspy') or '—'}",
            f"pymhf：{st.get('pymhf_version') or '缺失'}",
            f"agent：{'已连接' if st.get('reachable') else '未连接'}",
        ]
        self.status.setText("   ·   ".join(parts) + "\n" + (st.get("note") or ""))
        caps = (hello.get("capabilities") or {})
        rows = [
            ("玩家/星系/行星/船", bool(caps.get("player")), "low", "实时读取"),
            ("传送", bool(caps.get("teleport")), "high", "写入位置并触发加载"),
            ("扫描", bool(caps.get("scan")), "mid", "读取行星扫描字段"),
            ("还原", bool(caps.get("restore")), "mid", "还原上一次传送"),
        ]
        self.caps.setRowCount(len(rows))
        for i, (name, ok, risk, note) in enumerate(rows):
            self.caps.setItem(i, 0, QTableWidgetItem(name))
            self.caps.setItem(i, 1, QTableWidgetItem("是" if ok else "否"))
            self.caps.setItem(i, 2, QTableWidgetItem(risk))
            self.caps.setItem(i, 3, QTableWidgetItem(note))
        self.caps.resizeColumnsToContents()
        supported = bool(st.get("supported"))
        for b in (self.runtime_btn, self.deps_btn, self.probe_btn, self.inject_btn, self.start_btn):
            b.setEnabled(supported)

    # ---------------------------------------------------------------- 操作

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        for b in (self.runtime_btn, self.deps_btn, self.install_btn, self.inject_btn,
                  self.start_btn, self.stop_btn, self.refresh_btn, self.probe_btn):
            b.setEnabled(not busy)
        if text:
            self.status.setText(text)

    def _log(self, text: str) -> None:
        self.out.append(str(text))

    def _bootstrap_runtime(self) -> None:
        if not QMessageBox.question(self, "准备游戏内运行时",
                                    "会下载 Python embeddable 到 ~/.starforge/agent/runtime（约 10–30MB），"
                                    "需要网络。继续？") == QMessageBox.Yes:
            return
        self._set_busy(True, "正在准备 Python 运行时…")
        self._log("下载/解压 Python 运行时…")

        def done(res: dict) -> None:
            self._set_busy(False)
            self._log(json.dumps({k: res.get(k) for k in ("ok", "python", "error")},
                                 ensure_ascii=False, indent=1))
            if not res.get("ok"):
                self._log((res.get("output") or "")[-3000:])
            self.refresh()

        def fail(msg: str) -> None:
            self._set_busy(False)
            self._log(f"运行时准备失败：{msg}")

        run_worker(self.svc.agent_bootstrap_runtime, done, fail)

    def _install_deps(self) -> None:
        if not QMessageBox.question(self, "安装游戏内组件",
                                    "会通过 pip 安装 NMSpy（匹配当前游戏 build）和 pymhf[http_api]；"
                                    "需要网络。继续？") == QMessageBox.Yes:
            return
        self._set_busy(True, "正在安装/更新游戏内组件…（可能要几分钟）")

        def done(res: dict) -> None:
            self._set_busy(False)
            self._log(json.dumps({k: res.get(k) for k in ("ok", "cmd", "code")},
                                 ensure_ascii=False, indent=1))
            if not res.get("ok"):
                self._log((res.get("output") or "")[-4000:])
                if res.get("needs_runtime"):
                    QMessageBox.information(self, "先准备运行时",
                                            "还没有游戏内 Python 运行时；请先点「准备游戏内运行时」。")
            self.refresh()

        def fail(msg: str) -> None:
            self._set_busy(False)
            self._log(f"安装失败：{msg}")

        run_worker(self.svc.agent_install_deps, done, fail)

    def _install_mod(self) -> None:
        try:
            res = self.svc.agent_install_mod()
            self._log(f"Mod 已写入：{res.get('path')}")
            self.refresh()
        except Exception as e:                              # noqa: BLE001
            self._log(f"安装 Mod 失败：{type(e).__name__}: {e}")

    def _launch(self, attach: bool) -> None:
        if attach and self.auto_chk.isChecked():
            # 用户允许“没运行就启动”：直接改为启动游戏并注入
            try:
                st = self.svc.agent_status()
                if not st.get("game_running"):
                    attach = False
            except Exception:                              # noqa: BLE001
                pass
        self._set_busy(True, "正在注入并连接…")
        self._log("启动 pymhf 注入…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            self._set_busy(False)
            run_worker(self.svc.agent_wait, self._after_wait,
                       lambda m: self._log(f"等待 agent 失败：{m}"), 25.0)

        def fail(msg: str) -> None:
            self._set_busy(False)
            self._log(f"注入失败：{msg}")
            QMessageBox.warning(self, "注入失败", msg)

        run_worker(self.svc.agent_launch, done, fail, attach)

    def _after_wait(self, res: dict) -> None:
        self._log(json.dumps(res, ensure_ascii=False, indent=1))
        self.refresh()

    def _external_probe(self) -> None:
        self._log("外部内存只读探测…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))

        run_worker(self.svc.live_probe, done, lambda m: self._log(f"探测失败：{m}"))

    def _stop(self) -> None:
        try:
            self._log(json.dumps(self.svc.agent_stop(), ensure_ascii=False))
        except Exception as e:                              # noqa: BLE001
            self._log(f"停止失败：{type(e).__name__}: {e}")

    def _read(self, cmd: str) -> None:
        self._log(f"读取 {cmd}…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))

        run_worker(self.svc.agent_call, done, lambda m: self._log(f"读取失败：{m}"), cmd)

    def _teleport(self) -> None:
        glyphs = self.glyphs.text().strip().upper()
        if not glyphs:
            QMessageBox.information(self, "传送", "先填 12 位符文地址")
            return
        galaxy = None
        if self.galaxy_mode.currentData() == "custom":
            galaxy = int(self.galaxy.value())
        if QMessageBox.warning(
                self, "确认传送",
                f"将尝试把玩家位置写成 {glyphs}（星系：{galaxy if galaxy is not None else '当前'}）。\n"
                "只支持单人模式。请确认已备份存档。继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self._log("传送中…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            if not res.get("ok"):
                QMessageBox.warning(self, "传送失败", res.get("error") or "未知错误")

        run_worker(self.svc.agent_call, done, lambda m: self._log(f"传送失败：{m}"),
                   "teleport", glyphs=glyphs, galaxy=galaxy)

    def _restore(self) -> None:
        self._log("还原中…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))

        run_worker(self.svc.agent_call, done, lambda m: self._log(f"还原失败：{m}"), "restore")

    def _toggle_instant_scan(self, on: bool) -> None:
        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False))

        run_worker(self.svc.agent_call, done, lambda m: self._log(f"扫描开关失败：{m}"),
                   "scan.instant", on=on)

    def _scan(self, mode: str) -> None:
        self._log(f"扫描 {mode}…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))

        run_worker(self.svc.agent_call, done, lambda m: self._log(f"扫描失败：{m}"),
                   "scan", mode=mode)
