"""「送进游戏」按钮的二次确认：拒绝时不调用服务，确认后带 confirm=True 调用。"""
from __future__ import annotations

import os
from typing import ClassVar

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

REF = {"type": "sentinel", "seed": "0x1111222233334444"}


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class _FakeMessageBox:
    """替身：记录文案并返回预设按钮，不真的弹模态窗。"""

    calls: ClassVar[list] = []
    answer = None

    @classmethod
    def question(cls, *args, **kwargs):
        cls.calls.append((args, kwargs))
        return cls.answer


class _FakeService:
    def __init__(self):
        self.calls: list = []

    def live_push_ship(self, ref, confirm=False):
        self.calls.append((dict(ref), confirm))
        return {"ok": True, "emote": "星铸 · 拦截机"}


def _make_button(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from starforge.app.widgets import game_push

    _FakeMessageBox.calls = []
    _FakeMessageBox.StandardButton = QMessageBox.StandardButton
    workers: list = []
    monkeypatch.setattr(game_push, "QMessageBox", _FakeMessageBox)

    def fake_worker(fn, on_done, on_error, *args, **kwargs):
        workers.append({"fn": fn, "on_done": on_done, "on_error": on_error,
                        "args": args, "kwargs": kwargs})

    monkeypatch.setattr(game_push, "run_worker", fake_worker)

    svc = _FakeService()
    btn = game_push.GamePushButton(svc)
    btn.set_ship(REF)
    assert btn.isEnabled()
    return btn, svc, workers


def test_click_asks_for_confirmation_with_8_byte_wording(qapp, monkeypatch):
    btn, svc, workers = _make_button(monkeypatch)
    _FakeMessageBox.answer = None  # 模拟用户关掉对话框/未确认

    btn.click()

    assert len(_FakeMessageBox.calls) == 1
    _args, _kwargs = _FakeMessageBox.calls[0]
    text = _args[2]
    assert "只写 8 字节种子" in text
    assert "不改存档" in text
    assert svc.calls == []
    assert workers == []


def test_reject_does_not_call_service(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    btn, svc, workers = _make_button(monkeypatch)
    _FakeMessageBox.answer = QMessageBox.StandardButton.No

    btn.click()

    assert svc.calls == []
    assert workers == []
    assert btn.text() == "送进游戏"


def test_accept_calls_service_with_confirm(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    btn, svc, workers = _make_button(monkeypatch)
    _FakeMessageBox.answer = QMessageBox.StandardButton.Yes

    btn.click()

    assert len(workers) == 1
    fn, args, kwargs = workers[0]["fn"], workers[0]["args"], workers[0]["kwargs"]
    assert fn == svc.live_push_ship
    assert args == (REF,)
    assert kwargs == {"confirm": True}


def test_success_toast_says_no_reload_needed(qapp, monkeypatch):
    """实测写模板槽后不重载存档也能领取：成功 toast 必须明确"无需重载存档"。"""
    from PySide6.QtWidgets import QMessageBox

    from starforge.app.widgets import game_push

    btn, svc, workers = _make_button(monkeypatch)
    _FakeMessageBox.answer = QMessageBox.StandardButton.Yes
    toasts: list[str] = []
    monkeypatch.setattr(game_push.notify, "success",
                        lambda text: toasts.append(str(text)))

    btn.click()
    assert len(workers) == 1
    workers[0]["on_done"](svc.live_push_ship(REF, confirm=True))

    assert len(toasts) == 1
    assert toasts[0] == ("已写入「星铸 · 拦截机」模板；"
                         "现在去游戏表情菜单选它领取即可（无需重载存档）")
    assert "无需重载存档" in toasts[0]
    assert "表情菜单" in toasts[0]


def test_unchanged_toast_says_claim_directly(qapp, monkeypatch):
    """模板槽已经是这个种子时不写内存，直接提示去表情菜单领取。"""
    from PySide6.QtWidgets import QMessageBox

    from starforge.app.widgets import game_push

    btn, svc, workers = _make_button(monkeypatch)
    _FakeMessageBox.answer = QMessageBox.StandardButton.Yes
    toasts: list[str] = []
    monkeypatch.setattr(game_push.notify, "success",
                        lambda text: toasts.append(str(text)))

    btn.click()
    workers[0]["on_done"]({"ok": True, "unchanged": True,
                           "emote": "星铸 · 拦截机"})

    assert len(toasts) == 1
    assert toasts[0] == "模板槽已经是这个种子，直接去表情菜单领取即可"
    assert "无需重载存档" not in toasts[0]
