"""存档「已发现星球」数据层（只读）。

数据来源（本机 save Version 4746 实测）::

    DiscoveryManagerData
    └─ DiscoveryData-v1
       ├─ Store.Record[]        # 已完成的发现；Planet 记录在这里
       └─ Available[]           # 待上传/暂存；结构同样是 DD + TSrec

本模块只读：不启动游戏、不调用 unicorn、不写存档，也不依赖 ``starforge.app``。

字段位布局参考社区实现（nms-copilot, MIT），本实现独立重写：
  · ``DD.VP[1]`` 低 16 位是 ``GcBiomeType`` 枚举，bit 16 是 infested；
  · ``DD.UA`` 的 bit 52..55 是行星序号，清掉这 4 位就是系统地址。
上游代码没有复制；群系名称按本项目规范（Exotic / Lava / Waterworld / Gas giant）。

设计原则：
  · 字段缺失、UA 非法、VP 长度不足时一律返回 ``None``，不猜默认值；
  · 只从 ``DM.CN`` 取玩家命名，绝不生成「游戏自动名」；
  · 日志与警告只写计数，不写真实名字、账号或坐标。
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .glyphs import glyphs_for_ua, unpack_ua

# 本机实测的 JSON 路径。路径单独提出来，便于存档结构变化时只改一处。
DISCOVERY_PATH = ("DiscoveryManagerData", "DiscoveryData-v1", "Store", "Record")
AVAILABLE_PATH = ("DiscoveryManagerData", "DiscoveryData-v1", "Available")

PLANET_SHIFT = 52
PLANET_MASK = 0xF << PLANET_SHIFT

# 存档 UA 里 galaxy 在 bit 32..39，system 在 bit 40..51；
# 距离换算沿用 nms-copilot 公开的 400 ly/voxel 与 Robbins 常数。
LY_PER_VOXEL = 400.0
ROBBINS_CONSTANT = 0.661707182
VOXEL_UNCERTAINTY = ROBBINS_CONSTANT * LY_PER_VOXEL

# GcBiomeType 索引 → 规范名。index 11 在游戏里是 Test，数据层保留真值，
# 由 UI 决定是否隐藏；未知索引返回 None，不猜。
BIOMES: tuple[str, ...] = (
    "Lush", "Toxic", "Scorched", "Radioactive",
    "Frozen", "Barren", "Dead", "Exotic",
    "Red", "Green", "Blue", "Test",
    "Swamp", "Lava", "Waterworld", "Gas giant",
)
BIOME_BY_ID: dict[int, str] = {i: name for i, name in enumerate(BIOMES)}

# 查询层别名：兼容旧索引/界面里的 Weird/Volcanic/Ocean/Gas 等写法。
BIOME_ALIASES: dict[str, str] = {
    "weird": "Exotic",
    "volcanic": "Lava",
    "ocean": "Waterworld",
    "water world": "Waterworld",
    "gas": "Gas giant",
    "gasgiant": "Gas giant",
    "gas giant": "Gas giant",
}

# 过滤结果最多返回多少条；与 galaxy.query 的上限保持一致。
MAX_LIMIT = 500

_TRUE_WORDS = {"1", "true", "yes", "on", "y", "是", "有"}
_FALSE_WORDS = {"0", "false", "no", "off", "n", "否", "无", ""}
# UI 下拉框的「全部/不限」空值；数据层把它等同于 None，避免把 "" 当成筛选值。
_UNSET_WORDS = {"", "all", "any", "不限", "全部"}


# ---------------------------------------------------------------- 基础归一化


def normalize_ua(value: Any) -> int | None:
    """int / ``"0x…"`` / 十进制字符串 → 正整数 UA；非法、0、负数一律 ``None``。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            # 与 creature._ua_value 一致：只有 0x 前缀按十六进制，其余按十进制。
            number = int(text, 16) if text.lower().startswith("0x") else int(text)
        except ValueError:
            return None
    else:
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if number <= 0 or number > 0xFFFFFFFFFFFFFFFF:
        return None
    return number


