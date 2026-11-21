"""星图扫描结果 →「传送到此星球」：门地址推导与三种返回的界面文案。

全部打桩：不连 agent、不碰游戏进程，也不实例化真实 `Services`。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from starforge.app.pages import galaxy as page_mod

UA = 0x11200F19BDCE5
GLYPHS_PLANET_3 = "3112F19BDCE5"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class FakeServices:
    """只实现页面会用到的服务；记录 warp 调用，绝不创建 AgentClient。"""

    def __init__(self, result: dict | None = None, error: Exception | None = None):
        self.result = result if result is not None else {"ok": True, "confirmed": True}
        self.error = error
        self.warp_calls: list[dict] = []

    def warp_portal(self, glyphs: str, galaxy: int | None = None,
                    stage: str = "prepare_warp") -> dict:
        self.warp_calls.append({"glyphs": glyphs, "galaxy": galaxy, "stage": stage})
        if self.error is not None:
            raise self.error
        return dict(self.result)

    def glyph_strip_png(self, glyphs: str) -> bytes:
        return b""


def _sync_worker(fn, on_done=None, on_error=None, *args, **kwargs):
    try:
        res = fn(*args, **kwargs)
    except Exception as e:                                  # noqa: BLE001 - 与真实 worker 一致
        if on_error is not None:
            on_error(f"{type(e).__name__}: {e}")
        return
    if on_done is not None:
        on_done(res)


def _capture_notify(monkeypatch) -> dict[str, list[str]]:
    captured: dict[str, list[str]] = {"success": [], "error": [], "warn": [], "toast": []}
    for name in list(captured):
        def record(text, _name=name, **_kwargs):
            captured[_name].append(str(text))

        monkeypatch.setattr(page_mod.notify, name, record)
    return captured


def _accept_confirm(monkeypatch, answer=None) -> list[dict]:
    from PySide6.QtWidgets import QMessageBox

    seen: list[dict] = []

    def warn(parent, title, text, *args, **kwargs):
        seen.append({"title": title, "text": text})
        return QMessageBox.Yes if answer is None else answer

    monkeypatch.setattr(page_mod.QMessageBox, "warning", staticmethod(warn))
    return seen


def _make_page(monkeypatch, svc: FakeServices, row: dict):
    monkeypatch.setattr(page_mod, "get_services", lambda: svc)
    page = page_mod.GalaxyPage()
    page._fill_scan_rows([row])
    page.scan_table.show()
    page.scan_table.selectRow(0)
    return page


# ---------------------------------------------------------------- 门地址推导


def test_result_ua_generates_glyphs_for_selected_planet():
    assert page_mod._warp_glyphs_for({"ua": f"0x{UA:X}", "index": 3}) == GLYPHS_PLANET_3
    assert page_mod._warp_glyphs_for({"ua": UA, "planet_index": 6}) == "6112F19BDCE5"


def test_result_without_valid_address_has_no_glyphs():
    assert page_mod._warp_glyphs_for({}) == ""
    assert page_mod._warp_glyphs_for({"ua": "not-a-ua", "index": 1}) == ""
    # 第 1 位必须是 1..6；9 号行星不能悄悄退化成 1 号
    assert page_mod._warp_glyphs_for({"ua": f"0x{UA:X}", "index": 9}) == ""
    assert page_mod._warp_glyphs_for({"glyphs": "0104F19BDCE5"}) == ""


def test_existing_valid_glyphs_are_used_when_ua_is_missing():
    assert page_mod._warp_glyphs_for({"glyphs": "2112F19BDCE5"}) == "2112F19BDCE5"


# ---------------------------------------------------------------- 按钮可用性


def test_button_disabled_with_hint_when_row_has_no_address(qapp, monkeypatch):
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    page = _make_page(monkeypatch, FakeServices(),
                      {"index": 1, "system_name": "无地址星系",
                       "coords": "04E4:0070:01BC:0104"})
    assert page.warp_btn.isEnabled() is False
    assert "没有可用的门地址" in page.warp_hint.text()


def test_button_enabled_for_row_with_ua(qapp, monkeypatch):
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    page = _make_page(monkeypatch, FakeServices(), {
        "ua": f"0x{UA:X}", "index": 3, "system_name": "EOCS-1", "galaxy": 0})
    assert page.warp_btn.isEnabled() is True
    assert GLYPHS_PLANET_3 in page.warp_hint.text()


# ---------------------------------------------------------------- 三种返回文案


def test_success_toast_names_system_and_planet(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    confirmed = _accept_confirm(monkeypatch)
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    svc = FakeServices({"ok": True, "confirmed": True})
    page = _make_page(monkeypatch, svc, {
        "ua": f"0x{UA:X}", "index": 3, "system_name": "EOCS-1", "galaxy": 0,
        "coords": "04E4:0070:01BC:0104"})

    page._warp_selected_planet()

    assert svc.warp_calls == [
        {"glyphs": GLYPHS_PLANET_3, "galaxy": 0, "stage": "prepare_warp"}]
    assert captured["success"][-1] == "已传送到 EOCS-1/行星 #3"
    assert captured["error"] == []
    assert "会调用游戏内传送门机制，落到目标星球；失败可用「还原」回滚" in confirmed[0]["text"]
    assert page.warp_btn.isEnabled() is True


def test_build_unverified_shows_original_error_and_settings_hint(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    _accept_confirm(monkeypatch)
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    svc = FakeServices({"ok": False, "code": "E_BUILD_UNVERIFIED",
                        "error": "这版未验证：高风险写操作已禁用"})
    page = _make_page(monkeypatch, svc, {
        "ua": f"0x{UA:X}", "index": 3, "system_name": "EOCS-1", "galaxy": 0})

    page._warp_selected_planet()

    assert captured["success"] == []
    message = captured["error"][-1]
    assert message.startswith("传送失败：")
    assert "E_BUILD_UNVERIFIED" in message
    assert "这版未验证：高风险写操作已禁用" in message
    assert "需要先开启实验写入开关" in message
    assert "需要先开启实验写入开关" in page.status.text()
    assert page.warp_btn.isEnabled() is True


def test_network_failure_is_shown_verbatim(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    _accept_confirm(monkeypatch)
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    svc = FakeServices(error=ConnectionError("connection refused"))
    page = _make_page(monkeypatch, svc, {
        "ua": f"0x{UA:X}", "index": 3, "system_name": "EOCS-1", "galaxy": 0})

    page._warp_selected_planet()

    assert captured["success"] == []
    message = captured["error"][-1]
    assert "ConnectionError" in message and "connection refused" in message
    assert page.warp_btn.isEnabled() is True


def test_agent_error_dict_is_shown_verbatim(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    _accept_confirm(monkeypatch)
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    svc = FakeServices({"ok": False, "code": "E_AGENT", "error": "TimeoutError: timed out"})
    page = _make_page(monkeypatch, svc, {
        "ua": f"0x{UA:X}", "index": 3, "system_name": "EOCS-1", "galaxy": 0})

    page._warp_selected_planet()

    message = captured["error"][-1]
    assert "E_AGENT" in message and "TimeoutError: timed out" in message


def test_warp_never_uses_real_agent_client(qapp, monkeypatch):
    from starforge.services import Services

    def boom(_self):
        raise AssertionError("不应调用真实 AgentClient")

    monkeypatch.setattr(Services, "agent_client", boom)
    _capture_notify(monkeypatch)
    _accept_confirm(monkeypatch)
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    svc = FakeServices({"ok": True, "confirmed": True})
    page = _make_page(monkeypatch, svc, {
        "ua": f"0x{UA:X}", "index": 3, "system_name": "EOCS-1", "galaxy": 0})

    page._warp_selected_planet()

    assert svc.warp_calls and svc.warp_calls[0]["glyphs"] == GLYPHS_PLANET_3
