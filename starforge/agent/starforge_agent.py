# /// script
# dependencies = ["NMSpy==185034.0", "pymhf[http_api]==0.2.5"]
#
# [tool.pymhf]
# exe = "NMS.exe"
# steam_gameid = 275850
# start_exe = false
# start_paused = false
# interactive_console = false
#
# [tool.pymhf.gui]
# shown = false
#
# [tool.pymhf.logging]
# log_dir = "."
# log_level = "info"
# window_name_override = "starforge agent"
# ///
"""starforge 游戏内 agent（pymhf 单文件 Mod）。

由 starforge 原生界面安装/启动，不需要命令行。暴露本机 HTTP 端点：
  GET  /StarforgeAgent/hello
  GET  /StarforgeAgent/player
  GET  /StarforgeAgent/system
  GET  /StarforgeAgent/planet
  GET  /StarforgeAgent/planet/scan
  GET  /StarforgeAgent/ships
  GET  /StarforgeAgent/multitool
  GET  /StarforgeAgent/freighter
  GET  /StarforgeAgent/pets
  PUT  /StarforgeAgent/teleport?glyphs=...&galaxy=...
  PUT  /StarforgeAgent/teleport/portal?glyphs=...&galaxy=...
  PUT  /StarforgeAgent/scan?mode=read
  PUT  /StarforgeAgent/restore

依赖 NMSpy（版本跟随游戏 build）与 pymhf[http_api]。
所有写操作先记录快照；传送失败可调用 /restore 还原。
"""
from __future__ import annotations

import ctypes
import hmac
import json
import logging
import os
import queue
import threading
import time
from functools import wraps
from pathlib import Path
from typing import Any

import nmspy.data.basic_types as basic
import nmspy.data.types as nms
from nmspy.common import gameData
from nmspy.engine import GetNodeAbsoluteTransMatrix
from pymhf import Mod
from pymhf.core.hooking import one_shot
from pymhf.core.http_api import endpoint

log = logging.getLogger("starforge.agent")

# launch() 每次启动生成一次性 token；pymhf endpoint 没有稳定的 request header 读取接口，
# 所以客户端用 ?token=... 传。为空表示用户手动启动（未经过 starforge），只报告
# auth=disabled，不假装有认证。
#
# 为什么还要读文件：游戏若由 **Steam** 拉起（steam://rungameid），进程不会继承
# starforge 设置的 STARFORGE_AGENT_TOKEN，环境变量方案会静默失效（实测 auth=disabled）。
# 因此 launch() 在启动前把 token 写到 `~/.starforge/agent/token`，这里按
# 环境变量 → token 文件 → state.json 的顺序解析。
def _resolve_agent_token() -> str:
    token = os.environ.get("STARFORGE_AGENT_TOKEN", "").strip()
    if token:
        return token
    try:
        base = Path.home() / ".starforge" / "agent"
        p = base / "token"
        if p.exists():
            text = p.read_text("utf-8").strip()
            if text:
                return text
        p = base / "state.json"
        if p.exists():
            data = json.loads(p.read_text("utf-8"))
            return str((data or {}).get("token") or "").strip()
    except Exception:                                      # noqa: BLE001
        pass
    return ""


_AGENT_TOKEN = _resolve_agent_token()
_SNAPSHOT_LIMIT = 20


def _auth_block(token: str = "") -> dict | None:
    if not _AGENT_TOKEN:
        return None
    if hmac.compare_digest(str(token or ""), _AGENT_TOKEN):
        return None
    return {"ok": False, "code": "E_AUTH",
            "error": "agent token 无效或缺失（通过 ?token= 传递）"}


def _snapshot_path() -> Path:
    home = os.environ.get("STARFORGE_HOME")
    base = Path(home) if home else (Path.home() / ".starforge")
    return base / "agent" / "snapshots.json"


def _read_snapshot_file() -> list[dict]:
    try:
        data = json.loads(_snapshot_path().read_text("utf-8"))
        rows = data.get("snapshots") if isinstance(data, dict) else None
        return [r for r in (rows or []) if isinstance(r, dict)]
    except (OSError, ValueError, TypeError):
        return []


