"""服务端渲染：把模型渲成 PNG（纯 numpy，无 GPU / 无浏览器）。

用途：搜索结果的缩略图、详情页的大图，以及"3D 加载失败"时的兜底。
与 tools/render_model.py 同一套着色，但这里是包内实现并带磁盘缓存。
"""
from __future__ import annotations

import hashlib
import math
import os
import threading
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


def trim(img: np.ndarray, pad: int = 6) -> np.ndarray:
    """裁掉四周纯背景，让缩略图里的船/部件占满画面。"""
    bg = np.median(img.reshape(-1, 3), axis=0)
    diff = np.abs(img.astype(np.int16) - bg.astype(np.int16)).sum(2) > 12
    ys, xs = np.nonzero(diff)
    if len(ys) < 10:
        return img
    y0, y1 = max(0, ys.min() - pad), min(img.shape[0], ys.max() + pad)
    x0, x1 = max(0, xs.min() - pad), min(img.shape[1], xs.max() + pad)
    h, w = y1 - y0, x1 - x0
    side = max(h, w)
    sq = np.zeros((side, side, 3), np.uint8)
    sq[:] = bg.astype(np.uint8)
    oy, ox = (side - h) // 2, (side - w) // 2
    sq[oy:oy + h, ox:ox + w] = img[y0:y1, x0:x1]
    return sq


def placeholder_png(size: int = 256, label: str = "") -> bytes:
    """占位图：深色底 + 斜纹，用于"固定模型/无种子"这类没有 3D 的船。"""
    h = w = size
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.zeros((h, w, 3), np.float32) + np.array([0.055, 0.065, 0.085], np.float32)
    stripe = ((xx + yy) % 24) < 2
    base[stripe] = np.array([0.085, 0.10, 0.13], np.float32)
    border = 3
    base[:border, :] = base[-border:, :] = base[:, :border] = base[:, -border:] = np.array([0.12, 0.15, 0.2], np.float32)
    return png_bytes((np.clip(base, 0, 1) * 255).astype(np.uint8))


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
             views=("iso",), size=(420, 420), colours: dict | None = None,
             raster: bool | None = None, textures: dict | None = None) -> bytes:
    """直接按船型+种子渲图（内部构建模型，结果按 hash 缓存）。"""
    raw = (f"{type_}|{seed}|{','.join(parts or [])}|{','.join(views)}|{size[0]}|"
           + "|".join(f"{k}:{v}" for k, v in sorted((colours or {}).items())))
    key = hashlib.sha1(raw.encode()).hexdigest()[:20]

    def build() -> bytes:
        paths.ensure_shipwright_importable()
        from nms_procgen import model3d
        model = model3d.ship_model(seed, type_, parts or None, True, False)
        use_raster = (size[0] >= 260) if raster is None else raster
        if not use_raster:
            return png_bytes(render(model["groups"], views, size, colours=colours))
        # 网格用小图（ss=1 快），详情用大图（ss=2 细腻）
        ss = 2 if size[0] >= 440 else 1
        return png_bytes(rasterize(model["groups"], views, size, colours=colours,
                                   ss=ss, ambient=0.24, textures=textures))

    return _cache_png(key, build)


# ---------------------------------------------------------------- 三角光栅化（比点云像"建模"）

