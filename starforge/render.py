"""服务端渲染：把模型渲成 PNG（纯 numpy，无 GPU / 无浏览器）。

用途：搜索结果的缩略图、详情页的大图，以及"3D 加载失败"时的兜底。
与 tools/render_model.py 同一套着色，但这里是包内实现并带磁盘缓存。
"""
from __future__ import annotations

import hashlib
import math
import os
import struct
import zlib

import numpy as np

from . import gltf
from .core import paths

GROUP_COLOR = {"paint": (0.55, 0.62, 0.78), "secondary": (0.30, 0.33, 0.40),
               "metal": (0.45, 0.47, 0.50), "dark": (0.13, 0.14, 0.17),
               "glow": (1.00, 0.62, 0.22), "glass": (0.55, 0.78, 0.90)}

VIEWS = {"iso": (35, 18), "side": (90, 6), "front": (0, 6), "top": (0, 88), "back": (180, 10)}


def png_bytes(rgb: np.ndarray) -> bytes:
    h, w = rgb.shape[:2]
    raw = np.concatenate([np.zeros((h, 1), np.uint8), rgb.reshape(h, w * 3)], axis=1).tobytes()

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def _rot(axis: str, deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], np.float32)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], np.float32)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], np.float32)


def render(groups: dict, views=("iso",), size=(420, 420), splat: int = 2, ss: int = 2,
           colours: dict | None = None) -> np.ndarray:
    """ss = 超采样倍率：先按 ss 倍尺寸点绘，再块平均降采样，点云看起来更"实"。"""
    allp = np.concatenate([g[0] for g in groups.values()])
    center = (allp.min(0) + allp.max(0)) / 2
    span = float((allp.max(0) - allp.min(0)).max()) or 1.0

    pts, nrm, cols = [], [], []
    for key, (p, n, uv, ix) in groups.items():
        cls = key[0] if isinstance(key, tuple) else key
        base = np.array((colours or {}).get(cls) or GROUP_COLOR.get(cls, (0.62, 0.62, 0.66)), np.float32)
        pts.append(np.asarray(p, np.float32))
        nrm.append(np.asarray(n, np.float32))
        cols.append(np.tile(base, (len(p), 1)))
    P = np.concatenate(pts) - center
    N = np.concatenate(nrm)
    C = np.concatenate(cols)

    W0, H0 = size
    ss = max(1, int(ss))
    W, H = W0 * ss, H0 * ss
    splat = max(splat, 1) * (2 if ss > 1 else 1)
    out = np.zeros((H, len(views) * W, 3), np.float32) + np.array([0.043, 0.055, 0.075], np.float32)
    light = np.array([0.45, 0.75, 0.5], np.float32)
    light /= np.linalg.norm(light)
    rng = range(-splat, splat + 1)

    for k, vname in enumerate(views):
        yaw, pitch = VIEWS.get(vname, (35, 18))
        R = _rot("y", yaw) @ _rot("x", pitch)
        q = P @ R.T
        n = N @ R.T
        x = q[:, 0] / span * (W * 0.60) + W / 2
        y = -q[:, 1] / span * (W * 0.60) + H / 2
        shade = 0.35 + 0.65 * np.clip(n @ light, 0, 1)
        col = np.clip(C * shade[:, None], 0, 1)
        order = np.argsort(q[:, 2])
        xi = x[order].astype(np.int32)
        yi = y[order].astype(np.int32)
        ci = col[order]
        for dx in rng:
            for dy in rng:
                xs = np.clip(xi + dx, 0, W - 1)
                ys = np.clip(yi + dy, 0, H - 1)
                out[ys, k * W + xs] = ci
    out = np.clip(out, 0, 1)
    if ss > 1:                                  # 块平均降采样
        out = out.reshape(H0, ss, len(views) * W0, ss, 3).mean(axis=(1, 3))
    return (out * 255).astype(np.uint8)


def _cache_png(key: str, builder) -> bytes:
    d = paths.cache_dir() / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{key}.png"
    if path.exists():
        return path.read_bytes()
    data = builder()
    tmp = str(path) + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return data


def model_png(glb_bytes: bytes, views=("iso",), size=(420, 420), colours: dict | None = None) -> bytes:
    """从我们自己产出的 glb 渲图（不需要再跑一遍 model3d）。"""
    key = hashlib.sha1(glb_bytes[:4096] + b"|".join(v.encode() for v in views)).hexdigest()[:20] + f"-{size[0]}"
    return _cache_png(key, lambda: png_bytes(render(gltf.parse_pack(glb_bytes)[1], views, size, colours=colours)))


def ship_png(type_: str, seed: str, parts: list[str] | None = None,
             views=("iso",), size=(420, 420), colours: dict | None = None) -> bytes:
    """直接按船型+种子渲图（内部构建模型，结果按 hash 缓存）。"""
    raw = (f"{type_}|{seed}|{','.join(parts or [])}|{','.join(views)}|{size[0]}|"
           + "|".join(f"{k}:{v}" for k, v in sorted((colours or {}).items())))
    key = hashlib.sha1(raw.encode()).hexdigest()[:20]

    def build() -> bytes:
        paths.ensure_shipwright_importable()
        from nms_procgen import model3d
        model = model3d.ship_model(seed, type_, parts or None, True, False)
        return png_bytes(render(model["groups"], views, size, colours=colours))

    return _cache_png(key, build)
