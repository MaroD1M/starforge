import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 老 CI/容器布局的兜底路径；本机找不到真实目录时仍按原位置跳过，不改变语义。
_FALLBACK_GAME_DIR = Path("/workspace/nms/No Man's Sky")
_FALLBACK_SAVES_DIR = Path("/workspace/nms/NMS存档")


def _normalize_game(folder: str | None) -> str | None:
    """用 starforge.locate_game.normalize 校验/纠正候选游戏目录。"""
    try:
        from starforge import locate_game
    except Exception:                                      # noqa: BLE001
        return None
    return locate_game.normalize(folder)


def _discover_game_dir() -> Path | None:
    """跨平台发现游戏根目录：NMS_DIR → 自动查找 → 老布局兜底。"""
    fixed = _normalize_game(os.environ.get("NMS_DIR"))
    if fixed:
        return Path(fixed)
    try:
        from starforge import locate_game
        found = locate_game.find()
        if found:
            return Path(found)
    except Exception:                                      # noqa: BLE001
        pass
    if (_FALLBACK_GAME_DIR / "Binaries" / "NMS.exe").exists():
        return _FALLBACK_GAME_DIR
    return None


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """每个测试用独立的 STARFORGE_HOME，避免污染真实 ~/.starforge。"""
    monkeypatch.setenv("STARFORGE_NO_WARM", "1")   # 测试里不跑后台预热
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("STARFORGE_HOME", str(home))
    from starforge.core import settings as settings_mod
    settings_mod._CURRENT = None
    yield home
    settings_mod._CURRENT = None


@pytest.fixture(autouse=True)
def no_game_running(monkeypatch):
    """写测试只操作**存档副本**，不该被本机正在运行的游戏挡住。

    `starforge.save.transaction` 调用的是 `writer.game_running()`，
    所以打桩 `writer.game_running` 即可同时覆盖 writer 与 transaction 两条写入路径。
    需要验证"游戏在跑就拒绝"的用例，可在用例内把它改回 `lambda: True`。
    """
    from starforge.save import writer
    monkeypatch.setattr(writer, "game_running", lambda: False)


@pytest.fixture(scope="session")
def gamedata():
    from starforge.core import paths
    gd = paths.gagarin_gamedata()
    if not gd:
        pytest.skip("找不到 Gagarin GAMEDATA")
    return gd


@pytest.fixture(scope="session", autouse=True)
def _global_game_env():
    """有游戏目录就全局设置 NMS_DIR：`nms_save.gamepath.find` 带 lru_cache，
    首次调用若没有环境变量会把空结果缓存下来，导致后续测试莫名失败。"""
    cand = _discover_game_dir()
    if cand is not None:
        # 无效 NMS_DIR 同样会让 gamepath.find() 缓存空结果，能用自动发现值就覆盖它。
        os.environ["NMS_DIR"] = str(cand)
        try:
            from nms_save import gamepath
            gamepath.find.cache_clear()
        except Exception:
            pass


@pytest.fixture(scope="session")
def nms_dir():
    """真实游戏目录（缺它就跳过需要 pak/exe 的测试）。"""
    cand = _discover_game_dir() or _FALLBACK_GAME_DIR
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
    """真实存档目录：STARFORGE_SAVES → 各平台默认位置 → 老布局兜底。"""
    from starforge.core import paths
    cands: list[Path] = []
    env = paths.env_saves()
    if env:
        cands.append(env)
    cands += list(paths.default_save_dirs())
    cands.append(_FALLBACK_SAVES_DIR)
    for cand in cands:
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
