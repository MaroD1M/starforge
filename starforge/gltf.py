"""把 Shipwright 的 `model3d.pack()` 二进制转成标准 glTF 2.0（.glb）。

pack 格式（nms_procgen/model3d.py:786）：
  u32 头长 | JSON 头（4 字节对齐，空格填充） | 每组 pos f32[n,3] · nrm f32[n,3] · uv f32[n,2] · idx u32[m]
"""
from __future__ import annotations

import json
import struct

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


def _material(cls: str, colours: dict) -> dict:
    c = colours.get(cls) or colours.get("paint") or _GROUP_COLOR.get(cls, (0.7, 0.7, 0.72))
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


def build_glb(header: dict, groups: dict, colours: dict | None = None, name: str = "ship") -> bytes:
    colours = colours or header.get("colours") or {}
    mats, prims, views, accessors, blobs, off = [], [], [], [], [], 0

    def view(arr, target):
        nonlocal off
        raw = np.ascontiguousarray(arr).tobytes()
        pad = -len(raw) % 4
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(raw), "target": target})
        blobs.append(raw + b"\0" * pad)
        off += len(raw) + pad
        return len(views) - 1

    def acc(v, ctype, atype, count, lo=None, hi=None):
        a = {"bufferView": v, "componentType": ctype, "count": count, "type": atype}
        if lo is not None:
            a["min"], a["max"] = lo, hi
        accessors.append(a)
        return len(accessors) - 1

    midx = {}
    for key, (pos, nrm, uv, idx) in groups.items():
        cls = key[0] if isinstance(key, tuple) else key
        if cls not in midx:
            midx[cls] = len(mats)
            mats.append(_material(cls, colours))
        ap = acc(view(pos, 34962), 5126, "VEC3", len(pos),
                 np.asarray(pos, np.float32).min(0).tolist(), np.asarray(pos, np.float32).max(0).tolist())
        an = acc(view(nrm, 34962), 5126, "VEC3", len(nrm))
        au = acc(view(uv, 34962), 5126, "VEC2", len(uv))
        ai = acc(view(idx, 34963), 5125, "SCALAR", len(idx))
        prims.append({"attributes": {"POSITION": ap, "NORMAL": an, "TEXCOORD_0": au},
                      "indices": ai, "material": midx[cls], "mode": 4})

    blob = b"".join(blobs)
    gltf = {"asset": {"version": "2.0", "generator": "starforge"},
            "scene": 0, "scenes": [{"nodes": [0], "name": name}],
            "nodes": [{"mesh": 0, "name": name}],
            "meshes": [{"name": name, "primitives": prims}],
            "materials": mats, "buffers": [{"byteLength": len(blob)}],
            "bufferViews": views, "accessors": accessors}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + (8 + len(blob) if blob else 0)
    out = struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
    if blob:
        out += struct.pack("<II", len(blob), 0x004E4942) + blob
    return out
