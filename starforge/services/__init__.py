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
from . import history

log = log.get("services")

_HIGH_RISK_CAPABILITIES = frozenset({
    "teleport", "restore", "scan.discover", "scan.instant", "teleport.portal",
})
# 显式开启 allow_unverified_agent 后，允许在未验证 build 上测试的写命令；
# scan.discover 仍保持关闭（会写发现列表）。多人模式始终禁用。
_EXPERIMENTAL_WRITE_CAPABILITIES = frozenset({
    "teleport", "restore", "scan.instant", "teleport.portal",
})
_MULTIPLAYER_REASON = "多人模式已启用：高风险写操作被禁用"
_AGENT_CONFIRM_TIMEOUT = 3.0
_AGENT_CONFIRM_INTERVAL = 0.25


def _ok(**kw: Any) -> dict:
    return {"ok": True, **kw}


def _brief(value: Any, limit: int = 240) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


_REDACT_KEY_HINTS = ("token", "secret", "password", "passwd", "api_key", "apikey",
                     "authorization", "cookie", "session")
_REDACT_TEXT_PATTERNS = (
    __import__("re").compile(r"(?i)(bearer\s+)([A-Za-z0-9._~+/=-]+)"),
    __import__("re").compile(r"(?i)(authorization\s*[:=]\s*)([^\r\n]+)"),
    __import__("re").compile(
        r"(?i)((?:access_|refresh_|api_)?token|secret|password|passwd|api[_-]?key)"
        r"(\s*[:=]\s*)([^\s,;]+)"),
)


def _redact_text(text: Any) -> str:
    """日志/诊断文本中常见的凭据值一律替换为 ***，避免诊断包泄密。"""
    out = str(text or "")
    for pat in _REDACT_TEXT_PATTERNS:
        if pat.groups == 2:
            out = pat.sub(lambda m: m.group(1) + "***", out)
        else:
            out = pat.sub(lambda m: m.group(1) + m.group(2) + "***", out)
    return out


