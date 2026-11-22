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
        assert "主操作：写回存档" in page.action_note.text()
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
        assert "主操作：送进游戏" in page.action_note.text()
    finally:
        page.close()


def test_ship_viewer_demo_mesh(qapp):
    from starforge.app.widgets.ship_viewer import ShipViewer

    viewer = ShipViewer()
    viewer.set_demo()
    assert viewer._groups
    assert viewer._radius > 0.5


def test_link_steps_and_settings_groups(qapp, monkeypatch):
    """联动是三步链路，设置是四个默认折叠的问题分组。"""
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
            "运行时 / 组件", "游戏连接", "模板 Mod"]
        assert all(panel.action.text() for panel in steps)
        assert link.advanced.is_expanded() is False
        assert link.live_assets.isVisibleTo(link.advanced) is False
        assert "实时资产" in link.advanced.title_label.text()
    finally:
        link.close()

    settings = settings_mod.SettingsPage()
    try:
        groups = settings.findChildren(FoldSection)
        assert [group.title_label.text() for group in groups] == [
            "路径与自动检测", "安全与性能", "版本与代理", "诊断"]
        assert all(group.is_expanded() is False for group in groups)
        assert settings.run_health_btn.objectName() == "primary"
    finally:
        settings.close()


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
