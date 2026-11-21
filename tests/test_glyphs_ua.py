"""符文串换算：UA ↔ 12 位符文必须按**位段**重排，不能把十六进制位直接截 12 位。

背景（handbook 01 卷第 6 章实测）：`0x11200F19BDCE5` 的符文是 `1112F19BDCE5`，
而"取低 12 位"会得到 `1200F19BDCE5`——丢 system 最高半字节、且不插行星位。
"""
from starforge import glyphs as g

UA = 0x11200F19BDCE5
GLYPHS = "1112F19BDCE5"


def test_ua_int_to_glyphs():
    assert g.digits_for(UA) == GLYPHS


def test_ua_hex_string_to_glyphs():
    assert g.digits_for("0x11200F19BDCE5") == GLYPHS
    assert g.digits_for("0X11200F19BDCE5") == GLYPHS


def test_glyph_string_passthrough():
    assert g.digits_for(GLYPHS) == GLYPHS
    assert g.digits_for(GLYPHS.lower()) == GLYPHS


def test_twelve_digit_0x_stays_glyph():
    """12 位十六进制有歧义：历史行为当符文串，保持兼容（UA 真实长度通常 >12 位）。"""
    assert g.digits_for("0x1043FEE69929") == "1043FEE69929"


def test_roundtrip_against_upstream_layout():
    """与上游 describe() 的字段语义一致：planet/system/y/z/x 各取自己那段。"""
    u = g.unpack_ua(UA)
    assert u["system"] == 0x112
    s = g.glyphs_for_ua(UA)
    assert s[1:4] == "%03X" % (u["system"] & 0xFFF)
    assert s[4:6] == "%02X" % (u["y"] & 0xFF)
    assert s[6:9] == "%03X" % (u["z"] & 0xFFF)
    assert s[9:12] == "%03X" % (u["x"] & 0xFFF)


def test_panel_payload_reports_12_digits():
    p = g.panel_payload(UA)
    assert p["glyphs"] == GLYPHS and len(p["digits"]) == 12
    assert p["icons"][0] == f"/api/glyphs/{GLYPHS[0]}.png"
