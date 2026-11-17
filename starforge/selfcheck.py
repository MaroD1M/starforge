"""端到端自检：一条命令验证整条链路（含"在存档副本上真实写入并回滚"）。

用法：
    python -m starforge selfcheck            # 全部（写入只发生在临时副本上）
    python -m starforge selfcheck --no-write # 跳过写入步骤

输出每一步的 耗时 / 结果 / 关键数字；任一步失败会给出可执行的下一步建议。
这一步不碰真实存档：写入测试先把 save.hg 复制到临时目录再动。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import traceback

from .core import log, paths, settings

log = log.get("selfcheck")


def _step(name: str, fn, critical: bool = True) -> dict:
    t0 = time.time()
    try:
        detail = fn()
        return {"name": name, "ok": True, "ms": int((time.time() - t0) * 1000),
                "detail": detail, "critical": critical}
    except Exception as e:                                  # noqa: BLE001
        log.debug("%s 失败：%s", name, traceback.format_exc())
        return {"name": name, "ok": False, "ms": int((time.time() - t0) * 1000),
                "detail": f"{type(e).__name__}: {e}", "critical": critical}


def _textures() -> str:
    from . import tex
    st = tex.status()
    return st["reason"]


def run(include_write: bool = True) -> dict:
    from . import glyphs, preview, render, search, system
    from .data import load_catalog, load_icons
    from .data.shipref import ShipRef
    from .save import library, writer

    steps: list[dict] = []
    state: dict = {}

    # 1) 只读数据
    steps.append(_step("部件目录 catalog", lambda: (
        lambda c: f"{len(c.ships)} 船型 / {c.stats['O']} 部件")(load_catalog())))
    steps.append(_step("部件图标 icons", lambda: (
        lambda i: f"{i.counts}")(load_icons())))

    # 2) 存档
    def _ships():
        p = library.resolve(None)
        ships, warns = library.open_ships(p)
        state["save"] = str(p)
        state["ships"] = ships
        return f"{len(ships)} 艘（{os.path.basename(p)}）" + (f"；警告 {len(warns)}" if warns else "")
    steps.append(_step("读存档", _ships))

    # 3) 搜索
    def _search():
        ship = "sentinel"
        if state.get("ships"):
            cand = [s for s in state["ships"] if s.type in search.SEARCHABLE]
            if cand:
                ship = cand[0].type
        cat = load_catalog()
        parts = cat.parts_of(ship) or ["_PIT_A"]
        part = parts[min(3, len(parts) - 1)]              # 取该船型的一个真实部件当条件
        res = search.run(search.SearchQuery(ship=ship, want=[part], avoid=[], look=None,
                                            limit=2, max_seeds=5_000_000, time_limit=12, workers=1))
        if not res:
            raise RuntimeError("3M 种子内没有命中（可放宽条件）")
        state["hit"] = res[0]
        return f"{ship} + {part} → {len(res)} 个（首个 {res[0]['seed']}）"
    steps.append(_step("搜索种子", _search))

    # 4) 预览 + glb
    def _preview():
        ref = ShipRef(**{k: state["hit"][k] for k in ("type", "seed", "parts") if k in state["hit"]})
        info = preview.build(ref, want_glb=True)
        if info.get("level") != "L1":
            raise RuntimeError(info.get("reason") or "未达到 L1（游戏目录没配好？）")
        path = preview.glb_for(ref)
        state["ref"] = ref
        return f"L1 {info.get('verts', 0)} 顶点 / {os.path.getsize(path) / 1e6:.1f} MB"
    steps.append(_step("3D 预览 + glb", _preview))

    # 5) 服务端缩略图
    steps.append(_step("缩略图 PNG", lambda: (
        lambda b: f"{len(b)} B")(render.ship_png(state["hit"]["type"], state["hit"]["seed"],
                                                 state["hit"].get("parts"), ("iso",), (260, 260)))))

    # 6) 符文
    def _glyph():
        from . import glyphs as g
        png = g.panel_png("1043FEE69929", tile=96)
        src = g.panel_payload("1043FEE69929")["source"]
        return f"{len(png)} B · 源={'游戏原图' if src == 'game' else '内置位图字体（缺 BC7 解码器或 pak）'}"
    steps.append(_step("符文面板", _glyph))

    # 7) 星系（需游戏）
    def _system():
        s = system.system(None, planets=True)
        return f"{s['ua']} · {s['planets']} 行星 · {len(s['ships'])} 船 · {s['elapsed_ms']} ms"
    steps.append(_step("星系生成", _system))

    # 8) 写入（只在副本上）
    if include_write:
        def _write():
            src = state.get("save")
            if not src:
                raise RuntimeError("没有可用的存档")
            tmpdir = tempfile.mkdtemp(prefix="starforge-selfcheck-")
            dst = os.path.join(tmpdir, os.path.basename(src))
            shutil.copy2(src, dst)
            ships, _ = library.open_ships(dst)
            target = next((s for s in ships if s.type in search.SEARCHABLE), None)
            if target is None:
                raise RuntimeError("副本里没有可换外观的船")
            newseed = "0x1234567890ABCDEF"
            old_write = settings.current().write_enabled
            settings.update(write_enabled=True)
            try:
                res = writer.apply_seed(dst, target.slot, ShipRef(type=target.type, seed=newseed), confirm=True)
            finally:
                settings.update(write_enabled=old_write)
            backup = res.get("backup")
            ok = res.get("verified") and os.path.exists(backup)
            shutil.rmtree(tmpdir, ignore_errors=True)
            if not ok:
                raise RuntimeError("写入/回读未通过")
            return f"槽位 {target.slot} 写入并读回成功，备份已生成"
        steps.append(_step("写入存档（副本）", _write))

    # 9) 实时通道：只报状态，不写
    def _live():
        from .live import mem, writer as live_writer
        st = live_writer.status()
        if not st["supported"]:
            return "不支持（非 Windows）——存档写回与符文浮窗仍可用"
        return f"Windows · {'已连上游戏' if st['running'] else '游戏未运行'}"
    steps.append(_step("实时通道状态", _live, critical=False))

    critical_ok = all(s["ok"] for s in steps if s["critical"])
    return {"ok": critical_ok, "steps": steps,
            "summary": f"{sum(1 for s in steps if s['ok'])}/{len(steps)} 步通过"}


def main() -> int:
    from .core import console
    console.setup_console()
    rep = run(include_write=True)
    print("starforge 自检")
    print("-" * 68)
    for s in rep["steps"]:
        mark = "✓" if s["ok"] else ("!" if not s["critical"] else "✗")
        print(f"{mark} {s['name']:16s} {s['ms']:>6d} ms  {s['detail']}")
    print("-" * 68)
    print(rep["summary"], "·", "全部关键步骤通过" if rep["ok"] else "有关键步骤失败")
    if not rep["ok"]:
        print("\n排障顺序：① 设置页确认游戏/存档/数据目录 → ② 运行 'python -m starforge selftest' "
              "→ ③ 看 ~/.starforge/logs/nmsforge.log")
    return 0 if rep["ok"] else 1
