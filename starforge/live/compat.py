"""第三方模板兼容：直接复用 Super Ship Hunter 已装的两个槽。

为什么值得做：很多玩家机器上已经装了 SSH（它的数据 Mod 只覆盖 sentinel/exotic 两型）。
starforge 可以不要求用户换成我们的模板，直接写它的槽——**立刻就能验证实时通道**。

SSH 的两个槽（读自其 `REWARDTABLE.EXML`）：
  R_TEMP_ROBOT  sentinel  Seed=-8627197555170607105  Slots=120
  R_TEMP_EXOTIC exotic    Seed=-8627197555170677010  Slots=120
注意：两者 Slots 相同（都是 120），所以**只能靠 8 字节种子本身区分**。
"""
from __future__ import annotations

MASK64 = (1 << 64) - 1


def _u64(v: int) -> int:
    return v & MASK64


SSH_ENTRIES = [
    {"index": 100, "type": "sentinel", "id": "R_TEMP_ROBOT", "label": "拦截机",
     "class": "Robot", "model": "MODELS/COMMON/SPACECRAFT/SENTINELSHIP/SENTINELSHIP_PROC.SCENE.MBIN",
     "factory_seed": _u64(-8627197555170607105), "slots": 120, "source": "super-ship-hunter"},
    {"index": 101, "type": "exotic", "id": "R_TEMP_EXOTIC", "label": "异星",
     "class": "Royal", "model": "MODELS/COMMON/SPACECRAFT/S-CLASS/S-CLASS_PROC.SCENE.MBIN",
     "factory_seed": _u64(-8627197555170677010), "slots": 120, "source": "super-ship-hunter"},
]


def manifest() -> list[dict]:
    return [dict(e) for e in SSH_ENTRIES]
