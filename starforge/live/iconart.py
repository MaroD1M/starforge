"""表情图标生成器：用游戏模型渲成「蓝图风」BC1 DDS。

为什么不用游戏自带的 `TYPE.*.DDS`：那一组是**船型类别符号**（例如 shuttle 那张其实
是一对齿轮），不是飞船外观。这里用 starforge 自己的渲染器把每个模板的真船渲出来，
再压成 BC1（DXT1）并随 Mod 一起分发。

风格（2026-11-21 定版）：
  · iso 视角、真实涂装做体积；
  · 船体压暗，只保留**边缘描线**（青色）+ 细网格；
  · 128×128，BC1_UNORM（DX10 头），单文件约 8 KB。
"""
from __future__ import annotations

import os
import struct

import numpy as np

from .. import paint, render
from ..core import log
from . import exml

log = log.get("iconart")

SIZE = 128
BG = np.array((14, 18, 25), np.float32)
TINT = np.array((0.35, 0.85, 1.0), np.float32) * 255
# 渲染器会整幅填这个底色，遮罩必须按"与底色差异"算，不能用 any(axis=2)。
RENDER_BG = np.array((0.043, 0.055, 0.075), np.float32) * 255


# ---------------------------------------------------------------- BC1 / DDS


def bc1_encode(rgb: np.ndarray) -> bytes:
    """极简 BC1 编码：每 4×4 块取最亮/最暗像素作端点，4 色模式。"""
    h, w, _ = rgb.shape
    if h % 4 or w % 4:
        raise ValueError(f"BC1 需要 4 的倍数尺寸，收到 {w}x{h}")
    blocks = (rgb.reshape(h // 4, 4, w // 4, 4, 3)
                 .transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3).astype(np.int32))
    lum = blocks @ np.array([299, 587, 114], np.int32)
    n = len(blocks)
    c0 = blocks[np.arange(n), lum.argmax(1)]
    c1 = blocks[np.arange(n), lum.argmin(1)]

    def pack(c):
        return ((c[:, 0] >> 3) << 11) | ((c[:, 1] >> 2) << 5) | (c[:, 2] >> 3)

    p0, p1 = pack(c0), pack(c1)
    swap = p0 < p1
    p0, p1 = np.where(swap, p1, p0), np.where(swap, p0, p1)

    def expand(p):
        r, g, b = (p >> 11) & 0x1F, (p >> 5) & 0x3F, p & 0x1F
        return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1)

    e0, e1 = expand(p0), expand(p1)
    pal = np.stack([e0, e1, (2 * e0 + e1) // 3, (e0 + 2 * e1) // 3], 1).astype(np.int32)
    idx = ((blocks[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1).argmin(-1).astype(np.uint32)
    bits = (idx << (2 * np.arange(16, dtype=np.uint32))).sum(1).astype(np.uint32)

    out = bytearray()
    for a, b, v in zip(p0, p1, bits):
        out += struct.pack("<HHI", int(a), int(b), int(v))
    return bytes(out)


def dds_bc1(rgb: np.ndarray) -> bytes:
    """包成带 DX10 头的 BC1_UNORM DDS（游戏里实测可加载）。"""
    h, w, _ = rgb.shape
    linear = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
    pf = struct.pack("<II4sIIIII", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
    header = (b"DDS " + struct.pack("<IIIIIII", 124, flags, h, w, linear, 0, 0)
              + b"\x00" * 44 + pf + struct.pack("<IIIII", 0x1000, 0, 0, 0, 0))
    dx10 = struct.pack("<IIIII", 71, 3, 0, 1, 0)      # BC1_UNORM / TEXTURE2D
    return header + dx10 + bc1_encode(rgb)


# ---------------------------------------------------------------- 画面处理


def _ship_mask(img: np.ndarray) -> np.ndarray:
    mask = np.abs(img - RENDER_BG).max(axis=2) > 7.0
    grown = mask.copy()
    grown |= np.roll(grown, 1, 0) | np.roll(grown, -1, 0)
    grown |= np.roll(grown, 1, 1) | np.roll(grown, -1, 1)
    return grown


def _trim(img: np.ndarray, pad: int = 4) -> np.ndarray:
    mask = img.any(axis=2)
    ys, xs = np.where(mask)
    if not len(ys):
        return img
    y0, y1 = max(0, ys.min() - pad), min(img.shape[0], ys.max() + 1 + pad)
    x0, x1 = max(0, xs.min() - pad), min(img.shape[1], xs.max() + 1 + pad)
    return img[y0:y1, x0:x1]


def _fit(crop: np.ndarray, size: int) -> np.ndarray:
    ch, cw = crop.shape[:2]
    side = max(ch, cw)
    canvas = np.zeros((side, side, 3), np.float32)
    canvas[(side - ch) // 2:(side - ch) // 2 + ch,
           (side - cw) // 2:(side - cw) // 2 + cw] = crop
    idx = np.arange(size) * side // size
    return canvas[np.ix_(idx, idx)]


def blueprint_icon(ship: str, seed: str, size: int = SIZE) -> np.ndarray:
    """渲一艘船 → 蓝图风 RGB uint8（size×size）。"""
    from ..core import paths

    paths.ensure_shipwright_importable()
    from nms_procgen import model3d

    colours = paint.look(seed, ship)
    model = model3d.ship_model(seed, ship, None, True, False)
    img = render.rasterize(model["groups"], views=("iso",), size=(size * 2, size * 2),
                           ss=2, ambient=0.35, fill=0.7, colours=colours)
    img = _trim(img.astype(np.float32))
    ship_img = _fit(img, size)
    mask = _ship_mask(ship_img)
    lum = ship_img.mean(axis=2) / 255.0
    gx = np.abs(np.diff(lum, axis=1, append=lum[:, -1:]))
    gy = np.abs(np.diff(lum, axis=0, append=lum[-1:, :]))
    edge = np.clip((gx + gy) * 3.2, 0, 1)[..., None] * mask[..., None]

    out = np.tile(BG, (size, size, 1))
    out[mask] = out[mask] * 0.7 + TINT * 0.08
    out = out * (1 - edge) + TINT * edge
    for g in range(0, size, 40 if size >= 120 else 20):
        out[g, :, :] = out[g, :, :] * 0.85 + 12
        out[:, g, :] = out[:, g, :] * 0.85 + 12
    return np.clip(out, 0, 255).astype(np.uint8)


def generate(dest: str | None = None) -> dict:
    """重新生成 8 张图标 DDS，返回 {path, files, bytes}。"""
    dest = dest or exml.ICON_ASSET_DIR
    os.makedirs(dest, exist_ok=True)
    files = []
    for i, (type_, _m, _l, _c) in enumerate(exml.TEMPLATES):
        seed = "0x%016X" % exml.factory_seed(i)
        rgb = blueprint_icon(type_, seed)
        path = os.path.join(dest, f"template.{type_}.dds")
        with open(path, "wb") as f:
            f.write(dds_bc1(rgb))
        files.append(path)
        log.info("图标 %s -> %s", type_, path)
    return {"path": dest, "files": files,
            "bytes": sum(os.path.getsize(p) for p in files)}


if __name__ == "__main__":                              # python -m starforge.live.iconart
    rep = generate()
    print(f"生成 {len(rep['files'])} 张，共 {rep['bytes']} B -> {rep['path']}")
