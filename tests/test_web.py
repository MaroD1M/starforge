"""Web 层：安全闸门 + API 契约。"""
import pytest

from starforge.core import settings as settings_mod


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True
    assert j["write_enabled"] is False
    assert j["preview_level"] in ("L0", "L1")


def test_catalog_api(client, gamedata):
    j = client.get("/api/catalog").get_json()
    assert j["ok"] and j["source"] in ("gagarin", "game")
    assert len(j["ships"]) == 8 and "sentinel" in j["ships"]
    assert j["ships"]["sentinel"]["parts"] > 0


def test_catalog_ship_api(client, gamedata):
    j = client.get("/api/catalog/sentinel").get_json()
    assert j["ok"] and any(g["group"] == "_PIT_" for g in j["groups"])


def test_catalog_unknown_ship(client, gamedata):
    r = client.get("/api/catalog/banana")
    assert r.status_code == 404
    assert r.get_json()["error"]["kind"] == "not_found"


def test_icon_route(client, gamedata):
    r = client.get("/api/icons/_PIT_A.png?ship=sentinel")
    assert r.status_code == 200 and r.mimetype == "image/png"
    assert r.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_icon_missing_404(client, gamedata):
    assert client.get("/api/icons/_NOPE_.png").status_code == 404


def test_saves_scan(client, saves_dir):
    j = client.get(f"/api/saves?dir={saves_dir}").get_json()
    assert j["ok"] and j["found"] is True
    assert any(f["kind"] == "manifest" for f in j["files"])


def test_ships_list(client, saves_dir):
    j = client.get(f"/api/ships?path={saves_dir / 'save.hg'}").get_json()
    assert j["ok"] and j["count"] >= 5
    assert j["ships"][0]["seed"].startswith("0x")


def test_write_gate_is_closed_by_default(client):
    r = client.post("/api/saves/apply", json={"confirm": True})
    assert r.status_code == 403
    assert r.get_json()["error"]["kind"] == "write_disabled"


def test_write_gate_opens_then_needs_confirm(client, monkeypatch):
    """闸门顺序：先 write_enabled，再 confirm，最后才碰存档。

    这里显式把"找不到存档"固定住——否则本机设了 STARFORGE_SAVES 时，用例会走到
    "存档里没有第 -1 艘船"的 400，测试就跟着环境漂了（这条坑由 goal 轮跑全量时暴露）。
    """
    from starforge.core.errors import SaveNotFound
    from starforge.save import library as library_mod

    def _no_save(*a, **k):
        raise SaveNotFound("没有找到存档目录")

    settings_mod.update(write_enabled=True)
    monkeypatch.setattr(library_mod, "resolve", _no_save)
    r = client.post("/api/saves/apply", json={})
    assert r.status_code == 400                     # 缺 confirm
    # 有 confirm 但没配置存档路径 → 明确 404，而不是静默成功
    r = client.post("/api/saves/apply", json={"confirm": True, "type": "sentinel", "seed": "0x1"})
    assert r.status_code == 404


def test_bad_origin_refused(client):
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.get_json()["error"]["kind"] == "bad_origin"


def test_local_origin_allowed(client):
    r = client.get("/api/health", headers={"Origin": "http://127.0.0.1:1234"})
    assert r.status_code == 200


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200 and b"starforge" in r.data.lower() or b"\xe9\xa3\x9e\xe8\x88\xb9" in r.data
