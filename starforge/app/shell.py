"""原生主窗口（Command Deck）：4 个工作区 + 状态条 + 命令面板 + 任务栏。

信息架构（本轮重构的核心）：

* **情报台**：搜船 / 已发现 / 星图 / 符文 —— 先找到值得去的地方；
* **我的**：船队 / 设计器 / 存档 —— 管好自己的船与存档；
* **联动**：连接 / 送种子 / 模板 Mod / 实时资产 / 传送 —— 把结果送进游戏；
* **设置**：路径 / 安全 / 运行时 / 诊断 —— 出问题时知道去哪里修。

旧 7 个平级页面仍保留为隐藏兼容入口（Ctrl+1…Ctrl+7、命令面板「页面」组），
但默认导航只显示 4 个工作区，避免同级控件过多。
"""
from __future__ import annotations

import os
from itertools import pairwise

from PySide6.QtCore import QSettings, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import paths, strings
from ..services import get_services
from .context import AppContext
from .pages.fleet import FleetPage
from .pages.galaxy import GalaxyPage
from .pages.game_link import GameLinkPage
from .pages.home import HomePage
from .pages.settings import SettingsPage
from .pages.ship_designer import ShipDesignerPage
from .pages.ship_lab import ShipLabPage
from .theme import (
    COMMAND_BAR_MARGIN,
    CONTEXT_BAR_HEIGHT,
    CONTEXT_BAR_MARGIN,
    RAIL_WIDTH,
    SPACE_L,
    SPACE_M,
    SPACE_S,
    SPACE_XS,
)
from .widgets.command_palette import CommandPalette
from .widgets.feedback import ToastHost
from .widgets.job_dock import JobDock
from .widgets.page import reveal_widget
from .widgets.page_header import PageHeader
from .widgets.rf_navigation import RfWorkspaceNav
from .widgets.rf_onboarding import RfOnboardingWizard
from .widgets.rf_status_strip import RfStatusStrip
from .widgets.ui import Card, ElidedLabel, focus_first_input
from .widgets.worker import run as run_worker

# 兼容旧导航：键、标题与 Ctrl+数字快捷键保持原样，但默认隐藏。
NAV = [
    ("home", "概览"),
    ("search", "飞船实验室"),
    ("designer", "设计器"),
    ("mine", "我的船队"),
    ("systems", "星图"),
    ("live", "游戏内代理"),
    ("settings", "设置"),
]

SHORTCUT_KEYS = [key for key, _label in NAV if key != "designer"] + ["designer"]
SHORTCUT_INDEX = {key: index for index, key in enumerate(SHORTCUT_KEYS, 1)}

CHIP_LABELS = {"data": "数据层", "saves": "存档", "game": "游戏", "write": "写入"}
NAV_GROUPS = [
    ("探索", ("home", "search", "designer")),
    ("资料", ("mine", "systems")),
    ("连接", ("live", "settings")),
]

