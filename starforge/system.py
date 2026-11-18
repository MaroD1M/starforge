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
# 上游 `levels[0..3]` 的含义：各哨兵预设下的等级（索引 2 是游戏判定 dissonant 用的"normal"预设）
SENTINEL_LV = ("none", "low", "aggressive", "corrupted")
# 行星字段的"离线可得性"——别让界面假装有天气数据（T9 spike 的负结果）
PLANET_FIELDS = {
    "offline": ["biome", "sentinels(4 预设)", "seed", "levels"],
    "need_game": ["weather", "flora", "fauna", "resources"],
    "note": "天气/植被/生物清单由游戏运行时的行星生成器给出；上游 systemgen 用的是占位表，"
            "离线拿不到（实测：`_planets()` 只读 +0x34CC 起的 4 个哨兵等级）。由 M4 的 planet.current 补。",
}


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
    """有游戏目录且里面有 NMS.exe。

    除了设置里的 `game_dir`，也认 `NMS_DIR` 环境变量——CLI/CI 与"设置页还没填但环境里给了"
    的场景都会走到这里，少一个假失败（handbook 05 卷 K21 的同类问题）。
    """
    if _has_exe(settings.current().game_dir):
        return True
    return _has_exe(os.environ.get("NMS_DIR"))


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
    planet_list = []
    for p in info.get("planet_list") or []:
        lv = list(p.get("levels") or [])
        planet_list.append({**p,
                            # levels 是"各哨兵预设下的等级"，索引 2 = 游戏判定 dissonant 用的那个
                            "sentinel_presets": [SENTINEL_LV[i] if 0 <= i < len(SENTINEL_LV) else "?"
                                                 for i in (lv + [0, 0, 0, 0])[:4]],
                            "sentinel_index": lv[2] if len(lv) > 2 else 0,
                            "fields_offline": ["biome", "sentinels", "seed"],
                            "fields_need_game": ["weather", "flora", "fauna", "resources"]})
    return {**d,
            "planets": info.get("planets", 0), "moons": info.get("moons", 0),
            "race": info.get("race"), "inhabited": info.get("inhabited"),
            "dissonant": bool(info.get("dissonant")),
            "interceptor": ("0x%016X" % info["interceptor"]) if info.get("interceptor") else None,
            "planet_list": planet_list,
            "ships": ships, "region_valid": info.get("region_valid"),
            "elapsed_ms": int((time.time() - t0) * 1000)}


# ---------------------------------------------------------------- 种子反查星系


def locate_seed(seed: str | int, save_path: str | None = None, max_steps: int = 3000,
                limit: int = 6) -> dict:
    """船种子 → 它可能出自哪个星系（含符文），并用生成器逐条证实。

    反查是**精确但欠定**的：种子里没有写"这个星系是往回数第几步"，所以每试一步都是
    一次可能撞上"看着像真的"地址。上游实测 400 个随机种子里有 45 个能反解出候选。
    因此这里分两步：`locate` 出候选 → `systemgen.confirm` 真的把系统生成出来，
    只有生成结果里确实有这艘船才算命中（返回 where/what：坠毁点/空间站/船型）。

    已知星系（存档里访问/发现过的）会优先排前——命中已知星系的候选几乎必然正确。
    """
    _require()
    locate, systemgen = _mods()
    if isinstance(seed, str):
        seed = int(seed, 16) if seed.lower().startswith("0x") else int(seed)
    seed = int(seed)

    known: set[int] = set()
    known_err = None
    try:
        from .save import library
        paths.ensure_shipwright_importable()
        from nms_save import save as nms_save
        p = str(library.resolve(save_path))
        known = locate.save_known_systems(nms_save.open_save(p).readable)
    except Exception as e:                                  # noqa: BLE001
        known_err = f"{type(e).__name__}: {e}"

    t0 = time.time()
    rows = locate.locate(seed, max_steps=int(max(1, min(int(max_steps), 20000))),
                         known_systems=known)
    confirmed = []
    checked_err = None
    if rows:
        try:
            confirmed = systemgen.confirm(seed, rows[: max(1, int(limit))])
        except Exception as e:                              # noqa: BLE001
            checked_err = f"{type(e).__name__}: {e}"
    hits = []
    for r in confirmed:
        ua = int(r["ua"], 16) if isinstance(r.get("ua"), str) else int(r["ua"])
        d = locate.describe(ua)
        hits.append({**d, "steps": r.get("steps"), "visited": bool(r.get("visited")),
                     "where": r.get("where"), "what": r.get("what"),
                     "glyphs": d["glyphs"], "coords": d["coords"],
                     "portal_hint": f"传送门输入 {d['glyphs']}"})
    out = {"seed": "0x%016X" % seed, "candidates": len(rows), "hits": hits,
           "known_systems": len(known), "elapsed_ms": int((time.time() - t0) * 1000)}
    if known_err:
        out["known_systems_error"] = known_err
    if checked_err:
        out["confirm_error"] = checked_err
    if not hits:
        out["reason"] = ("这个种子反解不出可信的星系统（种子反查本身欠定：只有部分种子能反解），"
                         "或候选系统生成失败。可以把它当作'这艘船来自未知星系'继续用。")
    log.info("种子反查 %s：候选 %d → 命中 %d（%.2fs）", out["seed"], len(rows), len(hits),
             out["elapsed_ms"] / 1000)
    return out


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
            "planet_fields": PLANET_FIELDS,
            "note": "需要游戏 NMS.exe（unicorn 执行星系生成器）；缺游戏时本模块禁用，其余功能不受影响"}
