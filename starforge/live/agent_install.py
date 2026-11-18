"""游戏内 agent 的安装/启动/状态（全部可由原生界面按钮触发，不需要命令行）。

agent 本体是 ``starforge/agent/starforge_agent.py``（pymhf 单文件 Mod）。
依赖：
  · NMSpy（版本跟随游戏 build，例如 185034.0）
  · pymhf[http_api]（把 Mod 注入 NMS.exe，并提供 127.0.0.1:5000 HTTP API）

本模块只负责文件、依赖检测和子进程启动；真正读写游戏状态在 Mod 内。
"""
from __future__ import annotations

import importlib.metadata
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from ..core import log, paths, settings
from . import build, mem
from .agent_client import AgentClient, AgentError

log = log.get("agent")


def mod_source() -> Path:
    """源码 / PyInstaller onedir / _MEIPASS 三种布局都能找到 agent 文件。"""
    here = Path(__file__).resolve().parent.parent / "agent" / "starforge_agent.py"
    if here.exists():
        return here
    import sys
    cands = []
    if getattr(sys, "_MEIPASS", ""):
        cands.append(Path(sys._MEIPASS) / "starforge" / "agent" / "starforge_agent.py")
    exe_dir = Path(sys.executable).resolve().parent
    cands += [exe_dir / "_internal" / "starforge" / "agent" / "starforge_agent.py",
              exe_dir / "starforge" / "agent" / "starforge_agent.py"]
    for c in cands:
        if c.exists():
            return c
    return here


def agent_dir() -> Path:
    d = paths.app_home() / "agent"
    d.mkdir(parents=True, exist_ok=True)
    return d


def installed_mod() -> Path:
    return agent_dir() / "starforge_agent.py"


RUNTIME_PY_VERSION = "3.12.8"


def runtime_dir() -> Path:
    return agent_dir() / "runtime"


def _has_agent_packages(py: Path) -> bool:
    """判断一个 runtime 里是否真的装了 nmspy + pymhf（避免选中半成品）。"""
    base = py.parent
    site = base / "Lib" / "site-packages"
    return (site / "nmspy").is_dir() and (site / "pymhf").is_dir()


def runtime_python() -> Path | None:
    """找一个可用来运行 pymhf 的 Python。

    优先级：应用自带 runtime → 用户运行时 → 非冻结环境的本进程 Python → PATH。
    **必须真的含 nmspy+pymhf**；旧版本留下的空 runtime 会被跳过。
    """
    exe_dir = Path(sys.executable).resolve().parent
    cands = [
        exe_dir / "agent-runtime" / "python.exe",
        exe_dir / "_internal" / "agent-runtime" / "python.exe",
        Path(__file__).resolve().parents[2] / "agent-runtime" / "python.exe",
        runtime_dir() / "python.exe",
    ]
    if getattr(sys, "_MEIPASS", ""):
        cands.append(Path(sys._MEIPASS) / "agent-runtime" / "python.exe")
    for cand in cands:
        if cand.exists() and _has_agent_packages(cand):
            return cand
    # 开发环境：本进程 Python 已装 pymhf 时可以直接用
    if not getattr(sys, "frozen", False) and sys.executable:
        try:
            import pymhf  # noqa: F401
            return Path(sys.executable)
        except Exception:                                # noqa: BLE001
            pass
    return None


