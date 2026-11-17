"""找游戏安装目录（Windows 优先，跨平台尽力）。

为什么单独一个模块：打包版用户不会手填路径，自动发现必须够聪明。
顺序：
  1. 环境变量 NMS_DIR
  2. NMS-Shipwright 的 gamepath.find()（它自己会查 Steam/GOG/注册表）
  3. **我们自己补的兜底**：
     · 注册表 HKCU\\Software\\Valve\\Steam 的 SteamPath
     · 各磁盘的 SteamLibrary / steamapps/libraryfolders.vdf
     · 常见安装路径（含 D:/E: 等非系统盘）
  4. 都不行 → 返回 None（由 UI 弹原生目录选择框）
"""
from __future__ import annotations

import os
import re
import string

from .core import log

log = log.get("locate_game")

GAME_DIR_NAME = "No Man's Sky"


def looks_like_game(folder: str | None) -> bool:
    if not folder:
        return False
    return (os.path.exists(os.path.join(folder, "Binaries", "NMS.exe"))
            and os.path.isdir(os.path.join(folder, "GAMEDATA", "PCBANKS")))


def _steam_roots() -> list[str]:
    """Steam 根目录候选：注册表 → 常见路径 → 各磁盘。"""
    roots: list[str] = []
    if os.name == "nt":
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for value in ("SteamPath", "InstallPath"):
                            try:
                                p = winreg.QueryValueEx(k, value)[0]
                                if p:
                                    roots.append(os.path.normpath(p))
                            except OSError:
                                pass
                except OSError:
                    pass
        except Exception as e:                            # noqa: BLE001
            log.debug("读注册表失败：%s", e)
    # 常见路径
    for base in filter(None, [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                              r"C:\Program Files (x86)", r"C:\Program Files"]):
        roots.append(os.path.join(base, "Steam"))
    # 各磁盘（Windows）
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if not os.path.exists(drive):
                continue
            for name in ("Steam", "SteamLibrary", os.path.join("Program Files (x86)", "Steam")):
                roots.append(os.path.join(drive, name))
    else:
        home = os.path.expanduser("~")
        roots += [os.path.join(home, ".steam", "steam"),
                  os.path.join(home, ".local", "share", "Steam")]
    # 去重且存在
    seen, out = set(), []
    for r in roots:
        r = os.path.normpath(r)
        if r.lower() in seen:
            continue
        seen.add(r.lower())
        if os.path.isdir(r):
            out.append(r)
    return out


def _library_paths(steam_root: str) -> list[str]:
    """解析 steamapps/libraryfolders.vdf，拿到所有库目录。"""
    out = [steam_root]
    vdf = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    try:
        text = open(vdf, encoding="utf-8", errors="replace").read()
    except OSError:
        return out
    for m in re.finditer(r'"path"\s+"([^"]+)"', text):
        p = m.group(1).replace("\\\\", "\\")
        if os.path.isdir(p):
            out.append(os.path.normpath(p))
    return out


def find() -> str | None:
    """返回游戏根目录（含 Binaries/NMS.exe 与 GAMEDATA/PCBANKS），找不到返回 None。"""
    env = os.environ.get("NMS_DIR")
    if looks_like_game(env):
        return os.path.normpath(env)

    # 交给 Shipwright（它会查 Steam/GOG/微软商店）
    try:
        from .core import paths
        paths.ensure_shipwright_importable()
        from nms_save import gamepath
        p = gamepath.find()
        if looks_like_game(p):
            return p
    except Exception as e:                                 # noqa: BLE001
        log.debug("gamepath.find 不可用：%s", e)

    # 自己兜底扫 Steam 库
    for root in _steam_roots():
        for lib in _library_paths(root):
            cand = os.path.join(lib, "steamapps", "common", GAME_DIR_NAME)
            if looks_like_game(cand):
                return cand
    return None


def candidates() -> list[str]:
    """给"让用户确认"用：列出所有看起来像游戏目录的路径。"""
    out = []
    for root in _steam_roots():
        for lib in _library_paths(root):
            cand = os.path.join(lib, "steamapps", "common", GAME_DIR_NAME)
            if looks_like_game(cand) and cand not in out:
                out.append(cand)
    return out
