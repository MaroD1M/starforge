# 开源项目「按条件筛选星球」评估

> **范围**：只读研究。未修改业务代码，未启动/注入游戏进程，未写存档。
> **本机验证**：`<存档>`（`save.hg`，save Version 4746，Win|Final，ActiveContext=Main）。
> 文档只记录聚合统计与字段路径，**不记录真实种子、坐标、玩家名或账号 ID**。
> **标记约定**：
>
> | 标记 | 含义 |
> |---|---|
> | ✅ | 本机已实测（读代码/读存档/跑离线生成器） |
> | 🟡 | 高置信（上游源码/文档/交叉一致），但未在本机完整复跑 |
> | ⬜ | 未验证，需要更多存档/实机确认 |
> | ⛔ | 上游未公开源码或数据，无法验证 |

---

## 0. 结论先行

1. **最值得先做的不是「预测未发现星球」，而是「检索已经发现、但散落在存档里的星球」。**
   存档的 `DiscoveryManagerData → DiscoveryData-v1 → Store → Record[]` 已经包含 830 条行星发现记录；
   群系与「虫蚀」直接编码在每条记录的 `DD.VP[1]` 里，**不需要游戏、不需要 unicorn、不需要 PRNG 重实现**。
   （✅ 本机实测；与离线 `systemgen` 抽样 8/8 群系一致）
2. **nms-copilot 的筛选维度比想象中少**：只有 biome、infested、named、discoverer、distance/nearest、
   biome subtype（存档里实际取不到）。它没有哨兵、天气、资源、dissonant、经济、种族这些筛选。
   （🟡 源码：`crates/nms-query/src/find.rs`；`crates/nms-graph/src/extract.rs`）
3. **nms-core 不能替代 unicorn 做行星级筛选。** 它能精确/高置信地算系统级的星型、行星数、行星种子、
   经济/种族/冲突、名字；但**没有真实的行星群系算法**。`economy.js` 的 `pickBiome()` 是按星系颜色/
   银河类型加权的**统计抽样**，不是某个具体行星的真实群系。（🟡 源码与 README）
4. **APF 与 NMSSaveEditor 不能复用代码。** 前者源码未发布、仓库无 LICENSE；后者仓库只有二进制、
   无 LICENSE、无源码。只能借鉴产品/交互思路，不能复制代码、数据或逆向其二进制。
5. **建议继续用 unicorn 跑 `NMS.exe` 的生成器**，不要现在重写 Threefish/Skein PRNG：
   unicorn 是「对当前安装版本精确」的方案（0.039 s/系统，约 25 系统/秒），
   PRNG 重实现只能覆盖系统级字段，且游戏一更新就可能**静默失准**；unicorn 至少会**响亮地失败**。
6. **第一功能建议**：星图新增「已发现星球」页签，读存档、按群系/虫蚀/命名/发现者/距离筛选，
   支持排序、CSV、复用现有符文/传送入口。改动集中在 1 个新模块 + 1 个服务方法 + 1 个页签，
   不需要数据库迁移、不需要游戏目录、不写存档。

---

## 1. 存档内「已发现星球」检索

### 1.1 nms-copilot 做了什么

**项目定位**：Rust 写的本地「银河副驾」，直接读 `save.hg`，建立系统/行星/基地的实时索引；
CLI、REPL、MCP 三种入口共用同一查询引擎。许可证是 **MIT OR Apache-2.0**。
（`[参考] https://github.com/oxur/nms-copilot`）

**筛选维度（`find` / `export`）**：

| 维度 | 参数 | 数据来源 | 说明 |
|---|---|---|---|
| 群系 | `--biome Lush` | 存档 `DD.VP[1]` 低 16 位 | `GcBiomeType` 枚举 |
| 虫蚀 | `--infested` | 存档 `DD.VP[1]` bit 16 | 与「dissonant」不是同一个概念 |
| 已命名 | `--named` | 存档 `DM.CN` | 只对玩家改过名的行星/系统有效 |
| 发现者 | `--discoverer` | 存档 `OWS.USN`（系统级） | 大小写不敏感子串 |
| 距离 | `--within`、`--nearest` | 地址坐标计算 | 400 ly/ voxel；同 voxel 不同系统约 264.68 ly |
| 名字搜索 | `--name-pattern` | `DM.CN` | 行星名或系统名 |
| 群系子类型 | `biome_subtype` | 存档实际取不到 | 代码里保留字段，但 `VP` 不提供 |

证据：
- `crates/nms-graph/src/extract.rs` 的 `extract_biome_from_vp()` 明确写了
  `VP[0]=seed hash`、`VP[1]=biome/flags`：低 16 位是 `GcBiomeType`，bit 16 是 infested；
  `extract_seed_from_vp()` 取 `VP[0]`。
- `crates/nms-query/src/find.rs` 的 `FindQuery` 只有 `biome / biome_subtype / infested /
  within_ly / nearest / name_pattern / discoverer / named_only / from`。
- `docs/data-interchange.md` 的导出字段只有 `planet_name / biome / system_name / distance_ly /
  portal_glyphs / portal_emoji / coords_* / galaxy / discoverer / infested`。
- 地址与距离：`crates/nms-core/src/address.rs` 的 `distance_ly()`，`LY_PER_VOXEL = 400.0`，
  同 voxel 不同 SSI 用 `ROBBINS_CONSTANT * 400`。

**它的限制**：
- 没有哨兵、天气、资源、flora/fauna、dissonant、经济、冲突、种族筛选。
- 行星名只来自 `DM.CN`；绝大多数行星没有名字，不能从存档恢复「游戏自动生成的名字」。
- 群系子类型取不到；`BiomeSubType` 在存档路径里没有可靠来源。
- 发现者按**系统**记录取，不是按行星；同一系统内所有行星共用一个发现者。

**NMSSaveEditor 的定位（补充）**：
- 它的 README 只承诺「编辑存档里的原始 JSON」，并带发现列表截图；**没有文档化的 JSON 导出 API/CLI**。
- 仓库只有 `NMSSaveEditor.exe/jar/zip` 和文档，**没有 LICENSE、没有源码**；因此不能作为
  “导出 JSON 的依赖”，也不能复制/反编译它的二进制。
  （`[参考] https://github.com/goatfungus/NMSSaveEditor`；`[参考]` 仓库 contents API）
- 对我们的价值仅限于：确认「发现列表」这个产品形态存在，以及参考它展示发现者/时间的交互。
  真正的数据出口应该由我们自己的 `nms_save` 读 JSON 树来完成。

### 1.2 我们现有能力

#### 1.2.1 `nms_save` 能读到什么

`nms_save.open_save()` 返回完整、已反混淆的 JSON 树：
`[代码] NMS-Shipwright/nms_save/save.py:137-150`。
但**没有面向「行星发现」的高层 API**。目前唯一消费发现记录的是种子反查里的“已知星系”：

