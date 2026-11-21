"""「送进游戏」服务封装：四条路径全部打桩，绝不触碰真实游戏内存。"""
from __future__ import annotations

import contextlib
import types

import pytest

from starforge.services import Services, get_services

REF = {"type": "sentinel", "seed": "0x1111222233334444"}


@pytest.fixture(autouse=True)
def _write_enabled():
    """这些用例验证的是闸门之后的编排；默认把写开关打开，闸门用例自己关掉。"""
    from starforge.core import settings

    settings.update(write_enabled=True)
    yield


def _status(running: bool = True, supported: bool = True) -> dict:
    return {"platform": "windows", "supported": supported,
            "running": running, "pid": 8580 if running else None}


def _no_push(*_args, **_kwargs):
    raise AssertionError("这条路径不应该调用 live_push")


def _no_attach(*_args, **_kwargs):
    raise AssertionError("闸门拒绝时不应该连接游戏进程")


@contextlib.contextmanager
def _fake_attach(_name: str = "NMS.exe"):
    yield types.SimpleNamespace(pid=5168)


def test_push_ship_success_carries_emote_title(monkeypatch):
    svc = get_services()
    calls: dict = {}

    monkeypatch.setattr(Services, "live_status", lambda self: _status())

    def fake_push(self, type_: str, seed: str | int, confirm: bool = False) -> dict:
        calls.update(type=type_, seed=seed, confirm=confirm)
        value = int(seed, 16)
        return {"ok": True, "address": 0x7FF612345678, "type": type_,
                "before": 0x1, "after": value, "seed": value, "score": 1.0}

    monkeypatch.setattr(Services, "live_push", fake_push)

    res = svc.live_push_ship(REF, confirm=True)

    assert res["ok"] is True
    assert res["emote"] == "星铸 · 拦截机"
    assert res["template"] == "STARFORGE_SENTINEL"
    assert res["type"] == "sentinel"
    assert res["seed"] == "0x1111222233334444"
    assert calls == {"type": "sentinel", "seed": "0x1111222233334444",
                     "confirm": True}


def test_push_ship_rejects_when_game_not_running(monkeypatch):
    svc = get_services()
    monkeypatch.setattr(Services, "live_status", lambda self: _status(running=False))
    monkeypatch.setattr(Services, "live_push", _no_push)

    res = svc.live_push_ship(REF, confirm=True)

    assert res["ok"] is False
    assert res["reason"] == "game_not_running"
    assert res["error"] == "先启动游戏并进入存档，再送进游戏"
    assert res["emote"] == "星铸 · 拦截机"


def test_push_ship_reports_missing_template(monkeypatch):
    svc = get_services()
    monkeypatch.setattr(Services, "live_status", lambda self: _status())
    monkeypatch.setattr(Services, "live_push", _no_push)

    # 货船不在 8 个模板槽里；模板检查先于连接游戏，因此不会读进程。
    res = svc.live_push_ship({"type": "freighter", "seed": "0x1"}, confirm=True)

    assert res["ok"] is False
    assert res["reason"] == "no_template"
    assert res["error"] == "先在游戏内页安装模板 Mod 并重启游戏"
    assert "freighter" in res["detail"]


def test_push_ship_surfaces_write_error_verbatim(monkeypatch):
    from starforge.live import writer

    svc = get_services()
    monkeypatch.setattr(Services, "live_status", lambda self: _status())

    def failing_push(self, type_: str, seed: str | int,
                     confirm: bool = False) -> dict:
        raise writer.LocateError("回读校验失败：期望 0x1111222233334444，实际 0x0")

    monkeypatch.setattr(Services, "live_push", failing_push)

    res = svc.live_push_ship(REF, confirm=True)

    assert res["ok"] is False
    assert res["reason"] == "write_failed"
    assert "回读校验失败" in res["error"]
    assert "0x1111222233334444" in res["error"]
    assert res["emote"] == "星铸 · 拦截机"


def test_push_ship_rejects_bad_seed_without_touching_game(monkeypatch):
    svc = get_services()
    monkeypatch.setattr(Services, "live_status", _no_push)
    monkeypatch.setattr(Services, "live_push", _no_push)

    res = svc.live_push_ship({"type": "sentinel", "seed": "not-a-seed"}, confirm=True)

    assert res["ok"] is False
    assert res["reason"] == "bad_ref"
    assert "种子格式不对" in res["error"]


