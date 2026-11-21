"""同伴（Pets）读取：把存档里的 `PlayerStateData.Pets[]` 变成可展示的条目。

为什么单独一层（PLAN-V4 · T8 / M8-lite）：
  · 存档里每只同伴是"描述符 + 种子"结构（`Descriptors` + `CreatureSeed/SpeciesSeed/GenusSeed`），
    与飞船同构 —— 这是将来"按外观搜同伴"的入口；
  · 上游 `nms_save.extras.companions()` 只给 6 个字段，够列表但不够做图鉴/写回，
    所以这里直接读原始条目，把描述符、种子、性格、UA 一并带出来；
  · **只读**：本模块不做任何写操作（写回同伴属 T8 第二阶段，需要生成器验证后才做）。
"""
from __future__ import annotations

import os
import re

from .core import log, paths
from .glyphs import glyphs_for_ua, unpack_ua

log = log.get("creature")

# 银河序号 → 名称（与上游 `nms_procgen.locate.GALAXIES` 一致；只用于显示，不参与换算）
GALAXY_NAMES = ("Euclid", "Hilbert Dimension", "Calypso", "Hesperius Dimension", "Hyades",
                "Ickjamatew", "Butterfly", "Tikomaa", "Occupati", "Budullangr")

# 描述符末尾的纯数字（实测 8–10 位）是社区所称的「唯一 ID」，不参与部件分组
_UNIQUE_ID_RE = re.compile(r"^\d{8,12}$")

# 游戏里 `CreatureType` 的取值 → 中文（其余原样显示）
TYPE_ZH = {"Prey": "猎物", "Predator": "掠食者", "Passive": "温顺",
           "Flying": "飞行", "Swimming": "水生", "Proto": "原生"}
BIOME_ZH = {"Lush": "茂盛", "Toxic": "剧毒", "Scorched": "焦土", "Radioactive": "辐射",
            "Frozen": "冰冻", "Barren": "荒芜", "Dead": "死寂", "Exotic": "异域",
            "Red": "红", "Green": "绿", "Blue": "蓝", "Swamp": "沼泽", "Volcanic": "火山"}


def _nms():
    paths.ensure_shipwright_importable()
    from nms_save import save as nms_save
    return nms_save


def _seed_str(v) -> str:
    """存档里的种子有两种形状：`"0x…"` 字符串，或 `[bool, "0x…"]`。"""
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return str(v[1])
    return str(v or "")


def _int(v) -> int:
    """UA 在存档里可能是 int，也可能是 `"0x…"` 字符串。"""
    if isinstance(v, str) and v.strip().lower().startswith("0x"):
        return int(v.strip(), 16)
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _clean(v) -> str:
    """游戏里的枚举值都带 `^` 前缀。"""
    return str(v or "").lstrip("^")


