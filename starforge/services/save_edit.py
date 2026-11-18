"""存档安全编辑服务：货币、飞船改名、涂装。

UI 直接 ``from starforge.services import save_edit`` 调用。所有写操作都经过
``save.transaction.transact_save``：写开关、游戏进程检查、备份、原子写、读回校验、
失败回滚；并且只改目标字段，写后核对其它船/其它字段没有被牵动。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..core import log as log_mod
from ..core import paths, settings
from ..core.errors import BadRequest, SaveFormatError, WriteRefused
from ..save import library, transaction

log = log_mod.get("services.save_edit")

MAX_CURRENCY = 2 ** 31 - 1
CURRENCIES = ("units", "nanites", "quicksilver")
CURRENCY_LABELS = {"units": "单位", "nanites": "纳米簇", "quicksilver": "水银"}
PAINT_ALTS = ("Primary", "Alternative1", "Alternative2", "Alternative3", "Alternative4")


# ---------------------------------------------------------------- 内部工具


def _nms():
    paths.ensure_shipwright_importable()
    from nms_save import player, save as nms_save, ships as nms_ships

    return player, nms_save, nms_ships


def _player_path(path: str | None) -> Path:
    p = library.resolve(path)
    kind = library.classify(p)
    if kind != "player":
        reason = {
            "account": "这是账号数据，不是玩家存档（没有货币/飞船字段）",
            "manifest": "这是游戏的清单文件（mf_ 前缀），不含玩家数据",
        }.get(kind, "无法识别的文件类型，请选择 save.hg 或 save2.hg")
        raise SaveFormatError(reason)
    return p


def _open(path: str | None):
    p = _player_path(path)
    _, nms_save, _ = _nms()
    try:
        return p, nms_save.open_save(str(p))
    except Exception as e:                                 # noqa: BLE001
        raise SaveFormatError(f"无法读取存档：{type(e).__name__}: {e}") from e


def _slot(value: Any) -> int:
    try:
        slot = int(value)
    except (TypeError, ValueError) as e:
        raise BadRequest(f"槽位必须是整数，收到 {value!r}") from e
    if slot < 0:
        raise BadRequest(f"槽位不能为负数，收到 {slot}")
    return slot


def _target(nms_ships, readable: dict, slot: int):
    ships = nms_ships.list_ships(readable)
    target = next((s for s in ships if s.index == slot), None)
    if target is None:
        raise BadRequest(f"存档里没有第 {slot} 艘船（槽位为空或不存在）")
    return ships, target


def _safe_paint(nms_ships, readable: dict, slot: int):
    try:
        return nms_ships.get_ship_paint(readable, slot)
    except Exception:                                      # noqa: BLE001
        return None


def _rgb(value: Any, label: str) -> tuple[float, float, float]:
    if isinstance(value, dict):
        value = value.get("rgb") or value.get("colour") or value.get("color")
    try:
        if len(value) < 3:
            raise ValueError("too short")
        rgb = tuple(float(value[i]) for i in range(3))
    except (TypeError, ValueError, KeyError, IndexError) as e:
        raise BadRequest(f"{label} 必须是 [r, g, b] 三个数字") from e
    if any(not math.isfinite(v) for v in rgb):
        raise BadRequest(f"{label} 的每个分量必须是有效数字")
    if any(v < 0.0 or v > 1.0 for v in rgb):
        raise BadRequest(f"{label} 的每个分量必须在 0 到 1 之间")
    return rgb


def _same_rgb(a: Any, b: Any, tol: float = 1e-5) -> bool:
    try:
        return len(a) >= 3 and len(b) >= 3 and all(
            abs(float(x) - float(y)) <= tol for x, y in zip(a[:3], b[:3]))
    except (TypeError, ValueError):
        return False


def _paint_matches(written: dict, after: dict | None) -> bool:
    if not after or not written:
        return False
    if after.get("palette") != written.get("palette"):
        return False
    if after.get("primary_index") != written.get("primary_index"):
        return False
    if after.get("accent_index") != written.get("accent_index"):
        return False
    want_channels = written.get("channels") or {}
    got_channels = after.get("channels") or {}
    for alt, want in want_channels.items():
        got = got_channels.get(alt) or {}
        if not _same_rgb(got.get("rgb"), want.get("rgb")):
            return False
        if int(got.get("index", -999)) != int(want.get("index", -999)):
            return False
    return True


def _require_confirm(confirm: bool) -> None:
    if not confirm:
        raise BadRequest("缺少 confirm=true（写操作必须二次确认）")


def _currency_values(units: Any, nanites: Any, quicksilver: Any) -> dict:
    values = {}
    for name, value in (("units", units), ("nanites", nanites),
                        ("quicksilver", quicksilver)):
        if value is None:
            continue
        label = CURRENCY_LABELS[name]
        try:
            number = int(value)
        except (TypeError, ValueError) as e:
            raise BadRequest(
                f"{label}必须是 0 到 {MAX_CURRENCY:,} 之间的整数，收到 {value!r}") from e
        if not 0 <= number <= MAX_CURRENCY:
            raise BadRequest(
                f"{label}必须在 0 到 {MAX_CURRENCY:,} 之间，收到 {number:,}")
        values[name] = number
    if not values:
        raise BadRequest("没有要修改的货币：至少提供 units、nanites、quicksilver 之一")
    return values


# ---------------------------------------------------------------- 货币


def currencies(path: str | None = None) -> dict:
    """读存档里的 units / nanites / quicksilver。"""
    p, opened = _open(path)
    player, _, _ = _nms()
    try:
        return player.get_currencies(opened.readable)
    except KeyError as e:
        raise SaveFormatError(f"存档里没有货币字段（可能版本不兼容）：{e}") from e
    except Exception as e:                                 # noqa: BLE001
        raise SaveFormatError(f"读取货币失败：{type(e).__name__}: {e}") from e


def apply_currencies(path: str, units=None, nanites=None, quicksilver=None,
                     confirm: bool = False, copy: bool = False) -> dict:
    """修改一项或多项货币；返回 ``before/after/backup/verified/copy``。"""
    settings.require_write()
    _require_confirm(confirm)
    values = _currency_values(units, nanites, quicksilver)
    p = _player_path(path)
    player, _, _ = _nms()
    snapshot: dict[str, Any] = {}

    def mutate(readable: dict):
        snapshot.update(player.get_currencies(readable))
        try:
            player.set_currencies(readable, **values)
        except ValueError as e:
            raise BadRequest(f"货币值不合法：{e}") from e
        return dict(snapshot)

    def verify(readable: dict):
        after = player.get_currencies(readable)
        for name, wanted in values.items():
            if after.get(name) != wanted:
                raise WriteRefused(
                    f"写后校验失败：{CURRENCY_LABELS[name]}读到 {after.get(name)}，"
                    f"预期 {wanted}")
        for name in CURRENCIES:
            if name not in values and after.get(name) != snapshot.get(name):
                raise WriteRefused(
                    f"写后校验失败：未修改的{CURRENCY_LABELS[name]}被改动了")
        return after

    return transaction.transact_save(str(p), mutate, verify, copy=copy)


# ---------------------------------------------------------------- 飞船元数据


def ship_meta(path: str, slot: int) -> dict:
    """读某艘船的名字与涂装；没有涂装时 ``paint`` 为 None。"""
    slot = _slot(slot)
    _, opened = _open(path)
    _, _, nms_ships = _nms()
    _, target = _target(nms_ships, opened.readable, slot)
    return {"name": target.name or "",
            "paint": _safe_paint(nms_ships, opened.readable, slot)}


def apply_ship_name(path: str, slot: int, name: str,
                    confirm: bool = False, copy: bool = False) -> dict:
    """只改目标船的名字，写后核对其它船与目标船其它字段都没动。"""
    settings.require_write()
    _require_confirm(confirm)
    slot = _slot(slot)
    if not isinstance(name, str):
        raise BadRequest("船名必须是文本")
    p = _player_path(path)
    _, _, nms_ships = _nms()
    snapshot: dict[str, Any] = {}

    def mutate(readable: dict):
        ships, target = _target(nms_ships, readable, slot)
        snapshot["target"] = (target.name or "", target.filename, target.seed)
        snapshot["others"] = {
            s.index: (s.name or "", s.filename, s.seed) for s in ships if s.index != slot
        }
        try:
            nms_ships.set_ship_name(readable, slot, name)
        except Exception as e:                             # noqa: BLE001
            raise BadRequest(f"无法修改第 {slot} 艘船的名字：{type(e).__name__}: {e}") from e
        return snapshot["target"][0]

    def verify(readable: dict):
        ships, target = _target(nms_ships, readable, slot)
        after = target.name or ""
        if after != name:
            raise WriteRefused(f"写后校验失败：船名读到 {after!r}，预期 {name!r}")
        if (target.name or "", target.filename, target.seed) != (
                name, snapshot["target"][1], snapshot["target"][2]):
            raise WriteRefused("写后校验失败：目标船的其它字段被改动了")
        others = {s.index: (s.name or "", s.filename, s.seed)
                  for s in ships if s.index != slot}
        if others != snapshot["others"]:
            raise WriteRefused("写后校验失败：其它船的名字被改动了（写错槽位）")
        return after

    return transaction.transact_save(str(p), mutate, verify, copy=copy)


# ---------------------------------------------------------------- 涂装


def apply_ship_paint(path: str, slot: int, primary, accent=None,
                     palette_id: str = "FREIGHTER",
                     primary_index: int | None = None,
                     accent_index: int | None = None,
                     channels: dict | None = None,
                     confirm: bool = False, copy: bool = False) -> dict:
    """给目标船涂装（普通船；槽位 0–11）。

    只改该槽位的 ``CharacterCustomisationData``；其它船的名字/种子/涂装都要核对未变。
    返回的 ``after`` 是游戏调色板吸附后的实际颜色。
    """
    settings.require_write()
    _require_confirm(confirm)
    slot = _slot(slot)
    if slot >= 12:
        raise BadRequest(f"槽位 {slot} 没有涂装项（只支持 0–11）")
    primary = _rgb(primary, "主色")
    accent = primary if accent is None else _rgb(accent, "副色")
    if not isinstance(palette_id, str) or not palette_id:
        raise BadRequest("调色板名称必须是非空文本")
    p = _player_path(path)
    _, _, nms_ships = _nms()
    try:
        palettes = nms_ships._palettes()                   # 上游自带的调色板表
    except Exception as e:                                 # noqa: BLE001
        raise BadRequest(f"缺少涂装调色板数据，无法写入：{type(e).__name__}") from e
    if palette_id not in palettes:
        raise BadRequest(f"未知调色板 {palette_id!r}；可用：{', '.join(sorted(palettes)[:8])}…")

    snapshot: dict[str, Any] = {}

    def mutate(readable: dict):
        ships, target = _target(nms_ships, readable, slot)
        snapshot["target"] = (target.name or "", target.filename, target.seed)
        snapshot["before"] = _safe_paint(nms_ships, readable, slot)
        snapshot["others"] = {
            s.index: (s.name or "", s.filename, s.seed,
                      _safe_paint(nms_ships, readable, s.index))
            for s in ships if s.index != slot
        }
        try:
            written = nms_ships.set_ship_paint(
                readable, slot, primary=primary, accent=accent, palette_id=palette_id,
                primary_index=primary_index, accent_index=accent_index, channels=channels)
        except Exception as e:                             # noqa: BLE001
            raise BadRequest(
                f"无法修改第 {slot} 艘船的涂装：{type(e).__name__}: {e}") from e
        snapshot["written"] = written
        return snapshot["before"]

    def verify(readable: dict):
        ships, target = _target(nms_ships, readable, slot)
        if (target.name or "", target.filename, target.seed) != snapshot["target"]:
            raise WriteRefused("写后校验失败：目标船的其它字段被改动了")
        others = {
            s.index: (s.name or "", s.filename, s.seed,
                      _safe_paint(nms_ships, readable, s.index))
            for s in ships if s.index != slot
        }
        if others != snapshot["others"]:
            raise WriteRefused("写后校验失败：其它船的涂装被改动了（写错槽位）")
        after = _safe_paint(nms_ships, readable, slot)
        if not _paint_matches(snapshot.get("written") or {}, after):
            raise WriteRefused("写后校验失败：涂装与预期不符")
        return after

    return transaction.transact_save(str(p), mutate, verify, copy=copy)


__all__ = ["currencies", "apply_currencies", "ship_meta", "apply_ship_name",
           "apply_ship_paint"]
