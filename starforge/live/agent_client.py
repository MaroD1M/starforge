"""本机 agent HTTP 客户端（pymhf Mod 暴露的端点）。

游戏内 Mod 由 ``starforge.agent`` 安装/启动；它在 pymhf 的 HTTP API 上监听
``http://127.0.0.1:5000/StarforgeAgent``。本模块只做 HTTP 调用，不导入 nmspy，
也不直接碰游戏内存。

``launch`` 会把一次性 token 和实际端口写进 ``~/.starforge/agent/state.json``。
客户端默认从该文件读取 base/token，并把 token 作为查询参数附加到**每个**请求。
限制：pymhf 的 endpoint 没有稳定暴露 request header 的接口，所以 token 走
query（会出现在本机 URL 和日志里，但只绑定 127.0.0.1，且每次启动都会更换）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_PORT = 5000
DEFAULT_BASE = f"http://127.0.0.1:{DEFAULT_PORT}/StarforgeAgent"
STATE_NAME = "state.json"


def agent_home() -> Path:
    from ..core import paths

    d = paths.app_home() / "agent"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_file() -> Path:
    return agent_home() / STATE_NAME


def base_for_port(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}/StarforgeAgent"


def read_state() -> dict:
    """读取启动状态；损坏/不存在时返回空 dict，绝不抛异常。"""
    try:
        data = json.loads(state_file().read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def write_state(data: dict) -> Path:
    """原子写私有状态文件（Linux/macOS 上 chmod 0600）。"""
    path = state_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def clear_state() -> None:
    try:
        state_file().unlink()
    except OSError:
        pass


class AgentError(RuntimeError):
    pass


class AgentClient:
    def __init__(self, base: str | None = None, timeout: float = 5.0,
                 token: str | None = None):
        state = read_state() if (base is None or token is None) else {}
        self.base = (base or state.get("base") or DEFAULT_BASE).rstrip("/")
        self.token = token if token is not None else str(state.get("token") or "")
        self.timeout = timeout

    # ---------------------------------------------------------------- HTTP

    def _call(self, path: str, method: str = "GET", params: dict | None = None,
              timeout: float | None = None) -> dict:
        url = self.base + path
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        if self.token:
            # 见模块说明：pymhf 没有稳定的 header 读取接口，token 走 query。
            clean["token"] = self.token
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
        req = urllib.request.Request(url, method=method)
        # 本机 agent 不经过系统代理（否则 http_proxy 会把 127.0.0.1 转给代理）
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=timeout or self.timeout) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            # 保留状态码，调用方要靠 405 判断"方法不对"并回退。
            raise AgentError(f"agent 返回 HTTP {e.code}：{e.reason}") from e
        except urllib.error.URLError as e:
            raise AgentError(f"连不上游戏内 agent：{e.reason}") from e
        except TimeoutError as e:
            raise AgentError("agent 响应超时") from e
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError as e:
            raise AgentError(f"agent 返回的不是 JSON：{data[:120]!r}") from e

    def _read(self, path: str, params: dict | None = None,
              timeout: float | None = None) -> dict:
        """读端点：优先 GET；405 时回退 PUT。

        背景：pymhf 的 `@endpoint` 在**没有显式声明 method** 时会把路由注册成 PUT
        （实测 build 185034 + pymhf 0.2.5 的 openapi.json 里 11 个端点全是 put）。
        新版 agent 会给只读端点显式标 GET，这里两种都兼容，避免版本错位就全挂。
        """
        try:
            return self._call(path, method="GET", params=params, timeout=timeout)
        except AgentError as e:
            if "HTTP 405" not in str(e):
                raise
            return self._call(path, method="PUT", params=params, timeout=timeout)

    # ---------------------------------------------------------------- 能力

    def ping(self, timeout: float = 2.0) -> bool:
        try:
            self._read("/hello", timeout=timeout)
            return True
        except Exception:                                  # noqa: BLE001
            return False

    def hello(self) -> dict:
        return self._read("/hello")

    def player(self) -> dict:
        return self._read("/player")

    def system(self) -> dict:
        return self._read("/system")

    def planet(self) -> dict:
        return self._read("/planet")

    def planet_scan(self) -> dict:
        return self._read("/planet/scan")

    def ships(self) -> dict:
        return self._read("/ships")

    def multitool(self) -> dict:
        return self._read("/multitool")

    def freighter(self) -> dict:
        return self._read("/freighter")

    def pets(self) -> dict:
        return self._read("/pets")

    # ---------------------------------------------------------------- 热重载

    def admin_reload(self) -> dict:
        """让进程内的 agent 重新加载自身（改完代码不必退出游戏）。"""
        return self._call("/admin/reload", method="PUT", timeout=10.0)

    # ---------------------------------------------------------------- 写

    def teleport(self, glyphs: str, galaxy: int | None = None) -> dict:
        return self._call("/teleport", method="PUT",
                          params={"glyphs": glyphs, "galaxy": galaxy if galaxy is not None else -1},
                          timeout=15.0)

    def teleport_portal(self, glyphs: str, galaxy: int | None = None,
                        stage: str = "prepare_warp") -> dict:
        return self._call("/teleport/portal", method="PUT",
                          params={"glyphs": glyphs,
                                  "galaxy": galaxy if galaxy is not None else -1,
                                  "stage": stage},
                          timeout=25.0)

    def scan(self, mode: str = "read") -> dict:
        return self._call("/scan", method="PUT", params={"mode": mode}, timeout=15.0)

    def scan_instant(self, on: bool = True) -> dict:
        return self._call("/scan/instant", method="PUT", params={"on": 1 if on else 0})

    def restore(self) -> dict:
        return self._call("/restore", method="PUT", timeout=15.0)

    def call(self, cmd: str, **params: Any) -> dict:
        """受限白名单：界面只能通过这些命令，未知命令本地拒绝。"""
        fn = {
            "hello": self.hello, "player": self.player, "system": self.system,
            "planet": self.planet, "planet.scan": self.planet_scan, "ships": self.ships,
            "multitool": self.multitool, "freighter": self.freighter, "pets": self.pets,
            "teleport": lambda: self.teleport(params.get("glyphs", ""), params.get("galaxy")),
            "teleport.portal": lambda: self.teleport_portal(
                params.get("glyphs", ""), params.get("galaxy"),
                params.get("stage") or "prepare_warp"),
            "scan": lambda: self.scan(params.get("mode", "read")),
            "scan.discover": lambda: self.scan("discover"),
            "scan.instant": lambda: self.scan_instant(bool(params.get("on", True))),
            "restore": self.restore,
            "admin.reload": self.admin_reload,
        }.get(cmd)
        if fn is None:
            raise AgentError(f"未知 agent 命令：{cmd}")
        return fn()
