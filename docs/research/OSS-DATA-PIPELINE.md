# 开源内容解算 / 模型 / 数据 API 评估

> 研究时点：2026-11-22。范围：只读阅读本仓库代码与上游 README/许可/源码结构；未启动游戏、
> 未注入游戏进程、未改业务代码、未把任何游戏资产或上游数据写入仓库。
> 本机游戏 build：**185034**（`NMS.exe` 的 `FileVersion`，见 `[代码] starforge/live/build.py:96-115`）。
>
> 标记约定：
> - `[代码]` 本仓库文件与行号；
> - `[参考] URL` 上游 README / 许可 / 源码；
> - `[实测]` 本次实际调用 GitHub API、上游 HTTP API 或读取本机文件得到的结果；
> - `🟡` 高置信推断；`⬜` 未验证；`⛔` 需要逆向或实机才能继续。

---

## 0. 结论摘要

1. **许可证比旧研究更细，不能一概写“MIT/NOASSERTION”。**
   - HGPAKtool：**MIT**；我们已经在用。
   - MBINCompiler / libMBIN：`LICENSE.md` 正文是 **LGPL-3.0**（GitHub API 因文本识别显示
     `NOASSERTION/Other`）。旧文档 `CREATURE-SEARCH.md` 的“NOASSERTION（自定义）”应更正为
     **LGPL-3.0，按弱传染库对待**。
   - nms-archive：仓库标注 **GPL-3.0**，但 README 同时写明“所有游戏文件归 Hello Games 所有”。
     **GPL 不能给游戏资产授权**；其中的 MBIN/MXML 仍不能进我们的 MIT 仓库。
   - NMSDK、nms-ship-customizer、AssistantNMS/WebApi：**没有 LICENSE 文件**（GitHub API
     `license = null`）→ 默认保留所有权利，代码/数据都不能复制。
   - Coordinate-Converter、nms-items-interface、AssistantNMS/App 与 WebApp：**GPL-3.0**；
     只能参考算法/交互，不能复制代码或数据。
2. **可复用的是“算法、格式、坐标数学、产品结构”，不是上游数据。**
   坐标/符文换算、`descriptor → scene → geometry → glTF` 的流程、版本来源记录与失败关闭策略，
   都可以用自己的代码重写；pak/MBIN/MXML/DDS/FBX/OBJ、上游导出的 JSON/FBX、游戏表数据，
   一律不进仓库，只在玩家本机运行时从自己的游戏目录提取。
3. **投入产出最高的落地点是“地址工作台补坐标/符文双向换算”**，不是 3D。
   这是 `FEATURE-GAPS.md` 已记录的 P2 缺口（`坐标文本解析`），纯数学、无资产、无许可风险，
   0.5–1 天可验收；做完直接提升“找船/找生物 → 分享地址 → 传送”的闭环。
4. **生物/工具 3D 的技术路线是通的，但都依赖本机游戏数据 + 版本探针。**
   我们的 `gltf.py` / `render.py` 与模型类型无关；`model3d._scene_meshes` / `_geometry` 是通用件；
   缺的是“描述符 → 场景节点名”的映射（生物）和“工具种子/类型 → 场景/描述符”的入口（工具）。
   NMSDK、NMSCD Creature-Builder 只能证明“整只场景导入 + 按描述符显隐”可行，代码/资产都不可用。
5. **飞船拼装不需要 nms-ship-customizer。**
   它已退化为一个 15 MB 的单文件 three.js 实验页 + 跳转 `nms.center`，无 LICENSE；
   我们的 Shipwright `model3d` + `paint.look` + Gagarin `catalog.txt` 已经是更完整的实现。
6. **内容百科可以接 AssistantNMS 作为“可选在线数据源”，但不能作为离线依赖。**
   API 实测可用（`api.nmsassistant.com`），但 WebApi 仓库无许可、响应没有游戏版本字段，
   且条目 ID 覆盖不完整；离线必须明确显示“未收录”，不能拿旧数据冒充当前版本。

---

## 1. 上游项目逐项评估

### 1.1 总表

