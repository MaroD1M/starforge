"""AOB（字节模式）扫描引擎：多候选 + 结构评分 + 命中缓存。

来自 SSH 的教训（上一轮审计 P0-2/P0-3）：
  · 单条签名、只取首个命中 → 一次小更新全废，且可能写错对象；
  · 所以这里：收集**全部**命中，用调用方给的"结构自洽性"打分挑最可信的那个。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_CANDIDATES = 64


@dataclass
class Pattern:
    """形如 "01 ?? 00 34 00 00 00" 的字节模式（支持 ?? 通配）。"""
    text: str
    name: str = ""
    offset: int = 0                  # 命中后加在地址上的偏移（可为负）

    def __post_init__(self) -> None:
        toks = self.text.split()
        if not toks:
            raise ValueError("空模式")
        self.tokens = toks
        self.literals = [(i, int(t, 16)) for i, t in enumerate(toks) if t != "??"]
        if not self.literals:
            raise ValueError("模式里至少要有一个字节")
        self.anchor, self.anchor_off = self._longest_run()

    def _longest_run(self) -> tuple[bytes, int]:
        best_start, best_len, start = 0, 0, None
        toks = self.tokens + ["??"]
        for i, t in enumerate(toks):
            if t != "??":
                if start is None:
                    start = i
            elif start is not None:
                if i - start > best_len:
                    best_start, best_len = start, i - start
                start = None
        run = bytes(int(self.tokens[i], 16) for i in range(best_start, best_start + best_len))
        return run, best_start

    @property
    def length(self) -> int:
        return len(self.tokens)


_TERM = object()


def find_all(buf: bytes, pat: Pattern, limit: int = MAX_CANDIDATES) -> list[int]:
    """在不大于 limit 个候选处返回命中位置（字节偏移）。"""
    out: list[int] = []
    if len(buf) < pat.length:
        return out
    # 用最长字面量做锚点快速跳（C 速度），再校验通配位
    pos = 0
    anchor = pat.anchor
    while True:
        i = buf.find(anchor, pos)
        if i < 0:
            break
        start = i - pat.anchor_off
        pos = i + 1
        if start < 0 or start + pat.length > len(buf):
            continue
        if all(buf[start + k] == v for k, v in pat.literals):
            out.append(start)
            if len(out) >= limit:
                break
    return out


def regex_for(pat: Pattern) -> re.Pattern:
    """字面量太碎时的兜底：转成正则（连续 ?? 合并成 .{n}）。"""
    parts = []
    i = 0
    toks = pat.tokens
    while i < len(toks):
        if toks[i] == "??":
            j = i
            while j < len(toks) and toks[j] == "??":
                j += 1
            n = j - i
            parts.append(b"." if n == 1 else b".{%d}" % n)
            i = j
        else:
            parts.append(re.escape(bytes([int(toks[i], 16)])))
            i += 1
    return re.compile(b"".join(parts), re.DOTALL)


def pick_best(candidates: list[int], score) -> tuple[int | None, list[tuple[int, float]]]:
    """score(addr) -> 0..1。返回 (最佳地址, 全部打分)，低于 0.5 视为不可信。"""
    scored = [(a, float(score(a))) for a in candidates]
    scored.sort(key=lambda x: (-x[1], x[0]))
    best = scored[0][0] if scored and scored[0][1] >= 0.5 else None
    return best, scored


@dataclass
class ScanPlan:
    """一次扫描要做的事：在哪块内存里、用哪些模式、命中后怎么验。"""
    patterns: list[Pattern] = field(default_factory=list)
    min_score: float = 0.5

    def add(self, text: str, name: str = "", offset: int = 0) -> Pattern:
        p = Pattern(text=text, name=name, offset=offset)
        self.patterns.append(p)
        return p
