"""批量导出：zip 里必须有 glb/png/manifest，固定模型要写明原因。"""
import io
import json
import zipfile


def test_export_zip_contains_files(game_env):
    from starforge import export
    data, stats = export.export_zip(
        [{"type": "sentinel", "seed": "0x884609884CD21A5C", "name": "大黄蜂"}],
        include_glb=True, include_png=True, png_size=320)
    assert stats["count"] == 1 and stats["exported"] == 1
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    assert any(n.endswith(".glb") for n in names)
    assert any(n.endswith(".png") for n in names)
    man = json.loads(z.read("manifest.json"))
    assert man["exported"] == 1 and man["items"][0]["type"] == "sentinel"
    assert man["items"][0]["colours"]


def test_export_marks_fixed_models(game_env):
    from starforge import export
    data, stats = export.export_zip(
        [{"type": "corvette", "seed": "0x6AB373B9", "name": "采集者工程船"}],
        include_glb=True, include_png=True, png_size=200)
    z = zipfile.ZipFile(io.BytesIO(data))
    man = json.loads(z.read("manifest.json"))
    assert stats["exported"] == 0
    assert "固定模型" in man["items"][0]["note"]


def test_export_rejects_bad_item(game_env):
    from starforge import export
    _, stats = export.export_zip([{"type": "sentinel", "seed": "nonsense"}])
    assert stats["failed"] == 1


def test_export_api(client, game_env):
    r = client.post("/api/export", json={"items": [{"type": "sentinel", "seed": "0x884609884CD21A5C"}],
                                         "png": True, "glb": True, "size": 200})
    assert r.status_code == 200 and r.mimetype == "application/zip"
    assert r.data[:2] == b"PK"
    assert r.headers["X-Export-Count"] == "1"


def test_export_api_needs_items(client):
    assert client.post("/api/export", json={}).status_code == 400


# ---------------------------------------------------------------- 贴图采样

def test_tex_sample_maps_uv_to_pixels():
    import numpy as np
    from starforge import tex
    img = np.zeros((2, 2, 4), np.uint8)
    img[0, 0] = [255, 0, 0, 255]
    img[0, 1] = [0, 255, 0, 255]
    img[1, 0] = [0, 0, 255, 255]
    img[1, 1] = [255, 255, 0, 255]
    got = tex.sample(img, np.array([0.1, 0.9, 0.1, 0.9]), np.array([0.1, 0.1, 0.9, 0.9]))
    assert got[0].tolist() == [1.0, 0.0, 0.0]
    assert got[1].tolist() == [0.0, 1.0, 0.0]
    assert got[2].tolist() == [0.0, 0.0, 1.0]
    assert got[3].tolist() == [1.0, 1.0, 0.0]


def test_rasterize_uses_texture_when_given():
    """给了贴图就必须真的采样（否则贴图管线等于没接）。"""
    import numpy as np
    from starforge import render
    # 一个朝向相机的大三角，UV 覆盖整张贴图
    pos = np.array([[-1, -1, 0], [1, -1, 0], [0, 1, 0]], np.float32)
    nrm = np.tile([0, 0, 1], (3, 1)).astype(np.float32)
    uv = np.array([[0, 0], [1, 0], [0, 1]], np.float32)
    idx = np.array([0, 1, 2], np.uint32)
    groups = {("paint", "TEX/A.dds"): (pos, nrm, uv, idx)}
    tex_img = np.zeros((8, 8, 4), np.uint8)
    tex_img[:, :] = [200, 40, 40, 255]                 # 纯红贴图
    # ambient=1 让光照不再压暗，直接看贴图颜色是否被用上
    out = render.rasterize(groups, ("iso",), (64, 64), ss=1, ambient=1.0,
                           textures={"TEX/A.dds": tex_img})
    red = (out[:, :, 0] > 150) & (out[:, :, 1] < 100)
    assert red.sum() > 20                              # 有像素被贴图染红
