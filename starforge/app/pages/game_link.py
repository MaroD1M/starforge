"""游戏内通道：连接状态机、实时遥测、传送/扫描安全区。"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox, QTextEdit,
                               QVBoxLayout, QWidget)

from ...services import get_services
from ..widgets.ui import Card, muted
from ..widgets.worker import run as run_worker


class GameLinkPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._loaded = False
        self._runtime_ready = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)

        status = Card("连接状态", "正常包内置运行时，不需要联网")
        sv = status.v
        steps = QHBoxLayout()
        self.step_runtime = QLabel("1  运行时")
        self.step_mod = QLabel("2  Mod")
        self.step_agent = QLabel("3  Agent")
        for lab in (self.step_runtime, self.step_mod, self.step_agent):
            lab.setObjectName("chip")
            steps.addWidget(lab)
        steps.addStretch(1)
        sv.addLayout(steps)
        self.status = muted("检查中…")
        sv.addWidget(self.status)
        row = QHBoxLayout()
        self.connect_btn = QPushButton("连接游戏（自动安装 Mod）")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.clicked.connect(self._connect)
        row.addWidget(self.connect_btn)
        self.start_btn = QPushButton("启动游戏并注入")
        self.start_btn.clicked.connect(lambda: self._connect(start_game=True))
        row.addWidget(self.start_btn)
        self.stop_btn = QPushButton("停止注入器")
        self.stop_btn.clicked.connect(self._stop)
        row.addWidget(self.stop_btn)
        self.refresh_btn = QPushButton("刷新状态")
        self.refresh_btn.clicked.connect(self.refresh)
        row.addWidget(self.refresh_btn)
        self.repair_btn = QPushButton("修复运行时/组件")
        self.repair_btn.clicked.connect(self._repair)
        row.addWidget(self.repair_btn)
        self.probe_btn = QPushButton("外部内存只读探测")
        self.probe_btn.clicked.connect(self._external_probe)
        row.addWidget(self.probe_btn)
        sv.addLayout(row)
        root.addWidget(status)

        tele = Card("实时遥测")
        tv = tele.v
        row2 = QHBoxLayout()
        for text, cmd in (("玩家位置", "player"), ("当前星系", "system"),
                          ("当前行星", "planet"), ("游戏内船槽", "ships")):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, c=cmd: self._read(c))
            row2.addWidget(btn)
        tv.addLayout(row2)
        self.telemetry = muted("连接后点上面的按钮读取游戏内状态。")
        tv.addWidget(self.telemetry)
        root.addWidget(tele)

        safety = Card("安全区", "高风险操作；先备份存档")
        fv = safety.v
        form = QFormLayout()
        self.glyphs = QLineEdit()
        self.glyphs.setPlaceholderText("12 位传送门地址，例如 1043FEE69929")
        form.addRow("符文地址", self.glyphs)
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
        tp = QPushButton("传送到此地址")
        tp.clicked.connect(self._teleport)
        row3.addWidget(tp)
        restore = QPushButton("还原上一次传送")
        restore.clicked.connect(lambda: self._call("restore"))
        row3.addWidget(restore)
        form.addRow("", row3)
        fv.addLayout(form)
        row4 = QHBoxLayout()
        scan = QPushButton("读取当前行星扫描")
        scan.clicked.connect(lambda: self._call("scan", mode="read"))
        row4.addWidget(scan)
        self.instant = QCheckBox("游戏内扫描即时完成")
        self.instant.toggled.connect(lambda on: self._call("scan.instant", on=on))
        row4.addWidget(self.instant)
        row4.addStretch(1)
        fv.addLayout(row4)
        root.addWidget(safety)

        logcard = Card("日志")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        logcard.add(self.log)
        root.addWidget(logcard, 1)

    # ---------------------------------------------------------------- 状态

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self.refresh()

    def _chip(self, label: QLabel, text: str, ok: bool) -> None:
        label.setText(f"{text}")
        label.setProperty("state", "ok" if ok else "warn")
        label.style().unpolish(label)
        label.style().polish(label)

    def refresh(self) -> None:
        def done(st: dict) -> None:
            runtime = bool(st.get("runtime_ready"))
            self._runtime_ready = runtime
            reachable = bool(st.get("reachable"))
            self._chip(self.step_runtime, "1  运行时 ✓" if runtime else "1  运行时 ✗", runtime)
            self._chip(self.step_mod, "2  Mod ✓" if st.get("mod_installed") else "2  Mod ✗",
                       bool(st.get("mod_installed")))
            self._chip(self.step_agent, "3  Agent ✓" if reachable else "3  Agent ✗", reachable)
            self.status.setText(st.get("note") or "")
            self.repair_btn.setEnabled(bool(st.get("supported")) and not runtime)
            self.connect_btn.setEnabled(bool(st.get("supported")))
            self.start_btn.setEnabled(bool(st.get("supported")))
            self.stop_btn.setEnabled(bool(st.get("supported")))

        def fail(msg: str) -> None:
            self.status.setText(f"状态读取失败：{msg}")

        run_worker(self.svc.agent_status, done, fail)

    def _log(self, text: str) -> None:
        self.log.append(str(text))

    # ---------------------------------------------------------------- 连接

    def _connect(self, start_game: bool = False) -> None:
        if not self._runtime_ready:
            QMessageBox.information(self, "运行时缺失",
                                    "内置运行时未就绪；请先点「修复运行时/组件」，或重新解压完整包。")
            return
        self.connect_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self._log("注入中…" if not start_game else "启动游戏并注入…")

        def launched(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            run_worker(self.svc.agent_wait, self._after_wait,
                       lambda m: self._log(f"等待 agent 失败：{m}"), 25.0)

        def fail(msg: str) -> None:
            self.connect_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self._log(f"注入失败：{msg}")
            QMessageBox.warning(self, "注入失败", msg)

        run_worker(self.svc.agent_launch, launched, fail, attach=not start_game)

    def _after_wait(self, res: dict) -> None:
        self._log(json.dumps(res, ensure_ascii=False, indent=1))
        self.refresh()

    def _stop(self) -> None:
        try:
            self._log(json.dumps(self.svc.agent_stop(), ensure_ascii=False))
        except Exception as e:                              # noqa: BLE001
            self._log(f"停止失败：{type(e).__name__}: {e}")

    def _external_probe(self) -> None:
        self._log("外部内存只读探测…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))

        def fail(msg: str) -> None:
            self._log(f"探测失败：{msg}")

        run_worker(self.svc.live_probe, done, fail)

    def _repair(self) -> None:
        self._log("修复运行时/组件…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            self.refresh()

        def fail(msg: str) -> None:
            self._log(f"修复失败：{msg}")

        run_worker(self.svc.agent_install_deps, done, fail)

    # ---------------------------------------------------------------- 读取

    def _read(self, cmd: str) -> None:
        self._log(f"读取 {cmd}…")
        self.telemetry.setText("读取中…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            if cmd == "player":
                loc = res.get("location") or {}
                self.telemetry.setText(
                    f"UA {res.get('ua') or '—'}  ·  行星 {loc.get('planet', '—')}  ·  "
                    f"星系 {loc.get('system', '—')}  ·  {res.get('system_name') or ''}")
            elif cmd == "system":
                self.telemetry.setText(
                    f"{res.get('system_name') or '当前星系'}  ·  {len(res.get('planets') or [])} 颗行星")
            elif cmd == "planet":
                p = res.get("planet") or {}
                self.telemetry.setText(
                    f"{p.get('name') or p.get('planet_type') or '行星'}  ·  "
                    f"{p.get('weather') or ''}  ·  {p.get('resources') or ''}")
            elif cmd == "ships":
                self.telemetry.setText(f"游戏内船槽：{len(res.get('ships') or [])} 艘")

        def fail(msg: str) -> None:
            self.telemetry.setText(f"读取失败：{msg}")
            self._log(f"读取失败：{msg}")

        run_worker(self.svc.agent_call, done, fail, cmd)

    # ---------------------------------------------------------------- 写

    def _call(self, cmd: str, **params) -> None:
        self._log(f"{cmd}…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))

        run_worker(self.svc.agent_call, done, lambda m: self._log(f"{cmd} 失败：{m}"), cmd, **params)

    def _teleport(self) -> None:
        glyphs = self.glyphs.text().strip().upper()
        if not glyphs:
            QMessageBox.information(self, "传送", "先填 12 位符文地址")
            return
        galaxy = int(self.galaxy.value()) if self.galaxy_mode.currentData() == "custom" else None
        if QMessageBox.warning(
                self, "确认传送",
                f"将尝试把玩家位置写成 {glyphs}（星系：{galaxy if galaxy is not None else '当前'}）。\n"
                "只支持单人模式。请确认已备份存档。继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self._call("teleport", glyphs=glyphs, galaxy=galaxy)
