"""`starforge agent hello` 与 `starforge live push` 的 CLI 契约。

agent 是 pymhf + NMSpy 的 Python Mod，不是 DLL；这里不启动游戏内组件，
只 monkeypatch 安装/运行时/HTTP 三种状态，锁住能力表的推导规则。
`live push` 的写入函数也被 monkeypatch，测试绝不碰游戏内存。
"""
from __future__ import annotations

import contextlib
import json
import types

import pytest

from starforge import __main__ as cli
from starforge.live import agent_client, agent_install, build, mem, writer

READ_ONLY = {"player.ua", "player.position", "player.stats", "system.current",
             "planet.current", "ship.read"}
HIGH_RISK = {"teleport.system", "teleport.position", "ship.write_parts", "debug.flags"}


@pytest.fixture(autouse=True)
def _write_enabled():
    """live push 的闸门测试需要显式打开写开关；拒绝用例自己再关掉。"""
    from starforge.core import settings

    settings.update(write_enabled=True)
    yield


# ---------------------------------------------------------------- agent 探测假件


def _patch_agent_state(monkeypatch, tmp_path, *, installed: bool, runtime: bool,
                       reachable: bool, write_allowed: bool = False,
                       status: str = "unverified") -> None:
    """伪造 agent_install / agent_client，并让 build.summary 返回指定闸门。"""
    monkeypatch.setattr(mem, "IS_WINDOWS", True)

    @contextlib.contextmanager
    def _attach(_name="NMS.exe"):
        yield types.SimpleNamespace(pid=5168)

    monkeypatch.setattr(mem, "attach", _attach)

    mod = tmp_path / "starforge_agent.py"
    if installed:
        mod.write_text("# fake agent mod\n", encoding="utf-8")
    monkeypatch.setattr(agent_install, "installed_mod", lambda: mod)
    monkeypatch.setattr(agent_install, "runtime_python",
                        lambda: (tmp_path / "python.exe") if runtime else None)
    monkeypatch.setattr(agent_install, "runtime_dir", lambda: tmp_path / "runtime")
    # 测试环境可能恰好装了 pymhf；关掉"模块可导入"这条兜底，保证状态可复现。
    monkeypatch.setattr(cli, "_module_available", lambda _name: False)

    class _FakeClient:
        def __init__(self, base=None, timeout=5.0, token=None):
            self.base = base or "http://127.0.0.1:5000/StarforgeAgent"
            self.timeout = timeout
            self.token = token or ""
            self.reachable = reachable

        def hello(self):
            if not self.reachable:
                raise agent_client.AgentError("agent 未启动")
            return {"ok": True, "agent": "test"}

    monkeypatch.setattr(agent_client, "AgentClient", _FakeClient)
    monkeypatch.setattr(build, "summary", lambda fp=None: {
        "version": "185034", "build_id": "185034-TEST", "status": status,
        "verified": write_allowed, "write_allowed": write_allowed,
        "reason": "" if write_allowed else
        f"这版未验证（build 185034-TEST，status={status}）：只允许只读能力",
    })


def _run_agent(capsys) -> tuple[int, dict]:
    rc = cli.cmd_agent(types.SimpleNamespace(action="hello"))
    return rc, json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------- agent hello


def test_agent_hello_reports_full_capability_table(monkeypatch, tmp_path, capsys):
    _patch_agent_state(monkeypatch, tmp_path, installed=False, runtime=False,
                       reachable=False)
    rc, rep = _run_agent(capsys)
    assert rep["proto"] == 1
    caps = rep["capabilities"]
    # 与 CLI 的 `_AGENT_CAPABILITIES` 对齐（13 项）；不破坏既有键名。
    assert len(caps) == 13
    for name in ("player.ua", "system.current", "planet.current", "ship.read",
                 "ship.write_seed", "ship.write_class", "ship.write_parts",
                 "teleport.system", "teleport.position", "scan.planet", "debug.flags"):
        assert name in caps, name
        assert set(caps[name]) == {"available", "reason", "risk"}
        assert caps[name]["risk"] in ("low", "mid", "high")
    assert rc == 5


def test_agent_hello_is_json_only(monkeypatch, tmp_path, capsys):
    _patch_agent_state(monkeypatch, tmp_path, installed=False, runtime=False,
                       reachable=False)
    rc, rep = _run_agent(capsys)
    assert isinstance(rep, dict) and "capabilities" in rep
    assert rep["next"].startswith("按 docs/AGENT.md")


