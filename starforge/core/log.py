"""结构化日志：控制台 + 滚动文件，统一字段（级别/模块/消息/耗时）。"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from . import paths

_FMT = "%(asctime)s %(levelname)-5s %(name)-18s %(message)s"
_ready = False


def setup(level: int = logging.INFO) -> logging.Logger:
    global _ready
    root = logging.getLogger("starforge")
    if _ready:
        return root
    root.setLevel(level)
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter(_FMT, "%H:%M:%S"))
    root.addHandler(h)
    try:
        fh = RotatingFileHandler(paths.log_file(), maxBytes=2 << 20, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter(_FMT))
        root.addHandler(fh)
    except OSError:
        pass  # 只读环境/无 home 时退化为仅控制台
    _ready = True
    return root


def get(name: str) -> logging.Logger:
    setup()
    return logging.getLogger(f"starforge.{name}")
