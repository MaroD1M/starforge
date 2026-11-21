# 生物建模与「按特征搜索 → 传送」研究

> 研究范围：只读分析（代码、`<存档>`、公开上游仓库/文档），未启动游戏、未改业务代码。
> 验证环境：本机存档 `<存档>`（30 个同伴槽位、29 只有效）；研究时本机**没有安装 NMS**，
> 因此所有涉及 `PCBANKS` / `NMS.exe` 的结论沿用历史实测，标注为「未复验」。
>
> **后续更新（2026-11-21～22）**：本机已安装并实机验证 build 185034；
> `prepare_warp` 传送、`/pets` 只读解析、模板 Mod/图标均已落地。相关结论以
> `docs/LESSONS.md` 与 `docs/AGENT.md` 为准；本文仍是“研究/未验证”视角。

**标记约定**

| 标记 | 含义 |
|---|---|
| ✅ | 本机已实测（读代码或读存档） |
| 🟡 | 高置信（上游源码/社区资料/交叉一致），但未在本机复跑 |
| ⬜ | 未验证，必须实机/实包确认 |
| ⛔ | 需要逆向或实机内存操作才能继续 |

---

## 0. 结论先行

1. **生物的「外观」不是由单个种子决定的。** 物理部件由存档里的 `Descriptors[]` 明确列出；
   颜色/纹理由 `CreatureSeed` / `CreatureSecondarySeed` / `ColourBaseSeed` 决定；
   体型由 `Scale` + `BoneScaleSeed` 决定。**只拿一个 seed 无法离线画出生物**。
   （✅ 存档字段 + 社区一致口径；见 §3.1）
2. **不能像飞船那样「种子 → 部件」离线复现。** 社区（含 MIT 的 nmstoolkit）明确写了
   「不做 seed-accurate rendering，种子到部件的映射被社区刻意保持私有」。
   我们要么基于已存描述符渲染，要么做「合法部件组合生成器」，不要做 seed→parts。
3. **野生生物的种子绑定行星。** 本机 699 条动物发现记录里，`CreatureSeed/SpeciesSeed/GenusSeed`
   三个位置**没有一次跨星球重复**；同伴的种子能在本存档发现记录里命中时，命中的 `UA`
   与同伴 `UA` **完全一致**（16/29）。所以「找某只野生生物」的正确终点是
   **行星地址（UA）→ 12 位符文 → 传送**，不是一个可写入的种子。
4. **同伴可以改外观/改种子，但那是「造宠物」，不是「找生物」。** 写回结构上可行
   （`Pets[]` 就是 JSON，现有写事务可复用），但存在模型损坏、互动失效、联机共享、
   `AllowUnmodifiedReroll` 等风险；不建议作为第一阶段。
5. **3D 预览的资源链是通的，且比旧结论乐观。** 描述符 MBIN、场景、几何、贴图都在游戏包里；
   上游 NMSCD 的做法是「整只 rig 的 FBX + 按描述符名字隐藏未选部件」，不是逐部件骨骼拼装。
   我们的 `gltf.py` / `render.py` / `model3d.py` 大部分可复用；缺的是「生物描述符树 →
   场景节点名」的映射与贴图槽解析（⬜ 未验证）。
6. **「按特征搜索」应先做「已知生物索引」，而不是「宇宙暴力搜索」。** 本机已有：
   29 只同伴、699 条动物发现、行星 `CreatureIDs`（agent 可读）。先在这些真实数据上
   做过滤/搜索，再接传送；「全宇宙按外观搜」需要逆向生成器或第三方数据库授权。

---

## 1. 我们现在能读到什么

### 1.1 存档里的同伴 `PlayerStateData.Pets[]`

入口：`starforge/creature.py:54-106`（`companions()`），直接读 `nms_save` 的可读 JSON。
上游 `nms_save.extras.companions()` 只给 6 个字段（`NMS-Shipwright/nms_save/extras.py:202-210`），
我们自己的实现把整条记录展开：

| 字段 | 含义 | 备注 |
|---|---|---|
| `CreatureID` | 生物角色/物种 ID（如 `TREX`、`PLANTCAT`） | 带 `^` 前缀，需 strip |
| `Descriptors[]` | **物理部件 ID 列表** | 末尾通常是一个 10 位纯数字 ID（见下） |
| `CreatureSeed` | 主颜色/纹理种子（`[bool, "0x…"]`） | 与 `BoneScaleSeed` 经常相同，但不是必然 |
| `CreatureSecondarySeed` | 次颜色种子 | 常见 `[false, "0x0"]` |
| `SpeciesSeed` / `GenusSeed` | 物种/属种子 | 与发现记录里的种子同源 |
| `ColourBaseSeed` | 颜色基种子 | 常见 `[false, "0x0"]`，非零时影响配色 |
| `BoneScaleSeed` | 骨骼缩放种子 | 影响体型比例 |
| `Scale` | 整体缩放 | 0.1–10 左右 |
| `Biome` / `CreatureType` / `Predator` / `HasFur` | 群系/类型/掠食/有毛 | 枚举值带 `^` |
| `UA` | 来源行星的 Universe Address | 可能是 int 或 `"0x…"` 字符串 |
| `Trust` / `Traits[]` / `Moods[]` | 信任/性格/情绪 | 数值，可直接展示 |
| `BirthTime` / `LastEggTime` / `EggModified` | 时间与蛋状态 | 写回时容易漏 |
| `PetBattler*` | 战斗相关（新版本） | 本机存档已出现，旧解析器会忽略 |

**本机实测统计（29 只有效同伴）**

| 指标 | 值 |
|---|---|
| 有效同伴 / 槽位 | 29 / 30 |
| 不同 `CreatureID` | 22 |
| 不同来源行星（UA） | 19 |
| 来源银河 | Euclid 23、Budullangr 4、Hilbert Dimension 2 |
| 不同部件 ID（不含末尾数字） | 116 |
| 末尾带 10 位数字 ID | 27 / 29 |
| `CreatureSeed == BoneScaleSeed` | 29 / 29（本存档；**不是**通用规律） |
| `ColourBaseSeed` 非零 | 4 / 29 |

