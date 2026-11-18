#!/usr/bin/env python3
"""包体体积报告（纯 stdlib，CI / 本机都能跑）。

用法::

    python scripts/size_report.py dist/starforge/_internal
    python scripts/size_report.py dist/starforge --top 30 --by package
    python scripts/size_report.py dist/starforge --by category
    python scripts/size_report.py dist/starforge-v0.14.4-win64.zip --top 30 --fail-over 110
    python scripts/size_report.py dist/starforge --json > before.json
    python scripts/size_report.py dist/starforge --compare before.json
    python scripts/size_report.py --self-test

设计目标：
  * 不依赖第三方库（release runner 只保证 Python + 项目依赖）；
  * 目录和 zip 都支持；zip 直接读中央目录，不解压；
  * 支持按目录（dir）、包（package）、类别（category）聚合；
  * 可用 --compare 读取裁剪前的 JSON，报告裁剪前后差异；
  * 脚本只读，不修改 dist。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

MIB = 1024 * 1024
GROUP_BY_CHOICES = ("dir", "package", "category")

DEV_DIR_NAMES = {
    "__pycache__", "tests", "test", "examples", "demos", "samples",
    "docs", "doc", "include", "headers",
}
DEV_SUFFIXES = {".pyc", ".pyo", ".pyi", ".pdb", ".lib", ".a", ".exp",
                ".h", ".hpp", ".hh", ".hxx"}
BINARY_SUFFIXES = {".dll", ".pyd", ".so", ".dylib", ".exe"}
DATA_SUFFIXES = {
    ".dat", ".json", ".qss", ".png", ".ico", ".ttf", ".ttc", ".qm",
    ".xml", ".js", ".css", ".html", ".svg", ".zip",
}
LAUNCHER_SUFFIXES = {".exe", ".bat", ".cmd", ".ps1"}


def human(n: int) -> str:
    """把字节数格式化成便于阅读的 MiB/KiB。"""
    if n >= MIB:
        return f"{n / MIB:.1f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


def _strip_common_root(names: list[str]) -> str:
    """zip 里常有一层 starforge/；只在所有文件都位于同一目录下时剥离。"""
    if not names:
        return ""
    first = names[0].split("/", 1)[0]
    if "/" not in names[0]:
        return ""
    if all(n == first or n.startswith(first + "/") for n in names):
        return first
    return ""


def _parts(name: str) -> list[str]:
    return [p for p in name.replace("\\", "/").split("/") if p and p != "."]


def group_key_dir(name: str) -> str:
    """把相对路径归入一个有意义的顶层目录。"""
    parts = _parts(name)
    if len(parts) < 2:
        return "(根目录文件)"
    if parts[0] == "_internal":
        return "/".join(parts[:2])
    if parts[0] == "agent-runtime":
        if "site-packages" in parts:
            idx = parts.index("site-packages")
            if len(parts) > idx + 1:
                return "/".join(parts[: idx + 2])
        return "agent-runtime"
    return parts[0]


def group_key_package(name: str) -> str:
    """按 Python 包/顶层组件聚合（比 dir 更细，适合定位 agent 依赖）。"""
    parts = _parts(name)
    if len(parts) < 2:
        return "(根目录文件)"
    if parts[0] == "_internal":
        if len(parts) >= 3 or not Path(parts[1]).suffix:
            return "_internal/" + parts[1]
        return "_internal (根文件)"
    if parts[0] == "agent-runtime":
        if "site-packages" in parts:
            idx = parts.index("site-packages")
            if len(parts) > idx + 1:
                return "agent-runtime/" + parts[idx + 1]
            return "agent-runtime/site-packages"
        if parts[1] == "Lib" and len(parts) > 2 and not Path(parts[-1]).suffix:
            return "agent-runtime/Lib/" + parts[2]
        return "agent-runtime"
    return parts[0]


def _category_for_path(name: str) -> str:
    parts = _parts(name)
    lowered = "/".join(parts).lower()
    suffix = Path(name).suffix.lower()
    if suffix in DEV_SUFFIXES or any(p.lower() in DEV_DIR_NAMES for p in parts[:-1]):
        return "开发/测试冗余"
    if parts and parts[0] == "agent-runtime":
        return "agent runtime"
    if parts and parts[0] == "_internal":
        if "pyside6" in lowered or "qt6" in lowered or "/qt/" in lowered:
            return "Qt/PySide6"
        if lowered.startswith("_internal/numpy"):
            return "numpy"
        if lowered.startswith("_internal/unicorn"):
            return "unicorn"
        if suffix in BINARY_SUFFIXES:
            return "原生库/可执行文件"
        if suffix in DATA_SUFFIXES:
            return "数据/资源"
        return "其它 Python/模块"
    if suffix in LAUNCHER_SUFFIXES:
        return "启动器/脚本"
    if parts and parts[0] in {"starforge", "starforge-safe.bat"}:
        return "启动器/脚本"
    return "其它"


GROUPERS = {
    "dir": group_key_dir,
    "package": group_key_package,
    "category": _category_for_path,
}


def _group_rows(ranked: list, total: int, limit: int | None) -> list[dict]:
    rows = []
    for name, data in ranked[:limit] if limit is not None else ranked:
        rows.append({
            "name": name,
            "size": data["size"],
            "compressed": data["compressed"],
            "files": data["files"],
            "share": (data["size"] / total * 100) if total else 0.0,
        })
    return rows


def _report_from_entries(
    root_label: str,
    entries: list[tuple[str, int, int]],
    *,
    archive_size: int | None = None,
    top: int = 20,
    largest: int = 10,
    group_by: str = "dir",
) -> dict:
    """entries: [(relative_posix_name, file_size, compressed_size)]。"""
    if group_by not in GROUPERS:
        raise ValueError(f"未知聚合方式：{group_by}")
    names = [e[0] for e in entries]
    prefix = _strip_common_root(names)
    if prefix:
        entries = [
            (n[len(prefix) + 1:] if n.startswith(prefix + "/") else n, size, comp)
            for n, size, comp in entries
        ]
        root_label = f"{root_label} (已剥离 {prefix}/)"

    groups: dict[str, dict[str, int]] = defaultdict(
        lambda: {"size": 0, "compressed": 0, "files": 0}
    )
    total = total_compressed = 0
    grouper = GROUPERS[group_by]
    for name, size, comp in entries:
        key = grouper(name)
        groups[key]["size"] += size
        groups[key]["compressed"] += comp
        groups[key]["files"] += 1
        total += size
        total_compressed += comp

    ranked = sorted(groups.items(), key=lambda kv: kv[1]["size"], reverse=True)
    biggest = sorted(entries, key=lambda e: e[1], reverse=True)[:largest]

    return {
        "root": root_label,
        "group_by": group_by,
        "total_size": total,
        "total_compressed": total_compressed,
        "archive_size": archive_size,
        "file_count": len(entries),
        "groups": _group_rows(ranked, total, top),
        "groups_all": _group_rows(ranked, total, None),
        "largest": [
            {"name": name, "size": size, "compressed": comp}
            for name, size, comp in biggest
        ],
    }


def scan_dir(
    root: Path, *, top: int = 20, largest: int = 10, group_by: str = "dir"
) -> dict:
    entries: list[tuple[str, int, int]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fname in filenames:
            p = Path(dirpath) / fname
            try:
                size = p.stat().st_size
            except OSError:
                continue
            rel = p.relative_to(root).as_posix()
            entries.append((rel, size, size))
    return _report_from_entries(
        str(root), entries, top=top, largest=largest, group_by=group_by
    )


def scan_zip(
    path: Path, *, top: int = 20, largest: int = 10, group_by: str = "dir"
) -> dict:
    entries: list[tuple[str, int, int]] = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            entries.append((info.filename.replace("\\", "/"), info.file_size, info.compress_size))
    return _report_from_entries(
        str(path),
        entries,
        archive_size=path.stat().st_size,
        top=top,
        largest=largest,
        group_by=group_by,
    )


def compare_reports(baseline: dict, current: dict) -> dict:
    """计算 current 相对 baseline 的体积变化（用于 CI 裁剪前后对比）。"""
    base_groups = {g["name"]: g for g in baseline.get("groups_all")
                   or baseline.get("groups", [])}
    cur_groups = {g["name"]: g for g in current.get("groups_all")
                  or current.get("groups", [])}
    changes = []
    for name in sorted(set(base_groups) | set(cur_groups)):
        before = int(base_groups.get(name, {}).get("size", 0))
        after = int(cur_groups.get(name, {}).get("size", 0))
        changes.append({
            "name": name,
            "before": before,
            "after": after,
            "delta": after - before,
            "files_before": int(base_groups.get(name, {}).get("files", 0)),
            "files_after": int(cur_groups.get(name, {}).get("files", 0)),
        })
    changes.sort(key=lambda c: abs(c["delta"]), reverse=True)

    before_total = int(baseline.get("total_size", 0))
    after_total = int(current.get("total_size", 0))
    return {
        "baseline_root": baseline.get("root", ""),
        "baseline_total_size": before_total,
        "baseline_archive_size": baseline.get("archive_size"),
        "total_size_delta": after_total - before_total,
        "total_compressed_delta": int(current.get("total_compressed", 0))
        - int(baseline.get("total_compressed", 0)),
        "file_count_delta": int(current.get("file_count", 0))
        - int(baseline.get("file_count", 0)),
        "groups": changes,
    }


def _signed(n: int) -> str:
    return f"+{human(n)}" if n >= 0 else f"-{human(abs(n))}"


def print_comparison(comparison: dict) -> None:
    before = int(comparison.get("baseline_total_size", 0))
    delta = int(comparison.get("total_size_delta", 0))
    after = before + delta
    pct = (delta / before * 100) if before else 0.0
    print("\n裁剪前后对比（解压体积）:")
    print(f"  {human(before)} -> {human(after)}  ({_signed(delta)}, {pct:+.1f}%)")
    if comparison.get("file_count_delta"):
        print(f"  文件数变化: {comparison['file_count_delta']:+d}")
    rows = [c for c in comparison.get("groups", []) if c["delta"]]
    if rows:
        print(f"  {'目录/包/类别':<46} {'裁剪前':>10}  {'裁剪后':>10}  {'变化':>10}")
        for c in rows[:15]:
            name = c["name"]
            if len(name) > 44:
                name = "…" + name[-43:]
            print(f"  {name:<46} {human(c['before']):>10}  "
                  f"{human(c['after']):>10}  {_signed(c['delta']):>10}")


def print_report(report: dict) -> None:
    label = {"dir": "目录", "package": "包", "category": "类别"}.get(
        report.get("group_by", "dir"), report.get("group_by", "dir")
    )
    print(f"\n体积报告: {report['root']}（按{label}）")
    print(f"文件数: {report['file_count']}")
    print(f"解压体积: {human(report['total_size'])}")
    if report["archive_size"] is not None:
        print(f"zip 实际大小: {human(report['archive_size'])}")
        print(f"zip 内条目压缩后合计: {human(report['total_compressed'])}")

    print(f"\n{label}排行（按解压体积）:")
    print(f"  {'#':>2}  {label:<46} {'体积':>10}  {'占比':>6}  {'文件':>6}")
    for i, g in enumerate(report["groups"], 1):
        name = g["name"]
        if len(name) > 44:
            name = "…" + name[-43:]
        print(f"  {i:>2}  {name:<46} {human(g['size']):>10}  {g['share']:>5.1f}%  {g['files']:>6}")

    if report["largest"]:
        print("\n最大文件:")
        for f in report["largest"]:
            name = f["name"]
            if len(name) > 62:
                name = "…" + name[-61:]
            print(f"  {human(f['size']):>10}  {name}")
    if report.get("comparison"):
        print_comparison(report["comparison"])
    print()


def relevant_size(report: dict) -> int:
    """预算判断用实际发布物大小：zip 用归档大小，目录用解压体积。"""
    return int(report["archive_size"] or report["total_size"])


def _self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="sf-size-") as td:
        root = Path(td) / "dist" / "starforge"
        files = {
            "_internal/PySide6/Qt6Core.dll": b"x" * 1200,
            "_internal/numpy/_core/a.pyd": b"y" * 700,
            "_internal/unicorn/lib/unicorn.dll": b"z" * 500,
            "_internal/numpy/tests/test_x.py": b"t" * 90,
            "agent-runtime/python.exe": b"p" * 300,
            "agent-runtime/Lib/site-packages/dearpygui/dearpygui.py": b"d" * 200,
            "agent-runtime/Lib/site-packages/dearpygui/__pycache__/x.pyc": b"c" * 40,
            "starforge.exe": b"e" * 100,
        }
        for rel, data in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

        rep = scan_dir(root)
        assert rep["total_size"] == sum(len(v) for v in files.values()), rep
        assert rep["group_by"] == "dir", rep
        keys = {g["name"] for g in rep["groups"]}
        assert "_internal/PySide6" in keys, keys
        assert "_internal/numpy" in keys, keys
        assert "_internal/unicorn" in keys, keys
        assert "agent-runtime/Lib/site-packages/dearpygui" in keys, keys
        assert "(根目录文件)" in keys, keys

        prep = scan_dir(root, group_by="package")
        pkeys = {g["name"] for g in prep["groups_all"]}
        assert "_internal/PySide6" in pkeys, pkeys
        assert "_internal/numpy" in pkeys, pkeys
        assert "_internal/unicorn" in pkeys, pkeys
        assert "agent-runtime/dearpygui" in pkeys, pkeys
        assert "agent-runtime" in pkeys or "agent-runtime (根文件)" in pkeys, pkeys

        crep = scan_dir(root, group_by="category")
        ckeys = {g["name"] for g in crep["groups_all"]}
        assert "Qt/PySide6" in ckeys, ckeys
        assert "numpy" in ckeys, ckeys
        assert "unicorn" in ckeys, ckeys
        assert "agent runtime" in ckeys, ckeys
        assert "开发/测试冗余" in ckeys, ckeys
        assert "启动器/脚本" in ckeys, ckeys

        same = compare_reports(rep, rep)
        assert same["total_size_delta"] == 0, same
        assert all(c["delta"] == 0 for c in same["groups"]), same

        extra = root / "_internal" / "numpy" / "_core" / "b.pyd"
        extra.write_bytes(b"n" * 30)
        rep2 = scan_dir(root)
        cmp = compare_reports(rep, rep2)
        assert cmp["total_size_delta"] == 30, cmp
        assert any(c["name"] == "_internal/numpy" and c["delta"] == 30
                   for c in cmp["groups"]), cmp

        assert json.loads(json.dumps(rep2))["total_size"] == rep2["total_size"]

        zpath = Path(td) / "starforge-test.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel, data in files.items():
                zf.writestr("starforge/" + rel, data)
        zrep = scan_zip(zpath)
        assert zrep["total_size"] == rep["total_size"], zrep
        assert "_internal/PySide6" in {g["name"] for g in zrep["groups"]}, zrep
        assert zrep["archive_size"] == zpath.stat().st_size

        zprep = scan_zip(zpath, group_by="package")
        assert "agent-runtime/dearpygui" in {g["name"] for g in zprep["groups_all"]}, zprep
    print("size_report self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(description="统计 dist 包体（stdlib，支持 zip/目录）")
    ap.add_argument("path", nargs="?", help="dist 目录或发布 zip（默认 dist/starforge）")
    ap.add_argument("--top", type=int, default=20, help="显示前 N 项（默认 20）")
    ap.add_argument("--largest", type=int, default=10, help="显示前 N 个最大文件（默认 10）")
    ap.add_argument("--by", "--group-by", dest="group_by", choices=GROUP_BY_CHOICES,
                    default="dir", help="聚合方式：dir（目录）/package（包）/category（类别）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（便于其它脚本消费）")
    ap.add_argument("--compare", metavar="BASELINE.json",
                    help="读取裁剪前的 JSON，报告裁剪前后对比")
    ap.add_argument("--fail-over", type=float, metavar="MIB",
                    help="超过该体积（MiB）时以退出码 1 结束；zip 按归档大小判断")
    ap.add_argument("--self-test", action="store_true", help="创建临时目录/zip 做自检后退出")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()

    target = Path(a.path or "dist/starforge")
    if not target.exists():
        print(f"路径不存在：{target}", file=sys.stderr)
        print("示例：python scripts/size_report.py dist/starforge/_internal", file=sys.stderr)
        return 2

    if zipfile.is_zipfile(target):
        report = scan_zip(target, top=a.top, largest=a.largest, group_by=a.group_by)
    elif target.is_dir():
        report = scan_dir(target, top=a.top, largest=a.largest, group_by=a.group_by)
    else:
        print(f"不是目录也不是 zip：{target}", file=sys.stderr)
        return 2

    if a.compare:
        baseline_path = Path(a.compare)
        if not baseline_path.exists():
            print(f"对比基线不存在：{baseline_path}", file=sys.stderr)
            return 2
        try:
            baseline = json.loads(baseline_path.read_text("utf-8-sig"))
        except (OSError, ValueError) as e:
            print(f"读取对比基线失败：{e}", file=sys.stderr)
            return 2
        report["comparison"] = compare_reports(baseline, report)

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)

    if a.fail_over is not None:
        size = relevant_size(report) / MIB
        if size > a.fail_over:
            print(
                f"体积超标：{size:.1f} MiB > 预算 {a.fail_over:.1f} MiB",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
