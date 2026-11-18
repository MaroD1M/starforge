# 游戏内扫描可行性：星球矿物 / 动植物 / 附近传送门·古遗迹·货船·飞船

> 研究日期：2026-11-18  
> 范围：只读研究与路线判断，不改代码。结论基于本机 NMSpy 类型定义、`starforge` 现有 agent、NMS.py/Gagarin/SSH/NMSCoordinates/NMS Companion 的行为与代码/文档，以及本地 `NMS存档/save.hg` 的真实解码结果。
>
> 一句话结论：**“当前星球摘要 + 已发现记录 + 当前已存在 marker”可以走只读；‘当前星球所有物种’需要读 `CreatureRoles/SpawnData` 并实机校准；‘附近未发现的传送门/古遗迹’和‘附近动态货船/飞船’没有可直接读的全局列表，必须进程内定位实体或调用扫描事件；真正的 portal warp 与写发现列表都不是现在能假装完成的。**

---

## 0. 判定口径与总表

本文使用四档判定：

| 标记 | 含义 |
|---|---|
| ✅ 可只读 | 现有类型/结构直接可读，最多补字段和 UI，不需要调用游戏函数 |
| 🟡 需实现 | 结构已定位，但需要新代码、偏移校准或数据交叉验证；失败可降级 |
| 🔴 需进程内函数/实机校准 | 必须调用游戏函数、hook 或遍历引擎实体；版本敏感，可能崩溃 |
| ⛔ 不可做 | 当前数据源/接口不具备，或不能在不伪造的前提下完成 |

### 0.1 能力总表

| 能力 | 判定 | 关键数据源 | 现在能不能说“完成” |
|---|---|---|---|
| 读当前星球资源摘要（资源名、常见/稀有/罕见物质、额外资源提示） | ✅ | `cGcPlanetData.CommonSubstanceID/RareSubstanceID/UncommonSubstanceID/ExtraResourceHints`、`cGcPlanetInfo.Resources` | 能读；UI 尚未完整呈现，需实机对照 |
| 读当前星球生物描述/植物描述 | ✅ | `cGcPlanetInfo.Fauna/Flora/PlanetDescription` | 能读；只是描述，不是物种清单 |
| 读当前星球 `CreatureIDs` | ✅ | `cGcPlanetData.CreatureIDs` | 能读；是否等于“全部物种”待校准 |
| 列出当前星球所有物种（含未发现） | 🟡/🔴 | `cGcPlanetData.GenerationData.CreatureRoles.AvailableRoles`、`cGcPlanetData.SpawnData.Creatures` | 不能直接宣称完成；需读全表并与游戏内物种数对照 |
| 列出当前星球所有植物物种 | 🔴 | 没有 `FloraIDs`；只能从 `SpawnData.Objects/SelectableObjects` 或扫描记录推断 | 不能宣称完成 |
| 列出已发现的动物/植物/矿物 | ✅ | 存档 `DiscoveryManagerData.DiscoveryData-v1.Store.Record[]`（`DD.DT=Animal/Flora/Mineral`） | 能读；只有已发现，且没有物种中文名/位置 |
| 读附近已存在的 marker（含传送门/建筑/飞船/货船类别） | 🟡 | `cGcSimulation.mScanManager.mMarkerList.maMarkerObjects` | 结构已定位，需实机校准与过滤 |
| 找附近“未发现”的传送门/古遗迹/建筑 | 🔴 | `cGcScanEvent`/`cGcScanEventManager`/`cGcBuilding` 实体；NMSpy 没有现成列表 | 不能只读完成；需要扫描事件或实体遍历 |
| 读本星系空间站/Atlas/黑洞/SpacePoi 的地图对象 | 🟡 | `cGcSolarSystem.mSolarSystemMap.maAssociatedMapObjects` | 可读；需校准对象数量与坐标单位 |
| 读附近动态货船/NPC 飞船 | 🔴 | 没有全局实例列表；`SystemShips` 只是预载配置 | 不能完成 |
| 读自己拥有的飞船/货船/传送终点 | ✅ | `player_state.mShipResources`、`maTeleportEndpoints`、存档 `ShipOwnership` | 能读；不是“附近” |
| 游戏内扫描条立即完成 | ✅（UI 效果）/🟡 | hook `cGcBinoculars.UpdateScanBarProgress` | 能拉满进度条；不写发现，不等于发现 |
| 把物种写进发现列表（`scan.discover`） | 🔴 | `cGcDiscoveryManager.SubmitDiscoveryData` + 完整 `cGcDiscoveryData` | 不能；当前 offset/结构未校准 |
| 真正 portal warp（`cGcPortalComponent.WarpPlayer`） | 🔴 | 活的 `cGcPortalComponent` 指针 + `mPortalData.mTargetUA/mbActive` | 不能；需要实机捕获真实组件并验证落点 |
| 写玩家位置 + `APPLOCALLOAD`（现有 teleport） | 🟡（能试，不是 portal） | `player_state.mLocation` + `GcApplication.StateChange` | 不能称为“传送门效果”；需快照/回滚/落点校验 |

---

## 1. 当前 starforge agent 的真实状态

### 1.1 现有端点

`starforge/starforge/agent/starforge_agent.py` 现在暴露：

| 端点 | 类型 | 实际行为 |
|---|---|---|
| `GET /hello` | 读 | 报告 `player/system/planet/planet.scan/ships/teleport/teleport.portal/scan/scan.discover/scan.instant/restore` 能力 |
| `GET /player` | 读 | `player_state.mLocation`、UA、货币、世界坐标、星系名 |
| `GET /system` | 读 | `simulation.mpSolarSystem.maPlanets[]`，每颗行星只走 `_planet_info` |
| `GET /planet` | 读 | 当前行星 `_planet_info` |
| `GET /planet/scan` | 读 | 当前行星 `_planet_scan_info`：`PlanetInfo` + `CreatureIDs` + 三种物质 + `ExtraResourceHints` |
| `GET /ships` | 读 | `player_state.mShipResources` 的 12 个槽 |
| `PUT /teleport` | 写 | 写 `mLocation.GalacticAddress` + `StateChange("APPLOCALLOAD")` |
| `PUT /teleport/portal` | 写（实验） | 当前 `_PORTAL_WARP_CALIBRATED=False`，只返回 `E_UNSUPPORTED` |
| `PUT /restore` | 写 | 回到上一次 `teleport` 快照 |
| `PUT /scan/instant` | 写（hook） | 把 `cGcBinoculars.UpdateScanBarProgress` 的进度拉到 1；不写发现 |
| `PUT /scan` | 读/占位 | `read` 实际返回 `self.planet()`（基础字段），`discover` 暂不开放 |

### 1.2 三个必须指出的现状问题

1. **`/scan` 与 `/planet/scan` 不一致**：`/scan?mode=read` 调的是 `self.planet()`，不会返回 `common_substance/rare_substance/extra_resource_hints`；完整档案在 `/planet/scan`。做 dossier 时不要接错端点。
2. **`planet.scan` 被归到高风险**：`services/__init__.py` 的 `_HIGH_RISK_CAPABILITIES` 包含 `"planet.scan"`，未验证 build 时会被 build 闸门降级，尽管它只读。建议后续把“只读 dossier”和“写发现/传送”分开；本文只给结论，不在这里改代码。
3. **`/teleport/portal` 的代码在“假设已校准”后会先返回 `ok:true`**：`_portal_warp()` 里即使 `confirmed:false` 也返回 `{"ok": True, "experimental": True}`。验收时必须要求 `confirmed:true` + 落点读回，否则不能算成功。另外 `/hello` 的 `teleport.portal` 只看 `_portal_api()["available"]`，不把 `portal.calibrated` 作为必要条件；UI 不应把“API 存在”当成“可用的 portal warp”。

当前 agent 的 `_planet_info()` 只读 `PlanetInfo` 的固定字符串与 `CreatureIDs/Common/Rare/Uncommon`；它**没有**读 `GenerationData.CreatureRoles`、`SpawnData.Creatures`、`BuildingData`、`mScanManager`、`mSolarSystemMap`，也没有读存档发现记录。这就是“dossier”与“扫描结果”之间的真实差距。

---

## 2. 星球矿物 / 资源

### 2.1 游戏内存里到底有哪些字段

以 NMSpy 当前 `nmspy/data/exported_types.py` 的 `cGcPlanetData` 为准（`exported_types.py:38821`）：

