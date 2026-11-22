"""地址互转的纯数学层：UA ↔ 银河坐标 ↔ 12 位传送门符文。

本模块**不读存档、不碰游戏进程、不依赖 numpy**，只做位段与进制的换算，方便
地址工作台、发现索引和测试共用同一套规则。实现依据是本仓库已验证的 UA 布局
（``glyphs.unpack_ua``）与公开的传送门字段顺序，未复制任何上游项目代码。

术语与约定：

* **UA**：``x(12) + z(12) + y(8) + galaxy(8) + system(12) + planet(4)``，
  最多 56 位。voxel 的 x/z 是 12 位有符号数，y 是 8 位有符号数。
* **portal code**：12 位十六进制，字段顺序是
  ``planet(1) + system(3) + Y(2) + Z(3) + X(3)``。
* **银河坐标**：``XXXX:YYYY:ZZZZ:SSSS``，顺序是 ``X:Y:Z:system``。
  每个字段都是 4 位十六进制；Y 实际只有低 2 位有效。
* 显示坐标的偏移：X/Z 加 ``0x7FF`` 再对 4096 取模，Y 加 ``0x7F`` 再对 256
  取模。因此银河中心（voxel 全 0、system=0）显示为
  ``07FF:007F:07FF``，全 0 的 portal code ``000000000000`` 正好对应它。
* portal code 的 X/Y/Z 字段就是 voxel 的补码位段（不做偏移），所以
  portal ``0x800`` 对应 voxel ``-2048``，显示坐标是 ``0xFFF``。

错误策略：字段越界、planet 不在 1..6、planet=0（未知/不可传送）时一律返回
``None``，不截断、不猜默认值。唯一的例外是**解码** portal code 为坐标时允许
planet 位为 0，因为坐标本身不包含行星；要再编码成 UA/portal 时必须显式给出
1..6 的 planet。
"""
from __future__ import annotations

from typing import Any

HEX = "0123456789ABCDEF"

PLANET_SHIFT = 52
PLANET_MASK = 0xF << PLANET_SHIFT

COORD_X_OFFSET = 0x7FF
COORD_Y_OFFSET = 0x7F
COORD_X_MOD = 0x1000
COORD_Y_MOD = 0x100

GALAXY_CENTER_COORDS = "07FF:007F:07FF"
GALAXY_CENTER_GLYPHS = "000000000000"

_MAX_UA = (1 << 64) - 1


# ---------------------------------------------------------------- 基础工具


