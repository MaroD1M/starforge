"""catalog.txt 解析（Gagarin 的飞船部件目录树）。

语法（实测 3628 行：8 船型 / 543 组 / 1430 选项 / C≡E=225 / 66 调色板）：
  SHIP <type> <scene.mbin>   声明船型与根场景
  SCENE <path>               当前节点场景
  L <group>                  开插槽组（无显式闭合，只有 C/E 成对）
  O <part> <n>               组内部件选项（n ∈ {20,0,1}）
  C ... E                    条件块
  R -|<path>                 组内场景替换
  P <material> <k> <256 floats>   材质调色板（k ∈ 0..5，4 个 Space* 为 0）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Catalog:
    ships: dict = field(default_factory=dict)      # type -> {"scene": str, "groups": {grp: [(part, weight)]}}
    index: dict = field(default_factory=dict)      # PART -> [(type, group, weight)]
    palettes: dict = field(default_factory=dict)   # material -> (k, [(r,g,b,a)...])
    stats: dict = field(default_factory=dict)
    opens_at_eof: int = 0

    def locate(self, part: str) -> list[tuple[str, str, int]]:
        return self.index.get(part.upper(), [])

    def parts_of(self, ship: str) -> list[str]:
        s = self.ships.get(ship)
        if not s:
            return []
        return [p for opts in s["groups"].values() for p, _ in opts]

    def groups_of(self, ship: str) -> dict:
        return (self.ships.get(ship) or {}).get("groups", {})


def parse(path: str | Path) -> Catalog:
    cat = Catalog()
    cur = None
    stack: list[tuple[str, str | None]] = []
    stats = {"ship": 0, "scene": 0, "L": 0, "O": 0, "C": 0, "E": 0, "R": 0, "palette": 0}
    for raw in Path(path).read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tok = line.split()
        k = tok[0]
        if k == "SHIP":
            cur = {"scene": None, "groups": {}}
            cat.ships[tok[1]] = cur
            stats["ship"] += 1
            stack.clear()
        elif k == "SCENE":
            stats["scene"] += 1
            if cur is not None and len(tok) > 1:
                cur["scene"] = tok[1]
        elif k == "L":
            stats["L"] += 1
            stack.append(("L", tok[1]))
            if cur is not None:
                cur["groups"].setdefault(tok[1], [])
        elif k == "C":
            stats["C"] += 1
            stack.append(("C", None))
        elif k == "E":
            stats["E"] += 1
            if stack:
                stack.pop()
        elif k == "O":
            stats["O"] += 1
            if cur is None:
                continue
            grp = next((n for t, n in reversed(stack) if t == "L"), None)
            if grp is None:
                continue
            part = tok[1]
            weight = int(tok[2]) if len(tok) > 2 else 0
            cur["groups"].setdefault(grp, []).append((part, weight))
            cat.index.setdefault(part.upper(), []).append(
                (next(t for t, v in cat.ships.items() if v is cur), grp, weight))
        elif k == "R":
            stats["R"] += 1
        elif k == "P":
            stats["palette"] += 1
            name, tag = tok[1], int(tok[2])
            floats = [float(x) for x in tok[3:]]
            cols = [tuple(floats[i:i + 4]) for i in range(0, len(floats), 4)]
            cat.palettes[name] = (tag, cols)
    cat.stats = stats
    cat.opens_at_eof = len(stack)
    return cat


def load(gamedata: str | Path) -> Catalog:
    """gamedata 指向 GAMEDATA 根（其下有 Gagarin/ships/catalog.txt）。"""
    p = Path(gamedata)
    f = p / "Gagarin" / "ships" / "catalog.txt"
    if not f.exists():
        f = p / "ships" / "catalog.txt"
    if not f.exists():
        raise FileNotFoundError(f"找不到 catalog.txt（{p}）")
    return parse(f)
