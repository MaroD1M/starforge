"""游戏侧数据 Mod 生成器：给 8 种 `_PROC` 船型各造一个"奖励模板槽"。

做法沿用 Super Ship Hunter（MIT）验证过的路线：
  `REWARDTABLE.EXML` 里加 `GcRewardSpecificShip`，其 `ShipResource{ Filename, Seed }`
  就是外部程序要改写的 16 字节种子字段。

我们对它做两处加固（来自上一轮审计 P0-2 的建议）：
  1. **每个槽的 `ShipLayout.Slots` 取不同值**（120..127）——`Slots` 不会被游戏归一化，
     可以当签名的一部分，避免 8 条 AOB 退化成同一条；
  2. **首次定位用出厂种子**（`STARFORGE_<i>` 的 ASCII），写入后就靠 Slots 定位。

生成的目录结构（丢进 `GAMEDATA/MODS/` 即被游戏加载）：
  starforge-templates/
    METADATA/REALITY/TABLES/REWARDTABLE.EXML
    README.txt
"""
from __future__ import annotations

import os

# 8 种可换外观的程序化船型 → (游戏内模型, 展示名, ShipClass)
TEMPLATES = [
    ("sentinel", "MODELS/COMMON/SPACECRAFT/SENTINELSHIP/SENTINELSHIP_PROC.SCENE.MBIN", "拦截机", "Robot"),
    ("fighter", "MODELS/COMMON/SPACECRAFT/FIGHTERS/FIGHTER_PROC.SCENE.MBIN", "战斗机", "Fighter"),
    ("hauler", "MODELS/COMMON/SPACECRAFT/DROPSHIPS/DROPSHIP_PROC.SCENE.MBIN", "运输舰", "Dropship"),
    ("explorer", "MODELS/COMMON/SPACECRAFT/SCIENTIFIC/SCIENTIFIC_PROC.SCENE.MBIN", "探索舰", "Scientific"),
    ("shuttle", "MODELS/COMMON/SPACECRAFT/SHUTTLE/SHUTTLE_PROC.SCENE.MBIN", "穿梭机", "Shuttle"),
    ("exotic", "MODELS/COMMON/SPACECRAFT/S-CLASS/S-CLASS_PROC.SCENE.MBIN", "异星", "Royal"),
    ("living", "MODELS/COMMON/SPACECRAFT/S-CLASS/BIOPARTS/BIOSHIP_PROC.SCENE.MBIN", "生物舰", "Alien"),
    ("solar", "MODELS/COMMON/SPACECRAFT/SAILSHIP/SAILSHIP_PROC.SCENE.MBIN", "太阳帆", "Sail"),
]

# 出厂种子：7 字节 ASCII 前缀 + 1 字节序号 = 恰好 64 位（种子字段是 int64！）
# 之前用 9 字节 "STARFORGE" 会溢出 u64 —— 已被测试抓住。
TAG = b"STARFOR"


def factory_seed(index: int) -> int:
    """0x00..0x07 对应的可搜索、互不相同的 64 位出厂种子。"""
    if not 0 <= index < 16:
        raise ValueError("index 必须在 0..15")
    return int.from_bytes(TAG, "little") | ((0xA0 + index) << 56)


def slots_for(index: int) -> int:
    return 120 + index          # 120..127：非归一化字段，可当签名


def _entry(index: int, type_: str, model: str, label: str, ship_class: str) -> str:
    seed = factory_seed(index)
    slots = slots_for(index)
    rid = f"STARFORGE_{type_.upper()}"
    return f'''    <Property name="SpecialRewardTable" value="GcGenericRewardTableEntry" _id="{rid}">
      <Property name="Id" value="{rid}" />
      <Property name="List" value="GcRewardTableItemList">
        <Property name="RewardChoice" value="GiveAll" />
        <Property name="OverrideZeroSeed" value="false" />
        <Property name="UseInventoryChoiceOverride" value="false" />
        <Property name="IncrementStat" value="" />
        <Property name="List">
          <Property name="GcRewardTableItem" _id="ITEM_{rid}">
            <Property name="PercentageChance" value="100" />
            <Property name="LabelID" value="" />
            <Property name="Reward" value="GcRewardSpecificShip">
              <Property name="GcRewardSpecificShip">
                <Property name="ShipResource" value="GcResourceElement">
                  <Property name="Filename" value="{model}" />
                  <Property name="ResHandle" value="GcResource">
                    <Property name="ResourceID" value="0" />
                  </Property>
                  <Property name="Seed" value="{seed}" />
                </Property>
                <Property name="ShipLayout" value="GcInventoryLayout">
                  <Property name="Slots" value="{slots}" />
                  <Property name="Seed" value="1" />
                  <Property name="Level" value="1" />
                </Property>
                <Property name="ShipClass" value="{ship_class}" />
              </Property>
            </Property>
          </Property>
        </Property>
      </Property>
    </Property>'''


def rewardtable_xml() -> str:
    entries = "\n".join(_entry(i, t, m, label, cls)
                        for i, (t, m, label, cls) in enumerate(TEMPLATES))
    return f'''<?xml version="1.0" encoding="utf-8"?>
<Data template="GcRewardTable">
  <Property name="SpecialRewardTable">
{entries}
  </Property>
</Data>
'''


README = """starforge 模板 Mod
==================

这是给 starforge 的「游戏内实时通道」用的数据 Mod：为 8 种可换外观的飞船各提供一个
奖励模板槽。starforge 只改写每个模板的 `Seed` 字段（16 字节），不会碰你的存档，
也不会改写游戏代码。

安装
----
把整个 `starforge-templates` 文件夹复制到：

    <游戏目录>\\GAMEDATA\\MODS\\

即最终形如：

    ...\\No Man's Sky\\GAMEDATA\\MODS\\starforge-templates\\METADATA\\REALITY\\TABLES\\REWARDTABLE.EXML

卸载
----
删掉 `starforge-templates` 文件夹即可。

注意
----
* 数据 Mod 采用 `_id` 合并语义（与社区通行做法一致）；若你装了别的改 REWARDTABLE 的 Mod，
  可能互相覆盖，请只保留一个。
* 本 Mod 不含任何游戏原始文件。模板参数（槽位数/等级/船型）参考了社区公开做法，
  仍可能随游戏版本变化；若某船型领不出来，请反馈。
"""


def write_mod(dest: str) -> dict:
    """生成完整 Mod 目录，返回 {path, files, entries}。"""
    root = os.path.join(dest, "starforge-templates")
    tables = os.path.join(root, "METADATA", "REALITY", "TABLES")
    os.makedirs(tables, exist_ok=True)
    rt = os.path.join(tables, "REWARDTABLE.EXML")
    with open(rt, "w", encoding="utf-8") as f:
        f.write(rewardtable_xml())
    with open(os.path.join(root, "README.txt"), "w", encoding="utf-8") as f:
        f.write(README)
    return {"path": root, "files": [rt, os.path.join(root, "README.txt")],
            "entries": [{"type": t, "id": f"STARFORGE_{t.upper()}",
                         "seed": factory_seed(i), "slots": slots_for(i),
                         "model": m} for i, (t, m, _l, _c) in enumerate(TEMPLATES)]}


def manifest() -> list[dict]:
    """给外部写入器用的清单：每个槽的类型/出厂种子/Slots/模型。"""
    return [{"index": i, "type": t, "model": m, "label": label, "class": cls,
             "id": f"STARFORGE_{t.upper()}", "factory_seed": factory_seed(i),
             "slots": slots_for(i)} for i, (t, m, label, cls) in enumerate(TEMPLATES)]
