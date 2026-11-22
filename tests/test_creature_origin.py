"""同伴 → 来源行星 → 12 位符文 →（可选）传送：纯逻辑与界面文案。

全部打桩：不读真实存档、不连 agent、不实例化真实 `Services`。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from starforge import creature
from starforge.app.widgets import fleet_companion as companion_mod
from starforge.app.widgets import pets_view as pets_mod

# 已知 UA：system=0x104, y=-15, z=-1603, x=-795, galaxy=0, planet=0
UA_PLANET_0 = 0x11200F19BDCE5
# 同一地址把行星位改成 3 → 门地址第一位变 3
UA_PLANET_3 = UA_PLANET_0 | (3 << 52)
GLYPHS_PLANET_3 = "3112F19BDCE5"


def _fake_pet(**overrides) -> dict:
    pet = {
        "CreatureID": "^TREX",
        "CustomName": "^Apex",
        "CreatureType": {"CreatureType": "^Predator"},
        "Biome": {"Biome": "^Lush"},
        "Descriptors": ["^_BODY_REX", "^_HEAD_REX", "^_SHAPE_XRARE", "1234567890"],
        "CreatureSeed": [False, "0x1111"],
        "SpeciesSeed": [False, "0xABCD"],
        "GenusSeed": [False, "0xEF"],
        "UA": f"0x{UA_PLANET_3:X}",
        "Scale": 1.5,
        "Trust": 3,
        "Traits": [1, 2],
    }
    pet.update(overrides)
    return pet


# ---------------------------------------------------------------- UA → origin → glyphs


def test_origin_and_glyphs_from_companion_ua():
    entry = creature.companion_entry(_fake_pet(), 4)
    assert entry is not None
    origin = entry["origin"]
    assert origin == {
        "galaxy": 0,
        "galaxy_name": "Euclid",
        "system": 0x112,
        "planet": 3,
        "voxel_x": -795,
        "voxel_y": -15,
        "voxel_z": -1603,
        "ua": f"0x{UA_PLANET_3:X}",
    }
    assert entry["glyphs"] == GLYPHS_PLANET_3
    assert entry["glyphs"][0] == "3"


def test_planet_zero_degrades_to_no_glyphs_but_keeps_origin():
    entry = creature.companion_entry(_fake_pet(UA=f"0x{UA_PLANET_0:X}"))
    assert entry["origin"]["planet"] == 0
    assert entry["glyphs"] is None
    assert "行星位为 0" in pets_mod.pet_detail_text(entry)


def test_missing_and_invalid_ua_never_invent_defaults():
    for raw in (None, "", 0, "0x0", "not-a-ua", "0xZZ"):
        entry = creature.companion_entry(_fake_pet(UA=raw))
        assert entry["origin"] is None
        assert entry["glyphs"] is None
        assert entry["ua"] == 0


def test_origin_for_ua_accepts_int_and_hex_string():
    a = creature.origin_for_ua(UA_PLANET_3)
    b = creature.origin_for_ua(f"0x{UA_PLANET_3:X}")
    assert a == b
    assert a["system"] == 0x112 and a["planet"] == 3


# ---------------------------------------------------------------- 字段推导


def test_species_key_uses_existing_fields_and_records_source():
    entry = creature.companion_entry(_fake_pet())
    assert entry["species_key"] == "TREX|0xABCD"
    assert entry["species_key_source"] == "CreatureID + SpeciesSeed"

    no_species = creature.companion_entry(
        _fake_pet(SpeciesSeed=[False, "0x0"], GenusSeed=[False, "0xBEEF"]))
    assert no_species["species_key"] == "TREX|0xBEEF"
    assert "GenusSeed" in no_species["species_key_source"]

    bare = creature.companion_entry(
        _fake_pet(SpeciesSeed=[False, "0x0"], GenusSeed=[False, "0x0"]))
    assert bare["species_key"] == "TREX"
    assert "为空" in bare["species_key_source"]


def test_descriptor_groups_and_unique_id_are_split():
    entry = creature.companion_entry(_fake_pet())
    assert entry["unique_id"] == "1234567890"
    assert entry["descriptors"] == [
        "_BODY_REX", "_HEAD_REX", "_SHAPE_XRARE", "1234567890"]
    assert entry["descriptor_groups"] == {
        "BODY": [{"id": "_BODY_REX", "rarity": False}],
        "HEAD": [{"id": "_HEAD_REX", "rarity": False}],
        "SHAPE": [{"id": "_SHAPE_XRARE", "rarity": True}],
    }


def test_empty_descriptors_do_not_invent_groups():
    entry = creature.companion_entry(_fake_pet(Descriptors=[]))
    assert entry["descriptor_groups"] == {}
    assert entry["unique_id"] is None


# ---------------------------------------------------------------- 界面：按钮与文案


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class FakeServices:
    """只实现 PetsView 用到的服务；记录 warp 调用，绝不创建 AgentClient。"""

    def __init__(self, result: dict | None = None, error: Exception | None = None,
                 planet_result: dict | None = None,
                 planet_error: Exception | None = None):
        self.result = result if result is not None else {"ok": True, "confirmed": True}
        self.error = error
        self.planet_result = planet_result if planet_result is not None else {
            "ok": True, "count": 2, "fauna": [
                {"name": "动物甲", "creature_seed": "0xA1", "discoverer": "旅行者"},
                {"name": "动物乙", "creature_seed": "0xB2", "discoverer": ""},
            ], "reason": None}
        self.planet_error = planet_error
        self.warp_calls: list[dict] = []
        self.planet_calls: list[dict] = []

    def warp_portal(self, glyphs: str, galaxy: int | None = None,
                    stage: str = "prepare_warp") -> dict:
        self.warp_calls.append({"glyphs": glyphs, "galaxy": galaxy, "stage": stage})
        if self.error is not None:
            raise self.error
        return dict(self.result)

    def companion_planet(self, companion, path: str | None = None) -> dict:
        self.planet_calls.append({"companion": companion, "path": path})
        if self.planet_error is not None:
            raise self.planet_error
        return dict(self.planet_result)


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

        monkeypatch.setattr(pets_mod.notify, name, record)
    return captured


def _accept_confirm(monkeypatch, answer=None) -> list[dict]:
    from PySide6.QtWidgets import QMessageBox

    seen: list[dict] = []

    def warn(parent, title, text, *args, **kwargs):
        seen.append({"title": title, "text": text})
        return QMessageBox.Yes if answer is None else answer

    monkeypatch.setattr(pets_mod.QMessageBox, "warning", staticmethod(warn))
    return seen


def _make_view(monkeypatch, svc: FakeServices, pet: dict):
    monkeypatch.setattr(pets_mod, "run_worker", _sync_worker)
    view = pets_mod.PetsView(svc)
    view._render({"creatures": [pet], "_roles": {"count": 1}})
    view.show()
    return view


def test_source_column_and_detail_show_ua_and_glyphs(qapp, monkeypatch):
    pet = creature.companion_entry(_fake_pet())
    view = _make_view(monkeypatch, FakeServices(), pet)
    assert view.table.item(0, 4).text() == "Euclid · 行星 #3"
    detail = view.detail_label.text()
    assert f"UA：0x{UA_PLANET_3:X}" in detail
    assert f"符文：{GLYPHS_PLANET_3}" in detail
    assert view.warp_btn.isEnabled() is True
    assert view.copy_glyph_btn.isEnabled() is True


def test_warp_and_copy_disabled_without_valid_glyphs(qapp, monkeypatch):
    pet = creature.companion_entry(_fake_pet(UA=f"0x{UA_PLANET_0:X}"))
    view = _make_view(monkeypatch, FakeServices(), pet)
    assert view.table.item(0, 4).text() == "Euclid · 行星未知"
    assert view.warp_btn.isEnabled() is False
    assert view.copy_glyph_btn.isEnabled() is False
    assert "行星位为 0" in view.detail_label.text()


def test_success_wording_and_service_call(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    confirmed = _accept_confirm(monkeypatch)
    svc = FakeServices({"ok": True, "confirmed": True})
    view = _make_view(monkeypatch, svc, creature.companion_entry(_fake_pet()))

    view._warp_selected()

    assert svc.warp_calls == [
        {"glyphs": GLYPHS_PLANET_3, "galaxy": 0, "stage": "prepare_warp"}]
    assert "已传送到来源星球：Euclid · 行星 #3" in view.status.text()
    assert captured["success"][-1].startswith("已传送到来源星球")
    assert captured["error"] == []
    assert "调用游戏内传送门机制，失败可用「还原」回滚" in confirmed[0]["text"]
    assert GLYPHS_PLANET_3 in confirmed[0]["text"]
    assert view.warp_btn.isEnabled() is True


def test_unconfirmed_wording_is_distinct(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    _accept_confirm(monkeypatch)
    svc = FakeServices({"ok": True, "confirmed": False,
                        "confirm_error": "40 秒内未读回目标位置"})
    view = _make_view(monkeypatch, svc, creature.companion_entry(_fake_pet()))

    view._warp_selected()

    assert "传送未确认" in view.status.text()
    assert "命令已执行；失败可用「还原」回滚" in view.status.text()
    assert captured["warn"][-1].startswith("传送未确认")
    assert captured["success"] == []


def test_build_unverified_failure_mentions_settings(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    _accept_confirm(monkeypatch)
    svc = FakeServices({"ok": False, "code": "E_BUILD_UNVERIFIED",
                        "error": "这版未验证：高风险写操作已禁用"})
    view = _make_view(monkeypatch, svc, creature.companion_entry(_fake_pet()))

    view._warp_selected()

    message = view.status.text()
    assert message.startswith("传送失败：")
    assert "E_BUILD_UNVERIFIED" in message
    assert "这版未验证：高风险写操作已禁用" in message
    assert "需要先开启实验写入开关" in message
    assert "设置页" in message
    assert captured["success"] == []
    assert captured["error"][-1] == message


def test_cancel_does_not_call_service(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _capture_notify(monkeypatch)
    _accept_confirm(monkeypatch, QMessageBox.No)
    svc = FakeServices()
    view = _make_view(monkeypatch, svc, creature.companion_entry(_fake_pet()))

    view._warp_selected()

    assert svc.warp_calls == []
    assert view.status.text() == "已取消传送。"


def test_warp_never_uses_real_agent_client(qapp, monkeypatch):
    from starforge.services import Services

    def boom(_self):
        raise AssertionError("不应调用真实 AgentClient")

    monkeypatch.setattr(Services, "agent_client", boom)
    _capture_notify(monkeypatch)
    _accept_confirm(monkeypatch)
    svc = FakeServices({"ok": True, "confirmed": True})
    view = _make_view(monkeypatch, svc, creature.companion_entry(_fake_pet()))

    view._warp_selected()

    assert svc.warp_calls and svc.warp_calls[0]["glyphs"] == GLYPHS_PLANET_3


# ---------------------------------------------------------------- 船队右栏联查

def _make_panel(monkeypatch, svc: FakeServices, pet: dict):
    """同步 worker + 真实 PetsView 绑定，验证右栏详情与列表动作共用一套逻辑。"""
    monkeypatch.setattr(companion_mod, "run_worker", _sync_worker)
    view = _make_view(monkeypatch, svc, pet)
    panel = companion_mod.FleetCompanionPanel(svc)
    panel.bind_pets(view)
    panel.set_path("/tmp/save.hg")
    panel.set_creature(pet)
    return panel, view


def test_panel_shows_origin_glyphs_and_fauna(qapp, monkeypatch):
    pet = creature.companion_entry(_fake_pet())
    svc = FakeServices()
    panel, view = _make_panel(monkeypatch, svc, pet)

    assert panel.source_label.text() == "来源行星：Euclid · 行星 #3"
    assert panel.glyph_label.text() == f"符文：{GLYPHS_PLANET_3}"
    facts = panel.detail_label.text()
    assert not any(line.startswith(("来源：", "符文："))
                   for line in facts.splitlines())
    assert f"UA：0x{UA_PLANET_3:X}" in facts
    assert panel.fauna_state == "ok"
    text = panel.fauna_label.text()
    assert "该行星动物（前 2/2 条）" in text
    assert "动物甲" in text and "动物乙" in text
    assert view.warp_btn.isEnabled() is True
    assert svc.planet_calls and svc.planet_calls[0]["path"] == "/tmp/save.hg"

    # 复制/传送动作由右栏按钮触发，但复用列表视图的确认与风险文案。
    panel.copy_btn.click()
    assert GLYPHS_PLANET_3 in panel.status_label.text()


def test_panel_fauna_empty_state(qapp, monkeypatch):
    svc = FakeServices(planet_result={
        "ok": True, "count": 0, "fauna": [],
        "reason": "没有找到该行星的动物发现记录"})
    panel, _ = _make_panel(monkeypatch, svc, creature.companion_entry(_fake_pet()))

    assert panel.fauna_state == "empty"
    assert "暂无动物记录" in panel.fauna_label.text()
    assert panel.retry_btn.isHidden() is False


def test_panel_fauna_error_state(qapp, monkeypatch):
    svc = FakeServices(planet_result={
        "ok": False, "count": 0, "fauna": [], "reason": "读取存档失败：坏文件"})
    panel, _ = _make_panel(monkeypatch, svc, creature.companion_entry(_fake_pet()))

    assert panel.fauna_state == "error"
    assert "联查失败" in panel.fauna_label.text()
    assert "坏文件" in panel.fauna_label.text()
    assert panel.retry_btn.isHidden() is False


def test_panel_fauna_loading_state_is_visible(qapp, monkeypatch):
    svc = FakeServices()
    pet = creature.companion_entry(_fake_pet())
    view = _make_view(monkeypatch, svc, pet)
    monkeypatch.setattr(companion_mod, "run_worker", lambda *a, **k: None)
    panel = companion_mod.FleetCompanionPanel(svc)
    panel.bind_pets(view)
    panel.set_creature(pet)

    assert panel.fauna_state == "loading"
    assert "正在联查" in panel.fauna_label.text()
    assert panel.retry_btn.isHidden() is True


def test_panel_warp_uses_confirm_and_risk_copy(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    confirmed = _accept_confirm(monkeypatch)
    svc = FakeServices({"ok": True, "confirmed": True})
    panel, _ = _make_panel(monkeypatch, svc, creature.companion_entry(_fake_pet()))

    panel.warp_btn.click()

    assert svc.warp_calls == [
        {"glyphs": GLYPHS_PLANET_3, "galaxy": 0, "stage": "prepare_warp"}]
    assert "调用游戏内传送门机制，失败可用「还原」回滚" in confirmed[0]["text"]
    assert "已传送到来源星球" in panel.status_label.text()
    assert captured["success"][-1].startswith("已传送到来源星球")


def test_panel_without_glyphs_disables_actions_and_skips_lookup(qapp, monkeypatch):
    svc = FakeServices()
    pet = creature.companion_entry(_fake_pet(UA=f"0x{UA_PLANET_0:X}"))
    panel, _ = _make_panel(monkeypatch, svc, pet)

    assert "行星未知" in panel.source_label.text()
    assert panel.copy_btn.isEnabled() is False
    assert panel.warp_btn.isEnabled() is False
    assert panel.fauna_state == "empty"
    assert svc.planet_calls == []