```python
# NMS-Shipwright/nms_procgen/locate.py:141-153
dm = readable.get("DiscoveryManagerData", {}).get("DiscoveryData-v1", {})
for r in (dm.get("Store", {}).get("Record") or []) + (dm.get("Available") or []):
    dd = r.get("DD", {})
    if dd.get("DT") == "SolarSystem" and dd.get("UA") is not None:
        ...
```

它只取 `SolarSystem` 的 `UA`，组成 `known_systems`；**不读 `Planet` 记录，也不读 `VP`/`DM`/`OWS`**。
`[代码] NMS-Shipwright/nms_procgen/locate.py:141-153`

我们的存档层只封装了船/库存/任务等：
`[代码] starforge/save/library.py:113-158`（`open_ships`）、
`[代码] starforge/save/extras.py`（库存/知识/基地等编辑）。
没有 `discoveries()` / `planets_discovered()` 之类的只读接口。

#### 1.2.2 存档 JSON 路径（本机实测）

```
save.hg
└─ DiscoveryManagerData
   └─ DiscoveryData-v1
      ├─ Store
      │  └─ Record[]                     ← 已完成的发现记录（3240 条）
      │     ├─ DD
      │     │  ├─ DT                     ← "Planet" / "SolarSystem" / "Animal" / ...
      │     │  ├─ UA                     ← 56 位打包地址（int 或 "0x..." 字符串）
      │     │  └─ VP[]                   ← 变长数组；Planet 的 VP 有 2 项
      │     ├─ DM
      │     │  └─ CN                     ← 可选，玩家给的名字（字符串）
      │     ├─ OWS
      │     │  ├─ LID / UID / USN        ← 本地 ID / 平台账号 ID / 显示名
      │     │  ├─ PTK                    ← "ST" / "PS" / ...
      │     │  └─ TS                     ← 发现时间（Unix 秒）
      │     ├─ FL
      │     │  ├─ C                      ← created 标志
      │     │  └─ U                      ← uploaded 标志（行星记录里不可靠）
      │     └─ RID                       ← 可选，重命名/上传记录 ID（不透明）
      ├─ Available[]                     ← 待上传/暂存记录（本机 10 条，含 1 条 Planet）
      │  ├─ DD
      │  └─ TSrec
      ├─ Enqueued[]                      ← 本机 0 条
      ├─ ReserveStore / ReserveManaged   ← 计数，不是行数
      └─ ...
```

另外，`BaseContext.PlayerStateData` 里还有：
- `VisitedSystems[]`：只到系统级，不含行星/群系；
- `UniverseAddress`：玩家当前位置；
- `PersistentPlayerBases[]`：基地名/地址，可作为「从基地算距离」的参考点（后续）。

#### 1.2.3 `Planet` 记录怎么解

本机 830 条 `Planet` 记录，`VP` 长度全部为 2（`[实测]`）：

| 字段 | 含义 | 解码 |
|---|---|---|
| `DD.UA` | 行星地址 | `planet_index = (UA >> 52) & 0xF`；`system_ua = UA & ~(0xF << 52)`；`galaxy = (system_ua >> 32) & 0xFF` |
| `DD.VP[0]` | seed/hash | 不用于筛选；不要展示为「种子」 |
| `DD.VP[1]` | biome + flags | `biome_index = flags & 0xFFFF`；`infested = bool(flags & 0x10000)` |
| `DM.CN` | 玩家命名（可选） | 只对改过名的记录存在；不要当成游戏生成名 |
| `OWS.USN` | 发现者显示名 | 空字符串表示未知；不要推断账号 |
| `OWS.TS` | 发现时间 | Unix 秒；0/缺失表示未知 |
| `FL.U` | 上传标志 | **不可靠**：本机 830 条 Planet 中只有 21 条有 `U=1`，567 条完全没有 `FL`；不要做「已上传」筛选 |

`biome_index` 对应关系（与 `NMS-Shipwright/nms_procgen/systemgen.py:31-32` 一致）：

| index | 名称 | 备注 |
|---|---|---|
| 0 | Lush | |
| 1 | Toxic | |
| 2 | Scorched | |
| 3 | Radioactive | |
| 4 | Frozen | |
| 5 | Barren | |
| 6 | Dead | |
| 7 | Exotic | nms-copilot 叫 `Weird`；我们是 `Exotic` |
| 8 | Red | |
| 9 | Green | |
| 10 | Blue | |
| 11 | Test | 跳过，不展示 |
| 12 | Swamp | |
| 13 | Lava | 旧 UI 叫 `Volcanic`，不一致 |
| 14 | Waterworld | 旧 UI 叫 `Ocean`，不一致 |
| 15 | Gas giant | 旧 UI 叫 `Gas`，不一致 |

**本机聚合实测（不含真实地址/种子/名字）**：

| 指标 | 值 |
|---|---|
| `Planet` 记录 | 830 |
| 去重后的 `(system_ua, planet_index)` | 814 |
| 行星序号分布 | 1:207、2:189、3:148、4:120、5:99、6:67 |
| 重复键 | 16 组，最多 2 条/组（需去重） |
| 涉及银河 | 6 个（0/1/2/3/9/18） |
| `DM.CN` 行星名 | 43 条 |
| `DM.CN` 系统名 | 19 条 |
| infested | 85 条 |
| 群系分布 | Lush 271、Frozen 88、Scorched 75、Toxic 73、Radioactive 72、Exotic 64、Barren 58、Dead 41、Red 20、Blue 19、Swamp 18、Green 18、Lava 5、Waterworld 4、Gas giant 4 |

**与离线生成器交叉验证**（`[实测]`）：
从 Euclid 抽样 8 个行星发现记录，按 `UA` 去掉行星位后调用 `systemgen.system(system_ua, planets=True)`，
比较 `planet_list[planet_index-1].biome` 与 `VP[1] & 0xFFFF`：**8/8 一致**。
其中 `biome 7` 在存档侧叫 `Weird`（nms-copilot 命名），我们生成器叫 `Exotic`；只是标签不同，索引相同。
这说明「存档里的群系」与「游戏生成器的群系」使用同一套枚举；本次 8 个样本一致，
足以支撑第一版，但仍需多版本回归（见 §1.3）。

**性能实测**（本机 Python，非打包环境）：
- `open_save()` + 反混淆：**0.787 s**；
- 从 3240 条记录里抽 830 条 Planet 并解码：**0.001 s**；
- 过滤 + 按距离排序：**0.0004 s**。
因此「每次打开页签重读存档」完全可接受；不需要先落库。

#### 1.2.4 存档里没有的字段

