# /// script
# dependencies = ["NMSpy==185034.0", "pymhf[http_api]>=0.2.5"]
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
  GET  /StarforgeAgent/ships
  PUT  /StarforgeAgent/teleport?glyphs=...&galaxy=...
  PUT  /StarforgeAgent/scan?mode=read
  PUT  /StarforgeAgent/restore

依赖 NMSpy（版本跟随游戏 build）与 pymhf[http_api]。
所有写操作先记录快照；传送失败可调用 /restore 还原。
"""
from __future__ import annotations

import ctypes
import logging
from typing import Any

import nmspy.data.basic_types as basic
import nmspy.data.types as nms
from nmspy.common import gameData
from nmspy.engine import GetNodeAbsoluteTransMatrix
from pymhf import Mod
from pymhf.core.http_api import endpoint

log = logging.getLogger("starforge.agent")


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


class StarforgeAgent(Mod):
    __author__ = "starforge"
    __description__ = "starforge 游戏内通道：状态读取 / 传送 / 扫描"
    __version__ = "0.1.0"

    def __init__(self) -> None:
        super().__init__()
        self._snapshot: dict | None = None
        self._last_error = ""
        self.instant_scan = False

    @nms.cGcBinoculars.UpdateScanBarProgress.before
    def _force_scan_progress(self, this, lfScanProgress):
        if self.instant_scan and lfScanProgress < 1:
            return (this, 1)
        return None

    # ------------------------------------------------------------ 基础

    @endpoint("/hello")
    def hello(self) -> dict:
        try:
            import nmspy

            version = getattr(nmspy, "__version__", "unknown")
        except Exception:                                  # noqa: BLE001
            version = "unknown"
        app = gameData.GcApplication
        return {"ok": True, "agent": self.__version__, "nmspy": version,
                "game_attached": app is not None,
                "multiplayer": bool(getattr(app, "mbMultiplayerActive", False)) if app else False,
                "capabilities": {
                    "player": True, "system": True, "planet": True, "ships": True,
                    "teleport": True, "scan": "read", "scan.discover": False,
                    "scan.instant": True, "restore": True,
                }}

    @endpoint("/player")
    def player(self) -> dict:
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
    def ships(self) -> dict:
        try:
            ps = gameData.player_state
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
    def system(self) -> dict:
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
    def planet(self) -> dict:
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
    def teleport(self, glyphs: str = "", galaxy: int = -1) -> dict:
        try:
            dest = _decode_glyphs(glyphs)
            cur = _location()
            if cur is None:
                return {"ok": False, "error": "玩家状态不可用"}
            if galaxy is None or int(galaxy) < 0:
                dest["reality"] = cur["reality"]
            else:
                dest["reality"] = max(0, min(254, int(galaxy)))
            self._snapshot = dict(cur)
            log.info("teleport %s -> %s", cur, dest)
            self._write_location(dest)
            self._trigger_load()
            return {"ok": True, "before": cur, "after": dest,
                    "glyphs": glyphs.upper(), "note": "已写入并触发加载；若未生效请用 restore 还原"}
        except Exception as e:                             # noqa: BLE001
            self._last_error = f"{type(e).__name__}: {e}"
            return {"ok": False, "error": self._last_error}

    @endpoint("/restore", method="PUT")
    def restore(self) -> dict:
        if not self._snapshot:
            return {"ok": False, "error": "没有可还原的快照"}
        try:
            self._write_location(self._snapshot)
            self._trigger_load()
            return {"ok": True, "restored": self._snapshot}
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ------------------------------------------------------------ 扫描

    @endpoint("/scan/instant", method="PUT")
    def scan_instant(self, on: bool = True) -> dict:
        self.instant_scan = bool(on)
        return {"ok": True, "instant_scan": self.instant_scan,
                "note": "开启后游戏内扫描条会立即完成；不写发现列表"}

    @endpoint("/scan", method="PUT")
    def scan(self, mode: str = "read") -> dict:
        """当前实现：read=读取行星完整信息；discover=暂不直接写发现。

        扫描“即时完成”由 Mod 在游戏内把扫描条拉满即可；这里返回当前行星数据，
        让界面能显示天气/资源/动植物。写发现（scan.discover）需要确认发现管理器偏移，
        暂不开放，避免把错误数据写进发现列表。
        """
        if mode not in ("read", "discover"):
            return {"ok": False, "error": "mode 只能是 read/discover"}
        data = self.planet()
        if not data.get("ok"):
            return data
        return {"ok": True, "mode": mode, "planet": data["planet"],
                "note": "discover 暂未开放；read 已返回实时行星字段"}
