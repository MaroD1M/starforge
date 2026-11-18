#!/usr/bin/env python3
"""构建游戏内 agent 的独立 Python 运行时（Windows CI / 本机均可跑）。

产物：build/agent-runtime/python.exe + site-packages（NMSpy + pymhf[http_api]）
发布时把它放到 dist/starforge/agent-runtime/；starforge 会优先使用它，
这样用户不需要自己装 Python，也不需要在 PowerShell 里跑 pip。

安装策略（避免把 pymhf 的 GUI 全家桶塞进发布包）：
  1. NMSpy 用 --no-deps 安装，绕过它声明的 pymhf[gui,http_api]；
  2. 只安装 pymhf[http_api]（不带 gui extra），因此不会下载 DearPyGUI；
  3. pywin32 是 pymhf/pywinctl 的硬依赖，仍安装，但安装后裁掉 IDE/示例/
     win32comext 等 agent 不用的部分（可用 STARFORGE_AGENT_KEEP_PYWIN32_EXT=1 保留）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "3.11.9"
NMSpy_VERSION = os.environ.get("STARFORGE_NMSPY_VERSION", "185034.0")
# NMSpy 185034.0 的元数据要求 pymhf==0.2.5；固定版本便于复现和体积对比。
PYMHF_VERSION = os.environ.get("STARFORGE_PYMHF_VERSION", "0.2.5")
DEST = Path("build/agent-runtime")

WITH_GUI = os.environ.get("STARFORGE_AGENT_WITH_GUI") == "1"
KEEP_PYWIN32_EXT = os.environ.get("STARFORGE_AGENT_KEEP_PYWIN32_EXT") == "1"

# “安装依赖时顺带装进来、但 starforge 的无人值守 agent 用不到”的部分。
# 只删明确的开发/文档/静态库文件；保留 nmspy、pymhf、fastapi、uvicorn、pydantic、
# pywin32 的核心 win32/win32com（pymhf 的窗口检测和 pywinctl 会 import）。
PYWIN32_DROP_DIRS = (
    "pythonwin", "isapi", "adodbapi",
    "win32/test", "win32/Demos", "win32/scripts", "win32/libs", "win32/include",
    "win32com/test", "win32com/HTML", "win32com/demos", "win32com/makegw",
    "win32com/servers", "win32com/include",
)
PYWIN32_DROP_FILES = ("PyWin32.chm",)
PYWIN32_DROP_GLOBS = (
    "win32/**/*.lib", "win32com/**/*.lib", "win32comext/**/*.lib",
)

# 通用开发冗余（对整个 runtime，包括 embeddable Python 根目录）。
DEV_DIR_NAMES = {
    "__pycache__", "tests", "test", "examples", "demos", "samples",
    "docs", "doc", "include", "headers",
}
DEV_FILE_GLOBS = (
    "**/*.pyc", "**/*.pyo", "**/*.pyi", "**/*.pdb",
    "**/*.lib", "**/*.a", "**/*.exp",
    "**/*.h", "**/*.hpp", "**/*.hh", "**/*.hxx",
    "**/*.c", "**/*.cpp", "**/*.pyx", "**/*.pxd",
)


def _path_size(path: Path) -> int:
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


def _remove(path: Path) -> int:
    """删除文件/目录并返回腾出的字节数；不存在时返回 0。"""
    if not path.exists():
        return 0
    size = _path_size(path)
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as e:
        print(f"  跳过 {path}：{e}")
        return 0
    return size


def _remove_named_dirs(root: Path, names: set[str]) -> tuple[int, int]:
    removed = count = 0
    for dirpath, dirnames, _filenames in os.walk(root, topdown=True):
        keep = []
        for name in dirnames:
            p = Path(dirpath) / name
            if name in names:
                n = _remove(p)
                if n:
                    removed += n
                    count += 1
            else:
                keep.append(name)
        dirnames[:] = keep
    return removed, count


def _remove_globs(root: Path, patterns: tuple[str, ...]) -> tuple[int, int]:
    removed = count = 0
    for pattern in patterns:
        for p in root.glob(pattern):
            if not p.exists():
                continue
            n = _remove(p)
            if n:
                removed += n
                count += 1
    return removed, count


def prune_runtime(runtime: Path, site_packages: Path) -> None:
    """裁掉 agent runtime 里确定不需要的开发/文档/静态文件（保守清单）。"""
    before = _path_size(runtime)
    removed = 0
    count = 0

    # NMSpy 声明了 pymhf[gui]；默认只装 [http_api]，这里再兜底清理旧版本遗留。
    # starforge 启动 agent 时固定 gui.shown=False；pymhf 的 injected 对 GUI 导入失败
    # 做了兜底。STARFORGE_AGENT_WITH_GUI=1 时保留 DearPyGUI 和字体。
    if not WITH_GUI:
        for p in site_packages.glob("dearpygui*"):
            n = _remove(p)
            if n:
                removed += n
                count += 1
        n = _remove(site_packages / "pymhf" / "gui" / "fonts")
        if n:
            removed += n
            count += 1

    # pywin32：核心 win32/win32com/pywin32_system32 必留；IDE、示例、帮助、
    # 静态库和 win32comext 扩展（shell/mapi/adsi/...）agent 均不使用。
    drop_dirs = list(PYWIN32_DROP_DIRS)
    if not KEEP_PYWIN32_EXT:
        drop_dirs.append("win32comext")
    for rel in drop_dirs + list(PYWIN32_DROP_FILES):
        n = _remove(site_packages / rel)
        if n:
            removed += n
            count += 1
    for pattern in PYWIN32_DROP_GLOBS:
        for p in site_packages.glob(pattern):
            n = _remove(p)
            if n:
                removed += n
                count += 1

    # pip 的 console scripts；运行时直接 python.exe -c，不需要。
    for p in (runtime / "Scripts", runtime / "bin",
              site_packages / "Scripts", site_packages / "bin"):
        n = _remove(p)
        if n:
            removed += n
            count += 1

    # 测试/示例/文档/头文件目录（整个 runtime，含 site-packages）。
    n, c = _remove_named_dirs(runtime, DEV_DIR_NAMES)
    removed += n
    count += c

    # 字节码/类型存根/调试符号/静态库/C 源文件；保留 .pyd/.dll 和运行数据。
    n, c = _remove_globs(runtime, DEV_FILE_GLOBS)
    removed += n
    count += c

    after = _path_size(runtime)
    print(f"agent runtime 裁剪：{before / 1e6:.1f} MB -> {after / 1e6:.1f} MB"
          f"（释放 {removed / 1e6:.1f} MB，{count} 项）")


def _pip_install(site_packages: Path, *requirements: str, no_deps: bool = False) -> None:
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--no-compile", "--ignore-installed",
        "--disable-pip-version-check", "--no-warn-script-location",
        "--target", str(site_packages),
    ]
    if no_deps:
        cmd.append("--no-deps")
    cmd.extend(requirements)
    subprocess.run(cmd, check=True)


def install_agent_packages(site_packages: Path) -> None:
    extras = "gui,http_api" if WITH_GUI else "http_api"
    print("安装 NMSpy（--no-deps，避免被 NMSpy 的 pymhf[gui] 拖入 DearPyGUI）")
    _pip_install(site_packages, f"NMSpy=={NMSpy_VERSION}", no_deps=True)
    print(f"安装 pymhf[{extras}]=={PYMHF_VERSION} 及其运行时依赖")
    _pip_install(site_packages, f"pymhf[{extras}]=={PYMHF_VERSION}")


def run_self_check(py: Path) -> None:
    env = dict(os.environ)
    env["PYTEST_VERSION"] = "1"       # pymhf 在 import 期会弹 questionary；CI/agent 里必须绕过
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    code = """
import importlib.util
import nmspy, pymhf, fastapi, uvicorn
from pymhf.core.mod_loader import Mod
from pymhf.core.http_api import api_app
from pymhf.core.utils import get_main_window_handle
from pymhf.gui.proxy import _GUIProxy
import nmspy.data.basic_types
import nmspy.data.types
from nmspy.common import gameData
import win32api, win32con, win32gui, win32process, win32gui_struct
from win32com.client import GetObject
import keyboard._winkeyboard
import pymem, cyminhook, pyrun_injected
"""
    if WITH_GUI:
        code += "import dearpygui\n"
    else:
        code += """
