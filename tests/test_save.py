"""ShipRef 数据模型与存档层测试（用真实存档）。"""
import pytest

from starforge.data.shipref import ShipRef, ShipRefError, PROC_MODELS, coerce
from starforge.save import library


# ---------------------------------------------------------------- ShipRef


def test_seed_normalised():
    r = ShipRef(type="fighter", seed="0xABC").normalized()
    assert r.seed == "0x0000000000000ABC"


def test_seed_rejects_garbage():
    with pytest.raises(ShipRefError):
        ShipRef(type="fighter", seed="12345").normalized()
    with pytest.raises(ShipRefError):
        ShipRef(type="fighter", seed="0xZZZ").normalized()


def test_type_rejects_unknown():
    with pytest.raises(ShipRefError):
        ShipRef(type="banana", seed="0x1").normalized()


def test_proc_model_match():
    assert ShipRef(type="fighter", seed="0x1", model="MODELS/X/FIGHTER_PROC.SCENE.MBIN").proc_model_matches()
    assert not ShipRef(type="fighter", seed="0x1", model="MODELS/X/GOLDENVECTOR.SCENE.MBIN").proc_model_matches()


def test_coerce_dict_and_object():
    a = coerce({"type": "sentinel", "seed": "0x99"})
    assert a.seed == "0x0000000000000099"
    assert coerce(a) is a


def test_all_types_have_proc_models():
    assert len(PROC_MODELS) == 10 and "sentinel" in PROC_MODELS


# ---------------------------------------------------------------- 存档层


def test_classify(saves_dir):
    assert library.classify(saves_dir / "save.hg") in ("player", "unknown")
    assert library.classify(saves_dir / "accountdata.hg") == "account"
    assert library.classify(saves_dir / "mf_save.hg") == "manifest"


def test_scan_dir_reports_every_file(saves_dir):
    res = library.scan_dir(saves_dir)
    assert res["found"] is True
    kinds = {f["name"]: f["kind"] for f in res["files"]}
    assert kinds["accountdata.hg"] == "account"
    assert kinds["mf_save.hg"] == "manifest"
    # mf_ 与 accountdata 必须给中文原因，而不是抛异常
    for f in res["files"]:
        if f["kind"] != "player":
            assert f["error"]


def test_open_ships_real(saves_dir):
    ships, warns = library.open_ships(saves_dir / "save.hg")
    assert len(ships) >= 5
    assert all(s.seed.startswith("0x") and len(s.seed) == 18 for s in ships)
    # 至少要有可换外观的程序化船；固定模型（护卫舰等）允许存在
    assert any(s.can_preview for s in ships)
    assert all(s.type in ("sentinel", "fighter", "hauler", "explorer", "shuttle",
                          "exotic", "living", "solar", "corvette", "unknown") for s in ships)


def test_open_ships_second_slot(saves_dir):
    ships, _ = library.open_ships(saves_dir / "save2.hg")
    assert len(ships) >= 5


def test_accountdata_refused_with_reason(saves_dir):
    from starforge.core.errors import SaveFormatError
    with pytest.raises(SaveFormatError) as e:
        library.open_ships(saves_dir / "accountdata.hg")
    assert "账号" in str(e.value) or "清单" in str(e.value)


def test_missing_file(saves_dir):
    from starforge.core.errors import SaveNotFound
    with pytest.raises(SaveNotFound):
        library.probe(saves_dir / "nope.hg")
