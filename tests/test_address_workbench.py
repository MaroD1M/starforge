"""地址工作台：三形态互转的纯函数 + 离屏 UI 用例。"""
from __future__ import annotations

import os

import pytest

from starforge.app.dialogs.address import (
    PLANET_UNKNOWN,
    classify_address_input,
    convert_address,
    looks_like_coordinate_input,
    normalize_glyphs,
    parse_seed,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

GLYPHS = "3112F19BDCE5"
COORDS = "04E4:0070:01BC:0112"
UA_TEXT = "0x311200F19BDCE5"
UA_VALUE = 0x311200F19BDCE5


# ---------------------------------------------------------------- 基础校验


@pytest.mark.parametrize("text, expected", [
    ("1043FEE69929", "1043FEE69929"),
    ("1043fee69929", "1043FEE69929"),
    ("1043 FEE6 9929", "1043FEE69929"),
    ("1043-FEE6-9929", "1043FEE69929"),
    ("0x1043FEE69929", "1043FEE69929"),
])
def test_normalize_glyphs_accepts_common_forms(text, expected):
    assert normalize_glyphs(text) == expected


@pytest.mark.parametrize("text", ["", "1043", "1043FEE6992", "1043FEE699299",
                                  "1043FEE6992G", "0x11200F19BDCE5"])
def test_normalize_glyphs_rejects_bad_input(text):
    with pytest.raises(ValueError):
        normalize_glyphs(text)


@pytest.mark.parametrize("text, expected", [
    ("0xDEADBEEF", 0xDEADBEEF),
    ("0Xdeadbeef", 0xDEADBEEF),
    ("  0x0123456789ABCDEF  ", 0x0123456789ABCDEF),
    ("DEADBEEF", 0xDEADBEEF),
    ("12345", 12345),
])
def test_parse_seed_accepts_hex_and_decimal(text, expected):
    assert parse_seed(text) == expected


@pytest.mark.parametrize("text", ["", "0x", "0xZZ", "-1", "hello",
                                  "0x10000000000000000"])
def test_parse_seed_rejects_bad_input(text):
    with pytest.raises(ValueError):
        parse_seed(text)


@pytest.mark.parametrize("text", [
    "04E4:0070:01BC:0104",
    "04E4 0070 01BC 0104",
    "04E4：0070：01BC：0104",
])
def test_coordinate_texts_are_detected(text):
    assert looks_like_coordinate_input(text)


# ---------------------------------------------------------------- 三形态互转


def test_glyphs_to_coords_and_ua():
    result = convert_address(GLYPHS)
    assert result["ok"] is True
    assert result["kind"] == "glyphs"
    assert result["glyphs"] == GLYPHS
    assert result["coords"] == COORDS
    assert result["ua"] == UA_VALUE
    assert result["ua_text"] == UA_TEXT
    assert result["planet"] == 3
    assert result["teleportable"] is True
    assert result["warning"] == ""


def test_coords_to_glyphs_and_ua():
    result = convert_address(COORDS, planet=3)
    assert result["ok"] is True
    assert result["kind"] == "coords"
    assert result["glyphs"] == GLYPHS
    assert result["coords"] == COORDS
    assert result["ua_text"] == UA_TEXT
    assert result["planet"] == 3
    assert result["teleportable"] is True


def test_ua_to_glyphs_and_coords():
    result = convert_address(UA_TEXT)
    assert result["ok"] is True
    assert result["kind"] == "ua"
    assert result["glyphs"] == GLYPHS
    assert result["coords"] == COORDS
    assert result["ua_text"] == UA_TEXT
    assert result["planet"] == 3
    assert result["galaxy"] == 0


def test_coords_with_planet_zero_are_not_teleportable():
    result = convert_address(COORDS, planet=0)
    assert result["ok"] is True
    assert result["coords"] == COORDS
    assert result["glyphs"] is None
    assert result["ua_text"] == "0x11200F19BDCE5"
    assert result["planet"] == 0
    assert result["teleportable"] is False
    assert result["warning"] == PLANET_UNKNOWN


def test_ua_with_planet_zero_is_unknown_planet():
    result = convert_address("0x11200F19BDCE5")
    assert result["ok"] is True
    assert result["glyphs"] is None
    assert result["coords"] == COORDS
    assert result["warning"] == PLANET_UNKNOWN
    assert result["teleportable"] is False


def test_galaxy_center_glyphs_are_decodable_but_not_teleportable():
    result = convert_address("000000000000")
    assert result["ok"] is True
    assert result["ua_text"] == "0x0"
    assert result["coords"] == "07FF:007F:07FF:0000"
    assert result["warning"] == PLANET_UNKNOWN


@pytest.mark.parametrize("text, planet, needle", [
    ("", 1, "请输入"),
    ("1043", 1, "12 位"),
    ("1043FEE6992G", 1, "0-9"),
    ("000000000001", 1, "1–6"),
    ("not-an-address", 1, "0-9"),
    ("04E4:0100:01BC:0104", 1, "Y 段"),
    ("04E4:0070:01BC", 1, ""),           # 3 段合法，系统默认 0
    ("XYZ", 1, "3 或 4 段"),
    ("0xZZ", 1, "0x…"),
    ("0x10000000000000000", 1, "64 位"),
])
def test_invalid_inputs_report_clear_reasons(text, planet, needle):
    result = convert_address(text, planet=planet)
    if needle:
        assert result["ok"] is False
        assert needle in result["message"]
    else:
        assert result["ok"] is True
        assert result["coords"].endswith(":0000")


def test_invalid_planet_choice_is_rejected():
    result = convert_address(COORDS, planet=9)
    assert result["ok"] is False
    assert "0–6" in result["message"]


def test_classify_address_input_covers_four_kinds():
    assert classify_address_input("  ")["kind"] == "empty"
    glyph = classify_address_input(GLYPHS)
    assert glyph["kind"] == "glyphs" and glyph["value"] == GLYPHS
    coords = classify_address_input(COORDS)
    assert coords["kind"] == "coords" and coords["value"] == COORDS
    ua = classify_address_input(UA_TEXT)
    assert ua["kind"] == "ua" and ua["value"] == UA_VALUE
    invalid = classify_address_input("not-an-address")
    assert invalid["kind"] == "glyphs" and invalid["message"]


# ---------------------------------------------------------------- UI 用例


@pytest.fixture()
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class FakeServices:
    def glyph_strip_png(self, glyphs: str) -> bytes:
        return b""


def _sync_worker(fn, on_done=None, on_error=None, *args, **kwargs):
    try:
        res = fn(*args, **kwargs)
    except Exception as e:                                  # noqa: BLE001
        if on_error is not None:
            on_error(f"{type(e).__name__}: {e}")
        return
    if on_done is not None:
        on_done(res)


def _make_page(monkeypatch):
    from starforge.app.pages import galaxy as page_mod

    monkeypatch.setattr(page_mod, "get_services", lambda: FakeServices())
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    page = page_mod.GalaxyPage()
    page.tabs.setCurrentWidget(page.address_page)
    return page


def _submit(page, text: str, planet: int = 3) -> None:
    page.addr_input.setText(text)
    index = page.addr_planet.findData(planet)
    assert index >= 0
    page.addr_planet.setCurrentIndex(index)
    page.primary_btn.click()


def test_ui_coords_produce_all_three_forms(qapp, monkeypatch):
    page = _make_page(monkeypatch)
    assert page.primary_btn.text() == "转换地址"

    _submit(page, COORDS, planet=3)

    assert page.addr_glyphs_edit.text() == GLYPHS
    assert page.addr_coords_edit.text() == COORDS
    assert page.addr_ua_edit.text() == UA_TEXT
    assert page._addr_teleportable is True
    assert page.addr_fill.isEnabled() is True
    assert page.addr_glyphs_copy.isEnabled() is True
    assert "转换完成" in page.status.text()
    assert "可分别复制" in page.status.text()


def test_ui_glyphs_fill_coords_ua_and_planet(qapp, monkeypatch):
    page = _make_page(monkeypatch)
    _submit(page, GLYPHS, planet=1)

    assert page.addr_coords_edit.text() == COORDS
    assert page.addr_ua_edit.text() == UA_TEXT
    assert page.addr_planet.currentData() == 3


def test_ui_ua_fills_glyphs_and_coords(qapp, monkeypatch):
    page = _make_page(monkeypatch)
    _submit(page, UA_TEXT, planet=1)

    assert page.addr_glyphs_edit.text() == GLYPHS
    assert page.addr_coords_edit.text() == COORDS
    assert page.addr_ua_edit.text() == UA_TEXT


def test_ui_planet_zero_marks_unknown_and_disables_teleport(qapp, monkeypatch):
    page = _make_page(monkeypatch)
    _submit(page, COORDS, planet=0)

    assert page.addr_glyphs_edit.text() == "—"
    assert page.addr_coords_edit.text() == COORDS
    assert page.addr_ua_edit.text() == "0x11200F19BDCE5"
    assert page.addr_note.isHidden() is False
    assert page.addr_note.text() == PLANET_UNKNOWN
    assert page.addr_fill.isEnabled() is False
    assert page.addr_glyphs_copy.isEnabled() is False
    assert page.addr_coords_copy.isEnabled() is True
    assert page.addr_ua_copy.isEnabled() is True


def test_ui_invalid_input_shows_reason_without_crashing(qapp, monkeypatch):
    page = _make_page(monkeypatch)
    _submit(page, "not-an-address", planet=1)

    assert page.status.text().startswith("地址转换失败：")
    assert "0-9" in page.status.text()
    assert page.addr_glyphs_edit.text() == ""
    assert page.addr_fill.isEnabled() is False


def test_ui_copy_buttons_write_expected_values(qapp, monkeypatch):
    from PySide6.QtGui import QGuiApplication

    page = _make_page(monkeypatch)
    _submit(page, COORDS, planet=3)

    page.addr_coords_copy.click()
    assert QGuiApplication.clipboard().text() == COORDS
    page.addr_glyphs_copy.click()
    assert QGuiApplication.clipboard().text() == GLYPHS
    page.addr_ua_copy.click()
    assert QGuiApplication.clipboard().text() == UA_TEXT
