"""只读数据层：Gagarin 目录/图标 + ShipRef 数据模型 + 与 Shipwright 的桥。

注意：本模块对外只暴露 `load_catalog()` / `load_icons()`，
不要把 `catalog` / `icons` 直接当函数名再导出——那会遮蔽同名子模块。
"""
from __future__ import annotations

from pathlib import Path

from .catalog import Catalog, load as _load_catalog
from .icons import IconSet
from .icons import load as _load_icons
from .shipref import ShipRef, ShipRefError, PROC_MODELS, SAVE_CATEGORY, coerce

_CACHE: dict[str, object] = {}


def _gamedata(gamedata: str | Path | None):
    from ..core import paths, settings
    gd = gamedata or settings.current().gamedata_resolved() or paths.gagarin_gamedata()
    if not gd:
        raise FileNotFoundError("找不到 GAMEDATA（catalog.txt / icons.bin）")
    return Path(gd)


def load_catalog(gamedata: str | Path | None = None) -> Catalog:
    gd = _gamedata(gamedata)
    key = f"cat:{gd}"
    if key not in _CACHE:
        _CACHE[key] = _load_catalog(gd)
    return _CACHE[key]  # type: ignore[return-value]


def load_icons(gamedata: str | Path | None = None) -> IconSet:
    gd = _gamedata(gamedata)
    return _load_icons(gd)


__all__ = ["load_catalog", "load_icons", "Catalog", "IconSet",
           "ShipRef", "ShipRefError", "PROC_MODELS", "SAVE_CATEGORY", "coerce"]