def test_agent_not_installed_is_detected(monkeypatch, tmp_path, capsys):
    _patch_agent_state(monkeypatch, tmp_path, installed=False, runtime=False,
                       reachable=False)
    rc, rep = _run_agent(capsys)
    assert rc == 5
    assert rep["agent"]["installed"] is False
    assert rep["agent"]["runtime"] is False
    assert rep["agent"]["reachable"] is False
    assert "未安装" in rep["note"]
    assert all(not v["available"] for v in rep["capabilities"].values())
    assert all(v["reason"] == "agent 未运行/未连接"
               for v in rep["capabilities"].values())


def test_agent_installed_but_not_connected(monkeypatch, tmp_path, capsys):
    _patch_agent_state(monkeypatch, tmp_path, installed=True, runtime=True,
                       reachable=False)
    rc, rep = _run_agent(capsys)
    assert rc == 5
    assert rep["agent"]["installed"] is True
    assert rep["agent"]["runtime"] is True
    assert rep["agent"]["reachable"] is False
    assert "已安装" in rep["note"] and "未连接" in rep["note"]
    assert all(not v["available"] for v in rep["capabilities"].values())


def test_agent_connected_keeps_unverified_build_read_only(monkeypatch, tmp_path, capsys):
    _patch_agent_state(monkeypatch, tmp_path, installed=True, runtime=True,
                       reachable=True, write_allowed=False, status="unverified")
    rc, rep = _run_agent(capsys)
    assert rc == 0
    assert rep["agent"]["reachable"] is True
    assert "agent 已连接" in rep["note"]
    caps = rep["capabilities"]
    for name in READ_ONLY:
        assert caps[name]["available"] is True, name
        assert caps[name]["reason"] == ""
    for name in set(caps) - READ_ONLY:
        assert caps[name]["available"] is False, name
        assert "build 未校准（status=unverified）" in caps[name]["reason"], name
    assert rep["build"]["write_allowed"] is False


def test_agent_connected_verified_allows_writes_but_not_experimental(
        monkeypatch, tmp_path, capsys):
    _patch_agent_state(monkeypatch, tmp_path, installed=True, runtime=True,
                       reachable=True, write_allowed=True, status="verified")
    rc, rep = _run_agent(capsys)
    assert rc == 0
    caps = rep["capabilities"]
    for name in ("ship.write_seed", "ship.write_class", "teleport.system",
                 "teleport.position", "scan.planet"):
        assert caps[name]["available"] is True, name
    for name in ("ship.write_parts", "debug.flags"):
        assert caps[name]["available"] is False, name
        assert "实验性" in caps[name]["reason"], name


# ---------------------------------------------------------------- live push


def _patch_live(monkeypatch, fake_push) -> None:
    monkeypatch.setattr(mem, "IS_WINDOWS", True)

    @contextlib.contextmanager
    def _attach(_name="NMS.exe"):
        yield types.SimpleNamespace(pid=5168)

    monkeypatch.setattr(mem, "attach", _attach)
    monkeypatch.setattr(writer, "push", fake_push)


@pytest.mark.parametrize(("raw", "want"), [
    ("0x1111222233334444", 0x1111222233334444),
    ("0XCAFE", 0xCAFE),
    ("1229", 1229),
    ("0", 0),
    ("0x1_0000", 0x10000),
])
def test_live_push_seed_parsing(raw, want):
    assert cli._parse_seed(raw) == want


@pytest.mark.parametrize("raw", ["", "0x", "abc", "-1", "2**64", "0x1_0000_0000_0000_0000"])
def test_live_push_rejects_bad_seed(raw):
    with pytest.raises(ValueError):
        cli._parse_seed(raw)


def test_live_push_invalid_type_is_readable(capsys):
    a = types.SimpleNamespace(type="nope", seed="0x1", json=False)
    rc = cli.cmd_live_push(a)
    err = capsys.readouterr().err
    assert rc == 2
    assert "未知船型" in err and "sentinel" in err


def test_live_push_invalid_seed_is_readable(capsys):
    a = types.SimpleNamespace(type="sentinel", seed="not-a-seed", json=False)
    rc = cli.cmd_live_push(a)
    err = capsys.readouterr().err
    assert rc == 2
    assert "种子无效" in err


