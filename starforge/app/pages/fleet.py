"""我的船队：存档 → 船只网格 → 3D 详情。"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSplitter, QStyledItemDelegate, QTabWidget, QVBoxLayout,
                               QWidget)

from ...export import export_zip
from ...services import get_services
from .. import notify
from ..dialogs.backup import BackupDialog
from ..dialogs.class_editor import ClassEditorDialog
from ..dialogs.save_edit import SaveEditDialog
from ..widgets.feedback import EmptyState, ErrorBanner, LoadingOverlay
from ..widgets.page_header import PageHeader
from ..widgets.pets_view import PetsView
from ..widgets.ship_card import install_card_delegate
from ..widgets.ship_viewer import ShipViewer
from ..widgets.ui import Card, icon_from_png, muted
from ..widgets.worker import run as run_worker


STAT_LABELS = {"damage": "伤害", "shield": "护盾", "hyperdrive": "超空间驱动",
               "agility": "机动性"}


def _write_export(path: str, items: list[dict]) -> dict:
    """后台线程：生成 zip 并落盘，返回纯数据给 UI。"""
    data, stats = export_zip(items)
    Path(path).write_bytes(data)
    return {"path": path, **stats}


class FleetPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self._loaded = False
        self._loaded_path = ""
        self._exporting = False
        self._loading = False
        self._editing = False
        self._restoring = False
        self._watched_path = ""
        self._watch_ignore_until = 0.0
        self._ships: list[dict] = []
        self._sort_key = "type"
        self._sort_desc = False
        self._thumb_queue: list[QListWidgetItem] = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._next_thumb)
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.timeout.connect(self._on_watch_timeout)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_save_file_changed)
        self._build_ui()
        self.loading_overlay = LoadingOverlay(self, "正在读取存档…")
        self.loading = self.loading_overlay
        self.overlay = self.loading_overlay
        self.empty = self.empty_state
        self.error = self.error_banner
        self._update_ship_empty()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(8)

        self.header = PageHeader(
            "我的船队",
            "监视存档变化，随时备份恢复或批量导出，并查看飞船属性与 3D 模型。")
        root.addWidget(self.header)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        left = Card("存档", "自动发现或手动选择")
        v = left.v
        self.path = QLineEdit()
        self.path.setPlaceholderText("save.hg")
        v.addWidget(self.path)
        row = QHBoxLayout()
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        row.addStretch(1)
        v.addLayout(row)
        self.info = muted("选择存档后读取")
        v.addWidget(self.info)
        v.addStretch(1)
        split.addWidget(left)

        self.load_btn = QPushButton("读取存档")
        self.load_btn.setObjectName("primary")
        self.load_btn.setToolTip("读取当前存档中的飞船与同伴")
        self.load_btn.clicked.connect(self._load)
        self.header.add_action(self.load_btn)

        self.backup_btn = QPushButton("备份恢复")
        self.backup_btn.setToolTip("查看已有备份，或从备份恢复当前存档")
        self.backup_btn.clicked.connect(self._open_backups)
        self.header.add_action(self.backup_btn)

        self.save_edit_btn = QPushButton("存档编辑…")
        self.save_edit_btn.setEnabled(False)
        self.save_edit_btn.setToolTip("修改存档中的货币与飞船名称/涂装；先备份，可写入副本")
        self.save_edit_btn.clicked.connect(self._open_save_edit)
        self.header.add_action(self.save_edit_btn)

        self.export_btn = QPushButton("批量导出")
        self.export_btn.setEnabled(False)
        self.export_btn.setToolTip("把当前存档中的飞船导出为压缩包（ZIP；含 3D 模型文件 glb、预览图 png 与清单）")
        self.export_btn.clicked.connect(self._export_all)
        self.header.add_action(self.export_btn)

        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(8, 0, 8, 0)
        self.tabs = QTabWidget()
        mv.addWidget(self.tabs, 1)

        ship_tab = QWidget()
        sv = QVBoxLayout(ship_tab)
        sv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.result_info = QLabel("还没有飞船")
        self.result_info.setObjectName("muted")
        bar.addWidget(self.result_info)
        bar.addStretch(1)

        self.sort_mode = QComboBox()
        self.sort_mode.addItem("按类型", "type")
        self.sort_mode.addItem("按等级", "class")
        self.sort_mode.addItem("按种子", "seed")
        self.sort_mode.currentIndexChanged.connect(self._apply_sort)
        bar.addWidget(self.sort_mode)

        self.sort_order = QComboBox()
        self.sort_order.addItem("升序", False)
        self.sort_order.addItem("降序", True)
        self.sort_order.currentIndexChanged.connect(self._apply_sort)
        bar.addWidget(self.sort_order)

        self.view_mode = QComboBox()
        self.view_mode.addItem("卡片", "grid")
        self.view_mode.addItem("列表", "list")
        self.view_mode.currentIndexChanged.connect(self._apply_view_mode)
        bar.addWidget(self.view_mode)

        sv.addLayout(bar)

        self.error_banner = ErrorBanner()
        self.error_banner.set_retry_callback(self._load)
        sv.addWidget(self.error_banner)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setWordWrap(False)
        self._card_delegate = install_card_delegate(self.list, 110)
        self.list.itemSelectionChanged.connect(self._select)
        sv.addWidget(self.list, 1)

        self.empty_state = EmptyState(
            "没有存档",
            "选择 save.hg 后点「读取存档」；监视到存档变化会自动刷新。",
            icon="◇", button_text="读取存档")
        self.empty_state.set_action("读取存档", self._load)
        sv.addWidget(self.empty_state, 1)
        self.tabs.addTab(ship_tab, "飞船")

        self.pets = PetsView(self.svc)
        self.tabs.addTab(self.pets, "同伴")
        self.tabs.currentChanged.connect(self._tab_changed)
        split.addWidget(mid)

        right = Card("飞船详情")
        rv = right.v
        self.title = QLabel("未选择飞船")
        self.title.setStyleSheet("font-size:15px;font-weight:700;")
        rv.addWidget(self.title)
        self.viewer = ShipViewer()
        self.viewer.setMinimumHeight(300)
        rv.addWidget(self.viewer, 1)
        self.pets_note = QLabel("同伴 3D 预览需要生物生成器；当前只展示描述符与种子。")
        self.pets_note.setWordWrap(True)
        self.pets_note.setAlignment(Qt.AlignCenter)
        self.pets_note.setMinimumHeight(300)
        self.pets_note.hide()
        rv.addWidget(self.pets_note, 1)
        self.detail = muted("选中一艘飞船后在这里查看 3D 模型、等级与属性。")
        rv.addWidget(self.detail)
        row2 = QHBoxLayout()
        copy = QPushButton("复制种子")
        copy.clicked.connect(self._copy_seed)
        row2.addWidget(copy)
        self.edit_btn = QPushButton("船级/属性…")
        self.edit_btn.setEnabled(False)
        self.edit_btn.setToolTip("修改选中飞船的等级与属性；先备份，可写入副本")
        self.edit_btn.clicked.connect(self._open_class_editor)
        row2.addWidget(self.edit_btn)
        compare = QPushButton("加入对比")
        compare.setEnabled(False)
        row2.addWidget(compare)
        rv.addLayout(row2)
        split.addWidget(right)
        split.setSizes([300, 720, 420])

    # ---------------------------------------------------------------- 数据

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._auto()

    def _auto(self) -> None:
        if self.path.text().strip():
            self._load()
            return

        def done(res: dict) -> None:
            p = res.get("path") or ""
            if p:
                self.path.setText(p)
                self._load()
            else:
                self.info.setText("没有自动找到存档；请点「浏览…」选择 save.hg")
                self._show_ship_empty("没有存档", "没有自动找到存档；请点「浏览…」选择 save.hg。")

        def fail(msg: str) -> None:
            text = f"没有自动找到存档：{msg}"
            self.info.setText(text)
            self._show_ship_empty("没有存档", text)

        run_worker(self.svc.default_save, done, fail)

    def _browse(self) -> None:
        start = self.path.text()
        if start and not Path(start).is_file():
            start = str(Path(start).parent) if Path(start).parent.exists() else ""
        p, _ = QFileDialog.getOpenFileName(self, "选择存档", start, "存档 (*.hg);;所有文件 (*)")
        if p:
            self.path.setText(p)
            self._load()

    def _open_backups(self) -> None:
        path = self.path.text().strip()
        if not path:
            self.info.setText("请先选择或读取存档，再查看备份")
            self._show_ship_empty("没有存档", "请先选择或读取存档，再查看备份。")
            notify.warn("请先选择或读取存档")
            return
        dlg = BackupDialog(path, self)
        self._restoring = True
        try:
            dlg.exec()
        finally:
            self._restoring = False
        if dlg.restored:
            self._watch_ignore_until = time.monotonic() + 2.0
            notify.success("存档恢复成功，正在刷新")
            self._load()

    # ---------------------------------------------------------------- 存档监视

    def _watch_save(self, path: str) -> None:
        path = str(path or "").strip()
        if path == self._watched_path and (not path or path in self._watcher.files()):
            return
        for old in list(self._watcher.files()):
            self._watcher.removePath(old)
        self._watched_path = path
        if path and Path(path).is_file() and path not in self._watcher.files():
            self._watcher.addPath(path)

    def _on_save_file_changed(self, path: str) -> None:
        path = str(path)
        if self._watched_path and path != self._watched_path:
            return
        if path and Path(path).is_file() and path not in self._watcher.files():
            self._watcher.addPath(path)
        if self._is_busy():
            return
        self._watch_timer.start(1000)

    def _on_watch_timeout(self) -> None:
        if self._is_busy() or time.monotonic() < self._watch_ignore_until:
            return
        path = self.path.text().strip() or self._loaded_path
        if not path or not Path(path).is_file():
            return
        self._load(notice="存档已变化，已刷新")

    def _is_busy(self) -> bool:
        return self._exporting or self._editing or self._restoring or self._loading

    def _tab_changed(self, index: int) -> None:
        is_pets = self.tabs.widget(index) is self.pets
        if is_pets:
            self.title.setText("同伴")
            self.viewer.hide()
            self.pets_note.show()
            self.detail.setText("同伴目前只读：描述符、种子、群系；3D 需要生物生成器。")
            if self._loaded_path:
                self.pets.set_save_path(self._loaded_path)
                self.pets.ensure_loaded()
        else:
            self.title.setText("飞船详情" if hasattr(self, "title") else "飞船详情")
            self.pets_note.hide()
            self.viewer.show()
            self.detail.setText("选中一艘飞船后在这里查看 3D 模型、等级与属性。")

    def _status(self, text: str) -> None:
        window = self.window()
        status = getattr(window, "statusBar", None)
        if callable(status):
            try:
                status().showMessage(text, 4000)
                return
            except Exception:                          # noqa: BLE001
                pass
        self.info.setText(text)

    def _load(self, notice: str = "") -> None:
        self._loading = True
        self._thumb_timer.stop()
        self._thumb_queue.clear()
        self.load_btn.setEnabled(False)
        self.error_banner.clear()
        self.info.setText("正在读取存档…")
        self.result_info.setText("正在读取存档…")
        self.list.clear()
        self.list.hide()
        self.empty_state.hide()
        self.pets.clear()
        self._ships = []
        self._loaded_path = ""
        self._update_actions()
        self.loading_overlay.start("正在读取存档…")

        def done(res: dict) -> None:
            self._loading = False
            self.loading_overlay.stop()
            self.error_banner.clear()
            self._loaded_path = str(res.get("path") or "")
            self._ships = res.get("ships") or []
            self.result_info.setText(f"{len(self._ships)} 艘  ·  {res.get('path')}")
            warns = res.get("warnings") or []
            self.info.setText(f"{len(self._ships)} 艘" + (f"  ·  {len(warns)} 条警告" if warns else ""))
            self._rebuild_ship_list()
            self.load_btn.setEnabled(True)
            self._watch_save(self._loaded_path)
            self.pets.set_save_path(self._loaded_path, invalidate=True)
            self._update_actions()
            self._update_ship_empty()
            if notice:
                notify.toast(notice, "info")

        def fail(msg: str) -> None:
            self._loading = False
            self.loading_overlay.stop()
            text = f"读取存档失败：{msg}"
            self.info.setText(text)
            self.result_info.setText("读取失败")
            self._ships = []
            self._loaded_path = ""
            self.list.clear()
            self.pets.clear()
            self.load_btn.setEnabled(True)
            self.error_banner.show_error(text)
            self._show_ship_empty("读取失败", "请检查存档路径后重试。")
            self._update_actions()
            notify.error(text)

        run_worker(self.svc.ships, done, fail, self.path.text().strip() or None)

    def _next_thumb(self) -> None:
        if not self._thumb_queue:
            return
        item = self._thumb_queue.pop(0)
        s = item.data(Qt.UserRole) or {}
        if not s.get("procedural", True):
            if self._thumb_queue:
                self._thumb_timer.start(20)
            return

        def done(data: bytes) -> None:
            try:
                item.setIcon(icon_from_png(data, 160))
            except Exception:                              # noqa: BLE001
                pass
            if self._thumb_queue:
                self._thumb_timer.start(30)

        def fail(_msg: str) -> None:
            if self._thumb_queue:
                self._thumb_timer.start(30)

        run_worker(self.svc.preview_png, done, fail,
                   s.get("type"), s.get("seed"), s.get("parts"), 240)

    def _apply_view_mode(self) -> None:
        grid = self.view_mode.currentData() == "grid"
        self.list.setViewMode(QListWidget.IconMode if grid else QListWidget.ListMode)
        if grid:
            self._card_delegate = install_card_delegate(self.list, 110)
        else:
            self.list.setItemDelegate(QStyledItemDelegate(self.list))
            self.list.setIconSize(QSize(72, 50))
            self.list.setGridSize(QSize())

    # ---------------------------------------------------------------- 排序/空态

    def _sorted_ships(self) -> list[dict]:
        key = self._sort_key

        def value(ship: dict):
            if key == "class":
                primary = ship.get("ship_class") or ""
            elif key == "seed":
                primary = ship.get("seed") or ""
            else:
                primary = ship.get("type_label") or ship.get("type") or ""
            return (str(primary).casefold(), str(ship.get("seed") or "").casefold())

        return sorted(self._ships, key=value, reverse=self._sort_desc)

    def _selected_seed(self) -> str:
        items = self.list.selectedItems()
        if not items:
            return ""
        return str((items[0].data(Qt.UserRole) or {}).get("seed") or "")

    def _apply_sort(self) -> None:
        self._sort_key = str(self.sort_mode.currentData() or "type")
        self._sort_desc = bool(self.sort_order.currentData())
        if self._ships:
            self._rebuild_ship_list()

    def _rebuild_ship_list(self) -> None:
        selected = self._selected_seed()
        self.list.clear()
        self._thumb_queue.clear()
        for s in self._sorted_ships():
            item = QListWidgetItem(s.get("seed") or "")
            item.setData(Qt.UserRole, s)
            item.setToolTip(f"{s.get('type_label') or s.get('type')}  {s.get('ship_class') or ''}")
            self.list.addItem(item)
            self._thumb_queue.append(item)
            if selected and str(s.get("seed") or "") == selected:
                item.setSelected(True)
        if self._thumb_queue:
            self._thumb_timer.start(50)

    def _show_ship_empty(self, title: str, description: str = "") -> None:
        self.list.hide()
        self.empty_state.title_label.setText(title)
        self.empty_state.description_label.setText(description)
        self.empty_state.description_label.setVisible(bool(description))
        self.empty_state.show()

    def _update_ship_empty(self) -> None:
        if self._loading:
            self.list.hide()
            self.empty_state.hide()
            return
        if self._ships:
            self.list.show()
            self.empty_state.hide()
            return
        if self._loaded_path:
            self._show_ship_empty(
                "没有飞船", "这个存档里没有飞船；可以备份恢复，或重新读取存档。")
        else:
            self._show_ship_empty(
                "没有存档", "选择 save.hg 后点「读取存档」；监视到存档变化会自动刷新。")

    # ---------------------------------------------------------------- Inspector

    def _select(self) -> None:
        self._update_actions()
        items = self.list.selectedItems()
        if not items:
            return
        s = items[0].data(Qt.UserRole) or {}
        self.title.setText(f"{s.get('type_label') or s.get('type')}  {s.get('seed')}")
        self.detail.setText("生成 3D 几何…")

        def done(mesh: dict) -> None:
            self.viewer.set_mesh(mesh.get("groups") or {}, mesh.get("colours") or {})
            stats = s.get("stats") or {}
            st = "  ".join(f"{STAT_LABELS.get(k, k)}: {v}" for k, v in stats.items()) or "无属性数据"
            self.detail.setText(f"{st}\n{mesh.get('verts', 0):,} 顶点 / {mesh.get('tris', 0):,} 三角")

        def fail(msg: str) -> None:
            try:
                self.viewer.set_demo()
            except Exception:
                pass
            self.detail.setText(f"真实 3D 不可用（{msg}）")

        run_worker(self.svc.preview_mesh, done, fail,
                   s.get("type"), s.get("seed"), s.get("parts"))

    def _update_actions(self) -> None:
        items = self.list.selectedItems()
        ship = items[0].data(Qt.UserRole) if items else None
        self.save_edit_btn.setEnabled(bool(self._loaded_path) and not self._is_busy())
        self.export_btn.setEnabled(bool(self._ships) and not self._exporting)
        self.edit_btn.setEnabled(bool(ship) and ship.get("slot") is not None
                                 and bool(self._loaded_path))

    def _export_all(self) -> None:
        if not self._ships:
            self.info.setText("还没有飞船可导出：请先读取存档")
            notify.warn("还没有飞船可导出，请先读取存档")
            return
        start = "starforge-fleet.zip"
        if self._loaded_path:
            p = Path(self._loaded_path)
            start = str(p.with_name(f"{p.stem}-ships.zip"))
        path, _ = QFileDialog.getSaveFileName(
            self, "导出全部飞船", start, "ZIP 压缩包 (*.zip);;所有文件 (*)")
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        items = [{k: s.get(k) for k in ("type", "seed", "parts", "name") if k in s}
                 for s in self._ships]
        self._exporting = True
        self._update_actions()
        self.info.setText(f"导出 {len(items)} 艘到 {path}…")

        def done(res: dict) -> None:
            self._exporting = False
            self._update_actions()
            failed = int(res.get("failed") or 0)
            exported = int(res.get("exported") or 0)
            count = int(res.get("count") or len(items))
            tail = f" · 失败 {failed}" if failed else ""
            self.info.setText(f"导出完成 {exported}/{count} 艘{tail} · {res.get('path')}")
            if failed:
                notify.warn(f"导出完成 {exported}/{count} 艘，失败 {failed} 艘；详情见压缩包内的清单")
            else:
                notify.success(f"导出成功：{exported}/{count} 艘飞船")

        def fail(msg: str) -> None:
            self._exporting = False
            self._update_actions()
            self.info.setText(f"导出失败：{msg}")
            notify.error(f"导出失败：{msg}")

        run_worker(_write_export, done, fail, path, items)

    def _open_class_editor(self) -> None:
        items = self.list.selectedItems()
        if not items:
            self.info.setText("先选中一艘飞船再修改船级/属性")
            notify.warn("先选中一艘飞船")
            return
        ship = items[0].data(Qt.UserRole) or {}
        path = self._loaded_path or self.path.text().strip()
        if not path:
            self.info.setText("请先读取存档，再修改船级/属性")
            notify.warn("请先读取存档")
            return
        if ship.get("slot") is None:
            self.info.setText("这艘飞船没有可写入的槽位")
            notify.warn("这艘飞船没有可写入的槽位")
            return
        dlg = ClassEditorDialog(path, ship, self)
        self._editing = True
        try:
            accepted = dlg.exec() == QDialog.Accepted
        finally:
            self._editing = False
        if not accepted:
            return
        self._watch_ignore_until = time.monotonic() + 2.0
        res = dlg.result or {}
        target = str(res.get("path") or "")
        if res.get("copy") and target:
            self.path.setText(target)
        summary = f"船级/属性写入成功 · 槽位 {res.get('slot', ship.get('slot'))}"
        self.info.setText(summary)
        notify.success(summary)
        self._load()

    def _open_save_edit(self) -> None:
        if not self._loaded_path:
            self.info.setText("请先读取存档，再编辑货币与飞船")
            notify.warn("请先读取存档")
            return
        items = self.list.selectedItems()
        ship = (items[0].data(Qt.UserRole) or {}) if items else {}
        dlg = SaveEditDialog(self._loaded_path, self._ships, ship, self)
        self._editing = True
        try:
            accepted = dlg.exec() == QDialog.Accepted
        finally:
            self._editing = False
        self._update_actions()
        if not accepted:
            return
        res = dlg.result or {}
        target = str(res.get("path") or "")
        if res.get("copy") and target:
            self.path.setText(target)
        changed = set(res.get("changed") or [])
        bits = []
        if "currencies" in changed:
            bits.append("货币")
        if {"name", "paint"} & changed:
            bits.append(f"飞船槽位 {res.get('slot', ship.get('slot', '?'))}")
        summary = "存档编辑写入成功" + (f" · {' / '.join(bits)}" if bits else "")
        if res.get("copy"):
            summary += "（副本）"
        self.info.setText(summary)
        notify.success(summary)
        self._watch_ignore_until = time.monotonic() + 2.0
        self._load()

    def _copy_seed(self) -> None:
        items = self.list.selectedItems()
        if items:
            s = items[0].data(Qt.UserRole) or {}
            QGuiApplication.clipboard().setText(s.get("seed") or "")
            self.info.setText("种子已复制")
            notify.success("种子已复制")
