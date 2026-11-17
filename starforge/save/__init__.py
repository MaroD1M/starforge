"""存档层：只通过 Shipwright 的 nms_save 读写，不自行解析字节。"""
from . import library

__all__ = ["library"]
