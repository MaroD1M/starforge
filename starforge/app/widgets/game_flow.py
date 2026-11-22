"""联动页的三步骤面板：① 运行时/组件 → ② 游戏连接 → ③ 模板 Mod。

每个步骤固定包含：序号、状态 chip、一行状态、一个主按钮（+ 可选次按钮）。
状态色只表达「完成 / 进行中 / 待完成 / 需处理」，避免页面再叠一层说明文字。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import SPACE_S, SPACE_XS

STATES = {
    "done": ("完成", "ok"),
    "current": ("进行中", "warn"),
    "waiting": ("待完成", ""),
    "error": ("需处理", "bad"),
}

_PANEL_QSS = """
QFrame#stepPanel {
    background: #0f141d;
    border: 1px solid #1e2432;
    border-radius: 10px;
}
QFrame#stepPanel[state="done"] { border-color: #1d4a38; background: #0e1c17; }
QFrame#stepPanel[state="current"] { border-color: #2f6fd0; background: #101a2b; }
QFrame#stepPanel[state="error"] { border-color: #4d2a22; background: #1d1210; }
QLabel#stepIndex { color: #8b95a7; font-size: 15px; font-weight: 700; }
QFrame#stepPanel[state="done"] QLabel#stepIndex { color: #a8e8c9; }
QFrame#stepPanel[state="current"] QLabel#stepIndex { color: #7fb6ff; }
QFrame#stepPanel[state="error"] QLabel#stepIndex { color: #f3b6a7; }
QLabel#stepTitle { color: #e6ecf5; font-size: 13px; font-weight: 700; }
"""


def _refresh(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


class StepPanel(QFrame):
    """单个步骤：状态色 + 状态文本 + 一个主按钮。"""

    def __init__(self, index: int, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("stepPanel")
        self.setProperty("state", "waiting")
        self.setStyleSheet(_PANEL_QSS)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setAccessibleName(f"第 {index} 步：{title}")

        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE_S, SPACE_S, SPACE_S, SPACE_S)
        v.setSpacing(SPACE_XS)

        top = QHBoxLayout()
        top.setSpacing(SPACE_XS)
        self.index_label = QLabel(str(index))
        self.index_label.setObjectName("stepIndex")
        top.addWidget(self.index_label)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("stepTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.title_label, 1)
        self.chip = QLabel("待完成")
        self.chip.setObjectName("chip")
        self.chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        top.addWidget(self.chip)
        v.addLayout(top)

        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(0)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(self.status, 1)

        self.action = QPushButton("")
        self.action.setFocusPolicy(Qt.StrongFocus)
        self.action.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        v.addWidget(self.action)

        self.alt = QPushButton("")
        self.alt.setObjectName("ghostButton")
        self.alt.setFocusPolicy(Qt.StrongFocus)
        self.alt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.alt.setVisible(False)
        self._alt_callback = None
        self.alt.clicked.connect(self._run_alt)
        v.addWidget(self.alt)

    # ---------------------------------------------------------------- 状态

    def set_state(self, state: str, status: str = "",
                  action_text: str | None = None,
                  action_tooltip: str = "") -> None:
        state = state if state in STATES else "waiting"
        label, chip_state = STATES[state]
        self.setProperty("state", state)
        self.chip.setText(label)
        self.chip.setProperty("state", chip_state)
        self.status.setText(str(status or ""))
        self.status.setToolTip(str(status or ""))
        self.setAccessibleName(
            f"第 {self.index_label.text()} 步：{self.title_label.text()}，{label}")
        if action_text is not None:
            self.action.setText(str(action_text))
        self.action.setToolTip(action_tooltip or str(action_text or ""))
        # 只有「当前要做的这一步」用主按钮高亮；其余保持可点但不抢注意力。
        if state in ("current", "error"):
            role = "primary"
        elif state == "done":
            role = "ghostButton"
        else:
            role = ""
        if self.action.objectName() != role:
            self.action.setObjectName(role)
            _refresh(self.action)
        _refresh(self)

    def set_status(self, text: str) -> None:
        self.status.setText(str(text or ""))
        self.status.setToolTip(str(text or ""))

    def set_alt(self, text: str, tooltip: str = "", callback=None) -> None:
        self.alt.setText(str(text or ""))
        self.alt.setToolTip(tooltip or str(text or ""))
        self.alt.setVisible(bool(text))
        self._alt_callback = callback

    def _run_alt(self) -> None:
        if callable(self._alt_callback):
            self._alt_callback()


__all__ = ["STATES", "StepPanel"]
