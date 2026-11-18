"""接口层错误码回归：异常必须映射成 4xx，而不是 500。

这两个是 04 卷审计发现的真隐患（曾经：`/api/saves/apply` 在"游戏正在运行"时抛
`WriteRefused`，但 `routes.py` 没 import 它 → Windows 上连不上游戏会变成 500 internal）。
"""
import shutil

import pytest

from starforge.core import settings as settings_mod
from starforge.glyphs import _decode_dds


@pytest.fixture()
def save_copy(saves_dir, tmp_path, game_env):
    dst = tmp_path / "save.hg"
    shutil.copy2(saves_dir / "save.hg", dst)
    return dst


def test_apply_while_game_running_is_409(client, save_copy, monkeypatch):
    from starforge.save import writer
    settings_mod.update(write_enabled=True)
    monkeypatch.setattr(writer, "game_running", lambda: True)
    r = client.post("/api/saves/apply", json={"path": str(save_copy), "slot": 2,
                                              "type": "sentinel", "seed": "0x1111222233334444",
                                              "confirm": True})
    assert r.status_code == 409, r.get_json()
    assert r.get_json()["error"]["kind"] in ("write_refused", "write_blocked")


def test_class_while_game_running_is_409(client, save_copy, monkeypatch):
    from starforge.save import writer
    settings_mod.update(write_enabled=True)
    monkeypatch.setattr(writer, "game_running", lambda: True)
    r = client.post("/api/saves/class", json={"path": str(save_copy), "slot": 2,
                                              "ship_class": "S", "confirm": True})
    assert r.status_code == 409, r.get_json()


def test_dxt1_dds_decodes():
    """DXT1/3/5 分支必须能解码（旧代码 `from . import dds` 指向不存在的模块）。"""
    import struct
    hdr = bytearray(128)
    hdr[0:4] = b"DDS "
    struct.pack_into("<I", hdr, 12, 4)
    struct.pack_into("<I", hdr, 16, 4)
    hdr[84:88] = b"DXT1"
    block = struct.pack("<HHI", 0xFFFF, 0x0000, 0)
    w, h, rgba = _decode_dds(bytes(hdr) + block)
    assert (w, h) == (4, 4) and len(rgba) == 64


def test_unknown_dds_fourcc_raises():
    hdr = bytearray(128)
    hdr[0:4] = b"DDS "
    hdr[84:88] = b"XXXX"
    with pytest.raises(NotImplementedError):
        _decode_dds(bytes(hdr))
