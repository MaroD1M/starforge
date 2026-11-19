"""原生主窗口（Command Deck）：CommandBar + NavRail + Workspace + JobDock。"""
from __future__ import annotations

from PySide6.QtCore import QSettings, QThreadPool, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import paths, strings
from ..services import get_services
from .context import AppContext
from .pages.home import HomePage
from .pages.game_link import GameLinkPage
from .pages.fleet import FleetPage
from .pages.ship_lab import ShipLabPage
from .pages.settings import SettingsPage
from .pages.ship_designer import ShipDesignerPage
from .pages.galaxy import GalaxyPage
from .widgets.command_palette import CommandPalette
from .widgets.feedback import ToastHost
from .widgets.job_dock import JobDock
from .widgets.page_header import PageHeader
from .widgets.ui import focus_first_input
from .widgets.worker import run as run_worker

NAV = [
    ("home", "概览"),
    ("search", "飞船实验室"),
    ("designer", "设计器"),
    ("mine", "我的船队"),
    ("systems", "星图"),
    ("live", "游戏内代理"),
    ("settings", "设置"),
]

# 新页面不改变已有快捷键：设计器排在 Ctrl+7，其余保持原编号。
SHORTCUT_KEYS = [key for key, _label in NAV if key != "designer"] + ["designer"]
SHORTCUT_INDEX = {key: index for index, key in enumerate(SHORTCUT_KEYS, 1)}