| 字段 | 是否存在 | 获取方式 | 备注 |
|---|---|---|---|
| biome | ✅ 有（VP） | 解码 | 精确，已验证 |
| infested | ✅ 有（VP bit16） | 解码 | 与 dissonant 不同 |
| 行星名 | 🟡 部分有（DM.CN） | 解码 | 只对改过名的 |
| 发现者 | ✅ 有（OWS.USN） | 解码 | 可能是其他玩家 |
| 发现时间 | ✅ 有（OWS.TS） | 解码 | 可能为 0 |
| 行星序号 | ✅ 有（UA bits52-55） | 解码 | 1..6 |
| 坐标/符文/距离 | ✅ 可由 UA 推导 | `glyphs.py` | 不需要游戏 |
| 哨兵 | ❌ 存档没有 | `systemgen` 单系统生成 | 需要 NMS.exe |
| dissonant | ❌ 存档没有 | `systemgen` 系统级判定 | 需要 NMS.exe |
| 天气/flora/fauna/资源 | ❌ 存档没有 | 只有 `planet.current` 能读**当前**行星 | 不能批量筛选 |
| 经济/冲突/星型 | ❌ 存档没有 | 可接 nms-core 或补生成器 | 当前 DB 里也是空 |
| biome subtype | ❌ 存档没有 | 需要生成器/游戏数据 | nms-copilot 也取不到 |
| 地形/颜色/水/环 | ❌ 存档没有 | 需要完整行星生成器 | APF 有，但闭源 |

### 1.3 结论与不确定项

**结论**：
- nms-copilot 的「已发现星球筛选」是**存档驱动**的，核心是 `VP[1]` 的位域解码；
  它没有依赖游戏 exe，也没有 PRNG。
- 我们的 `nms_save` **能读到原始记录**，但**没有语义化 API**；缺的不是数据，而是解码/去重/筛选层。
- 这套数据足以支撑第一功能；哨兵/天气/资源只能后续按需生成或读当前行星。

**不确定项**：
- ⬜ `VP[1]` 的位布局是否在更老/更新存档版本中稳定。本机只验证了 Version 4746；
  需要用 2–3 个不同版本存档做回归（至少 2002+ / Worlds / 当前）。
- 🟡 `infested` 与游戏内「dissonant/腐化」不是同一概念；UI 文案必须写「虫蚀（Infested）」，
  不能写「异常/腐化」。
- 🟡 `DM.CN` 只能证明「有玩家命名」，不能证明「所有行星名都能恢复」；
  nms-core 的 `save-import/README` 甚至认为发现记录通常不带名字。我们的 43 条说明它**有时**带，
  但不要向用户承诺「名字都有」。
- ⬜ `Available[]` 的语义（待上传？暂存？）未确认；本机只有 1 条 Planet。第一版可以读入但标 `pending`。
- 🟡 行星记录是否覆盖「所有到过的行星」未验证；它更像「已扫描/已记录」的子集，文案不要写「全部去过」。

---

## 2. 离线预测未发现的星球

### 2.1 nms-core（JS，MIT）

**它到底算什么**：
- 输入 portal code / UA + galaxy，走 `iprng.js` 的 Threefish/Skein 风格 64 位混合，
  得到 32 位 system seed；再用 `prng.js` 的 32 位乘法 PRNG 拉流。
- `system.js` 算：星型、行星数、卫星数、safe-start、紫星系/气态巨行星、经济类型、财富、冲突、
  主导种族、uncharted/abandoned/pirate、行星种子数组、系统名、行星名。
- `planet.js` 算：行星名（**作者明确说是“plausible guess”，不是真算法**）。
- `economy.js` 算：经济/冲突/种族的**显示词**、sell%/buy%、环的概率与样式；
  其中的 `pickBiome()` 是**按星色/银河类型加权的统计抽样**，不是具体行星的真实群系。

关键证据：
- `[参考] https://github.com/elegra1965-source/nms-core` README：
  “Game-accurate star type, planet count, black hole / Atlas placement, system/region/planet name generation…
  real economy/wealth/conflict/race/uncharted/abandoned/pirate derivation”。
  **没有**说能算 biome/weather/sentinels/resources。
- `[参考] README 的 Haven 校准`：post-Cosmos 系统各字段 99.7–99.9%；
  `system.js` 头部对 1000 系统 ground truth 的自述是 94.76–99.80%，并明确 planet-level data 不在覆盖范围。
- `[参考] planet.js` 头部：行星名是 “plausible-sounding GUESS, not real save data”。
- `[参考] economy.js` 头部：`pickBiome()` 的权重来自 wiki/Haven 统计，**不是**逐行星确定性算法；
  `BIOME_WEIGHTS_HAVEN` 是 110,688 颗行星的统计份额。
- `[参考] save-import/README.md`：它只读基地名，不读发现记录；并明确“planet/system discovery records
  never carry a player-given name”（与我们的 `DM.CN` 观察有出入，见 §1.3）。

**优点**：
- 纯 ES module，无 npm 依赖；系统级生成极快（BigInt 运算，非模拟器）。
- 系统级字段（星型、行星数、经济/种族/冲突）可离线、可复现、有较大语料验证。
- 可作为「没有游戏目录时的降级展示」或「系统级预筛」。

**缺点/风险**：
- **不能算行星级 biome/sentinel/weather/resources**；`pickBiome()` 只是分布抽样。
  用它预测“某颗行星是不是 Lush”会系统性出错，不能作为筛选依据。
- 行星名是猜测，不能当真实名字展示。
- 版本耦合是「算法/语料耦合」：游戏更新后不会报错，只会**静默失准**；
  需要重新对 corpus 验证。README 自己说 pre-Cosmos 只有 91–96%。
- `economy.js` 的概率表来自 decompiled MBIN / wiki 转录；许可证虽是 MIT，但**数据权利**有争议；
  不要直接复制这些表。
- `letter-map/` 约 3 MB，是名字生成语料；不要复制进我们的仓库。

### 2.2 ATLAS APF TURBO（C++，闭源）

**能确认的**：
- Windows 10/11 x64、AVX2；独立 exe；不需要游戏进程、不需要 Python/VS。
- 筛选维度非常全：biome、classification、sub-biome、terrain、colours、weather、water、resources、
  Sentinel conditions、system/moon structural filters、parent/moon relationship、body-count、
  result scope、constraint-aware filter choices、Randomise Anchor Region、分页、CSV、APFZ 归档。
- 声称 deterministic；对“生成值 vs 最终渲染值”有区分（例如 water palette vs 实际水色）。
- 仓库只放 README/CHANGELOG/issue 模板/Release，**源码与内部数据集未发布**。
  （`[参考] https://github.com/87pbvg6yrp-ctrl/atlas-apf-turbo`；仓库树无 LICENSE 文件）

**不能确认的**：
- 算法（是否也是 Threefish/Skein + 完整行星生成器）、版本耦合方式、准确率、速度数据。
- 许可证：**没有 LICENSE = 默认保留所有权利**；不能复制代码/数据，不能反编译其 exe。
- 只能借鉴**产品/交互**：约束感知的筛选器、结果范围选择、锚点区域随机化、分页/CSV。

**结论**：⛔ 不能作为代码/算法依赖；作为「筛选器 UX 的参考」有价值。

### 2.3 我们的 unicorn 方案

