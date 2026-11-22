"""游戏内 agent 的安装/启动/状态（全部可由原生界面按钮触发，不需要命令行）。

agent 本体是 ``starforge/agent/starforge_agent.py``（pymhf 单文件 Mod）。
依赖：
  · NMSpy（版本跟随游戏 build，例如 185034.0）
  · pymhf[http_api]（把 Mod 注入 NMS.exe，并提供 127.0.0.1:5000 HTTP API）

本模块只负责文件、依赖检测和子进程启动；真正读写游戏状态在 Mod 内。
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from ..core import log, paths, settings
from . import build, mem
from .agent_client import (
    DEFAULT_PORT,
    AgentClient,
    AgentError,
    base_for_port,
    clear_state,
    read_state,
    state_file,
    write_state,
)

log = log.get("agent")

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


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


TOKEN_FILE_NAME = "token"


def _load_or_create_token(path: Path | None = None) -> str:
    """读取持久化 token；不存在/为空才生成一次并写盘（尽量 0600）。

    为什么不能每次启动都换 token：游戏里已经运行的 agent 只在启动时读一次 token，
    第二次注入/重启 launcher 后若覆盖文件，客户端拿新 token 会一直 401。这里沿用
    已有 token，``state.json`` 与文件保持一致。不要把这个值写进日志。
    """
    target = Path(path) if path else agent_dir() / TOKEN_FILE_NAME
    try:
        token = target.read_text("utf-8").strip()
    except FileNotFoundError:
        token = ""
    except OSError as e:
        log.warning("无法读取 agent token 文件：%s", e)
        token = ""
    if token:
        return token
    token = secrets.token_urlsafe(32)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(token, encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    except OSError:
        log.warning("无法写入 agent token 文件；Steam 启动时认证会退化为 disabled")
    return token


# 构建 runtime（packaging/build_agent_runtime.py）与应用安装器共用这份版本矩阵。
# 版本不再散落在两个文件里：修改时同步改这里；tests/test_agent_runtime.py 会
# 校验构建脚本常量与下面一致，status() 也会报告实际 runtime 与矩阵的偏差。
AGENT_RUNTIME_MANIFEST = {
    "python": "3.11.9",
    "nmspy_default": "185034.0",
    "nmspy_by_build": {"185034": "185034.0"},
    "pymhf": "0.2.5",
}

RUNTIME_PY_VERSION = AGENT_RUNTIME_MANIFEST["python"]
AGENT_PYMHF_VERSION = AGENT_RUNTIME_MANIFEST["pymhf"]
LAUNCHER_LOG_NAME = "launcher.log"
SNAPSHOTS_NAME = "snapshots.json"

_LAUNCH_LOCK = threading.RLock()


def launcher_log_path() -> Path:
    return agent_dir() / LAUNCHER_LOG_NAME


def snapshots_path() -> Path:
    """agent 侧持久化快照的位置（只读 helper，方便诊断/服务层展示）。"""
    return agent_dir() / SNAPSHOTS_NAME


def tail_launcher_log(lines: int = 200, max_bytes: int = 128 * 1024) -> dict:
    """只读地取 launcher.log 末尾若干行；不存在时返回 exists=False，不创建文件。"""
    path = launcher_log_path()
    want = max(1, min(int(lines or 200), 2000))
    try:
        if not path.exists():
            return {"ok": True, "path": str(path), "exists": False,
                    "lines": [], "text": "", "truncated": False}
        size = path.stat().st_size
        start = max(0, size - max(1024, int(max_bytes or 128 * 1024)))
        with open(path, "rb") as f:
            if start:
                f.seek(start)
            raw = f.read()
        text = raw.decode("utf-8", errors="replace")
        rows = text.splitlines()
        return {"ok": True, "path": str(path), "exists": True,
                "size": size, "truncated": start > 0,
                "lines": rows[-want:], "text": "\n".join(rows[-want:])}
    except OSError as e:
        return {"ok": False, "path": str(path), "exists": path.exists(),
                "lines": [], "text": "", "error": f"{type(e).__name__}: {e}"}


def port_available(port: int, host: str = "127.0.0.1") -> bool:
    """检查本机端口能否绑定；用于 5000 固定端口的冲突检测。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, int(port)))
        except OSError:
            return False
        return True


