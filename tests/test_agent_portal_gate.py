"""planet.scan / teleport.portal 的 build + allow_unverified + 多人闸门。"""
from __future__ import annotations

import pytest

from starforge.core import settings as settings_mod
from starforge.live.agent_client import AgentClient, AgentError
from starforge.services import get_services


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
                "player": True, "system": True, "planet": True,
                "planet.scan": True, "ships": True,
                "teleport": True, "teleport.portal": True,
                "scan": "read", "scan.discover": False,
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


def _allow_unverified(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(settings_mod.current(), "allow_unverified_agent", value)


def test_unverified_build_blocks_portal_but_allows_planet_scan(monkeypatch):
    _patch(monkeypatch, verified=False)
    _allow_unverified(monkeypatch, False)
    client = _FakeClient()
    _use_client(monkeypatch, client)
    svc = get_services()

    res = svc.agent_call("teleport.portal", glyphs="1043FEE69929")
    assert res["ok"] is False and res["code"] == "E_BUILD_UNVERIFIED"
    assert "未验证" in res["error"]

    # planet.scan 是只读能力，不应被 build 闸门挡住
    res = svc.agent_call("planet.scan")
    assert res["ok"] is True
    assert ("planet.scan", {}) in client.calls


def test_allow_unverified_enables_experimental_portal_write(monkeypatch):
    _patch(monkeypatch, verified=False, multiplayer=False)
    _allow_unverified(monkeypatch, True)
    client = _FakeClient(multiplayer=False)
    _use_client(monkeypatch, client)

    res = get_services().agent_call("teleport.portal", glyphs="1043FEE69929", galaxy=3)
    assert res["ok"] is True
    assert res["cmd"] == "teleport.portal"
    assert ("teleport.portal", {"glyphs": "1043FEE69929", "galaxy": 3}) in client.calls


def test_allow_unverified_enables_normal_teleport_on_unverified_build(monkeypatch):
    _patch(monkeypatch, verified=False)
    _allow_unverified(monkeypatch, True)
    client = _FakeClient()
    _use_client(monkeypatch, client)

    res = get_services().agent_call("teleport", glyphs="1043FEE69929")
    assert res["ok"] is True
    assert ("teleport", {"glyphs": "1043FEE69929"}) in client.calls


def test_multiplayer_blocks_portal_even_when_allow_unverified(monkeypatch):
    _patch(monkeypatch, verified=False, multiplayer=True)
    _allow_unverified(monkeypatch, True)
    client = _FakeClient(multiplayer=True)
    _use_client(monkeypatch, client)

    res = get_services().agent_call("teleport.portal", glyphs="1043FEE69929")
    assert res["ok"] is False and res["code"] == "E_MULTIPLAYER"
    assert "多人" in res["error"]
    assert ("teleport.portal", {"glyphs": "1043FEE69929"}) not in client.calls


def test_unknown_agent_capability_is_rejected_locally():
    with pytest.raises(AgentError, match="未知 agent 命令"):
        AgentClient(base="http://127.0.0.1:1/StarforgeAgent").call("teleport.quantum")


def test_live_capabilities_exposes_new_entries(monkeypatch):
    _patch(monkeypatch, verified=False)
    _allow_unverified(monkeypatch, False)
    cap = get_services().live_capabilities()
    assert "planet.scan" in cap["capabilities"]
    assert "teleport.portal" in cap["capabilities"]
    assert cap["capabilities"]["planet.scan"]["available"] is True
    portal = cap["capabilities"]["teleport.portal"]
    assert portal["available"] is False
    assert portal.get("blocked_by") == "build"
