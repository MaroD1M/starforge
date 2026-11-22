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


def cmd_live(a) -> int:
    """``starforge live`` 的分派：默认 probe，push 走模板槽写入。"""
    if getattr(a, "action", "probe") == "push":
        return cmd_live_push(a)
    return cmd_live_probe(a)


def cmd_live_push(a) -> int:
    """把外观种子写进模板槽：定位 → 写入 → 回读校验（全部由 writer.push 完成）。

    这是 ``starforge live push`` 的实现。写闸门与 UI/Web 共用 ``Services.live_push``：
    写开关关闭或没给 ``--yes`` 都会在连接游戏之前被拒绝。没有 ``--force``：
    定位不唯一或回读不符时宁可失败，也不猜地址写内存。
    """
    import json as _json

    from .core.errors import BadRequest, WriteDisabled
    from .live import exml, mem, writer
    from .services import E_CONFIRM_REQUIRED, E_WRITE_DISABLED, get_services

    type_ = str(getattr(a, "type", "") or "").strip()
    types: list[str] = []
    try:
        types = sorted({e["type"] for e in exml.manifest()})
    except Exception as e:                                 # noqa: BLE001
        return _live_push_error(a, f"读取模板类型清单失败：{type(e).__name__}: {e}",
                                "确认安装包完整后重试。", code=2)
    if not type_:
        return _live_push_error(a, "缺少 --type", f"可用类型：{', '.join(types)}", code=2)
    if type_ not in types:
        return _live_push_error(a, f"未知船型：{type_}", f"可用类型：{', '.join(types)}", code=2)
    try:
        seed = _parse_seed(getattr(a, "seed", None))
    except ValueError as e:
        return _live_push_error(a, f"种子无效：{e}",
                                "用 0x 前缀十六进制（例如 0x1111222233334444）或十进制，"
                                "范围 0..2^64-1。", code=2)

    try:
        result = get_services().live_push(
            type_, seed, confirm=bool(getattr(a, "yes", False)))
    except WriteDisabled as e:
        return _live_push_error(
            a, str(e),
            "到设置页打开“允许写入”（或运行 starforge settings --write 1）后重试。",
            code=2, error_code=E_WRITE_DISABLED)
    except BadRequest as e:
        return _live_push_error(
            a, str(e),
            "确认只写 8 字节模板种子、不改存档后，加 --yes 重跑。",
            code=2, error_code=E_CONFIRM_REQUIRED)
    except mem.LiveUnsupported as e:
        if not mem.IS_WINDOWS:
            return _live_push_error(a, "实时写入仅支持 Windows。",
                                    "Linux/Proton 下请改用存档写回；符文浮窗不受影响。",
                                    code=3)
        return _live_push_error(a, f"连不上游戏：{e}",
                                "先启动 NMS.exe 并载入存档，再重试；不需要结束游戏进程。", code=4)
    except writer.LocateError as e:
        msg = str(e)
        if "模板槽" in msg or "templates" in msg:
            hint = ("没找到模板槽：确认 starforge-templates 模板 Mod 已安装并重启游戏，"
                    "且已经进入存档；可先运行 live probe 检查候选。")
        elif "回读" in msg:
            hint = ("回读校验失败：地址可能已失效。不要反复重试写入；"
                    "重启游戏后先用 live probe 检查模板槽。")
        else:
            hint = "写入被拒绝；先运行 live probe 检查模板槽与游戏状态。"
        return _live_push_error(a, f"写入失败：{msg}", hint, code=5)
    except Exception as e:                                 # noqa: BLE001
        return _live_push_error(a, f"写入失败：{type(e).__name__}: {e}",
                                "先运行 live probe 检查游戏状态。", code=5)

    if getattr(a, "json", False):
        print(_json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    if result.get("unchanged"):
        print(f"{type_} 模板槽已经是这个种子（{_fmt_seed(result.get('seed'))}），无需写入。")
    else:
        print(f"已写入 {type_} 模板槽。")
    print(f"  地址：{_fmt_addr(result.get('address'))}")
    print(f"  种子：{_fmt_seed(result.get('seed'))}")
    if "before" in result and "after" in result:
        print(f"  回读：{_fmt_seed(result['before'])} → {_fmt_seed(result['after'])}")
    if result.get("score") is not None:
        print(f"  置信：{float(result['score']):.2f}")
    return 0


def _as_int(value) -> int:
    """服务层把 u64 转成 hex 字符串（避免 Qt int64 溢出），CLI 两种都要能吃。"""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value or "0").strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text or "0")


