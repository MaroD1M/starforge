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

def test_live_push_sanitizes_u64_for_qt_signals(monkeypatch):
    """写入返回的种子是 u64（>2^63），透传给 Qt 信号会 OverflowError；服务层要转成 hex 字符串。"""
    import contextlib

    from starforge.core import settings
    from starforge.live import mem, writer

    old = bool(settings.current().write_enabled)
    settings.update(write_enabled=True)
    monkeypatch.setattr(mem, "IS_WINDOWS", True)
    monkeypatch.setattr(mem, "attach", lambda *_a, **_k: contextlib.nullcontext(object()))
    monkeypatch.setattr(
        writer, "push",
        lambda *_a, **_k: {"ok": True, "seed": 0xCBB96B52CAB439CF,
                           "before": 0xA0524F4652415453, "after": 0xCBB96B52CAB439CF,
                           "address": 0x13B3B8F59E8, "score": 1.0})
    try:
        res = get_services().live_push("sentinel", "0xCBB96B52CAB439CF", confirm=True)
    finally:
        settings.update(write_enabled=old)

    assert res["ok"] is True
    for key in ("seed", "before", "after", "address"):
        assert isinstance(res[key], str) and res[key].startswith("0x"), (key, res[key])
    assert res["score"] == 1.0

# ---------------------------------------------------------------- 发现索引 / 同伴联查


def _synthetic_ua(*, planet: int = 1, system: int = 0x100) -> int:
    from starforge import address

    return address.ua_from_parts(0, system, 0, 0, 0, planet)


def _synthetic_discovery_tree() -> dict:
    """手写发现树：2 颗行星 + 1 条动物记录，不含真实存档内容。"""
    return {
        "DiscoveryManagerData": {
            "DiscoveryData-v1": {
                "Store": {
                    "Record": [
                        {"DD": {"DT": "Planet", "UA": _synthetic_ua(planet=1),
                                "VP": [0x11, 0]}, "DM": {"CN": "Synthetic Alpha"}},
                        {"DD": {"DT": "Planet", "UA": _synthetic_ua(planet=2),
                                "VP": [0x22, 4]}},
                        {"DD": {"DT": "Animal", "UA": _synthetic_ua(planet=1),
                                "VP": [0xAA, 0xBB, 0xCC, 0xDD]}},
                    ]
                },
                "Available": [],
            }
        }
    }


def test_services_discoveries_index_and_query(tmp_path, monkeypatch):
    import pytest

    from starforge import discoveries
    from starforge.core.errors import BadRequest

    tree = _synthetic_discovery_tree()
    planets = discoveries.planets_from_tree(tree)["planets"]
    save = tmp_path / "save.hg"
    save.write_bytes(b"synthetic services save")

    monkeypatch.setattr(discoveries, "discovered_planets", lambda path=None: {
        "ok": True, "path": str(save), "count": len(planets),
        "planets": planets, "records": len(planets), "duplicates": 0,
        "warnings": [],
    })

    svc = get_services()
    first = svc.discoveries_index(str(save))
    assert first["ok"] is True
    assert first["rebuilt"] is True and first["cached"] is False
    assert first["count"] == 2

    second = svc.discoveries_index(str(save))
    assert second["ok"] is True
    assert second["cached"] is True and second["rebuilt"] is False

    got = svc.discoveries_query(order="biome")
    assert got["ok"] is True and got["count"] == 2
    lushes = svc.discoveries_query(biome="Lush", order="biome")
    assert lushes["count"] == 1
    assert lushes["planets"][0]["name"] == "Synthetic Alpha"

    with pytest.raises(BadRequest):
        svc.discoveries_query(order="unsupported")


def test_services_companion_planet_and_planet_fauna(tmp_path, monkeypatch):
    from starforge import address, discoveries

    tree = _synthetic_discovery_tree()
    save = tmp_path / "save.hg"
    save.write_bytes(b"synthetic companion save")
    monkeypatch.setattr(discoveries, "_open_tree", lambda path=None: (save, tree))

    svc = get_services()
    companion = {
        "index": 3,
        "name": "Synthetic Companion",
        "creature": "Synthetic_Creature",
        "species_key": "Synthetic_Creature|0x1",
        "ua": _synthetic_ua(planet=1),
        "origin": None,
    }
    res = svc.companion_planet(companion)
    assert res["ok"] is True
    assert res["found"] is True
    assert res["count"] == 1
    assert res["planet_index"] == 1
    assert res["planet_ua"] == f"0x{_synthetic_ua(planet=1):X}"
    assert res["system_ua"] == f"0x{(0x100 << 40):X}"
    assert res["glyphs"] == "110000000000"
    assert res["coords"] == "07FF:007F:07FF:0100"
    assert res["fauna"][0]["creature_seed"] == "0xAA"
    assert res["companion"]["name"] == "Synthetic Companion"

    # 行星可定位、但没有动物记录：ok=True + 空列表 + 原因。
    empty = svc.companion_planet({"ua": _synthetic_ua(planet=2)})
    assert empty["ok"] is True and empty["found"] is False
    assert empty["fauna"] == [] and "没有找到" in empty["reason"]

    # 行星位为 0 / 地址缺失：ok=False + 明确原因，不猜默认行星。
    unknown = svc.companion_planet({"ua": address.ua_from_parts(0, 0x100, 0, 0, 0, 1)
                                    & ~discoveries.PLANET_MASK})
    assert unknown["ok"] is False and "行星位" in unknown["reason"]
    assert svc.companion_planet({"name": "no address"})["ok"] is False
    assert svc.companion_planet(None)["ok"] is False

    # 也接受 origin（creature.companions 的条目形状）。
    by_origin = svc.companion_planet({"origin": {
        "galaxy": 0, "system": 0x100, "planet": 1,
        "voxel_x": 0, "voxel_y": 0, "voxel_z": 0,
    }})
    assert by_origin["ok"] is True and by_origin["count"] == 1

    fauna = svc.planet_fauna(0x100 << 40, 1)
    assert fauna["ok"] is True and fauna["count"] == 1
    fauna_empty = svc.planet_fauna(0x100 << 40, 3)
    assert fauna_empty["ok"] is True and fauna_empty["count"] == 0
    assert "没有找到" in fauna_empty["reason"]
    assert svc.planet_fauna(0x100 << 40, 0)["ok"] is False
    assert svc.planet_fauna("bad", 1)["ok"] is False

def test_agent_connect_does_not_reinject_when_already_reachable(monkeypatch):
    """已连接时必须直接返回，不能再次注入（重复注入会让游戏退出）。"""
    from starforge.live import agent_install
    from starforge.live.agent_client import AgentClient

    monkeypatch.setattr(AgentClient, "ping", lambda self, timeout=2.0: True)
    called = {}
    monkeypatch.setattr(agent_install, "launch",
                        lambda **kw: called.setdefault("launch", kw) or {"ok": True})
    res = get_services().agent_connect()
    assert res["ok"] is True and res.get("already_connected") is True
    assert "launch" not in called


def test_agent_connect_injects_only_when_not_reachable(monkeypatch):
    from starforge.live import agent_install, mem
    from starforge.live.agent_client import AgentClient

    monkeypatch.setattr(AgentClient, "ping", lambda self, timeout=2.0: False)
    monkeypatch.setattr(mem, "find_pid", lambda *_a, **_k: 1234)
    seen = {}
    monkeypatch.setattr(agent_install, "launch",
                        lambda **kw: seen.update(kw) or {"ok": True, "pid": 1})
    res = get_services().agent_connect()
    assert res["ok"] is True
    assert seen.get("attach") is False