**现状**：
- `starforge/system.py` 通过 `nms_procgen.systemgen` 在 unicorn 里执行 `NMS.exe` 的星系生成器：
  `[代码] starforge/system.py:3`、`:97-125`、`:204-257`。
- 单系统行星数据来自 `systemgen._planets()`：
  `[代码] NMS-Shipwright/nms_procgen/systemgen.py:139-158`。
  它只读 `seed / biome / levels[4] / sentinels`；**weather/flora/fauna/resources 是空的**。
- 地址/版本适配靠 `exeaddr.py` 的字节签名：
  `[代码] NMS-Shipwright/nms_procgen/exeaddr.py:16-26`、`:39-42`。
  游戏补丁后签名不匹配会抛错，而不是静默错。
- 性能：文档实测 0.039 s/系统（热身），约 25 系统/秒：
  `[代码] starforge/system.py:3`。
- 许可：`unicorn` 是 **GPL-2.0**，当前 PyInstaller 打包存在合规讨论：
  `[代码] THIRD_PARTY_NOTICES.md:15`、`:20-34`。

**优点**：
- 对**当前安装版本**精确：biome、哨兵、dissonant、行星数、船池都来自游戏自己的代码。
- 已集成、已有扫描/索引/传送链路；不需要重新验证 PRNG。
- 失败模式明确：签名不匹配会报错，不会给用户“看起来对但其实是错”的结果。

**缺点**：
- 慢：25/s；扫 10 万系统要 ~67 分钟（单进程）。
- 版本耦合在「二进制签名」上；补丁后可能暂时不可用，需要更新签名。
- GPL-2.0 打包合规问题；如果未来要闭源分发，需要进程隔离/可选依赖/替换引擎。
- 不能批量给天气/资源/动植物；这些只有 `planet.current` 能读当前行星：
  `[代码] starforge/agent/starforge_agent.py:757-781`；能力表见
  `[代码] starforge/services/__init__.py:943`。

### 2.4 对比表

| 维度 | nms-core（JS） | APF（C++，闭源） | 我们的 unicorn |
|---|---|---|---|
| 行星级 biome | ❌ 只有统计抽样 | ✅ 声称有（无法验证） | ✅ 精确（当前版本） |
| 行星级 sentinels | ❌ | ✅ 声称有 | ✅ 精确 |
| weather/resources | ❌ | ✅ 声称有 | ❌（只有当前行星） |
| 行星名 | 🟡 猜测 | 未知 | 🟡 存档 `DM.CN` 才有 |
| 系统级经济/种族/冲突 | ✅ 98–99%（post-Cosmos 口径 99.7–99.9%） | 未知 | 🟡 种族有；经济/冲突当前 DB 为空 |
| 速度 | 未实测，理论上快 | 声称高，未实测 | 0.039 s/系统，约 25/s |
| 版本耦合 | 算法/语料，静默失准 | 未知 | 二进制签名，响亮失败 |
| 依赖 | 纯 JS/BigInt；名字需 3 MB 语料 | Windows/AVX2 exe | unicorn(GPL-2.0) + NMS.exe + PCBANKS |
| 许可 | MIT（部分表来自游戏数据） | 无 LICENSE，源码未发布 | GPL-2.0 依赖 + 我们的 MIT |
| 可复用性 | 可参考/可移植（保留 notice） | ⛔ 不可复制 | 已在用 |

### 2.5 建议

**继续用 unicorn，不引入 PRNG 重实现。** 理由：

1. 我们的筛选核心是**行星级 biome/sentinel**；nms-core/PRNG 不提供真实值，`pickBiome()` 只是抽样，
   不能拿来回答「这颗行星是不是 Lush」。没有它，重实现只解决系统级字段，收益不足以抵消验证成本。
2. 第一功能（存档已发现星球）**完全不需要生成器**；先把 830 条真实发现记录用起来，性价比最高。
3. 性能瓶颈如果出现，优先做：
   - 按系统缓存（同一系统多个行星只生成一次）；
   - 扫描任务复用/并行（注意 unicorn 单实例限制）；
   - 先按系统级条件过滤，再生成行星；
   - 只对用户选中的系统懒生成哨兵/dissonant。
4. 只有在以下条件同时成立时，才考虑 PRNG：
   - 需要 >1000 系统/秒的「全宇宙暴力搜索」；
   - 能接受系统级 98–99% 准确率、且不需要行星级 biome；
   - 有独立验证语料与法务对 `economy.js` 概率表/编译数据的结论。
   即使那时，也应该做**clean-room 重实现**，只参考公开算法事实，不复制上游代码/表。

**可选补充**：如果只是想在索引里补「经济/冲突/种族」列，nms-core 的 `systemAttributes()` 是参考；
但当前 DB 里 economy/conflict 全为空（`[实测]` 200 系统），而 UI 也没有这两列筛选，
所以这不属于第一优先级。

---

## 3. 筛选条件与排序

### 3.1 现有筛选器盘点

**扫描页**（`[代码] starforge/app/pages/galaxy.py:566-580`）：
群系、哨兵、种族、拦截机、最少行星、异常、扫描系统数。

**银河索引页**（`[代码] starforge/app/pages/galaxy.py:1061-1075`）：
群系、哨兵、种族、异常、最少行星、拦截机。

**服务/查询**（`[代码] starforge/galaxy.py:111-165`）：
`biome / sentinels / race / dissonant / min_planets / has_interceptor`，
固定 `ORDER BY scanned_at DESC`，`limit` 上限 500。

**当前问题（实测）**：

| 问题 | 证据 | 影响 |
|---|---|---|
| 群系词表不一致 | `INDEX_BIOMES` 有 `Weird/Volcanic/Ocean/Gas/Mega Exotic/Desert`（`app/pages/galaxy.py:29-32`），而 DB 实际值是 `Exotic/Lava/Waterworld/Gas giant/Red/Green/Blue`（`systemgen.py:31-32`） | 选这些选项查不到任何行 |
| `system.BIOMES` 过期 | `system.py:17-18` 只有 13 项，缺 Red/Green/Blue/Waterworld/Gas giant，且含 `Mega Exotic/Desert` | `capabilities()` 报错词表 |
| 天气/植被/生物列永远为空 | `galaxy.py:45-47` 有列，但 `systemgen` 不填；`[实测]` 1019 行星行中 weather/flora/fauna 非空数均为 0 | CSV/UI 显示空列，误导用户 |
| 经济/冲突永远为空 | `galaxy.py:30-31` 有列，但 `system.get()` 不返回；`[实测]` 200 系统非空数为 0 | 不能做经济筛选 |
| 没有距离/发现者/命名/虫蚀筛选 | `store.query()` 只支持 6 个键 | 已发现星球场景缺失 |
| 排序固定 | `galaxy.py:143` `ORDER BY scanned_at DESC` | 不能按距离/群系/发现时间 |
| 导出上限 500 | `services/__init__.py:753`、`web/routes.py:423` | 大结果被截断 |

