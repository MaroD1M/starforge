"""游戏内实时通道（可选，默认关闭）。

分四块：
  scan.py    AOB 扫描引擎（多候选 + 结构评分）
  exml.py    游戏侧模板 Mod 生成器（8 种 _PROC 各一槽）
  mem.py     进程内存读写（Windows，含测试用 FakeProcess）
  writer.py  定位模板槽 → 写 seed → 回读校验
"""
from . import exml, mem, scan, writer

__all__ = ["scan", "exml", "mem", "writer"]