def _as_int(value: Any) -> int | None:
    """VP 里的 flags/seed 可能是 int 或 ``"0x…"`` 字符串；失败返回 None。"""
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
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _positive_int(value: Any) -> int | None:
    """Unix 秒等正整数字段；0/缺失/非法返回 None。"""
    number = _as_int(value)
    return number if number is not None and number > 0 else None


def _is_unset(value: Any) -> bool:
    """UI 的「全部/不限」空值：None、空字符串、all/any/不限/全部。"""
    if value is None:
        return True
    return isinstance(value, str) and value.strip().casefold() in _UNSET_WORDS


def _as_flag(value: Any) -> bool | None:
    """把 ``True/False``、0/1、以及常见中英文词转成布尔；无法识别返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().casefold()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None


# ---------------------------------------------------------------- UA / VP 解码


def decode_vp(vp: Any) -> dict:
    """解码 ``DD.VP``。

    返回 ``{biome_index, biome, infested, vp0, flags, ok}``；VP 缺失、长度 <2
    或 flags 非法时对应字段为 ``None``。``ok`` 只表示 flags 是否能解出。
    """
    raw = list(vp) if isinstance(vp, (list, tuple)) else None
    out = {
        "biome_index": None,
        "biome": None,
        "infested": None,
        "vp0": raw[0] if raw else None,
        "flags": None,
        "ok": False,
    }
    if not raw or len(raw) < 2:
        return out
    flags = _as_int(raw[1])
    if flags is None:
        return out
    biome_index = flags & 0xFFFF
    out.update({
        "biome_index": biome_index,
        "biome": BIOME_BY_ID.get(biome_index),
        "infested": bool(flags & 0x10000),
        "flags": flags,
        "ok": True,
    })
    return out


def coords_for_ua(ua: Any) -> str | None:
    """UA → 信号增幅器风格坐标 ``XXXX:YYYY:ZZZZ:SSSS``；非法 UA 返回 None。"""
    value = normalize_ua(ua)
    if value is None:
        return None
    u = unpack_ua(value)
    return (f"{u['x'] + 0x7FF:04X}:{u['y'] + 0x7F:04X}:"
            f"{u['z'] + 0x7FF:04X}:{u['system']:04X}")


def _glyphs_for(system_ua: int | None, planet_index: int | None) -> str | None:
    """系统地址 + 1..6 的行星序号 → 12 位符文；不合法就不生成。"""
    if system_ua is None or planet_index is None:
        return None
    try:
        planet = int(planet_index)
        if not 1 <= planet <= 6:
            return None
        return glyphs_for_ua(int(system_ua), planet=planet)
    except (TypeError, ValueError, OverflowError):
        return None


def _system_address(ua: int) -> int:
    return ua & ~PLANET_MASK


# ---------------------------------------------------------------- 记录 → 行星


def _record_system_ua(rec: dict, dd: dict) -> int | None:
    """记录里显式给出的系统地址（某些存档/合成数据可能没有行星位）。"""
    for container in (rec, dd):
        if not isinstance(container, dict):
            continue
        for key in ("system_ua", "SystemUA", "systemUA", "system"):
            value = normalize_ua(container.get(key))
            if value is not None:
                return _system_address(value)
    return None


def _record_planet_index(rec: dict, dd: dict) -> int | None:
    """记录里单独给出的行星序号（0..15），用于 UA 缺行星位时补位。"""
    for container in (rec, dd):
        if not isinstance(container, dict):
            continue
        for key in ("planet_index", "PlanetIndex", "planetIndex", "index", "PI"):
            value = _as_int(container.get(key))
            if value is not None and 0 <= value <= 0xF:
                return value
    return None


def planet_from_record(rec: Any, *, source: str = "save",
                       system_names: dict[int, str] | None = None,
                       system_discoverers: dict[int, str] | None = None) -> dict | None:
    """单条 ``Planet`` 发现记录 → 可序列化字典；非 Planet/空记录返回 None。

    字段缺失时值为 ``None``，不会用 0、空字符串或推测值填充。
    ``source`` 为 ``"save"``（Store）或 ``"save-pending"``（Available）。
    行星自己的 ``DM.CN/OWS.USN`` 优先；缺失时可回退到系统级映射。
    """
    if not isinstance(rec, dict):
        return None
    dd = rec.get("DD")
    if not isinstance(dd, dict):
        return None
    dt = str(dd.get("DT") or "").lstrip("^")
    if dt != "Planet":
        return None

    # UA：先看 DD.UA，再看记录顶层；缺失时用「系统地址 + 行星序号」补。
    ua = normalize_ua(dd.get("UA"))
    if ua is None:
        ua = normalize_ua(rec.get("UA"))
    fallback_index = _record_planet_index(rec, dd)
    fallback_system = _record_system_ua(rec, dd)

    if ua is None and fallback_system is not None and fallback_index is not None:
        ua = (fallback_system & ~PLANET_MASK) | ((fallback_index & 0xF) << PLANET_SHIFT)
    elif ua is not None and ((ua >> PLANET_SHIFT) & 0xF) == 0 \
            and fallback_index is not None and fallback_index > 0:
        # 有些记录把行星位写成 0，行星序号另存；只在能确定时补位。
        ua = (ua & ~PLANET_MASK) | ((fallback_index & 0xF) << PLANET_SHIFT)

    if ua is not None:
        planet_index = (ua >> PLANET_SHIFT) & 0xF
        system_ua = _system_address(ua) or None
        galaxy = unpack_ua(ua)["galaxy"] if system_ua is not None else None
    else:
        planet_index = fallback_index
        system_ua = fallback_system
        galaxy = unpack_ua(system_ua)["galaxy"] if system_ua is not None else None

    vp_raw = dd.get("VP")
    if vp_raw is None:
        vp_raw = rec.get("VP")
    vp = list(vp_raw) if isinstance(vp_raw, (list, tuple)) else None
    decoded = decode_vp(vp)

    dm = rec.get("DM") if isinstance(rec.get("DM"), dict) else {}
    ows = rec.get("OWS") if isinstance(rec.get("OWS"), dict) else {}
    raw_name = dm.get("CN")
    name = str(raw_name).strip() if isinstance(raw_name, str) and raw_name.strip() else None
    raw_usn = ows.get("USN")
    discoverer = (str(raw_usn).strip()
                  if isinstance(raw_usn, str) and raw_usn.strip() else None)
    if discoverer is None and system_ua is not None and system_discoverers:
        discoverer = system_discoverers.get(system_ua)
    discovered_at = _positive_int(ows.get("TS"))
    if discovered_at is None:
        # Available[] 没有 OWS，只有 TSrec（同样是 Unix 秒）。
        discovered_at = _positive_int(rec.get("TSrec"))

    system_name = None
    if system_ua is not None and system_names:
        system_name = system_names.get(system_ua)

    system_text = f"0x{system_ua:X}" if system_ua is not None else None
    ua_text = f"0x{ua:X}" if ua is not None else None
    return {
        # 任务约定的 ua = 行星地址；system_ua 另给，供传送/分组使用。
        "ua": ua_text,
        "planet_ua": ua_text,
        "system_ua": system_text,
        "system_key": (f"{galaxy}:{system_text}" if system_ua is not None else None),
        "planet_index": planet_index,
        "galaxy": galaxy,
        "biome": decoded["biome"],
        "biome_index": decoded["biome_index"],
        "infested": decoded["infested"],
        "named": bool(name),
        "name": name,
        "discoverer": discoverer,
        "discovered_at": discovered_at,
        "system_name": system_name,
        "glyphs": _glyphs_for(system_ua, planet_index),
        "coords": coords_for_ua(system_ua),
        "vp0": decoded["vp0"],
        "vp": vp,
        "source": "save-pending" if source == "save-pending" else "save",
        "pending": source == "save-pending",
    }


# ---------------------------------------------------------------- 存档树解析


def _get_path(tree: Any, path: tuple[str, ...]) -> Any:
    cur = tree
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _system_meta(readable: Any) -> tuple[dict[int, str], dict[int, str]]:
    """从 SolarSystem 记录建立 ``system_ua -> 名字/发现者`` 映射（只用于显示）。"""
    names: dict[int, str] = {}
    discoverers: dict[int, str] = {}
    for path in (DISCOVERY_PATH, AVAILABLE_PATH):
        rows = _get_path(readable, path)
        if not isinstance(rows, list):
            continue
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            dd = rec.get("DD")
            if not isinstance(dd, dict):
                continue
            if str(dd.get("DT") or "").lstrip("^") != "SolarSystem":
                continue
            ua = normalize_ua(dd.get("UA"))
            if ua is None:
                continue
            system_ua = _system_address(ua)
            dm = rec.get("DM") if isinstance(rec.get("DM"), dict) else {}
            ows = rec.get("OWS") if isinstance(rec.get("OWS"), dict) else {}
            cn = dm.get("CN")
            usn = ows.get("USN")
            if isinstance(cn, str) and cn.strip():
                names[system_ua] = cn.strip()
            if isinstance(usn, str) and usn.strip():
                discoverers[system_ua] = usn.strip()
    return names, discoverers


def _planet_key(planet: dict, seq: int) -> tuple:
    """去重键：优先 ``(system_ua, planet_index)``，UA 不可用时退回原始 UA。"""
    system_ua = planet.get("system_ua")
    planet_index = planet.get("planet_index")
    if system_ua and planet_index is not None:
        return ("system", system_ua, int(planet_index))
    if planet.get("ua"):
        return ("ua", planet["ua"])
    return ("record", seq)


def _rank(planet: dict) -> tuple:
    """合并重复记录时的优先级：Store 优先，其次发现时间，最后记录顺序。"""
    return (
        1 if planet.get("source") == "save" else 0,
        int(planet.get("discovered_at") or -1),
        int(planet.get("_seq", -1)),
    )


def _merge_planet(old: dict, new: dict) -> dict:
    """合并同一颗行星的重复记录；保留原始条目中的非空字段。"""
    winner, loser = (new, old) if _rank(new) >= _rank(old) else (old, new)
    merged = dict(winner)
    for key, value in loser.items():
        if key.startswith("_"):
            continue
        if merged.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
            merged[key] = value
    # 命名状态由最终 name 决定，避免合并后出现「named=True 但没有名字」。
    merged["named"] = bool(merged.get("name"))
    if old.get("source") == "save" or new.get("source") == "save":
        merged["source"] = "save"
        merged["pending"] = False
    else:
        merged["source"] = "save-pending"
        merged["pending"] = True
    merged["_seq"] = min(int(old.get("_seq", 0)), int(new.get("_seq", 0)))
    return merged


def planets_from_tree(readable: Any) -> dict:
    """从已打开的存档 JSON 树解析行星发现记录（纯函数，便于合成测试）。

    返回 ``{found, planets, warnings, records, duplicates}``：
      · ``found`` 表示存档里是否存在发现数据容器；
      · ``records`` 是原始 Planet 记录数（含重复）；
      · ``planets`` 按 ``(system_ua, planet_index)`` 合并后的行；
      · 非法 UA 的行会保留（字段为 None），不会丢原始记录。
    """
    store = _get_path(readable, DISCOVERY_PATH)
    available = _get_path(readable, AVAILABLE_PATH)
    found = store is not None or available is not None
    warnings: list[str] = []
    if not found:
        return {
            "found": False,
            "planets": [],
            "warnings": ["没有找到 DiscoveryManagerData.DiscoveryData-v1（可能不是玩家存档或版本不兼容）"],
            "records": 0,
            "duplicates": 0,
        }

    system_names, system_discoverers = _system_meta(readable)
    raw: list[dict] = []
    for source, rows, label in (
        ("save", store, "Store.Record"),
        ("save-pending", available, "Available"),
    ):
        if rows is None:
            continue
        if not isinstance(rows, list):
            warnings.append(f"{label} 不是数组，已跳过")
            continue
        for rec in rows:
            planet = planet_from_record(rec, source=source, system_names=system_names,
                                        system_discoverers=system_discoverers)
            if planet is None:
                continue
            planet["_seq"] = len(raw)
            raw.append(planet)

    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    duplicates = 0
    for planet in raw:
        key = _planet_key(planet, int(planet.get("_seq", 0)))
        if key in merged:
            merged[key] = _merge_planet(merged[key], planet)
            duplicates += 1
        else:
            merged[key] = planet
            order.append(key)

    planets: list[dict] = []
    for key in order:
        row = dict(merged[key])
        row.pop("_seq", None)
        planets.append(row)

    invalid_ua = sum(1 for row in planets if row.get("ua") is None)
    missing_vp = sum(1 for row in planets if row.get("vp") is None)
    unknown_biome = sum(1 for row in planets
                        if row.get("biome_index") is not None and row.get("biome") is None)
    if duplicates:
        warnings.append(f"发现记录有 {duplicates} 条重复（按 system_ua + planet_index 合并）")
    if invalid_ua:
        warnings.append(f"{invalid_ua} 颗行星没有可用地址（UA），字段保留为 None")
    if missing_vp:
        warnings.append(f"{missing_vp} 颗行星缺少 VP，群系/虫蚀为 None")
    if unknown_biome:
        warnings.append(f"{unknown_biome} 颗行星的群系索引未知，未猜测名称")
    return {
        "found": True,
        "planets": planets,
        "warnings": warnings,
        "records": len(raw),
        "duplicates": duplicates,
    }


def _stats(planets: list[dict]) -> dict:
    """给界面用的聚合计数；不包含任何真实地址/名字。"""
    biomes = Counter(row["biome"] for row in planets if row.get("biome"))
    return {
        "biomes": dict(biomes.most_common()),
        "infested": sum(1 for row in planets if row.get("infested")),
        "named": sum(1 for row in planets if row.get("named")),
        "pending": sum(1 for row in planets if row.get("pending")),
        "unknown_biome": sum(1 for row in planets if row.get("biome") is None),
    }


def _open_tree(path: str | None = None) -> tuple[Any, Any]:
    """打开存档并返回 ``(路径, readable JSON 树)``；供测试打桩。"""
    from .core import paths
    from .save import library

    p = library.resolve(path)
    paths.ensure_shipwright_importable()
    from nms_save import save as nms_save

    return p, nms_save.open_save(str(p)).readable


# ---------------------------------------------------------------- 只读 API


def discovered_planets(path: str | None = None) -> dict:
    """读取当前存档里的已发现行星。

    返回 ``{ok, path, count, planets, warnings, ...}``。读不到存档时
    ``ok=False``、``count=0``，并在 ``warnings`` 里说明原因；不抛裸异常，
    方便 UI 显示空态。字段解码失败不会伪造默认值。
    """
    try:
        p, readable = _open_tree(path)
    except Exception as e:                                # noqa: BLE001 - 上游异常类型很多
        return {
            "ok": False,
            "path": str(path or ""),
            "count": 0,
            "records": 0,
            "duplicates": 0,
            "planets": [],
            "warnings": [f"读取存档失败：{type(e).__name__}: {e}"],
        }

    parsed = planets_from_tree(readable)
    planets = parsed["planets"]
    version = readable.get("Version") if isinstance(readable, dict) else None
    return {
        "ok": bool(parsed["found"]),
        "path": str(p),
        "count": len(planets),
        "records": parsed["records"],
        "duplicates": parsed["duplicates"],
        "planets": planets,
        "warnings": list(parsed["warnings"]),
        "version": version,
        "stats": _stats(planets),
    }


def distance_ly(ua_a: Any, ua_b: Any) -> float | None:
    """两个 UA 的估算距离（ly）；任一方非法或跨银河时返回 None。

    规则（与社区公开算法一致，独立重写）：
      · 同系统（同 voxel + 同 system index）→ 0；
      · 同 voxel、不同 system index → Robbins 常数 × 400 ≈ 264.68 ly；
      · 其他 → 三维 voxel 欧氏距离 × 400。
    跨银河的距离没有物理意义，因此不计算、不编造。
    """
    a = normalize_ua(ua_a)
    b = normalize_ua(ua_b)
    if a is None or b is None:
        return None
    ua = unpack_ua(a)
    ub = unpack_ua(b)
    if ua["galaxy"] != ub["galaxy"]:
        return None
    same_voxel = (ua["x"], ua["y"], ua["z"]) == (ub["x"], ub["y"], ub["z"])
    if same_voxel:
        return 0.0 if ua["system"] == ub["system"] else VOXEL_UNCERTAINTY
    dx = float(ua["x"] - ub["x"])
    dy = float(ua["y"] - ub["y"])
    dz = float(ua["z"] - ub["z"])
    return (dx * dx + dy * dy + dz * dz) ** 0.5 * LY_PER_VOXEL


def _canonical_biome(value: Any) -> str | None:
    """群系名/索引/中文/旧别名 → 规范名；认不出返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return BIOME_BY_ID.get(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return BIOME_BY_ID.get(int(text))
    lowered = text.casefold()
    for name in BIOMES:
        if name.casefold() == lowered:
            return name
    alias = BIOME_ALIASES.get(lowered)
    if alias:
        return alias
    # 中文名：反查 zh.BIOME_ZH，再走一次别名（火山→Volcanic→Lava）。
    try:
        from . import zh
    except Exception:                                     # noqa: BLE001
        return None
    for english, chinese in zh.BIOME_ZH.items():
        if chinese == text:
            return _canonical_biome(english)
    return None


def _row_biome(row: dict) -> str | None:
    name = _canonical_biome(row.get("biome"))
    if name is not None:
        return name
    index = row.get("biome_index")
    return BIOME_BY_ID.get(index) if isinstance(index, int) else None


def _row_ua(row: dict) -> int | None:
    for key in ("ua", "planet_ua", "system_ua"):
        value = normalize_ua(row.get(key))
        if value is not None:
            return value
    return None


def _int_or(value: Any, default: int = -1) -> int:
    number = _as_int(value)
    return default if number is None else number


def _system_sort_key(row: dict) -> tuple:
    return (_int_or(row.get("galaxy")), normalize_ua(row.get("system_ua")) or -1,
            _int_or(row.get("planet_index")))


def _distance_sort_key(row: dict) -> tuple:
    value = row.get("distance_ly")
    if value is None:
        return (1, 0.0)
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, 0.0)


