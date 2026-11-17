"""桌面应用外壳：一个真正的原生窗口，不用浏览器。

实现方式（与 NMS-Shipwright 同一条路）：本地起 Flask → 用 pywebview 开一个原生窗口
（Windows 上走 Edge WebView2）→ 窗口里跑的就是我们自己的 HTML/JS。

好处：
  · 不出现浏览器地址栏/标签页，看起来就是一个应用；
  · 通过 pywebview 的 JS API 提供**原生目录/文件选择框**，用户不用手打路径；
  · 窗口尺寸/位置记忆；关闭即退出（后台 Flask 线程是 daemon）。
若 pywebview 不可用（没装/无 WebView2），自动退回浏览器并给出说明。
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import webbrowser

from .core import log, paths, settings, strings

log = log.get("desktop")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(port: int, timeout: float = 20.0) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:                        # noqa: BLE001
            time.sleep(0.15)
    return False


class _Api:
    """暴露给页面的原生能力：选目录、选文件、打开目录、窗口控制。"""

    def __init__(self, window_getter=None):
        self._get_window = window_getter

    def pick_folder(self, kind: str = "game") -> str:
        """原生"选择文件夹"对话框；返回绝对路径或空串。"""
        w = self._get_window() if self._get_window else None
        if w is None:
            return ""
        try:
            res = w.create_file_dialog(w.FOLDER_DIALOG)
        except Exception as e:                   # noqa: BLE001
            log.debug("目录选择失败：%s", e)
            return ""
        if not res:
            return ""
        path = res[0] if isinstance(res, (list, tuple)) else str(res)
        # 选完顺手写进设置，省得用户再点保存
        key = {"game": "game_dir", "saves": "saves_dir", "gamedata": "gamedata_dir"}.get(kind)  # "any" → 不写设置
        if key:
            settings.update(**{key: path})
        return path

    def pick_file(self, kind: str = "save") -> str:
        w = self._get_window() if self._get_window else None
        if w is None:
            return ""
        try:
            res = w.create_file_dialog(w.OPEN_DIALOG, file_types=("存档 (*.hg;*.json)", "所有文件 (*.*)"))
        except Exception as e:                   # noqa: BLE001
            log.debug("文件选择失败：%s", e)
            return ""
        if not res:
            return ""
        path = res[0] if isinstance(res, (list, tuple)) else str(res)
        if kind == "save" and path:
            settings.update(saves_dir=os.path.dirname(path))
        return path

    def open_path(self, path: str) -> bool:
        """在资源管理器里打开目录（Windows: explorer）。"""
        try:
            if not path or not os.path.exists(path):
                return False
            if os.name == "nt":
                os.startfile(path)                       # noqa: S606
            else:
                webbrowser.open("file://" + os.path.abspath(path))
            return True
        except Exception as e:                            # noqa: BLE001
            log.debug("打开目录失败：%s", e)
            return False

    def overlay_command(self, glyphs: str) -> list[str]:
        """构造"符文置顶窗口"的启动命令（打包版与源码版路径不同）。"""
        import sys as _sys
        if getattr(_sys, "frozen", False):
            return [_sys.executable, "glyph-overlay", str(glyphs), "--click-through"]
        return [_sys.executable, "-m", "starforge", "glyph-overlay", str(glyphs), "--click-through"]

    def launch_overlay(self, glyphs: str) -> bool:
        """开一个独立的置顶符文窗口（不注入游戏，Esc 关闭）。"""
        import subprocess
        import sys as _sys
        try:
            cmd = self.overlay_command(glyphs)
            kwargs = {"close_fds": True}
            if os.name == "nt":
                kwargs["creationflags"] = 0x00000008      # DETACHED_PROCESS
            subprocess.Popen(cmd, **kwargs)
            log.info("已启动符文置顶窗口：%s", glyphs)
            return True
        except Exception as e:                            # noqa: BLE001
            log.warning("启动置顶窗口失败：%s", e)
            return False

    def info(self) -> dict:
        return {"version": __import__("starforge").__version__,
                "home": str(paths.app_home()),
                "platform": "windows" if os.name == "nt" else os.name}


def _window_state_file():
    return paths.app_home() / "window.json"


def _load_state() -> dict:
    try:
        return json.loads(_window_state_file().read_text("utf-8"))
    except Exception:                                     # noqa: BLE001
        return {}


def _save_state(state: dict) -> None:
    try:
        _window_state_file().write_text(json.dumps(state), "utf-8")
    except OSError:
        pass


def run(port: int = 0, width: int = 1440, height: int = 900, debug: bool = False) -> int:
    """启动原生窗口。失败时退回浏览器并返回 3。"""
    from .web.app import create_app

    s = settings.current()
    port = port or s.port or _free_port()
    app = create_app()
    t = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, threaded=True,
                                                use_reloader=False), daemon=True)
    t.start()
    if not _wait_ready(port, 25 if debug else 15):
        print("本地服务没起来，请看日志 ~/.starforge/logs/", file=__import__("sys").stderr)
        return 4

    url = f"http://127.0.0.1:{port}/"
    info = probe()
    if not info["available"]:
        log.warning("窗口不可用：%s", info["reason"])
    try:
        import webview
    except Exception as e:                                # noqa: BLE001
        log.warning("pywebview 不可用（%s），改用浏览器", e)
        print(f"没装 pywebview，已改用浏览器打开：{url}", file=__import__("sys").stderr)
        webbrowser.open(url)
        try:
            while True:                                    # 保持进程存活
                time.sleep(1)
        except KeyboardInterrupt:
            return 0

    state = _load_state()
    api = _Api()
    win = webview.create_window(
        strings.APP_TITLE, url,
        width=int(state.get("w") or width), height=int(state.get("h") or height),
        min_size=(1100, 720),
        background_color="#0a0c11",
        text_select=False,
        js_api=api,
    )
    api._get_window = lambda: win

    def _on_closed() -> None:
        try:
            _save_state({"w": win.width, "h": win.height})
        except Exception:                                  # noqa: BLE001
            pass

    win.events.closed += _on_closed
    try:
        webview.start(debug=debug, http_server=False)       # 阻塞直到窗口关闭
    except Exception as e:                                 # noqa: BLE001
        log.error("窗口启动失败：%s", e)
        print(f"窗口启动失败（{e}），已改用浏览器：{url}", file=__import__("sys").stderr)
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
    return 0


def probe() -> dict:
    """窗口能力自检：pywebview / pythonnet（Windows Edge 后端需要）/ WebView2 运行时。"""
    out = {"pywebview": False, "pythonnet": None, "windows": os.name == "nt",
           "available": False, "reason": ""}
    try:
        import webview
        out["pywebview"] = True
        out["version"] = getattr(webview, "__version__", "")
    except Exception as e:                                 # noqa: BLE001
        out["reason"] = f"没装 pywebview（{type(e).__name__}）"
        return out
    if os.name == "nt":
        try:
            import clr  # noqa: F401                     # pythonnet：Edge 渲染必需
            out["pythonnet"] = True
        except Exception:                                  # noqa: BLE001
            out["pythonnet"] = False
            out["reason"] = "缺少 pythonnet（Windows Edge 窗口需要；将退回浏览器）"
    out["available"] = out["pywebview"] and (out["pythonnet"] in (True, None))
    if out["available"]:
        out["reason"] = ""
    return out


def available() -> bool:
    return bool(probe()["available"])
