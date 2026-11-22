"""同伴列表：只读展示存档里的同伴描述符与种子。"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...creature import portal_glyphs_valid
from ...services import Services, get_services
from .. import notify
from .feedback import EmptyState, ErrorBanner, LoadingOverlay
from .ui import muted
from .worker import run as run_worker

PET_TABLE_HEADERS = ("名称", "生物类型", "群系", "CreatureID", "来源", "种子",
                     "信任/特征数量")
# 详情区只展示前几条动物记录，避免一屏被长列表占满；完整数量写在标题里。
FAUNA_PREVIEW_LIMIT = 3
PET_PREVIEW_NOTE = "同伴 3D 预览仍需要生物生成器；来源与符文来自存档 UA，不伪造模型。"
PET_NO_SAVE_NOTE = "请先在「存档」中选择 save.hg；同伴 3D 预览需要生物生成器。"
# 传送失败时（E_BUILD_UNVERIFIED）给用户的下一步；与星图页保持同一口径。
BUILD_UNVERIFIED_HINT = (
    "需要先开启实验写入开关（设置页 → 安全 → 允许未验证 build 的实验写入）")
WARP_WARNING = "会调用游戏内传送门机制，失败可用「还原」回滚。"


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


def pet_source(creature: dict) -> str:
    """来源列：星系名 + 行星序号；缺 UA/行星位为 0 时显示「未知」，不猜。"""
    origin = creature.get("origin") if isinstance(creature, dict) else None
    if not isinstance(origin, dict):
        return "未知"
    galaxy = str(origin.get("galaxy_name") or "").strip()
    if not galaxy and origin.get("galaxy") is not None:
        galaxy = f"银河 #{origin.get('galaxy')}"
    try:
        planet = int(origin.get("planet"))
    except (TypeError, ValueError):
        planet = None
    if galaxy and planet is not None and planet > 0:
        return f"{galaxy} · 行星 #{planet}"
    if galaxy:
        return f"{galaxy} · 行星未知"
    if planet is not None and planet > 0:
        return f"行星 #{planet}"
    return "未知"


def pet_glyphs(creature: dict) -> str | None:
    """只接受 `creature.glyphs` 里已经算好且合法的 12 位门地址。"""
    raw = creature.get("glyphs") if isinstance(creature, dict) else None
    text = str(raw or "").strip().upper()
    return text if portal_glyphs_valid(text) else None


def pet_warp_target(creature: dict) -> dict | None:
    """传送目标；没有合法 glyphs 时返回 None（按钮因此保持禁用）。"""
    glyphs = pet_glyphs(creature)
    if not glyphs:
        return None
    origin = creature.get("origin") if isinstance(creature, dict) else None
    galaxy = None
    if isinstance(origin, dict) and origin.get("galaxy") is not None:
        try:
            galaxy = int(origin.get("galaxy"))
        except (TypeError, ValueError):
            galaxy = None
    return {"glyphs": glyphs, "galaxy": galaxy, "label": pet_source(creature)}


def format_descriptor_groups(groups: Any, limit: int = 4) -> str:
    """描述符分组 → 一行中文摘要；没有分组时给「—」。"""
    if not isinstance(groups, dict) or not groups:
        return "—"
    parts: list[str] = []
    for group, items in list(groups.items())[:max(1, int(limit))]:
        ids = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            part = _text(item.get("id"), "")
            if not part:
                continue
            ids.append(f"{part}{'(稀有)' if item.get('rarity') else ''}")
        if ids:
            parts.append(f"{group}: {', '.join(ids)}")
    return "；".join(parts) or "—"


def fauna_preview_rows(fauna: Any, limit: int = FAUNA_PREVIEW_LIMIT) -> list[str]:
    """动物发现记录 →「名称 · 种子 · 发现者」行；只取前 ``limit`` 条。"""
    rows: list[str] = []
    try:
        count = max(1, int(limit))
    except (TypeError, ValueError):
        count = FAUNA_PREVIEW_LIMIT
    for item in fauna or []:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), "(未命名)")
        seed = _text(item.get("creature_seed"), "—")
        bits = [f"{len(rows) + 1}. {name}", f"种子 {seed}"]
        discoverer = _text(item.get("discoverer"), "")
        if discoverer:
            bits.append(f"发现者 {discoverer}")
        rows.append(" · ".join(bits))
        if len(rows) >= count:
            break
    return rows


def fauna_state_text(res: Any, limit: int = FAUNA_PREVIEW_LIMIT) -> tuple[str, str]:
    """联查结果 → (状态, 中文文案)。

    ``状态`` 为 ``ok`` / ``empty`` / ``error``，分别对应有记录、可定位但没有
    动物记录、地址/存档不可用。调用方据此切换颜色或是否显示「重试」。
    """
    if not isinstance(res, dict):
        return "error", "该行星动物联查失败：返回数据不合法。"
    if res.get("ok") is False:
        reason = _text(res.get("reason"), "未知错误")
        return "error", f"该行星动物联查失败：{reason}。"
    fauna = res.get("fauna") or []
    rows = fauna_preview_rows(fauna, limit)
    if not rows:
        reason = _text(res.get("reason"), "没有找到该行星的动物发现记录")
        return "empty", f"该行星暂无动物记录：{reason}。"
    try:
        total = int(res.get("count") or len(fauna))
    except (TypeError, ValueError):
        total = len(fauna)
    head = f"该行星动物（前 {len(rows)}/{total} 条）："
    return "ok", "\n".join([head, *rows])


def pet_detail_text(creature: dict) -> str:
    """详情区：UA、12 位符文、物种标识与部件分组；缺失字段明确写「未知」。"""
    if not isinstance(creature, dict):
        return "选中一只同伴后查看来源与符文。"
    origin = creature.get("origin")
    lines: list[str] = []
    if isinstance(origin, dict):
        system = origin.get("system")
        system_text = f"（system {int(system):03X}）" if isinstance(system, int) else ""
        lines.append(f"来源：{pet_source(creature)}{system_text}")
        lines.append(f"UA：{_text(origin.get('ua'))}")
    else:
        lines.append("来源：未知（UA 缺失、为 0 或不可解析）")
        lines.append("UA：—")
    glyphs = pet_glyphs(creature)
    if glyphs:
        lines.append(f"符文：{glyphs}")
    elif isinstance(origin, dict):
        lines.append("符文：—（行星位为 0 或地址不合法）")
    else:
        lines.append("符文：—（没有可用的 UA）")
    species = _text(creature.get("species_key"), "未知")
    source = _text(creature.get("species_key_source"), "现有字段推导")
    lines.append(f"物种标识：{species}（来源：{source}）")
    unique = _text(creature.get("unique_id"), "—")
    if unique != "—":
        lines.append(f"唯一 ID：{unique}")
    lines.append(f"部件：{format_descriptor_groups(creature.get('descriptor_groups'))}")
    return "\n".join(lines)


def pet_warp_confirm_text(creature: dict) -> str:
    target = pet_warp_target(creature) or {}
    name = _text((creature or {}).get("name"), "(未命名)")
    label = target.get("label") or pet_source(creature)
    glyphs = target.get("glyphs") or "—"
    return (
        f"即将传送到「{name}」的来源星球：{label}\n"
        f"门地址 {glyphs}。\n\n"
        f"{WARP_WARNING}\n"
        "这是高风险写操作，请确认游戏已就绪。是否继续？")


def pet_warp_message(res: dict | None, creature: dict | None = None) -> tuple[str, str]:
    """传送结果 → (kind, 中文文案)；kind 为 success / unconfirmed / failed。"""
    res = res if isinstance(res, dict) else {}
    label = pet_source(creature or {})
    if not res.get("ok"):
        code = str(res.get("code") or "").strip()
        error = str(res.get("error") or "").strip() or "未知错误"
        message = " · ".join(p for p in (code, error) if p)
        if code == "E_BUILD_UNVERIFIED":
            message += "；" + BUILD_UNVERIFIED_HINT
        return "failed", f"传送失败：{message}"
    if res.get("confirmed") is False:
        detail = str(res.get("confirm_error") or "40 秒内未读回目标位置")
        return ("unconfirmed",
                f"传送未确认：{detail}（命令已执行；失败可用「还原」回滚）")
    return "success", f"已传送到来源星球：{label}"


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
            pet_source(creature),
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
    """同伴标签页；无数据时不伪造 3D 或缩略图。

    ``inline_detail=False`` 时把详情/动作留给外部详情区（船队页右栏），
    本组件只负责列表、加载状态与选中广播。
    """

    selectionChanged = Signal(dict)
    statusChanged = Signal(str)

    def __init__(self, svc: Services | None = None, parent=None,
                 inline_detail: bool = True):
        super().__init__(parent)
        self.svc = svc or get_services()
        self._inline_detail = bool(inline_detail)
        self._path = ""
        self._loaded = False
        self._loading = False
        self._token = 0
        self._payload: dict | None = None
        self._pairs: list[tuple[list[str], dict]] = []
        self._detail_creature: dict | None = None
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
        self.table.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self.table, 1)

        self.detail_label = QLabel("选中一只同伴后查看来源、UA 与符文。")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if self._inline_detail:
            root.addWidget(self.detail_label)

        detail_bar = QHBoxLayout()
        self.copy_glyph_btn = QPushButton("复制符文")
        self.copy_glyph_btn.setObjectName("ghostButton")
        self.copy_glyph_btn.setEnabled(False)
        self.copy_glyph_btn.setToolTip("复制选中同伴来源行星的 12 位门地址")
        self.copy_glyph_btn.clicked.connect(self._copy_glyph)
        detail_bar.addWidget(self.copy_glyph_btn)
        self.warp_btn = QPushButton("传送到来源星球")
        self.warp_btn.setObjectName("primaryButton")
        self.warp_btn.setEnabled(False)
        self.warp_btn.setToolTip("选中一只有合法符文的同伴后可传送到它的来源星球")
        self.warp_btn.clicked.connect(self._warp_selected)
        detail_bar.addWidget(self.warp_btn)
        detail_bar.addStretch(1)
        if self._inline_detail:
            root.addLayout(detail_bar)

        self.status = muted("")
        if self._inline_detail:
            root.addWidget(self.status)

        self.foot = muted(PET_PREVIEW_NOTE)
        if self._inline_detail:
            root.addWidget(self.foot)
        else:
            # 外部详情区接管这些控件；仍保留对象供兼容调用，但不参与布局。
            for widget in (self.detail_label, self.status, self.foot,
                           self.copy_glyph_btn, self.warp_btn):
                widget.setParent(self)
                widget.hide()

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
        if column == 6:
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
        self._pairs = list(pairs)
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
                elif c == 4:
                    item.setToolTip("来源星系 / 行星；没有可解析的 UA 时显示「未知」")
                self.table.setItem(r, c, item)
        header = self.table.horizontalHeader()
        header.setSortIndicator(
            self._sort_column,
            Qt.DescendingOrder if self._sort_desc else Qt.AscendingOrder)
        if pairs:
            self.table.selectRow(0)
            self._show_detail(pairs[0][1])
        else:
            self._clear_detail()

    def _selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._clear_detail()
            return
        row = rows[0].row()
        if 0 <= row < len(self._pairs):
            self._show_detail(self._pairs[row][1])

    def _show_detail(self, creature: dict) -> None:
        self._detail_creature = creature if isinstance(creature, dict) else None
        self.detail_label.setText(pet_detail_text(creature))
        target = pet_warp_target(creature)
        enabled = target is not None
        self.copy_glyph_btn.setEnabled(enabled)
        self.warp_btn.setEnabled(enabled)
        if target:
            self.copy_glyph_btn.setToolTip(f"复制符文 {target['glyphs']}")
            self.warp_btn.setToolTip(
                f"调用游戏内传送门机制，传送到 {target['label']}（门地址 {target['glyphs']}）")
        else:
            self.copy_glyph_btn.setToolTip("这只同伴没有合法符文可复制")
            self.warp_btn.setToolTip("只在符文合法时可用；行星位为 0 或 UA 缺失时不能传送")
        if self._detail_creature is not None:
            self.selectionChanged.emit(dict(self._detail_creature))

    def _clear_detail(self, text: str = "选中一只同伴后查看来源、UA 与符文。") -> None:
        had_selection = self._detail_creature is not None
        self._detail_creature = None
        self.detail_label.setText(text)
        self.copy_glyph_btn.setEnabled(False)
        self.warp_btn.setEnabled(False)
        if had_selection:
            self.selectionChanged.emit({})

    # ---------------------------------------------------------------- 外部详情区

    def selected_creature(self) -> dict | None:
        return dict(self._detail_creature) if self._detail_creature else None

    def copy_glyph(self) -> bool:
        """供外部详情区复用：复制当前选中同伴的符文。"""
        return self._copy_glyph()

    def warp_selected(self) -> None:
        """供外部详情区复用：传送当前选中同伴到来源星球。"""
        self._warp_selected()

    def _set_status(self, text: str) -> None:
        self.status.setText(text)
        self.statusChanged.emit(str(text))

    def _copy_glyph(self) -> bool:
        glyphs = pet_glyphs(self._detail_creature or {})
        if not glyphs:
            text = "复制符文失败：这只同伴没有合法符文。"
            self._set_status(text)
            notify.warn(text)
            return False
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(glyphs)
        text = f"已复制符文：{glyphs}"
        self._set_status(text)
        notify.toast(text)
        return True

    def _warp_selected(self) -> None:
        creature = self._detail_creature or {}
        target = pet_warp_target(creature)
        if not target:
            text = "传送失败：这只同伴没有合法符文（行星位为 0 或 UA 缺失）。"
            self._set_status(text)
            notify.warn("传送失败：请先选择一只有合法符文的同伴")
            return
        answer = QMessageBox.warning(
            self, "确认传送到来源星球", pet_warp_confirm_text(creature),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            self._set_status("已取消传送。")
            return

        glyphs = target["glyphs"]
        self.warp_btn.setEnabled(False)
        self.copy_glyph_btn.setEnabled(False)
        self.warp_btn.setText("传送中…")
        self._set_status(
            f"传送中：正在调用游戏内传送门传送到 {target['label']}（{glyphs}）…")
        notify.toast(f"正在传送到 {target['label']}（{glyphs}）…")

        def restore() -> None:
            self.warp_btn.setText("传送到来源星球")
            still = pet_warp_target(self._detail_creature or {}) is not None
            self.warp_btn.setEnabled(still)
            self.copy_glyph_btn.setEnabled(still)

        def done(res: dict) -> None:
            restore()
            kind, text = pet_warp_message(res, creature)
            self._set_status(text)
            if kind == "success":
                notify.success(text)
            elif kind == "unconfirmed":
                notify.warn(text)
            else:
                notify.error(text)

        def fail(msg: str) -> None:
            restore()
            text = f"传送失败：{msg}"
            self._set_status(text)
            notify.error(text)

        run_worker(self.svc.warp_portal, done, fail,
                   glyphs=glyphs, galaxy=target.get("galaxy"))

    def _show_empty(self, title: str, text: str) -> None:
        self.table.hide()
        self.table.setRowCount(0)
        self._pairs = []
        self._clear_detail()
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
        self._pairs = []
        self._clear_detail()
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
