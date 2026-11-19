"""存档编辑：货币与飞船名称/涂装。

所有读写都交给 ``starforge.services.save_edit``；对话框只负责展示、校验、
二次确认和把结果反馈给 Fleet。备份、原子写、读回校验与回滚由服务层负责。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..widgets.worker import run as run_worker

MAX_CURRENCY = 2 ** 31 - 1
MAX_NAME_LENGTH = 64
CURRENCY_KEYS = ("units", "nanites", "quicksilver")
CURRENCY_LABELS = {"units": "单位", "nanites": "纳米", "quicksilver": "水银"}
_MAX_HINT = f"{MAX_CURRENCY:,}"


# ---------------------------------------------------------------- 纯数据工具


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def currencies_from_result(result) -> dict[str, int]:
    """从服务返回值里取出货币；兼容平铺、currencies、after 等包装。"""
    data = _dict(result)
    for key in ("currencies", "after", "values", "data", "result", "before"):
        sub = data.get(key)
        if isinstance(sub, dict) and any(k in sub for k in CURRENCY_KEYS):
            data = sub
            break
    out: dict[str, int] = {}
    for key in CURRENCY_KEYS:
        if key not in data:
            continue
        try:
            out[key] = int(data[key])
        except (TypeError, ValueError):
            continue
    return out


def currency_changes(current: dict | None, edited: dict | None) -> dict[str, int]:
    """只返回真正改动过的货币；当前值未知的币种不会被提交。"""
    old = _dict(current)
    new = _dict(edited)
    out: dict[str, int] = {}
    for key in CURRENCY_KEYS:
        if key not in old or key not in new:
            continue
        label = CURRENCY_LABELS[key]
        try:
            before = validate_currency(old[key], label)
            after = validate_currency(new[key], label)
        except ValueError:
            continue
        if after != before:
            out[key] = after
    return out


def validate_currency(value, label: str = "金额") -> int:
    """把输入转成非负整数，并在超出存档上限时给出中文错误。"""
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("，", "")
    else:
        text = value
    try:
        number = int(text)
    except (TypeError, ValueError):
        raise ValueError(f"{label}必须是整数") from None
    if number < 0:
        raise ValueError(f"{label}不能为负数")
    if number > MAX_CURRENCY:
        raise ValueError(f"{label}不能超过 {_MAX_HINT}")
    return number


def format_currency(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def validate_ship_name(name) -> str:
    text = str(name or "").strip()
    if not text:
        raise ValueError("飞船名称不能为空")
    if len(text) > MAX_NAME_LENGTH:
        raise ValueError(f"飞船名称不能超过 {MAX_NAME_LENGTH} 个字符")
    return text


def colour_from_value(value) -> QColor | None:
    """兼容 RGB 0..1、RGB 0..255、#rrggbb 和 {"rgb": [...]} 等写法。"""
    if isinstance(value, QColor):
        return QColor(value)
    if isinstance(value, dict):
        for key in ("rgb", "colour", "color", "value", "primary", "accent", "Colour"):
            if key in value:
                found = colour_from_value(value[key])
                if found is not None:
                    return found
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if not text.startswith("#") and len(text) == 6:
            text = "#" + text
        colour = QColor(text)
        return colour if colour.isValid() else None
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            nums = [float(v) for v in value[:3]]
        except (TypeError, ValueError):
            return None
        if all(0.0 <= n <= 1.0 for n in nums):
            return QColor.fromRgbF(nums[0], nums[1], nums[2])
        return QColor(
            max(0, min(255, int(round(nums[0])))),
            max(0, min(255, int(round(nums[1])))),
            max(0, min(255, int(round(nums[2])))),
        )
    return None


def colour_to_rgb(colour: QColor) -> tuple[float, float, float]:
    return (colour.redF(), colour.greenF(), colour.blueF())


def colour_hex(colour: QColor) -> str:
    return colour.name()


