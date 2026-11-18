"""3D 贴图 spike：UV + 游戏 DDS → glb 内嵌 PNG / 原生视口采样。

没有游戏数据或解码依赖时，真实数据用例跳过；纯合成用例始终运行，保证
"有贴图走贴图、没贴图退回平涂" 两条路都不回退成崩溃。
"""
from __future__ import annotations

import json
import struct

import numpy as np
import pytest


def _glb_json(data: bytes) -> dict:
    magic, version, _total = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67 and version == 2
    jlen, jtype = struct.unpack_from("<II", data, 12)
    assert jtype == 0x4E4F534A
    return json.loads(data[20:20 + jlen])


def _glb_chunk(data: bytes) -> bytes:
    jlen, _ = struct.unpack_from("<II", data, 12)
    off = 20 + jlen
    blen, btype = struct.unpack_from("<II", data, off)
    assert btype == 0x004E4942
    return data[off + 8:off + 8 + blen]


def _tri_group(tex: str = "") -> dict:
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
    nrm = np.tile([0, 0, 1], (3, 1)).astype(np.float32)
    uv = np.array([[0, 0], [1, 0], [0, 1]], np.float32)
    idx = np.array([0, 1, 2], np.uint32)
    return {("paint", tex): (pos, nrm, uv, idx)}


def _red_texture(side: int = 8) -> np.ndarray:
    img = np.zeros((side, side, 4), np.uint8)
    img[:, :, 0] = 220
    img[:, :, 3] = 255
    return img


def test_glb_embeds_textured_material_and_png():
    from starforge import gltf

    groups = _tri_group("TEX/A.dds")
    data = gltf.build_glb({"groups": []}, groups, colours={"paint": (1, 0, 0)},
                          textures={"TEX/A.dds": _red_texture()})
    js = _glb_json(data)
    assert len(js["images"]) == 1 and js["images"][0]["mimeType"] == "image/png"
    assert len(js["textures"]) == 1 and js["samplers"][0]["wrapS"] == 10497
    mat = js["materials"][0]
    assert "baseColorTexture" in mat["pbrMetallicRoughness"]
    assert js["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"] >= 0

    blob = _glb_chunk(data)
    img_view = js["bufferViews"][js["images"][0]["bufferView"]]
    png = blob[img_view["byteOffset"]:img_view["byteOffset"] + img_view["byteLength"]]
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_glb_without_texture_keeps_flat_fallback():
    from starforge import gltf

    data = gltf.build_glb({"groups": []}, _tri_group(), colours={"paint": (0.2, 0.4, 0.6)})
    js = _glb_json(data)
    assert "images" not in js and "textures" not in js
    mat = js["materials"][0]
    assert mat["pbrMetallicRoughness"]["baseColorFactor"][:3] == pytest.approx([0.2, 0.4, 0.6])


def test_glb_can_emit_external_texture_reference():
    from starforge import gltf

    data = gltf.build_glb({"groups": []}, _tri_group("TEX/A.dds"),
                          textures={"TEX/A.dds": {"uri": "TEX/A.png"}},
                          embed_textures=False)
    js = _glb_json(data)
    assert js["images"] == [{"uri": "TEX/A.png"}]


def test_png_encoder_accepts_rgb_and_rgba():
    from starforge import gltf

    rgb = np.zeros((2, 3, 3), np.uint8)
    png = gltf.encode_png(rgb)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack_from(">II", png, 16)
    assert (w, h) == (3, 2)


def test_ship_viewer_accepts_uploaded_texture():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from starforge.app.widgets.ship_viewer import ShipViewer

    app = QApplication.instance() or QApplication([])
    viewer = ShipViewer()
    try:
        viewer.set_mesh(_tri_group("TEX/A.dds"), {"paint": (1, 0, 0)},
                        textures={"TEX/A.dds": _red_texture()})
        assert viewer._groups and viewer._radius > 0
        assert viewer._texture_inputs["TEX/A.dds"].shape == (8, 8, 4)
        viewer.clear()
        assert viewer._groups == {} and viewer._texture_inputs == {}
    finally:
        viewer.close()
        if app.applicationName() == "":
            app.setApplicationName("starforge-test")


def test_real_ship_glb_contains_game_textures(game_env):
    """有游戏 + hgpaktool + texture2ddecoder 时，真实飞船必须生成带 PNG 的 glb。"""
    from starforge import preview
    from starforge.data.shipref import ShipRef

    ref = ShipRef(type="fighter", seed="0x884609884CD21A5C")
    info = preview.build(ref, want_glb=True)
    if info.get("level") != "L1":
        pytest.skip(info.get("reason") or "游戏 3D 不可用")
    if not info.get("textures"):
        pytest.skip("这艘船/本机没有可解码的材质贴图（平涂回退仍可用）")

    path = preview.glb_for(ref)
    with open(path, "rb") as f:
        data = f.read()
    js = _glb_json(data)
    assert len(js.get("images", [])) > 0
    assert len(js.get("textures", [])) == len(js["images"])
    assert any("baseColorTexture" in m.get("pbrMetallicRoughness", {})
               for m in js["materials"])
    assert js["meshes"][0]["primitives"][0]["attributes"].get("TEXCOORD_0") is not None
    blob = _glb_chunk(data)
    v = js["bufferViews"][js["images"][0]["bufferView"]]
    assert blob[v["byteOffset"]:v["byteOffset"] + 8] == b"\x89PNG\r\n\x1a\n"
