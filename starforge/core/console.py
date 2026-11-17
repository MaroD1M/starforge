"""控制台编码兜底。

Windows 的默认控制台编码常是 cp1252/cp936，直接 print 中文会抛 UnicodeEncodeError
（CI 第一次构建就是这么挂的）。这里在进程启动时把标准流切成 UTF-8，
无法编码的字符降级为替代符而不是崩溃。
"""
from __future__ import annotations

import io
import os
import sys


def setup_console() -> None:
    """把标准流切成 UTF-8；**没有标准流时（PyInstaller --windowed）换成空流**。

    Windows 无控制台打包时 sys.stdout / sys.stderr 是 None，任何 print() 都会抛异常。
    这里统一兜住，命令行版不受影响。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except Exception:                              # noqa: BLE001
                pass
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
        except (AttributeError, ValueError, OSError):
            try:
                setattr(sys, name, io.TextIOWrapper(stream.buffer, encoding="utf-8",
                                                    errors="replace", line_buffering=True))
            except Exception:                                          # noqa: BLE001
                pass


def safe(text: object) -> str:
    """给"一定要打印出来"的场景用：不能编码的字符替换掉，绝不抛异常。"""
    s = str(text)
    try:
        s.encode(sys.stdout.encoding or "utf-8")
        return s
    except (UnicodeEncodeError, LookupError):
        return s.encode(sys.stdout.encoding or "utf-8", "replace").decode(
            sys.stdout.encoding or "utf-8", "replace")
