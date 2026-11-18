"""Home：指挥舱概览页。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ...services import get_services
from ..widgets.worker import run as run_worker


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    box = QFrame()
    box.setObjectName("card")
    v = QVBoxLayout(box)
    v.setContentsMargins(16, 14, 16, 14)
    t = QLabel(title)
    t.setObjectName("muted")
    v.addWidget(t)
    return box, v


class HomePage(QWidget):
    navigate = Signal(str)

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
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(16)

        title = QLabel("今日战报")
        title.setStyleSheet("font-size:24px;font-weight:700;")
        root.addWidget(title)
        sub = QLabel("搜船、看船、找星球、连接游戏——所有动作都在这个窗口里完成。")
        sub.setObjectName("muted")
        root.addWidget(sub)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.cards: dict[str, QLabel] = {}
        for i, (key, name) in enumerate((("data", "数据层"), ("saves", "存档"),
                                         ("game", "游戏"), ("live", "游戏内通道"))):
            box, v = _card(name)
            value = QLabel("—")
            value.setStyleSheet("font-size:18px;font-weight:600;")
            self.cards[key] = value
            v.addWidget(value)
            grid.addWidget(box, 0, i)
        root.addLayout(grid)

        actions = QLabel("快速开始")
        actions.setStyleSheet("font-size:16px;font-weight:600;margin-top:8px;")
        root.addWidget(actions)
        row = QHBoxLayout()
        for label, key, primary in (("开始找船", "search", True), ("我的船队", "mine", False),
                                    ("星图", "systems", False), ("连接游戏", "live", False)):
            btn = QPushButton(label)
            if primary:
                btn.setObjectName("primary")
            btn.clicked.connect(lambda _=False, k=key: self.navigate.emit(k))
            row.addWidget(btn)
        row.addStretch(1)
        root.addLayout(row)

        tips, tv = _card("第一次使用")
        for text in (
            "1. 设置页确认真实游戏目录与存档目录。",
            "2. 游戏内通道已内置运行时，正常包不需要联网安装。",
            "3. 先进游戏并载入存档，再点「连接游戏」。",
            "4. 传送/扫描属于高风险写操作，先备份存档。",
        ):
            line = QLabel(text)
            line.setObjectName("muted")
            tv.addWidget(line)
        root.addWidget(tips)
        root.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll)

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self.refresh()

    def refresh(self) -> None:
        run_worker(self.svc.health, self._apply_health, lambda _m: None)
        run_worker(self.svc.agent_status, self._apply_agent,
                   lambda m: self.cards["live"].setText(f"不可用：{m}"))

    def _apply_health(self, h: dict) -> None:
        self.cards["data"].setText("就绪" if h.get("data_ready") else "缺失")
        self.cards["saves"].setText("已发现" if h.get("saves_ready") else "未发现")
        self.cards["game"].setText("已设置" if h.get("game_dir") else "未设置")

    def _apply_agent(self, st: dict) -> None:
        if st.get("reachable"):
            self.cards["live"].setText("agent 已连接")
        elif st.get("runtime_ready"):
            self.cards["live"].setText("运行时就绪")
        else:
            self.cards["live"].setText("组件缺失")
