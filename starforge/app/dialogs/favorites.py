"""收藏夹管理：搜索、预览、删除、导入/导出与清空。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ...data.shipref import TYPE_LABELS
from ...services import favorites
from ..widgets.ui import muted


def type_label(value: object) -> str:
    """把船型 key 转成界面用中文标签。"""
    key = str(value or "")
    return TYPE_LABELS.get(key, key)


def filter_items(items: list[dict], query: str) -> list[dict]:
    """按类型 / 种子 / 名称过滤收藏（大小写不敏感）。"""
    needle = (query or "").strip().casefold()
    if not needle:
        return list(items)
    out = []
    for item in items:
        haystack = " ".join((
            str(item.get("type") or ""),
            type_label(item.get("type")),
            str(item.get("seed") or ""),
            str(item.get("name") or ""),
        )).casefold()
        if needle in haystack:
            out.append(item)
    return out


def empty_text(total: int, shown: int, query: str = "") -> str:
    """空态提示；有内容时返回空串。"""
    if total <= 0:
        return ("收藏夹是空的。在飞船实验室选中飞船后点「☆ 收藏」，"
                "或点「导入…」载入 JSON / nsh1: 分享码。")
    if shown <= 0:
        return f"没有匹配「{query.strip()}」的收藏。"
    return ""


class FavoritesDialog(QDialog):
    """已收藏船只列表；选中后可把条目交回飞船实验室载入。"""

    shipSelected = Signal(object)

    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store or favorites
        self._items: list[dict] = []
        self._visible: list[dict] = []
        self.setWindowTitle("收藏夹")
        self.resize(780, 560)
        self._build_ui()
        self.refresh()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        title = QLabel("收藏夹")
        title.setStyleSheet("font-size:15px;font-weight:700;")
        root.addWidget(title)
        root.addWidget(muted("收藏保存在本机；可搜索、载入到实验室、导出 JSON 或导入分享码。"))

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索类型 / 种子 / 名称")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        row.addWidget(self.search, 1)
        self.count = QLabel("")
        self.count.setObjectName("muted")
        row.addWidget(self.count)
        root.addLayout(row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["类型", "种子", "名称"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.itemDoubleClicked.connect(lambda _item: self._load_selected())
        root.addWidget(self.table, 1)

        self.empty = muted("")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setContentsMargins(0, 18, 0, 18)
        root.addWidget(self.empty)

        self.preview = QLabel("选中条目后在这里预览种子。")
        self.preview.setObjectName("muted")
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.preview)

        self.status = muted("")
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        self.import_btn = QPushButton("导入…")
        self.import_btn.setToolTip("导入收藏 JSON，或每行一个 nsh1: 分享码")
        self.import_btn.clicked.connect(self._import_file)
        buttons.addWidget(self.import_btn)
        self.export_btn = QPushButton("导出…")
        self.export_btn.setToolTip("把全部收藏导出为 JSON 清单")
        self.export_btn.clicked.connect(self._export_file)
        buttons.addWidget(self.export_btn)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self._clear_all)
        buttons.addWidget(self.clear_btn)
        buttons.addStretch(1)
        self.delete_btn = QPushButton("删除")
        self.delete_btn.clicked.connect(self._delete_selected)
        buttons.addWidget(self.delete_btn)
        self.load_btn = QPushButton("载入到实验室")
        self.load_btn.setObjectName("primary")
        self.load_btn.clicked.connect(self._load_selected)
        buttons.addWidget(self.load_btn)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        root.addLayout(buttons)

    # ---------------------------------------------------------------- 数据

    def refresh(self) -> None:
        try:
            self._items = list(self.store.list())
        except Exception as e:                              # noqa: BLE001
            self._items = []
            self.status.setText(f"读取收藏失败：{e}")
        self._fill()

    def _fill(self) -> None:
        previous = self.selected_item()
        previous_key = (previous.get("type"), previous.get("seed")) if previous else None
        self._visible = filter_items(self._items, self.search.text())
        self.table.setRowCount(len(self._visible))
        for row, item in enumerate(self._visible):
            values = [type_label(item.get("type")), str(item.get("seed") or ""),
                      str(item.get("name") or "") or "—"]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(str(item.get("seed") or ""))
                if column == 0:
                    cell.setData(Qt.UserRole, item)
                self.table.setItem(row, column, cell)
            if previous_key and (item.get("type"), item.get("seed")) == previous_key:
                self.table.selectRow(row)
        self._update_empty()
        self._on_select()

    def _apply_filter(self) -> None:
        self._fill()

    def _update_empty(self) -> None:
        text = empty_text(len(self._items), len(self._visible), self.search.text())
        self.empty.setText(text)
        self.empty.setVisible(bool(text))
        query = self.search.text().strip()
        if query:
            self.count.setText(f"{len(self._visible)} / {len(self._items)}")
        else:
            self.count.setText(f"{len(self._items)} 个收藏")

    def selected_item(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._visible):
            return None
        cell = self.table.item(row, 0)
        item = cell.data(Qt.UserRole) if cell else None
        return dict(item) if isinstance(item, dict) else None

    def _on_select(self) -> None:
        item = self.selected_item()
        if item:
            label = type_label(item.get("type"))
            name = str(item.get("name") or "") or "未命名"
            parts = " ".join(item.get("parts") or [])
            text = f"{label} · {name}\n种子：{item.get('seed') or ''}"
            if parts:
                text += f"\n部件：{parts}"
            self.preview.setText(text)
        else:
            self.preview.setText("选中条目后在这里预览种子。")
        self._update_actions()

    def _update_actions(self) -> None:
        has_selection = self.selected_item() is not None
        has_items = bool(self._items)
        self.load_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
        self.export_btn.setEnabled(has_items)
        self.clear_btn.setEnabled(has_items)

    # ---------------------------------------------------------------- 操作

    def _load_selected(self) -> None:
        item = self.selected_item()
        if not item:
            return
        item["type_label"] = type_label(item.get("type"))
        item["source"] = "favorites"
        self.shipSelected.emit(item)
        self.accept()

    def _delete_selected(self) -> None:
        item = self.selected_item()
        if not item:
            return
        try:
            removed = self.store.remove(item)
        except Exception as e:                              # noqa: BLE001
            self.status.setText(f"删除失败：{e}")
            return
        self.refresh()
        self.status.setText("已删除所选收藏" if removed else "条目已不存在")

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入收藏", "", "收藏清单 (*.json);;分享码 (*.txt);;所有文件 (*)")
        if not path:
            return
        try:
            text = Path(path).read_text("utf-8")
            result = self.store.import_(text)
        except Exception as e:                              # noqa: BLE001
            self.status.setText(f"导入失败：{e}")
            QMessageBox.warning(self, "导入失败", str(e))
            return
        self.refresh()
        added = int(result.get("added") or 0)
        skipped = int(result.get("skipped") or 0)
        self.status.setText(f"导入完成：新增 {added} 个，跳过重复 {skipped} 个")

    def _export_file(self) -> None:
        if not self._items:
            self.status.setText("收藏夹是空的，没有可导出的条目")
            return
        default = str(Path.home() / "starforge-收藏.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出收藏", default, "收藏清单 (*.json);;所有文件 (*)")
        if not path:
            return
        try:
            target = self.store.export_to(path)
        except Exception as e:                              # noqa: BLE001
            self.status.setText(f"导出失败：{e}")
            QMessageBox.warning(self, "导出失败", str(e))
            return
        self.status.setText(f"已导出 {len(self._items)} 个收藏到 {target}")

    def _clear_all(self) -> None:
        if not self._items:
            return
        answer = QMessageBox.question(
            self, "清空收藏夹",
            f"确定清空全部 {len(self._items)} 个收藏？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            self.store.clear()
        except Exception as e:                              # noqa: BLE001
            self.status.setText(f"清空失败：{e}")
            return
        self.refresh()
        self.status.setText("收藏夹已清空")
