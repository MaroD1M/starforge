"""本地收藏夹与分享码。

收藏保存在 ``~/.starforge/favorites.json``（可用 ``STARFORGE_HOME`` 覆盖），
结构::

    {"format": "starforge-favs", "version": 1,
     "items": [{"type": "fighter", "seed": "0x...", "parts": [...], "name": "..."}]}

所有写操作都在进程内锁里完成，并通过「临时文件 + os.replace」原子落盘，
避免界面进程与后台任务同时读写时留下半个 JSON。

分享码格式::

    nsh1:<URL-safe base64(紧凑 JSON)>

JSON 固定包含 ``type``/``seed``/``parts``，可选 ``name``。解码时用
:class:`starforge.data.shipref.ShipRef` 校验船型、种子与部件名。为了兼容旧版
网页，解码也接受 ``type;seed;parts`` / ``type|seed|parts`` 的紧凑串。
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..core import paths
from ..data.shipref import ShipRef, ShipRefError

PREFIX = "nsh1:"
FORMAT = "starforge-favs"
VERSION = 1
FILENAME = "favorites.json"

# 模块里会导出一个名为 list 的函数（需求指定的 API），先留一份内建 list 的引用。
_LIST = list

_LOCK = threading.RLock()


class FavoritesError(ValueError):
    """收藏/分享码相关的可读错误。"""


class ShareCodeError(FavoritesError):
    """分享码格式或内容不合法。"""


class ShareRef(ShipRef):
    """解码分享码后得到的 ShipRef；额外支持字典式读取，方便界面直接使用。"""

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and hasattr(self, key)

    def keys(self):
        return tuple(self.__dataclass_fields__)  # type: ignore[attr-defined]

    def items(self):
        return ((k, getattr(self, k)) for k in self.keys())


# --------------------------------------------------------------------- 路径/存储


def favorites_file(path: str | os.PathLike | None = None) -> Path:
    """收藏文件路径；不传时按 ``STARFORGE_HOME`` 动态解析。"""
    if path is not None:
        return Path(path).expanduser()
    return paths.app_home() / FILENAME


def _empty() -> dict:
    return {"format": FORMAT, "version": VERSION, "items": []}


def _key(item: dict) -> tuple[str, str]:
    return (str(item.get("type") or "").lower(), str(item.get("seed") or "").upper())


def _normalize_item(ref: Any) -> dict:
    """把 ShipRef/dict 规范成收藏条目，并用 ShipRef 做完整校验。"""
    if isinstance(ref, ShipRef):
        ship = ref
    elif isinstance(ref, dict):
        fields = {k: ref.get(k) for k in
                  ("type", "seed", "parts", "model", "look", "name", "source",
                   "slot", "procedural") if k in ref}
        if not fields.get("type") or not fields.get("seed"):
            raise FavoritesError("收藏条目缺少 type 或 seed")
        ship = ShipRef(**fields)
    else:
        raise FavoritesError(f"无法识别的收藏来源：{type(ref).__name__}")
    try:
        ship = ship.normalized()
    except ShipRefError as e:
        raise FavoritesError(str(e)) from e
    name = ship.name if isinstance(ship.name, str) else str(ship.name or "")
    return {"type": ship.type, "seed": ship.seed,
            "parts": _LIST(ship.parts or []), "name": name.strip()}


def _coerce(ref: Any = None, seed: str | None = None, parts: Any = None,
            name: str | None = None, kw: dict | None = None) -> dict:
    """兼容多种调用：add("fighter", "0x..") / add({...}) / add(type=..., seed=...)。"""
    kw = kw or {}
    data: dict
    if ref is None:
        data = {k: v for k, v in kw.items()
                if k in ("type", "seed", "parts", "name")}
    elif isinstance(ref, str) and seed is not None:
        data = {"type": ref, "seed": seed}
        if parts is not None:
            data["parts"] = parts
        if name is not None:
            data["name"] = name
    elif isinstance(ref, (ShipRef, dict)):
        data = _normalize_item(ref)
        if parts is not None:
            data["parts"] = parts
        if name is not None:
            data["name"] = name
    elif isinstance(ref, str) and seed is None and kw.get("type"):
        data = {"type": kw["type"], "seed": ref}
        if parts is not None:
            data["parts"] = parts
        if name is not None:
            data["name"] = name
    else:
        raise FavoritesError("需要提供飞船 type 与 seed")
    if not data.get("type") or not data.get("seed"):
        raise FavoritesError("需要提供飞船 type 与 seed")
    return _normalize_item(data)


def _load_file(path: Path) -> dict:
    try:
        text = path.read_text("utf-8")
    except FileNotFoundError:
        return _empty()
    except OSError as e:
        raise FavoritesError(f"读不了收藏文件 {path}：{e}") from e
    if not text.strip():
        return _empty()
    try:
        raw = json.loads(text)
    except ValueError as e:
        raise FavoritesError(f"收藏文件不是合法 JSON：{e}") from e
    if isinstance(raw, dict):
        items = raw.get("items")
        if items is None:
            items = raw.get("favorites")
        if items is None:
            items = []
    elif isinstance(raw, _LIST):
        items = raw
    else:
        raise FavoritesError("收藏文件格式不对：根节点应为对象或数组")
    if not isinstance(items, _LIST):
        raise FavoritesError("收藏文件格式不对：items 应为数组")
    clean = []
    for item in items:
        try:
            clean.append(_normalize_item(item))
        except FavoritesError:
            continue                       # 单个坏条目不应让整个收藏夹打不开
    return {"format": FORMAT, "version": VERSION, "items": clean}


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
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
                         "items": _LIST(items)})


# --------------------------------------------------------------------- 分享码


def _payload(ref: Any) -> dict:
    item = _normalize_item(ref)
    out = {"type": item["type"], "seed": item["seed"], "parts": item["parts"]}
    if item.get("name"):
        out["name"] = item["name"]
    return out


def encode_share(ref: Any) -> str:
    """把 ShipRef/dict 编码成 ``nsh1:`` 开头的 URL-safe base64 分享码。"""
    raw = json.dumps(_payload(ref), ensure_ascii=False,
                     separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return PREFIX + body


def _decode_legacy(text: str) -> dict:
    """兼容旧网页的 ``type;seed;parts|parts`` / ``type|seed|parts`` 格式。"""
    sep = ";" if ";" in text else "|"
    bits = text.split(sep)
    if len(bits) < 2:
        raise ShareCodeError("分享码内容不是可识别的 JSON 或紧凑串")
    parts_raw = bits[2] if len(bits) > 2 else ""
    parts = [p for p in re.split(r"[|,]", parts_raw) if p]
    data = {"type": bits[0].strip(), "seed": bits[1].strip(), "parts": parts}
    if len(bits) > 3 and bits[3].strip():
        data["name"] = bits[3].strip()
    return data


def decode_share(code: str) -> ShareRef:
    """解码分享码并用 :class:`ShipRef` 校验；非法输入抛 :class:`ShareCodeError`。"""
    if not isinstance(code, str):
        raise ShareCodeError("分享码必须是字符串")
    text = code.strip()
    if not text:
        raise ShareCodeError("分享码为空")
    if text[:5].lower() == PREFIX:
        text = text[5:].strip()
    elif ":" in text[:8]:
        raise ShareCodeError(f"分享码前缀不对，应为 {PREFIX}")
    if not text:
        raise ShareCodeError("分享码缺少内容")
    pad = "=" * (-len(text) % 4)
    try:
        raw = base64.b64decode(text + pad, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as e:
        raise ShareCodeError("分享码不是合法的 URL-safe base64") from e
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ShareCodeError("分享码内容不是 UTF-8 文本") from e
    if decoded.lstrip().startswith(("{", "[")):
        try:
            data = json.loads(decoded)
        except ValueError as e:
            raise ShareCodeError(f"分享码里的 JSON 不合法：{e}") from e
    else:
        data = _decode_legacy(decoded)
    if not isinstance(data, dict):
        raise ShareCodeError("分享码内容应为对象")
    fields = {k: data.get(k) for k in
              ("type", "seed", "parts", "model", "look", "name", "source",
               "slot", "procedural") if k in data}
    if isinstance(fields.get("parts"), str):
        fields["parts"] = [p for p in re.split(r"[|,]", fields["parts"]) if p]
    if not fields.get("type") or not fields.get("seed"):
        raise ShareCodeError("分享码缺少 type 或 seed")
    try:
        ship = ShareRef(**fields).normalized()
    except ShipRefError as e:
        raise ShareCodeError(f"分享码内容无效：{e}") from e
    if not ship.source or ship.source == "search":
        ship.source = "share"
    return ship


# --------------------------------------------------------------------- 导入解析


def _parse_import(data: Any) -> list[dict]:
    if isinstance(data, (bytes, bytearray)):
        try:
            data = bytes(data).decode("utf-8")
        except UnicodeDecodeError as e:
            raise FavoritesError("导入内容不是 UTF-8 文本") from e
    if isinstance(data, str):
        text = data.strip()
        if not text:
            raise FavoritesError("导入内容为空")
        if text[:1] in ("{", "["):
            try:
                return _parse_import(json.loads(text))
            except ValueError as e:
                raise FavoritesError(f"导入内容不是合法 JSON：{e}") from e
        codes = [c for c in re.split(r"[\s,]+", text) if c]
        return [_normalize_item(decode_share(c)) for c in codes]
    if isinstance(data, dict):
        if "items" in data:
            seq = data.get("items")
        elif "favorites" in data:
            seq = data.get("favorites")
        elif data.get("type") and data.get("seed"):
            seq = [data]
        else:
            raise FavoritesError("导入内容缺少 items 列表")
        if not isinstance(seq, _LIST):
            raise FavoritesError("导入内容里的 items 应为数组")
        return _parse_import(seq)
    if isinstance(data, (_LIST, tuple)):
        out = []
        for item in data:
            if isinstance(item, str):
                out.append(_normalize_item(decode_share(item)))
            else:
                out.append(_normalize_item(item))
        return out
    raise FavoritesError(f"无法识别的导入内容：{type(data).__name__}")


# --------------------------------------------------------------------- 存储对象


class FavoritesStore:
    """线程安全的收藏夹；``path=None`` 时跟随 ``STARFORGE_HOME``。"""

    def __init__(self, path: str | os.PathLike | None = None):
        self._path = Path(path).expanduser() if path is not None else None

    def file(self, path: str | os.PathLike | None = None) -> Path:
        return favorites_file(path if path is not None else self._path)

    def list(self, path: str | os.PathLike | None = None) -> list[dict]:
        with _LOCK:
            return deepcopy(_load_file(self.file(path))["items"])

    def add(self, ref: Any = None, seed: str | None = None, parts: Any = None,
            name: str | None = None, path: str | os.PathLike | None = None,
            **kw: Any) -> dict:
        item = _coerce(ref, seed, parts, name, kw)
        with _LOCK:
            p = self.file(path)
            data = _load_file(p)
            key = _key(item)
            for i, old in enumerate(data["items"]):
                if _key(old) == key:
                    data["items"][i] = item
                    break
            else:
                data["items"].append(item)
            _save_file(p, data["items"])
            return deepcopy(item)

    def remove(self, ref: Any = None, seed: str | None = None, path: Any = None,
               **kw: Any) -> bool:
        item = _coerce(ref, seed, parts=None, name=None, kw=kw)
        with _LOCK:
            p = self.file(path)
            data = _load_file(p)
            key = _key(item)
            kept = [x for x in data["items"] if _key(x) != key]
            changed = len(kept) != len(data["items"])
            if changed:
                _save_file(p, kept)
            return changed

    def toggle(self, ref: Any = None, seed: str | None = None, parts: Any = None,
               name: str | None = None, path: Any = None, **kw: Any) -> bool:
        """收藏/取消收藏；返回操作后是否在收藏夹里。"""
        item = _coerce(ref, seed, parts, name, kw)
        with _LOCK:
            p = self.file(path)
            data = _load_file(p)
            key = _key(item)
            kept = [x for x in data["items"] if _key(x) != key]
            if len(kept) != len(data["items"]):
                _save_file(p, kept)
                return False
            kept.append(item)
            _save_file(p, kept)
            return True

    def is_fav(self, ref: Any = None, seed: str | None = None, path: Any = None,
               **kw: Any) -> bool:
        item = _coerce(ref, seed, parts=None, name=None, kw=kw)
        with _LOCK:
            key = _key(item)
            return any(_key(x) == key for x in _load_file(self.file(path))["items"])

    def export(self, path: Any = None) -> str:
        """导出为带版本号的 JSON 文本（可直接保存成文件发给别人）。"""
        items = self.list(path)
        return json.dumps({"format": FORMAT, "version": VERSION, "items": items},
                          ensure_ascii=False, indent=1)

    def import_(self, data: Any, path: Any = None) -> dict:
        """导入 JSON 清单、条目数组或 ``nsh1:`` 分享码；重复条目自动跳过。"""
        incoming = _parse_import(data)
        with _LOCK:
            p = self.file(path)
            merged = _load_file(p)["items"]
            seen = {_key(x) for x in merged}
            added = []
            skipped = 0
            for item in incoming:
                key = _key(item)
                if key in seen:
                    skipped += 1
                    continue
                seen.add(key)
                merged.append(item)
                added.append(item)
            if added:
                _save_file(p, merged)
            return {"added": len(added), "skipped": skipped,
                    "items": deepcopy(added)}

    def export_to(self, dest: str | os.PathLike, path: Any = None) -> Path:
        """把收藏清单写到指定文件（仍使用原子写）。"""
        target = Path(dest).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, {"format": FORMAT, "version": VERSION,
                               "items": self.list(path)})
        return target

    def encode_share(self, ref: Any) -> str:
        return encode_share(ref)

    def decode_share(self, code: str) -> ShareRef:
        return decode_share(code)

    def clear(self, path: Any = None) -> None:
        with _LOCK:
            _save_file(self.file(path), [])


_DEFAULT = FavoritesStore()
Favorites = FavoritesStore


# --------------------------------------------------------------------- 模块级 API


def list(path: Any = None) -> list[dict]:
    return _DEFAULT.list(path)


def add(ref: Any = None, seed: str | None = None, parts: Any = None,
        name: str | None = None, path: Any = None, **kw: Any) -> dict:
    return _DEFAULT.add(ref, seed, parts, name, path, **kw)


def remove(ref: Any = None, seed: str | None = None, path: Any = None,
           **kw: Any) -> bool:
    return _DEFAULT.remove(ref, seed, path, **kw)


def toggle(ref: Any = None, seed: str | None = None, parts: Any = None,
           name: str | None = None, path: Any = None, **kw: Any) -> bool:
    return _DEFAULT.toggle(ref, seed, parts, name, path, **kw)


def is_fav(ref: Any = None, seed: str | None = None, path: Any = None,
           **kw: Any) -> bool:
    return _DEFAULT.is_fav(ref, seed, path, **kw)


def export(path: Any = None) -> str:
    return _DEFAULT.export(path)


def export_to(dest: str | os.PathLike, path: Any = None) -> Path:
    return _DEFAULT.export_to(dest, path)


def import_(data: Any, path: Any = None) -> dict:
    return _DEFAULT.import_(data, path)


def clear(path: Any = None) -> None:
    return _DEFAULT.clear(path)


# 常见别名，方便界面/脚本按不同习惯调用。
list_favorites = list
add_favorite = add
remove_favorite = remove
toggle_favorite = toggle
is_favorite = is_fav
export_favorites = export
import_favorites = import_
import_data = import_
import_items = import_
load = list
all_favorites = list
share_code = encode_share
make_share_code = encode_share
parse_share_code = decode_share
decode_share_code = decode_share
encode = encode_share
decode = decode_share
FavoritesStoreError = FavoritesError

# ``import`` 是关键字，不能写 def import；挂到模块属性上兼容 getattr(favorites, "import")。
globals()["import"] = import_

__all__ = [
    "FavoritesStore", "Favorites", "FavoritesError", "ShareCodeError", "ShareRef",
    "PREFIX", "FORMAT", "VERSION", "FILENAME", "favorites_file",
    "list", "add", "remove", "toggle", "is_fav", "export", "export_to",
    "import_", "clear", "list_favorites", "add_favorite", "remove_favorite",
    "toggle_favorite", "is_favorite", "export_favorites", "import_favorites",
    "import_data", "import_items", "load", "all_favorites",
    "encode_share", "decode_share", "share_code", "make_share_code",
    "parse_share_code", "decode_share_code", "encode", "decode", "import",
]