> `docs/research/FEATURE-GAPS.md:96-108` 也已经记录「银河地图缺失」「离线天气/资源字段缺失」，
> 本文不重复造轮子；下面的建议是在这些缺口上做**可落地的最小闭环**。

### 3.2 数据可得性矩阵

| 筛选条件 | 存档发现（无需游戏） | 银河索引（已扫描） | 单系统生成（unicorn） | 当前行星 agent |
|---|---|---|---|---|
| 群系 biome | ✅ `VP` | ✅ `planets.biome` | ✅ | ✅ |
| 虫蚀 infested | ✅ `VP` bit16 | ❌ 未存 | ❌ 生成器不返回 | ❌ |
| dissonant/异常 | ❌ | ✅ `systems.dissonant` | ✅ | ❌ |
| 哨兵 | ❌ | ✅ `planets.sentinels` | ✅ | ✅ |
| 行星数 | ❌ | ✅ `systems.planets` | ✅ | ❌ |
| 拦截机 | ❌ | ✅ `systems.interceptor` | ✅ | ❌ |
| 种族 | ❌ | ✅ `systems.race` | ✅ | ❌ |
| 经济/冲突 | ❌ | ❌（列存在但空） | ❌（生成器不返回） | ❌ |
| 天气/资源/动植物 | ❌ | ❌ | ❌ | ✅ 仅当前行星 |
| 命名 | ✅ `DM.CN` | ❌ | ❌ | ❌ |
| 发现者 | ✅ `OWS.USN` | ❌ | ❌ | ❌ |
| 发现时间 | ✅ `OWS.TS` | 🟡 `scanned_at` 是扫描时间，不是发现时间 | ❌ | ❌ |
| 距我/距中心 | ✅ 由 UA 算 | ✅ 由 coords 算 | ✅ | ✅ |
| 星系 | ✅ UA bits32-39 | ✅ `systems.galaxy` | ✅ | ✅ |

### 3.3 建议增加的筛选条件（按优先级）

**P0（存档发现页，第一版就做）**：
- 群系（单选 + “全部”；后续可多选）
- 虫蚀（不限/是/否）
- 命名（不限/已命名/未命名）
- 发现者（文本子串，大小写不敏感）
- 星系（当前银河/全部/指定银河）
- 距我 ≤ N ly（以当前 `UniverseAddress` 为原点；可切换“距中心”）
- 排序：距我、群系、发现时间、行星序号、名字

**P1（索引/扫描页补齐）**：
- 距离排序与 `within` 过滤（距我/距中心）
- 群系词表统一（含 Red/Green/Blue/Waterworld/Gas giant/Lava）
- 结果表增加“距我/距中心”列
- 修复天气/资源空列：要么隐藏，要么标“需游戏内扫描”
- 经济/冲突：在数据源补齐前不展示

**P2（需要 unicorn/agent，按需懒加载）**：
- 哨兵、dissonant、拦截机、行星数：对选中的已发现系统调用 `systemgen`，补全详情；
- 天气/资源/动植物：只能对“当前行星”用 `planet.current`，不做批量筛选；
- 经济/冲突：若未来引入 nms-core 或补生成器，再作为系统级筛选。

**不建议**：
- 把 `biome subtype` 做成筛选（存档没有，nms-copilot 也取不到）；
- 用 `pickBiome()` 的统计结果冒充真实群系；
- 用 `FL.U` 做“已上传”筛选（数据不可靠）。

### 3.4 排序规则

建议统一为「服务端排序 + 稳定 tie-break」：

| 排序 | 主键 | tie-break |
|---|---|---|
| 距我 | `distance_ly` 升序 | galaxy、system_ua、planet_index |
| 距中心 | `distance_to_core_ly` 升序 | 同上 |
| 群系 | biome 名称 | distance、planet_index |
| 发现时间 | `OWS.TS` 降序（新→旧） | distance |
| 行星序号 | `planet_index` 升序 | distance |
| 名字 | locale-aware/不区分大小写 | distance |

距离公式（nms-copilot 的公开实现，`[参考] crates/nms-core/src/address.rs`）：
- 同一 system（同 voxel + 同 SSI）→ 0；
- 同一 voxel、不同 SSI → `ROBBINS_CONSTANT * 400 ≈ 264.68 ly`；
- 其他 → `sqrt(dx² + dy² + dz²) * 400`。
UI 上写「约」，不要假装是精确导航距离。

### 3.5 UI 组织

**推荐：在「星图」页新增一个「已发现」页签**，而不是再做一个独立页面。
现有页签已经有：行星 / 本星系船池 / 扫描结果 / 银河索引 / 地址工作台
（`[代码] starforge/app/pages/galaxy.py:311-425`）。

```
┌ 星图 ──────────────────────────────────────────────────────────────┐
│ 当前星系：… · 扫描：… · 索引：… · 地址：…                          │
│ [行星] [船池] [扫描结果] [★已发现] [银河索引] [地址工作台]           │
│                                                                    │
│ 群系[全部▾] 虫蚀[不限▾] 命名[不限▾] 发现者[______] 星系[当前▾]     │
│ 距我≤[50000]ly  排序[距我▾]  [刷新] [导出 CSV]   命中 271/830      │
│ ┌────────────────┬──────┬────┬────────┬──────┬────────┬─────────┐ │
│ │ 行星            │ 群系 │虫蚀│ 发现者  │ 距我 │ 发现时间│ 符文    │ │
│ ├────────────────┼──────┼────┼────────┼──────┼────────┼─────────┤ │
│ │ (未命名) #3     │ 茂盛 │ 否 │ 我      │ 0 ly │ 2026-… │ 3…      │ │
│ └────────────────┴──────┴────┴────────┴──────┴────────┴─────────┘ │
│ 详情：群系/虫蚀/发现者/时间/距离/符文  [复制符文][浮窗][传送]        │
└────────────────────────────────────────────────────────────────────┘
```

**布局理由**：
- 复用现有 `GalaxyFlowLayout` 的自动换行筛选条（`[代码] starforge/app/pages/galaxy.py:262-302`），
  窄窗口不会把中文压扁。
- 复用右侧详情面板和传送按钮（`[代码] starforge/app/pages/galaxy.py:433-473`）；
  只要行里带 `ua / planet_index / glyphs / coords / galaxy`，`_warp_target_for()` 就能工作
  （`[代码] starforge/app/pages/galaxy.py:121-155`）。
- 表格用 `QTableWidget`，行数据放 `Qt.UserRole`，与现有扫描/索引表一致
  （`[代码] starforge/app/pages/galaxy.py:1383-1399`）。
- 不在第一版做地图；地图是 P3（`docs/research/FEATURE-GAPS.md:107`）。
  如果要做，建议单独的 `QPainter` 2D 散点（x/z），颜色按群系，点击同步选中行；
  不引入 Three.js/Electron（`docs/archive/COMMUNITY-UI-ROADMAP-2026-11-18.md:103-104` 的结论仍然成立）。

