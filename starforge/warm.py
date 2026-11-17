"""启动预热：把第一次操作最慢的几件事在后台先做掉。

实测（3.4 MB 存档 / 32 GB 游戏）：
  · 部件图标索引        0.01 s（已懒解码，不必预热）
  · pak 解包元数据      0.16 s（首次）
  · 单船 3D 几何解包    首次 5–6 s，之后 0.3–1.5 s   ← 值得预热
  · 系统生成            首次 5 s，之后 0.04 s        ← 值得预热

策略：后台线程按"轻 → 重"顺序跑，任一步失败只记日志，不打扰用户。
"""
from __future__ import annotations

import threading
import time

from .core import log, settings

log = log.get("warm")

_state = {"running": False, "done": False, "step": "", "ms": {}, "error": ""}
_lock = threading.Lock()


def status() -> dict:
    with _lock:
        return dict(_state)


def start(background: bool = True) -> dict:
    """启动预热（幂等）。返回当前状态。"""
    with _lock:
        if _state["running"] or _state["done"]:
            return dict(_state)
        _state.update(running=True, done=False, step="准备", error="")
    t = threading.Thread(target=_run, daemon=True, name="starforge-warm")
    if background:
        t.start()
        return status()
    _run()
    return status()


def _timed(step: str, fn) -> None:
    with _lock:
        _state["step"] = step
    t0 = time.time()
    try:
        fn()
        ms = int((time.time() - t0) * 1000)
        with _lock:
            _state["ms"][step] = ms
        log.info("预热 %s 完成 %d ms", step, ms)
    except Exception as e:                                  # noqa: BLE001
        with _lock:
            _state["error"] = f"{step}: {type(e).__name__}: {e}"
        log.info("预热 %s 跳过（%s）", step, type(e).__name__)


def _run() -> None:
    from .core import paths
    s = settings.current()

    def _metadata():
        if not s.game_dir:
            raise RuntimeError("没有游戏目录")
        import os
        os.environ.setdefault("NMS_DIR", s.game_dir)
        paths.ensure_shipwright_importable()
        from nms_procgen import emu
        emu.extract_metadata()

    def _one_model():
        """解一艘船的几何，把最贵的解包摊到启动时。"""
        if not s.game_dir:
            raise RuntimeError("没有游戏目录")
        from .data import load_catalog
        from .preview import build
        cat = load_catalog()
        ship = "fighter"
        parts = cat.parts_of(ship)[:1] or None
        build(__import__("starforge.data.shipref", fromlist=["ShipRef"]).ShipRef(
            type=ship, seed="0xE8C906B07D0E85D3", parts=parts), want_glb=False)

    def _system():
        if not s.game_dir:
            raise RuntimeError("没有游戏目录")
        from . import system
        if system.available():
            system.system(None)                              # 用存档当前位置热身

    _timed("pak 元数据", _metadata)
    _timed("单船几何", _one_model)
    _timed("系统生成", _system)
    with _lock:
        _state.update(running=False, done=True, step="完成")
