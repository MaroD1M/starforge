"""飞船设计器：船型/部件树 → 原生 3D 预览 → 已选摘要与种子搜索。

数据只走 ``Services``：部件树用 ``catalog_ship``，3D 用 ``preview_mesh``，
失败时退回 ``preview_png``。本页不直接写存档（后端尚未验证）。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...services import get_services
from ..widgets.ship_viewer import ShipViewer
from ..widgets.ui import Card, icon_from_png, muted, placeholder_icon
from ..widgets.worker import run as run_worker

SHIPS = [("sentinel", "拦截机"), ("fighter", "战斗机"), ("hauler", "运输舰"),
         ("explorer", "探索舰"), ("shuttle", "穿梭机"), ("exotic", "异星"),
         ("living", "生物舰"), ("solar", "太阳帆")]

EXAMPLE_SEED = "0x992C8A47F60A6B10"


# ---------------------------------------------------------------- 纯逻辑

def single_choice(selection: dict[str, str], group: str, part: str | None) -> dict[str, str]:
    """每个组只保留一个部件；part 为空表示清空该组。"""
    out = dict(selection or {})
    gid = str(group or "")
    if not gid:
        return out
    value = str(part or "").strip()
    if value:
        out[gid] = value
    else:
        out.pop(gid, None)
    return out


def _group_options(group: dict) -> tuple[str, str, dict[str, str]]:
    gid = str(group.get("group") or "")
    label = str(group.get("label") or gid)
    options = {str(opt.get("part") or ""): str(opt.get("label") or opt.get("part") or "")
               for opt in group.get("options") or []}
    return gid, label, options


def selected_parts(selection: dict[str, str] | None,
                   groups: list[dict] | None = None) -> list[str]:
    """按部件树顺序输出有效选择；空选返回 []，未知部件被忽略。"""
    chosen = dict(selection or {})
    if not chosen:
        return []
    if not groups:
        return [str(part) for _gid, part in sorted(chosen.items()) if part]
    out: list[str] = []
    for group in groups:
        gid, _label, options = _group_options(group)
        part = str(chosen.get(gid) or "")
        if part and part in options:
            out.append(part)
    return out


def selection_rows(selection: dict[str, str] | None,
                   groups: list[dict] | None = None) -> list[dict]:
    """给右侧摘要用的行：组/部件中文名与原始内部名。"""
    chosen = dict(selection or {})
    rows: list[dict] = []
    for group in groups or []:
        gid, group_label, options = _group_options(group)
        part = str(chosen.get(gid) or "")
        if part and part in options:
            rows.append({"group": gid, "group_label": group_label,
                         "part": part, "part_label": options[part]})
    return rows


def preview_params(ship: str, seed: str,
                   groups: list[dict] | None = None,
                   selection: dict[str, str] | None = None) -> dict:
    """集中生成 preview_mesh 的参数，保证 UI 与测试使用同一套整理规则。"""
    return {"ship": str(ship or ""), "seed": str(seed or "").strip(),
            "parts": selected_parts(selection, groups)}


def normalize_result(row: dict | None) -> dict:
    """把搜索结果整理成稳定的字段，避免界面直接依赖上游字典细节。"""
    data = row or {}
    parts = data.get("parts") or []
    return {
        "type": str(data.get("type") or ""),
        "type_label": str(data.get("type_label") or data.get("type") or ""),
        "seed": str(data.get("seed") or "").strip(),
        "parts": [str(part) for part in parts if part],
    }


def result_summary(row: dict | None) -> str:
    data = normalize_result(row)
    label = data["type_label"] or "未知船型"
    return f"{label}  {data['seed']}".strip()


# ---------------------------------------------------------------- 页面

class ShipDesignerPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._loaded = False
        self._groups: list[dict] = []
        self._selection: dict[str, str] = {}
        self._catalog_token = 0
        self._mesh_token = 0
        self._render_token = 0
        self._updating_tree = False
        self._search_job = None
        self._icon_queue: list[tuple[QTreeWidgetItem, str, str]] = []
        self._icon_timer = QTimer(self)
        self._icon_timer.setSingleShot(True)
        self._icon_timer.setInterval(20)
        self._icon_timer.timeout.connect(self._next_icon)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(220)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._search_timer = QTimer(self)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._poll_search)
        self._build_ui()

    # ------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)
        split.addWidget(self._build_parts())
        split.addWidget(self._build_preview())
        split.addWidget(self._build_actions())
        split.setSizes([320, 620, 430])
        split.setStretchFactor(1, 1)

    def _build_parts(self) -> QWidget:
        wrap = Card("船型与部件", "每组单选一个部件")
        v = wrap.v

        v.addWidget(QLabel("船型"))
        self.ship = QComboBox()
        for key, label in SHIPS:
            self.ship.addItem(label, key)
        self.ship.currentIndexChanged.connect(self._load_parts)
        v.addWidget(self.ship)

        row = QHBoxLayout()
        self.parts_status = muted("选择船型后加载部件表")
        row.addWidget(self.parts_status, 1)
        clear = QPushButton("清空")
        clear.setToolTip("清空所有组的选择")
        clear.clicked.connect(self._clear_parts)
        row.addWidget(clear)
        v.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["部件", "组"])
        self.tree.setColumnWidth(0, 210)
        self.tree.setIconSize(QSize(40, 40))
        self.tree.setStyleSheet("QTreeWidget::item { height: 38px; }")
        self.tree.itemChanged.connect(self._on_tree_changed)
        self.tree.itemClicked.connect(self._show_part_detail)
        v.addWidget(self.tree, 1)

        self.part_detail = QLabel("点击部件查看预览与详情")
        self.part_detail.setObjectName("muted")
        self.part_detail.setMinimumHeight(54)
        self.part_detail.setWordWrap(True)
        self.part_detail.setStyleSheet("background:#08111d;border:1px solid #24384a;border-radius:8px;padding:8px;")
        v.addWidget(self.part_detail)

        self.parts_count = muted("尚未加载部件表")
        v.addWidget(self.parts_count)
        return wrap

    def _build_preview(self) -> QWidget:
        wrap = Card("3D 预览", "拖动旋转 · 滚轮缩放 · 双击复位")
        v = wrap.v

        self.viewer = ShipViewer()
        self.viewer.setMinimumHeight(320)
        v.addWidget(self.viewer, 1)

        self.fallback = QLabel()
        self.fallback.setAlignment(Qt.AlignCenter)
        self.fallback.setWordWrap(True)
        self.fallback.setMinimumHeight(320)
        self.fallback.hide()
        v.addWidget(self.fallback, 1)

        views = QHBoxLayout()
        for text, mode in (("等轴", "iso"), ("俯视", "top"),
                           ("侧视", "side"), ("正视", "front")):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, m=mode: self.viewer.set_view(m))
            views.addWidget(button)
        spin = QPushButton("自转")
        spin.setCheckable(True)
        spin.toggled.connect(self.viewer.set_spin)
        views.addWidget(spin)
        v.addLayout(views)

        self.preview_detail = muted("选择部件后将生成 3D 预览。")
        v.addWidget(self.preview_detail)
        return wrap

    def _build_actions(self) -> QWidget:
        wrap = Card("已选部件", "单选 · 摘要")
        v = wrap.v

        self.summary = QListWidget()
        self.summary.setMaximumHeight(150)
        v.addWidget(self.summary)
        self.summary_count = muted("尚未选择部件（空选也可以预览默认外形）")
        v.addWidget(self.summary_count)

        v.addWidget(QLabel("预览种子"))
        seed_row = QHBoxLayout()
        self.seed_edit = QLineEdit(EXAMPLE_SEED)
        self.seed_edit.setPlaceholderText("例如 0x992C8A47F60A6B10")
        self.seed_edit.editingFinished.connect(self._refresh_preview)
        seed_row.addWidget(self.seed_edit, 1)
        copy = QPushButton("复制种子")
        copy.clicked.connect(self._copy_seed)
        seed_row.addWidget(copy)
        v.addLayout(seed_row)

        self.search_btn = QPushButton("用这些部件搜索种子")
        self.search_btn.setObjectName("primary")
        self.search_btn.clicked.connect(self._start_search)
        v.addWidget(self.search_btn)

        self.search_status = muted("至少选择一个部件后即可搜索。")
        v.addWidget(self.search_status)

        v.addWidget(QLabel("搜索结果"))
        self.results = QListWidget()
        self.results.itemSelectionChanged.connect(self._select_result)
        v.addWidget(self.results, 1)

        self.write_btn = QPushButton("写入存档（暂不可用）")
        self.write_btn.setEnabled(False)
        self.write_btn.setToolTip("直接写部件到存档的后端尚未验证，本页不开放此操作")
        v.addWidget(self.write_btn)
        v.addWidget(muted("说明：直接写部件到存档的后端尚未验证，本页刻意禁用；"
                          "如需写入，请使用「飞船实验室」的完整流程。"))
        return wrap

    # ------------------------------------------------------------ 数据

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._load_parts()

    def _load_parts(self, *_args) -> None:
        ship = self.ship.currentData()
        self._catalog_token += 1
        token = self._catalog_token
        self._groups = []
        self._selection = {}
        self.tree.clear()
        self.parts_status.setText("读取部件表…")
        self.parts_count.setText("")
        self._update_summary()
        self._schedule_preview()

        def done(res: dict) -> None:
            if token != self._catalog_token:
                return
            self._groups = list(res.get("groups") or [])
            self._populate_tree()
            source = self._source_label(res.get("source"))
            self.parts_status.setText(f"部件表已加载 · {source}")
            total = sum(len(g.get("options") or []) for g in self._groups)
            self.parts_count.setText(f"{len(self._groups)} 个组 / {total} 个部件")
            self._update_summary()
            self._schedule_preview()

        def fail(msg: str) -> None:
            if token != self._catalog_token:
                return
            self._groups = []
            self._selection = {}
            self.tree.clear()
            self.parts_status.setText(f"读不到部件表：{msg}")
            self.parts_count.setText("错误态：可切换船型重试，或检查游戏目录")
            self._update_summary()
            self._show_placeholder(f"部件表不可用：{msg}")

        run_worker(self.svc.catalog_ship, done, fail, ship)

    def _populate_tree(self) -> None:
        self._updating_tree = True
        self._icon_queue.clear()
        total = 0
        try:
            self.tree.clear()
            for group in self._groups:
                gid, label, _options = _group_options(group)
                top = QTreeWidgetItem([label, ""])
                top.setData(0, Qt.UserRole, gid)
                top.setFlags(top.flags() & ~Qt.ItemIsSelectable)
                top.setToolTip(0, gid)
                for opt in group.get("options") or []:
                    part = str(opt.get("part") or "")
                    child = QTreeWidgetItem([str(opt.get("label") or part), gid])
                    child.setData(0, Qt.UserRole, part)
                    child.setData(0, Qt.UserRole + 1, gid)
                    child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                    child.setCheckState(0, Qt.Unchecked)
                    child.setIcon(0, placeholder_icon(part))
                    child.setToolTip(0, f"{part}\n组：{gid}")
                    if total < 24:
                        self._icon_queue.append((child, self.ship.currentData(), part))
                    total += 1
                    top.addChild(child)
                self.tree.addTopLevelItem(top)
                top.setExpanded(True)
        finally:
            self._updating_tree = False
        if self._icon_queue:
            self._icon_timer.start(30)

    def _next_icon(self) -> None:
        if not self._icon_queue:
            return
        item, ship, part = self._icon_queue.pop(0)

        def done(data: bytes | None) -> None:
            if data:
                try:
                    item.setIcon(0, icon_from_png(data, 40))
                except Exception:                          # noqa: BLE001
                    pass
            if self._icon_queue:
                self._icon_timer.start(20)

        run_worker(self.svc.part_icon, done, lambda _m: None, ship, part, 48)
        if self._icon_queue:
            self._icon_timer.start(20)

    def _show_part_detail(self, item: QTreeWidgetItem, _column: int) -> None:
        part = item.data(0, Qt.UserRole)
        if not part:
            return
        gid = item.data(0, Qt.UserRole + 1) or item.text(1)
        self.part_detail.setText(f"{part}  ·  组 {gid}\n读取预览…")

        def done(data: bytes | None) -> None:
            if data:
                pix = QPixmap()
                pix.loadFromData(data, "PNG")
                if not pix.isNull():
                    self.part_detail.setPixmap(pix)
                    self.part_detail.setToolTip(f"{part} / {gid}")
                    return
            self.part_detail.setText(f"{part}  ·  组 {gid}\n该部件没有可渲染的几何（结构件/空槽）")

        run_worker(self.svc.part_icon, done,
                   lambda m: self.part_detail.setText(f"{part} 预览失败：{m}"),
                   self.ship.currentData(), part, 96)

    @staticmethod
    def _source_label(source: str | None) -> str:
        return {"game": "游戏资源", "gagarin": "Gagarin 数据表",
                "none": "无数据"}.get(source or "", "未知来源")

    def _on_tree_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating_tree or column != 0:
            return
        gid = item.data(0, Qt.UserRole + 1)
        part = item.data(0, Qt.UserRole)
        if not gid or not part:
            return
        self._updating_tree = True
        try:
            if item.checkState(0) == Qt.Checked:
                parent = item.parent()
                if parent is not None:
                    for index in range(parent.childCount()):
                        sibling = parent.child(index)
                        if sibling is not item and sibling.checkState(0) == Qt.Checked:
                            sibling.setCheckState(0, Qt.Unchecked)
                self._selection = single_choice(self._selection, gid, part)
            elif self._selection.get(gid) == part:
                self._selection = single_choice(self._selection, gid, None)
        finally:
            self._updating_tree = False
        self._update_summary()
        self._schedule_preview()

    def _clear_parts(self) -> None:
        self._updating_tree = True
        try:
            for index in range(self.tree.topLevelItemCount()):
                top = self.tree.topLevelItem(index)
                for child_index in range(top.childCount()):
                    top.child(child_index).setCheckState(0, Qt.Unchecked)
        finally:
            self._updating_tree = False
        self._selection = {}
        self._update_summary()
        self._schedule_preview()

    def _update_summary(self) -> None:
        rows = selection_rows(self._selection, self._groups)
        self.summary.clear()
        for row in rows:
            item = QListWidgetItem(f"{row['group_label']}：{row['part_label']}")
            item.setToolTip(f"{row['group']} / {row['part']}")
            self.summary.addItem(item)
        count = len(rows)
        if count:
            self.summary_count.setText(f"已选 {count} 个组")
        else:
            self.summary_count.setText("尚未选择部件（空选也可以预览默认外形）")
        self.search_btn.setEnabled(bool(rows) and self._search_job is None)

    # ------------------------------------------------------------ 预览

    def _schedule_preview(self) -> None:
        self._preview_timer.start()

    def _current_params(self) -> dict:
        return preview_params(self.ship.currentData(), self.seed_edit.text(),
                              self._groups, self._selection)

    def _refresh_preview(self) -> None:
        self._preview_timer.stop()
        params = self._current_params()
        self._mesh_token += 1
        self._render_token += 1
        token = self._mesh_token
        self.preview_detail.setText("生成 3D…")
        self.fallback.hide()
        self.viewer.show()

        def done(mesh: dict) -> None:
            if token != self._mesh_token:
                return
            try:
                self.viewer.set_mesh(mesh.get("groups") or {}, mesh.get("colours") or {})
            except Exception as e:                          # noqa: BLE001
                self._preview_failed(token, f"{type(e).__name__}: {e}")
                return
            self.preview_detail.setText(
                f"{mesh.get('verts', 0):,} 顶点 / {mesh.get('tris', 0):,} 三角\n"
                "拖动旋转 · 滚轮缩放 · 双击复位")
            QTimer.singleShot(1200, lambda: self._check_viewer(token))

        def fail(msg: str) -> None:
            if token == self._mesh_token:
                self._preview_failed(token, msg)

        run_worker(self.svc.preview_mesh, done, fail,
                   params["ship"], params["seed"], params["parts"])

    def _check_viewer(self, token: int) -> None:
        if token != self._mesh_token:
            return
        if getattr(self.viewer, "_failed", False) or getattr(self.viewer, "_error", ""):
            reason = getattr(self.viewer, "_error", "") or "3D 初始化失败"
            self._preview_failed(token, reason)

    def _preview_failed(self, token: int, reason: str) -> None:
        if token != self._mesh_token:
            return
        params = self._current_params()
        self._render_token += 1
        render_token = self._render_token
        self.preview_detail.setText(f"实时 3D 不可用：{reason}；正在尝试渲染图…")

        def done(data: bytes) -> None:
            if token != self._mesh_token or render_token != self._render_token:
                return
            pix = QPixmap()
            pix.loadFromData(data or b"", "PNG")
            if pix.isNull():
                self._show_placeholder(f"实时 3D 不可用：{reason}\n渲染图也不可用")
                return
            self.fallback.setText("")
            self.fallback.setPixmap(pix.scaled(480, 480, Qt.KeepAspectRatio,
                                               Qt.SmoothTransformation))
            self.viewer.hide()
            self.fallback.show()
            self.preview_detail.setText(f"实时 3D 不可用：{reason}\n已退回渲染图。")

        def fail(msg: str) -> None:
            if token == self._mesh_token and render_token == self._render_token:
                self._show_placeholder(f"实时 3D 不可用：{reason}\n渲染图失败：{msg}")

        run_worker(self.svc.preview_png, done, fail,
                   params["ship"], params["seed"], params["parts"], 420)

    def _show_placeholder(self, text: str) -> None:
        self.fallback.setPixmap(QPixmap())
        self.fallback.setText(text)
        self.viewer.hide()
        self.fallback.show()

    # ------------------------------------------------------------ 操作

    def _copy_seed(self) -> None:
        seed = self.seed_edit.text().strip()
        QGuiApplication.clipboard().setText(seed)
        self.search_status.setText("种子已复制" if seed else "种子为空，未复制")

    def _start_search(self) -> None:
        parts = selected_parts(self._selection, self._groups)
        if not parts:
            self.search_status.setText("空选无法搜索：请先至少选择一个部件")
            return
        ship = self.ship.currentData()
        self.results.clear()
        self.search_status.setText("搜索中…")
        self.search_btn.setEnabled(False)
        payload = {"ship": ship, "want": parts, "avoid": [], "limit": 12,
                   "max_seeds": 20_000_000, "time_limit": 20.0, "workers": 1}
        try:
            self._search_job = self.svc.start_search(payload)
        except Exception as e:                              # noqa: BLE001
            self._search_job = None
            self.search_btn.setEnabled(True)
            self.search_status.setText(f"无法开始搜索：{type(e).__name__}: {e}")
            return
        self._search_timer.start()

    def _poll_search(self) -> None:
        job = self._search_job
        if job is None:
            self._search_timer.stop()
            return
        progress = job.progress or {}
        tested = progress.get("tested") or 0
        rate = progress.get("rate") or 0
        self.search_status.setText(f"搜索中… 已测 {tested:,} 个种子  {rate/1e6:.1f} 百万/秒")
        if job.status == "running":
            return

        self._search_timer.stop()
        self._search_job = None
        self.search_btn.setEnabled(bool(selected_parts(self._selection, self._groups)))
        if job.error:
            self.search_status.setText(f"搜索失败：{job.error}")
            return
        rows = list(job.result or [])
        for row in rows:
            data = normalize_result(row)
            item = QListWidgetItem(f"{result_summary(row)}  ·  {len(data['parts'])} 个部件")
            item.setData(Qt.UserRole, row)
            item.setToolTip(data["seed"])
            self.results.addItem(item)
        if rows:
            self.search_status.setText(f"命中 {len(rows)} 个（已测 {tested:,}）")
        else:
            self.search_status.setText("没有命中：条件可能太严")

    def _select_result(self) -> None:
        items = self.results.selectedItems()
        if not items:
            return
        row = items[0].data(Qt.UserRole) or {}
        data = normalize_result(row)
        if not data["seed"]:
            self.search_status.setText("这条结果没有可用的种子")
            return
        self.seed_edit.setText(data["seed"])
        self.search_status.setText(f"已选用种子 {data['seed']}，3D 预览已更新")
        self._refresh_preview()