def requested_port() -> int:
    """pymhf 目前固定监听 5000；允许环境变量覆盖以便将来/自建 runtime。

    如果 pymhf 版本升级后支持端口配置，只需让 launch 把该值传进去；现在只记录
    来源并在启动前做冲突检测，不假装随机端口已经生效。
    """
    raw = os.environ.get("STARFORGE_AGENT_PORT")
    if raw:
        try:
            value = int(raw)
            if 1 <= value <= 65535:
                return value
        except ValueError:
            pass
    return DEFAULT_PORT


def runtime_dir() -> Path:
    return agent_dir() / "runtime"


def _has_agent_packages(py: Path) -> bool:
    """判断一个 runtime 里是否真的装了 nmspy + pymhf（避免选中半成品）。"""
    base = py.parent
    site = base / "Lib" / "site-packages"
    return (site / "nmspy").is_dir() and (site / "pymhf").is_dir()


_OWN_PID_MARKER = "# STARFORGE_OWN_PID_PATCH"
_OWN_PID_ORIGINAL = "binary = pymem.Pymem(_internal.EXE_NAME, exact_match=True)"


def patch_runtime_own_pid(py: Path | None = None) -> dict:
    """给 pymhf 里所有「按进程名打开 NMS.exe」的地方打幂等补丁。

    为什么需要：pymhf 注入时原本按 ``_internal.EXE_NAME``（NMS.exe）找进程，
    游戏崩溃留下同名僵尸/多个实例时会打开错误的 PID。补丁先 ``Pymem(os.getpid())``，
    失败再回退原名。除了 ``injected.py``，``core/memutils.py`` 在建 hook 时也会
    按名字找进程——漏掉它就会出现「注入成功但 0 hooks、代理不可用」。
    """
    try:
        py = Path(py) if py else (runtime_python() or bare_runtime_python())
        if not py:
            return {"ok": False, "patched": False, "reason": "没有可用的运行时"}
        site = py.parent / "Lib" / "site-packages" / "pymhf"
        if not site.is_dir():
            return {"ok": False, "patched": False, "path": str(site),
                    "reason": "找不到 pymhf 目录"}
        patched: list[str] = []
        skipped: list[str] = []
        for target in sorted(site.rglob("*.py")):
            changed, reason = _patch_own_pid_file(target)
            if changed:
                patched.append(str(target))
            elif reason != "missing":
                skipped.append(f"{target.name}:{reason}")
        if patched:
            log.info("已为 pymhf 注入自身 PID 补丁：%s", ", ".join(
                Path(p).name for p in patched))
            return {"ok": True, "patched": True, "files": patched,
                    "path": patched[0]}
        return {"ok": True, "patched": False,
                "path": str(site / "injected.py"),
                "reason": "已经打过补丁" if not skipped else "没有可补丁的行",
                "skipped": skipped}
    except Exception as e:                              # noqa: BLE001 - 补丁失败不能影响启动
        return {"ok": False, "patched": False,
                "error": f"{type(e).__name__}: {e}"}


def _patch_own_pid_file(target: Path) -> tuple[bool, str]:
    """把单个文件里的 ``x = pymem.Pymem(_internal.EXE_NAME, ...)`` 包成自身 PID 优先。"""
    try:
        text = target.read_text("utf-8")
    except OSError:
        return False, "unreadable"
    if _OWN_PID_MARKER in text:
        return False, "patched"
    original = "pymem.Pymem(_internal.EXE_NAME, exact_match=True)"
    if original not in text:
        return False, "missing"
    out: list[str] = []
    changed = False
    for line in text.splitlines(keepends=True):
        if original in line and "=" in line:
            lhs = line.split("=", 1)[0].strip()
            indent = line[: len(line) - len(line.lstrip())]
            if lhs and lhs.isidentifier():
                out.append(f"{indent}{_OWN_PID_MARKER}: 先用本进程 PID 打开自身，"
                           "失败再回退按进程名\n")
                out.append(f"{indent}try:\n")
                out.append(f"{indent}    {lhs} = pymem.Pymem(os.getpid())\n")
                out.append(f"{indent}except Exception:\n")
                out.append(f"{indent}    {line.lstrip()}")
                changed = True
                continue
        out.append(line)
    if not changed:
        return False, "unsupported"
    if not any(line.strip() == "import os" for line in out):
        insert_at = 0
        for index, line in enumerate(out):
            if line.startswith("import ") or line.startswith("from "):
                insert_at = index + 1
        out.insert(insert_at, "import os\n")
    target.write_text("".join(out), "utf-8")
    return True, "patched"