| 字段 | 偏移 | 类型 | 语义 | 能否只读 |
|---|---:|---|---|---|
| `PlanetInfo` | `0x3548` | `cGcPlanetInfo` | 行星面板的本地化文本 | ✅ |
| `PlanetInfo.Resources` | `PlanetInfo +0x400` | `cTkFixedString0x80` | 资源摘要字符串（游戏 UI 用） | ✅ |
| `CommonSubstanceID` | `0x33D0` | `TkID0x10` | 常见物质 ID（定长 ASCII） | ✅ |
| `RareSubstanceID` | `0x3400` | `TkID0x10` | 稀有物质 ID | ✅ |
| `UncommonSubstanceID` | `0x3430` | `TkID0x10` | 不常见物质 ID | ✅ |
| `ExtraResourceHints` | `0x33F0` | `cTkDynamicArray[cGcPlanetDataResourceHint]` | 额外资源提示（`Hint` + `Icon`） | ✅ |
| `ResourceLevel` | `0x3540` | `eResourceLevelEnum` | `Low/High` | ✅ |
| `Hazard` | `0x3440` | `cGcPlanetHazardData` | 生存危害曲线（与“资源”不同） | ✅ |
| `SpawnData` | `0x32D8` | `cGcEnvironmentSpawnData` | 生物/物体/地标/可选物体的生成表 | ✅（模板） |
| `BuildingData` | `0x3338` | `cGcPlanetBuildingData` | 建筑生成模板/槽位，**不是已放置建筑坐标** | ✅（模板） |

`cGcPlanetDataResourceHint`（`exported_types.py:8745`）：

```text
_total_size_ = 0x20
Hint: TkID0x10  @0x00
Icon: TkID0x10  @0x10
```

### 2.2 特别注意：当前 NMSpy 没有 `ResourceHints` 这个字段

需求里提到 `cGcPlanetData.ResourceHints`。**在本地 NMSpy 的当前类型定义中，`cGcPlanetData` 只有 `ExtraResourceHints`，没有 `ResourceHints`。** `grep` 全 `nmspy/data` 也没有 `cGcPlanetData.ResourceHints`。

可能原因：

- 不同游戏 build 的字段名/布局不同；
- 其它项目把“资源提示数组”口语化叫成 `ResourceHints`；
- 旧版 NMSpy 或某个反编译版本用了不同命名。

落地时不要按名字硬编码：**以当前 build 的 `NMS.exe` 反射/`cGcPlanetData` 布局为准**。如果某版确实出现 `ResourceHints`，应先验证它是不是 `ExtraResourceHints` 的别名或另一个数组，再做读取。

### 2.3 哪些是“只读”，哪些需要“扫描函数”

| 需求 | 是否需要扫描函数 | 说明 |
|---|---|---|
| 星球资源摘要（`Resources`、三种 `SubstanceID`、`ExtraResourceHints`） | **不需要** | 行星生成/加载后 `cGcPlanetData` 就有；只读字段即可 |
| 资源 ID 翻译成中文/图标 | 不需要游戏扫描 | 可离线查 `cGcTerrainGlobals` 的 `MiningSubstanceBiome[17]`、`MiningSubstanceRare`、`MiningSubstanceStar`、`MiningSubstanceStarExtreme`（`exported_types.py`，`cGcTerrainGlobals`）或物品表 |
| 把某个矿物标记为“已发现” | **需要** | `cGcBinoculars.PopulateDiscoveryInfo(..., lbSubmitDiscovery=True)` 或 `cGcDiscoveryManager.SubmitDiscoveryData` |
| 附近矿点的精确位置 | **需要扫描/实体遍历** | `ExtraResourceHints` 不含坐标；`SpawnData` 只是生成模板；真正矿点是场景实体或扫描事件产物 |
| 已发现的矿物清单 | **不需要** | 读存档 `DiscoveryManagerData...DD.DT=Mineral`，但只有已发现 |

### 2.4 “附近矿点”为什么不能只读 `cGcPlanetData`

`cGcPlanetData.SpawnData` 是 `cGcEnvironmentSpawnData`，包含：

```text
Creatures, DetailObjects, DistantObjects, Landmarks, Objects, SelectableObjects
```

这些是**生成表和权重**，不是当前世界里的实例坐标。`BuildingData` 同理：

```text
Buildings: cTkDynamicArray[cGcBuildingSpawnData]
BuildingSlots: ...
OverrideBuildings: ...
PlanetRadius, Spacing, VoronoiPointDivisions, VoronoiPointSeed, ...
```

`cGcBuildingSpawnData` 里有 `Seed/Radius/Density/Classification` 等，但它是“这类建筑怎么生成”的模板，不是“这个传送门在 (x,y,z)”。真正的 `cGcBuilding` 实例有：

```text
mpPlanet: cGcPlanet*   @0x70
mpData: cGcBuildingSpawnData* @0x78
mNode: TkHandle        @0x80
meScanState: i32       @0xB4
```

但 NMSpy **没有给出 `cGcBuilding` 的全局链表/数组**，只能从扫描事件 `cGcScanEvent.mpBuilding`、marker 或实体遍历拿到。因此“附近矿点/建筑位置”不是读一个字段就能完成。

### 2.5 判定、依赖、风险、验收、最小步骤

| 项 | 内容 |
|---|---|
| **判定** | 星球资源摘要 **✅ 可只读**；附近矿点位置 **🔴 需进程内实体/扫描事件** |
| **依赖** | `cGcPlanetData` 布局（当前 build）；`TkID` 定长字符串读取；`cTkDynamicArray` 安全遍历；`cGcTerrainGlobals` 翻译表 |
| **风险** | 偏移随 build 变化；`ExtraResourceHints` 数组长度异常会越界；把 `SpawnData/BuildingData` 当成实际坐标会给出假位置；多人模式不能写发现 |
| **验收** | 在 10 颗已加载行星上，`Resources/Common/Rare/Uncommon/ExtraResourceHints` 与游戏内分析面板一致；空值必须能解释为“确实没有”；单次读取 < 100 ms；0 崩溃 |
| **最小实现步骤** | 1) agent 的 `_planet_scan_info()` 已读三种物质与 `ExtraResourceHints`，先接 UI；2) 增加 `cGcTerrainGlobals` 的 ID→名称/图标翻译；3) 在 `/planet/scan` 输出 `source:"memory"`、`complete`、`unsupported[]`；4) “附近矿点”另开只读实验端点，只返回 marker/实体候选，不承诺覆盖全部 |

---

## 3. 动植物

### 3.1 描述字段：`PlanetInfo.Fauna / Flora`

`cGcPlanetInfo`（`exported_types.py:8769`）是固定字符串集合：

| 字段 | 偏移 | 类型 | 语义 |
|---|---:|---|---|
| `Fauna` | `+0x200` | `cTkFixedString0x80` | 动物描述（如“丰富/稀少/无”） |
| `Flora` | `+0x280` | `cTkFixedString0x80` | 植物描述 |
| `PlanetDescription` | `+0x300` | `cTkFixedString0x80` | 行星总体描述 |
| `PlanetType` | `+0x380` | `cTkFixedString0x80` | 行星类型 |
| `Resources` | `+0x400` | `cTkFixedString0x80` | 资源摘要 |
| `Weather` | `+0x480` | `cTkFixedString0x80` | 天气 |
| `SpecialFauna` | `+0x505` | `bool` | 特殊动物标记 |

这些字段**只是描述性文本**，不是物种清单。当前 agent 的 `_planet_info()` 已经读取 `Fauna/Flora/PlanetDescription/PlanetType`，所以“读描述”是 ✅。

### 3.2 真正的物种数据：`CreatureIDs` / `CreatureRoles` / `SpawnData`

#### (a) `cGcPlanetData.CreatureIDs`

```text
CreatureIDs: cTkDynamicArray[TkID0x10] @0x33E0
```

`TkID0x10` 是 16 字节定长 ASCII（`basic_types.py:334`，`__str__` 直接解码）。这很可能是行星上生成出来的生物 ID 列表（如 `FISH`、`ANTELOPE` 等）；是否完整必须按 3.5 校准。当前 agent 已读：

```python
out["creature_ids"] = [_s(x) for x in data.CreatureIDs]
```

这是“列出当前星球物种”的最短路径，但**它是否包含全部物种、是否只含已启用角色、是否在未加载行星上为空，必须实机校准**。

#### (b) `cGcPlanetData.GenerationData.CreatureRoles`

`cGcPlanetData.GenerationData` 在 `0x3180`，类型 `cGcPlanetGenerationIntermediateData`（`exported_types.py:31492`）：

```text
CreatureRoles: cGcCreatureRoleDataTable @0x00（即 PlanetData + 0x3180）
CreatureAirFile / CreatureCaveFile / CreatureExtraWaterFile /
CreatureLandFile / CreatureRobotFile / CreatureWaterFile
ExternalObjectListIndices / ExternalObjectLists
Seed, TerrainFile, Terrain, Biome, BiomeSubType, Class, Size, StarType, ...
```

`cGcCreatureRoleDataTable`（`exported_types.py:29045`）：

```text
AvailableRoles: cTkDynamicArray[cGcCreatureRoleData] @0x00
MaxProportionFlying: f32 @0x10
SandWormFrequency: f32 @0x14
HasSandWorms: bool @0x18
```

`cGcCreatureRoleData`（`exported_types.py:29030`，`_total_size_ = 0x5D8`）：

