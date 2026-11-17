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
    def __init__(self):
        self.ships: dict[str, dict[str, bytes]] = {}   # 船型 -> 部件 -> png
        self.flat: dict[str, bytes] = {}               # 部件 -> png（跨船型唯一时才有意义）
        self.ambiguous: set[str] = set()
        self.parts: dict[str, bytes] = {}              # 建筑部件
        self.versions: dict[str, int] = {}
        self.counts: dict[str, int] = {}

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
            try:
                png = gshi.png_bytes(w, h, gshi.decode(ver, w, h, data))
            except ValueError:
                continue
            self.ships.setdefault(ship, {})[key] = png
            if key in self.flat:
                self.ambiguous.add(key)
            else:
                self.flat[key] = png
            n += 1
        self.counts["ships"] = n

    def _load_parts(self, path: Path) -> None:
        ver, ents = gshi.parse_container(path)
        self.versions["parts"] = ver
        n = 0
        for name, w, h, data in ents:
            key = name.split("/")[-1].upper()
            try:
                self.parts[key] = gshi.png_bytes(w, h, gshi.decode(ver, w, h, data))
            except ValueError:
                continue
            n += 1
        self.counts["parts"] = n

    # --- 查询 ---
    def png(self, part: str, ship: str | None = None) -> bytes | None:
        key = part.upper()
        if ship:
            got = self.ships.get(ship, {}).get(key)
            if got:
                return got
        if key in self.flat:
            return self.flat[key]
        return self.parts.get(key) or self.parts.get(key.replace("_", ""))

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