def _apply_own_pid_patch(py: Path | None = None) -> dict:
    """调用补丁并只记日志；任何失败都不向 launch 抛异常。"""
    result = patch_runtime_own_pid(py)
    if not result.get("ok"):
        log.warning("pymhf 自身 PID 补丁未应用（不影响启动）：%s",
                    result.get("error") or result.get("reason") or "未知原因")
    return result


def _runtime_candidates() -> list[Path]:
    """所有可能放 agent runtime 的位置（按优先级）。"""
    exe_dir = Path(sys.executable).resolve().parent
    cands = [
        exe_dir / "agent-runtime" / "python.exe",
        exe_dir / "_internal" / "agent-runtime" / "python.exe",
        Path(__file__).resolve().parents[2] / "agent-runtime" / "python.exe",
        runtime_dir() / "python.exe",
    ]
    if getattr(sys, "_MEIPASS", ""):
        cands.append(Path(sys._MEIPASS) / "agent-runtime" / "python.exe")
    return cands


def bare_runtime_python() -> Path | None:
    """只要 python.exe 存在就返回（不要求已装依赖）。

    为什么需要单独一个：``runtime_python()`` 只认"已经装好 nmspy+pymhf"的运行时，
    而**第一次安装依赖**时恰恰还没有这些包。用它做 pip 安装的入口，否则
    「准备运行时 → 安装组件」在干净机器上永远报"没有可用的 Python 运行时"。
    """
    for cand in _runtime_candidates():
        if cand.exists():
            return cand
    return None


def runtime_python() -> Path | None:
    """找一个可用来运行 pymhf 的 Python。

    优先级：应用自带 runtime → 用户运行时 → 非冻结环境的本进程 Python → PATH。
    **必须真的含 nmspy+pymhf**；旧版本留下的空 runtime 会被跳过（装依赖用
    ``bare_runtime_python()``）。
    """
    for cand in _runtime_candidates():
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
    """修复运行时：正常包已内置，只有缺失/损坏时才下载（仅 Windows）。"""
    if not mem.IS_WINDOWS:
        return {"ok": False, "error": "Python 运行时只需在 Windows 上准备"}
    rt = runtime_python()
    if rt and _has_agent_packages(rt):
        report = runtime_report()
        note = "运行时已内置，无需下载"
        if not report.get("ok"):
            note += "；但版本与清单不一致，建议运行「修复运行时/游戏内组件」"
        return {"ok": True, "python": str(rt), "note": note,
                "versions": report, "needs_update": not report.get("ok")}
    py = runtime_dir() / "python.exe"
    if py.exists() and _has_agent_packages(py):
        report = runtime_report()
        note = "运行时已存在"
        if not report.get("ok"):
            note += "；但版本与清单不一致，建议运行「修复运行时/游戏内组件」"
        return {"ok": True, "python": str(py), "note": note,
                "versions": report, "needs_update": not report.get("ok")}
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
                           encoding="utf-8", errors="replace", timeout=300, creationflags=_NO_WINDOW)
        logs.append((r.stdout or "") + (r.stderr or ""))
        if r.returncode != 0:
            return {"ok": False, "error": "pip 安装失败", "output": "\n".join(logs)}
        say("运行时已就绪")
        return {"ok": True, "python": str(py), "output": "\n".join(logs)}
    except Exception as e:                               # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "output": "\n".join(logs)}


def expected_nmspy_version(fp: dict | None = None) -> str:
    """按 build 查 NMSpy 版本；地址书显式 nmspy 字段优先于 PE 文件版本。

    地址书 ``build`` 是 NMS 游戏 build（例如 185034），NMSpy 的发行版版本可能
    带补丁号（185034.0）。不要在地址书缺失时把任意 PE FileVersion 当成 NMSpy
    版本；只有在它是纯数字 build 时才按映射/``<build>.0`` 推断。
    """
    fp = fp or build.fingerprint()
    known = build.lookup(fp) or {}
    explicit = str(known.get("nmspy") or "").strip()
    if explicit:
        return explicit
    build_no = str(known.get("build") or "").strip()
    if not build_no.isdigit():
        cand = str(fp.get("version") or "").strip()
        build_no = cand if cand.isdigit() else ""
    if not build_no:
        return ""
    mapped = AGENT_RUNTIME_MANIFEST["nmspy_by_build"].get(build_no)
    return mapped or f"{build_no}.0"


