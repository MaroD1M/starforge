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
