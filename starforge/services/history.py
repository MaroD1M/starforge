"""本地最近活动/历史。

历史保存在 ``~/.starforge/history.json``（可用 ``STARFORGE_HOME`` 覆盖），
结构::

    {"format": "starforge-history", "version": 1,
     "items": [{"kind": "search", "title": "搜索完成", "detail": "...",
                "ts": "2026-11-18T12:34:56+08:00", "ref": "search",
                "ok": true, "failed": false, "result": "ok"}]}

条目按时间倒序保存，最多 200 条。所有写操作都在进程内锁里完成，并通过
「临时文件 + os.replace」原子落盘；读/写异常都不会影响调用方的主流程。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import paths

FORMAT = "starforge-history"
VERSION = 1
FILENAME = "history.json"
MAX_ITEMS = 200
LIMIT = MAX_ITEMS

_LIST = list
_LOCK = threading.RLock()


class HistoryStore:
    """线程安全的活动历史；``path=None`` 时跟随 ``STARFORGE_HOME``。"""

    def __init__(self, path: str | os.PathLike | None = None):
        self._path = Path(path).expanduser() if path is not None else None

    def file(self, path: str | os.PathLike | None = None) -> Path:
        return history_file(path if path is not None else self._path)

    def list(self, limit: int | None = None,
             path: str | os.PathLike | None = None) -> list[dict]:
        with _LOCK:
            items = deepcopy(_load_file(self.file(path))["items"])
        if limit is not None:
            items = items[: max(0, int(limit))]
        return items

    def recent(self, limit: int = 8,
               path: str | os.PathLike | None = None) -> list[dict]:
        return self.list(limit=limit, path=path)

    def record(self, kind: str, title: str, detail: str = "",
               ref: str | None = None, ok: bool = True,
               path: str | os.PathLike | None = None,
               ts: str | None = None, **kw: Any) -> dict:
        if "failed" in kw:
            ok = not bool(kw["failed"])
        item = _make_item(kind, title, detail, ref, ok, ts)
        try:
            with _LOCK:
                p = self.file(path)
                data = _load_file(p)
                data["items"].insert(0, item)
                _save_file(p, data["items"])
        except Exception:                                   # noqa: BLE001
            # 历史只是辅助信息，任何磁盘/权限错误都不能打断主操作。
            pass
        return deepcopy(item)

    def add(self, *args: Any, **kw: Any) -> dict:
        return self.record(*args, **kw)

    def append(self, *args: Any, **kw: Any) -> dict:
        return self.record(*args, **kw)

    def clear(self, path: str | os.PathLike | None = None) -> None:
        try:
            with _LOCK:
                _save_file(self.file(path), [])
        except Exception:                                   # noqa: BLE001
            pass


def history_file(path: str | os.PathLike | None = None) -> Path:
    """历史文件路径；不传时按 ``STARFORGE_HOME`` 动态解析。"""
    if path is not None:
        return Path(path).expanduser()
    return paths.app_home() / FILENAME


def _empty() -> dict:
    return {"format": FORMAT, "version": VERSION, "items": []}


def _make_item(kind: str, title: str, detail: str = "", ref: str | None = None,
               ok: bool = True, ts: str | None = None) -> dict:
    stamp = ts or datetime.now().astimezone().isoformat(timespec="seconds")
    item = {
        "kind": str(kind or ""),
        "title": str(title or ""),
        "detail": str(detail or ""),
        "ts": stamp,
        "ok": bool(ok),
        "failed": not bool(ok),
        "result": "ok" if ok else "failed",
    }
    if ref:
        item["ref"] = str(ref)
    return item


def _normalize_item(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    title = raw.get("title")
    if not kind and not title:
        return None
    ok = raw.get("ok")
    if ok is None:
        if "failed" in raw:
            ok = not bool(raw["failed"])
        elif raw.get("result") is not None:
            ok = str(raw["result"]).lower() in ("ok", "success", "成功")
        else:
            ok = True
    return _make_item(str(kind or ""), str(title or ""), str(raw.get("detail") or ""),
                      raw.get("ref") if raw.get("ref") else None,
                      bool(ok), raw.get("ts") or None)


def _load_file(path: Path) -> dict:
    try:
        text = path.read_text("utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return _empty()
    except OSError:
        return _empty()
    if not text.strip():
        return _empty()
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        return _empty()
    if isinstance(raw, dict):
        items = raw.get("items")
        if items is None:
            items = raw.get("history")
        if items is None:
            items = raw.get("entries")
        if items is None:
            items = []
    elif isinstance(raw, _LIST):
        items = raw
    else:
        return _empty()
    if not isinstance(items, _LIST):
        return _empty()
    clean = []
    for entry in items:
        item = _normalize_item(entry)
        if item is not None:
            clean.append(item)
        if len(clean) >= MAX_ITEMS:
            break
    return {"format": FORMAT, "version": VERSION, "items": clean}


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _save_file(path: Path, items: list[dict]) -> None:
    _atomic_write(path, {"format": FORMAT, "version": VERSION,
                         "items": _LIST(items)[:MAX_ITEMS]})


_DEFAULT = HistoryStore()
History = HistoryStore


# --------------------------------------------------------------------- 模块级 API


def list(limit: int | None = None, path: Any = None) -> list[dict]:
    return _DEFAULT.list(limit=limit, path=path)


def recent(limit: int = 8, path: Any = None) -> list[dict]:
    return _DEFAULT.recent(limit=limit, path=path)


def record(kind: str, title: str, detail: str = "", ref: str | None = None,
           ok: bool = True, path: Any = None, ts: str | None = None,
           **kw: Any) -> dict:
    return _DEFAULT.record(kind, title, detail, ref, ok, path, ts, **kw)


def add(kind: str, title: str, detail: str = "", ref: str | None = None,
        ok: bool = True, path: Any = None, ts: str | None = None,
        **kw: Any) -> dict:
    return record(kind, title, detail, ref, ok, path, ts, **kw)


def append(kind: str, title: str, detail: str = "", ref: str | None = None,
           ok: bool = True, path: Any = None, ts: str | None = None,
           **kw: Any) -> dict:
    return record(kind, title, detail, ref, ok, path, ts, **kw)


def clear(path: Any = None) -> None:
    return _DEFAULT.clear(path)


load = list
entries = list
all_entries = list
latest = recent
recent_items = recent
log = record
push = record
record_history = record
clear_history = clear


__all__ = [
    "HistoryStore", "History", "FORMAT", "VERSION", "FILENAME", "MAX_ITEMS", "LIMIT",
    "history_file", "list", "recent", "record", "add", "append", "clear", "load",
    "entries", "all_entries", "latest", "recent_items", "log", "push",
    "record_history", "clear_history",
]
