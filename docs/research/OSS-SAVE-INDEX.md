# 存档索引：发现 / 生物 / 飞船 / 工具

> **研究范围**：只读分析本机存档、项目现有代码、公开上游仓库的 README/文档/少量源码结构。
> 未启动游戏、未 attach 游戏进程、未改业务代码、未写存档。
>
> **脱敏约定**：本文不记录任何真实种子、坐标、星系名、玩家 ID 或存档绝对路径。
> 所有示例地址统一写成 `0x…` / `<UA>` / `<行星名>`；统计数字只保留聚合计数。
>
> **验证环境**：本机 `save.hg`（3.4 MB 量级，LZ4 分块容器）与另外 3 份玩家存档；
> 读取日期 2026-11-22。研究文档 `CREATURE-SEARCH.md` 成文于 2026-11-21，本文的
> 发现记录数比它多 30 条（玩家继续游玩导致），以本文实测为准并注明差异。
>
> **与同仓库研究的边界**：`OSS-PLANET-SEARCH.md` 已单独评估“只做行星筛选”的可行性
> （结论一致：`VP[1]` 可离线解群系/感染，星图新增页签）。本文把范围扩到
> **行星 + 野生生物 + 同伴 + 飞船 + 工具 + 基地/传送点**，并补上持久索引 schema、
> 增量策略与多实体查询。若只做行星筛选，可以不建库；要做跨实体检索，建议按本文建
> `discoveries.db`。

---

## 0. 结论先行

1. **最值得做的不是“再造一个 NomNom”，而是把存档里的发现记录变成可查询的本地索引。**
   本机存档已有 830 条行星发现、702 条动物发现、413 条星系发现；行星的群系与“感染”
   标志可以从 `DD.VP[1]` 离线解出，**不需要游戏进程、不需要 `NMS.exe`**。
   `nms-copilot` 已经证明这条路可行（MIT/Apache-2.0），但它没有做生物/飞船/工具。
2. **生物外观仍然不能离线复现。** `CREATURE-SEARCH.md` 的结论不变：野生生物的种子包绑定
   行星，外观由 `Descriptors[]` + 多个种子共同决定，社区也刻意不公开 seed→parts。
   我们能做的是：**已知同伴按描述符筛**、**野生生物按行星/种子/原型筛**，不能承诺
   “按头/腿/颜色搜全宇宙”。
3. **同伴、飞船、工具、货船、护卫舰、基地、传送点都在同一个 `PlayerStateData` 下**，
   适合同一张派生索引；飞船按 `(type, seed)` 去重，工具按 `seed`，行星按 `planet_ua`，
   野生动物按 `(planet_ua, creature_seed)`。
4. **建议独立一个 `discoveries.db`，不要塞进 `galaxy.db`。** `galaxy.db` 是“程序化扫描
   结果”，`discoveries.db` 是“玩家存档快照”；两者生命周期、重建条件、字段语义都不同。
   查询时用 `ATTACH` 或服务层二次查询做关联。
5. **增量策略以“内容哈希 + 版本戳”为准，mtime/size 只做快路径。** 单份存档 3k 行量级，
   全量替换一次 <100 ms，比做逐行 diff 更稳；`extractor_ver` 变化时强制重建。
6. **UI 不新开页。** 星图页新增一个“我的发现”页签（与现有 5 个页签并列），舰队页的
   同伴/飞船/工具 tab 加筛选条，首页加统计卡，设置页加“本地索引”管理；详情面板复用
   现有符文面板与传送按钮。
7. **许可必须分清**：`libNOM.io`、`NomNom` 都是 **GPL-3.0**（不是 MIT），`NMSE` 是
   **AGPL-3.0** 且含“游戏派生”代码；只能读文档/功能，不能复制代码。`nms-copilot` 是
   MIT/Apache-2.0，思路可对照，但本项目按“不复制上游代码/数据”执行。
8. **最值得先做的查询场景**：
   - ① 我还没到过的茂盛/无哨兵行星（发现记录 + `VisitedSystems`）；
   - ② 我的同伴来自哪颗行星 + 那颗行星还有哪些动物种子；
   - ③ 我拥有的飞船按类型/种子/部件筛；
   - ④ 星系详情 + CSV 导出（给 Excel / 社区分享）。

---

## 1. 存档里与“发现”相关的结构

### 1.1 顶层结构（本机实测）

```
save.hg（LZ4 分块，magic 0xFEEDA1E5）
└─ JSON
   ├─ Version / Platform
   ├─ BaseContext
   │  ├─ GameMode
   │  ├─ PlayerStateData        （本机 263 个键）
   │  └─ SpawnStateData
   ├─ DiscoveryManagerData
   │  └─ DiscoveryData-v1
   │      ├─ Store.Record[]     （本机 3,240 条发现）
   │      ├─ Available[]        （本机 10 条“最近”）
   │      ├─ Enqueued / ReserveManaged / ReserveStore
   ├─ ActiveContext
   ├─ CommonStateData
   └─ ExpeditionContext
```

`accountdata.hg` 是明文 JSON，但不是玩家存档（没有 `ShipOwnership`）；
`mf_*.hg` 是 432 字节清单。这两类在 `save/library.py` 里已经被正确拒绝，索引层不需要再处理。

（来源：`starforge/save/library.py:1-7,60-99`；本机 `open_save` 只读实测。）

### 1.2 发现记录：`DiscoveryManagerData.DiscoveryData-v1.Store.Record[]`

单条记录的结构：

```json
{
  "DD":  {"DT": "<类型>", "UA": <int 或 "0x…">, "VP": ["0x…", …]},
  "DM":  {"CN": "<玩家命名>"},          // 仅玩家改过名时存在
  "OWS": {"UID": "…", "USN": "…", "PTK": "…", "LID": "…", "TS": 0}
}
```

本机 3,240 条的分布与 `VP` 语义：

| `DT` | 条数 | `VP` 长度 | 字段语义（已核实/高置信） | 可索引内容 |
|---|---:|---|---|---|
| `Planet` | 830 | 2 | `VP[0]`=行星种子；`VP[1]` 低 16 位=群系枚举，bit 16=感染 | ✅ 群系、感染、种子 |
| `Animal` | 702 | 4 或 5 | `VP[0]`=CreatureSeed；`VP[1]`=角色/原型种子；`VP[2]`=SpeciesSeed；`VP[3]`=GenusSeed；`VP[4]`=疑似第二性别 | ✅ 种子/行星；❌ 外观 |
| `Flora` | 532 | 2 | `VP[0]` 种子、`VP[1]` 变体（未深挖） | 部分（种子/行星） |
| `Mineral` | 640 | 2 | `VP[0]` 种子、`VP[1]` 变体（未深挖） | 部分（种子/行星） |
| `SolarSystem` | 413 | 1 | 星系发现；`VP[0]` 疑为星系种子（索引不使用） | ✅ 名称、发现者、时间 |
| `Sector` | 60 | 2 | 星区 | 低价值 |
| `SpacePoi` | 39 | 1 | 兴趣点 | 低价值 |
| `Interactable` | 20 | 2 | 交互物 | 低价值 |
| `SpaceStation` | 4 | 0 | 空间站 | 低价值 |

**必须处理的五个细节：**

1. **`UA` 类型混用。** 本机 830 条行星记录里 623 条是 `"0x…"` 字符串、207 条是整数；
   动物记录同样是 427 字符串 / 275 整数。所有读取必须先做 `int(v,16)` / `int(v)` 归一化，
   否则位运算直接抛 `TypeError`（研究中实际踩到）。
2. **行星 `UA` 是完整 56 位地址（低 52 位系统地址 + 高 4 位行星序号）。**
   `planet_index = (ua >> 52) & 0xF`，`galaxy = (ua >> 32) & 0xFF`，
   `planet_ua & ~(0xF << 52)` 就是系统地址；
   本机 828/830 能对上一条 `SolarSystem` 记录（2 条孤立行星记录，需跳过并计数）。
3. **行星记录会重复。** 830 行 → 814 个唯一 `UA`。去重键用 `(UA, VP[0])` 仍是 814；
   合并时“后出现的非空字段覆盖先出现的”，原始记录保留在 `discovery_records`。
4. **`DM.CN` 很少。** 本机只有 76 条带名字：43 Planet、19 SolarSystem、12 Animal、
   1 Flora、1 Sector。**绝大多数行星没有存档内名字**，UI 不能编造；可用地址/符文/
   “未命名”占位。`nms-copilot` 也是只把 `DM.CN` 当显式名字（来源：
   `crates/nms-graph/src/extract.rs` 的 `extract_discovery_names_from_validated`）。
5. **`OWS.UID` 不是记录主键。** 830 条行星只有 79 个不同 `UID`（账号级标识）；
   去重不要用它，否则会把整份存档折成几十条。

**行星群系 `VP[1]` 的位布局**（来源：nms-copilot `extract.rs` 的
`extract_biome_from_vp`；本机独立验证 830/830 都能解出 0–15 的枚举）：

```
flags = int(VP[1], 16) 或 int(VP[1])
biome_id = flags & 0xFFFF
infested = (flags >> 16) & 1
```

枚举顺序（与本机分布一致）：

| id | 群系 | id | 群系 |
|---:|---|---:|---|
| 0 | Lush | 8 | Red |
| 1 | Toxic | 9 | Green |
| 2 | Scorched | 10 | Blue |
| 3 | Radioactive | 11 | Test（跳过） |
| 4 | Frozen | 12 | Swamp |
| 5 | Barren | 13 | Lava |
| 6 | Dead | 14 | Waterworld |
| 7 | Weird | 15 | GasGiant |

本机 830 条行星的群系分布（只列计数，用于验证解析没有整列落空）：
Lush 271、Frozen 88、Scorched 75、Toxic 73、Radioactive 72、Weird 64、Barren 58、
Dead 41、Red 20、Blue 19、Swamp 18、Green 18、Lava 5、Waterworld 4、GasGiant 4；
感染 85 条。解析失败 0 条。

> ⚠️ 这个映射是社区从游戏数据反推的，跨版本可能变。索引层要保留 `biome_id` 原始值，
> 映射失败时写 `NULL` + `index_errors`，不要猜。
> 同仓库 `OSS-PLANET-SEARCH.md` 另做了 8/8 的离线 `systemgen` 抽样对照，结论一致；
> 但样本仍小，跨版本要重新验。

### 1.3 访问、位置、基地、传送、奇观