def build_number(version: str) -> str:
    """取版本里的游戏 build 段（``185034.0`` -> ``185034``）。"""
    return str(version or "").strip().split(".", 1)[0]


def nmspy_version_ok(installed: str, expected: str) -> bool:
    if not installed:
        return False
    if not expected:
        return True
    return installed == expected or build_number(installed) == build_number(expected)


def runtime_report(info: dict | None = None, expected: str | None = None) -> dict:
    """把“实际 runtime”与清单/游戏 build 对比；纯函数，便于离线单测。"""
    info = info if info is not None else _runtime_info()
    expected = expected if expected is not None else expected_nmspy_version()
    manifest = dict(AGENT_RUNTIME_MANIFEST)
    installed = {
        "python": str(info.get("python_version") or ""),
        "nmspy": str(info.get("nmspy") or ""),
        "nmspy_module": str(info.get("nmspy_module") or ""),
        "pymhf": str(info.get("pymhf") or ""),
        "fastapi": str(info.get("fastapi") or ""),
        "uvicorn": str(info.get("uvicorn") or ""),
    }
    mismatches: list[str] = []
    if not info.get("python"):
        mismatches.append("没有可用的 agent runtime")
    if info.get("python") and not installed["python"]:
        mismatches.append("无法读取 runtime 的 Python 版本")
    elif installed["python"] and installed["python"] != manifest["python"]:
        mismatches.append(
            f"Python {installed['python']} != 清单 {manifest['python']}")
    if not installed["nmspy"]:
        mismatches.append("未安装/无法读取 NMSpy")
    elif expected and not nmspy_version_ok(installed["nmspy"], expected):
        mismatches.append(f"NMSpy {installed['nmspy']} != 期望 {expected}")
    if installed["nmspy_module"] and expected and not nmspy_version_ok(
            installed["nmspy_module"], expected):
        mismatches.append(
            f"NMSpy 模块 __version__ {installed['nmspy_module']} != 期望 {expected}")
    if not installed["pymhf"]:
        mismatches.append("未安装/无法读取 pymhf")
    elif not (installed["pymhf"] == manifest["pymhf"]
              or installed["pymhf"].startswith(manifest["pymhf"] + ".")):
        mismatches.append(f"pymhf {installed['pymhf']} != 清单 {manifest['pymhf']}")
    if not info.get("http_api"):
        mismatches.append("pymhf[http_api] 缺失（fastapi/uvicorn 不可用）")
    return {"ok": not mismatches, "manifest": manifest, "expected_nmspy": expected,
            "installed": installed, "mismatches": mismatches}


def _dist_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""
    except Exception:                                    # noqa: BLE001
        return ""


