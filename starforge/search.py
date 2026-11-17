"""种子搜索：把 Shipwright 的 fast_search 包成"可校验、可取消、带 ETA"的服务。

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


def validate(q: SearchQuery) -> SearchQuery:
    """船型合法 / 部件属于该船型 / 条件非空。"""
    if q.ship not in SEARCHABLE:
        raise QueryError(f"不支持搜索的船型：{q.ship!r}（可选：{', '.join(SEARCHABLE)}）")
    from . import parts as parts_mod
    try:
        allowed = {p.upper() for p in parts_mod.parts_of(q.ship)}
    except Exception as e:                                 # noqa: BLE001
        raise QueryError(f"取不到 {q.ship} 的部件表：{e}（需要游戏目录或 Gagarin 的 GAMEDATA）")
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
    try:
        for seed, parts in fast_search(
                q.ship, q.want, q.avoid, q.limit, max_seeds=q.max_seeds,
                time_limit=q.time_limit, workers=max(1, int(q.workers)),
                stats=stats, should_stop=stop, look=q.look or None):
            ref = ShipRef(type=q.ship, seed="0x%016X" % seed, parts=[p for _g, p in parts],
                          source="search").normalized()
            if ref.seed in seen:
                continue
            seen.add(ref.seed)
            out.append(ref.to_dict())
            _progress(stats.get("tested", 0), stats.get("seconds", time.time() - started))
            if len(out) >= q.limit:
                break
            if job is not None and job.should_stop():
                break
    finally:
        _progress(stats.get("tested", 0), stats.get("seconds", time.time() - started))

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