def ship_meta_values(result) -> dict:
    """把 ship_meta 的返回值整理成 name/paint/slot（兼容常见包装层）。"""
    data = _dict(result)
    for key in ("meta", "ship", "data", "result", "after", "before"):
        sub = data.get(key)
        if isinstance(sub, dict) and any(
                k in sub for k in ("name", "paint", "palette", "primary", "accent", "slot")):
            data = sub
            break
    paint = data.get("paint")
    if not isinstance(paint, dict):
        paint = {k: data.get(k) for k in
                 ("palette", "primary", "accent", "primary_index", "accent_index", "channels")
                 if k in data}
    name = data.get("name")
    if name is None:
        name = data.get("Name")
    return {"name": "" if name is None else str(name), "paint": paint,
            "slot": data.get("slot")}


def ship_choices(ships: list[dict] | None, current_ship: dict | None = None) -> list[dict]:
    """同型槽位 + 当前槽位；当前槽位排在最前。"""
    current = _dict(current_ship)
    current_slot = current.get("slot")
    try:
        current_slot = int(current_slot) if current_slot is not None else None
    except (TypeError, ValueError):
        current_slot = None
    current_type = current.get("type")

    candidates: list[dict] = []
    if current and current_slot is not None:
        candidates.append(current)
    for ship in ships or []:
        if not isinstance(ship, dict):
            continue
        slot = ship.get("slot")
        if slot is None:
            continue
        if current_type and ship.get("type") != current_type and slot != current_slot:
            continue
        candidates.append(ship)

    out: list[dict] = []
    seen: set[int] = set()
    for ship in candidates:
        try:
            slot = int(ship.get("slot"))
        except (TypeError, ValueError):
            continue
        if slot in seen:
            continue
        seen.add(slot)
        kind = ship.get("type_label") or ship.get("type") or "未知船型"
        prefix = "当前槽位" if slot == current_slot else f"槽位 {slot}"
        label = f"{prefix} · {kind}"
        name = str(ship.get("name") or "").strip()
        if name:
            label += f" · {name}"
        seed = str(ship.get("seed") or "")
        if seed:
            label += f" · {seed[:12]}"
        out.append({"slot": slot, "ship": ship, "label": label})
    out.sort(key=lambda row: (row["slot"] != current_slot, row["slot"]))
    return out


def readable_error(message) -> str:
    """去掉异常类名，尽量只留可读的中文说明。"""
    text = str(message or "").strip()
    for name in ("RuntimeError", "ValueError", "TypeError", "KeyError", "OSError",
                 "ImportError", "ModuleNotFoundError", "BadRequest", "WriteRefused"):
        for sep in (": ", ":"):
            prefix = name + sep
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break
    return text or "未知错误"


def _service():
    try:
        from ...services import save_edit as module
    except Exception as e:                                  # noqa: BLE001
        raise RuntimeError(
            "存档编辑服务不可用：请确认 starforge.services.save_edit 已就绪") from e
    return module


def _copy_target(path: str) -> str:
    if path.endswith(".edited.hg"):
        return path
    base = path[:-3] if path.lower().endswith(".hg") else path
    return base + ".edited.hg"


def _result_path(result, fallback: str, copy: bool) -> str:
    data = _dict(result)
    path = str(data.get("path") or "")
    if path:
        return path
    return _copy_target(fallback) if copy else fallback


# ---------------------------------------------------------------- 后台任务


def _read_currencies(path: str):
    return _service().currencies(path)


def _read_ship_meta(path: str, slot: int):
    return _service().ship_meta(path, slot)


