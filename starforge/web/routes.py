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
    """船型与部件统计。来源可以是 Gagarin 目录，也可以是从游戏资源推导。"""
    from .. import parts as parts_mod
    src = parts_mod.source()
    ships, failed = {}, {}
    for t in parts_mod.SHIPS:
        try:
            s = parts_mod.summary(t)
            ships[t] = {"groups": s["groups"], "parts": s["parts"]}
        except Exception as e:                             # noqa: BLE001
            failed[t] = str(e)
    if not ships:
        raise NotFound("取不到任何船型的部件表：请确认游戏目录，或安装 Gagarin 的 GAMEDATA")
    payload = {"source": src, "ships": ships,
               "note": {"gagarin": "来自 Gagarin 目录（带权重与缩略图）",
                        "game": "从游戏资源推导（无权重/缩略图，需游戏目录）"}.get(src, "")}
    if failed:
        payload["failed"] = failed
    return ok(**payload)


@bp.get("/catalog/<ship>")
def api_catalog_ship(ship: str):
    from .. import parts as parts_mod
    try:
        tree = parts_mod.tree(ship)
    except ValueError as e:
        raise NotFound(str(e))
    return ok(ship=ship, source=parts_mod.source(), groups=tree)


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
    """同型换种子写回存档（F05）。写开关关闭 -> 403；缺确认 -> 400；跨型 -> 400。"""
    from ..data.shipref import ShipRef
    from ..save import writer
    settings.require_write()                       # 闸门最先：未开启就 403，不泄露任何路径信息
    body = request.get_json(silent=True) or {}
    if not body.get("confirm"):
        raise BadRequest("缺少 confirm=true（写操作必须二次确认）")
    path = body.get("path") or str(library.resolve(None))
    src = ShipRef(type=(body.get("type") or ""), seed=(body.get("seed") or ""),
                  parts=body.get("parts") or None, source="search")
    return ok(**writer.apply_seed(path, int(body.get("slot", -1)), src, confirm=True))


@bp.get("/saves/backups")
def api_backups():
    from ..save import writer
    path = request.args.get("path") or str(library.resolve(None))
    return ok(path=path, backups=writer.backups(path))


@bp.post("/saves/restore")
def api_restore():
    from ..save import writer
    body = request.get_json(silent=True) or {}
    path = body.get("path") or str(library.resolve(None))
    return ok(**writer.restore(path, body.get("backup") or "", confirm=bool(body.get("confirm"))))


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


# ---------------------------------------------------------------- 星系 / 星球（M4）

@bp.get("/capabilities")
def api_capabilities():
    from .. import preview, system
    return ok(preview_level=preview.level(), system=system.capabilities(),
              write_enabled=settings.current().write_enabled)


@bp.get("/system")
def api_system():
    from .. import system
    ua = request.args.get("ua")
    glyphs = request.args.get("glyphs")
    save = request.args.get("save")
    try:
        if glyphs:
            ua_val = __import__("nms_procgen.locate", fromlist=["x"]).parse_address(glyphs)
        elif ua:
            ua_val = int(ua, 16) if str(ua).lower().startswith("0x") else int(ua)
        else:
            ua_val = None
        return ok(**system.system(ua_val, planets=request.args.get("planets") != "0", save_path=save))
    except Exception as e:                     # noqa: BLE001
        raise BadRequest(f"{type(e).__name__}: {e}")


@bp.post("/system/scan")
def api_system_scan():
    from .. import jobs, system
    body = request.get_json(silent=True) or {}
    if not system.available():
        raise __import__("starforge.core.errors", fromlist=["x"]).GameFilesMissing(
            "没有检测到游戏目录：扇扫需要 NMS.exe 与 PCBANKS")
    center = body.get("center")
    ua = None
    if center:
        try:
            ua = int(str(center), 16) if str(center).lower().startswith("0x") else None
            if ua is None:
                from nms_procgen import locate
                ua = locate.parse_address(str(center))
        except Exception as e:                 # noqa: BLE001
            raise BadRequest(f"无法解析圆心地址：{e}")
    job = jobs.REGISTRY.create("system_scan")
    params = dict(center_ua=ua, radius=int(body.get("radius") or 0),
                  systems_per_region=int(body.get("systems") or 200),
                  filters=body.get("filters") or {}, limit=int(body.get("limit") or 40),
                  save_path=body.get("save"))
    job.progress.update({k: v for k, v in params.items() if k != "save_path"})
    jobs.run_in_thread(job, lambda j: system.scan(job=j, **params))
    return ok(job_id=job.id, params={k: v for k, v in params.items() if k != "save_path"})


# ---------------------------------------------------------------- 服务端缩略图

