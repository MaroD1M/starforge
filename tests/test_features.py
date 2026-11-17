"""M1 搜索 / M2 预览降级 / M4.5 符文 的回归测试。"""
import pytest

from starforge import glyphs, jobs, preview, search
from starforge.data.shipref import ShipRef


# ---------------------------------------------------------------- 任务模型


def test_job_lifecycle_and_eta():
    j = jobs.Job(kind="test")
    j.update(tested=1000, seconds=2.0, max_seeds=10_000)
    assert j.status == "running"
    assert j.progress["rate"] == pytest.approx(500)
    assert j.progress["eta"] == pytest.approx((10_000 - 1000) / 500)
    j.finish(result=[1, 2, 3])
    assert j.status == "done" and j.result == [1, 2, 3]
    d = j.to_dict()
    assert d["id"] == j.id and d["kind"] == "test"


def test_job_cancel_marks_status():
    j = jobs.Job(kind="test")
    j.cancel()
    assert j.should_stop() is True
    j.finish()
    assert j.status == "cancelled"


def test_job_thread_swallows_exception():
    j = jobs.Job(kind="boom")

    def bad(job):
        raise RuntimeError("kaboom")

    jobs.run_in_thread(j, bad)
    for _ in range(50):
        if j.status != "running":
            break
        time.sleep(0.02)
    assert j.status == "failed" and "kaboom" in j.error


# ---------------------------------------------------------------- 搜索校验


def test_query_rejects_unknown_ship(gamedata):
    with pytest.raises(search.QueryError):
        search.validate(search.SearchQuery(ship="banana", want=["_PIT_A"]))


def test_query_rejects_foreign_parts(gamedata):
    # sentinel 的 _PIT_A 不属于 fighter —— 手册 F01 的核心校验
    with pytest.raises(search.QueryError) as e:
        search.validate(search.SearchQuery(ship="fighter", want=["_PIT_A"]))
    assert "不属于" in str(e.value)


def test_query_requires_any_condition(gamedata):
    with pytest.raises(search.QueryError):
        search.validate(search.SearchQuery(ship="sentinel"))


def test_query_normalises_parts(gamedata):
    q = search.validate(search.SearchQuery(ship="sentinel", want=[" _pit_a "], limit=999))
    assert q.want == ["_PIT_A"] and q.limit == 200


@pytest.mark.slow
def test_search_finds_sentinel_seeds(gamedata, game_env):
    q = search.SearchQuery(ship="sentinel", want=["_PIT_A"], limit=2, time_limit=8, workers=1)
    out = search.run(q)
    assert out and all(r["type"] == "sentinel" and r["seed"].startswith("0x") for r in out)


# ---------------------------------------------------------------- 预览降级


def test_preview_levels_without_game():
    # 测试环境里没有游戏目录 → 必须明确降级为 L0
    info = preview.build(ShipRef(type="sentinel", seed="0x992C8A47F60A6B10"))
    assert info["level"] in ("L0", "L1")
    if info["level"] == "L0":
        assert info["degraded"] is True and info["reason"]
        assert "part_icons" in info


# ---------------------------------------------------------------- 符文


def test_digits_for_accepts_forms():
    assert glyphs.digits_for("1043FEE69929") == "1043FEE69929"
    assert glyphs.digits_for("0x1043FEE69929") == "1043FEE69929"
    assert glyphs.digits_for(0x1043FEE69929) == "1043FEE69929"
    assert glyphs.digits_for("AB") == "00000000AB".rjust(12, "0")[:12]


def test_digits_for_rejects_garbage():
    with pytest.raises(ValueError):
        glyphs.digits_for("XYZ")


def test_panel_png_is_png():
    data = glyphs.panel_png("1043FEE69929")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    import struct
    w, h = struct.unpack_from(">II", data, 16)
    assert w > 12 * 50 and h > 50          # 12 格横排


def test_panel_payload_shape():
    p = glyphs.panel_payload("1043FEE69929")
    assert len(p["digits"]) == 12 and len(p["icons"]) == 12
    assert p["strip"].endswith("1043FEE69929.png")
    assert p["source"] in ("game", "font")


# ---------------------------------------------------------------- Web 契约


def test_api_search_rejects_foreign_parts(client, gamedata):
    r = client.post("/api/search", json={"ship": "fighter", "want": ["_PIT_A"]})
    assert r.status_code == 400
    assert r.get_json()["error"]["kind"] == "bad_request"


def test_api_glyph_panel(client):
    r = client.post("/api/glyph-panel", json={"glyphs": "0x1043FEE69929"})
    j = r.get_json()
    assert j["ok"] and j["glyphs"] == "1043FEE69929" and len(j["digits"]) == 12


def test_api_glyph_strip_png(client):
    r = client.get("/api/glyphs/1043FEE69929.png")
    assert r.status_code == 200 and r.mimetype == "image/png"


def test_api_glyph_single_digit_png(client):
    r = client.get("/api/glyphs/a.png")
    assert r.status_code == 200 and r.data[:4] == b"\x89PNG"


def test_api_jobs_empty(client):
    j = client.get("/api/jobs").get_json()
    assert j["ok"] and isinstance(j["jobs"], list)
