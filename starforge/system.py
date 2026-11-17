"""星系/星球：地址解析、系统生成、按条件扇扫。

实测（本机 4 核）：systemgen 热身 0.039 s/系统 → 单进程约 25 系统/秒。
依赖游戏 exe（unicorn 跑 NMS.exe 的星系生成器）；缺游戏时整块功能禁用并说明原因，
不影响搜索/预览/存档。
"""
from __future__ import annotations

import os
import time

from .core import log, paths, settings
from .core.errors import GameFilesMissing

log = log.get("system")

BIOMES = ("Lush", "Frozen", "Toxic", "Scorched", "Radioactive", "Barren", "Dead",
          "Exotic", "Mega Exotic", "Weird", "Swamp", "Volcanic", "Desert")
SENTINELS = ("none", "low", "high", "aggressive", "corrupted")


def _prepare_env() -> None:
    """systemgen 通过 NMS_DIR / NMS_TOOL_CACHE 定位游戏与缓存。"""
    s = settings.current()
    if s.game_dir:
        os.environ["NMS_DIR"] = s.game_dir
    os.environ.setdefault("NMS_TOOL_CACHE", str(paths.cache_dir() / "gamecache"))
    paths.ensure_shipwright_importable()


def _has_exe(folder: str | None) -> bool:
    if not folder:
        return False
    for name in ("Binaries/NMS.exe", "binaries/nms.exe", "Binaries/nms.exe"):
        if os.path.exists(os.path.join(folder, *name.split("/"))):
            return True
    return False


def available() -> bool:
    return _has_exe(settings.current().game_dir)


def _require() -> None:
    if not available():
        raise GameFilesMissing("没有检测到游戏目录：星系/星球搜索需要 NMS.exe 与 PCBANKS",
                               hint="在设置里指定游戏安装目录（含 Binaries/NMS.exe）")


def _mods():
    _prepare_env()
    from nms_procgen import locate, systemgen
    return locate, systemgen


# ---------------------------------------------------------------- 地址


def describe(text: str | int) -> dict:
    locate, _ = _mods()
    if isinstance(text, int):
        ua = text
    else:
        ua = locate.parse_address(str(text))
    return locate.describe(ua)


def current_ua(save_path: str | None = None) -> int:
    """从存档读当前所在系统地址。"""
    from .save import library
    paths.ensure_shipwright_importable()
    from nms_save import save as nms_save
    locate, _ = _mods()
    p = str(library.resolve(save_path))
    return locate.save_location(nms_save.open_save(p).readable)


# ---------------------------------------------------------------- 单个系统


def system(ua: int | None = None, planets: bool = True, save_path: str | None = None) -> dict:
    _require()
    locate, systemgen = _mods()
    if ua is None:
        ua = current_ua(save_path)
    t0 = time.time()
    with systemgen.borrow() as sg:
        info = sg.system(int(ua), planets=planets)
    d = locate.describe(int(ua))
    ships = [{**s, "seed": ("0x%016X" % s["seed"]) if isinstance(s.get("seed"), int) else s.get("seed")}
             for s in info.get("ships", [])]
    return {**d,
            "planets": info.get("planets", 0), "moons": info.get("moons", 0),
            "race": info.get("race"), "inhabited": info.get("inhabited"),
            "dissonant": bool(info.get("dissonant")),
            "interceptor": ("0x%016X" % info["interceptor"]) if info.get("interceptor") else None,
            "planet_list": info.get("planet_list") or [],
            "ships": ships, "region_valid": info.get("region_valid"),
            "elapsed_ms": int((time.time() - t0) * 1000)}


# ---------------------------------------------------------------- 扇扫


def _matches(planet: dict, filters: dict) -> bool:
    biome = filters.get("biome")
    if biome and (planet.get("biome_name") or "").lower() != str(biome).lower():
        return False
    sent = filters.get("sentinels")
    if sent and (planet.get("sentinels") or "").lower() != str(sent).lower():
        return False
    return True


def scan(center_ua: int | None = None, radius: int = 0, systems_per_region: int = 200,
         filters: dict | None = None, limit: int = 40, job=None,
         save_path: str | None = None) -> list[dict]:
    """在中心附近的 region 里批量生成系统，按条件挑星球。

    返回每条 = 星系信息 + 行星信息（含 glyphs，方便直接用符文浮窗）。
    """
    _require()
    locate, systemgen = _mods()
    filters = dict(filters or {})
    if center_ua is None:
        center_ua = current_ua(save_path)
    center = locate.describe(int(center_ua))
    regions = list(systemgen.regions_around(int(center_ua), max(0, min(int(radius), 3))))
    inds = list(systemgen.SYSTEM_INDICES)[: max(1, min(int(systems_per_region), 767))]

    hits: list[dict] = []
    tested = 0
    t0 = time.time()
    with systemgen.borrow() as sg:
        for (x, y, z) in regions:
            for s in inds:
                if job is not None and job.should_stop():
                    break
                ua = locate.pack_ua(x, y, z, s, center["galaxy"])
                try:
                    info = sg.system(ua, planets=True)
                except RuntimeError:
                    continue
                tested += 1
                if not info.get("region_valid"):
                    continue
                if filters.get("dissonant") and not info.get("dissonant"):
                    continue
                if info.get("planets", 0) < int(filters.get("min_planets") or 0):
                    continue
                rows = [p for p in (info.get("planet_list") or []) if _matches(p, filters)]
                if not rows:
                    continue
                d = locate.describe(ua)
                for p in rows:
                    hits.append({**d, **p, "dissonant": bool(info.get("dissonant")),
                                 "interceptor": ("0x%016X" % info["interceptor"]) if info.get("interceptor") else None})
                    if len(hits) >= limit:
                        break
                if job is not None:
                    job.update(tested=tested, seconds=round(time.time() - t0, 2), found=len(hits),
                               scanned=tested)
                if len(hits) >= limit:
                    break
            if len(hits) >= limit or (job is not None and job.should_stop()):
                break
    log.info("扇扫 %d 系统（%.1fs）→ %d 条；filter=%s", tested, time.time() - t0, len(hits), filters)
    return hits


def capabilities() -> dict:
    return {"available": available(), "biomes": list(BIOMES), "sentinels": list(SENTINELS),
            "note": "需要游戏 NMS.exe（unicorn 执行星系生成器）；缺游戏时本模块禁用，其余功能不受影响"}