def _discovered_sort_key(row: dict) -> tuple:
    value = _as_int(row.get("discovered_at"))
    if value is None or value <= 0:
        return (1, 0)
    return (0, -value)


def _biome_sort_key(row: dict) -> tuple:
    name = _row_biome(row)
    return (1 if name is None else 0, (name or "").casefold(),
            _distance_sort_key(row), _discovered_sort_key(row), _system_sort_key(row))


def _normalize_sort(sort: str | None, has_origin: bool) -> str:
    text = str(sort or "auto").strip().casefold()
    if text in ("", "auto"):
        return "distance" if has_origin else "discovered"
    if text in ("distance", "nearest", "near"):
        if not has_origin:
            raise ValueError("按距离排序需要同时提供 near_ua")
        return "distance"
    if text in ("biome", "group", "type"):
        return "biome"
    if text in ("order", "input", "record"):
        return "order"
    if text in ("discovered", "discovery", "time", "date", "recent"):
        return "discovered"
    raise ValueError(f"不支持的排序方式：{sort!r}（可用 distance / biome / discovered / order）")


def filter_discovered(planets: Any, *, biome: Any = None, infested: Any = None,
                      named: Any = None, near_ua: Any = None,
                      max_distance: Any = None, limit: int | None = 500,
                      sort: str = "auto") -> list[dict]:
    """筛选/排序已发现行星；返回新列表，不修改传入的行。

    · ``biome`` 接受规范名、枚举索引、中文名或旧别名（Weird/Volcanic/Ocean/Gas）；
    · ``infested`` / ``named`` 为 None 表示不限；字段未知时不会被当成 False；
    · ``near_ua`` 提供后会给每行加 ``distance_ly``；距离无法计算时为 None；
    · ``max_distance`` 必须与 ``near_ua`` 同时使用；
    · ``sort`` 支持 ``distance`` / ``biome`` / ``discovered`` / ``order`` / ``auto``；
    · ``limit`` 默认 500，超过 500 会被截断。
    """
    rows = [dict(item) for item in (planets or []) if isinstance(item, dict)]

    biome_unset = _is_unset(biome)
    infested_unset = _is_unset(infested)
    named_unset = _is_unset(named)
    near_unset = _is_unset(near_ua)
    max_unset = _is_unset(max_distance)

    origin = normalize_ua(near_ua) if not near_unset else None
    if not near_unset and origin is None:
        raise ValueError("near_ua 不是合法的 UA")
    if not max_unset:
        if origin is None:
            raise ValueError("max_distance 需要同时提供 near_ua")
        try:
            max_ly = float(max_distance)
        except (TypeError, ValueError) as e:
            raise ValueError("max_distance 必须是数字") from e
        if max_ly < 0:
            max_ly = 0.0
    else:
        max_ly = None

    if origin is not None:
        for row in rows:
            row["distance_ly"] = distance_ly(_row_ua(row), origin)

    wanted_biome = _canonical_biome(biome) if not biome_unset else None
    if not biome_unset:
        rows = [row for row in rows if wanted_biome is not None
                and _row_biome(row) == wanted_biome]

    want_infested = _as_flag(infested) if not infested_unset else None
    if not infested_unset:
        rows = [row for row in rows if row.get("infested") is not None
                and bool(row["infested"]) == bool(want_infested)]

    want_named = _as_flag(named) if not named_unset else None
    if not named_unset:
        rows = [row for row in rows if bool(row.get("named")) == bool(want_named)]

    if max_ly is not None:
        rows = [row for row in rows if row.get("distance_ly") is not None
                and float(row["distance_ly"]) <= max_ly]

    mode = _normalize_sort(sort, origin is not None)
    if mode == "distance":
        rows.sort(key=lambda row: (_distance_sort_key(row), _system_sort_key(row)))
    elif mode == "biome":
        rows.sort(key=_biome_sort_key)
    elif mode == "discovered":
        rows.sort(key=lambda row: (_discovered_sort_key(row),
                                   _distance_sort_key(row), _system_sort_key(row)))
    # mode == "order"：保留传入/存档记录顺序，不做二次排序。

    if limit is not None:
        try:
            count = int(limit)
        except (TypeError, ValueError) as e:
            raise ValueError("limit 必须是整数") from e
        rows = rows[: max(0, min(count, MAX_LIMIT))]
    return rows


__all__ = [
    "AVAILABLE_PATH",
    "BIOMES",
    "BIOME_BY_ID",
    "DISCOVERY_PATH",
    "LY_PER_VOXEL",
    "MAX_LIMIT",
    "VOXEL_UNCERTAINTY",
    "coords_for_ua",
    "decode_vp",
    "discovered_planets",
    "distance_ly",
    "filter_discovered",
    "normalize_ua",
    "planet_from_record",
    "planets_from_tree",
]
