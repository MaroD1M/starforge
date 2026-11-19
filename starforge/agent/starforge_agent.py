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
from pymhf.core.http_api import endpoint

log = logging.getLogger("starforge.agent")

# launch() 每次启动生成一次性 token，通过子进程环境注入；pymhf endpoint 没有稳定
# 的 request header 读取接口，所以客户端用 ?token=... 传。为空表示用户手动启动
# （未经过 starforge），只报告 auth=disabled，不假装有认证。
_AGENT_TOKEN = os.environ.get("STARFORGE_AGENT_TOKEN", "").strip()
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


# cGcPortalComponent::WarpPlayer 的原始组件构造路径尚未在 Windows 实机上校准。
# 未校准时 teleport.portal 只报告 unsupported，绝不假装成功。
_PORTAL_WARP_CALIBRATED = False


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


def _portal_warp(dest: dict) -> dict:
    """尝试通过 cGcPortalComponent 触发 portal warp。

    只有 API 齐全且 ``_PORTAL_WARP_CALIBRATED`` 为真时才真正调用游戏函数；
    否则返回明确的 unsupported，避免在未校准 build 上写错组件/地址。
    """
    api = _portal_api()
    if not api.get("available"):
        return _portal_unsupported(api.get("error") or "cGcPortalComponent 不可用")
    if not _PORTAL_WARP_CALIBRATED:
        return _portal_unsupported(
            "cGcPortalComponent API 可用，但 raw 组件偏移/WarpPlayer 调用尚未实机校准")
    try:
        cls = nms.cGcPortalComponent
        size = max(0x1000, ctypes.sizeof(cls) + 0x100)
        buffer = ctypes.create_string_buffer(size)
        component = cls.from_buffer(buffer)
        target_ua = _pack_ua(dest)
        component.OnAttached()
        component.mPortalData.mTargetUA = target_ua
        component.mPortalData.mbActive = True
        component.Prepare()
        component.WarpPlayer()
        # buffer 必须活到 warp 完成；由调用方持有（见 teleport_portal）。
        return {"ok": True, "experimental": True, "confirmed": False,
                "target_ua": f"0x{target_ua:016X}",
                "_buffer": buffer,
                "note": "已调用 cGcPortalComponent.WarpPlayer；本版未实机校准，"
                        "落点是否生效需在游戏内确认，失败请用 restore 还原"}
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

    @endpoint("/hello")
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
                    "teleport": write_ok, "teleport.portal": write_ok and portal["available"],
                    "portal.calibrated": bool(portal.get("calibrated")),
                    "scan": "read", "scan.discover": False,
                    "scan.instant": write_ok, "restore": write_ok,
                }}

    @endpoint("/player")
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

    @endpoint("/ships")
    @_game_thread
    def ships(self, token: str = "") -> dict:
        blocked = _auth_block(token)
        if blocked:
            return blocked
        try:
            ps = gameData.player_state
            if ps is None:
                return {"ok": False, "error": "还没进入存档（player_state 为空）"}
            ships = ps.mShipResources
            rows = []
            for i, res in enumerate(ships):
                try:
                    filename = _s(res.Filename)
                    seed = int(res.Seed)
                except Exception:                          # noqa: BLE001
                    continue
                if not seed and not filename:
                    continue
                rows.append({"slot": i, "filename": filename,
                             "seed": "0x%016X" % (seed & 0xFFFFFFFFFFFFFFFF)})
            primary = int(getattr(ps, "miPrimaryShip", 0) or 0)
            return {"ok": True, "primary": primary, "ships": rows}
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @endpoint("/system")
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

    @endpoint("/planet")
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

    @endpoint("/planet/scan")
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
                        token: str = "") -> dict:
        """实验：尝试用 cGcPortalComponent 走游戏 portal warp。

        API/偏移未实机校准前一律返回 ``ok:false`` + ``本版未实现/需实机校准``；
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
            log.info("teleport.portal %s -> %s", cur, dest)
            result = _portal_warp(dest)
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
