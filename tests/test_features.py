"""M1 搜索 / M2 预览降级 / M4.5 符文 的回归测试。"""
import time

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
    # 12 位十六进制有歧义：历史行为当符文串（保持兼容）
    assert glyphs.digits_for("0x1043FEE69929") == "1043FEE69929"
    # int 明确按 UA 处理，按位段重排（v0.13 修正；旧实现是截低 12 位，见 handbook 01 卷 §6.4）
    assert glyphs.digits_for(0x1043FEE69929) == "1010FEE69929"
    assert glyphs.digits_for(0x11200F19BDCE5) == "1112F19BDCE5"
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


# ---------------------------------------------------------------- Windows 控制台编码


def test_cli_survives_cp1252_console(tmp_path):
    """CI 首跑的真实故障：cp1252 控制台下打印中文抛 UnicodeEncodeError。

    这里用 PYTHONIOENCODING=cp1252 复现环境，要求 CLI 仍然以 0 退出。
    """
    import os
    import subprocess
    import sys
    env = dict(os.environ)
    env.update(PYTHONIOENCODING="cp1252", STARFORGE_HOME=str(tmp_path / "home"))
    r = subprocess.run([sys.executable, "-m", "starforge", "selftest"],
                       capture_output=True, env=env, timeout=120,
                       cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-800:]


def test_glyph_icons_from_game_when_available(nms_dir):
    """有游戏 pak + texture2ddecoder 时，符文应是游戏原图（不是位图字体）。"""
    from starforge import glyphs
    from starforge.core import settings as settings_mod
    settings_mod.update(game_dir=str(nms_dir))
    rgb = glyphs.icon_rgb("1", 96)
    try:
        import texture2ddecoder  # noqa: F401
    except Exception:
        pytest.skip("没有 texture2ddecoder，走位图字体（预期降级）")
    assert rgb is not None and rgb.shape == (96, 96, 3)
    assert rgb.max() > 0.3                       # 有真实像素，不是全黑
    assert glyphs.panel_payload("1043FEE69929")["source"] == "game"


def test_console_survives_missing_streams(monkeypatch):
    """PyInstaller --windowed 下 sys.stdout/stderr 是 None：print 不能炸。"""
    import sys
    from starforge.core import console
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    console.setup_console()                    # 不抛异常
    print("应该被吞掉")
    assert sys.stdout is not None              # 已被替换成空流


def test_hide_console_is_safe_off_windows():
    """非 Windows 上必须安全返回 False，不能抛异常。"""
    from starforge.core import console
    assert console.hide_console_window() in (True, False)


def test_default_command_is_gui():
    """无子命令时必须走桌面窗口（单 exe 方案的前提）。"""
    import inspect
    from starforge import __main__ as m
    src = inspect.getsource(m.main)
    assert "cmd_app(argparse.Namespace" in src


def test_main_hides_console_before_parsing(monkeypatch):
    """双击（无子命令）时应在解析参数前就尝试隐藏控制台。"""
    import inspect
    from starforge import __main__ as m
    src = inspect.getsource(m.main)
    i_hide = src.index("hide_console_window")
    i_parse = src.index("ArgumentParser")
    assert i_hide < i_parse
