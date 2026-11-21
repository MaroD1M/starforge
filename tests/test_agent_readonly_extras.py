"""只读扩展端点（/multitool、/freighter、/pets）的解析层单测。

`starforge_agent.py` 是 pymhf 单文件 Mod，正常导入会拉起 nmspy/pymhf，所以这里用
桩模块把它加载进来，只测**纯解析函数**（运行时对象 → dict）的三条路径：
有数据 / 空 / 字段缺失。真实内存读取由实机验证，不在这里伪造。
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

AGENT = (Path(__file__).resolve().parents[1] / "starforge" / "agent"
         / "starforge_agent.py")


def _deco(fn):
    return fn


def _load_agent(monkeypatch, tmp_path):
    """用最小桩加载 agent 模块（不启动 pymhf）。"""
    nmspy = types.ModuleType("nmspy")
    nmspy.__path__ = []
    data_pkg = types.ModuleType("nmspy.data")
    data_pkg.__path__ = []
    basic = types.ModuleType("nmspy.data.basic_types")
    nms = types.ModuleType("nmspy.data.types")

    nms.cGcApplication = types.SimpleNamespace(Update=types.SimpleNamespace(after=_deco))
    nms.cTkFSM = types.SimpleNamespace(StateChange=types.SimpleNamespace(after=_deco))
    nms.cGcBinoculars = types.SimpleNamespace(
        UpdateScanBarProgress=types.SimpleNamespace(before=_deco))

    common = types.ModuleType("nmspy.common")
    common.gameData = types.SimpleNamespace()
    engine = types.ModuleType("nmspy.engine")
    engine.GetNodeAbsoluteTransMatrix = lambda *a, **k: None
    exported = types.ModuleType("nmspy.data.exported_types")

    pymhf = types.ModuleType("pymhf")
    pymhf.__path__ = []
    pymhf.Mod = object
    pymhf_core = types.ModuleType("pymhf.core")
    pymhf_core.__path__ = []
    hooking = types.ModuleType("pymhf.core.hooking")
    hooking.one_shot = _deco
    http_api = types.ModuleType("pymhf.core.http_api")

    def endpoint(*args, **kwargs):
        return _deco

    http_api.endpoint = endpoint

    for name, mod in {
        "nmspy": nmspy, "nmspy.data": data_pkg,
        "nmspy.data.basic_types": basic, "nmspy.data.types": nms,
        "nmspy.data.exported_types": exported, "nmspy.common": common,
        "nmspy.engine": engine, "pymhf": pymhf, "pymhf.core": pymhf_core,
        "pymhf.core.hooking": hooking, "pymhf.core.http_api": http_api,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    monkeypatch.setenv("STARFORGE_AGENT_TOKEN", "")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    spec = importlib.util.spec_from_file_location("sf_agent_under_test", AGENT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 桩对象


class EnumVal:
    def __init__(self, value: int):
        self.value = value


class Fixed:
    """cTkFixedString / TkID：`.value` 是 bytes。"""

    def __init__(self, text: str | bytes):
        self.value = text.encode("utf-8") if isinstance(text, str) else text


class Var:
    """VariableSizeString：`.value` 是 str。"""

    def __init__(self, text: str):
        self.value = text


class Seed:
    def __init__(self, value: int):
        self.Seed = value


class Dyn:
    def __init__(self, items: list):
        self.value = items
        self.Size = len(items)

    def __iter__(self):
        return iter(self.value)

    def __len__(self):
        return len(self.value)


def _inv(filled: int = 2, capacity: int = 60, cls: int = 3):
    slots = [types.SimpleNamespace(Id=Fixed("WARP_CELL"), Amount=5,
                                   MaxAmount=99, Type=EnumVal(1))
             for _ in range(filled)]
    return types.SimpleNamespace(
        Name=Fixed(""), Class=EnumVal(cls), Width=10, Height=6,
        Slots=Dyn(slots), ValidSlotIndices=Dyn([None] * capacity))


def _multitool(name: str = "分解者", model: str = "MODELS/COMMON/WEAPONS/"
               "MULTITOOL/SWARMMULTITOOL.SCENE.MBIN",
               seed: int = 0x9BA274EE421CB66F, filled: int = 2, cls: int = 3):
    return types.SimpleNamespace(
        Name=Fixed(name), Seed=Seed(seed),
        Resource=types.SimpleNamespace(Filename=Var(model)),
        Store=_inv(filled, cls=cls), Layout=types.SimpleNamespace(Level=1),
        PrimaryMode=0, SecondaryMode=1, IsLarge=True)


def _empty_multitool():
    return types.SimpleNamespace(
        Name=Fixed(""), Seed=Seed(0),
        Resource=types.SimpleNamespace(Filename=Var("")),
        Store=_inv(0, capacity=0, cls=0),
        Layout=types.SimpleNamespace(Level=1),
        PrimaryMode=0, SecondaryMode=0, IsLarge=False)


def _pet(name: str = "蝴蝶坐骑", cid: str = "LARGEBUTTERFLY",
         seed: int = 0x0E4E24DB2A1F78BE):
    return types.SimpleNamespace(
        CreatureID=Fixed(cid), CustomName=Fixed(name), CustomSpeciesName=Fixed(""),
        CreatureType=EnumVal(26), Biome=EnumVal(4), Predator=False, HasFur=False,
        EggModified=False, Trust=0.9, Scale=1.0, BirthTime=123,
        UA=0x1234567890ABCDEF, HasBeenSummoned=True,
        Descriptors=Dyn([Fixed("_FWINGS_02"), Fixed("_MOTHBODY_01")]),
        CreatureSeed=Seed(seed), CreatureSecondarySeed=Seed(1),
        SpeciesSeed=Seed(2), GenusSeed=Seed(3), BoneScaleSeed=Seed(4),
        ColourBaseSeed=Seed(5), Traits=[1.0, 2.0], Moods=[0.5, 0.6])


def _empty_pet():
    return types.SimpleNamespace(
        CreatureID=Fixed(""), CustomName=Fixed(""),
        Descriptors=Dyn([]), HasBeenSummoned=False)


def _frigate(name: str = "运输", seed: int = 0xFC8B9E1EA041663B):
    return types.SimpleNamespace(
        CustomName=Fixed(name), ResourceSeed=Seed(seed),
        HomeSystemSeed=Seed(0xC100FD6E3100), FrigateClass=EnumVal(6),
        InventoryClass=EnumVal(3), Race=EnumVal(2), DamageTaken=0,
        TotalNumberOfExpeditions=4, TotalNumberOfSuccessfulEvents=3,
        TotalNumberOfFailedEvents=1, Stats=Dyn([1, 2, 3]),
        TraitIDs=Dyn([Fixed("TRAIT_A")]))


def _freighter_data(with_freighter: bool = True, frigate_count: int = 1):
    fleet = [types.SimpleNamespace(
        Resource=types.SimpleNamespace(Filename=Var(""), Seed=Seed(-1)),
        Inventory=_inv(0, capacity=0, cls=0),
        Inventory_Cargo=_inv(0, capacity=0, cls=0),
        Dismissed=False) for _ in range(8)]
    return types.SimpleNamespace(
        PlayerFreighterName=Fixed("星海巨兽" if with_freighter else ""),
        CurrentFreighter=types.SimpleNamespace(
            Filename=Var("MODELS/COMMON/SPACECRAFT/INDUSTRIAL/"
                         "CAPITALFREIGHTER_PROC.SCENE.MBIN" if with_freighter else ""),
            Seed=Seed(0x2B97354BAED22B24 if with_freighter else 0)),
        CurrentFreighterHomeSystemSeed=Seed(0xC100FD6E3100),
        FreighterInventory=_inv(5 if with_freighter else 0,
                                cls=3 if with_freighter else 0),
        FreighterInventory_Cargo=_inv(0, capacity=0, cls=0),
        FreighterInventory_TechOnly=_inv(0, capacity=0, cls=0),
        FreighterLayout=types.SimpleNamespace(Level=1),
        FreighterFleet=fleet,
        FleetFrigates=Dyn([_frigate() for _ in range(frigate_count)]),
    )


# ---------------------------------------------------------------- /multitool


def test_multitool_payload_with_data(monkeypatch, tmp_path):
    m = _load_agent(monkeypatch, tmp_path)
    data = types.SimpleNamespace(
        Multitools=[_multitool(), _empty_multitool()],
        CurrentWeapon=types.SimpleNamespace(
            Filename=Var("MODELS/COMMON/WEAPONS/MULTITOOL/SWARMMULTITOOL.SCENE.MBIN"),
            GenerationSeed=Seed(0x9BA274EE421CB66F)))

    res = m._multitool_payload(data)
    assert res["ok"] is True
    assert res["count"] == 1 and len(res["slots"]) == 2
    first = res["slots"][0]
    assert first["name"] == "分解者" and first["class"] == "S"
    assert first["seed"] == "0x9BA274EE421CB66F"
    assert first["type"] == "unknown"            # SWARMMULTITOOL 不在船型表里
    assert first["inventory"]["filled"] == 2
    assert first["inventory"]["items"][0]["id"] == "WARP_CELL"
    assert res["current_slot"] == 0
    assert res["slots"][1]["empty"] is True and res["slots"][1]["class"] is None
    assert res["raw"][0]["name_hex"] == "分解者".encode().hex()
    assert "unsupported" not in res


def test_multitool_payload_empty_slots(monkeypatch, tmp_path):
    m = _load_agent(monkeypatch, tmp_path)
    data = types.SimpleNamespace(
        Multitools=[_empty_multitool() for _ in range(6)],
        CurrentWeapon=types.SimpleNamespace(Filename=Var(""), GenerationSeed=Seed(0)))

    res = m._multitool_payload(data)
    assert res["ok"] is True
    assert res["count"] == 0 and len(res["slots"]) == 6
    assert all(row["empty"] for row in res["slots"])
    assert res["current_slot"] is None


def test_multitool_payload_missing_fields(monkeypatch, tmp_path):
    m = _load_agent(monkeypatch, tmp_path)

    res = m._multitool_payload(types.SimpleNamespace())
    assert res["ok"] is False and res["unsupported"] is True
    assert "Multitools" in res["error"]

    # 结构在但单槽字段缺失：行内标 unsupported，绝不抛异常/编造
    data = types.SimpleNamespace(
        Multitools=[types.SimpleNamespace()],
        CurrentWeapon=types.SimpleNamespace())
    res = m._multitool_payload(data)
    assert res["ok"] is True
    row = res["slots"][0]
    assert row["empty"] is True
    assert "Name" in row["unsupported"] and "Seed" in row["unsupported"]


# ---------------------------------------------------------------- /freighter


def test_freighter_payload_with_data(monkeypatch, tmp_path):
    m = _load_agent(monkeypatch, tmp_path)
    res = m._freighter_payload(_freighter_data(frigate_count=2))

    assert res["ok"] is True
    fr = res["freighter"]
    assert fr["owned"] is True and fr["class"] == "S"
    assert fr["name"] == "星海巨兽"
    assert fr["type"] == "freighter"
    assert fr["seed"] == "0x2B97354BAED22B24"
    assert fr["home_system_seed"] == "0x0000C100FD6E3100"
    assert fr["inventory"]["filled"] == 5
    assert res["fleet_slots"] == 8 and res["fleet_count"] == 0 and res["fleet"] == []
    assert res["frigate_count"] == 2
    assert res["frigates"][0]["class"] == "DeepSpace"
    assert res["frigates"][0]["inventory_class"] == "S"
    assert res["frigates"][0]["race"] == "Explorers"
    assert res["raw"]["current"]["seed"] == 0x2B97354BAED22B24


def test_freighter_payload_empty(monkeypatch, tmp_path):
    m = _load_agent(monkeypatch, tmp_path)
    res = m._freighter_payload(_freighter_data(with_freighter=False, frigate_count=0))

    assert res["ok"] is True
    assert res["freighter"]["owned"] is False
    assert res["fleet"] == [] and res["frigates"] == []
    assert res["frigate_count"] == 0
    assert res["fleet_note"]


def test_freighter_payload_missing_fields(monkeypatch, tmp_path):
    m = _load_agent(monkeypatch, tmp_path)
    res = m._freighter_payload(types.SimpleNamespace())
    assert res["ok"] is False and res["unsupported"] is True
    assert "货船" in res["error"]


# ---------------------------------------------------------------- /pets


def test_pets_payload_with_data(monkeypatch, tmp_path):
    m = _load_agent(monkeypatch, tmp_path)
    data = types.SimpleNamespace(Pets=Dyn([_pet(), _empty_pet()]))

    res = m._pets_payload(data)
    assert res["ok"] is True and res["count"] == 1
    pet = res["pets"][0]
    assert pet["name"] == "蝴蝶坐骑" and pet["species"] == "LARGEBUTTERFLY"
    assert pet["type"] == "Passive" and pet["biome"] == "Frozen"
    assert pet["descriptors"] == ["_FWINGS_02", "_MOTHBODY_01"]
    assert pet["seeds"]["creature"] == "0x0E4E24DB2A1F78BE"
    assert pet["has_been_summoned"] is True
    assert pet["active"] is None and pet["active_supported"] is False
    assert pet["ua"] == "0x1234567890ABCDEF"
    assert res["raw"][0]["creature"] == "LARGEBUTTERFLY"
    assert "unsupported" not in res


def test_pets_payload_empty(monkeypatch, tmp_path):
    m = _load_agent(monkeypatch, tmp_path)
    res = m._pets_payload(types.SimpleNamespace(Pets=Dyn([_empty_pet() for _ in range(30)])))
    assert res["ok"] is True and res["count"] == 0 and res["pets"] == []
    assert "空槽" in res["note"]


def test_pets_payload_missing_fields(monkeypatch, tmp_path):
    m = _load_agent(monkeypatch, tmp_path)
    res = m._pets_payload(types.SimpleNamespace())
    assert res["ok"] is False and res["unsupported"] is True
    assert "Pets" in res["error"]

    # 有 CreatureID 但没有名字/种子：行内 unsupported，不崩
    partial = types.SimpleNamespace(CreatureID=Fixed("COW"))
    res = m._pets_payload(types.SimpleNamespace(Pets=Dyn([partial])))
    assert res["ok"] is True and res["count"] == 1
    row = res["pets"][0]
    assert row["name"] == ""
    assert "CustomName" in row["unsupported"]
    assert "CreatureSeed" in row["unsupported"]


# ---------------------------------------------------------------- 客户端白名单


def test_client_exposes_readonly_extras(monkeypatch):
    from starforge.live.agent_client import AgentClient

    c = AgentClient(base="http://127.0.0.1:1/StarforgeAgent", token="")
    seen = []

    def fake_call(path, method="GET", params=None, timeout=None):
        seen.append(path)
        return {"ok": True, "path": path}

    monkeypatch.setattr(c, "_call", fake_call)
    for cmd in ("multitool", "freighter", "pets"):
        assert c.call(cmd)["ok"] is True
    assert seen == ["/multitool", "/freighter", "/pets"]
