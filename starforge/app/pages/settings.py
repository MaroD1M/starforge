"""设置与诊断：Card 布局，原生路径选择。"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QTextEdit, QVBoxLayout,
                               QWidget)

from ...core import paths, settings as settings_core
from ...services import get_services
from .. import notify, theme
from ..widgets.feedback import EmptyState, ErrorBanner, LoadingOverlay
from ..widgets.page_header import PageHeader
from ..widgets.ui import Card, muted
from ..widgets.worker import run as run_worker


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
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self.header = PageHeader(
            "设置与诊断",
            "管理游戏路径、安全写入、界面氛围，并运行环境体检与导出诊断。")
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

        safety = Card("安全", "写入默认关闭；每次写入仍需确认")
        self.write = QCheckBox("允许写入存档")
        self.write.toggled.connect(self._save)
        safety.add(self.write)
        safety.add(muted("写入流程：备份 → 原子写入 → 读回校验 → 失败回滚。"))
        root.addWidget(safety)

        look = Card("界面氛围", "无人深空风格 / 中性")
        self.atmosphere = QCheckBox("无人深空风格（深空渐变 · 琥珀/青点缀）")
        self.atmosphere.setToolTip("取消勾选即回到中性深色主题")
        self.atmosphere.toggled.connect(self._atmosphere_changed)
        look.add(self.atmosphere)
        look.add(muted("可选，不影响数据可读性。"))
        root.addWidget(look)

        diag = Card("诊断", "可复制/导出的诊断数据（JSON 格式）")
        row2 = QHBoxLayout()
        doctor = QPushButton("运行体检")
        doctor.clicked.connect(self._doctor)
        row2.addWidget(doctor)
        export = QPushButton("导出诊断")
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
                self.atmosphere.setChecked(bool(s.get("atmosphere",
                                                      settings_core.current().atmosphere)))
            finally:
                self._syncing = False
            self._update_path_empty()
            self.error_banner.clear()

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

    def _save(self) -> None:
        try:
            atmosphere = self.atmosphere.isChecked()
            self.svc.update_settings(game_dir=self.game.text().strip(),
                                     saves_dir=self.saves.text().strip(),
                                     write_enabled=self.write.isChecked(),
                                     atmosphere=atmosphere)
            theme.set_atmosphere(atmosphere)
            self._update_path_empty()
            self.error_banner.clear()
            self._log("设置已保存")
            notify.success("设置已保存。")
        except Exception as e:                              # noqa: BLE001
            text = f"保存失败：{type(e).__name__}: {e}"
            self._log(text)
            self.error_banner.show_error(text)
            notify.error(text)

    def _atmosphere_changed(self, on: bool) -> None:
        if getattr(self, "_syncing", False):
            return
        try:
            self.svc.update_settings(atmosphere=bool(on))
            theme.set_atmosphere(bool(on))
            self._log("界面氛围已切换为无人深空风格。" if on
                      else "界面氛围已切换为中性深色主题。")
            self.error_banner.clear()
            notify.success("已切换为无人深空风格。" if on
                           else "已切换为中性深色主题。")
        except Exception as e:                              # noqa: BLE001
            text = f"切换氛围失败：{type(e).__name__}: {e}"
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
        path, _ = QFileDialog.getSaveFileName(self, "导出诊断", "starforge-diagnostics.json",
                                              "JSON (*.json)")
        if not path:
            notify.warn("已取消导出诊断。")
            return
        self.loading_overlay.start("正在导出诊断…")
        notify.toast("正在导出诊断…")

        def doctor_done(doc: dict) -> None:
            try:
                payload = {"health": self.svc.health(),
                           "settings": self.svc.settings_snapshot(), "doctor": doc}
                Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                      "utf-8")
            except Exception as e:                          # noqa: BLE001
                doctor_failed(f"{type(e).__name__}: {e}")
                return
            self.loading_overlay.stop()
            self._log(f"诊断已导出：{path}")
            self.error_banner.clear()
            notify.success(f"诊断已导出：{path}")

        def doctor_failed(msg: str) -> None:
            self.loading_overlay.stop()
            text = f"导出失败：{msg}"
            self._log(text)
            self.error_banner.show_error(text)
            notify.error(text)

        run_worker(self.svc.doctor, doctor_done, doctor_failed)

    def _log(self, text: str) -> None:
        self.out.append(str(text))
