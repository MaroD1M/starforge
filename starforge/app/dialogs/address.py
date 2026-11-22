"""地址工作台的输入校验与三种形态互转（纯函数，便于单独测试）。

三种输入形态：

* 12 位传送门符文（``1..6`` + system/Y/Z/X 的位段）；
* 银河坐标 ``X:Y:Z:SSSS``（每段十六进制）；
* ``0x…`` 宇宙地址（UA）。

输出始终包含「符文 / 坐标 / UA」三行。坐标本身不含行星位，所以调用方要显式
传 ``planet``；``planet=0`` 表示未知行星，只输出坐标与系统级 UA，并标注不可传送。
所有换算都走 ``starforge.address`` 的纯数学层，界面不再自己拼位段。
"""
from __future__ import annotations

import re

from ... import address as address_mod
from ...address import PLANET_MASK

GLYPH_LENGTH = 12
MAX_SEED = 0xFFFFFFFFFFFFFFFF
MAX_UA = 0xFFFFFFFFFFFFFFFF

GLYPH_FORMAT = "符文串必须是 12 位十六进制，且第 1 位（行星）为 1–6。"
COORD_FORMAT = (
    "坐标格式：X:Y:Z:SSSS（十六进制；X/Z 0000–0FFF，Y 0000–00FF，系统 0000–0FFF）。")
UA_FORMAT = "UA 必须形如 0x… 的十六进制（最多 16 位）。"
PLANET_UNKNOWN = "未知行星，不可传送"

_HEX = re.compile(r"^[0-9A-F]+$")
_SPACED_COORD = re.compile(r"^[0-9A-Fa-f]{3,4}(?:\s+[0-9A-Fa-f]{3,4}){3}$")
_COORD_MARK = re.compile(
    r"[:\uFF1A,;\uFF0C]|\b[XYZxyz]\s*[:=]|\b[XYZxyz]\s*[-+]?\d|^\s*(?:xyz|coords?|坐标)\b",
    re.IGNORECASE)


def normalize_glyphs(text: str) -> str:
    """把 glyphs 输入规范成 12 位大写十六进制；不合法时抛 ValueError。"""
    raw = str(text or "").strip()
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    compact = re.sub(r"[\s_-]+", "", raw)
    if not compact:
        raise ValueError("请输入 12 位符文（0-9 / A-F）。")
    if len(compact) != GLYPH_LENGTH:
        raise ValueError(f"符文必须是 12 位十六进制（当前 {len(compact)} 位）。")
    glyphs = compact.upper()
    if not _HEX.fullmatch(glyphs):
        raise ValueError("符文只能包含 0-9 和 A-F。")
    return glyphs


def parse_seed(text: str) -> int:
    """解析 0x… 十六进制种子（也接受十进制/无前缀十六进制）；不合法时抛 ValueError。

    这是「种子反查」这个次要动作的输入解析，不是地址三形态之一。
    """
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("请输入种子，例如 0x0123456789ABCDEF。")
    if raw.startswith(("+", "-")):
        raise ValueError("种子不能为负数，请使用 0x… 或无符号数值。")
    if raw.lower().startswith("0x"):
        body = raw[2:]
        if not body or not _HEX.fullmatch(body.upper()):
            raise ValueError("种子必须是 0x… 十六进制，例如 0x0123456789ABCDEF。")
        value = int(body, 16)
    elif re.fullmatch(r"[0-9]+", raw):
        value = int(raw, 10)
    elif re.fullmatch(r"[0-9A-Fa-f]+", raw):
        value = int(raw, 16)
    else:
        raise ValueError("种子必须是 0x… 十六进制，例如 0x0123456789ABCDEF。")
    if value > MAX_SEED:
        raise ValueError("种子超出 64 位范围（最大 0xFFFFFFFFFFFFFFFF）。")
    return value


def looks_like_coordinate_input(text: str) -> bool:
    """识别坐标文本（如 04E4:0070:01BC:0104 或 X:1 Y:2 Z:3）。"""
    raw = str(text or "").strip()
    if not raw:
        return False
    return bool(_COORD_MARK.search(raw) or _SPACED_COORD.fullmatch(raw))