@bp.get("/thumb/<ship>/<seed>.png")
def api_thumb(ship: str, seed: str):
    from .. import preview, render
    parts = [p for p in (request.args.get("parts") or "").split(",") if p]
    views = tuple(v for v in (request.args.get("views") or "iso").split(",") if v in render.VIEWS)
    size = max(160, min(int(request.args.get("size") or 420), 900))
    try:
        from .. import paint as paint_mod
        cols = paint_mod.look(seed, ship) if request.args.get("paint", "1") != "0" else None
        data = render.ship_png(ship, seed, parts or None, views or ("iso",), (size, size), colours=cols)
    except Exception as e:                     # noqa: BLE001 - 没有游戏数据时退 L0 部件图
        from ..glyphs import panel_png
        raise BadRequest(f"无法渲染：{type(e).__name__}: {e}")
    return Response(data, mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------- 设置 / 诊断

@bp.get("/settings")
def api_settings_get():
    s = settings.current()
    from .. import preview, system
    return ok(settings={"write_enabled": s.write_enabled, "confirm_writes": s.confirm_writes,
                        "saves_dir": s.saves_dir, "gamedata_dir": s.gamedata_dir,
                        "game_dir": s.game_dir, "backup_keep": s.backup_keep},
              resolved={"saves_dir": str(s.saves_dir_resolved() or ""),
                        "gamedata_dir": str(s.gamedata_resolved() or "")},
              preview_level=preview.level(), system_available=system.available())


@bp.post("/settings")
def api_settings_set():
    body = request.get_json(silent=True) or {}
    allowed = {k: body[k] for k in ("write_enabled", "confirm_writes", "saves_dir",
                                    "gamedata_dir", "game_dir", "backup_keep") if k in body}
    s = settings.update(**allowed)
    return ok(settings={"write_enabled": s.write_enabled, "saves_dir": s.saves_dir,
                        "gamedata_dir": s.gamedata_dir, "game_dir": s.game_dir})


@bp.get("/autodetect")
def api_autodetect():
    """自动发现游戏/存档/数据目录（只填空项）。?apply=0 只看不写。"""
    apply = request.args.get("apply", "1") not in ("0", "false", "no")
    return ok(**settings.autodetect(apply=apply))


@bp.get("/diagnostics")
def api_diagnostics():
    from .. import preview, system
    from ..save import library
    out = {"version": __import__("starforge").__version__,
           "preview_level": preview.level(),
           "write_enabled": settings.current().write_enabled}
    try:
        out["shipwright"] = str(paths.shipwright_root())
    except Exception as e:                        # noqa: BLE001
        out["shipwright"] = f"缺失：{e}"
    gd = settings.current().gamedata_resolved()
    out["gamedata"] = str(gd) if gd else "未配置"
    if gd:
        try:
            cat = load_catalog(gd)
            out["catalog"] = cat.stats
        except Exception as e:                    # noqa: BLE001
            out["catalog"] = f"读取失败：{e}"
    try:
        out["saves"] = library.scan_dir()["dir"]
    except Exception as e:                        # noqa: BLE001
        out["saves"] = f"不可用：{e}"
    out["system"] = system.capabilities()
    return ok(**out)


# ---------------------------------------------------------------- 实时通道（M5）

@bp.get("/live/status")
def api_live_status():
    from ..live import writer
    return ok(**writer.status())


@bp.post("/live/template-mod")
def api_live_template_mod():
    """生成模板 Mod 到指定目录（默认写进缓存目录，供用户复制到 GAMEDATA/MODS）。"""
    from ..live import exml
    body = request.get_json(silent=True) or {}
    dest = body.get("dest") or str(paths.cache_dir())
    out = exml.write_mod(dest)
    return ok(**out, hint="把 starforge-templates 文件夹复制到 游戏目录/GAMEDATA/MODS/ 即可")


@bp.get("/live/probe")
def api_live_probe():
    """只读诊断：报告每种船型找到几个模板槽候选（不写任何内存）。"""
    from ..live import mem, writer
    if not mem.IS_WINDOWS:
        raise GameFilesMissing("实时通道仅支持 Windows", hint="存档写回与符文浮窗在其它平台可用")
    try:
        proc = mem.attach("NMS.exe")
    except mem.LiveUnsupported as e:
        raise WriteRefused(str(e))
    with proc:
        return ok(**writer.probe(proc))


@bp.post("/live/push")
def api_live_push():
    from ..live import mem, writer
    settings.require_write()                       # 仍受写开关约束
    body = request.get_json(silent=True) or {}
    if not body.get("confirm"):
        raise BadRequest("缺少 confirm=true（写入游戏内存必须二次确认）")
    type_, seed = body.get("type"), body.get("seed")
    if not type_ or not seed:
        raise BadRequest("需要 type 与 seed")
    if not mem.IS_WINDOWS:
        raise GameFilesMissing("实时通道仅支持 Windows（Linux/Proton 无法读写进程内存）",
                               hint="可以改用存档写回，或把游戏内符文浮窗当作替代")
    try:
        proc = mem.attach("NMS.exe")
    except mem.LiveUnsupported as e:
        raise WriteRefused(str(e))
    with proc:
        try:
            return ok(**writer.push(proc, str(type_), str(seed)))
        except writer.LocateError as e:
            raise WriteRefused(str(e))
