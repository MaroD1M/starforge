"""玩家发现记录的本地 SQLite 索引（``~/.starforge/cache/discoveries.db``）。

只读存档、只写缓存；不启动游戏、不 attach 进程、不改存档。实现按
``docs/research/OSS-SAVE-INDEX.md`` 的 schema 做了**简化**：只落行星发现行，
够用且容易重建。完整的多实体索引（动物/飞船/基地/传送点）留给后续版本。

增量语义（与文档 §3.5 一致）：

1. 先看 ``saves.size + mtime_ns + extractor_ver``：全部相同直接复用，**不读文件**；
2. 再看 ``sha256(原始存档)``：内容没变、只是 mtime 被重写时也复用；
3. 以上任一变化或 ``EXTRACTOR_VER`` 升级 → 重新解析，并在**单事务**里替换该存档
   的所有行星行；失败回滚，旧快照保留。

并发：WAL + ``busy_timeout=5000``，Python 侧用模块级 ``RLock`` 包住“检查 + 重建”。
"""
from __future__ import annotations

import hashlib
import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from . import address, discoveries
from .core import log, paths

log = log.get("discoveries")

# 提取器版本：字段语义/群系映射/去重策略变化时 +1，旧缓存会被强制重建。
EXTRACTOR_VER = 1
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS saves (
    save_id       TEXT PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,
    size          INTEGER NOT NULL,
    mtime_ns      INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    extractor_ver INTEGER NOT NULL,
    indexed_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS planets (
    save_id      TEXT NOT NULL,
    system_ua    TEXT NOT NULL,
    planet_index INTEGER NOT NULL,
    planet_ua    TEXT,
    biome        TEXT,
    infested     INTEGER,
    named        INTEGER NOT NULL DEFAULT 0,
    name         TEXT,
    discovered_at INTEGER,
    system_name  TEXT,
    glyphs       TEXT,
    coords       TEXT,
    PRIMARY KEY (save_id, system_ua, planet_index)
);

CREATE INDEX IF NOT EXISTS idx_discoveries_biome
    ON planets(save_id, biome, infested);
CREATE INDEX IF NOT EXISTS idx_discoveries_named
    ON planets(save_id, named);

CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
"""

_LOCK = threading.RLock()
_MAX_LIMIT = discoveries.MAX_LIMIT


# ---------------------------------------------------------------- 连接/工具


def db_path() -> str:
    """默认库路径：``<STARFORGE_HOME>/cache/discoveries.db``。"""
    return str(paths.cache_dir() / "discoveries.db")


def _connect(db_file: str | None = None) -> sqlite3.Connection:
    target = str(db_file or db_path())
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('schema_version', ?)",
                 (str(SCHEMA_VERSION),))
    conn.commit()
    return conn


def _save_id(path: Path) -> str:
    """存档 ID 稳定于真实路径；不包含用户名以外的任何内容。"""
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:16]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hex(value: Any) -> str | None:
    """UA → 规范 ``0x%X``；非法/0 返回 None。"""
    number = discoveries.normalize_ua(value)
    return f"0x{number:X}" if number is not None else None


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text, 16) if text.lower().startswith("0x") else int(text)
        except ValueError:
            return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _fail(reason: str, **extra: Any) -> dict:
    return {"ok": False, "count": 0, "rebuilt": False, "cached": False,
            "skipped": 0, "error": reason, **extra}


# ---------------------------------------------------------------- 行星行


def _rows_from_planets(planets: Any) -> tuple[list[tuple], int]:
    """``discoveries`` 行星字典 → DB 行；坏记录跳过并计数。"""
    rows: list[tuple] = []
    skipped = 0
    seen: set[tuple[str, int]] = set()
    for item in planets or []:
        if not isinstance(item, dict):
            skipped += 1
            continue
        system_ua = discoveries.normalize_ua(item.get("system_ua"))
        planet_index = _int_or_none(item.get("planet_index"))
        if system_ua is None or planet_index is None or not 0 <= planet_index <= 0xF:
            skipped += 1
            continue
        system_hex = f"0x{system_ua:X}"
        planet_ua = discoveries.normalize_ua(item.get("planet_ua") or item.get("ua"))
        if planet_ua is None and planet_index > 0:
            # 系统地址 + 行星序号在数学上唯一确定行星地址，不是猜测。
            planet_ua = system_ua | (planet_index << discoveries.PLANET_SHIFT)
        key = (system_hex, planet_index)
        if key in seen:
            # discoveries 已经合并过重复记录；这里再出现只可能是调用方手工拼接的数据。
            skipped += 1
            continue
        seen.add(key)
        infested = item.get("infested")
        infested_value = None if infested is None else int(bool(infested))
        discovered_at = _int_or_none(item.get("discovered_at"))
        if discovered_at is not None and discovered_at <= 0:
            discovered_at = None
        rows.append((
            system_hex, planet_index, _hex(planet_ua),
            _text(item.get("biome")), infested_value,
            int(bool(item.get("named"))), _text(item.get("name")),
            discovered_at, _text(item.get("system_name")),
            _text(item.get("glyphs")), _text(item.get("coords")),
        ))
    return rows, skipped


def _cached_count(conn: sqlite3.Connection, save_id: str) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM planets WHERE save_id=?",
                       (save_id,)).fetchone()
    return int(row["n"] if row else 0)


# ---------------------------------------------------------------- 建索引


def index_save(path: str | None = None, *, db_file: str | None = None) -> dict:
    """把一份存档的发现记录落进索引。

    返回 ``{"ok", "count", "rebuilt", "cached", "skipped"}``：
      · ``cached=True`` 表示 size+mtime 或 sha256 命中，复用了已有快照；
      · ``rebuilt=True`` 表示这次真正重写了该存档的行；
      · ``skipped`` 是无法落库的坏记录数（缺系统地址/行星序号）。
    """
    from .save import library

    try:
        save_path = library.resolve(path)
    except Exception as e:                                # noqa: BLE001 - 上游异常类型多
        return _fail(f"定位存档失败：{type(e).__name__}: {e}")
    try:
        stat = save_path.stat()
    except OSError as e:
        return _fail(f"读取存档状态失败：{type(e).__name__}: {e}")

    save_id = _save_id(save_path)
    with _LOCK:
        conn = _connect(db_file)
        try:
            row = conn.execute("SELECT * FROM saves WHERE save_id=?", (save_id,)).fetchone()
            same_version = bool(row and row["extractor_ver"] == EXTRACTOR_VER)

            # 快路径：完全不读文件。
            if (same_version and row["size"] == stat.st_size
                    and row["mtime_ns"] == stat.st_mtime_ns):
                return {"ok": True, "count": _cached_count(conn, save_id),
                        "rebuilt": False, "cached": True, "skipped": 0,
                        "save_id": save_id, "path": str(save_path),
                        "reason": "size+mtime"}

            try:
                digest = _sha256(save_path)
            except OSError as e:
                return _fail(f"计算存档哈希失败：{type(e).__name__}: {e}")

            # 慢路径：内容没变，只是 mtime/size 被动过 → 复用旧快照。
            if same_version and row["sha256"] == digest:
                with conn:
                    conn.execute(
                        "UPDATE saves SET size=?, mtime_ns=?, indexed_at=? WHERE save_id=?",
                        (stat.st_size, stat.st_mtime_ns, int(time.time()), save_id))
                return {"ok": True, "count": _cached_count(conn, save_id),
                        "rebuilt": False, "cached": True, "skipped": 0,
                        "save_id": save_id, "path": str(save_path),
                        "reason": "sha256"}

            # 慢路径：真正解析。只调用数据层，不在本模块碰存档字节。
            parsed = discoveries.discovered_planets(str(save_path))
            if not parsed.get("ok"):
                reason = (parsed.get("warnings") or ["读取发现记录失败"])[0]
                return _fail(str(reason), save_id=save_id, path=str(save_path))
            rows, skipped = _rows_from_planets(parsed.get("planets"))
            now = int(time.time())
            with conn:                                  # 单存档单事务替换
                conn.execute("DELETE FROM planets WHERE save_id=?", (save_id,))
                conn.execute(
                    """INSERT INTO saves(save_id, path, size, mtime_ns, sha256,
                                         extractor_ver, indexed_at)
                       VALUES(?,?,?,?,?,?,?)
                       ON CONFLICT(save_id) DO UPDATE SET
                         path=excluded.path, size=excluded.size,
                         mtime_ns=excluded.mtime_ns, sha256=excluded.sha256,
                         extractor_ver=excluded.extractor_ver,
                         indexed_at=excluded.indexed_at""",
                    (save_id, str(save_path), stat.st_size, stat.st_mtime_ns,
                     digest, int(EXTRACTOR_VER), now))
                conn.executemany(
                    """INSERT OR REPLACE INTO planets(
                         save_id, system_ua, planet_index, planet_ua, biome,
                         infested, named, name, discovered_at, system_name,
                         glyphs, coords)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [(save_id, *r) for r in rows])
                conn.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('extractor_ver', ?)",
                             (str(EXTRACTOR_VER),))
                conn.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('updated_at', ?)",
                             (str(now),))
            if skipped:
                log.info("发现索引：%s 跳过了 %d 条坏记录", save_path.name, skipped)
            return {"ok": True, "count": len(rows), "rebuilt": True,
                    "cached": False, "skipped": skipped,
                    "save_id": save_id, "path": str(save_path)}
        finally:
            conn.close()


