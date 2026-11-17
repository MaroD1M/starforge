"""路径解析：一切可配置项都从环境变量/设置读取，代码里不写死绝对路径。

环境变量（都有合理默认）：
  STARFORGE_HOME        应用数据目录（默认 ~/.starforge）
  STARFORGE_SHIPWRIGHT  NMS-Shipwright 仓库根（默认同机 ../NMS-Shipwright 或 /workspace/nms/NMS-Shipwright）
  STARFORGE_GAMEDATA    Gagarin 的 GAMEDATA 根（含 Gagarin/ships/catalog.txt）
  STARFORGE_SAVES       存档目录（默认按平台猜测）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = ".starforge"


def app_home() -> Path:
    p = Path(os.environ.get("STARFORGE_HOME") or (Path.home() / APP_DIR_NAME))
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_file() -> Path:
    return app_home() / "settings.json"


def log_file() -> Path:
    d = app_home() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "starforge.log"


def cache_dir() -> Path:
    d = app_home() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _first_existing(*cands: str | Path) -> Path | None:
    for c in cands:
        if not c:
            continue
        p = Path(c).expanduser()
        if p.exists():
            return p
    return None


def shipwright_root() -> Path:
    env = os.environ.get("STARFORGE_SHIPWRIGHT")
    here = Path(__file__).resolve()
    cands = [env,
             here.parents[2] / "NMS-Shipwright",          # 与仓库并列
             here.parents[2].parent / "NMS-Shipwright",
             "/workspace/nms/NMS-Shipwright"]
    p = _first_existing(*cands)
    if not p:
        from .errors import GameFilesMissing
        raise GameFilesMissing("找不到 NMS-Shipwright 仓库（搜索与存档解析依赖它）",
                               hint="设置环境变量 STARFORGE_SHIPWRIGHT 指向仓库根目录")
    return p


def ensure_shipwright_importable() -> str:
    """让 `nms_save` / `nms_procgen` 可导入。

    顺序：
      1) 已经被打包进程序（PyInstaller 把 vendor 版放进 _internal）→ 直接可用；
      2) 否则把同机的 NMS-Shipwright 仓库加进 sys.path（开发/高级用户）；
      3) 都没有 → 抛 GameFilesMissing，并提示在设置里指定或改用自包含发布包。

    另外在导入**之前**把 NMS_TOOL_CACHE 指到可写目录，避免往程序安装目录里写缓存。
    """
    import os as _os
    if not _os.environ.get("NMS_TOOL_CACHE"):
        _os.environ["NMS_TOOL_CACHE"] = str(cache_dir() / "gamecache")
    try:                                   # 1) 打包版：已经能导入
        import nms_save  # noqa: F401
        return _os.path.dirname(_os.path.dirname(nms_save.__file__))
    except Exception:                      # noqa: BLE001
        pass
    root = str(shipwright_root())          # 2) 同机仓库
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def gagarin_gamedata() -> Path | None:
    env = os.environ.get("STARFORGE_GAMEDATA")
    here = Path(__file__).resolve()
    cands = [env,
             here.parents[2] / "Gagarin_Titov" / "GAMEDATA",   # 开发布局
             here.parents[2] / "vendor" / "gamedata",          # 发布包布局
             "/workspace/nms/Gagarin_Titov/GAMEDATA"]
    return _first_existing(*cands)


def default_save_dirs() -> list[Path]:
    """按平台猜测存档目录（只用于"自动发现"，找不到就让用户手填）。"""
    out: list[Path] = []
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        if base:
            root = Path(base) / "HelloGames" / "NMS"
            if root.exists():
                out += sorted(p for p in root.glob("st_*") if p.is_dir())
                out.append(root)
    else:
        home = Path.home()
        out += [
            home / ".steam/steam/steamapps/compatdata/275850/pfx/drive_c/users/steamuser/AppData/Roaming/HelloGames/NMS",
            home / ".local/share/Steam/steamapps/compatdata/275850/pfx/drive_c/users/steamuser/AppData/Roaming/HelloGames/NMS",
        ]
        # 开发机上常把存档单独放一个目录
        out.append(home / "NMS")
    return [p for p in out if p.is_dir()]


def env_saves() -> Path | None:
    p = os.environ.get("STARFORGE_SAVES")
    return Path(p).expanduser() if p else None
