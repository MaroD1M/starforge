"""地址工作台：输入校验/分类的纯函数。"""
from __future__ import annotations

import pytest

from starforge.app.dialogs.address import (
    COORD_UNSUPPORTED,
    classify_address_input,
    looks_like_coordinate_input,
    normalize_glyphs,
    parse_seed,
)


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
                                  "1043FEE6992G", "0x10400F19BDCE5"])
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
    "X: 1 Y: 2 Z: 3",
    "X 123 Y 45 Z 67",
    "坐标 1 2 3",
])
def test_coordinate_texts_are_detected(text):
    assert looks_like_coordinate_input(text)
    result = classify_address_input(text)
    assert result["kind"] == "coords"
    assert "暂不支持" in result["message"]
    assert "XYZ" in result["message"] or "xyz" in result["message"]


def test_classify_glyphs_seed_empty_and_invalid():
    glyph = classify_address_input("1043 FEE6 9929")
    assert glyph["kind"] == "glyphs" and glyph["value"] == "1043FEE69929"

    seed = classify_address_input("0x0123456789ABCDEF")
    assert seed["kind"] == "seed" and seed["value"] == 0x0123456789ABCDEF
    assert seed["text"] == "0x0123456789ABCDEF"

    assert classify_address_input("  ")["kind"] == "empty"
    invalid = classify_address_input("not-an-address")
    assert invalid["kind"] == "invalid" and invalid["message"]


def test_coordinate_message_is_explicit():
    assert "暂不支持" in COORD_UNSUPPORTED
    assert "XYZ" in COORD_UNSUPPORTED