# ---------------------------------------------------------------- 查询


def _db_rows(conn: sqlite3.Connection, save_id: str | None) -> list[dict]:
    sql = ("SELECT save_id, system_ua, planet_index, planet_ua, biome, infested, "
           "named, name, discovered_at, system_name, glyphs, coords FROM planets")
    args: tuple = ()
    if save_id:
        sql += " WHERE save_id=?"
        args = (save_id,)
    sql += " ORDER BY system_ua, planet_index"
    out: list[dict] = []
    for row in conn.execute(sql, args):
        item = dict(row)
        item["ua"] = item.get("planet_ua")
        item["named"] = bool(item.get("named"))
        item["infested"] = (None if item.get("infested") is None
                            else bool(item["infested"]))
        out.append(item)
    return out


def _center_distance_ly(ua: Any) -> float | None:
    """到银河中心（voxel 0,0,0）的估算距离；地址不可用时 None。"""
    value = discoveries.normalize_ua(ua)
    if value is None:
        return None
    try:
        u = address.unpack_ua(value)
    except (TypeError, ValueError):
        return None
    return math.sqrt(u["x"] ** 2 + u["y"] ** 2 + u["z"] ** 2) * discoveries.LY_PER_VOXEL


def _distance_key(row: dict) -> tuple:
    value = row.get("distance_ly")
    if value is None:
        return (1, 0.0, str(row.get("system_ua") or ""), int(row.get("planet_index") or 0))
    return (0, float(value), str(row.get("system_ua") or ""),
            int(row.get("planet_index") or 0))