def _fmt_seed(value) -> str:
    return "0x%016X" % (_as_int(value) & 0xFFFFFFFFFFFFFFFF)


def _fmt_addr(value) -> str:
    return "0x%X" % _as_int(value)


def _parse_seed(text) -> int:
    """解析 ``--seed``：``0x`` 前缀按十六进制，其余按十进制；必须是 u64。"""
    raw = str(text if text is not None else "").strip().replace("_", "")
    if not raw:
        raise ValueError("没有提供 --seed")
    try:
        value = int(raw, 16) if raw.lower().startswith("0x") else int(raw, 10)
    except ValueError as e:
        raise ValueError(f"{raw!r} 不是十六进制/十进制整数") from e
    if not 0 <= value < 2 ** 64:
        raise ValueError(f"{raw!r} 超出 0..2^64-1")
    return value


def _live_push_error(a, message: str, hint: str = "", code: int = 1,
                     error_code: str = "") -> int:
    """统一失败输出：``--json`` 时 stdout 仍是可解析的 JSON，人读模式走 stderr。"""
    if getattr(a, "json", False):
        payload = {"ok": False, "error": message, "hint": hint}
        if error_code:
            payload["code"] = error_code
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print(message, file=sys.stderr)
        if hint:
            print(hint, file=sys.stderr)
    return code


# 能力表：名字 → (风险, 类别)。类别只决定"需要什么条件才可用"：
#   read         agent 可达即可（未验证 build 也只读）
#   write        agent 可达 **且** build.write_allowed
#   experimental 布局/位域尚未确认，即使条件满足也保持关闭
_AGENT_CAPABILITIES: dict[str, tuple[str, str]] = {
    "player.ua": ("low", "read"),
    "player.position": ("low", "read"),
    "player.stats": ("low", "read"),
    "system.current": ("low", "read"),
    "planet.current": ("low", "read"),
    "ship.read": ("low", "read"),
    "ship.write_seed": ("mid", "write"),
    "ship.write_class": ("mid", "write"),
    "ship.write_parts": ("high", "experimental"),
    "teleport.system": ("high", "write"),
    "teleport.position": ("high", "write"),
    "scan.planet": ("mid", "write"),
    "debug.flags": ("high", "experimental"),
}

_AGENT_EXPERIMENTAL_REASONS = {
    "ship.write_parts": "实验性：部件数组布局未确认",
    "debug.flags": "实验性：位域未验证",
}


def _module_available(name: str) -> bool:
    """只查模块是否存在，不 import（pymhf 首次 import 可能很慢）。"""
    try:
        import importlib.util

        return importlib.util.find_spec(name) is not None
    except Exception:                                      # noqa: BLE001
        return False


def _runtime_ready(python_path, runtime_dir) -> bool:
    """pymhf/NMSpy 可导入，或 agent runtime 目录已经存在。"""
    if python_path:
        return True
    if _module_available("pymhf") and _module_available("nmspy"):
        return True
    try:
        return bool(runtime_dir) and Path(runtime_dir).exists()
    except OSError:
        return False


