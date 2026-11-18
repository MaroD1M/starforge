"""种子搜索：把 Shipwright 的 fast_search 包成"可校验、可取消、带 ETA"的服务。

两种涂装过滤（M2）：
  · **索引模式**（快、全量向量化）：`look = {"primary": [3, 17], "secondary": [0]}`——
    按游戏调色板索引过滤，交给上游 `textures.look_mask`，与搜索同速。
  · **RGB 模式**（准、后置）：`look = {"primary": [0.95, 0.78, 0.10], "tol": 0.18}`——
    上游只按部件筛，命中后用 `paint.look()` 解出真实配色再比距离。代价是每个候选要算一次
    配色（毫秒级），所以有 `max_candidates` 预算，超了就明确告知"没扫完"。

校验放在前面（手册 F01）：部件必须属于该船型，否则整次搜索没有意义——
实测中把 sentinel 的部件传给 fighter，上游会直接抛 ValueError。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .core import log
from .data import load_catalog, ShipRef
from .data.shipref import PROC_MODELS, ShipRefError

log = log.get("search")

# 这些船型的种子决定外观；freighter 类不在"按部件搜索"的范围
SEARCHABLE = ("fighter", "hauler", "explorer", "shuttle", "exotic", "living", "solar", "sentinel")


@dataclass
class SearchQuery:
    ship: str = "fighter"
    want: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    look: dict | None = None
    limit: int = 12
    max_seeds: int = 50_000_000
    time_limit: float = 20.0
    workers: int = 1

    def to_dict(self) -> dict:
        return {"ship": self.ship, "want": list(self.want), "avoid": list(self.avoid),
                "look": self.look, "limit": self.limit, "max_seeds": self.max_seeds,
                "time_limit": self.time_limit, "workers": self.workers}


class QueryError(ValueError):
    pass


# ---------------------------------------------------------------- 涂装过滤

LOOK_INDEX_KEYS = ("primary", "secondary", "undercoat", "mode")
LOOK_RGB_KEYS = ("primary", "secondary")


def look_kind(look: dict | None) -> str:
    """`index` / `rgb` / `none`——决定走"上游向量化"还是"命中后置过滤"。"""
    if not look:
        return "none"
    for k in LOOK_RGB_KEYS:
        v = look.get(k)
        if isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            return "rgb"
    return "index"


def look_upstream(look: dict | None) -> dict | None:
    """只把"索引模式"的键交给上游；RGB 模式上游不认识，传下去会静默筛空。"""
    if look_kind(look) != "index":
        return None
    return {k: v for k, v in (look or {}).items() if k in LOOK_INDEX_KEYS and v}


def _dist(a, b) -> float:
    """归一化 RGB 的欧氏距离（0..√3），不按权重——先简单可解释，后续再加感知色差。"""
    return sum((float(x) - float(y)) ** 2 for x, y in zip(a[:3], b[:3])) ** 0.5


def colour_matches(seed: str, ship: str, look: dict) -> tuple[bool, dict]:
    """RGB 模式的实际判定：解出这艘船的真实配色，逐个角色比距离。"""
    from . import paint
    got = paint.look(seed, ship) or {}
    tol = float(look.get("tol") or 0.18)
    detail = {}
    ok = True
    for role in LOOK_RGB_KEYS:
        want = look.get(role)
        if not want:
            continue
        have = got.get("paint" if role == "primary" else "secondary")
        if not have:
            ok = False                       # 拿不到配色（缺游戏数据）→ 不算命中
            detail[role] = None
            continue
        d = _dist(have, want)
        detail[role] = round(d, 4)
        if d > tol:
            ok = False
    return ok, detail


def validate(q: SearchQuery) -> SearchQuery:
    """船型合法 / 部件属于该船型 / 条件非空。"""
    if q.ship not in SEARCHABLE:
        raise QueryError(f"不支持搜索的船型：{q.ship!r}（可选：{', '.join(SEARCHABLE)}）")
    from . import parts as parts_mod
    try:
        tree = parts_mod.tree(q.ship)
    except Exception as e:                                 # noqa: BLE001
        raise QueryError(f"取不到 {q.ship} 的部件表：{e}（需要游戏目录或 Gagarin 的 GAMEDATA）")
    allowed = {o["part"].upper() for g in tree for o in g["options"]}
    # 同一个插槽组只能出一个部件，否则组合永远不成立：直接给出可读错误
    group_of = {o["part"].upper(): g["group"] for g in tree for o in g["options"]}
    label_of = {o["part"].upper(): (o.get("label") or o["part"]) for g in tree for o in g["options"]}
    by_group = {}
    for p in q.want:
        gid = group_of.get(p.upper())
        if gid:
            by_group.setdefault(gid, []).append(p)
    clash = {g: ps for g, ps in by_group.items() if len(ps) > 1}
    if clash:
        gid, ps = next(iter(clash.items()))
        names = " / ".join(label_of.get(p.upper(), p) for p in ps)
        raise QueryError(f"同一个插槽组只能选一个：{names}（{gid}）——请去掉一个再搜")
    if not allowed:
        raise QueryError(f"部件目录里没有船型 {q.ship!r} 的数据")
    for key in ("want", "avoid"):
        bad = [p for p in getattr(q, key) if p.strip().upper() not in allowed]
        if bad:
            raise QueryError(
                f"这些部件不属于 {q.ship}：{', '.join(bad[:6])}"
                f"（该船型共 {len(allowed)} 个可选部件；检查是否把别的船型的部件拖过来了）")
    if not q.want and not q.avoid and not q.look:
        raise QueryError("至少给一个条件：想要/不要的部件，或涂装")
    if q.look is not None:
        if not isinstance(q.look, dict):
            raise QueryError("look 必须是对象，例如 {\"primary\": [0.95,0.78,0.10], \"tol\": 0.18}")
        if look_kind(q.look) == "rgb":
            for role in LOOK_RGB_KEYS:
                v = q.look.get(role)
                if v is None:
                    continue
                if not (isinstance(v, (list, tuple)) and len(v) == 3
                        and all(0.0 <= float(x) <= 1.0 for x in v)):
                    raise QueryError(f"{role} 必须是 3 个 0..1 的分量（RGB 归一化），收到 {v!r}")
            tol_raw = q.look.get("tol", 0.18)          # 注意：tol=0 是非法值，不能被 `or` 吞掉
            tol = 0.18 if tol_raw is None else float(tol_raw)
            if not 0.0 < tol <= 1.0:
                raise QueryError(f"tol 必须在 (0,1]，收到 {tol}")
            q.look = {**q.look, "tol": tol,
                      "max_candidates": max(50, min(int(q.look.get("max_candidates") or 4000), 200_000))}
        else:
            for k, v in q.look.items():
                if k in LOOK_INDEX_KEYS and v is not None and not isinstance(v, (list, tuple, str)):
                    raise QueryError(f"索引模式下 {k} 应是索引列表，收到 {v!r}")
    q.limit = max(1, min(int(q.limit), 200))
    q.time_limit = max(1.0, min(float(q.time_limit), 300.0))
    q.max_seeds = max(1000, min(int(q.max_seeds), 2_000_000_000))
    q.want = [p.strip().upper() for p in q.want]
    q.avoid = [p.strip().upper() for p in q.avoid]
    return q


def make_filter_query(q: SearchQuery) -> SearchQuery:
    """上游的 make_filter 只吃 part id；这里做一次"提前失败"，让错误在 API 层就是 400。"""
    return validate(q)


def run(q: SearchQuery, job=None) -> list[dict]:
    """同步执行搜索；job 用于上报进度与响应取消。返回 ShipRef 字典列表。"""
    from .core import paths
    paths.ensure_shipwright_importable()
    from nms_procgen.fastsearch import fast_search

    q = validate(q)
    started = time.time()
    out: list[dict] = []
    seen: set[str] = set()

    def _progress(tested: int, seconds: float) -> None:
        if job is not None:
            job.update(tested=tested, seconds=seconds, found=len(out),
                       max_seeds=q.max_seeds, time_limit=q.time_limit)

    stop = (lambda: job.should_stop()) if job is not None else None
    stats: dict = {}
    rgb_mode = look_kind(q.look) == "rgb"
    upstream_look = look_upstream(q.look)
    budget = int((q.look or {}).get("max_candidates") or 4000) if rgb_mode else None
    candidates = 0
    colour_checked = 0
    try:
        for seed, parts in fast_search(
                q.ship, q.want, q.avoid,
                # RGB 模式要"多要候选再筛色"，所以向上游要更宽的窗口（上限仍是 limit 的结果数）
                (max(q.limit * 8, 64) if rgb_mode else q.limit),
                max_seeds=q.max_seeds,
                time_limit=q.time_limit, workers=max(1, int(q.workers)),
                stats=stats, should_stop=stop, look=upstream_look):
            candidates += 1
            if rgb_mode:
                if budget is not None and candidates > budget:
                    log.info("涂装后置过滤到预算上限（%d 个候选）仍未凑够 %d 个，先返回已有的", budget, q.limit)
                    break
                colour_checked += 1
                ok, detail = colour_matches("0x%016X" % seed, q.ship, q.look or {})
                if not ok:
                    _progress(stats.get("tested", 0), stats.get("seconds", time.time() - started))
                    continue
            ref = ShipRef(type=q.ship, seed="0x%016X" % seed, parts=[p for _g, p in parts],
                          source="search").normalized()
            if ref.seed in seen:
                continue
            seen.add(ref.seed)
            row = ref.to_dict()
            if rgb_mode:
                row["look_match"] = detail
            out.append(row)
            _progress(stats.get("tested", 0), stats.get("seconds", time.time() - started))
            if len(out) >= q.limit:
                break
            if job is not None and job.should_stop():
                break
    finally:
        _progress(stats.get("tested", 0), stats.get("seconds", time.time() - started))
        if rgb_mode:
            log.info("涂装后置过滤：候选 %d，验色 %d，命中 %d", candidates, colour_checked, len(out))

    log.info("搜索 %s want=%s → %d 个结果（%.1fs，测试 %s 个种子）",
             q.ship, q.want[:4], len(out), time.time() - started, stats.get("tested"))
    return out


def explain(q: SearchQuery) -> dict:
    """给 UI 用：条件概览 + 粗略耗时估计（按实测 13 M seeds/s 单核）。"""
    from .core import paths
    paths.ensure_shipwright_importable()
    from nms_procgen.fastsearch import measure  # 上游的概率估算
    q = validate(q)
    try:
        odds = measure(q.ship, q.want, q.avoid, q.look or None)  # 1 in N
    except Exception:                                            # noqa: BLE001
        odds = None
    est_seconds = None
    if odds and odds > 0:
        est_seconds = round(odds / 13_000_000, 1)                # 实测单核 13 M/s
    return {"query": q.to_dict(), "one_in": odds, "estimate_seconds": est_seconds,
            "note": "估计基于本机实测 13M seeds/s（单核）；多核可再快约 1.5 倍"}