def query(biome: Any = None, infested: Any = None, named: Any = None,
          limit: int | None = 500, order: str = "distance", *,
          near_ua: Any = None, save_id: str | None = None,
          db_file: str | None = None) -> list[dict]:
    """按群系/感染/命名筛选索引里的行星。

    ``order="distance"`` 默认按到银河中心的距离；给出 ``near_ua`` 时改为到该
    地址的距离（与 ``discoveries.filter_discovered(sort="distance")`` 同源）。
    ``order="biome"`` 按群系名排序。筛选/排序规则直接复用数据层，保证两处结果
    一致；参数非法时抛 ``ValueError``。
    """
    mode = str(order or "distance").strip().casefold()
    if mode not in ("distance", "biome", "discovered", "order"):
        raise ValueError(f"不支持的排序方式：{order!r}（可用 distance / biome）")
    conn = _connect(db_file)
    try:
        rows = _db_rows(conn, save_id)
    finally:
        conn.close()

    if mode == "biome":
        return discoveries.filter_discovered(rows, biome=biome, infested=infested,
                                             named=named, limit=limit, sort="biome")
    if mode == "discovered":
        return discoveries.filter_discovered(rows, biome=biome, infested=infested,
                                             named=named, limit=limit, sort="discovered")
    if mode == "order":
        return discoveries.filter_discovered(rows, biome=biome, infested=infested,
                                             named=named, limit=limit, sort="order")

    origin = None if near_ua in (None, "") else near_ua
    if origin is not None:
        return discoveries.filter_discovered(rows, biome=biome, infested=infested,
                                             named=named, near_ua=origin,
                                             limit=limit, sort="distance")

    filtered = discoveries.filter_discovered(rows, biome=biome, infested=infested,
                                             named=named, limit=None, sort="order")
    for row in filtered:
        row["distance_ly"] = _center_distance_ly(row.get("ua"))
    filtered.sort(key=_distance_key)
    if limit is not None:
        try:
            count = int(limit)
        except (TypeError, ValueError) as e:
            raise ValueError("limit 必须是整数") from e
        filtered = filtered[: max(0, min(count, _MAX_LIMIT))]
    return filtered


