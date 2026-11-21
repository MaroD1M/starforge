"""writer 的 copy=True 路径：传入 `.edited.hg` 时不得"自己复制自己"。

历史缺陷：`apply_seed` / `apply_class` 在 `save_path` 已经以 `.edited.hg` 结尾时
仍然调用 `shutil.copy2(original_path, save_path)`，在 Windows 上抛 SameFileError。
这里全部在 tmp_path 的存档副本上验证：连续两次 copy=True 写回同一个 `.edited.hg`
都应成功，且原 `save.hg` 字节不变。

本机 NMS.exe 可能正在运行，所以测试内把 `writer.game_running` 打桩成 False；
只影响本文件，不碰 conftest，也不写真实存档。
"""
import shutil

import pytest

from starforge.core import settings as settings_mod
from starforge.data.shipref import ShipRef
from starforge.save import library, writer


@pytest.fixture()
def save_copy(saves_dir, tmp_path, monkeypatch):
    """真实 save.hg 的临时副本；同时让 writer 认为游戏没在运行。"""
    dst = tmp_path / "save.hg"
    shutil.copy2(saves_dir / "save.hg", dst)
    monkeypatch.setattr(writer, "game_running", lambda: False)
    settings_mod.update(write_enabled=True)
    return dst


@pytest.fixture()
def edited_copy(save_copy):
    """已经存在的 `.edited.hg`，用来模拟"上一次 copy=True 留下的副本"。"""
    dst = save_copy.with_name("save.edited.hg")
    shutil.copy2(save_copy, dst)
    return dst


def _previewable_ship(save_path):
    ships, _ = library.open_ships(save_path)
    if not ships:
        pytest.skip("存档里没有船")
    target = next((s for s in ships if s.can_preview), ships[0])
    return target


def _classed_ship(save_path):
    """挑一艘原始存档里明确带等级的船；没有就跳过。"""
    ships, _ = library.open_ships(save_path)
    for ship in ships:
        if ship.ship_class:
            return ship, ship.ship_class
    pytest.skip("存档里没有带等级的船")


def _assert_seed(save_path, slot, expected_seed, label):
    parsed, _ = library.open_ships(save_path)
    got = next((s for s in parsed if s.slot == slot), None)
    assert got is not None, f"{label}：写回后存档里找不到槽位 {slot}（文件可能已损坏）"
    assert got.seed.upper() == expected_seed.upper(), (
        f"{label}：槽位 {slot} 的种子是 {got.seed}，预期 {expected_seed}")


def test_apply_seed_twice_on_edited_does_not_self_copy(save_copy, edited_copy):
    """连续两次 copy=True 写回同一个 .edited.hg：都成功、可再解析、原档字节不动。"""
    target = _previewable_ship(save_copy)
    original_bytes = save_copy.read_bytes()
    # 两次用不同种子，确保第二次确实又写了一遍，而不是读到缓存。
    wanted_seeds = ("0x0123456789ABCDEF", "0xFEDCBA9876543210")

    for attempt, wanted in enumerate(wanted_seeds, start=1):
        source = ShipRef(type=target.type, seed=wanted)
        res = writer.apply_seed(str(edited_copy), target.slot, source,
                                confirm=True, copy=True)
        assert res["verified"] is True, f"第 {attempt} 次写回未通过校验：{res!r}"
        assert res["copy"] is True, f"第 {attempt} 次写回的结果丢了 copy=True：{res!r}"
        assert res["path"] == str(edited_copy), (
            f"第 {attempt} 次写回应直接写回 {edited_copy}，实际路径是 {res['path']}")
        _assert_seed(edited_copy, target.slot, wanted, f"apply_seed 第 {attempt} 次写回")
        assert save_copy.read_bytes() == original_bytes, (
            f"apply_seed 第 {attempt} 次写回后原档 save.hg 的字节被改动了")


def test_apply_class_twice_on_edited_does_not_self_copy(save_copy, edited_copy):
    """apply_class 的 copy=True 同类路径：已有 .edited.hg 时原地写，不自己复制自己。"""
    target, original_class = _classed_ship(save_copy)
    original_bytes = save_copy.read_bytes()
    # 换一个等级再换回来，两次都走同一条 copy=True 路径。
    wanted_classes = ("A", "S") if original_class != "A" else ("S", "A")

    for attempt, wanted_class in enumerate(wanted_classes, start=1):
        res = writer.apply_class(str(edited_copy), target.slot, ship_class=wanted_class,
                                 confirm=True, copy=True)
        assert res["verified"] is True, f"第 {attempt} 次改级未通过校验：{res!r}"
        assert res["ships_untouched"] is True, (
            f"第 {attempt} 次改级后其它船的种子被改动了：{res!r}")
        assert res["copy"] is True, f"第 {attempt} 次改级的结果丢了 copy=True：{res!r}"
        assert res["path"] == str(edited_copy), (
            f"第 {attempt} 次改级应直接写回 {edited_copy}，实际路径是 {res['path']}")
        assert res["after"]["class"] == wanted_class, (
            f"第 {attempt} 次改级后读到等级 {res['after']['class']}，预期 {wanted_class}")
        assert save_copy.read_bytes() == original_bytes, (
            f"apply_class 第 {attempt} 次写回后原档 save.hg 的字节被改动了")
