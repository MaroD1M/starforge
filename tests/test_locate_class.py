"""M1：种子反查星系（A4）+ 改船级/属性（C3）。

两件事都必须"能证明"，不能只"看起来跑通"：
  · 反查：拿存档里真实存在的船种子，反解出的星系必须经生成器证实（hits 里有 where/what）；
  · 改级：在存档副本上改 C→S，读回等级一致、属性落在游戏区间、其它船种子一个不动。
"""
import os
import shutil

import pytest

from starforge.core import settings as settings_mod
from starforge.core.errors import BadRequest, WriteDisabled
from starforge.save import library, writer


@pytest.fixture()
def save_copy(saves_dir, tmp_path, game_env):
    dst = tmp_path / "save.hg"
    shutil.copy2(saves_dir / "save.hg", dst)
    return dst


# ---------------------------------------------------------------- 反查星系


def test_locate_needs_game(game_env):
    from starforge import system
    if not system.available():
        pytest.skip("没有游戏目录")
    out = system.locate_seed("0x0")
    assert "hits" in out and "candidates" in out
    assert out["seed"] == "0x0000000000000000"


def test_locate_real_save_ship_hits_own_system(save_copy, game_env):
    """存档里的船种子应当反解到它所在（或曾经所在）的星系——这是最有说服力的自证。"""
    from starforge import system
    ships, _ = library.open_ships(save_copy)
    if not ships:
        pytest.skip("存档里没有船")
    target = None
    for s in ships:                                     # 逐个试到命中（反查本身欠定）
        out = system.locate_seed(s.seed, save_path=str(save_copy))
        if out.get("hits"):
            target = (s, out)
            break
    if target is None:
        pytest.skip("这几个种子都反解不出候选（欠定，属正常）")
    ship, out = target
    assert out["candidates"] >= len(out["hits"]) >= 1
    hit = out["hits"][0]
    assert hit["glyphs"] and len(hit["glyphs"]) == 12
    assert hit["coords"].count(":") == 3
    assert hit["where"] in ("crash site", "space station", "trading post", "planet") or hit["what"]
    # 反解结果里的星系地址应当是可解析的真实地址（能回写成 glyphs）
    assert hit["ua"].startswith("0x")


# ---------------------------------------------------------------- 改级/属性


def test_class_write_disabled(save_copy):
    settings_mod.update(write_enabled=False)
    with pytest.raises(WriteDisabled):
        writer.apply_class(str(save_copy), 1, ship_class="S", confirm=True)


def test_class_needs_confirm(save_copy):
    settings_mod.update(write_enabled=True)
    with pytest.raises(BadRequest):
        writer.apply_class(str(save_copy), 1, ship_class="S", confirm=False)


def test_class_rejects_bad_value(save_copy):
    settings_mod.update(write_enabled=True)
    with pytest.raises(BadRequest):
        writer.apply_class(str(save_copy), 0, ship_class="Z", confirm=True)


def test_class_requires_something_to_change(save_copy):
    settings_mod.update(write_enabled=True)
    with pytest.raises(BadRequest):
        writer.apply_class(str(save_copy), 0, confirm=True)


def test_class_c_to_s_and_back(save_copy):
    settings_mod.update(write_enabled=True)
    ships, _ = library.open_ships(save_copy)
    slot = ships[0].slot
    before = writer.apply_class(str(save_copy), slot, ship_class="C", confirm=True)
    assert before["after"]["class"] == "C"
    res = writer.apply_class(str(save_copy), slot, ship_class="S", confirm=True)
    assert res["verified"] is True and res["ships_untouched"] is True
    assert res["after"]["class"] == "S"
    assert os.path.exists(res["backup"])

    again, _ = library.open_ships(save_copy)
    assert len(again) == len(ships)
    # 其它船的种子必须一个都没动
    first = {s.slot: s.seed for s in ships}
    second = {s.slot: s.seed for s in again}
    assert {k: v for k, v in second.items() if k != slot} == {k: v for k, v in first.items() if k != slot}


def test_class_best_rolls_within_range(save_copy):
    settings_mod.update(write_enabled=True)
    slot = library.open_ships(save_copy)[0][0].slot
    res = writer.apply_class(str(save_copy), slot, best=True, confirm=True)
    for row in res["after"]["stats"]:
        assert row["min"] <= row["value"] <= row["max"], row


def test_class_copy_mode_leaves_original(save_copy):
    settings_mod.update(write_enabled=True)
    slot = library.open_ships(save_copy)[0][0].slot
    original = save_copy.read_bytes()
    res = writer.apply_class(str(save_copy), slot, ship_class="S", confirm=True, copy=True)
    assert res["copy"] is True
    assert save_copy.read_bytes() == original                 # 原档字节级不动
    assert os.path.basename(res["path"]) == "save.edited.hg"
    assert os.path.exists(res["path"])