| 路径 | 本机规模 | 结构/语义 | 索引用途 |
|---|---:|---|---|
| `PlayerStateData.VisitedSystems[]` | 512 项 → 233 个唯一系统 | `X + Y<<12 + Z<<20 + Sys<<32`，**不含银河** | “我是否到过”的主要证据 |
| `PlayerStateData.UniverseAddress.GalacticAddress` | 1 | `VoxelX/Y/Z` + `SolarSystemIndex` + `PlanetIndex`，`RealityIndex`=银河 | 当前位置、距离基准 |
| `PlayerStateData.PersistentPlayerBases[]` | 48 | `GalacticAddress`（整数）、`Name`、`Position`、`RID`、`Owner.USN` | 基地索引、按基地找星系 |
| `PlayerStateData.TeleportEndpoints[]` | 203 | `UniverseAddress.GalacticAddress`（dict）、`Name`、`TeleporterType` | 传送点索引、常用目的地 |
| `PlayerStateData.SpacePoiDiscoveries[]` | 256 槽 / 75 有效 | `UA` + `PackedData0/1` | 兴趣点/“是否到过”辅助证据 |
| `PlayerStateData.WonderCreatureRecords[]` | 15 | `GenerationID=[bool, seed]`、`WonderStatValue` | 与动物发现记录交叉链接 |
| `PlayerStateData.WonderPlanetRecords[]` | 11 | `GenerationID=[bool, seed]`、`WonderStatValue` | 与行星记录交叉链接 |
| `PlayerStateData.PlanetSeeds[16]` / `PlanetPositions[16]` | 16 / 16 | 当前星系的 16 个行星槽种子/位置 | 补全“当前星系没有发现记录”的行星 |

关键事实：

- `VisitedSystems` 的 512 项去重后只有 233 个系统；与 413 条 `SolarSystem` 发现记录
  取交集是 181，并集 465。也就是说 **“到过”与“发现”不是一回事**：有 52 个系统到过
  但没有星系发现记录，也有 232 个系统是发现/扫描过但不在最近访问缓冲里。
- `VisitedSystems` 不存银河。`nms_procgen.locate.from_visited(v)` 能把项还原成
  “银河=0”的系统地址；要落到具体银河，必须用 `addr_key`（清掉 galaxy 位后的系统地址）
  去发现记录里匹配，匹配不到才退回“当前银河”并标记 `galaxy_inferred=1`。
- `SpacePoiDiscoveries` 的 75 个 `UA` 全部能对上一个 `SolarSystem` 记录，是干净的系统级证据。
- `Wonder*.GenerationID` 的第一位是布尔（本机全为 `true`），第二位才是种子/ID；
  读取时不要直接把整个数组当种子。
- 当前行星的 `creature_ids` / `fauna` 只能由 agent 实机读取（`GET /planet`），
  历史行星拿不到；索引把这类字段当“可选补全”，不作为真相来源。

（来源：`nms_procgen/locate.py` 的 `from_visited` / `save_known_systems` 文档；
`CREATURE-SEARCH.md §1.3`；本机只读统计。）

### 1.4 同伴、飞船、工具、货船、护卫舰

#### 同伴 `PlayerStateData.Pets[]`

本机 30 个槽位、29 只有效。现有 `starforge/creature.py` 已经展开得很完整：

| 字段 | 含义 | 现有代码 |
|---|---|---|
| `CreatureID` | 生物角色/物种 ID（带 `^`） | ✅ |
| `Descriptors[]` | 物理部件 ID 列表（末尾可能有 10 位唯一 ID） | ✅ |
| `CreatureSeed` / `CreatureSecondarySeed` | 主/次颜色纹理种子 | ✅ |
| `SpeciesSeed` / `GenusSeed` | 物种/属种子 | ✅ |
| `ColourBaseSeed` / `BoneScaleSeed` | 颜色基/骨骼缩放种子 | ✅ |
| `Scale` / `Biome` / `CreatureType` / `Predator` / `HasFur` | 体型/群系/类型/掠食/有毛 | ✅ |
| `UA` | 来源行星地址 | ✅ 解码为 galaxy/system/planet/glyphs |
| `Trust` / `Traits[]` / `Moods[]` / `BirthTime` | 信任/性格/情绪/出生时间 | ✅ 部分 |
| `CustomSpeciesName` | 玩家给“物种”起的名字 | ❌ 未读 |
| `SenderData`（`UID/USN/PTK/LID/TS`） | 共享/赠送来源 | ❌ 未读 |
| `AllowUnmodifiedReroll` / `EggModified` / `PetBattler*` | 重算/蛋/战斗 | ❌ 未读 |

**索引必须补的三个字段**：`CustomSpeciesName`、`SenderData.USN`（判断“别人送的宠物”，
不能把它的 `UA` 当 100% 可信来源）、`AllowUnmodifiedReroll`（提示可能被游戏重算）。

（来源：`starforge/creature.py:188-262`；`CREATURE-SEARCH.md §1.1`。）

#### 飞船 `PlayerStateData.ShipOwnership[]` / `ArchivedShipOwnership[]`

- 本机 `ShipOwnership` 12 个槽位，`nms_save.ships.list_ships()` 读出 9 艘非空。
- 每艘：`Name`、`Resource.Seed`（`[bool,"0x…"]`）、`Resource.Filename`、
  `Inventory.Class`、`Location`、`Inventory.BaseStatValues`。
- `nms_save` 已封装成 `Ship.index/name/filename/seed/is_procedural/category_guess/raw`；
  我们的 `ShipRef.from_save_ship()` 再补类型与统计。
- `ArchivedShipOwnership` 18 个槽位目前**完全没读**；如果要做“全部飞船”，
  必须把 `storage='archived'` 一起索引。

#### 多用途工具 `PlayerStateData.Multitools[]` / `ArchivedMultitools[]`

本机 6 + 18 个槽位。每项：`Name`、`Seed`、`Resource.Filename`、
`Store.Class.InventoryClass`、`Store.ValidSlotIndices`、`CustomisationData`、
`PrimaryMode/SecondaryMode`、`IsLarge`。`nms_save.extras.multitools()` 已经能给出
`index/name/seed/class/model/slots/active`，但**没有持久化索引**。

#### 货船 / 护卫舰 / 舰队

- `CurrentFreighter`：`Resource.Seed`、`Resource.Filename`、`Name`（实际名字在
  `PlayerFreighterName`），另有 3 个货船库存。
- `FleetFrigates[]` 30 项：`CustomName`、`FrigateClass`、`Race`、`Stats[11]`、
  `TraitIDs[]`、`HomeSystemSeed`、`ResourceSeed`、`ForcedTraitsSeed`、
  远征/损坏计数。
- `FreighterFleet[]` 8 项（编队），`SquadronPilots[]` 4 项。
- 现有 `nms_save.extras.frigates()` 可读，但只在舰队页临时展示，不落库。

### 1.5 我们现有代码读到了哪些、缺哪些

| 存档路径 | 现有入口 | 现状 | 缺口 |
|---|---|---|---|
| `Pets[]` | `starforge/creature.py:238-262` | ✅ 完整读取并解码 UA/符文 | `CustomSpeciesName`、`SenderData`、重算标记 |
| `ShipOwnership[]` | `save/library.py:113-158` → `nms_save.ships` | ✅ 9 艘，带类型/统计 | 不落库、不跨存档 |
| `ArchivedShipOwnership[]` | — | ❌ | 18 个归档槽 |
| `Multitools[]` / `ArchivedMultitools[]` | `nms_save.extras.multitools()` | ⚠️ 只在临时 UI 用 | 无索引、无归档 |
| `FleetFrigates[]` | `nms_save.extras.frigates()` | ⚠️ 舰队页临时展示 | 无索引、无远征状态 |
| `CurrentFreighter` | 舰队页展示 | ⚠️ 部分 | 无索引 |
| `DiscoveryManagerData.*` | — | ❌ **生产代码完全没读** | 行星/动物/星系发现 |
| `VisitedSystems[]` | `locate.save_known_systems()`（种子反查间接用） | ⚠️ | 没进索引，没和发现合并 |
| `PersistentPlayerBases[]` | — | ❌ | 基地索引 |
| `TeleportEndpoints[]` | agent 快照是另一套 | ⚠️ | 没进索引 |
| `SpacePoiDiscoveries[]` | — | ❌ | 兴趣点 |
| `Wonder*Records[]` | — | ❌ | 奇观 |
| `PlanetSeeds[]` / `PlanetPositions[]` | — | ❌ | 当前星系补全 |
| `DiscoveryData-v1.Available[]` | — | ❌ | 最近 10 条发现 |

**结论**：我们“读同伴/飞船”的链路是齐的，但**没有持久层**；“读发现记录”的链路
完全缺失。`CREATURE-SEARCH.md` 里的 699 条动物统计是研究脚本临时读的，不是产品能力。

现有 `library._SHIPS_CACHE` 的键是 `(路径, mtime, size)`（`save/library.py:27-33`），
这正是增量索引的雏形；把它从“进程内字典”升级为“SQLite 持久层”即可。

**`has_visited` 的口径**（写进服务层，不要每处各算一套）：

```
has_visited = 1
  if visits 里有 source ∈ {visited, current, base, teleport, poi}
```

`source='pet'`（同伴来源行星）只作“可能到过”的辅助证据，不单独置 `has_visited`：
共享宠物可能来自别人的星球（`SenderData` 非空时尤其如此）。

---

## 2. 开源项目对照与许可

### 2.1 总表

