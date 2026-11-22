"""设置与诊断：按「路径 / 安全 / 运行时 / 诊断」分组，默认折叠。"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core import paths
from ...services import get_services
from .. import notify
from ..dialogs.confirm import ask_write
from ..widgets.feedback import EmptyState, ErrorBanner, LoadingOverlay
from ..widgets.page import PAGE_MARGINS, PAGE_SPACING, reveal_widget
from ..widgets.page_header import PageHeader
from ..widgets.settings_flow import FoldSection
from ..widgets.ui import Card, elide_label, muted
from ..widgets.worker import run as run_worker


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_KIND_LABELS = {
    "player": "玩家存档",
    "account": "账号数据",
    "manifest": "清单文件",
    "unknown": "无法识别",
}


def _human_size(value: object) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "—"
    if size < 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "—"


def _risk_tag(text: str, state: str = "warn") -> QLabel:
    """只读/写/安装风险标识，沿用主题里的 chip 样式。"""
    lab = QLabel(text)
    lab.setObjectName("chip")
    lab.setProperty("state", state)
    lab.setToolTip(f"风险标识：{text}")
    return lab


def _path_row(edit: QLineEdit, title: str = "选择目录") -> QWidget:
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    h.addWidget(edit, 1)
    btn = QPushButton("浏览…")

    def pick() -> None:
        p = QFileDialog.getExistingDirectory(box, title, edit.text())
        if p:
            edit.setText(p)

    btn.clicked.connect(pick)
    h.addWidget(btn)
    return box


_GATING_ALIASES = ("allow_unverified_agent", "allow_unverified_writes",
                   "allow_unverified_build_writes", "agent_allow_unverified_writes",
                   "allow_unverified_build", "experimental_writes")


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._loaded = False
        self._syncing = False
        self._env_loaded = False
        self._saves_files: list[dict] = []
        self._saves_default = ""
        self._saves_dir = ""
        self._health: dict = {}
        self._resolved_paths: dict = {}
        self._saves_explicit = False
        self._unverified_key: str | None = None
        self._build_ui()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(*PAGE_MARGINS)
        root.setSpacing(PAGE_SPACING)

        self.header = PageHeader(
            "设置与诊断",
            "按问题分组：路径、安全、运行时、诊断；先跑一次体检，再展开要改的那一组。")
        root.addWidget(self.header)
        self.error_banner = ErrorBanner("")
        self.error_banner.set_retry_callback(self._load)
        root.addWidget(self.error_banner)

        # ------------------------------------------------------------ 运行体检
        health = Card("运行体检", "一次检查路径、依赖、存档与写入；只读，不改任何设置。")
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.chip_game = QLabel("游戏目录 —")
        self.chip_saves = QLabel("存档目录 —")
        self.chip_data = QLabel("数据 —")
        self.chip_write = QLabel("写入 —")
        self.chip_agent = QLabel("游戏内代理 —")
        for chip in (self.chip_game, self.chip_saves, self.chip_data,
                     self.chip_write, self.chip_agent):
            chip.setObjectName("chip")
            chip.setSizePolicy(chip.sizePolicy().horizontalPolicy(),
                               chip.sizePolicy().verticalPolicy())
            chips.addWidget(chip)
        chips.addStretch(1)
        health.add_layout(chips)
        self.health_summary = muted("尚未运行体检；点「运行体检」开始。")
        health.add(self.health_summary)
        health_actions = QHBoxLayout()
        health_actions.setSpacing(6)
        self.run_health_btn = QPushButton("运行体检")
        self.run_health_btn.setObjectName("primary")
        self.run_health_btn.setToolTip("检查 Python 依赖、游戏/存档/数据目录与写入开关；只读")
        self.run_health_btn.clicked.connect(self._doctor)
        health_actions.addWidget(self.run_health_btn)
        self.health_detail_btn = QPushButton("查看诊断详情")
        self.health_detail_btn.setObjectName("ghostButton")
        self.health_detail_btn.setToolTip("展开「诊断」分组，查看体检原文与自检结果")
        self.health_detail_btn.clicked.connect(self._open_diagnostics)
        health_actions.addWidget(self.health_detail_btn)
        health_actions.addStretch(1)
        health.add_layout(health_actions)
        root.addWidget(health)

        # ------------------------------------------------------------ 路径
        self.paths_group = FoldSection(
            "路径与自动检测",
            "路径 · 游戏 / 存档 / 数据目录；自动检测优先，找不到再手动选择。",
            summary="游戏、存档与数据目录；自动检测只读，保存才会写设置。")
        path_tags = QHBoxLayout()
        path_tags.setSpacing(6)
        path_tags.addWidget(_risk_tag("自动检测=只读", "ok"))
        path_tags.addWidget(_risk_tag("保存=写设置", "warn"))
        path_tags.addStretch(1)
        self.paths_group.add_body_layout(path_tags)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.game = QLineEdit()
        self.game.setPlaceholderText("游戏根目录（含 Binaries/NMS.exe）")
        self.game.setToolTip("例如 D:\\SteamLibrary\\steamapps\\common\\No Man's Sky")
        form.addRow("游戏目录", _path_row(self.game, "选择游戏根目录"))
        self.saves = QLineEdit()
        self.saves.setPlaceholderText("存档目录（含 save.hg）")
        self.saves.setToolTip("例如 %APPDATA%\\HelloGames\\NMS")
        form.addRow("存档目录", _path_row(self.saves, "选择存档目录"))
        self.gamedata = QLineEdit()
        self.gamedata.setPlaceholderText("数据目录（含 Gagarin/ships/catalog.txt；留空=自动）")
        self.gamedata.setToolTip(
            "可选：Gagarin 数据目录。留空时依次尝试游戏目录/GAMEDATA 与环境变量 STARFORGE_GAMEDATA。")
        form.addRow("数据目录", _path_row(self.gamedata, "选择数据目录"))
        self.game.textChanged.connect(self._update_path_empty)
        self.saves.textChanged.connect(self._update_path_empty)
        self.game.textChanged.connect(self._sync_paths_summary)
        self.saves.textChanged.connect(self._sync_paths_summary)
        self.gamedata.textChanged.connect(self._sync_paths_summary)
        path_actions = QHBoxLayout()
        path_actions.setSpacing(6)
        self.autodetect_btn = QPushButton("自动检测")
        self.autodetect_btn.setToolTip("自动查找游戏、存档与数据目录；只读，不改设置")
        self.autodetect_btn.clicked.connect(self._autodetect)
        path_actions.addWidget(self.autodetect_btn)
        self.save_btn = QPushButton("保存路径（写设置）")
        self.save_btn.setToolTip("把三个路径写入本机设置；不修改任何存档或游戏文件")
        self.save_btn.clicked.connect(self._save)
        path_actions.addWidget(self.save_btn)
        path_actions.addStretch(1)
        form.addRow("", path_actions)
        self.paths_group.add_body_layout(form)

        self.resolved_summary = elide_label(
            "游戏：未设置 · 存档：未设置 · 数据：自动检测")
        self.resolved_summary.setObjectName("muted")
        self.paths_group.add_body(self.resolved_summary)

        self.path_empty = EmptyState(
            "尚未设置游戏与存档目录",
            "点「自动检测」尝试查找，或手动选择目录；未设置时无法读取存档或连接游戏。",
            icon="⌂",
            button_text="自动检测")
        self.path_empty.setMaximumHeight(168)
        self.path_empty.actionTriggered.connect(self._autodetect)
        self.paths_group.add_body(self.path_empty)

        saves_row = QHBoxLayout()
        saves_row.setSpacing(6)
        saves_row.addWidget(_risk_tag("扫描=只读", "ok"))
        saves_row.addWidget(_risk_tag("切换=写设置", "warn"))
        saves_row.addStretch(1)
        self.paths_group.add_body_layout(saves_row)
        self.saves_summary = elide_label("尚未扫描存档目录。")
        self.saves_summary.setObjectName("muted")
        self.paths_group.add_body(self.saves_summary)

        self.saves_table = QTableWidget(0, 5)
        self.saves_table.setObjectName("settingsSavesTable")
        self.saves_table.setHorizontalHeaderLabels(["文件", "类型", "大小", "船数", "可读性"])
        self.saves_table.verticalHeader().setVisible(False)
        self.saves_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.saves_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.saves_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.saves_table.setAlternatingRowColors(True)
        self.saves_table.setMinimumHeight(200)
        self.saves_table.setMaximumHeight(240)
        header = self.saves_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.saves_table.itemSelectionChanged.connect(self._saves_selection_changed)
        self.saves_table.itemDoubleClicked.connect(lambda *_: self._use_saves_dir())

        detail_box = QWidget()
        detail = QVBoxLayout(detail_box)
        detail.setContentsMargins(8, 0, 0, 0)
        detail.setSpacing(6)
        detail.addWidget(muted("选中一行查看完整路径与可执行提示"))
        self.save_detail = QLabel("尚未扫描存档目录。")
        self.save_detail.setWordWrap(True)
        self.save_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.save_detail.setMinimumWidth(240)
        detail.addWidget(self.save_detail, 1, Qt.AlignTop)
        saves_split = QSplitter(Qt.Horizontal)
        saves_split.setObjectName("settingsSavesSplitter")
        saves_split.setChildrenCollapsible(False)
        saves_split.setMinimumHeight(210)
        saves_split.addWidget(self.saves_table)
        saves_split.addWidget(detail_box)
        saves_split.setStretchFactor(0, 3)
        saves_split.setStretchFactor(1, 2)
        saves_split.setSizes([560, 340])
        self.paths_group.add_body(saves_split)

        saves_btns = QHBoxLayout()
        saves_btns.setSpacing(6)
        self.saves_refresh_btn = QPushButton("刷新列表（只读）")
        self.saves_refresh_btn.setToolTip("重新扫描存档目录；只读取文件头，不写任何文件")
        self.saves_refresh_btn.clicked.connect(self._load_saves)
        saves_btns.addWidget(self.saves_refresh_btn)
        self.saves_use_btn = QPushButton("设为当前存档目录（写设置）")
        self.saves_use_btn.setToolTip(
            "把选中存档所在目录写入设置；不会修改存档。"
            "回到「我的 → 船队」点「读取存档」后按该目录的 save.hg / save2.hg 读取")
        self.saves_use_btn.setEnabled(False)
        self.saves_use_btn.clicked.connect(self._use_saves_dir)
        saves_btns.addWidget(self.saves_use_btn)
        self.saves_open_btn = QPushButton("打开目录（只读）")
        self.saves_open_btn.setToolTip("在资源管理器中打开当前存档目录")
        self.saves_open_btn.clicked.connect(self._open_saves_dir)
        saves_btns.addWidget(self.saves_open_btn)
        saves_btns.addStretch(1)
        self.paths_group.add_body_layout(saves_btns)
        self.paths_group.add_body(muted(
            "切换只决定「我的 → 船队」重新读取时扫描哪个目录；"
            "要精确使用 save3.hg 这类文件，请到船队页点「浏览…」选择。"))
        root.addWidget(self.paths_group)

        # ------------------------------------------------------------ 安全
        self.safety_group = FoldSection(
            "安全与性能",
            "安全 · 写入默认关闭；修改后立即保存。",
            summary="写入开关、二次确认、实验写、多人提示与性能选项。")
        sv = self.safety_group.body_layout
        self.write = QCheckBox("允许写入存档")
        self.write.setObjectName("settingsWriteEnabled")
        self.write.toggled.connect(self._save)
        self.safety_group.add_body(self.write)
        self.confirm_writes = QCheckBox("写入前二次确认")
        self.confirm_writes.setObjectName("settingsConfirmWrites")
        self.confirm_writes.toggled.connect(self._save)
        self.safety_group.add_body(self.confirm_writes)
        self.allow_unverified = QCheckBox("允许未验证游戏版本实验写操作")
        self.allow_unverified.setAccessibleName("允许未验证游戏版本实验写操作")
        self.allow_unverified.toggled.connect(self._save_gating)
        self.safety_group.add_body(self.allow_unverified)
        self.gating_note = muted("读取安全设置中…")
        self.safety_group.add_body(self.gating_note)
        mp_note = QLabel("多人模式：传送 / 还原 / 扫描写会自动禁用；请退到单人模式再操作。")
        mp_note.setObjectName("chip")
        mp_note.setProperty("state", "warn")
        mp_note.setWordWrap(True)
        sv.addWidget(mp_note)
        perf = QFormLayout()
        perf.setHorizontalSpacing(12)
        perf.setVerticalSpacing(8)
        self.backup_keep = QSpinBox()
        self.backup_keep.setObjectName("settingsBackupKeep")
        self.backup_keep.setRange(0, 9999)
        self.backup_keep.setSpecialValueText("0（永不删除）")
        self.backup_keep.setToolTip("每次写入生成的备份最多保留多少份；0 表示永不自动删除")
        self.backup_keep.valueChanged.connect(self._save)
        perf.addRow("备份保留数", self.backup_keep)
        self.workers = QSpinBox()
        self.workers.setObjectName("settingsWorkers")
        self.workers.setRange(0, 64)
        self.workers.setSpecialValueText("0（自动）")
        self.workers.setToolTip("搜索/扫描的工作线程数；0 由程序自动选择")
        self.workers.valueChanged.connect(self._save)
        perf.addRow("搜索线程数", self.workers)
        self.safety_group.add_body_layout(perf)
        self.safety_group.add_body(muted("写入流程：备份 → 原子写入 → 读回校验 → 失败回滚。"))
        root.addWidget(self.safety_group)

        # ------------------------------------------------------------ 运行时
        self.runtime_group = FoldSection(
            "版本与代理",
            "运行时 · 游戏内组件状态与安装 / 修复 / 卸载；不写存档。",
            summary="build 指纹、NMSpy / pymhf 组件与代理文件。")
        rt_tags = QHBoxLayout()
        rt_tags.setSpacing(6)
        rt_tags.addWidget(_risk_tag("查看=只读", "ok"))
        rt_tags.addWidget(_risk_tag("安装=写本机文件", "warn"))
        rt_tags.addWidget(_risk_tag("卸载=删除代理文件", "warn"))
        rt_tags.addStretch(1)
        self.runtime_group.add_body_layout(rt_tags)
        self.build_label = QLabel("游戏 build：展开本组后检查…")
        self.build_label.setObjectName("settingsBuildStatus")
        self.build_label.setWordWrap(True)
        self.runtime_group.add_body(self.build_label)
        self.agent_label = QLabel("游戏内代理：展开本组后检查…")
        self.agent_label.setObjectName("settingsAgentStatus")
        self.agent_label.setWordWrap(True)
        self.runtime_group.add_body(self.agent_label)
        self.runtime_label = elide_label("运行时：展开本组后检查…")
        self.runtime_label.setObjectName("settingsRuntimeStatus")
        self.runtime_group.add_body(self.runtime_label)
        self.agent_file_label = elide_label("代理文件：展开本组后检查…")
        self.agent_file_label.setObjectName("settingsAgentFileStatus")
        self.runtime_group.add_body(self.agent_file_label)

        rt_grid = QGridLayout()
        rt_grid.setHorizontalSpacing(6)
        rt_grid.setVerticalSpacing(6)
        self.bootstrap_btn = QPushButton("准备运行时")
        self.bootstrap_btn.setToolTip(
            "安装/解压 Python 运行时到 ~/.starforge/agent/runtime；缺失时才联网")
        self.bootstrap_btn.clicked.connect(self._prepare_runtime)
        rt_grid.addWidget(self.bootstrap_btn, 0, 0)
        self.repair_btn = QPushButton("安装 / 修复组件")
        self.repair_btn.setToolTip(
            "安装或更新 NMSpy + pymhf 到运行时；不写存档。缺运行时时先点「准备运行时」")
        self.repair_btn.clicked.connect(self._repair)
        rt_grid.addWidget(self.repair_btn, 0, 1)
        self.install_agent_btn = QPushButton("重写代理文件（安装）")
        self.install_agent_btn.setToolTip(
            "把当前版本的 starforge_agent.py 写入 ~/.starforge/agent；不碰存档")
        self.install_agent_btn.clicked.connect(self._install_agent_file)
        rt_grid.addWidget(self.install_agent_btn, 1, 0)
        self.uninstall_agent_btn = QPushButton("卸载组件（卸载）")
        self.uninstall_agent_btn.setToolTip(
            "删除 ~/.starforge/agent/starforge_agent.py；不动运行时、存档或游戏目录")
        self.uninstall_agent_btn.clicked.connect(self._uninstall_agent_file)
        rt_grid.addWidget(self.uninstall_agent_btn, 1, 1)
        rt_grid.setColumnStretch(0, 1)
        rt_grid.setColumnStretch(1, 1)
        self.runtime_group.add_body_layout(rt_grid)
        self.runtime_note = muted(
            "正常安装包已内置运行时；「准备运行时」只在缺失/损坏时使用。")
        self.runtime_group.add_body(self.runtime_note)

        env_row = QHBoxLayout()
        env_row.setSpacing(6)
        self.env_refresh_btn = QPushButton("刷新状态")
        self.env_refresh_btn.clicked.connect(self._refresh_env)
        env_row.addWidget(self.env_refresh_btn)
        copy_logs = QPushButton("复制最近日志")
        copy_logs.setToolTip("复制 starforge.log / launcher.log 的尾部内容（只读，已脱敏）")
        copy_logs.clicked.connect(self._copy_recent_logs)
        env_row.addWidget(copy_logs)
        launcher = QPushButton("查看 launcher.log 摘要")
        launcher.setToolTip("在「诊断」里显示 launcher.log 的最近内容（只读）")
        launcher.clicked.connect(self._show_launcher)
        env_row.addWidget(launcher)
        env_row.addStretch(1)
        self.runtime_group.add_body_layout(env_row)
        self.runtime_group.toggled.connect(self._on_runtime_toggled)
        root.addWidget(self.runtime_group)

        # ------------------------------------------------------------ 诊断
        self.diag_group = FoldSection(
            "诊断",
            "诊断 · 体检原文、自检与诊断包；只读，不执行写入步骤。",
            summary="体检原文、自检结果与诊断包。")
        diag_row = QHBoxLayout()
        diag_row.setSpacing(6)
        diag_row.addWidget(_risk_tag("只读", "ok"))
        self.doctor_btn = QPushButton("运行体检")
        self.doctor_btn.clicked.connect(self._doctor)
        diag_row.addWidget(self.doctor_btn)
        self.selfcheck_btn = QPushButton("运行自检（只读）")
        self.selfcheck_btn.setToolTip(
            "运行 Services.diagnostics（selfcheck，include_write=False）；不写存档")
        self.selfcheck_btn.clicked.connect(self._selfcheck)
        diag_row.addWidget(self.selfcheck_btn)
        export = QPushButton("导出诊断包")
        export.setToolTip("导出 ZIP：health / doctor / selfcheck / build / agent / 脱敏设置 / 日志")
        export.clicked.connect(self._export_diag)
        diag_row.addWidget(export)
        logs = QPushButton("打开日志目录")
        logs.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(paths.app_home() / "logs"))))
        diag_row.addWidget(logs)
        diag_row.addStretch(1)
        self.diag_group.add_body_layout(diag_row)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setMinimumHeight(220)
        self.out.setMaximumHeight(320)
        self.out.setPlaceholderText("体检结果会以结构化文本显示在这里。")
        self.diag_group.add_body(self.out)
        self.doctor_output = self.out

        self.selfcheck_summary = muted("尚未运行自检。")
        self.diag_group.add_body(self.selfcheck_summary)
        self.selfcheck_table = QTableWidget(0, 4)
        self.selfcheck_table.setObjectName("settingsSelfcheckTable")
        self.selfcheck_table.setHorizontalHeaderLabels(["状态", "步骤", "耗时", "详情"])
        self.selfcheck_table.verticalHeader().setVisible(False)
        self.selfcheck_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.selfcheck_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.selfcheck_table.setAlternatingRowColors(True)
        self.selfcheck_table.setMinimumHeight(140)
        self.selfcheck_table.setMaximumHeight(240)
        sc_header = self.selfcheck_table.horizontalHeader()
        sc_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        sc_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        sc_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        sc_header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.diag_group.add_body(self.selfcheck_table)
        self.selfcheck_hint = muted("")
        self.diag_group.add_body(self.selfcheck_hint)
        self.selfcheck_table.hide()
        self.selfcheck_hint.hide()
        root.addWidget(self.diag_group)

        about = Card("关于")
        about.add(QLabel(f"starforge {__import__('starforge').__version__} · 原生界面（Qt）"))
        about.add(muted("只监听本机；不联网；默认只读；游戏内代理默认不安装。"))
        root.addWidget(about)
        root.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self._syncing = False
        self.loading_overlay = LoadingOverlay(self, "正在处理…")
        self.loading = self.loading_overlay
        self._update_path_empty()
        self._sync_paths_summary()

    # ---------------------------------------------------------------- 数据

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._load()
        self._load_gating()

    def _load(self) -> None:
        def done(res: dict) -> None:
            s = res.get("settings") or {}
            r = res.get("resolved") or {}
            self._syncing = True
            try:
                # 输入框只显示“已保存的设置”；留空表示自动检测。
                # 解析出的默认路径放在摘要/tooltip 里，避免误写回设置。
                self._resolved_paths = dict(r)
                self._saves_explicit = bool(str(s.get("saves_dir") or "").strip())
                self.game.setText(str(s.get("game_dir") or ""))
                self.saves.setText(str(s.get("saves_dir") or ""))
                self.gamedata.setText(str(s.get("gamedata_dir") or ""))
                self.write.setChecked(bool(s.get("write_enabled")))
                self.confirm_writes.setChecked(bool(s.get("confirm_writes", True)))
                self.backup_keep.setValue(_coerce_int(s.get("backup_keep"), 0))
                self.workers.setValue(_coerce_int(s.get("workers"), 0))
            finally:
                self._syncing = False
            self._update_path_empty()
            self._sync_paths_summary(r)
            self.error_banner.clear()
            self._refresh_health()
            self._load_saves()

        def fail(msg: str) -> None:
            text = f"读取设置失败：{msg}"
            self._log(text)
            self.error_banner.show_error(text)
            self.paths_group.set_chip("读取失败", "bad")
            self.paths_group.set_summary(
                "下一步：检查本机设置文件是否可读，或点「自动检测」重新定位。")
            notify.error(text)

        run_worker(self.svc.settings_snapshot, done, fail)

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
                self.gating_note.setText(
                    "当前版本没有「允许未验证游戏版本实验写操作」设置，暂不可用。")
            else:
                self.allow_unverified.setChecked(bool(settings.get(key)))
                self.allow_unverified.setEnabled(True)
                self.allow_unverified.setToolTip(
                    "由游戏版本闸门控制；未验证版本仍可能拒绝实验写操作。")
                self.gating_note.setText(
                    "实验写仍受游戏版本闸门约束；关闭后立即生效。")
            self.allow_unverified.blockSignals(False)

        def fail(msg: str) -> None:
            self._unverified_key = None
            self.allow_unverified.blockSignals(True)
            self.allow_unverified.setChecked(False)
            self.allow_unverified.blockSignals(False)
            self.allow_unverified.setEnabled(False)
            self.allow_unverified.setToolTip("读取安全设置失败，暂不可用。")
            self.gating_note.setText(
                f"读取安全设置失败：{msg}；此选项暂不可用。")

        run_worker(self.svc.settings_snapshot, done, fail)

    def _save_gating(self, on: bool) -> None:
        if self._syncing:
            return
        if not self._unverified_key:
            self.gating_note.setText("当前版本没有对应的安全设置，此选项不可用。")
            notify.warn("当前版本没有对应的安全设置，此选项不可用。")
            return
        try:
            self.svc.update_settings(**{self._unverified_key: bool(on)})
        except Exception as e:                              # noqa: BLE001
            text = f"保存安全设置失败：{type(e).__name__}: {e}"
            self.gating_note.setText(text)
            self.error_banner.show_error(text)
            notify.error(text)
            return
        self.gating_note.setText("安全设置已保存；实验写操作仍受游戏版本闸门约束。"
                                 if on else "安全设置已保存；实验写操作已关闭。")
        notify.success("安全设置已保存。")

    def _update_path_empty(self) -> None:
        if not hasattr(self, "path_empty"):
            return
        has_game = bool(self.game.text().strip())
        has_saves = bool(self.saves.text().strip())
        if has_game or has_saves:
            self.path_empty.hide()
            return
        self.path_empty.title_label.setText("尚未设置游戏与存档目录")
        self.path_empty.description_label.setText(
            "点「自动检测」尝试查找，或手动选择目录；未设置时无法读取存档或连接游戏。")
        self.path_empty.description_label.setVisible(True)
        self.path_empty.show()

    def _sync_paths_summary(self, resolved: dict | None = None) -> None:
        resolved = resolved if isinstance(resolved, dict) else {}
        game = self.game.text().strip() or str(resolved.get("game_dir") or "")
        saves = self.saves.text().strip() or str(resolved.get("saves_dir") or "")
        data = self.gamedata.text().strip() or str(resolved.get("gamedata_dir") or "")
        parts = [f"游戏：{game or '未设置'}",
                 f"存档：{saves or '未设置'}",
                 f"数据：{data or '自动检测'}"]
        self.resolved_summary.setText(" · ".join(parts))
        self.resolved_summary.setToolTip("\n".join(parts))
        paths_ok = bool(game) and bool(saves)
        self.paths_group.set_chip("已定位" if paths_ok else "需设置",
                                  "ok" if paths_ok else "warn")
        # 顶部体检 chip 已经显示“已设置/未设置”，这里不再重复；
        # 折叠摘要只保留扫描结果的动态信息（由 _saves_done 写入）。
        self.paths_group.set_summary("")

    def _save(self, *_args) -> None:
        if self._syncing:
            return
        try:
            self.svc.update_settings(
                game_dir=self.game.text().strip(),
                saves_dir=self.saves.text().strip(),
                gamedata_dir=self.gamedata.text().strip(),
                write_enabled=self.write.isChecked(),
                confirm_writes=self.confirm_writes.isChecked(),
                backup_keep=int(self.backup_keep.value()),
                workers=int(self.workers.value()))
            self._update_path_empty()
            self._sync_paths_summary()
            self._refresh_health()
            self.error_banner.clear()
            self._log("设置已保存")
            notify.success("设置已保存。")
        except Exception as e:                              # noqa: BLE001
            text = f"保存失败：{type(e).__name__}: {e}"
            self._log(text)
            self.error_banner.show_error(text)
            notify.error(text)

    # ------------------------------------------------------------ 健康/体检

    def _refresh_health(self) -> None:
        run_worker(self.svc.health, self._health_done, self._health_failed)

    def _set_chip(self, chip: QLabel, text: str, state: str) -> None:
        chip.setText(text)
        if state in ("ok", "warn", "bad"):
            chip.setProperty("state", state)
        else:
            chip.setProperty("state", "")
        chip.setToolTip(text)
        style = chip.style()
        if style is not None:
            style.unpolish(chip)
            style.polish(chip)

    def _health_done(self, res: dict) -> None:
        h = res if isinstance(res, dict) else {}
        self._health = h
        self._apply_health_chips(h)
        self.health_summary.setText(self._health_advice(h))
        self.health_summary.setToolTip(self.health_summary.text())

    def _health_failed(self, msg: str) -> None:
        self._set_chip(self.chip_game, "游戏目录 —", "warn")
        self._set_chip(self.chip_saves, "存档目录 —", "warn")
        self._set_chip(self.chip_data, "数据 —", "warn")
        self._set_chip(self.chip_write, "写入 —", "warn")
        self._set_chip(self.chip_agent, "代理 —", "warn")
        text = f"体检失败：{msg}；展开「诊断」查看日志或导出诊断包。"
        self.health_summary.setText(text)
        self.health_summary.setToolTip(text)
        self._log(text)

    def _apply_health_chips(self, h: dict) -> None:
        game = str(h.get("game_dir") or "")
        saves = str(h.get("saves_dir") or "")
        self._set_chip(self.chip_game, "游戏目录 已设置" if game else "游戏目录 未设置",
                       "ok" if game else "warn")
        self.chip_game.setToolTip(game or "未设置：展开「路径」选择或自动检测")
        if saves and not getattr(self, "_saves_explicit", False):
            saves_text = "存档目录 自动"
        else:
            saves_text = "存档目录 已设置" if saves else "存档目录 未设置"
        self._set_chip(self.chip_saves, saves_text, "ok" if saves else "warn")
        self.chip_saves.setToolTip(saves or "未设置：展开「路径」选择存档目录")
        data_ready = bool(h.get("data_ready"))
        self._set_chip(self.chip_data, "数据 就绪" if data_ready else "数据 缺失",
                       "ok" if data_ready else "warn")
        self.chip_data.setToolTip(
            "数据层可用" if data_ready else "缺 Gagarin/catalog.txt：展开「路径」检查数据目录")
        write_on = bool(h.get("write_enabled"))
        self._set_chip(self.chip_write, "写入 开启" if write_on else "写入 关闭",
                       "warn" if write_on else "ok")
        self.chip_write.setToolTip("写入开关可在「安全」组修改；默认关闭。")
        live = bool(h.get("live_available"))
        self._set_chip(self.chip_agent, "代理 可用" if live else "代理 不可用",
                       "ok" if live else "warn")
        self.chip_agent.setToolTip(
            "游戏内通道可用" if live else "游戏内通道仅支持 Windows；离线功能不受影响")

    @staticmethod
    def _health_advice(h: dict) -> str:
        if not h.get("game_dir"):
            return "下一步：点「自动检测」；找不到就展开「路径」手动选择游戏根目录。"
        if not h.get("saves_ready"):
            return "下一步：展开「路径」选择存档目录（含 save.hg），或点「自动检测」。"
        if not h.get("data_ready"):
            return "下一步：展开「路径」确认数据目录含 Gagarin/ships/catalog.txt。"
        return ("环境就绪：可回到「联动」连接游戏；有异常时展开「诊断」导出诊断包。")

    # ------------------------------------------------------------ 存档列表

    def _load_saves(self) -> None:
        folder = self.saves.text().strip()
        if not folder:
            # 不主动扫描系统默认存档目录：路径未设置时先让用户确认位置，
            # 既避免误读别的存档，也避免打开设置页就触发全盘存档解析。
            self._saves_dir = ""
            self._saves_files = []
            self.saves_table.setRowCount(0)
            self.saves_summary.setText(
                "尚未设置存档目录：点「自动检测」或在上方选择含 save.hg 的目录。")
            self.save_detail.setText(
                "下一步：选择存档目录后点「刷新列表」；扫描只读取文件头，不写存档。")
            self.saves_use_btn.setEnabled(False)
            return
        self.saves_summary.setText("正在扫描存档目录…（只读，不写存档）")
        self.saves_refresh_btn.setEnabled(False)

        def fetch() -> dict:
            data = self.svc.saves(folder)
            default = ""
            try:
                default = str((self.svc.default_save() or {}).get("path") or "")
            except Exception:                               # noqa: BLE001 - 默认存档只是提示
                default = ""
            return {"saves": data if isinstance(data, dict) else {},
                    "default": default}

        run_worker(fetch, self._saves_done, self._saves_failed)

    def _saves_done(self, res: dict) -> None:
        self.saves_refresh_btn.setEnabled(True)
        res = res if isinstance(res, dict) else {}
        data = res.get("saves") or {}
        files = [f for f in (data.get("files") or []) if isinstance(f, dict)]
        self._saves_files = files
        self._saves_default = str(res.get("default") or "")
        self._saves_dir = str(data.get("dir") or "")

        def _key(f: dict) -> tuple:
            path = os.path.normcase(str(f.get("path") or ""))
            default_rank = 0 if self._saves_default and path == os.path.normcase(
                self._saves_default) else 1
            return (str(f.get("kind") or "") != "player", not bool(f.get("ok")),
                    default_rank, str(f.get("name") or "").lower())

        files.sort(key=_key)
        self.saves_table.setRowCount(0)
        for f in files:
            self._append_save_row(f)
        players = [f for f in files if f.get("kind") == "player" and f.get("ok")]
        if not self._saves_dir:
            self.saves_summary.setText(
                "未找到存档目录：展开「路径」选择，或点「自动检测」。")
            self.save_detail.setText(
                "没有可读取的存档目录。\n下一步：在「路径」选择存档目录（含 save.hg），"
                "再点「刷新列表」。")
        elif not files:
            self.saves_summary.setText(
                f"目录 {self._saves_dir} 里没有 .hg 文件；确认是否选错目录。")
            self.save_detail.setText(
                f"路径：{self._saves_dir}\n\n"
                "没有发现 .hg 文件。请确认这里是否是无人深空的存档目录。")
        else:
            self.saves_summary.setText(
                f"目录 {self._saves_dir} · {len(files)} 个文件 · "
                f"{len(players)} 份可读玩家存档")
            self.save_detail.setText(
                "选中一行查看完整路径、船数与可读性。\n"
                "「设为当前存档目录」只写入设置；不会修改存档内容。")
        if self._saves_dir:
            default_name = (os.path.basename(self._saves_default)
                            if self._saves_default else "未找到")
            self.paths_group.set_summary(
                f"{len(files)} 个存档文件 · 默认 {default_name} · 扫描只读")
        self.saves_use_btn.setEnabled(bool(self._saves_dir or self.saves.text().strip()))
        if players and not self._saves_default:
            self.save_detail.setText(self.save_detail.text() +
                                     "\n\n船队页未找到默认存档（save.hg / save2.hg）。")
        if self._saves_default:
            self.saves_summary.setToolTip(
                f"「我的 → 船队」当前默认存档：{self._saves_default}")
        else:
            self.saves_summary.setToolTip("没有找到默认存档（save.hg / save2.hg）")

    def _append_save_row(self, f: dict) -> None:
        row = self.saves_table.rowCount()
        self.saves_table.insertRow(row)
        name = str(f.get("name") or "—")
        path = str(f.get("path") or "")
        kind = str(f.get("kind") or "unknown")
        ok = bool(f.get("ok"))
        error = str(f.get("error") or "")
        is_default = bool(self._saves_default) and os.path.normcase(
            path) == os.path.normcase(self._saves_default)
        name_item = QTableWidgetItem(f"{name}（默认）" if is_default else name)
        name_item.setData(Qt.UserRole, f)
        name_item.setToolTip(path or name)
        self.saves_table.setItem(row, 0, name_item)

        kind_item = QTableWidgetItem(_KIND_LABELS.get(kind, kind))
        kind_item.setToolTip(f"类型：{_KIND_LABELS.get(kind, kind)}")
        self.saves_table.setItem(row, 1, kind_item)

        size_item = QTableWidgetItem(_human_size(f.get("size")))
        size_item.setToolTip(f"{_coerce_int(f.get('size'), 0)} 字节")
        size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.saves_table.setItem(row, 2, size_item)

        ships = "—" if kind != "player" or not ok else str(_coerce_int(f.get("ships"), 0))
        ships_item = QTableWidgetItem(ships)
        ships_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.saves_table.setItem(row, 3, ships_item)

        if kind != "player":
            readable, color = "不适用", QColor("#8b95a7")
            read_tip = f"不适用：{error or '不是玩家存档'}"
        elif ok:
            readable, color = "可读", QColor("#a8e8c9")
            read_tip = f"可读：{_coerce_int(f.get('ships'), 0)} 艘船"
        else:
            readable, color = "不可读", QColor("#f3b6a7")
            read_tip = f"不可读：{error or '未知原因'}"
        read_item = QTableWidgetItem(readable)
        read_item.setForeground(color)
        read_item.setToolTip(read_tip)
        self.saves_table.setItem(row, 4, read_item)

    def _saves_failed(self, msg: str) -> None:
        self.saves_refresh_btn.setEnabled(True)
        text = f"扫描存档目录失败：{msg}"
        self.saves_summary.setText(text + "；可点「刷新列表」重试。")
        self.save_detail.setText(
            f"{text}\n\n下一步：确认存档目录存在且可访问；仍失败时展开「诊断」打开日志目录。")
        self._log(text)
        self.error_banner.show_error(text)

    def _selected_save(self) -> dict | None:
        row = self.saves_table.currentRow()
        if row < 0:
            return None
        item = self.saves_table.item(row, 0)
        data = item.data(Qt.UserRole) if item is not None else None
        return data if isinstance(data, dict) else None

    def _saves_selection_changed(self) -> None:
        f = self._selected_save()
        if f is None:
            self.saves_use_btn.setEnabled(bool(self._saves_dir or self.saves.text().strip()))
            return
        self.saves_use_btn.setEnabled(True)
        path = str(f.get("path") or "")
        kind = str(f.get("kind") or "unknown")
        kind_text = _KIND_LABELS.get(kind, kind)
        lines = [
            f"文件：{f.get('name') or '—'}",
            f"路径：{path or '—'}",
            f"类型：{kind_text}",
            f"大小：{_human_size(f.get('size'))}",
        ]
        if kind == "player":
            lines.append(f"船数：{_coerce_int(f.get('ships'), 0) if f.get('ok') else '—'}")
        lines.append(f"可读性：{'可读' if f.get('ok') else '不适用或不可读'}")
        if f.get("error"):
            lines.append(f"原因：{f['error']}")
        if kind != "player":
            lines.append("提示：这类文件不能当作玩家存档读取，切换到它所在目录也不会改变这一点。")
        elif self._saves_default and os.path.normcase(path) == os.path.normcase(
                self._saves_default):
            lines.append("提示：这是船队页默认读取的存档（重新读取时生效）。")
        else:
            lines.append(
                "提示：船队页默认优先读取 save.hg / save2.hg；要精确使用这个文件，"
                "请到「我的 → 船队」点「浏览…」选择。")
        self.save_detail.setText("\n".join(lines))

    def _use_saves_dir(self) -> None:
        f = self._selected_save()
        folder = ""
        if f and f.get("path"):
            folder = os.path.dirname(str(f["path"]))
        folder = folder or self._saves_dir or self.saves.text().strip()
        if not folder:
            notify.warn("还没有可切换的存档目录；请先选择或自动检测。")
            return
        try:
            self.svc.update_settings(saves_dir=folder)
        except Exception as e:                              # noqa: BLE001
            text = f"保存存档目录失败：{type(e).__name__}: {e}"
            self.saves_summary.setText(text)
            self.error_banner.show_error(text)
            notify.error(text)
            return
        self._syncing = True
        try:
            self.saves.setText(folder)
        finally:
            self._syncing = False
        self._update_path_empty()
        self._sync_paths_summary()
        self._log(f"已切换存档目录：{folder}")
        notify.success("已设为当前存档目录；回到「我的 → 船队」点「读取存档」生效。")
        self._load_saves()
        self._refresh_health()

    def _open_saves_dir(self) -> None:
        folder = self._saves_dir or self.saves.text().strip()
        if not folder or not os.path.isdir(folder):
            notify.warn("存档目录不存在或尚未设置；请先选择目录或自动检测。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _open_diagnostics(self) -> None:
        """顶部「查看诊断详情」：展开诊断组并滚到可见位置。"""
        self.diag_group.set_expanded(True)
        self.diag_group.set_spotlight(True)
        QTimer.singleShot(1800, lambda: self.diag_group.set_spotlight(False))
        reveal_widget(self.diag_group)

    def _autodetect(self) -> None:
        self._log("自动检测中…")
        self.loading_overlay.start("正在自动检测游戏与存档目录…")
        notify.toast("正在自动检测游戏与存档目录…")
        run_worker(self.svc.autodetect, self._after_autodetect,
                   self._autodetect_failed, True)

    def _after_autodetect(self, res: dict) -> None:
        self.loading_overlay.stop()
        res = res if isinstance(res, dict) else {}
        found = res.get("found") or {}
        self._log(json.dumps(res, ensure_ascii=False, indent=1))
        if found:
            notify.success(f"自动检测完成：找到 {len(found)} 项路径。")
        else:
            notify.warn("未找到游戏或存档目录，请手动选择。")
        self._load()

    def _autodetect_failed(self, msg: str) -> None:
        self.loading_overlay.stop()
        text = f"自动检测失败：{msg}"
        self._log(text)
        self.error_banner.show_error(text)
        notify.error(text)

    # ------------------------------------------------------------ 运行时

    def _on_runtime_toggled(self, expanded: bool) -> None:
        """运行时组默认折叠：展开时才检查 build、代理与组件，避免首屏等待。"""
        if expanded:
            self._refresh_env()
            self._refresh_runtime()

    def _refresh_env(self) -> None:
        run_worker(self.svc.diagnostics_overview, self._env_done, self._env_failed)

    def _refresh_runtime(self) -> None:
        run_worker(self.svc.live_capabilities, self._runtime_done, self._runtime_failed)

    def _env_done(self, res: dict) -> None:
        res = res if isinstance(res, dict) else {}
        self.build_label.setText(self._format_build(res.get("build") or {}))
        self.build_label.setToolTip(self.build_label.text())
        self.agent_label.setText(self._format_agent(res.get("agent") or {}))
        self.agent_label.setToolTip(self.agent_label.text())

    def _env_failed(self, msg: str) -> None:
        text = f"读取 build/代理状态失败：{msg}"
        self.build_label.setText("游戏 build：未知（状态读取失败）")
        self.agent_label.setText(f"游戏内代理：未知（{msg}）")
        self._log(text)

    def _runtime_done(self, cap: dict) -> None:
        cap = cap if isinstance(cap, dict) else {}
        st = cap.get("status") or {}
        supported = bool(st.get("supported"))
        runtime_files = bool(st.get("runtime_ready"))
        ready = (runtime_files and bool(st.get("pymhf_http_api"))
                 and bool(st.get("nmspy_version")) and bool(st.get("pymhf_version")))
        py = str(st.get("runtime_python_version") or "")
        err = str(st.get("runtime_error") or "")
        nmspy = str(st.get("nmspy_version") or "")
        pymhf = str(st.get("pymhf_version") or "")
        if not supported:
            runtime = "运行时：不可用（游戏内通道仅支持 Windows）"
        elif runtime_files:
            runtime = f"运行时：已就绪 · Python {py or '版本未知'}"
            if not ready:
                missing = []
                if not nmspy:
                    missing.append("NMSpy")
                if not pymhf:
                    missing.append("pymhf")
                if not st.get("pymhf_http_api"):
                    missing.append("HTTP API")
                runtime += " · 组件缺 " + "、".join(missing)
        else:
            runtime = "运行时：缺失或不完整" + (f"（{err}）" if err else "")
        self.runtime_label.setText(runtime)
        self.runtime_label.setToolTip(
            f"NMSpy {nmspy or '—'} · pymhf {pymhf or '—'}\n"
            f"{st.get('runtime_python') or '运行时路径未知'}")
        mod_path = str(st.get("mod_path") or "")
        installed = bool(st.get("mod_installed"))
        self.agent_file_label.setText(
            f"代理文件：已安装 · {os.path.basename(mod_path) if mod_path else '路径未知'}"
            if installed else "代理文件：未安装（不影响离线功能）")
        self.agent_file_label.setToolTip(mod_path or "~/.starforge/agent/starforge_agent.py")
        self.bootstrap_btn.setEnabled(supported and not runtime_files)
        self.repair_btn.setEnabled(supported and runtime_files)
        self.install_agent_btn.setEnabled(supported)
        self.uninstall_agent_btn.setEnabled(supported and installed)
        if not runtime_files:
            self.runtime_note.setText(
                "运行时缺失：先点「准备运行时」；正常安装包已内置，通常无需联网。")
        elif not ready:
            self.runtime_note.setText(
                "运行时已就绪但组件不完整：点「安装 / 修复组件」补齐；不会写存档。")
        else:
            self.runtime_note.setText(
                "运行时与组件已就绪；卸载只删除代理文件，不影响运行时与存档。")
        if ready:
            self.runtime_group.set_chip("组件就绪", "ok")
            self.runtime_group.set_summary(
                f"运行时就绪 · NMSpy {nmspy or '—'} · pymhf {pymhf or '—'}；"
                "安装/卸载只写本机代理目录。")
        elif not runtime_files:
            self.runtime_group.set_chip("缺运行时", "warn")
            self.runtime_group.set_summary(
                "下一步：展开本组点「准备运行时」，再点「安装 / 修复组件」。")
        else:
            self.runtime_group.set_chip("需修复", "bad")
            self.runtime_group.set_summary("组件不完整：展开本组点「安装 / 修复组件」。")

    def _runtime_failed(self, msg: str) -> None:
        self.runtime_label.setText(f"运行时：状态未知（{msg}）")
        self.runtime_label.setToolTip(msg)
        self.runtime_group.set_chip("状态未知", "warn")
        self.runtime_group.set_summary(
            "下一步：点「刷新状态」；仍失败时展开「诊断」查看日志。")
        self._log(f"读取运行时状态失败：{msg}")

    def _prepare_runtime(self) -> None:
        if not ask_write(
                self, "准备运行时",
                "将把 Python 运行时写入 ~/.starforge/agent/runtime。\n"
                "不会修改存档或游戏 GAMEDATA。继续？"):
            notify.toast("已取消准备运行时。")
            return
        self._log("准备游戏内运行时…")
        self.loading_overlay.start("正在准备游戏内运行时…")
        notify.toast("正在准备游戏内运行时…")
        self.runtime_note.setText("正在准备运行时；正常安装包已内置，通常无需下载。")

        def done(res: dict) -> None:
            self.loading_overlay.stop()
            res = res if isinstance(res, dict) else {}
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            if res.get("ok") is False:
                detail = str(res.get("error") or "未知错误")
                text = (f"准备运行时失败：{detail}；请检查网络与磁盘空间，"
                        "或重新解压完整安装包。")
                self.runtime_note.setText(text)
                self.error_banner.show_error(text)
                notify.error(text)
                return
            note = str(res.get("note") or "")
            py = str(res.get("python") or "")
            self.runtime_note.setText(note or f"运行时已就绪：{py}")
            notify.success("运行时已就绪。")
            self._refresh_env()
            self._refresh_runtime()

        def fail(msg: str) -> None:
            self.loading_overlay.stop()
            text = (f"准备运行时失败：{msg}；请检查网络/磁盘空间，"
                    "或重新解压完整安装包。")
            self._log(text)
            self.runtime_note.setText(text)
            self.error_banner.show_error(text)
            notify.error(text)

        run_worker(self.svc.agent_bootstrap_runtime, done, fail)

    def _repair(self) -> None:
        if not ask_write(
                self, "安装 / 修复组件",
                "将安装或更新 NMSpy + pymhf 到 ~/.starforge/agent。\n"
                "不会修改存档或游戏 GAMEDATA。继续？"):
            notify.toast("已取消安装 / 修复组件。")
            return
        self._log("安装/修复运行时与游戏内组件…")
        self.loading_overlay.start("正在安装/修复游戏内组件…")
        notify.toast("正在安装/修复游戏内组件…")
        self.runtime_note.setText("正在安装/更新 NMSpy + pymhf；不会写存档。")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            self.loading_overlay.stop()
            res = res if isinstance(res, dict) else {}
            if res.get("ok") is False:
                detail = str(res.get("error") or res.get("code") or "未知错误")
                if res.get("needs_runtime"):
                    text = (f"修复未完成：{detail}；先点「准备运行时」，"
                            "再重试「安装 / 修复组件」。")
                else:
                    text = (f"修复未完成：{detail}；可先点「准备运行时」检查运行时，"
                            "或展开「诊断」查看日志。")
                self.runtime_note.setText(text)
                self.error_banner.show_error(text)
                notify.error(text)
                self._refresh_env()
                self._refresh_runtime()
                return
            self.runtime_note.setText(
                str(res.get("note") or "").strip()
                or "游戏内组件已安装/修复；可点「刷新状态」。")
            notify.success("游戏内组件已就绪。")
            self._refresh_env()
            self._refresh_runtime()

        def fail(msg: str) -> None:
            text = (f"修复失败：{msg}；先点「准备运行时」，或展开「诊断」查看日志后重试。")
            self._log(text)
            self.loading_overlay.stop()
            self.runtime_note.setText(text)
            self.error_banner.show_error(text)
            notify.error(text)

        run_worker(self.svc.agent_install_deps, done, fail)

    def _install_agent_file(self) -> None:
        if not ask_write(
                self, "重写代理文件",
                "将把 starforge_agent.py 写入 ~/.starforge/agent。\n"
                "不会修改存档或游戏 GAMEDATA。继续？"):
            notify.toast("已取消写入代理文件。")
            return
        self._log("重写代理文件…")
        self.runtime_note.setText("正在把 starforge_agent.py 写入 ~/.starforge/agent…")

        def done(res: dict) -> None:
            res = res if isinstance(res, dict) else {}
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            if res.get("ok") is False:
                text = f"写入代理文件失败：{res.get('error') or '未知错误'}"
                self.runtime_note.setText(text + "；可检查 ~/.starforge 目录权限。")
                self.error_banner.show_error(text)
                notify.error(text)
                return
            path = str(res.get("path") or "")
            size = res.get("bytes")
            suffix = f"（{size} B）" if size is not None else ""
            self.runtime_note.setText(
                f"已写入代理文件：{path}{suffix}；重启游戏后生效。"
                if path else "已写入代理文件；重启游戏后生效。")
            notify.success("代理文件已写入。")
            self._refresh_env()
            self._refresh_runtime()

        def fail(msg: str) -> None:
            text = f"写入代理文件失败：{msg}；可检查 ~/.starforge 目录权限。"
            self._log(text)
            self.runtime_note.setText(text)
            self.error_banner.show_error(text)
            notify.error(text)

        run_worker(self.svc.agent_install_mod, done, fail)

    def _uninstall_agent_file(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self, "卸载游戏内组件",
            "将删除 ~/.starforge/agent/starforge_agent.py。\n"
            "不会删除运行时、存档或游戏 GAMEDATA；已注入游戏的代理会保留到游戏退出。\n\n"
            "继续卸载？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            notify.toast("已取消卸载。")
            return
        self._log("卸载游戏内组件…")
        self.runtime_note.setText("正在删除代理文件…")

        def uninstall() -> dict:
            from ...live import agent_install

            return agent_install.uninstall_mod()

        def done(res: dict) -> None:
            res = res if isinstance(res, dict) else {}
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            if res.get("ok") is False:
                text = f"卸载失败：{res.get('error') or '未知错误'}"
                self.runtime_note.setText(text + "；可手动检查 ~/.starforge/agent。")
                self.error_banner.show_error(text)
                notify.error(text)
                return
            self.runtime_note.setText(
                "已卸载代理文件；运行时与存档未改动。" if res.get("removed")
                else "代理文件本来就不存在；无需卸载。")
            notify.success("游戏内组件已卸载（代理文件）。")
            self._refresh_env()
            self._refresh_runtime()

        def fail(msg: str) -> None:
            text = f"卸载失败：{msg}；可手动检查 ~/.starforge/agent。"
            self._log(text)
            self.runtime_note.setText(text)
            self.error_banner.show_error(text)
            notify.error(text)

        run_worker(uninstall, done, fail)

    @staticmethod
    def _format_build(info: dict) -> str:
        info = info if isinstance(info, dict) else {}
        if info.get("error"):
            return f"游戏 build：未知（{info['error']}）"
        bid = info.get("build_id") or (
            (info.get("fingerprint") or {}).get("version") if isinstance(
                info.get("fingerprint"), dict) else "") or "未知"
        status = str(info.get("status") or "").strip().lower()
        if info.get("verified"):
            return f"游戏 build：{bid} · 已验证（写权限仍受安全设置约束）"
        if status == "unverified":
            return f"游戏 build：{bid} · 未验证（只读）"
        return f"游戏 build：{bid} · 未知/未验证（只读）"

    @staticmethod
    def _format_agent(info: dict) -> str:
        info = info if isinstance(info, dict) else {}
        if info.get("error"):
            return f"游戏内代理：状态未知（{info['error']}）"
        if not info.get("supported"):
            return f"游戏内代理：不可用（{info.get('note') or '仅支持 Windows'}）"
        state = "已连接" if info.get("reachable") else (
            "游戏运行中，未连接" if info.get("game_running") else "未连接")
        note = str(info.get("note") or "").strip()
        return f"游戏内代理：{state}" + (f" · {note}" if note else "")

    # ------------------------------------------------------------ 日志/诊断

    def _copy_recent_logs(self) -> None:
        self._log("读取最近日志…")
        run_worker(self.svc.recent_logs, self._copy_logs_done, self._log_failed)

    def _copy_logs_done(self, res: dict) -> None:
        res = res if isinstance(res, dict) else {}
        files = res.get("files") or []
        if not files:
            notify.warn("没有找到日志文件。")
            self._log("没有找到日志文件。")
            return
        parts = []
        for item in files:
            parts.append(f"===== {item.get('name')} · {item.get('path')} =====")
            parts.append(str(item.get("text") or ""))
        QGuiApplication.clipboard().setText("\n".join(parts))
        self._log(f"已复制最近日志：{len(files)} 个文件")
        notify.success(f"已复制最近日志（{len(files)} 个文件）。")

    def _show_launcher(self) -> None:
        self._log("读取 launcher.log…")
        self.diag_group.set_expanded(True)
        run_worker(self.svc.recent_logs, self._launcher_done, self._log_failed, 20)

    def _launcher_done(self, res: dict) -> None:
        res = res if isinstance(res, dict) else {}
        files = res.get("files") or []
        item = next((f for f in files
                     if str(f.get("name") or "").lower() == "launcher.log"), None)
        if item is None:
            self.out.setPlainText(
                "没有找到 launcher.log。\n\n"
                "它只在游戏内代理启动后生成；可先到「联动」连接游戏，或打开日志目录检查。")
            notify.warn("没有找到 launcher.log。")
            return
        head = (f"launcher.log 摘要（最近 {len(item.get('text') or '')} 字符"
                + ("，已截断" if item.get("truncated") else "") + f"）\n{item.get('path')}\n"
                + "-" * 68 + "\n")
        self.out.setPlainText(head + str(item.get("text") or ""))
        self._log("已显示 launcher.log 摘要。")

    def _log_failed(self, msg: str) -> None:
        text = f"读取日志失败：{msg}"
        self._log(text)
        self.error_banner.show_error(text)
        notify.error(text)

    def _doctor(self) -> None:
        self._log("体检中…")
        self.loading_overlay.start("正在运行环境体检…")
        notify.toast("正在运行环境体检…")
        run_worker(self.svc.doctor, self._doctor_done, self._doctor_failed)

    def _doctor_done(self, res: dict) -> None:
        self.loading_overlay.stop()
        res = res if isinstance(res, dict) else {}
        self.out.setPlainText(self._format_doctor(res))
        self._log("体检完成。")
        if res.get("health"):
            self._apply_health_chips(res.get("health") or {})
        if res.get("ok", True):
            self.diag_group.set_chip("通过", "ok")
            self.diag_group.set_summary("上次体检通过；需要时展开查看原文或导出诊断包。")
            self.health_summary.setText(
                "体检通过：路径、依赖与写入状态正常；有异常时展开「诊断」。")
            self.error_banner.clear()
            notify.success("体检完成：通过。")
        else:
            self.diag_group.set_chip("异常", "bad")
            self.diag_group.set_summary(
                "上次体检发现异常：展开本组查看详情，或导出诊断包。")
            self.health_summary.setText(
                "体检发现异常：展开「诊断」查看原因；下一步按提示修复后重跑。")
            notify.warn("体检完成：发现异常，详情见诊断结果。")
        self.health_summary.setToolTip(self.health_summary.text())

    def _doctor_failed(self, msg: str) -> None:
        self.loading_overlay.stop()
        text = f"体检失败：{msg}"
        self.out.setPlainText(text)
        self._log(text)
        self.diag_group.set_chip("失败", "bad")
        self.diag_group.set_summary("下一步：展开本组打开日志目录，或导出诊断包。")
        self.health_summary.setText(text + "；展开「诊断」查看日志。")
        self.error_banner.show_error(text)
        notify.error(text)

    # ------------------------------------------------------------ 自检

    def _selfcheck(self) -> None:
        self.selfcheck_btn.setEnabled(False)
        self.selfcheck_summary.setText("正在运行自检…（只读，不写存档）")
        self.loading_overlay.start("正在运行自检（只读）…")
        notify.toast("正在运行自检（只读）…")
        run_worker(self.svc.diagnostics, self._selfcheck_done, self._selfcheck_failed)

    def _selfcheck_failed(self, msg: str) -> None:
        self.selfcheck_btn.setEnabled(True)
        self.loading_overlay.stop()
        text = f"自检失败：{msg}"
        self.selfcheck_summary.setText(text + "；可点「运行自检」重试。")
        self.selfcheck_table.hide()
        self.selfcheck_hint.show()
        self.selfcheck_hint.setText(
            "下一步：先在「诊断」点「运行体检」确认 Python/Qt 依赖，"
            "再打开日志目录查看 starforge.log 尾部；仍失败时导出诊断包。")
        self._log(text)
        self.error_banner.show_error(text)
        notify.error(text)

    def _selfcheck_done(self, res: dict) -> None:
        self.selfcheck_btn.setEnabled(True)
        self.loading_overlay.stop()
        res = res if isinstance(res, dict) else {}
        steps = [s for s in (res.get("steps") or []) if isinstance(s, dict)]
        self.selfcheck_table.setRowCount(0)
        self.selfcheck_table.show()
        self.selfcheck_hint.show()
        for step in steps:
            self._append_selfcheck_row(step)
        passed = sum(1 for s in steps if s.get("ok"))
        summary = str(res.get("summary") or f"{passed}/{len(steps)} 步通过")
        ok = bool(res.get("ok", passed == len(steps)))
        self.selfcheck_summary.setText(
            f"{summary} · {'全部关键步骤通过' if ok else '有关键步骤失败'}")
        self.selfcheck_hint.setText(self._selfcheck_advice(steps, ok))
        self._log(f"自检完成：{summary}")
        if ok:
            self.error_banner.clear()
            notify.success(f"自检完成：{summary}")
        else:
            notify.warn(f"自检完成：{summary}；请按下方建议处理。")

    def _append_selfcheck_row(self, step: dict) -> None:
        row = self.selfcheck_table.rowCount()
        self.selfcheck_table.insertRow(row)
        ok = bool(step.get("ok"))
        critical = bool(step.get("critical", True))
        if ok:
            state, color = "✓ 通过", QColor("#a8e8c9")
        elif critical:
            state, color = "✗ 失败", QColor("#f3b6a7")
        else:
            state, color = "! 非关键失败", QColor("#f0cd9a")
        state_item = QTableWidgetItem(state)
        state_item.setForeground(color)
        self.selfcheck_table.setItem(row, 0, state_item)
        name = str(step.get("name") or "—")
        name_item = QTableWidgetItem(name)
        name_item.setToolTip("关键步骤" if critical else "非关键步骤")
        self.selfcheck_table.setItem(row, 1, name_item)
        ms = step.get("ms")
        time_item = QTableWidgetItem(f"{_coerce_int(ms, 0)} ms" if ms is not None else "—")
        time_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.selfcheck_table.setItem(row, 2, time_item)
        detail = str(step.get("detail") or "—")
        detail_item = QTableWidgetItem(detail)
        detail_item.setToolTip(detail)
        self.selfcheck_table.setItem(row, 3, detail_item)

    @staticmethod
    def _selfcheck_advice(steps: list[dict], ok: bool) -> str:
        if ok:
            return ("下一步：全部关键步骤通过。可回到「诊断」点「导出诊断包」留档；"
                    "游戏内代理相关项仍需在「联动」页连接后再验证。")
        failed = [s for s in steps if not s.get("ok")]
        critical = [s for s in failed if s.get("critical", True)]
        target = critical[0] if critical else (failed[0] if failed else {})
        name = str(target.get("name") or "")
        detail = str(target.get("detail") or "").lower()
        prefix = "关键步骤失败" if critical else "非关键步骤失败"
        if "部件目录" in name or "部件图标" in name or "catalog" in detail:
            action = ("展开「路径」确认数据目录含 Gagarin/ships/catalog.txt，"
                      "或设置 STARFORGE_GAMEDATA 后点「刷新列表」/重跑自检。")
        elif "存档" in name or "save" in detail:
            action = ("展开「路径」选择含 save.hg 的存档目录；若存档损坏，"
                      "请用「我的 → 船队 → 备份」恢复一份可读存档后再试。")
        elif "搜索" in name:
            action = "放宽搜索条件（减少 want/avoid）并确认数据目录可用后重试。"
        elif "3D" in name or "预览" in name or "glb" in detail:
            action = ("确认游戏根目录正确（含 Binaries/NMS.exe）且 GAMEDATA 完整；"
                      "否则 3D 预览会停在 L0。")
        elif "缩略图" in name:
            action = "先运行「运行体检」确认 numpy / texture2ddecoder 可用，再重跑自检。"
        elif "符文" in name:
            action = ("确认游戏 pak 可读且 texture2ddecoder 可用；缺失时会退化为内置字体，"
                      "不影响其它功能。")
        elif "星系" in name:
            action = ("星系生成需要 unicorn 与游戏数据：先运行「运行体检」确认 unicorn 可用，"
                      "并在「路径」确认游戏目录。")
        elif "实时通道" in name:
            action = ("该项是非关键项：打开游戏并在「联动」页连接后重跑自检；"
                      "不连接也能继续使用离线功能。")
        else:
            action = ("打开「诊断」里的「打开日志目录」，查看 starforge.log 尾部；"
                      "仍无法定位时点「导出诊断包」。")
        return f"下一步（{prefix}：{name or '未知步骤'}）：{action}"

    @staticmethod
    def _format_doctor(res: dict) -> str:
        ok = bool(res.get("ok", True))
        lines = [f"体检结果：{'通过' if ok else '异常'}"]
        if res.get("python"):
            lines.append(f"Python：{res['python']}")
        if res.get("platform"):
            lines.append(f"平台：{res['platform']}")
        deps = res.get("deps") or {}
        if deps:
            lines.append("依赖：")
            for name, state in deps.items():
                shown = "正常" if str(state).strip().lower() == "ok" else str(state)
                lines.append(f"  {name}：{shown}")
        health = res.get("health") or {}
        if health:
            lines.append("健康检查：")
            lines.append(f"  数据层：{'就绪' if health.get('data_ready') else '缺失'}")
            lines.append(f"  存档：{'已发现' if health.get('saves_ready') else '未发现'}")
            lines.append(f"  游戏目录：{health.get('game_dir') or '未设置'}")
            lines.append(f"  写入：{'已启用' if health.get('write_enabled') else '已关闭'}")
            lines.append(f"  游戏内代理：{'可用' if health.get('live_available') else '不可用'}")
        return "\n".join(lines)

    def _export_diag(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出诊断包",
                                              "starforge-diagnostics.zip",
                                              "ZIP (*.zip)")
        if not path:
            notify.warn("已取消导出诊断。")
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        self.loading_overlay.start("正在导出诊断包…")
        notify.toast("正在导出诊断包…")
        run_worker(self.svc.export_diagnostics, self._export_done,
                   self._export_failed, path)

    def _export_done(self, res: dict) -> None:
        self.loading_overlay.stop()
        res = res if isinstance(res, dict) else {}
        path = res.get("path") or "诊断包"
        entries = res.get("entries") or []
        errors = res.get("errors") or {}
        self._log(f"诊断已导出：{path}（{len(entries)} 个文件）")
        if errors:
            text = "部分诊断项失败：" + "；".join(f"{k}: {v}" for k, v in errors.items())
            self._log(text)
            self.error_banner.show_error(text)
            self.diag_group.set_chip("部分失败", "warn")
            notify.warn(f"诊断包已导出，但有 {len(errors)} 项失败。")
        else:
            self.error_banner.clear()
            self.diag_group.set_chip("已导出", "ok")
            self.diag_group.set_summary(f"诊断包已导出：{path}")
            notify.success(f"诊断已导出：{path}")

    def _export_failed(self, msg: str) -> None:
        self.loading_overlay.stop()
        text = f"导出失败：{msg}"
        self._log(text)
        self.error_banner.show_error(text)
        notify.error(text)

    def _log(self, text: str) -> None:
        self.out.append(str(text))
