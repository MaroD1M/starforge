"""设置/诊断页：路径、写入开关、原生环境体检。"""
from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...services import get_services
from ..widgets.worker import run as run_worker


def _path_row(edit: QLineEdit, kind: str) -> QWidget:
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(edit, 1)
    btn = QPushButton("浏览…")

    def pick() -> None:
        if kind == "save":
            p, _ = QFileDialog.getOpenFileName(box, "选择存档", edit.text(), "存档 (*.hg);;所有文件 (*)")
        else:
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
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(16, 16, 16, 16)

        paths = QGroupBox("路径（多数情况可自动检测）")
        form = QFormLayout(paths)
        self.game = QLineEdit()
        self.game.setPlaceholderText("游戏根目录（含 Binaries/NMS.exe）")
        form.addRow("游戏目录", _path_row(self.game, "dir"))
        self.saves = QLineEdit()
        self.saves.setPlaceholderText("存档目录（含 save.hg）")
        form.addRow("存档目录", _path_row(self.saves, "dir"))
        self.gamedata = QLineEdit()
        self.gamedata.setPlaceholderText("可选：Gagarin GAMEDATA；留空则从游戏资源推导")
        form.addRow("数据目录", _path_row(self.gamedata, "dir"))
        row = QHBoxLayout()
        auto = QPushButton("自动检测")
        auto.clicked.connect(self._autodetect)
        row.addWidget(auto)
        save = QPushButton("保存")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        row.addWidget(save)
        form.addRow("", row)
        root.addWidget(paths)

        safety = QGroupBox("安全")
        sv = QVBoxLayout(safety)
        self.write = QCheckBox("允许写入存档（默认关闭；每次写入仍需确认）")
        self.write.toggled.connect(self._save)
        sv.addWidget(self.write)
        sv.addWidget(QLabel("写入流程：备份 → 原子写 → 读回校验 → 失败回滚。"))
        root.addWidget(safety)

        diag = QGroupBox("环境体检")
        dv = QVBoxLayout(diag)
        row2 = QHBoxLayout()
        self.doctor_btn = QPushButton("运行体检")
        self.doctor_btn.clicked.connect(self._doctor)
        row2.addWidget(self.doctor_btn)
        row2.addStretch(1)
        dv.addLayout(row2)
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setMinimumHeight(260)
        dv.addWidget(self.out)
        root.addWidget(diag)

        about = QGroupBox("关于")
        av = QVBoxLayout(about)
        av.addWidget(QLabel("starforge 原生界面（PySide6）· Windows 10/11"))
        av.addWidget(QLabel("只监听本机；不联网；默认只读；写入前自动备份。"))
        root.addWidget(about)
        root.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll)

    # ---------------------------------------------------------------- 状态

    def _load(self) -> None:
        def done(res: dict) -> None:
            s = res.get("settings") or {}
            r = res.get("resolved") or {}
            self.game.setText(s.get("game_dir") or r.get("game_dir") or "")
            self.saves.setText(s.get("saves_dir") or r.get("saves_dir") or "")
            self.gamedata.setText(s.get("gamedata_dir") or r.get("gamedata_dir") or "")
            self.write.setChecked(bool(s.get("write_enabled")))

        run_worker(self.svc.settings_snapshot, done, lambda m: self._log(m))

    def _save(self) -> None:
        kw = {"game_dir": self.game.text().strip(),
              "saves_dir": self.saves.text().strip(),
              "gamedata_dir": self.gamedata.text().strip(),
              "write_enabled": self.write.isChecked()}
        try:
            self.svc.update_settings(**kw)
            self._log("设置已保存")
        except Exception as e:                              # noqa: BLE001
            self._log(f"保存失败：{type(e).__name__}: {e}")

    def _autodetect(self) -> None:
        self._log("自动检测中…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            self._load()

        run_worker(self.svc.autodetect, done, lambda m: self._log(m), True)

    def _doctor(self) -> None:
        self.doctor_btn.setEnabled(False)
        self._log("体检中…")

        def done(res: dict) -> None:
            self._log(json.dumps(res, ensure_ascii=False, indent=1))
            self.doctor_btn.setEnabled(True)

        def fail(msg: str) -> None:
            self._log(f"体检失败：{msg}")
            self.doctor_btn.setEnabled(True)

        run_worker(self.svc.doctor, done, fail)

    def _log(self, text: str) -> None:
        self.out.append(str(text))
