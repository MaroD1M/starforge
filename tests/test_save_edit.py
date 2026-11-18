"""存档安全编辑服务：货币 / 改名 / 涂装 / 失败回滚 / copy 模式。

全部在真实存档的临时副本上做；没有存档样本时整组跳过。
"""
import os
import shutil

import pytest

from starforge.core import settings as settings_mod
from starforge.core.errors import BadRequest, WriteDisabled, WriteRefused
from starforge.save import library
from starforge.services import save_edit


@pytest.fixture()
def save_copy(saves_dir, tmp_path, game_env):
    src = saves_dir / "save.hg"
    dst = tmp_path / "save.hg"
    shutil.copy2(src, dst)
    return dst


def _paint_slot(save_copy) -> int:
    ships, _ = library.open_ships(save_copy)
    slot = next((s.slot for s in ships if s.slot < 12), None)
    if slot is None:
        pytest.skip("存档里没有 0–11 范围内可涂装的船")
    return slot


def test_write_disabled_refused(save_copy):
    settings_mod.update(write_enabled=False)
    with pytest.raises(WriteDisabled):
        save_edit.apply_currencies(str(save_copy), units=1, confirm=True)


def test_needs_confirm(save_copy):
    settings_mod.update(write_enabled=True)
    with pytest.raises(BadRequest):
        save_edit.apply_currencies(str(save_copy), units=1, confirm=False)


def test_currencies_roundtrip(save_copy):
    settings_mod.update(write_enabled=True)
    before = save_edit.currencies(str(save_copy))
    wanted = {"units": 123_456_789, "nanites": 98_765, "quicksilver": 4_321}

    res = save_edit.apply_currencies(str(save_copy), confirm=True, **wanted)

    assert res["verified"] is True
    assert res["copy"] is False
    assert res["before"] == before
    assert res["after"] == wanted
    assert os.path.exists(res["backup"])
    assert save_edit.currencies(str(save_copy)) == wanted

    # 只改指定的一项：其它货币保持原值
    only_units = save_edit.apply_currencies(str(save_copy), units=777, confirm=True)
    assert only_units["after"]["units"] == 777
    assert only_units["after"]["nanites"] == wanted["nanites"]
    assert only_units["after"]["quicksilver"] == wanted["quicksilver"]


def test_ship_rename_only_touches_target(save_copy):
    settings_mod.update(write_enabled=True)
    ships, _ = library.open_ships(save_copy)
    slot = ships[0].slot
    old_names = {s.slot: s.name for s in ships}
    new_name = "星铸测试船"

    res = save_edit.apply_ship_name(str(save_copy), slot, new_name, confirm=True)

    assert res["verified"] is True
    assert res["before"] == old_names[slot]
    assert res["after"] == new_name
    assert os.path.exists(res["backup"])
    assert save_edit.ship_meta(str(save_copy), slot)["name"] == new_name
    after, _ = library.open_ships(save_copy)
    for ship in after:
        if ship.slot != slot:
            assert ship.name == old_names[ship.slot]


def test_ship_paint_writes_and_keeps_others(save_copy):
    settings_mod.update(write_enabled=True)
    slot = _paint_slot(save_copy)
    others_before = {s.slot: save_edit.ship_meta(str(save_copy), s.slot)
                     for s in library.open_ships(save_copy)[0] if s.slot != slot}

    res = save_edit.apply_ship_paint(
        str(save_copy), slot, primary=(0.9, 0.1, 0.05), accent=(0.05, 0.1, 0.9),
        confirm=True)

    assert res["verified"] is True
    assert res["after"] is not None
    assert res["after"]["palette"] == "FREIGHTER"
    meta = save_edit.ship_meta(str(save_copy), slot)
    assert meta["paint"]["palette"] == "FREIGHTER"
    assert meta["paint"]["primary"] == res["after"]["primary"]
    for s in library.open_ships(save_copy)[0]:
        if s.slot != slot:
            assert save_edit.ship_meta(str(save_copy), s.slot) == others_before[s.slot]


def test_failed_verification_rolls_back_bytes(save_copy, monkeypatch):
    settings_mod.update(write_enabled=True)
    original_bytes = save_copy.read_bytes()
    ships, _ = library.open_ships(save_copy)
    slot = ships[0].slot

    from nms_save import ships as nms_ships
    real_set = nms_ships.set_ship_name

    def liar(tree, index, name):
        real_set(tree, index, "写错的名字")

    monkeypatch.setattr(nms_ships, "set_ship_name", liar)
    with pytest.raises(WriteRefused) as e:
        save_edit.apply_ship_name(str(save_copy), slot, "预期的名字", confirm=True)

    assert "回滚" in str(e.value)
    assert save_copy.read_bytes() == original_bytes


def test_copy_mode_leaves_original_untouched(save_copy):
    settings_mod.update(write_enabled=True)
    before = save_edit.currencies(str(save_copy))
    original_bytes = save_copy.read_bytes()

    res = save_edit.apply_currencies(str(save_copy), units=42, confirm=True, copy=True)

    assert res["copy"] is True
    assert res["path"].endswith(".edited.hg")
    assert res["original"] == str(save_copy)
    assert os.path.exists(res["path"])
    assert os.path.exists(res["backup"])
    assert save_copy.read_bytes() == original_bytes
    assert save_edit.currencies(str(save_copy)) == before
    edited = save_edit.currencies(res["path"])
    assert edited["units"] == 42