def _ua_value(v) -> int | None:
    """UA → 正整数；缺失/0/非法都返回 None（不猜一个默认地址）。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        text = v.strip()
        if not text:
            return None
        try:
            value = int(text, 16) if text.lower().startswith("0x") else int(text)
        except ValueError:
            return None
    else:
        try:
            value = int(v)
        except (TypeError, ValueError):
            return None
    return value if value > 0 else None


def portal_glyphs_valid(glyphs) -> bool:
    """与 agent 端 `_decode_glyphs` 一致的合法门地址校验（只校验，不改写）。"""
    text = str(glyphs or "").strip().upper()
    if len(text) != 12 or any(c not in "0123456789ABCDEF" for c in text):
        return False
    try:
        if not 1 <= int(text[0], 16) <= 6:
            return False
        if int(text[1:4], 16) in (0, 0xFFF):
            return False
        if int(text[4:6], 16) == 0x80:
            return False
        return not (int(text[6:9], 16) == 0x800 or int(text[9:12], 16) == 0x800)
    except ValueError:
        return False


def origin_for_ua(ua) -> dict | None:
    """UA → 来源行星位域；UA 缺失/0/非法返回 None。

    只用 `glyphs.unpack_ua` 做位段拆分，不调用 `nms_procgen`，也不访问游戏进程。
    `planet` 为 0 时仍保留 origin（地址本身可读），但 `glyphs` 会是 None。
    """
    value = _ua_value(ua)
    if value is None:
        return None
    try:
        u = unpack_ua(value)
    except (TypeError, ValueError, OverflowError):
        return None
    g = int(u["galaxy"])
    return {
        "galaxy": g,
        "galaxy_name": GALAXY_NAMES[g] if 0 <= g < len(GALAXY_NAMES) else f"Galaxy {g + 1}",
        "system": int(u["system"]),
        "planet": int(u["planet"]),
        "voxel_x": int(u["x"]),
        "voxel_y": int(u["y"]),
        "voxel_z": int(u["z"]),
        "ua": f"0x{value:X}",
    }


def _glyphs_for(origin: dict | None) -> str | None:
    """origin → 12 位门地址；行星位不是 1..6（含 0）或地址不合法时返回 None。"""
    if not isinstance(origin, dict):
        return None
    planet = origin.get("planet")
    try:
        planet = int(planet)
        value = int(str(origin.get("ua") or ""), 16)
    except (TypeError, ValueError):
        return None
    if not 1 <= planet <= 6:
        return None
    try:
        glyphs = glyphs_for_ua(value, planet)
    except (TypeError, ValueError, OverflowError):
        return None
    return glyphs if portal_glyphs_valid(glyphs) else None


def _descriptor_group(part: str) -> str:
    """`_BODY_PLANT` → `BODY`；认不出前缀的归到 `OTHER`（不丢部件）。"""
    text = str(part or "").strip().lstrip("^").lstrip("_")
    head = text.split("_", 1)[0].strip()
    return head.upper() if head else "OTHER"


def _descriptor_layout(descriptors) -> tuple[dict, str | None]:
    """描述符 → ({组: [{id, rarity}]}, 末尾纯数字唯一 ID 或 None)。"""
    items = [_clean(x) for x in (descriptors or []) if _clean(x)]
    unique_id = None
    if items and _UNIQUE_ID_RE.match(items[-1]):
        unique_id = items.pop()
    groups: dict[str, list[dict]] = {}
    for part in items:
        group = _descriptor_group(part)
        groups.setdefault(group, []).append({
            "id": part,
            "rarity": "XRARE" in part.upper(),
        })
    return groups, unique_id


def _nonzero_seed(v) -> str:
    text = _seed_str(v).strip()
    return "" if text.lower() in ("", "0", "0x0", "0x0000000000000000") else text


def _species_key(cid: str, pet: dict) -> tuple[str, str]:
    """(物种标识, 来源说明)。

    存档没有现成的「物种 ID」字段，这里用现有字段推导：`CreatureID` 是角色/物种名，
    `SpeciesSeed` 是该物种在存档里的种子；种子为 0 时退回 `GenusSeed`，再没有就只用角色名。
    """
    species = _nonzero_seed(pet.get("SpeciesSeed"))
    if species:
        return f"{cid}|{species}", "CreatureID + SpeciesSeed"
    genus = _nonzero_seed(pet.get("GenusSeed"))
    if genus:
        return f"{cid}|{genus}", "CreatureID + GenusSeed（SpeciesSeed 为空）"
    return cid, "CreatureID（SpeciesSeed/GenusSeed 为空）"


def companion_entry(pet: dict, index: int = 0) -> dict | None:
    """单条 `Pets[]` → 展示用字典；空槽/坏条目返回 None。

    `origin` / `glyphs` 在 UA 缺失、为 0 或行星位为 0 时为 None——**不编造默认值**。
    """
    if not isinstance(pet, dict):
        return None
    cid = _clean(pet.get("CreatureID"))
    if cid in ("", "^"):
        return None
    descriptors = [_clean(x) for x in (pet.get("Descriptors") or [])]
    ctype = _clean((pet.get("CreatureType") or {}).get("CreatureType"))
    biome = _clean((pet.get("Biome") or {}).get("Biome"))
    ua_number = _ua_value(pet.get("UA")) or 0
    origin = origin_for_ua(ua_number)
    glyphs = _glyphs_for(origin)
    groups, unique_id = _descriptor_layout(descriptors)
    species_key, species_source = _species_key(cid, pet)
    return {
        "index": index,
        "name": _clean(pet.get("CustomName")) or "(未命名)",
        "creature": cid,
        "creature_zh": cid.replace("_", " ").title(),
        "type": ctype,
        "type_zh": TYPE_ZH.get(ctype, ctype),
        "biome": biome,
        "biome_zh": BIOME_ZH.get(biome, biome),
        "predator": bool(pet.get("Predator")),
        "scale": round(float(pet.get("Scale") or 1.0), 3),
        "has_fur": bool(pet.get("HasFur")),
        "descriptors": descriptors,
        "descriptor_groups": groups,
        "unique_id": unique_id,
        "species_key": species_key,
        "species_key_source": species_source,
        "seeds": {
            "creature": _seed_str(pet.get("CreatureSeed")),
            "creature2": _seed_str(pet.get("CreatureSecondarySeed")),
            "species": _seed_str(pet.get("SpeciesSeed")),
            "genus": _seed_str(pet.get("GenusSeed")),
        },
        "ua": ua_number,
        "origin": origin,
        "glyphs": glyphs,
        "trust": pet.get("Trust"),
        "birth": pet.get("BirthTime"),
        "traits": len(pet.get("Traits") or []),
    }


def companions(save_path: str | None = None) -> dict:
    """→ {path, count, creatures:[...], note}"""
    from .save import library
    p = str(library.resolve(save_path))
    d = _nms().open_save(p).readable
    ps = d.get("BaseContext", {}).get("PlayerStateData", {})
    raw = ps.get("Pets") or []
    out = []
    for i, pet in enumerate(raw):
        entry = companion_entry(pet, i)
        if entry is not None:
            out.append(entry)
    try:
        known = set(role_names().get("roles") or [])
    except Exception:                                  # noqa: BLE001
        known = set()
    if known:
        for c in out:
            c["role_known"] = c["creature"] in known
    note = None
    if not raw:
        note = "这个存档里还没有同伴（Pets 为空）"
    elif not out:
        note = "Pets 里有条目但都是空槽"
    return {"path": p, "count": len(out), "creatures": out, "note": note,
            "preview": "3D 预览需要生物生成器（T8 第二阶段，未实现）；这里先给描述符与种子"}


# ---------------------------------------------------------------- 能力：能不能离线画生物

_RIGS_CACHE: dict | None = None


def scan_exe_symbols(limit: int = 8) -> dict:
    """在 `NMS.exe` 的反射字符串里找"生物生成器"入口（T8 第二阶段的探路）。

    实测（本机 2026-11-18，89,540,680 B 的 NMS.exe）能搜到：
      · `cGcPlanetGenerator::GenerateCreatureRoles(cGcPlanetData&, unsigned __int64 const&)`
        —— 行星生成器里"决定这颗行星有哪些生物角色"的函数（与 `systemgen` 调的那族函数同级）；
      · `Metadata/Simulation/Ecosystem/CreatureDataTable.mbin` —— 生物角色数据表；
      · `cGcCreatureData` / `cGcEcosystemCreatureData` / `eCreatureType` / `eCreatureRole` 等类型。
    → 说明"角色的生成"可以像行星那样外部跑；但"外观（部件网格）"还需要生物描述符解析，
      那是另一条链，尚未定位。
    """
    out = {"exe": None, "found": {}, "note": ""}
    try:
        import re
        from .core import settings
        gd = settings.current().game_dir or os.environ.get("NMS_DIR") or ""
        exe = os.path.join(gd, "Binaries", "NMS.exe") if gd else ""
        if not exe or not os.path.exists(exe):
            out["note"] = "找不到 NMS.exe"
            return out
        out["exe"] = exe
        blob = open(exe, "rb").read()
        strs = [s.decode("ascii", "replace") for s in re.findall(rb"[ -~]{8,}", blob)]
        wanted = {
            "GenerateCreatureRoles": "cGcPlanetGenerator::GenerateCreatureRoles（决定行星上刷什么生物）",
            "CreatureDataTable.mbin": "Metadata/Simulation/Ecosystem/CreatureDataTable.mbin（生物角色表）",
            "cGcCreatureData": "生物数据类",
            "cGcEcosystemCreatureData": "生态生物数据类",
            "eCreatureRole": "生物角色枚举",
        }
        for key, desc in wanted.items():
            hits = [s for s in strs if key in s]
            out["found"][key] = {"hit": bool(hits), "count": len(hits), "desc": desc,
                                 "sample": hits[0][:200] if hits else ""}
        out["note"] = ("角色生成可外部化（有函数与数据表）；外观网格仍需生物描述符解析链，未定位"
                       if out["found"]["GenerateCreatureRoles"]["hit"] else "未在反射里找到生成函数")
    except Exception as e:                             # noqa: BLE001
        out["note"] = f"扫描失败：{type(e).__name__}: {e}"
    return out


def capabilities(deep: bool = False) -> dict:
    """生物 3D 的可行性盘点（T8 spike 的结论固化在这里，别让界面画饼）。

    实测（本地 2026-11-18）：
      · `NMSARC.Precache.pak` 里有 **287 个** `.descriptor.mbin`（77 个 rig 目录），
        每个 rig 的 descriptor 里带该 rig 的**部件词表**（如 antelope：`_BODY_DEER/_BODY_FAT/_HEAD_DEER`）；
      · 每个 rig 的几何在 `NMSARC.MeshPlanetCREATURES.pak`（661 条 `<rig>/<mesh>.geometry.mbin.pc`），
        贴图在 `NMSARC.TexCreature*` 系列包里；
      · **但**存档里同伴的描述符用的是另一套词（`_BODY_PLANT`/`_SHAPE_XRARE`/`_HEAD_PLANT1`/`_MESH_PLANT`），
        在这些静态 rig descriptor 里**找不到** —— 它们是运行时生物生成器的产物。
    → 所以"按种子画同伴 3D"必须先拿到生物生成器（等同行星的 `systemgen`），属 T8 第二阶段。
    """
    global _RIGS_CACHE
    if _RIGS_CACHE is not None:
        return _RIGS_CACHE
    out = {"descriptors": 0, "rigs": [], "geometry_pak": False, "texture_paks": 0,
           "preview_possible": False,
           "reason": "同伴描述符（_BODY_PLANT 等）不在静态 rig descriptor 里，需要运行时生物生成器",
           "spike": "见 handbook/06 T8：descriptor 可解析（正向），但词表不同源（负向）"}
    try:
        from .core import settings
        gd = settings.current().game_dir or os.environ.get("NMS_DIR") or ""
        pcbanks = os.path.join(gd, "GAMEDATA", "PCBANKS") if gd else ""
        if not pcbanks or not os.path.isdir(pcbanks):
            out["reason"] = "没有游戏目录（PCBANKS 不可读）"
            _RIGS_CACHE = out
            return out
        from hgpaktool import HGPAKFile
        pre = os.path.join(pcbanks, "NMSARC.Precache.pak")
        names = []
        if os.path.exists(pre):
            with HGPAKFile(pre) as f:
                names = [h[0] for h in f.get_hashes() if isinstance(h, tuple)]
        desc = [n for n in names if n.lower().endswith(".descriptor.mbin") and "creature" in n.lower()]
        rigs = sorted({n.split("/")[4] for n in desc if len(n.split("/")) > 5 and n.split("/")[4].endswith("rig")})
        if not rigs:                                   # 目录层级不稳定时退一步：取所有含 rig 的段
            rigs = sorted({seg for n in desc for seg in n.split("/") if seg.endswith("rig")})
        out["descriptors"] = len(desc)
        out["rigs"] = rigs
        out["geometry_pak"] = os.path.exists(os.path.join(pcbanks, "NMSARC.MeshPlanetCREATURES.pak"))
        out["texture_paks"] = len([p for p in os.listdir(pcbanks)
                                   if p.startswith("NMSARC.TexCreature") and p.endswith(".pak")])
    except Exception as e:                             # noqa: BLE001
        out["reason"] = f"盘点失败：{type(e).__name__}: {e}"
    if deep:
        out["generator"] = scan_exe_symbols()
        rn = role_names()
        out["role_table"] = {"file": rn["file"], "bytes": rn["bytes"],
                            "count": rn["count"], "sample": rn["roles"][:24], "note": rn["note"]}
        rt = role_table()
        out["role_table"]["structure"] = {k: rt.get(k) for k in
                                         ("class", "layout_matches", "entries", "entry_size", "note")}
    _RIGS_CACHE = out
    return out


# ---------------------------------------------------------------- 生物角色表（T8-3）

_ROLES_CACHE: dict | None = None


def role_names(limit: int = 400) -> dict:
    """从 `Metadata/Simulation/Ecosystem/CreatureDataTable.mbin` 里读出**生物角色名**（启发式）。

    实测（本机 2026-11-18）：该 MBIN 258,712 B、版本 `0xCE4`，字符串表 1962 条，里面是
    `DEFAULT / FISH / SWIMCOW / SWIMRODENT / JELLYFISH / CRAB / SEASNAKE / SHARK / BIRD /
    FLYINGSNAKE / FLYINGLIZARD / BUTTERFLY …` 这类**角色名**。

    注意：字段名是哈希编码的（文件里没有 `GcCreatureData` / `Filename` 这类明文），
    所以这张表只能"按字符串表取出角色名"，要拿**字段结构**得实现通用 MBIN 字段读取器 +
    反射类名映射（工作量是另一个专题，没做）。
    """
    global _ROLES_CACHE
    if _ROLES_CACHE is not None:
        return _ROLES_CACHE
    out = {"file": None, "bytes": 0, "roles": [], "count": 0,
           "note": "字段名哈希编码，未实现通用 MBIN 字段读取器（T8-3 后续）"}
    try:
        import re
        from .core import paths
        paths.ensure_shipwright_importable()
        from nms_save import gamefiles
        dest = os.path.join(str(paths.cache_dir()), "creaturedata")
        os.makedirs(dest, exist_ok=True)
        gamefiles.extract(dest, ["*/Ecosystem/CreatureDataTable.mbin"],
                          "NMSARC.globals.pak", keep_dirs=True)
        hit = None
        for r, _d, fs in os.walk(dest):
            for f in fs:
                if f.lower().endswith("creaturedatatable.mbin"):
                    hit = os.path.join(r, f)
        if not hit:
            out["note"] = "没抽到 CreatureDataTable.mbin"
            _ROLES_CACHE = out
            return out
        blob = open(hit, "rb").read()
        out["file"] = hit
        out["bytes"] = len(blob)
        toks = [t.decode("ascii", "replace") for t in re.findall(rb"[A-Z][A-Z0-9_]{2,19}", blob)]
        seen, roles = set(), []
        for t in toks:
            if t in seen or t in ("DEFAULT", "MBIN", "PC"):
                continue
            seen.add(t)
            roles.append(t)
        out["roles"] = roles[:limit]
        out["count"] = len(roles)
    except Exception as e:                             # noqa: BLE001
        out["note"] = f"读取失败：{type(e).__name__}: {e}"
    _ROLES_CACHE = out
    return out


# ---------------------------------------------------------------- 角色表结构（T8-3 续）

_ROLE_TABLE_CACHE: dict | None = None


def role_table() -> dict:
    """`CreatureDataTable.mbin` 的**结构级**解析结果（不猜字段语义）。

    实测（本机 2026-11-18）：
      · 文件 258,712 B，头 `0xCCCCCCCC` ×2 / ver `0xCE4` / name_hash `0x58f2caec` / guid `0x37d55099b13b9f9c`；
      · 用 `NMS.exe` 反射反查：该 hash 对应 **`cGcCreatureDataTable`**，`matches=True`，只有 1 个字段 `Table`；
      · `Table` 的元素是 **`cGcCreatureData`（208 B / 29 个字段）**；
      · 列表头在 `0x20`：`i64 rel=16` → 数据 `0x30`，`i32 count=86`，即 **86 条 × 208 B = 0x4610**，与文件里下一个结构正好接上。
    仍未解：条目里是**数值 ID（TkID 哈希）**，角色名在另一张名字表里 —— 要把 ID 映射回名字，
    需要类型系统与名字表索引，属 T8-3 的下一步。
    """
    global _ROLE_TABLE_CACHE
    if _ROLE_TABLE_CACHE is not None:
        return _ROLE_TABLE_CACHE
    out = {"class": None, "layout_matches": False, "entries": 0, "entry_size": 0,
           "fields": [], "note": ""}
    try:
        import struct
        from .core import paths
        paths.ensure_shipwright_importable()
        rn = role_names()
        if not rn.get("file"):
            out["note"] = "角色表文件不可用"
            _ROLE_TABLE_CACHE = out
            return out
        blob = open(rn["file"], "rb").read()
        from nms_save import gamemeta
        meta = gamemeta.exe_meta()
        name_hash, guid = struct.unpack_from("<I", blob, 0x0C)[0], struct.unpack_from("<Q", blob, 0x10)[0]
        out["name_hash"] = name_hash
        out["guid"] = guid
        lay = meta.layout("cGcCreatureDataTable")
        out["layout_matches"] = lay.matches(blob)
        out["class"] = lay.name
        out["fields"] = list(lay.fields)
        rel, cnt = struct.unpack_from("<qi", blob, 0x20)
        data = 0x20 + rel
        entry = meta.element(lay, "Table")
        out["entries"] = cnt
        out["entry_size"] = entry.size
        out["data_at"] = data
        out["end_at"] = data + cnt * entry.size
        # 条目解析：`Id` 是 16 字节定长 ASCII（实测 "FISH"/"FISHFLOCK"/"SWIMCOW"…），不是哈希！
        items = []
        for i in range(min(cnt, 512)):
            off = data + i * entry.size
            raw = blob[off:off + entry.size]
            name = raw[48:64].split(b"\0", 1)[0].decode("ascii", "replace")
            items.append({
                "index": i,
                "id": name,
                "force_type": struct.unpack_from("<i", raw, 144)[0] if len(raw) >= 148 else None,
                "real_type": struct.unpack_from("<i", raw, 196)[0] if len(raw) >= 200 else None,
                "eco_system": bool(raw[202]) if len(raw) >= 203 else None,
                "can_be_female": bool(raw[200]) if len(raw) >= 201 else None,
                "min_scale": struct.unpack_from("<f", raw, 168)[0] if len(raw) >= 172 else None,
                "max_scale": struct.unpack_from("<f", raw, 164)[0] if len(raw) >= 168 else None,
                # 192 处按 float 读出来是 2.8e-45 这类垃圾值 → 实际是整数（未确认语义，标 raw）
                "rarity_raw": struct.unpack_from("<i", raw, 192)[0] if len(raw) >= 196 else None,
                "forced_only": bool(raw[203]) if len(raw) >= 204 else None,
            })
        out["items"] = items
        out["names"] = [x["id"] for x in items if x["id"]]
        out["note"] = (f"已解析 {len(items)} 条角色条目；`Id` 是 16 字节定长 ASCII（实测 FISH/FISHFLOCK/…），"
                       "不是哈希——角色名可直接读出。`min/max_scale` 合理；`rarity_raw` 按 int 读（按 float 是垃圾值，"
                       "语义未确认）。`Data`（+0，16 B）实测是 TkDynamicArray 头：offset(u32) + pad + count(u32) + "
                       "`0xAAAAAA01` 魔数；元素类型在反射里没有类布局（classptr=0），所以外观仍未解——"
                       "但拿到了具体线索：entry0 的 Data 在 0x45e0、count=2、下一条目在 0x4758（跨度 0x178=376 B，"
                       "即约 188 B/元素），后续可按这个步长反推元素结构。")
        out["fields"] = [{"name": k, "offset": v["offset"], "size": v["size"], "type": v["type"]}
                         for k, v in entry.fields.items()][:29]
    except Exception as e:                             # noqa: BLE001
        out["note"] = f"结构解析失败：{type(e).__name__}: {e}"
    _ROLE_TABLE_CACHE = out
    return out
