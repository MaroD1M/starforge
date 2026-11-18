"""船级/属性编辑：改 C/B/A/S、best、逐项属性，写回前二次确认。

所有写入都走 ``Services.apply_class``，由存档层负责备份、原子写、读回校验与回滚。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...services import get_services
from ..widgets.worker import run as run_worker

STAT_LABELS = {
    "damage": "伤害",
    "shield": "护盾",
    "hyperdrive": "超光速",
    "agility": "机动",
}
STAT_ORDER = ("damage", "shield", "hyperdrive", "agility")
CLASS_ORDER = ("C", "B", "A", "S")


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def stat_rows(stats: dict | None) -> list[dict]:
    """把存档摘要里的 stats 整理成稳定的显示行（纯数据，便于测试）。"""
    data = stats or {}
    keys = [k for k in STAT_ORDER if k in data]
    if not keys:
        keys = list(STAT_ORDER)
    return [{"key": k, "label": STAT_LABELS.get(k, k),
             "value": _number(data.get(k))} for k in keys]


def changed_values(current: dict | None, edited: dict | None) -> dict:
    """只提交用户真的改过的属性；值未变时返回空字典。"""
    old = current or {}
    out = {}
    for key, value in (edited or {}).items():
        if value is None:
            continue
        try:
            new = float(value)
        except (TypeError, ValueError):
            continue
        if key not in old or abs(new - _number(old.get(key))) > 1e-9:
            out[key] = new
    return out


def stat_summary(values: dict | None) -> str:
    """把属性字典格式化成一行中文摘要（确认框/状态栏共用）。"""
    bits = []
    for key in STAT_ORDER:
        if key in (values or {}):
            bits.append(f"{STAT_LABELS.get(key, key)} {_number(values[key]):g}")
    return " · ".join(bits) or "无"


class ClassEditorDialog(QDialog):
    """读取当前船的等级/属性，允许修改后安全写回。"""

    def __init__(self, save_path: str, ship: dict, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self.save_path = str(save_path or "")
        self.ship = dict(ship or {})
        self.changed = False
        self.result: dict | None = None
        self._current_stats = {
            key: _number(value) for key, value in (self.ship.get("stats") or {}).items()}
        self._spins: dict[str, QDoubleSpinBox] = {}
        self.setWindowTitle("船级 / 属性")
        self.resize(620, 520)
        self._build_ui()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)

        title = QLabel(f"{self.ship.get('type_label') or self.ship.get('type') or '飞船'}  "
                       f"{self.ship.get('seed') or ''}")
        title.setStyleSheet("font-size:15px;font-weight:700;")
        root.addWidget(title)

        self.where = QLabel(
            f"存档：{self.save_path or '未选择'}\n槽位：{self.ship.get('slot', '?')}  ·  "
            f"当前等级：{self.ship.get('ship_class') or '未知'}")
        self.where.setObjectName("muted")
        self.where.setWordWrap(True)
        self.where.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.where)

        warn = QLabel("写入会先自动备份；写后读回校验，失败自动回滚。"
                      "属性越界会被拒绝，不会造出游戏不可能给出的数值。")
        warn.setObjectName("muted")
        warn.setWordWrap(True)
        root.addWidget(warn)

        form = QFormLayout()
        self.class_box = QComboBox()
        self.class_box.addItem("保持不变", "")
        for name in CLASS_ORDER:
            self.class_box.addItem(f"{name} 级", name)
        current = str(self.ship.get("ship_class") or "").upper()
        index = self.class_box.findData(current)
        self.class_box.setCurrentIndex(max(index, 0))
        form.addRow("船级", self.class_box)
        root.addLayout(form)

        self.best = QCheckBox("最佳属性（best=true，按当前/新等级取各属性上限）")
        self.best.setToolTip("勾选后由游戏区间自动取上限；下面手填的属性不会提交。")
        self.best.toggled.connect(self._set_stats_enabled)
        root.addWidget(self.best)

        stats_box = QWidget()
        stats_form = QFormLayout(stats_box)
        stats_form.setContentsMargins(0, 8, 0, 0)
        for row in stat_rows(self._current_stats):
            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            spin.setRange(0.0, 1_000_000.0)
            spin.setSingleStep(0.1)
            spin.setValue(row["value"])
            spin.setToolTip("只提交改动过的项；留成当前值表示不改")
            stats_form.addRow(row["label"], spin)
            self._spins[row["key"]] = spin
        root.addWidget(stats_box)

        hint = QLabel("提示：只提交你改动过的属性；等级可选 C / B / A / S。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.copy = QCheckBox("写入副本（save.edited.hg），不动原档")
        self.copy.setChecked(True)
        self.copy.setToolTip("原档始终保留；副本可改名成 save.hg / save2.hg 后进游戏验证")
        root.addWidget(self.copy)

        self.status = QLabel("修改后点「写入存档」。")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.ok = QPushButton("写入存档")
        self.ok.setObjectName("primary")
        self.ok.clicked.connect(self._apply)
        buttons.addWidget(self.ok)
        root.addLayout(buttons)

    def _set_stats_enabled(self, best: bool) -> None:
        for spin in self._spins.values():
            spin.setEnabled(not best)

    # ---------------------------------------------------------------- 数据

    def edited_stats(self) -> dict:
        return {key: spin.value() for key, spin in self._spins.items()}

    def values_to_write(self) -> dict:
        if self.best.isChecked():
            return {}
        return changed_values(self._current_stats, self.edited_stats())

    def _confirmation(self, ship_class: str, values: dict, best: bool) -> str:
        before = self.ship.get("ship_class") or "未知"
        lines = [
            f"存档：{self.save_path}",
            f"槽位：{self.ship.get('slot')}",
            f"船级：{before} → {ship_class or '保持不变'}",
        ]
        if best:
            lines.append("属性：按等级取最佳（best=true）")
        elif values:
            lines.append(f"属性：{stat_summary(values)}")
        else:
            lines.append("属性：保持不变")
        lines.append("会先自动备份，写后读回校验；失败自动回滚。")
        if self.copy.isChecked():
            lines.append("将写入副本 save.edited.hg（原档不动）。")
        lines.append("\n确定写入？")
        return "\n".join(lines)

    def _apply(self) -> None:
        slot = self.ship.get("slot")
        if slot is None:
            QMessageBox.warning(self, "无法写入", "这艘船没有可写的槽位。")
            return
        ship_class = str(self.class_box.currentData() or "")
        values = self.values_to_write()
        best = self.best.isChecked()
        if not ship_class and not values and not best:
            QMessageBox.information(self, "没有改动", "等级、属性和 best 都没有改动。")
            return
        if QMessageBox.warning(
                self, "确认写入",
                self._confirmation(ship_class, values, best),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return

        self.ok.setEnabled(False)
        self.status.setText("写入中…（备份 → 原子写 → 读回校验）")

        def done(res: dict) -> None:
            self.changed = True
            self.result = res
            before = (res.get("before") or {}).get("class") or "?"
            after = (res.get("after") or {}).get("class") or "?"
            backup = res.get("backup") or ""
            target = res.get("path") or self.save_path
            self.status.setText(
                f"写入成功 · 等级 {before} → {after} · 备份 {os.path.basename(str(backup))}")
            note = "（副本，原档未动）" if res.get("copy") else ""
            QMessageBox.information(
                self, "写入成功",
                f"槽位 {res.get('slot', slot)} 已更新{note}。\n"
                f"文件：{target}\n备份：{backup}\n"
                f"等级：{before} → {after}\n"
                f"其它船种子未动：{res.get('ships_untouched', True)}")
            self.accept()

        def fail(msg: str) -> None:
            self.ok.setEnabled(True)
            self.status.setText(f"写入失败：{msg}")
            QMessageBox.warning(
                self, "写入失败",
                f"{msg}\n\n未完成的写入会自动回滚；如仍异常，请用「备份 / 恢复…」还原。")

        run_worker(self.svc.apply_class, done, fail, self.save_path, int(slot),
                   ship_class, values or None, best, True, self.copy.isChecked())