def rasterize(groups: dict, views=("iso",), size=(640, 640), colours: dict | None = None,
              ss: int = 1, ambient: float = 0.28, fill: float = 0.62,
              spec_amount: float = 0.0, jitter_amount: float = 0.0,
              textures: dict | None = None) -> np.ndarray:
    """把三角面真正填充出来（z-buffer + Lambert 面着色）。

    点云渲染只在顶点处落点，看起来"散"；光栅化会把面填满，观感接近正常建模软件。
    对小三角形（多数）走"单像素"快路径，大三角形才做包围盒填充，保证速度。
    """
    pts, tris, cols = [], [], []
    off = 0
    for key, (p, n, uv, ix) in groups.items():
        cls = key[0] if isinstance(key, tuple) else key
        base = np.array((colours or {}).get(cls) or GROUP_COLOR.get(cls, (0.62, 0.62, 0.66)), np.float32)
        P = np.asarray(p, np.float32)
        I = np.asarray(ix, np.int64).reshape(-1, 3)
        pts.append(P)
        tris.append(I + off)
        cols.append(np.tile(base, (len(I), 1)))
        off += len(P)
    P = np.concatenate(pts)
    T = np.concatenate(tris)
    C = np.concatenate(cols)
    center = (P.min(0) + P.max(0)) / 2
    rel = P - center
    # 用 99.5 分位定尺度：个别远离主体的支点不会把主体缩得很小
    span = float(np.percentile(np.abs(rel), 99.5)) * 2 or 1.0
    P = rel

    uv_all = np.concatenate([g[2] for g in groups.values()]).astype(np.float32)
    glow_mask = np.repeat(
        np.array([1.0 if (k[0] if isinstance(k, tuple) else k) == "glow" else 0.0 for k in groups],
                 np.float32),
        [len(g[3]) // 3 for g in groups.values()])
    W, H = size[0] * ss, size[1] * ss
    out = np.zeros((H, len(views) * W, 3), np.float32) + np.array([0.043, 0.055, 0.075], np.float32)
    light = np.array([0.42, 0.78, 0.46], np.float32)
    light /= np.linalg.norm(light)
    fill_light = np.array([-0.55, 0.15, -0.35], np.float32)
    fill_light /= np.linalg.norm(fill_light)
    rim_light = np.array([0.0, 0.35, -1.0], np.float32)
    rim_light /= np.linalg.norm(rim_light)

    for k, vname in enumerate(views):
        yaw, pitch = VIEWS.get(vname, (35, 18))
        R = _rot("y", yaw) @ _rot("x", pitch)
        q = P @ R.T
        scr = np.empty((len(q), 2), np.float32)
        scr[:, 0] = q[:, 0] / span * (W * fill) + k * W + W / 2
        scr[:, 1] = -q[:, 1] / span * (W * fill) + H / 2
        z = q[:, 2]
        zbuf = np.full((H, W), -1e9, np.float32)
        tile = out[:, k * W:(k + 1) * W]

        tri_tex = None
        if textures:
            tri_tex = np.concatenate([np.full(len(g[3]) // 3, (k[1] if isinstance(k, tuple) else ""), dtype=object)
                                      for k, g in groups.items()])
        a, b, c = scr[T[:, 0]], scr[T[:, 1]], scr[T[:, 2]]
        za, zb, zc = z[T[:, 0]], z[T[:, 1]], z[T[:, 2]]
        area = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])
        # 面法线（世界坐标）用于着色
        wp = P[T]
        fn = np.cross(wp[:, 1] - wp[:, 0], wp[:, 2] - wp[:, 0])
        ln = np.linalg.norm(fn, axis=1, keepdims=True)
        fn = fn / np.where(ln == 0, 1, ln)
        L = R.T @ light
        F = R.T @ fill_light
        RIM = R.T @ rim_light
        d_main = np.clip(fn @ L, 0, 1)
        d_fill = np.clip(fn @ F, 0, 1)
        d_rim = np.clip(fn @ RIM, 0, 1) ** 3
        shade = ambient + (1.0 - ambient) * d_main
        # 高光：半角向量的高次幂（面法线近似）
        Half = (L + np.array([0, 0, 1], np.float32)); Half /= np.linalg.norm(Half)
        spec = np.clip(fn @ Half, 0, 1) ** 22
        # glow 类：自发光（灯/推进器），不吃环境光
        # 漫反射为主；高光/轮廓都很轻，避免整体发白
        jitter = 1.0 + jitter_amount * np.sin(d_main * 233.0)   # 逐面微差（可选）
        lit = shade * jitter + spec_amount * spec
        fcol = np.clip(C * np.clip(lit, 0, 1.02)[:, None]
                       + glow_mask[:, None] * C * 0.85, 0, 1)

        # 背面剔除（法线朝外的才画）
        fn_view = fn @ R.T
        front = fn_view[:, 2] > 0
        big = front & (np.abs(area) >= 3.0)   # 小于 3 平方像素的走向量化单像素路径
        # (a) 小三角：全部向量化（画家算法：远→近覆盖）
        small_idx = np.nonzero(front & ~big)[0]
        if len(small_idx):
            cx = ((a[small_idx, 0] + b[small_idx, 0] + c[small_idx, 0]) / 3).astype(np.int32)
            cy = ((a[small_idx, 1] + b[small_idx, 1] + c[small_idx, 1]) / 3).astype(np.int32)
            np.clip(cx, 0, W - 1, out=cx); np.clip(cy, 0, H - 1, out=cy)
            order = np.argsort(za[small_idx])          # 远的先画
            colors_small = fcol[small_idx]
            if textures and tri_tex is not None:
                from . import tex as tex_mod
                sel = small_idx
                for tkey, img_t in textures.items():
                    m = np.array([tri_tex[j] == tkey for j in sel], bool) if len(sel) else None
                    if m is None or not m.any():
                        continue
                    idxs = sel[m]
                    uu = uv_all[T[idxs, 0], 0] * 0.34 + uv_all[T[idxs, 1], 0] * 0.33 + uv_all[T[idxs, 2], 0] * 0.33
                    vv = uv_all[T[idxs, 0], 1] * 0.34 + uv_all[T[idxs, 1], 1] * 0.33 + uv_all[T[idxs, 2], 1] * 0.33
                    colors_small[m] = tex_mod.sample(img_t, uu, vv) * np.clip(shade[idxs], 0.15, 1.2)[:, None]
            tile[cy[order], cx[order]] = colors_small[order]
        # (b) 大三角：包围盒 + 重心坐标填充（数量少）
        for i in np.nonzero(big)[0]:
            ax, ay = a[i]; bx, by = b[i]; cx_, cy_ = c[i]
            minx = int(max(0, np.floor(min(ax, bx, cx_)))); maxx = int(min(W - 1, np.ceil(max(ax, bx, cx_))))
            miny = int(max(0, np.floor(min(ay, by, cy_)))); maxy = int(min(H - 1, np.ceil(max(ay, by, cy_))))
            if minx > maxx or miny > maxy:
                continue
            xs = np.arange(minx, maxx + 1, dtype=np.float32) + 0.5
            ys = np.arange(miny, maxy + 1, dtype=np.float32) + 0.5
            if len(xs) * len(ys) > 60000:
                continue
            X, Y = np.meshgrid(xs, ys)
            w0 = ((bx - ax) * (Y - ay) - (by - ay) * (X - ax)) / area[i]
            w1 = ((cx_ - bx) * (Y - by) - (cy_ - by) * (X - bx)) / area[i]
            w2 = 1.0 - w0 - w1
            mask = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not mask.any():
                continue
            depth = w2 * za[i] + w0 * zb[i] + w1 * zc[i]
            sub = zbuf[miny:maxy + 1, minx:maxx + 1]
            upd = mask & (depth > sub)
            if not upd.any():
                continue
            sub[upd] = depth[upd]
            tri_col = fcol[i]
            tkey = tri_tex[i] if tri_tex is not None else ""
            if tkey and tkey in (textures or {}):
                img_t = (textures or {})[tkey]
                uu = w2 * uv_all[T[i, 0], 0] + w0 * uv_all[T[i, 1], 0] + w1 * uv_all[T[i, 2], 0]
                vv = w2 * uv_all[T[i, 0], 1] + w0 * uv_all[T[i, 1], 1] + w1 * uv_all[T[i, 2], 1]
                from . import tex as tex_mod
                samp = tex_mod.sample(img_t, uu, vv) * float(np.clip(shade[i], 0.15, 1.2))
                tile[miny:maxy + 1, minx:maxx + 1][upd] = samp[upd]
            else:
                tile[miny:maxy + 1, minx:maxx + 1][upd] = tri_col

    if ss > 1:
        out = out.reshape(size[1], ss, len(views) * size[0], ss, 3).mean(axis=(1, 3))
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)


