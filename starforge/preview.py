"""预览：L0 部件图 / L1 真 3D（读你自己的游戏 pak）/ L2 游戏内。

降级规则（手册 §2.6）：
  有游戏目录且能解出几何 → L1；否则 L0，并在响应里写明原因，绝不静默降级。
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from .core import log, paths, settings, strings
import numpy as np

from . import paint as paint_mod, render, tex as tex_mod
from . import parts as parts_mod
from .data.shipref import PROC_MODELS, ShipRef
from . import gltf

log = log.get("preview")


def level() -> str:
    from .system import _has_exe
    s = settings.current()
    if not s.game_dir:
        return "L0"
    banks = os.path.join(s.game_dir, "GAMEDATA", "PCBANKS")
    return "L1" if (_has_exe(s.game_dir) and os.path.isdir(banks)) else "L0"


# 缓存代次：旧缓存只有平涂材质，改成贴图版本后必须重新生成，不能继续命中旧 glb。
_CACHE_SCHEMA = "glb-tex-v1"
_TEXTURE_MAX_SIDE = 1024      # 预览用贴图上限，避免整艘船的 PNG 把 glb 撑到几十 MB


def _cache_key(ref: ShipRef, level_: str) -> str:
    raw = json.dumps([_CACHE_SCHEMA, level_, ref.type, ref.seed, ref.parts, ref.model],
                     sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _out_dir() -> str:
    d = paths.cache_dir() / "preview"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def ensure_texture_paths() -> None:
    """修一下 Windows 路径分隔符在 Linux 上的上游兼容问题。

    Shipwright 的 ``shiptex.maps_for`` 只按 ``/`` 拆材质路径，而场景文件里的材质名带
    ``\\``。在 Windows 上碰巧能打开，在 Linux 上材质文件找不到，几何组就丢掉贴图名。
    这里只把传入路径统一成 ``/``，不改变任何贴图/UV 数据。
    """
    try:
        paths.ensure_shipwright_importable()
        from nms_procgen import shiptex
    except Exception:                                      # noqa: BLE001 - 没有上游就保持平涂
        return
    orig = getattr(shiptex, "maps_for", None)
    if orig is None or getattr(orig, "_starforge_path_safe", False):
        return

    def maps_for(material):
        return orig(material.replace("\\", "/") if isinstance(material, str) else material)

    maps_for._starforge_path_safe = True                   # type: ignore[attr-defined]
    shiptex.maps_for = maps_for                            # type: ignore[assignment]


def _limit_texture(img: np.ndarray, max_side: int = _TEXTURE_MAX_SIDE) -> np.ndarray:
    """最近邻缩到 max_side 以内；只用于预览，不改 UV。"""
    h, w = img.shape[:2]
    side = max(h, w)
    if side <= max_side:
        return img
    scale = max_side / float(side)
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    ys = np.minimum((np.arange(nh) * h // nh), h - 1)
    xs = np.minimum((np.arange(nw) * w // nw), w - 1)
    return np.ascontiguousarray(img[ys][:, xs])


def _textures_for(groups: dict) -> dict[str, np.ndarray]:
    """{tex: RGBA}；能解码几张算几张，单张失败只让那一组退回平涂。"""
    ensure_texture_paths()
    out: dict[str, np.ndarray] = {}
    for key in groups:
        tex = key[1] if isinstance(key, tuple) and len(key) > 1 else ""
        if not tex or tex in out:
            continue
        try:
            out[tex] = _limit_texture(tex_mod.rgba(tex))
        except Exception as e:                             # noqa: BLE001
            log.debug("贴图跳过 %s：%s", tex, e)
    return out


def part_icons(ship: str, parts: list[str] | None) -> list[dict]:
    """L0 用的部件图清单（直接由游戏几何渲染，不依赖 Gagarin 图标）。"""
    try:
        tree = parts_mod.tree(ship)
        group_of = {o["part"].upper(): g["group"] for g in tree for o in g.get("options") or []}
    except Exception:                                      # noqa: BLE001
        group_of = {}
    return [{"part": p, "groups": [group_of[p.upper()]] if p.upper() in group_of else [],
             "icon": f"/api/part-thumb/{ship}/{p}.png"} for p in (parts or [])]


def build(ref: ShipRef, want_glb: bool = True) -> dict:
    """返回预览描述；L1 时顺带产出 glb 文件（缓存）。"""
    ref = ref.normalized()
    if not ref.can_preview:
        return {"key": "-", "level": "L0", "type": ref.type, "type_label": ref.type_label,
                "seed": ref.seed, "parts": ref.parts, "glb": None, "verts": 0, "tris": 0,
                "degraded": True, "can_preview": False,
                "reason": ("这是固定模型（如护卫舰/复古拦截机），外观不由种子决定，无法生成 3D。"
                           if not ref.procedural else "种子为 0 或类型不支持，无法生成 3D。"),
                "part_icons": part_icons(ref.type, ref.parts)}
    lvl = level()
    key = _cache_key(ref, lvl)
    glb_path = os.path.join(_out_dir(), f"{key}.glb")
    info = {"key": key, "level": lvl, "type": ref.type, "type_label": ref.type_label,
            "seed": ref.seed, "can_preview": True,
            "parts": ref.parts, "glb": None, "verts": 0, "tris": 0,
            "degraded": lvl == "L0", "reason": "" if lvl == "L1" else strings.PREVIEW_L0}

    if lvl == "L0":
        info["part_icons"] = part_icons(ref.type, ref.parts)
        info["gallery"] = [i["icon"] for i in info["part_icons"] if i["icon"]]
        return info

    if want_glb and os.path.exists(glb_path):
        st = os.stat(glb_path)
        info.update(glb=f"/api/model/{ref.type}/{ref.seed}.glb",
                    bytes=st.st_size, cached=True, built_at=int(st.st_mtime))
        return info

    try:
        colours = paint_mod.look(ref.seed, ref.type)
        info["colours"] = {k: paint_mod.hexcol(v) for k, v in colours.items()}
        paths.ensure_shipwright_importable()
        ensure_texture_paths()
        from nms_procgen import model3d
        t0 = time.time()
        model = model3d.ship_model(ref.seed, ref.type, ref.parts, True, False)
        verts = sum(len(g[0]) for g in model["groups"].values())
        tris = sum(len(g[3]) // 3 for g in model["groups"].values())
        if want_glb:
            blob = model3d.pack(model)
            header, groups = gltf.parse_pack(blob)
            textures = _textures_for(groups)
            data = gltf.build_glb(header, groups, colours=colours,
                                  name=f"{ref.type}_{ref.seed}", textures=textures)
            with open(glb_path + ".part", "wb") as f:
                f.write(data)
            os.replace(glb_path + ".part", glb_path)
            info.update(bytes=len(data), textures=len(textures))
        info.update(verts=verts, tris=tris, seconds=round(time.time() - t0, 2), cached=False,
                    glb=f"/api/model/{ref.type}/{ref.seed}.glb" if want_glb else None,
                    posable=bool(model.get("posable")), degraded=False, reason="")
        info.setdefault("textures", 0)
        log.info("L1 预览 %s %s：%d 顶点 / %d 三角 / %.1fs", ref.type, ref.seed, verts, tris,
                 time.time() - t0)
    except Exception as e:                          # noqa: BLE001 - 降级到 L0，但要说原因
        info.update(level="L0", degraded=True,
                    reason=f"3D 构建失败（{type(e).__name__}: {e}），已降级为部件图",
                    part_icons=part_icons(ref.type, ref.parts))
        log.warning("L1 预览失败，降级 L0：%s", e)
    return info


def part_model(ship: str, part: str) -> dict:
    """只取一个部件的几何（用于部件级 3D 预览）。"""
    paths.ensure_shipwright_importable()
    from nms_procgen import model3d
    # 上游会把"固定件"（座舱盖/起落架/武器）一起返回；用一个不存在的部件名求出固定件集合，
    # 再做差集，才是这个部件本身。
    base = model3d._picked_meshes(ship, {"__SF_NONE__"}, None, frozenset())
    meshes = model3d._picked_meshes(ship, {part.upper()}, None, frozenset())
    keys = {(g, h, w.tobytes()) for g, h, w, *_ in base}
    own = [m for m in meshes if (m[0], m[1], m[2].tobytes()) not in keys]
    if not own:
        raise ValueError(f"这艘船没有部件 {part}（可能属于别的船型）")
    meshes = own
    geos = model3d._geometry(sorted({g for g, *_ in meshes if g}))
    groups = {}
    for g, h, world, cls, posed, first, tex in meshes:
        m = geos.get(g, {}).get(h)
        if m is None:
            continue
        pos = m[0] @ world[:3, :3].T + world[:3, 3]
        nrm = m[1] @ world[:3, :3].T
        key = (cls, tex)
        groups.setdefault(key, ([], [], [], []))
        groups[key][0].append(pos.astype(np.float32))
        groups[key][1].append(nrm.astype(np.float32))
        groups[key][2].append(m[2])
        groups[key][3].append(m[3])
    out = {}
    for key, (p_, n_, uv_, ix_) in groups.items():
        out[key] = (np.concatenate(p_), np.concatenate(n_), np.concatenate(uv_), np.concatenate(ix_))
    allp = np.concatenate([g[0] for g in out.values()])
    return {"groups": out, "bounds": (allp.min(0).tolist(), allp.max(0).tolist())}


def part_png(ship: str, part: str, size: int = 200) -> bytes:
    """部件 3D 缩略图（光栅化，缓存）。"""
    import hashlib
    key = hashlib.sha1(f"part|{ship}|{part.upper()}|{size}".encode()).hexdigest()[:20]
    def build() -> bytes:
        m = part_model(ship, part)
        img = render.rasterize(m["groups"], ("iso",), (size, size), ss=2, ambient=0.32, fill=0.86)
        return render.png_bytes(img)
    return render._cache_png(key, build)


def glb_for(ref: ShipRef) -> str:
    """确保 glb 存在并返回路径（供 /api/model 用）。"""
    info = build(ref, want_glb=True)
    if info.get("level") != "L1" or not info.get("glb"):
        raise FileNotFoundError(info.get("reason") or "当前没有 3D 资源")
    path = os.path.join(_out_dir(), f"{info['key']}.glb")
    if not os.path.exists(path):
        raise FileNotFoundError("glb 未生成")
    return path
