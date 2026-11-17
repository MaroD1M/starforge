"""JSON API（S0/S1 范围）。

GET  /api/health              能力与配置摘要
GET  /api/catalog             船型/组/部件统计
GET  /api/catalog/<ship>      某船型的插槽组与选项
GET  /api/icons/<part>.png    部件缩略图（?ship= 指定船型）
GET  /api/saves               扫描存档目录，逐个判定类型与可读性
GET  /api/ships               列出存档里的船（ShipRef 列表 + 警告）
POST /api/saves/apply         写回存档（S4 才实现；此网关先落地安全闸门）
"""
from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from ..core import log, paths, settings, strings
from ..core.errors import BadRequest, GameFilesMissing, NotFound, WriteDisabled
from ..data import load_catalog, load_icons
from ..save import library

log = log.get("api")
bp = Blueprint("api", __name__, url_prefix="/api")


def ok(**kw):
    return jsonify({"ok": True, **kw})


# ---------------------------------------------------------------- 能力


@bp.get("/health")
def health():
    s = settings.current()
    gd = s.gamedata_resolved()
    saves = s.saves_dir_resolved()
    game = s.game_dir
    level = "L1" if game else "L0"
    return ok(version=__import__("starforge").__version__,
              preview_level=level,
              preview_text=strings.PREVIEW_L1 if game else strings.PREVIEW_L0,
              gamedata=str(gd) if gd else "",
              saves_dir=str(saves) if saves else "",
              game_dir=game or "",
              write_enabled=s.write_enabled,
              shipwright=str(paths.shipwright_root()) if _has_shipwright() else "",
              data_ready=bool(gd), saves_ready=bool(saves))


def _has_shipwright() -> bool:
    try:
        paths.shipwright_root()
        return True
    except Exception:                                     # noqa: BLE001
        return False


# ---------------------------------------------------------------- 目录/图标


@bp.get("/catalog")
def api_catalog():
    gd = settings.current().gamedata_resolved()
    if not gd:
        raise NotFound(strings.ERR_NO_GAMEDATA)
    cat = load_catalog(gd)
    return ok(stats=cat.stats,
              open_scopes_at_eof=cat.opens_at_eof,
              ships={t: {"groups": len(v["groups"]),
                         "parts": sum(len(o) for o in v["groups"].values()),
                         "scene": v["scene"]} for t, v in cat.ships.items()},
              palettes=sorted(cat.palettes.keys()))


@bp.get("/catalog/<ship>")
def api_catalog_ship(ship: str):
    gd = settings.current().gamedata_resolved()
    if not gd:
        raise NotFound(strings.ERR_NO_GAMEDATA)
    cat = load_catalog(gd)
    if ship not in cat.ships:
        raise NotFound(f"没有这个船型：{ship}")
    grp = cat.groups_of(ship)
    return ok(ship=ship, scene=cat.ships[ship]["scene"],
              groups=[{"group": g, "options": [{"part": p, "weight": w} for p, w in opts]}
                      for g, opts in grp.items()])


@bp.get("/icons/<part>.png")
def api_icon(part: str):
    gd = settings.current().gamedata_resolved()
    if not gd:
        raise NotFound(strings.ERR_NO_GAMEDATA)
    ics = load_icons(gd)
    ship = request.args.get("ship") or None
    data = ics.png(part, ship)
    if not data:
        raise NotFound(f"没有这个部件的缩略图：{part}")
    return Response(data, mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------- 存档


@bp.get("/saves")
def api_saves():
    folder = request.args.get("dir")
    return ok(**library.scan_dir(folder))


@bp.get("/ships")
def api_ships():
    path = request.args.get("path")
    p = library.resolve(path)
    ships, warns = library.open_ships(p)
    return ok(path=str(p), count=len(ships),
              ships=[s.to_dict() for s in ships], warnings=warns)


@bp.post("/saves/apply")
def api_apply():
    """写回存档。S4 实现；现在只负责把安全闸门立起来。"""
    settings.require_write()                              # 未开启 -> 403 write_disabled
    body = request.get_json(silent=True) or {}
    if not body.get("confirm"):
        raise BadRequest("缺少 confirm=true（写操作必须二次确认）")
    raise NotImplementedError("写回存档将在 S4 实现")