def _agent_probe(timeout: float = 1.5) -> dict:
    """真实探测游戏内 agent（只读）：Mod 文件、runtime、本机 HTTP hello。

    agent 是 pymhf 注入的 **Python Mod**（``starforge_agent.py`` + NMSpy），不是 DLL。
    连接探测只发一个 ``GET /hello``，超时默认 1.5s，绝不写游戏状态。
    """
    info: dict = {"installed": False, "installed_path": "", "runtime": False,
                  "runtime_python": "", "runtime_dir": "", "reachable": False,
                  "base": "", "hello": {}, "error": ""}
    try:
        from .live import agent_install
    except Exception as e:                                 # noqa: BLE001
        info["error"] = f"无法加载 agent 安装模块：{type(e).__name__}: {e}"
        return info

    try:
        mod = agent_install.installed_mod()
        info["installed_path"] = str(mod)
        info["installed"] = bool(mod.exists())
    except Exception as e:                                 # noqa: BLE001
        info["error"] = f"无法检查 agent Mod 文件：{type(e).__name__}: {e}"

    py = None
    rdir = ""
    try:
        py = agent_install.runtime_python()
        rdir = str(agent_install.runtime_dir())
        info["runtime_python"] = str(py) if py else ""
        info["runtime_dir"] = rdir
    except Exception as e:                                 # noqa: BLE001
        tail = f"无法检查 agent 运行时：{type(e).__name__}: {e}"
        info["error"] = f"{info['error']}；{tail}" if info["error"] else tail
    info["runtime"] = _runtime_ready(py, rdir)

    try:
        from .live import agent_client

        client = agent_client.AgentClient(timeout=timeout)
        info["base"] = str(getattr(client, "base", "") or "")
        try:
            hello = client.hello()
        except Exception as e:                             # noqa: BLE001
            info["error"] = f"{type(e).__name__}: {e}"
        else:
            info["reachable"] = True
            info["hello"] = hello if isinstance(hello, dict) else {"value": hello}
    except Exception as e:                                 # noqa: BLE001
        info["error"] = f"无法创建 agent 客户端：{type(e).__name__}: {e}"
    return info


def _agent_capabilities(*, reachable: bool, write_allowed: bool, status: str) -> dict:
    """按真实 agent/build 状态推导能力表（不是常量）。"""
    disconnected = "agent 未运行/未连接"
    build_block = f"build 未校准（status={status or 'unknown'}），只允许只读"
    table: dict[str, dict] = {}
    for name, (risk, kind) in _AGENT_CAPABILITIES.items():
        if not reachable:
            available, reason = False, disconnected
        elif kind in ("write", "experimental") and not write_allowed:
            available, reason = False, build_block
        elif kind == "experimental":
            available, reason = False, _AGENT_EXPERIMENTAL_REASONS[name]
        else:
            available, reason = True, ""
        table[name] = {"available": available, "reason": reason, "risk": risk}
    return table