def _redact(value: Any) -> Any:
    """递归脱敏：token/secret/password 等键值以及字符串里的凭据片段。"""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(hint in lowered for hint in _REDACT_KEY_HINTS):
                out[key] = "***"
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _record(kind: str, title: str, detail: Any = "", ref: str | None = None,
            ok: bool = True) -> None:
    """写一条最近活动；历史异常绝不能影响主流程。"""
    try:
        history.record(kind, title, _brief(detail), ref=ref, ok=ok)
    except Exception:                                       # noqa: BLE001
        pass


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
        env = dict(os.environ)
        env["PYTHONFAULTHANDLER"] = "0"
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=flags, env=env)
        out = (r.stdout or "").strip()
        data = None
        for line in reversed(out.splitlines()):
            try:
                data = json.loads(line)
                break
            except ValueError:
                continue
        if data is None:
            if r.returncode == 3221226505:  # 0xC0000409
                raise RuntimeError(
                    "系统生成子进程被 Windows 终止（0xC0000409）。这通常是 Unicorn 在 Windows 上"
                    "与 faulthandler/VEH 的冲突；主界面已隔离，不会跟着崩。请把日志发回，"
                    "必要时改用 unicorn==2.0.1.post1。")
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
            "workers": s.workers,
            "port": s.port,
            "theme": s.theme,
            "allow_unverified_agent": s.allow_unverified_agent,
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

        query = self._query(payload)
        try:
            rows = run(query, job=job)
        except Exception as e:                              # noqa: BLE001
            _record("search", "搜索失败", f"{type(e).__name__}: {e}", "search", False)
            raise
        _record("search", "搜索完成", f"{query.ship} · 找到 {len(rows)} 个结果", "search")
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

        def _run(j):
            try:
                rows = run(query, job=j)
            except Exception as e:                          # noqa: BLE001
                _record("search", "搜索失败", f"{type(e).__name__}: {e}", "search", False)
                raise
            _record("search", "搜索完成", f"{query.ship} · 找到 {len(rows)} 个结果", "search")
            return rows

        run_in_thread(job, _run)
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
        try:
            res = writer.apply_seed(p, int(slot), ref, confirm=confirm, copy=copy)
        except Exception as e:                              # noqa: BLE001
            _record("write", "写回存档失败",
                    f"槽位 {slot} · {ref.type} {ref.seed} · {type(e).__name__}: {e}",
                    "mine", False)
            raise
        _record("write", "写回存档成功",
                f"槽位 {res.get('slot', slot)} · {res.get('type', ref.type)} "
                f"{res.get('after', ref.seed)} · 备份 {res.get('backup') or '无'}",
                "mine")
        return _ok(**res)

    def apply_class(self, path: str, slot: int, ship_class: str = "",
                    values: dict | None = None, best: bool = False,
                    confirm: bool = False, copy: bool = False) -> dict:
        from ..save import library, writer

        p = str(library.resolve(path))
        try:
            res = writer.apply_class(p, int(slot), ship_class=ship_class, values=values,
                                     best=best, confirm=confirm, copy=copy)
        except Exception as e:                              # noqa: BLE001
            _record("write", "修改船级失败",
                    f"槽位 {slot} · {type(e).__name__}: {e}", "mine", False)
            raise
        before = (res.get("before") or {}).get("class") or "?"
        after = (res.get("after") or {}).get("class") or "?"
        _record("write", "修改船级成功",
                f"槽位 {res.get('slot', slot)} · {before} → {after} · "
                f"备份 {res.get('backup') or '无'}", "mine")
        return _ok(**res)

    # ------------------------------------------------------------ 船队 / 设计器扩展

    def fleet_extras(self, path: str | None = None) -> dict:
        """只读读取货船、护卫舰与多用途工具；每项独立报告不可用原因。"""
        from ..core.errors import SaveFormatError
        from ..save import library

        p = library.resolve(path)
        kind = library.classify(p)
        if kind != "player":
            reason = {
                "account": "这是账号数据，不是玩家存档（没有船队字段）",
                "manifest": "这是游戏的清单文件（mf_ 前缀），不含船队数据",
            }.get(kind, "无法识别的文件类型，请选择 save.hg 或 save2.hg")
            raise SaveFormatError(reason)

        paths.ensure_shipwright_importable()
        from nms_save import extras as nms_extras
        from nms_save import save as nms_save
        from nms_save import ships as nms_ships

        opened = nms_save.open_save(str(p))
        readable = opened.readable
        out: dict[str, Any] = {"path": str(p), "freighter": None,
                               "frigates": [], "multitools": [], "errors": {}}
        for key, fn in (("freighter", nms_ships.get_freighter),
                        ("frigates", nms_extras.frigates),
                        ("multitools", nms_extras.multitools)):
            try:
                out[key] = fn(readable)
            except Exception as e:                          # noqa: BLE001
                out["errors"][key] = f"{type(e).__name__}: {e}"
        out["available"] = {key: key not in out["errors"]
                            for key in ("freighter", "frigates", "multitools")}
        return _ok(**out)

    def apply_design(self, path: str, ship: str, seed: str, slot: Any = "new",
                     name: str = "", parts: list[str] | None = None,
                     paint: dict | None = None, confirm: bool = False,
                     copy: bool = False) -> dict:
        """把设计器的一套种子写入新船槽或替换现有槽；可选涂装。

        新建飞船使用 Shipwright 已验证的 ``ships.create_ship``（复制主船后换模型/种子），
        改色使用 ``ships.set_ship_paint``；两者都只通过 ``transact_save`` 写入。
        """
        from ..core.errors import BadRequest, WriteRefused
        from ..data.shipref import ShipRef, type_from_model
        from ..save import library, transaction

        if not confirm:
            raise BadRequest("缺少 confirm=true（写操作必须二次确认）")
        ref = ShipRef(type=str(ship or ""), seed=str(seed or ""), parts=parts,
                      name=str(name or ""), source="design").normalized()
        paths.ensure_shipwright_importable()
        from nms_procgen import ROOTS
        from nms_save import player as nms_player
        from nms_save import ships as nms_ships

        rel = ROOTS.get(ref.type)
        if not rel or not rel.lower().endswith(".descriptor.mbin"):
            raise BadRequest(f"设计器暂不支持写入这个船型：{ref.type}")
        filename = "MODELS/" + rel[len("models/"):].upper().replace(
            ".DESCRIPTOR.MBIN", ".SCENE.MBIN")

        paint = dict(paint or {})
        if paint:
            paint.setdefault("palette", "FREIGHTER")
            primary = paint.get("primary") or (0.0, 0.0, 0.0)
            accent = paint.get("accent")
        else:
            primary = accent = None

        p = str(library.resolve(path))
        snapshot: dict[str, Any] = {}

        def mutate(readable: dict):
            owned = readable.get("BaseContext", {}).get("PlayerStateData", {}).get(
                "ShipOwnership", [])
            before = {s.index: (s.name or "", s.filename, s.seed)
                      for s in nms_ships.list_ships(readable)}
            snapshot["before"] = before
            snapshot["before_paint"] = {}
            if str(slot).strip().lower() == "new":
                empty = [i for i, entry in enumerate(owned)
                         if not entry.get("Resource", {}).get("Filename")]
                if not empty:
                    raise BadRequest("存档里没有空船槽；请先腾出一个槽位或选择替换现有飞船")
                target = empty[0]
                clone_from = nms_player.primary_ship(readable)
                try:
                    nms_ships.create_ship(readable, target, filename, ref.seed,
                                          str(name or ref.type_label)[:64], clone_from)
                except Exception as e:                      # noqa: BLE001
                    raise BadRequest(f"新建飞船失败：{type(e).__name__}: {e}") from e
                what = f"新建飞船（槽位 {target}）"
            else:
                try:
                    target = int(slot)
                except (TypeError, ValueError) as e:
                    raise BadRequest(f"槽位必须是整数或 new，收到 {slot!r}") from e
                if not (0 <= target < len(owned)):
                    raise BadRequest(f"存档里没有槽位 {target}")
                if not owned[target].get("Resource", {}).get("Filename"):
                    raise BadRequest(f"槽位 {target} 是空的；请选择新建飞船")
                ships = nms_ships.list_ships(readable)
                current = next((s for s in ships if s.index == target), None)
                if current is None:
                    raise BadRequest(f"槽位 {target} 没有可读取的飞船")
                cur_type = type_from_model(current.filename)
                try:
                    if cur_type == ref.type:
                        nms_ships.set_ship_seed(readable, target, ref.seed)
                    else:
                        nms_ships.set_ship_model(readable, target, filename, ref.seed)
                    if name:
                        nms_ships.set_ship_name(readable, target, str(name)[:64])
                except Exception as e:                      # noqa: BLE001
                    raise BadRequest(f"写入飞船失败：{type(e).__name__}: {e}") from e
                what = f"替换槽位 {target}"
            snapshot["target"] = target
            snapshot["what"] = what
            if paint:
                try:
                    snapshot["before_paint"] = nms_ships.get_ship_paint(readable, target)
                    snapshot["paint"] = nms_ships.set_ship_paint(
                        readable, target, primary=primary, accent=accent,
                        palette_id=str(paint.get("palette") or "FREIGHTER"))
                except Exception as e:                      # noqa: BLE001
                    raise BadRequest(f"涂装写入失败：{type(e).__name__}: {e}") from e
            return {"slot": target, "what": what, "seed": ref.seed}

        def verify(readable: dict):
            target = snapshot["target"]
            ship_now = next((s for s in nms_ships.list_ships(readable)
                             if s.index == target), None)
            if ship_now is None:
                raise WriteRefused(f"写后校验失败：槽位 {target} 没有飞船")
            after_ref = ShipRef.from_save_ship(ship_now).normalized()
            if after_ref.type != ref.type:
                raise WriteRefused(
                    f"写后校验失败：船型读到 {after_ref.type}，预期 {ref.type}")
            if int(after_ref.seed, 16) != int(ref.seed, 16):
                raise WriteRefused(
                    f"写后校验失败：种子读到 {after_ref.seed}，预期 {ref.seed}")
            if name and (ship_now.name or "") != str(name)[:64]:
                raise WriteRefused("写后校验失败：飞船名称与预期不符")
            got_paint = None
            if paint:
                got_paint = nms_ships.get_ship_paint(readable, target)
                want = snapshot.get("paint") or {}
                if not got_paint or got_paint.get("palette") != want.get("palette"):
                    raise WriteRefused("写后校验失败：涂装调色板与预期不符")
                if got_paint.get("primary_index") != want.get("primary_index"):
                    raise WriteRefused("写后校验失败：涂装主色索引与预期不符")
            return {"slot": target, "type": after_ref.type, "seed": after_ref.seed,
                    "name": ship_now.name or "", "paint": got_paint,
                    "what": snapshot.get("what", "")}

        try:
            res = transaction.transact_save(p, mutate, verify, copy=copy)
        except Exception as e:                              # noqa: BLE001
            _record("write", "写入设计失败",
                    f"{ref.type} {ref.seed} · {type(e).__name__}: {e}", "mine", False)
            raise
        _record("write", "写入设计成功",
                f"{res.get('after', {}).get('what', '')} · {ref.type} {ref.seed} · "
                f"备份 {res.get('backup') or '无'}", "mine")
        return _ok(**res)

    def backups(self, path: str) -> dict:
        from ..save import library, writer

        p = str(library.resolve(path))
        try:
            rows = writer.backups(p)
        except Exception as e:                              # noqa: BLE001
            _record("backup", "查看备份失败",
                    f"{p} · {type(e).__name__}: {e}", "mine", False)
            raise
        _record("backup", "查看备份", f"{p} · {len(rows)} 个可用备份", "mine")
        return _ok(path=p, backups=rows)

    def restore(self, path: str, backup_path: str, confirm: bool = False) -> dict:
        from ..save import library, writer

        p = str(library.resolve(path))
        try:
            res = writer.restore(p, backup_path, confirm=confirm)
        except Exception as e:                              # noqa: BLE001
            _record("restore", "恢复备份失败",
                    f"{p} · {type(e).__name__}: {e}", "mine", False)
            raise
        _record("restore", "恢复备份成功",
                f"{p} · 来源 {res.get('restored_from') or backup_path}", "mine")
        return _ok(**res)

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

    def part_icon(self, ship: str, part: str, size: int = 32) -> bytes | None:
        """部件树小图标：直接从游戏几何渲染（带磁盘缓存），不依赖 Gagarin。"""
        try:
            return self.part_thumb(ship, part, size=max(32, size))
        except Exception:                                  # noqa: BLE001
            return None

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

        def _run(_j):
            try:
                result = self._internal("system-scan", payload, timeout=900.0).get("result") or []
            except Exception as e:                          # noqa: BLE001
                _record("scan", "星系扫描失败", f"{type(e).__name__}: {e}", "systems", False)
                raise
            hits = result if isinstance(result, list) else (result.get("hits") or [])
            _record("scan", "星系扫描完成",
                    f"命中 {len(hits)} 个结果 · 每区 {systems_per_region} 个系统", "systems")
            return result

        run_in_thread(job, _run)
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

        def _run(_j):
            try:
                result = self._internal("galaxy-scan", payload, timeout=1800.0).get("result") or {}
            except Exception as e:                          # noqa: BLE001
                _record("scan", "银河扫描失败", f"{type(e).__name__}: {e}", "systems", False)
                raise
            if isinstance(result, dict):
                scanned = int(result.get("scanned") or 0)
                hits = result.get("hits") or []
                detail = f"扫描 {scanned} 个星系 · 命中 {len(hits)} 个"
            else:
                detail = f"命中 {len(result or [])} 个结果"
            _record("scan", "银河扫描完成", detail, "systems")
            return result

        run_in_thread(job, _run)
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

    def agent_log_tail(self, lines: int = 200) -> dict:
        """只读 launcher.log 末尾；UI 可自行决定是否展示，不在这里改界面。"""
        from ..live import agent_install

        return agent_install.tail_launcher_log(lines=lines)

    def agent_snapshots(self, limit: int = 20) -> dict:
        """只读传送快照文件（由游戏内 agent 在传送前写入）。"""
        from ..live import agent_install

        path = agent_install.snapshots_path()
        try:
            import json

            data = json.loads(path.read_text("utf-8"))
            rows = data.get("snapshots") if isinstance(data, dict) else None
            return {"ok": True, "path": str(path), "exists": True,
                    "snapshots": list(rows or [])[-max(1, int(limit)):]}
        except FileNotFoundError:
            return {"ok": True, "path": str(path), "exists": False, "snapshots": []}
        except (OSError, ValueError, TypeError) as e:
            return {"ok": False, "path": str(path), "exists": path.exists(),
                    "snapshots": [], "error": f"{type(e).__name__}: {e}"}

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

        try:
            res = agent_install.launch(attach=attach)
        except Exception as e:                              # noqa: BLE001
            _record("agent", "启动游戏内代理失败",
                    f"{'连接' if attach else '启动'} · {type(e).__name__}: {e}", "live", False)
            raise
        _record("agent", "启动游戏内代理",
                "连接已运行的游戏" if attach else "启动游戏并注入", "live",
                bool(res.get("ok", True)))
        return res

    def agent_stop(self) -> dict:
        from ..live import agent_install

        try:
            res = agent_install.stop()
        except Exception as e:                              # noqa: BLE001
            _record("agent", "停止游戏内代理失败", f"{type(e).__name__}: {e}", "live", False)
            raise
        _record("agent", "停止游戏内代理", "", "live", bool(res.get("ok", True)))
        return res

    def agent_wait(self, timeout: float = 20.0) -> dict:
        from ..live import agent_install

        try:
            res = agent_install.wait_ready(timeout)
        except Exception as e:                              # noqa: BLE001
            _record("agent", "连接游戏失败", f"{type(e).__name__}: {e}", "live", False)
            raise
        ok = bool(res.get("ok", True))
        _record("agent", "连接游戏成功" if ok else "连接游戏失败",
                "" if ok else _brief(res.get("error") or "等待超时", 120), "live", ok)
        return res

    def agent_client(self):
        from ..live.agent_client import AgentClient

        return AgentClient()

    def live_capabilities(self) -> dict:
        """给"游戏内"页用的能力表：agent hello + build 闸门 + 多人闸门。

        返回结构保持兼容：仍然有 ``attached/reachable/note/capabilities/status/build``，
        只给每个能力追加 ``blocked_by``（build/multiplayer）方便界面解释原因。
        即使 agent hello 声称 teleport=true，未验证 build 或多人模式下也会被强制降级。
        """
        from ..live import agent_install, build

        st = agent_install.status()
        hello = st.get("hello") or {}
        real = hello.get("capabilities") or {}
        multiplayer = bool(hello.get("multiplayer"))
        build_info = st.get("build")
        if not isinstance(build_info, dict) or not ("verified" in build_info
                                                     or "write_allowed" in build_info):
            try:
                build_info = build.summary()
            except Exception as e:                          # noqa: BLE001
                build_info = {"error": f"{type(e).__name__}: {e}", "verified": False,
                              "write_allowed": False,
                              "reason": f"无法确认游戏 build：{type(e).__name__}: {e}；只允许只读能力"}
        write_allowed = bool(build_info.get("write_allowed",
                                            build_info.get("verified", False)))
        build_reason = build_info.get("reason") or "这版未验证：只允许只读能力"
        allow_unverified = bool(settings.current().allow_unverified_agent)
        caps = {
            "player": (bool(real.get("player")), "读取玩家 UA/坐标/位置", "low"),
            "system": (bool(real.get("system")), "读取当前星系/行星表", "low"),
            "planet": (bool(real.get("planet")), "读取当前行星天气/资源/动植物", "low"),
            "planet.scan": (bool(real.get("planet.scan")),
                            "读取当前行星完整档案（实验只读）", "mid"),
            "ships": (bool(real.get("ships")), "读取游戏内 12 个船槽", "low"),
            "teleport": (bool(real.get("teleport")), "写入位置并触发加载；可用 restore 还原", "high"),
            "teleport.portal": (bool(real.get("teleport.portal")),
                                "实验：cGcPortalComponent portal warp（未校准默认不可用）", "high"),
            "scan": (bool(real.get("scan")), "读取行星扫描数据", "mid"),
            "scan.discover": (bool(real.get("scan.discover")), "写入发现列表（暂未开放）", "high"),
            "scan.instant": (bool(real.get("scan.instant")), "游戏内扫描条立即完成", "mid"),
            "restore": (bool(real.get("restore")), "还原上一次传送快照", "mid"),
        }
        table = {k: {"available": ok, "reason": reason if not ok else "", "risk": risk}
                 for k, (ok, reason, risk) in caps.items()}
        for key in _HIGH_RISK_CAPABILITIES:
            item = table.get(key)
            if item is None:
                continue
            if not write_allowed:
                if allow_unverified and key in _EXPERIMENTAL_WRITE_CAPABILITIES:
                    item["experimental"] = True
                    item["unverified_allowed"] = True
                else:
                    item["available"] = False
                    item["reason"] = build_reason
                    item["blocked_by"] = "build"
                    continue
            if multiplayer:
                item["available"] = False
                item["reason"] = _MULTIPLAYER_REASON
                item["blocked_by"] = "multiplayer"
        return {"attached": bool(st.get("game_running")), "reachable": bool(st.get("reachable")),
                "note": st.get("note") or "", "capabilities": table,
                "status": st, "build": build_info, "multiplayer": multiplayer,
                "write_allowed": write_allowed}

    @staticmethod
    def _is_high_risk_agent_cmd(cmd: str, params: dict | None = None) -> bool:
        if cmd in _HIGH_RISK_CAPABILITIES:
            return True
        if cmd == "scan":
            return str((params or {}).get("mode") or "read").lower() == "discover"
        return False

    _AGENT_TITLES = {
        "hello": "连接游戏",
        "player": "读取玩家位置",
        "system": "读取当前星系",
        "planet": "读取当前行星",
        "planet.scan": "行星扫描",
        "ships": "读取游戏内船槽",
        "teleport": "传送",
        "teleport.portal": "传送门传送",
        "scan": "扫描",
        "scan.discover": "发现扫描",
        "scan.instant": "即时扫描",
        "scan.poi": "兴趣点扫描",
        "restore": "恢复游戏内快照",
    }

    def agent_call(self, cmd: str, **params: Any) -> dict:
        res = self._agent_call_unrecorded(cmd, **params)
        ok = bool(res.get("ok", True))
        label = self._AGENT_TITLES.get(cmd, f"游戏内操作 {cmd}")
        detail = ""
        if cmd in ("teleport", "teleport.portal"):
            glyphs = str(params.get("glyphs") or "")
            galaxy = params.get("galaxy")
            detail = f"目标 {glyphs}" + (f" · 星系 {galaxy}" if galaxy is not None else "")
        elif cmd == "scan":
            detail = f"模式 {params.get('mode') or 'read'}"
        elif cmd == "scan.poi":
            detail = f"类型 {params.get('kind') or 'portal'}"
        if not ok:
            err = res.get("error") or res.get("code") or ""
            detail = f"{detail} · {err}" if detail else err
        _record("agent", f"{label}{'成功' if ok else '失败'}", detail, "live", ok)
        return res

    def _agent_call_unrecorded(self, cmd: str, **params: Any) -> dict:
        """调用 agent；写命令先经 build/多人闸门，再走客户端白名单。"""
        from ..live import build

        high_risk = self._is_high_risk_agent_cmd(cmd, params)
        allow_experimental = (bool(settings.current().allow_unverified_agent)
                              and cmd in _EXPERIMENTAL_WRITE_CAPABILITIES)
        if high_risk and not allow_experimental:
            try:
                build_info = build.summary()
            except Exception as e:                          # noqa: BLE001
                build_info = {"verified": False, "write_allowed": False,
                              "reason": f"无法确认游戏 build：{type(e).__name__}: {e}；"
                                        "只允许只读能力"}
            if not build_info.get("write_allowed",
                                  build_info.get("verified", False)):
                return {"ok": False, "code": "E_BUILD_UNVERIFIED",
                        "error": build_info.get("reason") or "这版未验证：高风险写操作已禁用",
                        "build": build_info}
        client = self.agent_client()
        if high_risk:
            try:
                hello = client.call("hello")
            except Exception as e:                          # noqa: BLE001
                return {"ok": False, "code": "E_AGENT",
                        "error": f"{type(e).__name__}: {e}"}
            if hello.get("multiplayer"):
                return {"ok": False, "code": "E_MULTIPLAYER", "error": _MULTIPLAYER_REASON,
                        "multiplayer": True}
        try:
            res = {"ok": True, **client.call(cmd, **params)}
        except Exception as e:                              # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if cmd in ("teleport", "teleport.portal") and res.get("ok") and not res.get("confirmed"):
            res = self._confirm_teleport_location(client, res)
        return res

    @staticmethod
    def _location_key(loc: dict | None) -> tuple[int, ...] | None:
        loc = loc or {}
        keys = ("planet", "system", "voxel_x", "voxel_y", "voxel_z", "reality")
        if not all(k in loc for k in keys):
            return None
        try:
            return tuple(int(loc[k]) for k in keys)
        except (TypeError, ValueError):
            return None

    def _confirm_teleport_location(self, client, res: dict,
                                   timeout: float | None = None,
                                   interval: float | None = None) -> dict:
        """传送后轮询 /player 对比目标位置；只做读回，不伪造成功也不自动改写存档。"""
        import time

        dest = res.get("after") if isinstance(res.get("after"), dict) else None
        want = self._location_key(dest)
        if want is None:
            res["confirmed"] = False
            res["confirmation"] = "unconfirmed"
            res["confirm_error"] = "agent 未返回可对比的目标位置"
            return res
        timeout = _AGENT_CONFIRM_TIMEOUT if timeout is None else max(0.0, float(timeout))
        interval = _AGENT_CONFIRM_INTERVAL if interval is None else max(0.0, float(interval))
        deadline = time.monotonic() + timeout
        last_error = ""
        while True:
            try:
                got = self._location_key((client.call("player") or {}).get("location"))
                if got == want:
                    res["confirmed"] = True
                    res["confirmation"] = "confirmed"
                    res["confirmed_location"] = dest
                    return res
            except Exception as e:                          # noqa: BLE001
                last_error = f"{type(e).__name__}: {e}"
            if time.monotonic() >= deadline:
                break
            time.sleep(interval)
        res["confirmed"] = False
        res["confirmation"] = "unconfirmed"
        res["confirm_error"] = last_error or f"{timeout:.1f}s 内位置未读回确认"
        return res

    def live_probe(self) -> dict:
        from ..live import mem, writer

        with mem.attach("NMS.exe") as proc:
            return _ok(**writer.probe(proc))

    def live_push(self, type_: str, seed: str | int) -> dict:
        from ..live import mem, writer

        try:
            with mem.attach("NMS.exe") as proc:
                res = writer.push(proc, type_, seed)
        except Exception as e:                              # noqa: BLE001
            _record("agent", "送进游戏失败",
                    f"{type_} {seed} · {type(e).__name__}: {e}", "live", False)
            raise
        _record("agent", "送进游戏成功", f"{type_} {seed}", "live",
                bool(res.get("ok", True)))
        return _ok(**res)

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

    def build_status(self) -> dict:
        """当前 NMS.exe 的 build 指纹与写闸门；未知/未验证明确返回只读。"""
        from ..live import build

        try:
            return _ok(**build.summary())
        except Exception as e:                              # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            return {"ok": False, "error": msg, "build_id": "unknown",
                    "status": "unknown", "verified": False, "write_allowed": False,
                    "reason": f"无法确认游戏 build：{msg}；只允许只读能力"}

    def diagnostics_overview(self) -> dict:
        try:
            agent = self.agent_status()
            agent = _ok(**agent) if isinstance(agent, dict) else {"ok": True, "status": agent}
        except Exception as e:                              # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            agent = {"ok": False, "error": msg, "supported": False,
                     "reachable": False, "game_running": False,
                     "note": f"游戏内代理状态不可用：{msg}"}
        return _ok(build=self.build_status(), agent=agent)

    @staticmethod
    def _recent_log_paths(limit: int = 5) -> list:
        log_dir = paths.app_home() / "logs"
        candidates = []
        try:
            candidates.extend(p for p in log_dir.glob("*.log*") if p.is_file())
        except OSError:
            pass
        launcher = paths.app_home() / "agent" / "launcher.log"
        if launcher.is_file():
            candidates.append(launcher)
        seen = set()
        unique = []
        for p in candidates:
            try:
                key = str(p.resolve()).lower()
            except OSError:
                key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(p)

        def _mtime(p) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0

        unique.sort(key=_mtime, reverse=True)
        return unique[:max(1, int(limit or 1))]

    def recent_logs(self, limit: int = 5, max_bytes: int = 256 * 1024) -> dict:
        """最近的 starforge/launcher 日志；只读尾部，限制文件数与单文件大小。"""
        files = []
        max_bytes = max(1, int(max_bytes or 1))
        for p in self._recent_log_paths(limit):
            try:
                size = p.stat().st_size
                with open(p, "rb") as fh:
                    if size > max_bytes:
                        fh.seek(size - max_bytes)
                    text = fh.read(max_bytes).decode("utf-8", "replace")
                files.append({"name": p.name, "path": str(p), "size": int(size),
                              "truncated": bool(size > max_bytes),
                              "text": _redact_text(text)})
            except OSError as e:
                files.append({"name": p.name, "path": str(p), "size": 0,
                              "truncated": False,
                              "text": f"[读取失败] {type(e).__name__}: {e}"})
        return _ok(files=files, limit=max(1, int(limit or 1)), max_bytes=max_bytes)

    def export_diagnostics(self, dest: str, include_selfcheck: bool = True) -> dict:
        """把 health/doctor/selfcheck/build/agent/脱敏设置/日志导出为 ZIP。

        单个组件失败不会让整个导出失败：manifest 的 ``errors`` 会记录原因；
        真正的写文件失败会抛 ``RuntimeError``，界面显示可读错误。
        """
        import json
        import zipfile
        from datetime import datetime, timezone
        from pathlib import Path

        target = Path(dest).expanduser()
        errors: dict[str, str] = {}
        entries: dict[str, bytes] = {}

        def add_json(name: str, fn) -> None:
            try:
                value = fn()
            except Exception as e:                          # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"
                errors[name] = msg
                value = {"ok": False, "error": msg}
            entries[name] = json.dumps(_redact(value), ensure_ascii=False,
                                       indent=2).encode("utf-8")

        add_json("health.json", self.health)
        add_json("doctor.json", self.doctor)
        add_json("build.json", self.build_status)
        add_json("agent.json", self.agent_status)
        add_json("settings.json", self.settings_snapshot)
        if include_selfcheck:
            add_json("selfcheck.json", self.diagnostics)
        else:
            entries["selfcheck.json"] = json.dumps(
                {"ok": None, "skipped": True, "reason": "导出时未运行自检"},
                ensure_ascii=False, indent=2).encode("utf-8")

        logs_meta = []
        try:
            log_files = self.recent_logs(limit=5, max_bytes=256 * 1024).get("files") or []
        except Exception as e:                              # noqa: BLE001
            log_files = []
            errors["logs"] = f"{type(e).__name__}: {e}"
        for index, item in enumerate(log_files):
            base = Path(str(item.get("name") or "log.txt")).name or "log.txt"
            arc = f"logs/{base}"
            if arc in entries:
                arc = f"logs/{index}-{base}"
            entries[arc] = _redact_text(item.get("text") or "").encode("utf-8", "replace")
            logs_meta.append({"archive": arc, "path": item.get("path") or "",
                              "size": item.get("size") or 0,
                              "truncated": bool(item.get("truncated"))})

        manifest = {
            "app": "starforge",
            "version": __import__("starforge").__version__,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": sorted(entries) + ["manifest.json"],
            "logs": logs_meta,
            "errors": errors,
            "note": "设置与日志已脱敏；不包含 token/密码。",
        }
        entries["manifest.json"] = json.dumps(manifest, ensure_ascii=False,
                                              indent=2).encode("utf-8")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                for name in sorted(entries):
                    zf.writestr(name, entries[name])
        except OSError as e:
            raise RuntimeError(f"无法写入诊断包 {target}：{e}") from e
        return _ok(path=str(target), entries=sorted(entries),
                   bytes=target.stat().st_size, errors=errors,
                   logs=logs_meta, manifest=manifest)


SERVICES = Services()


def get_services() -> Services:
    return SERVICES


__all__ = ["SERVICES", "Services", "get_services", "history"]