```text
Info: cGcCreatureInfo @0x000
Description: cGcCreatureRoleDescription @0x518
Filter: TkID0x20 @0x580
CreatureId: TkID0x10 @0x5A0
Seed: GcSeed @0x5B0
Diet: enum @0x5C0
GroupsPerSquareKm: f32 @0x5C4
HemiSphere: enum @0x5C8
TileType: enum @0x5CC
Type: cGcCreatureTypes @0x5D0
```

`cGcCreatureInfo`（`exported_types.py:18430`）还带：

```text
BiomeDesc/DietDesc/NotesDesc/TempermentDesc, Age, Height1/Height2,
Rarity, Weight1/Weight2, Diet, Gender1/Gender2,
Height/Weight 的本地化字符串, Notes, Temperament
```

`cGcCreatureRoleDescription`（`exported_types.py:18515`）带：

```text
Filter, ForceID, RequireTag, ActiveTime, Density, ForceType,
Min/MaxGroupSize, Min/MaxSize, ProbabilityOfBeingEnabled, Role
```

因此：**`CreatureRoles.AvailableRoles` 比 `CreatureIDs` 更适合做“全部角色/物种档案”**，能给出 `CreatureId`、类型、稀有度、描述、活动时间、群体大小、生成概率等。

#### (c) `cGcPlanetData.SpawnData.Creatures`

`SpawnData` 在 `0x32D8`，`cGcEnvironmentSpawnData`（`exported_types.py:38804`）：

```text
Creatures: cTkDynamicArray[cGcCreatureSpawnData] @0x00
DetailObjects / DistantObjects / Landmarks / Objects / SelectableObjects
```

`cGcCreatureSpawnData`（`exported_types.py:36754`，`0x148`）：

```text
ExtraResource: cGcResourceElement @0x00
FemaleResource: cGcResourceElement @0x48
Resource: cGcResourceElement @0x90
Filter: TkID0x20 @0xD8
CreatureID: TkID0x10 @0xF8
CreatureActiveInDayChance: f32 @0x108
CreatureActiveInNightChance: f32 @0x10C
CreatureDespawnDistance: f32 @0x110
CreatureGroupsPerSquareKm: f32 @0x114
CreatureMaxGroupSize: i32 @0x118
CreatureMinGroupSize: i32 @0x11C
CreatureRole: cGcCreatureRoles @0x120
CreatureSpawnDistance: f32 @0x124
CreatureType: cGcCreatureTypes @0x128
HemiSphere: enum @0x12C
MaxScale: f32 @0x130
MinScale: f32 @0x134
Rarity: enum @0x138
RoleDataIndex: i32 @0x13C
TileType: enum @0x140
AllowFur: bool @0x144
Herd: bool @0x145
SwapPrimaryForRandomColour: bool @0x146
SwapPrimaryForSecondaryColour: bool @0x147
```

这也是一个“完整物种/生成实例”候选源：`CreatureID`、角色、类型、稀有度、大小、昼夜概率、群体规模都在。它与 `CreatureIDs`、`CreatureRoles.AvailableRoles` 应当交叉验证。

#### (d) `cGcPlanetGenerator` 的生成函数

NMSpy 的 `cGcPlanetGenerator`（`types.py:1998`）提供了函数签名/hook：

| 函数 | 作用 |
|---|---|
| `Generate(lPlanetData, lGenerationData, lpPlanet)` | 行星整体生成 |
| `GenerateCreatureRoles(lPlanetData, lUA)` | 决定这颗行星有哪些生物角色 |
| `GenerateCreatureInfo(lPlanetData, lRole)` | 为某个角色生成信息 |
| `GenerateQueryInfo(lQueryData, lGenerationData, lUA)` | 生成查询信息 |
| `FillCreatureSpawnDataFromDescription(lRole, lSpawnData, lPlanetData)` | 从角色描述填充生成数据 |
| `GenerateCreatureSpawnData(lPlanetData)` | 生成该行星的生物生成表 |

这些是 **🔴 需要进程内函数调用或离线复刻生成器** 的路径。当前 `starforge` 的 `creature.py` 只做了：

- `role_names()`：从 `Metadata/Simulation/Ecosystem/CreatureDataTable.mbin` 提取角色名；
- `role_table()`：解析 `cGcCreatureDataTable` 的 86 条 `cGcCreatureData`，拿到 `Id/ForceType/RealType/MinScale/MaxScale` 等；
- 明确的结论：**“每个行星具体分配哪些角色”仍然需要运行时生成器，静态表不够**。

### 3.3 与 `DiscoveryManager` 的关系

`cGcDiscoveryManager`（`types.py:1489`）目前只暴露：

```python
@function_hook("48 89 5C 24 ? ...")
def SubmitDiscoveryData(this, lDiscoveryData: cGcDiscoveryData*, lpbLocallyNew: bool*)
```

`cGcDiscoveryData`（`types.py:1484`）只有：

```text
mUniverseAddress: u64 @0x00
meType: cGcDiscoveryType @0x40
```

`cGcDiscoveryType`（`external_enums.py:4242`）包含：

```text
Unknown, SolarSystem, Planet, Animal, Flora, Mineral, Sector,
Building, Interactable, Sentinel, Starship, Artifact, Mystery,
Treasure, Control, HarvestPlant, FriendlyDrone, SpacePoi, SpaceStation
```

关键事实：

- `cGcGameState` 里 `mDiscoveryManager` 的候选偏移 `0x2BA3B8` 是**注释掉的**（`types.py:1520`），NMSpy 当前没有启用它；
- 因此 agent **不能**通过 `gameData` 直接拿到 discovery manager；
- 可以 hook `SubmitDiscoveryData`，在游戏真正提交发现时捕获 `this` 指针，再验证/缓存；
- 当前 `cGcDiscoveryData` 是 `@partial_struct`，缺 `VP`（variation hashes）、flags、owner 等字段，不能安全构造来写；
- 所以 `scan.discover` 现在只能是 `False`。

### 3.4 存档里的“已发现”记录（可以只读）

`DiscoveryManagerData.DiscoveryData-v1` 有 5 个键（本地 `save.hg` 实测）：

```text
ReserveStore, ReserveManaged, Store, Available, Enqueued
```

`Store.Record[]` 是主记录列表。每条记录形状（本地样本）：

```json
{
  "DD": {"UA": 4933512850009402, "DT": "Planet", "VP": ["0xD0A259390B3921DC", 7]},
  "DM": {},
  "OWS": {"LID": "...", "UID": "...", "USN": "...", "PTK": "", "TS": 1791726683},
  "FL": {"C": 1},
  "RID": "...",
  "PTK": "ST"
}
```

`DD` = discovery data：

- `UA`：宇宙地址（系统/行星打包；`locate.py` 的 `pack_ua/unpack_ua` 可解）；
- `DT`：`cGcDiscoveryType` 字符串；
- `VP`：variation hashes / 变体列表（动物/植物/矿物用来区分具体物种，**不是坐标**）；
- `DM.CN`：自定义名称（本地样本里只有少量 SolarSystem 记录有，例如“胖胖私人传送星系”）；
- `OWS`：发现者/时间戳；`FL`：flags；`RID/PTK`：记录 ID/平台。

本地样本 `Store.Record` 共 **3210** 条，`DT` 分布：

```text
Planet 828, Animal 699, Mineral 625, Flora 524, SolarSystem 412,
Sector 59, SpacePoi 39, Interactable 20, SpaceStation 4
```

`Available` 另有 10 条（可能是待上传/最近可用记录；语义需进一步确认），`Enqueued` 为 0。

结论：

- **已发现动物/植物/矿物**：✅ 可从存档只读；能按 `DD.UA` 归到行星；
- **当前星球全部物种**：❌ 存档没有；只有已发现的那部分；
- **物种中文名**：存档没有，只有 `VP` 哈希；名称要靠游戏内本地化/发现记录/生成器；
- **动物 ID 与 `VP` 的对应关系**：当前未验证；不能把 `VP` 直接当 `CreatureId`。

`nms_procgen/locate.py` 的 `save_known_systems()` 已经示范了如何读 `DiscoveryData-v1` 里的 `SolarSystem` 记录。可以照同样方式扩展出 `save_discoveries_by_ua()`，只读 `Animal/Flora/Mineral`。

### 3.5 能否“列出当前星球所有物种”？

分三层回答：

| 问题 | 答案 |
|---|---|
| 能读当前星球的**生物描述**吗？ | ✅ `PlanetInfo.Fauna/Flora` |
| 能读当前星球的**物种 ID 列表**吗？ | ✅ `CreatureIDs` 可读，但它是否完整待校准 |
| 能读当前星球的**全部角色/生成数据**吗？ | 🟡 `CreatureRoles.AvailableRoles` + `SpawnData.Creatures` 结构齐全；需要新代码 + 实机对照 |
| 能不加载行星、离线列出任意星球全部物种吗？ | 🔴/⛔ 需要 `cGcPlanetGenerator.GenerateCreatureRoles/GenerateCreatureSpawnData` 或复刻生成器；当前 `starforge` 没有 |
| 能列“已发现”物种吗？ | ✅ 存档 `DiscoveryData-v1`，但只有已发现 |
| 能列“未发现”物种吗？ | 🟡 只有读内存 `CreatureRoles/SpawnData/CreatureIDs` 才可能；不能从存档得到 |

