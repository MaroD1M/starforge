"""`starforge agent hello`：代理握手入口的能力表契约。

现在还没有 DLL，但入口必须先固定——否则 Windows 那轮实机验证没有可对照的输出。
这组测试锁的是"能力表结构"，不是"能不能连游戏"（连接只在 Windows 上才有意义）。
"""
import json
import types

from starforge.__main__ import cmd_agent


def _run(capsys):
    rc = cmd_agent(types.SimpleNamespace(action="hello"))
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_agent_hello_reports_full_capability_table(capsys):
    rc, rep = _run(capsys)
    assert rep["proto"] == 1
    caps = rep["capabilities"]
    # 与 docs/AGENT-PROTOCOL.md 的命令表对齐（13 项）
    for name in ("player.ua", "system.current", "planet.current", "ship.read",
                 "ship.write_seed", "ship.write_class", "ship.write_parts",
                 "teleport.system", "teleport.position", "scan.planet", "debug.flags"):
        assert name in caps, name
        assert set(caps[name]) == {"available", "reason", "risk"}
        assert caps[name]["risk"] in ("low", "mid", "high")
    assert len(caps) == 13


def test_agent_hello_says_why_unavailable(capsys):
    rc, rep = _run(capsys)
    # 非 Windows 上一定带原因说明；不能只说 available=false
    assert rep["note"]
    assert all(v["reason"] for v in rep["capabilities"].values())
    assert rep["next"].startswith("按 docs/VERIFY-AGENT-WINDOWS.md")
    assert rc in (0, 5)          # 0=已连上（Windows+游戏在跑），5=没连上


def test_agent_hello_is_json_only(capsys):
    """实机回报要能整段贴回来，所以 stdout 必须是纯 JSON。"""
    rc, rep = _run(capsys)
    assert isinstance(rep, dict) and "capabilities" in rep
