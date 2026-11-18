#!/usr/bin/env python3
"""构建游戏内 agent 的独立 Python 运行时（Windows CI / 本机均可跑）。

产物：build/agent-runtime/python.exe + site-packages（NMSpy + pymhf[http_api]）
发布时把它放到 dist/starforge/agent-runtime/；starforge 会优先使用它，
这样用户不需要自己装 Python，也不需要在 PowerShell 里跑 pip。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "3.12.8"
NMSpy_VERSION = os.environ.get("STARFORGE_NMSPY_VERSION", "185034.0")
DEST = Path("build/agent-runtime")


def main() -> int:
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
    if "import site" not in text:
        text += "\nLib\\site-packages\nimport site\n"
    pth.write_text(text, "utf-8")
    py = DEST / "python.exe"
    get_pip = DEST / "get-pip.py"
    print("下载 get-pip")
    with urllib.request.urlopen("https://bootstrap.pypa.io/get-pip.py", timeout=180) as r:
        get_pip.write_bytes(r.read())
    subprocess.run([str(py), str(get_pip)], check=True)
    subprocess.run([str(py), "-m", "pip", "install",
                    f"NMSpy=={NMSpy_VERSION}", "pymhf[http_api]>=0.2.5"], check=True)
    subprocess.run([str(py), "-c", "import nmspy,pymhf,fastapi,uvicorn;print('runtime ok')"], check=True)
    print("agent runtime ->", DEST.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
