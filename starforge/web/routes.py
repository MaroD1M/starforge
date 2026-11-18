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

import time

from flask import Blueprint, Response, jsonify, request

from ..core import log, paths, settings, strings
from ..core.errors import BadRequest, GameFilesMissing, NotFound, WriteDisabled, WriteRefused
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
              data_ready=bool(gd), saves_ready=bool(saves),
              desktop=_desktop_info())


def _desktop_info() -> dict:
    """原生窗口能力（界面用它决定显示"桌面窗口"还是"浏览器模式"+原因）。"""
    try:
        from .. import desktop
        info = desktop.probe()
        info["mode"] = "desktop" if info.get("available") else "browser"
        info["fallback_reason"] = desktop.LAST_FALLBACK_REASON or ""
        return info
    except Exception as e:                        # noqa: BLE001
        return {"available": False, "mode": "browser", "reason": f"{type(e).__name__}: {e}"}


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
    from ..data.shipref import TYPE_LABELS
    payload = {"source": src, "ships": ships,
               "ship_labels": {t: TYPE_LABELS.get(t, t) for t in ships},
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
    except Exception as e:                        # noqa: BLE001 - 上游各种异常都别冒 500
        raise NotFound(f"取不到 {ship} 的部件表：{type(e).__name__}: {e}")
    from .. import zh as zh_mod
    for g in tree:
        g["label"] = zh_mod.group_label(g["group"])
        for o in g["options"]:
            o["label"] = zh_mod.part_label(o["part"])
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
    rows = []
    for s in ships:
        d = s.to_dict()
        d.update(type_label=s.type_label, can_preview=s.can_preview)
        rows.append(d)
    return ok(path=str(p), count=len(ships), ships=rows, warnings=warns)


@bp.get("/creatures/table")
def api_creature_table():
    """角色表结构级解析（表 → 86 条 cGcCreatureData；字段名来自 exe 反射）。"""
    from .. import creature
    return ok(**creature.role_table())


@bp.get("/creatures/roles")
def api_creature_roles():
    """生物角色名表（来自游戏内 CreatureDataTable.mbin 的字符串表，启发式提取）。"""
    from .. import creature
    r = creature.role_names()
    return ok(count=r["count"], roles=r["roles"], bytes=r["bytes"],
              file=r["file"], note=r["note"])


@bp.get("/creatures/capabilities")
def api_creature_caps():
    """生物 3D 的可行性盘点（T8 spike 结论），界面据此决定显示"暂不支持"还是预览。"""
    from .. import creature
    deep = request.args.get("deep") in ("1", "true", "yes")
    return ok(**creature.capabilities(deep=deep))


@bp.get("/creatures")
def api_creatures():
    """存档里的同伴（只读）。M8-lite：先给描述符与种子，3D 留到生物生成器之后。"""
    from .. import creature
    try:
        return ok(**creature.companions(request.args.get("path")))
    except Exception as e:                     # noqa: BLE001
        raise BadRequest(f"{type(e).__name__}: {e}")


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
    return ok(**writer.apply_seed(path, int(body.get("slot", -1)), src, confirm=True,
                                  copy=bool(body.get("copy"))))


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
    raw = body.get("glyphs") if body.get("glyphs") not in (None, "") else body.get("ua")
    if raw in (None, ""):
        raw = request.args.get("glyphs") or request.args.get("ua")
    if raw in (None, ""):
        raise BadRequest("需要 glyphs 或 ua")
    try:
        # 传 UA（int 或 0x…）时由 glyphs.digits_for 按位段重排成符文串，不要先 str() 成十进制
        payload = glyph_mod.panel_payload(raw if isinstance(raw, int) else str(raw))
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
    from .. import zh as zh_mod
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
        info = system.system(ua_val, planets=request.args.get("planets") != "0", save_path=save)
        info["race_zh"] = zh_mod.race_label(info.get("race"))
        for pl in info.get("planet_list") or []:
            pl["biome_zh"] = zh_mod.biome_label(pl.get("biome_name"))
            pl["sentinels_zh"] = zh_mod.sentinel_label(pl.get("sentinels"))
        for sh in info.get("ships") or []:
            sh["kind_zh"] = zh_mod.kind_label(sh.get("kind"))
            sh["type_label"] = zh_mod.zh(__import__("starforge.data.shipref", fromlist=["TYPE_LABELS"]).TYPE_LABELS,
                                         sh.get("type"), sh.get("type") or "")
        return ok(**info)
    except Exception as e:                     # noqa: BLE001
        raise BadRequest(f"{type(e).__name__}: {e}")


@bp.post("/locate")
def api_locate():
    """船种子 → 星系坐标 + 符文（并用生成器证实）。"""
    from .. import system
    body = request.get_json(silent=True) or {}
    seed = body.get("seed") or request.args.get("seed")
    if not seed:
        raise BadRequest("需要 seed（十六进制字符串或整数）")
    try:
        out = system.locate_seed(seed, save_path=body.get("save"),
                                 max_steps=int(body.get("max_steps") or 3000),
                                 limit=int(body.get("limit") or 6))
    except GameFilesMissing:
        raise
    except Exception as e:                      # noqa: BLE001
        raise BadRequest(f"{type(e).__name__}: {e}")
    return ok(**out)


@bp.post("/saves/class")
def api_apply_class():
    """改船级/属性（备份→原子写→读回→失败回滚）。"""
    from ..save import writer
    body = request.get_json(silent=True) or {}
    if not body.get("confirm"):
        raise BadRequest("写操作需要 confirm=true")
    path = body.get("path") or str(library.resolve(None))
    values = body.get("values") or None
    if values is not None and not isinstance(values, dict):
        raise BadRequest("values 必须是 {属性ID: 数值} 的对象")
    return ok(**writer.apply_class(path, int(body.get("slot", -1)),
                                   ship_class=body.get("ship_class") or "",
                                   values=values, best=bool(body.get("best")),
                                   confirm=True, copy=bool(body.get("copy"))))


@bp.get("/galaxy/export.csv")
def api_galaxy_export():
    """把索引里符合条件的星系导成 CSV（给 Excel/表格用）。"""
    import csv
    import io

    from .. import galaxy
    a = request.args
    filters = {}
    for k in ("biome", "sentinels", "race"):
        if a.get(k):
            filters[k] = a.get(k)
    if a.get("dissonant") is not None:
        filters["dissonant"] = a.get("dissonant") in ("1", "true", "yes")
    if a.get("min_planets"):
        filters["min_planets"] = int(a["min_planets"])
    if a.get("has_interceptor") in ("1", "true", "yes"):
        filters["has_interceptor"] = True
    st = galaxy.GalaxyStore()
    try:
        rows = st.query(filters, limit=int(a.get("limit") or 500))
    finally:
        st.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ua", "glyphs", "coords", "galaxy", "race", "planets", "dissonant",
                "interceptor", "planet_index", "biome", "sentinels", "weather"])
    for r in rows:
        for pl in (r.get("matched_planets") or [{}]):
            w.writerow([r.get("ua"), r.get("glyphs"), r.get("coords"), r.get("galaxy"),
                        r.get("race"), r.get("planets"), int(bool(r.get("dissonant"))),
                        r.get("interceptor") or "", pl.get("index", ""), pl.get("biome") or "",
                        pl.get("sentinels") or "", pl.get("weather") or ""])
    data = buf.getvalue()
    fn = "galaxy-%s.csv" % time.strftime("%Y%m%d-%H%M%S")
    return Response(data, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@bp.get("/galaxy/stats")
def api_galaxy_stats():
    from .. import galaxy
    st = galaxy.GalaxyStore()
    try:
        return ok(**st.stats())
    finally:
        st.close()


@bp.get("/galaxy/query")
def api_galaxy_query():
    """在已扫过的银河索引里按条件查（不需要游戏在跑）。"""
    from .. import galaxy
    a = request.args
    filters = {}
    for k in ("biome", "sentinels", "race"):
        if a.get(k):
            filters[k] = a.get(k)
    if a.get("dissonant") is not None:
        filters["dissonant"] = a.get("dissonant") in ("1", "true", "yes")
    for k in ("min_planets",):
        if a.get(k):
            filters[k] = int(a.get(k))
    if a.get("has_interceptor") in ("1", "true", "yes"):
        filters["has_interceptor"] = True
    st = galaxy.GalaxyStore()
    try:
        rows = st.query(filters, limit=int(a.get("limit") or 50))
        return ok(filters=filters, count=len(rows), rows=rows, store=st.stats())
    finally:
        st.close()


@bp.post("/galaxy/scan")
def api_galaxy_scan():
    """扫一片区域并**落库**（与 /system/scan 的区别：那个只返回命中，不留索引）。"""
    from .. import galaxy, jobs, system
    if not system.available():
        raise GameFilesMissing("没有检测到游戏目录：银河扫描需要 NMS.exe 与 PCBANKS")
    body = request.get_json(silent=True) or {}
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
    params = dict(center_ua=ua, radius=int(body.get("radius") or 0),
                  systems_per_region=int(body.get("systems") or 60),
                  filters=body.get("filters") or {}, limit=int(body.get("limit") or 40),
                  save_path=body.get("save"))
    job = jobs.REGISTRY.create("galaxy_scan")
    job.progress.update({k: v for k, v in params.items() if k != "save_path"})

    def work(j):
        return galaxy.scan(job=j, **params)

    jobs.run_in_thread(job, work)
    return ok(job_id=job.id, params={k: v for k, v in params.items() if k != "save_path"})


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
    def _scan(j):
        rows = system.scan(job=j, **params)
        from .. import zh as zh_mod
        for r in rows:
            r["biome_zh"] = zh_mod.biome_label(r.get("biome_name"))
            r["sentinels_zh"] = zh_mod.sentinel_label(r.get("sentinels"))
        return rows
    jobs.run_in_thread(job, _scan)
    return ok(job_id=job.id, params={k: v for k, v in params.items() if k != "save_path"})


# ---------------------------------------------------------------- 批量导出

@bp.post("/export")
def api_export():
    """把若干艘船导出成 zip（glb + png + manifest.json）。"""
    from .. import export
    body = request.get_json(silent=True) or {}
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise BadRequest("需要 items：每项至少含 type 与 seed")
    data, stats = export.export_zip(items, include_glb=body.get("glb", True),
                                    include_png=body.get("png", True),
                                    png_size=int(body.get("size") or 640))
    name = body.get("name") or "starforge-export"
    return Response(data, mimetype="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}.zip"',
                             "X-Export-Count": str(stats["exported"])})


