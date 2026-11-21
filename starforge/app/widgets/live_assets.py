"""实时资产只读卡片：多功能工具 / 货船与舰队 / 同伴。

数据全部来自游戏内代理的只读端点（``/multitool``、``/freighter``、``/pets``）。
这里只做展示整理：缺字段给中文占位，空槽用「—」，不猜测任何会写回游戏的数据。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .ui import Card, muted

BLOCKS = ("multitool", "freighter", "pets")
BLOCK_LABELS = {
    "multitool": "多功能工具",
    "freighter": "货船与舰队",
    "pets": "同伴",
}
WAITING_TEXT = "尚未连接游戏内代理；连接并载入存档后自动读取。"
NO_SAVE_TEXT = "游戏还没进入存档；载入存档后自动读取。"
LOADING_TEXT = "读取中…"
EMPTY = "—"
DEFAULT_PET_SOURCE = ""

_CURRENT_STYLE = (
    "QLabel#liveAssetCurrent {"
    " background:#152238; border:1px solid #2f6fd0; border-radius:6px;"
    " padding:4px 6px; color:#e6ecf5; font-weight:700; }"
)


def _text(value: Any, fallback: str = EMPTY) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _num(value: Any, fallback: str = EMPTY) -> str:
    if value is None or value == "":
        return fallback
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return _text(value, fallback)


def _slots(payload: dict | None) -> list[dict]:
    rows = (payload or {}).get("slots")
    return [row for row in rows or [] if isinstance(row, dict)]


def multitool_summary(payload: dict | None) -> str:
    """「6 槽 · 实际 3 把 · 当前槽 0」；没有槽数据时明确说明。"""
    payload = payload or {}
    slots = _slots(payload)
    if not slots:
        return "代理没有返回多功能工具槽数据。"
    owned = payload.get("count")
    if not isinstance(owned, int):
        owned = sum(1 for row in slots if not row.get("empty"))
    current = payload.get("current_slot")
    current_text = _num(current, EMPTY)
    return f"{len(slots)} 槽 · 实际 {owned} 把 · 当前槽 {current_text}"


def multitool_slots(payload: dict | None) -> list[dict]:
    """每行：槽号、展示文本、是否空槽、是否当前槽。"""
    payload = payload or {}
    current = payload.get("current_slot")
    rows: list[dict] = []
    for index, slot in enumerate(_slots(payload)):
        number = slot.get("slot", index)
        is_current = current is not None and number == current
        if slot.get("empty"):
            rows.append({"slot": number, "text": f"槽 {_num(number)}    {EMPTY}",
                         "empty": True, "current": is_current})
            continue
        inventory = slot.get("inventory") or {}
        filled = _num(inventory.get("filled"))
        capacity = _num(inventory.get("capacity"))
        rows.append({
            "slot": number,
            "text": (f"槽 {_num(number)}    {_text(slot.get('name'), '（未命名）')} · "
                     f"{_text(slot.get('class'))} 级 · 种子 {_text(slot.get('seed'))} · "
                     f"库存 {filled}/{capacity}"),
            "empty": False,
            "current": is_current,
        })
    return rows


def _inventory_text(inventory: dict | None) -> str:
    inventory = inventory or {}
    if not inventory:
        return EMPTY
    return f"{_num(inventory.get('filled'))}/{_num(inventory.get('capacity'))}"


def freighter_summary(payload: dict | None) -> str:
    """货船名称/等级/库存摘要；未持有时写「未持有货船」。"""
    freighter = (payload or {}).get("freighter") or {}
    if not freighter.get("owned"):
        return "未持有货船"
    inventory = freighter.get("inventory") or {}
    return (f"名称：{_text(freighter.get('name'), '（未命名货船）')} · "
            f"等级 {_text(freighter.get('class'))} · "
            f"库存 {_inventory_text(inventory)}")


def frigate_lines(payload: dict | None, limit: int = 3) -> list[str]:
    """护卫舰数量 + 前几条（名称/等级），不补造条目。"""
    payload = payload or {}
    frigates = [row for row in payload.get("frigates") or [] if isinstance(row, dict)]
    count = payload.get("frigate_count")
    if not isinstance(count, int):
        count = len(frigates)
    lines = [f"护卫舰：{count} 艘"]
    for index, row in enumerate(frigates[:max(0, int(limit))]):
        lines.append(f"{index + 1}. {_text(row.get('name'), '（未命名）')} · "
                     f"{_text(row.get('class'))}")
    return lines


def pets_active_text(payload: dict | None) -> str:
    """当前出战同伴；存档结构没有该标记时明确写「未知」，不当作未出战。"""
    payload = payload or {}
    pets = [row for row in payload.get("pets") or [] if isinstance(row, dict)]
    supported = payload.get("active_supported")
    if supported is None and pets:
        flags = [row.get("active_supported") for row in pets]
        if any(flag is False for flag in flags):
            supported = False
    if supported is False:
        return "当前出战：未知（存档结构不提供该标记）"
    active = payload.get("active")
    if active is None:
        active = next((row.get("active") for row in pets if row.get("active") is not None),
                      None)
    if active is None:
        return f"当前出战：{EMPTY}"
    for index, row in enumerate(pets):
        if row.get("index") == active:
            return f"当前出战：第 {index + 1} 号 {_text(row.get('name'), '（未命名）')}"
    return f"当前出战：{_text(active)}"


def pet_lines(payload: dict | None) -> list[str]:
    """名字 · 物种 · 种子；逐个同伴列出，不合并、不虚构。"""
    lines: list[str] = []
    for pet in (payload or {}).get("pets") or []:
        if not isinstance(pet, dict):
            continue
        seeds = pet.get("seeds") or {}
        lines.append(f"{_text(pet.get('name'), '（未命名）')} · "
                     f"{_text(pet.get('species'), '未知物种')} · "
                     f"种子 {_text(seeds.get('creature'))}")
    return lines


def pets_empty_text(payload: dict | None) -> str:
    note = str((payload or {}).get("note") or "").strip()
    return note or "这个存档里还没有同伴。"


def pets_source_text(payload: dict | None) -> str:
    source = str((payload or {}).get("source") or "").strip()
    return f"来源：{source}" if source else DEFAULT_PET_SOURCE


def live_asset_error_text(label: str, message: str = "", code: str = "",
                          unsupported: bool = False) -> str:
    """把 agent 错误整理成可读中文；原始错误保留在括号里，方便回报。"""
    raw = str(message or "").strip()
    low = raw.lower()
    unreachable = ("连不上" in raw or "响应超时" in raw or any(
        hint in low for hint in ("connection refused", "connection reset", "connectionerror",
                                 "timed out", "timeout", "urlopen error", "econnrefused",
                                 "winerror 10061")))
    if code == "E_AGENT" or unreachable:
        reason = "未连接游戏内代理；请先点「连接游戏」并确认游戏已注入。"
    elif ("还没进入存档" in raw or "未进入存档" in raw
          or "玩家状态不可用" in raw or "player_state" in low):
        reason = "游戏尚未进入存档；请先载入存档后重试。"
    elif unsupported or any(x in raw for x in ("不支持", "未实现", "unknown",
                                               "not implemented")):
        reason = "当前游戏内代理不支持该读取能力。"
    elif raw:
        reason = raw
    else:
        reason = "游戏内代理没有返回有效数据。"
    detail = f"（{raw}）" if raw and reason != raw else ""
    return f"{label}读取失败：{reason}{detail}"


class LiveAssetsCard(Card):
    """只读资产卡片；由页面把 worker 结果传进来，自己不碰网络。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("实时资产（只读）",
                         "只读：从当前存档读取多功能工具、货船与同伴；不会写回游戏。",
                         parent)
        self._build_blocks()
        self.set_waiting()

    # ---------------------------------------------------------------- 结构

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size:12.5px;font-weight:700;color:#dbe4f0;")
        self.add(label)
        return label

    def _build_blocks(self) -> None:
        self._section("多功能工具（只读）")
        self.multitool_status = muted(EMPTY)
        self.add(self.multitool_status)
        self.multitool_rows = QVBoxLayout()
        self.multitool_rows.setSpacing(3)
        self.add_layout(self.multitool_rows)

        self._section("货船与舰队（只读）")
        self.freighter_status = QLabel(EMPTY)
        self.freighter_status.setWordWrap(True)
        self.add(self.freighter_status)
        self.freighter_body = muted(EMPTY)
        self.add(self.freighter_body)

        self._section("同伴（只读）")
        self.pets_status = muted(EMPTY)
        self.add(self.pets_status)
        self.pets_body = QLabel(EMPTY)
        self.pets_body.setWordWrap(True)
        self.add(self.pets_body)
        self.pets_source = muted("")
        self.pets_source.setVisible(False)
        self.add(self.pets_source)

        for label in (self.freighter_status, self.pets_body):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)

    # ---------------------------------------------------------------- 状态

    def set_waiting(self, note: str = WAITING_TEXT) -> None:
        self._reset(note)

    def set_loading(self) -> None:
        self._reset(LOADING_TEXT)

    def _reset(self, note: str) -> None:
        self.multitool_status.setText(note)
        self._clear_multitool_rows()
        self.freighter_status.setText(note)
        self.freighter_body.setText(EMPTY)
        self.pets_status.setText(note)
        self.pets_body.setText(EMPTY)
        self.pets_source.setText("")
        self.pets_source.setVisible(False)

    def set_error(self, block: str, text: str) -> None:
        """单块失败：只在该块显示错误，不保留任何旧/空数据。"""
        text = str(text or "读取失败。")
        if block == "multitool":
            self.multitool_status.setText(text)
            self._clear_multitool_rows()
        elif block == "freighter":
            self.freighter_status.setText(text)
            self.freighter_body.setText(EMPTY)
        elif block == "pets":
            self.pets_status.setText(text)
            self.pets_body.setText(EMPTY)
            self.pets_source.setText("")
            self.pets_source.setVisible(False)

    def set_data(self, block: str, payload: dict | None) -> None:
        payload = payload if isinstance(payload, dict) else {}
        if block == "multitool":
            self.multitool_status.setText(multitool_summary(payload))
            self._set_multitool_rows(multitool_slots(payload))
        elif block == "freighter":
            self.freighter_status.setText(freighter_summary(payload))
            self.freighter_body.setText("\n".join(frigate_lines(payload)))
        elif block == "pets":
            self.pets_status.setText(pets_active_text(payload))
            lines = pet_lines(payload)
            self.pets_body.setText("\n".join(lines) if lines else pets_empty_text(payload))
            source = pets_source_text(payload)
            self.pets_source.setText(source)
            self.pets_source.setVisible(bool(source))

    # ---------------------------------------------------------------- 行

    def _clear_multitool_rows(self) -> None:
        while self.multitool_rows.count():
            item = self.multitool_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _set_multitool_rows(self, rows: list[dict]) -> None:
        self._clear_multitool_rows()
        for row in rows:
            label = QLabel(str(row.get("text") or EMPTY))
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if row.get("current"):
                label.setObjectName("liveAssetCurrent")
                label.setStyleSheet(_CURRENT_STYLE)
                label.setToolTip("当前使用中的多功能工具")
            else:
                label.setStyleSheet("padding:4px 6px;")
            self.multitool_rows.addWidget(label)
