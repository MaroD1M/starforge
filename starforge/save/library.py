"""存档访问：包 Shipwright 的 nms_save，绝不直接碰文件字节（读写都由它负责）。

关键事实（已用真实存档验证）：
  · save.hg / save2.hg 是 LZ4 分块容器（magic 0xFEEDA1E5，16 字节头），能读；
  · accountdata.hg 是明文 JSON，但不是玩家存档（没有 ShipOwnership），要明确报"不适用"；
  · mf_*.hg 是 432 字节的高熵清单（既非 zlib 也非 lz4），本工具忽略并提示。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..core import log, paths
from ..core.errors import BadRequest, SaveFormatError, SaveNotFound
from ..data import ShipRef

log = log.get("save")

PLAYER_SAVE_RE = re.compile(r"^(save|save\d+)(\.edited|\.copy)?\.hg$", re.I)
ACCOUNT_RE = re.compile(r"^accountdata\.hg$", re.I)
MANIFEST_RE = re.compile(r"^mf_", re.I)

CHUNK_MAGIC = b"\xe5\xa1\xed\xfe"


_SHIPS_CACHE: dict[tuple, tuple[list, list]] = {}      # (路径, mtime, 大小) -> (船, 警告)


def _cache_key(p: Path) -> tuple:
    st = p.stat()
    return (str(p.resolve()), int(st.st_mtime), st.st_size)


def clear_cache() -> None:
    _SHIPS_CACHE.clear()


def _nms():
    """延迟导入 Shipwright，避免它在 import 期就要求游戏目录。"""
    paths.ensure_shipwright_importable()
    from nms_save import save as nms_save, ships as nms_ships, codec as nms_codec
    return nms_save, nms_ships, nms_codec


@dataclass
class SaveFile:
    path: Path
    kind: str                    # player | account | manifest | unknown
    ok: bool = False
    ships: int = 0
    error: str = ""
    size: int = 0

    def to_dict(self) -> dict:
        return {"name": self.path.name, "path": str(self.path), "kind": self.kind,
                "ok": self.ok, "ships": self.ships, "size": self.size, "error": self.error}


def classify(path: Path) -> str:
    name = path.name
    if MANIFEST_RE.match(name):
        return "manifest"
    if ACCOUNT_RE.match(name):
        return "account"
    if not PLAYER_SAVE_RE.match(name):
        return "unknown"
    try:
        head = path.read_bytes()[:4]
    except OSError:
        return "unknown"
    if head == CHUNK_MAGIC or head[:1] == b"{":
        return "player"
    return "unknown"


def _non_player_reason(kind: str) -> str:
    return {"account": "这是账号数据，不是玩家存档（没有飞船列表）",
            "manifest": "这是游戏的清单文件（mf_ 前缀），不含飞船数据",
            "unknown": "无法识别的文件类型"}.get(kind, "这不是玩家存档")


def probe(path: str | Path) -> SaveFile:
    p = Path(path).expanduser()
    if not p.exists():
        raise SaveNotFound(f"文件不存在：{p}")
    kind = classify(p)
    sf = SaveFile(path=p, kind=kind, size=p.stat().st_size)
    if kind != "player":
        sf.error = _non_player_reason(kind)
        return sf
    try:
        nms_save, nms_ships, _ = _nms()
        opened = nms_save.open_save(str(p))
        sf.ships = len(nms_ships.list_ships(opened.readable))
        sf.ok = True
    except Exception as e:                                  # noqa: BLE001 - 上游异常类型很多
        sf.error = f"{type(e).__name__}: {e}"
    return sf


def scan_dir(folder: str | Path | None = None) -> dict:
    from ..core import settings
    d = Path(folder).expanduser() if folder else settings.current().saves_dir_resolved()
    if not d or not Path(d).exists():
        return {"dir": str(d or ""), "found": False, "files": []}
    files = [probe(p) for p in sorted(Path(d).glob("*.hg"))]
    players = [f for f in files if f.kind == "player" and f.ok]
    return {"dir": str(d), "found": bool(players), "files": [f.to_dict() for f in files],
            "usable": [str(f.path) for f in players]}


def open_ships(path: str | Path) -> tuple[list[ShipRef], list[str]]:
    """-> (ShipRef 列表, 警告列表)。只解码一次（原来 probe 里还会再开一遍）。"""
    p = Path(path).expanduser()
    if not p.exists():
        raise SaveNotFound(f"文件不存在：{p}")
    if classify(p) != "player":
        raise SaveFormatError(_non_player_reason(classify(p)))
    key = _cache_key(p)
    if key in _SHIPS_CACHE:
        return _SHIPS_CACHE[key]
    nms_save, nms_ships, _ = _nms()
    try:
        opened = nms_save.open_save(str(p))
    except Exception as e:                                 # noqa: BLE001
        raise SaveFormatError(f"{type(e).__name__}: {e}")
    raw = nms_ships.list_ships(opened.readable)
    try:
        stats_by_slot = {}
        for sh in raw:
            try:
                st = nms_ships.ship_stats(opened.readable, sh.index)
                stats_by_slot[sh.index] = st
            except Exception:                      # noqa: BLE001
                continue
    except Exception:                              # noqa: BLE001
        stats_by_slot = {}
    out, warns = [], []
    for sh in raw:
        try:
            ref = ShipRef.from_save_ship(sh).normalized()
        except Exception as e:                             # noqa: BLE001
            warns.append(f"槽位 {getattr(sh, 'index', '?')} 无法转换：{e}")
            continue
        st = stats_by_slot.get(ref.slot)
        if st:
            from ..data.shipref import stats_summary
            ref.ship_class = str(st.get("class") or "")
            ref.stats = stats_summary(st)
        if not ref.procedural:
            warns.append(f"槽位 {ref.slot} 是固定模型（{ref.type_label}），外观不由种子决定")
        elif not ref.proc_model_matches():
            warns.append(f"槽位 {ref.slot} 声称程序化但模型与类型不符（{ref.model}）")
        out.append(ref)
    log.info("读取存档 %s：%d 艘船", p.name, len(out))
    _SHIPS_CACHE[key] = (out, warns)
    return out, warns


def default_save_path() -> Path:
    """挑一个玩家存档：优先 save.hg / save2.hg。

    这里**不做 probe()**（那会把整个存档解码一遍）——只看文件名和头 4 字节，
    真正能不能读由后面的 open_ships 决定，失败会抛明确的 SaveFormatError。
    """
    from ..core import settings
    d = settings.current().saves_dir_resolved()
    if not d:
        raise SaveNotFound("没有找到存档目录")
    for name in ("save.hg", "save2.hg"):
        cand = Path(d) / name
        if cand.exists() and classify(cand) == "player":
            return cand
    players = [p for p in Path(d).glob("*.hg") if classify(p) == "player"]
    if players:
        return sorted(players)[0]
    raise SaveNotFound(f"目录 {d} 里没有玩家存档（只有账号数据/清单文件）")


def resolve(path: str | None = None) -> Path:
    if path:
        p = Path(path).expanduser()
        if not p.exists():
            raise BadRequest(f"存档路径不存在：{p}")
        if p.is_dir():
            raise BadRequest(f"这是目录，不是存档文件：{p}（请选择 save.hg 或 save2.hg）")
        return p
    return default_save_path()
