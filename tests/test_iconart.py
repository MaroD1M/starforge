"""表情图标生成器：BC1/DDS 编码与文件头（不依赖游戏数据的部分可完全离线测试）。"""
from __future__ import annotations

import struct

import numpy as np
import pytest

from starforge.live import iconart


def test_bc1_encode_size():
    rgb = np.zeros((8, 8, 3), np.uint8)
    data = iconart.bc1_encode(rgb)
    assert len(data) == (8 // 4) * (8 // 4) * 8 == 32


def test_bc1_rejects_bad_size():
    with pytest.raises(ValueError):
        iconart.bc1_encode(np.zeros((6, 8, 3), np.uint8))


def test_dds_header_is_dx10_bc1():
    rgb = np.full((128, 128, 3), 40, np.uint8)
    data = iconart.dds_bc1(rgb)
    assert data[:4] == b"DDS "
    h, w = struct.unpack_from("<II", data, 12)[0], struct.unpack_from("<II", data, 16)[0]
    assert (w, h) == (128, 128)
    assert data[84:88] == b"DX10"
    assert struct.unpack_from("<I", data, 128)[0] == 71          # BC1_UNORM
    assert len(data) == 148 + (128 // 4) * (128 // 4) * 8


def test_shipped_icons_are_blueprint_bc1():
    """随包图标必须是 128×128 BC1 DDS（坏文件会让表情显示空白）。"""
    for type_, *_ in iconart.exml.TEMPLATES:
        path = iconart.exml.icon_asset(type_)
        data = open(path, "rb").read()
        assert data[:4] == b"DDS ", type_
        assert data[84:88] == b"DX10", type_
        h = struct.unpack_from("<I", data, 12)[0]
        w = struct.unpack_from("<I", data, 16)[0]
        assert (w, h) == (128, 128), (type_, w, h)
        assert len(data) == 148 + (128 // 4) * (128 // 4) * 8, type_