CHIP_LABELS = {"data": "数据层", "saves": "存档", "game": "游戏", "write": "写入"}
NAV_GROUPS = [
    ("探索", ("home", "search", "designer")),
    ("资料", ("mine", "systems")),
    ("连接", ("live", "settings")),
]


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self.context = AppContext(self.svc, self)
        self.setWindowTitle(strings.APP_TITLE)
        self.setMinimumSize(1180, 760)
        self._settings = QSettings(str(paths.app_home() / "native-window.ini"), QSettings.IniFormat)
        self._active = "home"
        self._designer_page = None
        self._build_ui()
        self._annotate_dock()
        self.toast_host = ToastHost(self)
        self.toast_host.setAccessibleName("通知浮层")
        self.toast_host.setToolTip("显示操作反馈、状态与错误提示")
        self.context.toastRequested.connect(self.toast)
        self.context.navigateRequested.connect(self.goto)
        self.pages["home"].openRequested.connect(self._open_home_target)
        self._restore_geometry()
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(5000)
        self._health_timer.timeout.connect(self.refresh_health)
        self._health_timer.start()
        self.refresh_health()
        sc = QShortcut(QKeySequence("Ctrl+K"), self)
        sc.activated.connect(self.open_palette)
        for i, key in enumerate(SHORTCUT_KEYS, 1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self).activated.connect(
                lambda k=key: self.goto(k))
        QShortcut(QKeySequence("F5"), self).activated.connect(self.refresh_with_toast)
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self.focus_current_filter)
        QShortcut(QKeySequence("Ctrl+Shift+T"), self).activated.connect(self._toggle_dock)

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_rail())

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        rv.addWidget(self._build_command_bar())

        self.stack = QStackedWidget()
        self.pages = {
            "home": HomePage(),
            "search": ShipLabPage(),
            "designer": ShipDesignerPage(),
            "mine": FleetPage(),
            "systems": GalaxyPage(),
            "live": GameLinkPage(),
            "settings": SettingsPage(),
        }
        self.pages["home"].navigate.connect(self.goto)
        for page in self.pages.values():
            self.stack.addWidget(page)
        rv.addWidget(self.stack, 1)

        self.dock = JobDock()
        rv.addWidget(self.dock)
        root.addWidget(right, 1)

        self._wire_tab_order()
        self.statusBar().setAccessibleName("状态栏")
        self.statusBar().setToolTip("显示当前操作结果与提示")
        self.statusBar().showMessage("就绪")
        self.goto("home", remember=False)

    def _wire_tab_order(self) -> None:
        """导航 → 命令面板 → 当前页内容 → 任务栏，避免 Tab 在侧栏里打转。"""
        chain = [self._buttons[key] for key, _label in NAV]
        chain.append(self.palette_btn)
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)
        if chain:
            QWidget.setTabOrder(chain[-1], self.stack)
        QWidget.setTabOrder(self.stack, self.dock.toggle)
        QWidget.setTabOrder(self.dock.toggle, self.dock.cancel_btn)
        QWidget.setTabOrder(self.dock.cancel_btn, self.dock.clear_btn)
        QWidget.setTabOrder(self.dock.clear_btn, self.dock.list)

    def _annotate_dock(self) -> None:
        self.dock.setAccessibleName("任务栏")
        self.dock.setToolTip("查看进行中与已结束任务（Ctrl+Shift+T 展开/收起）")
        self.dock.toggle.setAccessibleName("展开或收起任务栏")
        self.dock.toggle.setToolTip("展开或收起任务栏（Ctrl+Shift+T）")
        self.dock.cancel_btn.setAccessibleName("取消进行中的任务")
        self.dock.cancel_btn.setToolTip("取消当前选中的进行中任务")
        self.dock.clear_btn.setAccessibleName("清空已完成任务")
        self.dock.clear_btn.setToolTip("只从任务栏隐藏已结束任务，不删除服务端记录")
        self.dock.list.setAccessibleName("任务列表")
        self.dock.list.setToolTip("选择任务查看详情或取消进行中的任务")

    def _build_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("navRail")
        rail.setAccessibleName("主导航")
        rail.setToolTip("切换概览、飞船实验室、设计器、船队、星图、游戏内代理与设置")
        rail.setFixedWidth(190)
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(12, 16, 12, 16)
        brand = QLabel("STARFORGE")
        brand.setObjectName("brand")
        brand.setAccessibleName("应用名称：STARFORGE")
        rv.addWidget(brand)
        sub = QLabel("无人深空 · 飞船猎人")
        sub.setObjectName("muted")
        sub.setAccessibleName("应用副标题：无人深空飞船猎人")
        rv.addWidget(sub)
        rv.addSpacing(16)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        group_of = {key: name for name, keys in NAV_GROUPS for key in keys}
        last_group = None
        for key, label in NAV:
            group = group_of.get(key)
            if group and group != last_group:
                section = QLabel(group)
                section.setObjectName("navSection")
                section.setAccessibleName(f"导航分组：{group}")
                rv.addWidget(section)
                last_group = group
            btn = QPushButton(label)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            shortcut = f"Ctrl+{SHORTCUT_INDEX[key]}"
            hint = f"切换到{label}页面（{shortcut}）"
            btn.setAccessibleName(f"{label}页面")
            btn.setToolTip(hint)
            btn.setStatusTip(hint)
            btn.setFocusPolicy(Qt.StrongFocus)
            btn.clicked.connect(lambda _=False, k=key: self.goto(k))
            self._group.addButton(btn)
            self._buttons[key] = btn
            rv.addWidget(btn)
        rv.addStretch(1)

        ver = QLabel(f"v{__import__('starforge').__version__}")
        ver.setObjectName("muted")
        ver.setAccessibleName(f"版本号：{__import__('starforge').__version__}")
        rv.addWidget(ver)
        self.mode = QLabel("原生窗口 · Qt（PySide6）界面")
        self.mode.setObjectName("muted")
        self.mode.setAccessibleName("运行模式：原生窗口")
        rv.addWidget(self.mode)
        return rail

    def _build_command_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("commandBar")
        bar.setAccessibleName("命令栏")
        bar.setToolTip("当前页面、命令面板入口与运行状态")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 8, 16, 8)
        self.breadcrumb = QLabel("概览")
        self.breadcrumb.setObjectName("breadcrumb")
        self.breadcrumb.setAccessibleName("当前页面：概览")
        self.breadcrumb.setToolTip("当前所在页面")
        h.addWidget(self.breadcrumb)
        h.addSpacing(10)
        self.palette_btn = QPushButton("命令面板（Ctrl+K）")
        self.palette_btn.setObjectName("ghostButton")
        self.palette_btn.setAccessibleName("打开命令面板")
        self.palette_btn.setToolTip("搜索并执行命令（Ctrl+K）")
        self.palette_btn.setStatusTip("搜索并执行命令（Ctrl+K）")
        self.palette_btn.setFocusPolicy(Qt.StrongFocus)
        self.palette_btn.clicked.connect(self.open_palette)
        h.addWidget(self.palette_btn)
        h.addStretch(1)
        self.chips: dict[str, QLabel] = {}
        for key, text in (("data", "数据层"), ("saves", "存档"), ("game", "游戏"), ("write", "写入")):
            chip = QLabel(text)
            chip.setObjectName("chip")
            chip.setAccessibleName(f"{CHIP_LABELS[key]}状态：{text}")
            chip.setToolTip(f"{CHIP_LABELS[key]}状态：{text}")
            self.chips[key] = chip
            h.addWidget(chip)
        self.job_label = QLabel("")
        self.job_label.setObjectName("muted")
        self.job_label.setAccessibleName("当前任务")
        self.job_label.setToolTip("当前后台任务摘要")
        h.addWidget(self.job_label)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("任务进度")
        self.progress.setToolTip("当前后台任务完成进度")
        self.progress.setFixedWidth(140)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        h.addWidget(self.progress)
        return bar

    def _page_for(self, key: str):
        page = self.pages.get(key)
        if page is not None:
            return page
        if key == "designer":
            if self._designer_page is None:
                from .pages.ship_designer import ShipDesignerPage

                self._designer_page = ShipDesignerPage()
                self.stack.addWidget(self._designer_page)
                self.pages["designer"] = self._designer_page
            return self._designer_page
        return None

    def goto(self, key: str, remember: bool = True) -> None:
        page = self._page_for(key)
        if page is None:
            return
        self._active = key
        self.stack.setCurrentWidget(page)
        ensure = getattr(page, "ensure_loaded", None)
        if callable(ensure):
            ensure()
        for k, btn in self._buttons.items():
            btn.setChecked(k == key)
        label = dict(NAV).get(key, key)
        self.breadcrumb.setText(label)
        self.breadcrumb.setAccessibleName(f"当前页面：{label}")
        self.breadcrumb.setToolTip(f"当前页面：{label}")
        page.setAccessibleName(f"{label}页面")
        self._annotate_page_header(page, label)
        if remember:
            self.statusBar().showMessage(label)

    def _annotate_page_header(self, page: QWidget, label: str) -> None:
        for header in page.findChildren(PageHeader):
            header.setAccessibleName(f"{label}页头")
            header.setToolTip(f"{label}：页面标题与说明")
            header.title.setAccessibleName("页面标题")
            header.title.setToolTip(header.title.text())
            header.subtitle.setAccessibleName("页面说明")
            header.subtitle.setToolTip(header.subtitle.text())

    # ---------------------------------------------------------------- 命令面板

    def open_palette(self) -> None:
        actions = [
            ("页面", "概览", lambda: self.goto("home")),
            ("页面", "飞船实验室 / 搜索飞船", lambda: self.goto("search")),
            ("页面", "设计器 / 飞船设计器", lambda: self.goto("designer")),
            ("页面", "我的船队", lambda: self.goto("mine")),
            ("页面", "星图 / 星系与行星", lambda: self.goto("systems")),
            ("页面", "游戏内代理 / 连接游戏", lambda: self.goto("live")),
            ("页面", "设置", lambda: self.goto("settings")),
            ("操作", "收藏夹", self._open_favorites),
            ("操作", "备份 / 恢复", self._open_backups),
            ("操作", "地址工作台", self._open_address_workbench),
            ("操作", "刷新状态", self.refresh_with_toast),
            ("操作", "聚焦当前页过滤框", self.focus_current_filter),
            ("操作", "展开/收起任务栏", self._toggle_dock),
            ("操作", "打开日志目录", self._open_logs),
            ("操作", "复制版本号", self._copy_version),
        ]
        CommandPalette(actions, self).exec()

    def focus_current_filter(self) -> None:
        """Ctrl+L：优先调用当前页自带接口，否则聚焦第一个过滤控件。"""
        page = self.stack.currentWidget()
        if page is None:
            self.toast("当前页面没有可聚焦的过滤框", "info")
            return
        for name in ("focus_filter", "_focus_filter"):
            method = getattr(page, name, None)
            if callable(method):
                try:
                    method()
                    self.statusBar().showMessage("已聚焦当前页过滤框")
                    return
                except Exception:                            # noqa: BLE001 - 页面接口失败时继续回退
                    pass
        target = focus_first_input(page)
        if target is not None:
            self.statusBar().showMessage("已聚焦当前页过滤框")
            return
        self.toast("当前页面没有可聚焦的过滤框；请使用页面内的筛选或搜索控件", "info")

    def _toggle_dock(self) -> None:
        self.dock.toggle_body()
        self.toast("任务栏已收起" if self.dock.list.isHidden() else "任务栏已展开", "info")

    def _open_home_target(self, target: str) -> None:
        if target == "address":
            page = self.pages.get("systems")
            tabs = getattr(page, "tabs", None)
            if tabs is not None:
                for index in range(tabs.count()):
                    if tabs.tabText(index) == "地址工作台":
                        tabs.setCurrentIndex(index)
                        break
            self.toast("已打开地址工作台", "info")
        elif target == "favorites":
            self._open_favorites()

    def _open_favorites(self) -> None:
        self.goto("search")
        page = self.pages.get("search")
        opener = getattr(page, "open_favorites", None)
        if callable(opener):
            opener()

    def _open_backups(self) -> None:
        self.goto("mine")
        page = self.pages.get("mine")
        opener = getattr(page, "open_backups", None)
        if callable(opener):
            opener()

    def _open_address_workbench(self) -> None:
        self.goto("systems")
        self._open_home_target("address")

    def _open_logs(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.app_home() / "logs")))
        self.toast("已打开日志目录", "success")

    def _copy_version(self) -> None:
        QGuiApplication.clipboard().setText(__import__("starforge").__version__)
        self.toast("版本号已复制", "success")

    def toast(self, text: str, kind: str = "info", duration: int | None = None) -> None:
        """统一的轻量反馈：叠加在窗口右下角，同时更新状态栏。"""
        text = str(text or "").strip()
        if not text:
            return
        host = getattr(self, "toast_host", None)
        if host is not None:
            host.toast(text, kind=kind, duration=duration)
        self.statusBar().showMessage(text, 4000)

    # ---------------------------------------------------------------- 状态

    def refresh_with_toast(self) -> None:
        self.refresh_health(notify=True)

    def refresh_health(self, notify: bool = False) -> None:
        def done(res: dict) -> None:
            self.context.publish_health(res)
            self._apply_health(res)
            if notify:
                self.toast("状态已刷新", "success")

        def failed(msg: str) -> None:
            text = f"健康检查失败：{msg}"
            self.statusBar().showMessage(text)
            if notify:
                self.toast(text, "error")

        run_worker(self.svc.health, done, failed)

    def _apply_health(self, h: dict) -> None:
        def set_chip(key: str, text: str, state: str) -> None:
            chip = self.chips[key]
            chip.setText(text)
            chip.setAccessibleName(f"{CHIP_LABELS[key]}状态：{text}")
            chip.setToolTip(f"{CHIP_LABELS[key]}状态：{text}")
            chip.setProperty("state", state)
            chip.style().unpolish(chip)
            chip.style().polish(chip)

        data_ok = bool(h.get("data_ready"))
        set_chip("data", "数据层 ✓" if data_ok else "数据层 ✗", "ok" if data_ok else "bad")
        saves_ok = bool(h.get("saves_ready"))
        set_chip("saves", "存档 ✓" if saves_ok else "存档 ✗", "ok" if saves_ok else "warn")
        game_ok = bool(h.get("game_dir"))
        set_chip("game", "游戏 ✓" if game_ok else "游戏未设置", "ok" if game_ok else "warn")
        write = bool(h.get("write_enabled"))
        set_chip("write", "写入已开" if write else "只读", "warn" if write else "ok")
        self.mode.setText(f"预览级别 {h.get('preview_level', 'L0')} · 原生窗口")

    def set_job(self, label: str, percent: int | None = None) -> None:
        self.job_label.setText(label)
        self.job_label.setAccessibleName(f"当前任务：{label or '空闲'}")
        self.job_label.setToolTip(label or "当前没有后台任务")
        if percent is None:
            self.progress.setVisible(False)
        else:
            self.progress.setVisible(True)
            self.progress.setValue(max(0, min(100, percent)))
        self.context.publish_job({"label": label, "percent": percent})

    # ---------------------------------------------------------------- 窗口

    def _restore_geometry(self) -> None:
        geo = self._settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1440, 900)

    def showEvent(self, e) -> None:                         # noqa: N802 - Qt 回调
        super().showEvent(e)
        self._apply_dark_titlebar()

    def _apply_dark_titlebar(self) -> None:
        if not __import__("sys").platform.startswith("win"):
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            dwm = ctypes.windll.dwmapi
            on = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
            # Windows 11: 标题栏/文字颜色跟随深色主题
            color = ctypes.c_int(0x00160F0B)  # 0x00BBGGRR
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
            text = ctypes.c_int(0x00F5ECE6)
            dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text), ctypes.sizeof(text))
        except Exception:                                  # noqa: BLE001
            pass

    def closeEvent(self, e) -> None:                        # noqa: N802 - Qt 回调
        self._settings.setValue("geometry", self.saveGeometry())
        QThreadPool.globalInstance().waitForDone(4000)
        super().closeEvent(e)
