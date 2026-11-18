"""CLI 入口：`python -m starforge <命令>`。

  serve              起本地网页（默认）
  ships [--path P]   列出存档里的船
  saves [--dir D]    扫描存档目录
  catalog [--ship T] 目录统计
  icon PART [-o F]   导出某部件缩略图
  selftest           自检（不依赖游戏）
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from .core import console, lock, log, paths, settings, strings

if __name__ == "__main__" and len(sys.argv) <= 1:
    console.hide_console_window()

log = log.get("cli")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cmd_app(a) -> int:
    """默认命令：打开原生桌面窗口。旧 pywebview 回退已移除。"""
    console.hide_console_window()          # 单 exe：双击时把控制台藏掉
    if getattr(a, "browser", False):
        print("--browser 已移除：原生界面请用 starforge app；调试 API 请用 starforge serve",
              file=sys.stderr)
        return 2
    if getattr(a, "safe", False):
        os.environ["STARFORGE_SAFE"] = "1"
        os.environ["QT_OPENGL"] = "software"
    try:
        from .app.main import run as native_run
        return native_run([sys.argv[0]])
    except Exception as e:                                 # noqa: BLE001
        print(f"原生界面启动失败：{type(e).__name__}: {e}", file=sys.stderr)
        print("请确认安装包完整，或运行 starforge doctor 查看依赖。", file=sys.stderr)
        return 5


def cmd_serve(a) -> int:
    from .web.app import create_app
    s = settings.current()
    port = a.port or s.port or _free_port()
    app = create_app()
    url = f"http://127.0.0.1:{port}/"
    lk = lock.InstanceLock()
    try:
        lk.acquire()
    except lock.AlreadyRunning as e:
        print(f"{e}；直接打开 {url} 或先关掉那个实例", file=sys.stderr)
        return 2
    try:
        print(f"{strings.APP_TITLE} JSON API → {url}   (Ctrl+C 退出)")
        print("原生界面请用 starforge app；该地址只提供 JSON API。", file=sys.stderr)
        app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)
    finally:
        lk.release()
    return 0


def cmd_ships(a) -> int:
    from .save import library
    p = library.resolve(a.path)
    ships, warns = library.open_ships(p)
    print(f"{p}  {len(ships)} 艘")
    for s in ships:
        flag = "" if s.procedural else "  [固定模型：改种子无效]"
        print(f"  [{s.slot}] {s.type:9s} {s.seed}  {s.name or '(未命名)'}{flag}")
    for w in warns:
        print("  ! " + w)
    return 0


def cmd_saves(a) -> int:
    from .save import library
    res = library.scan_dir(a.dir)
    print(f"目录：{res['dir'] or '(未配置)'}")
    for f in res["files"]:
        state = "可读" if f["ok"] else "不可用"
        print(f"  {f['name']:18s} {f['size']:>8d}B  {f['kind']:8s} {state:5s} {f['ships'] and str(f['ships'])+' 艘' or ''} {f['error']}")
    return 0


def cmd_catalog(a) -> int:
    from .data import load_catalog
    gd = settings.current().gamedata_resolved()
    if not gd:
        print(strings.ERR_NO_GAMEDATA, file=sys.stderr)
        return 1
    cat = load_catalog(gd)
    if a.ship:
        for g, opts in cat.groups_of(a.ship).items():
            print(f"{g}  ({len(opts)} 项)")
            for p, w in opts:
                print(f"    {p}  {w}")
        return 0
    print(json.dumps({t: {"groups": len(v["groups"]),
                          "parts": sum(len(o) for o in v["groups"].values())}
                      for t, v in cat.ships.items()}, ensure_ascii=False, indent=1))
    print("palettes:", ", ".join(sorted(cat.palettes)))
    return 0


def cmd_icon(a) -> int:
    from .data import load_icons
    gd = settings.current().gamedata_resolved()
    if not gd:
        print(strings.ERR_NO_GAMEDATA, file=sys.stderr)
        return 1
    data = load_icons(gd).png(a.part, a.ship)
    if not data:
        print(f"没有这个部件：{a.part}", file=sys.stderr)
        return 1
    out = Path(a.out or f"{a.part.strip('_')}.png")
    out.write_bytes(data)
    print(f"-> {out} ({len(data)} B)")
    return 0


def cmd_settings(a) -> int:
    from .core import settings as st
    kw = {}
    if a.saves is not None:
        kw["saves_dir"] = a.saves
    if a.gamedata is not None:
        kw["gamedata_dir"] = a.gamedata
    if a.game is not None:
        kw["game_dir"] = a.game
    if a.write is not None:
        kw["write_enabled"] = a.write
    if kw:
        st.update(**kw)
    s = st.current()
    print(f"设置文件：{paths.settings_file()}")
    for k in ("write_enabled", "saves_dir", "gamedata_dir", "game_dir", "port"):
        print(f"  {k:14s} {getattr(s, k)!r}")
    return 0


def cmd_live_probe(a) -> int:
    import json as _json
    from .live import mem, writer
    if not mem.IS_WINDOWS:
        print("实时通道仅支持 Windows；存档写回与符文浮窗在其它平台可用。", file=sys.stderr)
        return 3
    try:
        proc = mem.attach("NMS.exe")
    except mem.LiveUnsupported as e:
        print(f"连不上游戏：{e}", file=sys.stderr)
        return 4
    with proc:
        rep = writer.probe(proc)
    print(_json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


def cmd_agent(a) -> int:
    """游戏内代理（M4）的握手/自检入口。

    现在还没有 DLL，但入口先固定下来：`agent hello` 打印**能力表**（每项 available/reason），
    与 `docs/AGENT-PROTOCOL.md` 的命令表一一对应。装上 agent 之后同一条命令就会走真实握手。
    """
    import json as _json
    from .live import mem
    caps = {
        "player.ua": (False, "需要 agent（M4）", "low"),
        "player.position": (False, "需要 agent（M4）", "low"),
        "player.stats": (False, "需要 agent（M4）", "low"),
        "system.current": (False, "需要 agent（M4）", "low"),
        "planet.current": (False, "需要 agent（M4）", "low"),
        "ship.read": (False, "需要 agent（M4）", "low"),
        "ship.write_seed": (False, "需要 agent（M4）", "mid"),
        "ship.write_class": (False, "需要 agent（M4）", "mid"),
        "ship.write_parts": (False, "实验性：部件数组布局未确认", "high"),
        "teleport.system": (False, "需要 agent（M5）", "high"),
        "teleport.position": (False, "需要 agent（M5）+ 落点预检", "high"),
        "scan.planet": (False, "需要 agent（M6）", "mid"),
        "debug.flags": (False, "实验性：位域未验证", "high"),
    }
    attached = False
    note = ""
    if not mem.IS_WINDOWS:
        note = "非 Windows：内存通道不可用（存档写回与符文浮窗不受影响）"
    else:
        try:
            with mem.attach("NMS.exe") as proc:
                attached = True
                note = f"已连上游戏进程 pid={getattr(proc, 'pid', '?')}，但 agent DLL 尚未安装（M4）"
        except Exception as e:                             # noqa: BLE001
            note = f"未连上游戏：{type(e).__name__}: {e}"
    table = {k: {"available": False, "reason": r, "risk": risk} for k, (_ok, r, risk) in caps.items()}
    rep = {"proto": 1, "agent": None, "attached": attached, "note": note,
           "capabilities": table,
           "next": "按 docs/VERIFY-AGENT-WINDOWS.md 第 4 节回报；M4 落地后这里会变成真实握手"}
    print(_json.dumps(rep, ensure_ascii=False, indent=1))
    return 0 if a.action != "hello" else (0 if attached else 5)


def cmd_internal(a) -> int:
    """隐藏的内部子进程入口：把 unicorn/systemgen 隔离出去。"""
    import json as _json

    # Unicorn 在 Windows 上使用 VEH 按需提交代码页；faulthandler 会抢在它前面
    # 捕获 access violation，导致 uc_mem_map 崩溃。子进程里必须关掉。
    try:
        import faulthandler as _fh

        _fh.disable()
    except Exception:                                      # noqa: BLE001
        pass

    try:
        payload = _json.loads(a.payload or "{}")
    except ValueError as e:
        print(_json.dumps({"ok": False, "error": f"payload 不是 JSON：{e}"}))
        return 2
    try:
        if a.kind == "system":
            from . import system as system_mod

            ua = payload.get("ua")
            glyphs = payload.get("glyphs")
            if glyphs:
                from nms_procgen.locate import parse_address

                ua = parse_address(glyphs)
            result = system_mod.system(ua, planets=bool(payload.get("planets", True)),
                                       save_path=payload.get("save_path"))
        elif a.kind == "locate":
            from . import system as system_mod

            result = system_mod.locate_seed(payload.get("seed"), save_path=payload.get("save_path"),
                                            max_steps=int(payload.get("max_steps") or 3000),
                                            limit=int(payload.get("limit") or 6))
        elif a.kind == "system-scan":
            from . import system as system_mod

            result = system_mod.scan(
                center_ua=payload.get("center_ua"), radius=int(payload.get("radius") or 0),
                systems_per_region=int(payload.get("systems_per_region") or 200),
                filters=payload.get("filters") or {}, limit=int(payload.get("limit") or 40),
                save_path=payload.get("save_path"))
        elif a.kind == "galaxy-scan":
            from . import galaxy

            result = galaxy.scan(
                center_ua=payload.get("center_ua"), radius=int(payload.get("radius") or 0),
                systems_per_region=int(payload.get("systems_per_region") or 60),
                filters=payload.get("filters") or {}, limit=int(payload.get("limit") or 40),
                save_path=payload.get("save_path"))
        else:
            print(_json.dumps({"ok": False, "error": f"未知内部任务：{a.kind}"}))
            return 2
        print(_json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except Exception as e:                                  # noqa: BLE001
        print(_json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        return 1


def cmd_doctor(a) -> int:
    """环境体检：把"运行时会不会缺东西"一次说清（打包产物排障的第一条命令）。

    检查项：Python/平台、关键三方库、unicorn（能不能建 Uc）、系统生成器能不能借用、
    Qt/PySide6 原生界面、上游数据层。
    """
    import json as _json
    import platform
    out = {"python": sys.version.split()[0], "platform": platform.platform(),
           "frozen": bool(getattr(sys, "frozen", False)), "deps": {}, "notes": []}
    for mod, why in (("numpy", "渲染/几何"), ("flask", "本地服务"), ("lz4", "存档解压"),
                     ("hgpaktool", "pak 解包"), ("texture2ddecoder", "BC7 贴图"),
                     ("pefile", "exe 反射（生物角色表）"),
                     ("capstone", "反汇编（仅开发期分析用，运行时不需要）")):
        try:
            __import__(mod)
            out["deps"][mod] = "ok"
        except Exception as e:                             # noqa: BLE001
            out["deps"][mod] = f"{type(e).__name__}: {e}"
            out["notes"].append(f"{mod} 缺失（{why}会降级）")
    # unicorn：不只是 import，还要能真的建 Uc（Windows 打包最常见是 DLL 没带进去）
    try:
        import unicorn
        uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_64)
        uc.mem_map(0x1000, 0x1000)
        out["unicorn"] = {"ok": True, "version": getattr(unicorn, "__version__", "?")}
    except Exception as e:                                 # noqa: BLE001
        out["unicorn"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        out["notes"].append("unicorn 不可用 → 星系/行星生成、种子反查星系会失效")
    # 系统生成器
    try:
        from . import system as system_mod
        out["systemgen"] = {"available": system_mod.available()}
    except Exception as e:                                 # noqa: BLE001
        out["systemgen"] = {"available": False, "error": f"{type(e).__name__}: {e}"}
    # 原生界面
    try:
        import PySide6
        from PySide6.QtWidgets import QApplication  # noqa: F401
        out["gui"] = {"available": True, "framework": "PySide6",
                      "version": getattr(PySide6, "__version__", "?")}
    except Exception as e:                                 # noqa: BLE001
        out["gui"] = {"available": False, "reason": f"{type(e).__name__}: {e}"}
        out["notes"].append("PySide6/Qt 不可用 → 原生界面无法启动")
    # 上游数据层
    try:
        from .core import paths
        out["upstream"] = paths.ensure_shipwright_importable()
    except Exception as e:                                 # noqa: BLE001
        out["upstream"] = f"{type(e).__name__}: {e}"
    optional = {"capstone"}
    required_ok = all(v == "ok" for k, v in out["deps"].items() if k not in optional)
    ok = out["unicorn"]["ok"] and required_ok and bool(out["gui"].get("available"))
    out["ok"] = ok
    print(_json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if ok else 7


def cmd_glyph_overlay(a) -> int:
    from . import glyphs as glyph_mod
    try:
        digits = glyph_mod.digits_for(a.glyphs)
        png = glyph_mod.panel_png(digits, tile=a.tile)
    except ValueError as e:
        print(f"符文串无效：{e}", file=sys.stderr)
        return 2
    try:
        from .app.overlay import show as qt_show

        qt_show(digits, png, alpha=a.alpha, click_through=a.click_through, scale=a.scale)
        return 0
    except Exception as e:                                  # noqa: BLE001
        print(f"Qt 浮窗不可用：{type(e).__name__}: {e}", file=sys.stderr)
        return 3


def cmd_webcheck(a) -> int:
    """打包后验证 API-only 服务：不占端口、不起子进程。"""
    from .web.app import create_app
    app = create_app()
    c = app.test_client()
    optional = {"/api/catalog/fighter", "/api/part-thumb/sentinel/_PIT_A.png"}
    checks = []
    for path in ("/", "/api/health", "/api/settings", "/api/capabilities",
                 "/api/textures/status", "/api/catalog/fighter",
                 "/api/part-thumb/sentinel/_PIT_A.png", "/api/warm",
                 "/api/galaxy/stats", "/api/creatures/capabilities"):
        r = c.get(path)
        if path in optional:
            ok = (r.status_code == 200 and len(r.data) > 20) or (
                r.status_code == 404 and r.mimetype == "application/json")
        else:
            ok = r.status_code == 200 and len(r.data) > 20
        checks.append((path, r.status_code, len(r.data), ok))
    root = c.get("/").get_json() or {}
    checks.append(("根路径为 JSON API", 200, 0, root.get("service") == "starforge-api"))
    bad = [c_ for c_ in checks if not c_[3]]
    for path, code, size, ok in checks:
        print(f"{'✓' if ok else '✗'} {path:30s} {code} {size:>8d}B")
    if bad:
        print(f"接口自检失败：{len(bad)} 项", file=sys.stderr)
        return 1
    print("接口自检通过")
    return 0

def cmd_selftest(a) -> int:
    from .data import load_catalog, load_icons
    gd = settings.current().gamedata_resolved()
    try:
        sw = paths.ensure_shipwright_importable()
        try:                               # 是不是同机仓库？
            repo = os.path.abspath(str(paths.shipwright_root()))
            kind = "同机仓库" if os.path.normcase(repo) == os.path.normcase(os.path.abspath(sw)) else "内置(打包版)"
        except Exception:                  # noqa: BLE001  没有仓库 → 只能是内置
            kind = "内置(打包版)"
        print(f"Shipwright: {sw}  [{kind}]")
    except Exception as e:                 # noqa: BLE001 - 没装上游也要能自检
        print(f"Shipwright: 未找到（{e}）")
    print("GAMEDATA  :", gd or "未找到")
    if gd:
        cat = load_catalog(gd)
        print(f"  catalog: {cat.stats}")
        ics = load_icons(gd)
        print(f"  icons  : {ics.counts} 版本 {ics.versions}")
        sample = sorted(ics.flat)[:3]
        print(f"  样本图 : {[(s, len(ics.flat[s])) for s in sample]}")
    from .save import library
    res = library.scan_dir()
    print("存档      :", res["dir"] or "未配置", f"{len(res.get('files', []))} 个文件")
    return 0


def _ok(fn) -> bool:
    try:
        fn()
        return True
    except Exception:                                     # noqa: BLE001
        return False


def _strip_internal_args(argv: list[str]) -> list[str]:
    """丢掉 pywebview / WebView2 之类的内部参数（它们用同名 exe 启子进程）。

    实测：打包后 pywebview 会带 `parent_pid=<n>` 重新执行本程序，
    若当成子命令解析就会刷 `invalid choice: 'parent_pid=...'`。
    """
    out, skip_next = [], False
    for a in argv:
        if skip_next:
            skip_next = False
            continue
        if a in ("--parent-pid", "--pid", "--hwnd"):
            skip_next = True
            continue
        if a.startswith("parent_pid=") or a.startswith("--parent_pid=") or a.startswith("-pid="):
            continue
        out.append(a)
    return out


def main(argv=None) -> int:
    console.setup_console()          # Windows cp1252 下 print 中文不再崩（CI 首跑踩过）
    argv = _strip_internal_args(list(sys.argv[1:] if argv is None else argv))
    if not argv:                          # 双击启动：尽早把控制台藏掉，减少闪烁
        console.hide_console_window()
    ap = argparse.ArgumentParser(prog="starforge", description=strings.APP_TITLE)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("app", help="打开桌面窗口（默认原生）")
    p.add_argument("--browser", action="store_true", help="强制用浏览器打开（调试用）")
    p.add_argument("--safe", action="store_true", help="安全模式：软件 OpenGL，排查显卡驱动崩溃")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=cmd_app)

    p = sub.add_parser("serve", help="本地 JSON API 调试（无静态网页）")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("ships", help="列出存档里的船")
    p.add_argument("--path")
    p.set_defaults(func=cmd_ships)

    p = sub.add_parser("saves", help="扫描存档目录")
    p.add_argument("--dir")
    p.set_defaults(func=cmd_saves)

    p = sub.add_parser("catalog", help="飞船部件目录")
    p.add_argument("--ship")
    p.set_defaults(func=cmd_catalog)

    p = sub.add_parser("icon", help="导出部件缩略图")
    p.add_argument("part")
    p.add_argument("--ship")
    p.add_argument("-o", "--out")
    p.set_defaults(func=cmd_icon)

    p = sub.add_parser("settings", help="查看/修改设置")
    p.add_argument("--saves")
    p.add_argument("--gamedata")
    p.add_argument("--game")
    p.add_argument("--write", type=lambda v: v.lower() in ("1", "true", "yes", "on"), default=None)
    p.set_defaults(func=cmd_settings)

    p = sub.add_parser("glyph-overlay", help="把 12 个传送门符文贴成置顶窗口")
    p.add_argument("glyphs", help="12 位 glyph 串或系统地址")
    p.add_argument("--alpha", type=float, default=0.94)
    p.add_argument("--tile", type=int, default=72, help="每个符文像素")
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--click-through", action="store_true", help="鼠标穿透（不挡游戏点击）")
    p.set_defaults(func=cmd_glyph_overlay)

    p = sub.add_parser("live", help="实时通道（只读诊断）")
    p.add_argument("action", choices=["probe"], nargs="?", default="probe")
    p.set_defaults(func=lambda a: cmd_live_probe(a))

    p = sub.add_parser("_internal", help=argparse.SUPPRESS)
    p.add_argument("kind", choices=["system", "locate", "system-scan", "galaxy-scan"])
    p.add_argument("--payload", default="{}")
    p.set_defaults(func=cmd_internal)

    p = sub.add_parser("doctor", help="环境体检（依赖/unicorn/Qt/上游）")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("agent", help="游戏内代理（M4）：hello / 能力表")
    p.add_argument("action", choices=["hello"], nargs="?", default="hello")
    p.set_defaults(func=cmd_agent)

    p = sub.add_parser("webcheck", help="验证 API 与关键接口（打包后必跑）")
    p.set_defaults(func=cmd_webcheck)

    p = sub.add_parser("selfcheck", help="端到端自检（写入只在存档副本上）")
    p.add_argument("--no-write", action="store_true")
    p.set_defaults(func=lambda a: __import__("starforge.selfcheck", fromlist=["main"]).main(
        include_write=not a.no_write))

    p = sub.add_parser("selftest", help="自检")
    p.set_defaults(func=cmd_selftest)

    a = ap.parse_args(argv)
    if not getattr(a, "func", None):
        return cmd_app(argparse.Namespace(port=0, debug=False))     # 双击 → 原生窗口
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
