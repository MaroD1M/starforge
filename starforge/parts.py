"""部件树：优先用 Gagarin 的 catalog（带权重与缩略图），缺它时**从游戏资源自己算**。

这样 starforge 不再依赖外部数据文件：
  · 有 Gagarin 的 `GAMEDATA/Gagarin/ships/catalog.txt` → 用它（更快、带权重/图标）
  · 没有 → 用 NMS-Shipwright 的 `generator.all_parts()` 从游戏 pak 里的场景描述符推导

对上层只暴露一个结构：
    [{"group": "_PIT_", "options": [{"part": "_PIT_A", "weight": 20}, ...]}, ...]
"""
from __future__ import annotations

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
    """当前部件树来自哪里：gagarin / game / none。"""
    try:
        load_catalog()
        return "gagarin"
    except Exception:                            # noqa: BLE001
        pass
    s = settings.current()
    if s.game_dir:
        return "game"
    return "none"


def available() -> bool:
    return source() != "none"


def tree(ship: str) -> list[dict]:
    """部件树。先试 Gagarin 目录，失败则从游戏资源推导。"""
    if ship not in PROC_MODELS:
        raise ValueError(f"未知船型：{ship}")
    try:
        got = _from_catalog(ship)
        if got:
            return got
    except Exception as e:                       # noqa: BLE001
        log.debug("catalog 不可用（%s），改用游戏资源推导", type(e).__name__)
    try:
        got = _from_game(ship)
    except Exception as e:                       # noqa: BLE001 - 没游戏/没数据：给出可读原因
        raise ValueError(f"取不到 {ship} 的部件表：{type(e).__name__}: {e}") from e
    if not got:
        raise ValueError(f"游戏资源里没有 {ship} 的部件描述（游戏目录是否配置正确？）")
    return got


def parts_of(ship: str) -> list[str]:
    return [o["part"] for g in tree(ship) for o in g["options"]]


def summary(ship: str) -> dict:
    t = tree(ship)
    return {"ship": ship, "groups": len(t),
            "parts": sum(len(g["options"]) for g in t), "source": source()}
