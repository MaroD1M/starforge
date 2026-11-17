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


# ---------------------------------------------------------------- 搜索 / 任务（M1）

def _query_from_request(data: dict):
    from ..search import SearchQuery
    return SearchQuery(ship=(data.get("ship") or "fighter"),
                       want=list(data.get("want") or []),
                       avoid=list(data.get("avoid") or []),
                       look=data.get("look") or None,
                       limit=int(data.get("limit") or 12),
                       max_seeds=int(data.get("max_seeds") or 50_000_000),
                       time_limit=float(data.get("time_limit") or 20),
                       workers=int(data.get("workers") or 1))


@bp.post("/search")
def api_search_start():
    from .. import jobs, search
    body = request.get_json(silent=True) or {}
    q = _query_from_request(body)
    try:
        search.validate(q)                       # 提前失败：400 而不是跑到一半才炸
    except search.QueryError as e:
        raise BadRequest(str(e))
    job = jobs.REGISTRY.create("search")
    job.progress.update(q.to_dict())

    def work(j):
        return search.run(q, job=j)

    jobs.run_in_thread(job, work)
    return ok(job_id=job.id, query=q.to_dict())


@bp.get("/search/estimate")
def api_search_estimate():
    from .. import search
    body = {k: request.args.get(k) for k in ("ship",)}
    want = [p for p in (request.args.get("want") or "").split(",") if p]
    avoid = [p for p in (request.args.get("avoid") or "").split(",") if p]
    q = _query_from_request({"ship": body["ship"], "want": want, "avoid": avoid})
    try:
        return ok(**search.explain(q))
    except search.QueryError as e:
        raise BadRequest(str(e))


@bp.get("/jobs")
def api_jobs():
    from .. import jobs
    return ok(jobs=[j.to_dict(include_result=False) for j in jobs.REGISTRY.all()])


@bp.get("/jobs/<job_id>")
def api_job(job_id: str):
    from .. import jobs
    job = jobs.REGISTRY.get(job_id) or (_ for _ in ()).throw(NotFound(f"没有这个任务：{job_id}"))
    return ok(**job.to_dict())


@bp.delete("/jobs/<job_id>")
def api_job_cancel(job_id: str):
    from .. import jobs
    job = jobs.REGISTRY.get(job_id)
    if not job:
        raise NotFound(f"没有这个任务：{job_id}")
    job.cancel()
    return ok(cancelled=True, id=job_id)


# ---------------------------------------------------------------- 预览（M2）

@bp.get("/preview/<ship>/<seed>")
def api_preview(ship: str, seed: str):
    from .. import preview
    from ..data.shipref import ShipRef
    parts = [p for p in (request.args.get("parts") or "").split(",") if p]
    ref = ShipRef(type=ship, seed=seed, parts=parts or None)
    try:
        return ok(**preview.build(ref, want_glb=request.args.get("glb") != "0"))
    except Exception as e:                            # noqa: BLE001
        raise BadRequest(f"{type(e).__name__}: {e}")


@bp.get("/model/<ship>/<seed>.glb")
def api_model(ship: str, seed: str):
    from .. import preview
    from ..data.shipref import ShipRef
    parts = [p for p in (request.args.get("parts") or "").split(",") if p]
    path = preview.glb_for(ShipRef(type=ship, seed=seed, parts=parts or None))
    return Response(open(path, "rb").read(), mimetype="model/gltf-binary",
                    headers={"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------- 符文（M4.5）

@bp.get("/glyphs/<name>.png")
def api_glyphs_png(name: str):
    from .. import glyphs as glyph_mod
    try:
        if len(name) == 1:
            data = glyph_mod.icon_png(name) or glyph_mod.panel_png(name, tile=160)
        else:
            data = glyph_mod.panel_png(name)
    except ValueError as e:
        raise BadRequest(str(e))
    return Response(data, mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})


@bp.post("/glyph-panel")
def api_glyph_panel():
    from .. import glyphs as glyph_mod
    body = request.get_json(silent=True) or {}
    text = body.get("glyphs") or body.get("ua") or request.args.get("glyphs")
    if not text:
        raise BadRequest("需要 glyphs 或 ua")
    try:
        payload = glyph_mod.panel_payload(str(text))
    except ValueError as e:
        raise BadRequest(str(e))
    payload.update(target=body.get("target"), pinned=bool(body.get("pinned")))
    return ok(**payload)
