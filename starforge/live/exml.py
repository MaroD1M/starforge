"""游戏侧数据 Mod 生成器：给 8 种 `_PROC` 船型各造一个"奖励模板槽"。

做法沿用 Super Ship Hunter（MIT）验证过的路线：
  `REWARDTABLE.EXML` 里加 `GcRewardSpecificShip`，其 `ShipResource{ Filename, Seed }`
  就是外部程序要改写的 16 字节种子字段。

我们对它做两处加固（来自上一轮审计 P0-2 的建议）：
  1. **每个槽的 `ShipLayout.Slots` 取不同值**（120..127）——`Slots` 不会被游戏归一化，
     可以当签名的一部分，避免 8 条 AOB 退化成同一条；
  2. **首次定位用出厂种子**（`STARFORGE_<i>` 的 ASCII），写入后就靠 Slots 定位。

为了让玩家**在游戏里点得出来**，另外两份文件负责"触发入口"（结构照 SSH 样本）：
  * `EMOTEMENU.EXML`：8 条 `GcPlayerEmote`（`_id` = 模板 id）→ 表情菜单里多出 8 个选项；
  * `PLAYERCHARACTER.ENTITY.EXML`：8 条动画 + `BOOT` 状态里的 `GcAnimFrameEvent`
    → `GcRewardAction`，玩家选中表情时游戏发放对应奖励。

生成的目录结构（丢进 `GAMEDATA/MODS/` 即被游戏加载）：
  starforge-templates/
    METADATA/REALITY/TABLES/REWARDTABLE.EXML
    METADATA/UI/EMOTEMENU.EXML
    MODELS/COMMON/PLAYER/PLAYERCHARACTER/PLAYERCHARACTER/ENTITIES/PLAYERCHARACTER.ENTITY.EXML
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

# 三份文件的相对路径（与游戏加载路径严格一致）
REWARDTABLE_REL = os.path.join("METADATA", "REALITY", "TABLES", "REWARDTABLE.EXML")
EMOTEMENU_REL = os.path.join("METADATA", "UI", "EMOTEMENU.EXML")
PLAYERCHARACTER_REL = os.path.join(
    "MODELS", "COMMON", "PLAYER", "PLAYERCHARACTER", "PLAYERCHARACTER",
    "ENTITIES", "PLAYERCHARACTER.ENTITY.EXML")

# 表情标题只复用游戏里**已经存在**的本地化 key（SSH 实测有效），循环使用。
# 不引入全新的 Loc key：没被 LocTable 定义的 key 会原样显示成大写字符串。
EMOTE_TITLES = [
    "NOTIFY_SPACE_POLICE_TITLE",
    "BASESTATS_ROYAL_L",
    "UI_LOCAL_ROBOT",
    "UI_OUTSYS_ROBOT",
]

# 自带的本地化表：表情标题用自己的 key，避免 8 个表情共用 4 个占位标题。
# `.mxml` 是游戏的“合并式”本地化文件（按 Id 合并），所以只写新增的 8 条即可。
LOCTABLE_REL = "LocTable.mxml"
EMOTE_TITLE_PREFIX = "STARFORGE_EMOTE_"


def emote_title_key(type_: str) -> str:
    return EMOTE_TITLE_PREFIX + type_.upper()


# 8 条表情各自的标题（简中 / 繁中 / 英文）：**每种语言内部不混排**。
TITLE_TEXT = {
    "sentinel": ("星铸 · 拦截机", "星鑄 · 攔截機", "Starforge · Interceptor"),
    "fighter": ("星铸 · 战斗机", "星鑄 · 戰鬥機", "Starforge · Fighter"),
    "hauler": ("星铸 · 运输舰", "星鑄 · 運輸艦", "Starforge · Hauler"),
    "explorer": ("星铸 · 探索舰", "星鑄 · 探索艦", "Starforge · Explorer"),
    "shuttle": ("星铸 · 穿梭机", "星鑄 · 穿梭機", "Starforge · Shuttle"),
    "exotic": ("星铸 · 异星", "星鑄 · 異星", "Starforge · Exotic"),
    "living": ("星铸 · 生物舰", "星鑄 · 生物艦", "Starforge · Living"),
    "solar": ("星铸 · 太阳帆", "星鑄 · 太陽帆", "Starforge · Solar"),
}

# 游戏本地化表的语言字段（照其原表顺序；缺哪个就填英文，不影响加载）。
LOC_LANGS = (
    "BrazilianPortuguese", "Dutch", "English", "French", "German", "Italian",
    "Japanese", "Korean", "LatinAmericanSpanish", "Polish", "Portuguese",
    "Russian", "SimplifiedChinese", "Spanish", "TencentChinese",
    "TraditionalChinese", "USEnglish",
)

# 表情动画复用游戏已有的一段扳机动画；我们只需要"播得完 + 触发帧事件"。
EMOTE_ANIM = ("MODELS/COMMON/PLAYER/PLAYERCHARACTER/ANIMS/BINOCS/"
              "2H_BINOCS_UNSHEATHE.ANIM.MBIN")


def template_id(type_: str) -> str:
    """模板 id：REWARDTABLE 的 `_id`、表情 id、动画名共用同一个字符串。"""
    return f"STARFORGE_{type_.upper()}"


def template_ids() -> list[str]:
    """8 个模板 id（顺序与 TEMPLATES 一致）。"""
    return [template_id(t) for t, _m, _l, _c in TEMPLATES]


def factory_seed(index: int) -> int:
    """0x00..0x07 对应的可搜索、互不相同的 64 位出厂种子。"""
    if not 0 <= index < 16:
        raise ValueError("index 必须在 0..15")
    return int.from_bytes(TAG, "little") | ((0xA0 + index) << 56)


def slots_for(index: int) -> int:
    return 120 + index          # 120..127：非归一化字段，可当签名


# 每型船在 `GcInventoryLayoutSizeType` 里的尺寸枚举（值取自 MBINCompiler 的枚举表；
# 注意游戏里穿梭机的 medium/large 是 `Sht*` 而不是 `Shu*`，这是游戏自己的拼写）。
SHIP_SIZE_TYPE = {
    "sentinel": "RobotLarge",
    "fighter": "FgtLarge",
    "hauler": "DrpLarge",
    "explorer": "SciLarge",
    "shuttle": "ShtLarge",
    "exotic": "RoyLarge",
    "living": "AlienLarge",
    "solar": "SailLarge",
}

# 表情图标不再用游戏的 `TYPE.*.DDS`——那些是"类别符号"（穿梭机那张其实是一对齿轮）。
# 这里用 starforge 自己的渲染器把 8 个模板的**真船**渲成 128×128 BC1 DDS，
# 随仓库放在 `live/assets/icons/`，生成 Mod 时原样复制进去。
ICON_DIR = "TEXTURES/UI/FRONTEND/ICONS/STARFORGE"
ICON_ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets", "icons")

SHIP_ICON = {
    "sentinel": "TEMPLATE.SENTINEL.DDS",
    "fighter": "TEMPLATE.FIGHTER.DDS",
    "hauler": "TEMPLATE.HAULER.DDS",
    "explorer": "TEMPLATE.EXPLORER.DDS",
    "shuttle": "TEMPLATE.SHUTTLE.DDS",
    "exotic": "TEMPLATE.EXOTIC.DDS",
    "living": "TEMPLATE.LIVING.DDS",
    "solar": "TEMPLATE.SOLAR.DDS",
}


def icon_path(type_: str) -> str:
    """表情图标在游戏虚拟文件系统里的路径。"""
    return f"{ICON_DIR}/{SHIP_ICON[type_]}"


def icon_asset(type_: str) -> str:
    """仓库里对应的 DDS 文件（生成 Mod 时复制）。"""
    return os.path.join(ICON_ASSET_DIR, SHIP_ICON[type_].lower())

# 领到手的船名（`NameOverride` 是字面量，不走本地化）：用纯中文，避免中英混排。
SHIP_NAME = {
    "sentinel": "星铸·拦截机",
    "fighter": "星铸·战斗机",
    "hauler": "星铸·运输舰",
    "explorer": "星铸·探索舰",
    "shuttle": "星铸·穿梭机",
    "exotic": "星铸·异星",
    "living": "星铸·生物舰",
    "solar": "星铸·太阳帆",
}

# 领船时附带的科技（Id 用游戏通用物品 id；`_id` 按模板加前缀，避免 8 条奖励互相合并）。
SHIP_TECH = (
    ("LAUNCHER", 300), ("SHIPJUMP1", 200), ("HYPERDRIVE", 120), ("SHIPSHIELD", 200),
)


def _tech_slot(rid: str, item: str, amount: int) -> str:
    return f'''                  <Property name="Slots" value="GcInventoryElement" _id="{rid}_{item}">
                    <Property name="Type" value="GcInventoryType">
                      <Property name="InventoryType" value="Technology" />
                    </Property>
                    <Property name="Id" value="{item}" />
                    <Property name="Amount" value="{amount}" />
                    <Property name="MaxAmount" value="{amount}" />
                    <Property name="DamageFactor" value="0.000000" />
                    <Property name="FullyInstalled" value="true" />
                    <Property name="Index" value="GcInventoryIndex">
                      <Property name="X" value="-1" />
                      <Property name="Y" value="-1" />
                    </Property>
                  </Property>'''


def _entry(index: int, type_: str, model: str, label: str, ship_class: str) -> str:
    """一条 `GcRewardSpecificShip` 奖励。

    结构照 Super Ship Hunter（MIT）实测可用的条目，只把船型相关字段参数化。
    这些字段缺一不可：少 `ShipType`/`IsRewardShip` 时游戏会把奖励当成"购买货船"，
    少 `List` 上的 `value="GcRewardTableItem"` 时会按错误类型解析奖励项。
    """
    seed = factory_seed(index)
    slots = slots_for(index)
    rid = template_id(type_)
    size_type = SHIP_SIZE_TYPE[type_]
    tech = "\n".join(_tech_slot(rid, item, amount) for item, amount in SHIP_TECH)
    return f'''    <Property name="SpecialRewardTable" value="GcGenericRewardTableEntry" _id="{rid}">
      <Property name="Id" value="{rid}" />
      <Property name="List" value="GcRewardTableItemList">
        <Property name="RewardChoice" value="GiveAll" />
        <Property name="OverrideZeroSeed" value="false" />
        <Property name="UseInventoryChoiceOverride" value="false" />
        <Property name="IncrementStat" value="" />
        <Property name="List">
          <Property name="List" value="GcRewardTableItem" _index="0">
            <Property name="PercentageChance" value="100.000000" />
            <Property name="LabelID" value="" />
            <Property name="Reward" value="GcRewardSpecificShip">
              <Property name="GcRewardSpecificShip">
                <Property name="ShipResource" value="GcResourceElement">
                  <Property name="Filename" value="{model}" />
                  <Property name="ResHandle" value="GcResource">
                    <Property name="ResourceID" value="0" />
                  </Property>
                  <Property name="Seed" value="{seed}" />
                  <Property name="ProceduralTexture" value="TkProceduralTextureChosenOptionList">
                    <Property name="Samplers" />
                  </Property>
                  <Property name="AltId" value="" />
                </Property>
                <Property name="Customisation" value="GcCharacterCustomisationData">
                  <Property name="DescriptorGroups" />
                  <Property name="PaletteID" value="" />
                  <Property name="Colours" />
                  <Property name="TextureOptions" />
                  <Property name="BoneScales" />
                  <Property name="Scale" value="1.000000" />
                </Property>
                <Property name="ShipLayout" value="GcInventoryLayout">
                  <Property name="Slots" value="{slots}" />
                  <Property name="Seed" value="1" />
                  <Property name="Level" value="1" />
                </Property>
                <Property name="ShipInventory" value="GcInventoryContainer">
                  <Property name="Slots">
{tech}
                  </Property>
                  <Property name="ValidSlotIndices" />
                  <Property name="Class" value="GcInventoryClass">
                    <Property name="InventoryClass" value="S" />
                  </Property>
                  <Property name="StackSizeGroup" value="GcInventoryStackSizeGroup">
                    <Property name="InventoryStackSizeGroup" value="Default" />
                  </Property>
                  <Property name="BaseStatValues" />
                  <Property name="SpecialSlots" />
                  <Property name="Width" value="0" />
                  <Property name="Height" value="0" />
                  <Property name="IsCool" value="false" />
                  <Property name="Name" value="" />
                  <Property name="Version" value="0" />
                </Property>
                <Property name="CostAmount" value="0" />
                <Property name="CostCurrency" value="GcCurrency">
                  <Property name="Currency" value="Units" />
                </Property>
                <Property name="ShipType" value="GcSpaceshipClasses">
                  <Property name="ShipClass" value="{ship_class}" />
                </Property>
                <Property name="UseOverrideSizeType" value="true" />
                <Property name="OverrideSizeType" value="GcInventoryLayoutSizeType">
                  <Property name="SizeType" value="{size_type}" />
                </Property>
                <Property name="NameOverride" value="{SHIP_NAME[type_]}" />
                <Property name="IsGift" value="true" />
                <Property name="IsRewardShip" value="true" />
                <Property name="FormatAsSeasonal" value="false" />
                <Property name="ModelViewOverride" value="GcModelViews">
                  <Property name="ModelViews" value="None" />
                </Property>
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


# ---------------------------------------------------------------- 表情菜单
#
# `_id` 合并语义：游戏把同 `_id` 的 `GcPlayerEmote` 与内置表情表合并，
# 因此只需写出新增的 8 条，不需要复制游戏原始 EMOTEMENU 内容。
# 图标全部用 pak 里**实际存在**的 DDS（逐个用 hgpaktool 校验过，见 SHIP_ICON）；
# 运输舰 / 探索舰没有同名图标，改用最接近的货船 / 穿梭机图标，避免整排空白。


def _emote(index: int, type_: str) -> str:
    tid = template_id(type_)
    title = emote_title_key(type_)
    icon = icon_path(type_)
    return f'''    <Property name="Emotes" value="GcPlayerEmote" _id="{tid}">
      <Property name="Title" value="{title}" />
      <Property name="ChatText" value="" />
      <Property name="ChatUsesPrefix" value="false" />
      <Property name="EmoteID" value="{tid}" />
      <Property name="AnimationName" value="{tid}" />
      <Property name="PropData" value="GcPlayerEmotePropData" />
      <Property name="Icon" value="TkTextureResource">
        <Property name="Filename" value="{icon}" />
        <Property name="ResHandle" value="GcResource">
          <Property name="ResourceID" value="0" />
        </Property>
      </Property>
      <Property name="LinkedSpecialID" value="" />
      <Property name="NeverShowInMenu" value="false" />
      <Property name="LoopAnimUntilMove" value="" />
      <Property name="CloseMenuOnSelect" value="false" />
      <Property name="MoveToCancel" value="true" />
      <Property name="GekAnimationName" value="" />
      <Property name="GekLoopAnimUntilMove" value="" />
      <Property name="AvailableUnderwater" value="false" />
      <Property name="RidingAnimationName" value="{tid}" />
      <Property name="IsPetCommand" value="false" />
      <Property name="PetCommandTitle" value="" />
    </Property>'''


def emotemenu_xml() -> str:
    """表情菜单：8 条 `GcPlayerEmote`，选中即触发同名动画。

    标题用自己的 `STARFORGE_EMOTE_<TYPE>` key，由同目录的 `LocTable.mxml` 提供文案，
    这样 8 个表情各有独立名字，不会再出现"三个表情同名"的情况。
    """
    entries = "\n".join(_emote(i, t) for i, (t, _m, _l, _c) in enumerate(TEMPLATES))
    return f'''<?xml version="1.0" encoding="utf-8"?>
<Data template="cGcPlayerEmoteList">
  <Property name="Emotes">
{entries}
  </Property>
</Data>
'''


def _loc_entry(type_: str) -> str:
    zh_s, zh_t, en = TITLE_TEXT[type_]
    rows = []
    for lang in LOC_LANGS:
        value = zh_s if lang == "SimplifiedChinese" else (
            zh_t if lang == "TraditionalChinese" else en)
        rows.append(f'      <Property name="{lang}" value="{value}" />')
    return (f'    <Property name="Table" value="TkLocalisationEntry">\n'
            f'      <Property name="Id" value="{emote_title_key(type_)}" />\n'
            + "\n".join(rows) + "\n    </Property>")


def loctable_mxml() -> str:
    """表情标题的本地化表：8 条，按 Id 合并进游戏原表。"""
    entries = "\n".join(_loc_entry(t) for t, _m, _l, _c in TEMPLATES)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<Data template="TkLocalisationTable">
  <Property name="Table">
{entries}
  </Property>
</Data>
'''


# ---------------------------------------------------------------- 玩家实体（触发器）


def _anim_data(type_: str) -> str:
    tid = template_id(type_)
    return f'''                    <Property name="Anims" value="TkAnimationData">
                      <Property name="Anim" value="{tid}" />
                      <Property name="Filename" value="{EMOTE_ANIM}" />
                      <Property name="AnimType" value="OneShotBlendable" />
                      <Property name="AnimGroupOverride" value="false" />
                      <Property name="Priority" value="0" />
                      <Property name="FrameStart" value="0" />
                      <Property name="FrameEnd" value="0" />
                      <Property name="FrameEndGame" value="0" />
                      <Property name="StartNode" value="" />
                      <Property name="ExtraStartNodes" />
                      <Property name="AdditiveBaseAnim" value="" />
                      <Property name="AdditiveBaseFrame" value="0.000000" />
                      <Property name="Mask" value="" />
                      <Property name="OffsetMin" value="0.000000" />
                      <Property name="OffsetMax" value="0.000000" />
                      <Property name="Delay" value="0.000000" />
                      <Property name="Speed" value="1.000000" />
                      <Property name="ActionStartFrame" value="0.000000" />
                      <Property name="ActionFrame" value="-1.000000" />
                      <Property name="Actions" />
                      <Property name="CreatureSize" value="AllSizes" />
                      <Property name="Notifies" />
                      <Property name="Additive" value="false" />
                      <Property name="Mirrored" value="false" />
                      <Property name="Active" value="true" />
                      <Property name="Has30HzFrames" value="false" />
                      <Property name="GameData" value="TkAnimationGameData">
                        <Property name="RootMotion" value="None" />
                        <Property name="BlockPlayerMovement" value="false" />
                        <Property name="BlockPlayerWeapon" value="Unblocked" />
                      </Property>
                    </Property>'''


def _trigger(type_: str) -> str:
    tid = template_id(type_)
    return f'''                        <Property name="Triggers" value="GcActionTrigger">
                          <Property name="Event" value="GcAnimFrameEvent">
                            <Property name="GcAnimFrameEvent">
                              <Property name="Anim" value="{tid}" />
                              <Property name="FrameStart" value="0" />
                              <Property name="StartFromEnd" value="false" />
                            </Property>
                          </Property>
                          <Property name="Action">
                            <Property name="Action" value="GcRewardAction" _index="1">
                              <Property name="GcRewardAction">
                                <Property name="Reward" value="{tid}" />
                              </Property>
                            </Property>
                          </Property>
                        </Property>'''


def playercharacter_xml() -> str:
    """玩家实体：注册 8 条动画，并在 `BOOT` 状态挂 8 条「播到第 0 帧就发奖」的触发器。

    状态 id 必须沿用 `BOOT`（SSH 实测可用）：`_id` 合并后与内置状态合流，
    无需复制游戏原有的整份 PLAYERCHARACTER 实体数据。
    """
    anims = "\n".join(_anim_data(t) for t, _m, _l, _c in TEMPLATES)
    triggers = "\n".join(_trigger(t) for t, _m, _l, _c in TEMPLATES)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<Data template="cTkAttachmentData">
  <Property name="Components">
    <Property name="Components" value="TkAnimationComponentData">
      <Property name="TkAnimationComponentData">
        <Property name="Anims">
{anims}
        </Property>
      </Property>
    </Property>
    <Property name="Components" value="GcTriggerActionComponentData">
      <Property name="GcTriggerActionComponentData">
        <Property name="States">
          <Property name="States" value="GcActionTriggerState" _id="BOOT">
            <Property name="StateID" value="BOOT" />
            <Property name="Triggers">
{triggers}
            </Property>
          </Property>
        </Property>
      </Property>
    </Property>
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

装好之后，游戏的表情菜单里会多出 8 个可领取模板，标题形如「Starforge 模板 · 拦截机」
（由随包的 LocTable.mxml 提供，图标取自 ICONS/SHIPTYPES）。选中任意一个表情，就会领取到
对应船型的飞船；**领到手的船外观由该模板的种子决定**——starforge 实时通道改的就是这个种子，
不会碰你的存档，也不会改写游戏代码。

卸载
----
删掉 `starforge-templates` 文件夹即可。

注意
----
* 数据 Mod 采用 `_id` 合并语义（与社区通行做法一致）；若你装了别的改 REWARDTABLE /
  EMOTEMENU / PLAYERCHARACTER 实体的 Mod，可能互相覆盖，请只保留一个。
* 表情图标是 starforge 用游戏模型现渲的 8 张真船图（128×128 DDS，含 BC1 压缩），
  不再复用游戏里的船型类别符号（那张"穿梭机"其实是一对齿轮）。
* 表情标题随游戏语言显示（简中「星铸 · 拦截机」/ 繁中「星鑄 · 攔截機」/ 英文
  「Starforge · Interceptor」），领到的船名固定为中文，不再中英混排。
* 本 Mod 不含任何游戏原始文件。模板参数（槽位数/等级/船型）参考了社区公开做法，
  仍可能随游戏版本变化；若某船型领不出来，请反馈。
"""


