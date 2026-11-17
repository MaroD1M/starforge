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
from . import paint as paint_mod
from .data import load_catalog, load_icons
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


def _cache_key(ref: ShipRef, level_: str) -> str:
    raw = json.dumps([level_, ref.type, ref.seed, ref.parts, ref.model], sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _out_dir() -> str:
    d = paths.cache_dir() / "preview"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def part_icons(ship: str, parts: list[str] | None) -> list[dict]:
    """L0 用的部件图清单（每项带 URL 与所属插槽组）。"""
    cat = load_catalog()
    icons = load_icons()
    loc = {p.upper(): cat.locate(p) for p in (parts or [])}
    out = []
    for p in (parts or []):
        key = p.upper()
        groups = sorted({g for _t, g, _w in loc.get(key, [])})
        out.append({"part": p, "groups": groups,
                    "icon": f"/api/icons/{p}.png?ship={ship}" if icons.png(p, ship) else None})
    return out


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
        from nms_procgen import model3d
        t0 = time.time()
        model = model3d.ship_model(ref.seed, ref.type, ref.parts, True, False)
        verts = sum(len(g[0]) for g in model["groups"].values())
        tris = sum(len(g[3]) // 3 for g in model["groups"].values())
        if want_glb:
            blob = model3d.pack(model)
            header, groups = gltf.parse_pack(blob)
            data = gltf.build_glb(header, groups, colours=colours, name=f"{ref.type}_{ref.seed}")
            with open(glb_path + ".part", "wb") as f:
                f.write(data)
            os.replace(glb_path + ".part", glb_path)
            info.update(bytes=len(data))
        info.update(verts=verts, tris=tris, seconds=round(time.time() - t0, 2), cached=False,
                    glb=f"/api/model/{ref.type}/{ref.seed}.glb" if want_glb else None,
                    posable=bool(model.get("posable")), degraded=False, reason="")
        log.info("L1 预览 %s %s：%d 顶点 / %d 三角 / %.1fs", ref.type, ref.seed, verts, tris,
                 time.time() - t0)
    except Exception as e:                          # noqa: BLE001 - 降级到 L0，但要说原因
        info.update(level="L0", degraded=True,
                    reason=f"3D 构建失败（{type(e).__name__}: {e}），已降级为部件图",
                    part_icons=part_icons(ref.type, ref.parts))
        log.warning("L1 预览失败，降级 L0：%s", e)
    return info


def glb_for(ref: ShipRef) -> str:
    """确保 glb 存在并返回路径（供 /api/model 用）。"""
    info = build(ref, want_glb=True)
    if info.get("level") != "L1" or not info.get("glb"):
        raise FileNotFoundError(info.get("reason") or "当前没有 3D 资源")
    path = os.path.join(_out_dir(), f"{info['key']}.glb")
    if not os.path.exists(path):
        raise FileNotFoundError("glb 未生成")
    return path
