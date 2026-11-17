#!/usr/bin/env python3
"""把 NMS-Shipwright（MIT）的必要部分 vendor 到 build/vendor，供 PyInstaller 打包。

只复制运行时真正需要的：
  nms_save/*.py · nms_procgen/*.py（含 designs/names） · data/mapping.json
  data/palettes · data/special_ships · LICENSE
不复制 data/gamecache（那是运行时缓存，几十 MB）。

用法：
  python packaging/vendor.py --shipwright ../NMS-Shipwright --dest build/vendor
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

COPY_DIRS = [("nms_save", "nms_save"), ("nms_procgen", "nms_procgen"),
             ("data/palettes", "data/palettes"), ("data/special_ships", "data/special_ships")]
COPY_FILES = [("data/mapping.json", "data/mapping.json"), ("LICENSE", "THIRD_PARTY_SHIPWRIGHT_LICENSE.txt")]
SKIP = {"__pycache__", ".git", "gamecache", "tests"}


def _sha(src: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", src, "rev-parse", "HEAD"], text=True).strip()
    except Exception:                                   # noqa: BLE001
        return "unknown"


def main() -> int:
    try:                                  # Windows 控制台可能是 cp1252，输出统一转 utf-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                     # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--shipwright", required=True)
    ap.add_argument("--dest", default="build/vendor")
    a = ap.parse_args()
    src, dst = a.shipwright, a.dest
    if not os.path.exists(os.path.join(src, "nms_save")):
        print(f"不是 NMS-Shipwright 仓库：{src}", file=sys.stderr)
        return 2
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)

    for rel_src, rel_dst in COPY_DIRS:
        s, d = os.path.join(src, rel_src), os.path.join(dst, rel_dst)
        if not os.path.exists(s):
            continue
        shutil.copytree(s, d, ignore=shutil.ignore_patterns(*SKIP))
    for rel_src, rel_dst in COPY_FILES:
        s, d = os.path.join(src, rel_src), os.path.join(dst, rel_dst)
        if os.path.exists(s):
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)

    commit = _sha(src)
    with open(os.path.join(dst, "VENDORED.txt"), "w", encoding="utf-8") as f:
        f.write(f"NMS-Shipwright @ {commit}\nLicense: MIT (see THIRD_PARTY_SHIPWRIGHT_LICENSE.txt)\n"
                "Vendored by starforge packaging/vendor.py — 仅打包用，不进入 starforge 仓库。\n")

    size = sum(os.path.getsize(os.path.join(r, f)) for r, _d, fs in os.walk(dst) for f in fs)
    print(f"vendored -> {dst}  ({size/1e3:.0f} KB, commit {commit[:7]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
