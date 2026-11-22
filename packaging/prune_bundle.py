#!/usr/bin/env python3
"""裁剪 PyInstaller onedir 产物里确定不需要的 Qt/numpy/unicorn 冗余。

这个脚本只删除“运行时不会加载”的开发/静态文件和未使用 Qt 模块，不碰业务
代码。release.yml 在 PyInstaller 之后调用：

    python packaging/prune_bundle.py dist/starforge/_internal

默认删除 opengl32sw.dll（软件 OpenGL 兜底，约 20 MB）；需要“安全模式”软件
渲染时加 --keep-software-opengl。

删除项与依据见 docs/SIZE-BUDGET.md。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

QT_PLUGIN_DIRS = (
    "designer", "qmltooling", "sqldrivers", "tls", "networkinformation",
    "networkaccess", "vectorimageformats", "platforminputcontexts", "generic",
    "iconengines",
)
QT_DLLS = (
    "Qt6Svg.dll", "Qt6Network.dll", "Qt6Qml.dll", "Qt6QmlModels.dll",
    "Qt6QmlCompiler.dll", "Qt6Quick.dll", "Qt6Quick3D.dll",
    "Qt6QuickControls2.dll", "Qt6QuickTemplates2.dll", "Qt6Designer.dll",
    "Qt6DesignerComponents.dll", "Qt6Help.dll", "Qt6Sql.dll", "Qt6Test.dll",
    "Qt6Multimedia.dll", "Qt6Charts.dll", "Qt6DataVisualization.dll",
    "Qt6Bluetooth.dll", "Qt6Nfc.dll", "Qt6SerialPort.dll", "Qt6UiTools.dll",
    "Qt6Scxml.dll", "Qt6StateMachine.dll", "Qt6WebEngineCore.dll",
    "Qt6WebEngineWidgets.dll", "Qt6WebEngineQuick.dll", "pyside6qml.abi3.dll",
)
NUMPY_DIRS = ("f2py", "distutils", "_core/include")
DEV_FILE_SUFFIXES = {".pyc", ".pyo", ".pdb", ".pyi", ".lib", ".a"}


def _size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                pass
    return total


class Pruner:
    def __init__(self) -> None:
        self.removed = 0
        self.items = 0

    def path(self, path: Path) -> None:
        if not path.exists():
            return
        size = _size(path)
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as exc:
            print(f"  跳过 {path}：{exc}")
            return
        self.removed += size
        self.items += 1


def prune(internal: Path, *, keep_software_opengl: bool = False) -> Pruner:
    p = Pruner()

    # unicorn 运行时只需要 Python 包 + lib/unicorn.dll。
    p.path(internal / "unicorn" / "include")
    for lib in (internal / "unicorn" / "lib").glob("*.lib"):
        p.path(lib)

    # 界面文案在 Python/QSS 里，应用没有安装 QTranslator。
    p.path(internal / "PySide6" / "translations")
    p.path(internal / "PySide6" / "qml")
    for name in QT_PLUGIN_DIRS:
        p.path(internal / "PySide6" / "plugins" / name)

    imageformats = internal / "PySide6" / "plugins" / "imageformats"
    if imageformats.is_dir():
        for dll in imageformats.glob("*.dll"):
            if dll.name != "qico.dll":
                p.path(dll)
    platforms = internal / "PySide6" / "plugins" / "platforms"
    if platforms.is_dir():
        for dll in platforms.glob("*.dll"):
            if dll.name not in {"qwindows.dll", "qoffscreen.dll"}:
                p.path(dll)

    # 被 Qt 插件依赖带回的模块 DLL；Python 侧也已在 spec 里 exclude。
    for name in QT_DLLS:
        for hit in internal.rglob(name):
            p.path(hit)

    if not keep_software_opengl:
        p.path(internal / "PySide6" / "opengl32sw.dll")
        p.path(internal / "opengl32sw.dll")

    # numpy：--collect-all 时代的遗留兜底；新 spec 已不收集，保留以防回退。
    for rel in NUMPY_DIRS:
        p.path(internal / "numpy" / rel)
    numpy = internal / "numpy"
    if numpy.is_dir():
        for tests in numpy.rglob("tests"):
            p.path(tests)
    for suffix in (".pyi", ".lib", ".a"):
        for hit in numpy.rglob(f"*{suffix}"):
            p.path(hit)

    # 字节码/调试符号（PyInstaller 正常不会带，保险起见）。
    for cache in internal.rglob("__pycache__"):
        p.path(cache)
    for suffix in (".pyc", ".pyo", ".pdb"):
        for hit in internal.rglob(f"*{suffix}"):
            p.path(hit)

    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="裁剪 PyInstaller onedir 的 Qt/numpy/unicorn 冗余")
    ap.add_argument("internal", nargs="?", default="dist/starforge/_internal",
                    help="PyInstaller 的 _internal 目录")
    ap.add_argument("--keep-software-opengl", action="store_true",
                    help="保留 opengl32sw.dll（无 GPU/远程桌面时的软件 OpenGL 兜底）")
    a = ap.parse_args(argv)

    internal = Path(a.internal)
    if not internal.is_dir():
        print(f"找不到 _internal 目录：{internal}", file=sys.stderr)
        return 2
    before = _size(internal)
    p = prune(internal, keep_software_opengl=a.keep_software_opengl)
    after = _size(internal)
    print(f"裁剪 _internal：{before / 1024 / 1024:.1f} MiB -> "
          f"{after / 1024 / 1024:.1f} MiB（释放 {p.removed / 1024 / 1024:.1f} MiB，"
          f"{p.items} 项）")
    if not a.keep_software_opengl:
        print("已移除 opengl32sw.dll（安全模式 3D 将退回服务端 PNG）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
