"""原生主窗口（Command Deck）：CommandBar + NavRail + Workspace + JobDock。"""
from __future__ import annotations

from PySide6.QtCore import QSettings, QThreadPool, QTimer, QUrl
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
from .pages.home import HomePage
from .pages.live import LivePage
from .pages.mine import MinePage
from .pages.search import SearchPage
from .pages.settings import SettingsPage
from .pages.systems import SystemsPage
from .widgets.command_palette import CommandPalette
from .widgets.job_dock import JobDock
from .widgets.worker import run as run_worker

NAV = [
    ("home", "概览"),
    ("search", "飞船实验室"),
    ("mine", "我的船队"),
    ("systems", "星图"),
    ("live", "游戏内"),
    ("settings", "设置"),
]


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self.setWindowTitle(strings.APP_TITLE)
        self.setMinimumSize(1180, 760)
        self._settings = QSettings(str(paths.app_home() / "native-window.ini"), QSettings.IniFormat)
        self._active = "home"
        self._build_ui()
        self._restore_geometry()
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(5000)
        self._health_timer.timeout.connect(self.refresh_health)
        self._health_timer.start()
        self.refresh_health()
        sc = QShortcut(QKeySequence("Ctrl+K"), self)
        sc.activated.connect(self.open_palette)

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
            "search": SearchPage(),
            "mine": MinePage(),
            "systems": SystemsPage(),
            "live": LivePage(),
            "settings": SettingsPage(),
        }
        self.pages["home"].navigate.connect(self.goto)
        for page in self.pages.values():
            self.stack.addWidget(page)
        rv.addWidget(self.stack, 1)

        self.dock = JobDock()
        rv.addWidget(self.dock)
        root.addWidget(right, 1)

        self.statusBar().showMessage("就绪")
        self.goto("home", remember=False)

    def _build_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("navRail")
        rail.setFixedWidth(190)
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(12, 16, 12, 16)
        brand = QLabel("STARFORGE")
        brand.setObjectName("brand")
        rv.addWidget(brand)
        sub = QLabel("无人深空 · 飞船猎人")
        sub.setObjectName("muted")
        rv.addWidget(sub)
        rv.addSpacing(16)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for key, label in NAV:
            btn = QPushButton(label)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self.goto(k))
            self._group.addButton(btn)
            self._buttons[key] = btn
            rv.addWidget(btn)
        rv.addStretch(1)

        ver = QLabel(f"v{__import__('starforge').__version__}")
        ver.setObjectName("muted")
        rv.addWidget(ver)
        self.mode = QLabel("原生窗口 · PySide6")
        self.mode.setObjectName("muted")
        rv.addWidget(self.mode)
        return rail

    def _build_command_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("commandBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 8, 16, 8)
        self.breadcrumb = QLabel("概览")
        self.breadcrumb.setObjectName("breadcrumb")
        h.addWidget(self.breadcrumb)
        h.addSpacing(10)
        palette = QPushButton("命令  Ctrl+K")
        palette.setObjectName("ghostButton")
        palette.clicked.connect(self.open_palette)
        h.addWidget(palette)
        h.addStretch(1)
        self.chips: dict[str, QLabel] = {}
        for key, text in (("data", "数据层"), ("saves", "存档"), ("game", "游戏"), ("write", "写入")):
            chip = QLabel(text)
            chip.setObjectName("chip")
            self.chips[key] = chip
            h.addWidget(chip)
        self.job_label = QLabel("")
        self.job_label.setObjectName("muted")
        h.addWidget(self.job_label)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(140)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        h.addWidget(self.progress)
        return bar

    def goto(self, key: str, remember: bool = True) -> None:
        page = self.pages.get(key)
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
        if remember:
            self.statusBar().showMessage(label)

    # ---------------------------------------------------------------- 命令面板

    def open_palette(self) -> None:
        actions = [
            ("概览 / Home", lambda: self.goto("home")),
            ("飞船实验室 / 搜船", lambda: self.goto("search")),
            ("我的船队", lambda: self.goto("mine")),
            ("星图 / 星球", lambda: self.goto("systems")),
            ("游戏内 / 连接", lambda: self.goto("live")),
            ("设置", lambda: self.goto("settings")),
            ("刷新状态", self.refresh_health),
            ("展开/收起任务 Dock", self.dock.toggle_body),
            ("打开日志目录", lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(paths.app_home() / "logs")))),
            ("复制版本号", lambda: QGuiApplication.clipboard().setText(
                __import__("starforge").__version__)),
        ]
        CommandPalette(actions, self).exec()

    # ---------------------------------------------------------------- 状态

    def refresh_health(self) -> None:
        def done(res: dict) -> None:
            self._apply_health(res)

        run_worker(self.svc.health, done, lambda msg: self.statusBar().showMessage(f"健康检查失败：{msg}"))

    def _apply_health(self, h: dict) -> None:
        def set_chip(key: str, text: str, state: str) -> None:
            chip = self.chips[key]
            chip.setText(text)
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
        self.mode.setText(f"{h.get('preview_level', 'L0')} · 原生窗口")

    def set_job(self, label: str, percent: int | None = None) -> None:
        self.job_label.setText(label)
        if percent is None:
            self.progress.setVisible(False)
        else:
            self.progress.setVisible(True)
            self.progress.setValue(max(0, min(100, percent)))

    # ---------------------------------------------------------------- 窗口

    def _restore_geometry(self) -> None:
        geo = self._settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1440, 900)

    def closeEvent(self, e) -> None:                        # noqa: N802 - Qt 回调
        self._settings.setValue("geometry", self.saveGeometry())
        QThreadPool.globalInstance().waitForDone(4000)
        super().closeEvent(e)
