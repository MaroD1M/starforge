"""地址工作台的输入校验与分类（纯函数，便于单独测试）。"""
from __future__ import annotations

import re

GLYPH_LENGTH = 12
MAX_SEED = 0xFFFFFFFFFFFFFFFF

_HEX = re.compile(r"^[0-9A-F]+$")
_SPACED_COORD = re.compile(r"^[0-9A-Fa-f]{3,4}(?:\s+[0-9A-Fa-f]{3,4}){3}$")
_COORD_MARK = re.compile(
    r"[:\uFF1A,;\uFF0C]|\b[XYZxyz]\s*[:=]|\b[XYZxyz]\s*[-+]?\d|^\s*(?:xyz|coords?|坐标)\b",
    re.IGNORECASE)

COORD_UNSUPPORTED = (
    "暂不支持直接解析坐标文本；需要 XYZ 格式（或先换算成 12 位 glyphs）。"
    "当前仅支持 12 位 glyphs 与 0x… 种子。"
)


def normalize_glyphs(text: str) -> str:
    """把 glyphs 输入规范成 12 位大写十六进制；不合法时抛 ValueError。"""
    raw = str(text or "").strip()
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    compact = re.sub(r"[\s_-]+", "", raw)
    if not compact:
        raise ValueError("请输入 12 位 glyphs（0-9 / A-F）。")
    if len(compact) != GLYPH_LENGTH:
        raise ValueError(f"glyphs 必须是 12 位十六进制（当前 {len(compact)} 位）。")
    glyphs = compact.upper()
    if not _HEX.fullmatch(glyphs):
        raise ValueError("glyphs 只能包含 0-9 和 A-F。")
    return glyphs


def parse_seed(text: str) -> int:
    """解析 0x… 十六进制种子（也接受十进制/无前缀十六进制）；不合法时抛 ValueError。"""
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


def classify_address_input(text: str) -> dict:
    """按输入形态分类：empty / glyphs / seed / coords / invalid。"""
    raw = str(text or "").strip()
    if not raw:
        return {"kind": "empty", "value": None,
                "message": "请输入 12 位 glyphs 或 0x… 种子。"}
    if looks_like_coordinate_input(raw):
        return {"kind": "coords", "value": raw, "message": COORD_UNSUPPORTED}
    if raw.lower().startswith("0x"):
        try:
            seed = parse_seed(raw)
        except ValueError as e:
            return {"kind": "invalid", "value": raw, "message": str(e)}
        return {"kind": "seed", "value": seed, "text": f"0x{seed:016X}", "message": ""}
    compact = re.sub(r"[\s_-]+", "", raw)
    if len(compact) == GLYPH_LENGTH and _HEX.fullmatch(compact.upper()):
        return {"kind": "glyphs", "value": compact.upper(), "message": ""}
    try:
        seed = parse_seed(raw)
    except ValueError as e:
        return {"kind": "invalid", "value": raw, "message": str(e)}
    return {"kind": "seed", "value": seed, "text": f"0x{seed:016X}", "message": ""}
