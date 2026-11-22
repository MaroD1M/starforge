"""银河索引：把"扫过的星系/行星"存进 SQLite，之后按条件秒查。

为什么需要它（PLAN-V4 · T10）：
  · 扇扫一次几百~几千个星系，每次都重算等于白干（`systemgen` 热态 0.039 s/系统，但架不住量大）；
  · 条件查询（茂盛 + 无哨兵 + 有拦截机 + ≥4 行星）需要索引，而不是每次重新生成；
  · 断点续扫、去重、增量刷新都要求有持久层。

设计取舍：
  · **只存结构化字段**（ua/坐标/符文/种族/经济/冲突/行星数/dissonant + 行星行），
    行星原始字典进 `planet_list` JSON 备查，不做全字段建模——游戏更新加字段时不用迁移；
  · `ua` 用十六进制字符串（如 `0x11200F19BDCE5`）做主键，便于人读与跟符文对照；
  · 写入用 `INSERT ... ON CONFLICT DO UPDATE`，重复扫同一星系就是刷新，不会膨胀。
"""
from __future__ import annotations

import json
import sqlite3
import time

from .core import log, paths

log = log.get("galaxy")

SCHEMA = """
CREATE TABLE IF NOT EXISTS systems (
    ua          TEXT PRIMARY KEY,
    coords      TEXT,
    glyphs      TEXT,
    galaxy      INTEGER,
    race        TEXT,
    economy     TEXT,
    conflict    TEXT,
    planets     INTEGER,
    moons       INTEGER,
    dissonant   INTEGER,
    interceptor TEXT,
    planet_list TEXT,
    scanned_at  INTEGER
);
CREATE TABLE IF NOT EXISTS planets (
    ua        TEXT NOT NULL,
    idx       INTEGER NOT NULL,
    biome     TEXT,
    sentinels TEXT,
    weather   TEXT,
    flora     TEXT,
    fauna     TEXT,
    dissonant INTEGER,
    PRIMARY KEY (ua, idx)
);
CREATE INDEX IF NOT EXISTS idx_planets_biome ON planets(biome);
CREATE INDEX IF NOT EXISTS idx_planets_sent  ON planets(sentinels);
CREATE INDEX IF NOT EXISTS idx_systems_diss  ON systems(dissonant);
CREATE INDEX IF NOT EXISTS idx_systems_pl    ON systems(planets);
"""


def db_path() -> str:
    return str(paths.cache_dir() / "galaxy.db")


class GalaxyStore:
    def __init__(self, path: str | None = None):
        self.path = path or db_path()
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------------------------------------------------------------- 写

    def upsert_system(self, row: dict) -> None:
        """row 来自 `system.system()`（已含 planets/race/dissonant/planet_list…）。"""
        pl = row.get("planet_list") or []
        self.conn.execute(
            """INSERT INTO systems (ua, coords, glyphs, galaxy, race, economy, conflict, planets,
                                    moons, dissonant, interceptor, planet_list, scanned_at)
               VALUES (:ua,:coords,:glyphs,:galaxy,:race,:economy,:conflict,:planets,
                       :moons,:dissonant,:interceptor,:planet_list,:scanned_at)
               ON CONFLICT(ua) DO UPDATE SET
                 coords=excluded.coords, glyphs=excluded.glyphs, galaxy=excluded.galaxy,
                 race=excluded.race, economy=excluded.economy, conflict=excluded.conflict,
                 planets=excluded.planets, moons=excluded.moons, dissonant=excluded.dissonant,
                 interceptor=excluded.interceptor, planet_list=excluded.planet_list,
                 scanned_at=excluded.scanned_at""",
            {"ua": str(row.get("ua")), "coords": row.get("coords"), "glyphs": row.get("glyphs"),
             "galaxy": int(row.get("galaxy") or 0), "race": row.get("race"),
             "economy": row.get("economy"), "conflict": row.get("conflict"),
             "planets": int(row.get("planets") or 0), "moons": int(row.get("moons") or 0),
             "dissonant": 1 if row.get("dissonant") else 0, "interceptor": row.get("interceptor"),
             "planet_list": json.dumps(pl, ensure_ascii=False), "scanned_at": int(time.time())})
        for i, p in enumerate(pl):
            self.conn.execute(
                """INSERT INTO planets (ua, idx, biome, sentinels, weather, flora, fauna, dissonant)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(ua, idx) DO UPDATE SET
                     biome=excluded.biome, sentinels=excluded.sentinels, weather=excluded.weather,
                     flora=excluded.flora, fauna=excluded.fauna, dissonant=excluded.dissonant""",
                (str(row.get("ua")), int(p.get("index", i)), p.get("biome_name") or p.get("biome"),
                 p.get("sentinels"), p.get("weather"), p.get("flora"), p.get("fauna"),
                 1 if row.get("dissonant") else 0))
        self.conn.commit()

    # ---------------------------------------------------------------- 查

    def stats(self) -> dict:
        s = self.conn.execute("SELECT COUNT(*) n, MAX(scanned_at) t FROM systems").fetchone()
        p = self.conn.execute("SELECT COUNT(*) n FROM planets").fetchone()
        return {"systems": s["n"], "planets": p["n"], "updated": s["t"], "db": self.path}

    def query(self, filters: dict | None = None, limit: int = 50) -> list[dict]:
        """条件查询 → 星系 + 命中的行星行。

        filters 支持的键：biome / sentinels / dissonant / min_planets / race / has_interceptor。
        """
        f = dict(filters or {})
        where, args = [], []
        if f.get("race"):
            where.append("s.race = ?"); args.append(str(f["race"]))
        if f.get("dissonant") is not None:
            where.append("s.dissonant = ?"); args.append(1 if f["dissonant"] else 0)
        if f.get("has_interceptor"):
            where.append("s.interceptor IS NOT NULL")
        if f.get("min_planets"):
            where.append("s.planets >= ?"); args.append(int(f["min_planets"]))
        if f.get("min_moons"):
            where.append("s.moons >= ?"); args.append(int(f["min_moons"]))

        pwhere = []
        if f.get("biome"):
            pwhere.append("p.biome = ?"); args.append(str(f["biome"]))
        if f.get("sentinels"):
            pwhere.append("p.sentinels = ?"); args.append(str(f["sentinels"]))

        sql = ("SELECT s.*, p.idx AS p_idx, p.biome AS p_biome, p.sentinels AS p_sentinels, "
               "p.weather AS p_weather, p.flora AS p_flora, p.fauna AS p_fauna "
               "FROM systems s JOIN planets p ON p.ua = s.ua ")
        if where:
            sql += "WHERE " + " AND ".join(where) + " "
        if pwhere:
            sql += ("AND " if where else "WHERE ") + " AND ".join(pwhere) + " "
        sql += "ORDER BY s.scanned_at DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))

        out, seen = [], {}
        for r in self.conn.execute(sql, args):
            row = seen.get(r["ua"])
            if row is None:
                row = {k: r[k] for k in ("ua", "coords", "glyphs", "galaxy", "race", "economy",
                                         "conflict", "planets", "moons", "dissonant", "interceptor")}
                row["dissonant"] = bool(row["dissonant"])
                row["matched_planets"] = []
                seen[r["ua"]] = row
                out.append(row)
            row["matched_planets"].append({
                "index": r["p_idx"], "biome": r["p_biome"], "sentinels": r["p_sentinels"],
                "weather": r["p_weather"], "flora": r["p_flora"], "fauna": r["p_fauna"]})
        return out

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:                                  # noqa: BLE001
            pass


