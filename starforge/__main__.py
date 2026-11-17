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
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from .core import console, lock, log, paths, settings, strings

log = log.get("cli")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
        if not a.no_browser:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        print(f"{strings.APP_TITLE} → {url}   (Ctrl+C 退出)")
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


def cmd_glyph_overlay(a) -> int:
    from . import glyphs as glyph_mod, overlay
    try:
        digits = glyph_mod.digits_for(a.glyphs)
        png = glyph_mod.panel_png(digits, tile=a.tile)
    except ValueError as e:
        print(f"符文串无效：{e}", file=sys.stderr)
        return 2
    try:
        overlay.show(digits, png, alpha=a.alpha, click_through=a.click_through, scale=a.scale)
    except overlay.OverlayUnsupported as e:
        print(f"无法显示置顶窗口：{e}\n可改用：python -m starforge serve（浏览器里的符文弹层）",
              file=sys.stderr)
        return 3
    return 0


def cmd_selftest(a) -> int:
    from .data import load_catalog, load_icons
    gd = settings.current().gamedata_resolved()
    try:
        sw = str(paths.shipwright_root())
    except Exception:                      # noqa: BLE001 - 没装上游也要能自检
        sw = "未找到"
    print("Shipwright:", sw)
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


def main(argv=None) -> int:
    console.setup_console()          # Windows cp1252 下 print 中文不再崩（CI 首跑踩过）
    ap = argparse.ArgumentParser(prog="starforge", description=strings.APP_TITLE)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("serve", help="启动本地网页")
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

    p = sub.add_parser("selfcheck", help="端到端自检（写入只在存档副本上）")
    p.add_argument("--no-write", action="store_true")
    p.set_defaults(func=lambda a: __import__("starforge.selfcheck", fromlist=["main"]).main())

    p = sub.add_parser("selftest", help="自检")
    p.set_defaults(func=cmd_selftest)

    a = ap.parse_args(argv)
    if not getattr(a, "func", None):
        return cmd_serve(argparse.Namespace(port=0, no_browser=False))
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
