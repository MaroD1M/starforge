"""船队只读扩展与存档扩展编辑：纯格式逻辑 + 真实存档临时副本。"""
from __future__ import annotations

import shutil

import pytest

from starforge.app.dialogs.save_extras import (
    inventory_rows,
    knowledge_rows,
    quest_rows,
    reward_rows,
    words_text,
)
from starforge.app.pages.fleet import (
    freighter_rows,
    frigate_rows,
    multitool_rows,
)
from starforge.core import settings as settings_mod
from starforge.core.errors import BadRequest, WriteDisabled
from starforge.save import extras as save_extras
from starforge.save import library
from starforge.services import get_services

# ---------------------------------------------------------------- 纯格式


def test_frigate_rows_keep_confirmed_fields():
    rows = frigate_rows([{
        "name": "星尘号", "type": "Combat", "class": "A",
        "stats": {"Combat": 30, "Exploration": 12, "Mining": 8, "Diplomacy": 4,
                  "Fuel burn rate": 2, "Speed": 110},
        "expeditions": 7, "damaged": True, "seed": "0xABC",
    }])
    assert rows == [["星尘号", "Combat", "A", "30", "12", "8", "4", "2", "110",
                     "7", "受损", "0xABC"]]


def test_multitool_and_freighter_rows_are_read_only_safe():
    assert multitool_rows([{"name": "主工具", "class": "S", "model": "Rifle",
                            "slots": 24, "seed": "0x1", "active": True}]) == [
        ["主工具", "S", "Rifle", "24", "0x1", "是"]]
    assert multitool_rows(None) == []
    rows = freighter_rows({"filename": "MODELS/X/FREIGHTER_PROC.SCENE.MBIN",
                           "seed": "0x2", "home": "0x3"})
    assert ["型号", "FREIGHTER_PROC.SCENE.MBIN"] in rows
    assert ["种子", "0x2"] in rows
    assert freighter_rows(None)[0] == ["型号", "—"]


def test_save_extra_table_formatters():
    rows = inventory_rows({"slots": [
        {"x": 1, "y": 0, "name": "铁", "id": "^FE", "amount": 250,
         "max": 9999, "type": "Substance", "damaged": False},
        {"x": 0, "y": 0, "name": "护盾", "id": "^SHIELD", "amount": 1,
         "max": 1, "type": "Technology", "damaged": True},
    ]})
    assert rows[0][0] == "0,0" and rows[0][6] == "损坏"
    assert rows[1][0] == "1,0" and rows[1][1] == "铁"
    assert knowledge_rows({"groups": [{"group": "tech", "label": "科技",
                                       "known": 3, "total": 9}]}) == [["科技", "3", "9"]]
    assert words_text({"words": {"Gek": [2, 5]}}) == "Gek 2/5"
    assert quest_rows({"quests": [{"title": "任务", "step": "步骤",
                                   "status": "done", "key": "A|1"}]}) == [
        ["任务", "步骤", "已完成", "A|1"]]
    assert reward_rows({"items": [{"id": "EXPD_X", "name": "奖励",
                                   "unlocked": True, "redeemed": False}]}) == [
        ["奖励", "EXPD_X", "是", "否"]]


# ---------------------------------------------------------------- 真实存档


@pytest.fixture()
def save_copy(saves_dir, tmp_path):
    src = saves_dir / "save.hg"
    dst = tmp_path / "save.hg"
    shutil.copy2(src, dst)
    return dst


def test_fleet_extras_reads_real_save(saves_dir):
    res = get_services().fleet_extras(str(saves_dir / "save.hg"))
    assert res["ok"] is True
    assert res["available"]["frigates"] and res["available"]["multitools"]
    assert isinstance(res["frigates"], list)
    assert isinstance(res["multitools"], list)
    assert res["errors"] == {}