# ---------------------------------------------------------------- 后台预取

_PREFETCH_Q: "queue.Queue" = None
_PREFETCH_THREAD = None
_PREFETCH_LOCK = threading.Lock()


def _prefetch_worker() -> None:
    while True:
        job = _PREFETCH_Q.get()
        if job is None:
            return
        type_, seed, size, parts = job
        try:
            ship_png(type_, seed, parts, ("iso",), (size, size))
        except Exception as e:                              # noqa: BLE001
            log.debug("预取失败 %s %s：%s", type_, seed, e)


def prefetch(items, size: int = 340) -> int:
    """把一批缩略图排队后台渲染（幂等：同一进程一个 worker）。"""
    global _PREFETCH_Q, _PREFETCH_THREAD
    with _PREFETCH_LOCK:
        if _PREFETCH_Q is None:
            import queue
            _PREFETCH_Q = queue.Queue(maxsize=256)
        if _PREFETCH_THREAD is None or not _PREFETCH_THREAD.is_alive():
            import threading as _t
            _PREFETCH_THREAD = _t.Thread(target=_prefetch_worker, daemon=True, name="sf-prefetch")
            _PREFETCH_THREAD.start()
    n = 0
    for it in items:
        try:
            _PREFETCH_Q.put_nowait((it.get("type"), it.get("seed"), size, it.get("parts")))
            n += 1
        except Exception:                                   # noqa: BLE001 - 队列满就算了
            break
    return n
