"""种子反查星系：后台调用 ``Services.locate``，区分候选与已证实结果。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ...services import get_services
from ..widgets.ui import muted
from ..widgets.worker import run as run_worker

LOCATE_HEADERS = ["坐标", "符文串", "星系", "位置 / 船", "已到访"]
UNKNOWN_GALAXY = "反查欠定"


def _text(value: object) -> str:
    return str(value or "").strip()


def _where_what(hit: dict) -> str:
    parts = []
    for key in ("where", "what"):
        value = _text(hit.get(key))
        if value:
            parts.append(value)
    return " / ".join(parts)


def locate_rows(result: dict | None) -> list[dict]:
    """把服务返回的 hits 整理成表格/复制用的稳定行。"""
    rows = []
    for hit in (result or {}).get("hits") or []:
        if not isinstance(hit, dict):
            continue
        where_what = _where_what(hit)
        if not where_what and hit.get("steps") is not None:
            where_what = f"往回第 {hit.get('steps')} 步"
        rows.append({
            "ua": _text(hit.get("ua")),
            "coords": _text(hit.get("coords")),
            "glyphs": _text(hit.get("glyphs")),
            "galaxy": hit.get("galaxy"),
            "where": _text(hit.get("where")),
            "what": _text(hit.get("what")),
            "where_what": where_what,
            "visited": bool(hit.get("visited")),
            "steps": hit.get("steps"),
            "portal_hint": _text(hit.get("portal_hint")),
            "raw": hit,
        })
    return rows


def locate_summary(result: dict | None, seed: str = "") -> str:
    """一句话概览：候选/已证实数量，绝不把候选说成命中。"""
    data = result or {}
    seed_text = _text(data.get("seed")) or _text(seed)
    candidates = int(data.get("candidates") or 0)
    hits = len(locate_rows(data))
    bits = [f"种子：{seed_text or '—'}", f"候选：{candidates}", f"已证实：{hits}"]
    if data.get("known_systems") is not None:
        bits.append(f"已知星系：{data.get('known_systems')}")
    if data.get("elapsed_ms") is not None:
        bits.append(f"耗时：{data.get('elapsed_ms')} ms")
    return "  ·  ".join(bits)


def locate_empty_text(result: dict | None) -> str:
    """无结果说明；明确"反查欠定"，不伪造命中。"""
    if result is None:
        return "输入种子后点「重新反查」；反查可能较慢，且只有部分种子能反解。"
    candidates = int(result.get("candidates") or 0)
    if locate_rows(result):
        return ""
    reason = _text(result.get("reason"))
    extra = f"（{reason}）" if reason else ""
    return (f"{UNKNOWN_GALAXY}：候选 {candidates} 个，但没有经生成器证实的星系{extra}。"
            "这不代表种子无效，只说明它可能来自未知/未访问星系。")


class LocateDialog(QDialog):
    """显示种子反查结果；支持复制坐标/符文，无结果时说明反查欠定。"""

    def __init__(self, seed: str, parent=None, services=None, auto_start: bool = True,
                 result: dict | None = None):
        super().__init__(parent)
        self.svc = services or get_services()
        self.seed = _text(seed)
        self._rows: list[dict] = []
        self._busy = False
        self._worker = None
        self.setWindowTitle("查所在星系")
        self.resize(820, 520)
        self._build_ui()
        if result is not None:
            self.set_result(result)
        elif auto_start:
            self.start()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        title = QLabel("查所在星系")
        title.setStyleSheet("font-size:15px;font-weight:700;")
        root.addWidget(title)

        self.seed_label = QLabel(f"种子：{self.seed or '—'}")
        self.seed_label.setObjectName("muted")
        self.seed_label.setWordWrap(True)
        self.seed_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.seed_label)

        root.addWidget(muted(
            "反查是精确但欠定的：先列出候选，再由生成器证实。"
            "只有「已证实」行才代表真的找到了这艘船所在的星系。"))

        self.summary = QLabel("尚未反查。")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary.setAccessibleName("反查结果概览")
        root.addWidget(self.summary)

        self.empty = muted(locate_empty_text(None))
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)

        self.table = QTableWidget(0, len(LOCATE_HEADERS))
        self.table.setHorizontalHeaderLabels(LOCATE_HEADERS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAccessibleName("已证实星系列表")
        self.table.itemSelectionChanged.connect(self._update_actions)
        root.addWidget(self.table, 1)

        self.status = muted("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        self.retry_btn = QPushButton("重新反查")
        self.retry_btn.setToolTip("重新调用 Services.locate（候选越多越慢）")
        self.retry_btn.clicked.connect(self.start)
        buttons.addWidget(self.retry_btn)
        self.copy_coords_btn = QPushButton("复制坐标")
        self.copy_coords_btn.setEnabled(False)
        self.copy_coords_btn.clicked.connect(self._copy_coords)
        buttons.addWidget(self.copy_coords_btn)
        self.copy_glyphs_btn = QPushButton("复制符文")
        self.copy_glyphs_btn.setEnabled(False)
        self.copy_glyphs_btn.clicked.connect(self._copy_glyphs)
        buttons.addWidget(self.copy_glyphs_btn)
        buttons.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        root.addLayout(buttons)
        self._update_actions()

    # ---------------------------------------------------------------- 数据

    def start(self) -> None:
        if self._busy:
            return
        if not self.seed:
            self.status.setText("没有种子可反查。")
            return
        self._busy = True
        self.retry_btn.setEnabled(False)
        self.copy_coords_btn.setEnabled(False)
        self.copy_glyphs_btn.setEnabled(False)
        self.table.setRowCount(0)
        self._rows = []
        self.summary.setText(f"正在反查种子 {self.seed}…")
        self.empty.setText("正在生成候选；候选越多越慢，请稍候。")
        self.status.setText("正在反查…")
        try:
            self._worker = run_worker(self.svc.locate, self.set_result, self._failed, self.seed)
        except Exception as e:                              # noqa: BLE001
            self._failed(f"{type(e).__name__}: {e}")

    def _failed(self, msg: str) -> None:
        self._busy = False
        self.retry_btn.setEnabled(True)
        self.table.setRowCount(0)
        self._rows = []
        self.summary.setText(f"反查失败：{msg}")
        self.empty.setText("没有拿到候选星系；请检查种子或游戏目录后重试。")
        self.status.setText(f"反查失败：{msg}")
        self._update_actions()

    def set_result(self, result: dict | None) -> None:
        self._busy = False
        self.retry_btn.setEnabled(True)
        self._rows = locate_rows(result)
        self.summary.setText(locate_summary(result, self.seed))
        self.empty.setText(locate_empty_text(result))
        self.empty.setVisible(bool(locate_empty_text(result)))
        self._fill()
        hits = len(self._rows)
        if hits:
            self.status.setText(f"反查完成：{hits} 个已证实星系。")
            self.table.selectRow(0)
        else:
            self.status.setText(locate_empty_text(result))
        self._update_actions()

    def _fill(self) -> None:
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            galaxy = row.get("galaxy")
            values = [
                row.get("coords") or "—",
                row.get("glyphs") or "—",
                str(galaxy) if galaxy is not None else "—",
                row.get("where_what") or "—",
                "是" if row.get("visited") else "否",
            ]
            for j, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(row.get("portal_hint") or str(value))
                if j == 0:
                    item.setData(Qt.UserRole, row)
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()

    def _selected_row(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if rows:
            item = self.table.item(rows[0].row(), 0)
            row = item.data(Qt.UserRole) if item else None
            if isinstance(row, dict):
                return row
        return self._rows[0] if self._rows else None

    def _update_actions(self) -> None:
        row = self._selected_row()
        coords = bool(row and row.get("coords"))
        glyphs = bool(row and row.get("glyphs"))
        self.copy_coords_btn.setEnabled(coords)
        self.copy_glyphs_btn.setEnabled(glyphs)

    def _copy_coords(self) -> None:
        self._copy_text((self._selected_row() or {}).get("coords"), "坐标")

    def _copy_glyphs(self) -> None:
        self._copy_text((self._selected_row() or {}).get("glyphs"), "符文串")

    def _copy_text(self, value: object, label: str) -> None:
        text = _text(value)
        if not text:
            self.status.setText(f"当前没有可复制的{label}。")
            return
        QGuiApplication.clipboard().setText(text)
        self.status.setText(f"{label}已复制：{text}")