def stats(db_file: str | None = None) -> dict:
    """索引规模与聚合计数；不返回真实地址/名字。"""
    conn = _connect(db_file)
    try:
        saves = conn.execute("SELECT COUNT(*) n FROM saves").fetchone()["n"]
        planets = conn.execute("SELECT COUNT(*) n FROM planets").fetchone()["n"]
        infested = conn.execute(
            "SELECT COUNT(*) n FROM planets WHERE infested=1").fetchone()["n"]
        named = conn.execute(
            "SELECT COUNT(*) n FROM planets WHERE named=1").fetchone()["n"]
        biomes = {row["biome"]: row["n"] for row in conn.execute(
            "SELECT biome, COUNT(*) n FROM planets WHERE biome IS NOT NULL "
            "GROUP BY biome ORDER BY n DESC, biome")}
        updated = conn.execute("SELECT MAX(indexed_at) t FROM saves").fetchone()["t"]
        meta = {row["k"]: row["v"] for row in conn.execute("SELECT k, v FROM meta")}
        return {"ok": True, "db": conn.execute("PRAGMA database_list").fetchone()["file"],
                "saves": int(saves), "planets": int(planets),
                "biomes": biomes, "infested": int(infested), "named": int(named),
                "updated": updated, "extractor_ver": EXTRACTOR_VER,
                "active_extractor_ver": _int_or_none(meta.get("extractor_ver")),
                "schema_version": SCHEMA_VERSION}
    finally:
        conn.close()


# ---------------------------------------------------------------- 动物发现（同伴联查用）


def _get_path(tree: Any, path: tuple[str, ...]) -> Any:
    cur = tree
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _seed_hex(value: Any) -> str | None:
    number = _int_or_none(value)
    return None if number is None else f"0x{number:X}"


def _animal_row(rec: dict, source: str, seq: int) -> dict | None:
    """单条 ``Animal`` 发现记录 → 行星动物行；非动物/坏记录返回 None。"""
    dd = rec.get("DD")
    if not isinstance(dd, dict):
        return None
    if str(dd.get("DT") or "").lstrip("^") != "Animal":
        return None

    ua = discoveries.normalize_ua(dd.get("UA"))
    if ua is None:
        ua = discoveries.normalize_ua(rec.get("UA"))
    fallback_index = discoveries._record_planet_index(rec, dd)
    fallback_system = discoveries._record_system_ua(rec, dd)

    if ua is not None:
        system_ua = ua & ~discoveries.PLANET_MASK
        planet_index = (ua >> discoveries.PLANET_SHIFT) & 0xF
    else:
        system_ua = fallback_system
        planet_index = fallback_index
    if (planet_index in (None, 0)) and fallback_index not in (None, 0):
        planet_index = fallback_index
    if system_ua is None or planet_index is None:
        return None

    vp_raw = dd.get("VP")
    if vp_raw is None:
        vp_raw = rec.get("VP")
    vp = list(vp_raw) if isinstance(vp_raw, (list, tuple)) else []

    def seed(i: int) -> str | None:
        return _seed_hex(vp[i]) if len(vp) > i else None

    dm = rec.get("DM") if isinstance(rec.get("DM"), dict) else {}
    ows = rec.get("OWS") if isinstance(rec.get("OWS"), dict) else {}
    ts = _int_or_none(ows.get("TS"))
    if ts is None or ts <= 0:
        ts = _int_or_none(rec.get("TSrec"))
        ts = ts if ts is not None and ts > 0 else None

    return {
        "planet_ua": _hex(ua if ua is not None else
                          (system_ua | (planet_index << discoveries.PLANET_SHIFT)
                           if planet_index > 0 else system_ua)),
        "system_ua": f"0x{system_ua:X}",
        "planet_index": int(planet_index),
        "creature_seed": seed(0),
        "role_seed": seed(1),
        "species_seed": seed(2),
        "genus_seed": seed(3),
        "variant_seed": seed(4),
        "name": _text(dm.get("CN")),
        "discoverer": _text(ows.get("USN")),
        "discovered_at": ts,
        "source": "save-pending" if source == "save-pending" else "save",
        "_seq": seq,
    }


