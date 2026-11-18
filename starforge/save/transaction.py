"""通用存档写事务：读 → 备份 → 修改 → 原子写 → 读回校验 → 失败回滚。

所有会改写 ``.hg`` 的服务都走这里，复用 ``save.writer`` 里已经验证过的编码、
备份和原子写实现，避免再写一套。``mutate`` 拿到第一次打开的 ``OpenSave.readable``，
``verify`` 拿到写后重新打开的 ``readable``；两者返回值分别作为结果的 before/after。
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Callable

from ..core import log as log_mod
from ..core import settings
from ..core.errors import BadRequest, WriteRefused
from . import writer

log = log_mod.get("save.transaction")


def _nms():
    from ..core import paths

    paths.ensure_shipwright_importable()
    from nms_save import save as nms_save

    return nms_save


def _clear_cache() -> None:
    """存档内容变了，船列表缓存必须失效；缓存清理失败不影响写入结果。"""
    try:
        from . import library

        library.clear_cache()
    except Exception:                                       # noqa: BLE001
        pass


def transact_save(path: str, mutate: Callable[[dict], Any],
                  verify: Callable[[dict], Any], copy: bool = False) -> dict:
    """在一个存档上安全地执行一次修改。

    · ``mutate(readable)``：原地修改可读 JSON；返回值作为 ``before``；
    · ``verify(readable)``：拿到写后重新打开的树做核对；返回值作为 ``after``，
      显式返回 ``False`` 或抛异常都视为校验失败；
    · ``copy=True``：先复制成 ``<存档>.edited.hg``，只改副本，原档一字节不动。

    任何失败都会把目标文件的原始字节原子写回，备份文件保留供手工恢复。
    """
    path = str(path)
    settings.require_write()
    if writer.game_running():
        raise WriteRefused("游戏正在运行，请先退出游戏再写入（否则会被游戏覆盖）")
    if not os.path.exists(path):
        raise BadRequest(f"存档不存在：{path}")

    original_path = path
    target_path = path
    if copy:
        target_path = writer._copy_path(path)
        if os.path.abspath(target_path) != os.path.abspath(original_path):
            shutil.copy2(original_path, target_path)
        log.info("写事务使用副本：%s（原档 %s 不动）", target_path, original_path)

    original = open(target_path, "rb").read()
    backup = writer._backup(target_path)
    _clear_cache()
    nms_save = _nms()

    try:
        opened = nms_save.open_save(target_path)
        before = mutate(opened.readable)
        data = writer._encode(opened)
        writer._atomic_write(target_path, data)

        # 不信任自己的写入：重新解码，再交给调用方核对。
        reread = nms_save.open_save(target_path)
        after = verify(reread.readable)
        if after is False:
            raise WriteRefused("写后校验失败：写回的内容与预期不符")

        _clear_cache()
        log.info("写事务完成：%s（备份 %s）", os.path.basename(target_path), backup)
        return {
            "ok": True,
            "path": target_path,
            "original": original_path,
            "copy": bool(copy),
            "backup": backup,
            "before": before,
            "after": after,
            "bytes": len(data),
            "verified": True,
        }
    except Exception as e:                                  # noqa: BLE001
        # 回滚到写事务开始前的原始字节；备份不删，留给用户兜底。
        try:
            writer._atomic_write(target_path, original)
            _clear_cache()
            log.error("写入失败已回滚：%s（备份 %s）", e, backup)
        except Exception as e2:                             # noqa: BLE001
            log.error("回滚也失败！请手工把 %s 复制回 %s（%s）", backup, target_path, e2)
        raise WriteRefused(f"写入未完成，已回滚：{e}。备份保留在 {backup}") from e


__all__ = ["transact_save"]