def _runtime_info() -> dict:
    """用实际要注入的 Python 读取已安装发行版信息。

    这里只查 dist-info，不 import nmspy/pymhf：pymhf 首次 import 会执行较多
    初始化，在 Windows Defender 冷启动时可能超过 30 秒，导致“运行时明明在，
    却显示缺少组件”的假阴性。真正 import 由 launch 子进程完成，失败会写入
    launcher.log；状态页只需要确认发行版文件齐全。
    """
    py = runtime_python()
    if not py:
        return {"python": "", "nmspy": "", "pymhf": "", "http_api": False}
    code = (
        "import json, platform, re\n"
        "from importlib import metadata as m\n"
        "from pathlib import Path\n"
        "out={'python_version': platform.python_version()}\n"
        "for dist,key in (('NMSpy','nmspy'),('nmspy','nmspy'),('pymhf','pymhf'),\n"
        "                 ('fastapi','fastapi'),('uvicorn','uvicorn')):\n"
        " try:\n"
        "  out[key]=m.version(dist)\n"
        " except Exception:\n"
        "  pass\n"
        # 双校验：dist-info 之外再读模块源码里的 __version__，不 import nmspy/pymhf
        # （pymhf 首次 import 可能触发较慢的初始化）。
        "try:\n"
        " import importlib.util\n"
        " spec=importlib.util.find_spec('nmspy')\n"
        " if spec and spec.origin:\n"
        "  text=Path(spec.origin).read_text(encoding='utf-8', errors='replace')\n"
        "  found=re.search(r\"__version__\\s*=\\s*['\\\"]([^'\\\"]+)\", text)\n"
        "  if found: out['nmspy_module']=found.group(1)\n"
        "except Exception as e:\n"
        " out['nmspy_module_error']=type(e).__name__+': '+str(e)\n"
        "out['http_api']=bool(out.get('fastapi') and out.get('uvicorn'))\n"
        "print(json.dumps(out))\n"
    )
    try:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONSTARTUP", None)
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONUTF8"] = "1"
        r = subprocess.run([str(py), "-B", "-c", code], cwd=str(py.parent),
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20, env=env,
                           creationflags=_NO_WINDOW)
        data = json.loads((r.stdout or "{}").strip().splitlines()[-1] or "{}")
        data["python"] = str(py)
        if r.returncode:
            data["error"] = (r.stderr or r.stdout or f"退出码 {r.returncode}").strip()[-500:]
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
    report = runtime_report(rinfo, expected)
    nmspy = rinfo.get("nmspy") or _dist_version("NMSpy") or _dist_version("nmspy")
    pymhf = rinfo.get("pymhf") or _dist_version("pymhf")
    exe_dir = Path(sys.executable).resolve().parent
    bundled = bool(rt and str(rt).lower().startswith(str(exe_dir).lower()))
    game_running = False
    pid = None
    if mem.IS_WINDOWS:
        try:
            pid = mem.find_pid("NMS.exe")
            game_running = bool(pid)
        except Exception:                                # noqa: BLE001
            pass
    state = read_state()
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
        "nmspy_module_version": str(rinfo.get("nmspy_module") or ""),
        "expected_nmspy": expected,
        "nmspy_ok": bool(nmspy) and (not expected or nmspy_version_ok(nmspy, expected)),
        "pymhf_version": pymhf,
        "pymhf_http_api": bool(rinfo.get("http_api")),
        "runtime_python": str(rt) if rt else "",
        "runtime_python_version": report["installed"].get("python") or "",
        "runtime_ready": bool(rt and _has_agent_packages(rt)),
        "runtime_bundled": bundled,
        "runtime_error": str(rinfo.get("error") or ""),
        "runtime_manifest": report["manifest"],
        "runtime_versions_ok": bool(report["ok"]),
        "runtime_mismatches": report["mismatches"],
        "agent_base": client.base,
        "agent_port": state.get("port") or requested_port(),
        "agent_state": str(state_file()),
        "launcher_log": str(launcher_log_path()),
        "snapshots": str(snapshots_path()),
        "reachable": reachable,
        "hello": hello,
        "build": build.summary(fp),
        "note": _note(mem.IS_WINDOWS, game_running, nmspy, expected, pymhf, reachable,
                      bool(rt and _has_agent_packages(rt)), bundled,
                      str(rinfo.get("error") or ""), bool(rinfo.get("http_api")),
                      bool(report["ok"])),
    }


def _note(windows: bool, running: bool, nmspy: str, expected: str, pymhf: str,
          reachable: bool, runtime_ready: bool = False, bundled: bool = False,
          runtime_error: str = "", http_api: bool = False,
          versions_ok: bool = True) -> str:
    if not windows:
        return "游戏内通道仅支持 Windows；其它功能不受影响"
    if runtime_ready and nmspy and pymhf and http_api:
        prefix = "内置运行时已就绪（无需下载）" if bundled else "运行时已就绪"
        if not versions_ok:
            return prefix + "；但版本与清单不完全一致，请点「修复运行时/游戏内组件」"
        if not running:
            return prefix + "；启动游戏并载入存档后点「连接游戏」"
        if not reachable:
            return prefix + "；点「连接游戏」注入 agent"
        return prefix + "；agent 已连接"
    if runtime_ready and (not nmspy or not pymhf or not http_api):
        detail = f"：{runtime_error}" if runtime_error else ""
        return f"运行时文件存在，但游戏内组件不完整{detail}；请点「修复运行时/游戏内组件」"
    if not nmspy or not pymhf:
        return "内置运行时缺失或不完整；请重新解压完整安装包（正常包不需要联网安装）"
    if expected and nmspy and not nmspy_version_ok(nmspy, expected):
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


