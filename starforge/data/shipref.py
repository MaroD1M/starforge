"""ShipRef：全项目唯一的数据模型（决策单 §2.3）。

任何管线（搜索/预览/写存档/写模板槽）只吃/吐这个结构。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

# type -> 对应的 _PROC 模型文件名（只列可换 seed 的程序化模型）
PROC_MODELS = {
    "fighter": "FIGHTER_PROC.SCENE.MBIN",
    "hauler": "DROPSHIP_PROC.SCENE.MBIN",
    "explorer": "SCIENTIFIC_PROC.SCENE.MBIN",
    "shuttle": "SHUTTLE_PROC.SCENE.MBIN",
    "exotic": "S-CLASS_PROC.SCENE.MBIN",
    "living": "BIOSHIP_PROC.SCENE.MBIN",
    "solar": "SAILSHIP_PROC.SCENE.MBIN",
    "sentinel": "SENTINELSHIP_PROC.SCENE.MBIN",
    "freighter": "FREIGHTER_PROC.SCENE.MBIN",
    "capital_freighter": "CAPITALFREIGHTER_PROC.SCENE.MBIN",
}
# 存档里的类别名（Shipwright ships._category_guess）→ 统一 type
SAVE_CATEGORY = {
    "fighter": "fighter", "hauler": "hauler", "explorer": "explorer", "shuttle": "shuttle",
    "exotic": "exotic", "living": "living", "solar": "solar", "sentinel": "sentinel",
    "freighter": "freighter", "capital freighter": "capital_freighter",
    "capital_freighter": "capital_freighter",
}

_SEED_RE = re.compile(r"^0x[0-9A-Fa-f]{1,16}$")


class ShipRefError(ValueError):
    pass


@dataclass
class ShipRef:
    type: str
    seed: str
    parts: list[str] | None = None
    model: str | None = None
    look: dict | None = None
    name: str = ""
    source: str = "search"          # search|save|memory|design
    slot: int | None = None         # 来自存档时的槽位
    procedural: bool = True

    # --- 构造 ---
    @classmethod
    def from_save_ship(cls, sh) -> "ShipRef":
        """把 Shipwright 的 ships.Ship 转成 ShipRef。"""
        cat = (sh.category_guess or "").lower()
        typ = SAVE_CATEGORY.get(cat, cat or "unknown")
        return cls(type=typ, seed=sh.seed, model=sh.filename or None,
                   name=(sh.name or "").strip(), source="save", slot=sh.index,
                   procedural=bool(sh.is_procedural))

    # --- 校验 ---
    def normalized(self) -> "ShipRef":
        if self.type not in PROC_MODELS and self.type != "unknown":
            raise ShipRefError(f"未知船型：{self.type!r}")
        if not _SEED_RE.match(self.seed or ""):
            raise ShipRefError(f"种子格式不对：{self.seed!r}（应形如 0x8BA812880CFAAA1C）")
        self.seed = "0x" + self.seed[2:].upper().rjust(16, "0")
        if self.parts:
            self.parts = [p.strip().upper() for p in self.parts if p and p.strip()]
        return self

    def proc_model_matches(self) -> bool:
        """种子是否真的能改变外观（模型必须是本类型的 _PROC）。"""
        want = PROC_MODELS.get(self.type)
        if not want or not self.model:
            return self.procedural
        return self.model.upper().endswith(want)

    def to_dict(self) -> dict:
        return asdict(self)


def coerce(obj) -> ShipRef:
    """dict / ShipRef / 存档 Ship 都能转。"""
    if isinstance(obj, ShipRef):
        return obj.normalized()
    if isinstance(obj, dict):
        return ShipRef(**{k: obj.get(k) for k in
                          ("type", "seed", "parts", "model", "look", "name", "source", "slot", "procedural")
                          if k in obj}).normalized()
    if hasattr(obj, "seed") and hasattr(obj, "category_guess"):
        return ShipRef.from_save_ship(obj).normalized()
    raise ShipRefError(f"无法识别的 ShipRef 来源：{type(obj).__name__}")