assert importlib.util.find_spec('dearpygui') is None, 'DearPyGUI 不应出现在最小 runtime'
assert importlib.util.find_spec('pythonwin') is None, 'pythonwin IDE 应已裁剪'
assert importlib.util.find_spec('adodbapi') is None, 'adodbapi 示例应已裁剪'
try:
    from pymhf.gui.gui import GUI
except ModuleNotFoundError:
    pass  # 与 pymhf.injected 的兜底一致：无 DearPyGUI 时不创建 GUI
"""
    code += "\nprint('runtime ok')\n"
    subprocess.run([str(py), "-B", "-c", code], check=True, env=env)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="构建 starforge 的游戏内 agent Python 运行时")
    ap.add_argument("--no-prune", action="store_true",
                    help="只下载/安装，不裁剪也不自检（CI 用它先记录裁剪前体积）")
    ap.add_argument("--prune-only", action="store_true",
                    help="裁剪已有 runtime 并自检，不重新下载/安装")
    a = ap.parse_args(argv)

    site_packages = DEST / "Lib" / "site-packages"
    py = DEST / "python.exe"

    if a.prune_only:
        if not py.exists() or not site_packages.exists():
            print(f"找不到已构建的 runtime：{DEST}（先正常构建一次）")
            return 2
        prune_runtime(DEST, site_packages)
        run_self_check(py)
        print("agent runtime ->", DEST.resolve())
        return 0

    if sys.platform != "win32" and os.environ.get("STARFORGE_FORCE_RUNTIME") != "1":
        print("agent 运行时只用于 Windows；跳过（设置 STARFORGE_FORCE_RUNTIME=1 可强制）")
        return 0
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    url = f"https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip"
    print("下载", url)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        with urllib.request.urlopen(url, timeout=180) as r:
            shutil.copyfileobj(r, tmp)
        zpath = tmp.name
    with zipfile.ZipFile(zpath) as z:
        z.extractall(DEST)
    os.unlink(zpath)
    pth = next(DEST.glob("python*._pth"))
    text = pth.read_text("utf-8")
    lines = text.splitlines()
    if not any(line.strip() == "import site" for line in lines):
        text += "\nLib\\site-packages\nimport site\n"
    elif not any(line.strip().lower() == "lib\\site-packages" for line in lines):
        text += "\nLib\\site-packages\n"
    pth.write_text(text, "utf-8")
    site_packages.mkdir(parents=True, exist_ok=True)
    # 不在 embeddable Python 里 bootstrap pip（它的 _pth 容易把 pip 装丢）；
    # 直接用构建机的 Python 把依赖装进 runtime 的 site-packages。
    install_agent_packages(site_packages)
    if a.no_prune:
        print("已跳过裁剪与自检（--no-prune）；CI 会记录裁剪前体积后再执行 --prune-only")
    else:
        prune_runtime(DEST, site_packages)
        run_self_check(py)
    print("agent runtime ->", DEST.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