# ---------------------------------------------------------------- 工作区模型
# 每个 view 直接映射到现有页面实例；tab/anchor/focus 只是“把页面带到对应位置”，
# 不重写页面内容，也不改变页面构造签名。
WORKSPACES = [
    {
        "key": "intel",
        "title": "情报台",
        "claim": "先找到值得去的地方：搜船、已发现、星图与符文都在这里。",
        "views": [
            {
                "key": "search", "title": "搜船", "page": "search",
                "hint": "按型号、部件与颜色组合搜索飞船；选中后可送进游戏。",
            },
            {
                "key": "discovered", "title": "已发现", "page": "systems",
                "tab": "已发现",
                "hint": "查看已经发现并记录的行星与星系。",
            },
            {
                "key": "map", "title": "星图", "page": "systems", "tab": "行星",
                "default": True,
                "hint": "查看当前星系的行星与船池，或扫描附近星系找乐土。",
            },
            {
                "key": "glyphs", "title": "符文", "page": "systems",
                "tab": "地址工作台", "focus": "addr_lookup",
                "hint": "用符文地址或种子反查星系，并填入传送。",
            },
        ],
    },
    {
        "key": "mine",
        "title": "我的",
        "claim": "船队、设计与存档，都归到“我的”名下。",
        "views": [
            {
                "key": "fleet", "title": "船队", "page": "mine", "default": True,
                "hint": "查看存档里的飞船、同伴、护卫舰与货船。",
            },
            {
                "key": "designer", "title": "设计器", "page": "designer",
                "hint": "用部件与种子设计新船，并可写回存档。",
            },
            {
                "key": "archive", "title": "存档", "page": "mine",
                "anchor": "存档", "focus": "path",
                "hint": "选择 save.hg、读取、备份或恢复当前存档。",
            },
        ],
    },
    {
        "key": "link",
        "title": "联动",
        "claim": "把搜到的种子、模板与实时数据送进游戏。",
        "views": [
            {
                "key": "connect", "title": "连接", "page": "live", "default": True,
                "anchor": "连接状态", "focus": "connect_btn",
                "hint": "连接已运行的游戏，读取实时遥测与行星档案。",
            },
            {
                "key": "seed", "title": "送种子", "page": "search",
                "hint": "在搜索结果选中飞船，点右下角「送进游戏」写入模板槽。",
                "toast": "选中一艘飞船后，点右下角「送进游戏」；只写模板种子，不动存档。",
            },
            {
                "key": "mod", "title": "模板 Mod", "page": "live",
                "anchor": "表情模板 Mod", "focus": "install_mod_btn",
                "hint": "安装后游戏表情菜单会出现 8 个可领取模板；装完重启游戏。",
                "toast": "点「安装 / 更新模板 Mod」，装完重启游戏；只写游戏 MODS 目录。",
            },
            {
                "key": "assets", "title": "实时资产", "page": "live",
                "anchor": "实时资产",
                "hint": "只读查看多功能工具、货船与同伴；不会写回游戏。",
            },
            {
                "key": "warp", "title": "传送", "page": "live",
                "anchor": "安全区", "focus": "glyphs",
                "hint": "按符文地址传送；传送会写玩家位置，先备份存档。",
                "toast": "传送会写玩家位置；高风险操作，请先备份存档。",
            },
        ],
    },
    {
        "key": "settings",
        "title": "设置",
        "claim": "路径、安全、运行时与诊断：出问题时知道去哪里修。",
        "views": [
            {
                "key": "paths", "title": "路径", "page": "settings", "default": True,
                "anchor": "路径", "focus": "game",
                "hint": "确认游戏目录与存档目录；自动检测优先。",
            },
            {
                "key": "safety", "title": "安全", "page": "settings",
                "anchor": "安全与性能", "focus": "write",
                "hint": "写入默认关闭；可设置二次确认、备份保留数与线程数。",
            },
            {
                "key": "runtime", "title": "运行时", "page": "settings",
                "anchor": "版本与代理",
                "hint": "查看 build 指纹、游戏内代理状态与只读日志。",
            },
            {
                "key": "diag", "title": "诊断", "page": "settings",
                "anchor": "诊断", "focus": "selfcheck_btn",
                "hint": "运行体检/自检并导出诊断包；不执行写入步骤。",
            },
        ],
    },
]

WORKSPACE_BY_KEY = {ws["key"]: ws for ws in WORKSPACES}
VIEW_BY_KEY: dict[str, dict] = {}
VIEW_TO_WORKSPACE: dict[str, str] = {}
PAGE_DEFAULT_VIEW: dict[str, str] = {}
for _workspace in WORKSPACES:
    for _view in _workspace["views"]:
        _view = dict(_view)
        _view["workspace"] = _workspace["key"]
        VIEW_BY_KEY[_view["key"]] = _view
        VIEW_TO_WORKSPACE[_view["key"]] = _workspace["key"]
        if _view.get("default") and _view["page"] not in PAGE_DEFAULT_VIEW:
            PAGE_DEFAULT_VIEW[_view["page"]] = _view["key"]


