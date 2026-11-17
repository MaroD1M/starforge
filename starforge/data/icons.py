"""图标集：把 ships/icons.bin（96×96，v1）与 parts/icons.bin（64×64，v2）合成一张查询表。

命名约定（实测）：ships 里名字是 `<船型>/<部件>`，parts 里是 `p/<部件ID>`。
按 `<船型>` 分桶，避免不同船型的同名部件互相覆盖。
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import gshi

_LOCK = threading.RLock()


class IconSet:
    """图标集：**懒解码**。

    容器里 1900+ 张图，全都解一遍要 ~4 秒；但一次页面通常只看十几张。
    所以这里只建"名字 → 数据切片"的索引，真正用到才解码并缓存 PNG。
    """

    def __init__(self):
        self.ships: dict[str, dict[str, tuple]] = {}    # 船型 -> 部件 -> (ver,w,h,data)
        self.flat: dict[str, tuple] = {}
        self.ambiguous: set[str] = set()
        self.parts: dict[str, tuple] = {}               # 建筑部件
        self.versions: dict[str, int] = {}
        self.counts: dict[str, int] = {}
        self._png: dict[tuple, bytes] = {}

    def _decode(self, slot: tuple) -> bytes | None:
        ver, w, h, data = slot
        key = (ver, w, h, id(data))
        hit = self._png.get(key)
        if hit is not None:
            return hit
        try:
            png = gshi.png_bytes(w, h, gshi.decode(ver, w, h, data))
        except ValueError:
            return None
        self._png[key] = png
        return png

    # --- 加载 ---
    @classmethod
    def load(cls, gamedata: str | Path) -> "IconSet":
        gd = Path(gamedata)
        base = gd / "Gagarin" if (gd / "Gagarin").exists() else gd
        self = cls()
        ships_bin = base / "ships" / "icons.bin"
        parts_bin = base / "parts" / "icons.bin"
        if ships_bin.exists():
            self._load_ships(ships_bin)
        if parts_bin.exists():
            self._load_parts(parts_bin)
        return self

    def _load_ships(self, path: Path) -> None:
        ver, ents = gshi.parse_container(path)
        self.versions["ships"] = ver
        n = 0
        for name, w, h, data in ents:
            ship, _, part = name.partition("/")
            key = (part or name).upper()
            slot = (ver, w, h, data)
            self.ships.setdefault(ship, {})[key] = slot
            if key in self.flat:
                self.ambiguous.add(key)
            else:
                self.flat[key] = slot
            n += 1
        self.counts["ships"] = n

    def _load_parts(self, path: Path) -> None:
        ver, ents = gshi.parse_container(path)
        self.versions["parts"] = ver
        n = 0
        for name, w, h, data in ents:
            key = name.split("/")[-1].upper()
            self.parts[key] = (ver, w, h, data)
            n += 1
        self.counts["parts"] = n

    # --- 查询 ---
    def png(self, part: str, ship: str | None = None) -> bytes | None:
        key = part.upper()
        slot = None
        if ship:
            slot = self.ships.get(ship, {}).get(key)
        if slot is None:
            slot = self.flat.get(key) or self.parts.get(key) or self.parts.get(key.replace("_", ""))
        return self._decode(slot) if slot else None

    def where(self, part: str) -> list[str]:
        key = part.upper()
        return sorted(s for s, d in self.ships.items() if key in d)


_CACHE: dict[str, IconSet] = {}


def load(gamedata: str | Path) -> IconSet:
    k = str(gamedata)
    with _LOCK:
        if k not in _CACHE:
            _CACHE[k] = IconSet.load(gamedata)
        return _CACHE[k]
