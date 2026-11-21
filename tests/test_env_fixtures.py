"""环境自适应 fixture 的回归测试。

`conftest.py` 里的 `no_game_running` 为了让写测试不被本机正在运行的游戏挡住，
会把 `writer.game_running` 打桩成 `False`。这里显式证明**安全闸门没有被抹掉**：
把桩改回 `True` 时，写回仍然必须抛 `WriteRefused`。
"""
import shutil

import pytest

from starforge.core import settings as settings_mod
from starforge.core.errors import WriteRefused
from starforge.data.shipref import ShipRef
from starforge.save import library, writer


@pytest.fixture()
def save_copy(saves_dir, tmp_path, game_env):
    dst = tmp_path / "save.hg"
    shutil.copy2(saves_dir / "save.hg", dst)
    return dst


def test_fixtures_resolve_real_game_data(nms_dir, saves_dir, gamedata):
    """跨平台发现必须真的落到本机目录上（否则这些用例会被 skip 掉）。"""
    assert (nms_dir / "Binaries" / "NMS.exe").exists()
    assert (saves_dir / "save.hg").exists()
    assert (gamedata / "Gagarin").is_dir()


def test_game_running_guard_still_refuses(save_copy, monkeypatch):
    """打桩只关掉"游戏在跑"的误报，真正的拒绝语义必须保留。"""
    settings_mod.update(write_enabled=True)
    ships, _ = library.open_ships(save_copy)
    slot = next(s.slot for s in ships if s.type == "sentinel")
    original_bytes = save_copy.read_bytes()

    monkeypatch.setattr(writer, "game_running", lambda: True)
    with pytest.raises(WriteRefused) as e:
        writer.apply_seed(str(save_copy), slot,
                          ShipRef(type="sentinel", seed="0x1111222233334444"),
                          confirm=True)
    assert "游戏正在运行" in str(e.value)
    assert save_copy.read_bytes() == original_bytes          # 拒绝发生在任何写入之前