def test_live_push_prints_human_summary(monkeypatch, capsys):
    seen = {}

    def fake_push(proc, type_, seed):
        seen.update(proc=proc, type=type_, seed=seed)
        return {"ok": True, "address": 0x1234, "type": type_,
                "before": 0, "after": seed, "seed": seed, "score": 1.0}

    _patch_live(monkeypatch, fake_push)
    rc = cli.cmd_live_push(types.SimpleNamespace(
        type="sentinel", seed="0x1111222233334444", json=False, yes=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert seen["type"] == "sentinel" and seen["seed"] == 0x1111222233334444
    assert "已写入 sentinel 模板槽" in out
    assert "0x1111222233334444" in out


def test_live_push_json_output(monkeypatch, capsys):
    def fake_push(proc, type_, seed):
        return {"ok": True, "address": 0x1234, "type": type_, "seed": seed}

    _patch_live(monkeypatch, fake_push)
    rc = cli.cmd_live_push(types.SimpleNamespace(
        type="solar", seed="42", json=True, yes=True))
    rep = json.loads(capsys.readouterr().out)
    assert rc == 0 and rep["ok"] is True and rep["seed"] == 42


def test_live_push_locate_failure_has_actionable_hint(monkeypatch, capsys):
    def fake_push(proc, type_, seed):
        raise writer.LocateError(
            "没找到 sentinel 的模板槽。可能原因：① 没装 starforge-templates 数据 Mod")

    _patch_live(monkeypatch, fake_push)
    rc = cli.cmd_live_push(types.SimpleNamespace(
        type="sentinel", seed="0x1", json=False, yes=True))
    err = capsys.readouterr().err
    assert rc == 5
    assert "模板槽" in err and "模板 Mod" in err


def test_live_push_without_yes_refuses_before_attaching(monkeypatch, capsys):
    """没给 --yes 时必须在连接游戏之前退出，退出码 2。"""
    def _no_attach(_name="NMS.exe"):
        raise AssertionError("没有 --yes 不应该连接游戏进程")

    monkeypatch.setattr(mem, "IS_WINDOWS", True)
    monkeypatch.setattr(mem, "attach", _no_attach)

    rc = cli.cmd_live_push(types.SimpleNamespace(
        type="sentinel", seed="0x1", json=False))
    err = capsys.readouterr().err
    assert rc == 2
    assert "二次确认" in err and "--yes" in err


def test_live_push_without_yes_json_reports_confirm_code(monkeypatch, capsys):
    def _no_attach(_name="NMS.exe"):
        raise AssertionError("没有 --yes 不应该连接游戏进程")

    monkeypatch.setattr(mem, "IS_WINDOWS", True)
    monkeypatch.setattr(mem, "attach", _no_attach)

    rc = cli.cmd_live_push(types.SimpleNamespace(
        type="sentinel", seed="0x1", json=True))
    rep = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert rep["ok"] is False
    assert rep["code"] == "E_CONFIRM_REQUIRED"


def test_live_push_requires_write_enabled(monkeypatch, capsys):
    from starforge.core import settings

    def _no_attach(_name="NMS.exe"):
        raise AssertionError("写开关关闭时不应该连接游戏进程")

    settings.update(write_enabled=False)
    monkeypatch.setattr(mem, "IS_WINDOWS", True)
    monkeypatch.setattr(mem, "attach", _no_attach)

    rc = cli.cmd_live_push(types.SimpleNamespace(
        type="sentinel", seed="0x1", json=False, yes=True))
    err = capsys.readouterr().err
    assert rc == 2
    assert "写入功能当前关闭" in err


def test_live_push_main_wires_parser_to_command(monkeypatch, capsys):
    def fake_push(proc, type_, seed):
        return {"ok": True, "address": 0x10, "type": type_, "seed": seed}

    _patch_live(monkeypatch, fake_push)
    rc = cli.main(["live", "push", "--type", "fighter", "--seed", "0xCAFE",
                   "--yes", "--json"])
    rep = json.loads(capsys.readouterr().out)
    assert rc == 0 and rep["type"] == "fighter" and rep["seed"] == 0xCAFE


def test_live_push_argparse_rejects_unknown_type(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["live", "push", "--type", "nope", "--seed", "1"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "invalid choice" in err and "sentinel" in err
