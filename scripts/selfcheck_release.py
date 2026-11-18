#!/usr/bin/env python3
"""Starforge 发布前自检（纯 stdlib，CI / 本机都能跑）。

用法::

    python3 scripts/selfcheck_release.py
    python3 scripts/selfcheck_release.py --json
    python3 scripts/selfcheck_release.py --fail-on error

检查项：
  * 版本号一致性：``starforge/__init__.py``、``pyproject.toml``、``CHANGELOG.md``
    最新标题，并提示最近的 git tag；
  * 必需文件：原生壳、页面目录、agent、``live/builds/*.json``、文档索引；
  * 文档链接：``docs/README.md`` 中的相对链接目标是否存在；
  * 遗留依赖：``requirements*.txt`` / CI 工作流中不应再安装
    pywebview / pythonnet / clr_loader / tkinter（注释、legacy extra、
    PyInstaller ``--exclude-module`` 不算）；
  * 过期标记：关键代码里的 TODO / FIXME / “待实现”只统计，不判失败。

退出码：默认存在 ``error`` 时为 1；``--fail-on warning`` 时 warning 也为 1；
``--fail-on none`` 永远为 0。脚本只读，不修改任何文件。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]

VERSION_RE = re.compile(r'^\s*__version__\s*=\s*["\']([^"\']+)["\']', re.M)
PROJECT_VERSION_RE = re.compile(r'^\s*version\s*=\s*["\']([^"\']+)["\']', re.M)
CHANGELOG_VERSION_RE = re.compile(r'^##\s+v?([0-9][^\s（(]*)', re.M)
LINK_RE = re.compile(r'!?\[[^\]]*\]\(([^)]+)\)')
MARKER_RE = re.compile(r'\b(?:TODO|FIXME)\b|待实现', re.I)
LEGACY_RE = re.compile(r'(?<![A-Za-z0-9_])(pywebview|pythonnet|clr_loader|_?tkinter)(?![A-Za-z0-9_])',
                       re.I)

OPTIONAL_INDEX_DOCS = (
    "GAP-ANALYSIS.md",
    "COMMUNITY-UI-ROADMAP.md",
    "INGAME-SCAN-FEASIBILITY.md",
    "UI-TERMS.md",
    "PACKAGING.md",
    "SAVE-API-INVENTORY.md",
    "CLEANUP-AUDIT.md",
)

KEY_FILE_GLOBS = (
    "starforge/app/**/*.py",
    "starforge/services/**/*.py",
    "starforge/live/**/*.py",
    "starforge/agent/**/*.py",
    "starforge/core/**/*.py",
    "starforge/save/**/*.py",
    "starforge/__main__.py",
    "packaging/*.py",
)

REQUIRED_FILES = (
    "starforge/app/shell.py",
    "starforge/agent/starforge_agent.py",
    "docs/README.md",
    "CHANGELOG.md",
    "pyproject.toml",
)


def _base_version(version: str) -> str:
    """0.14.4-beta / v0.14.4 -> 0.14.4。"""
    text = version.strip().lstrip("vV")
    return re.split(r"[-+]", text, maxsplit=1)[0]


def _read(path: Path) -> str:
    return path.read_text("utf-8", errors="replace")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _find_version(path: Path, pattern: re.Pattern[str]) -> str | None:
    if not path.is_file():
        return None
    match = pattern.search(_read(path))
    return match.group(1) if match else None


def _git_latest_tag() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def _check_result(check_id: str, status: str, message: str,
                  details: list[str] | None = None) -> dict:
    return {
        "id": check_id,
        "status": status,
        "message": message,
        "details": details or [],
    }


def check_versions() -> list[dict]:
    checks: list[dict] = []
    init_path = ROOT / "starforge/__init__.py"
    pyproject_path = ROOT / "pyproject.toml"
    changelog_path = ROOT / "CHANGELOG.md"

    init_version = _find_version(init_path, VERSION_RE)
    project_version = _find_version(pyproject_path, PROJECT_VERSION_RE)

    details: list[str] = []
    if not init_version:
        details.append("starforge/__init__.py 未找到 __version__")
    if not project_version:
        details.append("pyproject.toml 未找到 [project] version")
    if details:
        checks.append(_check_result("version.files", "error", "版本号缺失", details))
    elif _base_version(init_version) != _base_version(project_version):
        checks.append(_check_result(
            "version.files", "error", "包版本号不一致",
            [f"starforge/__init__.py = {init_version}",
             f"pyproject.toml = {project_version}"],
        ))
    else:
        note = "" if init_version == project_version else "（仅预发布后缀不同）"
        checks.append(_check_result(
            "version.files", "ok",
            f"__init__ 与 pyproject 一致：{init_version}{note}",
        ))

    latest = None
    if changelog_path.is_file():
        match = CHANGELOG_VERSION_RE.search(_read(changelog_path))
        latest = match.group(1) if match else None
    if not latest:
        checks.append(_check_result(
            "version.changelog", "error",
            "CHANGELOG.md 未找到形如 `## vX.Y.Z` 的最新标题",
        ))
    elif not init_version:
        checks.append(_check_result(
            "version.changelog", "error",
            f"CHANGELOG 最新标题为 {latest}，但包版本号缺失",
        ))
    elif _base_version(latest) != _base_version(init_version):
        checks.append(_check_result(
            "version.changelog", "error", "CHANGELOG 最新版本与包版本不一致",
            [f"CHANGELOG.md = {latest}", f"starforge/__init__.py = {init_version}"],
        ))
    else:
        note = "" if latest == init_version else "（CHANGELOG 为预发布标题）"
        checks.append(_check_result(
            "version.changelog", "ok",
            f"CHANGELOG 最新标题与包版本一致：{latest}{note}",
        ))

    tag = _git_latest_tag()
    if not tag:
        checks.append(_check_result(
            "version.tag", "warning",
            "没有可用的 git tag；发布前请确认已打对应版本 tag",
        ))
    elif init_version and _base_version(tag) == _base_version(init_version):
        note = "" if _base_version(tag) == tag.lstrip("vV") else "（预发布 tag）"
        checks.append(_check_result(
            "version.tag", "ok", f"最近 tag 与包版本一致：{tag}{note}",
        ))
    else:
        checks.append(_check_result(
            "version.tag", "warning", "最近 git tag 与当前包版本不一致",
            [f"最近 tag = {tag}", f"包版本 = {init_version or '?'}"],
        ))
    return checks


def check_required_files() -> dict:
    missing = [rel for rel in REQUIRED_FILES if not (ROOT / rel).is_file()]
    pages = sorted((ROOT / "starforge/app/pages").glob("*.py"))
    if not pages:
        missing.append("starforge/app/pages/*.py")
    if not (ROOT / "starforge/agent").is_dir():
        missing.append("starforge/agent/")
    builds = sorted((ROOT / "starforge/live/builds").glob("*.json"))
    if not builds:
        missing.append("starforge/live/builds/*.json")

    details: list[str] = [f"缺少：{item}" for item in missing]
    status = "error" if missing else "ok"
    message = "必需文件缺失" if missing else (
        f"必需文件齐全（页面 {len(pages)} 个，builds {len(builds)} 个）"
    )
    return _check_result("files.required", status, message, details)


def check_build_json() -> dict:
    builds = sorted((ROOT / "starforge/live/builds").glob("*.json"))
    bad: list[str] = []
    for path in builds:
        try:
            data = json.loads(_read(path))
        except (OSError, ValueError) as exc:
            bad.append(f"{path.relative_to(ROOT)}: {exc}")
            continue
        if not isinstance(data, dict):
            bad.append(f"{path.relative_to(ROOT)}: 顶层不是 JSON 对象")
    if bad:
        return _check_result("files.builds", "error", "live/builds JSON 无效", bad)
    if not builds:
        return _check_result("files.builds", "error", "没有 live/builds/*.json")
    return _check_result(
        "files.builds", "ok",
        "live/builds JSON 可解析：" + ", ".join(p.name for p in builds),
    )


def _relative_link_targets(doc: Path) -> list[tuple[int, str, str]]:
    """返回 (行号, 原始目标, 去锚点后的相对路径)。"""
    out: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(_read(doc).splitlines(), 1):
        for match in LINK_RE.finditer(line):
            raw = match.group(1).strip()
            if raw.startswith("<") and raw.endswith(">"):
                raw = raw[1:-1].strip()
            if not raw:
                continue
            parsed = urlparse(raw)
            if parsed.scheme or raw.startswith("#") or raw.startswith("//"):
                continue
            target = unquote(parsed.path)
            if not target:
                continue
            out.append((lineno, raw, target))
    return out


def check_docs_index() -> dict:
    doc = ROOT / "docs/README.md"
    if not doc.is_file():
        return _check_result("docs.index", "error", "docs/README.md 不存在")
    targets = {target for _line, _raw, target in _relative_link_targets(doc)}
    names = {Path(target).name for target in targets}
    missing: list[str] = []
    for name in OPTIONAL_INDEX_DOCS:
        if (ROOT / "docs" / name).is_file() and name not in names:
            missing.append(f"docs/{name} 存在但未收录进 docs/README.md")
    if missing:
        return _check_result("docs.index", "warning", "文档索引未补齐", missing)
    return _check_result("docs.index", "ok", "docs/README.md 已收录现有新文档")


def check_doc_links() -> dict:
    doc = ROOT / "docs/README.md"
    if not doc.is_file():
        return _check_result("docs.links", "error", "docs/README.md 不存在")
    broken: list[str] = []
    for lineno, raw, target in _relative_link_targets(doc):
        resolved = (doc.parent / target).resolve()
        if not resolved.exists():
            broken.append(f"docs/README.md:{lineno}: {raw} -> {resolved}")
    if broken:
        return _check_result("docs.links", "error", "docs/README.md 存在失效相对链接", broken)
    return _check_result("docs.links", "ok", "docs/README.md 相对链接全部可达")


def _legacy_hits_in_file(path: Path, *, ci: bool) -> list[str]:
    hits: list[str] = []
    try:
        lines = _read(path).splitlines()
    except OSError as exc:
        return [f"{_display_path(path)}: 读取失败：{exc}"]
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ci and "--exclude-module" in line:
            continue
        code = line.split("#", 1)[0]
        match = LEGACY_RE.search(code)
        if match:
            hits.append(f"{_display_path(path)}:{lineno}: {stripped}（命中 {match.group(1)}）")
    return hits


def check_legacy_dependencies() -> dict:
    files = sorted(ROOT.glob("requirements*.txt"))
    workflows = ROOT / ".github/workflows"
    if workflows.is_dir():
        files += sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml"))
    hits: list[str] = []
    for path in files:
        hits += _legacy_hits_in_file(path, ci=path.suffix.lower() in (".yml", ".yaml"))
    if hits:
        return _check_result(
            "deps.legacy", "error",
            "requirements/CI 中仍出现已移除依赖（注释、legacy extra、--exclude-module 除外）",
            hits,
        )
    return _check_result(
        "deps.legacy", "ok",
        "requirements/CI 未发现 pywebview/pythonnet/clr_loader/tkinter 安装项",
    )


def check_expired_markers() -> dict:
    counts: dict[str, int] = {}
    total = 0
    for pattern in KEY_FILE_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            count = len(MARKER_RE.findall(_read(path)))
            if count:
                rel = str(path.relative_to(ROOT))
                counts[rel] = count
                total += count
    details = [f"{rel}: {count}" for rel, count in sorted(counts.items())]
    if total:
        message = f"TODO/FIXME/待实现 共 {total} 处（仅报告，不影响退出码）"
    else:
        message = "未发现 TODO/FIXME/待实现"
    return _check_result("markers.todo", "info", message, details)


def collect() -> dict:
    checks = []
    checks += check_versions()
    checks.append(check_required_files())
    checks.append(check_build_json())
    checks.append(check_docs_index())
    checks.append(check_doc_links())
    checks.append(check_legacy_dependencies())
    checks.append(check_expired_markers())

    summary = {"checks": len(checks), "ok": 0, "warning": 0, "error": 0, "info": 0}
    for check in checks:
        status = check["status"]
        summary[status] = summary.get(status, 0) + 1

    return {
        "tool": "starforge-selfcheck",
        "schema": 1,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "root": str(ROOT),
        "checks": checks,
        "summary": summary,
    }


def print_human(report: dict) -> None:
    labels = {"ok": "OK", "warning": "WARN", "error": "ERROR", "info": "INFO"}
    print("Starforge 发布前自检")
    print(f"根目录：{report['root']}")
    for check in report["checks"]:
        print(f"[{labels.get(check['status'], check['status']).upper()}] "
              f"{check['id']}: {check['message']}")
        if check["status"] in ("error", "warning"):
            for detail in check["details"]:
                print(f"       - {detail}")
    summary = report["summary"]
    print(f"结果：{summary['checks']} 项检查，"
          f"{summary['error']} error / {summary['warning']} warning / {summary['info']} info")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(
        description="Starforge 发布前自检（纯 stdlib，只读）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument(
        "--fail-on", choices=("none", "warning", "error"), default="error",
        help="达到该级别时以退出码 1 结束（默认 error）",
    )
    args = parser.parse_args(argv)

    report = collect()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human(report)

    summary = report["summary"]
    failed = False
    if args.fail_on == "error":
        failed = summary["error"] > 0
    elif args.fail_on == "warning":
        failed = summary["error"] > 0 or summary["warning"] > 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