部件前缀分布（可当作「特征维度」）：

```
_BODY_ 12  _HEAD_ 10  _TAIL_ 6  _MESH_ 4  _FLOAT_ 3  _SHAPE_ 2
_FWINGS_/_BWINGS_/_MWINGS_ 各 2  _REXBACK_ 2  _ANTENNAS_ 2  _ACC_ 2
_SHOULDERACC_ 2  _BCA_ 2  _GHACCS_ 2  _CRABSHELL_ 1 …
```

**末尾的 10 位数字是什么**：两个独立社区工具都把它当「唯一 ID」：
NMSCD 导出的 JSON 里总会带一个随机生成的 10 位数字（`src/helper/idHelper.ts`），
laanp 的 Excel 工具也要求「Unique ID 必须随机化，否则别人看到的宠物不是你改的样子」。
语义（是否参与配件/花纹的随机）⬜ 未验证，但**改外观时应重新生成它**是社区共识。

### 1.2 发现数据：野生生物记录

存档顶层还有 `DiscoveryManagerData.DiscoveryData-v1.Store.Record[]`。
本机 3,210 条记录，其中 **699 条 `DT == "Animal"`**。下面是**结构示例**（数值已脱敏）：

```json
{"DD": {"UA": 123456789012345, "DT": "Animal",
        "VP": ["0x0123456789ABCDE1", "0x0123456789ABCDE2",
               "0x0123456789ABCDE3", "0x0123456789ABCDE4"]},
 "OWS": {"UID": "...", "USN": "...", "TS": 0}}
```

`DD.VP` 是 4 个或 5 个 64 位种子（476 条 4 个、223 条 5 个）。
把 699 条记录按位置做唯一性统计（✅ 本机实测）：

| 位置 | 唯一值数 | 跨星球重复 | 与同伴字段的对应 |
|---|---|---|---|
| `VP[0]` | 692 | **0** | `CreatureSeed` |
| `VP[1]` | 56 | 52 / 56 | 疑似「角色/原型种子」（56 ≈ 角色数量级）⬜ |
| `VP[2]` | 699 | **0** | `SpeciesSeed` |
| `VP[3]` | 529 | **0** | `GenusSeed` |
| `VP[4]`（仅 5 值记录） | 222 | **0** | 疑似第二性别 / `CreatureSecondarySeed` ⬜ |

**关键交叉验证**：29 只同伴中，有 16 只的 `(CreatureSeed, SpeciesSeed, GenusSeed)`
能在本存档的动物记录里找到；命中的记录 `UA` **全部等于**同伴 `UA`。
另外 13 只找不到（可能来自其他存档、发现记录被裁剪、或宠物被编辑/共享过）。
→ 这既证明「种子包 + 行星」是一个整体，也说明**不能把 `UA` 当作 100% 可信的来源**
（社区共享宠物经常把 `UA` 写成 0）。

`VP[1]` 只有 56 个值且大量跨星球复用，最可能是「物种所属的角色/原型」；
如果后续要按「属/科」搜索，这一位是入口。⬜ 语义未验证。

### 1.3 行星侧：agent 能读什么（需实机）

`starforge/agent/starforge_agent.py` 已实现：

| 端点 | 关键字段 | 说明 |
|---|---|---|
| `GET /planet` | `creature_ids`、`fauna`、`special_fauna`、`biome`、`weather` | 直接读 `cGcPlanetData.CreatureIDs`（`starforge_agent.py:751-775`） |
| `GET /planet/scan` | 同上 + 资源/额外提示 | 每个字段独立降级，失败标 `unsupported` |
| `GET /pets` | `descriptors`、6 个种子、`ua`、`scale`、`traits/moods` | 运行时字段，可与存档互校（`:564-608`） |

UI 端 `app/widgets/planet_dossier.py:16-18` 已经把 `fauna` / `creature_ids` 显示出来。
这意味着**「当前行星有哪些生物角色」已经是现成能力**（只到角色 ID，不到外观/种子）。

### 1.4 游戏数据表与资源

来自 `starforge/creature.py` 与历史实测（本机无游戏目录，未复验）：

| 数据 | 位置 | 状态 |
|---|---|---|
| 生物角色表 | `Metadata/Simulation/Ecosystem/CreatureDataTable.mbin` | 86 条，角色名可读；`Data` 字段未解（188 B/元素线索） |
| 生物描述符 | `NMSARC.Precache.pak` 里的 287 个 `.descriptor.mbin`（77 个目录） | 可解析（`nms_procgen/mbin.py` 同款结构） |
| Rig / 骨架 | `anteloperig / blobrig / catrig / trexrig …`（历史实测 18 个骨架族） | 名称可读 |
| 几何 | `NMSARC.MeshPlanetCREATURES.pak`（661 条 `<rig>/<mesh>.geometry.mbin.pc`） | 在位 |
| 贴图 | `NMSARC.TexCreature*.pak`（26 个包） | 在位 |
| 生成函数 | `cGcPlanetGenerator::GenerateCreatureRoles(cGcPlanetData&, u64 const&)` | ⛔ 未外部化 |

`role_table()`（`creature.py:273-347`）已经能把 86 条角色条目按 208 B 解析出
`Id / ForceType / RealType / MinScale / MaxScale` 等；`Data`（+0，16 B）是
`TkDynamicArray` 头，元素结构未解 —— 这是「从角色表拿外观」的最后一块，尚缺。

### 1.5 现有 UI / API / 写事务

