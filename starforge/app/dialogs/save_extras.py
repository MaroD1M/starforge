"""存档扩展编辑：库存、词语/知识、任务、奖励。

只展示和写入 Shipwright ``nms_save`` 已确认的字段。所有写操作调用
``starforge.save.extras``，底层统一走备份、二次确认、原子写、读回校验与回滚；
没有稳定 API 的货船/中队/同伴写回不会出现在这里。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...save import extras as save_extras
from ..widgets.worker import run as run_worker

INVENTORY_HEADERS = ("槽位", "物品", "ID", "数量", "上限", "类型", "状态")
KNOWLEDGE_HEADERS = ("分组", "已学", "总数")
QUEST_HEADERS = ("任务", "步骤", "状态", "键")
REWARD_HEADERS = ("奖励", "ID", "已解锁", "已领取")

STATUS_ZH = {"done": "已完成", "in_progress": "进行中",
             "not_started": "未开始", "unknown": "未知"}
UNLOCK_LABELS = {"tech": "科技蓝图", "products": "制作配方", "base": "基地部件",
                 "customisation": "飞船涂装部件", "refiner": "精炼配方",
                 "cooking": "烹饪配方"}
REWARD_LABELS = {"expedition": "远征奖励", "twitch": "Twitch 掉落",
                 "special": "特殊奖励", "shop": "水银商店"}


def _text(value, fallback: str = "—") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def inventory_rows(payload: dict | None) -> list[list[str]]:
    """库存格子 → 表格行（按 y、x 排序，空库存安全）。"""
    data = payload or {}
    slots = [s for s in data.get("slots") or [] if isinstance(s, dict)]
    try:
        slots.sort(key=lambda s: (int(s.get("y") or 0), int(s.get("x") or 0)))
    except (TypeError, ValueError):
        pass
    rows = []
    for slot in slots:
        rows.append([
            f"{_text(slot.get('x'), '0')},{_text(slot.get('y'), '0')}",
            _text(slot.get("name"), "(未知物品)"),
            _text(slot.get("id")),
            _text(slot.get("amount"), "0"),
            _text(slot.get("max"), "0"),
            _text(slot.get("type")),
            "损坏" if slot.get("damaged") else "正常",
        ])
    return rows


def knowledge_rows(payload: dict | None) -> list[list[str]]:
    rows = []
    for group in (payload or {}).get("groups") or []:
        if not isinstance(group, dict):
            continue
        rows.append([_text(group.get("label") or group.get("group")),
                     _text(group.get("known"), "0"),
                     _text(group.get("total"), "0")])
    return rows


def words_text(payload: dict | None) -> str:
    words = (payload or {}).get("words") or {}
    bits = []
    for race in ("Gek", "Vy'keen", "Korvax", "Atlas", "Autophage"):
        pair = words.get(race)
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            bits.append(f"{race} {pair[0]}/{pair[1]}")
    return " · ".join(bits) or "没有词语数据"


def quest_rows(payload: dict | None) -> list[list[str]]:
    rows = []
    for quest in (payload or {}).get("quests") or []:
        if not isinstance(quest, dict):
            continue
        rows.append([
            _text(quest.get("title") or quest.get("id"), "(未命名任务)"),
            _text(quest.get("step"), ""),
            STATUS_ZH.get(str(quest.get("status") or ""), _text(quest.get("status"))),
            _text(quest.get("key"), ""),
        ])
    return rows


def reward_rows(payload: dict | None) -> list[list[str]]:
    rows = []
    for item in (payload or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        rows.append([
            _text(item.get("name") or item.get("id")),
            _text(item.get("id")),
            "是" if item.get("unlocked") else "否",
            "是" if item.get("redeemed") else "否",
        ])
    return rows


def _read_error_text(action: str, message: str) -> str:
    text = str(message or "").strip()
    for prefix in ("RuntimeError: ", "ValueError: ", "SaveFormatError: ",
                   "BadRequest: ", "WriteRefused: "):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return f"{action}失败：{text or '未知错误'}"


from ..dialogs.confirm import ask_write

class SaveExtrasDialog(QDialog):
    def __init__(self, save_path: str, parent=None):
        super().__init__(parent)
        self.save_path = str(save_path or "")
        self.result: dict | None = None
        self._busy = False
        self._inventories: list[dict] = []
        self._current_inventory: dict | None = None
        self.setWindowTitle("存档扩展编辑")
        self.resize(860, 640)
        self._build_ui()
        self.refresh()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        title = QLabel("存档扩展编辑")
        title.setStyleSheet("font-size:15px;font-weight:700;")
        root.addWidget(title)
        self.path_label = QLabel(self.save_path or "没有选中存档")
        self.path_label.setObjectName("muted")
        self.path_label.setWordWrap(True)
        root.addWidget(self.path_label)
        warn = QLabel("写入前自动备份，写后读回校验；失败自动回滚。"
                      "勾选「写入副本」时原存档保持不动。")
        warn.setObjectName("muted")
        warn.setWordWrap(True)
        root.addWidget(warn)

        self.tabs = QTabWidget()
        self._build_inventory_tab()
        self._build_knowledge_tab()
        self._build_quest_tab()
        self._build_reward_tab()
        root.addWidget(self.tabs, 1)

        self.copy = QCheckBox("写入副本（save.edited.hg），原档保持不动")
        self.copy.setChecked(True)
        root.addWidget(self.copy)

        self.status = QLabel("正在读取存档…")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        self.refresh_btn = QPushButton("重新读取")
        self.refresh_btn.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_btn)
        buttons.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        root.addLayout(buttons)

    @staticmethod
    def _table(headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(list(headers))
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _build_inventory_tab(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 12, 8, 8)
        row = QHBoxLayout()
        row.addWidget(QLabel("库存"))
        self.inventory_combo = QComboBox()
        self.inventory_combo.currentIndexChanged.connect(self._load_inventory)
        row.addWidget(self.inventory_combo, 1)
        refresh = QPushButton("刷新库存")
        refresh.clicked.connect(self._load_inventories)
        row.addWidget(refresh)
        v.addLayout(row)
        self.inventory_info = QLabel("选择库存查看格子。")
        self.inventory_info.setObjectName("muted")
        self.inventory_info.setWordWrap(True)
        v.addWidget(self.inventory_info)
        self.inventory_table = self._table(INVENTORY_HEADERS)
        v.addWidget(self.inventory_table, 1)

        form = QFormLayout()
        self.item_id = QLineEdit()
        self.item_id.setPlaceholderText("物品 ID，例如 ^FUEL1 或 ^TECH_POWER")
        form.addRow("物品 ID", self.item_id)
        self.amount = QSpinBox()
        self.amount.setRange(1, 2 ** 31 - 1)
        self.amount.setValue(1)
        form.addRow("数量", self.amount)
        v.addLayout(form)

        ops = QHBoxLayout()
        for text, op in (("填入选中格", "set"), ("改数量", "amount"),
                         ("清空选中格", "remove"), ("填满堆叠", "fill"),
                         ("科技充满", "recharge"), ("修复损坏", "repair"),
                         ("扩满槽位", "expand")):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, o=op: self._inventory_op(o))
            ops.addWidget(button)
        ops.addStretch(1)
        v.addLayout(ops)
        self.tabs.addTab(page, "库存")

    def _build_knowledge_tab(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 12, 8, 8)
        self.words_label = QLabel("正在读取词语…")
        self.words_label.setObjectName("muted")
        self.words_label.setWordWrap(True)
        v.addWidget(self.words_label)
        self.knowledge_table = self._table(KNOWLEDGE_HEADERS)
        v.addWidget(self.knowledge_table, 1)

        words = QHBoxLayout()
        words.addWidget(QLabel("词语种族"))
        self.race_combo = QComboBox()
        self.race_combo.addItem("全部", None)
        for race in save_extras.RACES:
            self.race_combo.addItem(race, race)
        words.addWidget(self.race_combo)
        learn_words = QPushButton("学会这些词语")
        learn_words.clicked.connect(self._learn_words)
        words.addWidget(learn_words)
        words.addStretch(1)
        v.addLayout(words)

        groups = QHBoxLayout()
        groups.addWidget(QLabel("知识分组"))
        self.unlock_combo = QComboBox()
        for group in save_extras.UNLOCK_GROUPS:
            self.unlock_combo.addItem(UNLOCK_LABELS.get(group, group), group)
        groups.addWidget(self.unlock_combo)
        learn_group = QPushButton("学会整组")
        learn_group.clicked.connect(self._learn_group)
        groups.addWidget(learn_group)
        groups.addStretch(1)
        v.addLayout(groups)
        self.tabs.addTab(page, "知识")

    def _build_quest_tab(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 12, 8, 8)
        self.quest_info = QLabel("任务名来自游戏语言表；没有游戏目录时只显示任务 ID。")
        self.quest_info.setObjectName("muted")
        self.quest_info.setWordWrap(True)
        v.addWidget(self.quest_info)
        self.quest_table = self._table(QUEST_HEADERS)
        v.addWidget(self.quest_table, 1)
        row = QHBoxLayout()
        refresh = QPushButton("刷新任务")
        refresh.clicked.connect(self._load_quests)
        row.addWidget(refresh)
        complete = QPushButton("标记选中为完成")
        complete.clicked.connect(self._complete_quests)
        row.addWidget(complete)
        row.addStretch(1)
        v.addLayout(row)
        self.tabs.addTab(page, "任务")

    def _build_reward_tab(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 12, 8, 8)
        row = QHBoxLayout()
        row.addWidget(QLabel("奖励分组"))
        self.reward_combo = QComboBox()
        for group in save_extras.REWARD_GROUPS:
            self.reward_combo.addItem(REWARD_LABELS.get(group, group), group)
        self.reward_combo.currentIndexChanged.connect(self._load_rewards)
        row.addWidget(self.reward_combo, 1)
        refresh = QPushButton("刷新奖励")
        refresh.clicked.connect(self._load_rewards)
        row.addWidget(refresh)
        v.addLayout(row)
        self.reward_info = QLabel("选择分组查看奖励。")
        self.reward_info.setObjectName("muted")
        self.reward_info.setWordWrap(True)
        v.addWidget(self.reward_info)
        self.reward_table = self._table(REWARD_HEADERS)
        v.addWidget(self.reward_table, 1)
        ops = QHBoxLayout()
        for text, unlock, redeemed in (("解锁选中", True, None), ("锁定选中", False, None),
                                       ("标记已领取", None, True), ("设为可再领", None, False)):
            button = QPushButton(text)
            button.clicked.connect(
                lambda _=False, u=unlock, r=redeemed: self._apply_rewards(u, r))
            ops.addWidget(button)
        ops.addStretch(1)
        v.addLayout(ops)
        self.tabs.addTab(page, "奖励")

    # ---------------------------------------------------------------- 后台任务

    def _run(self, fn, done, action: str, *args, exclusive: bool = False) -> None:
        if exclusive and self._busy:
            return
        if exclusive:
            self._busy = True
        self.status.setText(f"{action}…")

        def ok(result) -> None:
            self._busy = False
            done(result)

        def fail(message: str) -> None:
            self._busy = False
            self.status.setText(_read_error_text(action, message))

        run_worker(fn, ok, fail, *args)

    @staticmethod
    def _fill(table: QTableWidget, rows: list[list[str]], data: list[dict] | None = None) -> None:
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                if data is not None and j == 0:
                    item.setData(Qt.UserRole, data[i])
                table.setItem(i, j, item)
        table.resizeColumnsToContents()

    # ---------------------------------------------------------------- 库存

    def _load_inventories(self) -> None:
        def done(payload: dict) -> None:
            self._inventories = list(payload.get("inventories") or [])
            self.inventory_combo.blockSignals(True)
            self.inventory_combo.clear()
            for inv in self._inventories:
                self.inventory_combo.addItem(
                    f"{inv.get('group') or ''} · {inv.get('name') or inv.get('path')} "
                    f"({inv.get('used', 0)}/{inv.get('slots', 0)})", inv.get("path"))
            self.inventory_combo.blockSignals(False)
            self.status.setText(f"{payload.get('path')} · {len(self._inventories)} 个库存")
            if self._inventories:
                self._load_inventory()

        self._run(save_extras.inventories, done, "读取库存", self.save_path)

    def _load_inventory(self, *_args) -> None:
        path = self.inventory_combo.currentData()
        if not path:
            return

        def done(payload: dict) -> None:
            self._current_inventory = payload
            self._fill(self.inventory_table, inventory_rows(payload))
            self.inventory_info.setText(
                f"{payload.get('path')} · {payload.get('width')}×{payload.get('height')} · "
                f"已用 {len(payload.get('slots') or [])} · 上限 {payload.get('max_slots') or '—'}")
            self.status.setText("库存已读取")

        self._run(save_extras.inventory, done, "读取库存", self.save_path, str(path))

    def _selected_slot(self) -> tuple[int, int] | None:
        rows = self.inventory_table.selectionModel().selectedRows()
        if not rows:
            return None
        text = self.inventory_table.item(rows[0].row(), 0).text()
        try:
            x, y = (int(v) for v in text.split(",", 1))
        except (TypeError, ValueError):
            return None
        return x, y

    def _inventory_op(self, op: str) -> None:
        path = self.inventory_combo.currentData()
        if not path:
            QMessageBox.information(self, "库存", "先选择一个库存")
            return
        kw: dict = {}
        if op in ("set", "amount", "remove"):
            slot = self._selected_slot()
            if slot is None:
                QMessageBox.information(self, "库存", "先在表格里选中一个格子")
                return
            kw.update(x=slot[0], y=slot[1])
        if op == "set":
            item_id = self.item_id.text().strip()
            if not item_id:
                QMessageBox.information(self, "库存", "填入物品需要物品 ID")
                return
            kw.update(id=item_id, amount=self.amount.value())
        elif op == "amount":
            kw.update(amount=self.amount.value())
        if not ask_write(self, "确认写入",
                f"将对库存 {path} 执行「{op}」。会先备份，写后读回校验；继续？",):
            return

        def done(result: dict) -> None:
            self.status.setText("库存写入成功，已通过读回校验")
            self.result = {"kind": "inventory", "path": result.get("path"),
                           "copy": result.get("copy")}
            if result.get("path"):
                self.save_path = str(result["path"])
                self.path_label.setText(self.save_path)
            self._load_inventory()

        self._run(save_extras.apply_inventory, done, "写入库存",
                  self.save_path, str(path), op, True, self.copy.isChecked(),
                  exclusive=True, **kw)

    # ---------------------------------------------------------------- 知识

    def _load_knowledge(self) -> None:
        def done(payload: dict) -> None:
            self._fill(self.knowledge_table, knowledge_rows(payload))
            self.words_label.setText(words_text(payload))
            self.status.setText(f"{payload.get('path')} · 知识进度已读取")

        self._run(save_extras.knowledge, done, "读取知识", self.save_path)

    def _learn_words(self) -> None:
        race = self.race_combo.currentData()
        label = race or "全部种族"
        if not ask_write(self, "确认写入",
                f"将学会{label}的全部词语。会先备份，写后读回校验；继续？",):
            return

        def done(result: dict) -> None:
            self.status.setText(f"学会词语成功 · 新增 {result.get('added', 0)}")
            self.result = {"kind": "words", "path": result.get("path"),
                           "copy": result.get("copy")}
            if result.get("path"):
                self.save_path = str(result["path"])
                self.path_label.setText(self.save_path)
            self._load_knowledge()

        self._run(save_extras.apply_words, done, "学习词语", self.save_path,
                  [race] if race else None, True, self.copy.isChecked(), exclusive=True)

    def _learn_group(self) -> None:
        group = self.unlock_combo.currentData()
        label = UNLOCK_LABELS.get(group, group)
        if not ask_write(self, "确认写入",
                f"将学会「{label}」整组内容。会先备份，写后读回校验；继续？",):
            return

        def done(result: dict) -> None:
            self.status.setText(f"学习知识成功 · 新增 {result.get('added', 0)}")
            self.result = {"kind": "knowledge", "path": result.get("path"),
                           "copy": result.get("copy")}
            if result.get("path"):
                self.save_path = str(result["path"])
                self.path_label.setText(self.save_path)
            self._load_knowledge()

        self._run(save_extras.apply_learn_all, done, "学习知识", self.save_path,
                  str(group), True, self.copy.isChecked(), exclusive=True)

    # ---------------------------------------------------------------- 任务

    def _load_quests(self) -> None:
        def done(payload: dict) -> None:
            quests = [q for q in payload.get("quests") or [] if isinstance(q, dict)]
            self._fill(self.quest_table, quest_rows(payload), quests)
            self.quest_info.setText(f"{payload.get('path')} · {len(quests)} 个任务")
            self.status.setText("任务已读取")

        self._run(save_extras.quests, done, "读取任务", self.save_path)

    def _complete_quests(self) -> None:
        rows = self.quest_table.selectionModel().selectedRows()
        keys = []
        for row in rows:
            quest = self.quest_table.item(row.row(), 0).data(Qt.UserRole) or {}
            if quest.get("key"):
                keys.append(quest["key"])
        if not keys:
            QMessageBox.information(self, "任务", "先选中要完成的任务")
            return
        if not ask_write(self, "确认写入",
                f"将把 {len(keys)} 个任务标记为完成。会先备份，写后读回校验；继续？",):
            return

        def done(result: dict) -> None:
            self.status.setText(f"任务写入成功 · {len(keys)} 个已标记完成")
            self.result = {"kind": "quests", "path": result.get("path"),
                           "copy": result.get("copy")}
            if result.get("path"):
                self.save_path = str(result["path"])
                self.path_label.setText(self.save_path)
            self._load_quests()

        self._run(save_extras.apply_skip_quests, done, "写入任务",
                  self.save_path, keys, True, self.copy.isChecked(), exclusive=True)

    # ---------------------------------------------------------------- 奖励

    def _load_rewards(self, *_args) -> None:
        group = self.reward_combo.currentData()
        if not group:
            return

        def done(payload: dict) -> None:
            items = [r for r in payload.get("items") or [] if isinstance(r, dict)]
            self._fill(self.reward_table, reward_rows(payload), items)
            self.reward_info.setText(
                f"{payload.get('path')} · 显示 {payload.get('shown', len(items))}/{len(items)} 条")
            self.status.setText("奖励已读取")

        self._run(save_extras.rewards, done, "读取奖励",
                  self.save_path, str(group), "", 100_000)

    def _apply_rewards(self, unlock: bool | None, redeemed: bool | None) -> None:
        group = self.reward_combo.currentData()
        rows = self.reward_table.selectionModel().selectedRows()
        ids = []
        for row in rows:
            item = self.reward_table.item(row.row(), 0).data(Qt.UserRole) or {}
            if item.get("id"):
                ids.append(item["id"])
        if not group:
            return
        if not ids:
            QMessageBox.information(self, "奖励", "先选中要修改的奖励")
            return
        action = ("解锁" if unlock else "锁定") if unlock is not None else (
            "标记已领取" if redeemed else "设为可再领")
        if not ask_write(self, "确认写入",
                f"将对 {len(ids)} 个奖励执行「{action}」。会先备份，写后读回校验；继续？",):
            return

        def done(result: dict) -> None:
            self.status.setText(f"奖励写入成功 · {action} {len(ids)} 个")
            self.result = {"kind": "rewards", "path": result.get("path"),
                           "copy": result.get("copy")}
            if result.get("path"):
                self.save_path = str(result["path"])
                self.path_label.setText(self.save_path)
            self._load_rewards()

        self._run(save_extras.apply_rewards, done, "写入奖励",
                  self.save_path, str(group), ids, unlock, redeemed, True,
                  self.copy.isChecked(), exclusive=True)

    # ---------------------------------------------------------------- 加载

    def refresh(self) -> None:
        if not self.save_path:
            self.status.setText("没有选中存档")
            return
        self._load_inventories()
        self._load_knowledge()
        self._load_quests()
        self._load_rewards()


__all__ = [
    "INVENTORY_HEADERS",
    "KNOWLEDGE_HEADERS",
    "QUEST_HEADERS",
    "REWARD_HEADERS",
    "STATUS_ZH",
    "SaveExtrasDialog",
    "inventory_rows",
    "knowledge_rows",
    "quest_rows",
    "reward_rows",
    "words_text",
]
