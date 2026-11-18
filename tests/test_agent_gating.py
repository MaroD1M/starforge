"""agent build 闸门 + 多人安全降级（不依赖真实游戏）。"""
from __future__ import annotations

from pathlib import Path

from starforge.services import get_services

HIGH_RISK = {"teleport", "restore", "scan.discover", "scan.instant"}
READ_ONLY = {"player", "system", "planet", "ships"}


def _build_info(verified: bool) -> dict:
    return {
        "build_id": "185034-ABCDEF123456",
        "status": "verified" if verified else "unverified",
        "known": {"build": "185034"},
        "verified": verified,
        "write_allowed": verified,
        "reason": "" if verified else "这版未验证（build 185034，status=unverified）：只允许只读能力",
    }


def _status(multiplayer: bool = False) -> dict:
    return {
        "supported": True,
        "runtime_ready": True,
        "mod_installed": True,
        "reachable": True,
        "game_running": True,
        "note": "agent 已连接",
        "hello": {
            "ok": True,
            "in_game": True,
            "multiplayer": multiplayer,
            "capabilities": {
                "player": True, "system": True, "planet": True, "ships": True,
                "teleport": True, "scan": "read", "scan.discover": True,
                "scan.instant": True, "restore": True,
            },
        },
    }


def _patch(monkeypatch, *, verified: bool, multiplayer: bool = False) -> None:
    from starforge.live import agent_install, build

    monkeypatch.setattr(build, "summary", lambda fp=None: _build_info(verified))
    monkeypatch.setattr(agent_install, "status", lambda: _status(multiplayer))


class _FakeClient:
    def __init__(self, multiplayer: bool = False):
        self.multiplayer = multiplayer
        self.calls: list[tuple[str, dict]] = []

    def call(self, cmd: str, **params):
        self.calls.append((cmd, params))
        if cmd == "hello":
            return {"ok": True, "in_game": True, "multiplayer": self.multiplayer}
        return {"ok": True, "cmd": cmd, **params}


def _use_client(monkeypatch, client: _FakeClient) -> None:
    svc = get_services()
    monkeypatch.setattr(svc, "agent_client", lambda: client)


def test_unverified_build_downgrades_high_risk(monkeypatch):
    _patch(monkeypatch, verified=False)
    cap = get_services().live_capabilities()
    for key in HIGH_RISK:
        item = cap["capabilities"][key]
        assert item["available"] is False, key
        assert item.get("blocked_by") == "build"
        assert "未验证" in item["reason"]
    for key in READ_ONLY:
        assert cap["capabilities"][key]["available"] is True, key
    assert cap["build"]["verified"] is False
    assert cap["write_allowed"] is False


def test_verified_build_allows_high_risk(monkeypatch):
    _patch(monkeypatch, verified=True)
    cap = get_services().live_capabilities()
    for key in HIGH_RISK:
        assert cap["capabilities"][key]["available"] is True, key
        assert cap["capabilities"][key]["reason"] == ""
    assert cap["build"]["verified"] is True
    assert cap["write_allowed"] is True


def test_multiplayer_disables_high_risk_even_if_verified(monkeypatch):
    _patch(monkeypatch, verified=True, multiplayer=True)
    cap = get_services().live_capabilities()
    for key in HIGH_RISK:
        item = cap["capabilities"][key]
        assert item["available"] is False, key
        assert item.get("blocked_by") == "multiplayer"
        assert "多人" in item["reason"]
    for key in READ_ONLY:
        assert cap["capabilities"][key]["available"] is True, key
    assert cap["multiplayer"] is True


def test_agent_call_blocks_unverified_before_touching_agent(monkeypatch):
    _patch(monkeypatch, verified=False)
    client = _FakeClient()
    _use_client(monkeypatch, client)
    svc = get_services()
    res = svc.agent_call("teleport", glyphs="1043FEE69929", galaxy=3)
    assert res["ok"] is False and res["code"] == "E_BUILD_UNVERIFIED"
    assert "未验证" in res["error"]
    assert client.calls == []


def test_agent_call_blocks_multiplayer_write_but_allows_read(monkeypatch):
    _patch(monkeypatch, verified=True, multiplayer=True)
    client = _FakeClient(multiplayer=True)
    _use_client(monkeypatch, client)
    svc = get_services()
    for cmd, params in (("teleport", {"glyphs": "1043FEE69929"}),
                        ("restore", {}),
                        ("scan.instant", {"on": True}),
                        ("scan", {"mode": "discover"})):
        res = svc.agent_call(cmd, **params)
        assert res["ok"] is False and res["code"] == "E_MULTIPLAYER", cmd
        assert "多人" in res["error"]
    read = svc.agent_call("scan", mode="read")
    assert read["ok"] is True
    assert ("scan", {"mode": "read"}) in client.calls


def test_agent_call_verified_single_player_allows_write(monkeypatch):
    _patch(monkeypatch, verified=True, multiplayer=False)
    client = _FakeClient(multiplayer=False)
    _use_client(monkeypatch, client)
    res = get_services().agent_call("teleport", glyphs="1043FEE69929", galaxy=3)
    assert res["ok"] is True
    assert res["cmd"] == "teleport"
    assert ("teleport", {"glyphs": "1043FEE69929", "galaxy": 3}) in client.calls


def test_agent_mod_guards_all_high_risk_endpoints():
    src = Path(__file__).resolve().parents[1] / "starforge" / "agent" / "starforge_agent.py"
    text = src.read_text("utf-8")
    assert "_multiplayer_block()" in text
    for marker in ('def teleport', 'def restore', 'def scan_instant', 'def scan('):
        start = text.index(marker)
        end = text.find("    @endpoint", start + 1)
        chunk = text[start:end if end != -1 else len(text)]
        assert "_multiplayer_block()" in chunk, marker