| 能力 | 位置 | 现状 |
|---|---|---|
| 同伴列表 | `app/widgets/pets_view.py` | 只读表格：名称/类型/群系/CreatureID/种子/信任 |
| 同伴页提示 | `app/pages/fleet.py:299-304, 443-455` | 明确写「3D 需要生物生成器」 |
| JSON API | `web/routes.py:139-168` | `/creatures`、`/creatures/roles`、`/creatures/table`、`/creatures/capabilities` |
| 写事务 | `save/transaction.py:40-104` | 写开关、游戏进程检查、备份、原子写、读回校验、失败回滚、`copy=True` |
| 同伴写回 | `NMS-Shipwright/nms_save/extras.py:213-218` | **只有改名/改 Scale**；描述符/种子没有公开 API |

结论：**读的链路已经齐了；写的链路可复用，但只应该先做「改名/缩放」这种低风险字段。**

---

## 2. 上游开源方案研究

### 2.1 NMSCD Creature-Builder（重点）

- 仓库：<https://github.com/NMSCD/Creature-Builder>
- 线上：<https://creature.nmscd.com>
- 定位（README / 站点原文）：**「让玩家挑选可以一起使用的部件」**，
  按游戏文件里定义的规则构建生物；输出一段**可直接粘贴进存档编辑器**的宠物 JSON。
- 技术栈：React + TypeScript + three.js + Electron；模型是**预导出的 FBX/OBJ**，
  不是运行时从 pak 组装。

**它到底怎么工作（读源码确认）**

1. `src/assets/IPetData.json`：一张按 `CreatureId` 组织的**描述符兼容树**
   （`Details[].GroupId` → `Descriptors[].Id/Name/Children`），55 个角色、214 个描述符 ID、40 个组。
2. 用户逐组选择部件；树只提供「合法子部件」，所以不会拼出不存在的组合。
3. 输出 JSON：`CreatureID` + `Descriptors`（所选部件 + 一个随机 10 位唯一 ID）+ 种子/体型等。
4. 3D 预览（`objViewer.tsx`）：按 `CreatureID` 加载**整只** FBX/OBJ；
   未选中的部件通过 `getObjectByName(descriptor.Name)` / `${Name}Shape` **隐藏**，
   并过滤 `_coll`、`petacc_` 等辅助网格。**不是按骨骼逐件拼装**。
5. 数据来源：仓库里没有生成 `IPetData.json` 的脚本；从结构看是从游戏
   `cTkModelDescriptorList`（EXML/MBIN）导出的静态兼容树。

**局限（用我们自己的存档对照，✅ 实测）**

- 本机存档的 **22 个角色里，有 11 个在 IPetData 里没有树**：
  `PLANTCAT / HERMITCRAB / SCUTTLER_PET / WEIRDFLOAT / WALKINGBUILDING /
   LAND_JELLYFISH / PROTOROLLER / DIPLO_PET / PURPLE_WEIRD / PROTOFLYER / ROBO_RODENT`。
- 有树的 11 个角色里，只有 `ROBOTANTELOPE`、`FIEND`、部分 `LARGEBUTTERFLY` 能完全对上；
  `TREX / CAT / COW / GRUNT / TRICERATOPS / RODENT / BLOB / FLYINGSNAKE` 都缺大量实际部件。
- 结论：**这张表只能当参考，不能当数据源**；正确做法是从玩家本机的当前版本 pak
  重新生成描述符树。

**许可（重要）**：仓库**没有 LICENSE 文件**，`package.json` 也没有 `license` 字段
（GitHub API `/license` 返回 404）→ 默认「保留所有权利」，不能复制其代码；
仓库里的 `IPetData.json`、FBX/OBJ/DDS 还包含**游戏资产**，更不能进我们的仓库。

### 2.2 其他项目对照

