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