def _as_int(value: Any) -> int | None:
    """int / ``0x…`` / 十进制字符串 → int；bool、空值、非法值返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text, 16) if text.lower().startswith("0x") else int(text)
        except ValueError:
            return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _bounded(value: Any, minimum: int, maximum: int) -> int | None:
    number = _as_int(value)
    if number is None or not minimum <= number <= maximum:
        return None
    return number


def _signed(value: int, bits: int) -> int:
    """把 ``bits`` 位无符号值解释成补码有符号数。"""
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >= (1 << (bits - 1)) else value


def _ua_value(value: Any, *, allow_zero: bool = True) -> int | None:
    """UA 输入归一化；允许 0 用于银河中心/系统地址解码。"""
    number = _as_int(value)
    if number is None or number < 0 or number > _MAX_UA:
        return None
    if number == 0 and not allow_zero:
        return None
    return number


def _digits12(glyphs: Any) -> str | None:
    """portal code → 12 位大写十六进制；分隔符会被忽略，长度不对返回 None。"""
    if glyphs is None:
        return None
    raw = str(glyphs).strip().upper()
    if raw.startswith("0X"):
        raw = raw[2:]
    raw = "".join(ch for ch in raw if ch in HEX)
    return raw if len(raw) == 12 else None


def _parse_coords(coords: Any) -> dict | None:
    """``X:Y:Z[:system]`` → 有符号 voxel + system；任何字段越界返回 None。"""
    if coords is None:
        return None
    text = str(coords).strip().replace("：", ":").replace(",", ":")
    if not text:
        return None
    parts = [p.strip() for p in text.split(":")] if ":" in text else text.split()
    if len(parts) not in (3, 4) or any(not p for p in parts):
        return None
    try:
        raw_x, raw_y, raw_z = (int(p, 16) for p in parts[:3])
        system = int(parts[3], 16) if len(parts) == 4 else 0
    except ValueError:
        return None
    # 显示字段的有效范围：X/Z 12 位、Y 8 位、system 12 位。
    if not (0 <= raw_x < COORD_X_MOD and 0 <= raw_z < COORD_X_MOD
            and 0 <= raw_y < COORD_Y_MOD and 0 <= system < COORD_X_MOD):
        return None
    # 显示值 → voxel：先减偏移，再按补码解释。0x0 / 0xFFF / 0x800 都是
    # 合法显示值：0x800 = +1，0xFFF = -2048（Y 的 0xFF = -128）。
    return {
        "x": _signed(raw_x - COORD_X_OFFSET, 12),
        "y": _signed(raw_y - COORD_Y_OFFSET, 8),
        "z": _signed(raw_z - COORD_X_OFFSET, 12),
        "system": system,
    }


# ---------------------------------------------------------------- UA 打包


def ua_from_parts(galaxy: Any, system: Any, voxel_x: Any, voxel_y: Any,
                  voxel_z: Any, planet: Any) -> int | None:
    """六个字段 → UA；planet 必须是 1..6，越界/未知一律返回 None。

    参数顺序按地址工作台的约定：``galaxy, system, x, y, z, planet``。
    voxel 用有符号数：x/z ∈ [-2048, 2047]，y ∈ [-128, 127]。
    """
    g = _bounded(galaxy, 0, 0xFF)
    s = _bounded(system, 0, 0xFFF)
    x = _bounded(voxel_x, -0x800, 0x7FF)
    y = _bounded(voxel_y, -0x80, 0x7F)
    z = _bounded(voxel_z, -0x800, 0x7FF)
    p = _bounded(planet, 1, 6)
    if None in (g, s, x, y, z, p):
        return None
    return ((g & 0xFF) << 32) | ((s & 0xFFF) << 40) | (x & 0xFFF) \
        | ((z & 0xFFF) << 12) | ((y & 0xFF) << 24) | ((p & 0xF) << PLANET_SHIFT)


def unpack_ua(ua: Any) -> dict:
    """UA → 有符号字段 + galaxy/system/planet；非法输入抛 ValueError。

    与 ``starforge.glyphs.unpack_ua`` 的位布局保持一致；这里单独实现是为了让
    ``address.py`` 保持零依赖（避免与 ``glyphs.py`` 的再导出形成循环导入）。
    """
    value = _ua_value(ua)
    if value is None:
        raise ValueError(f"不是合法的 UA：{ua!r}")
    return {
        "x": _signed(value & 0xFFF, 12),
        "z": _signed(value >> 12 & 0xFFF, 12),
        "y": _signed(value >> 24 & 0xFF, 8),
        "galaxy": value >> 32 & 0xFF,
        "system": value >> 40 & 0xFFF,
        "planet": value >> PLANET_SHIFT & 0xF,
    }


# ---------------------------------------------------------------- UA ↔ 坐标


def coords_from_ua(ua: Any, *, include_system: bool = True) -> str | None:
    """UA → ``XXXX:YYYY:ZZZZ[:SSSS]``；非法 UA 返回 None。

    坐标不包含 galaxy/planet，所以 planet=0 的合法系统地址也能解码。
    银河中心（UA=0）返回 ``07FF:007F:07FF:0000``。
    """
    value = _ua_value(ua)
    if value is None:
        return None
    u = unpack_ua(value)
    text = (f"{(u['x'] + COORD_X_OFFSET) % COORD_X_MOD:04X}:"
            f"{(u['y'] + COORD_Y_OFFSET) % COORD_Y_MOD:04X}:"
            f"{(u['z'] + COORD_X_OFFSET) % COORD_X_MOD:04X}")
    return f"{text}:{u['system']:04X}" if include_system else text


def ua_from_coords(coords: Any, planet: Any = 1, *, galaxy: Any = 0) -> int | None:
    """``XXXX:YYYY:ZZZZ[:SSSS]`` + galaxy/planet → UA；任一项不合法返回 None。

    planet=0 表示未知/不可传送，按约定返回 None，不猜一个行星位。
    galaxy 不在坐标里，必须由调用方显式给出（默认 0 = Euclid）。
    """
    parsed = _parse_coords(coords)
    g = _bounded(galaxy, 0, 0xFF)
    p = _bounded(planet, 1, 6)
    if parsed is None or g is None or p is None:
        return None
    return ua_from_parts(g, parsed["system"], parsed["x"], parsed["y"],
                         parsed["z"], p)


# ---------------------------------------------------------------- 坐标 ↔ 符文


def glyphs_from_coords(coords: Any, planet: Any = 1, *, galaxy: Any = 0) -> str | None:
    """``XXXX:YYYY:ZZZZ[:SSSS]`` + planet → 12 位 portal code。

    planet 必须 1..6；galaxy 不进入 portal code，只做范围校验（默认 0）。
    字段全部按有符号 voxel 的补码位段写入，与 ``glyphs.glyphs_for_ua`` 一致。
    """
    parsed = _parse_coords(coords)
    p = _bounded(planet, 1, 6)
    g = _bounded(galaxy, 0, 0xFF)
    if parsed is None or p is None or g is None:
        return None
    return (f"{p:X}{parsed['system'] & 0xFFF:03X}"
            f"{parsed['y'] & 0xFF:02X}{parsed['z'] & 0xFFF:03X}"
            f"{parsed['x'] & 0xFFF:03X}")


def coords_from_glyphs(glyphs: Any, *, galaxy: Any = 0,
                       include_system: bool = True) -> str | None:
    """12 位 portal code → ``XXXX:YYYY:ZZZZ[:SSSS]``；非法符文返回 None。

    解码坐标不需要 planet，因此 ``000000000000`` 能还原成银河中心
    ``07FF:007F:07FF:0000``；但 planet 位大于 6 的串不是合法门地址，仍返回 None。
    galaxy 不参与计算，只做范围校验（默认 0）。
    """
    digits = _digits12(glyphs)
    g = _bounded(galaxy, 0, 0xFF)
    if digits is None or g is None or int(digits[0], 16) > 6:
        return None
    planet = int(digits[0], 16)
    if planet == 0 and digits != GALAXY_CENTER_GLYPHS:
        # planet 位为 0 只用于全 0 的银河中心；其他“无行星”门地址不猜坐标。
        return None
    system = int(digits[1:4], 16)
    y = int(digits[4:6], 16)
    z = int(digits[6:9], 16)
    x = int(digits[9:12], 16)
    vx = _signed(x, 12)
    vy = _signed(y, 8)
    vz = _signed(z, 12)
    text = (f"{(vx + COORD_X_OFFSET) % COORD_X_MOD:04X}:"
            f"{(vy + COORD_Y_OFFSET) % COORD_Y_MOD:04X}:"
            f"{(vz + COORD_X_OFFSET) % COORD_X_MOD:04X}")
    return f"{text}:{system:04X}" if include_system else text


def ua_from_glyphs(glyphs: Any, *, galaxy: Any = 0) -> int | None:
    """12 位 portal code + galaxy → UA；planet 必须是 1..6。"""
    digits = _digits12(glyphs)
    g = _bounded(galaxy, 0, 0xFF)
    if digits is None or g is None:
        return None
    p = int(digits[0], 16)
    if not 1 <= p <= 6:
        return None
    return ua_from_parts(g, int(digits[1:4], 16), _signed(int(digits[9:12], 16), 12),
                         _signed(int(digits[4:6], 16), 8),
                         _signed(int(digits[6:9], 16), 12), p)


def glyphs_for_ua(ua: Any, planet: Any = 1) -> str | None:
    """UA + 外部 planet → portal code；与 ``glyphs.glyphs_for_ua`` 同源。

    UA 自己的 planet 位可能是 0（常见），所以允许调用方显式覆盖；planet 必须 1..6。
    """
    value = _ua_value(ua)
    p = _bounded(planet, 1, 6)
    if value is None or p is None:
        return None
    u = unpack_ua(value)
    return (f"{p:X}{u['system'] & 0xFFF:03X}{u['y'] & 0xFF:02X}"
            f"{u['z'] & 0xFFF:03X}{u['x'] & 0xFFF:03X}")


__all__ = [
    "COORD_X_OFFSET",
    "COORD_Y_OFFSET",
    "GALAXY_CENTER_COORDS",
    "GALAXY_CENTER_GLYPHS",
    "PLANET_MASK",
    "PLANET_SHIFT",
    "coords_from_glyphs",
    "coords_from_ua",
    "glyphs_for_ua",
    "glyphs_from_coords",
    "ua_from_coords",
    "ua_from_glyphs",
    "ua_from_parts",
    "unpack_ua",
]