| 项目 | 做了什么 | 许可 | 对我们有用/不可用的部分 |
|---|---|---|---|
| [NMSCD/Creature-Builder](https://github.com/NMSCD/Creature-Builder) | 部件选择 + JSON 导出 + 整只模型显隐预览 | **无 LICENSE**（默认保留权利） | 交互/数据形状可参考；代码/资产不可复制 |
| [nmstoolkit](https://github.com/pljeroen/nmstoolkit) | 存档编辑、同伴编辑、描述符解析、随机部件 3D 预览 | MIT | **最有价值的对照**：明确写了「不做 seed→parts，社区刻意保密」；设计可参考，代码不复制 |
| [laanp/NMS-Creature-Builder](https://github.com/laanp/NMS-Creature-Builder) | Excel 宠物编辑器；18 个属性、种子、唯一 ID | 归档、无明确许可 | 证明「属性=描述符、颜色=种子、唯一 ID 要随机」 |
| [vectorcmdr/NMSE](https://github.com/vectorcmdr/NMSE) | 全功能存档编辑器（含同伴） | **AGPL-3.0** | 不复制代码；只作为字段语义参照 |
| [Creature Builder+](https://nms-creature-builder.fun/) | 网页版，3D 预览/动画 | 未公开/未验证 | 只能看效果；不要依赖 |
| [NMSCE](https://nmsce.com/) | 社区坐标库，**可按 fauna 特征搜索** | 站点/数据未授权 | 证明「按特征搜」的正确实现是**数据库**，不是生成器 |
| [MBINCompiler / libMBIN](https://github.com/monkeyman192/MBINCompiler) | MBIN ↔ EXML | **NOASSERTION（自定义）** | 只读文档；我们已有自己的 MBIN 解析 |
| [hgpaktool](https://github.com/monkeyman192/hgpaktool) | pak 读取 | MIT | 已在用（`THIRD_PARTY_NOTICES.md`） |

### 2.3 最关键的一条情报

nmstoolkit README 原文：

> **No seed-accurate rendering.** 3D previews use randomized part selection, not seed-based.
> The NMS modding community deliberately keeps the seed-to-parts mapping private to protect
> the seed-hunting community. This project follows the same approach — see
> [nms.center](https://nms.center).

其 `part_selector.py` 注释也写明：随机选择**不使用任何 NMS 种子**，
「开源代码不应让 seed-to-parts 计算成为可能」。

这不是法律限制，而是**社区规范**。我们的方案应当尊重它：
- 做「描述符 → 模型」的渲染（已有信息，不泄露种子映射）；
- 做「已知生物/自己宠物」的索引搜索；
- **不做**、也不发布 seed→parts 的逆向结果。

---

## 3. 五个核心问题

### Q1 外观是否由「种子 + 星球上下文」决定？能否离线复现？

**结论：种子单独不够；外观 = 显式描述符 + 颜色种子 + 体型。**
**从「种子」离线复现外观：目前不行（社区保密 + 无公开算法）。**
**从「已存描述符」离线复现外观：原理可行，但需当前版本游戏数据（⬜ 未在本机验证）。**

依据：

1. ✅ 本机 29 只同伴，`Descriptors` 是完整部件列表；不同同伴即使同一 `CreatureID`，
   种子和部件也不同（例如两只 `TREX`、两只 `ROBOTANTELOPE`）。
2. 🟡 社区一致口径（r/NMSCoordinateExchange、laanp、NMSSaveEditor issue）：
   > Colours are determined by `CreatureSeed`, `CreatureSecondarySeed`, and `ColourBaseSeed`.
   > Physical characteristics are determined by the `Descriptors` field.
3. 🟡 NMSCD 的构建器让用户直接选部件，种子只是独立的可随机字段——说明部件不是由种子「算」出来的，
   至少不是社区可复现的算法。
4. ⬜ 星球上下文决定「这颗星球有哪些物种/角色」（`GenerateCreatureRoles`），
   但一旦生成，部件已经写进存档；没有证据表明换个星球会重算一只**已存在**同伴的外观。

**不确定性**：
- `Descriptors` 末尾的 10 位数字是否参与外观随机（配件位置/花纹）⬜；
- `CreatureSecondarySeed` 与 `ColourBaseSeed` 的具体着色公式⬜（需要贴图/材质链）；
- 游戏更新后旧描述符是否会被重算（`AllowUnmodifiedReroll`）⬜。

**可做的验证（便宜）**：拿一只同伴，只改 `CreatureSeed`（不动 `Descriptors`），
进游戏看颜色是否变；再只改 `Descriptors` 中一个部件，看模型是否变。
两个实验就能把「种子 vs 部件」的边界钉死。

### Q2 能否按特征搜索 → 得到候选种子？搜索空间与数据结构？

要拆成三种「搜索」，它们的答案完全不同：

#### (a) 搜「已知生物」（自己的同伴 / 已发现的野生生物）——✅ 离线可做

- 数据：29 只同伴（116 个部件标签、22 个角色、19 个星球）+ 699 条动物发现。
- 可过滤字段：角色、群系、类型、掠食、体型、有毛、部件标签（`_BODY_*`/`_HEAD_*`/…）、
  `*XRARE` 稀有标记、来源银河/星球、是否已驯服。
- 结果：**宠物条目**或**行星地址**（不是新种子）。
- 数据结构：SQLite（复用 `galaxy.db` 模式）：
  `pets(index, role, biome, type, scale, predator, ua, species_seed, …)`、
  `pet_parts(pet_id, part, group, rarity)`、
  `animal_discoveries(ua, creature_seed, species_seed, genus_seed, archetype_seed, secondary)`、
  `planets(ua, glyphs, galaxy, biome, …)`。
- 这是第一阶段唯一「有真实数据、可验收」的搜索。

#### (b) 搜「可构建的宠物」——✅ 离线可做（需游戏目录重新生成规则）

- 输入：当前版本每个角色的描述符树（组/选项/权重/子组）。
- 输出：合法 `Descriptors` 组合 + 颜色种子 + 体型 + 唯一 ID → **一段宠物 JSON**。
- 搜索空间：**不是 2^64**。按 NMSCD 的表（不完整）穷举，每个角色合法组合
  最多 240 种、55 个角色合计约 1,562 种；本机存档的 116 个部件说明真实描述符树更大，
  真实组合数要等我们从本机 pak 重建后才能定（可能到几万/几十万，但仍是**可枚举的组合空间**，
  不是 2^64 的种子空间）。
- 注意：这产出的是「一只不存在的宠物」，不是「宇宙里某颗星球上的生物」；
  没有行星可传送，除非用户接受「写进存档」。

#### (c) 搜「全宇宙的野生生物」——⛔ 需逆向或第三方数据

- 暴力枚举行星 UA：不可行（18 quintillion 量级）。
- 先按群系/角色过滤行星：可行但需要 `GenerateCreatureRoles` 外部化（⛔）。
  `systemgen` 已有 ~0.039–0.1 s/系统的能力（约 25 系统/s），加上角色生成后
  可以做「在某个区域内找有 TREX 的星球」这种搜索，但**仍然拿不到部件/外观**。
- 用第三方数据库（NMSCE）：可行，但需要对方授权；Firestore 数据不是公开 API。
- **「按头/腿/颜色搜全宇宙」在没有 seed→parts 的前提下不可能实现。**

### Q3 生物种子是否绑定行星？「搜索指定生物」的终点是什么？

**结论：野生生物的种子包绑定行星。终点是「行星 UA + 符文 + 传送」，不是一个可写入的种子。**

依据：

1. ✅ 699 条动物发现记录：`VP[0]/VP[2]/VP[3]`（Creature/Species/Genus）在整份存档里
   **从未跨星球重复**；`VP[1]` 才有 52/56 跨星球复用（角色/原型级）。
2. ✅ 16/29 只同伴的种子能在发现记录中命中，且命中的 `UA` == 同伴 `UA`。
3. 🟡 NMS Wiki：一个物种（species/family）不会出现在第二颗星球上。
4. ✅ 29 只同伴的 `UA` 全部能解码成合法行星地址（19 个不同星球、3 个银河），
   `nms_procgen.locate.describe()` 直接给出 `coords` 与 12 位 `glyphs`。

**但是**：
- 同伴是「带在身上的快照」，外观由存档里的描述符决定；把它带到别的星球，
  它**不会变成当地生物**（⬜ 未实机对照，但由数据结构强烈支持）。
- ⬜ 社区有零散报告称在特殊生物星球上同伴会临时变成当地形态（可能是 bug/特例）；
  真实性未验证，需实机对照。这不影响「野生种子绑定行星」的结论。
- `UA` 可以被编辑/共享宠物写成 0，不能当唯一真相；需要「发现记录交叉验证」。
- 想让某只生物出现在另一颗星球：**做不到**（不改变世界种子/生成器）。

**因此产品语义应该是**：

| 用户想要 | 正确终点 | 错误承诺 |
|---|---|---|
| 找到某只野生生物 | 行星符文 → 传送 → 在当地找/驯服 | 「给你一个种子，刷出来」 |
| 拥有一只特定外观的宠物 | 生成宠物 JSON → 写存档/外部编辑器 | 「传送到某个星球就有」 |
| 分享一只宠物 | 分享宠物 JSON / 蛋 | 「分享种子」 |

### Q4 存档里的同伴能否直接改外观/改种子？风险？写事务能复用吗？

**结论：结构上可以；现有写事务可以直接复用；但风险高，第一阶段不要做。**

可行性：

- ✅ `Pets[i]` 就是普通 JSON；`transact_save()` 的 `mutate(readable)` 可以原地改
  `Descriptors`/种子/`Scale`/`CustomName`，调用方在 `verify()` 里读回逐字段核对；
  `writer._encode` 会重新编码整份存档，长度变化不是问题。
- ✅ 已有 `nms_save.extras.edit_companion()`（改名/缩放）作为低风险写回先例。
- ⬜ 没有验证过「改描述符后游戏是否接受、是否重算、是否影响其他字段」。

风险（按严重度）：

| 风险 | 说明 | 缓解 |
|---|---|---|
| 模型损坏 | 描述符不在该角色的合法树里 → 浮空/缺件/隐形；社区原话「can also mess up your pet」 | 只允许树内合法组合；写前预览；副本模式 |
| 互动失效 | 社区报告某些编辑宠物无法喂食/互动（“sequenced from eggs”类问题）⬜ | 先在可丢弃存档验证；不做批量 |
| 唯一 ID 未更新 | 改外观但沿用旧 10 位 ID，其他玩家可能看到旧外观 | 每次改外观重新生成 10 位 ID |
| 重算/回滚 | `AllowUnmodifiedReroll` / `EggModified` 可能让游戏改回或重算 ⬜ | 写后实机确认；保留备份 |
| 联机/共享 | 蛋可以送给别人；编辑宠物会传播；可能被视为作弊/污染社区 | 明确标注「自制/修改」，不冒充野生发现 |
| 槽位/数组 | 增删 `Pets[]` 还牵涉 `Eggs`、`UnlockedPetSlots`、`PetBattleTeam`、`PetAccessoryCustomisation` | 只改已有槽位字段，不增删 |
| 版本 | 描述符树随更新变化，旧组合可能失效 | 写回前校验当前版本树；版本指纹 |

**建议**：写回分三级：
1. L1：改名/缩放（已有上游 API）——可做；
2. L2：改颜色种子/体型（不动部件）——需实机验证；
3. L3：改 `Descriptors`（真正改外观）——只在 `copy=True` + 明确警告下做，且默认不发布。

### Q5 3D 预览需要哪些资源？现有 `gltf` 管线能复用到什么程度？

**需要的资源**

1. 描述符 MBIN：部件 ID/Name/引用/子组/权重（`cTkModelDescriptorList`）。
2. 场景 MBIN：节点树、变换、骨架、每个节点的 `GEOMETRY`。
3. 几何 MBIN + data：顶点/法线/UV/索引/蒙皮权重。
4. 材质 MBIN + 贴图：`TexCreature*.pak` 里的 DDS。
5. 可选：动画 MBIN（待机姿势）；没有动画时用绑定姿势也能看。

**可复用程度**

| 现有模块 | 复用 | 说明 |
|---|---|---|
| `nms_procgen/mbin.py` | ✅ 高 | 已解析 `cTkModelDescriptorList`（id/name/refs/kids）；`Chance` 权重还没取（结构里有，偏移待确认），提取路径/缓存要扩展到 creature |
| `nms_procgen/model3d.py` | 🟡 中高 | 场景解析、几何解码、蒙皮/关节/姿势是通用件；`_picked_meshes`/`ship_model` 是飞船专用入口，需要新写一个 creature 入口 |
| `starforge/gltf.py` | ✅ 高 | `parse_pack` / `build_glb` 与模型类型无关，直接可用 |
| `starforge/render.py` | ✅ 高 | 纯 numpy 软光栅（点云/三角 + 可选贴图采样），与模型类型无关，可做缩略图/降级 |
| `starforge/preview.py` | 🟡 中 | 缓存/L0-L1 降级/贴图注入的流程可照抄，飞船专用部分要替换 |
| `starforge/tex.py` | 🟡 中 | `rgba()` 能解 DDS；材质槽→贴图的映射需新写 |

**关键实现路径（比旧结论乐观）**

- NMSCD 的预览证明：整只 rig 的所有部件已经在模型里，**按描述符 Name 隐藏未选项**即可。
  我们不需要「按骨骼把部件拼起来」，只需要：
  1. 从描述符树拿到当前选择；
  2. 遍历场景节点，只保留名字命中所选描述符（或 `Name`/`Name+"Shape"`）的子树；
  3. 用绑定姿势/待机动画输出 GLB。
- ⬜ 未验证：生物场景是否真的一套包含全部部件；节点名是否等于描述符 `Name`；
  程序化角色（`PLANTCAT` 等）是否也有静态描述符/场景；贴图槽如何对应。
- 旧结论「`_BODY_PLANT` 在静态 rig descriptor 里零命中」需要复核：
  NMSCD 的 `IPetData.json` 里明确存在 `_BODY_PLANT`（BLOB）与 `_SHAPE_XRARE`（CAT），
  且本机 BLOB 同伴确实使用 `_BODY_PLANT,_PLANT_3`。因此旧结论**不应作为永久否定**，
  应作为 Phase 0 的第一个复核项。

---

## 4. 落地方案（分阶段）

> 标记：**离线可做** / **需实机** / **需逆向**。
> 依赖顺序：Phase 0 → 1 →（2a/2b/2c）→ 3；Phase 4 可与 2 并行。

### Phase 0：复核 spike（离线可做 + 需实机，0.5–1 天）

**目标**：把「3D 能不能做」从猜测变成事实，避免再写一份错误的否定文档。

1. 在装有 NMS 的机器上，列出 `NMSARC.Precache.pak` 中含 `creature` 的 `.descriptor.mbin`。
2. 抽 2–3 个角色（`blob`、`trex`、`plantcat` 若存在），用 `nms_procgen.mbin.load_descriptor`
   解析，检查：
   - 是否出现 `_BODY_PLANT` / `_HEAD_PLANT1` / `_MESH_PLANT`；
   - 每个描述符的 `refs` 是否指向 `.SCENE.MBIN`；
   - 场景节点名是否等于描述符 `Id`/`Name`（或 `Name+"Shape"`）。
3. 抽一个角色场景 + 几何，用 `model3d._scene_meshes` 取网格组，再走
   `model3d.pack` + `gltf.build_glb`，确认能出一只完整模型。
4. 结论写回本文件 §3 Q5 / §6，决定 Phase 4 是「整只模型显隐」还是「需生成器」。

**验收**：一个角色能在离线渲染出 PNG/GLB；或明确记录卡在哪一步。

### Phase 1：只读视图（+ 可选传送接线，离线可做 + 需实机，1–2 天）

**目标**：把「同伴 → 来源星球 → 符文」和「当前行星 → 生物角色」打通；默认不写存档、不做 3D。

后端（`starforge/creature.py`）：

- `companions()` 增加：
  - `origin`：`UA` → `{ua, galaxy, galaxy_name, coords, glyphs, planet}`（用 `nms_procgen.locate.describe`，失败返回 `None` + 原因）；
  - `descriptor_groups`：把部件拆成 `{group, id, rarity}`（`*XRARE` 标记稀有）；
  - `unique_id`：末尾 10 位数字（没有则 `None`）；
  - `species_key`：`(CreatureID, SpeciesSeed)`。
- 新增 `animal_discoveries(save_path)`：解析 `DiscoveryManagerData` 的 699 条 Animal，
  按 `UA` 建索引（只读）。
- 新增 `planet_fauna(ua)`：合并「该星球的同伴」+「该星球的发现记录」，
  输出「这颗星球已知有几只、哪些是宠物」。
- 新增 `current_planet_fauna()`：通过 `Services.agent_call("planet")` 拿 `creature_ids`
  （需实机，agent 未连接时明确降级）。

API/UI：

- `GET /api/creatures` 直接带上 `origin`/`descriptor_groups`（向后兼容）。
- `PetsView` 增加两列：「来源」（银河 + 12 位符文）与「部件」（前 3 个标签）；
  详情面板显示完整描述符分组、种子、UA、来源行星。
- 「复制符文」按钮；「传送」按钮作为**可选**接线（Phase 3 能力），默认折叠/二次确认，
  不改存档，只走 agent 的 `warp_portal`。
- 行星页已有 `creature_ids`；补一个「这些角色里哪些是你养过的」对照。

**验收**：
- 29 只同伴 → 19 个来源星球全部解出符文；无法解码的显示原因；
- 16/29 能关联到发现记录，关联错的为 0；
- 默认不写存档；传送只在用户显式触发 + 二次确认后发生，失败可用 `restore`；
- 现有测试全绿；新增纯函数测试（UA 解码、描述符分组、发现记录解析）。

**非目标**：3D、写回、seed→parts。

### Phase 2：搜索（分四块）

#### 2a 本地已知生物索引（离线可做，1–2 天）

- 建 `creature.db`（或复用 `galaxy.db`）：`pets` / `pet_parts` / `animal_discoveries` / `planets`。
- 搜索条件：角色、群系、类型、掠食、体型区间、有毛、部件标签、稀有标记、银河、是否已驯服。
- 结果：同伴卡片或行星卡片；点行星 → Phase 3 传送。
- 这是第一个真正可用的「按特征搜索」。

#### 2b 合法宠物生成器（离线可做，需游戏目录，2–3 天）

- 用本机 pak 重建当前版本的描述符树（不依赖 NMSCD 的 JSON）。
- 枚举/索引合法组合（规模按重建后的树计算；NMSCD 的残缺表是每角色 ≤240），
  支持「按部件/稀有度筛选」。
- 输出：宠物 JSON（复制/导出），**不直接写存档**。
- 可选：只对「自己的宠物」做「换头/换尾」的受控编辑，且走 `copy=True`。

#### 2c 行星角色搜索（需逆向 + 需实机，3–5 天起）

- 用 unicorn 外部化 `GenerateCreatureRoles`（参考 `systemgen` 的模式），
  输入行星/种子，输出角色列表（可能包含物种种子）。
- 结合 `galaxy.scan` 的 ~25 系统/s，做「区域内找有某角色的星球」。
- 仍然**不到外观**；只到「角色/群系/稀有度」。
- 风险：每次游戏更新要重对偏移；unicorn GPL 边界已有记录（见 `THIRD_PARTY_NOTICES.md`）。

#### 2d 第三方数据库（离线可做，但需授权，时间取决于对方）

- NMSCE 已有 fauna 搜索（Firestore `nmsceCombined`，字段含 `Genus`/`Diet`/`Temperament`/`addr`）。
- **不要抓取**：先联系站点/作者，确认许可与 API；否则只做「打开网页搜索」的外链。
- 若拿到授权：导入为只读表，按特征查 → 行星符文 → Phase 3。

### Phase 3：传送（需实机，0.5 天）

- 候选（行星 UA/符文）→ `Services.warp_portal(glyphs, galaxy, stage="prepare_warp")`
  （`services/__init__.py:1058-1066`）。
- 前置：agent 已连接、非多人、`allow_unverified_agent`、二次确认对话框
  （显示星球/星系/符文，允许取消）。
- 传送后已有 `_confirm_teleport_location` 读回位置；失败可 `restore`。
- **跨银河是风险项**：`warp_portal` 会把 `reality` 写进目标 UA（`starforge_agent.py:1287-1316`），
  但「从 Euclid 直接跳到 Budullangr」未实机验证；默认只对**当前银河**的候选开放，
  跨银河显示警告/先让用户自己到该银河。
- 验收：本机存档里 19 个来源星球中，同一银河的候选能成功传送并读回位置；
  跨银河标记「未验证」。

### Phase 4：3D 预览（需游戏目录；分四步）

1. **4a 资源与映射（离线可做，1–2 天）**：扩展 `mbin.py` 读生物描述符；确认
   「描述符 → 场景节点」命名规则；用 `model3d._scene_meshes` 导出整只模型。
2. **4b GLB（离线可做，1 天）**：把网格组喂给 `gltf.build_glb`；`render.render` 出缩略图；
   缓存键用 `(creature_id, 描述符集合, 游戏版本)`。
3. **4c 贴图/材质（离线可做，2–3 天）**：解析材质→DDS，用 `tex.rgba` 注入；
   没贴图时按材质类平涂（沿用 `gltf` 的降级）。
4. **4d 交互（1 天）**：描述符勾选 → 实时显隐；「缺失资源」明确降级，不伪造。

**验收**：本机 29 只同伴中至少 1 个角色能离线出 GLB/PNG；切换描述符能看到部件变化；
程序化角色（`PLANTCAT` 等）若缺静态资源，明确显示「需生成器」而不是空白模型。

---

## 5. 风险与许可

### 5.1 上游许可清单

| 上游 | 许可 | 结论 |
|---|---|---|
| NMSCD/Creature-Builder | **无 LICENSE / package.json 无 license** | 默认保留所有权利：**不复制代码、不复制 `IPetData.json`、不复制 FBX/OBJ/DDS** |
| nmstoolkit | MIT | 可参考设计；但其 README 明确反对 seed→parts，遵守社区规范 |
| NMSE | AGPL-3.0 | 不复制；只读字段语义 |
| MBINCompiler/libMBIN | NOASSERTION（自定义） | 不打包；只读文档 |
| hgpaktool | MIT | 已在用，保持声明 |
| NMSCE | 未授权 | 不抓取；先联系授权 |
| 我们自己的 starforge | MIT | 新增研究文档不改变许可 |

> 本文只引用上游结论与链接，**不含任何第三方源码**。如果后续新增依赖，
> 必须同步更新 `THIRD_PARTY_NOTICES.md`（现有包内许可边界见该文件）。

### 5.2 游戏数据再分发

- 仓库**不能**包含：pak、MBIN、EXML、DDS、FBX/OBJ、`IPetData.json`、任何从游戏导出的模型/贴图。
- 正确做法：运行时从玩家自己的 `GAMEDATA/PCBANKS` 提取到本地缓存（`nms_save.gamefiles.extract`），
  缓存不进 git；发布包也不带。
- 截图/缩略图可以展示，但不要打包成「素材库」。

### 5.3 逆向与社区规范

- `GenerateCreatureRoles` 外部化属于「跑游戏自己的代码」，技术上可行，
  但每次更新要重对偏移，且涉及 unicorn 的 GPL 边界（已有 `THIRD_PARTY_NOTICES.md`）。
- **seed→parts 映射**：社区刻意保密；即使逆向出来，也不应发布/内置。
  我们的产品可以没有它，仍然能提供「描述符渲染 + 已知生物搜索 + 传送」。
- 不要把「自制宠物」包装成「野生发现」；分享时标注修改来源。

### 5.4 写回风险

- 只在写开关打开、游戏退出、二次确认、备份、读回校验都满足时写；
  复用 `transact_save`，不要绕开。
- 第一阶段只读；第二阶段先 `copy=True`；第三阶段才考虑正式写。
- 联机模式不写；多人会话里不传送（agent 已有 `_multiplayer_block`）。

### 5.5 版本兼容

- 描述符树/角色表随游戏更新变化；「同一种子同一外观」只在**同一游戏版本**成立
  （与飞船一致，见 `handbook/01` 的版本守卫）。
- 任何 3D/生成器缓存都要带 `game_version` / `build` 指纹；更新后失效重建。

---

## 6. 未验证清单（按优先级）

| # | 问题 | 为什么重要 | 怎么验证 |
|---|---|---|---|
| 1 | 本地 pak 的生物描述符里是否有 `_BODY_PLANT/_HEAD_PLANT1/_MESH_PLANT` | 决定 3D 能否覆盖程序化角色 | Phase 0：抽 descriptor + 解析 |
| 2 | 生物场景节点名是否等于描述符 `Id`/`Name` | 决定「显隐法」是否可行 | Phase 0：解析一个 rig 场景 |
| 3 | 只改 `CreatureSeed` 是否改颜色、是否改部件 | 钉死「种子 vs 部件」 | 实机：可丢弃存档，两个对照组 |
| 4 | 换星球后同伴外观是否变化 | 决定产品文案 | 实机：同宠物两地截图 |
| 5 | `Descriptors` 末尾 10 位数字的确切作用 | 决定改外观时是否必须换 ID | 实机/社区对照 |
| 6 | 改 `Descriptors` 后宠物是否可互动、是否被重算 | 写回风险 | 实机：副本存档 |
| 7 | `VP[1]`/`VP[4]` 的语义 | 决定能否按属/性别搜索 | 更多地名/物种对照 |
| 8 | 跨银河 `reality` 写入是否可用 | Phase 3 边界 | 可丢弃存档，`prepare_warp` |
| 9 | 生物贴图材质槽映射 | 3D 贴图 | 抽材质 MBIN + DDS 对照 |
| 10 | NMSCE 数据授权 | Phase 2d 能否做 | 联系站点 |

---

## 7. 建议的第一阶段（最小可验证）

**一句话**：把「我的同伴 → 它来自哪颗星球 → 12 位符文 → 一键传送」做出来；以只读为主、传送为显式可选动作、可验收、能复用现有 agent。

**范围**

1. `starforge/creature.py`：
   - `companions()` 增加 `origin`（UA→符文/银河/坐标）、`descriptor_groups`、`unique_id`、`species_key`；
   - 新增 `animal_discoveries()` / `planet_fauna()`（只读 `DiscoveryManagerData`）。
2. `starforge/app/widgets/pets_view.py`：
   - 表格增加「来源」列（银河 + 符文），详情面板显示部件分组/种子/UA；
   - 「复制符文」按钮；「传送」按钮走二次确认（Phase 3 的最小接线）。
3. `starforge/services/__init__.py`：
   - `creatures()` 透传新字段；可选 `creature_origin()`；
   - 传送直接复用 `warp_portal`。
4. 测试（纯逻辑，不依赖真实游戏）：
   - UA 解码（合法/0/字符串/非法）；
   - 描述符分组与末尾数字识别；
   - 发现记录解析（4/5 个种子的边界）；
   - 关联规则（同 UA + 同 SpeciesSeed 才算命中）。

**验收**

- 29 只同伴全部显示「来源」：19 个星球、3 个银河；无法解码的显示原因，不猜。
- 16/29 能显示「该星球发现记录」的关联；关联错误 0。
- 同一银河的候选可以 `warp_portal` 并读回位置确认；跨银河明确标「未验证」。
- 不写存档、不做 3D、不承诺 seed→parts。
- `pytest` 全绿；`ruff` 无新增告警。

**为什么这是最小可验证**

- 它验证了整条价值链：**读存档 → 解 UA → 关联发现 → 符文 → 传送**；
- 不依赖游戏目录（除传送需 agent）、不依赖逆向、不依赖 3D；
- 即使后续 3D/搜索全部延期，这个功能本身对用户已经有价值（找回宠物来源）；
- 它产出的数据结构（`pets`/`discoveries`/`planets`）正好是 Phase 2a 搜索的地基。

**明确不做（第一阶段）**

- 不生成宠物、不改 `Descriptors`、不改种子；
- 不做「按外观搜全宇宙」；
- 不打包任何游戏资产/上游数据；
- 不实现 seed→parts。

---

## 附录 A：本机实测数据（可复现）

只读脚本要点（不写入存档）：

```python
# 让 nms_save / nms_procgen 可导入（发布包里已内置）
from starforge.core import paths
paths.ensure_shipwright_importable()

# 读同伴
from nms_save import save as S
d = S.open_save(path).readable
pets = d["BaseContext"]["PlayerStateData"]["Pets"]

# 读动物发现
recs = d["DiscoveryManagerData"]["DiscoveryData-v1"]["Store"]["Record"]
animals = [r["DD"] for r in recs if (r.get("DD") or {}).get("DT") == "Animal"]

# UA → 符文
from nms_procgen.locate import describe
describe(ua)  # -> {galaxy, galaxy_name, coords, glyphs, ...}
```

实测输出（聚合）：

- 同伴 29；角色 22；来源星球 19；银河 3；部件 116；末尾数字 27/29。
- 动物发现 699；4 值 476、5 值 223；`VP[0]/[2]/[3]` 跨星球重复 0。
- 16/29 同伴能在发现记录中命中同 `UA` 的种子包。

## 附录 B：参考链接

**上游仓库/工具**

- NMSCD Creature-Builder：<https://github.com/NMSCD/Creature-Builder>（无 LICENSE）
- 线上：<https://creature.nmscd.com>
- nmstoolkit：<https://github.com/pljeroen/nmstoolkit>（MIT；README 明确不做 seed-accurate）
- laanp NMS-Creature-Builder：<https://github.com/laanp/NMS-Creature-Builder>（归档）
- NMSE：<https://github.com/vectorcmdr/NMSE>（AGPL-3.0）
- MBINCompiler：<https://github.com/monkeyman192/MBINCompiler>（NOASSERTION）
- hgpaktool：<https://github.com/monkeyman192/hgpaktool>（MIT）
- NMSCE：<https://nmsce.com/>（fauna 搜索；数据未授权）

**文档/数据**

- libMBIN `GcCreatureData`：<https://monkeyman192.github.io/MBINCompiler/classes/gc/GcCreatureData>
- libMBIN `GcCreatureSpawnData`：<https://monkeyman192.github.io/MBINCompiler/classes/gc/GcCreatureSpawnData>
- libMBIN `GcResourceElement`：<https://monkeyman192.github.io/MBINCompiler/classes/gc/GcResourceElement>
- NMS Wiki Fauna / Genus（物种与行星的关系）：<https://nomanssky.fandom.com/wiki/Fauna>
- NMSSaveEditor issue #533（改宠物的实操与风险）：<https://github.com/goatfungus/NMSSaveEditor/issues/533>
- NMSSaveEditor 同伴编辑指南：<https://nmssaveeditor.net/guides/edit-companions-and-pets/>

**本仓库相关**

- `starforge/creature.py`、`app/widgets/pets_view.py`、`app/pages/fleet.py`
- `starforge/save/transaction.py`、`NMS-Shipwright/nms_save/extras.py`
- `starforge/gltf.py`、`starforge/render.py`、`starforge/preview.py`
- `docs/archive/CREATURE-MODELING-2026-11-18.md`（旧结论，需按本文 §3 Q5 复核）
- `handbook/06-PLAN-V4全量蓝图.md`（T8 背景）
