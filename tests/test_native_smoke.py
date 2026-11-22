"""原生壳冒烟：没有 PySide6 的机器跳过。"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def drain_background_workers(qapp):
    """原生页会起贴图/图标后台任务；测试结束前等它们收尾，避免 Qt 退出崩溃。"""
    yield
    from PySide6.QtCore import QThreadPool

    qapp.processEvents()
    QThreadPool.globalInstance().waitForDone(20000)
    qapp.processEvents()


@pytest.fixture(autouse=True)
def _stub_heavy_shell_services(monkeypatch):
    """壳层冒烟只验证结构与导航；不要启动真实 3D/部件/存档扫描后台线程。

    这些线程可能在 QApplication 销毁或临时目录清理后仍在读游戏 pak，
    在 Windows 上会触发 access violation，和界面回归无关。
    """
    from starforge.services import Services

    monkeypatch.setattr(Services, "part_icon", lambda self, *a, **k: b"")
    monkeypatch.setattr(Services, "part_thumb", lambda self, *a, **k: b"")
    monkeypatch.setattr(Services, "catalog_ship",
                        lambda self, *a, **k: {"groups": [], "source": "stub"})
    monkeypatch.setattr(Services, "saves",
                        lambda self, *a, **k: {"files": [], "folder": ""})
    monkeypatch.setattr(Services, "health", lambda self, *a, **k: {
        "game_dir": "", "saves_ready": False})
    monkeypatch.setattr(Services, "diagnostics_overview",
                        lambda self, *a, **k: {"checks": []})
    monkeypatch.setattr(Services, "live_capabilities",
                        lambda self, *a, **k: {"ready": False})



def test_native_main_window_builds(qapp, monkeypatch):
    from starforge.app.shell import MainWindow
    from starforge.services import Services

    # 本测试只验证壳层结构：不渲染真实部件图标，避免后台贴图线程
    # 在 Qt 退出阶段仍在跑（与应用逻辑无关，纯测试稳定性）。
    monkeypatch.setattr(Services, "part_icon", lambda *a, **k: None)
    monkeypatch.setattr(Services, "part_thumb", lambda *a, **k: b"")

    win = MainWindow()
    try:
        assert win.windowTitle()
        assert set(win.pages) == {"home", "search", "designer", "mine", "systems", "live", "settings"}
        assert win.stack.count() == 7
        win.goto("settings")
        assert win.stack.currentWidget() is win.pages["settings"]
    finally:
        win.close()
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().waitForDone(15000)
        qapp.processEvents()


def test_four_workspaces_and_mine_entries(qapp):
    from starforge.app.shell import WORKSPACE_BY_KEY, WORKSPACES

    assert [ws["title"] for ws in WORKSPACES] == ["情报台", "我的", "联动", "设置"]
    mine = WORKSPACE_BY_KEY["mine"]
    assert [view["title"] for view in mine["views"]] == ["船队", "设计器", "存档"]
    assert mine["views"][0]["page"] == "mine"


def test_fixed_model_never_requests_3d(qapp, monkeypatch):
    from starforge.app.pages import fleet as fleet_mod

    calls: list[str] = []

    def record(fn, *args, **kwargs):
        calls.append(getattr(fn, "__name__", str(fn)))

    monkeypatch.setattr(fleet_mod, "run_worker", record)
    page = fleet_mod.FleetPage()
    try:
        page._loaded_path = "C:/saves/save.hg"
        page._ships = [{"type": "fighter", "type_label": "战斗机",
                        "seed": "0xFIXED", "slot": 3, "procedural": False}]
        page._rebuild_ship_list()
        page.list.setCurrentRow(0)
        qapp.processEvents()
        assert "preview_mesh" not in calls
        assert "preview_png" not in calls
        assert "固定模型" in page.fallback.text()
        assert page.fallback.isHidden() is False
    finally:
        page.close()


def test_fleet_tabs_and_single_primary_action(qapp, monkeypatch):
    from starforge.app.pages import fleet as fleet_mod

    # 冒烟只验证布局/主操作；不启动缩略图与预览线程，避免测试进程退出时抢临时目录。
    monkeypatch.setattr(fleet_mod, "run_worker", lambda *a, **k: None)
    page = fleet_mod.FleetPage()
    try:
        assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
            "飞船", "同伴", "护卫舰", "工具", "货船"]
        assert page.companion is not None
        assert page.pets._inline_detail is False

        # 有可写槽位：写回是唯一主操作（危险色），送进游戏降为次要按钮。
        page._loaded_path = "C:/saves/save.hg"
        page._ships = [{"type": "fighter", "type_label": "战斗机", "seed": "0xA",
                        "slot": 3, "procedural": False,
                        "stats": {"damage": 10}}]
        page._rebuild_ship_list()
        page.list.setCurrentRow(0)
        qapp.processEvents()
        assert page.write_btn.objectName() == "dangerButton"
        assert page.write_btn.isEnabled() is True
        assert page.push_btn.objectName() == "ghostButton"
        # 主操作只用颜色表达；没有可写槽等情况才显示 action_note。
        assert page.action_note.isHidden()
        preview = page.write_preview.text()
        assert "写回前：未知 级 · 伤害 10" in preview
        assert "写回后：在「船级/属性…」对话框里确认 before → after" in preview

        # 没有可写槽位但有模板槽：送进游戏成为主操作。
        page._ships = [{"type": "fighter", "type_label": "战斗机", "seed": "0xB",
                        "slot": None, "procedural": False}]
        page._rebuild_ship_list()
        page.list.setCurrentRow(0)
        qapp.processEvents()
        assert page.write_btn.isEnabled() is False
        assert page.push_btn.objectName() == "primaryButton"
        assert page.action_note.isHidden()
    finally:
        page.close()


def _flow_states(page) -> list[str]:
    return [wrap.property("state") for wrap, _number, _label in page.flow._items]


def test_fleet_task_flow_detail_hidden_until_selected(qapp, monkeypatch):
    """船队：① 读存档 → ② 选一项 → ③ 执行；详情默认收起，× 收起。"""
    from starforge.app.pages import fleet as fleet_mod
    from starforge.app.widgets import fleet_companion as companion_mod
    from starforge.app.widgets import pets_view as pets_mod

    monkeypatch.setattr(fleet_mod, "run_worker", lambda *a, **k: None)
    monkeypatch.setattr(pets_mod, "run_worker", lambda *a, **k: None)
    monkeypatch.setattr(companion_mod, "run_worker", lambda *a, **k: None)
    page = fleet_mod.FleetPage()
    try:
        # 初始：只显示「读存档」，详情与同伴面板都不占右侧。
        assert _flow_states(page) == ["active", "pending", "pending"]
        assert page.detail_card.isHidden() is True
        assert page.companion.isHidden() is True
        assert page.load_btn.objectName() == "primary"
        assert page.browse_btn.objectName() == "ghostButton"
        assert page.more_btn.menu() is page.more_menu
        assert page.backup_btn in page.more_menu.actions()

        # 已读、未选中：第 2 步 active；自动选中已取消，表格占满。
        page._loaded_path = "C:/saves/save.hg"
        page._set_save_path(page._loaded_path)
        page._ships = [{"type": "fighter", "type_label": "战斗机", "seed": "0xA",
                        "slot": 3, "procedural": False}]
        page._rebuild_ship_list()
        page._update_ship_empty()
        page._sync_flow()
        assert _flow_states(page) == ["done", "active", "pending"]
        assert page.detail_card.isHidden() is True
        assert page.list.selectedItems() == []

        # 选中一行：第 3 步 active，详情出现，右上角 × 是统一图标按钮。
        page.list.setCurrentRow(0)
        qapp.processEvents()
        assert _flow_states(page) == ["done", "done", "active"]
        assert page.detail_card.isHidden() is False
        assert page.detail_close.objectName() == "uxIconButton"

        page.detail_close.click()
        qapp.processEvents()
        assert page.detail_card.isHidden() is True
        assert page.list.selectedItems() == []
        assert _flow_states(page) == ["done", "active", "pending"]

        # 同伴标签：没有选中同伴时不显示右栏；选中后才出现，× 可收起。
        page.tabs.setCurrentWidget(page.pets)
        assert page.detail_card.isHidden() is True
        assert page.companion.isHidden() is True
        page.pets._render({"creatures": [{"name": "小蓝", "creature": "BIRD",
                                         "seeds": {"creature": "0x12"}}],
                           "_roles": {"count": 1}})
        assert page.pets.selected_creature() is None
        page.pets.table.selectRow(0)
        qapp.processEvents()
        assert page.detail_card.isHidden() is False
        assert page.companion.isHidden() is False
        page.detail_close.click()
        qapp.processEvents()
        assert page.detail_card.isHidden() is True
        assert page.companion.isHidden() is True
    finally:
        page.close()


def test_ship_viewer_demo_mesh(qapp):
    from starforge.app.widgets.ship_viewer import ShipViewer

    viewer = ShipViewer()
    viewer.set_demo()
    assert viewer._groups
    assert viewer._radius > 0.5


def test_link_steps_and_settings_groups(qapp, monkeypatch):
    """联动是三步纵向行，设置是四个默认折叠的问题分组。"""
    from starforge.app.pages import game_link as link_mod
    from starforge.app.pages import settings as settings_mod
    from starforge.app.widgets.game_flow import StepPanel
    from starforge.app.widgets.settings_flow import FoldSection

    # 只检查分组结构；后台扫描/连接状态不在冒烟范围内。
    monkeypatch.setattr(link_mod, "run_worker", lambda *a, **k: None)
    monkeypatch.setattr(settings_mod, "run_worker", lambda *a, **k: None)
    link = link_mod.GameLinkPage()
    try:
        steps = link.findChildren(StepPanel)
        assert [panel.title_label.text() for panel in steps] == [
            "运行时", "游戏连接", "模板 Mod"]
        assert all(panel.action.text() for panel in steps)
        # 行式布局：状态点 + 一行状态都还在，只是不再竖排大卡。
        assert all(getattr(panel, "dot", None) is not None for panel in steps)
        assert link.advanced.is_expanded() is False
        assert link.live_assets.isVisibleTo(link.advanced) is False
        assert "高级" in link.advanced.title_label.text()
        assert "更多" in link.advanced.title_label.text()
    finally:
        link.close()

    settings = settings_mod.SettingsPage()
    try:
        groups = settings.findChildren(FoldSection)
        assert [group.title_label.text() for group in groups] == [
            "路径与自动检测", "安全与性能", "版本与代理", "诊断"]
        assert all(group.is_expanded() is False for group in groups)
        assert settings.run_health_btn.objectName() == "primary"
        # 行式设置：左侧标签统一固定 120，三行目录控件一致。
        from PySide6.QtWidgets import QLabel

        labels = {lab.text(): lab for lab in settings.findChildren(QLabel)}
        for name in ("游戏目录", "存档目录", "数据目录"):
            assert labels[name].minimumWidth() == 120
        assert settings.paths_group.chip.text() in ("已定位", "需设置")
    finally:
        settings.close()


def test_link_step2_buttons_follow_connection_state(qapp, monkeypatch):
    """第 2 步三态：已连接→刷新；游戏在跑→附加注入+重启；没跑→启动并注入。"""
    from starforge.app.pages import game_link as link_mod

    monkeypatch.setattr(link_mod, "run_worker", lambda *a, **k: None)
    page = link_mod.GameLinkPage()
    try:
        page._supported = True
        page._runtime_ready = True
        page._in_game = False

        # 已连接：主按钮只刷新，次按钮隐藏（绝不重复注入）。
        page._reachable = True
        page._game_running = True
        page._sync_steps()
        assert page.step2.action.text() == "刷新状态"
        assert page.step2.alt.isHidden()

        # 游戏在跑但不可达：主按钮附加注入，次按钮重启并注入可见。
        page._reachable = False
        page._game_running = True
        page._sync_steps()
        assert page.step2.action.text() == "附加注入"
        assert not page.step2.alt.isHidden()
        assert page.step2.alt.text() == "重启并注入"

        # 游戏没跑：主按钮启动游戏并注入，次按钮隐藏。
        page._game_running = False
        page._sync_steps()
        assert page.step2.action.text() == "启动游戏并注入"
        assert page.step2.alt.isHidden()
    finally:
        page.close()


def test_workspace_pages_keep_exactly_one_primary(qapp):
    """情报台搜船 / 我的设计器：每个页面只允许一个 primary。

    直接构造两个页面，避免把「壳」里其它页面的加载/预览拖进这条冒烟测试。
    """
    from PySide6.QtWidgets import QPushButton

    from starforge.app.pages.ship_designer import ShipDesignerPage
    from starforge.app.pages.ship_lab import ShipLabPage

    lab, designer = ShipLabPage(), ShipDesignerPage()
    try:
        for page, text in ((lab, "开始搜索"), (designer, "写入存档")):
            primaries = [button for button in page.findChildren(QPushButton)
                         if button.objectName() == "primary"]
            assert len(primaries) == 1, type(page).__name__
            assert primaries[0].text() == text
        assert lab.advanced.isHidden()
        assert designer.summary.isHidden()
    finally:
        lab.close()
        designer.close()