**验收“全部物种”的最低标准**：

1. 在 10 颗行星上，`CreatureIDs` 数量、`AvailableRoles` 数量、`SpawnData.Creatures` 数量三者能互相解释；
2. 与游戏内“发现物 → 动物”页面的总数（x/y 的 y）一致；
3. 每个 `CreatureId` 非空、不是 `^`；重复项可解释；
4. 退出星球再进入，列表稳定；
5. 未加载行星返回明确 `unsupported/empty`，不能返回空列表冒充“没有物种”。

### 3.6 判定、依赖、风险、验收、最小步骤

| 项 | 内容 |
|---|---|
| **判定** | 描述 ✅；`CreatureIDs` ✅；全部角色/物种 🟡（需实现+校准）；任意行星离线生成 🔴/⛔；已发现 ✅（存档） |
| **依赖** | `cGcPlanetData.GenerationData.CreatureRoles`、`cGcCreatureRoleData`、`cGcCreatureInfo`、`SpawnData.Creatures`、`cGcCreatureSpawnData`、`cGcCreatureDataTable`、存档 `DiscoveryData-v1` |
| **风险** | 数组长度/指针异常导致越界；`CreatureRoles` 可能只在行星生成后填充；`TkID` 可能带 `^` 或填充 0；把 `VP` 当物种 ID 会张冠李戴；写发现会污染成就/奖励 |
| **验收** | 见 3.5；另外读取 < 200 ms，0 崩溃；已发现列表与存档计数一致 |
| **最小实现步骤** | 1) 在 agent 增加只读 `_creature_dossier(data)`：读 `CreatureIDs`、`GenerationData.CreatureRoles.AvailableRoles`、`SpawnData.Creatures`，每项单独 try/except；2) 输出 `id/type/rarity/min_scale/max_scale/role/probability` 与 `source`；3) 在存档侧加 `save_discoveries_by_ua()`，按 `DD.UA` + `DT=Animal/Flora/Mineral` 归组；4) 把“全部/已发现/未知”分三栏；5) 实机对照 10 颗行星后再把 `complete` 置真 |

---

## 4. 附近传送门 / 古遗迹 / 货船 / 飞船 / 建筑

### 4.1 数据源矩阵

| 数据源 | 类/字段 | 性质 | 能回答什么 | 局限 |
|---|---|---|---|---|
| 扫描 marker 列表 | `cGcSimulation.mScanManager` @`0xF1B0` → `cGcScanManager.mMarkerList` @`0x2310` → `cGcMarkerList.maMarkerObjects`（`tk_vector[cGcMarkerPoint]`） | 内存只读 | 当前游戏已经创建/追踪的 marker：传送门、建筑、飞船、货船、空间站、信号等 | 不是“附近所有未发现物”；只有游戏已经放入列表的 marker |
| `cGcMarkerPoint` | `mPosition` @0x20、`mCustomName` @0x58、`mCustomSubtitle` @0x98、`meBuildingClass` @0x138、`meType` @0x291 | 内存只读 | marker 的位置、名称、建筑分类、marker 类型 | 需要安全遍历 vector；`mPosition` 是 `cTkPhysRelVec3`，单位/坐标空间要校准 |
| 扫描事件 | `cGcScanEvent`：`mMarker` @0x10、`mpEvent` @0x280、`mpBuilding` @0x288、`meEventState` @0x298；`cGcScanEventData` 的 `eSearchType`/`eBuildingLocation` | 内存 + 函数 | 游戏如何选择“最近的建筑/空间站/货船/Atlas”等 | NMSpy 没有 `cGcScanEvent` 的全局列表；`cGcScanEventManager` 只有静态 `PassesPlanetInfoChecks`，没有字段 |
| 星系地图对象 | `cGcSolarSystem.mSolarSystemMap` @`0x51BC20` → `cGcSolarSystemMap.maAssociatedMapObjects` @`0x1520`（64 个 `cGcSolarSystemMapObject`） | 内存只读 | 空间站、Atlas、黑洞、行星、气态巨行星、SpacePoi、SpaceBase 的对象与位置 | 只有星系级空间对象；没有地表传送门/古遗迹 |
| 星系生成数据 | `cGcSolarSystem.mSolarSystemData`：`SpacePoiPositions[32]` @0x1CE0、`SpaceStationSpawn` @0x1EE0、`Locators` @0x2470、`SystemShips` @0x24A0、`FreighterTimer` @0x2500、`MaxNumFreighters` @0x2538 等 | 内存只读 | 本星系的生成配置/候选位置 | 不是当前实例；`SystemShips` 是预载配置，不是附近飞船 |
| SpacePoi 实例 | `cGcSpacePoiSiteComponent`：`mPosition` @0x40、`mSpacePoiID` @0x50、`mpSpacePoiDataItem` @0x80、`mName` @0x140、`mDescription` @0x1C0 | 内存只读 | 某个已存在 SpacePoi 的名称/描述/位置 | 没有全局组件列表；需要实体遍历或 hook |
| 行星建筑模板 | `cGcPlanetData.BuildingData` @0x3338 → `Buildings: cTkDynamicArray[cGcBuildingSpawnData]`、`BuildingSlots`、`VoronoiPointSeed` 等 | 内存只读（模板） | 这颗行星会/可能生成哪些建筑类型、密度、分类 | **没有实际坐标**；不能当“附近传送门” |
| 实际建筑实例 | `cGcBuilding`：`mpPlanet` @0x70、`mpData` @0x78、`mNode` @0x80、`meScanState` @0xB4；`cGcBuildingSpawnData.Classification` @0xD3 | 内存（实体） | 某个已放置建筑的分类/扫描状态 | NMSpy 没有实体的全局列表；通常从扫描事件 `mpBuilding` 拿到 |
| 存档发现记录 | `DiscoveryManagerData.DiscoveryData-v1.Store.Record[]`，`DD.DT=Building/Artifact/SpacePoi/SpaceStation/Interactable` | 存档只读 | 已发现的建筑/古遗迹/空间站/POI | 只有已发现；本地样本 0 条 Building/Artifact；无精确行星内坐标 |
| 传送终点 | `cGcPlayerState.maTeleportEndpoints` @0x1AB70；`cGcTeleportEndpoint`：`Position` @0x10、`UniverseAddress` @0x20、`TeleporterType` @0x48、`Name` @0x4C | 内存只读 | 已知基地/空间站/货船等传送点 | 不是“附近未发现传送门” |
| 玩家飞船 | `player_state.mShipResources` @0x17EE0（12 个 `cGcResourceElement`）；存档 `ShipOwnership` | 内存/存档只读 | 自己拥有的飞船、当前主船 | 不是附近 NPC 飞船 |
| 货船归属 | `cGcGameState.mPlayerFreighterOwnership` @0x2B8340（4 个）；`cGcSolarSystemData.MaxNumFreighters/FreighterTimer` | 内存只读 | 自己的货船/生成配置 | 不是附近动态货船实例 |

### 4.2 各类目标逐项拆解

#### (a) 传送门

可用线索：

- `cGcMarkerType.Portal = 0x30`（`external_enums.py:5543`）；
- `cGcBuildingClassification.Portal = 0x10`（`external_enums.py:3615` 附近）；
- `cGcPortalComponent.PersistentData`：`mWorldMatrix @0x00`、`mUA @0x40`、`mTargetUA @0x48`、`mBuildingSeed @0x50`、`mbActive @0x60`、`mbIsStoryPortal @0x61`、`mbIsActiveCommunityPortal @0x62`；
- 存档 `cGcPortalSaveData`：`PortalSeed @0x00`、`LastPortalUA @0x10`、`IsStoryPortal @0x18`（`exported_types.py:9368` 附近）。

结论：

- **读当前已激活/已标记的传送门**：🟡。如果 `mScanManager.mMarkerList` 里有 `meType=Portal`，可以只读位置/名称；如果已经靠近并触发了 `cGcPortalComponent`，还能读 `mUA/mTargetUA/mbActive`。但 NMSpy 没有“所有 portal 组件”的全局列表。
- **找附近未发现的传送门**：🔴。`PlanetData.BuildingData` 只是模板；真正的传送门实体由建筑放置/扫描事件生成。需要：
  - 遍历 `cGcBuilding` 实体（NMSpy 未提供列表）；
  - 或构造/触发 `cGcScanEvent`（`eBuildingLocation=Nearest/PlanetSearch`，`eSearchType=FindBuildingClass`）；
  - 或 hook `cGcPortalComponent.Prepare/OnAttached`，在玩家靠近时捕获真实组件；
  - 或使用游戏内真实扫描（按 F）后读 marker。
- **只凭 glyph 地址推断“附近有传送门”**：⛔。地址只能定位星球/系统，不能定位传送门建筑。