# ---------------------------------------------------------------- 服务端缩略图

@bp.get("/part-thumb/<ship>/<part>.png")
def api_part_thumb(ship: str, part: str):
    """单个部件的 3D 缩略图（从游戏几何光栅化）。"""
    from .. import preview
    size = max(64, min(int(request.args.get("size") or 200), 420))
    from .. import render
    try:
        data = preview.part_png(ship, part, size)
    except Exception:                                       # noqa: BLE001
        # 该船没有这个部件 / 没有游戏文件：退回游戏内图标，再退回占位图（永远是 200）
        try:
            from ..data import load_icons
            ics = load_icons()
            data = ics.png(part, ship) or ics.png(part) or b""
        except Exception:                                   # noqa: BLE001
            data = b""
        if not data:
            data = render.placeholder_png(size)
    return Response(data, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@bp.get("/thumb/<ship>/<seed>.png")
def api_thumb(ship: str, seed: str):
    from .. import preview, render
    from ..data.shipref import PROC_MODELS
    parts = [p for p in (request.args.get("parts") or "").split(",") if p]
    views = tuple(v for v in (request.args.get("views") or "iso").split(",") if v in render.VIEWS)
    size = max(160, min(int(request.args.get("size") or 420), 900))
    if ship not in PROC_MODELS or int(str(seed), 16) == 0:
        return Response(render.placeholder_png(size), mimetype="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})
    try:
        from .. import paint as paint_mod
        cols = paint_mod.look(seed, ship) if request.args.get("paint", "1") != "0" else None
        data = render.ship_png(ship, seed, parts or None, views or ("iso",), (size, size), colours=cols)
    except Exception:                          # noqa: BLE001 - 没有游戏数据：给占位图，别让界面出现坏图
        data = render.placeholder_png(size)
    return Response(data, mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------- 设置 / 诊断

def _path_checks() -> dict:
    """设置页用：逐个路径判断是否真的可用（Windows 上大小写/斜杠都可能不一致）。"""
    import os
    s = settings.current()
    out = {}
    game = s.game_dir
    if game:
        exe = next((p for p in (os.path.join(game, "Binaries", "NMS.exe"),
                                os.path.join(game, "binaries", "nms.exe")) if os.path.exists(p)), None)
        banks = os.path.join(game, "GAMEDATA", "PCBANKS")
        out["game_dir"] = {"ok": bool(exe) and os.path.isdir(banks),
                           "detail": "找到 NMS.exe 与 PCBANKS" if exe and os.path.isdir(banks)
                           else "目录里没有 Binaries/NMS.exe 或 GAMEDATA/PCBANKS"}
    else:
        out["game_dir"] = {"ok": False, "detail": "未设置（3D 只能用部件图）"}
    sd = s.saves_dir_resolved()
    if sd:
        n = len(list(sd.glob("*.hg")))
        out["saves_dir"] = {"ok": n > 0, "detail": f"{n} 个 .hg 文件" if n else "目录里没有 .hg 存档"}
    else:
        out["saves_dir"] = {"ok": False, "detail": "未找到（可自动检测或手选）"}
    gd = s.gamedata_resolved()
    if gd:
        ok = os.path.exists(os.path.join(str(gd), "Gagarin", "ships", "catalog.txt"))
        out["gamedata_dir"] = {"ok": True, "detail": "含 Gagarin 目录数据" if ok
                               else "没有 Gagarin 数据，将改为从游戏资源推导部件树"}
    else:
        out["gamedata_dir"] = {"ok": True, "detail": "不设置也可以（从游戏资源推导）"}
    return out


@bp.get("/settings")
def api_settings_get():
    s = settings.current()
    from .. import preview, system
    return ok(settings={"write_enabled": s.write_enabled, "confirm_writes": s.confirm_writes,
                        "saves_dir": s.saves_dir, "gamedata_dir": s.gamedata_dir,
                        "game_dir": s.game_dir, "backup_keep": s.backup_keep},
              resolved={"saves_dir": str(s.saves_dir_resolved() or ""),
                        "gamedata_dir": str(s.gamedata_resolved() or "")},
              checks=_path_checks(),
              preview_level=preview.level(), system_available=system.available())


@bp.post("/settings")
def api_settings_set():
    body = request.get_json(silent=True) or {}
    allowed = {k: body[k] for k in ("write_enabled", "confirm_writes", "saves_dir",
                                    "gamedata_dir", "game_dir", "backup_keep") if k in body}
    s = settings.update(**allowed)
    return ok(settings={"write_enabled": s.write_enabled, "saves_dir": s.saves_dir,
                        "gamedata_dir": s.gamedata_dir, "game_dir": s.game_dir})


@bp.get("/textures/status")
def api_textures_status():
    """贴图可用性（材质描述符能否解析、能否解出一张图）。"""
    from .. import tex
    ship = request.args.get("ship") or "sentinel"
    return ok(ship=ship, **tex.status(ship))


@bp.get("/warm")
def api_warm():
    """预热状态；?start=1 时后台启动。"""
    from .. import warm
    if request.args.get("start") in ("1", "true", "yes"):
        return ok(**warm.start(background=True))
    return ok(**warm.status())


@bp.get("/desktop")
def api_desktop():
    """桌面窗口能力（界面用它决定是否显示"桌面窗口"徽标与提示）。"""
    from .. import desktop
    return ok(**desktop.probe())


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
