"""把设计器种子写入存档：新船槽或替换现有槽，可选涂装。

写入由 ``Services.apply_design`` 完成：使用 Shipwright 已验证的 ``create_ship`` /
``set_ship_seed`` / ``set_ship_model`` / ``set_ship_paint``，并走备份、二次确认、
读回校验与失败回滚。这里只负责选择目标与展示结果。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...services import get_services
from ..widgets.worker import run as run_worker


def _rgb(colour: QColor) -> list[float]:
    return [colour.redF(), colour.greenF(), colour.blueF()]


from ..dialogs.confirm import ask_write

class DesignWriteDialog(QDialog):
    def __init__(self, design: dict, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self.design = dict(design or {})
        self.result: dict | None = None
        self._busy = False
        self._primary = QColor("#c9c9c9")
        self._accent = QColor("#5a6474")
        self.setWindowTitle("写入设计到存档")
        self.resize(640, 520)
        self._build_ui()
        self._load_default()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        title = QLabel(f"写入设计：{self.design.get('name') or '未命名'}")
        title.setStyleSheet("font-size:15px;font-weight:700;")
        root.addWidget(title)

        seeds = self.design.get("found_seeds") or []
        ship = self.design.get("ship") or ""
        seed = seeds[0] if seeds else ""
        info = QLabel(f"船型 {ship} · 种子 {seed} · {len(self.design.get('want') or [])} 个部件")
        info.setObjectName("muted")
        info.setWordWrap(True)
        root.addWidget(info)

        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("save.hg")
        row.addWidget(self.path, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        load = QPushButton("读取槽位")
        load.clicked.connect(self._load)
        row.addWidget(load)
        root.addLayout(row)

        form = QFormLayout()
        self.target = QComboBox()
        self.target.addItem("新建飞船（第一个空槽）", "new")
        form.addRow("目标", self.target)
        self.name = QLineEdit(self.design.get("name") or "")
        self.name.setPlaceholderText("新飞船名称；留空使用船型名")
        form.addRow("名称", self.name)
        root.addLayout(form)

        paint_row = QHBoxLayout()
        self.paint_on = QCheckBox("同时涂装")
        self.paint_on.setToolTip("使用 Shipwright 已验证的 ShipOwnership 涂装字段；仅槽位 0–11")
        self.paint_on.toggled.connect(self._update_paint_buttons)
        paint_row.addWidget(self.paint_on)
        self.primary_btn = QPushButton("主色")
        self.primary_btn.clicked.connect(lambda: self._pick_colour("primary"))
        paint_row.addWidget(self.primary_btn)
        self.accent_btn = QPushButton("副色")
        self.accent_btn.clicked.connect(lambda: self._pick_colour("accent"))
        paint_row.addWidget(self.accent_btn)
        self.palette = QComboBox()
        self.palette.addItem("FREIGHTER（含纯黑）", "FREIGHTER")
        self.palette.addItem("SHIP", "SHIP")
        self.palette.setToolTip("SHIP 调色板没有纯黑；FREIGHTER 会给最近的黑色")
        paint_row.addWidget(self.palette)
        paint_row.addStretch(1)
        root.addLayout(paint_row)

        self.copy = QCheckBox("写入副本（save.edited.hg），原档保持不动")
        self.copy.setChecked(True)
        root.addWidget(self.copy)

        self.status = QLabel("选择目标后写入；会先备份，写后读回校验。")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.ok = QPushButton("确认写入")
        self.ok.setObjectName("primary")
        self.ok.setToolTip("校验设计种子后写入；失败会自动回滚")
        self.ok.clicked.connect(self._apply)
        buttons.addWidget(self.ok)
        root.addLayout(buttons)
        self._update_paint_buttons()

    def _update_paint_buttons(self) -> None:
        on = self.paint_on.isChecked()
        for widget in (self.primary_btn, self.accent_btn, self.palette):
            widget.setEnabled(on)
        self.primary_btn.setStyleSheet(
            f"border-color:{self._primary.name()};" if on else "")

    def _pick_colour(self, which: str) -> None:
        current = self._primary if which == "primary" else self._accent
        colour = QColorDialog.getColor(current, self, "选择涂装颜色")
        if not colour.isValid():
            return
        if which == "primary":
            self._primary = colour
        else:
            self._accent = colour
        self._update_paint_buttons()

    # ---------------------------------------------------------------- 数据

    def _load_default(self) -> None:
        def done(res: dict) -> None:
            path = str(res.get("path") or "")
            if path:
                self.path.setText(path)
                self._load()

        run_worker(self.svc.default_save, done,
                   lambda msg: self.status.setText(f"没有默认存档：{msg}"))

    def _browse(self) -> None:
        start = self.path.text()
        if start and not Path(start).is_file():
            start = str(Path(start).parent) if Path(start).parent.exists() else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择存档", start, "存档 (*.hg);;所有文件 (*)")
        if path:
            self.path.setText(path)
            self._load()

    def _load(self) -> None:
        path = self.path.text().strip() or None
        self.status.setText("读取存档槽位…")
        self.target.clear()
        self.target.addItem("新建飞船（第一个空槽）", "new")

        def done(res: dict) -> None:
            ships = res.get("ships") or []
            for ship in ships:
                slot = ship.get("slot")
                if slot is None:
                    continue
                label = (f"槽位 {slot} · {ship.get('type_label') or ship.get('type') or ''}"
                         f" · {ship.get('name') or ship.get('seed') or ''}")
                self.target.addItem(label, slot)
            self.status.setText(f"{res.get('path')} · 现有 {len(ships)} 艘；"
                                "新建会使用第一个空槽")

        def fail(msg: str) -> None:
            self.status.setText(f"读取失败：{msg}")

        run_worker(self.svc.ships, done, fail, path)

    def _apply(self) -> None:
        if self._busy:
            return
        path = self.path.text().strip()
        seeds = [s for s in self.design.get("found_seeds") or [] if s]
        if not path:
            QMessageBox.information(self, "写入设计", "先选择存档")
            return
        if not seeds:
            QMessageBox.information(self, "写入设计", "这个设计没有可用种子")
            return
        target = self.target.currentData()
        paint = None
        if self.paint_on.isChecked():
            paint = {"primary": _rgb(self._primary), "accent": _rgb(self._accent),
                     "palette": self.palette.currentData()}
        what = "新建飞船" if target == "new" else f"替换槽位 {target}"
        if not ask_write(self, "确认写入",
                f"将{what}，船型 {self.design.get('ship')}，种子 {seeds[0]}。\n"
                "会先备份，写后读回校验；失败自动回滚。继续？",):
            return
        self._busy = True
        self.ok.setEnabled(False)
        self.status.setText("写入中…")

        def done(res: dict) -> None:
            self._busy = False
            self.result = res or {}
            self.status.setText(
                f"写入成功 · {self.result.get('after', {}).get('what', '')} · "
                f"备份 {self.result.get('backup')}")
            QMessageBox.information(
                self, "写入成功",
                f"{self.result.get('after', {}).get('what', '')} 已写入，读回校验通过。\n"
                f"备份：{self.result.get('backup')}")
            self.accept()

        def fail(msg: str) -> None:
            self._busy = False
            self.ok.setEnabled(True)
            self.status.setText(f"写入失败：{msg}")
            QMessageBox.warning(self, "写入失败", msg)

        run_worker(self.svc.apply_design, done, fail, path,
                   str(self.design.get("ship") or ""), seeds[0], target,
                   self.name.text().strip(), self.design.get("want") or [],
                   paint, True, self.copy.isChecked())


__all__ = ["DesignWriteDialog"]