def _persist_snapshot(location: dict, dest: dict, glyphs: str = "") -> dict:
    """传送前把快照写进 ~/.starforge/agent/snapshots.json；失败则不传送。"""
    path = _snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = _read_snapshot_file()
    record = {
        "time": time.time(),
        "location": dict(location),
        "destination": dict(dest),
        "glyphs": str(glyphs).upper(),
    }
    rows.append(record)
    data = {"version": 1, "updated": time.time(), "snapshots": rows[-_SNAPSHOT_LIMIT:]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return record


def _latest_snapshot() -> dict | None:
    rows = _read_snapshot_file()
    for row in reversed(rows):
        if isinstance(row.get("location"), dict):
            return row["location"]
    return None


def _game_thread(fn):
    """HTTP 线程不能直接读写游戏对象；统一排队到游戏主线程执行。"""
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        return self._run_on_game_thread(lambda: fn(self, *args, **kwargs))
    return wrapper


def _s(value: Any) -> str:
    try:
        return str(value).strip()
    except Exception:                                      # noqa: BLE001
        return ""


def _fixed(value: Any) -> str:
    try:
        return str(value).split("\x00", 1)[0]
    except Exception:                                      # noqa: BLE001
        return ""


# 模型文件名 → 船型（与 starforge.data.shipref 的规则一致；只看文件名再看全路径，
# 避免 `.../S-CLASS/BIOPARTS/BIOSHIP_PROC...` 这种目录名带 S-CLASS 的误判）。
_MODEL_TOKENS = (
    ("SENTINELSHIP", "sentinel"), ("FIGHTER", "fighter"), ("DROPSHIP", "hauler"),
    ("SCIENTIFIC", "explorer"), ("SHUTTLE", "shuttle"), ("S-CLASS", "exotic"),
    ("BIOSHIP", "living"), ("SAILSHIP", "solar"), ("BIGGS", "corvette"),
    ("CAPITALFREIGHTER", "freighter"), ("FREIGHTER", "freighter"),
    ("VINTAGEINTERCEPTOR", "sentinel"), ("INTERCEPTOR", "sentinel"),
)


def _type_from_model(filename: str) -> str:
    up = (filename or "").upper()
    base = up.rsplit("/", 1)[-1]
    for scope in (base, up):
        for token, type_ in _MODEL_TOKENS:
            if token in scope:
                return type_
    return "unknown"


# ---------------------------------------------------------------- 只读扩展（工具/货船/同伴）
#
# **两套结构不能混用**（/ships 已踩过）：
#   · 运行时 `cGcPlayerState`（nmspy/data/types.py）是 partial_struct，只声明了
#     mInventories / mShipResources 等字段，**没有** Multitools / Pets /
#     FreighterFleet；它的偏移和存档结构完全不同。
#   · 存档结构 `cGcPlayerStateData`（nmspy/data/exported_types.py）才有这些字段。
#
# 因此这里调用游戏自己的 `cGcPlayerState.SaveToData()`：把**当前运行时状态**
# 序列化到一份我们自己分配的 `cGcPlayerStateData` 缓冲（只写本地缓冲，不改游戏
# 状态），再按存档结构解析。实机 build 185034（2026-11-21）已与同会话存档逐项核对，
# 工具/同伴/货船/frigate 全部一致。
#
# 枚举名取自 nmspy 的 external_enums（写入时固定一份，避免依赖 import 顺序）。
_INV_CLASS = {0: "C", 1: "B", 2: "A", 3: "S"}
_ITEM_TYPE = {0: "Substance", 1: "Technology", 2: "Product"}
_FRIGATE_CLASS = {0: "Combat", 1: "Exploration", 2: "Mining", 3: "Diplomacy",
                  4: "Support", 5: "Normandy", 6: "DeepSpace",
                  7: "DeepSpaceCommon", 8: "Pirate", 9: "GhostShip", 10: "Swarm"}
_ALIEN_RACE = {0: "Traders", 1: "Warriors", 2: "Explorers", 3: "Robots",
               4: "Atlas", 5: "Diplomats", 6: "Exotics", 7: "None", 8: "Builders"}
_BIOME = {0: "Lush", 1: "Toxic", 2: "Scorched", 3: "Radioactive", 4: "Frozen",
          5: "Barren", 6: "Dead", 7: "Weird", 8: "Red", 9: "Green", 10: "Blue",
          11: "Test", 12: "Swamp", 13: "Lava", 14: "Waterworld", 15: "GasGiant"}
_CREATURE_TYPE = {
    0: "None", 1: "Bird", 2: "FlyingLizard", 3: "FlyingSnake", 4: "Butterfly",
    5: "FlyingBeetle", 6: "Beetle", 7: "Fish", 8: "Shark", 9: "Crab", 10: "Snake",
    11: "Dino", 12: "Antelope", 13: "Rodent", 14: "Cat", 15: "Fiend",
    16: "BugQueen", 17: "BugFiend", 18: "Drone", 19: "Quad", 20: "SpiderQuad",
    21: "SpiderQuadMini", 22: "Walker", 23: "Predator", 24: "PlayerPredator",
    25: "Prey", 26: "Passive", 27: "FishPredator", 28: "FishPrey",
    29: "FiendFishSmall", 30: "FiendFishBig", 31: "Jellyfish", 32: "LandJellyfish",
    33: "RockCreature", 34: "MiniFiend", 35: "Floater", 36: "Scuttler",
    37: "Slug", 38: "MiniDrone", 39: "MiniRobo", 40: "SpaceFloater",
    41: "JellyBoss", 42: "JellyBossBrood", 43: "LandSquid", 44: "Weird",
    45: "SeaSnake", 46: "SandWorm", 47: "ProtoRoller", 48: "ProtoFlyer",
    49: "ProtoDigger", 50: "Plough", 51: "Digger", 52: "Drill",
    53: "Brainless", 54: "Pet",
}


def _save_int(value: Any) -> int | None:
    """读 ctypes 标量/枚举。c_enum32 的 int() 在 pymhf 0.2.5 上会走 bytes，
    所以统一取 `.value` 再转换；失败返回 None（调用方标 unsupported）。"""
    try:
        raw = value.value if hasattr(value, "value") else value
        if isinstance(raw, bytes):
            return int.from_bytes(raw, "little")
        return int(raw)
    except Exception:                                      # noqa: BLE001
        return None


def _save_text(value: Any) -> str:
    """cTkFixedString/TkID（bytes）与 VariableSizeString（str）都能读。"""
    try:
        raw = value.value if hasattr(value, "value") else value
        if isinstance(raw, bytes):
            raw = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
        return str(raw).split("\x00", 1)[0].lstrip("^")
    except Exception:                                      # noqa: BLE001
        return ""


def _save_hex(value: Any) -> str:
    """固定字符串/ID 的原始字节（校准用）。"""
    try:
        raw = value.value if hasattr(value, "value") else value
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        return bytes(raw).hex()
    except Exception:                                      # noqa: BLE001
        return ""


def _seed_hex(value: Any) -> str:
    try:
        return "0x%016X" % (int(value.Seed) & 0xFFFFFFFFFFFFFFFF)
    except Exception:                                      # noqa: BLE001
        return ""


def _enum_name(value: Any, names: dict[int, str]) -> str | None:
    number = _save_int(value)
    if number is None:
        return None
    return names.get(number) or f"unknown({number})"


def _row() -> dict:
    return {"unsupported": [], "field_errors": {}}


def _take(row: dict, field: str, read, default=None):
    """读一个字段；失败时在行内记录 unsupported + 原始异常，绝不编造默认值。"""
    try:
        return read()
    except Exception as e:                                 # noqa: BLE001
        row.setdefault("unsupported", []).append(field)
        row.setdefault("field_errors", {})[field] = f"{type(e).__name__}: {e}"
        return default


def _finish(row: dict) -> dict:
    if not row.get("unsupported"):
        row.pop("unsupported", None)
    if not row.get("field_errors"):
        row.pop("field_errors", None)
    return row


def _inv_summary(container: Any, limit: int = 8) -> dict:
    """cGcInventoryContainer → 库存摘要（格子数/容量/前几个物品）。"""
    out = _row()
    out["name"] = _take(out, "Name", lambda: _save_text(container.Name), "")
    out["class"] = _take(out, "Class", lambda: _enum_name(container.Class, _INV_CLASS))
    out["width"] = _take(out, "Width", lambda: int(container.Width))
    out["height"] = _take(out, "Height", lambda: int(container.Height))
    out["filled"] = _take(out, "Slots", lambda: int(container.Slots.Size), 0)
    out["capacity"] = _take(out, "ValidSlotIndices",
                            lambda: int(container.ValidSlotIndices.Size))
    items: list[dict] = []

    def read_items():
        for i, element in enumerate(container.Slots.value):
            if i >= limit:
                break
            items.append({
                "id": _save_text(element.Id),
                "amount": int(element.Amount),
                "max": int(element.MaxAmount),
                "type": _enum_name(element.Type, _ITEM_TYPE),
            })
        return items

    _take(out, "Slots.items", read_items)
    out["items"] = items
    return _finish(out)


def _multitool_slot_row(mt: Any, index: int) -> dict:
    out = _row()
    out["slot"] = index
    out["name"] = _take(out, "Name", lambda: _save_text(mt.Name), "")
    out["seed"] = _take(out, "Seed", lambda: _seed_hex(mt.Seed), "")
    out["model"] = _take(out, "Resource.Filename",
                         lambda: _save_text(mt.Resource.Filename), "")
    out["type"] = _type_from_model(out["model"]) if out["model"] else None
    out["class"] = _take(out, "Store.Class",
                         lambda: _enum_name(mt.Store.Class, _INV_CLASS))
    out["slot_level"] = _take(out, "Layout.Level", lambda: int(mt.Layout.Level))
    out["primary_mode"] = _take(out, "PrimaryMode", lambda: int(mt.PrimaryMode))
    out["secondary_mode"] = _take(out, "SecondaryMode", lambda: int(mt.SecondaryMode))
    out["is_large"] = _take(out, "IsLarge", lambda: bool(mt.IsLarge))
    out["inventory"] = _take(out, "Store", lambda: _inv_summary(mt.Store))
    inventory = out.get("inventory") or {}
    out["empty"] = not (out["model"] or out["name"] or inventory.get("filled"))
    if out["empty"]:
        # 空槽的 Class/Level 是零值，展示成 C/1 会像"编造"，这里明确置空。
        out["class"] = None
        out["slot_level"] = None
    return _finish(out)


def _multitool_raw(mt: Any, index: int) -> dict:
    out = {"slot": index}
    out["name_hex"] = _take(out, "Name.hex", lambda: _save_hex(mt.Name), "")
    out["seed"] = _take(out, "Seed", lambda: _save_int(mt.Seed.Seed))
    out["model_size"] = _take(out, "Resource.Filename.Size",
                              lambda: int(mt.Resource.Filename.Size))
    out["store_class"] = _take(out, "Store.Class", lambda: _save_int(mt.Store.Class))
    out["store_slots"] = _take(out, "Store.Slots.Size",
                               lambda: int(mt.Store.Slots.Size))
    out["layout_level"] = _take(out, "Layout.Level", lambda: int(mt.Layout.Level))
    return _finish(out)


def _multitool_payload(data: Any, raw_limit: int = 3) -> dict:
    out = _row()
    slots = _take(
        out, "Multitools",
        lambda: [_multitool_slot_row(mt, i) for i, mt in enumerate(data.Multitools)],
        None)
    if slots is None:
        out.update({"ok": False, "unsupported": True,
                    "error": "存档结构里读不到 Multitools（SaveToData 字段缺失）"})
        return _finish(out)
    out["slots"] = slots
    owned = [s for s in slots if not s.get("empty")]
    out["count"] = len(owned)
    out["current"] = {
        "model": _take(out, "CurrentWeapon.Filename",
                       lambda: _save_text(data.CurrentWeapon.Filename), "") or None,
        "seed": _take(out, "CurrentWeapon.GenerationSeed",
                      lambda: _seed_hex(data.CurrentWeapon.GenerationSeed), "") or None,
    }
    out["current"]["type"] = (_type_from_model(out["current"]["model"])
                              if out["current"]["model"] else None)
    current_slot = None
    seed = out["current"]["seed"]
    if seed and seed != "0x0000000000000000":
        for row in owned:
            if row.get("seed") == seed:
                current_slot = row["slot"]
                break
    if current_slot is None and out["current"]["model"]:
        for row in owned:
            if row.get("model") == out["current"]["model"]:
                current_slot = row["slot"]
                break
    out["current_slot"] = current_slot
    out["raw"] = _take(
        out, "raw",
        lambda: [_multitool_raw(mt, i)
                 for i, mt in enumerate(data.Multitools) if i < max(0, raw_limit)],
        [])
    out["source"] = ("cGcPlayerState.SaveToData() → cGcPlayerStateData.Multitools[6]"
                     "（存档布局；不是运行时 cGcPlayerState 偏移）")
    out["ok"] = True
    return _finish(out)


def _freighter_block(data: Any) -> dict:
    out = _row()
    out["name"] = _take(out, "PlayerFreighterName",
                        lambda: _save_text(data.PlayerFreighterName), "")
    out["model"] = _take(out, "CurrentFreighter.Filename",
                         lambda: _save_text(data.CurrentFreighter.Filename), "")
    out["seed"] = _take(out, "CurrentFreighter.Seed",
                        lambda: _seed_hex(data.CurrentFreighter.Seed), "")
    out["home_system_seed"] = _take(out, "CurrentFreighterHomeSystemSeed",
                                    lambda: _seed_hex(data.CurrentFreighterHomeSystemSeed), "")
    out["type"] = _type_from_model(out["model"]) if out["model"] else None
    out["inventory"] = _take(out, "FreighterInventory",
                             lambda: _inv_summary(data.FreighterInventory))
    out["cargo"] = _take(out, "FreighterInventory_Cargo",
                         lambda: _inv_summary(data.FreighterInventory_Cargo))
    out["tech"] = _take(out, "FreighterInventory_TechOnly",
                        lambda: _inv_summary(data.FreighterInventory_TechOnly))
    out["layout_level"] = _take(out, "FreighterLayout.Level",
                                lambda: int(data.FreighterLayout.Level))
    inventory = out.get("inventory") or {}
    out["class"] = inventory.get("class")
    seed = out.get("seed") or ""
    seed_ok = seed not in ("", "0x0000000000000000", "0xFFFFFFFFFFFFFFFF")
    out["owned"] = bool(out.get("name") or out.get("model")
                        or inventory.get("filled") or seed_ok)
    return _finish(out)


def _fleet_slot_row(f: Any, index: int) -> dict:
    out = _row()
    out["slot"] = index
    out["model"] = _take(out, "Resource.Filename",
                         lambda: _save_text(f.Resource.Filename), "")
    out["seed"] = _take(out, "Resource.Seed", lambda: _seed_hex(f.Resource.Seed), "")
    out["type"] = _type_from_model(out["model"]) if out["model"] else None
    out["inventory"] = _take(out, "Inventory", lambda: _inv_summary(f.Inventory))
    out["cargo"] = _take(out, "Inventory_Cargo", lambda: _inv_summary(f.Inventory_Cargo))
    out["dismissed"] = _take(out, "Dismissed", lambda: bool(f.Dismissed))
    seed = out.get("seed") or ""
    filled = (out.get("inventory") or {}).get("filled") or 0
    empty_seeds = ("", "0x0000000000000000", "0xFFFFFFFFFFFFFFFF")
    out["empty"] = not (out["model"] or filled or seed not in empty_seeds)
    return _finish(out)


def _frigate_row(fr: Any, index: int) -> dict:
    out = _row()
    out["slot"] = index
    out["name"] = _take(out, "CustomName", lambda: _save_text(fr.CustomName), "")
    out["seed"] = _take(out, "ResourceSeed", lambda: _seed_hex(fr.ResourceSeed), "")
    out["home_system_seed"] = _take(out, "HomeSystemSeed",
                                    lambda: _seed_hex(fr.HomeSystemSeed), "")
    out["class"] = _take(out, "FrigateClass",
                         lambda: _enum_name(fr.FrigateClass, _FRIGATE_CLASS))
    out["inventory_class"] = _take(out, "InventoryClass",
                                   lambda: _enum_name(fr.InventoryClass, _INV_CLASS))
    out["race"] = _take(out, "Race", lambda: _enum_name(fr.Race, _ALIEN_RACE))
    out["damage_taken"] = _take(out, "DamageTaken", lambda: int(fr.DamageTaken))
    out["expeditions"] = _take(out, "TotalNumberOfExpeditions",
                               lambda: int(fr.TotalNumberOfExpeditions))
    out["successes"] = _take(out, "TotalNumberOfSuccessfulEvents",
                             lambda: int(fr.TotalNumberOfSuccessfulEvents))
    out["failures"] = _take(out, "TotalNumberOfFailedEvents",
                            lambda: int(fr.TotalNumberOfFailedEvents))
    out["stats"] = _take(out, "Stats", lambda: [int(x) for x in fr.Stats.value])
    out["traits"] = _take(out, "TraitIDs",
                          lambda: [_save_text(x) for x in fr.TraitIDs.value])
    return _finish(out)


def _freighter_raw(data: Any, raw_limit: int = 2) -> dict:
    out = _row()
    out["current"] = {
        "filename_size": _take(out, "CurrentFreighter.Filename.Size",
                               lambda: int(data.CurrentFreighter.Filename.Size)),
        "filename_hex": _take(out, "CurrentFreighter.Filename.hex",
                              lambda: _save_hex(data.CurrentFreighter.Filename), ""),
        "name_hex": _take(out, "PlayerFreighterName.hex",
                          lambda: _save_hex(data.PlayerFreighterName), ""),
        "seed": _take(out, "CurrentFreighter.Seed.Seed",
                      lambda: _save_int(data.CurrentFreighter.Seed.Seed)),
        "home_seed": _take(out, "CurrentFreighterHomeSystemSeed.Seed",
                           lambda: _save_int(data.CurrentFreighterHomeSystemSeed.Seed)),
        "inventory_class": _take(out, "FreighterInventory.Class",
                                 lambda: _save_int(data.FreighterInventory.Class)),
        "inventory_slots": _take(out, "FreighterInventory.Slots.Size",
                                 lambda: int(data.FreighterInventory.Slots.Size)),
    }
    out["fleet"] = _take(
        out, "FreighterFleet.raw",
        lambda: [{"slot": i,
                  "model": _save_text(f.Resource.Filename),
                  "seed": _save_int(f.Resource.Seed.Seed),
                  "dismissed": bool(f.Dismissed)}
                 for i, f in enumerate(data.FreighterFleet) if i < max(0, raw_limit)],
        [])
    out["frigates"] = _take(
        out, "FleetFrigates.raw",
        lambda: [{"slot": i,
                  "name_hex": _save_hex(fr.CustomName),
                  "seed": _save_int(fr.ResourceSeed.Seed),
                  "class": _save_int(fr.FrigateClass)}
                 for i, fr in enumerate(data.FleetFrigates.value)
                 if i < max(0, raw_limit)],
        [])
    return _finish(out)


def _freighter_payload(data: Any, raw_limit: int = 3) -> dict:
    out = _row()
    block = _take(out, "Freighter", lambda: _freighter_block(data), None)
    if block is None:
        out.update({"ok": False, "unsupported": True,
                    "error": "存档结构里读不到货船字段（SaveToData 字段缺失）"})
        return _finish(out)
    core = {"CurrentFreighter.Filename", "CurrentFreighter.Seed", "FreighterInventory"}
    if core <= set(block.get("unsupported") or ()):
        out.update({"ok": False, "unsupported": True,
                    "error": "存档结构里读不到货船字段（SaveToData 字段缺失）"})
        return _finish(out)
    out["freighter"] = block
    fleet = _take(
        out, "FreighterFleet",
        lambda: [_fleet_slot_row(f, i) for i, f in enumerate(data.FreighterFleet)],
        None)
    if fleet is None:
        out["fleet"] = []
    else:
        out["fleet_slots"] = len(fleet)
        out["fleet"] = [row for row in fleet if not row.get("empty")]
    out["fleet_count"] = len(out["fleet"])
    if not out["fleet"]:
        out["fleet_note"] = "FreighterFleet 固定槽都为空（当前未持有其它货船）"
    frigates = _take(
        out, "FleetFrigates",
        lambda: [_frigate_row(fr, i)
                 for i, fr in enumerate(data.FleetFrigates.value) if i < 100],
        None)
    if frigates is None:
        out["frigates"] = []
    else:
        out["frigates"] = frigates
    out["frigate_count"] = len(out["frigates"])
    out["raw"] = _take(out, "raw", lambda: _freighter_raw(data, raw_limit), {})
    out["source"] = ("cGcPlayerState.SaveToData() → cGcPlayerStateData."
                     "CurrentFreighter / FreighterInventory* / FreighterFleet / FleetFrigates")
    out["ok"] = True
    return _finish(out)


def _pet_row(pet: Any, index: int) -> dict:
    out = _row()
    out["index"] = index
    out["species"] = _take(out, "CreatureID", lambda: _save_text(pet.CreatureID), "")
    out["name"] = _take(out, "CustomName", lambda: _save_text(pet.CustomName), "")
    if not out["name"]:
        out["name"] = _take(out, "CustomSpeciesName",
                            lambda: _save_text(pet.CustomSpeciesName), "")
    out["type_id"] = _take(out, "CreatureType", lambda: _save_int(pet.CreatureType))
    out["type"] = (_CREATURE_TYPE.get(out["type_id"]) if out["type_id"] is not None
                   else None)
    out["biome_id"] = _take(out, "Biome", lambda: _save_int(pet.Biome))
    out["biome"] = _BIOME.get(out["biome_id"]) if out["biome_id"] is not None else None
    out["predator"] = _take(out, "Predator", lambda: bool(pet.Predator))
    out["has_fur"] = _take(out, "HasFur", lambda: bool(pet.HasFur))
    out["egg_modified"] = _take(out, "EggModified", lambda: bool(pet.EggModified))
    out["trust"] = _take(out, "Trust", lambda: round(float(pet.Trust), 4))
    out["scale"] = _take(out, "Scale", lambda: round(float(pet.Scale), 4))
    out["birth_time"] = _take(out, "BirthTime", lambda: int(pet.BirthTime))
    out["ua"] = _take(out, "UA", lambda: "0x%016X" % (int(pet.UA) & 0xFFFFFFFFFFFFFFFF))
    out["descriptors"] = _take(
        out, "Descriptors",
        lambda: [_save_text(x) for i, x in enumerate(pet.Descriptors.value) if i < 64],
        [])
    out["seeds"] = {
        "creature": _take(out, "CreatureSeed", lambda: _seed_hex(pet.CreatureSeed), ""),
        "creature_secondary": _take(out, "CreatureSecondarySeed",
                                    lambda: _seed_hex(pet.CreatureSecondarySeed), ""),
        "species": _take(out, "SpeciesSeed", lambda: _seed_hex(pet.SpeciesSeed), ""),
        "genus": _take(out, "GenusSeed", lambda: _seed_hex(pet.GenusSeed), ""),
        "bone_scale": _take(out, "BoneScaleSeed",
                            lambda: _seed_hex(pet.BoneScaleSeed), ""),
        "colour_base": _take(out, "ColourBaseSeed",
                             lambda: _seed_hex(pet.ColourBaseSeed), ""),
    }
    out["traits"] = _take(out, "Traits", lambda: [round(float(x), 4) for x in pet.Traits])
    out["moods"] = _take(out, "Moods", lambda: [round(float(x), 4) for x in pet.Moods])
    out["has_been_summoned"] = _take(out, "HasBeenSummoned",
                                     lambda: bool(pet.HasBeenSummoned))
    # 存档结构没有"当前出战同伴"索引；active 不猜，明确标 unsupported。
    out["active"] = None
    out["active_supported"] = False
    out["active_note"] = ("cGcPlayerStateData 没有当前出战标记，只能读 "
                          "HasBeenSummoned（是否召唤过）")
    return _finish(out)


def _pet_raw(pet: Any, index: int) -> dict:
    out = {"slot": index}
    out["name_hex"] = _take(out, "CustomName.hex", lambda: _save_hex(pet.CustomName), "")
    out["creature"] = _take(out, "CreatureID", lambda: _save_text(pet.CreatureID), "")
    out["creature_seed"] = _take(out, "CreatureSeed.Seed",
                                 lambda: _save_int(pet.CreatureSeed.Seed))
    out["species_seed"] = _take(out, "SpeciesSeed.Seed",
                                lambda: _save_int(pet.SpeciesSeed.Seed))
    out["type"] = _take(out, "CreatureType", lambda: _save_int(pet.CreatureType))
    out["biome"] = _take(out, "Biome", lambda: _save_int(pet.Biome))
    out["summoned"] = _take(out, "HasBeenSummoned", lambda: bool(pet.HasBeenSummoned))
    return _finish(out)


def _pets_payload(data: Any, raw_limit: int = 3) -> dict:
    out = _row()

    def read_pets():
        rows = []
        for i, pet in enumerate(data.Pets):
            try:
                species = _save_text(pet.CreatureID)
            except Exception as e:                         # noqa: BLE001
                out["field_errors"].setdefault("Pets.CreatureID", f"{type(e).__name__}: {e}")
                continue
            if not species:
                continue                                   # 空槽
            rows.append(_pet_row(pet, i))
        return rows

    pets = _take(out, "Pets", read_pets, None)
    if pets is None:
        out.update({"ok": False, "unsupported": True,
                    "error": "存档结构里读不到 Pets（SaveToData 字段缺失）"})
        return _finish(out)
    out["pets"] = pets
    out["count"] = len(pets)
    if not pets:
        out["note"] = "Pets[30] 全是空槽（当前存档没有同伴）"
    out["raw"] = _take(
        out, "raw",
        lambda: [_pet_raw(pet, i) for i, pet in enumerate(data.Pets)
                 if i < max(0, raw_limit)],
        [])
    out["source"] = "cGcPlayerState.SaveToData() → cGcPlayerStateData.Pets[30]"
    out["ok"] = True
    return _finish(out)


def _save_state_data():
    """把当前运行时玩家状态序列化成存档结构。→ (data, error)"""
    try:
        import nmspy.data.exported_types as nmse
    except Exception as e:                                 # noqa: BLE001
        return None, f"nmspy.exported_types 不可用：{type(e).__name__}: {e}"
    ps = gameData.player_state
    if ps is None:
        return None, "还没进入存档（player_state 为空）"
    try:
        data = nmse.cGcPlayerStateData()
        ps.SaveToData(ctypes.byref(data))
        # 哨兵：SaveToData 未执行（hook 未绑上）时缓冲仍是全零；
        # 玩家背包必然有槽、存档也一定有游戏时长，两者都空才算失败。
        if int(data.Inventory.Slots.Size) <= 0 and int(data.TotalPlayTime) <= 0:
            return None, "SaveToData 没有填充数据（游戏函数未绑定？）"
        return data, ""
    except Exception as e:                                 # noqa: BLE001
        return None, f"SaveToData 失败：{type(e).__name__}: {e}"


def _location() -> dict | None:
    try:
        ps = gameData.player_state
        if ps is None:
            return None
        loc = ps.mLocation
        ga = loc.GalacticAddress
        return {
            "planet": int(ga.PlanetIndex),                 # 1-based
            "system": int(ga.SolarSystemIndex),
            "voxel_x": int(ga.VoxelX),
            "voxel_y": int(ga.VoxelY),
            "voxel_z": int(ga.VoxelZ),
            "reality": int(loc.RealityIndex),
        }
    except Exception:                                      # noqa: BLE001
        return None


def _multiplayer() -> bool:
    """多人状态；读不到时按单人处理（真正的写操作仍还有 build 闸门）。"""
    try:
        app = gameData.GcApplication
        return bool(getattr(app, "mbMultiplayerActive", False)) if app else False
    except Exception:                                      # noqa: BLE001
        return False


def _multiplayer_block() -> dict | None:
    if not _multiplayer():
        return None
    return {"ok": False, "code": "E_MULTIPLAYER", "multiplayer": True,
            "error": "多人模式已启用：传送/还原/扫描写操作被禁用"}


def _pack_ua(loc: dict) -> int:
    return (
        (int(loc["voxel_x"]) & 0xFFF)
        | ((int(loc["voxel_z"]) & 0xFFF) << 12)
        | ((int(loc["voxel_y"]) & 0xFF) << 24)
        | ((int(loc["reality"]) & 0xFF) << 32)
        | ((int(loc["system"]) & 0xFFF) << 40)
        | ((int(loc["planet"]) & 0xF) << 52)
    )


def _decode_glyphs(glyphs: str) -> dict:
    text = str(glyphs).strip().upper()
    if len(text) != 12 or any(c not in "0123456789ABCDEF" for c in text):
        raise ValueError("需要 12 位十六进制传送门地址")
    planet = int(text[0], 16)
    system = int(text[1:4], 16)
    vy = int(text[4:6], 16)
    vz = int(text[6:9], 16)
    vx = int(text[9:12], 16)

    def signed(v: int, bits: int) -> int:
        return v - (1 << bits) if v & (1 << (bits - 1)) else v

    if not 1 <= planet <= 6:
        raise ValueError("第 1 位必须是 1..6（行星）")
    if system in (0, 0xFFF):
        raise ValueError("系统索引不能是 000 或 FFF")
    if vy == 0x80:
        raise ValueError("Y 坐标 80 是保留值")
    if vz == 0x800 or vx == 0x800:
        raise ValueError("X/Z 坐标 800 是保留值")
    return {"planet": planet, "system": system,
            "voxel_x": signed(vx, 12), "voxel_y": signed(vy, 8), "voxel_z": signed(vz, 12)}


def _planet_info(planet) -> dict:
    pi = planet.mPlanetData.PlanetInfo
    out = {
        "name": _fixed(planet.mPlanetData.Name),
        "planet_type": _fixed(pi.PlanetType),
        "biome": _fixed(pi.PlanetType),
        "weather": _fixed(pi.Weather),
        "fauna": _fixed(pi.Fauna),
        "flora": _fixed(pi.Flora),
        "resources": _fixed(pi.Resources),
        "description": _fixed(pi.PlanetDescription),
        "sentinels": [_fixed(x) for x in pi.SentinelsPerDifficulty],
        "extreme_weather": bool(pi.IsWeatherExtreme),
        "special_fauna": bool(pi.SpecialFauna),
    }
    try:
        data = planet.mPlanetData
        out["creature_ids"] = [_s(x) for x in data.CreatureIDs]
        out["common_substance"] = _s(data.CommonSubstanceID)
        out["rare_substance"] = _s(data.RareSubstanceID)
        out["uncommon_substance"] = _s(data.UncommonSubstanceID)
        out["planet_index"] = int(data.PlanetIndex)
    except Exception as e:                                 # noqa: BLE001
        out["extra_error"] = f"{type(e).__name__}: {e}"
    return out


def _planet_scan_info(planet) -> dict:
    """当前行星完整档案；每个扩展字段单独读取，失败的字段明确标记 unsupported。"""
    out = _planet_info(planet)
    out.pop("extra_error", None)
    data = planet.mPlanetData
    errors: dict[str, str] = {}
    unsupported: list[str] = []

    def read(name: str, convert):
        try:
            return convert(getattr(data, name))
        except Exception as e:                             # noqa: BLE001
            errors[name] = f"{type(e).__name__}: {e}"
            unsupported.append(name)
            return None

    def hints(values):
        rows = []
        for item in values:
            try:
                rows.append({"hint": _s(item.Hint), "icon": _s(item.Icon)})
            except Exception as e:                         # noqa: BLE001
                errors.setdefault("ExtraResourceHints",
                                  f"{type(e).__name__}: {e}")
                unsupported.append("ExtraResourceHints")
                return None
        return rows

    values = {
        "CreatureIDs": read("CreatureIDs", lambda v: [_s(x) for x in v]),
        "CommonSubstanceID": read("CommonSubstanceID", _s),
        "RareSubstanceID": read("RareSubstanceID", _s),
        "UncommonSubstanceID": read("UncommonSubstanceID", _s),
        "ExtraResourceHints": read("ExtraResourceHints", hints),
    }
    aliases = {
        "CreatureIDs": "creature_ids",
        "CommonSubstanceID": "common_substance",
        "RareSubstanceID": "rare_substance",
        "UncommonSubstanceID": "uncommon_substance",
        "ExtraResourceHints": "extra_resource_hints",
    }
    for raw_name, value in values.items():
        if value is not None:
            out[aliases[raw_name]] = value
        out[raw_name] = value
    out["complete"] = not unsupported
    if unsupported:
        out["unsupported"] = sorted(set(unsupported))
    if errors:
        out["field_errors"] = errors
    return out


# cGcPortalComponent::WarpPlayer 的调用路径分三档校准（见 _portal_warp）。
# 2026-11-21 实机（build 185034）结论：
#   · warp_only    → 无效（位置不变，不崩）
#   · prepare_warp → ✅ 成功传送到目标行星（UA/位置均改变，日志有 APPVIEW 加载）
#   · full         → 未测（OnAttached 可能多余）
_PORTAL_WARP_CALIBRATED = True
PORTAL_STAGES = ("warp_only", "prepare_warp", "full")
_PORTAL_DEFAULT_STAGE = "prepare_warp"


def _portal_api() -> dict:
    try:
        cls = nms.cGcPortalComponent
    except Exception as e:                                 # noqa: BLE001
        return {"available": False, "error": f"{type(e).__name__}: {e}"}
    missing = [name for name in ("OnAttached", "Prepare", "WarpPlayer")
               if not callable(getattr(cls, name, None))]
    if missing:
        return {"available": False, "error": "缺少 " + ", ".join(missing)}
    return {"available": True, "calibrated": bool(_PORTAL_WARP_CALIBRATED)}


def _portal_unsupported(detail: str = "") -> dict:
    out = {"ok": False, "code": "E_UNSUPPORTED", "unsupported": True,
           "error": "本版未实现/需实机校准",
           "note": "teleport.portal 为实验端点：raw cGcPortalComponent 构造和落点确认"
                   "都需要 Windows 实机校准"}
    if detail:
        out["detail"] = detail
    return out


def _portal_warp(dest: dict, stage: str = _PORTAL_DEFAULT_STAGE) -> dict:
    """尝试通过 cGcPortalComponent 触发 portal warp。

    分三档，便于实机逐级验证（任何一档都可能让游戏崩溃，务必在可丢弃存档上试）：

      · ``warp_only``    —— 只设置 `mPortalData.mTargetUA/mbActive` 后调 `WarpPlayer`
      · ``prepare_warp`` —— 先 `Prepare()` 再 `WarpPlayer`
      · ``full``         —— `OnAttached()` + `Prepare()` + `WarpPlayer`

    依据：nmspy 的手工逆向定义 `cGcPortalComponent.PersistentData{mUA, mTargetUA,
    mBuildingSeed, mbActive}`，且 `WarpPlayer` 的文档明确说“warps to
    PersistentData::mTargetUA, if mbActive is true”。
    """
    api = _portal_api()
    if not api.get("available"):
        return _portal_unsupported(api.get("error") or "cGcPortalComponent 不可用")
    stage = (stage or "warp_only").strip().lower()
    if stage not in PORTAL_STAGES:
        return {"ok": False, "code": "E_BAD_STAGE",
                "error": f"stage 必须是 {', '.join(PORTAL_STAGES)}，收到 {stage!r}"}
    try:
        cls = nms.cGcPortalComponent
        size = max(0x1000, ctypes.sizeof(cls) + 0x100)
        buffer = ctypes.create_string_buffer(size)
        component = cls.from_buffer(buffer)
        target_ua = _pack_ua(dest)
        if stage == "full":
            component.OnAttached()
        component.mPortalData.mTargetUA = target_ua
        component.mPortalData.mbActive = True
        if stage in ("prepare_warp", "full"):
            component.Prepare()
        component.WarpPlayer()
        # buffer 必须活到 warp 完成；由调用方持有（见 teleport_portal）。
        return {"ok": True, "experimental": True, "stage": stage, "confirmed": False,
                "target_ua": f"0x{target_ua:016X}",
                "_buffer": buffer,
                "note": "已调用 WarpPlayer；落点是否生效需在游戏内确认，失败请用 restore 还原"}
    except Exception as e:                                 # noqa: BLE001
        return _portal_unsupported(f"{type(e).__name__}: {e}")


class StarforgeAgent(Mod):
    __author__ = "starforge"
    __description__ = "starforge 游戏内通道：状态读取 / 传送 / 扫描"
    __version__ = "0.1.0"

    def __init__(self) -> None:
        super().__init__()
        self._snapshot: dict | None = None
        self._last_error = ""
        self._portal_buffer = None
        self.instant_scan = False
        self._game_queue: queue.Queue = queue.Queue()
        self._game_thread_id: int | None = None

    # ------------------------------------------------------------ 延迟绑定
    #
    # nmspy 的 `_INTERNAL_LoadSingletons` 用 `@one_shot` 在**下一次** StateChange 时绑定
    # `gameData.GcApplication`。我们注入时若已在存档内、又不再切状态，就会一直绑不上。
    #
    # 这里用**同一个函数、同一种取指针方式**再挂一次 one_shot（语义已被 nmspy 证明安全）：
    # 注入后只要发生一次状态切换（进存档、开/关菜单等）就会绑定。
    # 不采用"每帧在 cGcApplication.Update 里 map_struct"的写法——实测那次会让游戏以
    # “模组冲突”退出（见 docs/AGENT-INJECT-CRASH.md 第 13 节）。
    @one_shot
    @nms.cTkFSM.StateChange.after
    def _bind_app_on_state_change(self, this, *args):
        if gameData.GcApplication is not None:
            return
        try:
            from pymhf.core.memutils import get_addressof, map_struct

            gameData.GcApplication = map_struct(get_addressof(this), nms.cGcApplication)
            log.info("延迟绑定 cGcApplication 成功（状态切换触发）")
        except Exception as e:                             # noqa: BLE001
            log.warning("延迟绑定失败：%s", e)

    def _run_on_game_thread(self, fn, timeout: float = 6.0):
        if self._game_thread_id == threading.get_ident():
            return fn()
        ev = threading.Event()
        box: dict = {}
        self._game_queue.put((fn, box, ev))
        if not ev.wait(timeout):
            return {"ok": False, "code": "E_GAME_BUSY",
                    "error": "游戏主线程繁忙/未进入场景；请稍后重试"}
        if "error" in box:
            return {"ok": False, "error": box["error"]}
        return box.get("result")

    @nms.cGcApplication.Update.after
    def _drain_game_queue(self, this):
        self._game_thread_id = threading.get_ident()
        while True:
            try:
                fn, box, ev = self._game_queue.get_nowait()
            except queue.Empty:
                break
            try:
                box["result"] = fn()
            except Exception as e:                          # noqa: BLE001
                box["error"] = f"{type(e).__name__}: {e}"
            finally:
                ev.set()

    @nms.cGcBinoculars.UpdateScanBarProgress.before
    def _force_scan_progress(self, this, lfScanProgress):
        if self.instant_scan and not _multiplayer() and lfScanProgress < 1:
            return (this, 1)
        return None

    # ------------------------------------------------------------ 基础

    @endpoint("/hello", method="GET")
    @_game_thread
    def hello(self, token: str = "") -> dict:
        blocked = _auth_block(token)
        if blocked:
            return blocked
        try:
            import nmspy

            version = getattr(nmspy, "__version__", "unknown")
        except Exception:                                  # noqa: BLE001
            version = "unknown"
        app = gameData.GcApplication
        try:
            in_game = gameData.player_state is not None
        except Exception:                                  # noqa: BLE001
            in_game = False
        multiplayer = _multiplayer()
        write_ok = not multiplayer
        portal = _portal_api()
        return {"ok": True, "agent": self.__version__, "nmspy": version,
                "game_attached": app is not None, "in_game": in_game,
                "multiplayer": multiplayer,
                "auth": "token-query" if _AGENT_TOKEN else "disabled",
                "snapshots": str(_snapshot_path()),
                "capabilities": {
                    "player": True, "system": True, "planet": True,
                    "planet.scan": True, "ships": True,
                    "multitool": True, "freighter": True, "pets": True,
                    "teleport": write_ok, "teleport.portal": write_ok and portal["available"],
                    "portal.calibrated": bool(portal.get("calibrated")),
                   "portal.api": portal,
                    "scan": "read", "scan.discover": False,
                    "scan.instant": write_ok, "restore": write_ok,
                }}

    @endpoint("/player", method="GET")
    @_game_thread
    def player(self, token: str = "") -> dict:
        blocked = _auth_block(token)
        if blocked:
            return blocked
        loc = _location()
        if loc is None:
            return {"ok": False, "error": "玩家状态不可用（是否已进入存档？）"}
        out = {"ok": True, "location": loc, "ua": "0x%016X" % _pack_ua(loc)}
        try:
            ps = gameData.player_state
            out["stats"] = {
                "units": int(ps.muUnits), "nanites": int(ps.muNanites),
                "quicksilver": int(ps.muSpecials), "health": int(ps.miHealth),
                "shield": int(ps.miShield), "ship_health": int(ps.miShipHealth),
            }
        except Exception as e:                             # noqa: BLE001
            out["stats_error"] = f"{type(e).__name__}: {e}"
        try:
            pos = GetNodeAbsoluteTransMatrix(gameData.player.mRootNode).pos
            out["position"] = {"x": float(pos.x), "y": float(pos.y), "z": float(pos.z)}
        except Exception as e:                             # noqa: BLE001
            out["position_error"] = f"{type(e).__name__}: {e}"
        try:
            ss = gameData.simulation.mpSolarSystem
            if ss:
                name = basic.cTkFixedString0x80()
                ss.contents.GetName(ctypes.byref(name))
                out["system_name"] = _fixed(name)
        except Exception as e:                             # noqa: BLE001
            out["system_name_error"] = f"{type(e).__name__}: {e}"
        return out

    @endpoint("/ships", method="GET")
    @_game_thread
    def ships(self, token: str = "") -> dict:
        """游戏内已拥有的飞船（`cGcPlayerState.mShipResources[12]` + `miPrimaryShip`）。

        字段取值注意：
          · `cGcResourceElement.Seed` 是 `basic.GcSeed` 结构体，不是 int → 取 `.Seed`；
          · `Filename` 是 `VariableSizeString`，字符串在 `.value`；
          · 空槽的种子是 `0xFFFFFFFFFFFFFFFF`（-1 哨兵）。
        返回里的 `raw` 保留每槽原始值，便于后续校准。
        """
        blocked = _auth_block(token)
        if blocked:
            return blocked

        def _res_filename(res) -> str:
            try:
                return str(res.Filename.value)
            except Exception:                              # noqa: BLE001
                return _s(getattr(res, "Filename", ""))

        def _res_seed(res) -> int:
            value = getattr(res, "Seed", None)
            for attr in ("Seed", "value"):
                inner = getattr(value, attr, None)
                if isinstance(inner, int):
                    return inner & 0xFFFFFFFFFFFFFFFF
            try:
                return int(value) & 0xFFFFFFFFFFFFFFFF
            except Exception:                              # noqa: BLE001
                return 0

        try:
            ps = gameData.player_state
            if ps is None:
                return {"ok": False, "error": "还没进入存档（player_state 为空）"}
            resources = list(getattr(ps, "mShipResources", ()) or ())
            primary = int(getattr(ps, "miPrimaryShip", -1))
            empty = 0xFFFFFFFFFFFFFFFF
            raw, rows = [], []
            for i, res in enumerate(resources[:12]):
                filename = _res_filename(res)
                seed = _res_seed(res)
                raw.append({"slot": i, "filename": filename, "seed": "0x%016X" % seed})
                if seed in (0, empty) and not filename:
                    continue
                rows.append({"slot": i, "filename": filename, "seed": "0x%016X" % seed,
                             "type": _type_from_model(filename)})
            return {"ok": True, "primary": primary, "count": len(resources),
                    "ships": rows, "raw": raw,
                    "note": "slot = mShipResources 下标；primary = miPrimaryShip"}
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ------------------------------------------------------------ 只读：工具/货船/同伴

    @endpoint("/multitool", method="GET")
    @_game_thread
    def multitool(self, token: str = "") -> dict:
        """当前多功能工具 + 全部 6 个工具槽（名称/种子/等级/库存摘要）。

        取数路径：`cGcPlayerState.SaveToData()` → `cGcPlayerStateData.Multitools[6]`。
        不解引用运行时 `cGcPlayerState` 的偏移（见文件顶部的两套结构说明）。
        """
        blocked = _auth_block(token)
        if blocked:
            return blocked
        try:
            data, error = _save_state_data()
            if data is None:
                return {"ok": False, "unsupported": True, "error": error}
            return _multitool_payload(data)
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "unsupported": True,
                    "error": f"{type(e).__name__}: {e}"}

    @endpoint("/freighter", method="GET")
    @_game_thread
    def freighter(self, token: str = "") -> dict:
        """货船基础信息（型号/种子/等级/库存摘要）+ 货船槽 + 舰队（frigates）。

        舰队数据 `FleetFrigates` 是动态数组；`FreighterFleet` 是 8 个固定槽。
        读不到的子块会写进 `unsupported`，不会用默认值填。
        """
        blocked = _auth_block(token)
        if blocked:
            return blocked
        try:
            data, error = _save_state_data()
            if data is None:
                return {"ok": False, "unsupported": True, "error": error}
            return _freighter_payload(data)
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "unsupported": True,
                    "error": f"{type(e).__name__}: {e}"}

    @endpoint("/pets", method="GET")
    @_game_thread
    def pets(self, token: str = "") -> dict:
        """同伴列表（名字/种子/描述符/是否召唤过）。

        注意：`cGcPlayerStateData` **没有**"当前出战同伴"索引，所以 `active`
        固定返回 None 并标 `active_supported=false`；不要把它当成"未出战"。
        """
        blocked = _auth_block(token)
        if blocked:
            return blocked
        try:
            data, error = _save_state_data()
            if data is None:
                return {"ok": False, "unsupported": True, "error": error}
            return _pets_payload(data)
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "unsupported": True,
                    "error": f"{type(e).__name__}: {e}"}

    @endpoint("/system", method="GET")
    @_game_thread
    def system(self, token: str = "") -> dict:
        blocked = _auth_block(token)
        if blocked:
            return blocked
        loc = _location()
        if loc is None:
            return {"ok": False, "error": "玩家状态不可用"}
        out = {"ok": True, "location": loc, "ua": "0x%016X" % _pack_ua(loc), "planets": []}
        try:
            ss = gameData.simulation.mpSolarSystem
            if ss:
                name = basic.cTkFixedString0x80()
                ss.contents.GetName(ctypes.byref(name))
                out["system_name"] = _fixed(name)
                for i, planet in enumerate(ss.contents.maPlanets):
                    try:
                        info = _planet_info(planet)
                        info["index"] = i
                        out["planets"].append(info)
                    except Exception:                      # noqa: BLE001
                        continue
        except Exception as e:                             # noqa: BLE001
            out["error"] = f"{type(e).__name__}: {e}"
        return out

    @endpoint("/planet", method="GET")
    @_game_thread
    def planet(self, token: str = "") -> dict:
        blocked = _auth_block(token)
        if blocked:
            return blocked
        loc = _location()
        if loc is None:
            return {"ok": False, "error": "玩家状态不可用"}
        try:
            ss = gameData.simulation.mpSolarSystem
            idx = max(0, int(loc["planet"]) - 1)
            info = _planet_info(ss.contents.maPlanets[idx])
            info["index"] = idx
            info["planet_index"] = int(loc["planet"])
            return {"ok": True, "planet": info}
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @endpoint("/planet/scan", method="GET")
    @_game_thread
    def planet_scan(self, token: str = "") -> dict:
        """只读：当前行星完整档案（PlanetInfo + 物质/生物/额外资源提示）。"""
        blocked = _auth_block(token)
        if blocked:
            return blocked
        loc = _location()
        if loc is None:
            return {"ok": False, "error": "玩家状态不可用"}
        try:
            ss = gameData.simulation.mpSolarSystem
            if ss is None:
                return {"ok": False, "error": "当前星系不可用"}
            idx = max(0, int(loc["planet"]) - 1)
            info = _planet_scan_info(ss.contents.maPlanets[idx])
            info["index"] = idx
            info["planet_index"] = int(loc["planet"])
            return {"ok": True, "planet": info}
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ------------------------------------------------------------ 写：传送

    def _write_location(self, loc: dict) -> None:
        ps = gameData.player_state
        ga = ps.mLocation.GalacticAddress
        ga.PlanetIndex = int(loc["planet"])
        ga.SolarSystemIndex = int(loc["system"])
        ga.VoxelX = int(loc["voxel_x"])
        ga.VoxelY = int(loc["voxel_y"])
        ga.VoxelZ = int(loc["voxel_z"])
        ps.mLocation.RealityIndex = int(loc["reality"])

    def _trigger_load(self) -> None:
        app = gameData.GcApplication
        if app is None:
            raise RuntimeError("GcApplication 不可用")
        state = basic.cTkFixedString[0x10]("APPLOCALLOAD")  # type: ignore[index]
        app.StateChange(ctypes.addressof(state), 0, False)

    @endpoint("/admin/reload", method="PUT")
    def admin_reload(self, token: str = "") -> dict:
        """热重载本 Mod：改完 `starforge_agent.py` 后调用，不必退出游戏。

        用后台线程延迟 0.4s 执行，避免把正在返回响应的这次请求一起卸载。
        """
        blocked = _auth_block(token)
        if blocked:
            return blocked
        try:
            from pymhf.core.mod_loader import mod_manager
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "error": f"pymhf mod_manager 不可用：{type(e).__name__}: {e}"}
        try:
            keys = [str(k) for k in mod_manager.mods if "starforge" in str(k).lower()]
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "error": f"读不到已加载 Mod 列表：{type(e).__name__}: {e}"}
        if not keys:
            return {"ok": False, "error": "没找到 starforge mod",
                    "mods": [str(k) for k in mod_manager.mods]}

        def _do() -> None:
            time.sleep(0.4)
            for key in keys:
                try:
                    mod_manager.reload(key)
                    log.info("已热重载 %s", key)
                except Exception as e:                     # noqa: BLE001
                    log.error("热重载 %s 失败：%s", key, e)

        threading.Thread(target=_do, daemon=True, name="sf-reload").start()
        return {"ok": True, "scheduled": keys,
                "note": "后台重载中；端点会在数秒内重新注册，期间请勿并发调用"}

    @endpoint("/teleport", method="PUT")
    @_game_thread
    def teleport(self, glyphs: str = "", galaxy: int = -1, token: str = "") -> dict:
        blocked = _auth_block(token)
        if blocked:
            return blocked
        blocked = _multiplayer_block()
        if blocked:
            return blocked
        try:
            dest = _decode_glyphs(glyphs)
            cur = _location()
            if cur is None:
                return {"ok": False, "error": "还没进入存档（player_state 为空）"}
            if galaxy is None or int(galaxy) < 0:
                dest["reality"] = cur["reality"]
            else:
                dest["reality"] = max(0, min(254, int(galaxy)))
            try:
                record = _persist_snapshot(cur, dest, glyphs)
            except Exception as e:                         # noqa: BLE001
                return {"ok": False, "code": "E_SNAPSHOT",
                        "error": f"无法持久化传送快照，已取消传送：{type(e).__name__}: {e}"}
            self._snapshot = dict(cur)
            log.info("teleport %s -> %s", cur, dest)
            self._write_location(dest)
            self._trigger_load()
            return {"ok": True, "before": cur, "after": dest,
                    "glyphs": glyphs.upper(), "snapshot": record,
                    "snapshot_file": str(_snapshot_path()),
                    "confirmed": False, "confirmation": "pending",
                    "note": "已写入并触发加载；应用会读回位置确认，未生效请用 restore 还原"}
        except Exception as e:                             # noqa: BLE001
            self._last_error = f"{type(e).__name__}: {e}"
            return {"ok": False, "error": self._last_error}

    @endpoint("/teleport/portal", method="PUT")
    @_game_thread
    def teleport_portal(self, glyphs: str = "", galaxy: int = -1,
                        stage: str = "", token: str = "") -> dict:
        """实验：尝试用 cGcPortalComponent 走游戏 portal warp。

        `stage` 决定调用深度（见 `_portal_warp`）：warp_only / prepare_warp / full。
        旧 ``teleport``（写位置 + APPLOCALLOAD）保持不变。
        """
        blocked = _auth_block(token)
        if blocked:
            return blocked
        blocked = _multiplayer_block()
        if blocked:
            return blocked
        try:
            dest = _decode_glyphs(glyphs)
            cur = _location()
            if cur is None:
                return {"ok": False, "error": "还没进入存档（player_state 为空）"}
            if galaxy is None or int(galaxy) < 0:
                dest["reality"] = cur["reality"]
            else:
                dest["reality"] = max(0, min(254, int(galaxy)))
            try:
                record = _persist_snapshot(cur, dest, glyphs)
            except Exception as e:                         # noqa: BLE001
                return {"ok": False, "code": "E_SNAPSHOT",
                        "error": f"无法持久化传送快照，已取消传送：{type(e).__name__}: {e}"}
            log.info("teleport.portal %s -> %s (stage=%s)", cur, dest, stage)
            result = _portal_warp(dest, stage=stage or _PORTAL_DEFAULT_STAGE)
            buffer = result.pop("_buffer", None)
            if buffer is not None:
                self._portal_buffer = buffer
            result.setdefault("before", cur)
            result.setdefault("after", dest)
            result.setdefault("snapshot", record)
            return result
        except Exception as e:                             # noqa: BLE001
            self._last_error = f"{type(e).__name__}: {e}"
            return {"ok": False, "code": "E_PORTAL", "error": self._last_error}

    @endpoint("/restore", method="PUT")
    @_game_thread
    def restore(self, token: str = "") -> dict:
        blocked = _auth_block(token)
        if blocked:
            return blocked
        blocked = _multiplayer_block()
        if blocked:
            return blocked
        snapshot = self._snapshot
        from_disk = False
        if not snapshot:
            snapshot = _latest_snapshot()
            from_disk = bool(snapshot)
        if not snapshot:
            return {"ok": False, "error": "没有可还原的快照（内存和 snapshots.json 都为空）"}
        try:
            self._write_location(snapshot)
            self._trigger_load()
            return {"ok": True, "restored": snapshot, "from_disk": from_disk,
                    "confirmed": False, "confirmation": "pending"}
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ------------------------------------------------------------ 扫描

    @endpoint("/scan/instant", method="PUT")
    @_game_thread
    def scan_instant(self, on: bool = True, token: str = "") -> dict:
        blocked = _auth_block(token)
        if blocked:
            return blocked
        blocked = _multiplayer_block()
        if blocked:
            return blocked
        self.instant_scan = bool(on)
        return {"ok": True, "instant_scan": self.instant_scan,
                "note": "开启后游戏内扫描条会立即完成；不写发现列表"}

    @endpoint("/scan", method="PUT")
    @_game_thread
    def scan(self, mode: str = "read", token: str = "") -> dict:
        """当前实现：read=读取行星完整信息；discover=暂不直接写发现。

        扫描“即时完成”由 Mod 在游戏内把扫描条拉满即可；这里返回当前行星数据，
        让界面能显示天气/资源/动植物。写发现（scan.discover）需要确认发现管理器偏移，
        暂不开放，避免把错误数据写进发现列表。
        """
        blocked = _auth_block(token)
        if blocked:
            return blocked
        if mode not in ("read", "discover"):
            return {"ok": False, "error": "mode 只能是 read/discover"}
        if mode == "discover":
            blocked = _multiplayer_block()
            if blocked:
                return blocked
        data = self.planet(token=token)
        if not data.get("ok"):
            return data
        return {"ok": True, "mode": mode, "planet": data["planet"],
                "note": "discover 暂未开放；read 已返回实时行星字段"}

