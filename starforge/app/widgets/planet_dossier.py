"""行星档案与兴趣点的结构化展示（表格 + 可复制文本）。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

MISSING = "未提供"

PLANET_FIELDS = (
    ("行星名", ("name",)),
    ("类型", ("planet_type", "biome")),
    ("天气", ("weather",)),
    ("哨兵", ("sentinels",)),
    ("资源", ("resources",)),
    ("动物", ("fauna",)),
    ("植物", ("flora",)),
    ("生物标识（ID）", ("creature_ids",)),
    ("额外资源提示", ("extra_resource_hints",)),
)

POI_HEADERS = ("类型", "名称 / 描述", "距离", "地址 / 坐标", "备注")


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value).strip()


def _join(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return _text(value.get("hint") or value.get("name") or value.get("label")
                     or value.get("icon") or value)
    if isinstance(value, (list, tuple, set)):
        items = [_join(item) for item in value]
        return "、".join(item for item in items if item)
    return _text(value)


def _hints(value) -> str:
    if not isinstance(value, (list, tuple)):
        return _join(value)
    items = []
    for row in value:
        if isinstance(row, dict):
            hint = _text(row.get("hint"))
            icon = _text(row.get("icon"))
            if hint and icon and icon != hint:
                items.append(f"{hint}（图标：{icon}）")
            elif hint or icon:
                items.append(hint or icon)
        else:
            item = _text(row)
            if item:
                items.append(item)
    return "、".join(items)


def _first(data: dict, keys: tuple[str, ...]) -> tuple[bool, str]:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        rendered = _hints(value) if key == "extra_resource_hints" else _join(value)
        if rendered:
            return True, rendered
    return False, MISSING


def planet_rows(data: dict | None) -> list[tuple[str, str]]:
    data = data if isinstance(data, dict) else {}
    return [(label, _first(data, keys)[1]) for label, keys in PLANET_FIELDS]


def format_planet_text(data: dict | None) -> str:
    rows = planet_rows(data)
    lines = [f"{label}：{value}" for label, value in rows]
    data = data if isinstance(data, dict) else {}
    unsupported = data.get("unsupported")
    if unsupported:
        names = "、".join(str(x) for x in unsupported)
        lines.append(f"当前游戏内组件不支持的字段：{names}（缺失项显示“未提供”）")
    return "\n".join(lines)


def _poi_row(row, kind_label: str) -> list[str]:
    if not isinstance(row, dict):
        return [kind_label, _text(row) or MISSING, MISSING, MISSING, MISSING]
    kind = _text(row.get("kind") or row.get("type")) or kind_label
    name = _text(row.get("name") or row.get("label") or row.get("description")) or MISSING
    distance = row.get("distance")
    distance_text = MISSING if distance is None or _text(distance) == "" else _text(distance)
    glyphs = _text(row.get("glyphs"))
    ua = _text(row.get("ua") or row.get("galactic_address"))
    if glyphs and ua:
        address = f"传送门符文：{glyphs}；银河地址：{ua}"
    elif glyphs:
        address = f"传送门符文：{glyphs}"
    elif ua:
        address = f"银河地址：{ua}"
    else:
        address = MISSING
    note = _text(row.get("note") or row.get("hint")) or MISSING
    return [kind, name, distance_text, address, note]


class _DossierBase(QWidget):
    def __init__(self, headers: tuple[str, str] | tuple[str, ...], parent=None):
        super().__init__(parent)
        self._message = ""
        self._rows: list[tuple[str, ...]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(list(headers))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        head = self.table.horizontalHeader()
        if len(headers) == 2:
            head.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            head.setSectionResizeMode(1, QHeaderView.Stretch)
        else:
            head.setSectionResizeMode(QHeaderView.ResizeToContents)
            head.setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.table.hide()

    def set_message(self, text: str) -> None:
        self._message = str(text or "")
        self._rows = []
        self.table.setRowCount(0)
        self.table.hide()
        self.summary.setText(self._message)

    def set_rows(self, rows: list[tuple[str, ...]], summary: str) -> None:
        self._message = ""
        self._rows = [tuple(str(x) for x in row) for row in rows]
        self.summary.setText(summary)
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            for j, value in enumerate(row):
                item = QTableWidgetItem(value)
                if j == 0:
                    item.setData(Qt.UserRole, value)
                self.table.setItem(i, j, item)
        self.table.setVisible(bool(self._rows))
        self.table.resizeRowsToContents()

    def rows(self) -> list[tuple[str, ...]]:
        return list(self._rows)

    def has_data(self) -> bool:
        return bool(self._rows)

    def toPlainText(self) -> str:
        if not self._rows:
            return self._message
        return "\n".join("：".join(row) for row in self._rows)

    def text(self) -> str:
        return self.toPlainText()

    def setPlainText(self, text: str) -> None:
        self.set_message(text)

    def append(self, text: str) -> None:
        self._message = "\n".join(x for x in (self._message, str(text)) if x)
        self.summary.setText(self._message)

    def clear(self) -> None:
        self.set_message("")


class PlanetDossier(_DossierBase):
    def __init__(self, parent=None):
        super().__init__(("字段", "内容"), parent)
        self._data: dict = {}

    def set_planet(self, data: dict | None) -> None:
        data = data if isinstance(data, dict) else {}
        self._data = dict(data)
        rows = planet_rows(data)
        name = rows[0][1]
        kind = rows[1][1]
        summary = f"{name}  ·  {kind}"
        unsupported = data.get("unsupported") or []
        if unsupported:
            summary += f"  ·  部分字段不支持：{'、'.join(str(x) for x in unsupported)}"
        else:
            summary += "  ·  缺失字段显示“未提供”"
        self.set_rows(rows, summary)

    def toPlainText(self) -> str:
        if not self._rows:
            return self._message
        return format_planet_text(self._data)


class PoiDossier(_DossierBase):
    def __init__(self, parent=None):
        super().__init__(POI_HEADERS, parent)

    def set_pois(self, kind_label: str, rows: list) -> None:
        cleaned = [_poi_row(row, kind_label) for row in rows]
        self.set_rows(cleaned, f"附近{kind_label}：共 {len(cleaned)} 条结果。")

    def set_unavailable(self, kind_label: str, reason: str) -> None:
        self.set_message(f"附近{kind_label}暂不可用：{reason}")
