"""Home：指挥舱概览页。"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ...services import get_services, history
from ..notify import toast as notify_toast
from ..widgets.page import PAGE_MARGINS
from ..widgets.page_header import PageHeader
from ..widgets.worker import run as run_worker

KIND_LABELS = {
    "search": "搜索",
    "write": "写回",
    "backup": "备份",
    "restore": "恢复",
    "scan": "扫描",
    "agent": "游戏内",
    "system": "星系",
}

STATUS_TARGETS = {
    "data": ("search", "数据层由飞船实验室使用；可先确认设置里的数据目录。"),
    "saves": ("mine", "存档用于我的船队；读取后可查看飞船与同伴。"),
    "game": ("settings", "游戏目录在设置页确认，影响预览与游戏内代理。"),
    "live": ("live", "先进游戏并载入存档，再到游戏内代理连接。"),
}


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    box = QFrame()
    box.setObjectName("card")
    v = QVBoxLayout(box)
    v.setContentsMargins(16, 14, 16, 14)
    t = QLabel(title)
    t.setObjectName("muted")
    v.addWidget(t)
    return box, v


def _activity_time(ts) -> str:
    try:
        dt = datetime.fromisoformat(str(ts or "").replace("Z", "+00:00"))
        return dt.astimezone().strftime("%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        text = str(ts or "")
        return text[5:19].replace("T", " ") if len(text) >= 19 else text or "—"


class _ActivityRow(QFrame):
    """一条最近活动；有点击目标时可直接跳到相关页面。"""

    activated = Signal(str)

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.ref = str(item.get("ref") or "")
        self.setObjectName("activityRow")
        if self.ref:
            self.setCursor(Qt.PointingHandCursor)
            self.setFocusPolicy(Qt.StrongFocus)
            self.setToolTip("点击跳转到相关页面")
        else:
            self.setFocusPolicy(Qt.NoFocus)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        when = QLabel(_activity_time(item.get("ts")))
        when.setObjectName("muted")
        head.addWidget(when)
        kind = QLabel(KIND_LABELS.get(str(item.get("kind") or ""),
                                      str(item.get("kind") or "活动")))
        kind.setObjectName("muted")
        head.addWidget(kind)
        failed = bool(item.get("failed", not item.get("ok", True)))
        result = QLabel("失败" if failed else "成功")
        result.setStyleSheet("color:%s;font-weight:600;" %
                             ("#ff7a7a" if failed else "#63d29a"))
        head.addWidget(result)
        head.addStretch(1)
        v.addLayout(head)
        title = QLabel(str(item.get("title") or "活动"))
        title.setWordWrap(True)
        v.addWidget(title)
        detail = str(item.get("detail") or "").strip()
        if detail:
            line = QLabel(detail)
            line.setObjectName("muted")
            line.setWordWrap(True)
            v.addWidget(line)

    def _activate(self) -> None:
        if self.ref:
            self.activated.emit(self.ref)

    def mouseReleaseEvent(self, event) -> None:       # noqa: N802 - Qt 回调
        if (event.button() == Qt.LeftButton and self.ref
                and self.rect().contains(event.position().toPoint())):
            self._activate()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:           # noqa: N802 - Qt 回调
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._activate()
            event.accept()
            return
        super().keyPressEvent(event)


class _StatusCard(QFrame):
    clicked = Signal()

    def __init__(self, title: str, hint: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"{title}状态卡")
        self.setToolTip(hint)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("muted")
        v.addWidget(title_label)
        self.value = QLabel("—")
        self.value.setStyleSheet("font-size:18px;font-weight:600;color:#e6ecf5;")
        v.addWidget(self.value)
        hint_label = QLabel(hint)
        hint_label.setObjectName("muted")
        hint_label.setWordWrap(True)
        v.addWidget(hint_label)

    def set_value(self, text: str, state: str = "neutral") -> None:
        colors = {"ok": "#a8e8c9", "warn": "#f0cd9a",
                  "bad": "#f3b6a7", "neutral": "#e6ecf5"}
        self.value.setText(text)
        self.value.setStyleSheet(
            "font-size:18px;font-weight:600;color:%s;" %
            colors.get(state, colors["neutral"]))

    def mouseReleaseEvent(self, event) -> None:       # noqa: N802 - Qt 回调
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:           # noqa: N802 - Qt 回调
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class HomePage(QWidget):
    navigate = Signal(str)
    openRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._loaded = False
        self._notify_refresh = False
        self._health_text = "数据层、存档、游戏状态等待刷新"
        self._agent_text = "游戏内代理状态等待刷新"
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
        root.setSpacing(12)

        header = PageHeader(
            "今日战报",
            "搜飞船、看飞船、找星系与行星、连接游戏——所有操作都在这个窗口里完成。",
        )
        refresh = QPushButton("刷新状态")
        refresh.setToolTip("重新检查数据层、存档、游戏与游戏内代理（F5）")
        refresh.clicked.connect(lambda: self.refresh(notify=True))
        header.add_action(refresh)
        root.addWidget(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.cards: dict[str, QLabel] = {}
        self.card_boxes: dict[str, _StatusCard] = {}
        for i, (key, name) in enumerate((("data", "数据层"), ("saves", "存档"),
                                         ("game", "游戏"), ("live", "游戏内代理"))):
            hint = STATUS_TARGETS[key][1]
            box = _StatusCard(name, hint)
            self.cards[key] = box.value
            self.card_boxes[key] = box
            box.clicked.connect(lambda k=key: self._open_status(k))
            grid.addWidget(box, 0, i)
        root.addLayout(grid)

        actions = QLabel("快速开始")
        actions.setStyleSheet("font-size:16px;font-weight:600;margin-top:8px;")
        root.addWidget(actions)
        quick = QGridLayout()
        quick.setHorizontalSpacing(8)
        quick.setVerticalSpacing(8)
        entries = (
            ("开始找船", "search", "", True),
            ("设计器", "designer", "打开飞船设计器（Ctrl+7）", False),
            ("我的船队", "mine", "", False),
            ("地址工作台", "systems", "地址工作台在星图页的标签栏。", False),
            ("收藏夹", "search", "收藏夹在飞船实验室右侧，可载入或管理收藏。", False),
            ("星图", "systems", "", False),
            ("连接游戏", "live", "", False),
        )
        for i, (label, key, hint, primary) in enumerate(entries):
            btn = QPushButton(label)
            if primary:
                btn.setObjectName("primary")
            if hint:
                btn.setToolTip(hint)
            btn.clicked.connect(lambda _=False, k=key, t=label: self._quick(k, t))
            quick.addWidget(btn, i // 4, i % 4)
        root.addLayout(quick)

        activity = QFrame()
        activity.setObjectName("card")
        av = QVBoxLayout(activity)
        av.setContentsMargins(16, 14, 16, 14)
        av.setSpacing(4)
        head = QHBoxLayout()
        activity_title = QLabel("最近活动")
        activity_title.setObjectName("muted")
        head.addWidget(activity_title)
        head.addStretch(1)
        self.clear_history_button = QPushButton("清空历史")
        self.clear_history_button.setObjectName("ghostButton")
        self.clear_history_button.setToolTip("清空本机的最近活动记录（不影响存档与收藏）")
        self.clear_history_button.clicked.connect(self._clear_activity)
        head.addWidget(self.clear_history_button)
        av.addLayout(head)
        self.activity_hint = QLabel("显示最近 8 条操作；点击记录可跳到相关页面。")
        self.activity_hint.setObjectName("muted")
        self.activity_hint.setWordWrap(True)
        av.addWidget(self.activity_hint)
        self.activity_list = QVBoxLayout()
        self.activity_list.setSpacing(4)
        av.addLayout(self.activity_list)
        self.activity_rows: list[_ActivityRow] = []
        self.activity_box = activity
        root.addWidget(activity)

        recent, rv = _card("最近状态")
        self.recent = QLabel("等待刷新…")
        self.recent.setObjectName("muted")
        self.recent.setWordWrap(True)
        rv.addWidget(self.recent)
        root.addWidget(recent)

        tips, tv = _card("第一次使用")
        for text in (
            "1. 设置页确认真实游戏目录与存档目录。",
            "2. 游戏内代理已内置运行时，正常安装包不需要联网安装。",
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
        self._load_activity()

    def _load_activity(self) -> None:
        while self.activity_list.count():
            entry = self.activity_list.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()
        self.activity_rows = []
        try:
            items = history.recent(8)
        except Exception:                                  # noqa: BLE001
            items = []
        if not items:
            empty = QLabel("暂无活动。搜索、写回、扫描或连接游戏后会出现在这里。")
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            self.activity_list.addWidget(empty)
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            row = _ActivityRow(item)
            row.activated.connect(self._activity_clicked)
            self.activity_list.addWidget(row)
            self.activity_rows.append(row)

    def _activity_clicked(self, ref: str) -> None:
        if ref:
            self.navigate.emit(ref)

    def _clear_activity(self) -> None:
        try:
            history.clear()
        except Exception as e:                              # noqa: BLE001
            notify_toast(f"清空历史失败：{type(e).__name__}: {e}", "error")
            return
        self._load_activity()
        notify_toast("历史已清空", "success")

    def showEvent(self, event) -> None:                   # noqa: N802 - Qt 回调
        super().showEvent(event)
        self._load_activity()

    def _quick(self, key: str, label: str) -> None:
        self.navigate.emit(key)
        if label == "地址工作台":
            self.openRequested.emit("address")
        elif label == "收藏夹":
            self.openRequested.emit("favorites")

    def _open_status(self, key: str) -> None:
        target, hint = STATUS_TARGETS[key]
        notify_toast(hint, "info")
        self.navigate.emit(target)

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self.refresh()

    def refresh(self, notify: bool = False) -> None:
        self._notify_refresh = bool(notify)
        self.recent.setText("正在刷新状态…")
        self._load_activity()
        run_worker(self.svc.health, self._apply_health, self._health_error)
        run_worker(self.svc.agent_status, self._apply_agent, self._agent_error)

    def _health_error(self, message: str) -> None:
        self._health_text = f"数据层、存档、游戏状态检查失败：{message}"
        self._update_recent()
        if self._notify_refresh:
            self._notify_refresh = False
            notify_toast(f"健康检查失败：{message}", "error")

    def _agent_error(self, message: str) -> None:
        self.cards["live"].setText(f"不可用：{message}")
        self._agent_text = f"游戏内代理不可用：{message}"
        self._update_recent()

    def _apply_health(self, h: dict) -> None:
        data_ok = bool(h.get("data_ready"))
        saves_ok = bool(h.get("saves_ready"))
        game_ok = bool(h.get("game_dir"))
        data = "就绪" if data_ok else "缺失"
        saves = "已发现" if saves_ok else "未发现"
        game = "已设置" if game_ok else "未设置"
        self.card_boxes["data"].set_value(data, "ok" if data_ok else "bad")
        self.card_boxes["saves"].set_value(saves, "ok" if saves_ok else "warn")
        self.card_boxes["game"].set_value(game, "ok" if game_ok else "warn")
        self._health_text = f"数据层{data} · 存档{saves} · 游戏{game}"
        self._update_recent()
        if self._notify_refresh:
            self._notify_refresh = False
            notify_toast("状态已刷新", "success")

    def _apply_agent(self, st: dict) -> None:
        if st.get("reachable"):
            text, state = "游戏内代理已连接", "ok"
        elif (st.get("runtime_ready") and st.get("pymhf_http_api")
              and st.get("nmspy_version") and st.get("pymhf_version")):
            text, state = "运行时就绪", "warn"
        elif st.get("runtime_ready"):
            text, state = "组件异常", "bad"
        else:
            text, state = "组件缺失", "bad"
        self.card_boxes["live"].set_value(text, state)
        self._agent_text = f"游戏内代理：{text}"
        self._update_recent()

    def _update_recent(self) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.recent.setText(f"{stamp} · {self._health_text} · {self._agent_text}")