def test_fleet_extras_rejects_non_player(saves_dir):
    from starforge.core.errors import SaveFormatError
    with pytest.raises(SaveFormatError):
        get_services().fleet_extras(str(saves_dir / "accountdata.hg"))


def test_inventory_write_needs_write_and_confirm(save_copy):
    settings_mod.update(write_enabled=False)
    with pytest.raises(WriteDisabled):
        save_extras.apply_inventory(str(save_copy), "Inventory", "fill", confirm=True)
    settings_mod.update(write_enabled=True)
    with pytest.raises(BadRequest):
        save_extras.apply_inventory(str(save_copy), "Inventory", "fill", confirm=False)


def test_inventory_repair_and_fill_roundtrip(save_copy):
    settings_mod.update(write_enabled=True)
    invs = save_extras.inventories(str(save_copy))["inventories"]
    target = next(i for i in invs if i["path"] == "Inventory")
    res = save_extras.apply_inventory(str(save_copy), target["path"], "fill", confirm=True)
    assert res["verified"] is True
    after = save_extras.inventory(str(save_copy), target["path"])
    stacks = [s for s in after["slots"] if s["type"] != "Technology"]
    assert stacks and all(s["amount"] == s["max"] for s in stacks)


def test_words_learn_specific_race(save_copy, game_env):
    settings_mod.update(write_enabled=True)
    res = save_extras.apply_words(str(save_copy), ["Gek"], confirm=True)
    assert res["verified"] is True
    words = save_extras.knowledge(str(save_copy))["words"]
    assert words["Gek"][0] == words["Gek"][1]


def test_rewards_unlock_selected(save_copy, game_env):
    settings_mod.update(write_enabled=True)
    payload = save_extras.rewards(str(save_copy), group="expedition")
    locked = [r for r in payload["items"] if not r["unlocked"]]
    if not locked:
        pytest.skip("这个存档的远征奖励已全部解锁")
    target = locked[0]["id"]
    res = save_extras.apply_rewards(str(save_copy), "expedition", [target],
                                    unlock=True, confirm=True)
    assert res["verified"] is True
    after = save_extras.rewards(str(save_copy), group="expedition", query=target)["items"]
    assert after and after[0]["unlocked"] is True


def test_quests_read_and_skip_one(save_copy, game_env):
    settings_mod.update(write_enabled=True)
    rows = save_extras.quests(str(save_copy))["quests"]
    if not rows:
        pytest.skip("这个存档没有任务")
    pending = next((q for q in rows if q["status"] != "done" and q.get("final") is not None),
                   None)
    if pending is None:
        pytest.skip("没有可完成的任务")
    res = save_extras.apply_skip_quests(str(save_copy), [pending["key"]], confirm=True)
    assert res["verified"] is True
    after = {q["key"]: q for q in save_extras.quests(str(save_copy))["quests"]}
    assert after[pending["key"]]["status"] == "done"


def test_design_write_needs_confirm(save_copy):
    settings_mod.update(write_enabled=True)
    with pytest.raises(BadRequest):
        get_services().apply_design(str(save_copy), "fighter", "0x1",
                                    slot="new", confirm=False)


def test_design_write_replaces_existing_slot_in_copy(save_copy, game_env):
    settings_mod.update(write_enabled=True)
    from starforge.data.shipref import PROC_MODELS

    ships, _ = library.open_ships(save_copy)
    target = next((s for s in ships if s.slot < 12 and s.type in PROC_MODELS),
                  None)
    if target is None:
        pytest.skip("存档里没有可写回的程序化飞船")
    original = save_copy.read_bytes()
    res = get_services().apply_design(
        str(save_copy), target.type, target.seed, slot=target.slot,
        name="设计写回测试", confirm=True, copy=True)
    assert res["verified"] is True
    assert res["copy"] is True
    assert res["after"]["slot"] == target.slot
    assert res["after"]["seed"].upper() == target.seed.upper()
    assert save_copy.read_bytes() == original
    assert res["path"].endswith(".edited.hg")