#### (b) 古遗迹（Ruin/Monolith/Plaque）

- 分类：`cGcBuildingClassification.Ruin=0x11`、`Monolith=0xF`、`Plaque=0xE`、`Observatory=0xA`、`Beacon=0x8`、`Shelter=0x2`、`Abandoned=0x3` 等；
- marker：`cGcMarkerPoint.meBuildingClass` 可过滤；
- 扫描事件：`cGcScanEventData.eSearchType` 有 `FindBuildingClass`、`AnyShelter`、`AnyNPC` 等；`eBuildingLocation` 有 `Nearest/AllNearest/Random/PlanetSearch/NearestUnmarked`。

结论与传送门相同：**已存在 marker/事件可读；附近未发现古遗迹不能只读完成**。如果没有 marker，需要触发扫描事件或遍历 `cGcBuilding`。

#### (c) 建筑

- `cGcPlanetData.BuildingData` 是生成模板，不是已放置实例；
- 实际建筑在 `cGcBuilding`，`mpData` 指 `cGcBuildingSpawnData`，`meScanState` 是扫描状态；
- `cGcScanEvent.mpBuilding` 是扫描事件到实际建筑的桥；
- `cGcBuilding.Visited(lbLoad)`、`cGcBuilding.DestroyIntersectingVolcanoes()` 是函数，不是查询接口。

结论：

| 需求 | 判定 |
|---|---|
| 读“这颗行星可能生成哪些建筑类型/密度” | ✅ `BuildingData` 模板 |
| 读“当前已存在/已标记建筑” | 🟡 marker / scan event |
| 找“附近未发现建筑” | 🔴 需要事件/实体遍历 |
| 读“所有建筑坐标” | ⛔ 当前 NMSpy 没有全局建筑列表 |

#### (d) 货船

| 需求 | 判定 | 说明 |
|---|---|---|
| 自己的货船/货船传送点 | ✅/🟡 | `mPlayerFreighterOwnership`、`maTeleportEndpoints`、存档 |
| 本星系是否可能刷货船 | 🟡 | `cGcSolarSystemData.MaxNumFreighters`、`FreighterTimer`、`StartWithFreighters` 是配置，不是当前实例 |
| 附近动态货船（位置/型号） | 🔴 | 没有全局实例列表；只能从 marker（`Freighter`/`PlayerFreighter`）或实体遍历 |
| “触发货船战” | 🟡 | NMSCoordinates 通过改存档实现；不是扫描，且需要重载 |

#### (e) 飞船

| 需求 | 判定 | 说明 |
|---|---|---|
| 自己拥有的飞船/主船 | ✅ | `player_state.mShipResources`、`miPrimaryShip`、存档 `ShipOwnership` |
| 本星系预载的飞船类型 | 🟡 | `cGcSolarSystemData.SystemShips`（`cGcAISpaceshipPreloadCacheData`）是预载配置 |
| 附近 NPC/飞行的飞船 | 🔴 | 没有实例列表；marker 类型 `Ship=0xB` 只在游戏标记后才有 |
| 坠毁飞船/求救信号 | 🟡/🔴 | 扫描事件/发现记录；未发现时不能凭空给出 |

#### (f) 空间站 / Atlas / 黑洞 / SpacePoi

`cGcSolarSystemMapObject`（`types.py:1934`）：

```text
_total_size_ = 0xD0
meType: cGcSolarSystemMapObjectType @0x00
miIndex: i32 @0x08        # Planet/GasGiant 时的行星索引
mVector: cTkVector3 @0x70
mNode: TkHandle @0x80
mNode2: TkHandle @0x84
mVector1/2/3 @0x90/0xA0/0xB0
mbIsActivated: bool @0xC9
```

`cGcSolarSystemMapObjectType`：`Player, RemotePlayer, SpaceStation, AtlasStation, Blackhole, Planet, GasGiant, SpacePoi, SpaceBase`。

因此：

- **本星系空间站/Atlas/黑洞/SpacePoi 的地图位置**：🟡 可读；
- **地表传送门/古遗迹**：不在这个数组里；
- **附近货船**：不在这个数组里（只有 `SpaceBase` 等类型）。

### 4.3 判定、依赖、风险、验收、最小步骤

| 项 | 内容 |
|---|---|
| **判定** | 已存在 marker/地图对象 🟡；附近未发现传送门/古遗迹/建筑 🔴；附近动态货船/NPC 飞船 🔴；已发现记录 ✅（存档）；自己飞船/传送点 ✅ |
| **依赖** | `cGcSimulation.mScanManager`、`cGcScanManager.mMarkerList`、`cGcMarkerPoint`、`cGcSolarSystem.mSolarSystemMap`、`cGcSolarSystemData`、`cGcScanEvent`、`cGcBuilding`、`cGcSpacePoiSiteComponent`、存档 `DiscoveryData-v1` |
| **风险** | vector 遍历越界；`TkHandle`/`cTkPhysRelVec3` 不能直接当世界坐标；marker 只有“已追踪”的，不是“附近全部”；把模板当实例会给出假坐标；调用扫描事件可能导致游戏状态变化；多人不同步 |
| **验收** | marker 列表与游戏 HUD 上当前标记的数量/类型一致（至少 20 个样本）；空间站/Atlas/黑洞地图对象与星系图一致；过滤 `Portal/Ruin/Monolith` 不误报；0 崩溃；未发现的项必须返回 `unknown/unsupported`，不能伪造 |
| **最小实现步骤** | 1) 先做只读 `_markers(sim)`：安全遍历 `mScanManager.mMarkerList.maMarkerObjects`，输出 `position/name/subtitle/type/building_class`；2) 做只读 `_system_map(ss)`：遍历 64 个 `maAssociatedMapObjects`；3) 存档侧读 `DiscoveryData-v1` 的 `Building/Artifact/SpacePoi/SpaceStation`；4) UI 标注 `source=marker/system_map/save`；5) “附近未发现”要另立实验端点，先只做实体搜索/扫描事件原型，不默认开启 |

---

## 5. “直接传送门效果”：三种路径的差别与风险

### 5.1 `cGcPortalComponent.WarpPlayer`

`cGcPortalComponent`（`types.py:5679`）：

```text
mpData: cGcPortalComponentData* @0x30   # 实际只有 Temp float，几乎无信息
mPortalData: PersistentData @0x40
  mWorldMatrix: cTkMatrix34 @0x00
  mUA: u64 @0x40
  mTargetUA: u64 @0x48
  mBuildingSeed: GcSeed @0x50
  mbActive: bool @0x60
  mbIsStoryPortal: bool @0x61
  mbIsActiveCommunityPortal: bool @0x62
```

`WarpPlayer` 的 NMSpy 注释明确：

> Warps the player to this `cGcPortalComponent::PersistentData`'s `mTargetUA`, if `mbActive` is set to true.

也就是说，**真正的 portal warp 需要**：

1. 一个**活的、已 attached 的** `cGcPortalComponent` 实例；
2. `mPortalData.mTargetUA` 是目标 UA；
3. `mbActive=True`；
4. 组件所在的场景/节点/持久化数据完整。

这条路径最接近“游戏内走传送门”：会走 portal 自己的逻辑/表现/状态，而不是裸改玩家位置。

### 5.2 `cGcSpaceshipWarp.WarpToDistantSystem / Prepare`

`cGcSpaceshipWarp`（`types.py:2363`）：

```text
mJumpTarget: cGcWarpJumpTarget @0x10
meWarpState: eWarpState @0x9C
mfWarpTimeTotal @0xA8
mWarpInDestinationTM @0x4A0
meCurrentWarpEffect: eWarpEffectType @0x5F0
```

`eWarpEffectType` 包括：

```text
Normal=0, Teleport=1, ToNextGalaxy=2, BlackHole=3, GalaxyMap=5,
Portal=6, PortalStorySpace=7, PortalStoryPlanet=8, PortalCommunity=9,
Freighter=0xA, NexusExit=0xB, FreighterMegaWarp=0xC, FakePortalTeleport=0xD
```

函数：

- `Prepare(leEffectType, lbSilent)`；
- `WarpToDistantSystem(lJumpTarget, leEffectType, lbSilent)`；
- `Update/UpdatePulseDrive/GetPulseDriveFuelFactor`。

这条路径适合**系统级跳转**（飞船/货船/传送门效果），有 warp state 序列、目标 system、warp tunnel/生成/重生流程。它比 `APPLOCALLOAD` 更接近“真实传送”，但需要：

- 活的 `cGcSpaceshipWarp` 指针（`cGcSimulation.mWarp` @`0x25E0B0`）；
- 正确的 `cGcWarpJumpTarget`/`cGcGalacticSolarSystemAddress`；
- 通常在飞船内/允许 warp 的上下文；
- 实机校准效果类型和 silent 参数。

它**不能精确落到行星表面某个坐标**，更适合“到目标星系”。

### 5.3 `GcApplication.StateChange("APPLOCALLOAD")`

