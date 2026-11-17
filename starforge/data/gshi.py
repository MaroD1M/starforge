"""GSHI 图标容器（Gagarin 的 icons.bin）读写。

格式（由 winmm.dll @0x180030030 逆出，实测 1039+867 条全通）：
  header: char[4] "GSHI"; u16 version(1|2); u32 count
  entry : u8 namelen; char name[namelen]; u16 w; u16 h; u32 datalen; u8 data[datalen]
  stream: code=u8
            code >= 0x80 -> 跳过 (code & 0x7f) 个像素（保持透明）
            code <  0x80 -> 紧随 code 个原始像素（v1: g,a 两字节；v2: rgba 四字节）
"""
from __future__ import annotations

import struct
import zlib
from functools import lru_cache
from pathlib import Path

MAGIC = b"GSHI"


def parse_container(path: str | Path) -> tuple[int, list[tuple[str, int, int, bytes]]]:
    return parse_container_bytes(Path(path).read_bytes())


def parse_container_bytes(b: bytes) -> tuple[int, list[tuple[str, int, int, bytes]]]:
    if b[:4] != MAGIC:
        raise ValueError(f"不是 GSHI 容器：{b[:4]!r}")
    ver, n = struct.unpack_from("<II", b, 4)
    off = 12
    out = []
    for _ in range(n):
        ln = b[off]
        off += 1
        name = b[off:off + ln].decode("utf-8", "replace")
        off += ln
        w, h = struct.unpack_from("<HH", b, off)
        off += 4
        dl = struct.unpack_from("<I", b, off)[0]
        off += 4
        out.append((name, w, h, b[off:off + dl]))
        off += dl
    if off != len(b):
        raise ValueError(f"容器长度不符：解析到 {off}，文件 {len(b)}")
    return ver, out


def decode(ver: int, w: int, h: int, data: bytes, strict: bool = True) -> bytes:
    """-> RGBA bytes (w*h*4)。"""
    px = bytearray(w * h * 4)
    o = i = 0
    n = len(data)
    while i < n:
        code = data[i]
        i += 1
        if code >= 0x80:
            o += code - 0x80
            continue
        if ver == 1:
            if i + code * 2 > n:
                raise ValueError("v1 run 越界")
            for _ in range(code):
                g = data[i]
                a = data[i + 1]
                i += 2
                j = o * 4
                px[j] = px[j + 1] = px[j + 2] = g
                px[j + 3] = a
                o += 1
        else:
            if i + code * 4 > n:
                raise ValueError("v2 run 越界")
            for _ in range(code):
                j = o * 4
                px[j:j + 4] = data[i:i + 4]
                i += 4
                o += 1
    if o != w * h and strict:
        raise ValueError(f"像素数 {o} != {w * h}")
    return bytes(px)


def png_bytes(w: int, h: int, rgba: bytes) -> bytes:
    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


@lru_cache(maxsize=4096)
def _png(path: str, index: int) -> bytes:
    ver, ents = parse_container(path)
    name, w, h, data = ents[index]
    return png_bytes(w, h, decode(ver, w, h, data))
