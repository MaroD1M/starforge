"""外观涂装：从种子里解出真实配色（用 Shipwright 的 textures.ship_look）。

这一步让 3D/缩略图的颜色来自游戏数据本身，而不是写死的灰蓝色。
缺游戏文件时返回 {}，调用方退回默认色。
"""
from __future__ import annotations

from .core import log, paths

log = log.get("paint")

_CACHE: dict[tuple[str, str], dict] = {}

# 材质类 → 用哪个颜色槽
MAP = {"paint": "primary", "secondary": "secondary", "dark": "undercoat",
       "metal": "undercoat", "glass": "undercoat"}


def look(seed: str, ship: str) -> dict[str, list[float]]:
    """→ {"paint": [r,g,b], "secondary": ..., "dark": ...}（0..1，缺省 {}）。"""
    key = (str(seed).upper(), ship)
    if key in _CACHE:
        return _CACHE[key]
    try:
        paths.ensure_shipwright_importable()
        from nms_procgen import textures
        cols = textures.ship_look(seed, ship).get("colours") or {}
        out = {}
        for cls, slot in MAP.items():
            v = cols.get(slot)
            rgb = v.get("rgb") if isinstance(v, dict) else v
            if rgb:
                out[cls] = [float(x) for x in list(rgb)[:3]]
        _CACHE[key] = out
        return out
    except Exception as e:                       # noqa: BLE001 - 没有游戏数据就退回默认色
        log.debug("取种子的配色失败（%s），用默认色", type(e).__name__)
        _CACHE[key] = {}
        return {}


def hexcol(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c * 255)))) for c in rgb[:3])
