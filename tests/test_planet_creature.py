"""T9（行星字段）+ M8-lite（同伴只读）的契约测试。

T9 的结论是**部分负结果**，所以这里要同时锁两件事：
  1. 离线**能**拿到的字段（biome / sentinels / 4 个哨兵预设 / seed）必须真的在返回里；
  2. 离线**拿不到**的字段（天气/植被/生物/资源）必须在能力表里明确标成"需游戏内"，
     免得界面假装有数据。
"""
import pytest

from starforge import creature, system


# ---------------------------------------------------------------- T9 行星字段


def test_planet_rows_have_sentinel_presets(game_env):
    info = system.system(0x10400F19BDCE5, planets=True)
    pl = info["planet_list"]
    assert pl, "这个星系应当有行星"
    for p in pl:
        assert len(p["sentinel_presets"]) == 4
        assert p["sentinel_index"] == p["levels"][2]
        assert p["sentinels"] == p["sentinel_presets"][p["sentinel_index"]] or p["sentinels"] == "?"
        assert "biome" in p and "seed" in p


def test_planet_fields_capability_is_honest(game_env):
    cap = system.capabilities()["planet_fields"]
    assert set(cap["offline"]) and set(cap["need_game"])
    for f in ("weather", "flora", "fauna", "resources"):
        assert f in cap["need_game"], f"离线拿不到的字段必须标出来：{f}"
    assert "占位表" in cap["note"] or "离线" in cap["note"]


def test_api_system_exposes_presets(client, game_env):
    j = client.get("/api/system").get_json()
    assert j["ok"]
    for p in j["planet_list"]:
        assert "sentinel_presets" in p


# ---------------------------------------------------------------- 同伴（只读）


@pytest.fixture()
def save_path(saves_dir, game_env):
    return str(saves_dir / "save.hg")


def test_companions_reads_real_save(save_path):
    r = creature.companions(save_path)
    assert r["count"] >= 1, "这份存档里应当有同伴"
    assert r["path"].endswith(".hg")
    c = r["creatures"][0]
    for k in ("index", "name", "creature", "type_zh", "biome_zh", "scale", "descriptors",
              "seeds", "ua", "predator"):
        assert k in c, k
    assert set(c["seeds"]) == {"creature", "creature2", "species", "genus"}
    assert all(v.startswith("0x") for v in c["seeds"].values())
    assert isinstance(c["ua"], int) and c["ua"] >= 0
    assert "3D" in r["preview"]           # 明确告知预览还没实现


def test_companions_skips_empty_slots(save_path):
    r = creature.companions(save_path)
    assert all(c["creature"] for c in r["creatures"]), "空槽（CreatureID 为空）不应出现在结果里"


def test_api_creatures(client, save_path):
    j = client.get("/api/creatures?path=" + save_path).get_json()
    assert j["ok"] and j["count"] == len(j["creatures"])
    assert j["creatures"][0]["descriptors"]


def test_api_creatures_missing_path_is_bad_request(client):
    r = client.get("/api/creatures?path=/nonexistent/save.hg")
    assert r.status_code in (400, 404)
    assert r.get_json()["ok"] is False


# ---------------------------------------------------------------- T8 spike：生物 3D 可行性


def test_creature_capabilities_reports_honest_verdict(game_env):
    """T8 spike 的结论必须可机读：descriptor 能列出来，但 preview_possible=False 且给出原因。"""
    from starforge import creature as cr
    cr._RIGS_CACHE = None                      # 让本次真的去读 pak 索引
    cap = cr.capabilities()
    assert cap["descriptors"] > 0, "应当在 Precache 里找到生物描述符"
    assert cap["rigs"], "应当列出骨架族"
    assert all(r.endswith("rig") for r in cap["rigs"][:5])
    assert cap["geometry_pak"] is True
    assert cap["preview_possible"] is False
    assert cap["reason"] and "生成器" in cap["reason"]


def test_api_creature_capabilities(client, game_env):
    j = client.get("/api/creatures/capabilities").get_json()
    assert j["ok"] and j["descriptors"] >= 1 and isinstance(j["rigs"], list)


def test_exe_symbol_scan_finds_generator(game_env):
    """T8 第二阶段的探路：反射里能找到 GenerateCreatureRoles 与生物角色表。"""
    from starforge import creature as cr
    rep = cr.scan_exe_symbols()
    assert rep["exe"], "应当能定位 NMS.exe"
    f = rep["found"]
    assert f["GenerateCreatureRoles"]["hit"] is True
    assert f["CreatureDataTable.mbin"]["hit"] is True
    assert "生成" in rep["note"] or "外部化" in rep["note"]


def test_capabilities_deep_only_when_asked(game_env):
    from starforge import creature as cr
    cr._RIGS_CACHE = None
    light = cr.capabilities()
    assert "generator" not in light          # 默认不扫 89 MB 的 exe
    cr._RIGS_CACHE = None
    deep = cr.capabilities(deep=True)
    assert deep["generator"]["found"]["GenerateCreatureRoles"]["hit"] is True


# ---------------------------------------------------------------- T8-3：生物角色表


def test_role_names_from_creature_data_table(game_env):
    from starforge import creature as cr
    cr._ROLES_CACHE = None
    r = cr.role_names()
    assert r["bytes"] > 100_000, "CreatureDataTable.mbin 应当被抽出来"
    assert r["count"] > 100, f"角色名太少：{r['count']}"
    roles = set(r["roles"])
    for must in ("PLANTCAT", "CRAB", "SHARK", "BIRD"):
        assert must in roles, must
    assert "哈希" in r["note"]      # 必须如实说明字段名没解出来


def test_api_creature_roles(client, game_env):
    j = client.get("/api/creatures/roles").get_json()
    assert j["ok"] and j["count"] == len(j["roles"]) >= 100


def test_companion_role_ids_exist_in_table(save_path, game_env):
    """存档里的 CreatureID 应当能在角色表里找到——这是"同伴 ↔ 角色表"通了的证据。"""
    from starforge import creature as cr
    cr._ROLES_CACHE = None
    r = cr.companions(save_path)
    known = set(cr.role_names()["roles"])
    assert r["creatures"], "存档里应有同伴"
    hit = [c for c in r["creatures"] if c.get("role_known")]
    assert hit, "至少要有同伴的 CreatureID 命中角色表"
    assert all(c["creature"] in known for c in hit)


# ---------------------------------------------------------------- T8-3 续：角色表结构


def test_role_table_structure(game_env):
    from starforge import creature as cr
    cr._ROLE_TABLE_CACHE = None
    t = cr.role_table()
    assert t["class"] == "cGcCreatureDataTable"
    assert t["layout_matches"] is True, "MBIN 头里的 hash/guid 必须与反射里的类布局吻合"
    assert t["entries"] == 86, f"实测是 86 条，不是 {t['entries']}"
    assert t["entry_size"] == 208
    assert t["end_at"] == t["data_at"] + t["entries"] * t["entry_size"]
    names = [f["name"] for f in t["fields"]]
    assert "Id" in names and "RealType" in names
    # 条目本身也解出来了：Id 是 16 字节 ASCII（不是哈希）
    assert t["items"] and t["items"][0]["id"] == "FISH"
    assert "FISHFLOCK" in t["names"] and "CRAB" in t["names"]
    assert 0.1 < t["items"][0]["min_scale"] < 10
    assert "ASCII" in t["note"]


def test_api_creature_table(client, game_env):
    j = client.get("/api/creatures/table").get_json()
    assert j["ok"] and j["entries"] == 86 and j["layout_matches"] is True
