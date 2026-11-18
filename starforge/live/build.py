"""游戏 build 指纹与地址书（agent 的版本绑定）。

每个 NMS 更新都可能改函数地址/结构体偏移。agent **不允许**猜：
  · 先用 ``NMS.exe`` 的 sha256 + size + version 算出 build id；
  · 地址书里没有这个 build → 只允许只读能力，写/传送/扫描默认禁用；
  · 有多个同样可信的签名候选 → 拒绝写入（宁可不做，也不写错对象）。

地址书来源：
  1) 随包内置：``starforge/live/builds/*.json``（已验证的 build）；
  2) 用户实测：``~/.starforge/builds/*.json``（你回报后补进去的 build）。

本模块只做指纹/查找，不碰游戏进程。
"""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any


# 这些能力会改写游戏状态（位置/发现列表/扫描进度），必须只在已验证 build 上开放。
HIGH_RISK_CAPABILITIES = frozenset({"teleport", "restore", "scan.discover", "scan.instant"})


def _shipped_dir() -> Path:
    here = Path(__file__).resolve().parent / "builds"
    if here.exists():
        return here
    import sys
    cands = []
    if getattr(sys, "_MEIPASS", ""):
        cands.append(Path(sys._MEIPASS) / "starforge" / "live" / "builds")
    exe_dir = Path(sys.executable).resolve().parent
    cands += [exe_dir / "_internal" / "starforge" / "live" / "builds",
              exe_dir / "starforge" / "live" / "builds"]
    for c in cands:
        if c.exists():
            return c
    return here


def _user_dir() -> Path:
    from ..core import paths

    d = paths.app_home() / "builds"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fingerprint(exe_path: str | Path | None = None) -> dict:
    """读 NMS.exe 的稳定指纹；文件不存在时返回 ``{"error": ...}``。"""
    if exe_path is None:
        from ..core import settings

        game = settings.current().game_dir
        if not game:
            try:
                from ..locate_game import find

                game = find() or ""
            except Exception:                            # noqa: BLE001
                game = ""
        if not game:
            return {"error": "没有配置游戏目录"}
        exe_path = Path(game) / "Binaries" / "NMS.exe"
    p = Path(exe_path)
    if not p.exists():
        return {"error": f"文件不存在：{p}"}
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    st = p.stat()
    return {"path": str(p), "size": int(st.st_size),
            "mtime": int(st.st_mtime), "sha256": h.hexdigest().upper(),
            "version": _file_version(p), "platform": platform.platform()}


def _file_version(p: Path) -> str:
    """尽量取 PE 的 FileVersion；没有 pefile 时退回空串（sha256 仍是主键）。"""
    try:
        import pefile

        pe = pefile.PE(str(p), fast_load=True)
        info = getattr(pe, "VS_FIXEDFILEINFO", None) or []
        if info:
            v = info[0].dwFileVersionMS, info[0].dwFileVersionLS
            return "%d.%d.%d.%d" % (v[0] >> 16, v[0] & 0xFFFF, v[1] >> 16, v[1] & 0xFFFF)
    except Exception:                                    # noqa: BLE001
        pass
    return ""


def build_id(fp: dict | None = None) -> str:
    fp = fp or {}
    sha = (fp.get("sha256") or "")[:12]
    ver = fp.get("version") or fp.get("size") or "unknown"
    return f"{ver}-{sha}" if sha else str(ver)


def _load_dir(d: Path) -> list[dict]:
    out = []
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            data = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data.setdefault("source", str(p))
            out.append(data)
    return out


def known_builds() -> list[dict]:
    """内置 + 用户实测的 build 列表（同一 build 用户目录优先）。"""
    merged: dict[str, dict] = {}
    for row in _load_dir(_shipped_dir()) + _load_dir(_user_dir()):
        key = row.get("build") or row.get("sha256") or row.get("id")
        if key:
            merged[str(key)] = row
    return list(merged.values())


def lookup(fp: dict | None = None) -> dict | None:
    fp = fp or fingerprint()
    if fp.get("error"):
        return None
    sha = (fp.get("sha256") or "").upper()
    for row in known_builds():
        if (row.get("sha256") or "").upper() == sha:
            return row
    return None


def register(fp: dict, extra: dict | None = None) -> Path:
    """把一份实测指纹写进用户地址书（默认 status=unverified）。"""
    row: dict[str, Any] = {
        "build": str(fp.get("version") or fp.get("size") or "unknown"),
        "sha256": (fp.get("sha256") or "").upper(),
        "size": fp.get("size"),
        "version": fp.get("version") or "",
        "status": "unverified",
        "notes": "由 starforge 记录；签名/偏移需 Windows 实机校准后补全",
        "signatures": {},
        "offsets": {},
    }
    row.update(extra or {})
    name = (row.get("build") or "build") + ".json"
    path = _user_dir() / name
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2), "utf-8")
    return path


def summary(fp: dict | None = None) -> dict:
    """build 指纹 + 写闸门。

    ``write_allowed`` 只有在地址书里明确 ``status == "verified"`` 时才为 True；
    未知 build 和未验证 build 都保持只读，并通过 ``reason`` 说明原因。
    返回字段是在旧结构（fingerprint/build_id/known/verified/write_allowed）上追加，
    调用方可以继续只读旧字段。
    """
    fp = fp or fingerprint()
    row = lookup(fp)
    raw_status = (row or {}).get("status")
    status = str(raw_status or "").strip().lower()
    verified = status == "verified"
    if verified:
        reason = ""
    elif row:
        reason = (f"这版未验证（build {build_id(fp)}，status={status or 'unknown'}）："
                  "只允许只读能力")
    elif fp.get("error"):
        reason = f"无法确认游戏 build：{fp['error']}；只允许只读能力"
    else:
        reason = f"这版未验证（build {build_id(fp)} 不在地址书）：只允许只读能力"
    return {"fingerprint": fp, "build_id": build_id(fp), "known": row,
            "status": status or ("unknown" if not row else ""),
            "verified": verified, "write_allowed": verified, "reason": reason}
