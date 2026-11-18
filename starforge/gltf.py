"""把 Shipwright 的 `model3d.pack()` 二进制转成标准 glTF 2.0（.glb）。

pack 格式（nms_procgen/model3d.py:pack）：
  u32 头长 | JSON 头（4 字节对齐，空格填充） | 每组 pos f32[n,3] · nrm f32[n,3] · uv f32[n,2] · idx u32[m]

`build_glb` 另外可选接收每个几何组使用的贴图（RGBA ndarray / PNG 字节 / 外部
URI），把 PNG 内嵌进 GLB。没有贴图的组仍然使用原来的按材质类平涂，调用方不需要
改变旧路径。
"""
from __future__ import annotations

import json
import struct
import zlib

import numpy as np


def parse_pack(data: bytes) -> tuple[dict, dict]:
    (hlen,) = struct.unpack_from("<I", data, 0)
    header = json.loads(data[4:4 + hlen].decode("utf-8"))
    base = 4 + hlen
    groups = {}
    for g in header["groups"]:
        off = base + g["offset"]
        n, m = g["vertices"], g["indices"]
        pos = np.frombuffer(data, np.float32, n * 3, off).reshape(n, 3)
        off += n * 12
        nrm = np.frombuffer(data, np.float32, n * 3, off).reshape(n, 3)
        off += n * 12
        uv = np.frombuffer(data, np.float32, n * 2, off).reshape(n, 2)
        off += n * 8
        idx = np.frombuffer(data, np.uint32, m, off)
        groups[(g["class"], g.get("tex", ""))] = (pos, nrm, uv, idx)
    return header, groups


_GROUP_COLOR = {"paint": (0.55, 0.62, 0.78), "secondary": (0.30, 0.33, 0.40),
                "metal": (0.45, 0.47, 0.50), "dark": (0.13, 0.14, 0.17),
                "glow": (1.00, 0.62, 0.22), "glass": (0.55, 0.78, 0.90)}

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _as_rgba(image) -> np.ndarray | None:
    """把常见贴图输入统一成 (H, W, 4) uint8；不认识就返回 None。"""
    if isinstance(image, dict):
        image = image.get("rgba", image.get("data", image.get("pixels")))
    if isinstance(image, np.ndarray):
        arr = image
    elif isinstance(image, (bytes, bytearray, memoryview)):
        raw = bytes(image)
        if raw[:8] == _PNG_SIG:       # 已经是 PNG：由调用方原样内嵌
            return None
        return None
    else:
        try:
            arr = np.asarray(image)
        except Exception:                              # noqa: BLE001 - 不认识的贴图输入
            return None
    if arr.ndim != 3 or arr.shape[2] not in (3, 4) or not arr.size:
        return None
    if arr.dtype != np.uint8:
        arr = np.nan_to_num(arr.astype(np.float32))
        if arr.max() <= 1.0:
            arr = arr * 255.0
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.shape[2] == 3:
        alpha = np.full((arr.shape[0], arr.shape[1], 1), 255, np.uint8)
        arr = np.concatenate([arr, alpha], axis=2)
    return np.ascontiguousarray(arr)


def encode_png(image) -> bytes | None:
    """最小 PNG 编码器（8-bit RGBA，无滤波）；输入可以是 ndarray 或 {rgba: ndarray}。"""
    if isinstance(image, (bytes, bytearray, memoryview)) and bytes(image)[:8] == _PNG_SIG:
        return bytes(image)
    arr = _as_rgba(image)
    if arr is None:
        return None
    h, w = arr.shape[:2]
    raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return _PNG_SIG + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(raw, 6)) \
        + _png_chunk(b"IEND", b"")


def _material(cls: str, colours: dict) -> dict:
    # 回退顺序：本类配色 → 该类默认色（_GROUP_COLOR） → 主色 → 灰。
    # 早期版本直接回退到主色，导致发光件/金属件被涂成船身色，3D 看起来"一片同色"。
    c = colours.get(cls) or _GROUP_COLOR.get(cls) or colours.get("paint") or (0.7, 0.7, 0.72)
    c = [float(x) for x in list(c)[:3]]
    if cls == "glow":
        return {"name": cls, "pbrMetallicRoughness": {"baseColorFactor": c + [1.0],
                                                     "metallicFactor": 0.0, "roughnessFactor": 0.4},
                "emissiveFactor": c, "doubleSided": True}
    if cls == "glass":
        return {"name": cls, "pbrMetallicRoughness": {"baseColorFactor": [0.6, 0.75, 0.85, 0.35],
                                                     "metallicFactor": 0.1, "roughnessFactor": 0.08},
                "alphaMode": "BLEND", "doubleSided": True}
    return {"name": cls, "pbrMetallicRoughness": {"baseColorFactor": c + [1.0],
                                                  "metallicFactor": 0.25, "roughnessFactor": 0.62},
            "doubleSided": True}


def _textured_material(cls: str, colours: dict, tex_index: int, tex_name: str = "") -> dict:
    """在原有平涂材质上挂 baseColorTexture；贴图已经是游戏里的最终颜色，用白因子。"""
    mat = _material(cls, colours)
    pbr = mat["pbrMetallicRoughness"]
    pbr["baseColorFactor"] = [1.0, 1.0, 1.0, 1.0]
    pbr["baseColorTexture"] = {"index": tex_index, "texCoord": 0}
    if cls == "glow":
        mat["emissiveTexture"] = {"index": tex_index, "texCoord": 0}
        mat["emissiveFactor"] = [1.0, 1.0, 1.0]
    if tex_name:
        mat["name"] = f"{cls}:{tex_name.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}"
    return mat


