#!/usr/bin/env python3
"""在 Windows 上调用 PyInstaller，并给 COLLECT 的复制加短暂重试。

背景：Windows Defender 会短暂锁定刚写出的 DLL，PyInstaller 的 COLLECT 直接
``shutil.copyfile`` 时会偶发 ``PermissionError: ... MSVCP140.dll``（同一个源文件
用 PowerShell/Python 手工复制却正常）。CI 上一般不会遇到，本地打包会被打断。

这个包装只影响打包过程，不改变 PyInstaller 的收集逻辑：

    python packaging/pyinstaller_build.py packaging/starforge.spec
    python packaging/pyinstaller_build.py --noconfirm --clean packaging/starforge.spec
"""
from __future__ import annotations

import shutil
import sys
import time

_RETRIES = 8
_original_copyfile = shutil.copyfile


def _copyfile_with_retry(src, dst, *, follow_symlinks=True):
    delay = 0.05
    for attempt in range(_RETRIES):
        try:
            return _original_copyfile(src, dst, follow_symlinks=follow_symlinks)
        except PermissionError:
            if attempt == _RETRIES - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 2.0)


def main(argv: list[str] | None = None) -> int:
    shutil.copyfile = _copyfile_with_retry
    # PyInstaller 在调用 run() 之后才会解析命令行；这里保持参数原样。
    from PyInstaller.__main__ import run

    return run(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
