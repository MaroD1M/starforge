"""飞船设计器：部件树 → 原生 3D 预览 → 写入存档（唯一主操作）。

UI 约定：
  · primary 固定是「写入存档」；校验不通过时在旁边直接写原因，按钮同时禁用；
  · 「保存设计 / 载入设计」收进一个次级「设计文件」菜单，不再和主操作抢位置；
  · 左侧部件树带搜索框，并按「已选 / 可选」分组；右侧已选摘要可折叠；
  · 搜索种子、复制种子都降为次级；每个能力只有一个入口。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ...services import get_services
from .. import notify
from ..dialogs.design_write import DesignWriteDialog
from ..dialogs.part_preview import PartPreviewDialog
from ..widgets.lab_ui import WrapLabel, fixed_height
from ..widgets.page import PageSplitter, page_layout, scroll_panel
from ..widgets.page_header import PageHeader
from ..widgets.ship_viewer import ShipViewer
from ..widgets.ui import Card, icon_from_png, placeholder_icon
from ..widgets.worker import run as run_worker

SHIPS = [("sentinel", "拦截机"), ("fighter", "战斗机"), ("hauler", "运输舰"),
         ("explorer", "探索舰"), ("shuttle", "穿梭机"), ("exotic", "异星"),
         ("living", "生物舰"), ("solar", "太阳帆")]

EXAMPLE_SEED = "0x992C8A47F60A6B10"
# 三栏最小宽度：1180×760 以及 990px 内容宽（最小窗口减去导航栏）都不挤压。
DESIGNER_MIN_LEFT = 268
DESIGNER_MIN_MIDDLE = 320
DESIGNER_MIN_RIGHT = 324


def _slug(name: str) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(name or "").lower())
    return text.strip("_") or "design"


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


def write_block_reason(parts: list[str] | None, seeds: list[str] | None) -> str:
    """写入存档前的本地校验；返回空串表示可以写入。

    与 ``_current_design`` 的取种子顺序一致：结果列表里的有效种子也算，
    所以用户只要选中一个搜索结果，即使输入框里还是示例种子也能写入。
    """
    if not [part for part in parts or [] if str(part).strip()]:
        return "先选择部件"
    valid = []
    for seed in seeds or []:
        clean = normalize_design_seed(seed)
        if clean and clean not in valid:
            valid.append(clean)
    if not valid:
        return "先搜索并选中一个种子"
    return ""


# ---------------------------------------------------------------- 设计文件（本地 JSON）

DESIGN_SUFFIX = ".nmsdesign.json"
DESIGN_MAKER = "NMS Starforge"


def normalize_design_seed(value) -> str:
    """把 0x 开头的种子规范成 16 位大写；非法值返回空串。"""
    text = str(value or "").strip()
    if not text.lower().startswith("0x"):
        return ""
    digits = text[2:]
    if not digits or len(digits) > 16:
        return ""
    try:
        number = int(digits, 16)
    except (TypeError, ValueError):
        return ""
    return f"0x{number & ((1 << 64) - 1):016X}"


def design_payload(name: str, ship: str, selection: dict[str, str] | None,
                   groups: list[dict] | None, seeds: list[str] | None = None,
                   notes: str = "") -> dict:
    """生成可保存的设计 JSON；部件必须来自当前船型部件树。"""
    want = selected_parts(selection, groups)
    if not want:
        raise ValueError("请先至少选择一个部件，再保存设计")
    found = []
    for seed in seeds or []:
        clean = normalize_design_seed(seed)
        if clean and clean not in found:
            found.append(clean)
    return {
        "name": str(name or "").strip()[:60] or "未命名设计",
        "ship": str(ship or ""),
        "notes": str(notes or "")[:2000],
        "want": want,
        "avoid": [],
        "found_seeds": found,
        "made_with": DESIGN_MAKER,
    }


def design_document(data: dict, groups: list[dict] | None = None) -> dict:
    """校验并整理一个设计文件；未知船型/空部件会被拒绝，不猜测。"""
    if not isinstance(data, dict):
        raise ValueError("这不是设计文件（顶层必须是 JSON 对象）")
    ship = str(data.get("ship") or "")
    if ship not in {key for key, _label in SHIPS}:
        raise ValueError(f"设计文件里的船型未知：{ship!r}")
    raw_want = data.get("want") or []
    if isinstance(raw_want, str):
        raw_want = [p for p in raw_want.replace(",", " ").split() if p]
    want = [str(p).strip().upper() for p in raw_want
            if p is not None and str(p).strip()]
    if not want:
        raise ValueError("设计文件里没有部件")
    if groups:
        known = {str(opt.get("part") or "").upper()
                 for group in groups for opt in group.get("options") or []}
        unknown = [p for p in want if p not in known]
        if unknown:
            raise ValueError(f"这些部件不属于当前船型：{', '.join(unknown[:6])}")
    seeds = []
    for seed in data.get("found_seeds") or data.get("seeds") or []:
        clean = normalize_design_seed(seed)
        if clean and clean not in seeds:
            seeds.append(clean)
    return {
        "name": str(data.get("name") or "导入的设计").strip()[:60],
        "ship": ship,
        "notes": str(data.get("notes") or "")[:2000],
        "want": want,
        "avoid": [str(p).strip().upper() for p in data.get("avoid") or [] if str(p).strip()],
        "found_seeds": seeds,
        "made_with": str(data.get("made_with") or DESIGN_MAKER),
    }


def selection_from_parts(parts: list[str] | None, groups: list[dict] | None) -> dict[str, str]:
    """把设计文件里的部件列表还原成 {group: part}；未知部件直接忽略。"""
    wanted = {str(p).upper() for p in parts or []}
    out: dict[str, str] = {}
    for group in groups or []:
        gid, _label, options = _group_options(group)
        for part in options:
            if part.upper() in wanted and gid not in out:
                out[gid] = part
                break
    return out


def read_design_file(path: str | Path, groups: list[dict] | None = None) -> dict:
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"无法读取设计文件：{e}") from e
    return design_document(data, groups)


def write_design_file(path: str | Path, document: dict) -> str:
    target = Path(path)
    target.write_text(json.dumps(document, ensure_ascii=False, indent=1), "utf-8")
    return str(target)


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
        self._pending_design: dict | None = None
        self._summary_open = False
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
        self._detail_item: QTreeWidgetItem | None = None
        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.setInterval(120)
        self._detail_timer.timeout.connect(self._refresh_detail)
        self._build_ui()

    # ------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = page_layout(self)
        self.header = PageHeader(
            "设计器",
            "选部件、看 3D，最后写入存档；保存/载入收在「设计文件」菜单。")
        self.header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        root.addWidget(self.header)
        split = PageSplitter("ship_designer")
        root.addWidget(split, 1)

        parts = scroll_panel(self._build_parts())
        parts.setMinimumWidth(DESIGNER_MIN_LEFT)
        preview = self._build_preview()
        preview.setMinimumWidth(DESIGNER_MIN_MIDDLE)
        actions = scroll_panel(self._build_actions())
        actions.setMinimumWidth(DESIGNER_MIN_RIGHT)

        split.addWidget(parts)
        split.addWidget(preview)
        split.addWidget(actions)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.set_default_sizes([300, 500, 390])
        split.restore()
        self._sync_write_state()

    def _build_parts(self) -> QWidget:
        wrap = Card("船型与部件", "搜索后点部件；已选与可选分开显示")
        v = wrap.v

        v.addWidget(QLabel("船型"))
        self.ship = QComboBox()
        for key, label in SHIPS:
            self.ship.addItem(label, key)
        self.ship.currentIndexChanged.connect(self._load_parts)
        v.addWidget(self.ship)

        self.part_filter = QLineEdit()
        self.part_filter.setPlaceholderText("搜索部件名或内部 ID…")
        self.part_filter.setClearButtonEnabled(True)
        self.part_filter.textChanged.connect(self._filter_tree)
        v.addWidget(self.part_filter)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setIconSize(QSize(32, 32))
        self.tree.setStyleSheet("QTreeWidget::item { height: 32px; }")
        self.tree.setMouseTracking(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumHeight(176)
        self.tree.itemChanged.connect(self._on_tree_changed)
        self.tree.itemClicked.connect(self._show_part_detail)
        self.tree.currentItemChanged.connect(self._on_detail_current)
        v.addWidget(self.tree, 1)

        self.part_detail = WrapLabel("悬停或点击部件查看预览与详情")
        self.part_detail.setObjectName("muted")
        self.part_detail.setStyleSheet(
            "background:#08111d;border:1px solid #24384a;border-radius:8px;padding:8px;")
        v.addWidget(self.part_detail)

        detail_row = QHBoxLayout()
        self.parts_status = WrapLabel("选择船型后加载部件表")
        self.parts_status.setObjectName("muted")
        detail_row.addWidget(self.parts_status, 1)
        self.part_3d_btn = fixed_height(QPushButton("3D 预览"))
        self.part_3d_btn.setToolTip("在独立小窗中 3D 预览当前部件")
        self.part_3d_btn.clicked.connect(self._open_part_preview)
        detail_row.addWidget(self.part_3d_btn)
        v.addLayout(detail_row)
        return wrap

    def _build_preview(self) -> QWidget:
        wrap = Card("3D 预览")
        v = wrap.v

        self.viewer = ShipViewer()
        self.viewer.setMinimumHeight(300)
        v.addWidget(self.viewer, 1)

        self.fallback = QLabel()
        self.fallback.setAlignment(Qt.AlignCenter)
        self.fallback.setWordWrap(True)
        self.fallback.setMinimumHeight(300)
        self.fallback.hide()
        v.addWidget(self.fallback, 1)

        views = QHBoxLayout()
        views.setSpacing(6)
        views.addWidget(QLabel("视角"))
        self.view_combo = QComboBox()
        for text, mode in (("等轴", "iso"), ("俯视", "top"),
                           ("侧视", "side"), ("正视", "front")):
            self.view_combo.addItem(text, mode)
        self.view_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.view_combo.currentIndexChanged.connect(self._change_view)
        views.addWidget(self.view_combo, 1)
        self.spin = QCheckBox("自转")
        self.spin.toggled.connect(self.viewer.set_spin)
        views.addWidget(self.spin)
        v.addLayout(views)

        self.preview_detail = WrapLabel("选择部件后将生成 3D 预览。")
        self.preview_detail.setObjectName("muted")
        v.addWidget(self.preview_detail)
        return wrap

    def _build_actions(self) -> QWidget:
        wrap = Card("写入存档")
        v = wrap.v

        # 主操作置顶：无论下方摘要/结果列表怎么长，primary 始终在首屏可见。
        write_row = QHBoxLayout()
        write_row.setSpacing(8)
        self.write_design_btn = fixed_height(QPushButton("写入存档"))
        self.write_design_btn.setObjectName("primary")
        self.write_design_btn.setMinimumWidth(118)
        self.write_design_btn.setToolTip(
            "把当前种子写入新船槽或替换现有槽；先备份，可写入副本")
        self.write_design_btn.clicked.connect(self._write_design)
        write_row.addWidget(self.write_design_btn, 0)
        self.write_reason = WrapLabel("")
        self.write_reason.setObjectName("warn")
        self.write_reason.setStyleSheet("color:#f2b45c;")
        write_row.addWidget(self.write_reason, 1)
        v.addLayout(write_row)

        self.summary_toggle = QPushButton("已选摘要 ▸")
        self.summary_toggle.setFlat(True)
        self.summary_toggle.setCursor(Qt.PointingHandCursor)
        self.summary_toggle.setCheckable(True)
        self.summary_toggle.setToolTip("展开或收起已选部件摘要")
        self.summary_toggle.setStyleSheet(
            "QPushButton { border:none; background:transparent; color:#8b95a7;"
            " text-align:left; padding:0 2px; }"
            "QPushButton:hover { color:#e6ecf5; }")
        self.summary_toggle.toggled.connect(self._toggle_summary)
        v.addWidget(self.summary_toggle)

        self.summary = QListWidget()
        self.summary.setMinimumHeight(72)
        self.summary.setMaximumHeight(132)
        self.summary.setVisible(False)
        v.addWidget(self.summary)

        self.summary_count = WrapLabel("尚未选择部件（空选也可以预览默认外形）")
        self.summary_count.setObjectName("muted")
        v.addWidget(self.summary_count)

        v.addWidget(QLabel("预览 / 写入种子"))
        seed_row = QHBoxLayout()
        seed_row.setSpacing(6)
        self.seed_edit = QLineEdit(EXAMPLE_SEED)
        self.seed_edit.setPlaceholderText("例如 0x992C8A47F60A6B10")
        self.seed_edit.setMinimumWidth(80)
        self.seed_edit.textChanged.connect(self._sync_write_state)
        self.seed_edit.editingFinished.connect(self._refresh_preview)
        seed_row.addWidget(self.seed_edit, 1)
        self.copy_btn = fixed_height(QPushButton("复制"))
        self.copy_btn.setToolTip("复制当前种子")
        self.copy_btn.clicked.connect(self._copy_seed)
        seed_row.addWidget(self.copy_btn)
        v.addLayout(seed_row)

        self.search_btn = fixed_height(QPushButton("搜索种子"))
        self.search_btn.setToolTip("用当前部件组合搜索可用种子")
        self.search_btn.clicked.connect(self._start_search)
        v.addWidget(self.search_btn)

        self.search_status = WrapLabel("点「搜索种子」用当前部件找种子。")
        self.search_status.setObjectName("muted")
        v.addWidget(self.search_status)

        v.addWidget(QLabel("搜索结果"))
        self.results = QListWidget()
        self.results.setMinimumHeight(128)
        self.results.itemSelectionChanged.connect(self._select_result)
        v.addWidget(self.results, 1)

        self.files_btn = fixed_height(QPushButton("设计文件 ▾"))
        self.files_btn.setObjectName("ghostButton")
        self.files_btn.setToolTip("保存或载入本地 .nmsdesign.json；不写存档")
        self.files_menu = QMenu(self.files_btn)
        self.save_design_btn = QAction("保存设计…", self)
        self.save_design_btn.triggered.connect(self._save_design)
        self.files_menu.addAction(self.save_design_btn)
        self.load_design_btn = QAction("载入设计…", self)
        self.load_design_btn.triggered.connect(self._load_design)
        self.files_menu.addAction(self.load_design_btn)
        self.files_btn.setMenu(self.files_menu)
        v.addWidget(self.files_btn)
        return wrap

    # ------------------------------------------------------------ 树分组

    def _tree_group(self, title: str) -> QTreeWidgetItem:
        top = QTreeWidgetItem([title, ""])
        top.setFlags(top.flags() & ~Qt.ItemIsSelectable)
        return top

    def _make_part_item(self, part: str, gid: str, label: str) -> QTreeWidgetItem:
        child = QTreeWidgetItem([label, gid])
        child.setData(0, Qt.UserRole, part)
        child.setData(0, Qt.UserRole + 1, gid)
        child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
        child.setIcon(0, placeholder_icon(part))
        child.setToolTip(0, f"{part}\n组：{gid}")
        return child

    def _populate_tree(self) -> None:
        self._updating_tree = True
        self._icon_queue.clear()
        total = 0
        chosen_count = 0
        try:
            self.tree.clear()
            selected_root = self._tree_group("已选")
            available_root = self._tree_group("可选")
            for group in self._groups:
                gid, label, options = _group_options(group)
                selected = str(self._selection.get(gid) or "")
                if selected and selected in options:
                    chosen_count += 1
                    item = self._make_part_item(selected, gid,
                                                f"{label}：{options[selected]}")
                    item.setCheckState(0, Qt.Checked)
                    selected_root.addChild(item)
                remaining = [(part, part_label) for part, part_label in options.items()
                             if part != selected]
                if remaining:
                    group_node = QTreeWidgetItem([label, ""])
                    group_node.setFlags(group_node.flags() & ~Qt.ItemIsSelectable)
                    group_node.setToolTip(0, gid)
                    for part, part_label in remaining:
                        child = self._make_part_item(part, gid, part_label)
                        child.setCheckState(0, Qt.Unchecked)
                        group_node.addChild(child)
                        if total < 24:
                            self._icon_queue.append((child, self.ship.currentData(), part))
                        total += 1
                    available_root.addChild(group_node)
                    group_node.setExpanded(True)
            selected_root.setText(0, f"已选（{chosen_count}）")
            available_root.setText(0, f"可选（{total}）")
            self.tree.addTopLevelItem(selected_root)
            self.tree.addTopLevelItem(available_root)
            selected_root.setExpanded(True)
            available_root.setExpanded(True)
        finally:
            self._updating_tree = False
        self._filter_tree(self.part_filter.text())
        if self._icon_queue:
            self._icon_timer.start(30)

    def _iter_child_items(self):
        for index in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(index)
            for child_index in range(top.childCount()):
                node = top.child(child_index)
                if node.childCount():
                    for leaf_index in range(node.childCount()):
                        yield node.child(leaf_index)
                else:
                    yield node

    def _filter_tree(self, text: str) -> None:
        needle = str(text or "").strip().upper()
        for index in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(index)
            any_visible = False
            for node_index in range(top.childCount()):
                node = top.child(node_index)
                if node.childCount():
                    group_visible = False
                    group_match = needle and needle in node.text(0).upper()
                    for leaf_index in range(node.childCount()):
                        leaf = node.child(leaf_index)
                        part = str(leaf.data(0, Qt.UserRole) or "").upper()
                        show = not needle or group_match or needle in leaf.text(0).upper() \
                            or needle in part
                        leaf.setHidden(not show)
                        group_visible = group_visible or show
                    node.setHidden(not group_visible)
                    if group_visible and needle:
                        node.setExpanded(True)
                    any_visible = any_visible or group_visible
                else:
                    part = str(node.data(0, Qt.UserRole) or "").upper()
                    show = not needle or needle in node.text(0).upper() or needle in part
                    node.setHidden(not show)
                    any_visible = any_visible or show
            top.setHidden(not any_visible)
            if needle:
                top.setExpanded(True)

    def _focus_part(self, part: str) -> None:
        for item in self._iter_child_items():
            if str(item.data(0, Qt.UserRole) or "") == part:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return

    def _next_icon(self) -> None:
        if not self._icon_queue:
            return
        item, ship, part = self._icon_queue.pop(0)

        def done(data: bytes | None) -> None:
            try:
                if data:
                    item.setIcon(0, icon_from_png(data, 40))
            except RuntimeError:
                pass
            if self._icon_queue:
                self._icon_timer.start(20)

        run_worker(self.svc.part_icon, done, lambda _m: None, ship, part, 48)

    def _on_detail_current(self, item: QTreeWidgetItem | None, *_args) -> None:
        if item is None or item.childCount():
            return
        self._detail_item = item
        self._detail_timer.start()

    def _refresh_detail(self) -> None:
        item = self._detail_item
        if item is not None:
            self._show_part_detail(item, 0)

    def _open_part_preview(self) -> None:
        item = self.tree.currentItem() or self._detail_item
        if item is None or item.childCount():
            notify.warn("先选择一个部件")
            return
        part = str(item.data(0, Qt.UserRole) or "")
        if not part:
            notify.warn("先选择一个部件")
            return
        PartPreviewDialog(str(self.ship.currentData() or ""), part, self).exec()

    def _show_part_detail(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.childCount():
            return
        part = item.data(0, Qt.UserRole)
        if not part:
            return
        self._detail_item = item
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
        self._update_summary()
        self._schedule_preview()

        def done(res: dict) -> None:
            if token != self._catalog_token:
                return
            self._groups = list(res.get("groups") or [])
            self._populate_tree()
            source = self._source_label(res.get("source"))
            total = sum(len(g.get("options") or []) for g in self._groups)
            self.parts_status.setText(
                f"{len(self._groups)} 组 / {total} 个部件 · {source}")
            self._update_summary()
            self._schedule_preview()
            if self._pending_design is not None:
                pending, self._pending_design = self._pending_design, None
                self._apply_design(pending, quiet=True)

        def fail(msg: str) -> None:
            if token != self._catalog_token:
                return
            self._groups = []
            self._selection = {}
            self.tree.clear()
            self.parts_status.setText(f"读不到部件表：{msg}")
            self._update_summary()
            self._show_placeholder(f"部件表不可用：{msg}")

        run_worker(self.svc.catalog_ship, done, fail, ship)

    @staticmethod
    def _source_label(source: str | None) -> str:
        return {"game": "游戏资源", "gagarin": "Gagarin 数据表",
                "none": "无数据"}.get(source or "", "未知来源")

    def _on_tree_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating_tree or column != 0 or item.childCount():
            return
        gid = item.data(0, Qt.UserRole + 1)
        part = item.data(0, Qt.UserRole)
        if not gid or not part:
            return
        selected = item.checkState(0) == Qt.Checked
        if selected:
            self._selection = single_choice(self._selection, gid, part)
        elif self._selection.get(gid) == part:
            self._selection = single_choice(self._selection, gid, None)
        self._populate_tree()
        self._update_summary()
        self._schedule_preview()
        if selected:
            QTimer.singleShot(0, lambda p=str(part): self._focus_part(p))

    def _toggle_summary(self, on: bool) -> None:
        self._summary_open = bool(on)
        self.summary.setVisible(self._summary_open)
        self.summary_toggle.setText("已选摘要 ▾" if self._summary_open else "已选摘要 ▸")

    def _clear_parts(self) -> None:
        self._selection = {}
        self._populate_tree()
        self._update_summary()
        self._schedule_preview()

    def _apply_design(self, document: dict, quiet: bool = False) -> None:
        selection = selection_from_parts(document.get("want"), self._groups)
        self._selection = selection
        self._populate_tree()
        seeds = document.get("found_seeds") or []
        if seeds:
            self.seed_edit.setText(seeds[0])
        self._update_summary()
        self._schedule_preview()
        if not quiet:
            self.search_status.setText(
                f"已载入设计「{document.get('name') or '未命名'}」："
                f"{len(selection)} 个组 / {len(document.get('want') or [])} 个部件")

    def _save_design(self) -> None:
        if not selected_parts(self._selection, self._groups):
            self.search_status.setText("空设计不能保存：请先选择部件")
            return
        ship = str(self.ship.currentData() or "")
        label = self.ship.currentText() or ship
        name, ok = QInputDialog.getText(self, "保存设计", "设计名称：",
                                        text=f"{label} 设计")
        if not ok:
            return
        try:
            document = design_payload(name, ship, self._selection, self._groups,
                                      self._seed_candidates())
        except ValueError as e:
            self.search_status.setText(str(e))
            return
        start = str(Path.home() / f"{_slug(document['name'])}{DESIGN_SUFFIX}")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存设计文件", start, f"设计文件 (*{DESIGN_SUFFIX});;JSON (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += DESIGN_SUFFIX
        try:
            write_design_file(path, document)
        except OSError as e:
            self.search_status.setText(f"保存设计失败：{e}")
            return
        self.search_status.setText(f"设计已保存到 {path}（未写存档）")

    def _load_design(self) -> None:
        start = str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "载入设计文件", start,
            f"设计文件 (*{DESIGN_SUFFIX});;JSON (*.json);;所有文件 (*)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text("utf-8"))
        except (OSError, ValueError) as e:
            self.search_status.setText(f"无法读取设计文件：{e}")
            return
        ship = str((data or {}).get("ship") or "") if isinstance(data, dict) else ""
        current = str(self.ship.currentData() or "")
        try:
            if ship and ship != current:
                document = design_document(data)
                self._pending_design = document
                index = self.ship.findData(ship)
                if index < 0:
                    raise ValueError(f"当前设计器没有这个船型：{ship!r}")
                self.ship.setCurrentIndex(index)
                self.search_status.setText(f"已切换到 {self.ship.currentText()}，正在载入设计…")
                return
            document = design_document(data, self._groups)
        except ValueError as e:
            self.search_status.setText(str(e))
            return
        self._apply_design(document)

    def _seed_candidates(self) -> list[str]:
        seeds = []
        for index in range(self.results.count()):
            row = self.results.item(index).data(Qt.UserRole) or {}
            seed = normalize_design_seed(row.get("seed"))
            if seed and seed not in seeds:
                seeds.append(seed)
        current = normalize_design_seed(self.seed_edit.text())
        if current and current not in seeds:
            seeds.insert(0, current)
        return seeds

    def _current_design(self) -> dict:
        seeds = self._seed_candidates()
        try:
            return design_payload(f"{self.ship.currentText()} 设计",
                                  str(self.ship.currentData() or ""),
                                  self._selection, self._groups, seeds)
        except ValueError:
            return {"name": f"{self.ship.currentText()} 设计",
                    "ship": str(self.ship.currentData() or ""),
                    "want": [], "found_seeds": seeds}

    def _sync_write_state(self, *_args) -> None:
        reason = write_block_reason(selected_parts(self._selection, self._groups),
                                    self._seed_candidates())
        self.write_design_btn.setEnabled(not reason and self._search_job is None)
        self.write_reason.setText(reason)
        self.write_reason.setVisible(bool(reason))
        if reason:
            self.write_design_btn.setToolTip(f"暂不能写入：{reason}")
        else:
            self.write_design_btn.setToolTip(
                "把当前种子写入新船槽或替换现有槽；先备份，可写入副本")

    def _write_design(self) -> None:
        reason = write_block_reason(selected_parts(self._selection, self._groups),
                                    self._seed_candidates())
        if reason:
            self.search_status.setText(f"暂不能写入：{reason}")
            return
        document = self._current_design()
        seeds = document.get("found_seeds") or []
        seed = normalize_design_seed(seeds[0]) if seeds else ""
        if not seed:
            self.search_status.setText("没有可用种子：请先搜索并选中一个结果")
            return
        document["found_seeds"] = [seed] + [s for s in document.get("found_seeds") or []
                                            if s != seed]
        dialog = DesignWriteDialog(document, self)
        if dialog.exec() == dialog.Accepted:
            result = dialog.result or {}
            self.search_status.setText(
                f"写入成功 · {result.get('what') or ('槽位 ' + str(result.get('slot')))}")

    def _update_summary(self) -> None:
        rows = selection_rows(self._selection, self._groups)
        self.summary.clear()
        for row in rows:
            item = QListWidgetItem(f"{row['group_label']}：{row['part_label']}")
            item.setToolTip(f"{row['group']} / {row['part']}")
            self.summary.addItem(item)
        count = len(rows)
        if count:
            self.summary_count.setText(f"已选 {count} 个组；点部件可换或取消")
        else:
            self.summary_count.setText("尚未选择部件（空选也可以预览默认外形）")
        self.search_btn.setEnabled(bool(rows) and self._search_job is None)
        self._sync_write_state()

    # ------------------------------------------------------------ 预览

    def _schedule_preview(self) -> None:
        self._preview_timer.start()

    def _current_params(self) -> dict:
        return preview_params(self.ship.currentData(), self.seed_edit.text(),
                              self._groups, self._selection)

    def _change_view(self) -> None:
        mode = str(self.view_combo.currentData() or "iso")
        self.viewer.set_view(mode)

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
        self._sync_write_state()
        payload = {"ship": ship, "want": parts, "avoid": [], "limit": 12,
                   "max_seeds": 20_000_000, "time_limit": 20.0, "workers": 1}
        try:
            self._search_job = self.svc.start_search(payload)
        except Exception as e:                              # noqa: BLE001
            self._search_job = None
            self.search_btn.setEnabled(True)
            self._sync_write_state()
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
        self._sync_write_state()
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
            self._sync_write_state()
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
        self._sync_write_state()
        self._refresh_preview()
