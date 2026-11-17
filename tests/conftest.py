import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """每个测试用独立的 STARFORGE_HOME，避免污染真实 ~/.starforge。"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("STARFORGE_HOME", str(home))
    from starforge.core import settings as settings_mod
    settings_mod._CURRENT = None
    yield home
    settings_mod._CURRENT = None


@pytest.fixture(scope="session")
def gamedata():
    from starforge.core import paths
    gd = paths.gagarin_gamedata()
    if not gd:
        pytest.skip("找不到 Gagarin GAMEDATA")
    return gd


@pytest.fixture(scope="session")
def nms_dir():
    """真实游戏目录（缺它就跳过需要 pak/exe 的测试）。"""
    cand = Path("/workspace/nms/No Man's Sky")
    if not (cand / "Binaries" / "NMS.exe").exists():
        pytest.skip("没有游戏目录")
    return cand


@pytest.fixture()
def game_env(nms_dir, monkeypatch):
    monkeypatch.setenv("NMS_DIR", str(nms_dir))
    from starforge.core import settings as settings_mod
    settings_mod.update(game_dir=str(nms_dir))
    return nms_dir


@pytest.fixture(scope="session")
def saves_dir():
    from starforge.core import paths
    for cand in [Path("/workspace/nms/NMS存档"), *paths.default_save_dirs()]:
        if cand.exists() and list(cand.glob("*.hg")):
            return cand
    pytest.skip("没有存档样本")


@pytest.fixture()
def client():
    from starforge.web.app import create_app
    app = create_app()
    app.testing = True
    with app.test_client() as c:
        yield c


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 需要真实游戏数据的耗时测试")
