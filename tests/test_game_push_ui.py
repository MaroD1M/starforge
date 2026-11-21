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
    monkeypatch.setattr(
        game_push, "run_worker",
        lambda fn, on_done, on_error, *args, **kwargs: workers.append(
            (fn, args, kwargs)))

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
    fn, args, kwargs = workers[0]
    assert fn == svc.live_push_ship
    assert args == (REF,)
    assert kwargs == {"confirm": True}
