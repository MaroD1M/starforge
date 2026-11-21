"""服务层契约：原生 UI 与网页共用同一套用例入口。"""
from __future__ import annotations

from starforge.services import get_services


def test_health_is_framework_agnostic():
    svc = get_services()
    h = svc.health()
    assert h["ok"] is True
    for key in ("version", "preview_level", "write_enabled", "data_ready",
                "saves_ready", "live_available"):
        assert key in h


def test_settings_roundtrip():
    svc = get_services()
    before = svc.settings_snapshot()
    assert before["ok"] is True
    svc.update_settings(write_enabled=False, saves_dir="", gamedata_dir="", game_dir="")
    after = svc.settings_snapshot()
    assert after["settings"]["write_enabled"] is False
    assert "resolved" in after


def test_live_capabilities_exposes_teleport_and_scan(monkeypatch):
    from starforge.live import agent_install

    # 不能让测试依赖本机是否正在跑游戏：把 agent 状态钉成"未连接"。
    monkeypatch.setattr(agent_install, "status", lambda: {
        "attached": False, "reachable": False, "hello": {},
        "build": {"verified": False, "write_allowed": False, "reason": "这版未验证"},
    })
    svc = get_services()
    cap = svc.live_capabilities()
    names = set(cap["capabilities"])
    assert {"teleport", "scan", "player", "planet"} <= names
    assert all(v["available"] is False for v in cap["capabilities"].values())


def test_job_registry_roundtrip():
    from starforge.jobs import REGISTRY

    job = REGISTRY.create("test")
    job.update(tested=10, seconds=2)
    svc = get_services()
    got = svc.job(job.id)
    assert got["job"]["id"] == job.id
    assert got["job"]["kind"] == "test"
    job.finish(result=[])


def test_known_build_addressbook_contains_user_fingerprint():
    from starforge.live import build

    rows = build.known_builds()
    assert any(r.get("sha256") == "092236962EE050E419424699B5C343A0173F7773D5AD0866B7EC366D334C07D4"
               for r in rows)
    row = next(r for r in rows if r.get("build") == "185034")
    assert row["status"] == "unverified"
    assert "teleport.system" in row["capabilities"]


def test_agent_client_http_contract():
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    calls = []

    class H(BaseHTTPRequestHandler):
        def _do(self):
            calls.append((self.command, self.path))
            body = json.dumps({"ok": True, "path": self.path}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._do()

        def do_PUT(self):
            self._do()

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        from starforge.live.agent_client import AgentClient

        c = AgentClient(base=f"http://127.0.0.1:{srv.server_port}/StarforgeAgent")
        assert c.hello()["ok"] is True
        c.teleport("1043FEE69929", galaxy=3)
        c.scan("read")
        assert any("glyphs=1043FEE69929" in p and "galaxy=3" in p for _m, p in calls)
        assert any("mode=read" in p for _m, p in calls)
    finally:
        srv.shutdown()


def test_agent_install_mod_and_version_mapping():
    from starforge.live import agent_install

    assert agent_install.expected_nmspy_version({"version": "185034"}) == "185034.0"
    res = agent_install.install_mod()
    assert res["ok"] is True
    from pathlib import Path

    assert Path(res["path"]).exists()
    assert "StarforgeAgent" in Path(res["path"]).read_text("utf-8")

# ---------------------------------------------------------------- 模板 Mod / 连接

def test_install_template_mod_requires_confirm():
    import pytest

    from starforge.core.errors import BadRequest

    with pytest.raises(BadRequest):
        get_services().install_template_mod()


def test_agent_connect_refuses_without_game(monkeypatch):
    from starforge.live import mem

    monkeypatch.setattr(mem, "find_pid", lambda *_a, **_k: None)
    res = get_services().agent_connect()
    assert res["ok"] is False
    assert res["code"] == "E_NO_GAME"
