"""部件树：优先用 Gagarin 的 catalog（带权重与缩略图），缺它时**从游戏资源自己算**。

这样 starforge 不再依赖外部数据文件：
  · 有 Gagarin 的 `GAMEDATA/Gagarin/ships/catalog.txt` → 用它（更快、带权重/图标）
  · 没有 → 用 NMS-Shipwright 的 `generator.all_parts()` 从游戏 pak 里的场景描述符推导

对上层只暴露一个结构：
    [{"group": "_PIT_", "options": [{"part": "_PIT_A", "weight": 20}, ...]}, ...]
"""
from __future__ import annotations

import os

from .core import log, settings
from .data import load_catalog
from .data.shipref import PROC_MODELS

log = log.get("parts")

SHIPS = ("fighter", "hauler", "explorer", "shuttle", "exotic", "living", "solar", "sentinel")
DEFAULT_WEIGHT = 20


def _from_catalog(ship: str) -> list[dict]:
    cat = load_catalog()
    groups = cat.groups_of(ship)
    return [{"group": g, "options": [{"part": p, "weight": w} for p, w in opts]}
            for g, opts in groups.items()]


def _from_game(ship: str) -> list[dict]:
    from .core import paths
    paths.ensure_shipwright_importable()
    from nms_procgen.generator import all_parts
    found = all_parts(ship)                     # {group: [part, ...]}
    return [{"group": g, "options": [{"part": p, "weight": DEFAULT_WEIGHT} for p in parts]}
            for g, parts in found.items()]


def source() -> str:
    """当前部件树优先来自游戏资源；Gagarin 仅作为无游戏时的可选回退。"""
    s = settings.current()
    if s.game_dir or os.environ.get("NMS_DIR"):
        return "game"
    try:
        load_catalog()
        return "gagarin"
    except Exception:                            # noqa: BLE001
        pass
    return "none"


def available() -> bool:
    return source() != "none"


def tree(ship: str) -> list[dict]:
    """部件树。**游戏资源优先**；Gagarin 目录只作为无游戏时的可选回退。

    游戏里的 `*_PROC.descriptor.mbin` 同时提供结构、权重（xRARE/xNEVER）和部件名，
    所以 catalog.txt 不再是必需数据。
    """
    if ship not in PROC_MODELS:
        raise ValueError(f"未知船型：{ship}")
    try:
        got = _from_game(ship)
        if got:
            return got
    except Exception as e:                       # noqa: BLE001
        log.debug("游戏资源推导失败（%s），尝试 Gagarin 目录回退", type(e).__name__)
    try:
        got = _from_catalog(ship)
        if got:
            log.info("部件树回退到 Gagarin catalog（游戏资源不可用）")
            return got
    except Exception as e:                       # noqa: BLE001 - 没游戏/没数据：给出可读原因
        raise ValueError(f"取不到 {ship} 的部件表：{type(e).__name__}: {e}") from e
    raise ValueError(f"游戏资源里没有 {ship} 的部件描述（游戏目录是否配置正确？）")


def parts_of(ship: str) -> list[str]:
    return [o["part"] for g in tree(ship) for o in g["options"]]


def summary(ship: str) -> dict:
    t = tree(ship)
    return {"ship": ship, "groups": len(t),
            "parts": sum(len(g["options"]) for g in t), "source": source()}
