"""单实例锁：Shipwright 没有这一环，公开项目必须有（两个实例同时写存档 = 必然出事）。

实现：`~/.starforge/instance.lock` 存 PID；启动时若存在且 PID 仍存活则拒绝启动，否则接管。
"""
from __future__ import annotations

import os
import sys

from . import paths


class AlreadyRunning(RuntimeError):
    def __init__(self, pid: int):
        super().__init__(f"已有实例在运行（PID {pid}）")
        self.pid = pid


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class InstanceLock:
    def __init__(self):
        self.path = paths.app_home() / "instance.lock"
        self.held = False

    def acquire(self) -> "InstanceLock":
        if self.path.exists():
            try:
                pid = int(self.path.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if pid and pid != os.getpid() and _alive(pid):
                raise AlreadyRunning(pid)
        self.path.write_text(str(os.getpid()))
        self.held = True
        return self

    def release(self) -> None:
        if not self.held:
            return
        try:
            if self.path.exists() and self.path.read_text().strip() == str(os.getpid()):
                self.path.unlink()
        except OSError:
            pass
        self.held = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False
