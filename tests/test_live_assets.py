"""「实时资产（只读）」卡片：有数据 / 空数据 / agent 不可达。

全部打桩：不实例化真实 AgentClient、不连游戏、不读真实存档。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel, QPushButton

from starforge.app.pages import game_link as page_mod
from starforge.app.widgets.live_assets import (
    LiveAssetsCard,
    live_asset_error_text,
    multitool_slots,
    pets_active_text,
)

CAPABILITIES = {
    "status": {
        "runtime_ready": True, "pymhf_http_api": True,
        "nmspy_version": "1.0", "pymhf_version": "1.0",
        "reachable": True, "hello": {"in_game": True}, "supported": True,
        "note": "",
    },
    "capabilities": {
        "multitool": {"available": True}, "freighter": {"available": True},
        "pets": {"available": True}, "planet.scan": {"available": True},
        "scan.poi": {"available": True},
    },
    "build": {"build_id": "185034", "verified": True, "write_allowed": True},
    "multiplayer": False,
}

MULTITOOL = {
    "ok": True, "count": 2, "current_slot": 0,
    "slots": [
        {"slot": 0, "name": "分解者", "class": "S",
         "seed": "0x9BA274EE421CB66F", "empty": False,
         "inventory": {"filled": 2, "capacity": 24}},
        {"slot": 1, "name": "", "class": "A", "seed": "0x11", "empty": False,
         "inventory": {"filled": 0, "capacity": 12}},
        {"slot": 2, "name": "", "class": None, "seed": "", "empty": True,
         "inventory": {"filled": 0, "capacity": 0}},
    ],
}

FREIGHTER = {
    "ok": True,
    "freighter": {"owned": True, "name": "界主", "class": "S",
                  "inventory": {"filled": 51, "capacity": 120}},
    "frigate_count": 30,
    "frigates": [{"name": "运输", "class": "DeepSpace"},
                 {"name": "", "class": "Combat"},
                 {"name": "采矿", "class": "Industrial"}],
}

PETS = {
    "ok": True, "count": 2,
    "pets": [
        {"index": 6, "name": "蝴蝶坐骑", "species": "LARGEBUTTERFLY",
         "seeds": {"creature": "0x0E4E24DB2A1F78BE"},
         "active": None, "active_supported": False},
        {"index": 9, "name": "", "species": "COW", "seeds": {},
         "active": None, "active_supported": False},
    ],
    "source": "cGcPlayerState.SaveToData() → cGcPlayerStateData.Pets[30]",
}


class FakeServices:
    """只实现页面用到的服务；绝不创建 AgentClient。"""

    def __init__(self, results: dict | None = None, errors: dict | None = None):
        self.results = dict(results or {})
        self.errors = dict(errors or {})
        self.calls: list[str] = []

    def live_capabilities(self) -> dict:
        return dict(CAPABILITIES)

    def settings_snapshot(self) -> dict:
        return {"ok": True, "settings": {}}

    def agent_call(self, cmd: str, **_params) -> dict:
        self.calls.append(cmd)
        if cmd in self.errors:
            raise self.errors[cmd]
        return dict(self.results.get(cmd) or {"ok": True})


def _sync_worker(fn, on_done=None, on_error=None, *args, **kwargs):
    try:
        res = fn(*args, **kwargs)
    except Exception as e:                                  # noqa: BLE001 - 与真实 worker 一致
        if on_error is not None:
            on_error(f"{type(e).__name__}: {e}")
        return
    if on_done is not None:
        on_done(res)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _make_page(monkeypatch, svc: FakeServices) -> page_mod.GameLinkPage:
    monkeypatch.setattr(page_mod, "get_services", lambda: svc)
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    page = page_mod.GameLinkPage()
    page._apply_state(CAPABILITIES)          # 连接成功 → 自动拉一次资产
    return page


def _labels(widget) -> list[str]:
    return [label.text() for label in widget.findChildren(QLabel)]


# ---------------------------------------------------------------- 有数据


def test_card_shows_tools_freighter_and_pets(qapp, monkeypatch):
    svc = FakeServices({"multitool": MULTITOOL, "freighter": FREIGHTER, "pets": PETS})
    page = _make_page(monkeypatch, svc)
    card = page.live_assets

    assert svc.calls == ["multitool", "freighter", "pets"]
    assert card.title_label.text() == "实时资产（只读）"
    text = "\n".join(_labels(card))
    assert "多功能工具（只读）" in text
    assert "货船与舰队（只读）" in text
    assert "同伴（只读）" in text

    assert card.multitool_status.text() == "3 槽 · 实际 2 把 · 当前槽 0"
    assert "分解者 · S 级 · 种子 0x9BA274EE421CB66F · 库存 2/24" in text
    assert "（未命名） · A 级 · 种子 0x11 · 库存 0/12" in text
    assert "槽 2    —" in text

    assert card.freighter_status.text() == "名称：界主 · 等级 S · 库存 51/120"
    assert "护卫舰：30 艘" in card.freighter_body.text()
    assert "1. 运输 · DeepSpace" in card.freighter_body.text()

    assert card.pets_status.text() == "当前出战：未知（存档结构不提供该标记）"
    assert "蝴蝶坐骑 · LARGEBUTTERFLY · 种子 0x0E4E24DB2A1F78BE" in card.pets_body.text()
    assert "（未命名） · COW · 种子 —" in card.pets_body.text()
    assert card.pets_source.text().startswith("来源：cGcPlayerState")
    assert card.pets_source.isVisible() or card.pets_source.text()

    # 只读卡片：区块标题都写明「只读」，且没有任何按钮
    assert card.findChildren(QPushButton) == []
    assert page.error_banner.message.text() == ""


def test_current_slot_is_highlighted(qapp, monkeypatch):
    svc = FakeServices({"multitool": MULTITOOL, "freighter": FREIGHTER, "pets": PETS})
    page = _make_page(monkeypatch, svc)

    current = [label for label in page.live_assets.findChildren(QLabel)
               if label.objectName() == "liveAssetCurrent"]
    assert len(current) == 1
    assert "分解者" in current[0].text()
    assert current[0].toolTip() == "当前使用中的多功能工具"


# ---------------------------------------------------------------- 空数据


def test_empty_data_uses_dashes_and_real_notes(qapp, monkeypatch):
    empty_tool = {
        "ok": True, "count": 0, "current_slot": None,
        "slots": [{"slot": i, "empty": True, "class": None, "seed": "",
                   "inventory": {"filled": 0, "capacity": 0}} for i in range(6)],
    }
    empty_freighter = {"ok": True, "freighter": {"owned": False},
                       "frigate_count": 0, "frigates": []}
    empty_pets = {"ok": True, "pets": [],
                  "note": "Pets[30] 全是空槽（当前存档没有同伴）"}
    svc = FakeServices({"multitool": empty_tool, "freighter": empty_freighter,
                        "pets": empty_pets})
    page = _make_page(monkeypatch, svc)
    card = page.live_assets

    assert card.multitool_status.text() == "6 槽 · 实际 0 把 · 当前槽 —"
    rows = [label.text() for label in card.findChildren(QLabel)
            if label.text().startswith("槽 ")]
    assert len(rows) == 6 and all(row.endswith("—") for row in rows)

    assert card.freighter_status.text() == "未持有货船"
    assert card.freighter_body.text() == "护卫舰：0 艘"

    assert card.pets_status.text() == "当前出战：—"
    assert card.pets_body.text() == "Pets[30] 全是空槽（当前存档没有同伴）"
    assert page.error_banner.message.text() == ""


def test_empty_slot_and_missing_active_are_explicit():
    slots = multitool_slots({"slots": [{"slot": 4, "empty": True}], "current_slot": 4})
    assert slots[0]["empty"] is True
    assert slots[0]["current"] is True
    assert slots[0]["text"] == "槽 4    —"

    payload = {"pets": [{"index": 0, "name": "小蓝", "active": None,
                         "active_supported": False}]}
    assert pets_active_text(payload) == "当前出战：未知（存档结构不提供该标记）"
    # 不能把「读不到出战标记」误写成「未出战」
    assert "未出战" not in pets_active_text(payload)

    card = LiveAssetsCard()
    card.set_data("multitool", {"slots": [{"slot": 0, "empty": True}]})
    assert "槽 0    —" in "\n".join(_labels(card))


def test_page_refresh_auto_pulls_assets_once(qapp, monkeypatch):
    svc = FakeServices({"multitool": MULTITOOL, "freighter": FREIGHTER, "pets": PETS})
    monkeypatch.setattr(page_mod, "get_services", lambda: svc)
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    page = page_mod.GameLinkPage()

    page.refresh()                            # 等价于用户点「刷新状态」

    assert svc.calls == ["multitool", "freighter", "pets"]
    assert page.live_assets.multitool_status.text().startswith("3 槽")


# ---------------------------------------------------------------- agent 不可达


def test_unreachable_agent_shows_readable_errors_and_retry(qapp, monkeypatch):
    svc = FakeServices(
        results={
            "freighter": {"ok": False, "code": "E_AGENT",
                          "error": "连不上游戏内 agent：Connection refused"},
        },
        errors={"multitool": ConnectionError("connection refused"),
                "pets": RuntimeError("agent 响应超时")})
    page = _make_page(monkeypatch, svc)
    card = page.live_assets

    assert "多功能工具读取失败：未连接游戏内代理" in card.multitool_status.text()
    assert "ConnectionError" in card.multitool_status.text()
    assert "货船与舰队读取失败：未连接游戏内代理" in card.freighter_status.text()
    assert "同伴读取失败：未连接游戏内代理" in card.pets_status.text()

    # 失败不伪造空数据
    assert card.freighter_body.text() == "—"
    assert card.pets_body.text() == "—"
    assert "实际 0 把" not in card.multitool_status.text()

    # 页面横幅给出可读错误，并保留「重试」
    banner = page.error_banner
    assert banner.message.text().count("读取失败") == 3
    assert banner.retry.isEnabled() is True
    assert banner.retry.text() == "重试"

    # 重试成功后横幅收起、数据恢复
    svc.errors.clear()
    svc.results.update({"multitool": MULTITOOL, "freighter": FREIGHTER, "pets": PETS})
    banner.retry.click()
    assert page.error_banner.message.text() == ""
    assert card.freighter_status.text() == "名称：界主 · 等级 S · 库存 51/120"


def test_error_helper_keeps_original_detail():
    text = live_asset_error_text(
        "多功能工具", "agent 返回 HTTP 500：Internal Server Error",
        code="E_AGENT")
    assert text.startswith("多功能工具读取失败：未连接游戏内代理")
    assert "HTTP 500" in text

    assert ("游戏尚未进入存档" in
            live_asset_error_text("同伴", "还没进入存档（player_state 为空）"))
    assert ("不支持该读取能力" in
            live_asset_error_text("货船与舰队", "unknown endpoint", unsupported=True))


# ---------------------------------------------------------------- 隔离


def test_never_calls_real_agent_client(qapp, monkeypatch):
    from starforge.services import Services

    def boom(_self):
        raise AssertionError("不应调用真实 AgentClient")

    monkeypatch.setattr(Services, "agent_client", boom)
    svc = FakeServices({"multitool": MULTITOOL, "freighter": FREIGHTER, "pets": PETS})
    page = _make_page(monkeypatch, svc)

    assert svc.calls == ["multitool", "freighter", "pets"]
    assert page.live_assets.multitool_status.text().startswith("3 槽")


# ---------------------------------------------------------------- 三步状态机


def test_three_step_state_machine_highlights_only_next(qapp, monkeypatch):
    import copy

    from PySide6.QtWidgets import QPushButton

    def primaries() -> list:
        return [b for b in page.findChildren(QPushButton)
                if b.objectName() == "primary"]

    svc = FakeServices({"multitool": MULTITOOL, "freighter": FREIGHTER, "pets": PETS})
    page = _make_page(monkeypatch, svc)
    page._detect_template_mod = lambda: 0

    # 前两步完成 → 只有模板 Mod 是「进行中」，primary 只留给「刷新状态」
    page._apply_state(copy.deepcopy(CAPABILITIES))
    assert page.step1.property("state") == "done"
    assert page.step2.property("state") == "done"
    assert page.step3.property("state") == "current"
    assert page.step3.action.text() == "安装 / 更新模板 Mod"
    assert primaries() == [page.refresh_btn]

    # 运行时缺失 → 第 1 步进行中，后两步等待但仍可点；primary 是准备运行时
    blocked = copy.deepcopy(CAPABILITIES)
    blocked["status"].update({
        "runtime_ready": False, "pymhf_http_api": False,
        "nmspy_version": "", "pymhf_version": "",
        "reachable": False, "hello": {"in_game": False},
        "runtime_error": "找不到 python.exe"})
    blocked["capabilities"] = {}
    page._apply_state(blocked)
    assert page.step1.property("state") == "current"
    assert page.step2.property("state") == "waiting"
    assert page.step3.property("state") == "waiting"
    assert page.step1.action.text() == "准备运行时"
    assert "下一步" in page.status.text() and "运行时" in page.status.text()
    assert page.step2.action.isEnabled() and page.step3.action.isEnabled()
    assert primaries() == [page.step1.action]

    # 运行时文件在、组件缺失 → 第 1 步标红并给「安装 / 修复组件」
    page._apply_state({
        "status": {"runtime_ready": True, "pymhf_http_api": False,
                   "nmspy_version": "", "pymhf_version": "",
                   "reachable": False, "hello": {}, "supported": True},
        "capabilities": {},
        "build": {"build_id": "1", "verified": False},
        "multiplayer": False,
    })
    assert page.step1.property("state") == "error"
    assert page.step1.action.text() == "安装 / 修复组件"
    assert primaries() == [page.step1.action]
    page.close()
