"""同伴列表：只读展示存档里的同伴描述符与种子。"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QHBoxLayout, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ...services import Services, get_services
from .. import notify
from .feedback import EmptyState, ErrorBanner, LoadingOverlay
from .ui import muted
from .worker import run as run_worker

PET_TABLE_HEADERS = ("名称", "生物类型", "群系", "CreatureID", "种子", "信任/特征数量")
PET_PREVIEW_NOTE = "同伴 3D 预览需要生物生成器；当前只展示描述符与种子，不伪造模型。"
PET_NO_SAVE_NOTE = "请先在「存档」中选择 save.hg；同伴 3D 预览需要生物生成器。"


def pet_table_headers() -> list[str]:
    """表头用独立函数返回副本，方便界面与测试共用同一份中文文案。"""
    return list(PET_TABLE_HEADERS)


def _text(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def pet_seed(creature: dict) -> str:
    seeds = creature.get("seeds") or {}
    for key in ("creature", "species", "genus", "creature2"):
        value = _text(seeds.get(key), "")
        if value:
            return value
    return "—"


def format_trust_traits(trust: Any, traits: Any) -> str:
    trust_text = _text(trust, "—")
    try:
        trait_count = int(traits or 0)
    except (TypeError, ValueError):
        trait_count = 0
    return f"{trust_text} / {trait_count}"


def pet_rows(creatures: list[dict] | None) -> list[list[str]]:
    """把服务层同伴字典整理成表格行；缺字段时给中文占位，不抛异常。"""
    rows: list[list[str]] = []
    for creature in creatures or []:
        if not isinstance(creature, dict):
            continue
        rows.append([
            _text(creature.get("name"), "(未命名)"),
            _text(creature.get("type_zh") or creature.get("type"), "未知"),
            _text(creature.get("biome_zh") or creature.get("biome"), "未知"),
            _text(creature.get("creature"), "未知"),
            pet_seed(creature),
            format_trust_traits(creature.get("trust"), creature.get("traits")),
        ])
    return rows


def pets_empty_text(payload: dict | None = None, path: str = "") -> str:
    """空态/提示文案：无存档、无同伴、空槽都给出中文说明。"""
    if not str(path or "").strip():
        return "尚未读取存档：请先在「存档」中选择 save.hg。"
    if payload is None:
        return "暂无同伴数据。"
    if payload.get("creatures"):
        return ""
    note = str(payload.get("note") or "").strip()
    if note:
        return note
    return "这个存档里还没有同伴。"


def pets_preview_note(payload: dict | None = None) -> str:
    note = str((payload or {}).get("preview") or "").strip()
    return note or PET_PREVIEW_NOTE


def _load_pets(svc: Services, path: str) -> dict:
    data = svc.creatures(path)
    try:
        data["_roles"] = svc.creature_roles()
    except Exception as e:                              # noqa: BLE001 - 角色库只作补充
        data["_roles_error"] = str(e)
    return data


class PetsView(QWidget):
    """同伴标签页；无数据时不伪造 3D 或缩略图。"""

    def __init__(self, svc: Services | None = None, parent=None):
        super().__init__(parent)
        self.svc = svc or get_services()
        self._path = ""
        self._loaded = False
        self._loading = False
        self._token = 0
        self._payload: dict | None = None
        self._sort_column = 0
        self._sort_desc = False
        self._build_ui()
        self.loading_overlay = LoadingOverlay(self, "正在读取同伴…")
        self.loading = self.loading_overlay
        self.overlay = self.loading_overlay
        self.empty = self.empty_state
        self.error = self.error_banner
        self._show_empty("没有存档", PET_NO_SAVE_NOTE)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.count_label = QLabel("同伴")
        self.count_label.setObjectName("muted")
        bar.addWidget(self.count_label)
        bar.addStretch(1)
        self.refresh_btn = QPushButton("刷新同伴")
        self.refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(self.refresh_btn)
        root.addLayout(bar)

        self.error_banner = ErrorBanner()
        self.error_banner.set_retry_callback(self.refresh)
        root.addWidget(self.error_banner)

        self.empty_state = EmptyState(
            "没有存档", PET_NO_SAVE_NOTE, icon="◇", button_text="刷新同伴")
        self.empty_state.set_action("刷新同伴", self.refresh)
        root.addWidget(self.empty_state, 1)

        self.table = QTableWidget(0, len(PET_TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(pet_table_headers())
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        header.sectionClicked.connect(self._sort_by)
        root.addWidget(self.table, 1)

        self.foot = muted(PET_PREVIEW_NOTE)
        root.addWidget(self.foot)

        self.state = muted("")
        self.state.hide()
        root.addWidget(self.state)

    def set_save_path(self, path: str, invalidate: bool = False) -> None:
        path = str(path or "").strip()
        changed = path != self._path
        if not changed and not invalidate:
            return
        self._path = path
        self._loaded = False
        self._payload = None
        self._token += 1
        self.error_banner.clear()
        if not path:
            self._show_empty("没有存档", PET_NO_SAVE_NOTE)
            return
        if self.isVisible():
            self.refresh()
        elif changed:
            self._show_empty("同伴尚未加载", "切换到「同伴」标签后自动读取；" + PET_PREVIEW_NOTE)

    def ensure_loaded(self) -> None:
        if not self._path:
            self._show_empty("没有存档", PET_NO_SAVE_NOTE)
            return
        if not self._loaded and not self._loading:
            self.refresh()

    def refresh(self) -> None:
        path = self._path.strip()
        self._token += 1
        token = self._token
        if not path:
            self._loading = False
            self._loaded = False
            self._show_empty("没有存档", PET_NO_SAVE_NOTE)
            return
        self._loading = True
        self._payload = None
        self.error_banner.clear()
        self.count_label.setText("正在读取同伴…")
        self.foot.setText(PET_PREVIEW_NOTE)
        self.loading_overlay.start("正在读取同伴…")

        def done(payload: dict) -> None:
            if token != self._token:
                return
            self._loading = False
            self._loaded = True
            self.loading_overlay.stop()
            self._render(payload or {})

        def fail(msg: str) -> None:
            if token != self._token:
                return
            self._loading = False
            self._loaded = False
            self.loading_overlay.stop()
            self._show_error(msg)

        run_worker(_load_pets, done, fail, self.svc, path)

    def clear(self) -> None:
        self.set_save_path("", invalidate=True)

    @staticmethod
    def _sort_value(row: list[str], column: int):
        value = str(row[column]) if column < len(row) else ""
        if column == 5:
            parts = []
            for part in value.split("/"):
                try:
                    parts.append(float(part.strip()))
                except ValueError:
                    parts.append(0.0)
            return tuple(parts)
        return value.casefold()

    def _sort_by(self, column: int) -> None:
        if column == self._sort_column:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_column = column
            self._sort_desc = False
        if self._payload is not None:
            self._render(self._payload)
        else:
            header = self.table.horizontalHeader()
            header.setSortIndicator(
                self._sort_column,
                Qt.DescendingOrder if self._sort_desc else Qt.AscendingOrder)

    def _render(self, payload: dict) -> None:
        self._payload = payload
        creatures = [c for c in (payload.get("creatures") or []) if isinstance(c, dict)]
        rows = pet_rows(creatures)
        pairs = list(zip(rows, creatures))
        pairs.sort(key=lambda pair: self._sort_value(pair[0], self._sort_column),
                   reverse=self._sort_desc)
        self._fill_table(pairs)

        note = pets_empty_text(payload, self._path)
        self.state.setText(note)
        self.state.setVisible(False)

        if not pairs:
            title = "没有同伴" if self._path else "没有存档"
            base = note or "这个存档里还没有同伴。"
            self._show_empty(title, f"{base}\n{PET_PREVIEW_NOTE}")
            self.foot.setText(pets_preview_note(payload))
            return

        self.empty_state.hide()
        self.table.show()
        roles = payload.get("_roles") or {}
        role_count = roles.get("count")
        summary = f"{len(pairs)} 只同伴"
        if role_count is not None:
            summary += f" · 角色库 {role_count} 条"
        elif payload.get("_roles_error"):
            summary += " · 角色库不可用"
        self.count_label.setText(summary)
        self.foot.setText(pets_preview_note(payload))

    def _fill_table(self, pairs: list[tuple[list[str], dict]]) -> None:
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(pairs))
        for r, (row, creature) in enumerate(pairs):
            for c, value in enumerate(row):
                item = QTableWidgetItem(value)
                if c == 3:
                    if creature.get("role_known") is False:
                        item.setToolTip("角色库里没有这个 CreatureID")
                    else:
                        item.setToolTip("CreatureID 同时是生物角色名")
                self.table.setItem(r, c, item)
        header = self.table.horizontalHeader()
        header.setSortIndicator(
            self._sort_column,
            Qt.DescendingOrder if self._sort_desc else Qt.AscendingOrder)

    def _show_empty(self, title: str, text: str) -> None:
        self.table.hide()
        self.table.setRowCount(0)
        self.count_label.setText("同伴 · 0 只")
        self.state.setText(text)
        self.state.setVisible(False)
        self.empty_state.title_label.setText(title)
        self.empty_state.description_label.setText(text)
        self.empty_state.description_label.setVisible(bool(text))
        self.empty_state.show()
        self.foot.setText(PET_PREVIEW_NOTE)
        self.loading_overlay.stop()

    def _show_error(self, msg: str) -> None:
        text = f"读取同伴失败：{msg}"
        self.table.hide()
        self.table.setRowCount(0)
        self.count_label.setText("读取同伴失败")
        self.state.setText(text)
        self.state.setVisible(False)
        self.empty_state.title_label.setText("读取同伴失败")
        self.empty_state.description_label.setText("请重试，或检查存档路径。")
        self.empty_state.description_label.setVisible(True)
        self.empty_state.show()
        self.foot.setText(PET_PREVIEW_NOTE)
        self.error_banner.show_error(text)
        self.loading_overlay.stop()
        notify.error(text)
