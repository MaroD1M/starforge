"""生成一个最小的 BC1 DDS（用于验证 DDS 解析/解码链路，不依赖游戏文件）。

BC1 块 = 2 个 RGB565 端点 + 32 位索引。整块同色时索引全 0、两端点相同即可。
"""
from __future__ import annotations

import struct


def _rgb565(r: int, g: int, b: int) -> int:
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def make_bc1_dds(width: int, height: int, blocks: list[tuple[int, int, int]]) -> bytes:
    """blocks 按行优先给每个 4×4 块一个纯色。"""
    assert width % 4 == 0 and height % 4 == 0
    bw, bh = width // 4, height // 4
    assert len(blocks) == bw * bh
    data = bytearray()
    for color in blocks:
        c = _rgb565(*color)
        data += struct.pack("<HHI", c, c, 0)       # 端点相同 → 整块纯色
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)         # dwSize
    struct.pack_into("<I", header, 8, 0x00081007)  # flags: caps|height|width|pixelformat|linearsize
    struct.pack_into("<I", header, 12, height)
    struct.pack_into("<I", header, 16, width)
    struct.pack_into("<I", header, 20, len(data))  # pitchOrLinearSize
    struct.pack_into("<I", header, 28, 1)          # mipMapCount
    struct.pack_into("<I", header, 76, 32)         # pf.dwSize
    struct.pack_into("<I", header, 80, 0x4)        # DDPF_FOURCC
    header[84:88] = b"DXT1"
    struct.pack_into("<I", header, 108, 0x1000)    # caps: TEXTURE
    return bytes(header) + bytes(data)


def checkerboard_dds(width=16, height=16) -> bytes:
    bw, bh = width // 4, height // 4
    colors = [(220, 40, 40), (40, 200, 90), (60, 90, 220), (240, 210, 70)]
    blocks = [colors[(x + y) % 4] for y in range(bh) for x in range(bw)]
    return make_bc1_dds(width, height, blocks)
