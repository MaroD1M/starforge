"""应用服务层：UI 与 HTTP 共用的唯一用例入口。

原则：
  · 这里只做"编排"——参数校验、调用领域模块、把结果整理成可序列化的 dict；
  · 不在这一层碰 Qt、Flask、request、response；
  · 原生界面（``starforge.app``）和可选网页（``starforge.web``）都调用这里，
    避免换壳时把业务逻辑再写一遍。

P0 只覆盖高频用例；后续页面加功能时**先加服务方法，再加界面**。
"""
from __future__ import annotations

from typing import Any

from ..core import log, paths, settings, strings
from ..core.errors import BadRequest, NotFound

log = log.get("services")


def _ok(**kw: Any) -> dict:
    return {"ok": True, **kw}


def _labels(tree: list[dict]) -> list[dict]:
    from .. import zh

    for group in tree:
        group["label"] = zh.group_label(group["group"])
        for opt in group.get("options") or []:
            opt["label"] = zh.part_label(opt["part"])
    return tree


class Services:
    """一个无状态的服务门面；实例可以安全地在多个线程里调用。"""

    # ------------------------------------------------------------ 进程隔离

    @staticmethod
    def _internal(kind: str, payload: dict, timeout: float = 120.0) -> dict:
        """把 unicorn/systemgen 这类高风险原生调用放到独立进程。

        原因：Unicorn 在 Qt 线程里出现过原生 access violation；隔离后即使子进程崩，
        主界面也只显示错误，不会整个应用退出。
        """
        import json
        import os
        import subprocess
        import sys

        body = json.dumps(payload, ensure_ascii=False)
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "_internal", kind, "--payload", body]
        else:
            cmd = [sys.executable, "-m", "starforge", "_internal", kind, "--payload", body]
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=flags)
        out = (r.stdout or "").strip()
        data = None
        for line in reversed(out.splitlines()):
            try:
                data = json.loads(line)
                break
            except ValueError:
                continue
        if data is None:
            raise RuntimeError(f"内部任务没有返回 JSON（code={r.returncode}）：{(r.stderr or out)[-500:]}")
        if r.returncode != 0 or not data.get("ok", True):
            raise RuntimeError(data.get("error") or f"内部任务失败（code={r.returncode}）")
        return data

    # ------------------------------------------------------------ 健康/能力

    def health(self) -> dict:
        """原生窗口用的健康摘要（不依赖 WebView2）。"""
        s = settings.current()
        gd = s.gamedata_resolved()
        saves = s.saves_dir_resolved()
        game = s.game_dir or ""
        try:
            from .. import parts as parts_mod

            data_source = parts_mod.source()
            data_ready = data_source != "none"
        except Exception:                                   # noqa: BLE001
            data_source, data_ready = "none", False
        return _ok(
            version=__import__("starforge").__version__,
            platform="windows" if __import__("os").name == "nt" else __import__("sys").platform,
            preview_level="L1" if game else "L0",
            preview_text=strings.PREVIEW_L1 if game else strings.PREVIEW_L0,
            gamedata=str(gd) if gd else "",
            saves_dir=str(saves) if saves else "",
            game_dir=game,
            write_enabled=bool(s.write_enabled),
            data_ready=data_ready,
            data_source=data_source,
            saves_ready=bool(saves),
            live_available=self._live_available(),
        )

    @staticmethod
    def _live_available() -> bool:
        try:
            from ..live import mem

            return bool(mem.IS_WINDOWS)
        except Exception:                                   # noqa: BLE001
            return False

    def capabilities(self) -> dict:
        from .. import preview, system

        return _ok(preview_level=preview.level(), system=system.capabilities(),
                   write_enabled=settings.current().write_enabled,
                   live=self.live_status())

    # ------------------------------------------------------------ 设置

    def settings_snapshot(self) -> dict:
        s = settings.current()
        saves = s.saves_dir_resolved()
        gd = s.gamedata_resolved()
        return _ok(settings={
            "write_enabled": s.write_enabled,
            "confirm_writes": s.confirm_writes,
            "saves_dir": s.saves_dir,
            "gamedata_dir": s.gamedata_dir,
            "game_dir": s.game_dir,
            "backup_keep": s.backup_keep,
            "port": s.port,
            "theme": s.theme,
        }, resolved={
            "saves_dir": str(saves) if saves else "",
            "gamedata_dir": str(gd) if gd else "",
            "game_dir": s.game_dir or "",
        })

    def update_settings(self, **kw: Any) -> dict:
        settings.update(**kw)
        return self.settings_snapshot()

    def autodetect(self, apply: bool = True) -> dict:
        return settings.autodetect(apply=apply)

    # ------------------------------------------------------------ 数据目录

    def catalog(self) -> dict:
        from .. import parts as parts_mod
        from ..data.shipref import TYPE_LABELS

        source = parts_mod.source()
        ships: dict[str, dict] = {}
        failed: dict[str, str] = {}
        for t in parts_mod.SHIPS:
            try:
                s = parts_mod.summary(t)
                ships[t] = {"groups": s["groups"], "parts": s["parts"]}
            except Exception as e:                          # noqa: BLE001
                failed[t] = str(e)
        if not ships:
            raise NotFound("取不到任何船型的部件表：请确认游戏目录，或安装 Gagarin 的 GAMEDATA")
        note = {"gagarin": "来自 Gagarin 目录（带权重与缩略图）",
                "game": "从游戏资源推导（无权重/缩略图，需游戏目录）"}.get(source, "")
        payload = {"source": source, "ships": ships,
                   "ship_labels": {t: TYPE_LABELS.get(t, t) for t in ships}, "note": note}
        if failed:
            payload["failed"] = failed
        return _ok(**payload)

    def catalog_ship(self, ship: str) -> dict:
        from .. import parts as parts_mod

        try:
            tree = _labels(parts_mod.tree(ship))
        except ValueError as e:
            raise NotFound(str(e)) from e
        return _ok(ship=ship, source=parts_mod.source(), groups=tree)

    # ------------------------------------------------------------ 搜索

    @staticmethod
    def _query(payload: dict):
        from ..search import SearchQuery

        look = payload.get("look")
        if look is None and payload.get("look_on"):
            look = {"primary": payload.get("look_primary") or [0.95, 0.78, 0.10],
                    "tol": payload.get("look_tol", 0.18)}
            if payload.get("look_secondary_on"):
                look["secondary"] = payload.get("look_secondary") or [0.10, 0.10, 0.12]
        return SearchQuery(
            ship=str(payload.get("ship") or "fighter"),
            want=list(payload.get("want") or []),
            avoid=list(payload.get("avoid") or []),
            look=look,
            limit=int(payload.get("limit") or 12),
            max_seeds=int(payload.get("max_seeds") or 200_000_000),
            time_limit=float(payload.get("time_limit") or 20.0),
            workers=int(payload.get("workers") or 1),
        )

    def search(self, payload: dict, job=None) -> dict:
        from ..search import run

        rows = run(self._query(payload), job=job)
        return _ok(results=rows, count=len(rows))

    def search_estimate(self, payload: dict) -> dict:
        from ..search import explain

        return _ok(**explain(self._query(payload)))

    def start_search(self, payload: dict):
        """返回 ``jobs.Job``；调用方用它轮询进度/取消。"""
        from ..jobs import REGISTRY, run_in_thread
        from ..search import run

        query = self._query(payload)
        job = REGISTRY.create("search")
        run_in_thread(job, lambda j: run(query, job=j))
        return job

    # ------------------------------------------------------------ 任务

    def jobs(self) -> dict:
        from ..jobs import REGISTRY

        return _ok(jobs=[j.to_dict(include_result=False) for j in REGISTRY.all()])

    def job(self, job_id: str, include_result: bool = True) -> dict:
        from ..jobs import REGISTRY

        job = REGISTRY.get(job_id)
        if job is None:
            raise NotFound(f"没有任务 {job_id}")
        return _ok(job=job.to_dict(include_result=include_result))

    def cancel_job(self, job_id: str) -> dict:
        from ..jobs import REGISTRY

        job = REGISTRY.get(job_id)
        if job is None:
            raise NotFound(f"没有任务 {job_id}")
        job.cancel()
        return _ok(job=job.to_dict(include_result=False))

    # ------------------------------------------------------------ 存档

    def saves(self, folder: str | None = None) -> dict:
        from ..save import library

        return _ok(**library.scan_dir(folder))

    def ships(self, path: str | None = None) -> dict:
        from ..save import library

        p = library.resolve(path)
        ships, warns = library.open_ships(p)
        return _ok(path=str(p), ships=[s.to_dict() for s in ships], warnings=warns)

    def default_save(self) -> dict:
        from ..save import library

        return _ok(path=str(library.default_save_path()))

    def apply_seed(self, path: str, slot: int, source: dict, confirm: bool = False,
                   copy: bool = False) -> dict:
        from ..data.shipref import coerce
        from ..save import library, writer

        p = str(library.resolve(path))
        ref = coerce(source)
        return _ok(**writer.apply_seed(p, int(slot), ref, confirm=confirm, copy=copy))

    def apply_class(self, path: str, slot: int, ship_class: str = "",
                    values: dict | None = None, best: bool = False,
                    confirm: bool = False, copy: bool = False) -> dict:
        from ..save import library, writer

        p = str(library.resolve(path))
        return _ok(**writer.apply_class(p, int(slot), ship_class=ship_class, values=values,
                                        best=best, confirm=confirm, copy=copy))

    def backups(self, path: str) -> dict:
        from ..save import library, writer

        p = str(library.resolve(path))
        return _ok(path=p, backups=writer.backups(p))

    def restore(self, path: str, backup_path: str, confirm: bool = False) -> dict:
        from ..save import library, writer

        p = str(library.resolve(path))
        return _ok(**writer.restore(p, backup_path, confirm=confirm))

    # ------------------------------------------------------------ 预览

    def preview(self, ship: str, seed: str, parts: list[str] | None = None) -> dict:
        from .. import preview
        from ..data.shipref import ShipRef

        ref = ShipRef(type=ship, seed=seed, parts=parts, source="search").normalized()
        return _ok(**preview.build(ref))

    def glb_path(self, ship: str, seed: str, parts: list[str] | None = None) -> str:
        from .. import preview
        from ..data.shipref import ShipRef

        ref = ShipRef(type=ship, seed=seed, parts=parts, source="search").normalized()
        return preview.glb_for(ref)

    def preview_mesh(self, ship: str, seed: str,
                     parts: list[str] | None = None) -> dict:
        """原生 3D 视口用：直接返回 numpy 几何，不经过 glb。

        返回 ``{"groups": {(class, tex): (pos, nrm, uv, idx)}, "colours": {...}}``。
        这是 ``preview.build`` 的同源数据，导出 glb 仍走原路径。
        """
        from .. import paint
        from ..data.shipref import ShipRef

        ref = ShipRef(type=ship, seed=seed, parts=parts, source="search").normalized()
        if not ref.can_preview:
            raise BadRequest("这个船型/种子没有可生成的 3D")
        paths.ensure_shipwright_importable()
        from nms_procgen import model3d

        model = model3d.ship_model(ref.seed, ref.type, ref.parts, True, False)
        return {"groups": model["groups"], "colours": paint.look(ref.seed, ref.type) or {},
                "type": ref.type, "seed": ref.seed, "parts": ref.parts,
                "verts": sum(len(g[0]) for g in model["groups"].values()),
                "tris": sum(len(g[3]) // 3 for g in model["groups"].values())}

    def part_thumb(self, ship: str, part: str, size: int = 200) -> bytes:
        from .. import preview

        return preview.part_png(ship, part, size=size)

    def preview_png(self, ship: str, seed: str, parts: list[str] | None = None,
                    size: int = 240) -> bytes:
        from .. import render

        return render.ship_png(ship, seed, parts, size=(size, size), raster=size >= 260)

    def glyph_png(self, digit: str) -> bytes | None:
        from .. import glyphs as glyph_mod

        return glyph_mod.icon_png(digit)

    def glyph_strip_png(self, text: str | int) -> bytes:
        from .. import glyphs as glyph_mod

        return glyph_mod.panel_png(glyph_mod.digits_for(text))

    # ------------------------------------------------------------ 星系/星球

    def system(self, ua: int | None = None, glyphs: str | None = None,
               save_path: str | None = None, planets: bool = True) -> dict:
        from .. import zh as zh_mod
        from ..data.shipref import TYPE_LABELS

        data = self._internal("system", {"ua": ua, "glyphs": glyphs,
                                         "save_path": save_path, "planets": planets},
                              timeout=120.0)
        info = data.get("result") or {}
        info["race_zh"] = zh_mod.race_label(info.get("race"))
        for pl in info.get("planet_list") or []:
            pl["biome_zh"] = zh_mod.biome_label(pl.get("biome_name"))
            pl["sentinels_zh"] = zh_mod.sentinel_label(pl.get("sentinels"))
        for sh in info.get("ships") or []:
            sh["kind_zh"] = zh_mod.kind_label(sh.get("kind"))
            sh["type_label"] = zh_mod.zh(TYPE_LABELS, sh.get("type"), sh.get("type") or "")
        return _ok(**info)

    def locate(self, seed: str, save_path: str | None = None,
               max_steps: int = 3000, limit: int = 6) -> dict:
        data = self._internal("locate", {"seed": seed, "save_path": save_path,
                                         "max_steps": max_steps, "limit": limit},
                              timeout=180.0)
        return _ok(**(data.get("result") or {}))

    def start_system_scan(self, center_ua: int | None = None, radius: int = 0,
                          systems_per_region: int = 200, filters: dict | None = None,
                          limit: int = 40, save_path: str | None = None):
        from ..jobs import REGISTRY, run_in_thread

        payload = {"center_ua": center_ua, "radius": radius,
                   "systems_per_region": systems_per_region, "filters": filters or {},
                   "limit": limit, "save_path": save_path}
        job = REGISTRY.create("system-scan")
        run_in_thread(job, lambda _j: self._internal("system-scan", payload, timeout=900.0)
                      .get("result") or [])
        return job

    def galaxy_stats(self) -> dict:
        from .. import galaxy

        store = galaxy.GalaxyStore()
        try:
            return _ok(**store.stats())
        finally:
            store.close()

    def galaxy_query(self, filters: dict | None = None, limit: int = 40) -> dict:
        from .. import galaxy

        store = galaxy.GalaxyStore()
        try:
            return _ok(rows=store.query(filters or {}, limit=limit), stats=store.stats())
        finally:
            store.close()

    def galaxy_export_csv(self, filters: dict | None = None) -> str:
        import csv
        import io

        from .. import galaxy

        store = galaxy.GalaxyStore()
        try:
            rows = store.query(filters or {}, limit=500)
        finally:
            store.close()
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
        return buf.getvalue()

    def start_galaxy_scan(self, center_ua: int | None = None, radius: int = 0,
                          systems_per_region: int = 60, filters: dict | None = None,
                          limit: int = 40, save_path: str | None = None):
        from ..jobs import REGISTRY, run_in_thread

        payload = {"center_ua": center_ua, "radius": radius,
                   "systems_per_region": systems_per_region, "filters": filters or {},
                   "limit": limit, "save_path": save_path}
        job = REGISTRY.create("galaxy-scan")
        run_in_thread(job, lambda _j: self._internal("galaxy-scan", payload, timeout=1800.0)
                      .get("result") or {})
        return job

    # ------------------------------------------------------------ 符文

    def glyphs(self, text: str | int) -> dict:
        from .. import glyphs as glyph_mod

        return _ok(**glyph_mod.panel_payload(text))

    # ------------------------------------------------------------ 生物

    def creatures(self, save_path: str | None = None) -> dict:
        from .. import creature

        return _ok(**creature.companions(save_path))

    def creature_roles(self, limit: int = 400) -> dict:
        from .. import creature

        return _ok(**creature.role_names(limit))

    def creature_capabilities(self, deep: bool = False) -> dict:
        from .. import creature

        return _ok(**creature.capabilities(deep=deep))

    # ------------------------------------------------------------ 实时通道

    def live_status(self) -> dict:
        from ..live import writer

        return writer.status()

    def agent_status(self) -> dict:
        from ..live import agent_install

        return agent_install.status()

    def agent_install_mod(self) -> dict:
        from ..live import agent_install

        return agent_install.install_mod()

    def agent_install_deps(self, version: str | None = None) -> dict:
        from ..live import agent_install

        return agent_install.install_deps(version)

    def agent_bootstrap_runtime(self) -> dict:
        from ..live import agent_install

        return agent_install.bootstrap_runtime()

    def agent_launch(self, attach: bool = True) -> dict:
        from ..live import agent_install

        return agent_install.launch(attach=attach)

    def agent_stop(self) -> dict:
        from ..live import agent_install

        return agent_install.stop()

    def agent_wait(self, timeout: float = 20.0) -> dict:
        from ..live import agent_install

        return agent_install.wait_ready(timeout)

    def agent_client(self):
        from ..live.agent_client import AgentClient

        return AgentClient()

    def live_capabilities(self) -> dict:
        """给"游戏内"页用的能力表：agent 已连接时用 hello 的真实能力。"""
        from ..live import agent_install, build

        st = agent_install.status()
        hello = st.get("hello") or {}
        real = hello.get("capabilities") or {}
        caps = {
            "player": (bool(real.get("player")), "读取玩家 UA/坐标/位置", "low"),
            "system": (bool(real.get("system")), "读取当前星系/行星表", "low"),
            "planet": (bool(real.get("planet")), "读取当前行星天气/资源/动植物", "low"),
            "ships": (bool(real.get("ships")), "读取游戏内 12 个船槽", "low"),
            "teleport": (bool(real.get("teleport")), "写入位置并触发加载；可用 restore 还原", "high"),
            "scan": (bool(real.get("scan")), "读取行星扫描数据", "mid"),
            "scan.discover": (bool(real.get("scan.discover")), "写入发现列表（暂未开放）", "high"),
            "scan.instant": (bool(real.get("scan.instant")), "游戏内扫描条立即完成", "mid"),
            "restore": (bool(real.get("restore")), "还原上一次传送快照", "mid"),
        }
        table = {k: {"available": ok, "reason": reason if not ok else "", "risk": risk}
                 for k, (ok, reason, risk) in caps.items()}
        try:
            build_info = build.summary()
        except Exception as e:                              # noqa: BLE001
            build_info = {"error": f"{type(e).__name__}: {e}"}
        return {"attached": bool(st.get("game_running")), "reachable": bool(st.get("reachable")),
                "note": st.get("note") or "", "capabilities": table,
                "status": st, "build": build_info}

    def agent_call(self, cmd: str, **params: Any) -> dict:
        client = self.agent_client()
        try:
            return {"ok": True, **client.call(cmd, **params)}
        except Exception as e:                              # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def live_probe(self) -> dict:
        from ..live import mem, writer

        with mem.attach("NMS.exe") as proc:
            return _ok(**writer.probe(proc))

    def live_push(self, type_: str, seed: str | int) -> dict:
        from ..live import mem, writer

        with mem.attach("NMS.exe") as proc:
            return _ok(**writer.push(proc, type_, seed))

    def live_template_mod(self, dest: str | None = None) -> dict:
        from .. import paths as _paths
        from ..live import exml

        dest = dest or str(_paths.app_home() / "starforge-templates")
        return _ok(**exml.write_mod(dest))

    # ------------------------------------------------------------ 诊断

    def diagnostics(self) -> dict:
        from .. import selfcheck

        return _ok(**selfcheck.run(include_write=False))

    def doctor(self) -> dict:
        """轻量环境体检（原生壳设置页用；不要求 WebView2）。"""
        import importlib
        import platform
        import sys

        deps = {}
        for mod in ("numpy", "lz4", "hgpaktool", "texture2ddecoder", "pefile", "unicorn"):
            try:
                importlib.import_module(mod)
                deps[mod] = "ok"
            except Exception as e:                          # noqa: BLE001
                deps[mod] = f"{type(e).__name__}: {e}"
        try:
            import PySide6

            deps["PySide6"] = PySide6.__version__
        except Exception as e:                              # noqa: BLE001
            deps["PySide6"] = f"{type(e).__name__}: {e}"
        return _ok(python=sys.version.split()[0], platform=platform.platform(),
                   deps=deps, health=self.health())


SERVICES = Services()


def get_services() -> Services:
    return SERVICES


__all__ = ["SERVICES", "Services", "get_services"]