**可借鉴的交互**：
- nms-copilot：`find --biome Lush --nearest 5` 的“先筛选、再最近 N 个”；
  `--from "基地名"` 的参考点；`last` 回忆上次查询；CSV/JSON 导出。
- APF：筛选器“约束感知”（当前选择下不可能的组合置灰）、结果范围（行星/卫星/系统）、
  锚点区域随机化、分页。
- NMSSaveEditor：发现列表 + 详情 + 时间/发现者的展示方式（但它闭源，不能抄代码）。

### 3.6 空态与错误

- 没有存档：明确“未配置存档”，给“去设置”入口；不要显示 0 条假装成功。
- 存档版本/字段不支持：显示“该存档的发现记录格式未识别”，保留原始记录数；不要猜。
- `VP` 缺失/长度 <2：该行群系显示“未知”，仍可按发现者/距离筛选。
- 行星序号不在 1..6：不显示传送按钮（沿用现有 `_planet_digit` 的保守策略）。
- 多银河：默认“当前银河”；切“全部”时在表里显示银河列，避免坐标混淆。

---

## 4. 许可与合规

> 以下是工程判断，不是法律意见；发布前应让法务复核。

| 项目 | 许可证 | 源码是否可见 | 能否参考算法 | 能否复制代码 | 能否复用数据文件 |
|---|---|---|---|---|---|
| **nms-copilot** | **MIT OR Apache-2.0**（README 明确） | ✅ Rust workspace | ✅ | ✅（保留 copyright/notice；Apache 还要 NOTICE） | ⚠️ 不要复制 `mapping_mbincompiler.json`；我们已有 Shipwright 的 mapping |
| **nms-core** | **MIT** | ✅ JS ES module | ✅ | ✅（保留 LICENSE 与 upstream notice） | ⛔ 不要复制 `letter-map/`（~3 MB 语料）、`economy.js` 的 decompiled 概率表、Haven 统计表 |
| **ATLAS APF TURBO** | **无 LICENSE 文件** | ❌ 只有 README/docs/Release | ⛔ 无法验证算法 | ⛔ 默认保留所有权利 | ⛔ 不要复制 Release/数据 |
| **NMSSaveEditor** | **无 LICENSE 文件** | ❌ 仓库只有 exe/jar/zip + 文档 | ⛔ | ⛔ 不要反编译/分发 | ⛔ 不要复制 jar/exe/截图资源 |
| **MBINCompiler** | GitHub 标记 **NOASSERTION**（自定义） | ✅ C# | 参考可以 | ⚠️ 不要复制 mapping 数据 | ⛔ mapping 数据来源复杂 |
| **hadsh/nms_namegen** | **MIT** | ✅ Python | ✅ | ✅（保留 notice） | ⚠️ 名字语料仍可能含游戏数据权利 |
| **Hello Games 游戏资产** | 版权归 Hello Games | — | — | ⛔ 不要复制 pak/MBIN/贴图/存档 | ⛔ 不要随包分发 |

**具体口径**：

1. **nms-copilot 可以复用代码**，但它的 `mapping_mbincompiler.json` 来自 MBINCompiler；
   MBINCompiler 不是标准 MIT/Apache。我们**不需要**再引入 mapping：Shipwright 已经提供
   `nms_save/mapping.py` / `data/mapping.json`（`THIRD_PARTY_NOTICES.md:7`）。
   如果参考它的 `extract_biome_from_vp()`，这是**位域事实**，可以 clean-room 重写；
   若直接复制函数，保留 MIT/Apache notice。
2. **nms-core 的代码是 MIT，但数据不是“纯代码”**：
   - `economy.js` 的 `ODDS / RING_CHANCE` 来自 decompiled `GCSOLARGENERATIONGLOBALS.GLOBAL.MBIN`；
   - `BIOME_WEIGHTS_*` 来自 wiki/Haven 统计；
   - `letter-map/` 是名字生成语料。
   这些**不要复制**。算法事实（例如“VP[1] 低 16 位是 biome”）可以独立重写。
3. **APF / NMSSaveEditor 只能“看产品”**：不能复制代码、不能反编译、不能把它们的 exe/jar
   放进我们的包。可以借鉴“筛选器怎么组织”“结果表怎么分页”“发现列表怎么展示”。
4. **我们的项目是 MIT**（`LICENSE`），但当前打包了 **GPL-2.0 的 unicorn**；
   `THIRD_PARTY_NOTICES.md:20-34` 已列出 A/B/C/D 四种方案。第一功能不新增 GPL 依赖，
   不会加重这个问题；如果未来要闭源分发，优先评估 D（独立进程）而不是把 GPL 代码抄进来。
5. **隐私**：存档里的 `OWS.USN/UID` 是玩家账号/显示名。UI 本地显示可以；
   日志、CSV、错误报告默认不要写 `UID`；文档/测试夹具不要放真实名字。
6. **游戏资产**：不要复制游戏 pak/MBIN/贴图；我们的图标/字体已有独立许可说明
   （`THIRD_PARTY_NOTICES.md`）。

---

## 5. 建议（可立即实现）

### 5.1 功能一（推荐第一）：存档「已发现星球」筛选器

**目标**：不启动游戏、不依赖 `NMS.exe`，直接读当前存档，按群系/虫蚀/命名/发现者/距离筛选
已经发现的行星，并能复制符文/传送。

**为什么先做**：
- 数据已经在存档里，且群系与生成器 8/8 一致（✅）；
- 0.8 s 读一次、1 ms 过滤，体验接近即时；
- 不动数据库、不动游戏进程、不写存档，风险最低；
- 直接补上 nms-copilot 最核心的「已发现星球检索」能力，且比它多“虫蚀/距离/命名”组合。

#### 改动点

| 层 | 文件 | 改动 |
|---|---|---|
| 新模块 | `starforge/discoveries.py` | `read(save_path=None)` 解码 `Store.Record` + `Available`；`query(rows, filters, sort, origin_ua, limit)`；`export_csv(rows)`；`distance_ly()`；`stats(rows)` |
| 服务 | `starforge/services/__init__.py` | `discoveries(...)`、`discoveries_export_csv(...)`；直接调用新模块（无需 `_internal` 子进程） |
| UI | `starforge/app/pages/galaxy.py` | 新增「已发现」页签；筛选条、结果表、详情/传送复用；`ensure_loaded`/页签切换时懒加载；CSV 按钮 |
| UI 组件 | 复用 `GalaxyFlowLayout`、`GalaxyTablePane`、`EmptyState` | 不新建页面 |
| 中文 | `starforge/zh.py` | 补 `Lava/Waterworld/Gas giant` 等 `BIOME_ZH`；统一 `Exotic/Weird` 别名 |
| 测试 | `tests/test_discoveries.py` | 合成存档字典：正常/缺 VP/重复/多银河/命名/发现者/虫蚀 |
| 可选 API | `starforge/web/routes.py` | `GET /discoveries`、`GET /discoveries/export.csv` |
| 可选 CLI | `starforge/__main__.py` | `starforge discoveries --biome Lush --infested --within 50000 --csv` |

