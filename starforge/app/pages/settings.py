"""设置与诊断：Card 布局，原生路径选择。"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
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
        self.out.setPlaceholderText("体检结果会以结构化文本显示在这里。")
        diag.add(self.out)
        self.doctor_output = self.out
        root.addWidget(diag)

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
