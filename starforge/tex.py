"""飞船贴图：从游戏 pak 取 DDS，解码成 RGBA 供光栅化采样，或原样给 WebGL。

两条路：
  · `dds_bytes(path)`   → 原始 DDS（浏览器直接 `compressedTexImage2D`，无解码开销）
  · `rgba(path)`        → 解码后的 (H,W,4) uint8（服务端光栅化 / 导出 PNG 用）

拿不到材质描述符时会抛 `TextureUnavailable`，调用方退回纯色（这是常态，不是错误）。
"""
from __future__ import annotations

import threading

import numpy as np

from .core import log, paths

log = log.get("tex")

_CACHE: dict[str, np.ndarray] = {}
_LOCK = threading.Lock()
_CTOR = {"BC1": "decode_bc1", "BC2": "decode_bc3", "BC3": "decode_bc3",
         "BC4": "decode_bc4", "BC5": "decode_bc5", "BC7": "decode_bc7"}


class TextureUnavailable(RuntimeError):
    pass


def _shiptex():
    paths.ensure_shipwright_importable()
    from nms_procgen import shiptex
    return shiptex


def dds_bytes(path: str) -> bytes:
    """取一个 DDS 的原始字节（块压缩，未解码）。"""
    if not path:
        raise TextureUnavailable("没有贴图路径")
    data = _shiptex().blob(path)
    if not data:
        raise TextureUnavailable(f"pak 里没有这个贴图：{path}")
    return data


def describe(path: str) -> dict:
    d = _shiptex().describe(dds_bytes(path))
    if not d:
        raise TextureUnavailable(f"不认识的 DDS 格式：{path}")
    return d


def rgba(path: str) -> np.ndarray:
    """解码成 (H, W, 4) uint8（BGRA 已交换成 RGBA）。"""
    with _LOCK:
        hit = _CACHE.get(path)
    if hit is not None:
        return hit
    try:
        import texture2ddecoder as t2d
    except Exception as e:                                 # noqa: BLE001
        raise TextureUnavailable(f"缺少 texture2ddecoder（{type(e).__name__}）")
    info = describe(path)
    data = dds_bytes(path)[info["offset"]:]
    fn = getattr(t2d, _CTOR.get(info["format"], ""), None)
    if fn is None:
        raise TextureUnavailable(f"不支持解码 {info['format']}")
    raw = fn(data, info["width"], info["height"])
    img = np.frombuffer(raw, np.uint8).reshape(info["height"], info["width"], 4)
    img = img[:, :, [2, 1, 0, 3]]                          # BGRA → RGBA
    with _LOCK:
        _CACHE[path] = img
    return img


def ship_textures(groups: dict) -> dict:
    """{组键: rgba} —— 只对能解码的贴图返回，其余略过。"""
    out = {}
    for key in groups:
        tex = key[1] if isinstance(key, tuple) and len(key) > 1 else ""
        if not tex or tex in out:
            continue
        try:
            out[tex] = rgba(tex)
        except TextureUnavailable as e:
            log.debug("贴图跳过 %s：%s", tex, e)
    return out


def sample(img: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """按 UV 最近邻采样 → (...,3) float32（0..1）。"""
    h, w = img.shape[:2]
    x = np.clip((u % 1.0) * w, 0, w - 1).astype(np.int32)
    y = np.clip((v % 1.0) * h, 0, h - 1).astype(np.int32)
    return img[y, x, :3].astype(np.float32) / 255.0


def status(ship: str = "sentinel") -> dict:
    """贴图可用性自检：能不能读到材质描述符、能不能解出一张图。

    返回 {ok, reason, materials, textures, sampled}，供诊断页/selfcheck 显示。
    """
    out = {"ok": False, "reason": "", "materials": 0, "textures": 0,
           "sampled": "", "bytes": 0}
    try:
        st = _shiptex()
    except Exception as e:                                 # noqa: BLE001
        out["reason"] = f"上游模块不可用：{type(e).__name__}: {e}"
        return out
    try:
        mdir = str(st._materials_dir())
        import glob
        files = glob.glob(mdir.rstrip("\\/") + "/**/*.MBIN", recursive=True)
        out["materials"] = len(files)
    except Exception as e:                                 # noqa: BLE001
        out["reason"] = f"取材质目录失败：{type(e).__name__}: {e}"
        return out
    if not out["materials"]:
        out["reason"] = ("材质描述符为空（游戏 pak 里没解出 *.MATERIAL.MBIN）："
                         "贴图会退回种子配色，功能不受影响")
        return out
    try:
        paths.ensure_shipwright_importable()
        from nms_procgen import model3d
        model = model3d.ship_model("0x884609884CD21A5C", ship, None, True, False)
        texs = sorted({k[1] for k in model["groups"] if isinstance(k, tuple) and k[1]})
        out["textures"] = len(texs)
        if not texs:
            out["reason"] = "材质解析成功，但这艘船没有可用贴图"
            return out
        img = rgba(texs[0])
        out["sampled"] = texs[0]
        out["bytes"] = int(img.shape[0] * img.shape[1] * 4)
        out["ok"] = True
        out["reason"] = f"{len(texs)} 张贴图可用（示例 {texs[0].split('/')[-1]}）"
    except Exception as e:                                 # noqa: BLE001
        out["reason"] = f"贴图解码失败：{type(e).__name__}: {e}"
    return out
