"""多选对比：2–3 艘飞船并排展示缩略图、船级/属性与部件。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ...data.shipref import TYPE_LABELS
from ...services import get_services
from ..widgets.ui import muted
from ..widgets.worker import run as run_worker

MAX_COMPARE = 3

STAT_LABELS = {
    "damage": "伤害",
    "shield": "护盾",
    "hyperdrive": "超光速",
    "agility": "机动",
}
STAT_ORDER = ("damage", "shield", "hyperdrive", "agility")


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _text(value: object) -> str:
    return str(value or "").strip()


def ship_key(row: dict | None) -> tuple[str, str]:
    """对比去重键：船型不区分大小写，种子统一大写。"""
    data = row or {}
    return (_text(data.get("type")).casefold(), _text(data.get("seed")).upper())


def normalize_compare(rows, limit: int = MAX_COMPARE) -> list[dict]:
    """去重、保序并截断，最多 ``limit`` 艘（默认 3）。"""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = ship_key(row)
        if not key[0] and not key[1]:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
        if len(out) >= max(0, int(limit)):
            break
    return out


def merge_compare(rows, incoming, limit: int = MAX_COMPARE) -> list[dict]:
    """把新条目并入已有对比；重复与超出上限的条目直接忽略。"""
    return normalize_compare([*(rows or []), *(incoming or [])], limit=limit)


def add_to_compare(rows, row: dict, limit: int = MAX_COMPARE) -> list[dict]:
    """并入单艘飞船，返回新的对比列表。"""
    return merge_compare(rows, [row], limit=limit)


def compare_fields(row: dict | None) -> dict:
    """把结果/存档行整理成对比卡片要用的稳定字段。"""
    data = row or {}
    typ = _text(data.get("type"))
    label = _text(data.get("type_label")) or TYPE_LABELS.get(typ, typ) or "未知"
    raw_stats = data.get("stats") or {}
    stats = []
    for key in STAT_ORDER:
        if key not in raw_stats:
            continue
        value = _number(raw_stats.get(key))
        stats.append({"key": key, "label": STAT_LABELS.get(key, key), "value": value,
                      "text": f"{value:g}"})
    parts = [_text(part).upper() for part in (data.get("parts") or []) if _text(part)]
    ship_class = _text(data.get("ship_class")).upper() or "—"
    return {
        "key": ship_key(data),
        "type": typ,
        "type_label": label,
        "name": _text(data.get("name")),
        "seed": _text(data.get("seed")),
        "ship_class": ship_class,
        "stats": stats,
        "stats_text": " · ".join(f"{s['label']} {s['text']}" for s in stats) or "—",
        "parts": parts,
        "parts_text": " ".join(parts) or "—",
        "source": _text(data.get("source")),
    }


class CompareDialog(QDialog):
    """并排对比对话框；可把其中一艘交回飞船实验室的 Inspector。"""

    shipSelected = Signal(object)

    def __init__(self, rows, parent=None, services=None, thumb_size: int = 240):
        super().__init__(parent)
        self.svc = services or get_services()
        self.rows = normalize_compare(rows)
        self.fields = [compare_fields(row) for row in self.rows]
        self.thumb_size = int(thumb_size)
        self._pending = 0
        self._failed = 0
        self._thumbs: list[QLabel] = []
        self._workers = []
        self.setWindowTitle("飞船对比")
        self.resize(1080, 680)
        self._build_ui()
        self._load_thumbs()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        title = QLabel(f"飞船对比（{len(self.rows)} 艘）")
        title.setStyleSheet("font-size:15px;font-weight:700;")
        root.addWidget(title)
        root.addWidget(muted("并排查看缩略图、类型、种子、船级/属性和部件列表；"
                             "最多 3 艘，可在结果列表按 Ctrl / Shift 多选。"))

        self.state = muted("准备加载…")
        root.addWidget(self.state)

        body = QWidget()
        self._cards = QHBoxLayout(body)
        self._cards.setContentsMargins(0, 0, 0, 0)
        self._cards.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        if len(self.rows) < 2:
            self.state.setText("至少需要 2 艘飞船才能对比，请返回结果列表重新选择。")
            hint = QLabel("选择 2–3 艘飞船后点「加入对比」，再点「对比 (N)」。")
            hint.setObjectName("muted")
            hint.setAlignment(Qt.AlignCenter)
            self._cards.addWidget(hint, 1)
        else:
            self.state.setText(f"加载缩略图… 0/{len(self.rows)}")
            for index, (row, fields) in enumerate(zip(self.rows, self.fields)):
                self._cards.addWidget(self._build_card(index, row, fields), 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _build_card(self, index: int, row: dict, fields: dict) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumWidth(300)
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(6)

        thumb = QLabel("缩略图加载中…")
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setMinimumSize(self.thumb_size, self.thumb_size)
        thumb.setStyleSheet("background:#0c1119;border:1px solid #1e2432;border-radius:8px;")
        v.addWidget(thumb)
        self._thumbs.append(thumb)

        heading = QLabel(f"{fields['type_label']}  {fields['seed']}")
        heading.setStyleSheet("font-size:14px;font-weight:700;")
        heading.setWordWrap(True)
        v.addWidget(heading)

        meta = QLabel(f"类型：{fields['type_label']}\n"
                      f"种子：{fields['seed']}\n"
                      f"船级：{fields['ship_class']}")
        meta.setWordWrap(True)
        meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(meta)

        stats = QLabel(f"属性：{fields['stats_text']}")
        stats.setObjectName("muted")
        stats.setWordWrap(True)
        stats.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(stats)

        parts_text = "\n".join(f"· {part}" for part in fields["parts"]) or "—"
        parts = QLabel(f"部件（{len(fields['parts'])}）：\n{parts_text}")
        parts.setObjectName("muted")
        parts.setWordWrap(True)
        parts.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(parts)
        v.addStretch(1)

        choose = QPushButton("设为 Inspector 当前船")
        choose.clicked.connect(lambda _=False, r=row: self._choose(r))
        v.addWidget(choose)
        return card

    # ---------------------------------------------------------------- 加载

    def _load_thumbs(self) -> None:
        if len(self.rows) < 2:
            return
        self._pending = len(self.rows)
        for index, (row, fields) in enumerate(zip(self.rows, self.fields)):
            row_type = fields["type"] or row.get("type")
            seed = fields["seed"] or row.get("seed")
            parts = row.get("parts") or None
            if not row_type or not seed:
                self._thumb_failed(index, "缺少船型或种子")
                continue
            try:
                worker = run_worker(
                    self.svc.preview_png,
                    lambda data, i=index: self._thumb_done(i, data),
                    lambda msg, i=index: self._thumb_failed(i, msg),
                    row_type, seed, parts, self.thumb_size,
                )
                self._workers.append(worker)
            except Exception as e:                          # noqa: BLE001
                self._thumb_failed(index, f"{type(e).__name__}: {e}")

    def _thumb_done(self, index: int, data: bytes) -> None:
        pix = QPixmap()
        if data:
            pix.loadFromData(data, "PNG")
        if pix.isNull():
            self._thumb_failed(index, "缩略图为空")
            return
        if index < len(self._thumbs):
            self._thumbs[index].setPixmap(
                pix.scaled(self.thumb_size, self.thumb_size,
                           Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._thumb_finished()

    def _thumb_failed(self, index: int, msg: str) -> None:
        if index < len(self._thumbs):
            self._thumbs[index].setText(f"缩略图不可用\n{msg or '未知错误'}")
            self._thumbs[index].setWordWrap(True)
        self._failed += 1
        self._thumb_finished()

    def _thumb_finished(self) -> None:
        self._pending = max(0, self._pending - 1)
        done = len(self.rows) - self._pending
        if self._pending:
            self.state.setText(f"加载缩略图… {done}/{len(self.rows)}")
            return
        if self._failed:
            self.state.setText(f"对比已加载；{self._failed} 张缩略图失败，"
                               "其余类型/属性/部件信息仍然可用。")
        else:
            self.state.setText(f"已加载 {len(self.rows)} 艘飞船的缩略图。")

    # ---------------------------------------------------------------- 交互

    def _choose(self, row: dict) -> None:
        self.shipSelected.emit(dict(row))
        self.accept()