def bootstrap_runtime(out=None) -> dict:
    """在应用内下载 Python embeddable 并安装 agent 依赖（仅 Windows）。"""
    if not mem.IS_WINDOWS:
        return {"ok": False, "error": "Python 运行时只需在 Windows 上准备"}
    py = runtime_dir() / "python.exe"
    if py.exists() and _has_agent_packages(py):
        return {"ok": True, "python": str(py), "note": "运行时已存在"}
    d = runtime_dir()
    d.mkdir(parents=True, exist_ok=True)
    ver = RUNTIME_PY_VERSION
    url = f"https://www.python.org/ftp/python/{ver}/python-{ver}-embed-amd64.zip"
    logs = []

    def say(msg: str) -> None:
        logs.append(msg)
        if out:
            out(msg)

    try:
        say(f"下载 {url}")
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            with urllib.request.urlopen(url, timeout=120) as r:
                shutil.copyfileobj(r, tmp)
            zip_path = tmp.name
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(d)
        os.unlink(zip_path)
        pth = next(iter(d.glob("python*._pth")), None)
        if pth:
            text = pth.read_text("utf-8")
            lines = text.splitlines()
            if not any(line.strip() == "import site" for line in lines):
                text += "\nLib\\site-packages\nimport site\n"
            elif not any(line.strip().lower() == "lib\\site-packages" for line in lines):
                text += "\nLib\\site-packages\n"
            pth.write_text(text, "utf-8")
        say("下载 get-pip.py")
        get_pip = d / "get-pip.py"
        with urllib.request.urlopen("https://bootstrap.pypa.io/get-pip.py", timeout=120) as r:
            get_pip.write_bytes(r.read())
        say("安装 pip")
        r = subprocess.run([str(py), str(get_pip)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
        logs.append((r.stdout or "") + (r.stderr or ""))
        if r.returncode != 0:
            return {"ok": False, "error": "pip 安装失败", "output": "\n".join(logs)}
        say("运行时已就绪")
        return {"ok": True, "python": str(py), "output": "\n".join(logs)}
    except Exception as e:                               # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "output": "\n".join(logs)}


def expected_nmspy_version(fp: dict | None = None) -> str:
    fp = fp or build.fingerprint()
    # 已知 build 以地址书为准（NMS.exe 的 PE FileVersion 不一定是 NMSpy 的 build 号）
    known = build.lookup(fp) or {}
    ver = str(known.get("build") or fp.get("version") or "").strip()
    if ver.isdigit():
        return f"{ver}.0"
    return ""


def _dist_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""
    except Exception:                                    # noqa: BLE001
        return ""


def _runtime_info() -> dict:
    """用实际要注入的 Python 查询 nmspy/pymhf 版本（不是 starforge 自己的解释器）。"""
    py = runtime_python()
    if not py:
        return {"python": "", "nmspy": "", "pymhf": "", "http_api": False}
    code = (
        "import json\n"
        "try:\n"
        " import nmspy, pymhf\n"
        " out={'nmspy':getattr(nmspy,'__version__',''),'pymhf':getattr(pymhf,'__version__','')}\n"
        " try:\n"
        "  import fastapi, uvicorn\n"
        "  out['http_api']=True\n"
        " except Exception: out['http_api']=False\n"
        " print(json.dumps(out))\n"
        "except Exception as e:\n"
        " print(json.dumps({'error':type(e).__name__+': '+str(e)}))\n"
    )
    try:
        r = subprocess.run([str(py), "-c", code], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        import json
        data = json.loads((r.stdout or "{}").strip().splitlines()[-1] or "{}")
        data["python"] = str(py)
        return data
    except Exception as e:                               # noqa: BLE001
        return {"python": str(py), "error": f"{type(e).__name__}: {e}",
                "nmspy": "", "pymhf": "", "http_api": False}


def _installed_pymhf_with_api() -> bool:
    return bool(_runtime_info().get("http_api"))


def status() -> dict:
    fp = build.fingerprint()
    expected = expected_nmspy_version(fp)
    rt = runtime_python()
    rinfo = _runtime_info()
    nmspy = rinfo.get("nmspy") or _dist_version("NMSpy") or _dist_version("nmspy")
    pymhf = rinfo.get("pymhf") or _dist_version("pymhf")
    game_running = False
    pid = None
    if mem.IS_WINDOWS:
        try:
            pid = mem.find_pid("NMS.exe")
            game_running = bool(pid)
        except Exception:                                # noqa: BLE001
            pass
    client = AgentClient()
    reachable = client.ping()
    hello = {}
    if reachable:
        try:
            hello = client.hello()
        except AgentError as e:
            hello = {"ok": False, "error": str(e)}
    return {
        "platform": "windows" if mem.IS_WINDOWS else sys.platform,
        "supported": mem.IS_WINDOWS,
        "game_running": game_running,
        "pid": pid,
        "mod_installed": installed_mod().exists(),
        "mod_path": str(installed_mod()),
        "nmspy_version": nmspy,
        "expected_nmspy": expected,
        "nmspy_ok": bool(nmspy) and (not expected or nmspy.startswith(expected.rsplit(".", 1)[0])),
        "pymhf_version": pymhf,
        "pymhf_http_api": bool(rinfo.get("http_api")),
        "runtime_python": str(rt) if rt else "",
        "runtime_ready": bool(rt and _has_agent_packages(rt)),
        "reachable": reachable,
        "hello": hello,
        "build": build.summary(fp),
        "note": _note(mem.IS_WINDOWS, game_running, nmspy, expected, pymhf, reachable),
    }


def _note(windows: bool, running: bool, nmspy: str, expected: str, pymhf: str, reachable: bool) -> str:
    if not windows:
        return "游戏内通道仅支持 Windows；其它功能不受影响"
    if not nmspy or not pymhf:
        return "还没安装游戏内组件（NMSpy + pymhf）；点「安装/更新游戏内组件」"
    if expected and nmspy and not nmspy.startswith(expected.rsplit(".", 1)[0]):
        return f"游戏 build 是 {expected}，已装 NMSpy {nmspy}；请点「安装/更新游戏内组件」"
    if not running:
        return "组件已装；启动游戏并载入存档后点「注入并连接」"
    if not reachable:
        return "游戏在运行，但 agent 未连接；点「注入并连接」"
    return "agent 已连接，可以读取/传送/扫描"


def install_mod() -> dict:
    src = mod_source()
    if not src.exists():
        raise FileNotFoundError(f"找不到 agent 源文件：{src}")
    dst = installed_mod()
    dst.write_text(src.read_text("utf-8"), "utf-8")
    return {"ok": True, "path": str(dst), "bytes": dst.stat().st_size}


def uninstall_mod() -> dict:
    dst = installed_mod()
    if dst.exists():
        dst.unlink()
    return {"ok": True, "path": str(dst), "removed": not dst.exists()}


def install_deps(version: str | None = None, timeout: int = 600) -> dict:
    """在应用内一键安装/更新 NMSpy + pymhf（需要网络；失败会返回原命令与输出）。"""
    version = version or expected_nmspy_version()
    if not version:
        raise ValueError("无法从游戏 build 推断 NMSpy 版本")
    py = runtime_python()
    if not py:
        return {"ok": False, "needs_runtime": True,
                "error": "没有可用的 Python 运行时；请先点「准备游戏内运行时」"}
    cmd = [str(py), "-m", "pip", "install", "--upgrade",
           f"NMSpy=={version}", "pymhf[http_api]>=0.2.5"]
    log.info("安装游戏内组件：%s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "cmd": cmd, "error": f"安装超时（{timeout}s）", "output": str(e)}
    return {"ok": proc.returncode == 0, "cmd": cmd, "code": proc.returncode,
            "output": (proc.stdout or "") + (proc.stderr or "")}


_LAUNCH: subprocess.Popen | None = None


def launch(attach: bool = True) -> dict:
    """启动 pymhf 并注入 agent；attach=True 连正在运行的游戏，否则启动游戏。"""
    if not mem.IS_WINDOWS:
        raise RuntimeError("游戏内通道仅支持 Windows")
    install_mod()
    if not _installed_pymhf_with_api():
        raise RuntimeError("缺少 pymhf[http_api] 或 NMSpy；请先安装游戏内组件")
    fp = build.fingerprint()
    game = settings.current().game_dir
    if not game:
        try:
            from ..locate_game import find

            game = find() or ""
        except Exception:                                # noqa: BLE001
            game = ""
    exe = str(Path(game) / "Binaries" / "NMS.exe") if game else ""
    pid = mem.find_pid("NMS.exe")
    if attach and not pid:
        raise RuntimeError("游戏没有运行：请先进存档，或取消「只连接已运行的游戏」让应用启动游戏")
    if not attach and not exe:
        raise RuntimeError("没有配置游戏目录（设置页选择游戏根目录）")
    overrides = {
        "pid": pid if attach else None,
        "exe": exe or None,
        "start_exe": not attach,
        "start_paused": False,
        "steam_gameid": 275850,
        "interactive_console": False,
        "gui": {"shown": False},
        "logging": {"log_level": "info", "log_dir": str(agent_dir()), "shown": False},
    }
    code = (
        "import sys\n"
        "from pymhf import load_mod_file\n"
        "import json\n"
        "cfg=json.loads(sys.argv[2])\n"
        "cfg={k:v for k,v in cfg.items() if v is not None}\n"
        "load_mod_file(sys.argv[1], config_overrides=cfg)\n"
    )
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    # pymhf 的 __init__ 在非 pytest 环境会创建 questionary 提示；agent 是无人值守启动，
    # 设置这个变量让它跳过交互（load_mod_file 本身不走交互配置）。
    env["PYTEST_VERSION"] = "1"
    log_path = agent_dir() / "launcher.log"
    log_file = open(log_path, "a", encoding="utf-8")
    global _LAUNCH
    py = runtime_python()
    if not py:
        raise RuntimeError("没有可用的 Python 运行时；请先点「准备游戏内运行时」")
    _LAUNCH = subprocess.Popen(
        [str(py), "-c", code, str(installed_mod()), __import__("json").dumps(overrides)],
        cwd=str(agent_dir()), stdout=log_file, stderr=subprocess.STDOUT,
        env=env, close_fds=True,
        creationflags=0x00000008 if os.name == "nt" else 0,   # DETACHED_PROCESS
    )
    return {"ok": True, "pid": _LAUNCH.pid, "log": str(log_path),
            "build_id": build.build_id(fp), "attach": attach}


def stop() -> dict:
    global _LAUNCH
    if _LAUNCH and _LAUNCH.poll() is None:
        _LAUNCH.terminate()
        return {"ok": True, "stopped": _LAUNCH.pid}
    return {"ok": True, "stopped": None}


def wait_ready(timeout: float = 20.0) -> dict:
    """启动后轮询 HTTP，给界面一个确定的“已连接/超时”。"""
    client = AgentClient()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if client.ping():
            try:
                return {"ok": True, "hello": client.hello()}
            except AgentError as e:
                return {"ok": False, "error": str(e)}
        time.sleep(0.5)
    return {"ok": False, "error": f"{timeout:.0f}s 内没有连上 agent；看 {agent_dir() / 'launcher.log'}"}