def _write_changes(path: str, changes: dict, copy: bool) -> dict:
    """在一个后台任务里按需写入货币、名称、涂装；副本只复制一次。"""
    service = _service()
    target = str(path)
    made_copy = False
    sections: dict[str, dict] = {}
    order: list[str] = []

    if changes.get("currencies"):
        order.append("currencies")
    if changes.get("name") is not None:
        order.append("name")
    if changes.get("paint"):
        order.append("paint")

    for kind in order:
        use_copy = bool(copy) and not made_copy
        if kind == "currencies":
            result = service.apply_currencies(
                target, confirm=True, copy=use_copy, **changes["currencies"])
        elif kind == "name":
            result = service.apply_ship_name(
                target, int(changes["slot"]), changes["name"],
                confirm=True, copy=use_copy)
        else:
            primary, accent = changes["paint"]
            result = service.apply_ship_paint(
                target, int(changes["slot"]), primary, accent=accent,
                confirm=True, copy=use_copy)
        sections[kind] = result if isinstance(result, dict) else {"ok": True}
        new_target = _result_path(result, target, use_copy)
        if use_copy:
            made_copy = True
        target = new_target

    return {"path": target, "copy": bool(copy), "slot": changes.get("slot"),
            "sections": sections, "changed": order}


# ---------------------------------------------------------------- 对话框


from ..dialogs.confirm import ask_write