# ---------------------------------------------------------------- 扫描（可注入 provider 便于测试）


def scan(center_ua: int | None = None, radius: int = 0, systems_per_region: int = 60,
         filters: dict | None = None, limit: int = 40, job=None, save_path: str | None = None,
         provider=None, store: GalaxyStore | None = None) -> dict:
    """扫一片区域，把**每个**扫到的星系都写进索引，再按条件挑出命中。

    与 `system.scan()` 的区别：那个只返回命中（不落库）；这个落库，所以下次查询不用重算。
    `provider(ua) -> dict` 可注入（测试用假数据，不跑 unicorn）。
    """
    from . import system as system_mod

    provider = provider or (lambda ua: system_mod.system(ua, planets=True, save_path=save_path))
    own = store is None
    store = store or GalaxyStore()
    hits: list[dict] = []
    scanned = 0
    t0 = time.time()
    try:
        sectors = _sector_list(center_ua, radius, systems_per_region, save_path=save_path)
        for ua in sectors:
            if job is not None and job.should_stop():
                break
            try:
                info = provider(ua)
            except Exception as e:                       # noqa: BLE001
                log.debug("星系 %s 生成失败：%s", ua, e)
                continue
            if not info or not info.get("region_valid", True):
                continue
            info.setdefault("ua", "0x%X" % ua if isinstance(ua, int) else str(ua))
            store.upsert_system(info)
            scanned += 1
            if _system_matches(info, filters or {}):
                hits.append(info)
            if job is not None:
                job.update(tested=scanned, found=len(hits), seconds=round(time.time() - t0, 2),
                           scanned=scanned)
            if len(hits) >= int(limit):
                break
    finally:
        if own:
            stats = store.stats()
            store.close()
        else:
            stats = store.stats()
    log.info("银河索引：扫 %d 个星系 → 命中 %d（%.1fs）；库内 %s", scanned, len(hits),
             time.time() - t0, stats)
    return {"scanned": scanned, "hits": hits, "store": stats,
            "seconds": round(time.time() - t0, 2)}


def _sector_list(center_ua, radius, systems_per_region=60, save_path=None) -> list[int]:
    """把"中心 + 半径 + 每区系统数"展开成 UA 列表。"""
    from . import system as system_mod
    locate, systemgen = system_mod._mods()
    if center_ua is None:
        center_ua = system_mod.current_ua(save_path)
    center = locate.describe(int(center_ua))
    regions = list(systemgen.regions_around(int(center_ua), max(0, min(int(radius), 3))))
    inds = list(systemgen.SYSTEM_INDICES)[: max(1, min(int(systems_per_region or 60), 767))]
    out = []
    for (x, y, z) in regions:
        for s in inds:
            out.append(locate.pack_ua(x, y, z, s, center["galaxy"]))
    return out


def _system_matches(info: dict, f: dict) -> bool:
    if f.get("dissonant") and not info.get("dissonant"):
        return False
    if f.get("min_planets") and int(info.get("planets") or 0) < int(f["min_planets"]):
        return False
    if f.get("min_moons") and int(info.get("moons") or 0) < int(f["min_moons"]):
        return False
    if f.get("has_interceptor") and not info.get("interceptor"):
        return False
    if f.get("race") and str(info.get("race") or "").lower() != str(f["race"]).lower():
        return False
    pl = info.get("planet_list") or []
    if f.get("biome") and not any((p.get("biome_name") or "").lower() == str(f["biome"]).lower() for p in pl):
        return False
    if f.get("sentinels") and not any((p.get("sentinels") or "").lower() == str(f["sentinels"]).lower() for p in pl):
        return False
    return True