#### 数据契约

```python
# 一行（示例字段，不含真实值）
{
    "ua": "0x…",              # 系统 UA（去掉行星位）
    "planet_ua": "0x…",       # 原始行星 UA（含行星位）
    "planet_index": 3,         # 1..6
    "galaxy": 0,
    "glyphs": "3…",            # glyphs_for_ua(ua, planet_index)
    "coords": "XXXX:YYYY:ZZZZ:SSSS",
    "biome": "Lush",           # 规范名
    "biome_index": 0,
    "infested": False,
    "name": "…" or None,       # 只来自 DM.CN
    "system_name": "…" or None,# 只来自 SolarSystem 的 DM.CN
    "discoverer": "…" or None, # OWS.USN
    "discovered_at": 179… or None,
    "source": "save",          # 或 "save-pending"（Available）
}
```

实现要点：
- `planet_index = (ua >> 52) & 0xF`；`system_ua = ua & ~(0xF << 52)`；`galaxy = (system_ua >> 32) & 0xFF`。
- `flags` 可能是 int 或 `"0x…"` 字符串；两种都解。
- `biome_index == 11`（Test）跳过；未知 index 显示“未知”，不猜。
- `Store.Record` 与 `Available` 合并；按 `(system_ua, planet_index)` 去重，
  优先 `Store`、同源取 `OWS.TS` 更新的一条；`Available` 标 `save-pending`，发现者可能为空。
- 系统名/发现者：先建 `SolarSystem` 的 `(system_ua -> DM.CN/OWS.USN)` 映射；
  行星自己的 `DM.CN/OWS.USN` 优先，缺失时回退到系统级。
- 距离：默认以当前 `UniverseAddress` 为原点；无存档位置时按“距中心”或禁用距离筛选。
- 全部在内存完成；不做 SQLite 迁移。若后续数据量 >5 万，再加可选缓存（key = path+mtime+size）。

#### 验收标准

1. **无游戏也能用**：`game_dir` 为空 / `NMS.exe` 不存在时，打开「已发现」页签不抛
   `GameFilesMissing`；能显示记录数和群系分布。
2. **正确性**：本机存档 830 条 Planet、814 个去重键；`Lush=271`、`infested=85` 等聚合与
   §1.2.3 一致（以当前存档为准；测试用固定 fixture，不用实时值断言）。
3. **交叉验证**：抽 8 个 Euclid 系统，`biome_index` 与 `systemgen.system()` 一致（8/8）；
   该测试可在有游戏目录时跑，缺游戏时 skip。
4. **筛选组合**：群系 + 虫蚀 + 命名 + 发现者 + 距我 ≤ N + 星系 同时生效；
   排序稳定；结果数/空态正确。
5. **导出**：CSV UTF-8，表头包含 `planet_index,biome,infested,name,discoverer,distance_ly,glyphs,coords,galaxy`；
   不包含 `UID`；空结果也有表头。
6. **传送**：选中行后 `_warp_target_for()` 能生成合法 12 位符文；行星序号非法时按钮禁用；
   传送仍走现有二次确认/高风险路径，不新增自动传送。
7. **无副作用**：存档 mtime 不变；没有写文件；没有启动游戏/agent 进程。
8. **性能**：本机 830 条，页签首次加载 ≤2 s（worker 线程），筛选/排序 ≤50 ms。

#### 风险与缓解

| 风险 | 缓解 |
|---|---|
| `VP` 位布局随版本变化 | 记录 `Version`；解码失败标“未知”；加多版本 fixture；必要时按版本分支 |
| `DM.CN` 名字不完整 | UI 明确“仅显示玩家命名”；未命名显示 `#序号`；不生成假名 |
| 发现者可能是他人/隐私 | 只本地显示；CSV 默认不含 UID；日志脱敏 |
| `Available` 语义不明 | 标 `pending`；不参与“已上传”判断；去重优先 Store |
| 重复记录/群系冲突 | 按 `(system_ua, planet_index)` 去重；冲突时保留 Store/最新 TS，并打日志 |
| 多银河混排 | 默认当前银河；全部时显示银河列；距离只在同银河有意义 |
| 0.8 s 解码卡 UI | `run_worker` 后台加载；页签切换不重复解码，提供“刷新” |
| 传送是高风险写操作 | 复用现有确认/回滚；只生成目标，不自动执行 |

### 5.2 功能二：银河索引的「距离排序 + 群系词表修复」

**目标**：让已扫描索引也能按距离/群系稳定筛选，并修掉“选了查不到”的词表 bug。

**改动点**：
- `starforge/system.py:17-18`：`BIOMES` 改为与 `systemgen.py:31-32` 一致的 16 项
  （含 Red/Green/Blue/Waterworld/Gas giant；Test 可保留但不展示）。
- `starforge/app/pages/galaxy.py:29-32`：`INDEX_BIOMES` 从规范常量生成；
  `Weird→Exotic`、`Volcanic→Lava`、`Ocean→Waterworld`、`Gas→Gas giant` 作为别名；
  移除 `Mega Exotic/Desert` 或映射到 `Exotic/Barren`（需产品确认）。
- `starforge/galaxy.py:111-165`：`query()` 增加 `within_ly`、`origin_ua`、`sort`；
  用 `coords` 或 `ua` 计算距离；`ORDER BY` 白名单，禁止拼接用户输入。
- `starforge/app/pages/galaxy.py:410-414`：索引表增加“距我/距中心”列；
  `_fill_index` 写入数值排序键。
- `starforge/services/__init__.py:745-766`、`web/routes.py:403-473`：CSV/查询参数同步；
  `limit` 上限从 500 提高到可配置（或分页）。
- 天气/资源空列：在 UI/CSV 中隐藏，或标注“需游戏内扫描”；不要继续输出永远为空的列。

**验收**：
- 选 `Lava/Waterworld/Gas giant/Red/Green/Blue` 能查到 DB 中已有行；
- 选 `Weird/Volcanic/Ocean/Gas` 作为别名也能查到对应行；
- 索引结果按距离升序，tie-break 稳定；
- CSV 不再出现全空 weather 列（或明确标注）；
- 现有 200 系统/1019 行星索引不迁移、不丢数据。

**风险**：旧 DB 里已有 `Exotic/Lava/...` 值；别名只做查询层映射，不要批量改库；
`Mega Exotic/Desert` 的语义需要产品确认，别强行合并。

### 5.3 功能三（可选，P2）：已发现 + 索引合并视图 / 最近 N 个 / 轻量地图

**目标**：同一张表里同时看「存档已发现」和「扫描索引」，去重、标来源；
支持“最近 N 个”和 2D 散点图。

**改动点**：
- `starforge/services/__init__.py`：`discoveries(..., include_index=True)` 合并；
  以 `(ua, planet_index)` 为键；存档优先 biome/infested/name/discoverer，
  索引补 sentinels/dissonant/planets/race/interceptor；冲突时标 `conflict=True`。
