"""顶部状态条：数据层 / 存档 / 游戏 / 写入 四个可点击 chip。

旧壳层用不可点击的 QLabel 显示状态，用户看完仍不知道去哪里修。这里改成
按钮：点击后由壳层跳到设置里的对应卡片，并聚焦相关控件。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton

from ..theme import SPACE_XXS

CHIP_DEFS = (
    ("data", "数据层", "打开设置中的路径与数据目录"),
    ("saves", "存档", "打开设置中的存档目录"),
    ("game", "游戏", "打开设置中的游戏目录"),
    ("write", "写入", "打开设置中的安全与写入开关"),
)


_LABELS = {key: label for key, label, _hint in CHIP_DEFS}
_HINTS = {key: hint for key, _label, hint in CHIP_DEFS}


def _repolish(widget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


class RfStatusStrip(QFrame):
    chipClicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusStrip")
        self.setAccessibleName("运行状态")
        self.setToolTip("点击任一状态可跳到设置中的对应项")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACE_XXS)
        self.chips: dict[str, QPushButton] = {}
        for key, label, hint in CHIP_DEFS:
            chip = QPushButton(label)
            chip.setObjectName("statusChip")
            chip.setAccessibleName(f"{label}状态：检查中")
            chip.setToolTip(hint)
            chip.setStatusTip(hint)
            chip.setFocusPolicy(Qt.StrongFocus)
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(
                lambda _checked=False, k=key: self.chipClicked.emit(k))
            self.chips[key] = chip
            h.addWidget(chip)

    def set_health(self, health: dict | None) -> None:
        health = health if isinstance(health, dict) else {}
        data_ok = bool(health.get("data_ready"))
        saves_ok = bool(health.get("saves_ready"))
        game_ok = bool(health.get("game_dir"))
        write_on = bool(health.get("write_enabled"))
        specs = (
            ("data", "数据层 ✓" if data_ok else "数据层 ×",
             "ok" if data_ok else "bad"),
            ("saves", "存档 ✓" if saves_ok else "存档 ×",
             "ok" if saves_ok else "warn"),
            ("game", "游戏 ✓" if game_ok else "游戏未设置",
             "ok" if game_ok else "warn"),
            ("write", "写入已开" if write_on else "只读",
             "warn" if write_on else "ok"),
        )
        for key, text, state in specs:
            chip = self.chips[key]
            chip.setText(text)
            label = _LABELS[key]
            hint = _HINTS[key]
            chip.setAccessibleName(f"{label}状态：{text}，{hint}")
            chip.setToolTip(f"{label}状态：{text}。{hint}")
            chip.setStatusTip(f"{label}状态：{text}。{hint}")
            chip.setProperty("state", state)
            _repolish(chip)


__all__ = ["CHIP_DEFS", "RfStatusStrip"]