当前 `starforge` 的 teleport：

```python
ga = ps.mLocation.GalacticAddress
ga.PlanetIndex = dest["planet"]
ga.SolarSystemIndex = dest["system"]
ga.VoxelX/Y/Z = ...
ps.mLocation.RealityIndex = dest["reality"]

state = basic.cTkFixedString[0x10]("APPLOCALLOAD")
app.StateChange(ctypes.addressof(state), 0, False)
```

`StateChange` 是 `cTkFSM` 的状态切换（`types.py:1585`），`cTkFSMState.StateChange` 的签名则把 `lNewStateID` 声明为 `cTkFixedString[0x10]*`（`types.py:3804`）。两种签名在 NMSpy 里并存，当前代码按“指针到 fixed string”调用。

它的本质是：**改玩家 `mLocation`，然后强制进入本地加载状态**。它不是 portal 组件，也不是飞船 warp；它不保证：

- 目标星系/行星存在且可生成；
- 玩家落在合理地表位置（可能空中/地下/水里）；
- `mPrevLocation`、`simulation.mCurrentUA`、飞船位置/状态、星系对象同步；
- portal 的 `mTargetUA/mbActive` 状态、portal 表现、portal 后的 interference（版本相关）；
- 保存时写入的坐标与当前世界一致。

因此它最多是“冷传送/强制重载”的近似，不应在 UI 上称为“传送门效果”。

### 5.4 风险对比

| 维度 | 现有写位置 + APPLOCALLOAD | `cGcPortalComponent.WarpPlayer` | `cGcSpaceshipWarp.WarpToDistantSystem` |
|---|---|---|---|
| 是否真实 portal | 否 | 是（如果组件真实且 active） | 可模拟 portal effect（`Portal=6`/`FakePortalTeleport=0xD`） |
| 需要的对象 | `player_state` + `GcApplication` | 活的 portal 组件 + `mTargetUA/mbActive` | 活的 `simulation.mWarp` + 目标 system |
| 落点精度 | 只写 UA，地表位置不保证 | 由 portal/目标 UA 决定 | 星系级，不到地表 |
| 状态同步 | 只改 `mLocation`，可能漏 `mPrevLocation/mCurrentUA/飞船` | 走组件逻辑，较完整 | 走 warp state 序列，较完整 |
| 崩溃风险 | 中（FSM 状态/加载上下文） | 中高（组件指针/场景节点必须真实） | 中高（warp 上下文/飞船状态） |
| 存档风险 | 高（错误 UA 被自动保存） | 中（portal 可能写 portal 状态/interference） | 中 |
| 多人 | 必须禁用 | 必须禁用 | 必须禁用 |
| 版本敏感度 | 中（`StateChange` 签名/状态名） | 高（组件偏移 + 函数） | 高（warp 偏移 + 效果枚举） |
| 现在能否做 | 能试，需快照/回滚/落点读回 | 不能，先捕获真实组件 | 不能，先校准 |

### 5.5 当前 `/teleport/portal` 代码的额外风险

当前 `_portal_warp()` 在 `_PORTAL_WARP_CALIBRATED=True` 时会：

```python
buffer = ctypes.create_string_buffer(size)
component = cls.from_buffer(buffer)
component.OnAttached()
component.mPortalData.mTargetUA = target_ua
component.mPortalData.mbActive = True
component.Prepare()
component.WarpPlayer()
```

问题：

1. **这不是游戏创建的组件**：`mPortalData.mUA/mWorldMatrix`、`mpData`、场景节点、附着对象都没有初始化；
2. `OnAttached`/`Prepare` 很可能访问 `mpData`、节点、组件管理器，空指针会崩；
3. `WarpPlayer` 依赖真实 portal 上下文；裸 buffer 即使不崩，也可能没有效果；
4. `ctypes` 方法调用对 `this` 的传递依赖 pymhf hook 包装，不能假设和普通 Python 方法一样；
5. 返回 `ok:true` 但 `confirmed:false` 会误导 UI。

**正确路线**：不要构造假组件。先 hook/定位一个真实 `cGcPortalComponent`（例如在 `Prepare`/`OnAttached` 时缓存 `this`，或从真实 portal 的 marker/建筑反查），验证 `mPortalData.mUA` 与当前/目标行星一致，再改 `mTargetUA`、`mbActive` 并调用 `WarpPlayer`。改前保存原值，失败恢复。

### 5.6 判定与验收

| 项 | 内容 |
|---|---|
| **判定** | `cGcPortalComponent.WarpPlayer`：🔴 需真实组件 + 实机校准；`cGcSpaceshipWarp`：🔴；`APPLOCALLOAD`：🟡 能试但非 portal，需明确标注 |
| **依赖** | 真实 portal 组件/真实 `simulation.mWarp`；build 地址书；快照/回滚；落点读回 |
| **风险** | 崩溃、掉出世界、错误 UA 被保存、portal interference/任务状态异常、多人不同步 |
| **验收** | 1) 目标 UA 在 warp 后与 `player_state.mLocation` 一致；2) 游戏内星系名/行星序号/biome 与预期一致；3) 玩家不在地下/太空/坠落；4) 存档可正常重载；5) 失败可用 `restore` 回到原 UA；6) 至少 20 次随机目标 0 崩溃、0 存档损坏；7) 多人模式始终拒绝 |
| **最小实现步骤** | 1) 先只读：hook `cGcPortalComponent.Prepare/OnAttached` 捕获真实组件指针，读 `mUA/mTargetUA/mbActive`；2) 端点只返回 portal 信息，不调用 `WarpPlayer`；3) 做一次“对当前 portal 的目标调用 `WarpPlayer`”的自检（如果安全）；4) 再实现“设置目标 + 调用 + 读回 + 失败恢复”；5) 在 `confirmed` 前保持 `_PORTAL_WARP_CALIBRATED=False`；6) 系统级跳转另走 `cGcSpaceshipWarp`，不要混在 portal 端点里 |

---

## 6. 每个能力的详细判定

### 6.1 ✅ 可只读（现在就能做，最多补字段/UI）

| 能力 | 数据源 | 最小实现 | 验收 |
|---|---|---|---|
| 玩家 UA/坐标/星系名 | `player_state.mLocation`、`simulation.mpSolarSystem.GetName` | 已有 `/player` | 与游戏内坐标一致 |
| 当前行星 `PlanetInfo` 摘要 | `cGcPlanetData.PlanetInfo` | 已有 `_planet_info` | 10 颗行星字段一致 |
| 当前行星资源摘要 | `CommonSubstanceID/RareSubstanceID/UncommonSubstanceID/ExtraResourceHints` | `_planet_scan_info` 已有；接 UI | 与游戏分析面板一致 |
| 当前行星 `CreatureIDs` | `cGcPlanetData.CreatureIDs` | 已有 | 非空/空值可解释 |
| 自己拥有的飞船 | `mShipResources`、存档 `ShipOwnership` | 已有 `/ships` | 12 槽与存档一致 |
| 已发现的动物/植物/矿物/星系 | 存档 `DiscoveryData-v1` | 新增只读解析 | 计数与存档一致 |
| 已存在 marker（只读） | `mScanManager.mMarkerList` | 新增安全遍历 | 与 HUD 标记一致 |
| 本星系空间对象（空间站/Atlas/黑洞/SpacePoi） | `mSolarSystemMap.maAssociatedMapObjects` | 新增遍历 | 与星系图一致 |

### 6.2 🟡 需实现（结构已定位，代码/校准/验证缺失）

| 能力 | 依赖 | 风险 | 验收 | 最小步骤 |
|---|---|---|---|---|
| 当前行星全部生物角色 | `GenerationData.CreatureRoles.AvailableRoles`、`SpawnData.Creatures` | 数组指针/长度；未加载行星为空；角色是否全部启用 | 与游戏内物种总数一致；10 颗行星 | 读三套列表 + 输出 source/complete |
| 当前行星全部植物 | `SpawnData.Objects/SelectableObjects`、`PlanetInfo.Flora`、存档 Flora 记录 | 没有 `FloraIDs`，只能推断；可能把普通物体当植物 | 与游戏内植物发现数一致；不能多报 | 先输出“描述 + 已发现 + 候选物体”，不要宣称全量 |
| 已存在传送门/古遗迹 marker | `cGcMarkerPoint.meType/meBuildingClass` | marker 只有已追踪；坐标单位 | 20 个 marker 对照；Portal/Ruin/Monolith 不误报 | 只读过滤；不承诺“附近全部” |
| 空间站/Atlas/黑洞/SpacePoi 位置 | `cGcSolarSystemMapObject` | `mVector` 坐标空间；64 个对象可能有空槽 | 与星系图一致 | 安全遍历 64 个，过滤 `meType` |
| 扫描条立即完成 | `cGcBinoculars.UpdateScanBarProgress` hook | 只改 UI 进度；多人禁用 | 扫描条立即满；不产生发现 | 已有 `scan_instant` |
| 位置写 + APPLOCALLOAD | `mLocation` + `StateChange` | 非 portal；漏状态；可能掉出世界 | UA 读回 + 游戏内落点确认 + restore | 保留为 fallback，UI 标注“重载式传送” |

