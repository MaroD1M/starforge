"""存档扩展编辑：库存、词语/知识、任务、奖励。

只调用 Shipwright ``nms_save`` 中已经验证过的公开函数，不猜测字段偏移：
  · ``items.list_inventories / get_inventory / edit_inventory``
  · ``extras.knowledge / learn_words / learn_all / rewards / set_rewards``
  · ``quests.list_quests / skip_quests``

所有写操作都经过 ``save.transaction.transact_save``：写开关、游戏进程检查、备份、
原子写、读回校验、失败回滚。没有对应 API 的内容（货船/护卫舰/中队写回等）不在
这里伪造。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core import log as log_mod
from ..core import paths, settings
from ..core.errors import BadRequest, SaveFormatError, WriteRefused
from . import library, transaction

log = log_mod.get("save.extras")

RACES = ("Gek", "Vy'keen", "Korvax", "Atlas", "Autophage")
UNLOCK_GROUPS = ("tech", "products", "base", "customisation", "refiner", "cooking")
REWARD_GROUPS = ("expedition", "twitch", "special", "shop")


def _nms():
    paths.ensure_shipwright_importable()
    from nms_save import extras as nms_extras
    from nms_save import items as nms_items
    from nms_save import quests as nms_quests
    from nms_save import save as nms_save

    return nms_save, nms_items, nms_extras, nms_quests


def _player_path(path: str | None) -> Path:
    p = library.resolve(path)
    kind = library.classify(p)
    if kind != "player":
        reason = {
            "account": "这是账号数据，不是玩家存档（没有库存/任务字段）",
            "manifest": "这是游戏的清单文件（mf_ 前缀），不含玩家数据",
        }.get(kind, "无法识别的文件类型，请选择 save.hg 或 save2.hg")
        raise SaveFormatError(reason)
    return p


def _open(path: str | None):
    p = _player_path(path)
    nms_save = _nms()[0]
    try:
        return p, nms_save.open_save(str(p))
    except Exception as e:
        raise SaveFormatError(f"无法读取存档：{type(e).__name__}: {e}") from e


def _require_confirm(confirm: bool) -> None:
    if not confirm:
        raise BadRequest("缺少 confirm=true（写操作必须二次确认）")


# ---------------------------------------------------------------- 库存


def inventories(path: str | None = None) -> dict:
    """列出所有可编辑库存（含玩家/飞船/货船/多用途工具/基地箱子）。"""
    p, opened = _open(path)
    nms_items = _nms()[1]
    try:
        rows = nms_items.list_inventories(opened.readable)
    except Exception as e:
        raise SaveFormatError(f"读取库存列表失败：{type(e).__name__}: {e}") from e
    return {"path": str(p), "inventories": rows}


def inventory(path: str | None, inv_path: str) -> dict:
    """读一个库存的格子、物品与容量。"""
    if not str(inv_path or "").strip():
        raise BadRequest("缺少库存路径")
    _, opened = _open(path)
    nms_items = _nms()[1]
    try:
        return nms_items.get_inventory(opened.readable, str(inv_path))
    except Exception as e:
        raise BadRequest(f"读取库存失败：{type(e).__name__}: {e}") from e


def apply_inventory(path: str, inv_path: str, op: str,
                    confirm: bool = False, copy: bool = False, **kw: Any) -> dict:
    """执行一次库存编辑（set/amount/remove/fill/recharge/repair/expand/slots/unlock/lock）。"""
    settings.require_write()
    _require_confirm(confirm)
    if not str(inv_path or "").strip():
        raise BadRequest("缺少库存路径")
    p = _player_path(path)
    nms_items = _nms()[1]
    snapshot: dict[str, Any] = {}

    def mutate(readable: dict):
        try:
            snapshot["before"] = nms_items.get_inventory(readable, str(inv_path))
            snapshot["after"] = nms_items.edit_inventory(readable, str(inv_path), str(op), **kw)
        except ValueError as e:
            raise BadRequest(f"库存编辑被拒绝：{e}") from e
        return snapshot["before"]

    def verify(readable: dict):
        try:
            after = nms_items.get_inventory(readable, str(inv_path))
        except Exception as e:
            raise WriteRefused(f"写后无法读回库存：{type(e).__name__}: {e}") from e
        if after != snapshot.get("after"):
            raise WriteRefused("写后校验失败：库存内容与预期不符")
        return after

    res = transaction.transact_save(str(p), mutate, verify, copy=copy)
    log.info("库存编辑：%s %s %s", p.name, inv_path, op)
    return res


# ---------------------------------------------------------------- 词语/知识


def knowledge(path: str | None = None) -> dict:
    """已学词语与蓝图/配方/基地部件等知识分组统计。"""
    p, opened = _open(path)
    nms_extras = _nms()[2]
    try:
        out = nms_extras.knowledge(opened.readable)
    except Exception as e:
        raise SaveFormatError(f"读取知识进度失败：{type(e).__name__}: {e}") from e
    return {"path": str(p), **out}


def _words_by_race(readable: dict) -> dict[str, list[int]]:
    nms_extras = _nms()[2]
    groups = nms_extras.word_groups()
    known = {w["Group"].lstrip("^"): w["Races"] for w in
             (readable.get("BaseContext", {}).get("PlayerStateData", {}) or {}).get("KnownWordGroups", [])}
    out: dict[str, list[int]] = {}
    for group, race in groups.items():
        name = nms_extras.RACES.get(race)
        if not name:
            continue
        row = out.setdefault(name, [0, 0])
        row[1] += 1
        have = known.get(group) or []
        if race < len(have) and have[race]:
            row[0] += 1
    return out


def apply_words(path: str, races: list[str] | None = None,
                confirm: bool = False, copy: bool = False) -> dict:
    """学会指定种族（None = 全部）的全部词语；返回写前/写后统计。"""
    settings.require_write()
    _require_confirm(confirm)
    wanted = list(races) if races else list(RACES)
    unknown = [r for r in wanted if r not in RACES]
    if unknown:
        raise BadRequest(f"未知种族：{', '.join(unknown)}")
    p = _player_path(path)
    nms_extras = _nms()[2]
    snapshot: dict[str, Any] = {}

    def mutate(readable: dict):
        snapshot["before"] = _words_by_race(readable)
        try:
            snapshot["added"] = nms_extras.learn_words(readable, wanted)
        except Exception as e:
            raise BadRequest(f"学习词语失败：{type(e).__name__}: {e}") from e
        return snapshot["before"]

    def verify(readable: dict):
        after = _words_by_race(readable)
        for race in wanted:
            before = snapshot["before"].get(race) or [0, 0]
            now = after.get(race) or [0, 0]
            if now[0] < now[1]:
                raise WriteRefused(f"写后校验失败：{race} 仍有词语未学会")
            if now[0] < before[0]:
                raise WriteRefused(f"写后校验失败：{race} 的已学词语减少了")
        for race, before in snapshot["before"].items():
            if race in wanted:
                continue
            if (after.get(race) or [0, 0]) != before:
                raise WriteRefused(f"写后校验失败：未修改的 {race} 词语被改动了")
        return after

    res = transaction.transact_save(str(p), mutate, verify, copy=copy)
    res["added"] = snapshot.get("added", 0)
    log.info("学习词语：%s %s（新增 %s）", p.name, "/".join(wanted), res["added"])
    return res


def apply_learn_all(path: str, group: str,
                    confirm: bool = False, copy: bool = False) -> dict:
    """学会一个知识分组的全部内容；``group`` 见 ``UNLOCK_GROUPS``。"""
    settings.require_write()
    _require_confirm(confirm)
    group = str(group or "").strip()
    if group not in UNLOCK_GROUPS:
        raise BadRequest(f"未知知识分组：{group!r}")
    p = _player_path(path)
    nms_extras = _nms()[2]
    snapshot: dict[str, Any] = {}

    def mutate(readable: dict):
        snapshot["before"] = nms_extras.knowledge(readable)
        try:
            snapshot["added"] = nms_extras.learn_all(readable, group)
        except Exception as e:
            raise BadRequest(f"学习知识失败：{type(e).__name__}: {e}") from e
        return snapshot["before"]

    def verify(readable: dict):
        after = nms_extras.knowledge(readable)
        before_groups = {g["group"]: g for g in snapshot["before"].get("groups", [])}
        after_groups = {g["group"]: g for g in after.get("groups", [])}
        target = after_groups.get(group) or {}
        if target.get("known") != target.get("total"):
            raise WriteRefused(f"写后校验失败：知识分组 {group} 未全部学会")
        for key, before in before_groups.items():
            if key == group:
                continue
            if (after_groups.get(key) or {}).get("known") != before.get("known"):
                raise WriteRefused(f"写后校验失败：未修改的知识分组 {key} 被改动了")
        return after

    res = transaction.transact_save(str(p), mutate, verify, copy=copy)
    res["added"] = snapshot.get("added", 0)
    log.info("学习知识：%s %s（新增 %s）", p.name, group, res["added"])
    return res


# ---------------------------------------------------------------- 任务


def quests(path: str | None = None) -> dict:
    """列出存档中的任务与完成状态（任务名依赖游戏语言表）。"""
    p, opened = _open(path)
    nms_quests = _nms()[3]
    try:
        rows = nms_quests.list_quests(opened.readable)
    except Exception as e:
        raise SaveFormatError(f"读取任务失败（可能需要游戏目录）：{type(e).__name__}: {e}") from e
    return {"path": str(p), "quests": rows}


def apply_skip_quests(path: str, keys: list[str],
                      confirm: bool = False, copy: bool = False) -> dict:
    """把选中的任务标记为完成（只改这些任务的 Progress）。"""
    settings.require_write()
    _require_confirm(confirm)
    picked = [str(k) for k in (keys or []) if str(k).strip()]
    if not picked:
        raise BadRequest("没有选中任务")
    p = _player_path(path)
    nms_quests = _nms()[3]
    snapshot: dict[str, Any] = {}

    def mutate(readable: dict):
        rows = nms_quests.list_quests(readable)
        snapshot["before"] = {r["key"]: r.get("status") for r in rows}
        try:
            snapshot["changed"] = nms_quests.skip_quests(readable, picked)
        except ValueError as e:
            raise BadRequest(f"跳过任务失败：{e}") from e
        return [r for r in rows if r["key"] in set(picked)]

    def verify(readable: dict):
        rows = nms_quests.list_quests(readable)
        after = {r["key"]: r.get("status") for r in rows}
        for key in picked:
            if key not in after:
                raise WriteRefused(f"写后校验失败：任务 {key} 不存在")
            if after[key] != "done":
                raise WriteRefused(f"写后校验失败：任务 {key} 仍未完成")
        for key, status in snapshot["before"].items():
            if key in picked:
                continue
            if after.get(key) != status:
                raise WriteRefused(f"写后校验失败：未修改的任务 {key} 被改动了")
        return [r for r in rows if r["key"] in set(picked)]

    res = transaction.transact_save(str(p), mutate, verify, copy=copy)
    res["changed"] = snapshot.get("changed", [])
    log.info("跳过任务：%s %d 个", p.name, len(picked))
    return res


# ---------------------------------------------------------------- 奖励


def rewards(path: str | None = None, group: str = "", query: str = "",
            limit: int = 400) -> dict:
    """奖励分组与条目（解锁/已领取状态）。"""
    p, opened = _open(path)
    nms_extras = _nms()[2]
    try:
        out = nms_extras.rewards(opened.readable, group=group, query=query, limit=limit)
    except Exception as e:
        raise SaveFormatError(f"读取奖励失败：{type(e).__name__}: {e}") from e
    return {"path": str(p), **out}


def _reward_sets(readable: dict, group: str) -> tuple[set[str], set[str]]:
    nms_extras = _nms()[2]
    ps = readable["BaseContext"]["PlayerStateData"]
    known = {str(x) for x in ps.get("KnownSpecials", [])}
    redeem_key = nms_extras.REWARD_GROUPS[group][2]
    redeemed = {str(x) for x in ps.get(redeem_key, [])}
    return known, redeemed


def apply_rewards(path: str, group: str, ids: list[str] | None = None,
                  unlock: bool | None = None, redeemed: bool | None = None,
                  confirm: bool = False, copy: bool = False) -> dict:
    """解锁/锁定奖励，或标记为已领取/可再次领取。"""
    settings.require_write()
    _require_confirm(confirm)
    group = str(group or "").strip()
    if group not in REWARD_GROUPS:
        raise BadRequest(f"未知奖励分组：{group!r}")
    if unlock is None and redeemed is None:
        raise BadRequest("没有要修改的奖励状态")
    picked = [str(i) for i in (ids or []) if str(i).strip()]
    p = _player_path(path)
    nms_extras = _nms()[2]
    snapshot: dict[str, Any] = {}

    def mutate(readable: dict):
        if not picked:
            all_rows = nms_extras.rewards(readable, group=group, limit=100_000).get("items") or []
            snapshot["ids"] = [str(r["id"]) for r in all_rows]
        else:
            snapshot["ids"] = picked
        snapshot["before"] = _reward_sets(readable, group)
        try:
            snapshot["changed"] = nms_extras.set_rewards(
                readable, group, ids=snapshot["ids"] or None,
                unlock=unlock, redeemed=redeemed)
        except (ValueError, KeyError) as e:
            raise BadRequest(f"修改奖励失败：{e}") from e
        return {"known": sorted(snapshot["before"][0]),
                "redeemed": sorted(snapshot["before"][1])}

    def verify(readable: dict):
        known, redeem = _reward_sets(readable, group)
        target = {"^" + i for i in snapshot["ids"]}
        if unlock is not None:
            for tid in target:
                if (tid in known) != bool(unlock):
                    raise WriteRefused(f"写后校验失败：奖励 {tid} 解锁状态不符")
        if redeemed is not None:
            for tid in target:
                if (tid in redeem) != bool(redeemed):
                    raise WriteRefused(f"写后校验失败：奖励 {tid} 领取状态不符")
        return {"known": sorted(known), "redeemed": sorted(redeem)}

    res = transaction.transact_save(str(p), mutate, verify, copy=copy)
    res["changed"] = snapshot.get("changed", {"changed": 0})
    log.info("奖励编辑：%s %s", p.name, group)
    return res


__all__ = [
    "RACES",
    "REWARD_GROUPS",
    "UNLOCK_GROUPS",
    "apply_inventory",
    "apply_learn_all",
    "apply_rewards",
    "apply_skip_quests",
    "apply_words",
    "inventories",
    "inventory",
    "knowledge",
    "quests",
    "rewards",
]
