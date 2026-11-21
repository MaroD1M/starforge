"""agent 运行时/生命周期/传送确认的离线单测（不依赖 Windows 或游戏）。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import stat
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from starforge.core import paths
from starforge.live import agent_install
from starforge.live.agent_client import AgentClient, read_state, write_state


# ---------------------------------------------------------------- 版本矩阵


def _build_script_constants() -> dict:
    text = (Path(__file__).resolve().parents[1] / "packaging"
            / "build_agent_runtime.py").read_text("utf-8")

    def find(name: str) -> str:
        m = re.search(rf'^{name}\s*=\s*(?:os\.environ\.get\([^,]+,\s*)?"([^"]+)"',
                      text, re.M)
        assert m, name
        return m.group(1)

    return {"python": find("VERSION"),
            "nmspy": find("NMSpy_VERSION"),
            "pymhf": find("PYMHF_VERSION")}


def test_runtime_manifest_matches_build_script():
    built = _build_script_constants()
    assert agent_install.RUNTIME_PY_VERSION == built["python"]
    assert agent_install.AGENT_RUNTIME_MANIFEST["nmspy_default"] == built["nmspy"]
    assert agent_install.AGENT_PYMHF_VERSION == built["pymhf"]


def test_expected_nmspy_uses_manifest_mapping():
    assert agent_install.expected_nmspy_version({"version": "185034"}) == "185034.0"
    assert agent_install.expected_nmspy_version({"version": "not-a-build"}) == ""


def test_runtime_report_flags_mismatch_without_touching_runtime():
    rep = agent_install.runtime_report({
        "python": "C:/rt/python.exe",
        "python_version": "3.12.8",
        "nmspy": "180000.0",
        "pymhf": "0.1.0",
        "http_api": True,
    }, expected="185034.0")
    assert rep["ok"] is False
    assert any("Python" in x for x in rep["mismatches"])
    assert any("NMSpy" in x for x in rep["mismatches"])
    assert any("pymhf" in x for x in rep["mismatches"])


def test_runtime_report_accepts_manifest_versions():
    rep = agent_install.runtime_report({
        "python": "C:/rt/python.exe",
        "python_version": agent_install.RUNTIME_PY_VERSION,
        "nmspy": "185034.0",
        "nmspy_module": "185034.0",
        "pymhf": agent_install.AGENT_PYMHF_VERSION,
        "fastapi": "0.115.0",
        "uvicorn": "0.30.0",
        "http_api": True,
    }, expected="185034.0")
    assert rep["ok"] is True and rep["mismatches"] == []


def test_install_deps_does_not_early_exit_on_mismatched_bundled_runtime(
        monkeypatch, tmp_path):
    py = tmp_path / "python.exe"
    py.write_text("", "utf-8")
    monkeypatch.setattr(agent_install, "runtime_python", lambda: py)
    monkeypatch.setattr(agent_install, "_has_agent_packages", lambda _p: True)
    monkeypatch.setattr(agent_install, "_runtime_info", lambda: {
        "python": str(py), "python_version": agent_install.RUNTIME_PY_VERSION,
        "nmspy": "180000.0", "pymhf": "0.1.0", "http_api": True,
    })
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(agent_install.subprocess, "run", fake_run)
    res = agent_install.install_deps("185034.0")
    assert res["ok"] is True
    assert calls, "版本不匹配时必须尝试更新而不是直接早退"
    joined = " ".join(calls[0])
    assert "NMSpy==185034.0" in joined
    assert f"pymhf[http_api]=={agent_install.AGENT_PYMHF_VERSION}" in joined


def test_install_deps_refuses_to_reinstall_on_python_mismatch(monkeypatch, tmp_path):
    py = tmp_path / "python.exe"
    py.write_text("", "utf-8")
    monkeypatch.setattr(agent_install, "runtime_python", lambda: py)
    monkeypatch.setattr(agent_install, "_has_agent_packages", lambda _p: True)
    monkeypatch.setattr(agent_install, "_runtime_info", lambda: {
        "python": str(py), "python_version": "3.12.8",
        "nmspy": "185034.0", "pymhf": agent_install.AGENT_PYMHF_VERSION,
        "http_api": True,
    })

    def fail_run(*a, **kw):
        raise AssertionError("Python 版本不匹配时不能靠 pip 硬装")

    monkeypatch.setattr(agent_install.subprocess, "run", fail_run)
    res = agent_install.install_deps("185034.0")
    assert res["ok"] is False and res["code"] == "E_RUNTIME_PYTHON"
    assert "Python" in res["error"]
    assert res["versions"]["mismatches"]


def test_install_deps_matching_runtime_stays_offline(monkeypatch, tmp_path):
    py = tmp_path / "python.exe"
    py.write_text("", "utf-8")
    monkeypatch.setattr(agent_install, "runtime_python", lambda: py)
    monkeypatch.setattr(agent_install, "_has_agent_packages", lambda _p: True)
    monkeypatch.setattr(agent_install, "_runtime_info", lambda: {
        "python": str(py), "python_version": agent_install.RUNTIME_PY_VERSION,
        "nmspy": "185034.0", "pymhf": agent_install.AGENT_PYMHF_VERSION,
        "http_api": True,
    })

    def fail_run(*a, **kw):
        raise AssertionError("版本匹配时不应调用 pip")

    monkeypatch.setattr(agent_install.subprocess, "run", fail_run)
    res = agent_install.install_deps("185034.0")
    assert res["ok"] is True and res["versions"]["ok"] is True


# ---------------------------------------------------------------- token/state


def _serve(handler_calls: list[str]):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            handler_calls.append(self.path)
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv


def test_agent_client_reads_state_token_and_attaches_query(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "app_home", lambda: tmp_path)
    calls: list[str] = []
    srv = _serve(calls)
    try:
        base = f"http://127.0.0.1:{srv.server_port}/StarforgeAgent"
        write_state({"base": base, "token": "one-shot-token", "port": srv.server_port})
        assert AgentClient().hello()["ok"] is True
        assert "token=one-shot-token" in calls[-1]
        # 显式 base 也不能丢掉 state 里的 token
        AgentClient(base=base).hello()
        assert "token=one-shot-token" in calls[-1]
    finally:
        srv.shutdown()


@pytest.mark.skipif(os.name == "nt", reason="POSIX 权限位")
def test_agent_state_file_is_private(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "app_home", lambda: tmp_path)
    write_state({"base": "http://127.0.0.1:5000/StarforgeAgent", "token": "x"})
    path = tmp_path / "agent" / "state.json"
    assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    assert read_state()["token"] == "x"


def test_port_available_detects_conflict():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert agent_install.port_available(port) is False
    finally:
        s.close()
    assert agent_install.port_available(port) is True


# ---------------------------------------------------------------- 日志/快照


def test_launcher_log_tail_is_read_only(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "app_home", lambda: tmp_path)
    log = agent_install.launcher_log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("one\ntwo\nthree\nfour\n", "utf-8")
    res = agent_install.tail_launcher_log(lines=2)
    assert res["ok"] is True and res["exists"] is True
    assert res["lines"] == ["three", "four"]
    missing = agent_install.tail_launcher_log(lines=2)
    assert missing["exists"] is True            # 文件仍在
    log.unlink()
    gone = agent_install.tail_launcher_log(lines=2)
    assert gone["ok"] is True and gone["exists"] is False
    assert not log.exists()                    # helper 不能创建文件


def test_services_agent_log_and_snapshots(monkeypatch, tmp_path):
    from starforge.services import get_services

    monkeypatch.setattr(paths, "app_home", lambda: tmp_path)
    log = agent_install.launcher_log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("a\nb\n", "utf-8")
    snap = agent_install.snapshots_path()
    snap.write_text(json.dumps({"version": 1, "snapshots": [
        {"time": 1, "location": {"planet": 1}}]}), "utf-8")
    svc = get_services()
    assert svc.agent_log_tail(1)["lines"] == ["b"]
    assert svc.agent_snapshots()["snapshots"][0]["location"]["planet"] == 1


# ---------------------------------------------------------------- 传送确认


def _patch_verified(monkeypatch):
    from starforge.live import build

    monkeypatch.setattr(build, "summary", lambda fp=None: {
        "build_id": "185034-ABCDEF123456", "status": "verified",
        "known": {"build": "185034"}, "verified": True,
        "write_allowed": True, "reason": "",
    })


class _ConfirmClient:
    def __init__(self, location: dict | None):
        self.location = location
        self.calls: list[tuple[str, dict]] = []

    def call(self, cmd: str, **params):
        self.calls.append((cmd, params))
        if cmd == "hello":
            return {"ok": True, "multiplayer": False}
        if cmd == "teleport":
            return {"ok": True, "after": dict(self.location or {})}
        if cmd == "player":
            return {"ok": True, "location": self.location}
        return {"ok": True, "cmd": cmd, **params}


def test_teleport_confirmed_by_player_readback(monkeypatch):
    from starforge.services import get_services

    _patch_verified(monkeypatch)
    loc = {"planet": 2, "system": 7, "voxel_x": 1, "voxel_y": 2,
           "voxel_z": 3, "reality": 0}
    client = _ConfirmClient(loc)
    svc = get_services()
    monkeypatch.setattr(svc, "agent_client", lambda: client)
    res = svc.agent_call("teleport", glyphs="1043FEE69929")
    assert res["ok"] is True
    assert res["confirmed"] is True
    assert res["confirmation"] == "confirmed"
    assert ("player", {}) in client.calls


def test_teleport_reports_unconfirmed_instead_of_faking_success(monkeypatch):
    import starforge.services as services_mod
    from starforge.services import get_services

    _patch_verified(monkeypatch)
    dest = {"planet": 2, "system": 7, "voxel_x": 1, "voxel_y": 2,
            "voxel_z": 3, "reality": 0}
    other = dict(dest, system=99)
    client = _ConfirmClient(dest)
    svc = get_services()
    monkeypatch.setattr(svc, "agent_client", lambda: client)
    monkeypatch.setattr(services_mod, "_AGENT_CONFIRM_TIMEOUT", 0.0)
    monkeypatch.setattr(services_mod, "_AGENT_CONFIRM_INTERVAL", 0.0)
    # teleport 返回 dest，但 /player 读回 other
    client.location = dest
    original = client.call

    def call(cmd: str, **params):
        if cmd == "player":
            client.calls.append((cmd, params))
            return {"ok": True, "location": other}
        return original(cmd, **params)

    monkeypatch.setattr(client, "call", call)
    res = svc.agent_call("teleport", glyphs="1043FEE69929")
    assert res["ok"] is True              # 命令已下发，不等于落点已确认
    assert res["confirmed"] is False
    assert res["confirmation"] == "unconfirmed"
    assert res["confirm_error"]


# ---------------------------------------------------------------- agent 源码契约


def _source() -> str:
    return (Path(__file__).resolve().parents[1] / "starforge" / "agent"
            / "starforge_agent.py").read_text("utf-8")


def test_every_agent_endpoint_checks_token():
    text = _source()
    starts = [m.start() for m in re.finditer(r"@endpoint\(", text)]
    assert starts
    for start in starts:
        end = text.find("@endpoint(", start + 1)
        chunk = text[start:end if end != -1 else len(text)]
        assert 'token: str = ""' in chunk or "token: str = \"\"" in chunk
        assert "_auth_block(token)" in chunk


def test_agent_persists_snapshots_and_never_claims_unconfirmed():
    text = _source()
    assert "snapshots.json" in text
    assert "_persist_snapshot" in text
    assert '_latest_snapshot()' in text
    assert '"confirmation": "pending"' in text


def test_scan_discover_is_a_known_client_command(monkeypatch):
    c = AgentClient(base="http://127.0.0.1:1/StarforgeAgent", token="")
    seen = {}

    def fake_call(path, method="GET", params=None, timeout=None):
        seen.update({"path": path, "method": method, "params": params})
        return {"ok": True}

    monkeypatch.setattr(c, "_call", fake_call)
    assert c.call("scan.discover")["ok"] is True
    assert seen == {"path": "/scan", "method": "PUT", "params": {"mode": "discover"}}


def test_client_falls_back_to_put_on_405():
    """pymhf 会把没显式声明 method 的 endpoint 注册成 PUT；读端点要能回退。"""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from starforge.live.agent_client import AgentClient

    seen_methods = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen_methods.append("GET")
            self.send_error(405)

        def do_PUT(self):
            seen_methods.append("PUT")
            body = b'{"ok": true, "agent": "0.1.0"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        client = AgentClient(base=f"http://127.0.0.1:{srv.server_address[1]}/StarforgeAgent",
                             token="")
        assert client.hello()["agent"] == "0.1.0"
    finally:
        srv.shutdown()
    assert seen_methods == ["GET", "PUT"]

# ---------------------------------------------------------------- 首次安装依赖

def test_install_deps_uses_bare_runtime(tmp_path, monkeypatch):
    """干净机器上「准备运行时 → 安装组件」不能因为"还没装包"而找不到解释器。

    回归：install_deps 曾用 runtime_python()（只认已装 nmspy+pymhf 的运行时），
    导致刚 bootstrap 出来的空 runtime 永远被跳过，返回"没有可用的 Python 运行时"。
    """
    from starforge.live import agent_install as ai

    py = tmp_path / "python.exe"
    py.write_bytes(b"")
    monkeypatch.setattr(ai, "_runtime_candidates", lambda: [py])
    monkeypatch.setattr(ai, "_has_agent_packages", lambda _p: False)
    monkeypatch.setattr(ai, "runtime_python", lambda: None)

    seen = {}

    class _Done:
        returncode = 0
        stdout = "installed"
        stderr = ""

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return _Done()

    monkeypatch.setattr(ai.subprocess, "run", fake_run)
    rep = ai.install_deps(version="185034.0")

    assert rep.get("ok") is True, rep
    assert seen["cmd"][0] == str(py)
    assert any("NMSpy==185034.0" in str(part) for part in seen["cmd"])

# ---------------------------------------------------------------- attach 注入闸门

def test_launch_attach_is_refused_by_default(monkeypatch):
    """对已运行的游戏做注入会让 NMS.exe 在 python311.dll 里闪退，默认必须拒绝。"""
    from starforge.live import agent_install as ai

    monkeypatch.delenv("STARFORGE_ALLOW_ATTACH_INJECT", raising=False)
    monkeypatch.setattr(ai.mem, "IS_WINDOWS", True)
    with pytest.raises(RuntimeError) as e:
        ai.launch(attach=True)
    msg = str(e.value)
    assert "附加到已运行的游戏" in msg
    assert "STARFORGE_ALLOW_ATTACH_INJECT" in msg


def test_launch_attach_guard_can_be_overridden(monkeypatch):
    """显式打开环境变量后，闸门不再拦（后续失败由运行时报错）。"""
    from starforge.live import agent_install as ai

    monkeypatch.setenv("STARFORGE_ALLOW_ATTACH_INJECT", "1")
    monkeypatch.setattr(ai.mem, "IS_WINDOWS", True)
    monkeypatch.setattr(ai, "install_mod", lambda: {"ok": True})
    monkeypatch.setattr(ai, "_runtime_info", lambda: {"http_api": False})
    with pytest.raises(RuntimeError) as e:
        ai.launch(attach=True)
    assert "pymhf[http_api]" in str(e.value)      # 已经越过 attach 闸门