### 6.3 🔴 需进程内函数/实机校准

| 能力 | 依赖 | 风险 | 验收 | 最小步骤 |
|---|---|---|---|---|
| 附近未发现传送门/古遗迹/建筑 | 遍历 `cGcBuilding` 或触发 `cGcScanEvent`（`FindBuildingClass`/`Nearest`/`PlanetSearch`） | 版本偏移；事件状态；可能改变游戏状态；崩溃 | 找到的每个点都能在游戏内看到；不误报；可回滚 | 先 hook `cGcPortalComponent.Prepare` / `cGcScanEvent.Construct` 捕获真实对象，再只读列表；最后才做触发 |
| 附近动态货船/NPC 飞船 | 全局实体/marker `Freighter/Ship` | 没有列表；动态生成；多人 | 与游戏内可见目标一致 | 先读 marker；没有 marker 就明确 `unsupported` |
| 写发现（`scan.discover`） | `cGcDiscoveryManager` 指针 + 完整 `cGcDiscoveryData` | 污染发现/成就/奖励；存档损坏 | 只增加目标记录；重载后仍在；不额外发奖 | hook `SubmitDiscoveryData` 捕获 manager；用反射补全 `cGcDiscoveryData`；测试存档验证 |
| 真正 portal warp | 真实 `cGcPortalComponent` + `WarpPlayer` | 组件/场景上下文；崩溃；portal 状态 | 见 5.6 | 先捕获真实组件，读 `mUA/mTargetUA`，再谈写目标 |
| 系统级 warp | 真实 `cGcSpaceshipWarp` + `WarpToDistantSystem` | 飞船上下文；warp 状态 | 目标系统 UA 正确；不崩 | 用 `simulation.mWarp` 做只读状态，再校准 `Prepare/WarpToDistantSystem` |
| 任意行星离线生成物种 | `cGcPlanetGenerator.GenerateCreatureRoles/GenerateCreatureSpawnData` 或复刻 | 大工程；静态表不足 | 与在线生成一致 | 不作为近期目标；先做当前行星 |

### 6.4 ⛔ 不可做 / 不能假装

| 说法 | 为什么不行 |
|---|---|
| “我在当前星球列出了全部物种” 只凭 `CreatureIDs` | 未验证它是否完整/是否只含已启用；必须与 `CreatureRoles/SpawnData` 和游戏内 y 值对照 |
| “我找到了附近未发现的传送门/古遗迹” 只凭 `BuildingData` | `BuildingData` 是生成模板，不是坐标 |
| “附近有一艘货船/飞船” 只凭 `MaxNumFreighters/FreighterTimer/SystemShips` | 这些是生成配置/预载，不是当前实例 |
| “扫描已发现” 只凭 `scan.instant` | 它只是把进度条拉满；没有 `SubmitDiscoveryData` |
| “portal warp 成功” 只凭 `ok:true` | 必须落点读回 + 游戏内确认；当前 `_portal_warp` 在未确认时也会 `ok:true`（如果打开开关） |
| “离线生成任意星球天气/动植物/资源” | `system.py` 已明确 `PLANET_FIELDS`：weather/flora/fauna/resources 需要游戏运行时；上游 systemgen 只给 biome/sentinels/seed |
| “改存档发现列表” 当作无风险 | 发现记录与成就/奖励/上传状态相关；必须备份、验证、只读优先 |

---

## 7. 推荐实现顺序

### P0：只读 dossier（先让数据可信）

目标：一个**只读**的当前行星/星系档案，不写任何游戏状态。

内容：

1. `player_state.mLocation` + `simulation.mpSolarSystem`；
2. `_planet_scan_info`：`PlanetInfo` + 三种物质 + `ExtraResourceHints`；
3. `CreatureIDs` + `GenerationData.CreatureRoles.AvailableRoles` + `SpawnData.Creatures`；
4. `mScanManager.mMarkerList.maMarkerObjects`（只读）；
5. `mSolarSystemMap.maAssociatedMapObjects`（只读）；
6. 存档 `DiscoveryData-v1` 的已发现记录（按 UA 归组）。

输出约定：

- 每项带 `source: "memory" | "save" | "offline"`；
- 每项带 `complete: true/false` 和 `unsupported[]`；
- 不把“已发现”混进“全部”；
- 不把“模板”混进“实际位置”。

验收：

- 10 颗行星，资源/生物描述与游戏分析面板一致；
- `CreatureIDs`、`AvailableRoles`、`SpawnData.Creatures` 三者关系可解释；
- marker 数量/类型与 HUD 一致（至少 20 个样本）；
- 0 崩溃；单次查询 < 1 s。

### P1：扫描结果（只读 + 明确边界）

在 dossier 之上增加“扫描结果”端点：

- 只返回已存在的 marker / system map / save discovery；
- 每条带 `confidence`、`source`、`known/unknown`；
- 对“附近未发现传送门/古遗迹/货船/飞船”返回 `unsupported` 或“需要游戏内扫描/实验性实体搜索”，**不返回编造坐标**；
- `scan.instant` 保持“只加速 UI 扫描条，不写发现”；
- `scan.discover` 继续 `False`。

验收：

- 任何 `ok:true` 的结果都能在游戏内找到对应对象；
- “没有结果”必须是明确的 `empty/unsupported`，不是空数组冒充“扫完了”。

### P2：scan.discover（写发现，最后做）

只有在以下条件全部满足后才做：

1. 用 hook `cGcDiscoveryManager.SubmitDiscoveryData` 捕获并验证 manager 指针；
2. 用反射/MBIN 布局补全 `cGcDiscoveryData`（至少 `VP`、flags、owner 等；当前 `partial_struct` 不够）；
3. 单条写入在测试存档验证：发现列表 +1、重载后仍在、奖励行为符合预期、无额外货币异常；
4. 有完整备份/回滚；
5. 多人始终禁用。

在此之前，`scan.discover` 必须是 `False`，不能因为“能构造一个 `cGcDiscoveryData`”就开放。

### P3：portal warp（真正的传送门效果）

顺序必须是：

1. **只读捕获**：hook `cGcPortalComponent.Prepare/OnAttached`，缓存真实组件指针；读 `mPortalData.mUA/mTargetUA/mbActive/mWorldMatrix`；
2. **只读验证**：确认 `mUA` 与当前行星/建筑位置自洽，`mWorldMatrix` 合理；
3. **小步调用**：先对真实 portal 调用一次 `WarpPlayer`（目标就是它自己的 `mTargetUA`），观察是否崩溃/落点是否正确；
4. **目标设置**：保存原 `mTargetUA/mbActive`，写目标 UA，调用 `WarpPlayer`；
5. **读回**：`player_state.mLocation` 的 UA 必须等于目标；游戏内星系名/行星/biome 必须匹配；
6. **失败回滚**：恢复原 `mTargetUA/mbActive`；`/restore` 回到原位置；
7. **系统级跳转另走** `cGcSpaceshipWarp.WarpToDistantSystem`，不要用 portal 组件去模拟。

在 P3 完成前：

- `teleport.portal` 保持 `E_UNSUPPORTED`；
- 现有 `teleport` 可以保留，但 UI 必须写“写位置 + 本地重载，不是传送门”，并强制快照/回滚；
- 不要构造假 `cGcPortalComponent`（当前 `_portal_warp` 的裸 buffer 路线风险最高）。

### P4：离线任意行星生成（长期，非近期）

如果要做“不进入游戏也能知道任意星球物种/资源/建筑”：

- 需要复刻/调用 `cGcPlanetGenerator.GenerateCreatureRoles` / `GenerateCreatureSpawnData` / `Generate`；
- 需要 `cGcPlanetGenerationInputData`、`cGcSolarSystemGenerator.GeneratePlanetBiomes` 等完整生成链；
- 需要解决 `CreatureDataTable.mbin` 的字段/角色名映射（`starforge/creature.py` 已有部分）；
- 需要建筑放置/Voronoi 生成链，才能谈“传送门/古遗迹位置”；
- 这不是 1–2 个端点的事，不能作为“当前星球扫描”的前置。

---

## 8. 参考项目对照与本项目可复用点

