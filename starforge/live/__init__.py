"""游戏内实时通道（可选，默认关闭）。

分三块：
  scan.py  AOB 扫描引擎（多候选 + 结构评分）
  exml.py  游戏侧模板 Mod 生成器（8 种 _PROC 各一槽）
  mem.py   进程内存读写（平台层，Windows 为主）
  writer.py 定位 → 写 seed → 回读校验
"""
from . import exml, scan

__all__ = ["scan", "exml"]
