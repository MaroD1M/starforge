"""传送门符文：地址 → 12 个十六进制数字 → 图标/拼图。

关键事实（已在游戏文件里核实）：
  · 传送门符文 = 系统地址的 12 位十六进制（实测 stations.jsonl 5/5 通过）；
  · 游戏内图标：NMSARC.TexUI.pak → textures/ui/frontend/icons/update3/portalsymbol.<0-f>.dds
    16 张 256×256，DX10/DXGI 98 = BC7。BC7 解码需要额外依赖；没有依赖时退回内置位图字体，
    面板依然可用（只是不如游戏原图好看）。

对外：
  digits_for(text)   -> "1043FEE69929"
  icon_png(digit)    -> bytes|None（游戏原图，需解码器；结果缓存到磁盘）
  panel_png(glyphs)  -> bytes（12 联符文图，原图或位图字体）
"""
from __future__ import annotations

import os
import struct
import zlib
from functools import lru_cache

import numpy as np

from .core import log, paths

log = log.get("glyphs")

HEX = "0123456789ABCDEF"
TILE = 96          # 单格像素
GAP = 10

# 5×7 位图字体（0-9A-F 的十六进制字符），仅作无 BC7 解码器时的兜底
_FONT = {
    "0": (0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110),
    "1": (0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "2": (0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b01000, 0b11111),
    "3": (0b11110, 0b00001, 0b00001, 0b01110, 0b00001, 0b00001, 0b11110),
    "4": (0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010),
    "5": (0b11111, 0b10000, 0b11110, 0b00001, 0b00001, 0b10001, 0b01110),
    "6": (0b00110, 0b01000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110),
    "7": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000),
    "8": (0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110),
    "9": (0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00010, 0b01100),
    "A": (0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "B": (0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110),
    "C": (0b01110, 0b10001, 0b10000, 0b10000, 0b10000, 0b10001, 0b01110),
    "D": (0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110),
    "E": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111),
    "F": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000),
}


def digits_for(text: str | int) -> str:
    """接受 12 位 glyph 串、UA 整数、或 0x… 十六进制，统一成 12 位大写十六进制。"""
    if isinstance(text, int):
        text = "0x%X" % text
    s = str(text).strip().upper()
    if s.startswith("0X"):
        s = s[2:]
    if not s or any(c not in HEX for c in s):
        raise ValueError(f"不是合法的地址/glyph 串：{text!r}")
    if len(s) > 12:
        s = s[-12:]
    return s.rjust(12, "0")


def png_bytes(rgb: np.ndarray) -> bytes:
    """rgb: (h,w,3) uint8 → PNG。"""
    h, w = rgb.shape[:2]
    raw = np.concatenate([np.zeros((h, 1), np.uint8), rgb.reshape(h, w * 3)], axis=1).tobytes()

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def _draw_char(ch: str, scale: int = 10, fg=(0.82, 0.87, 0.95), bg=(0.05, 0.06, 0.08)) -> np.ndarray:
    rows = _FONT.get(ch, _FONT["0"])
    img = np.zeros((7 * scale, 5 * scale, 3), np.float32) + np.array(bg, np.float32)
    for y, bits in enumerate(rows):
        for x in range(5):
            if bits & (1 << (4 - x)):
                img[y * scale:(y + 1) * scale, x * scale:(x + 1) * scale] = fg
    return img


def _icon_dir() -> str:
    d = paths.cache_dir() / "glyphs"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _pak_path() -> str | None:
    """定位 NMSARC.TexUI.pak（含 portalsymbol.<0-f>.dds）。"""
    from .core import settings
    cands = []
    s = settings.current()
    if s.game_dir:
        cands.append(os.path.join(s.game_dir, "GAMEDATA", "PCBANKS", "NMSARC.TexUI.pak"))
    gd = s.gamedata_resolved()
    if gd:
        cands += [os.path.join(os.path.dirname(str(gd)), "PCBANKS", "NMSARC.TexUI.pak"),
                  os.path.join(str(gd), "PCBANKS", "NMSARC.TexUI.pak")]
    env = os.environ.get("NMS_DIR")
    if env:
        cands.append(os.path.join(env, "GAMEDATA", "PCBANKS", "NMSARC.TexUI.pak"))
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def _decode_dds(data: bytes) -> tuple[int, int, bytes]:
    """DDS → (w, h, RGBA)。DX10/BC7 走 texture2ddecoder；DXT1/3/5 走自带解码器。"""
    h = struct.unpack_from("<I", data, 12)[0]
    w = struct.unpack_from("<I", data, 16)[0]
    fourcc = data[84:88]
    if fourcc == b"DX10":
        dxgi = struct.unpack_from("<I", data, 128)[0]
        if dxgi in (98, 99):                       # BC7 / BC7_SRGB
            import texture2ddecoder
            return w, h, texture2ddecoder.decode_bc7(data[148:], w, h)
        raise NotImplementedError(f"DXGI {dxgi}")
    from . import dds as dds_mod
    w2, h2, rgba = dds_mod.decode_dds(data)
    return w2, h2, rgba.tobytes()


