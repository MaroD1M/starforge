"""原生主窗口：左侧导航 + 页面栈 + 状态芯片。"""
from __future__ import annotations

from PySide6.QtCore import QSettings, QTimer
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
from .pages.live import LivePage
from .pages.mine import MinePage
from .pages.search import SearchPage
from .pages.settings import SettingsPage
from .pages.systems import SystemsPage
from .widgets.worker import run as run_worker

NAV = [
    ("search", "搜船"),
    ("mine", "我的船"),
    ("systems", "星球"),
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
        self._build_ui()
        self._restore_geometry()
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(5000)
        self._health_timer.timeout.connect(self.refresh_health)
        self._health_timer.start()
        self.refresh_health()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        rail = QFrame()
        rail.setObjectName("navRail")
        rail.setFixedWidth(164)
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(10, 14, 10, 14)
        brand = QLabel("STARFORGE")
        brand.setObjectName("brand")
        rv.addWidget(brand)
        sub = QLabel("无人深空 · 飞船猎人")
        sub.setObjectName("muted")
        rv.addWidget(sub)
        rv.addSpacing(12)

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
        root.addWidget(rail)

        right = QWidget()
        rv2 = QVBoxLayout(right)
        rv2.setContentsMargins(0, 0, 0, 0)
        rv2.setSpacing(0)

        top = QFrame()
        top.setStyleSheet("background:#0d1119;border-bottom:1px solid #1e2432;")
        th = QHBoxLayout(top)
        th.setContentsMargins(14, 8, 14, 8)
        self.chips: dict[str, QLabel] = {}
        for key, text in (("data", "数据层"), ("saves", "存档"), ("game", "游戏"), ("write", "写入")):
            chip = QLabel(text)
            chip.setObjectName("chip")
            self.chips[key] = chip
            th.addWidget(chip)
        th.addStretch(1)
        self.job_label = QLabel("")
        self.job_label.setObjectName("muted")
        th.addWidget(self.job_label)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(160)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        th.addWidget(self.progress)
        rv2.addWidget(top)

        self.stack = QStackedWidget()
        self.pages = {
            "search": SearchPage(),
            "mine": MinePage(),
            "systems": SystemsPage(),
            "live": LivePage(),
            "settings": SettingsPage(),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        rv2.addWidget(self.stack, 1)
        root.addWidget(right, 1)

        self.statusBar().showMessage("就绪")
        self.goto("search", remember=False)

    def goto(self, key: str, remember: bool = True) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        for k, btn in self._buttons.items():
            btn.setChecked(k == key)
        if remember:
            self.statusBar().showMessage(f"{dict(NAV).get(key, key)}")

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

    def closeEvent(self, e) -> None:
        self._settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(e)