def fauna_from_tree(readable: Any, *, system_ua: Any = None,
                    planet_index: Any = None) -> dict:
    """从已打开的存档树提取动物发现记录（纯函数，便于合成测试）。

    返回 ``{fauna, count, records, skipped}``；按 ``(planet_ua, creature_seed)``
    去重，保留第一次出现的记录。``system_ua`` / ``planet_index`` 为 None 时不过滤。
    """
    target_system = discoveries.normalize_ua(system_ua)
    if target_system is not None:
        target_system &= ~discoveries.PLANET_MASK
    target_index = _int_or_none(planet_index)
    if target_index is not None and not 0 <= target_index <= 0xF:
        target_index = None

    rows: list[dict] = []
    seen: set[tuple] = set()
    records = 0
    skipped = 0
    seq = 0
    for path, source in ((discoveries.DISCOVERY_PATH, "save"),
                         (discoveries.AVAILABLE_PATH, "save-pending")):
        items = _get_path(readable, path)
        if items is None:
            continue
        if not isinstance(items, list):
            skipped += 1
            continue
        for rec in items:
            if not isinstance(rec, dict):
                skipped += 1
                continue
            dd = rec.get("DD")
            is_animal = (isinstance(dd, dict)
                         and str(dd.get("DT") or "").lstrip("^") == "Animal")
            row = _animal_row(rec, source, seq)
            seq += 1
            if row is None:
                if is_animal:
                    skipped += 1
                continue
            records += 1
            if target_system is not None:
                if discoveries.normalize_ua(row["system_ua"]) != target_system:
                    continue
            if target_index is not None and row["planet_index"] != target_index:
                continue
            key = (row["planet_ua"], row["creature_seed"] or f"#{row['_seq']}")
            if key in seen:
                continue
            seen.add(key)
            row.pop("_seq", None)
            rows.append(row)

    if skipped:
        log.info("动物发现：跳过 %d 条坏记录", skipped)
    return {"fauna": rows, "count": len(rows), "records": records, "skipped": skipped}


def planet_fauna(system_ua: Any, planet_index: Any,
                 path: str | None = None) -> dict:
    """某颗行星的动物发现记录（只读；没有记录时返回空 + 原因）。"""
    target_system = discoveries.normalize_ua(system_ua)
    index = _int_or_none(planet_index)
    if target_system is None:
        return {"ok": False, "count": 0, "fauna": [], "system_ua": None,
                "planet_index": index, "reason": "系统地址（system_ua）不合法"}
    target_system &= ~discoveries.PLANET_MASK
    if index is None or not 1 <= index <= 6:
        return {"ok": False, "count": 0, "fauna": [],
                "system_ua": f"0x{target_system:X}", "planet_index": index,
                "reason": "行星序号必须在 1..6（0 表示未知，不可定位）"}
    target_planet = target_system | (index << discoveries.PLANET_SHIFT)
    try:
        save_path, readable = discoveries._open_tree(path)
    except Exception as e:                                # noqa: BLE001
        return {"ok": False, "count": 0, "fauna": [],
                "system_ua": f"0x{target_system:X}", "planet_index": index,
                "planet_ua": f"0x{target_planet:X}",
                "reason": f"读取存档失败：{type(e).__name__}: {e}"}

    parsed = fauna_from_tree(readable, system_ua=target_system, planet_index=index)
    return {
        "ok": True,
        "path": str(save_path),
        "system_ua": f"0x{target_system:X}",
        "planet_ua": f"0x{target_planet:X}",
        "planet_index": index,
        "count": parsed["count"],
        "fauna": parsed["fauna"],
        "skipped": parsed["skipped"],
        "reason": None if parsed["count"] else "没有找到该行星的动物发现记录",
    }


__all__ = [
    "EXTRACTOR_VER",
    "SCHEMA",
    "SCHEMA_VERSION",
    "db_path",
    "fauna_from_tree",
    "index_save",
    "planet_fauna",
    "query",
    "stats",
]