- `starforge/app/pages/galaxy.py`：数据源下拉「已发现 / 索引 / 合并」；
  表增加“来源/哨兵/异常”列；排序/筛选对合并后的行生效。
- 新组件 `starforge/app/widgets/galaxy_map.py`：`QPainter` 画 x/z 散点；
  颜色按群系；点击选中行；只画当前银河；支持缩放/拖动可后置。
- `starforge/galaxy.py`：可选 `distance_ly` 辅助函数（或放 `discoveries.py` 复用）。

**验收**：
- 同一行星在两边都有时只出现一次，来源标“合并”；
- `nearest 5` 返回距离最近的 5 条，跨来源排序正确；
- 地图点与表格选中同步；无结果时显示空态；
- 不影响现有扫描/索引/传送。

**风险**：合并口径（以谁为准）需要产品定义；地图是 P3，不要为了它拖慢第一功能。

### 5.4 可借鉴但暂不做

| 事项 | 来源 | 为什么暂不做 |
|---|---|---|
| 重写 Threefish/Skein + 完整行星生成 | nms-core | 只能到系统级；行星 biome 无真实算法；版本静默失准；验证成本高 |
| 全宇宙暴力搜索（APF 式） | APF | 闭源；unicorn 25/s 不够；需要完整行星生成器/大量算力 |
| 天气/资源/动植物筛选 | APF | 存档没有；agent 只能读当前行星；不能批量 |
| biome subtype/地形/颜色/水/环筛选 | APF/nms-core | 存档没有；需要完整生成器；优先级低 |
| 路线规划/TSP/最近邻 | nms-copilot | 有价值，但和“筛选”是两个功能；先有结果集再谈路线 |
| MCP server / live save watch | nms-copilot | 架构级；当前先做只读页签 |
| 社区坐标 CSV 导入 | nms-copilot | 需要来源/许可/去重策略；先把本地发现做好 |
| 全屏/3D 银河地图 | nms-copilot/APF | 现有结论是“先表格后地图”；P3 |
| 发现记录写回/改发现者/改名字 | NMSSaveEditor | 高风险写操作；没有明确需求 |
| 多存档/多账号 atlas | nms-copilot | 当前单存档足够；多账号涉及隐私/缓存 |
| 经济/冲突/种族补全 | nms-core | 当前 DB 空列，但 UI 没消费；等有明确筛选需求再做 |

---

## 6. 不确定项与验证计划

| # | 假设 | 置信度 | 验证方式 |
|---|---|---|---|
| 1 | `VP[1] & 0xFFFF` = GcBiomeType，bit16 = infested | ✅ 本机 830/830 可解；8/8 与生成器一致 | 再取 2 个不同版本存档；抽 20 系统交叉验证 |
| 2 | 行星序号在 UA bits52-55，1..6 | ✅ 本机 830 条全部 1..6 | 多存档验证；异常值跳过 |
| 3 | `DM.CN` 是玩家命名，不是游戏生成名 | 🟡 43 条行星/19 系统；与 nms-core 说法有出入 | 在游戏内对照一个改名行星；不要承诺“全部名字” |
| 4 | `infested` 与 `dissonant` 不同 | 🟡 nms-copilot 命名 + 位域 | 游戏内找一颗 infested 行星，对照 UI 文案 |
| 5 | 400 ly/voxel，同 voxel 不同 SSI ≈264.68 ly | 🟡 nms-copilot 源码 | 用已知两地距离对照游戏星图；UI 标“约” |
| 6 | `Available[]` 是待上传/暂存 | ⬜ 本机 10 条，含 1 Planet | 存档前后对比；或查社区文档 |
| 7 | 行星发现记录覆盖“所有到过行星” | ⬜ 830 vs 512 visited systems | 游戏内统计对照；文案写“已记录” |
| 8 | nms-core 系统级准确率 98–99%（post-Cosmos 99.7–99.9%） | 🟡 上游自述 | 用本机已知系统抽样；不用于行星级 |
| 9 | APF 算法/准确率 | ⛔ 源码未发布 | 无法验证；只借鉴 UX |
| 10 | 经济/冲突可从 nms-core 补 | 🟡 上游自述 | 先不做；若做，需独立语料验证 |
| 11 | 天气/资源只能读当前行星 | ✅ agent 代码 `planet.current` | 不需要额外验证；不要做批量 |

---

## 7. 参考资料

**nms-copilot**
- README：https://github.com/oxur/nms-copilot
- 行星发现 → biome/infested：https://github.com/oxur/nms-copilot/blob/main/crates/nms-graph/src/extract.rs
- 查询维度：https://github.com/oxur/nms-copilot/blob/main/crates/nms-query/src/find.rs
- 导出字段：https://github.com/oxur/nms-copilot/blob/main/docs/data-interchange.md
- 距离公式：https://github.com/oxur/nms-copilot/blob/main/crates/nms-core/src/address.rs
- 许可证：MIT OR Apache-2.0（README / LICENSE-MIT / LICENSE-APACHE）

**nms-core**
- README：https://github.com/elegra1965-source/nms-core
- 系统生成：https://github.com/elegra1965-source/nms-core/blob/main/system.js
- 经济/群系抽样：https://github.com/elegra1965-source/nms-core/blob/main/economy.js
- 行星名：https://github.com/elegra1965-source/nms-core/blob/main/planet.js
- 存档导入说明：https://github.com/elegra1965-source/nms-core/blob/main/save-import/README.md
- 许可证：MIT（LICENSE，含第三方/游戏数据说明）

**ATLAS APF TURBO**
- README：https://github.com/87pbvg6yrp-ctrl/atlas-apf-turbo
- 仓库树（无 LICENSE、无源码）：https://api.github.com/repos/87pbvg6yrp-ctrl/atlas-apf-turbo/git/trees/main?recursive=1

**NMSSaveEditor**
- README：https://github.com/goatfungus/NMSSaveEditor
- 仓库内容（只有二进制/文档，无 LICENSE/源码）：https://api.github.com/repos/goatfungus/NMSSaveEditor/contents/
- FAQ：https://github.com/goatfungus/NMSSaveEditor/blob/master/FAQ.md

**其他**
- MBINCompiler（license 标记 NOASSERTION）：https://github.com/monkeyman192/MBINCompiler
- hadsh/nms_namegen（MIT）：https://github.com/hadsh/nms_namegen
- 我们自己的许可/第三方说明：`LICENSE`、`THIRD_PARTY_NOTICES.md`

---

## 8. 最终建议（一句话版）

**先做「存档已发现星球」只读筛选器：它把 830 条真实记录、15 种群系、虫蚀、发现者、距离
一次性变成可查表，不需要游戏、不需要数据库迁移、不写存档；nms-core 的 PRNG 和 APF 的全量预测
都不是这个需求的必要条件。**