def cmd_agent(a) -> int:
    """游戏内代理的握手/自检入口。

    agent 是 pymhf + NMSpy 的 Python Mod：``agent hello`` 真实检查 Mod 文件、
    runtime 与本机 HTTP，并按 build 闸门推导 13 项能力表。未连接时返回 5，
    已连接返回 0；所有探测只读。
    """
    import json as _json
    from .live import build, mem

    probe = _agent_probe()
    attached = False
    pid = None
    attach_error = ""
    if not mem.IS_WINDOWS:
        note = "非 Windows：内存通道不可用（存档写回与符文浮窗不受影响）"
    else:
        try:
            with mem.attach("NMS.exe") as proc:
                attached = True
                pid = getattr(proc, "pid", None)
        except Exception as e:                             # noqa: BLE001
            attach_error = f"{type(e).__name__}: {e}"
        if not attached:
            note = f"未连上游戏进程：{attach_error or '没有找到 NMS.exe'}"
            if probe["reachable"]:
                note += "；但本机 agent HTTP 可达（游戏可能尚未载入存档或进程权限不足）"
        elif probe["reachable"]:
            note = (f"已连上游戏进程 pid={pid if pid is not None else '?'}；"
                    "agent 已连接（pymhf + NMSpy 的 Python Mod）")
        elif not probe["installed"]:
            note = (f"已连上游戏进程 pid={pid if pid is not None else '?'}；agent 未安装"
                    "（它是 pymhf + NMSpy 的 Python Mod，不是 DLL；请在「游戏内」页安装）")
        elif not probe["runtime"]:
            note = (f"已连上游戏进程 pid={pid if pid is not None else '?'}；agent Mod 已安装"
                    f"（{probe['installed_path']}），但 pymhf/NMSpy 运行时缺失")
        else:
            note = (f"已连上游戏进程 pid={pid if pid is not None else '?'}；agent Mod 已安装"
                    "但未连接（需要注入/启动 pymhf agent）")

    try:
        build_info = build.summary()
    except Exception as e:                                 # noqa: BLE001
        build_info = {"version": "", "status": "unknown", "verified": False,
                      "write_allowed": False,
                      "reason": f"无法确认游戏 build：{type(e).__name__}: {e}；只允许只读能力"}
    status = str(build_info.get("status") or "unknown")
    write_allowed = bool(build_info.get("write_allowed"))
    table = _agent_capabilities(reachable=probe["reachable"],
                                write_allowed=write_allowed, status=status)
    rep = {"proto": 1, "agent": probe, "attached": attached, "note": note,
           "capabilities": table,
           "build": {"id": build_info.get("build_id") or "",
                     "version": build_info.get("version") or "",
                     "status": status,
                     "verified": bool(build_info.get("verified")),
                     "write_allowed": write_allowed},
           "next": ("按 docs/AGENT.md 第 8 节「故障排查表」回报；agent 是 pymhf + NMSpy "
                    "的 Python Mod，连接后再按 build 闸门决定只读/写入")}
    print(_json.dumps(rep, ensure_ascii=False, indent=1))
    action = getattr(a, "action", "hello")
    return 0 if action != "hello" else (0 if probe["reachable"] else 5)


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
    Qt/PySide6 原生界面、上游数据层、GAMEDATA（是否含 Gagarin/ships/catalog.txt）。
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
    # GAMEDATA：目录存在不等于可用（Steam 原版也有 GAMEDATA，但没有 Gagarin 的 catalog.txt）
    try:
        s = settings.current()
        gd = s.gamedata_resolved()
        if gd:
            out["gamedata"] = {"path": str(gd), "valid": True,
                               "reason": "含 Gagarin/ships/catalog.txt"}
        else:
            configured = s.gamedata_dir or ""
            reason = ("配置的目录缺少 Gagarin/ships/catalog.txt，自动发现也没有可用项"
                      if configured else
                      "未配置，且自动发现找不到含 Gagarin/ships/catalog.txt 的目录")
            out["gamedata"] = {"path": configured, "valid": False, "reason": reason}
            out["notes"].append(
                "GAMEDATA 无效（部件目录/搜索/3D/缩略图会失败）→ 在设置里把数据目录指向"
                "含 Gagarin/ships/catalog.txt 的 GAMEDATA，或设置环境变量 STARFORGE_GAMEDATA")
    except Exception as e:                                 # noqa: BLE001
        out["gamedata"] = {"path": "", "valid": False, "reason": f"{type(e).__name__}: {e}"}
        out["notes"].append(
            "GAMEDATA 检查失败 → 在设置里确认数据目录（需含 Gagarin/ships/catalog.txt）")
    optional = {"capstone"}
    required_ok = all(v == "ok" for k, v in out["deps"].items() if k not in optional)
    # 数据目录属于"用户环境"，不是运行时缺陷：缺它只降低能力（搜索/3D/缩略图不可用），
    # 不该让 doctor 整体失败——CI/干净机器本来就没有游戏数据。用 data_ready 单独表达。
    out["data_ready"] = bool(out["gamedata"].get("valid"))
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

    p = sub.add_parser("live", help="实时通道（probe 只读诊断 / push 写入模板槽）")
    p.add_argument("action", choices=["probe", "push"], nargs="?", default="probe")
    try:
        from .live.exml import manifest as _template_manifest

        _ship_types = sorted({e["type"] for e in _template_manifest()})
    except Exception:                                      # noqa: BLE001
        _ship_types = None                                 # 命令里再报可读错误
    p.add_argument("--type", choices=_ship_types,
                   help="模板船型：" + (", ".join(_ship_types) if _ship_types else "读取清单失败"))
    p.add_argument("--seed", help="外观种子：0x 前缀十六进制或十进制（u64）")
    p.add_argument("-y", "--yes", "--confirm", dest="yes", action="store_true",
                   help="确认写游戏内存（只写 8 字节模板种子，不改存档）")
    p.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    p.set_defaults(func=cmd_live)

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