| 项目 | 解决什么 | 许可（本次核实） | 是否含游戏资产/上游数据 | 我们的结论 |
|---|---|---|---|---|
| [HGPAKtool](https://github.com/monkeyman192/HGPAKtool) | 解包 NMS 5.50+ 的 `.pak` | **MIT** `[实测]` GitHub API + README | 工具本身不含；解出的内容含 | **继续用**（已在 `THIRD_PARTY_NOTICES.md`） |
| [MBINCompiler](https://github.com/monkeyman192/MBINCompiler) / libMBIN | MBIN ↔ MXML、结构定义、`mapping.json` | **LGPL-3.0**（`LICENSE.md` 正文）`[实测]`；GitHub 显示 Other | 仓库含测试数据/结构定义；发布包含 `mapping.json` | **只参考字段名/结构，不 vendor 代码或 DLL** |
| [NMSCD/nms-archive](https://github.com/NMSCD/nms-archive) | 各版本 MBIN/MXML 归档 | 仓库 **GPL-3.0**；README 明确游戏文件归 Hello Games | **是**（MBIN/MXML；README 说不含几何/贴图/动画/声音） | **只作人类可读参考**；不下载进仓库、不做自动数据源 |
| [NMSDK](https://github.com/monkeyman192/NMSDK) | Blender 导入/导出 NMS 场景与模型 | **无 LICENSE**（`license = null`）`[实测]` | 代码含游戏格式解析；示例/测试数据也按无许可处理 | **只参考流程**；不复制代码/资产 |
| [nms-ship-customizer](https://github.com/MetaIdea/nms-ship-customizer) | 网页版飞船拼装 + 3D | **无 LICENSE** `[实测]` | 15 MB 单文件实验页，含部件/颜色/种子输入 | **不集成**；用我们自己的 Shipwright |
| [NMSCD/Coordinate-Converter](https://github.com/NMSCD/Coordinate-Converter) | 符文 ↔ 存档坐标 | **GPL-3.0** `[实测]` | 无游戏资产；纯换算 | **只参考数学**；重写 |
| [AssistantNMS](https://github.com/AssistantNMS)（App/WebApp/WebApi） | 物品/配方/百科 API 与客户端 | App/WebApp **GPL-3.0**；WebApi **无 LICENSE** `[实测]` | App 数据来自游戏文件；API 返回派生数据 | **可选在线源**；不复制、不批量缓存 |
| [rdlu/nms-items-interface](https://github.com/rdlu/nms-items-interface) | 物品/配方/传送门查询（Web/TUI/MCP） | **GPL-3.0** `[实测]` | 仓库提交了派生 `data/*.json`（来自游戏表） | **只参考产品/数据管线**；不导入数据 |
| [NMSCD/Creature-Builder](https://github.com/NMSCD/Creature-Builder) | 生物部件选择 + 整只模型显隐预览 | 前文已核实：**无 LICENSE** | 含 `IPetData.json`、FBX/OBJ/DDS | **只参考思路**；不复制 |

### 1.2 HGPAKtool：pak 解包

- README 明确：**只支持 NMS 5.50（Worlds Part II）之后的 `.pak`**；PC 平台不需要 Oodle，
  Switch 才需要额外 DLL。`[参考] https://github.com/monkeyman192/HGPAKtool`
- 我们是 MIT 项目，HGPAKtool 也是 MIT；当前以子进程/库方式使用，许可边界干净。
- 对 build 185034：pak 容器格式仍是 5.50+ 一代，**大概率可直接读**；但仍应在运行时
  用“列出已知文件”做探针，失败就降级，不能假设。
- 本仓库使用点：`[代码] starforge/creature.py:339-345`、`starforge/glyphs.py:192-196`。

### 1.3 MBINCompiler / libMBIN：MBIN ↔ MXML

- `LICENSE.md` 正文是 **GNU LGPL v3**；README 说明：
  - 每次游戏更新都可能破坏 MBIN 格式，所以 **MBINCompiler 版本与游戏版本强绑定**；
  - `MBINCompiler.exe version <file>` 可以读出某个 MBIN 是用哪个版本编译的；
  - Worlds Part 2 之后改为 MXML（给游戏用时再改名 EXML）；
  - 开发者可单独使用 `libMBIN.dll`，结构定义是 C# 类。`[参考] https://github.com/monkeyman192/MBINCompiler`
- **许可含义**：LGPL 允许“作为独立库动态链接 + 提供源码/替换方式”，但不允许把其代码
  复制进 MIT 源码。我们已有自己的 MBIN 解析（`nms_procgen/mbin.py`，MIT），所以正确做法是：
  - 把 MBINCompiler 当“字段名/结构文档”参考（`GcCreatureData`、`GcResourceElement` 等）；
  - 如确需 MXML，作为**用户自装的外部命令行工具**调用，不打包、不静态链接；
  - 不把 `libMBIN.dll` 或 `mapping.json` 复制进仓库。
- 旧研究写“NOASSERTION（自定义）”不准确：GitHub API 仍报 `NOASSERTION`，但文件正文是
  LGPL-3.0。本文以文件正文为准。

### 1.4 nms-archive：版本归档

- 仓库按资料片分目录：`1.03-RELEASE` … `7.06-COSMOS-05.October.2026`。
  `[实测]` 顶层列表最新到 **7.06-COSMOS（2026-10-05）**，没有 7.10/7.14 目录。
- README 原文：
  > This repo does not contain model geometries, sounds, textures, animations, compiled shaders, language files.
  > **All of these game files are the property of Hello Games.**
  `[参考] https://github.com/NMSCD/nms-archive`
- 目录里确实有 `MODELS/`、`SCENES/`、`TEXTURES/`，但按 README 是 MBIN/MXML 定义文件，
  不是 DDS/几何二进制。它适合用来“看某个版本有没有某个描述符/路径”，不适合作为运行时数据源。
- **GPL-3.0 只覆盖仓库中可受版权保护的部分；游戏文件的权利仍归 Hello Games。**
  因此不能因为仓库是 GPL 就把 MBIN/MXML 当自由数据打进 MIT 仓库。
- 版本风险：最新归档是 7.06（2026-10）；同期上游提取记录（nms-items-interface 的
  `source.json`）是 build 180836，早于本机 185034（见 §5.1）；**不能假定结构同版**。

### 1.5 NMSDK：Blender 场景导入

- README/文档说明：
  - 通过 Blender 的 `File > Import` 导入 `*.SCENE.MBIN`；
  - 会导入场景引用的**所有组件**（大场景可能加载几分钟）；
  - 导入功能仍是 beta，主要问题是 NMS 的自定义 shader；
  - 导出依赖 MBINCompiler，且要求与游戏版本匹配。
  `[参考] https://github.com/monkeyman192/NMSDK`、`docs/importing/importing.md`
- **许可**：仓库没有 LICENSE 文件，GitHub API `license = null` → 默认保留所有权利。
  不能复制其 Python 代码、场景解析器或导出逻辑。
- 对我们的价值：证明“整只场景 + 引用子场景”是一条可行路径；我们的
  `model3d._scene_meshes` 已经做同样的事，且是 MIT。**不需要引入 Blender。**

### 1.6 nms-ship-customizer：飞船拼装

- `[实测]` 仓库 `index.html` 现在只做 302 跳转：
  `window.location.href = "https://nms.center"`。
- `Experiments/ShipCustomizer3DView.html` 是一个 **15,017,853 B** 的单文件实验页；
  前 300 KB 可见：
  - `Shiptype` 下拉、`Parts` 列表、`Seed` 输入、`Colorgroup` 与一组颜色按钮；
  - 内嵌 three.js（minified）。
  这说明它确实是“船型 + 部件 + 种子 + 配色”的实验，但：
  - **没有 LICENSE**，不能复制代码/部件表/颜色表；
  - 不是库、没有可复用的数据模型；
  - 已停止维护并跳转到 `nms.center`。
- 我们的对照物应是自己的 `NMS-Shipwright/nms_procgen/model3d.py`（MIT）与
  Gagarin `catalog.txt`（玩家本地游戏数据）：
  - 已实现 seed → 部件选择 → 场景引用 → 几何 → 贴图 → glTF/PNG；
  - `paint.look` 已处理涂装；
  - `catalog.py` 已解析 8 船型 / 543 组 / 1430 选项。
  **结论：不集成 nms-ship-customizer；最多把 nms.center 当交互参考。**

### 1.7 Coordinate-Converter：符文/坐标

- `[实测]` 源码只做两件事：
  1. 12 位 glyphs → 存档坐标 `{VoxelX, VoxelY, VoxelZ, SolarSystemIndex}`；
  2. `XXXX:YYYY:ZZZZ:SSSS`（19 字符）→ glyphs。
- 它**不处理银河（galaxy/reality）**，且反向生成时把行星位固定写成 `0`；
  这正好是我们地址工作台可以做得更完整的地方。
- 许可 GPL-3.0；换算常数是公开数学事实，可以自己重写，但不能复制其 TS 代码。

### 1.8 AssistantNMS：在线物品/配方 API

- 组织下仓库许可（`[实测]` GitHub API）：
  - `App`、`WebApp`、`WebComponents`：**GPL-3.0**；
  - `WebApi`：**无 LICENSE**（`license = null`）。
- API 实测（2026-11-22）：
  - `GET https://api.nmsassistant.com/ItemInfo/GameId/ANTIMATTER/en` → **200**，
    返回 `name / group / description / baseValueUnits / maxStackSize / colour / usages` 等；
  - `GET https://api.nmsassistant.com/ItemInfo/GameId` → **200**，本次返回 **3,340** 个 GameId；
  - `ANY_FISH` → **200**（说明不是只停在 2019 年的数据）；`SALVAGED_DATA` → **400**
    （条目 ID 命名与游戏内部 ID 不完全一致，不能猜）；
  - `GET https://api.nmsassistant.com/Version` → **200**，但内容是 App 版本
    `Release 1.60`（`activeDate = 2020-10-27`），**不是游戏数据版本**。
- 许可/条款风险：
  - WebApi 仓库无 LICENSE；App 的 T&C 明确禁止复制/修改 App、提取源码；
  - API 本身没有看到“允许批量抓取/再分发”的书面许可；
  - 因此只能做**用户显式开启的按需在线查询**：显示来源与“版本未知”，不批量拉取、
    不把返回数据提交进仓库、不作为写存档/判断版本的依据。
- 离线降级：没有网络或条目缺失时，明确显示“未收录/需要联网”，不影响本地已有功能；
  不要用旧缓存冒充当前版本。

### 1.9 nms-items-interface：物品/配方/传送门查询

- 许可 **GPL-3.0**；仓库提交了 `data/items.json`、`data/recipes.json`、`data/source.json` 等
  派生数据。`[参考] https://github.com/rdlu/nms-items-interface`
- 它最值得借鉴的是**数据管线纪律**，不是数据本身：
  - `data/source.json` 记录“游戏版本 + build + MBINCompiler 版本 + hgpaktool 版本 + 提取日期”；
  - 游戏更新后先比对 build，MBINCompiler 读不了就**拒绝提取并开 issue**，不静默产出错数据；
  - 传送门页实现了“portal code ↔ galactic address”双形态，并用品红色/字段色区分
    planet / system / Y / Z / X；
  - 用“银河中心不变量”做测试：portal `000000000000` ↔ galactic `07FF:007F:07FF`。
- 这些都可以用自己的代码重写；**其 JSON、字形轮廓、地址列表不能复制**。

---

## 2. 我们能合法复用什么

### 2.1 可以复用/重写（算法与格式）

| 能力 | 来源（参考） | 我们的做法 |
|---|---|---|
| pak 读取 | HGPAKtool（MIT） | 继续用；保持 `THIRD_PARTY_NOTICES.md` |
| MBIN 结构/字段名 | MBINCompiler 文档与类名（LGPL） | 只读参考；自己的 `nms_procgen/mbin.py` 解析 |
| 场景 → 几何 → 网格 | NMSDK / 我们的 `model3d` | 用 MIT 的 `_scene_meshes` / `_geometry`；不复制 NMSDK |
| 描述符树 | 我们的 `mbin.load_descriptor`；NMSCD 思路 | 自己解析；按 `Name` 显隐节点 |
| 坐标/符文数学 | Coordinate-Converter、nms-items-interface | 自己实现常数与位段；加测试 |
| 版本来源记录 | nms-items-interface 的 `source.json` 模式 | 在我们的缓存/响应里记录 build_id + schema |
| 在线物品查询 | AssistantNMS API | 可选适配器；按需、署名、不缓存/不再分发 |

### 2.2 可以运行时读取、但不能入库的数据

- 玩家本机的 `GAMEDATA/PCBANKS/*.pak` 及其解出的 MBIN/MXML、DDS、几何；
- Gagarin `catalog.txt` / `icons.bin`（玩家本地游戏目录）；
- 从游戏表派生的任何 JSON/CSV（物品、配方、生物角色、部件树）；
- 上游归档（nms-archive）与上游导出（Creature-Builder 的 `IPetData.json`、FBX/OBJ/DDS）。

正确做法：运行时提取到 `paths.cache_dir()`（已被 `.gitignore` 覆盖），缓存键带 `build_id`，
发布包不带；测试用合成 fixture，不用游戏资产。

### 2.3 不能做

- 不把 `mapping.json`、`libMBIN.dll`、MBINCompiler 源码复制进 MIT 仓库；
- 不把 nms-archive 的 MBIN/MXML 下载进仓库或打包；
- 不把 AssistantNMS / nms-items-interface 的 JSON 作为内置百科数据；
- 不把 NMSDK / nms-ship-customizer / Creature-Builder 的代码或资产复制进来；
- 不发布 seed→parts 的逆向结果（社区规范，见 `CREATURE-SEARCH.md` §2.3）。

---

## 3. 现有管线盘点（我们已有什么）

| 模块 | 现状 | 对本次评估的意义 |
|---|---|---|
| `[代码] starforge/gltf.py` | `parse_pack` / `build_glb`，支持平涂、贴图内嵌、外部 URI | **与模型类型无关**，生物/工具可直接复用 |
| `[代码] starforge/render.py` | 纯 numpy 点云 + 三角光栅化 + 贴图采样 + PNG 缓存 | 同样与模型类型无关；可做生物/工具缩略图 |
| `[代码] starforge/preview.py` | L0 部件图 / L1 真 3D / 降级原因；缓存键含类型/种子/部件 | 飞船专用入口；L0/L1 降级模式可照抄 |
| `[代码] starforge/live/iconart.py` | 用真模型渲“蓝图风”BC1 DDS 图标 | 若生物/工具 3D 落地，可复用同一套图标生成 |
| `[代码] starforge/creature.py` | 同伴描述符/种子/角色表/能力盘点 | 已有描述符解析与“外观不可从单 seed 复现”的结论 |
| `[代码] starforge/glyphs.py` | UA ↔ 12 位符文；BC7 符文图标；面板 | **缺 coords 形态**；是地址工作台的现成底座 |
| `[代码] starforge/app/dialogs/address.py` | 12 位 glyphs / 0x 种子分类；坐标明确“不支持” | 本次第一优先任务就改这里 |
| `[代码] starforge/data/*` | Gagarin catalog/icons/GSHI；仅飞船部件 | 生物/工具部件没有对应目录，需要本地 descriptor 解析 |

补充：`FEATURE-GAPS.md` 已把“坐标文本解析”列为 **缺失 P2**，“多用途工具 3D / 生物 3D”
列为缺失/只读；本文不重复审计，只给落地方案。

---

## 4. 落地点（按投入产出排序）

### 4.1 P1：地址工作台补“坐标 ↔ 符文 ↔ UA”

**为什么最优先**

- 纯数学，不需要游戏资产、不需要逆向、没有上游数据许可问题；
- 直接补 `FEATURE-GAPS.md` 的 P2 缺口，用户每天都在用（分享地址、找船、找生物、传送）；
- 可以把现有 `glyphs.py` 从“UA → 符文”升级为“四种形态互转”：
  **UA 整数 / 12 位 portal code / 银河坐标文本 / 存档坐标字段**；
- 0.5–1 天可完成并测试。

**需要的形态**

| 形态 | 例子 | 说明 |
|---|---|---|
| UA | `0x11200F19BDCE5` | 本仓库布局：x 12 + z 12 + y 8 + galaxy 8 + system 12 + planet 4（最多 56 位） |
| portal code | `1112F19BDCE5` | 第 1 位 planet，2–4 system，5–6 Y，7–9 Z，10–12 X |
| 银河坐标 | `0824:007F:00F3:01AC` | X:Y:Z:system（各 4 位十六进制；Y 实际 2 位有效） |
| 存档坐标 | `VoxelX / VoxelY / VoxelZ / SolarSystemIndex` | Coordinate-Converter 的输出形状；没有 galaxy/planet |

> **注意（本次读代码发现）**：`glyphs.py` 的注释写“UA 是 52 位”，但 `unpack_ua` 的实际布局
> 是 12+12+8+8+12+4 = **56 位**；而且常见 UA（如 `0x11200F19BDCE5`，49 位）的 planet 位是 0，
> 现有 `glyphs_for_ua` 必须靠**单独传入的 planet 参数**才能拼出第 1 位。地址工作台不能假设
> “UA 里一定有 planet”，否则会把 `planet=0` 的合法地址误判成无效。做互转时：
> - `ua_from_parts(...)` 显式写入 planet（允许 0，表示“未知/未编码”）；
> - `glyphs_from_ua(ua, planet=...)` 仍接受外部 planet；两者不要互相猜。

**换算常数（公开数学，自己实现）**

```
portal_X = (galactic_X + 2049) % 4096      galactic_X = (portal_X + 2047) % 4096
portal_Y = (galactic_Y +  129) %  256      galactic_Y = (portal_Y +  127) %  256
portal_Z = (galactic_Z + 2049) % 4096      galactic_Z = (portal_Z + 2047) % 4096
```

- 有符号 voxel：portal 值 > 2047（Y > 127）时减 4096（Y 减 256），与
  `glyphs.unpack_ua` 的符号扩展一致；
- 银河中心不变量：portal `000000000000` ↔ galactic `07FF:007F:07FF`（X/Y/Z，system=0）；
- **galaxy 不在 portal code 里**：portal code 只描述本银河内的位置；跨银河必须同时给
  galaxy index/reality。UI 必须让用户选银河，或从 UA 带出，不能猜。

**改动点**

- `starforge/glyphs.py`：新增纯函数（不破坏现有 `digits_for` 的兼容行为）：
  - `unpack_ua` 已有；
  - `glyphs_for_ua` 已有；
  - 新增 `ua_from_parts(galaxy, system, planet, x, y, z)`；
  - 新增 `coords_from_ua(ua)` / `ua_from_coords(...)`；
  - 新增 `glyphs_from_coords(coords, galaxy, planet)` / `coords_from_glyphs(glyphs, galaxy)`。
- `starforge/app/dialogs/address.py`：把 `kind="coords"` 从“拒绝”改成“解析”，支持
  `XXXX:YYYY:ZZZZ:SSSS`、空格/中文冒号等；输出 UA、portal code、坐标三种表示。
- `starforge/app/pages/galaxy.py`：地址工作台显示“银河/行星”选择，复制按钮同时给
  portal code 与银河坐标。
- 测试：`tests/test_glyphs_ua.py`、`tests/test_address_workbench.py`。

**验收**

- 已知样例 `0x11200F19BDCE5` → `1112F19BDCE5`（现有测试保持）；
- 随机 10,000 个合法地址（显式带 planet 1–6）：UA → portal → UA、UA → coords → UA
  全部往返一致；
- 银河中心 `000000000000` ↔ `07FF:007F:07FF`；
- planet=0 显示“行星未知/不可传送”，不当作合法门地址；planet>6、system 越界、
  X/Y/Z 越界都给出明确错误，不静默截断；
- 跨银河输入必须带 galaxy，缺失时提示而不是默认 Euclid；
- `pytest` 全绿，`ruff` 无新增告警。

### 4.2 P2：生物 3D（描述符 → 场景 → glTF）

**技术路径**

1. 从玩家本机 `NMSARC.Precache.pak` 取目标 rig 的 `.descriptor.mbin`；
2. 用 `nms_procgen.mbin.load_descriptor` 解析描述符树，拿到当前同伴的 `Descriptors[]`
   对应的 `Name` / `Id` / `refs`；
3. 用 `model3d._scene_meshes(scene_path)` 遍历整只场景（含 `REFERENCE` 子场景）；
4. 只保留名字命中“已选描述符”的子树（或按 `Name` / `Name+"Shape"` 过滤），
   未选中的部件隐藏——这是 NMSDK / Creature-Builder 证明可行的“整只模型显隐”，
   不是逐骨骼拼装；
5. 用 `gltf.build_glb` 出 GLB，用 `render.rasterize` 出 PNG；
6. 材质/贴图从本地 `NMSARC.TexCreature*.pak` 解析；没有贴图时按材质类平涂（现有降级）。

**需要的数据**

- 描述符 MBIN：`NMSARC.Precache.pak`（现有研究：287 个 creature descriptor，77 个 rig 目录）；
- 几何：`NMSARC.MeshPlanetCREATURES.pak`（现有研究：661 条 `<rig>/<mesh>.geometry.mbin.pc`）；
- 贴图：`NMSARC.TexCreature*.pak`（现有研究：26 个包）；
- 可选动画：没有动画时用绑定姿势也能看。

**必须先验证的 3 件事（Phase 0）**

1. 当前 build 185034 的 descriptor 里是否仍能找到同伴用的 `_BODY_PLANT` / `_HEAD_PLANT1` /
   `_MESH_PLANT`（旧研究说静态 rig 里找不到，但 NMSCD 表里存在，需复核）；
2. 场景节点名是否等于描述符 `Name` / `Id`（决定“显隐法”是否成立）；
3. 程序化角色（`PLANTCAT` 等）是否有静态场景；没有就明确显示“需生成器”，不画空白。

**许可边界**

- 不复制 NMSDK / Creature-Builder 的代码、`IPetData.json`、FBX/OBJ/DDS；
- 所有数据运行时从玩家本机 pak 提取，缓存不进 git；
- 不做、不发布 seed→parts 映射（社区规范）。

**投入**：Phase 0 spike 1–2 天；能出 1 个 rig 的 GLB/PNG 即算成功。完整多角色 + 贴图 5–8 天。

### 4.3 P3：工具 3D（多用途工具）

- 与生物同一套“场景 → 几何 → glTF”管线；区别是入口：
  - 需要先盘点 `MODELS/COMMON/WEAPONS/MULTITOOL` 下的 scene/descriptor/material；
    `[实测]` nms-archive 7.06 归档中存在该目录（但只有 MBIN/MXML 定义，不含几何）；
  - 本机几何包名需实际盘点（可能是 `MeshCommon` 或专用包，⬜ 未验证）；
  - 需要把存档里的 multitool `seed` / `model` / `class` 映射到场景或描述符；上游没有
    现成开源实现（`NMS-Shipwright` 只做飞船，`NMSDK` 是通用 Blender 导入）。
- 由于“工具外观是否由 seed 决定、以及 seed→模型”的链路未验证，**优先级低于生物**。
- 预期收益：工具页从“只读表格”升级为“3D 预览 + 分享图”；风险是工具模型/材质槽复杂，
  以及不同工具类型的场景差异大。

### 4.4 P4：内容百科（AssistantNMS 可选在线源）

**能做什么**

- 在物品/配方详情里加一个“在线补全”按钮或开关：
  - `GET /ItemInfo/GameId/{gameId}/{lang}`；
  - 展示名称、分类、描述、基础价值、堆叠、用途；
  - 明确标注“在线来源：AssistantNMS；游戏版本未知；未写入本地库”。
- 只按用户当前查询的 ID 请求，不遍历 `/ItemInfo/GameId` 的 3,340 条，不做后台批量同步。

**不能做什么**

- 不把 API 返回写入仓库或打包；
- 不长期缓存并当作“离线百科”（版本未知，会过期）；
- 不把 AssistantNMS 当作版本判断/写存档依据；
- 不复制其 App/WebApi 代码（WebApi 无 LICENSE，App 是 GPL-3.0）。

**离线降级**

| 情况 | 行为 |
|---|---|
| 用户未开启在线 | 只显示本地已有字段；没有百科入口或显示“离线模式” |
| 网络失败 / 超时 | 显示“在线数据不可用”，保留本地内容，不阻塞页面 |
| 条目 400/404 | 显示“该条目未收录”，不猜相近 ID |
| 版本不符/过旧 | 显示“来源未标注游戏版本”，不声称当前版本 |

**后续可选（不作为第一优先）**

- 用玩家自装 MBINCompiler 作为外部 CLI，把自己游戏里的物品/配方表转 MXML 再解析，
  生成本地百科；这是 LGPL 的“独立进程”用法，但要额外 .NET 依赖与版本维护，工作量大。
- 或者用我们自己的 `gamemeta` 反射布局解析 `cGcProductTable` / `cGcRecipeTable`；
  这是更长线的自研路线。

### 4.5 P5：部件数据（生物/工具的描述符目录）

- 飞船部件：已有 Gagarin `catalog.txt` + `catalog.py`（8 船型 / 543 组 / 1430 选项），
  `icons.py` 也能读本地 `icons.bin`。
- 生物/工具没有 Gagarin 等价目录；正确来源是**本机 descriptor MBIN**：
  - `mbin.load_descriptor` 已能解析 `cTkModelDescriptorList` 的 `id/name/refs/kids`；
  - 需要补 `Chance` 权重（结构里有，偏移待确认）和“组 → 选项”的展示；
  - 对生物，把描述符按 `_BODY_` / `_HEAD_` / `_TAIL_` / `_MESH_` 前缀分组（现有
    `creature._descriptor_group` 已做一半）。
- 不要把 NMSCD 的 `IPetData.json` 当数据源：它不完整（本机 22 个角色里 11 个没有树），
  且无 LICENSE。

---

## 5. 版本耦合风险与“探测 + 降级”

### 5.1 build 185034 与上游版本的关系

| 证据 | 值 | 含义 |
|---|---|---|
| 本机 `NMS.exe` FileVersion | **185034** | 我们所有游戏数据/3D 的版本主键 |
| NMSpy 最新版 | **185034.0**，PyPI 上传于 **2026-11-06** | NMSpy 版本号跟随游戏 build；说明 185034 是 2026-11 初的构建 `[实测]` |
| MBINCompiler 最近发布 | `v7.14.0-pre1`（2026-11-03）、`v7.10.0-pre1`（2026-10-28）、`v7.07.0-pre1`（2026-10-08） | 与 185034 同一时间窗口；**具体对应关系未官方标注** `[实测]` |
| nms-items-interface 数据源 | `Cosmos 7.06, build 180836`（GOG），MBINCompiler `v7.04.1-pre3` | 比 185034 旧；**不能把它的数据当同版** `[实测]` |
| nms-archive 最新 | `7.06-COSMOS-05.October.2026` | 比 185034 旧；没有 7.10/7.14 目录 `[实测]` |

**推断（🟡，非官方映射）**：按发布时间线，185034 落在 **7.10–7.14 的发布窗口**内
（MBINCompiler `7.10.0-pre1` 在 10-28、`7.14.0-pre1` 在 11-03；NMSpy `185034.0` 在 11-06）。
但没有官方映射，**不能断定 185034 就等于 7.14**；**唯一可靠的确认方式**是用 MBINCompiler 的
`version` 读一个本机 MBIN 的头版本，或直接比对我们自己的 `gamemeta` 布局是否 `matches()`。
文档/缓存里不要写死“185034 = 7.14”。

> 另外，Steam build 号与 GOG build 号不同（nms-items 的 `source.json` 同时记录了游戏版本、
> Steam/GOG build 与工具版本）。跨平台不要把 build 号当唯一键，**sha256 + FileVersion + MBIN 头**
> 三者一起用。

### 5.2 探测分层

| 层 | 探什么 | 失败时 |
|---|---|---|
| L0 文件 | `GAMEDATA/PCBANKS` 是否存在；`NMS.exe` 是否存在 | 直接 L0 图标/占位，说明“没有游戏目录” |
| L1 指纹 | `NMS.exe` 的 sha256、size、`FileVersion` → `build_id`（现有 `build.py`） | 未知 build → 只读，写入/传送/扫描关闭 |
| L2 pak | 用 HGPAKtool 列一个已知文件（如符文 DDS 或某个 MBIN） | pak 打不开 → 3D/数据提取全部降级，说明原因 |
| L3 MBIN | 读 MBIN 头（magic `0xCCCCCCCC`、version、name hash）；用 `gamemeta.layout(class).matches(blob)` 验证 | 结构不匹配 → 该字段标 `unsupported`，不猜 |
| L4 资源 | 场景/几何解码后检查顶点数、包围盒、材质名 | 单件失败只让该件退回平涂/占位 |

### 5.3 降级策略（必须显式，不静默）

- **未知 build / unverified build**：沿用现有 `build.summary()` 闸门：只读；写/传送/扫描
  默认禁用，`reason` 写明 build_id（`[代码] starforge/live/build.py:230-255`）。
- **3D 资源缺失**：走 `preview.py` 的 L0 降级，返回 `degraded=True` + `reason`，
  不返回空白 GLB。
- **MBIN 结构不匹配**：返回字段级 `unsupported`（参考 agent 现有“每字段独立降级”风格），
  不把错位读出的数字当真实值。
- **在线 API 失败**：百科入口显示“在线不可用”，本地功能不受影响。
- **缓存**：所有 3D/解析缓存键必须含 `build_id` + schema 版本 + pak mtime/hash；
  游戏更新后旧缓存自动失效，不能复用旧版本几何/描述符。

---

## 6. 下一步可做的具体任务（1–3 个）

### 任务 1（第一优先）：地址工作台坐标/符文互转

| 项 | 内容 |
|---|---|
| 目标 | 支持 `UA` / `portal code` / 银河坐标 `XXXX:YYYY:ZZZZ:SSSS` / 存档坐标四形态互转，并保留银河与行星位 |
| 文件 | `starforge/glyphs.py`、`starforge/app/dialogs/address.py`、`starforge/app/pages/galaxy.py`、`tests/test_glyphs_ua.py`、`tests/test_address_workbench.py` |
| 数据依赖 | **无**（纯数学常数） |
| 许可 | 无（自己实现公开换算） |
| 验收 | 10,000 个随机合法地址（显式 planet）往返一致；银河中心不变量；planet/galaxy 越界明确报错；现有 glyph 面板/复制不回归；`pytest` 全绿 |
| 估时 | 0.5–1 天 |

### 任务 2：生物 3D Phase 0 spike（单 rig 出 GLB/PNG）

| 项 | 内容 |
|---|---|
| 目标 | 用本机 pak 的一个 creature rig，按存档描述符显隐，离线出 1 个 GLB + 1 张 PNG |
| 文件 | 新建 `starforge/creature_model.py`（或扩展 `creature.py`）；复用 `nms_procgen.model3d._scene_meshes/_geometry`、`starforge/gltf.py`、`starforge/render.py`；新增 `tests/test_creature_model.py`（用合成网格，不依赖游戏） |
| 数据依赖 | 本机 `NMSARC.Precache.pak` descriptor、`NMSARC.MeshPlanetCREATURES.pak` 几何、`NMSARC.TexCreature*.pak` 贴图；build 185034 |
| 许可 | 不复制 NMSDK/Creature-Builder；数据只在本地缓存 |
| 验收 | 选定 rig（如 antelope/blob/trex）能出图；切换描述符能看到部件变化；缺资源/程序化角色明确显示“需生成器”；缓存键含 build_id |
| 估时 | 1–2 天（spike）；完整多角色 5–8 天 |

### 任务 3：可选在线百科适配器（AssistantNMS）

| 项 | 内容 |
|---|---|
| 目标 | 用户显式开启后，按当前物品 ID 查询 AssistantNMS，展示名称/描述/价值/用途；失败/离线明确降级 |
| 文件 | 新建 `starforge/services/codex.py`（provider 抽象 + `AssistantNMSProvider`）；`starforge/services/__init__.py` 暴露；`starforge/web/routes.py` 加只读端点；设置页加开关 |
| 数据依赖 | `https://api.nmsassistant.com/ItemInfo/GameId/{id}/{lang}`；仅按需、不批量 |
| 许可 | WebApi 无 LICENSE；只做在线查询，不复制数据/代码；UI 标注来源与“版本未知” |
| 验收 | 有网时 `ANTIMATTER`/`ANY_FISH` 能显示；无网/400 时显示“未收录/不可用”且不影响本地；测试用 mock HTTP，不依赖真实网络 |
| 估时 | 1–2 天 |

---

## 7. “只参考不集成”清单

| 项目 | 只参考什么 | 明确不做什么 |
|---|---|---|
| MBINCompiler / libMBIN | 类名、字段名、`version` 诊断方法、MXML 概念 | 不复制代码/DLL/`mapping.json`；不静态链接 |
| nms-archive | 某版本的路径/描述符是否存在、字段结构 | 不下载 MBIN/MXML 进仓库；不自动抓取；不作为运行时数据源 |
| NMSDK | “整场景导入 + 引用子场景”的流程；导入 beta 的坑 | 不复制 Blender 插件代码；不引入 Blender 依赖 |
| nms-ship-customizer | 船型/部件/种子/配色的交互形态 | 不复制 15 MB 实验页/颜色表/部件表；不集成 |
| Coordinate-Converter | 坐标↔符文的字段顺序与常数 | 不复制 TS 代码（GPL-3.0） |
| AssistantNMS | 在线物品字段形状、API 端点 | 不复制 App/WebApi 代码；不批量抓取；不内置数据 |
| nms-items-interface | `source.json` 版本溯源、失败关闭、传送门双形态 UI | 不导入 `data/*.json`；不复制 GPL 代码/字形轮廓 |
| NMSCD Creature-Builder | “按描述符 Name 显隐整只模型”的思路 | 不复制 `IPetData.json`、FBX/OBJ/DDS（无 LICENSE） |
| nmstoolkit（前文已评估） | “不做 seed→parts”的社区规范 | 不复制代码；不发布 seed→parts |

---

## 8. 数据合规红线（发布前检查）

- 仓库中不出现：`*.pak`、`*.mbin`、`*.mxml`、`*.exml`、`*.dds`、`*.fbx`、`*.obj`、
  从游戏导出的 `*.glb`、Gagarin `catalog.txt` / `icons.bin`、AssistantNMS/nms-items-interface 的
  JSON 数据、Creature-Builder 的 `IPetData.json`。
- 运行时缓存统一放在 `paths.cache_dir()`，且 `.gitignore` 覆盖；缓存键含 build_id。
- 测试 fixture 用合成数据（例如 `tests/fixtures/make_dds.py` 的思路），不提交真实游戏资产。
- 新增依赖/代码时同步更新 `THIRD_PARTY_NOTICES.md`；LGPL 组件如确需使用，单独说明动态链接/
  源码提供方式。
- 在线数据必须标注来源、时间、版本未知；不把在线结果写成“当前版本权威数据”。

---

## 9. 参考链接

- HGPAKtool：<https://github.com/monkeyman192/HGPAKtool>（MIT）
- MBINCompiler：<https://github.com/monkeyman192/MBINCompiler>（`LICENSE.md` = LGPL-3.0）
- libMBIN 类文档：<https://monkeyman192.github.io/MBINCompiler/classes/gc/GcCreatureData>
- nms-archive：<https://github.com/NMSCD/nms-archive>（GPL-3.0；游戏文件归 Hello Games）
- NMSDK：<https://github.com/monkeyman192/NMSDK>（无 LICENSE）
- NMSDK 导入文档：<https://github.com/monkeyman192/NMSDK/blob/master/docs/importing/importing.md>
- nms-ship-customizer：<https://github.com/MetaIdea/nms-ship-customizer>（无 LICENSE；已跳转 nms.center）
- Coordinate-Converter：<https://github.com/NMSCD/Coordinate-Converter>（GPL-3.0）
- AssistantNMS：<https://github.com/AssistantNMS>（App/WebApp GPL-3.0；WebApi 无 LICENSE）
- AssistantNMS API：<https://api.nmsassistant.com>（本次实测 `ItemInfo` 可用）
- nms-items-interface：<https://github.com/rdlu/nms-items-interface>（GPL-3.0）
- 本仓库相关：`starforge/glyphs.py`、`starforge/gltf.py`、`starforge/render.py`、
  `starforge/preview.py`、`starforge/creature.py`、`starforge/live/build.py`、
  `docs/research/CREATURE-SEARCH.md`、`docs/research/FEATURE-GAPS.md`

---

## 附录 A：本次实测记录（可复现）

| 检查 | 结果 |
|---|---|
| GitHub API `license`：HGPAKtool / MBINCompiler / nms-archive / NMSDK / ship-customizer / Coordinate-Converter / nms-items-interface | `MIT` / `NOASSERTION`（正文 LGPL-3.0）/ `GPL-3.0` / `null` / `null` / `GPL-3.0` / `GPL-3.0` |
| MBINCompiler 最近 release | `v7.14.0-pre1` 2026-11-03；`v7.10.0-pre1` 2026-10-28；`v7.07.0-pre1` 2026-10-08 |
| NMSpy 最新版 | `185034.0`，2026-11-06 |
| nms-archive 最新目录 | `7.06-COSMOS-05.October.2026` |
| nms-archive 7.06 `MODELS/COMMON` | 含 `WEAPONS/MULTITOOL`、`SPACECRAFT` 等（MBIN/MXML 定义） |
| `api.nmsassistant.com/ItemInfo/GameId` | 200，3,340 个 ID |
| `api.nmsassistant.com/ItemInfo/GameId/ANTIMATTER/en` | 200，含名称/描述/价值/堆叠/用途 |
| `api.nmsassistant.com/ItemInfo/GameId/ANY_FISH/en` | 200 |
| `api.nmsassistant.com/ItemInfo/GameId/SALVAGED_DATA/en` | 400（ID 命名不匹配） |
| `api.nmsassistant.com/Version` | 200，但返回 App 版本 `Release 1.60`（2020-10-27），不是游戏版本 |
| 本仓库 `glyphs.py` | 已有 UA ↔ 12 位符文；无坐标形态 |
| 本仓库 `address.py` | 坐标输入明确返回“不支持” |
| 本仓库 `gltf.py` / `render.py` | 与模型类型无关，可直接用于生物/工具 |
| 本仓库 `preview.py` | 飞船专用入口，L0/L1 降级模式可复用 |
