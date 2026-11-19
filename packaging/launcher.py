"""Windowed launcher for the Windows release.

Double-clicking ``starforge.exe`` starts the console CLI as a hidden child
process, so the native Qt window appears without a console flash.  When
arguments are supplied (``starforge.exe selftest`` / ``serve`` / ...), they are
forwarded to ``starforge-cli.exe`` and its exit code is returned.

Keeping the console build as a separate executable preserves CLI output and
avoids the Windows Terminal limitation of ``--hide-console``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_CREATE_NO_WINDOW = 0x08000000


def _show_error(text: str) -> None:
    if os.name != "nt":
        print(text, file=sys.stderr)
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "Starforge", 0x10)
    except Exception:                                      # noqa: BLE001
        pass


def main() -> int:
    base = Path(sys.executable).resolve().parent
    cli = base / "starforge-cli.exe"
    if not cli.exists():
        _show_error(f"找不到 starforge-cli.exe：\n{cli}\n\n请重新解压完整安装包。")
        return 2

    args = list(sys.argv[1:])
    if not args:
        args = ["app"]
    try:
        proc = subprocess.Popen(
            [str(cli), *args],
            cwd=str(base),
            close_fds=True,
            creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:                                 # noqa: BLE001
        _show_error(f"启动 Starforge 失败：\n{type(e).__name__}: {e}")
        return 3
    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
