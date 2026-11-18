"""本机 agent HTTP 客户端（pymhf Mod 暴露的端点）。

游戏内 Mod 由 ``starforge.agent`` 安装/启动；它在 pymhf 的 HTTP API 上监听
``http://127.0.0.1:5000/StarforgeAgent``。本模块只做 HTTP 调用，不导入 nmspy，
也不直接碰游戏内存。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:5000/StarforgeAgent"


class AgentError(RuntimeError):
    pass


class AgentClient:
    def __init__(self, base: str = DEFAULT_BASE, timeout: float = 5.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    # ---------------------------------------------------------------- HTTP

    def _call(self, path: str, method: str = "GET", params: dict | None = None,
              timeout: float | None = None) -> dict:
        url = self.base + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            url += "?" + urllib.parse.urlencode(clean)
        req = urllib.request.Request(url, method=method)
        # 本机 agent 不经过系统代理（否则 http_proxy 会把 127.0.0.1 转给代理）
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=timeout or self.timeout) as r:
                data = r.read()
        except urllib.error.URLError as e:
            raise AgentError(f"连不上游戏内 agent：{e.reason}") from e
        except TimeoutError as e:
            raise AgentError("agent 响应超时") from e
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError as e:
            raise AgentError(f"agent 返回的不是 JSON：{data[:120]!r}") from e

    # ---------------------------------------------------------------- 能力

    def ping(self, timeout: float = 2.0) -> bool:
        try:
            self._call("/hello", timeout=timeout)
            return True
        except Exception:                                  # noqa: BLE001
            return False

    def hello(self) -> dict:
        return self._call("/hello")

    def player(self) -> dict:
        return self._call("/player")

    def system(self) -> dict:
        return self._call("/system")

    def planet(self) -> dict:
        return self._call("/planet")

    def planet_scan(self) -> dict:
        return self._call("/planet/scan")

    def ships(self) -> dict:
        return self._call("/ships")

    # ---------------------------------------------------------------- 写

    def teleport(self, glyphs: str, galaxy: int | None = None) -> dict:
        return self._call("/teleport", method="PUT",
                          params={"glyphs": glyphs, "galaxy": galaxy if galaxy is not None else -1},
                          timeout=15.0)

    def teleport_portal(self, glyphs: str, galaxy: int | None = None) -> dict:
        return self._call("/teleport/portal", method="PUT",
                          params={"glyphs": glyphs, "galaxy": galaxy if galaxy is not None else -1},
                          timeout=15.0)

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
            "teleport": lambda: self.teleport(params.get("glyphs", ""), params.get("galaxy")),
            "teleport.portal": lambda: self.teleport_portal(
                params.get("glyphs", ""), params.get("galaxy")),
            "scan": lambda: self.scan(params.get("mode", "read")),
            "scan.instant": lambda: self.scan_instant(bool(params.get("on", True))),
            "restore": self.restore,
        }.get(cmd)
        if fn is None:
            raise AgentError(f"未知 agent 命令：{cmd}")
        return fn()