class SaveEditDialog(QDialog):
    """货币与飞船名称/涂装编辑；写入前二次确认，成功后可让 Fleet 刷新。"""

    def __init__(self, save_path: str, ships: list[dict] | None = None,
                 current_ship: dict | None = None, parent=None):
        super().__init__(parent)
        # 兼容把 (存档, 当前船, 船队) 顺序传进来的调用。
        if isinstance(ships, dict) and (current_ship is None or isinstance(current_ship, list)):
            ship_arg = ships
            ships = current_ship if isinstance(current_ship, list) else []
            current_ship = ship_arg

        self.save_path = str(save_path or "")
        self.ships = [dict(s) for s in (ships or []) if isinstance(s, dict)]
        self.current_ship = dict(current_ship or {})
        self.changed = False
        self.result: dict | None = None

        self._current_currencies: dict[str, int] = {}
        self._current_meta: dict = {}
        self._current_name = ""
        self._current_primary: QColor | None = None
        self._current_accent: QColor | None = None
        self._has_paint = False
        self._paint_dirty = False
        self._ship_ready = False
        self._busy = False

        self._primary_color = QColor("#c9c9c9")
        self._accent_color = QColor("#5a6474")

        self.setWindowTitle("存档编辑")
        self.resize(680, 560)
        self._build_ui()
        self.refresh()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        title = QLabel("存档编辑")
        title.setStyleSheet("font-size:15px;font-weight:700;")
        root.addWidget(title)

        self.path_label = QLabel(self.save_path or "没有选中存档")
        self.path_label.setObjectName("muted")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.path_label)

        warn = QLabel(
            "写入前会自动备份，写入后读回校验；失败会自动回滚。"
            "勾选「写入副本」时原存档保持不动。")
        warn.setObjectName("muted")
        warn.setWordWrap(True)
        root.addWidget(warn)

        self.tabs = QTabWidget()
        self._build_currency_tab()
        self._build_ship_tab()
        root.addWidget(self.tabs, 1)

        self.copy = QCheckBox("写入副本（save.edited.hg），原档保持不动")
        self.copy.setChecked(True)
        self.copy.setToolTip("建议先在副本上验证；确认无误后再替换原存档。")
        root.addWidget(self.copy)

        self.status = QLabel("正在读取当前存档…")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        self.refresh_btn = QPushButton("重新读取")
        self.refresh_btn.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_btn)
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.ok = QPushButton("写入存档")
        self.ok.setObjectName("primary")
        self.ok.setToolTip("按二次确认写入当前改动；只提交真正改过的项")
        self.ok.clicked.connect(self._apply)
        buttons.addWidget(self.ok)
        root.addLayout(buttons)

    def _build_currency_tab(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 12, 8, 8)

        self.currency_current = QLabel("正在读取当前货币…")
        self.currency_current.setObjectName("muted")
        self.currency_current.setWordWrap(True)
        v.addWidget(self.currency_current)

        form = QFormLayout()
        self.currency_spins: dict[str, QSpinBox] = {}
        for key in CURRENCY_KEYS:
            label = CURRENCY_LABELS[key]
            spin = QSpinBox()
            spin.setRange(0, MAX_CURRENCY)
            spin.setGroupSeparatorShown(True)
            spin.setEnabled(False)
            spin.setToolTip(f"{label}必须是非负整数，上限 {_MAX_HINT}")
            form.addRow(label, spin)
            self.currency_spins[key] = spin
        v.addLayout(form)

        hint = QLabel(
            f"非负整数，上限 {_MAX_HINT}（存档按有符号 32 位存放）；"
            "只提交改动过的币种。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)
        self.tabs.addTab(page, "货币")

    def _build_ship_tab(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 12, 8, 8)

        form = QFormLayout()
        self.slot_box = QComboBox()
        choices = ship_choices(self.ships, self.current_ship)
        for choice in choices:
            self.slot_box.addItem(choice["label"], choice)
        self.slot_box.setEnabled(bool(choices))
        self.slot_box.currentIndexChanged.connect(self._on_slot_changed)
        form.addRow("目标飞船", self.slot_box)

        self.ship_current = QLabel(
            "正在读取飞船信息…" if choices else "这个存档里没有可编辑的飞船。")
        self.ship_current.setObjectName("muted")
        self.ship_current.setWordWrap(True)
        form.addRow("当前信息", self.ship_current)

        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(MAX_NAME_LENGTH)
        self.name_edit.setPlaceholderText("输入飞船名称")
        self.name_edit.setEnabled(False)
        form.addRow("名称", self.name_edit)

        self.primary_btn = QPushButton()
        self.primary_btn.setEnabled(False)
        self.primary_btn.clicked.connect(lambda: self._pick_colour("primary"))
        form.addRow("主色", self.primary_btn)

        self.accent_btn = QPushButton()
        self.accent_btn.setEnabled(False)
        self.accent_btn.clicked.connect(lambda: self._pick_colour("accent"))
        form.addRow("副色", self.accent_btn)
        v.addLayout(form)
        self._paint_buttons()

        hint = QLabel(
            "颜色会按游戏调色板取最近色写入；副色通常用于装饰部位。"
            "只改名时不会提交涂装。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)
        self.tabs.addTab(page, "飞船")

    def _paint_buttons(self) -> None:
        for role, button, colour in (
                ("primary", self.primary_btn, self._primary_color),
                ("accent", self.accent_btn, self._accent_color)):
            label = "主色" if role == "primary" else "副色"
            button.setText(f"{label} {colour_hex(colour)}")
            button.setStyleSheet(
                f"border:1px solid {colour_hex(colour)}; color:{colour_hex(colour)};")

    def _set_ship_fields_enabled(self, enabled: bool) -> None:
        self.name_edit.setEnabled(enabled)
        self.primary_btn.setEnabled(enabled)
        self.accent_btn.setEnabled(enabled)

    def _selected_slot(self) -> int | None:
        data = self.slot_box.currentData()
        if not isinstance(data, dict):
            return None
        try:
            return int(data.get("slot"))
        except (TypeError, ValueError):
            return None

    # ---------------------------------------------------------------- 读取

    def refresh(self) -> None:
        if self._busy:
            return
        if not self.save_path:
            self.status.setText("没有选择存档，无法编辑。")
            self._set_ship_fields_enabled(False)
            for spin in self.currency_spins.values():
                spin.setEnabled(False)
            return
        self.status.setText("正在读取当前存档…")
        self._load_currencies()
        self._load_ship_meta()

    def _load_currencies(self) -> None:
        self.currency_current.setText("正在读取当前货币…")
        for spin in self.currency_spins.values():
            spin.setEnabled(False)
        self._current_currencies = {}

        def done(result) -> None:
            values = currencies_from_result(result)
            self._current_currencies = values
            if values:
                for key, spin in self.currency_spins.items():
                    if key in values:
                        spin.setValue(max(0, min(MAX_CURRENCY, values[key])))
                        spin.setEnabled(True)
                text = "  ·  ".join(
                    f"{CURRENCY_LABELS[key]} {format_currency(values[key])}"
                    for key in CURRENCY_KEYS if key in values)
                self.currency_current.setText(f"当前：{text}")
                self.status.setText("已读取当前货币；修改后点「写入存档」。")
            else:
                self.currency_current.setText("没有读到货币字段；请确认这是玩家存档。")
                self.status.setText("读取货币失败：返回数据里没有单位/纳米/水银。")

        def fail(message: str) -> None:
            text = readable_error(message)
            self.currency_current.setText(f"读取货币失败：{text}")
            self.status.setText(f"读取货币失败：{text}")

        run_worker(_read_currencies, done, fail, self.save_path)

    def _load_ship_meta(self) -> None:
        slot = self._selected_slot()
        self._ship_ready = False
        self._paint_dirty = False
        self._set_ship_fields_enabled(False)
        self._current_meta = {}
        self._current_name = ""
        self._current_primary = None
        self._current_accent = None
        self._has_paint = False
        self._primary_color = QColor("#c9c9c9")
        self._accent_color = QColor("#5a6474")
        self._paint_buttons()
        if slot is None:
            self.ship_current.setText("这个存档里没有可编辑的飞船。")
            return
        self.ship_current.setText(f"正在读取槽位 {slot} 的名称与涂装…")

        def done(result) -> None:
            if slot != self._selected_slot():
                return
            meta = ship_meta_values(result)
            self._current_meta = meta
            self._current_name = str(meta.get("name") or "")
            self.name_edit.setText(self._current_name)

            paint = _dict(meta.get("paint"))
            primary = colour_from_value(paint.get("primary"))
            accent = colour_from_value(paint.get("accent"))
            self._current_primary = primary
            self._current_accent = accent
            self._has_paint = bool(primary or accent)
            if primary is not None:
                self._primary_color = QColor(primary)
            if accent is not None:
                self._accent_color = QColor(accent)
            elif primary is not None:
                self._accent_color = QColor(primary)
            self._paint_buttons()

            name = self._current_name or "（未命名）"
            if self._has_paint:
                paint_text = (f"主色 {colour_hex(self._primary_color)}"
                              f" / 副色 {colour_hex(self._accent_color)}")
            else:
                paint_text = "未设置"
            self.ship_current.setText(f"名称：{name}  ·  涂装：{paint_text}")
            self._ship_ready = True
            self._set_ship_fields_enabled(True)
            self.status.setText(f"已读取飞船槽位 {slot}；修改后点「写入存档」。")

        def fail(message: str) -> None:
            if slot != self._selected_slot():
                return
            text = readable_error(message)
            self.ship_current.setText(f"读取飞船失败：{text}")
            self.status.setText(f"读取飞船失败：{text}")

        run_worker(_read_ship_meta, done, fail, self.save_path, slot)

    def _on_slot_changed(self) -> None:
        self._load_ship_meta()

    # ---------------------------------------------------------------- 编辑

    def _pick_colour(self, role: str) -> None:
        current = self._primary_color if role == "primary" else self._accent_color
        title = "选择主色" if role == "primary" else "选择副色"
        colour = QColorDialog.getColor(current, self, title)
        if not colour.isValid():
            return
        if role == "primary":
            self._primary_color = colour
        else:
            self._accent_color = colour
        self._paint_dirty = True
        self._paint_buttons()
        self.status.setText("颜色已修改；写入后才会保存到存档。")

    def _collect_changes(self) -> dict:
        changes: dict = {"currencies": {}, "slot": None, "name": None, "paint": None}

        edits = {key: spin.value() for key, spin in self.currency_spins.items()}
        if self._current_currencies:
            changed = currency_changes(self._current_currencies, edits)
            changes["currencies"] = changed
        elif any(value for value in edits.values()):
            raise ValueError("还没读到当前货币值，请先点「重新读取」。")

        slot = self._selected_slot()
        name_changed = False
        paint_changed = False
        if slot is not None and self._ship_ready:
            new_name = validate_ship_name(self.name_edit.text())
            if new_name != self._current_name.strip():
                changes["name"] = new_name
                name_changed = True
            if self._has_paint:
                paint_changed = self._paint_dirty or (
                    self._current_primary is not None
                    and self._primary_color != self._current_primary
                ) or (
                    self._current_accent is not None
                    and self._accent_color != self._current_accent
                )
            else:
                paint_changed = self._paint_dirty
            if paint_changed:
                changes["paint"] = (
                    colour_to_rgb(self._primary_color),
                    colour_to_rgb(self._accent_color),
                )
        else:
            if self.name_edit.text().strip() or self._paint_dirty:
                raise ValueError("还没读到飞船信息，请先选择飞船并点「重新读取」。")

        if name_changed or paint_changed:
            changes["slot"] = slot
        return changes

    def _confirmation(self, changes: dict) -> str:
        lines = [f"存档：{self.save_path}"]
        money = changes.get("currencies") or {}
        if money:
            bits = []
            for key in CURRENCY_KEYS:
                if key not in money:
                    continue
                before = self._current_currencies.get(key)
                if before is None:
                    bits.append(f"{CURRENCY_LABELS[key]} → {format_currency(money[key])}")
                else:
                    bits.append(
                        f"{CURRENCY_LABELS[key]} {format_currency(before)}"
                        f" → {format_currency(money[key])}")
            lines.append(f"货币：{'  ·  '.join(bits)}")
        slot = changes.get("slot")
        if changes.get("name") is not None:
            before = self._current_name or "（未命名）"
            lines.append(f"飞船槽位 {slot} 名称：{before} → {changes['name']}")
        if changes.get("paint"):
            primary, accent = changes["paint"]
            lines.append(
                f"飞船槽位 {slot} 涂装：主色 {colour_hex(self._primary_color)}"
                f" / 副色 {colour_hex(self._accent_color)}")
        lines.append("写入前会自动备份，写入后读回校验；失败自动回滚。")
        if self.copy.isChecked():
            lines.append("将写入副本 save.edited.hg（原档保持不动）。")
        else:
            lines.append("将直接修改原存档。")
        lines.append("\n确定写入？")
        return "\n".join(lines)

    def _apply(self) -> None:
        if self._busy:
            return
        if not self.save_path:
            QMessageBox.warning(self, "无法写入", "没有选择存档。")
            return
        try:
            changes = self._collect_changes()
        except ValueError as e:
            QMessageBox.warning(self, "输入有误", str(e))
            return
        if not (changes.get("currencies") or changes.get("name") is not None
                or changes.get("paint")):
            QMessageBox.information(self, "没有改动", "货币、名称和涂装都没有改动。")
            return
        if not ask_write(self, "确认写入", self._confirmation(changes)):
            return

        self._busy = True
        self.ok.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.status.setText("写入中…（备份 → 写入 → 读回校验）")

        def done(result: dict) -> None:
            self._busy = False
            self.ok.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            self.changed = True
            self.result = result if isinstance(result, dict) else {}
            target = str(self.result.get("path") or self.save_path)
            note = "（副本，原档未动）" if self.result.get("copy") else ""
            self.status.setText(f"写入成功{note} · {target}")
            QMessageBox.information(
                self, "写入成功",
                f"已写入{note}：\n{target}\n\n"
                "已自动备份并完成读回校验。")
            self.accept()

        def fail(message: str) -> None:
            self._busy = False
            self.ok.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            text = readable_error(message)
            self.status.setText(f"写入失败：{text}")
            QMessageBox.warning(
                self, "写入失败",
                f"{text}\n\n写入失败会自动回滚；如仍异常，请用「备份恢复」还原。")

        run_worker(_write_changes, done, fail,
                   self.save_path, changes, self.copy.isChecked())