def _planet_number(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 6 else None


def _galaxy_number(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 0xFF else None


def _parse_coords_text(text: str) -> tuple[str | None, str]:
    """坐标文本 → ``XXXX:YYYY:ZZZZ:SSSS``；失败时返回 ``(None, 原因)``。"""
    raw = str(text or "").strip()
    raw = (raw.replace("：", ":").replace(",", ":").replace("，", ":")
           .replace(";", ":").replace("；", ":"))
    parts = [part.strip() for part in raw.split(":")] if ":" in raw else raw.split()
    if len(parts) == 3:
        parts.append("0")
    if len(parts) != 4:
        return None, f"坐标必须包含 3 或 4 段。{COORD_FORMAT}"
    names = (("X", 0xFFF, 4), ("Y", 0xFF, 2), ("Z", 0xFFF, 4), ("系统", 0xFFF, 4))
    values: list[int] = []
    for part, (label, maximum, width) in zip(parts, names):
        if not part:
            return None, f"坐标 {label} 段为空。{COORD_FORMAT}"
        try:
            value = int(part, 16)
        except ValueError:
            return None, f"坐标 {label} 段不是十六进制：{part!r}。{COORD_FORMAT}"
        if not 0 <= value <= maximum:
            return None, (
                f"坐标 {label} 段超出范围 0–{maximum:0{width}X}（收到 {part}）。")
        values.append(value)
    x, y, z, system = values
    return f"{x:04X}:{y:04X}:{z:04X}:{system:04X}", ""


def _result(kind: str, *, glyphs: str | None = None, coords: str | None = None,
            ua: int | None = None, planet: int = 0, galaxy: int = 0,
            warning: str = "") -> dict:
    planet_known = 1 <= int(planet) <= 6
    return {
        "ok": True,
        "kind": kind,
        "glyphs": glyphs,
        "coords": coords,
        "ua": ua,
        "ua_text": None if ua is None else f"0x{int(ua):X}",
        "planet": int(planet),
        "planet_known": planet_known,
        "galaxy": int(galaxy),
        "teleportable": bool(planet_known and glyphs),
        "warning": warning,
        "message": "",
    }


def _failure(kind: str, message: str) -> dict:
    return {
        "ok": False,
        "kind": kind,
        "glyphs": None,
        "coords": None,
        "ua": None,
        "ua_text": None,
        "planet": 0,
        "planet_known": False,
        "galaxy": 0,
        "teleportable": False,
        "warning": "",
        "message": str(message or "无法识别输入。"),
    }


def _from_glyphs(raw: str, galaxy: int) -> dict:
    try:
        digits = normalize_glyphs(raw)
    except ValueError as e:
        return _failure("glyphs", str(e))
    if digits == address_mod.GALAXY_CENTER_GLYPHS:
        coords = address_mod.coords_from_glyphs(digits)
        if coords is None:
            return _failure("glyphs", "银河中心符文无法换算成坐标。")
        return _result("glyphs", glyphs=digits, coords=coords, ua=0,
                       planet=0, galaxy=galaxy, warning=PLANET_UNKNOWN)
    planet = int(digits[0], 16)
    if not 1 <= planet <= 6:
        return _failure(
            "glyphs",
            "符文第 1 位是行星编号，必须是 1–6（0 只用于银河中心 000000000000）。")
    ua = address_mod.ua_from_glyphs(digits, galaxy=galaxy)
    coords = address_mod.coords_from_glyphs(digits, galaxy=galaxy)
    if ua is None or coords is None:
        return _failure("glyphs", "符文里的门地址字段超出范围，无法换算。")
    return _result("glyphs", glyphs=digits, coords=coords, ua=ua,
                   planet=planet, galaxy=galaxy)


def _from_coords(raw: str, planet: int, galaxy: int) -> dict:
    coords, reason = _parse_coords_text(raw)
    if coords is None:
        return _failure("coords", reason)
    if 1 <= planet <= 6:
        ua = address_mod.ua_from_coords(coords, planet=planet, galaxy=galaxy)
        glyphs = address_mod.glyphs_from_coords(coords, planet=planet, galaxy=galaxy)
        if ua is None or glyphs is None:
            return _failure("coords", "坐标无法换算成 UA/符文，请检查字段范围。")
        return _result("coords", glyphs=glyphs, coords=address_mod.coords_from_ua(ua),
                       ua=ua, planet=planet, galaxy=galaxy)
    # planet=0：坐标仍然有效，只是不能生成门地址；保留系统级 UA（行星位为 0）。
    probe = address_mod.ua_from_coords(coords, planet=1, galaxy=galaxy)
    if probe is None:
        return _failure("coords", "坐标无法换算成 UA，请检查字段范围。")
    ua = probe & ~PLANET_MASK
    return _result("coords", coords=address_mod.coords_from_ua(ua), ua=ua,
                   planet=0, galaxy=galaxy, warning=PLANET_UNKNOWN)


def _from_ua(raw: str) -> dict:
    body = raw[2:].strip()
    if not body:
        return _failure("ua", f"UA 缺少 0x 后的十六进制数字。{UA_FORMAT}")
    try:
        value = int(body, 16)
    except ValueError:
        return _failure("ua", f"UA 必须是 0x… 十六进制（收到 {raw!r}）。")
    if not 0 <= value <= MAX_UA:
        return _failure("ua", "UA 超出 64 位范围。")
    try:
        fields = address_mod.unpack_ua(value)
    except ValueError as e:
        return _failure("ua", str(e))
    planet = int(fields.get("planet") or 0)
    galaxy = int(fields.get("galaxy") or 0)
    coords = address_mod.coords_from_ua(value)
    if coords is None:
        return _failure("ua", "UA 无法换算成坐标。")
    if planet == 0:
        return _result("ua", coords=coords, ua=value, planet=0, galaxy=galaxy,
                       warning=PLANET_UNKNOWN)
    if not 1 <= planet <= 6:
        return _result(
            "ua", coords=coords, ua=value, planet=planet, galaxy=galaxy,
            warning=f"UA 行星位为 {planet}（应在 0–6），不可传送。")
    glyphs = address_mod.glyphs_for_ua(value, planet)
    return _result("ua", glyphs=glyphs, coords=coords, ua=value,
                   planet=planet, galaxy=galaxy)


def convert_address(text: str, planet: int = 1, *, galaxy: int = 0) -> dict:
    """把任意一种地址输入换算成符文/坐标/UA 三形态。

    ``planet`` 只对坐标输入生效；符文/UA 自带行星位。``planet=0`` 合法，但
    结果会标注「未知行星，不可传送」。非法输入返回 ``ok=False`` 和明确原因。
    """
    raw = str(text or "").strip()
    if not raw:
        return _failure("empty", "请输入 12 位符文、X:Y:Z:SSSS 坐标或 0x… UA。")
    planet_number = _planet_number(planet)
    if planet_number is None:
        return _failure("invalid", "行星位必须是 0–6（0 = 未知，不可传送）。")
    galaxy_number = _galaxy_number(galaxy)
    if galaxy_number is None:
        return _failure("invalid", "银河编号必须是 0–255。")
    if raw.lower().startswith("0x"):
        return _from_ua(raw)
    if looks_like_coordinate_input(raw):
        return _from_coords(raw, planet_number, galaxy_number)
    return _from_glyphs(raw, galaxy_number)


def classify_address_input(text: str, *, planet: int = 1,
                           galaxy: int = 0) -> dict:
    """按输入形态分类：empty / glyphs / coords / ua / invalid。

    ``value`` 是规范化后的输入：glyphs 为大写 12 位、coords 为四段坐标、
    ua 为整数。无法识别时 ``message`` 给出明确原因。
    """
    raw = str(text or "").strip()
    if not raw:
        return {"kind": "empty", "value": None,
                "message": "请输入 12 位符文、X:Y:Z:SSSS 坐标或 0x… UA。"}
    result = convert_address(raw, planet=planet, galaxy=galaxy)
    if result["ok"]:
        kind = result["kind"]
        value = result["ua"] if kind == "ua" else (
            result["glyphs"] if kind == "glyphs" else result["coords"])
        return {"kind": kind, "value": value, "message": "", "result": result}
    kind = result["kind"] if result["kind"] in ("empty", "glyphs", "coords", "ua") \
        else "invalid"
    return {"kind": kind, "value": raw, "message": result["message"],
            "result": result}


__all__ = [
    "COORD_FORMAT",
    "GLYPH_FORMAT",
    "MAX_SEED",
    "PLANET_UNKNOWN",
    "UA_FORMAT",
    "classify_address_input",
    "convert_address",
    "looks_like_coordinate_input",
    "normalize_glyphs",
    "parse_seed",
]