def test_push_ship_rejects_zero_seed(monkeypatch):
    svc = get_services()
    monkeypatch.setattr(Services, "live_status", _no_push)
    monkeypatch.setattr(Services, "live_push", _no_push)

    res = svc.live_push_ship({"type": "sentinel", "seed": "0x0"}, confirm=True)

    assert res["ok"] is False
    assert res["reason"] == "bad_seed"
    assert "0x0" in res["error"]


@pytest.mark.parametrize("type_, title", [
    ("sentinel", "星铸 · 拦截机"),
    ("fighter", "星铸 · 战斗机"),
    ("hauler", "星铸 · 运输舰"),
    ("explorer", "星铸 · 探索舰"),
    ("shuttle", "星铸 · 穿梭机"),
    ("exotic", "星铸 · 异星"),
    ("living", "星铸 · 生物舰"),
    ("solar", "星铸 · 太阳帆"),
])
def test_all_eight_templates_have_emote_titles(monkeypatch, type_: str, title: str):
    svc = get_services()
    monkeypatch.setattr(Services, "live_status", lambda self: _status())
    monkeypatch.setattr(
        Services, "live_push",
        lambda self, t, s, confirm=False: {"ok": True, "type": t, "seed": int(s, 16)})

    res = svc.live_push_ship({"type": type_, "seed": "0xABCDEF"}, confirm=True)

    assert res["ok"] is True
    assert res["emote"] == title
    assert res["template"] == f"STARFORGE_{type_.upper()}"


# ---------------------------------------------------------------- 统一写闸门


def test_live_push_requires_confirm(monkeypatch):
    from starforge.core import settings
    from starforge.core.errors import BadRequest
    from starforge.live import mem

    settings.update(write_enabled=True)
    monkeypatch.setattr(mem, "attach", _no_attach)

    with pytest.raises(BadRequest) as exc:
        get_services().live_push("sentinel", "0x1")

    assert "写游戏内存需要二次确认" in str(exc.value)
    assert "8 字节" in exc.value.hint


def test_live_push_ship_requires_confirm(monkeypatch):
    from starforge.core import settings
    from starforge.core.errors import BadRequest
    from starforge.live import mem

    settings.update(write_enabled=True)
    monkeypatch.setattr(mem, "attach", _no_attach)
    monkeypatch.setattr(Services, "live_push", _no_push)

    with pytest.raises(BadRequest) as exc:
        get_services().live_push_ship(REF)

    assert "写游戏内存需要二次确认" in str(exc.value)


def test_live_push_refuses_when_write_disabled(monkeypatch):
    from starforge.core import settings
    from starforge.core.errors import WriteDisabled
    from starforge.live import mem

    settings.update(write_enabled=False)
    monkeypatch.setattr(mem, "attach", _no_attach)

    with pytest.raises(WriteDisabled) as exc:
        get_services().live_push("sentinel", "0x1", confirm=True)

    assert "写入功能当前关闭" in str(exc.value)


def test_live_push_ship_refuses_when_write_disabled(monkeypatch):
    from starforge.core import settings
    from starforge.core.errors import WriteDisabled
    from starforge.live import mem

    settings.update(write_enabled=False)
    monkeypatch.setattr(mem, "attach", _no_attach)
    monkeypatch.setattr(Services, "live_push", _no_push)

    with pytest.raises(WriteDisabled):
        get_services().live_push_ship(REF, confirm=True)


def test_live_push_success_after_confirm(monkeypatch):
    from starforge.core import settings
    from starforge.live import mem, writer

    settings.update(write_enabled=True)
    monkeypatch.setattr(mem, "IS_WINDOWS", True)
    monkeypatch.setattr(mem, "attach", _fake_attach)
    monkeypatch.setattr(
        writer, "push",
        lambda proc, type_, seed: {"type": type_, "seed": int(seed, 16),
                                   "address": 0x1234, "before": 0,
                                   "after": int(seed, 16)})

    res = get_services().live_push("sentinel", "0xCAFE", confirm=True)

    assert res["ok"] is True
    assert res["type"] == "sentinel"
    assert res["seed"] == 0xCAFE
    assert res["address"] == 0x1234