def install_deps(version: str | None = None, timeout: int = 600,
                 force: bool = False) -> dict:
    """修复/更新 NMSpy + pymhf。

    内置 runtime 已存在但 NMSpy/pymhf/HTTP API 版本不匹配时**不再直接早退**：
    会尝试把依赖升级到同一份 manifest；如果内置 runtime 只读/没有 pip，则返回
    可操作错误，而不是假装“已就绪”。匹配时仍然不联网。
    """
    rt = runtime_python()
    version = version or expected_nmspy_version()
    if rt and _has_agent_packages(rt):
        info = _runtime_info()
        report = runtime_report(info, version)
        if report["ok"] and not force:
            _apply_own_pid_patch(rt)
            return {"ok": True, "note": "运行时已内置且版本匹配，无需安装/更新",
                    "python": str(rt), "versions": report}
        if any(item.startswith("Python ") for item in report["mismatches"]):
            # pip 无法更换 runtime 的 Python 版本；不冒险在旧 runtime 上硬装，
            # 明确要求重新准备/解压与构建脚本一致的 runtime。
            return {"ok": False, "code": "E_RUNTIME_PYTHON", "python": str(rt),
                    "error": ("内置 runtime 的 Python 版本与版本清单不一致；"
                              "请点「准备游戏内运行时」重新下载/解压完整 runtime，"
                              "不要在同一 runtime 上强行安装依赖"),
                    "versions": report}
        log.info("游戏内组件需要更新：%s", "; ".join(report["mismatches"]))
    elif not version:
        raise ValueError("无法从游戏 build 推断 NMSpy 版本")
    py = rt or bare_runtime_python()
    if not py:
        return {"ok": False, "needs_runtime": True,
                "error": "没有可用的 Python 运行时；请先点「准备游戏内运行时」"}
    if not version:
        raise ValueError("无法从游戏 build 推断 NMSpy 版本")
    cmd = [str(py), "-m", "pip", "install", "--upgrade",
           f"NMSpy=={version}", f"pymhf[http_api]=={AGENT_PYMHF_VERSION}"]
    log.info("安装游戏内组件：%s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "cmd": cmd, "error": f"安装超时（{timeout}s）", "output": str(e)}
    except OSError as e:
        return {"ok": False, "cmd": cmd,
                "error": f"无法运行内置 runtime 的 pip（可能是只读安装目录）：{e}"}
    res = {"ok": proc.returncode == 0, "cmd": cmd, "code": proc.returncode,
           "output": (proc.stdout or "") + (proc.stderr or "")}
    if res["ok"]:
        _apply_own_pid_patch(py)
    return res


_LAUNCH: subprocess.Popen | None = None


def _existing_agent(port: int, state: dict) -> dict | None:
    """端口被占时判断是不是上一次启动的 starforge agent；是则复用而非硬杀。"""
    base = str(state.get("base") or base_for_port(port))
    client = AgentClient(base=base, token=str(state.get("token") or ""), timeout=1.0)
    try:
        hello = client.hello()
    except Exception:                                    # noqa: BLE001
        return None
    if hello.get("ok") and str(hello.get("agent") or "").strip():
        return {"hello": hello, "base": base, "token": str(state.get("token") or "")}
    return None


def launch(attach: bool = True, *, allow_attach: bool = False) -> dict:
    """启动 pymhf 并注入 agent；attach=True 连正在运行的游戏，否则启动游戏。

    每次启动生成一次性 token 写入私有 state.json，并注入 agent 子进程环境；
    AgentClient 随后自动读取。pymhf 的 HTTP API 目前固定 5000，无法可靠随机端口，
    所以这里只做可配置覆盖（STARFORGE_AGENT_PORT）+ 占用检测，不假装已经随机。

    **attach 默认被拒绝**：实测在 build 185034 上，对已初始化的游戏进程做注入会让
    NMS.exe 在 ``python311.dll`` 里访问冲突闪退（0xC0000005）。pymhf 的受支持路径是
    “先创建进程、再注入”，所以请用 ``attach=False`` 由应用启动游戏。调试/用户在
    UI 二次确认后可传 ``allow_attach=True``；环境变量
    ``STARFORGE_ALLOW_ATTACH_INJECT=1`` 仍可强制打开（风险自负）。

    ``attach=False`` 时如果游戏已经在运行，**不会**再让 Steam 拉起第二个实例：
    直接返回 ``E_GAME_RUNNING``，由 UI 决定「附加注入」或「重启并注入」。
    """
    if not mem.IS_WINDOWS:
        raise RuntimeError("游戏内通道仅支持 Windows")
    if attach and not allow_attach and os.environ.get("STARFORGE_ALLOW_ATTACH_INJECT") != "1":
        raise RuntimeError(
            "不支持“附加到已运行的游戏”注入：pymhf 在游戏初始化后注入会与游戏线程竞争，"
            "实测在 build 185034 上会导致 NMS.exe 访问冲突闪退（python311.dll 0xC0000005）。"
            "请改用“由应用启动游戏”的方式（会先创建进程再注入）。"
            "仅调试时可用环境变量 STARFORGE_ALLOW_ATTACH_INJECT=1 强制。")
    install_mod()
    info = _runtime_info()
    if not info.get("http_api"):
        detail = str(info.get("error") or "").strip()
        suffix = f"（{detail}）" if detail else ""
        raise RuntimeError(
            f"缺少 pymhf[http_api] 或 NMSpy；请先安装/修复游戏内组件{suffix}")
    fp = build.fingerprint()
    game = settings.current().game_dir
    if not game:
        try:
            from ..locate_game import find

            game = find() or ""
        except Exception:                                # noqa: BLE001
            game = ""
    exe = str(Path(game) / "Binaries" / "NMS.exe") if game else ""
    port = requested_port()
    state = read_state()
    if not port_available(port):
        existing = _existing_agent(port, state)
        if existing:
            return {"ok": True, "already_running": True, "pid": state.get("pid"),
                    "port": port, "base": existing["base"],
                    "log": str(launcher_log_path()), "build_id": build.build_id(fp),
                    "attach": attach, "token_auth": "query",
                    "note": "端口已有 starforge agent 在运行，复用现有一次性 token"}
        raise RuntimeError(
            f"agent 端口 {port} 已被其它进程占用。pymhf 当前只支持固定端口；"
            "请关闭占用进程，或设置 STARFORGE_AGENT_PORT（需要 pymhf/runtime 支持）")
    pid = mem.find_pid("NMS.exe", require_exe=True)
    if not attach and pid:
        # 游戏已在运行：绝不再让 Steam 拉起第二个实例（会抢占存档/端口并导致崩溃）。
        return {"ok": False, "code": "E_GAME_RUNNING", "pid": pid,
                "game_running": True, "attach": False,
                "error": ("游戏已在运行；请选择「附加注入」或先关闭游戏后「重启并注入」。"
                          "已进入存档时附加注入可能让游戏退出，建议先回主菜单。")}
    if attach:
        if not pid:
            raise RuntimeError("游戏没有运行：请先启动游戏并停在主菜单，再点「附加注入」")
        # Steam 启动瞬间会出现没有主窗口的同名子进程；注入到它只会得到
        # “0 hooks、代理不可达”。等真正带窗口的游戏进程出现再注入。
        window_pid = mem.find_pid("NMS.exe", require_exe=True, require_window=True)
        if not window_pid:
            raise RuntimeError(
                "游戏进程还在启动/加载（没有主窗口）。等主菜单画面出现后，"
                "再点「附加注入」；不要在这一步重复点击。")
        pid = window_pid
    if not attach and not exe:
        raise RuntimeError("没有配置游戏目录（设置页选择游戏根目录）")
    overrides = {
        "pid": pid if attach else None,
        # attach 模式不能传 exe：pymhf 见到 exe 会走"按进程名注入"分支，
        # 并把我们给的 `...\Binaries\NMS.exe` 再拼一次 Binaries（实测报
        # `...\Binaries\Binaries\NMS.exe`）。只给 pid，pymhf 会自己从进程取路径。
        "exe": None if attach else (exe or None),
        "start_exe": not attach,
        # 注入完成前保持进程暂停：对 NMS 这种一启动就有大量线程/DRM 钩子的宿主，
        # “先跑起来再注入”会让注入线程撞上加载器锁（实测 python311.dll 里
        # PyImport_GetModule 空指针崩溃）。ping/notepad 对照实验两种取值都正常，
        # 所以这里选更保守的一侧。
        "start_paused": True,
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
    token = _load_or_create_token()
    # 游戏若由 Steam 拉起就不会继承这里的环境变量；持久化 token 文件是 agent 的
    # 第二来源（见 starforge_agent._resolve_agent_token）。这里绝不每次换 token，
    # 否则已经注入的 agent 仍用旧 token，客户端会一直 401。
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    # agent 端读取并在每个 endpoint 校验；客户端通过 ?token= 传入。
    env["STARFORGE_AGENT_TOKEN"] = token
    env["STARFORGE_AGENT_PORT"] = str(port)
    # pymhf 的 __init__ 在非 pytest 环境会创建 questionary 提示；agent 是无人值守启动，
    # 设置这个变量让它跳过交互（load_mod_file 本身不走交互配置）。
    env["PYTEST_VERSION"] = "1"
    log_path = launcher_log_path()
    log_file = open(log_path, "a", encoding="utf-8")
    global _LAUNCH
    py = runtime_python()
    if not py:
        log_file.close()
        raise RuntimeError("没有可用的 Python 运行时；请先点「准备游戏内运行时」")
    _apply_own_pid_patch(py)
    with _LAUNCH_LOCK:
        try:
            _LAUNCH = subprocess.Popen(
                [str(py), "-c", code, str(installed_mod()),
                 json.dumps(overrides)],
                cwd=str(agent_dir()), stdout=log_file, stderr=subprocess.STDOUT,
                env=env, close_fds=True,
                creationflags=(_NO_WINDOW | 0x00000008) if os.name == "nt" else 0,
            )
        finally:
            log_file.close()
        base = base_for_port(port)
        write_state({
            "version": 1,
            "token": token,
            "port": port,
            "base": base,
            "pid": _LAUNCH.pid,
            "started_at": time.time(),
            "build_id": build.build_id(fp),
            "attach": bool(attach),
            "launcher_log": str(log_path),
            "token_in": "query",
            "port_note": "pymhf 固定端口；STARFORGE_AGENT_PORT 仅在 runtime 支持时生效",
        })
    out = {"ok": True, "pid": _LAUNCH.pid, "log": str(log_path),
           "port": port, "base": base, "state": str(state_file()),
           "token_auth": "query",
           "build_id": build.build_id(fp), "attach": attach}
    # 不要只看 Popen 成功：NMS 可能因为检测到注入而自行退出。
    alive = injected_game_alive(pid=pid) if attach else injected_game_alive()
    if not alive:
        out.update({
            "ok": False, "code": "E_GAME_EXITED",
            "error": ("注入后游戏进程已退出：NMS 会把注入的 Python/ctypes 识别为模组冲突并关闭游戏"
                      "（build 185034 实测，无崩溃转储）。不要反复重试；"
                      "存档写回、模板槽读写与表情领取都不受影响。"),
        })
    return out


def injected_game_alive(wait: float = 6.0, pid: int | None = None) -> bool:
    """注入后短暂观察游戏是否还活着。

    实测 build 185034：NMS 会把注入的 Python/ctypes 识别成"模组冲突"，
    弹出“是否禁用所有模组”后主动退出（无崩溃转储、不写 DISABLEMODS.TXT）。
    所以 launch() 不能只因为 Popen 成功就报告成功。

    传入 ``pid`` 时只检查该 PID 是否还在同名进程列表里，避免游戏崩溃后留下的
    另一个 NMS.exe 僵尸让结果看起来“还活着”。
    """
    time.sleep(max(0.0, wait))
    try:
        if pid is not None:
            return int(pid) in {int(x) for x in mem.iter_pids("NMS.exe")}
        return bool(mem.find_pid("NMS.exe"))
    except Exception:                                      # noqa: BLE001
        return False


def stop() -> dict:
    """停止本应用启动的 launcher；不清游戏进程，也不假装已解除注入。"""
    global _LAUNCH
    with _LAUNCH_LOCK:
        state = read_state()
        client = AgentClient(timeout=1.0)
        reachable = client.ping()
        stopped = None
        if _LAUNCH and _LAUNCH.poll() is None:
            _LAUNCH.terminate()
            stopped = _LAUNCH.pid
        clear_state()
    note = "已停止 launcher 进程"
    if reachable:
        note += "；agent 仍可能已注入游戏，彻底停用需重启游戏"
    if not stopped:
        note += "；没有本应用启动的 launcher 句柄（可能应用已重启），未盲目结束其它进程"
    return {"ok": True, "stopped": stopped, "launcher_pid": state.get("pid"),
            "agent_reachable": bool(reachable), "note": note}


def wait_ready(timeout: float = 20.0) -> dict:
    """启动后轮询 HTTP，给界面一个确定的“已连接/超时”。"""
    client = AgentClient()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if client.ping():
            try:
                return {"ok": True, "hello": client.hello(), "base": client.base}
            except AgentError as e:
                return {"ok": False, "error": str(e)}
        time.sleep(0.5)
    return {"ok": False,
            "error": f"{timeout:.0f}s 内没有连上 agent；看 {launcher_log_path()}"}
