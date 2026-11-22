"""符文串换算：UA ↔ 12 位符文必须按**位段**重排，不能把十六进制位直接截 12 位。

背景（handbook 01 卷第 6 章实测）：`0x11200F19BDCE5` 的符文是 `1112F19BDCE5`，
而"取低 12 位"会得到 `1200F19BDCE5`——丢 system 最高半字节、且不插行星位。
"""
import random

from starforge import address
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


# ---------------------------------------------------------------- 坐标 ↔ UA ↔ 符文


def test_ua_parts_roundtrip_random_10000():
    """随机 10,000 个合法地址：六字段 ↔ UA ↔ 坐标 ↔ 符文必须完全一致。"""
    rng = random.Random(20261122)
    for _ in range(10_000):
        galaxy = rng.randrange(0x100)
        system = rng.randrange(0x1000)
        x = rng.randrange(-0x800, 0x800)
        y = rng.randrange(-0x80, 0x80)
        z = rng.randrange(-0x800, 0x800)
        planet = rng.randrange(1, 7)

        ua = address.ua_from_parts(galaxy, system, x, y, z, planet)
        assert ua is not None
        packed = address.unpack_ua(ua)
        assert (packed["galaxy"], packed["system"], packed["x"], packed["y"],
                packed["z"], packed["planet"]) == (galaxy, system, x, y, z, planet)

        coords = address.coords_from_ua(ua)
        assert coords is not None
        assert address.ua_from_coords(coords, planet, galaxy=galaxy) == ua

        glyphs = address.glyphs_from_coords(coords, planet, galaxy=galaxy)
        assert glyphs == g.glyphs_for_ua(ua, planet)
        assert address.ua_from_glyphs(glyphs, galaxy=galaxy) == ua
        assert address.coords_from_glyphs(glyphs) == coords


def test_galaxy_center_invariant_and_unknown_planet():
    """银河中心：全 0 符文 ↔ 07FF:007F:07FF；planet=0 不可编码。"""
    assert address.coords_from_glyphs(address.GALAXY_CENTER_GLYPHS) == \
        "07FF:007F:07FF:0000"
    assert address.coords_from_glyphs(address.GALAXY_CENTER_GLYPHS,
                                      include_system=False) == address.GALAXY_CENTER_COORDS
    assert address.coords_from_ua(0) == "07FF:007F:07FF:0000"

    # planet=0 表示未知：所有“编码成 UA/门地址”的入口都返回 None，不猜。
    assert address.ua_from_parts(0, 0, 0, 0, 0, 0) is None
    assert address.ua_from_coords(address.GALAXY_CENTER_COORDS, planet=0) is None
    assert address.glyphs_from_coords(address.GALAXY_CENTER_COORDS, planet=0) is None
    assert address.ua_from_glyphs(address.GALAXY_CENTER_GLYPHS) is None
    # 显式给出合法 planet 时，同一位置可以正常编码。
    assert address.glyphs_from_coords(address.GALAXY_CENTER_COORDS, planet=1) == \
        "100000000000"


def test_coords_boundary_values_0_fff_800():
    """显示坐标 0x000/0x800/0xFFF 与 portal 位段 0x800 的边界含义。"""
    # 显示 0x800 = +1；0xFFF = -2048（12 位补码的最小值）。
    plus_one = address.ua_from_coords("0800:0080:0800:0000", 1)
    assert plus_one is not None
    assert address.unpack_ua(plus_one)["x"] == 1
    assert address.unpack_ua(plus_one)["y"] == 1
    assert address.unpack_ua(plus_one)["z"] == 1

    minus_min = address.ua_from_coords("0FFF:007F:07FF:0000", 1)
    assert minus_min is not None
    assert address.unpack_ua(minus_min)["x"] == -0x800
    assert address.glyphs_from_coords("0FFF:007F:07FF:0000", 1) == "100000000800"
    assert address.coords_from_glyphs("100000000800") == "0FFF:007F:07FF:0000"

    # Y 的 0x00FF = -128，portal 的 Y 位段是 0x80。
    y_min = address.ua_from_coords("07FF:00FF:07FF:0000", 1)
    assert y_min is not None
    assert address.unpack_ua(y_min)["y"] == -0x80
    glyph = address.glyphs_from_coords("07FF:00FF:07FF:0000", 1)
    assert glyph == "100080000000"
    assert address.coords_from_glyphs(glyph) == "07FF:00FF:07FF:0000"


def test_out_of_range_inputs_return_none():
    # planet 必须 1..6
    for planet in (0, 7, 15, -1):
        assert address.ua_from_parts(0, 0, 0, 0, 0, planet) is None
        assert address.ua_from_coords("07FF:007F:07FF:0000", planet) is None
        assert address.glyphs_from_coords("07FF:007F:07FF:0000", planet) is None
    # galaxy/system/voxel 越界
    assert address.ua_from_parts(0x100, 0, 0, 0, 0, 1) is None
    assert address.ua_from_parts(0, 0x1000, 0, 0, 0, 1) is None
    assert address.ua_from_parts(0, 0, 0x800, 0, 0, 1) is None
    assert address.ua_from_parts(0, 0, 0, 0x80, 0, 1) is None
    assert address.ua_from_parts(0, 0, 0, 0, -0x801, 1) is None
    # 坐标字段越界：X/Z 必须 < 0x1000，Y 必须 < 0x100，system 必须 < 0x1000
    assert address.ua_from_coords("1000:007F:07FF:0000", 1) is None
    assert address.ua_from_coords("07FF:0100:07FF:0000", 1) is None
    assert address.ua_from_coords("07FF:007F:07FF:1000", 1) is None
    # 符文长度/字符/planet 位非法
    for bad in (None, "", "12345", "12345678901G", "700000000000",
                "000000000001"):
        assert address.coords_from_glyphs(bad) is None


def test_coords_parser_accepts_common_separators():
    expected = address.ua_from_coords("04E4:0070:01BC:0112", 1)
    assert expected is not None
    assert address.ua_from_coords("04E4：0070：01BC：0112", 1) == expected
    assert address.ua_from_coords("04E4 0070 01BC 0112", 1) == expected
    assert address.ua_from_coords("04E4,0070,01BC,0112", 1) == expected


def test_address_helpers_match_existing_glyphs_layout():
    """新增纯函数与现有 `unpack_ua` / `glyphs_for_ua` 必须同源。"""
    samples = [0, UA, 0xFFFFFFFFFFFFFF, 0x11200F19BDCE5,
               address.ua_from_parts(7, 0xABC, -1234, -77, 987, 6)]
    for ua in samples:
        assert ua is not None
        assert address.unpack_ua(ua) == g.unpack_ua(ua)
        for planet in (1, 3, 6):
            assert address.glyphs_for_ua(ua, planet) == g.glyphs_for_ua(ua, planet)
            coords = address.coords_from_ua(ua)
            assert coords is not None
            assert address.glyphs_from_coords(coords, planet) == \
                g.glyphs_for_ua(ua, planet)