| 项目 | 对本问题的价值 | 不能直接复用 |
|---|---|---|
| **NMS.py / NMSpy** | 提供 `cGcPlanetData`、`cGcPlanetInfo`、`cGcCreatureRoleData`、`cGcScanManager`、`cGcMarkerPoint`、`cGcPortalComponent`、`cGcDiscoveryManager` 的类型/偏移/函数 hook；`example_mods/instantScanning.py` 证明 `cGcBinoculars.UpdateScanBarProgress` 可 hook | 类型是特定 build 的；`cGcDiscoveryManager` 偏移未启用；`cGcDiscoveryData` 是 partial |
| **Gagarin_Titov** | 进程内 DLL + 引擎调用；`logCreatures/logDiscoveries/logPlanetProbe/logPlanetSearch`、`Scan planet`、传送前 `Stand on a planet` 等行为证明“进程内”是完整扫描/传送的可行路线；传送使用引擎函数而非裸写 | 闭源、版本绑定、有版本闸门；不能直接拿到源码/API；它的 UI 证据不等于我们的偏移可用 |
| **NMS-Super-Ship-Hunter** | 证明外部内存 + 数据模板写入的“最后一公里”可行；多候选/结构校验/回读的思想可复用 | 只改飞船 seed，不涉及扫描/portal；只接受首个命中的旧实现有缺陷 |
| **NMSCoordinates** | 保存文件改位置 + 重新加载的“冷传送”成熟路线；能列出已发现空间站/基地并传送；能清除 portal interference | 不是内存扫描；不是 live 附近扫描；必须重载存档，不能即时 portal warp |
| **NMS Companion** | 基地/同伴/飞船/多工具备份恢复；证明存档结构是稳定的跨版本接口 | 不是实时扫描；不读取附近实体；不能回答“附近有什么” |
| **NMS Save Editor / NMSE** | 发现记录/传送点/建筑数据的存档侧编辑参考；说明“发现”可以持久化 | 不是进程内；写发现仍有成就/奖励副作用；不应作为 live 扫描方案 |

**本项目可复用的关键结论**：

- 只读数据优先从**当前进程内存**拿（`PlanetData`、`ScanManager`、`SolarSystemMap`），因为存档没有“当前世界全部实体”；
- “已发现”从**存档**拿，因为存档是持久化的事实；
- “全部/附近未发现”只能靠**运行时生成/实体遍历/扫描事件**，没有捷径；
- “传送门效果”必须用**真实 portal 组件**，不能用一个写入位置 + 本地加载状态冒充。

---

## 9. 最终结论（给产品/实现者的短版）

1. **星球矿物/资源**：星球摘要 ✅ 只读；精确附近矿点 🔴。`ResourceHints` 在当前 NMSpy 不存在，实际字段是 `ExtraResourceHints`，别按旧名硬编码。
2. **动植物**：描述 ✅；`CreatureIDs` ✅；**全部物种** 🟡（读 `CreatureRoles/SpawnData` 并实机对照后才成立）；**已发现** ✅（存档）；任意行星离线全量 🔴/⛔。
3. **附近传送门/古遗迹/货船/飞船/建筑**：已存在 marker / 星系地图对象 / 已发现记录 🟡/✅；**附近未发现** 🔴；附近动态货船/NPC 飞船 🔴。`BuildingData` 是模板，不是坐标。
4. **直接传送门效果**：`cGcPortalComponent.WarpPlayer` 是正路但需要真实组件；`cGcSpaceshipWarp` 是系统级正路；当前 `写位置 + APPLOCALLOAD` 只是加载式近似，风险高，不能叫 portal。
5. **实现顺序**：只读 dossier → 只读扫描结果 → （验证后）scan.discover → （捕获真实组件后）portal warp。  
6. **不能假装完成**：`scan.discover`、`teleport.portal`、`附近未发现传送门/古遗迹`、`当前星球全部物种`、`离线任意行星物种/建筑`，都必须等到对应验收通过；未通过时返回 `unsupported`，不要返回 `ok:true` 或空列表。

---

## 附录 A：本文用到的关键字段速查

### A.1 行星

```text
cGcPlanetData (0x3AE0)
  CommonSubstanceID      TkID0x10        @0x33D0
  CreatureIDs            DynamicArray    @0x33E0  (TkID0x10)
  ExtraResourceHints     DynamicArray    @0x33F0  (cGcPlanetDataResourceHint)
  RareSubstanceID        TkID0x10        @0x3400
  UncommonSubstanceID    TkID0x10        @0x3430
  PlanetInfo             cGcPlanetInfo   @0x3548
  Name                   FixedString0x80 @0x3A4E
  SpawnData              cGcEnvironmentSpawnData @0x32D8
  BuildingData           cGcPlanetBuildingData   @0x3338
  GenerationData         cGcPlanetGenerationIntermediateData @0x3180
    CreatureRoles        cGcCreatureRoleDataTable @+0x00
      AvailableRoles     DynamicArray[cGcCreatureRoleData] @+0x00
      MaxProportionFlying f32 @+0x10
      SandWormFrequency  f32 @+0x14
      HasSandWorms       bool @+0x18
  SpawnData.Creatures    DynamicArray[cGcCreatureSpawnData] @+0x00
```

### A.2 扫描 / marker

```text
cGcSimulation
  mScanManager           cGcScanManager @0xF1B0
  mpSolarSystem          cGcSolarSystem* @0x25E090
  mWarp                  cGcSpaceshipWarp @0x25E0B0
  mCurrentUA             u64 @0x265B10

cGcScanManager
  mMarkerList            cGcMarkerList @0x2310
    maMarkerObjects      tk_vector[cGcMarkerPoint] @0x00

cGcMarkerPoint (0x2B0)
  mPosition              cTkPhysRelVec3 @0x20
  mCustomName            FixedString0x40 @0x58
  mCustomSubtitle        FixedString0x80 @0x98
  meBuildingClass        cGcBuildingClassification @0x138
  meType                 cGcMarkerType @0x291
```

### A.3 SolarSystem / portal

```text
cGcSolarSystem
  maPlanets              cGcPlanet[6] @0x2E30
  mSolarSystemMap        cGcSolarSystemMap @0x51BC20
    maAssociatedMapObjects cGcSolarSystemMapObject[0x40] @0x1520
  mPlanetGenerator       cGcPlanetGenerator @0x522B40
  mSolarSystemGenerator  cGcSolarSystemGenerator @0x523750
  mSpacePoiGenerator     cGcSpacePoiGenerator @0x523E30
  mSpaceStationNode      TkHandle @0x523E60

cGcSolarSystemMapObject (0xD0)
  meType                 cGcSolarSystemMapObjectType @0x00
  miIndex                i32 @0x08
  mVector                cTkVector3 @0x70
  mbIsActivated          bool @0xC9

cGcPortalComponent
  mPortalData            PersistentData @0x40
    mWorldMatrix         cTkMatrix34 @0x00
    mUA                  u64 @0x40
    mTargetUA            u64 @0x48
    mBuildingSeed        GcSeed @0x50
    mbActive             bool @0x60
    mbIsStoryPortal      bool @0x61
    mbIsActiveCommunityPortal bool @0x62
```

### A.4 发现 / 存档

```text
DiscoveryManagerData
  DiscoveryData-v1
    Store.Record[]       # 主记录
    Available[]          # 待上传/可用记录（语义待确认）
    Enqueued[]
    ReserveStore / ReserveManaged

Record
  DD.UA                  # 宇宙地址
  DD.DT                  # cGcDiscoveryType: SolarSystem/Planet/Animal/Flora/Mineral/...
  DD.VP                  # variation hashes
  DM.CN                  # 可选自定义名称
  OWS                    # 发现者/时间戳
  FL / RID / PTK         # flags / 记录 ID / 平台
```

### A.5 引用文件

- `starforge/starforge/agent/starforge_agent.py`：`_planet_info`、`_planet_scan_info`、`_portal_warp`、`teleport`、`scan`
- `starforge/starforge/live/agent_client.py`：`planet_scan`、`teleport_portal`
- `starforge/starforge/services/__init__.py`：`_HIGH_RISK_CAPABILITIES`、`live_capabilities`、`agent_call`
- `starforge/starforge/system.py`：`PLANET_FIELDS`（weather/flora/fauna/resources 需要游戏）
- `starforge/starforge/creature.py`：`role_names`、`role_table`、`capabilities`
- `NMS.py/nmspy/data/types.py`：`cGcPlanetGenerator`、`cGcScanManager`、`cGcScanEvent`、`cGcBinoculars`、`cGcPortalComponent`
- `NMS.py/nmspy/data/exported_types.py`：`cGcPlanetData`、`cGcPlanetInfo`、`cGcCreatureRoleData`、`cGcCreatureSpawnData`、`cGcSolarSystemMapObject`、`cGcDiscoveryData`
- `NMS.py/nmspy/data/enums/external_enums.py`：`cGcDiscoveryType`、`cGcMarkerType`、`cGcBuildingClassification`、`cGcCreatureTypes`
- `NMS-Shipwright/nms_procgen/locate.py`：`save_known_systems`（已示范读 `DiscoveryData-v1`）
- `analysis/01-Gagarin_Titov.md`：进程内引擎调用、`logCreatures/logDiscoveries/Scan planet`、传送前置条件
- `analysis/05-NMS-Super-Ship-Hunter.md`：外部内存 + 模板槽、多候选/回读
- `analysis/03-NMS-Shipwright-save.md`：存档字段树、`ShipOwnership`、`Pets`
- `analysis/10-能力清单与实机效果.md`：已明确的“生物离线不可能/需游戏进程”结论
