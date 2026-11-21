"""游戏内通道：连接状态机、实时遥测、传送/扫描安全区。"""
from __future__ import annotations

import json
import os
import re

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QSpinBox, QTextEdit, QVBoxLayout, QWidget)

from ...services import get_services
from .. import notify
from ..widgets.feedback import EmptyState, ErrorBanner, LoadingOverlay
from ..widgets.live_assets import (BLOCK_LABELS, BLOCKS, NO_SAVE_TEXT,
                                   LiveAssetsCard, live_asset_error_text)
from ..widgets.page import PAGE_SPACING, SCROLL_MARGINS
from ..widgets.page_header import PageHeader
from ..widgets.planet_dossier import (MISSING, PlanetDossier, PoiDossier,
                                       format_planet_text)
from ..widgets.ui import Card, muted
from ..widgets.worker import run as run_worker

_READ_LABELS = {"player": "玩家位置", "system": "当前星系",
                "planet": "当前行星", "ships": "游戏内船槽"}
_CALL_LABELS = {"teleport": "传送", "teleport.portal": "传送门效果",
                "restore": "还原", "scan": "扫描", "scan.instant": "即时扫描"}
_CAP_FALLBACK = {"planet.scan": "planet", "scan.poi": "scan"}
_GATING_ALIASES = ("allow_unverified_agent", "allow_unverified_writes",
                   "allow_unverified_build_writes", "agent_allow_unverified_writes",
                   "allow_unverified_build", "experimental_writes")


from ..dialogs.confirm import ask_write

class GameLinkPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._loaded = False
        self._runtime_files = False
        self._runtime_ready = False
        self._runtime_error = ""
        self._reachable = False
        self._in_game = False
        self._build_verified = False
        self._multiplayer = False
        self._caps: dict = {}
        self._cap_state_known = False
        self._portal_available = False
        self._portal_reason = "当前游戏内代理未实现传送门效果；需要实机验证后启用。"
        self._unverified_key: str | None = None
        self._read_btns: list[QPushButton] = []
        self._safety_btns: list[QPushButton] = []
        self._cap_buttons: list[tuple[QWidget, str]] = []
        self._live_asset_errors: dict[str, str] = {}
        self._live_asset_generation = 0
        self._asset_banner_active = False
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1500)
        self._poll_timer.timeout.connect(self._poll_hello)
        self._poll_busy = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(*SCROLL_MARGINS)
        outer.setSpacing(PAGE_SPACING)
        scroll.setWidget(content)
        root.addWidget(scroll)

        self.header = PageHeader(
            "游戏内代理",
            "连接游戏、读取实时遥测、行星档案与兴趣点；高风险操作请先备份存档。")
        outer.addWidget(self.header)
        self.error_banner = ErrorBanner("")
        self.error_banner.set_retry_callback(self.refresh)
        outer.addWidget(self.error_banner)

        top = QGridLayout()
        top.setHorizontalSpacing(PAGE_SPACING)
        top.setVerticalSpacing(PAGE_SPACING)

        status = Card("连接状态", "正常包内置运行时，不需要联网")
        sv = status.v
        steps = QHBoxLayout()
        steps.setSpacing(6)
        self.step_runtime = QLabel("1  运行时")
        self.step_mod = QLabel("2  游戏内组件")
        self.step_mod.setToolTip("游戏内组件（NMSpy/pymhf）")
        self.step_agent = QLabel("3  游戏内代理")
        self.step_agent.setToolTip("由游戏内组件（NMSpy/pymhf）提供")
        for lab in (self.step_runtime, self.step_mod, self.step_agent):
            lab.setObjectName("chip")
            steps.addWidget(lab)
        steps.addStretch(1)
        sv.addLayout(steps)

        meta = QHBoxLayout()
        meta.setSpacing(6)
        self.build_status = QLabel("游戏版本 —")
        self.build_status.setObjectName("chip")
        self.mp_status = QLabel("多人：—")
        self.mp_status.setObjectName("chip")
        meta.addWidget(self.build_status)
        meta.addWidget(self.mp_status)
        meta.addStretch(1)
        sv.addLayout(meta)

        self.status = muted("检查中…")
        sv.addWidget(self.status)
        self.connection_empty = EmptyState(
            "正在检查游戏内代理",
            "先确认运行时与游戏内组件，再进入游戏并载入存档。",
            icon="◇")
        self.connection_empty.setMaximumHeight(176)
        self.connection_empty.actionTriggered.connect(self._connect)
        self.empty_state = self.connection_empty
        sv.addWidget(self.connection_empty)

        self.connect_btn = QPushButton("连接游戏")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.setToolTip("连接已运行的游戏并注入；缺少组件时会提示修复")
        self.connect_btn.clicked.connect(self._connect)
        sv.addWidget(self.connect_btn)

        actions = QGridLayout()
        actions.setHorizontalSpacing(6)
        actions.setVerticalSpacing(6)
        self.start_btn = QPushButton("启动游戏并注入")
        self.start_btn.clicked.connect(lambda: self._connect(start_game=True))
        actions.addWidget(self.start_btn, 0, 0)
        self.stop_btn = QPushButton("停止注入器")
        self.stop_btn.clicked.connect(self._stop)
        actions.addWidget(self.stop_btn, 0, 1)
        self.refresh_btn = QPushButton("刷新状态")
        self.refresh_btn.clicked.connect(self.refresh)
        actions.addWidget(self.refresh_btn, 1, 0)
        self.repair_btn = QPushButton("修复运行时/游戏内组件")
        self.repair_btn.clicked.connect(self._repair)
        actions.addWidget(self.repair_btn, 1, 1)
        self.probe_btn = QPushButton("外部内存只读探测")
        self.probe_btn.clicked.connect(self._external_probe)
        actions.addWidget(self.probe_btn, 2, 0, 1, 2)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        sv.addLayout(actions)
        top.addWidget(status, 0, 0)

        tele = Card("实时遥测", "连接并载入存档后可读取")
        tv = tele.v
        tele_grid = QGridLayout()
        tele_grid.setHorizontalSpacing(6)
        tele_grid.setVerticalSpacing(6)
        for i, (text, cmd) in enumerate((("玩家位置", "player"), ("当前星系", "system"),
                                         ("当前行星", "planet"), ("游戏内船槽", "ships"))):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, c=cmd: self._read(c))
            tele_grid.addWidget(btn, i // 2, i % 2)
            self._read_btns.append(btn)
            self._cap_buttons.append((btn, cmd))
        tele_grid.setColumnStretch(0, 1)
        tele_grid.setColumnStretch(1, 1)
        tv.addLayout(tele_grid)
        self.telemetry = muted("连接后点上面的按钮读取游戏内状态。")
        tv.addWidget(self.telemetry)
        tv.addStretch(1)
        top.addWidget(tele, 0, 1)
        top.setColumnStretch(0, 3)
        top.setColumnStretch(1, 2)
        outer.addLayout(top)

        self.live_assets = LiveAssetsCard()
        self.live_assets_card = self.live_assets
        outer.addWidget(self.live_assets)

        planet = Card("行星档案", "读取当前行星档案；需要先进入存档")
        pv = planet.v
        prow = QHBoxLayout()
        prow.setSpacing(6)
        self.planet_scan_btn = QPushButton("读取行星档案")
        self.planet_scan_btn.setToolTip("读取当前行星的天气、哨兵、资源、动植物与生物标识（ID）")
        self.planet_scan_btn.clicked.connect(self._planet_scan)
        prow.addWidget(self.planet_scan_btn)
        self.planet_refresh_btn = QPushButton("刷新档案")
        self.planet_refresh_btn.setToolTip("重新读取当前行星档案")
        self.planet_refresh_btn.clicked.connect(self._refresh_planet)
        prow.addWidget(self.planet_refresh_btn)
        self.planet_copy_btn = QPushButton("复制档案")
        self.planet_copy_btn.setToolTip("复制当前行星档案为文本")
        self.planet_copy_btn.clicked.connect(self._copy_planet)
        prow.addWidget(self.planet_copy_btn)
        prow.addStretch(1)
        pv.addLayout(prow)
        self.planet_result = PlanetDossier()
        self.planet_result.setMinimumHeight(150)
        self.planet_result.set_message("尚未读取行星档案；请先连接游戏并进入存档。")
        pv.addWidget(self.planet_result)
        self._cap_buttons.extend([(self.planet_scan_btn, "planet.scan"),
                                  (self.planet_refresh_btn, "planet.scan")])
        outer.addWidget(planet)

        safety = Card("安全区", "高风险操作；先备份存档")
        fv = safety.v
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.glyphs = QLineEdit()
        self.glyphs.setPlaceholderText("12 位传送门地址，例如 1043FEE69929")
        form.addRow("符文地址", self.glyphs)
        self.teleport_mode = QComboBox()
        self.teleport_mode.addItem("普通写位置", "teleport")
        self.teleport_mode.addItem("传送门效果", "teleport.portal")
        form.addRow("传送方式", self.teleport_mode)
        galaxy_row = QHBoxLayout()
        galaxy_row.setSpacing(6)
        self.galaxy_mode = QComboBox()
        self.galaxy_mode.addItem("保持当前星系", None)
        self.galaxy_mode.addItem("指定星系编号", "custom")
        galaxy_row.addWidget(self.galaxy_mode, 1)
        self.galaxy = QSpinBox()
        self.galaxy.setRange(0, 254)
        self.galaxy.setEnabled(False)
        self.galaxy_mode.currentIndexChanged.connect(
            lambda: self.galaxy.setEnabled(self.galaxy_mode.currentData() == "custom"))
        galaxy_row.addWidget(self.galaxy)
        form.addRow("目标星系", galaxy_row)
        transfer_row = QHBoxLayout()
        transfer_row.setSpacing(6)
        tp = QPushButton("传送到此地址")
        tp.clicked.connect(self._teleport)
        transfer_row.addWidget(tp)
        restore = QPushButton("还原上一次传送")
        restore.clicked.connect(lambda: self._call("restore"))
        transfer_row.addWidget(restore)
        transfer_row.addStretch(1)
        self._safety_btns.extend([tp, restore])
        self._cap_buttons.extend([(tp, "teleport"), (restore, "restore")])
        form.addRow("", transfer_row)
        fv.addLayout(form)

        self.portal_note = muted("")
        fv.addWidget(self.portal_note)

        scan_row = QHBoxLayout()
        scan_row.setSpacing(6)
        scan = QPushButton("读取当前行星扫描")
        scan.clicked.connect(lambda: self._call("scan", mode="read"))
        scan_row.addWidget(scan)
        self._safety_btns.append(scan)
        self._cap_buttons.append((scan, "scan"))
        self.instant = QCheckBox("游戏内扫描即时完成")
        self.instant.toggled.connect(lambda on: self._call("scan.instant", on=on))
        scan_row.addWidget(self.instant)
        self._cap_buttons.append((self.instant, "scan.instant"))
        scan_row.addStretch(1)
        fv.addLayout(scan_row)
        self.allow_unverified = QCheckBox("允许未验证游戏版本实验写操作")
        self.allow_unverified.setAccessibleName("允许未验证游戏版本实验写操作")
        self.allow_unverified.setEnabled(False)
        self.allow_unverified.setToolTip("当前版本没有对应的安全设置，暂不可用。")
        self.allow_unverified.toggled.connect(self._save_gating)
        fv.addWidget(self.allow_unverified)
        self.gating_note = muted("读取安全设置中…")
        fv.addWidget(self.gating_note)
        outer.addWidget(safety)

        poi = Card("附近兴趣点", "传送门 / 古遗迹 / 货船 / 飞船；需要游戏内代理实机校准")
        ov = poi.v
        poi_grid = QGridLayout()
        poi_grid.setHorizontalSpacing(6)
        poi_grid.setVerticalSpacing(6)
        self.poi_buttons: dict[str, QPushButton] = {}
        for i, (text, kind) in enumerate((("传送门", "portal"), ("古遗迹", "ruins"),
                                          ("货船", "freighter"), ("飞船", "ship"))):
            btn = QPushButton(text)
            btn.setToolTip(f"扫描附近的{text}：需要 agent 的 scan.poi 端点，当前尚未实现")
            btn.setEnabled(False)                         # scan.poi 端点未实现，避免点了必然报错
            btn.clicked.connect(lambda _=False, k=kind, t=text: self._scan_poi(k, t))
            poi_grid.addWidget(btn, i // 2, i % 2)
            self.poi_buttons[kind] = btn
        poi_grid.setColumnStretch(0, 1)
        poi_grid.setColumnStretch(1, 1)
        ov.addLayout(poi_grid)
        self.poi_result = PoiDossier()
        self.poi_result.setMinimumHeight(130)
        self.poi_result.set_message(
            "附近兴趣点：需要游戏内代理实机校准；未校准前不会显示任何结果，也不会伪造坐标。")
        ov.addWidget(self.poi_result)
        outer.addWidget(poi)

        mods = Card("表情模板 Mod", "安装后游戏表情菜单会出现 8 个可领取模板；只写游戏 GAMEDATA/MODS 目录")
        modbar = QHBoxLayout()
        self.install_mod_btn = QPushButton("安装 / 更新模板 Mod")
        self.install_mod_btn.setToolTip("把 starforge-templates 写入游戏 GAMEDATA/MODS；重启游戏后生效")
        self.install_mod_btn.clicked.connect(self._install_template_mod)
        modbar.addWidget(self.install_mod_btn)
        modbar.addStretch(1)
        self.open_mods_btn = QPushButton("打开 Mod 目录")
        self.open_mods_btn.setToolTip("在资源管理器中打开游戏 GAMEDATA/MODS")
        self.open_mods_btn.clicked.connect(self._open_mods_dir)
        modbar.addWidget(self.open_mods_btn)
        mods.add_layout(modbar)
        self.mod_status = QLabel("未安装（或未知）：点左侧按钮安装，装完需要重启游戏")
        self.mod_status.setWordWrap(True)
        mods.add(self.mod_status)
        outer.addWidget(mods)

        logcard = Card("日志", "诊断数据按 JSON 格式原样记录，便于回报问题")
        logbar = QHBoxLayout()
        logbar.addStretch(1)
        clear = QPushButton("清空")
        clear.clicked.connect(self._clear_log)
        logbar.addWidget(clear)
        copy = QPushButton("复制")
        copy.clicked.connect(self._copy_log)
        logbar.addWidget(copy)
        logcard.add_layout(logbar)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(150)
        self.log.setMaximumHeight(220)
        self.log.setStyleSheet("font-family:Consolas,monospace;font-size:11.5px;")
        logcard.add(self.log)
        outer.addWidget(logcard)
        outer.addStretch(1)

        self.portal_mode = self.teleport_mode
        self.portal_combo = self.teleport_mode
        self.planet_out = self.planet_result
        self.planet_scan_result = self.planet_result
        self.planet_dossier = self.planet_result
        self.planet_table = self.planet_result.table
        self.poi_out = self.poi_result
        self.poi_scan_result = self.poi_result
        self.poi_dossier = self.poi_result
        self.poi_table = self.poi_result.table
        self.unverified_writes = self.allow_unverified
        self.allow_unverified_writes = self.allow_unverified
        self.loading_overlay = LoadingOverlay(self, "正在连接游戏内代理…")
        self.loading = self.loading_overlay
        self._set_portal_available(False, self._portal_reason)

    # ---------------------------------------------------------------- 状态

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._load_gating()
        self.refresh()

    def _chip(self, label: QLabel, text: str, ok: bool) -> None:
        label.setText(f"{text}")
        label.setProperty("state", "ok" if ok else "warn")
        label.style().unpolish(label)
        label.style().polish(label)

    @staticmethod
    def _cn(text: str) -> str:
        value = str(text or "")
        for pattern, repl in ((r"游戏内\s*[Aa]gent", "游戏内代理"),
                              (r"\bAgent\b", "游戏内代理"), (r"\bagent\b", "游戏内代理"),
                              (r"\bInspector\b", "检查器"),
                              (r"\bBuild\b", "游戏版本"), (r"\bbuilds?\b", "游戏版本"),
                              (r"\bMod\b", "游戏内组件"), (r"\bmods?\b", "游戏内组件"),
                              (r"\bPOI\b", "兴趣点"), (r"\bUA\b", "银河地址")):
            value = re.sub(pattern, repl, value, flags=re.IGNORECASE)
        return value

    def refresh(self) -> None:
        self.loading_overlay.start("正在刷新游戏内代理状态…")

        def done(cap: dict) -> None:
            if not isinstance(cap, dict) or "status" not in cap:
                src = cap if isinstance(cap, dict) else {}
                cap = {"status": src, "capabilities": src.get("capabilities") or {},
                       "build": src.get("build") or {}}
            self._apply_state(cap)
            self.loading_overlay.stop()

        def fail(msg: str) -> None:
            text = f"状态读取失败：{self._cn(msg)}"
            self.status.setText(text)
            self.error_banner.show_error(text)
            self.loading_overlay.stop()
            notify.error(text)

        run_worker(self.svc.live_capabilities, done, fail)

    def _apply_state(self, cap: dict) -> None:
        """按 build/多人/hello 三方结果更新界面与按钮（可单独测试）。"""
        st = cap.get("status") or {}
        runtime_files = bool(st.get("runtime_ready"))
        runtime = (runtime_files and bool(st.get("pymhf_http_api"))
                   and bool(st.get("nmspy_version")) and bool(st.get("pymhf_version")))
        self._runtime_files = runtime_files
        self._runtime_ready = runtime
        self._runtime_error = str(st.get("runtime_error") or "")
        reachable = bool(st.get("reachable"))
        self._reachable = reachable
        hello = st.get("hello") or {}
        self._in_game = bool(hello.get("in_game"))
        self._multiplayer = bool(cap.get("multiplayer", hello.get("multiplayer")))
        build_info = cap.get("build") or st.get("build") or {}
        known = build_info.get("known") or {}
        verified = bool(build_info.get("write_allowed",
                                       build_info.get("verified", False)))
        self._build_verified = verified
        status_text = str(build_info.get("status") or ("verified" if verified else "unverified"))
        status_zh = {"verified": "已验证", "unverified": "未验证",
                     "unknown": "未知"}.get(status_text.lower(), self._cn(status_text))
        build_id = str(build_info.get("build_id") or known.get("build") or "—")
        self._chip(self.step_runtime, "1  运行时 ✓" if runtime_files else "1  运行时 ✗",
                   runtime_files)
        self._chip(self.step_mod, "2  游戏内组件 ✓" if runtime else "2  游戏内组件 ✗", runtime)
        if not runtime and st.get("mod_installed"):
            self.step_mod.setToolTip("游戏内组件文件已安装，但 NMSpy/pymhf 未就绪；请点修复")
        else:
            self.step_mod.setToolTip("游戏内组件（NMSpy/pymhf）")
        self._chip(self.step_agent, "3  游戏内代理 ✓" if reachable else "3  游戏内代理 ✗", reachable)
        self._chip(self.build_status, f"游戏版本 {build_id} · {status_zh}", verified)
        if self._multiplayer:
            mp_text, mp_ok = "多人：写已禁用", False
        elif not verified:
            mp_text, mp_ok = "单人：未验证只读", True
        else:
            mp_text, mp_ok = "单人：可写", True
        self._chip(self.mp_status, mp_text, mp_ok)
        self.build_status.setToolTip(self._cn(str(build_info.get("reason") or status_zh)))
        if reachable and not self._in_game:
            text = "已注入，但游戏还没进入存档。请载入存档后再读取/传送。"
        else:
            extra = []
            if not verified and build_info.get("reason"):
                extra.append(self._cn(str(build_info["reason"])))
            if self._multiplayer:
                extra.append("多人模式：传送/还原/扫描写已禁用")
            note = self._cn(str(st.get("note") or ""))
            text = "；".join([x for x in [note, *extra] if x])
        if not runtime and runtime_files and self._runtime_error:
            text = f"{text}；组件读取错误：{self._runtime_error}" if text else \
                f"组件读取错误：{self._runtime_error}"
        self.status.setText(text)
        self.repair_btn.setEnabled(bool(st.get("supported")) and not runtime)
        self.connect_btn.setEnabled(bool(st.get("supported")) and runtime)
        self.start_btn.setEnabled(bool(st.get("supported")) and runtime)
        self.stop_btn.setEnabled(bool(st.get("supported")))
        caps = cap.get("capabilities") or {}
        self._caps = caps
        self._cap_state_known = True
        for btn, key in self._cap_buttons:
            lookup = key if key in caps else _CAP_FALLBACK.get(key, key)
            info = caps.get(lookup) or {}
            btn.setEnabled(reachable and self._in_game and bool(info.get("available")))
            if key in ("planet.scan", "scan.poi"):
                reason = self._read_block_reason(key)
                btn.setToolTip(reason or btn.toolTip())
        if not self.planet_result.has_data():
            reason = self._read_block_reason("planet.scan")
            if reason:
                self.planet_result.set_message(f"行星档案不可用：{reason}")
        if not self.poi_result.has_data():
            reason = self._read_block_reason("scan.poi")
            if reason:
                self.poi_result.set_message(f"附近兴趣点暂不可用：{reason}")
        portal = caps.get("teleport.portal") or {}
        if not verified:
            portal_ok, portal_reason = False, "游戏版本未验证：传送门效果已禁用。"
        elif self._multiplayer:
            portal_ok, portal_reason = False, "多人模式：传送门效果已禁用。"
        else:
            portal_ok = bool(portal.get("available"))
            portal_reason = self._cn(str(portal.get("reason") or "")) or self._portal_reason
        self._set_portal_available(portal_ok, portal_reason)
        self.error_banner.clear()
        self._asset_banner_active = False
        self._update_connection_empty()
        if reachable and self._in_game:
            self._refresh_live_assets()
        else:
            self._reset_live_assets()
        if reachable and not self._in_game:
            if not self._poll_timer.isActive():
                self._poll_timer.start()
        else:
            self._poll_timer.stop()

    def _update_connection_empty(self) -> None:
        state = self.connection_empty
        if not self._runtime_ready:
            state.title_label.setText("游戏内组件未就绪")
            detail = f"（{self._runtime_error}）" if self._runtime_error else ""
            state.description_label.setText(
                f"运行时文件或 NMSpy/pymhf 未完整加载{detail}；请点「修复运行时/游戏内组件」。")
            state.description_label.setVisible(True)
            state.show()
        elif not self._reachable:
            state.title_label.setText("尚未连接游戏内代理")
            state.description_label.setText(
                "进入游戏并载入存档后，点「连接游戏」。")
            state.description_label.setVisible(True)
            state.show()
        elif not self._in_game:
            state.title_label.setText("已注入，等待进入存档")
            state.description_label.setText(
                "游戏内组件已就绪；载入存档后页面会自动刷新可用能力。")
            state.description_label.setVisible(True)
            state.show()
        else:
            state.hide()

    def _read_block_reason(self, key: str) -> str:
        if not self._runtime_ready:
            return "内置运行时未就绪；请先点「修复运行时/游戏内组件」。"
        if not self._reachable:
            return "未连接游戏内代理；请先点「连接游戏」并确认游戏已注入。"
        if not self._in_game:
            return "游戏还没进入存档；请先载入存档再读取。"
        caps = self._caps or {}
        lookup = key if key in caps else _CAP_FALLBACK.get(key, key)
        info = caps.get(lookup) or {}
        if not info.get("available"):
            reason = self._cn(str(info.get("reason") or "")).strip()
            if key == "planet.scan":
                return reason or "当前游戏内代理不支持读取行星档案。"
            if key == "scan.poi":
                return reason or "当前游戏内代理不支持扫描附近兴趣点。"
            return reason or "当前游戏内代理不支持该读取能力。"
        return ""

    # ------------------------------------------------------------ 实时资产

    def _reset_live_assets(self) -> None:
        """未连接/未进存档：只显示等待说明，不保留旧数据也不伪造空数据。"""
        self._live_asset_generation += 1
        self._live_asset_errors.clear()
        self._clear_asset_banner()
        if not self._reachable:
            self.live_assets.set_waiting()
        elif not self._in_game:
            self.live_assets.set_waiting(NO_SAVE_TEXT)
        else:
            self.live_assets.set_waiting()

    def _refresh_live_assets(self) -> None:
        """连接成功或页面刷新后自动拉一次三个只读端点。"""
        if not (self._reachable and self._in_game):
            self._reset_live_assets()
            return
        self._live_asset_generation += 1
        generation = self._live_asset_generation
        self._live_asset_errors.clear()
        self._clear_asset_banner()
        self.live_assets.set_loading()
        for cmd in BLOCKS:
            run_worker(
                self.svc.agent_call,
                lambda res, c=cmd, g=generation: self._asset_done(c, res, g),
                lambda msg, c=cmd, g=generation: self._asset_failed(c, msg, g),
                cmd)

    def _asset_done(self, cmd: str, res, generation: int) -> None:
        if generation != self._live_asset_generation:
            return                                   # 已被更新一轮刷新取代
        label = BLOCK_LABELS.get(cmd, cmd)
        if not isinstance(res, dict):
            self._asset_failed(cmd, f"返回类型异常：{type(res).__name__}", generation)
            return
        if res.get("ok") is False:
            text = live_asset_error_text(
                label,
                res.get("error") or res.get("reason") or "",
                code=str(res.get("code") or ""),
                unsupported=bool(res.get("unsupported")))
            self._asset_failed(cmd, text, generation, formatted=True)
            return
        self._live_asset_errors.pop(cmd, None)
        self.live_assets.set_data(cmd, res)
        self._log(f"实时资产：{label}已更新。")
        self._sync_asset_banner()

    def _asset_failed(self, cmd: str, message: str, generation: int,
                      formatted: bool = False) -> None:
        if generation != self._live_asset_generation:
            return
        label = BLOCK_LABELS.get(cmd, cmd)
        text = message if formatted else live_asset_error_text(label, message)
        self._live_asset_errors[cmd] = text
        self.live_assets.set_error(cmd, text)
        self._log(text)
        self._sync_asset_banner()

    def _sync_asset_banner(self) -> None:
        """把各区块的错误合并到页面横幅；全部成功后再收起。"""
        if self._live_asset_errors:
            text = "；".join(self._live_asset_errors[cmd] for cmd in BLOCKS
                             if cmd in self._live_asset_errors)
            self.error_banner.show_error(text)
            self._asset_banner_active = True
        elif self._asset_banner_active:
            self._clear_asset_banner()

    def _clear_asset_banner(self) -> None:
        """只收起本卡片此前展示的横幅，避免清掉其它操作的错误。"""
        if self._asset_banner_active:
            self.error_banner.clear()
            self._asset_banner_active = False

    def _set_portal_available(self, ok: bool, reason: str) -> None:
        self._portal_available = bool(ok)
        self._portal_reason = self._cn(reason or self._portal_reason)
        idx = self.teleport_mode.findData("teleport.portal")
        if idx >= 0:
            item = self.teleport_mode.model().item(idx)
            if item is not None:
                item.setEnabled(self._portal_available)
            self.teleport_mode.setItemData(idx, self._portal_reason, Qt.ToolTipRole)
            if not self._portal_available and self.teleport_mode.currentIndex() == idx:
                normal = self.teleport_mode.findData("teleport")
                if normal >= 0:
                    self.teleport_mode.setCurrentIndex(normal)
        if self._portal_available:
            self.portal_note.setText("传送门效果：可用；未验证版本或多人模式下会自动禁用。")
        else:
            self.portal_note.setText(f"传送门效果：已禁用。{self._portal_reason}")

    @staticmethod
    def _gating_key(settings: dict) -> str | None:
        for key in _GATING_ALIASES:
            if key in settings:
                return key
        for key in settings:
            low = str(key).lower()
            if ("unverified" in low and ("write" in low or "build" in low)) or \
                    ("experimental" in low and "write" in low):
                return str(key)
        return None

    def _load_gating(self) -> None:
        def done(res: dict) -> None:
            settings = (res or {}).get("settings") or {}
            key = self._gating_key(settings)
            self._unverified_key = key
            self.allow_unverified.blockSignals(True)
            if key is None:
                self.allow_unverified.setChecked(False)
                self.allow_unverified.setEnabled(False)
                self.allow_unverified.setToolTip("当前版本没有对应的安全设置，暂不可用。")
                self.gating_note.setText("当前版本没有“允许未验证游戏版本实验写操作”设置，暂不可用。")
            else:
                self.allow_unverified.setChecked(bool(settings.get(key)))
                self.allow_unverified.setEnabled(True)
                self.allow_unverified.setToolTip("由游戏版本闸门控制；未验证版本仍可能拒绝实验写操作。")
                self.gating_note.setText("已读取安全设置；实验写操作仍受游戏版本闸门约束。")
            self.allow_unverified.blockSignals(False)

        def fail(msg: str) -> None:
            self._unverified_key = None
            self.allow_unverified.blockSignals(True)
            self.allow_unverified.setChecked(False)
            self.allow_unverified.blockSignals(False)
            self.allow_unverified.setEnabled(False)
            self.allow_unverified.setToolTip("读取安全设置失败，暂不可用。")
            self.gating_note.setText(f"读取安全设置失败：{self._cn(msg)}；此选项暂不可用。")

        run_worker(self.svc.settings_snapshot, done, fail)

    def _save_gating(self, on: bool) -> None:
        if not self._unverified_key:
            self.gating_note.setText("当前版本没有对应的安全设置，此选项不可用。")
            notify.warn("当前版本没有对应的安全设置，此选项不可用。")
            return
        try:
            self.svc.update_settings(**{self._unverified_key: bool(on)})
        except Exception as e:                              # noqa: BLE001
            text = f"保存安全设置失败：{self._cn(f'{type(e).__name__}: {e}')}"
            self.gating_note.setText(text)
            self.error_banner.show_error(text)
            notify.error(text)
            return
        self.gating_note.setText("安全设置已保存；实验写操作仍受游戏版本闸门约束。"
                                 if on else "安全设置已保存；实验写操作已关闭。")
        notify.success("安全设置已保存。")

    def _poll_hello(self) -> None:
        if self._poll_busy:
            return
        self._poll_busy = True

        def done(res: dict) -> None:
            self._poll_busy = False
            if res.get("in_game"):
                self._poll_timer.stop()
                self.refresh()

        def fail(_msg: str) -> None:
            self._poll_busy = False

        run_worker(self.svc.agent_call, done, fail, "hello")

    def _log(self, text: str) -> None:
        self.log.append(str(text))

    def _copy_log(self) -> None:
        text = self.log.toPlainText()
        if not text.strip():
            notify.warn("日志为空，暂无可复制内容。")
            return
        QGuiApplication.clipboard().setText(text)
        notify.success("日志已复制。")

    def _clear_log(self) -> None:
        if not self.log.toPlainText().strip():
            notify.warn("日志已经是空的。")
            return
        self.log.clear()
        notify.success("日志已清空。")

    # ---------------------------------------------------------------- 连接

    def _connect(self, start_game: bool = False) -> None:
        if not self._runtime_ready:
            detail = f"：{self._runtime_error}" if self._runtime_error else ""
            text = (f"游戏内组件未就绪{detail}；请先点「修复运行时/游戏内组件」，"
                    "或重新解压完整包。")
            notify.warn(text)
            self.error_banner.show_error(text)
            return
        self.connect_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        text = "启动游戏并注入…" if start_game else "注入中…"
        self._log(text)
        self.loading_overlay.start("正在启动游戏并注入…" if start_game else "正在连接游戏内代理…")
        notify.toast(text)

        def launched(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            self.loading_overlay.set_text("等待游戏内代理响应…")
            notify.toast("游戏内组件已启动，等待游戏内代理响应…")
            run_worker(self.svc.agent_wait, self._after_wait, wait_fail, 25.0)

        def wait_fail(msg: str) -> None:
            text = f"等待游戏内代理失败：{self._cn(msg)}"
            self._log(text)
            self.loading_overlay.stop()
            self.error_banner.show_error(text)
            notify.error(text)

        def fail(msg: str) -> None:
            self.connect_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            text = f"注入失败：{self._cn(msg)}"
            self._log(text)
            self.loading_overlay.stop()
            self.error_banner.show_error(text)
            notify.error(text)

        if start_game:
            run_worker(self.svc.agent_launch, launched, fail, attach=False)
        else:
            # 已运行的游戏：走 agent_connect（内部用 attach=False，pymhf 会发现已运行实例）。
            # 不能再用 attach=True——实测那条路会让游戏以访问冲突退出。
            run_worker(self.svc.agent_connect, launched, fail)

    def _after_wait(self, res: dict) -> None:
        self._log(json.dumps(res, ensure_ascii=False, indent=1))
        self.loading_overlay.stop()
        if res.get("in_game"):
            notify.success("游戏内代理已连接。")
        else:
            notify.warn("游戏内代理已连接，但还未进入存档；请载入存档。")
        self.refresh()

    def _stop(self) -> None:
        try:
            self._log(json.dumps(self.svc.agent_stop(), ensure_ascii=False))
            notify.success("已停止注入器。")
        except Exception as e:                              # noqa: BLE001
            text = f"停止失败：{self._cn(f'{type(e).__name__}: {e}')}"
            self._log(text)
            self.error_banner.show_error(text)
            notify.error(text)

    def _external_probe(self) -> None:
        self._log("外部内存只读探测…")
        self.loading_overlay.start("正在进行外部内存只读探测…")
        notify.toast("正在进行外部内存只读探测…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            self.loading_overlay.stop()
            notify.success("外部内存只读探测完成，结果见日志。")

        def fail(msg: str) -> None:
            text = f"探测失败：{self._cn(msg)}"
            self._log(text)
            self.loading_overlay.stop()
            self.error_banner.show_error(text)
            notify.error(text)

        run_worker(self.svc.live_probe, done, fail)

    def _repair(self) -> None:
        self._log("修复运行时/游戏内组件…")
        self.loading_overlay.start("正在修复运行时/游戏内组件…")
        notify.toast("正在修复运行时/游戏内组件…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            self.loading_overlay.stop()
            if res.get("ok") is False:
                detail = self._cn(str(res.get("runtime_error") or res.get("error") or ""))
                text = f"修复未完成：{detail or '运行时组件不完整，请重新解压完整安装包'}"
                self.error_banner.show_error(text)
                notify.error(text)
                self.refresh()
                return
            notify.success("运行时/游戏内组件修复完成。")
            self.refresh()

        def fail(msg: str) -> None:
            text = f"修复失败：{self._cn(msg)}"
            self._log(text)
            self.loading_overlay.stop()
            self.error_banner.show_error(text)
            notify.error(text)

        run_worker(self.svc.agent_install_deps, done, fail)

    # ---------------------------------------------------------------- 读取

    def _read(self, cmd: str) -> None:
        label = _READ_LABELS.get(cmd, cmd)
        self._log(f"读取{label}…")
        self.telemetry.setText("读取中…")
        notify.toast(f"正在读取{label}…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            if cmd == "player":
                loc = res.get("location") or {}
                self.telemetry.setText(
                    f"银河地址 {res.get('ua') or '—'}  ·  行星 {loc.get('planet', '—')}  ·  "
                    f"星系 {loc.get('system', '—')}  ·  {res.get('system_name') or ''}")
            elif cmd == "system":
                self.telemetry.setText(
                    f"{res.get('system_name') or '当前星系'}  ·  "
                    f"{len(res.get('planets') or [])} 颗行星")
            elif cmd == "planet":
                p = res.get("planet") or {}
                self.telemetry.setText(
                    f"{p.get('name') or p.get('planet_type') or '行星'}  ·  "
                    f"{p.get('weather') or ''}  ·  {p.get('resources') or ''}")
            elif cmd == "ships":
                self.telemetry.setText(f"游戏内船槽：{len(res.get('ships') or [])} 艘")
            self.error_banner.clear()
            notify.success(f"{label}已更新。")

        def fail(msg: str) -> None:
            text = f"读取失败：{self._cn(msg)}"
            self.telemetry.setText(text)
            self._log(text)
            self.error_banner.show_error(text)
            notify.error(text)

        run_worker(self.svc.agent_call, done, fail, cmd)

    @staticmethod
    def _join(value) -> str:
        if value is None or value == "":
            return MISSING
        if isinstance(value, (list, tuple, set)):
            items = [str(x).strip() for x in value if str(x).strip()]
            return "、".join(items) if items else MISSING
        return str(value).strip() or MISSING

    def _format_planet(self, data: dict) -> str:
        return format_planet_text(data or {})

    def _planet_unavailable(self, res: dict) -> str:
        code = str(res.get("code") or "")
        err = self._cn(str(res.get("error") or res.get("reason") or "")).strip()
        low = err.lower()
        if code == "E_AGENT" or "连不上" in err or "响应超时" in err:
            return "行星档案不可用：未连接游戏内代理；请先点「连接游戏」并确认游戏已注入。"
        if ("还没进入存档" in err or "未进入存档" in err
                or "玩家状态不可用" in err or "player_state" in low):
            return "行星档案不可用：游戏尚未进入存档；请先载入存档后重试。"
        if "当前星系不可用" in err:
            return "行星档案不可用：当前星系不可用；请先载入存档并进入星系。"
        if err and any(x in err for x in ("未知", "未实现", "不支持", "unknown",
                                          "not implemented")):
            return "行星档案不可用：当前游戏内代理未实现行星档案读取（planet.scan）。"
        if err:
            return f"行星档案不可用：{err}"
        return "行星档案不可用：当前游戏内代理没有返回有效数据。"

    def _planet_scan(self) -> None:
        if self._cap_state_known:
            reason = self._read_block_reason("planet.scan")
            if reason:
                text = f"行星档案不可用：{reason}"
                self.planet_result.set_message(text)
                self._log(text)
                self.error_banner.show_error(text)
                notify.warn(text)
                return
        self.planet_result.set_message("正在读取当前行星档案…")
        self._log("读取行星档案…")
        self.loading_overlay.start("正在读取当前行星档案…")
        notify.toast("正在读取当前行星档案…")

        def done(res) -> None:
            res = res if isinstance(res, dict) else {"ok": False, "error": str(res)}
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            if not res.get("ok", False):
                text = self._planet_unavailable(res)
                self.planet_result.set_message(text)
                self._log(text)
                self.loading_overlay.stop()
                self.error_banner.show_error(text)
                notify.warn(text)
                return
            data = res.get("planet") or {}
            if not data and isinstance(res.get("result"), dict):
                data = res["result"].get("planet") or res["result"]
            if not data and isinstance(res.get("data"), dict):
                data = res["data"].get("planet") or res["data"]
            if not data:
                text = "行星档案不可用：当前游戏内代理没有返回有效数据。"
                self.planet_result.set_message(text)
                self._log(text)
                self.loading_overlay.stop()
                self.error_banner.show_error(text)
                notify.warn(text)
                return
            self.planet_result.set_planet(data)
            self._log("行星档案已更新。")
            self.loading_overlay.stop()
            self.error_banner.clear()
            notify.success("行星档案已更新。")

        def fail(msg: str) -> None:
            text = f"行星档案不可用：{self._cn(msg)}"
            self.planet_result.set_message(text)
            self._log(text)
            self.loading_overlay.stop()
            self.error_banner.show_error(text)
            notify.error(text)

        run_worker(self.svc.agent_call, done, fail, "planet.scan")

    def _refresh_planet(self) -> None:
        self._planet_scan()

    def _copy_planet(self) -> None:
        if not self.planet_result.has_data():
            self._log("没有可复制的行星档案；请先读取档案。")
            notify.warn("没有可复制的行星档案；请先读取档案。")
            return
        text = self.planet_result.toPlainText().strip()
        if not text:
            self._log("没有可复制的行星档案；请先读取档案。")
            notify.warn("没有可复制的行星档案；请先读取档案。")
            return
        QGuiApplication.clipboard().setText(text)
        self._log("行星档案已复制。")
        notify.success("行星档案已复制。")

    def _read_planet(self) -> None:
        self._planet_scan()

    def _install_template_mod(self) -> None:
        answer = QMessageBox.question(
            self, "安装模板 Mod",
            "将把 starforge-templates 写入游戏目录的 GAMEDATA/MODS/。\n"
            "不会修改游戏原始文件；删除该文件夹即可卸载。\n\n继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.install_mod_btn.setEnabled(False)
        self.mod_status.setText("正在安装…")

        def done(res: dict) -> None:
            self.install_mod_btn.setEnabled(True)
            if not res.get("ok", True):
                text = f"安装失败：{res.get('error') or res.get('code') or '未知错误'}"
                self.mod_status.setText(text)
                notify.error(text)
                return
            files = len(res.get("files") or [])
            self.mod_status.setText(
                f"已安装 {files} 个文件到 {res.get('path')}；重启游戏后生效")
            notify.success("模板 Mod 已安装，重启游戏后表情菜单可见")

        def fail(msg: str) -> None:
            self.install_mod_btn.setEnabled(True)
            self.mod_status.setText(f"安装失败：{msg}")
            notify.error(f"安装失败：{msg}")

        run_worker(self.svc.install_template_mod, done, fail, confirm=True)

    def _open_mods_dir(self) -> None:
        from ... import locate_game
        from ...core import settings

        game = locate_game.normalize(settings.current().game_dir or "")
        if not game:
            notify.warn("还没有配置游戏目录（设置页选择游戏根目录）")
            return
        path = os.path.join(game, "GAMEDATA", "MODS")
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _scan_poi(self, kind: str = "portal", label: str = "") -> None:
        label = label or {"portal": "传送门", "ruins": "古遗迹",
                          "freighter": "货船", "ship": "飞船"}.get(kind, "兴趣点")
        if self._cap_state_known:
            reason = self._read_block_reason("scan.poi").rstrip("。；; ")
            if reason:
                detail = f"{reason}；需要游戏内代理实机校准"
                self.poi_result.set_unavailable(label, detail)
                text = f"附近{label}暂不可用：{detail}。"
                self._log(text)
                self.error_banner.show_error(text)
                notify.warn(text)
                return
        self.poi_result.set_message(f"正在扫描附近{label}…")
        self._log(f"扫描附近{label}…")
        self.loading_overlay.start(f"正在扫描附近{label}…")
        notify.toast(f"正在扫描附近{label}…")

        def done(res) -> None:
            res = res if isinstance(res, dict) else {"ok": False, "error": str(res)}
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            if not res.get("ok", False):
                reason = self._poi_unavailable(res)
                self.poi_result.set_unavailable(label, reason)
                text = f"附近{label}暂不可用：{reason}"
                self._log(text)
                self.loading_overlay.stop()
                self.error_banner.show_error(text)
                notify.warn(text)
                return
            rows = (res.get("results") or res.get("pois") or res.get("items")
                    or res.get("poi") or [])
            if isinstance(rows, dict):
                rows = [rows]
            if not rows:
                reason = "兴趣点扫描（scan.poi）没有返回结果；需要游戏内代理实机校准"
                self.poi_result.set_unavailable(label, reason)
                text = f"附近{label}暂不可用：{reason}。"
                self._log(text)
                self.loading_overlay.stop()
                self.error_banner.show_error(text)
                notify.warn(text)
                return
            self.poi_result.set_pois(label, list(rows))
            self._log(f"附近{label}已更新。")
            self.loading_overlay.stop()
            self.error_banner.clear()
            notify.success(f"附近{label}已更新。")

        def fail(msg: str) -> None:
            reason = f"{self._cn(msg)}；需要游戏内代理实机校准"
            self.poi_result.set_unavailable(label, reason)
            text = f"附近{label}暂不可用：{reason}"
            self._log(text)
            self.loading_overlay.stop()
            self.error_banner.show_error(text)
            notify.error(text)

        run_worker(self.svc.agent_call, done, fail, "scan.poi", kind=kind)

    def _poi_unavailable(self, res: dict) -> str:
        code = str(res.get("code") or "")
        err = self._cn(str(res.get("error") or res.get("reason") or "")).strip()
        low = err.lower()
        if code == "E_AGENT" or "连不上" in err or "响应超时" in err:
            return "未连接游戏内代理；需要游戏内代理实机校准"
        if ("还没进入存档" in err or "未进入存档" in err
                or "玩家状态不可用" in err or "player_state" in low):
            return "游戏尚未进入存档；需要游戏内代理实机校准"
        if err and any(x in err for x in ("未知", "未实现", "不支持", "unknown",
                                          "not implemented")):
            return "兴趣点扫描（scan.poi）尚未实现；需要游戏内代理实机校准，暂不提供结果"
        if err:
            return f"{err}；需要游戏内代理实机校准"
        return "需要游戏内代理实机校准，暂不提供结果"

    # ---------------------------------------------------------------- 写

    def _call(self, cmd: str, **params) -> None:
        label = _CALL_LABELS.get(cmd, cmd)
        self._log(f"{label}…")
        notify.toast(f"正在{label}…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            if isinstance(res, dict) and res.get("ok") is False:
                text = f"{label}失败：{self._cn(str(res.get('error') or res.get('reason') or ''))}"
                self.error_banner.show_error(text)
                notify.error(text)
                return
            self.error_banner.clear()
            notify.success(f"{label}完成。")

        def fail(msg: str) -> None:
            text = f"{label}失败：{self._cn(msg)}"
            self._log(text)
            self.error_banner.show_error(text)
            notify.error(text)

        run_worker(self.svc.agent_call, done, fail, cmd, **params)

    def _teleport(self) -> None:
        glyphs = self.glyphs.text().strip().upper()
        if not glyphs:
            notify.warn("先填 12 位符文地址。")
            return
        mode = self.teleport_mode.currentData()
        portal = mode == "teleport.portal"
        if portal and not self._portal_available:
            notify.warn(self._portal_reason)
            return
        if not self._build_verified or self._multiplayer:
            reason = ("多人模式已启用：高风险写操作被禁用" if self._multiplayer
                      else "这版未验证：高风险写操作被禁用")
            notify.warn(reason)
            return
        galaxy = int(self.galaxy.value()) if self.galaxy_mode.currentData() == "custom" else None
        way = "传送门效果" if portal else "普通写位置"
        if not ask_write(self, "确认传送",
                f"将尝试以{way}把玩家位置写成 {glyphs}"
                f"（星系：{galaxy if galaxy is not None else '当前'}）。\n"
                "只支持单人模式。请确认已备份存档。继续？",):
            notify.toast("已取消传送。")
            return
        notify.toast(f"正在以{way}传送…")
        if portal:
            self._call("teleport.portal", glyphs=glyphs, galaxy=galaxy)
        else:
            self._call("teleport", glyphs=glyphs, galaxy=galaxy)
