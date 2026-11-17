"""ShipRef：全项目唯一的数据模型（决策单 §2.3）。

任何管线（搜索/预览/写存档/写模板槽）只吃/吐这个结构。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

# 模型文件名片段 → 船型（不要求带 _PROC：玩家存档里也可能是固定模型）
MODEL_TOKENS = (
    ("SENTINELSHIP", "sentinel"), ("FIGHTER", "fighter"), ("DROPSHIP", "hauler"),
    ("SCIENTIFIC", "explorer"), ("SHUTTLE", "shuttle"), ("S-CLASS", "exotic"),
    ("BIOSHIP", "living"), ("SAILSHIP", "solar"), ("BIGGS", "corvette"),
    ("CAPITALFREIGHTER", "capital_freighter"), ("FREIGHTER", "freighter"),
    ("POLICEFREIGHTER", "freighter"), ("PIRATEFREIGHTER", "freighter"),
    ("VINTAGEINTERCEPTOR", "sentinel"), ("INTERCEPTOR", "sentinel"),
)

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

# 允许出现的全部类型（程序化 + 固定模型 + 未知）
ALL_TYPES = set(PROC_MODELS) | {"corvette", "unknown"}

TYPE_LABELS = {
    "fighter": "战斗机", "hauler": "运输舰", "explorer": "探索舰", "shuttle": "穿梭机",
    "exotic": "异星", "living": "生物舰", "solar": "太阳帆", "sentinel": "拦截机",
    "freighter": "货船", "capital_freighter": "主力货船", "corvette": "护卫舰",
    "unknown": "未知",
}


class ShipRefError(ValueError):
    pass


def type_from_model(filename: str | None) -> str:
    """从模型路径推断船型；认不出就返回 "unknown"。

    注意顺序：**先看文件名，再看完整路径**。
    例：`.../S-CLASS/BIOPARTS/BIOSHIP_PROC.SCENE.MBIN` 的目录里带 S-CLASS，
    若直接匹配全路径会误判成异星；文件名是 BIOSHIP_PROC，应当判为生物舰。
    """
    up = (filename or "").upper()
    base = up.rsplit("/", 1)[-1]
    for scope in (base, up):
        for token, typ in MODEL_TOKENS:
            if token in scope:
                return typ
    return "unknown"


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
    ship_class: str = ""            # S/A/B/C（来自存档）
    stats: dict | None = None       # {damage, shield, hyperdrive, agility}

    # --- 构造 ---
    @classmethod
    def from_save_ship(cls, sh) -> "ShipRef":
        """把 Shipwright 的 ships.Ship 转成 ShipRef。

        类型推断三级兜底：上游的 category_guess → 模型文件名（不带 _PROC 也认）→ unknown。
        玩家存档里常见固定模型（如 `BIGGS.SCENE.MBIN`、`SAILSHIP.SCENE.MBIN`），
        上游可能猜成 unknown，这里补上。
        """
        cat = (sh.category_guess or "").lower()
        model = (sh.filename or "").upper()
        by_model = type_from_model(sh.filename)
        typ = SAVE_CATEGORY.get(cat) or by_model
        if not model.endswith("_PROC.SCENE.MBIN") and by_model != "unknown":
            typ = by_model                      # 固定模型以模型名为准（如 VINTAGEINTERCEPTOR → 拦截机）
        procedural = bool(sh.is_procedural) and model.endswith("_PROC.SCENE.MBIN")
        seed = (sh.seed or "0x0")
        if int(seed, 16) == 0:                     # 空槽/占位：标记为不可用
            procedural = False
        return cls(type=typ, seed=seed, model=sh.filename or None,
                   name=(sh.name or "").strip(), source="save", slot=sh.index,
                   procedural=procedural)

    # --- 校验 ---
    def normalized(self) -> "ShipRef":
        if self.type not in ALL_TYPES:
            raise ShipRefError(f"未知船型：{self.type!r}")
        if not _SEED_RE.match(self.seed or ""):
            raise ShipRefError(f"种子格式不对：{self.seed!r}（应形如 0x8BA812880CFAAA1C）")
        self.seed = "0x" + self.seed[2:].upper().rjust(16, "0")
        if self.parts:
            self.parts = [p.strip().upper() for p in self.parts if p and p.strip()]
        return self

    @property
    def can_preview(self) -> bool:
        """能不能用「种子 + 部件树」生成 3D：必须是程序化模型且类型在支持列表里。"""
        return bool(self.procedural) and self.type in PROC_MODELS and int(self.seed, 16) != 0

    @property
    def type_label(self) -> str:
        return TYPE_LABELS.get(self.type, self.type)

    def proc_model_matches(self) -> bool:
        """种子是否真的能改变外观（模型必须是本类型的 _PROC）。"""
        want = PROC_MODELS.get(self.type)
        if not want or not self.model:
            return self.procedural
        return self.model.upper().endswith(want)

    def to_dict(self) -> dict:
        return asdict(self)


def stats_summary(raw_stats: dict) -> dict:
    """把 ship_stats 的行转成 {damage/shield/hyperdrive/agility: value}。"""
    key = {"SHIP_DAMAGE": "damage", "SHIP_SHIELD": "shield",
           "SHIP_HYPERDRIVE": "hyperdrive", "SHIP_AGILE": "agility"}
    out = {}
    for row in raw_stats.get("stats") or []:
        k = key.get(str(row.get("id")))
        if k:
            out[k] = row.get("value")
    return out


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