_ICON_CACHE: dict[tuple[str, int], np.ndarray] = {}       # 只缓存成功结果（负结果会因设置变化而失效）


def icon_rgb(digit: str, size: int = 96) -> np.ndarray | None:
    """游戏原版符文 → (size,size,3) float32；缺依赖/缺 pak 返回 None（不缓存失败）。"""
    digit = str(digit).upper()
    hit = _ICON_CACHE.get((digit, size))
    if hit is not None:
        return hit
    pak = _pak_path()
    if not pak or len(digit) != 1 or digit not in HEX:
        return None
    try:
        from hgpaktool import HGPAKFile
        want = f"textures/ui/frontend/icons/update3/portalsymbol.{digit.lower()}.dds"
        with HGPAKFile(pak) as f:
            blob = dict(f.extract(filters=[want]))
        data = next(iter(blob.values()))
        w, h, rgba_bytes = _decode_dds(data)
        rgba = np.frombuffer(rgba_bytes, np.uint8).reshape(h, w, 4).astype(np.float32) / 255.0
        rgb = rgba[..., [2, 1, 0]] * rgba[..., 3:4] + np.array([0.04, 0.05, 0.07], np.float32) * (1 - rgba[..., 3:4])
        # 缩放到目标尺寸：能整除就面积平均（更平滑），否则最近邻采样（保证尺寸精确）
        k = h // size
        if k > 1 and h % size == 0 and w % size == 0:
            rgb = rgb.reshape(size, k, size, k, 3).mean(axis=(1, 3))
        elif rgb.shape[0] != size or rgb.shape[1] != size:
            yi = np.clip((np.arange(size) * (h / size)).astype(int), 0, h - 1)
            xi = np.clip((np.arange(size) * (w / size)).astype(int), 0, w - 1)
            rgb = rgb[yi][:, xi]
        out_rgb = np.clip(rgb, 0, 1).astype(np.float32)
        _ICON_CACHE[(digit, size)] = out_rgb
        return out_rgb
    except Exception as e:                          # noqa: BLE001
        log.debug("符文图标解码不可用（%s: %s），退回位图字体", type(e).__name__, e)
        return None


def icon_png(digit: str) -> bytes | None:
    """游戏原版符文图标（BC7 DDS 解码，结果缓存）。缺依赖/缺 pak 时返回 None。"""
    digit = str(digit).upper()
    if len(digit) != 1 or digit not in HEX:
        return None
    out = os.path.join(_icon_dir(), f"{digit}.png")
    if os.path.exists(out):
        return open(out, "rb").read()
    rgb = icon_rgb(digit, 256)
    if rgb is None:
        return None
    png = png_bytes((np.clip(rgb, 0, 1) * 255).astype(np.uint8))
    tmp = out + ".part"
    with open(tmp, "wb") as f:
        f.write(png)
    os.replace(tmp, out)
    return png


@lru_cache(maxsize=256)
def panel_png(glyphs: str, tile: int = TILE, gap: int = GAP) -> bytes:
    """12 个符文横排图。优先游戏原图，缺依赖时用内置位图字体。"""
    digits = digits_for(glyphs)
    tiles = []
    for ch in digits:
        rgb = icon_rgb(ch, tile)
        tiles.append(rgb if rgb is not None else _draw_char(ch, scale=max(4, tile // 9)))
    h = max(t.shape[0] for t in tiles)
    w = sum(t.shape[1] for t in tiles) + gap * (len(tiles) - 1)
    canvas = np.zeros((h, w, 3), np.float32) + np.array([0.03, 0.035, 0.05], np.float32)
    x = 0
    for t in tiles:
        canvas[0:t.shape[0], x:x + t.shape[1]] = t
        x += t.shape[1] + gap
    return png_bytes((np.clip(canvas, 0, 1) * 255).astype(np.uint8))


def panel_payload(glyphs: str) -> dict:
    """给浮窗用：数字序列 + 每位的图标 URL + 文本兜底。"""
    digits = digits_for(glyphs)
    return {"glyphs": digits, "digits": list(digits),
            "icons": [f"/api/glyphs/{d}.png" for d in digits],
            "strip": f"/api/glyphs/{digits}.png",
            "copy_text": digits, "source": "game" if icon_png(digits[0]) else "font"}
