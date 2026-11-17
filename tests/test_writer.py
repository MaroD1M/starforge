"""F05 写回存档：备份 / 原子写 / 读回校验 / 回滚 / 跨型拒绝。全部在**存档副本**上做。"""
import os
import shutil

import pytest

from starforge.core import settings as settings_mod
from starforge.core.errors import BadRequest, WriteDisabled, WriteRefused
from starforge.data.shipref import ShipRef
from starforge.save import library, writer


@pytest.fixture()
def save_copy(saves_dir, tmp_path, game_env):
    src = saves_dir / "save.hg"
    dst = tmp_path / "save.hg"
    shutil.copy2(src, dst)
    return dst


def test_write_disabled_is_403(save_copy):
    settings_mod.update(write_enabled=False)
    with pytest.raises(WriteDisabled):
        writer.apply_seed(str(save_copy), 1, ShipRef(type="sentinel", seed="0x992C8A47F60A6B10"), confirm=True)


def test_needs_confirm(save_copy):
    settings_mod.update(write_enabled=True)
    with pytest.raises(BadRequest):
        writer.apply_seed(str(save_copy), 1, ShipRef(type="sentinel", seed="0x992C8A47F60A6B10"), confirm=False)


def test_cross_type_refused(save_copy):
    settings_mod.update(write_enabled=True)
    ships, _ = library.open_ships(save_copy)
    other = next(s for s in ships if s.type != "sentinel")
    with pytest.raises(BadRequest) as e:
        writer.apply_seed(str(save_copy), other.slot, ShipRef(type="sentinel", seed="0x992C8A47F60A6B10"), confirm=True)
    assert "跨型" in str(e.value)


def test_apply_same_type_writes_and_verifies(save_copy):
    settings_mod.update(write_enabled=True)
    before, _ = library.open_ships(save_copy)
    target_slot = next(s.slot for s in before if s.type == "sentinel")
    src = ShipRef(type="sentinel", seed="0x1111222233334444")

    res = writer.apply_seed(str(save_copy), target_slot, src, confirm=True)
    assert res["verified"] is True and res["after"].upper() == "0X1111222233334444"
    assert os.path.exists(res["backup"])

    after, warns = library.open_ships(save_copy)
    assert len(after) == len(before)                      # 船数量不变
    got = next(s for s in after if s.slot == target_slot)  # 槽位是稀疏的，不能按下标取
    assert got.seed.upper() == "0X1111222233334444"
    # 存档里存在固定模型（护卫舰等）是正常的，只要求没有"真正的问题"警告
    assert not [w for w in warns if "无法" in w or "不符" in w]


def test_backup_can_restore(save_copy):
    settings_mod.update(write_enabled=True)
    ships, _ = library.open_ships(save_copy)
    slot = next(s.slot for s in ships if s.type == "sentinel")
    original = next(s for s in ships if s.slot == slot).seed
    res = writer.apply_seed(str(save_copy), slot, ShipRef(type="sentinel", seed="0xAAAABBBBCCCCDDDD"), confirm=True)

    out = writer.restore(str(save_copy), res["backup"], confirm=True)
    assert out["ok"]
    restored, _ = library.open_ships(save_copy)
    assert next(s for s in restored if s.slot == slot).seed.upper() == original.upper()
    assert os.path.exists(out["safety_copy"])


def test_failed_verification_rolls_back(save_copy, monkeypatch):
    settings_mod.update(write_enabled=True)
    original_bytes = save_copy.read_bytes()

    from nms_save import ships as nms_ships
    real_set = nms_ships.set_ship_seed

    def liar(json_tree, index, new_seed):
        real_set(json_tree, index, "0xDEADBEEFDEADBEEF")   # 写进去的和要求的不一样

    monkeypatch.setattr(nms_ships, "set_ship_seed", liar)
    ships, _ = library.open_ships(save_copy)
    slot = next(s.slot for s in ships if s.type == "sentinel")
    with pytest.raises(WriteRefused) as e:
        writer.apply_seed(str(save_copy), slot, ShipRef(type="sentinel", seed="0x1111222233334444"), confirm=True)
    assert "回滚" in str(e.value)
    assert save_copy.read_bytes() == original_bytes       # 字节级还原


def test_backups_listed(save_copy):
    settings_mod.update(write_enabled=True)
    ships, _ = library.open_ships(save_copy)
    slot = next(s.slot for s in ships if s.type == "sentinel")
    writer.apply_seed(str(save_copy), slot, ShipRef(type="sentinel", seed="0x1234"), confirm=True)
    got = writer.backups(str(save_copy))
    assert got and got[0]["path"].endswith(".bak")


def test_apply_to_copy_leaves_original_untouched(save_copy):
    """copy=True：原档一字节不动，改动写在 .edited.hg 上。"""
    settings_mod.update(write_enabled=True)
    ships, _ = library.open_ships(save_copy)
    slot = next(s.slot for s in ships if s.can_preview)
    seed_before = next(s.seed for s in ships if s.slot == slot)
    bytes_before = save_copy.read_bytes()

    res = writer.apply_seed(str(save_copy), slot, ShipRef(type=next(s.type for s in ships if s.slot == slot),
                                                          seed="0xFEDCBA9876543210"),
                            confirm=True, copy=True)
    assert res["copy"] is True and res["path"].endswith(".edited.hg")
    assert save_copy.read_bytes() == bytes_before          # 原档未动
    edited, _ = library.open_ships(res["path"])
    assert next(s for s in edited if s.slot == slot).seed.upper() == "0XFEDCBA9876543210"
    assert next(s for s in ships if s.slot == slot).seed == seed_before
