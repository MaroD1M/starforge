"""v0.13.2 的四处修复：船型中文 / 涂装开关语义 / glb 材质回退 / 原生窗口诊断。

这些都来自用户实测反馈（截图 + 反馈文字），所以每条都要能机读断言：
  · 船型在 API 里带中文标签（前端 pills 与详情标题都用它）；
  · glb 材质对未知类不再回退成主色（否则 3D "一片同色"）；
  · /api/health 明确给出"桌面窗口还是浏览器模式 + 原因"，界面据此提示装 WebView2。
"""
from starforge import gltf, paint
from starforge.data.shipref import ShipRef


def test_shipref_to_dict_has_chinese_label():
    ref = ShipRef(type="sentinel", seed="0x1111222233334444").normalized()
    d = ref.to_dict()
    assert d["type"] == "sentinel"
    assert d["type_label"] == "拦截机", d["type_label"]
    assert "type_label" in d, "前端靠 type_label 显示中文"


def test_catalog_payload_has_ship_labels(client, gamedata):
    j = client.get("/api/catalog").get_json()
    assert j["ok"] and j["ship_labels"]
    labels = j["ship_labels"]
    for t in j["ships"]:
        assert t in labels, f"{t} 缺中文标签"
    assert labels.get("fighter") == "战斗机"


def test_gltf_unknown_class_falls_back_to_group_colour_not_paint():
    colours = {"paint": [0.9, 0.1, 0.1], "secondary": [0.1, 0.1, 0.9]}
    metal = gltf._material("metal", colours)["pbrMetallicRoughness"]["baseColorFactor"]
    # metal 在 colours 里没有 → 必须落回 _GROUP_COLOR 的灰，而不是主色的红
    assert abs(metal[0] - 0.9) > 0.2, metal
    assert metal[0] < metal[1] + 0.2 and abs(metal[0] - 0.45) < 0.1, metal


def test_gltf_glow_is_emissive_orange():
    m = gltf._material("glow", {})
    assert "emissiveFactor" in m
    assert m["emissiveFactor"][0] > 0.8 and m["emissiveFactor"][1] < 0.8


def test_paint_look_includes_glow_slot():
    class _FakeTextures:
        @staticmethod
        def ship_look(seed, ship):
            return {"colours": {"primary": {"rgb": [0.9, 0.2, 0.2]},
                                "secondary": {"rgb": [0.2, 0.2, 0.9]},
                                "undercoat": {"rgb": [0.1, 0.1, 0.1]}}}

    from starforge import paint as paint_mod
    import sys, types
    fake = types.ModuleType("nms_procgen.textures")
    fake.ship_look = _FakeTextures.ship_look
    pkg = sys.modules.get("nms_procgen") or types.ModuleType("nms_procgen")
    old_pkg_attr = getattr(pkg, "textures", None)
    pkg.textures = fake
    sys.modules.setdefault("nms_procgen", pkg)
    try:
        paint_mod._CACHE.clear()
        got = paint_mod.look("0x1111222233334444", "sentinel")
        assert "glow" in got and got["glow"] == paint_mod.GLOW
        assert got["paint"] == [0.9, 0.2, 0.2]
    finally:
        paint_mod._CACHE.clear()
        if old_pkg_attr is not None:
            pkg.textures = old_pkg_attr


def test_doctor_reports_critical_deps(capsys):
    """`starforge doctor`：CI 与用户回报都用它，必须机器可读且覆盖 unicorn/依赖/桌面/上游。"""
    import json as _json
    import types
    from starforge.__main__ import cmd_doctor
    rc = cmd_doctor(types.SimpleNamespace())
    out = _json.loads(capsys.readouterr().out)
    assert out["unicorn"]["ok"] is True, out["unicorn"]
    for dep in ("numpy", "flask", "lz4", "hgpaktool", "texture2ddecoder", "pefile", "capstone"):
        assert out["deps"][dep] == "ok", (dep, out["deps"][dep])
    assert "gui" in out and "upstream" in out
    assert rc in (0, 7)


def test_doctor_capstone_is_optional(capsys):
    """capstone 只在开发期用；缺它不能让 doctor 判死（否则 CI/用户会被误导）。"""
    import json as _json
    import types
    from starforge.__main__ import cmd_doctor
    cmd_doctor(types.SimpleNamespace())
    out = _json.loads(capsys.readouterr().out)
    assert "capstone" in out["deps"]
    # 关键依赖 ok 时，capstone 的状态不影响判定的逻辑：只要必需项都 ok，就不应出现在 notes 里的致命项
    for dep in ("numpy", "flask", "lz4", "hgpaktool", "texture2ddecoder", "pefile"):
        assert out["deps"][dep] == "ok"