def write_mod(dest: str) -> dict:
    """生成完整 Mod 目录，返回 {path, files, entries}。"""
    root = os.path.join(dest, "starforge-templates")
    files: list[str] = []

    def _write(rel: str, text: str) -> str:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        files.append(path)
        return path

    _write(REWARDTABLE_REL, rewardtable_xml())
    _write(EMOTEMENU_REL, emotemenu_xml())
    _write(PLAYERCHARACTER_REL, playercharacter_xml())
    _write(LOCTABLE_REL, loctable_mxml())

    # 表情图标：把仓库里的 DDS 原样复制到 Mod 的贴图目录
    for type_, _m, _l, _c in TEMPLATES:
        src = icon_asset(type_)
        dst = os.path.join(root, ICON_DIR.replace("/", os.sep), SHIP_ICON[type_])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            fdst.write(fsrc.read())
        files.append(dst)

    _write("README.txt", README)
    return {"path": root, "files": files,
            "entries": [{"type": t, "id": template_id(t),
                         "seed": factory_seed(i), "slots": slots_for(i),
                         "model": m} for i, (t, m, _l, _c) in enumerate(TEMPLATES)]}


def manifest() -> list[dict]:
    """给外部写入器用的清单：每个槽的类型/出厂种子/Slots/模型。"""
    return [{"index": i, "type": t, "model": m, "label": label, "class": cls,
             "id": template_id(t), "factory_seed": factory_seed(i),
             "slots": slots_for(i)} for i, (t, m, label, cls) in enumerate(TEMPLATES)]
