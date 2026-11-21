"""设置：一个 JSON 文件，读写都要过校验；写入开关默认关闭。

S0 验收：`write_enabled` 默认 False，任何写接口在 False 时返回 403。
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict
from pathlib import Path

from . import paths

_LOCK = threading.RLock()

DEFAULTS = {
    "write_enabled": False,          # 三条安全要求之③：只读默认
    "confirm_writes": True,          # 每次写前要二次确认
    "saves_dir": "",                 # 空 = 自动发现
    "gamedata_dir": "",              # 空 = 自动发现（Gagarin 的 GAMEDATA）
    "game_dir": "",                  # 空 = 没有游戏（3D 走 L0 降级）
    "backup_keep": 0,                # 0 = 永不删备份（与 Shipwright 一致）
    "workers": 0,                    # 0 = 自动；搜索/扫描可用的工作线程数
    "port": 0,                       # 0 = 随机空闲端口
    "theme": "dark",
    "allow_unverified_agent": False, # 显式允许未验证 build 的实验性 agent 写命令
}


_TRUE_WORDS = {"1", "true", "yes", "on", "enabled", "无人深空", "深空"}
_FALSE_WORDS = {"0", "false", "no", "off", "disabled", "neutral", "中性", ""}


def _as_bool(value: object, default: bool) -> bool:
    """宽松解析旧配置里的布尔值；无法识别时保持默认，避免把 "false" 当成 True。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE_WORDS:
            return True
        if text in _FALSE_WORDS:
            return False
    return default


GAMEDATA_MARKER = ("Gagarin", "ships", "catalog.txt")


def gamedata_valid(path: str | Path | None) -> bool:
    """GAMEDATA 目录是否可用：必须含 Gagarin/ships/catalog.txt。

    只看目录存在会把 Steam 原版的 GAMEDATA（只有 PCBANKS/INPUT/MODS/SHADERCACHE）
    误判为有效，下游随后在 catalog.txt 上抛 FileNotFoundError。自动发现与解析
    统一用这一个判据。
    """
    if not path:
        return False
    try:
        p = Path(path).expanduser()
    except (OSError, TypeError, ValueError):
        return False
    return p.joinpath(*GAMEDATA_MARKER).is_file()


@dataclass
class Settings:
    write_enabled: bool = False
    confirm_writes: bool = True
    saves_dir: str = ""
    gamedata_dir: str = ""
    game_dir: str = ""
    backup_keep: int = 0
    workers: int = 0
    port: int = 0
    theme: str = "dark"
    allow_unverified_agent: bool = False

    @classmethod
    def load(cls) -> "Settings":
        f = paths.settings_file()
        data = dict(DEFAULTS)
        if f.exists():
            try:
                data.update(json.loads(f.read_text("utf-8")))
            except (OSError, ValueError, TypeError):
                pass
        known = {k: v for k, v in data.items() if k in DEFAULTS}
        return cls(**known)

    def save(self) -> None:
        with _LOCK:
            f = paths.settings_file()
            f.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), "utf-8")

    # --- 派生 ---
    def saves_dir_resolved(self) -> Path | None:
        if self.saves_dir:
            p = Path(self.saves_dir).expanduser()
            return p if p.exists() else None
        env = paths.env_saves()
        if env and env.exists():
            return env
        for p in paths.default_save_dirs():
            if list(p.glob("*.hg")):
                return p
        return None

    def gamedata_resolved(self) -> Path | None:
        """解析可用的 GAMEDATA；显式配置无效时回退自动发现，两者都无效返回 None。

        无效路径绝不返回：否则下游会在 catalog.txt / icons.bin 上抛
        FileNotFoundError，而不是得到可读的"未配置数据目录"。
        """
        if self.gamedata_dir:
            p = Path(self.gamedata_dir).expanduser()
            if gamedata_valid(p):
                return p
        auto = paths.gagarin_gamedata()
        return auto if auto and gamedata_valid(auto) else None


_CURRENT: Settings | None = None


def current() -> Settings:
    global _CURRENT
    if _CURRENT is None:
        _CURRENT = Settings.load()
    return _CURRENT


def update(**kw) -> Settings:
    global _CURRENT
    with _LOCK:
        s = current()
        for k, v in kw.items():
            if k in DEFAULTS:
                setattr(s, k, v)
        s.save()
    return s


def require_write() -> None:
    """写操作的唯一闸门。三条安全要求之③。"""
    from .errors import WriteDisabled
    if not current().write_enabled:
        raise WriteDisabled("写入功能当前关闭")


# ---------------------------------------------------------------- 自动发现

def autodetect(apply: bool = True) -> dict:
    """自动找游戏 / 存档 / 数据目录（对应项为空或无效时填），返回找到的结果与来源。

    优先级：
      游戏   NMS_DIR 环境变量 → Shipwright 的 gamepath.find()（Steam/GOG/注册表）
      存档   平台默认路径（Windows: %APPDATA%\\HelloGames\\NMS\\st_*）
      数据   游戏目录/GAMEDATA（若存在 Gagarin 的 catalog.txt 也认）
    """
    from . import log as log_mod, paths
    log = log_mod.get("settings")
    found: dict[str, str] = {}
    cur = current()
    changed: dict[str, str] = {}

    # 游戏目录（含 Steam 注册表/多磁盘兜底 + 常见填错自愈）
    from .. import locate_game
    if cur.game_dir:
        fixed = locate_game.normalize(cur.game_dir)
        if fixed and os.path.normcase(fixed) != os.path.normcase(cur.game_dir):
            found["game_dir"] = fixed
    else:
        hit = locate_game.find()
        if hit:
            found["game_dir"] = hit

    # 存档目录
    if not cur.saves_dir:
        for d in paths.default_save_dirs():
            if list(d.glob("*.hg")):
                found["saves_dir"] = str(d)
                break

    # 数据目录（Gagarin 的 GAMEDATA；优先游戏目录下的那份）
    # 已填但无效（例如误填 Steam 原版的 GAMEDATA）同样自愈，判据与 gamedata_resolved 一致。
    def _gamedata_candidate() -> str | None:
        g = found.get("game_dir") or cur.game_dir
        if g:
            cand = os.path.join(g, "GAMEDATA")
            if gamedata_valid(cand):
                return cand
        gd = paths.gagarin_gamedata()
        return str(gd) if gd and gamedata_valid(gd) else None

    if not gamedata_valid(cur.gamedata_dir):
        cand = _gamedata_candidate()
        if cand:
            found["gamedata_dir"] = cand

    if apply and found:
        update(**found)
        changed = dict(found)
        log.info("自动发现并写入设置：%s", ", ".join(f"{k}={v}" for k, v in found.items()))
    return {"found": found, "applied": bool(apply and changed)}
