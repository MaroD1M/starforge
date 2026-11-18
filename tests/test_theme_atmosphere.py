"""可选无人深空氛围：设置读写 + QSS 切换，不依赖游戏。"""
from __future__ import annotations

import json
import os

import pytest


def _write_settings(home, payload) -> None:
    (home / "settings.json").write_text(json.dumps(payload), "utf-8")


def test_atmosphere_default_and_roundtrip():
    from starforge.core import settings

    assert settings.current().atmosphere is False
    settings.update(atmosphere=True)
    settings._CURRENT = None
    assert settings.current().atmosphere is True
    settings.update(atmosphere=False)
    settings._CURRENT = None
    assert settings.current().atmosphere is False


def test_atmosphere_old_and_invalid_config_keeps_default(isolated_home):
    from starforge.core import settings

    _write_settings(isolated_home, {"write_enabled": True})
    settings._CURRENT = None
    s = settings.current()
    assert s.atmosphere is False
    assert s.write_enabled is True

    _write_settings(isolated_home, {"atmosphere": "not-a-bool"})
    settings._CURRENT = None
    assert settings.current().atmosphere is False

    _write_settings(isolated_home, {"atmosphere": "on"})
    settings._CURRENT = None
    assert settings.current().atmosphere is True

    (isolated_home / "settings.json").write_text("123", "utf-8")
    settings._CURRENT = None
    assert settings.current().atmosphere is False


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_set_atmosphere_switches_qss_and_palette(qapp):
    from PySide6.QtGui import QPalette

    from starforge.app import theme

    theme.apply(qapp)
    neutral_window = qapp.palette().color(QPalette.Window).name()
    assert qapp.styleSheet() == theme.QSS

    theme.set_atmosphere(True)
    assert qapp.styleSheet() == theme.ATMOSPHERE_QSS
    assert qapp.styleSheet() != theme.QSS
    assert "qlineargradient" in qapp.styleSheet()
    assert qapp.palette().color(QPalette.Window).name() != neutral_window

    for on in (False, True, False):
        theme.set_atmosphere(on)
    assert qapp.styleSheet() == theme.QSS
    assert qapp.palette().color(QPalette.Window).name() == neutral_window


def test_settings_page_applies_atmosphere_immediately(qapp):
    from starforge.app import theme
    from starforge.app.pages.settings import SettingsPage
    from starforge.core import settings

    page = SettingsPage()
    try:
        page.atmosphere.setChecked(True)
        page._save()
        assert settings.current().atmosphere is True
        assert qapp.styleSheet() == theme.ATMOSPHERE_QSS
    finally:
        page.deleteLater()
        theme.set_atmosphere(False)
