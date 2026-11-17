"""设置：一个 JSON 文件，读写都要过校验；写入开关默认关闭。

S0 验收：`write_enabled` 默认 False，任何写接口在 False 时返回 403。
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict, field
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
    "port": 0,                       # 0 = 随机空闲端口
    "theme": "dark",
}


@dataclass
class Settings:
    write_enabled: bool = False
    confirm_writes: bool = True
    saves_dir: str = ""
    gamedata_dir: str = ""
    game_dir: str = ""
    backup_keep: int = 0
    port: int = 0
    theme: str = "dark"

    @classmethod
    def load(cls) -> "Settings":
        f = paths.settings_file()
        data = dict(DEFAULTS)
        if f.exists():
            try:
                data.update(json.loads(f.read_text("utf-8")))
            except (OSError, ValueError):
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
        if self.gamedata_dir:
            p = Path(self.gamedata_dir).expanduser()
            return p if p.exists() else None
        return paths.gagarin_gamedata()


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