def _image_bytes(value) -> tuple[bytes, str] | None:
    """返回 (PNG 字节, mime) 或 None。"""
    if isinstance(value, dict):
        uri = value.get("uri") or value.get("path")
        if uri and not any(k in value for k in ("rgba", "data", "pixels")):
            return None                      # 外部引用，交给 build_glb 单独处理
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if raw[:8] == _PNG_SIG:
            return raw, "image/png"
        return None
    png = encode_png(value)
    return (png, "image/png") if png else None


def _external_uri(value, fallback: str) -> str:
    if isinstance(value, dict):
        uri = value.get("uri") or value.get("path")
        if uri:
            return str(uri)
    return fallback.replace("\\", "/")


def build_glb(header: dict, groups: dict, colours: dict | None = None, name: str = "ship",
              textures: dict | None = None, embed_textures: bool = True) -> bytes:
    """把几何组写成 .glb。

    `textures` 是 {组键里的 tex 字段: 贴图}。值可以是 RGBA ndarray、PNG 字节，或者
    {"uri": "..."} 外部引用。`embed_textures=False` 时 ndarray/PNG 也写成外部 URI
    （用于需要旁车文件的场景）；没有贴图的组照旧平涂。
    """
    colours = colours or header.get("colours") or {}
    textures = textures or {}
    mats, prims, views, accessors, blobs, off = [], [], [], [], [], 0
    images: list[dict] = []
    tex_defs: list[dict] = []
    tex_slots: dict[str, int] = {}

    def view(arr: bytes | np.ndarray, target: int | None = None) -> int:
        nonlocal off
        raw = arr if isinstance(arr, (bytes, bytearray)) else np.ascontiguousarray(arr).tobytes()
        raw = bytes(raw)
        pad = -len(raw) % 4
        v = {"buffer": 0, "byteOffset": off, "byteLength": len(raw)}
        if target is not None:
            v["target"] = target
        views.append(v)
        blobs.append(raw + b"\0" * pad)
        off += len(raw) + pad
        return len(views) - 1

    def image_view(mime: str, png: bytes | None = None, uri: str = "") -> int:
        if png is not None:
            bv = view(png)
            images.append({"bufferView": bv, "mimeType": mime})
        else:
            images.append({"uri": uri})
        return len(images) - 1

    # 先把所有实际使用的贴图放进 images/textures；同一个 tex 只放一次。
    for key in groups:
        tex = key[1] if isinstance(key, tuple) and len(key) > 1 else ""
        if not tex or tex in tex_slots or tex not in textures:
            continue
        value = textures[tex]
        got = _image_bytes(value)
        if got and embed_textures:
            src = image_view(got[1], png=got[0])
        elif isinstance(value, dict) and (value.get("uri") or value.get("path")):
            src = image_view("image/png", uri=_external_uri(value, tex + ".png"))
        elif got:
            src = image_view(got[1], uri=tex.replace("\\", "/") + ".png")
        else:
            continue
        tex_defs.append({"sampler": 0, "source": src})
        tex_slots[tex] = len(tex_defs) - 1

    def acc(v, ctype, atype, count, lo=None, hi=None):
        a = {"bufferView": v, "componentType": ctype, "count": count, "type": atype}
        if lo is not None:
            a["min"], a["max"] = lo, hi
        accessors.append(a)
        return len(accessors) - 1

    midx = {}
    for key, (pos, nrm, uv, idx) in groups.items():
        cls = key[0] if isinstance(key, tuple) else key
        tex = key[1] if isinstance(key, tuple) and len(key) > 1 else ""
        slot = tex_slots.get(tex)
        mkey = (cls, tex if slot is not None else "")
        if mkey not in midx:
            midx[mkey] = len(mats)
            if slot is not None:
                mats.append(_textured_material(cls, colours, slot, tex))
            else:
                mats.append(_material(cls, colours))
        ap = acc(view(pos, 34962), 5126, "VEC3", len(pos),
                 np.asarray(pos, np.float32).min(0).tolist(), np.asarray(pos, np.float32).max(0).tolist())
        an = acc(view(nrm, 34962), 5126, "VEC3", len(nrm))
        au = acc(view(uv, 34962), 5126, "VEC2", len(uv))
        ai = acc(view(idx, 34963), 5125, "SCALAR", len(idx))
        prims.append({"attributes": {"POSITION": ap, "NORMAL": an, "TEXCOORD_0": au},
                      "indices": ai, "material": midx[mkey], "mode": 4})

    blob = b"".join(blobs)
    gltf = {"asset": {"version": "2.0", "generator": "starforge"},
            "scene": 0, "scenes": [{"nodes": [0], "name": name}],
            "nodes": [{"mesh": 0, "name": name}],
            "meshes": [{"name": name, "primitives": prims}],
            "materials": mats, "buffers": [{"byteLength": len(blob)}],
            "bufferViews": views, "accessors": accessors}
    if images:
        gltf["images"] = images
        gltf["textures"] = tex_defs
        gltf["samplers"] = [{"magFilter": 9729, "minFilter": 9729,
                             "wrapS": 10497, "wrapT": 10497}]
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + (8 + len(blob) if blob else 0)
    out = struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
    if blob:
        out += struct.pack("<II", len(blob), 0x004E4942) + blob
    return out
