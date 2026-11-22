"""设置与诊断：Card 布局，原生路径选择。"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
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
from ..widgets.feedback import EmptyState, ErrorBanner, LoadingOverlay
from ..widgets.page import PAGE_MARGINS, PAGE_SPACING
from ..widgets.page_header import PageHeader
from ..widgets.ui import Card, muted
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


def _path_row(edit: QLineEdit) -> QWidget:
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(edit, 1)
    btn = QPushButton("浏览…")

    def pick() -> None:
        p = QFileDialog.getExistingDirectory(box, "选择目录", edit.text())
        if p:
            edit.setText(p)

    btn.clicked.connect(pick)
    h.addWidget(btn)
    return box


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
        self._build_ui()

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
            "管理游戏路径、安全写入，并运行环境体检与导出诊断。")
        root.addWidget(self.header)
        self.error_banner = ErrorBanner("")
        self.error_banner.set_retry_callback(self._load)
        root.addWidget(self.error_banner)

        paths_card = Card("路径", "自动检测优先；找不到再手动选择")
        form = QFormLayout()
        self.game = QLineEdit()
        self.game.setPlaceholderText("游戏根目录（含 Binaries/NMS.exe）")
        form.addRow("游戏目录", _path_row(self.game))
        self.saves = QLineEdit()
        self.saves.setPlaceholderText("存档目录（含 save.hg）")
        form.addRow("存档目录", _path_row(self.saves))
        self.game.textChanged.connect(self._update_path_empty)
        self.saves.textChanged.connect(self._update_path_empty)
        row = QHBoxLayout()
        auto = QPushButton("自动检测")
        auto.clicked.connect(self._autodetect)
        row.addWidget(auto)
        save = QPushButton("保存")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        row.addWidget(save)
        form.addRow("", row)
        paths_card.add_layout(form)
        self.path_empty = EmptyState(
            "尚未设置游戏与存档目录",
            "点「自动检测」尝试查找，或手动选择目录；未设置时无法读取存档或连接游戏。",
            icon="⌂",
            button_text="自动检测")
        self.path_empty.actionTriggered.connect(self._autodetect)
        paths_card.add(self.path_empty)
        root.addWidget(paths_card)

        saves_card = Card(
            "存档目录与文件",
            "只读扫描目录下的 .hg；「设为当前存档目录」只写设置，不碰存档内容")
        tag_row = QHBoxLayout()
        tag_row.setSpacing(6)
        tag_row.addWidget(_risk_tag("只读扫描", "ok"))
        tag_row.addWidget(_risk_tag("切换目录=写设置", "warn"))
        tag_row.addStretch(1)
        saves_card.add_layout(tag_row)
        self.saves_summary = muted("尚未扫描存档目录。")
        saves_card.add(self.saves_summary)
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
        saves_card.add(saves_split)

        saves_btns = QHBoxLayout()
        saves_btns.setSpacing(6)
        self.saves_refresh_btn = QPushButton("刷新列表（只读）")
        self.saves_refresh_btn.setToolTip("重新扫描存档目录；只读取文件头，不写任何文件")
        self.saves_refresh_btn.clicked.connect(self._load_saves)
        saves_btns.addWidget(self.saves_refresh_btn)
        self.saves_use_btn = QPushButton("设为当前存档目录（写设置）")
        self.saves_use_btn.setToolTip(
            "把选中存档所在目录写入设置；不会修改存档。"
            "回到「我的船队」点「读取存档」后按该目录的 save.hg / save2.hg 读取")
        self.saves_use_btn.setEnabled(False)
        self.saves_use_btn.clicked.connect(self._use_saves_dir)
        saves_btns.addWidget(self.saves_use_btn)
        self.saves_open_btn = QPushButton("打开目录（只读）")
        self.saves_open_btn.setToolTip("在资源管理器中打开当前存档目录")
        self.saves_open_btn.clicked.connect(self._open_saves_dir)
        saves_btns.addWidget(self.saves_open_btn)
        saves_btns.addStretch(1)
        saves_card.add_layout(saves_btns)
        saves_card.add(muted(
            "切换只决定「我的船队」重新读取时扫描哪个目录；切换后回到船队页点「读取存档」生效。"
            "若要精确使用 save3.hg 这类文件，请在船队页点「浏览…」选择该文件。"))
        root.addWidget(saves_card)

        safety = Card("安全与性能", "写入默认关闭；修改后立即保存")
        self.write = QCheckBox("允许写入存档")
        self.write.setObjectName("settingsWriteEnabled")
        self.write.toggled.connect(self._save)
        safety.add(self.write)
        self.confirm_writes = QCheckBox("写入前二次确认")
        self.confirm_writes.setObjectName("settingsConfirmWrites")
        self.confirm_writes.toggled.connect(self._save)
        safety.add(self.confirm_writes)
        perf = QFormLayout()
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
        safety.add_layout(perf)
        safety.add(muted("写入流程：备份 → 原子写入 → 读回校验 → 失败回滚。"))
        root.addWidget(safety)

        env = Card("版本与代理", "build 指纹、游戏内代理状态与只读日志入口")
        self.build_label = QLabel("游戏 build：检查中…")
        self.build_label.setObjectName("settingsBuildStatus")
        self.build_label.setWordWrap(True)
        env.add(self.build_label)
        self.agent_label = QLabel("游戏内代理：检查中…")
        self.agent_label.setObjectName("settingsAgentStatus")
        self.agent_label.setWordWrap(True)
        env.add(self.agent_label)
        env_row = QHBoxLayout()
        refresh = QPushButton("刷新状态")
        refresh.clicked.connect(self._refresh_env)
        env_row.addWidget(refresh)
        copy_logs = QPushButton("复制最近日志")
        copy_logs.setToolTip("复制 starforge.log / launcher.log 的尾部内容（只读，已脱敏）")
        copy_logs.clicked.connect(self._copy_recent_logs)
        env_row.addWidget(copy_logs)
        launcher = QPushButton("查看 launcher.log 摘要")
        launcher.setToolTip("在下方显示 launcher.log 的最近内容（只读）")
        launcher.clicked.connect(self._show_launcher)
        env_row.addWidget(launcher)
        env_row.addStretch(1)
        env.add_layout(env_row)
        root.addWidget(env)

        diag = Card("诊断", "导出 ZIP：health / doctor / selfcheck / build / agent / 脱敏设置 / 日志")
        row2 = QHBoxLayout()
        doctor = QPushButton("运行体检")
        doctor.clicked.connect(self._doctor)
        row2.addWidget(doctor)
        export = QPushButton("导出诊断包")
        export.setObjectName("primary")
        export.clicked.connect(self._export_diag)
        row2.addWidget(export)
        logs = QPushButton("打开日志目录")
        logs.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(paths.app_home() / "logs"))))
        row2.addWidget(logs)
        row2.addStretch(1)
        diag.add_layout(row2)
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setMinimumHeight(240)
        self.out.setMaximumHeight(320)
        self.out.setPlaceholderText("体检结果会以结构化文本显示在这里。")
        diag.add(self.out)
        self.doctor_output = self.out
        root.addWidget(diag)

        selfcheck = Card(
            "自检",
            "端到端验证数据层/存档/搜索/预览/符文/星系；只读，不执行写入步骤")
        sc_row = QHBoxLayout()
        sc_row.setSpacing(6)
        sc_row.addWidget(_risk_tag("只读", "ok"))
        self.selfcheck_btn = QPushButton("运行自检（只读）")
        self.selfcheck_btn.setToolTip(
            "运行 Services.diagnostics（selfcheck，include_write=False）；不写存档")
        self.selfcheck_btn.clicked.connect(self._selfcheck)
        sc_row.addWidget(self.selfcheck_btn)
        sc_row.addStretch(1)
        selfcheck.add_layout(sc_row)
        self.selfcheck_summary = muted("尚未运行自检。")
        selfcheck.add(self.selfcheck_summary)
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
        selfcheck.add(self.selfcheck_table)
        self.selfcheck_hint = muted("")
        selfcheck.add(self.selfcheck_hint)
        self.selfcheck_table.hide()
        self.selfcheck_hint.hide()
        root.addWidget(selfcheck)

        about = Card("关于")
        about.add(QLabel(f"starforge {__import__('starforge').__version__} · 原生界面（Qt）"))
        about.add(muted("只监听本机；不联网；默认只读；游戏内代理默认不安装。"))
        root.addWidget(about)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self._syncing = False
        self.loading_overlay = LoadingOverlay(self, "正在处理…")
        self.loading = self.loading_overlay
        self._update_path_empty()

    # ---------------------------------------------------------------- 数据

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._load()

    def _load(self) -> None:
        def done(res: dict) -> None:
            s = res.get("settings") or {}
            r = res.get("resolved") or {}
            self._syncing = True
            try:
                self.game.setText(s.get("game_dir") or r.get("game_dir") or "")
                self.saves.setText(s.get("saves_dir") or r.get("saves_dir") or "")
                self.write.setChecked(bool(s.get("write_enabled")))
                self.confirm_writes.setChecked(bool(s.get("confirm_writes", True)))
                self.backup_keep.setValue(_coerce_int(s.get("backup_keep"), 0))
                self.workers.setValue(_coerce_int(s.get("workers"), 0))
            finally:
                self._syncing = False
            self._update_path_empty()
            self.error_banner.clear()
            if not self._env_loaded:
                self._env_loaded = True
                self._refresh_env()
            self._load_saves()

        def fail(msg: str) -> None:
            text = f"读取设置失败：{msg}"
            self._log(text)
            self.error_banner.show_error(text)
            notify.error(text)

        run_worker(self.svc.settings_snapshot, done, fail)

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

    def _save(self, *_args) -> None:
        if self._syncing:
            return
        try:
            self.svc.update_settings(
                game_dir=self.game.text().strip(),
                saves_dir=self.saves.text().strip(),
                write_enabled=self.write.isChecked(),
                confirm_writes=self.confirm_writes.isChecked(),
                backup_keep=int(self.backup_keep.value()),
                workers=int(self.workers.value()))
            self._update_path_empty()
            self.error_banner.clear()
            self._log("设置已保存")
            notify.success("设置已保存。")
        except Exception as e:                              # noqa: BLE001
            text = f"保存失败：{type(e).__name__}: {e}"
            self._log(text)
            self.error_banner.show_error(text)
            notify.error(text)

    # ------------------------------------------------------------ 存档列表

    def _load_saves(self) -> None:
        folder = self.saves.text().strip() or None
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
                "未找到存档目录：请在上方「存档目录」里选择，或点「自动检测」。")
            self.save_detail.setText(
                "没有可读取的存档目录。\n下一步：在「路径」卡片选择存档目录（含 save.hg），"
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
        self.saves_use_btn.setEnabled(bool(self._saves_dir or self.saves.text().strip()))
        if players and not self._saves_default:
            self.save_detail.setText(self.save_detail.text() +
                                     "\n\n船队页未找到默认存档（save.hg / save2.hg）。")
        if self._saves_default:
            self.saves_summary.setToolTip(
                f"「我的船队」当前默认存档：{self._saves_default}")
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
            f"{text}\n\n下一步：确认存档目录存在且可访问；仍失败时打开日志目录查看原因。")
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
                "请到「我的船队」点「浏览…」选择。")
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
        self._log(f"已切换存档目录：{folder}")
        notify.success("已设为当前存档目录；回到「我的船队」点「读取存档」生效。")
        self._load_saves()

    def _open_saves_dir(self) -> None:
        folder = self._saves_dir or self.saves.text().strip()
        if not folder or not os.path.isdir(folder):
            notify.warn("存档目录不存在或尚未设置；请先选择目录或自动检测。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

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

    def _refresh_env(self) -> None:
        run_worker(self.svc.diagnostics_overview, self._env_done, self._env_failed)

    def _env_done(self, res: dict) -> None:
        res = res if isinstance(res, dict) else {}
        self.build_label.setText(self._format_build(res.get("build") or {}))
        self.agent_label.setText(self._format_agent(res.get("agent") or {}))

    def _env_failed(self, msg: str) -> None:
        text = f"读取 build/代理状态失败：{msg}"
        self.build_label.setText("游戏 build：未知（状态读取失败）")
        self.agent_label.setText(f"游戏内代理：未知（{msg}）")
        self._log(text)

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
        run_worker(self.svc.recent_logs, self._launcher_done, self._log_failed, 20)

    def _launcher_done(self, res: dict) -> None:
        res = res if isinstance(res, dict) else {}
        files = res.get("files") or []
        item = next((f for f in files
                     if str(f.get("name") or "").lower() == "launcher.log"), None)
        if item is None:
            self.out.setPlainText(
                "没有找到 launcher.log。\n\n"
                "它只在游戏内代理启动后生成；可先连接游戏，或打开日志目录检查。")
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
        if res.get("ok", True):
            self.error_banner.clear()
            notify.success("体检完成：通过。")
        else:
            notify.warn("体检完成：发现异常，详情见诊断结果。")

    def _doctor_failed(self, msg: str) -> None:
        self.loading_overlay.stop()
        text = f"体检失败：{msg}"
        self.out.setPlainText(text)
        self._log(text)
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
                    "游戏内代理相关项仍需在「游戏内代理」页连接后再验证。")
        failed = [s for s in steps if not s.get("ok")]
        critical = [s for s in failed if s.get("critical", True)]
        target = critical[0] if critical else (failed[0] if failed else {})
        name = str(target.get("name") or "")
        detail = str(target.get("detail") or "").lower()
        prefix = "关键步骤失败" if critical else "非关键步骤失败"
        if "部件目录" in name or "部件图标" in name or "catalog" in detail:
            action = ("在「路径」确认数据目录含 Gagarin/ships/catalog.txt，"
                      "或设置 STARFORGE_GAMEDATA 后点「刷新列表」/重跑自检。")
        elif "存档" in name or "save" in detail:
            action = ("在「路径」选择含 save.hg 的存档目录；若存档损坏，"
                      "请用「我的船队 → 备份」恢复一份可读存档后再试。")
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
            action = ("该项是非关键项：打开游戏并在「游戏内代理」页连接后重跑自检；"
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
            notify.warn(f"诊断包已导出，但有 {len(errors)} 项失败。")
        else:
            self.error_banner.clear()
            notify.success(f"诊断已导出：{path}")

    def _export_failed(self, msg: str) -> None:
        self.loading_overlay.stop()
        text = f"导出失败：{msg}"
        self._log(text)
        self.error_banner.show_error(text)
        notify.error(text)

    def _log(self, text: str) -> None:
        self.out.append(str(text))