class _PageStack(QStackedWidget):
    """最小尺寸只跟随当前页。

    QStackedWidget 默认取所有页的最大 sizeHint，一个很高的页面（例如星图）
    会让其它页也被撑出多余的滚动条。这里改为按当前页计算，切页时刷新几何。
    """

    def sizeHint(self):                                     # noqa: N802 - Qt API
        page = self.currentWidget()
        if page is not None:
            return page.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self):                              # noqa: N802 - Qt API
        page = self.currentWidget()
        if page is not None:
            return page.minimumSizeHint()
        return super().minimumSizeHint()

    def currentChanged(self, index: int) -> None:           # noqa: N802 - Qt 回调
        super().currentChanged(index)
        self.updateGeometry()


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        self.context = AppContext(self.svc, self)
        self.setWindowTitle(strings.APP_TITLE)
        self.setMinimumSize(1180, 760)
        self._settings = QSettings(str(paths.app_home() / "native-window.ini"), QSettings.IniFormat)
        self._active = "search"
        self._active_view = "search"
        self._workspace = "intel"
        self._last_view: dict[str, str] = {}
        self._health: dict = {}
        self._designer_page = None
        self._onboarding = None
        self.onboarding = None
        self._onboarding_scheduled = False
        self._next_action = None
        self._build_ui()
        self._annotate_dock()
        self._annotate_all_pages()
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
        QShortcut(QKeySequence("F1"), self).activated.connect(self.open_onboarding)
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
        rv.addWidget(self._build_context_bar())

        self.stack = _PageStack()
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

        # 工作区放进滚动区：窗口压到最小尺寸时，页面保持自身最小高度，
        # 由工作区滚动，而不是把卡片和文字压扁/裁切。
        self.workspace = QScrollArea()
        self.workspace.setObjectName("workspaceScroll")
        self.workspace.setWidgetResizable(True)
        self.workspace.setFrameShape(QFrame.NoFrame)
        self.workspace.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.workspace.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.workspace.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.workspace.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.workspace.viewport().setAutoFillBackground(False)
        self.workspace.setWidget(self.stack)
        rv.addWidget(self.workspace, 1)

        self.dock = JobDock()
        rv.addWidget(self.dock)
        root.addWidget(right, 1)

        self._wire_tab_order()
        self.statusBar().setAccessibleName("状态栏")
        self.statusBar().setToolTip("显示当前操作结果与提示")
        self.statusBar().showMessage("就绪")
        self.activate_view("search", announce=False, remember=False)

    def _wire_tab_order(self) -> None:
        """工作区导航 → 顶部命令/状态 → 当前页内容 → 任务栏。

        只连接当前可见的导航项：切换工作区后重新调用一次，避免隐藏按钮
        把显式 Tab 链断在半路。
        """
        chain = [w for w in self.nav.focus_chain() if w.isVisible()]
        # 按视觉顺序：顶部状态 chip → 上手 → 命令面板 → 下一步 → 页面内容。
        chain += [*self.chips.values(), self.guide_btn, self.palette_btn, self.next_btn]
        for first, second in pairwise(chain):
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

    def _annotate_all_pages(self) -> None:
        """启动时就把每个旧页面的页头标好，避免只在跳转后才可读。"""
        for key, label in NAV:
            page = self.pages.get(key)
            if page is not None:
                page.setAccessibleName(f"{label}页面")
                self._annotate_page_header(page, label)

    def _build_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("navRail")
        rail.setAccessibleName("主导航")
        rail.setToolTip("四个工作区：情报台、我的、联动、设置（F1 打开上手向导）")
        rail.setFixedWidth(RAIL_WIDTH)
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(SPACE_M, SPACE_L, SPACE_M, SPACE_L)
        rv.setSpacing(SPACE_XS)
        brand = QLabel("STARFORGE")
        brand.setObjectName("brand")
        brand.setAccessibleName("应用名称：STARFORGE")
        rv.addWidget(brand)
        sub = QLabel("无人深空 · 情报台")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        sub.setMinimumWidth(0)
        sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sub.setAccessibleName("应用副标题：无人深空情报台")
        rv.addWidget(sub)
        rv.addSpacing(SPACE_M)

        self.nav = RfWorkspaceNav(WORKSPACES)
        self.workspace_nav = self.nav
        self.nav.workspaceSelected.connect(self.activate_workspace)
        self.nav.viewSelected.connect(self.activate_view)
        rv.addWidget(self.nav)

        # 旧导航保留为隐藏兼容入口：Ctrl+1…Ctrl+7 与测试里的 _buttons 仍可用。
        self._legacy = QWidget(rail)
        self._legacy.setObjectName("legacyNav")
        self._legacy.setAccessibleName("旧版页面导航（兼容）")
        self._legacy.hide()
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for key, label in NAV:
            btn = QPushButton(label, self._legacy)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            shortcut = f"Ctrl+{SHORTCUT_INDEX[key]}"
            hint = f"切换到{label}页面（{shortcut}）"
            btn.setAccessibleName(f"{label}页面")
            btn.setToolTip(hint)
            btn.setStatusTip(hint)
            btn.setFocusPolicy(Qt.StrongFocus)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda _=False, k=key: self.goto(k))
            self._group.addButton(btn)
            self._buttons[key] = btn

        rv.addStretch(1)
        ver = QLabel(f"v{__import__('starforge').__version__}")
        ver.setObjectName("muted")
        ver.setAccessibleName(f"版本号：{__import__('starforge').__version__}")
        rv.addWidget(ver)
        self.mode = QLabel("原生窗口 · Qt（PySide6）界面")
        self.mode.setObjectName("muted")
        self.mode.setWordWrap(True)
        self.mode.setMinimumWidth(0)
        self.mode.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.mode.setAccessibleName("运行模式：原生窗口")
        rv.addWidget(self.mode)
        return rail

    def _build_command_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("commandBar")
        bar.setAccessibleName("命令栏")
        bar.setToolTip("当前工作区、运行状态、命令面板与上手向导")
        h = QHBoxLayout(bar)
        h.setContentsMargins(*COMMAND_BAR_MARGIN)
        h.setSpacing(SPACE_S)
        self.breadcrumb = QLabel("情报台 · 搜船")
        self.breadcrumb.setObjectName("breadcrumb")
        self.breadcrumb.setAccessibleName("当前页面：情报台 · 搜船")
        self.breadcrumb.setToolTip("当前所在工作区与入口")
        self.breadcrumb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        h.addWidget(self.breadcrumb)
        h.addStretch(1)

        self.status_strip = RfStatusStrip()
        self.status_strip.chipClicked.connect(self._open_setting_chip)
        self.chips = self.status_strip.chips
        h.addWidget(self.status_strip)

        # 任务摘要可能很长：用省略号，不要把右侧按钮挤出去。
        self.job_label = ElidedLabel("")
        self.job_label.setObjectName("muted")
        self.job_label.setAccessibleName("当前任务")
        self.job_label.setToolTip("当前后台任务摘要")
        self.job_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.job_label.setMaximumWidth(170)
        h.addWidget(self.job_label)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("任务进度")
        self.progress.setToolTip("当前后台任务完成进度")
        self.progress.setFixedWidth(110)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        h.addWidget(self.progress)

        self.guide_btn = QPushButton("上手")
        self.guide_btn.setObjectName("ghostButton")
        self.guide_btn.setAccessibleName("重新打开上手向导")
        self.guide_btn.setToolTip("三步上手：找游戏 → 找存档 → 可选装模板 Mod（F1）")
        self.guide_btn.setFocusPolicy(Qt.StrongFocus)
        self.guide_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.guide_btn.clicked.connect(self.open_onboarding)
        h.addWidget(self.guide_btn)

        self.palette_btn = QPushButton("命令面板")
        self.palette_btn.setObjectName("ghostButton")
        self.palette_btn.setAccessibleName("打开命令面板")
        self.palette_btn.setToolTip("搜索并执行命令（Ctrl+K）")
        self.palette_btn.setStatusTip("搜索并执行命令（Ctrl+K）")
        self.palette_btn.setFocusPolicy(Qt.StrongFocus)
        self.palette_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.palette_btn.clicked.connect(self.open_palette)
        h.addWidget(self.palette_btn)
        return bar

    def _build_context_bar(self) -> QFrame:
        """一条 40px 的“主张 + 下一步”带：每个工作区只强调一件事。"""
        bar = QFrame()
        bar.setObjectName("contextBar")
        bar.setAccessibleName("工作区提示")
        bar.setToolTip("当前工作区的主张与建议的下一步")
        bar.setFixedHeight(CONTEXT_BAR_HEIGHT)
        h = QHBoxLayout(bar)
        h.setContentsMargins(*CONTEXT_BAR_MARGIN)
        h.setSpacing(SPACE_S)
        self.claim_label = ElidedLabel("")
        self.claim_label.setObjectName("workspaceClaim")
        self.claim_label.setAccessibleName("工作区主张")
        self.claim_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.claim_label.setMinimumWidth(0)
        h.addWidget(self.claim_label, 1)
        self.next_text = QLabel("下一步")
        self.next_text.setObjectName("nextStepLabel")
        self.next_text.setAccessibleName("建议的下一步")
        self.next_text.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        h.addWidget(self.next_text)
        self.next_btn = QPushButton("去")
        self.next_btn.setObjectName("nextStepButton")
        self.next_btn.setAccessibleName("执行建议的下一步")
        self.next_btn.setFocusPolicy(Qt.StrongFocus)
        self.next_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.next_btn.clicked.connect(self._run_next_step)
        h.addWidget(self.next_btn)
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

    # ---------------------------------------------------------------- 导航

    @property
    def active_workspace(self) -> str:
        return self._workspace

    @property
    def active_view(self) -> str:
        return self._active_view

    def activate_workspace(self, key: str, remember: bool = True) -> None:
        workspace = WORKSPACE_BY_KEY.get(str(key))
        if workspace is None:
            return
        views = workspace.get("views") or []
        if not views:
            return
        view_key = self._last_view.get(workspace["key"])
        if not view_key or view_key not in VIEW_BY_KEY:
            view_key = str(views[0].get("key") or "")
        self.activate_view(view_key, announce=False, remember=remember)

    def activate_view(self, view_key: str, announce: bool = True,
                      remember: bool = True) -> None:
        view = VIEW_BY_KEY.get(str(view_key))
        if view is None:
            return
        page = self._page_for(str(view.get("page") or ""))
        if page is None:
            return
        workspace = WORKSPACE_BY_KEY[VIEW_TO_WORKSPACE[str(view_key)]]
        self._workspace = workspace["key"]
        self._active_view = str(view_key)
        self._active = str(view.get("page") or "")
        if remember:
            self._last_view[workspace["key"]] = str(view_key)
        self.nav.set_workspace(workspace["key"])
        self.nav.set_view(str(view_key))
        self.stack.setCurrentWidget(page)
        ensure = getattr(page, "ensure_loaded", None)
        if callable(ensure):
            ensure()
        self._apply_page_view(page, view)
        self._apply_claim(workspace, view)
        self.breadcrumb.setText(f"{workspace['title']} · {view['title']}")
        self.breadcrumb.setAccessibleName(
            f"当前页面：{workspace['title']} · {view['title']}")
        self.breadcrumb.setToolTip(f"当前页面：{workspace['title']} · {view['title']}")
        self._annotate_page_header(page, str(view.get("title") or ""))
        self._update_next_step()
        # 子导航随工作区显隐变化，Tab 链需要按新的可见项重建。
        self._wire_tab_order()
        if announce:
            hint = str(view.get("hint") or "")
            if hint:
                self.statusBar().showMessage(hint, 6000)
            toast = str(view.get("toast") or "")
            if toast:
                kind = "warn" if view_key == "warp" else "info"
                self.toast(toast, kind)

    def goto(self, key: str, remember: bool = True) -> None:
        """兼容旧页面键：随机映射到 IA 里的默认入口。"""
        key = str(key or "")
        view_key = PAGE_DEFAULT_VIEW.get(key)
        if view_key:
            self.activate_view(view_key, announce=False, remember=remember)
            return
        self._show_legacy_page(key, remember=remember)

    def _show_legacy_page(self, key: str, remember: bool = True) -> None:
        page = self._page_for(key)
        if page is None:
            return
        label = dict(NAV).get(key, key or "页面")
        self._active = key
        self._active_view = ""
        self.stack.setCurrentWidget(page)
        ensure = getattr(page, "ensure_loaded", None)
        if callable(ensure):
            ensure()
        self.nav.clear_view_selection()
        breadcrumb = f"{label}（旧版）"
        self.breadcrumb.setText(breadcrumb)
        self.breadcrumb.setAccessibleName(f"当前页面：{breadcrumb}")
        self.breadcrumb.setToolTip("旧版页面兼容入口；日常操作请使用四个工作区")
        self.claim_label.setText("旧版概览仅作兼容保留；日常请从左侧四个工作区进入。")
        self.claim_label.setToolTip(self.claim_label.text())
        self._annotate_page_header(page, label)
        self._update_next_step()
        if remember:
            self.statusBar().showMessage(f"已打开旧版{label}页面", 5000)

    def _apply_claim(self, workspace: dict, view: dict) -> None:
        claim = str(workspace.get("claim") or "")
        hint = str(view.get("hint") or "")
        text = claim
        if hint:
            text = f"{claim}  {hint}"
        self.claim_label.setText(text)
        self.claim_label.setToolTip(text)
        self.claim_label.setAccessibleName(f"{workspace['title']}主张：{claim}")

    # ---------------------------------------------------------------- 页面定位

    def _apply_page_view(self, page: QWidget, view: dict) -> None:
        tab = str(view.get("tab") or "")
        if tab:
            self._select_page_tab(page, tab)
        anchor = str(view.get("anchor") or "")
        focus_name = str(view.get("focus") or "")
        # 页面刚显示时尺寸还是 0；延后一帧再滚动/高亮/聚焦。
        QTimer.singleShot(0, lambda p=page, v=dict(view): self._reveal_page_target(p, v))
        if anchor or focus_name:
            self._reveal_page_target(page, view)

    def _reveal_page_target(self, page: QWidget, view: dict) -> None:
        try:
            anchor = str(view.get("anchor") or "")
            if anchor:
                card = self._find_card(page, anchor)
                if card is not None:
                    reveal_widget(card)
                    card.set_spotlight(True)
                    QTimer.singleShot(
                        1800, lambda c=card: self._clear_spotlight(c))
            focus_name = str(view.get("focus") or "")
            if focus_name:
                target = getattr(page, focus_name, None)
                if isinstance(target, QWidget) and target.isEnabled():
                    target.setFocus(Qt.OtherFocusReason)
                    if isinstance(target, QLineEdit):
                        target.selectAll()
        except RuntimeError:
            pass

    @staticmethod
    def _select_page_tab(page: QWidget, text: str) -> bool:
        tabs = getattr(page, "tabs", None)
        if tabs is None:
            return False
        try:
            for index in range(tabs.count()):
                if tabs.tabText(index) == text:
                    tabs.setCurrentIndex(index)
                    return True
        except RuntimeError:
            return False
        return False

    @staticmethod
    def _find_card(page: QWidget, title: str) -> Card | None:
        try:
            for card in page.findChildren(Card):
                label = getattr(card, "title_label", None)
                if label is not None and str(label.text()).startswith(title):
                    return card
        except RuntimeError:
            return None
        return None

    @staticmethod
    def _clear_spotlight(card: Card) -> None:
        try:
            card.set_spotlight(False)
        except RuntimeError:
            pass

    def _annotate_page_header(self, page: QWidget, label: str) -> None:
        for header in page.findChildren(PageHeader):
            header.setAccessibleName(f"{label}页头")
            header.setToolTip(f"{label}：页面标题与说明")
            header.title.setAccessibleName("页面标题")
            header.title.setToolTip(header.title.text())
            header.subtitle.setAccessibleName("页面说明")
            header.subtitle.setToolTip(header.subtitle.text())

    # ---------------------------------------------------------------- 下一步引导

    def _update_next_step(self) -> None:
        text, action_label, action = self._compute_next_step()
        self.next_text.setText(f"下一步：{text}")
        self.next_btn.setText(action_label)
        self.next_btn.setAccessibleName(f"下一步：{text}（{action_label}）")
        self.next_btn.setToolTip(text)
        self._next_action = action

    def _compute_next_step(self):
        h = self._health or {}
        if not h.get("game_dir"):
            return ("先找到游戏目录", "去设置", lambda: self._open_setting_chip("game"))
        if not h.get("saves_ready"):
            return ("找到存档目录", "去设置", lambda: self._open_setting_chip("saves"))
        view = self._active_view
        if view in ("search", "seed"):
            return ("搜一艘飞船", "去搜船", self._intent_search)
        if view == "map":
            return ("扫描附近星系，找一颗乐土", "去扫描", self._intent_scan)
        if view in ("discovered", "glyphs"):
            return ("用符文地址去看过的星系", "去搜船", self._intent_search)
        if view in ("fleet", "archive"):
            return ("读取我的存档", "去读取", self._intent_load_fleet)
        if view == "designer":
            return ("从搜索结果挑一艘船改成设计", "去搜船", self._intent_search)
        if view == "connect":
            return ("连接游戏，读取实时遥测", "去连接", self._intent_connect)
        if view in ("mod", "assets", "warp"):
            return ("连接游戏后再使用联动功能", "去连接", self._intent_connect)
        if view in ("paths", "safety", "runtime"):
            return ("跑一次诊断，确认环境正常", "去诊断", self._intent_diag)
        if view == "diag":
            return ("运行自检（只读）", "去自检", self._intent_selfcheck)
        return ("搜一艘飞船", "去搜船", self._intent_search)

    def _run_next_step(self) -> None:
        action = self._next_action
        if callable(action):
            action()

    def _intent_search(self) -> None:
        self.activate_view("search", announce=False)
        self.focus_current_filter()

    def _intent_scan(self) -> None:
        self.activate_view("map", announce=False)
        page = self.pages.get("systems")
        button = getattr(page, "scan_btn", None)
        if button is not None:
            button.setFocus(Qt.OtherFocusReason)
        self.toast("先调好群系/最少行星，再点右上角「扫描」；找乐土可把群系设为「茂盛」。", "info")

    def _intent_load_fleet(self) -> None:
        self.activate_view("fleet", announce=False)
        page = self.pages.get("mine")
        button = getattr(page, "load_btn", None)
        if button is not None:
            button.setFocus(Qt.OtherFocusReason)
        self.toast("确认存档路径后点「读取存档」；没有路径可先在「存档」入口选择 save.hg。", "info")

    def _intent_connect(self) -> None:
        self.activate_view("connect", announce=False)
        page = self.pages.get("live")
        button = getattr(page, "connect_btn", None)
        if button is not None:
            button.setFocus(Qt.OtherFocusReason)
        self.toast("先进入游戏并载入存档，再点「连接游戏」。", "info")

    def _intent_diag(self) -> None:
        self.activate_view("diag", announce=False)
        self.toast("诊断页可运行体检、自检并导出诊断包；默认只读。", "info")

    def _intent_selfcheck(self) -> None:
        self.activate_view("diag", announce=False)
        page = self.pages.get("settings")
        button = getattr(page, "selfcheck_btn", None)
        if button is not None:
            button.setFocus(Qt.OtherFocusReason)
        self.toast("点「运行自检（只读）」；不会执行写入步骤。", "info")

    def _intent_lush(self) -> None:
        self.activate_view("map", announce=False)
        page = self.pages.get("systems")
        combo = getattr(page, "biome", None)
        if combo is not None:
            index = combo.findData("Lush")
            if index >= 0:
                combo.setCurrentIndex(index)
        self.toast("群系已筛为「茂盛」；点右上角「扫描」开始找乐土。", "info")

    def _intent_seed(self) -> None:
        self.activate_view("seed", announce=False)
        self.toast("在搜索结果选中飞船，然后点右下角「送进游戏」。", "info")

    def _intent_mod(self) -> None:
        self.activate_view("mod", announce=False)
        self.toast("点「安装 / 更新模板 Mod」，装完重启游戏。", "info")

    def _intent_warp(self) -> None:
        self.activate_view("warp", announce=False)
        self.toast("传送会写玩家位置；请先备份存档。", "warn")

    # ---------------------------------------------------------------- 状态 chip

    def _open_setting_chip(self, key: str) -> None:
        targets = {
            "data": ("paths", "game", "已定位到设置中的游戏目录"),
            "saves": ("paths", "saves", "已定位到设置中的存档目录"),
            "game": ("paths", "game", "已定位到设置中的游戏目录"),
            "write": ("safety", "write", "已定位到设置中的写入开关"),
        }
        view, attr, message = targets.get(str(key), ("paths", "game", "已打开设置路径"))
        self.activate_view(view, announce=False)
        QTimer.singleShot(50, lambda: self._focus_setting(attr, message))

    def _focus_setting(self, attr: str, message: str) -> None:
        page = self.pages.get("settings")
        target = getattr(page, attr, None)
        if isinstance(target, QWidget) and target.isEnabled():
            target.setFocus(Qt.OtherFocusReason)
            if isinstance(target, QLineEdit):
                target.selectAll()
        self.statusBar().showMessage(message, 5000)
        self.toast(message, "info")

    # ---------------------------------------------------------------- 命令面板

    def open_palette(self) -> None:
        actions = [
            ("我要…", "搜一艘飞船", self._intent_search),
            ("我要…", "找一颗乐土星球（群系=茂盛）", self._intent_lush),
            ("我要…", "把飞船送进游戏", self._intent_seed),
            ("我要…", "安装模板 Mod", self._intent_mod),
            ("我要…", "传送（按符文地址）", self._intent_warp),
            ("我要…", "看诊断", self._intent_diag),
            ("我要…", "重新打开上手向导", self.open_onboarding),
            ("工作区", "情报台 / 搜船", lambda: self.activate_view("search")),
            ("工作区", "我的 / 船队", lambda: self.activate_view("fleet")),
            ("工作区", "联动 / 连接游戏", lambda: self.activate_view("connect")),
            ("工作区", "设置 / 路径", lambda: self.activate_view("paths")),
            ("页面", "概览（旧版）", lambda: self.goto("home")),
            ("页面", "飞船实验室（直达）", lambda: self.goto("search")),
            ("页面", "设计器（直达）", lambda: self.goto("designer")),
            ("页面", "我的船队（直达）", lambda: self.goto("mine")),
            ("页面", "星图（直达）", lambda: self.goto("systems")),
            ("页面", "游戏内代理（直达）", lambda: self.goto("live")),
            ("页面", "设置（直达）", lambda: self.goto("settings")),
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
            self.activate_view("glyphs", announce=False)
            self.toast("已打开地址工作台", "info")
        elif target == "favorites":
            self._open_favorites()

    def _open_favorites(self) -> None:
        self.activate_view("search", announce=False)
        page = self.pages.get("search")
        opener = getattr(page, "open_favorites", None)
        if callable(opener):
            opener()

    def _open_backups(self) -> None:
        self.activate_view("fleet", announce=False)
        page = self.pages.get("mine")
        opener = getattr(page, "open_backups", None)
        if callable(opener):
            opener()

    def _open_address_workbench(self) -> None:
        self.activate_view("glyphs", announce=False)

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

    # ---------------------------------------------------------------- 上手向导

    def open_onboarding(self) -> None:
        if self._onboarding is None:
            wizard = RfOnboardingWizard(self._health, self)
            wizard.detectRequested.connect(self._onboarding_detect)
            wizard.navigateRequested.connect(self._onboarding_navigate)
            wizard.completed.connect(self._onboarding_complete)
            wizard.skipped.connect(self._onboarding_skip)
            self._onboarding = wizard
            self.onboarding = wizard
        self._onboarding.update_health(self._health)
        self._onboarding.show()
        self._onboarding.raise_()
        self._onboarding.activateWindow()

    def _maybe_show_onboarding(self) -> None:
        if os.environ.get("STARFORGE_SKIP_ONBOARDING") == "1":
            return
        if self._onboarding_scheduled and self._onboarding is not None \
                and self._onboarding.isVisible():
            return
        if not self.isVisible():
            return
        if bool(self._settings.value("onboarding/seen", False, type=bool)):
            return
        if bool(self._settings.value("onboarding/done", False, type=bool)):
            return
        self._onboarding_scheduled = True
        self._settings.setValue("onboarding/seen", True)
        self._settings.sync()
        self.open_onboarding()

    def _onboarding_detect(self) -> None:
        wizard = self._onboarding
        if wizard is None:
            return

        def done(res: dict) -> None:
            res = res if isinstance(res, dict) else {}
            found = res.get("found") or {}
            wizard.set_busy(False)
            if found:
                self.toast(f"自动检测完成：找到 {len(found)} 项路径", "success")
            else:
                self.toast("没有找到游戏或存档目录，请手动选择", "warn")
            self.refresh_health()

        def failed(msg: str) -> None:
            wizard.set_busy(False)
            wizard.update_health(self._health)
            self.toast(f"自动检测失败：{msg}", "error")

        run_worker(self.svc.autodetect, done, failed, True)

    def _onboarding_navigate(self, target: str) -> None:
        target = str(target or "")
        if target == "link:mod":
            self.activate_view("mod", announce=True)
            return
        if target == "settings:saves":
            self.activate_view("paths", announce=False)
            QTimer.singleShot(50, lambda: self._focus_setting(
                "saves", "已定位到设置中的存档目录"))
            return
        self.activate_view("paths", announce=False)
        QTimer.singleShot(50, lambda: self._focus_setting(
            "game", "已定位到设置中的游戏目录"))

    def _onboarding_complete(self) -> None:
        self._mark_onboarding_done()
        self.toast("上手完成：可以开始搜船了", "success")

    def _onboarding_skip(self) -> None:
        self._mark_onboarding_done()
        self.toast("已跳过上手；随时点顶部「上手」重新打开", "info")

    def _mark_onboarding_done(self) -> None:
        self._settings.setValue("onboarding/done", True)
        self._settings.setValue("onboarding/seen", True)
        self._settings.sync()
        self.refresh_health()

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
        self._health = dict(h or {})
        self.status_strip.set_health(self._health)
        self.mode.setText(f"预览级别 {h.get('preview_level', 'L0')} · 原生窗口")
        if self._onboarding is not None:
            self._onboarding.update_health(self._health)
        self._update_next_step()

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
        if not self._onboarding_scheduled:
            self._onboarding_scheduled = True
            QTimer.singleShot(450, self._maybe_show_onboarding)

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