| 项目 | 许可（核实） | 它做了什么 | 我们能借鉴 | 不能做 |
|---|---|---|---|---|
| [libNOM.io](https://github.com/zencq/libNOM.io) | **GPL-3.0** | .NET 存档读写库；全平台容器、2001–2004 格式、JSONPath 取值/改值 | 平台/容器抽象、`LoadingStrategy`、按路径读写 JSON 的 API 形状 | 复制任何 C# 代码/测试/常量 |
| [NomNom](https://github.com/zencq/NomNom) | **GPL-3.0** | 图形化存档编辑器/管理器；备份恢复、槽位复制、JSON 导出、跨平台 | 功能清单、备份/恢复交互、JSON 编辑器组织 | 复制代码/界面/资源 |
| [NMSE](https://github.com/vectorcmdr/NMSE) | **AGPL-3.0** + 游戏派生部分 | 全功能编辑器；数据库搜索、发现/奇观编辑、宠物构建/战斗种子、护卫舰零件反查 | 功能清单、“无需载入存档的数据库搜索”这个产品点 | 复制代码；其 README 明确“游戏派生部分不供 wholesale reuse” |
| [nms-copilot](https://github.com/oxur/nms-copilot) | **MIT OR Apache-2.0** | Rust 存档解析 + 星系/行星/基地模型 + 查询/路线/导出/社区 CSV/MCP/实时监听 | 发现记录提取口径、缓存版本化、导出列、查询接口形状 | 本项目按“不复制代码/数据”执行；其 `mapping_mbincompiler.json` 来自 MBINCompiler，不能复制 |

### 2.2 libNOM.io（GPL-3.0，不是 MIT）

README 明确：支持 2001（Foundation 1.10–Prisms 3.53）、2002（含 Waypoint 扩展）、
2003（Worlds Part I 5.00–The Cursed 5.29）、2004（Worlds Part II 5.50+）；
按平台识别 Steam/GOG/PS4/Switch/Microsoft Store；提供 `PlatformCollection`、
`GetContainer(slot)`、`GetJsonValue<T>("PlayerStateData.…")`、`SetJsonValue(...)`。
它解决的是“**怎么安全地读写各平台存档**”，**没有索引/查询层**。

**许可结论**：GPL-3.0。我们是 MIT 项目，不能把它的代码、测试或大段注释搬进来；
它的 NuGet 包也不能作为依赖链进我们的发布物（否则整包应按 GPL 处理）。
只可阅读 README/公开 API 文档，字段路径属于事实信息。

### 2.3 NomNom（GPL-3.0）

定位是“最完整的存档编辑器”：管理器（自动备份/恢复、槽位复制/移动、JSON 导出）、
编辑器（货币/舰队/库存/外观/知识/原始 JSON）。它依赖 `libNOM.io`、`libNOM.collect`、
`libNOM.map`。它**没有“按条件搜发现”**，也没有本地索引。

**许可结论**：GPL-3.0，同上。可以借鉴“备份/恢复 + 原始 JSON 兜底”的产品思路，
不能复制代码或图标资源。

### 2.4 NMSE（AGPL-3.0 + 游戏派生）

README 的功能清单里，与本研究最相关的有：

- **Database Search panel**：不载入存档也能查数据库；
- **Discoveries / Wonders / Fossils / Raw materials** 的目录完成度工具；
- **Companion editing / Custom creature builder / Pet battle seed search**；
- **Corvette part reverse lookup**、**Starship customisation**；
- 多语言（含简体中文）。

README 同时写明：部分代码是从游戏反编译/重实现，“Those parts are game-derived,
are not covered by the project's AGPL licence, and are not intended for wholesale reuse
or redistribution in other tools.”

**许可结论**：AGPL-3.0 本身已经不能进 MIT 项目；游戏派生部分更是明确不建议复用。
只把它当**功能对照表**，不复制代码、数据、常量表。

### 2.5 nms-copilot（MIT OR Apache-2.0）

这是与本任务最接近的实现，值得逐项对照：

- **架构**：`nms-save`（原生解析 LZ4 + key mapping）→ `nms-graph`（星系/行星/基地模型，
  petgraph + R-tree）→ `nms-query`（find/route/show/stats）→ CLI/REPL/MCP；
  `nms-watch` 监听文件，`nms-cache` 做版本化磁盘缓存。
- **查询**：按群系、感染、命名、发现者、距离、`--nearest`、`--from <基地>`；
  路线规划（nearest-neighbor / 2-opt）；导出 JSON/CSV；社区 CSV 导入。
- **地址**：`LY_PER_VOXEL = 400.0`，距离=体素欧氏距离×400；同一体素不同 SSI 用
  “不确定度”常数（来源：`crates/nms-core/src/address.rs`；我们未复验）。
- **发现提取**：`SolarSystem` 行提供名称/发现者/时间；`Planet` 行提供
  `VP[0]` 种子、`VP[1]` 群系/感染；`DM.CN` 提供显式名字；孤立行星行可以创建系统。
- **缓存**：schema=4、semantic=6；缓存必须比源存档新；旧版本直接重建；
  缓存只存派生数据，不是备份。
- **不做的**：没有同伴/飞船/工具/货船/护卫舰索引；没有“按生物外观搜”。

**许可结论**：MIT/Apache-2.0 与我们的 MIT 兼容，法律上可以复用；但本项目约定
“不复制上游代码/数据”，所以只采用**字段语义与产品形状**，实现自己写。
如果未来要复用某个函数，必须在 `THIRD_PARTY_NOTICES.md` 加注、保留版权头、锁定 commit。

---

## 3. 本地索引设计

### 3.1 设计原则

1. **派生数据、可重建、绝不回写存档。** 删除 `discoveries.db` 不应影响任何用户数据；
   收藏夹/历史仍在 `~/.starforge/favorites.json` / `history.json`，不能塞进索引。
2. **只索引“能回答查询”的字段，其余进 raw JSON。** 游戏更新加字段时不用迁移；
   与 `galaxy.py` 的 `planet_list` JSON 兜底是同一思路。
3. **以存档文件为快照单位。** 一个 `save_id` 对应一份 `.hg`；多份存档（自动/手动/
   不同周目）各自一份，查询时可选“只看当前”或“合并所有”。
4. **地址是主键，名称只是属性。** 没名字就显示“未命名”+符文；不猜、不编。
5. **不确定的东西显式标记。** `galaxy_inferred`、`source`、`index_errors`、
   `extractor_ver` 都要能解释“这条数据是怎么来的”。
6. **不把 `OWS.UID` 当主键，不把 `VisitedSystems` 当全量历史。** 前者是账号标识，
   后者是最近 512 条环形缓冲。

### 3.2 放哪里、和 `galaxy.db` 的关系

```
~/.starforge/cache/
├─ galaxy.db          # 现有：程序化扫描结果（systems/planets）
├─ discoveries.db     # 新增：存档派生索引（只读快照）
└─ gamecache/         # 现有：游戏数据缓存
```

| 维度 | `galaxy.db` | `discoveries.db` |
|---|---|---|
| 数据来源 | `systemgen` 扫描（需要 `NMS.exe`） | 玩家 `.hg`（只需 `nms_save`） |
| 语义 | “这个地址生成出来是什么” | “玩家实际记录/到过什么” |
| 重建条件 | 扫描任务 | 存档内容哈希变化 / 提取器版本变化 |
| 主键 | `systems.ua` | `(save_id, system_ua)` |
| 典型查询 | 找未扫描的乐土 | 找“我已发现但没去过”的行星 |

**关联方式**（二选一，Phase 1 推荐 A）：

- A. 服务层二次查询：先查 `discoveries.db`，再用 `ua` 批量查 `galaxy.db`；
- B. SQL `ATTACH DATABASE '<cache>/galaxy.db' AS g`，直接 `LEFT JOIN g.systems`。

不要现在把两张表合并：`galaxy.db` 的 `SCHEMA` 没有版本戳，合并会牵动扫描任务与导出。

### 3.3 SQL DDL 草案

> 约定：地址一律存大写十六进制字符串。
> 系统地址 `system_ua` 为 52 位（planet 位清零）`0x%013X`；
> `addr_key` 是把 `system_ua` 的 galaxy 字节清零后的值（仍 `0x%013X`），用于跨银河匹配；
> 完整行星地址 `planet_ua` 为 56 位 `0x%014X`。
> 所有时间戳为 Unix 秒；缺失写 `NULL`，不要写 0 冒充。

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

-- 一份 .hg 一行；save_id 稳定于路径，content_hash 决定是否重建
CREATE TABLE IF NOT EXISTS saves (
    save_id       TEXT PRIMARY KEY,          -- sha1(realpath)[:16]
    path          TEXT NOT NULL UNIQUE,
    file_name     TEXT NOT NULL,
    slot          INTEGER,                   -- save.hg→1, save2.hg→2…
    size          INTEGER NOT NULL,
    mtime_ns      INTEGER NOT NULL,
    content_hash  TEXT NOT NULL,             -- sha256(原始 .hg)
    game_version  INTEGER,                   -- Version
    platform      TEXT,                      -- Platform
    game_mode     TEXT,                      -- BaseContext.GameMode
    extractor_ver INTEGER NOT NULL,
    indexed_at    INTEGER NOT NULL,
    missing       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_saves_hash ON saves(content_hash);

-- 星系：发现记录 + 访问缓冲 + 基地/传送/POI 的并集
CREATE TABLE IF NOT EXISTS systems (
    save_id         TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    system_ua       TEXT NOT NULL,           -- 0x%013X，含 galaxy
    addr_key        TEXT NOT NULL,           -- 清掉 galaxy 位，跨银河匹配
    galaxy          INTEGER NOT NULL,
    galaxy_inferred INTEGER NOT NULL DEFAULT 0,
    name            TEXT,                    -- DM.CN（仅命名时）
    discoverer      TEXT,                    -- OWS.USN
    discovered_at   INTEGER,                 -- OWS.TS
    planet_count    INTEGER NOT NULL DEFAULT 0,
    biome_mask      INTEGER NOT NULL DEFAULT 0,  -- bit(biome_id)
    has_infested    INTEGER NOT NULL DEFAULT 0,
    has_discovery   INTEGER NOT NULL DEFAULT 0,
    has_visited     INTEGER NOT NULL DEFAULT 0,
    has_base        INTEGER NOT NULL DEFAULT 0,
    has_teleport    INTEGER NOT NULL DEFAULT 0,
    has_poi         INTEGER NOT NULL DEFAULT 0,
    has_scan        INTEGER NOT NULL DEFAULT 0,
    first_seen_at   INTEGER,
    last_seen_at    INTEGER,
    PRIMARY KEY (save_id, system_ua)
);
CREATE INDEX IF NOT EXISTS idx_systems_addr    ON systems(save_id, addr_key);
CREATE INDEX IF NOT EXISTS idx_systems_visited ON systems(save_id, has_visited, galaxy);
CREATE INDEX IF NOT EXISTS idx_systems_biome   ON systems(save_id, biome_mask);

-- 行星：发现记录的 Planet 行；source 说明是“记录”“当前星系种子”还是“扫描”
CREATE TABLE IF NOT EXISTS planets (
    save_id      TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    planet_ua    TEXT NOT NULL,              -- 0x%014X（56 位，含行星位）
    system_ua    TEXT NOT NULL,
    planet_index INTEGER NOT NULL,
    galaxy       INTEGER NOT NULL,
    seed         TEXT,                       -- VP[0]
    biome_id     INTEGER,                    -- VP[1] & 0xFFFF
    biome        TEXT,                       -- 映射后的名字；失败为 NULL
    infested     INTEGER NOT NULL DEFAULT 0,
    name         TEXT,                       -- DM.CN
    discovered_at INTEGER,
    source       TEXT NOT NULL DEFAULT 'discovery',  -- discovery|planet_seed|scan
    PRIMARY KEY (save_id, system_ua, planet_index),
    UNIQUE (save_id, planet_ua)
);
CREATE INDEX IF NOT EXISTS idx_planets_biome   ON planets(save_id, biome_id, infested);
CREATE INDEX IF NOT EXISTS idx_planets_system  ON planets(save_id, system_ua);

-- 原始发现记录：审计/导出/未来字段的兜底
CREATE TABLE IF NOT EXISTS discovery_records (
    save_id    TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    record_id  TEXT NOT NULL,                -- sha1(dt|ua|vp0)[:16]
    dt         TEXT NOT NULL,
    ua         TEXT,                         -- 原始 UA（0x%014X，便于审计）
    planet_ua  TEXT,
    system_ua  TEXT,
    seed0      TEXT,
    vp         TEXT NOT NULL,                -- JSON 数组，原样保留
    name       TEXT,
    discoverer TEXT,
    ts         INTEGER,
    recent     INTEGER NOT NULL DEFAULT 0,   -- 来自 Available[]
    PRIMARY KEY (save_id, record_id)
);
CREATE INDEX IF NOT EXISTS idx_records_dt ON discovery_records(save_id, dt);

-- 野生动物：没有外观，只有种子包 + 行星
CREATE TABLE IF NOT EXISTS creatures (
    save_id       TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    record_id     TEXT NOT NULL,
    planet_ua     TEXT NOT NULL,
    system_ua     TEXT NOT NULL,
    creature_seed TEXT NOT NULL,             -- VP[0]
    role_seed     TEXT,                      -- VP[1]（原型/角色级，语义未定）
    species_seed  TEXT,                      -- VP[2]
    genus_seed    TEXT,                      -- VP[3]
    variant_seed  TEXT,                      -- VP[4]（仅部分记录）
    name          TEXT,                      -- DM.CN（很少）
    discovered_at INTEGER,
    PRIMARY KEY (save_id, record_id)
);
CREATE INDEX IF NOT EXISTS idx_creatures_seed    ON creatures(save_id, creature_seed);
CREATE INDEX IF NOT EXISTS idx_creatures_species ON creatures(save_id, species_seed);
CREATE INDEX IF NOT EXISTS idx_creatures_planet  ON creatures(save_id, planet_ua);

-- 同伴：当前存档的 Pets[]，按槽位唯一
CREATE TABLE IF NOT EXISTS companions (
    save_id         TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    slot            INTEGER NOT NULL,
    creature_id     TEXT NOT NULL,
    custom_name     TEXT,
    custom_species_name TEXT,
    creature_type   TEXT,
    biome           TEXT,
    predator        INTEGER NOT NULL DEFAULT 0,
    scale           REAL,
    has_fur         INTEGER NOT NULL DEFAULT 0,
    descriptors     TEXT NOT NULL,           -- JSON 数组
    descriptor_groups TEXT,                  -- JSON {组:[部件]}
    unique_id       TEXT,                    -- 末尾 8–12 位数字
    creature_seed   TEXT,
    creature_secondary_seed TEXT,
    species_seed    TEXT,
    genus_seed      TEXT,
    colour_base_seed TEXT,
    bone_scale_seed TEXT,
    ua              TEXT,
    system_ua       TEXT,
    planet_index    INTEGER,
    galaxy          INTEGER,
    glyphs          TEXT,
    sender_uid      TEXT,
    sender_usn      TEXT,
    trust           REAL,
    birth_time      INTEGER,
    species_key     TEXT,                    -- CreatureID|SpeciesSeed|GenusSeed
    species_key_source TEXT,
    PRIMARY KEY (save_id, slot)
);
CREATE INDEX IF NOT EXISTS idx_companions_species ON companions(save_id, creature_id, species_seed, genus_seed);
CREATE INDEX IF NOT EXISTS idx_companions_origin  ON companions(save_id, system_ua);

-- 同伴部件：把 JSON 拆成可索引行
CREATE TABLE IF NOT EXISTS companion_parts (
    save_id TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    slot    INTEGER NOT NULL,
    part    TEXT NOT NULL,
    grp     TEXT NOT NULL,                   -- BODY/HEAD/TAIL/MESH/…
    rare    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (save_id, slot, part)
);
CREATE INDEX IF NOT EXISTS idx_cparts_part ON companion_parts(part);
CREATE INDEX IF NOT EXISTS idx_cparts_grp  ON companion_parts(grp);

-- 飞船：owned / archived / current
CREATE TABLE IF NOT EXISTS ships (
    save_id    TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    storage    TEXT NOT NULL DEFAULT 'owned',   -- owned|archived|current
    slot       INTEGER NOT NULL,
    name       TEXT,
    type       TEXT,
    seed       TEXT NOT NULL,
    model      TEXT,
    procedural INTEGER NOT NULL DEFAULT 1,
    ship_class TEXT,
    stats      TEXT,                            -- JSON
    location   INTEGER,
    parts      TEXT,                            -- JSON|null（需要游戏数据时惰性计算）
    PRIMARY KEY (save_id, storage, slot)
);
CREATE INDEX IF NOT EXISTS idx_ships_seed ON ships(seed);
CREATE INDEX IF NOT EXISTS idx_ships_type ON ships(save_id, type);

-- 飞船部件：只有能拿到游戏数据时才填
CREATE TABLE IF NOT EXISTS ship_parts (
    save_id TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    storage TEXT NOT NULL,
    slot    INTEGER NOT NULL,
    part    TEXT NOT NULL,
    grp     TEXT NOT NULL,
    PRIMARY KEY (save_id, storage, slot, part)
);
CREATE INDEX IF NOT EXISTS idx_sparts_part ON ship_parts(part);

-- 多用途工具
CREATE TABLE IF NOT EXISTS multitools (
    save_id      TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    storage      TEXT NOT NULL DEFAULT 'owned',  -- owned|archived
    slot         INTEGER NOT NULL,
    name         TEXT,
    seed         TEXT,
    model        TEXT,
    mt_class     TEXT,
    slots        INTEGER,
    active       INTEGER NOT NULL DEFAULT 0,
    customisation TEXT,                          -- JSON
    PRIMARY KEY (save_id, storage, slot)
);
CREATE INDEX IF NOT EXISTS idx_tools_seed ON multitools(seed);

-- 护卫舰
CREATE TABLE IF NOT EXISTS frigates (
    save_id          TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    idx              INTEGER NOT NULL,
    name             TEXT,
    frigate_class    TEXT,
    race             TEXT,
    stats            TEXT,                       -- JSON
    traits           TEXT,                       -- JSON
    home_system_seed TEXT,
    resource_seed    TEXT,
    expeditions      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (save_id, idx)
);

-- 基地
CREATE TABLE IF NOT EXISTS bases (
    save_id      TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    rid          TEXT NOT NULL,
    name         TEXT,
    system_ua    TEXT NOT NULL,
    planet_index INTEGER,
    galaxy       INTEGER,
    position     TEXT,                           -- JSON [x,y,z]
    owner_usn    TEXT,
    base_type    TEXT,
    updated_at   INTEGER,
    PRIMARY KEY (save_id, rid)
);
CREATE INDEX IF NOT EXISTS idx_bases_system ON bases(save_id, system_ua);

-- 传送点
CREATE TABLE IF NOT EXISTS teleports (
    save_id      TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    idx          INTEGER NOT NULL,
    name         TEXT,
    system_ua    TEXT NOT NULL,
    planet_index INTEGER,
    galaxy       INTEGER,
    kind         TEXT,
    favourite    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (save_id, idx)
);
CREATE INDEX IF NOT EXISTS idx_teleports_system ON teleports(save_id, system_ua);

-- 奇观（与发现记录用种子交叉链接）
CREATE TABLE IF NOT EXISTS wonders (
    save_id TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    kind    TEXT NOT NULL,       -- planet|creature|flora|mineral|custom|weird_base|treasure
    gen_id  TEXT NOT NULL,
    stat    REAL,
    seen    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (save_id, kind, gen_id)
);

-- “我是怎么知道这个系统的”：一个系统可以有多条证据
CREATE TABLE IF NOT EXISTS visits (
    save_id    TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    system_ua  TEXT NOT NULL,
    galaxy     INTEGER NOT NULL,
    source     TEXT NOT NULL,    -- visited|discovery|planet|base|teleport|poi|current|pet|planet_seed
    first_seen INTEGER,
    last_seen  INTEGER,
    PRIMARY KEY (save_id, system_ua, source)
);

-- 解析失败/跳过计数：界面要能说“跳过了 2 条坏记录”
CREATE TABLE IF NOT EXISTS index_errors (
    save_id TEXT NOT NULL REFERENCES saves(save_id) ON DELETE CASCADE,
    scope   TEXT NOT NULL,
    detail  TEXT NOT NULL,
    count   INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (save_id, scope, detail)
);
```

**DDL 说明：**

- `ships.seed NOT NULL`：空槽不写行；`seed=0x0` 的占位船也不写，避免污染“我的船”。
- `planets` 用 `(save_id, system_ua, planet_index)` 做主键，`planet_ua` 做唯一约束；
  这样即使某条记录的 `UA` 行星位损坏，也能用 `(system, index)` 落位。
- `companion_parts` / `ship_parts` 是为了让“按部件筛”走索引，而不是 `LIKE '%_HEAD_%'`。
- `discovery_records.vp` 保留原始 JSON，未来游戏加 `VP[5]` 或改语义时不用改表。
- 所有 `save_id` 外键都 `ON DELETE CASCADE`；删除一份存档索引只需删 `saves` 一行。

### 3.4 去重键与合并策略

| 实体 | 自然键 | 跨存档/跨来源去重 | 合并策略 |
|---|---|---|---|
| 存档 | `save_id = sha1(realpath)[:16]` | 路径 | 内容哈希变→重建该 `save_id` |
| 系统 | `(galaxy, x, y, z, system_index)` = `system_ua` | `addr_key`（清掉 galaxy 位） | 发现记录优先；visited 无银河时按 `addr_key` 匹配 |
| 行星 | `planet_ua`；回退 `(system_ua, planet_index)` | `planet_ua` | 重复 Planet 行：**后出现的非空字段覆盖**，raw 保留 |
| 野生动物 | `(planet_ua, creature_seed)` | `creature_seed` + `planet_ua` | 同种子同星球视为同一只 |
| 同伴 | `(save_id, slot)` | `(creature_id, creature_seed, species_seed, genus_seed)` | 跨存档只做“相似匹配”，不强制唯一 |
| 飞船 | `(save_id, storage, slot)` | `(type, seed)` | 同种子同类型视为同一外观 |
| 工具 | `(save_id, storage, slot)` | `seed` | 同上 |
| 护卫舰 | `(save_id, idx)` | `(name, home_system_seed)` 仅参考 | 不跨存档合并 |
| 基地 | `(save_id, rid)` | `rid` | 同名不同 `rid` 不合并 |
| 传送点 | `(save_id, idx)` | `(system_ua, name)` 仅参考 | 不跨存档合并 |
| 奇观 | `(save_id, kind, gen_id)` | `(kind, gen_id)` | 同一种子视为同一奇观 |

**为什么不把 `PlanetSeed` 当主键**：本机 830 条行星记录只有 814 个唯一 `UA`，
但 `VP[0]`（行星种子）也可能在重复记录里出现；真正稳定的是地址。`PlanetSeed` 只做
查询条件，不做主键。同理，`CreatureSeed` 只在“同一行星”内唯一，不能单独当全局主键。

`addr_key` 可能在不同银河各命中一个系统（同一 x/y/z/system 在不同银河是合法的）；
匹配 `VisitedSystems` 时优先“当前银河”，其次“本存档已发现的银河”，都命中不了才新建
`galaxy_inferred=1` 的壳。

### 3.5 增量更新（mtime / hash / 版本戳）

```
index(path):
  stat → (size, mtime_ns)
  if saves 行存在 且 size/mtime 相同 且 extractor_ver 相同:
      return {"skipped": True, "reason": "mtime+size"}
  digest = sha256(path.read_bytes())
  if saves 行存在 且 content_hash 相同 且 extractor_ver 相同:
      UPDATE saves SET indexed_at=now, mtime_ns=…
      return {"skipped": True, "reason": "hash"}
  data = extract(path)                      # 只 open_save 一次
  BEGIN IMMEDIATE
    DELETE FROM systems/planets/... WHERE save_id=?
    INSERT saves + 所有派生行
    INSERT index_errors（坏记录计数）
  COMMIT
  return {"skipped": False, "counts": {...}}
```

要点：

1. **快路径只看 `size + mtime_ns`**，命中就完全不读文件；`mtime_ns` 用 `st_mtime_ns`，
   不要用秒级 `mtime`。
2. **慢路径用 `sha256(原始 .hg)`**。3.4 MB 文件约几毫秒；哈希相同说明“游戏只是重写了
   容器/时间戳”，不需要重解析。
3. **`extractor_ver` 是提取器版本号**（不是游戏版本）。字段语义改了、映射表改了、
   去重策略改了，就 +1；启动时发现 `saves.extractor_ver != CURRENT` 就重建该存档。
4. **单存档全量替换**：3k 行量级，单事务 `DELETE + INSERT` 比逐行 diff 简单且不会留孤儿。
   如果将来单存档超过 10 万行，再改为“按 `record_id` upsert + 删除缺失”。
5. **失败回滚**：解析/写入任何异常都 `ROLLBACK`，旧快照保留；`index_errors` 也只在
   成功事务里写，避免半成品。
6. **并发**：`PRAGMA journal_mode=WAL`、`busy_timeout=5000`；Python 侧用
   `threading.RLock` 包住“检查 + 重建”，避免 Qt 线程与 Web 线程同时 ingest。
7. **清理**：`prune` 只删 `missing=1` 且超过 N 天的 `saves` 行；不要在游戏运行时
   自动删文件索引（用户可能只是临时移走存档）。
8. **多存档合并查询**：默认 `save_id = 当前选中存档`；UI 提供“合并所有存档”开关，
   查询时 `GROUP BY planet_ua` 取 `MAX(discovered_at)`，并保留 `save_id` 来源。

---

## 4. 查询场景（SQL + 服务接口草案）

> 下面 SQL 都假设 `:save` 是当前 `save_id`；可选条件用 `:x IS NULL OR …` 写法，
> 服务层按传入的 filters 动态拼 WHERE（不要真的把 `NULL` 绑定成字符串）。
> `status` 的语义见 4.4。

### 4.1 按星球条件筛（群系 / 感染 / 命名 / 到过 / 发现者）

```sql
SELECT
    p.planet_ua,
    p.planet_index,
    p.name            AS planet_name,
    p.biome,
    p.infested,
    p.seed            AS planet_seed,
    s.system_ua,
    s.name            AS system_name,
    s.discoverer,
    s.galaxy,
    s.has_visited,
    s.has_discovery,
    CASE
      WHEN s.has_visited = 1 AND p.source = 'discovery' THEN '到过并记录'
      WHEN p.source = 'discovery'                       THEN '记录过（可能远程扫描）'
      WHEN s.has_visited = 1                            THEN '只到过星系'
      ELSE '未到过'
    END AS visit_status
FROM planets p
JOIN systems s
  ON s.save_id = p.save_id AND s.system_ua = p.system_ua
WHERE p.save_id = :save
  AND (:biome    IS NULL OR p.biome_id = :biome)
  AND (:infested IS NULL OR p.infested = :infested)
  AND (:named    IS NULL OR (:named = 1 AND p.name IS NOT NULL AND p.name <> ''))
  AND (:visited  IS NULL OR (:visited = 1 AND s.has_visited = 1))
  AND (:system   IS NULL OR s.system_ua = :system)
ORDER BY s.has_visited DESC, p.biome_id, p.planet_index
LIMIT :limit OFFSET :offset;
```

服务接口：

```python
# starforge/services/discoveries.py
def find_planets(
    *, save: str | None = None,
    biome: str | int | None = None,
    infested: bool | None = None,
    named: bool | None = None,
    visited: bool | None = None,
    system: str | None = None,
    limit: int = 100, offset: int = 0,
) -> dict:
    """→ {save, filters, count, rows, store, notes}"""
```

`biome` 同时接受中文/英文/枚举 id；服务层用 `zh.biome_label` 做展示，SQL 仍用 id。
返回行里带 `glyphs`（由 `planet_ua` + `planet_index` 生成，复用 `glyphs.glyphs_for_ua`）
和 `coords`（`unpack_ua`），UI 不再自己算。

### 4.2 按生物特征筛

#### (a) 同伴：按描述符/类型/群系/体型

```sql
-- 想要同时包含两个部件（AND）
SELECT c.*
FROM companions c
JOIN companion_parts p
  ON p.save_id = c.save_id AND p.slot = c.slot
WHERE c.save_id = :save
  AND (:type    IS NULL OR c.creature_type = :type)
  AND (:biome   IS NULL OR c.biome = :biome)
  AND (:predator IS NULL OR c.predator = :predator)
  AND (:creature_id IS NULL OR c.creature_id = :creature_id)
  AND (:min_scale IS NULL OR c.scale >= :min_scale)
  AND p.part IN (:part1, :part2)
GROUP BY c.save_id, c.slot
HAVING COUNT(DISTINCT p.part) = 2;

-- 只要任意一个 _HEAD_ 部件（OR / 组前缀）
SELECT DISTINCT c.*
FROM companions c
JOIN companion_parts p
  ON p.save_id = c.save_id AND p.slot = c.slot
WHERE c.save_id = :save AND p.grp = 'HEAD';

-- 排除某个部件
SELECT c.*
FROM companions c
WHERE c.save_id = :save
  AND NOT EXISTS (
    SELECT 1 FROM companion_parts p
    WHERE p.save_id = c.save_id AND p.slot = c.slot
      AND p.part = :avoid_part
  );
```

服务接口：

```python
def find_companions(
    *, save: str | None = None,
    creature_id: str | None = None,
    creature_type: str | None = None,
    biome: str | None = None,
    parts: list[str] | None = None,        # 全部命中
    any_parts: list[str] | None = None,    # 任意命中
    avoid_parts: list[str] | None = None,
    min_scale: float | None = None,
    predator: bool | None = None,
    limit: int = 100,
) -> dict:
    """同伴是唯一能按“外观部件”可靠筛的生物。"""
```

#### (b) 野生生物：按种子 / 行星 / 原型

```sql
-- 精确找某只野生生物（种子包来自同伴或发现记录）
SELECT cr.*, p.biome, p.name AS planet_name, s.name AS system_name
FROM creatures cr
JOIN planets p
  ON p.save_id = cr.save_id AND p.planet_ua = cr.planet_ua
JOIN systems s
  ON s.save_id = cr.save_id AND s.system_ua = cr.system_ua
WHERE cr.save_id = :save
  AND cr.creature_seed = :creature_seed
  AND (:planet IS NULL OR cr.planet_ua = :planet);

-- 按行星列出全部动物（做“这颗星球有什么”）
SELECT cr.creature_seed, cr.species_seed, cr.genus_seed, cr.name
FROM creatures cr
WHERE cr.save_id = :save AND cr.planet_ua = :planet
ORDER BY cr.creature_seed;

-- 同一“原型/角色”聚类（VP[1]，语义未验证，只作线索）
SELECT role_seed, COUNT(*) AS n, COUNT(DISTINCT planet_ua) AS planets
FROM creatures
WHERE save_id = :save AND role_seed IS NOT NULL
GROUP BY role_seed
ORDER BY n DESC;
```

**能力边界（必须写进 UI 文案）**：

- 野生生物没有 `Descriptors[]`，**不能**按“头/腿/颜色”筛；
- `role_seed` 只是“原型级”聚类，不能当物种学分类；
- 找野生生物的正确终点是**行星地址 → 12 位符文 → 传送**，不是“给一个种子刷出来”；
- 同伴的种子包能在本存档发现记录中命中时，命中的 `UA` 应与同伴 `UA` 一致
  （本机 16/29；`CREATURE-SEARCH.md §1.2`）。索引要提供这个交叉验证，
  但不能把 `UA` 当 100% 可信（共享宠物可能写 0）。

### 4.3 按飞船部件 / 种子筛

```sql
-- 种子精确查（拥有 + 归档）
SELECT *
FROM ships
WHERE save_id = :save AND seed = :seed;

-- 类型 + 部件（需要 ship_parts 已填充）
SELECT s.*
FROM ships s
JOIN ship_parts p
  ON p.save_id = s.save_id AND p.storage = s.storage AND p.slot = s.slot
WHERE s.save_id = :save
  AND s.type = :type
  AND p.part IN (:part1, :part2)
GROUP BY s.save_id, s.storage, s.slot
HAVING COUNT(DISTINCT p.part) = 2;
```

部件填充策略：

- `nms_procgen.fastsearch.generate(seed, ship)` 能在有游戏数据时给出
  `[(group, part), …]`；这是**本地计算**，不需要游戏进程。
- Phase 1 不填 `ship_parts`（避免把“需要游戏数据”变成索引前置条件）；
- Phase 2 在用户打开“按部件筛”时惰性计算并写回 `ships.parts` / `ship_parts`；
- 固定模型（非 `_PROC`）不计算部件，`procedural=0`，UI 明确“外观不由种子决定”。

服务接口：

```python
def find_ships(
    *, save: str | None = None,
    type: str | None = None,
    seed: str | None = None,
    parts: list[str] | None = None,
    storage: str = "owned",     # owned|archived|all
    limit: int = 100,
) -> dict
```

“找同部件的新种子”不查索引，直接把条件预填到飞船实验室的搜索框
（`starforge/search.py` 已有 `SearchQuery`）。

### 4.4 按“我是否到过”筛

先明确三个不同概念，UI 不能混：

| 状态 | 证据 | 含义 |
|---|---|---|
| **到过系统** | `VisitedSystems` / `SpacePoi` / 基地 / 传送点 / 当前系统 | 玩家至少进过这个星系 |
| **记录过行星** | `Planet` 发现行 | 玩家扫描/登陆并记录了这个行星（可能是远程扫描） |
| **发现过星系** | `SolarSystem` 发现行 | 玩家是命名/记录者（或至少触发过发现） |

```sql
-- 到过的系统
SELECT s.*
FROM systems s
WHERE s.save_id = :save AND s.has_visited = 1
ORDER BY s.last_seen_at DESC;

-- 到过、但没有任何行星记录的系统（“我去过但没细看”）
SELECT s.*
FROM systems s
WHERE s.save_id = :save
  AND s.has_visited = 1
  AND NOT EXISTS (
    SELECT 1 FROM planets p
    WHERE p.save_id = s.save_id AND p.system_ua = s.system_ua
      AND p.source = 'discovery'
  );

-- 记录过、但不在最近访问缓冲里的行星（“很久以前发现的”）
SELECT p.*, s.name AS system_name
FROM planets p
JOIN systems s ON s.save_id = p.save_id AND s.system_ua = p.system_ua
WHERE p.save_id = :save
  AND p.source = 'discovery'
  AND s.has_visited = 0;

-- 证据来源统计（给详情页解释“为什么说我来过”）
SELECT source, COUNT(*) AS n
FROM visits
WHERE save_id = :save
GROUP BY source
ORDER BY n DESC;
```

服务接口：

```python
def find_systems(
    *, save: str | None = None,
    visited: bool | None = None,
    discovered: bool | None = None,
    galaxy: int | None = None,
    limit: int = 200,
) -> dict

def system_detail(*, save: str | None = None, system_ua: str) -> dict:
    """→ {system, planets, creatures, companions, bases, teleports, evidence, glyphs}"""
```

`system_detail` 是 UI 详情面板的唯一入口；它把“这个星系有什么”一次查完，
避免界面 N+1 查询。

### 4.5 星系详情

```sql
SELECT * FROM systems
WHERE save_id = :save AND system_ua = :system;

SELECT * FROM planets
WHERE save_id = :save AND system_ua = :system
ORDER BY planet_index;

SELECT * FROM creatures
WHERE save_id = :save AND system_ua = :system;

SELECT * FROM companions
WHERE save_id = :save AND system_ua = :system;

SELECT * FROM bases
WHERE save_id = :save AND system_ua = :system;

SELECT * FROM teleports
WHERE save_id = :save AND system_ua = :system;

SELECT * FROM visits
WHERE save_id = :save AND system_ua = :system;
```

### 4.6 导出

行星 CSV（对齐 nms-copilot 的列，再加我们的字段）：

```
planet_name, system_name, biome, infested, planet_index, planet_seed,
portal_glyphs, coords_x, coords_y, coords_z, galaxy,
discoverer, visit_status, discovered_at
```

同伴 CSV：

```
slot, name, custom_species_name, creature_id, type, biome, scale,
predator, has_fur, descriptors, creature_seed, species_seed, genus_seed,
origin_system, origin_planet_index, origin_glyphs, sender_usn
```

飞船 CSV：

```
storage, slot, name, type, seed, class, procedural, parts,
damage, shield, hyperdrive, agility
```

实现建议：复用 `web/routes.py:403-439` 的 `csv.writer` + `Response` 形状；
Excel 兼容可在文本前加 UTF-8 BOM（`\ufeff`），现有 galaxy 导出没加，新导出可选。

---

## 5. 服务 / API / CLI 草案

### 5.1 模块划分

```
starforge/
├─ save/discoveries.py        # 纯读取/解析：records → 结构化 dict
├─ discoveries_index.py       # SQLite：DDL、ingest、query、prune
├─ services/discoveries.py    # 业务门面：参数校验、save 解析、中文标签
├─ web/routes.py              # /api/discoveries/*
└─ __main__.py                # `index` 子命令
```

与现有分层保持一致：

- `save/discoveries.py` 只依赖 `nms_save` 与 `glyphs`，不碰 Qt/Flask；
- `discoveries_index.py` 只碰 SQLite，不解析存档；
- `services/discoveries.py` 是 UI/HTTP 的唯一入口（参考 `services/save_edit.py` 的写法）；
- 索引重建是**只读存档**，不调用 `settings.require_write()`，也不启动游戏进程；
  但索引文件本身必须用临时文件 + `os.replace` 原子落盘，失败不能留下半个 `discoveries.db`。

### 5.2 `save/discoveries.py`

```python
DISCOVERY_PATH = ("DiscoveryManagerData", "DiscoveryData-v1", "Store", "Record")
AVAILABLE_PATH = ("DiscoveryManagerData", "DiscoveryData-v1", "Available")

def read_raw(readable: dict) -> dict:
    """→ {records, available, visited, current, bases, teleports, wonders, ...}"""

def normalize_ua(v) -> int | None:
    """int / '0x…' / 十进制字符串 → int；非法返回 None（不猜）。"""

def planet_from_record(rec: dict) -> dict | None:
    """Planet 行 → {planet_ua, system_ua, planet_index, galaxy, seed, biome_id, infested, name}"""

def animal_from_record(rec: dict) -> dict | None:
    """Animal 行 → {creature_seed, role_seed, species_seed, genus_seed, variant_seed, …}"""

def system_from_record(rec: dict) -> dict | None: ...
def companion_from_pet(pet: dict, slot: int) -> dict | None: ...   # 复用 creature.companion_entry
def ship_from_save(sh, storage: str) -> dict: ...                  # 复用 ShipRef
def multitool_from_save(m, index: int, storage: str, active: int) -> dict: ...
def frigate_from_save(f, index: int) -> dict: ...
def base_from_save(b) -> dict: ...
def teleport_from_save(t, index: int) -> dict: ...
def wonder_from_save(kind: str, row: dict) -> dict: ...
```

要求：

- 所有 `UA`/种子先归一化；非法值返回 `None` 并累加 `errors[scope] += 1`；
- 不打印真实种子/坐标到日志（只打印计数与槽位）；
- `companion_from_pet` 直接复用 `creature.companion_entry()`，避免两套解析；
- `ship_from_save` 复用 `ShipRef.from_save_ship()`，保证和搜索/预览一致；
- **孤立行星**：`Planet` 行的 `system_ua` 若没有对应 `SolarSystem` 行，创建 `systems` 壳
  （`has_discovery=0`，名称/发现者留空），不要因为缺系统行丢掉行星；
- **重复行星**：`record_id = sha1(dt|ua|vp0)` 把完全重复的记录折叠；`planet_ua` 相同但
  `VP` 不同的保留多行，实体行按“后出现的非空字段覆盖”。

### 5.3 `discoveries_index.py`

```python
CURRENT_EXTRACTOR = 1

class DiscoveriesStore:
    def __init__(self, path: str | None = None): ...
    def save_id(self, path: Path) -> str: ...
    def should_reindex(self, path: Path, force: bool = False) -> tuple[bool, str]: ...
    def ingest(self, path: Path, *, force: bool = False) -> dict: ...
    def stats(self, save_id: str | None = None) -> dict: ...
    def prune(self, missing_days: int = 30) -> dict: ...
    def query_planets(self, save_id: str, **f) -> list[dict]: ...
    def query_companions(self, save_id: str, **f) -> list[dict]: ...
    def query_wild(self, save_id: str, **f) -> list[dict]: ...
    def query_ships(self, save_id: str, **f) -> list[dict]: ...
    def query_tools(self, save_id: str, **f) -> list[dict]: ...
    def system_detail(self, save_id: str, system_ua: str) -> dict: ...
```

`ingest()` 返回：

```python
{
  "save_id": "...", "path": "<存档>", "skipped": False, "reason": "content-changed",
  "counts": {"systems": 465, "planets": 830, "animals": 702,
              "companions": 29, "ships": 9, "tools": 6, "frigates": 30,
              "bases": 48, "teleports": 203, "wonders": 78},
  "errors": {"planet_ua": 2},
  "seconds": 0.08,
}
```

### 5.4 REST

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/discoveries/index` | body `{path?, force?}`；同步执行（单存档 <200 ms），返回 counts |
| `GET` | `/api/discoveries/stats?save=` | 索引统计、最后更新时间、错误计数 |
| `GET` | `/api/discoveries/planets?save=&biome=&infested=&named=&visited=&system=&limit=&offset=` | 4.1 |
| `GET` | `/api/discoveries/companions?save=&type=&biome=&parts=a,b&any_parts=&avoid_parts=&min_scale=` | 4.2a |
| `GET` | `/api/discoveries/creatures?save=&seed=&species=&planet=&biome=` | 4.2b |
| `GET` | `/api/discoveries/ships?save=&type=&seed=&parts=&storage=` | 4.3 |
| `GET` | `/api/discoveries/tools?save=&seed=&class=&storage=` | 工具 |
| `GET` | `/api/discoveries/system?save=&ua=` | 4.5 |
| `GET` | `/api/discoveries/export.csv?kind=planets&…` | 4.6 |

约定：

- `save` 可传路径或 `save_id`；不传用 `library.default_save_path()`；
- 所有错误走现有 `BadRequest` / `SaveFormatError` / `SaveNotFound`，由 `web/app.py`
  统一转成 `{ok:false,error:{kind,message}}`；
- `limit` 上限 500（与 `galaxy.query` 一致），默认 100；
- 索引未建立时返回 `{ok:true, empty:true, hint:"先执行 POST /api/discoveries/index"}`，
  不要伪装成空结果。

### 5.5 CLI

```bash
python -m starforge index --saves-dir "<存档目录>"          # 索引全部玩家存档
python -m starforge index --save "<save.hg>" --rebuild      # 强制重建一份
python -m starforge index --stats                            # 查看索引大小/计数
python -m starforge index --prune                            # 清理 30 天未见的存档
```

输出只打印计数与耗时，不打印种子/坐标。

### 5.6 测试

- **合成存档 fixture**：手写一个最小 JSON（2 个系统、3 个行星、2 个动物、1 只同伴、
  2 艘船、1 个工具、1 个访问系统），**不含真实种子/坐标**；`open_save` 用假
  `readable` 注入，或直接把 JSON 喂给 `extract(readable)`。
- 断言：计数、群系映射、感染位、UA 混合类型、孤立行星跳过、重复行星去重、
  第二次 ingest `skipped`、`extractor_ver` 变化后重建。
- 本机集成测试只做**只读**断言（计数范围），不把真实数据写入仓库/CI。

---

## 6. UI 组织：不新开页，接进现有 7 页

现有导航（`starforge/app/shell.py:47-66`）：

```
探索：概览 / 飞船实验室 / 设计器
资料：我的船队 / 星图
连接：游戏内代理 / 设置
```

### 6.1 页面级改动

| 页面 | 改动 | 不做什么 |
|---|---|---|
| **概览** `home` | 增加“发现统计”卡：行星/星系/动物/同伴/飞船计数、Top 群系、最近 10 条发现；点击带筛选跳到星图 | 不堆新图表、不做全屏 dashboard |
| **星图** `systems` | 新增一个 **“我的发现”** 页签：筛选条 + 表格 + 右侧详情；保留现有“银河索引”页签（程序化扫描）不动 | 不新建独立“发现”页 |
| **我的船队** `mine` | 同伴 tab 加筛选条（类型/群系/部件组/体型/来源）；飞船 tab 加类型/种子/部件筛选；工具 tab 加种子/等级筛选；详情加“来源行星”链接 | 不复制一套新的列表组件 |
| **飞船实验室** `search` | 结果卡增加“在存档中找同部件”按钮，预填搜索条件 | 不改搜索算法 |
| **设计器** `designer` | 无改动（最多“保存到收藏”已有） | 不塞索引 |
| **游戏内代理** `live` | 当前行星卡增加“查看该星系发现”链接，跳到星图详情 | Phase 2 先在页面刷新时读索引，不做常驻文件监听 |
| **设置** `settings` | 新增“本地索引”区：路径、大小、计数、最后更新、重建/清理按钮、“合并所有存档”开关 | 不放调试用原始 JSON |

### 6.2 星图“我的发现”tab 布局

```
┌ 筛选条 ────────────────────────────────────────────────────────────┐
│ 群系 [全部▾]  感染 [全部▾]  状态 [全部▾]  □ 只看命名  □ 只看到过   │
│ 星系 [____________]  排序 [最近发现▾]  [查询] [导出 CSV] [刷新]   │
├ 表格 ──────────────────────────────────────────────┬ 详情 ────────┤
│ 行星 | 星系 | 群系 | 感染 | 状态 | 符文 | 发现者  │ <行星名>     │
│ …                                                  │ 符文图       │
│                                                    │ 坐标/种子    │
│                                                    │ 动物种子列表 │
│                                                    │ 基地/传送点  │
│                                                    │ [复制符文]   │
│                                                    │ [传送到这里] │
└────────────────────────────────────────────────────┴──────────────┘
```

- 表格只放 6–7 列，避免横向滚动；种子/坐标放详情。
- “状态”列用颜色/徽标：到过并记录（绿）、记录过（蓝）、只到过星系（灰）、未到过（无色）。
- 详情面板复用 `starforge/app/widgets/planet_dossier.py` 与 `glyphs.panel_png()`；
  传送按钮复用 `pages/galaxy.py` 的 `_warp_target_for` / `_warp_confirm_text` 逻辑。
- 双击行 = 打开详情；“复制符文”写剪贴板；“导出”只导出当前筛选结果。

### 6.3 舰队页筛选条

- 同伴：`类型`（Prey/Predator/…）、`群系`、`部件组`（BODY/HEAD/TAIL/…）、
  `最小体型`、`来源银河`、`□ 有共享来源`；表格增加“来源星系/符文”“发现记录命中”。
- 飞船：`类型`、`种子`（精确/前缀）、`部件`（多选）、`□ 包含归档`；
  结果行保留现有“预览/送进游戏/收藏”。
- 工具：`等级`、`种子`、`□ 包含归档`、`□ 只看当前`。
- 所有筛选都在本地索引上做，不触发行星生成器/游戏进程。

### 6.4 导出入口

- 星图“我的发现”工具栏：`导出 CSV`（当前筛选）。
- 舰队页同伴/飞船 tab：`导出 CSV`（当前列表）。
- 设置页：`导出全部索引为 JSON`（带 `format/version/extractor_ver`，便于排障/迁移）。
- 导出文件名带时间戳，内容含真实种子/坐标，导出前弹一次确认（“文件包含你的坐标与种子”）。

---

## 7. 分阶段落地

### Phase 1：只读索引（无 UI，2–3 天）

**目标**：能在一台没有安装游戏的机器上，从 `.hg` 建出可查询的索引。

任务：

1. `save/discoveries.py`：发现记录/访问/基地/传送/奇观/同伴/飞船/工具/护卫舰解析。
2. `discoveries_index.py`：DDL、`ingest`、`stats`、`prune`、基础 `query_*`。
3. `services/discoveries.py`：参数校验 + 中文标签 + `system_detail`。
4. `web/routes.py`：stats/planets/companions/creatures/ships/system/export。
5. `__main__.py`：`index` 子命令。
6. 测试：合成 fixture + 本机只读计数。

**验收**：

- 本机 4 份玩家存档都能索引；`save.hg` 计数与 1.2/1.3 一致（允许 ± 玩家继续游玩）；
- 第二次运行同一文件返回 `skipped: true`；
- 改一个字节/强制 `--rebuild` 后计数一致；
- 没有游戏目录时 `system.available() == False`，索引仍可用；
- 坏记录（2 条孤立行星）不导致整份失败，`index_errors` 有计数；
- 日志不含真实种子/坐标。

### Phase 2：筛选 UI（2–3 天）

**目标**：用户能在现有页面里完成 4 个查询场景，不需要命令行。

任务：

1. 星图新增“我的发现”页签 + 筛选条 + 详情面板 + 跳转。
2. 舰队页同伴/飞船/工具筛选条；同伴“来源行星”跳转。
3. 首页统计卡 + 最近发现。
4. 设置页“本地索引”区。
5. 懒加载部件（`ship_parts`）与“在存档中找同部件”。

**验收**：

- 组合筛选（群系+感染+到过+命名）返回正确；清空筛选恢复全量；
- 1000 行以内查询 <200 ms（本机 3k 行远低于此）；
- 空态/未建索引/存档损坏都有明确文案，不显示假数据；
- 详情面板的“传送到这里”复用现有确认流程，不新增写路径；
- 同伴“来源行星”能跳到星图并选中对应系统。

### Phase 3：导出 / 分享（2 天）

**目标**：把索引结果变成可带走的东西，但不做社区数据库。

任务：

1. CSV/JSON 导出（行星/同伴/飞船/工具），列固定、带版本号。
2. `nsd1:` 分享码（行星：glyphs + biome + seed；同伴：宠物 JSON 的只读子集）。
3. 可选：社区 CSV 导入（`system_name,portal_glyphs,galaxy,biome`），
   带 `source` 标签、去重、默认不覆盖“个人发现”。
4. 可选：距离/最近排序（`LY_PER_VOXEL=400`，需先在本机复核）。

**验收**：

- 导出文件可被 Excel 打开（UTF-8 BOM 可选），空结果输出表头；
- 分享码解码后通过 `ShipRef`/字段校验，坏码给可读错误；
- 导入不持久化到存档，只进索引；重复行计入 `skipped`；
- 导出前有“包含真实坐标/种子”的确认。

---

## 8. 与 nms-copilot 的差异

### 8.1 功能矩阵

| 能力 | nms-copilot | starforge 现状 | 结论 |
|---|---|---|---|
| 原生 `.hg` 解析 | ✅ Rust 自研 | ✅ `nms_save`（Shipwright） | 已有，不重复 |
| 行星发现索引（群系/感染/名称/发现者） | ✅ | ❌ 只有程序化扫描索引 | **首要补齐** |
| 地址/符文/坐标 | ✅ | ✅ `glyphs.py` / `locate` | 已有 |
| 距离/最近排序 | ✅ `LY_PER_VOXEL=400` | ❌ | Phase 3 可选 |
| 路线规划（NN/2-opt） | ✅ | ❌ | 不做；我们做单点传送 |
| 基地索引 | ✅ | 读得到但不索引 | 索引里加 `bases` |
| 传送点索引 | 部分 | 读得到但不索引 | 索引里加 `teleports` |
| 多存档 | ✅ 15 slots | ⚠️ `scan_dir` 只列不索引 | 按 `save_id` 索引 |
| 实时监听 + 缓存 | ✅ watcher + 版本化 cache | ⚠️ 内存 `_SHIPS_CACHE` | Phase 2 轮询，Phase 3 再评估 |
| 导出 JSON/CSV | ✅ 行星 | ⚠️ 只有 `galaxy.db` CSV | 扩到行星/同伴/飞船 |
| 社区 CSV 导入 | ✅ | ❌ | Phase 3 可选 |
| MCP server | ✅ | ❌（HTTP API + agent） | 不做 |
| 同伴索引 | ❌ | ✅ 读 `Pets[]` | **我们的差异点** |
| 飞船索引/部件 | ❌ | ✅ 搜索 + 存档读取 | **我们的差异点** |
| 工具/货船/护卫舰 | ❌ | ⚠️ UI 部分展示 | 索引里补齐 |
| 中文 UI | ❌ | ✅ | 保持 |
| 生物外观筛选 | ❌（明确不做） | ❌（明确不做） | 一致，不承诺 |

### 8.2 可直接对照的功能清单（来自 nms-copilot README/docs）

- `find --biome/--infested/--named/--discoverer/--within/--nearest/--from`
- `route --biome --algo nn|2opt --warp-range`
- `show system <id>` / `show base <name>`
- `stats --biomes`
- `export --format json|csv`
- `import community_data.csv --source`
- `saves` / `--slot` / 多账号
- `where_am_i` / `nms://player/location`
- 缓存 schema/semantic 版本、缓存必须比源存档新
- `last` / `map` / `galaxy` 视图（REPL 专属，我们不需要）

### 8.3 我们缺的（按优先级）

1. 发现记录解析与索引（P0）；
2. 多存档 `save_id` + 增量（P0）；
3. 行星筛选 UI（P1）；
4. 导出（P1）；
5. 距离/最近（P2，可选）；
6. 社区导入（P2，可选，注意授权）；
7. 实时监听（P3，可选）。

---

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 游戏更新改 `VP` 语义/新增 DT | 群系整列错/空 | 保留 `discovery_records.vp` 原始 JSON；`biome_id` 先落原始值；映射失败写 `NULL` + `index_errors`；`extractor_ver` 版本化 |
| `UA` 混合类型/孤立记录 | 解析异常/计数偏差 | 统一 `normalize_ua`；非法跳过并计数；2 条孤立行星不阻断 |
| `VisitedSystems` 不含银河 | “到过”误判到别的银河 | 用 `addr_key` 匹配发现记录；匹配不到标 `galaxy_inferred=1`；UI 显示“银河按当前推断” |
| 行星记录重复 | 行星数偏大/名字被覆盖 | 自然键 `(system_ua, planet_index)`；`planet_ua` 唯一；后出现的非空字段覆盖；raw 全保留 |
| 名称缺失 | UI 看起来“全是空” | 显示“未命名”+符文/地址；不生成假名；命名筛选用 `DM.CN` |
| 同伴外观不可复现 | 用户期待“按外观搜野生” | UI 明确“只能按已知描述符筛同伴”；野生只按行星/种子/原型；不发布 seed→parts |
| `UA` 被共享宠物写 0 | 来源行星错误 | 交叉验证发现记录；`SenderData` 非空时标“共享来源”；不把 `UA=0` 当有效 |
| 索引含真实种子/坐标 | 隐私/分享风险 | 只存本地 `~/.starforge/cache`；不遥测；导出前确认；设置页可清除 |
| SQLite 并发/OneDrive | `database is locked` / WAL 失败 | WAL + `busy_timeout` + 进程内锁；网络盘回退 `journal_mode=DELETE` 并给可读错误 |
| 许可见解污染 | MIT 项目被迫 GPL/AGPL | 只读 GPL/AGPL 文档；不复制代码/测试/常量；nms-copilot 也只取思路；必要时加 `THIRD_PARTY_NOTICES` |
| 社区数据授权 | 不能分发 NMSCE 数据 | 不内置；只支持用户自己导入 CSV；不代理其 Firestore/API |
| 游戏运行时读存档 | 读到半写文件 | 只读 + LZ4 头校验；失败保留旧快照；UI 提示“游戏正在保存，稍后重试”；不自动写回 |

---

## 10. 未验证 / 待实机

1. `VP[1]` 群系映射跨版本是否稳定（本机 build 已验，旧/新版本未验）。
2. `VisitedSystems` 的 512 项是否随版本变化；是否有“到过但不在缓冲”的更长历史。
3. `PlanetSeeds[16]` / `PlanetPositions[16]` 的槽位与 `planet_index` 是否一一对应。
4. `Wonder*.GenerationID[1]` 与发现记录种子的对应关系（本机只做了存在性检查）。
5. `Pets[].SenderData` 在共享宠物上的填充率；`UA=0` 的比例。
6. `LY_PER_VOXEL=400` 是否与当前版本一致（nms-copilot 的标定，我们未复验）。
7. `Available[]` 的 10 条是否总是“最近发现”，是否会与 `Store.Record` 重复。
8. 多存档（自动/手动）是否共享同一发现记录；合并查询是否需要“同周目”判断。

---

## 附录 A：字段路径 → 索引列速查

| 存档路径 | 索引表.列 |
|---|---|
| `Version` | `saves.game_version` |
| `Platform` | `saves.platform` |
| `BaseContext.GameMode` | `saves.game_mode` |
| `PlayerStateData.UniverseAddress.GalacticAddress` | `visits.source='current'` → `systems.has_visited` |
| `PlayerStateData.VisitedSystems[]` | `visits.source='visited'` → `systems.has_visited` |
| `PlayerStateData.Pets[]` | `companions` + `companion_parts` |
| `PlayerStateData.ShipOwnership[]` | `ships.storage='owned'` |
| `PlayerStateData.ArchivedShipOwnership[]` | `ships.storage='archived'` |
| `PlayerStateData.Multitools[]` | `multitools.storage='owned'` |
| `PlayerStateData.ArchivedMultitools[]` | `multitools.storage='archived'` |
| `PlayerStateData.FleetFrigates[]` | `frigates` |
| `PlayerStateData.CurrentFreighter` | `ships.storage='current'`（或单独 freighter 表） |
| `PlayerStateData.PersistentPlayerBases[]` | `bases` |
| `PlayerStateData.TeleportEndpoints[]` | `teleports` |
| `PlayerStateData.SpacePoiDiscoveries[]` | `visits.source='poi'` |
| `PlayerStateData.Wonder*Records[]` | `wonders` |
| `PlayerStateData.PlanetSeeds[]` | `planets.source='planet_seed'` |
| `DiscoveryManagerData.DiscoveryData-v1.Store.Record[]` | `discovery_records` + `systems`/`planets`/`creatures` |
| `DiscoveryManagerData.DiscoveryData-v1.Available[]` | `discovery_records.recent=1` |
| `DD.DT` | `discovery_records.dt` |
| `DD.UA` | `system_ua` / `planet_ua` / `record.ua` |
| `DD.VP[0]` | `planets.seed` / `creatures.creature_seed` / `records.seed0` |
| `DD.VP[1]`（Planet） | `planets.biome_id` + `planets.infested` |
| `DD.VP[2..4]`（Animal） | `creatures.species_seed` / `genus_seed` / `variant_seed` |
| `DM.CN` | `systems.name` / `planets.name` / `creatures.name` |
| `OWS.USN` | `systems.discoverer` / `discovery_records.discoverer` |
| `OWS.TS` | `systems.discovered_at` / `discovery_records.ts` |

## 附录 B：来源

**本机/项目内**

- `starforge/save/library.py`（存档分类、`open_ships`、`_SHIPS_CACHE`）
- `starforge/save/extras.py`（库存/知识/任务/奖励；写事务）
- `starforge/services/save_edit.py`（货币/船名/涂装；写前写后校验）
- `starforge/creature.py`（`Pets[]` 解析、UA→origin/glyphs、角色表）
- `starforge/galaxy.py`（`galaxy.db` 的 SQLite 模式与查询）
- `starforge/search.py`（种子搜索、部件校验、涂装过滤）
- `starforge/glyphs.py`（UA→12 位符文、位段拆分）
- `starforge/app/shell.py`（7 页导航）
- `starforge/app/pages/galaxy.py`（星图 tab、筛选、传送）
- `starforge/app/pages/fleet.py`（舰队页 tab）
- `starforge/web/routes.py`（`/galaxy/query`、`/galaxy/export.csv` 的响应形状）
- `docs/research/CREATURE-SEARCH.md`（生物种子绑定行星、外观不可复现、许可对照）
- `docs/research/OSS-PLANET-SEARCH.md`（行星筛选的独立研究；群系/感染/距离/星图页签）
- `docs/research/FEATURE-GAPS.md`（存档列表/传送快照的 UI 缺口）

**上游（2026-11-22 访问）**

- libNOM.io README：<https://github.com/zencq/libNOM.io>（GPL-3.0；格式 2001–2004；
  `PlatformCollection` / `GetJsonValue` / `SetJsonValue`）
- NomNom README：<https://github.com/zencq/NomNom>（GPL-3.0；管理器/编辑器/备份）
- NMSE README：<https://github.com/vectorcmdr/NMSE>（AGPL-3.0；Database Search、
  Discoveries/Wonders、Companion、Corvette part reverse lookup）
- nms-copilot README：<https://github.com/oxur/nms-copilot>（MIT OR Apache-2.0；
  crates、find/route/export/import、live/cache）
- nms-copilot `docs/data-interchange.md`、`docs/exploration.md`、`docs/live-atlas.md`
- nms-copilot `crates/nms-graph/src/extract.rs`（`VP[1]` 群系位布局、`DM.CN` 名称、
  SolarSystem 元数据、孤立行星处理）
- nms-copilot `crates/nms-core/src/address.rs`（`LY_PER_VOXEL=400.0`、距离/符文布局）
- MBINCompiler：<https://github.com/monkeyman192/MBINCompiler>（NOASSERTION；只读文档，
  不复制 mapping 数据）

---

## 附：最值得先做的三个查询（给实现排期）

1. **`find_planets(biome="Lush", infested=False, visited=False)`**
   —— “我还没去过的乐土”，直接对应玩家最有价值的决策；只依赖发现记录 + VisitedSystems，
   不需要游戏进程。
2. **`system_detail(companion.system_ua)` + `find_wild(planet=companion.ua)`**
   —— “我的同伴来自哪颗星球，那里还有什么动物”，把已有 `Pets[]` 解析与发现记录连起来，
   是别的编辑器没有的差异化能力。
3. **`find_ships(type=..., seed=..., parts=[...])`**
   —— “我拥有的船里，哪些是这种部件组合”，把现有搜索/预览能力变成可检索资产。
