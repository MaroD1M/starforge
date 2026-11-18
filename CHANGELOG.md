# 更新记录

## v0.13.2-beta（按你实测反馈修 4 处）

- **船型中文化**：船型按钮与详情标题此前渲染的是英文 id（`fighter`/`sentinel`…），现在统一走中文表
  （异星 / 探索舰 / 战斗机 / 运输舰 / 生物舰 / 拦截机 / 穿梭机 / 太阳帆），`title` 保留英文原名便于对照。
  根因：`ShipRef.type_label` 是 property，`to_dict()` 用 `asdict()` 不带它；`/api/catalog` 也没给标签表。
- **涂装筛选"没生效"**：实际是**控件语义重叠**——总开关未勾时 `buildLook()` 直接返回 `null`，
  而下面还有两个独立的"启用"小勾（截图里正是这个状态）。现在合并为：勾总开关即按「主色」筛，
  另可勾「副色也要像」；结果栏显示"已按涂装过滤（主色 Δ≤0.18）"，0 结果时直接提示"容差太严，调到 0.18/0.28 或取消副色"。
- **3D 观感不如缩略图**（三条实因，逐条修）：
  1. glb 材质对未知类（发光件）回退成**主色** → 现在回退 `_GROUP_COLOR`，并把 `glow` 定为固定暖色 + `emissiveFactor`；
     实测同一艘拦截机 glb：`glow base=[1.0,0.62,0.22] emissive=[1.0,0.62,0.22]`、`metal [0.573,0.584,0.573]`、`paint [0.969,0.816,0.42]`；
  2. 查看器着色器：加 sRGB→线性、**三点光**（主/补/轮廓）、Blinn 高光、输出 gamma——不再"一片平涂"；
  3. 渲染分辨率提到 `dpr × 1.5`（封顶 3）做超采样，观感更接近服务端光栅化。
- **原生窗口**：`desktop.probe()` 增加 **Edge WebView2 运行时检测**（注册表 + 常见安装路径），
  `/api/health` 暴露 `desktop:{available,mode,reason}`；顶部芯片在浏览器模式下可**点开**看原因与安装指引；
  设置页新增「原生窗口」诊断行与「诊断 / 怎么装 WebView2」；
  `starforge app --browser` 可显式用浏览器（调试），双击 exe 仍然默认原生窗口。
- 新增测试 7 项（中文标签、catalog 标签表、glb 材质回退、glow 自发光、paint 的 glow 槽、health 的 desktop 段、probe 原因可执行）。

## v0.13.1-beta（打包自检覆盖新模块）

- `webcheck` 增加 `/api/galaxy/stats` 与 `/api/creatures/capabilities` 两项——这两个模块（`galaxy` / `creature`）
  是 v0.13 新增的，放进打包后自检才能在产物里证明它们**真的进包了**（否则只会在用户点开对应页时才炸）。
  自检项 13 → **15 项**。
- 其余与 v0.13.0-beta 相同。

## v0.13.0-beta（M1–M3 交付 + T8/T9 研判）

> 自 v0.12.2 以来的全部改动：三个新能力（种子反查星系 / 按涂装筛 / 银河索引）+ 两处专项研判（行星字段、生物角色表）
> + 若干真 bug 修复与文档对齐。测试从 168 项增至 **223 项**，`selfcheck` 10/10、`webcheck` 13 项全过。

**新增能力一句话**：搜到种子能告诉你「它在哪个星系、符文是什么」；能按真实配色筛船；扫过的星系落进本地库并可按条件秒查、导出 CSV；存档里的 29 只同伴与游戏内 86 条生物角色表都能读出来。

### 汇总：本轮修掉的真 bug

| Bug | 影响 | 修法 |
|---|---|---|
| `glyphs.digits_for(UA)` 截低 12 位十六进制 | `0x10400F19BDCE5` 算成 `0400F19BDCE5`（符文错） | 按位段重排（`glyphs_for_ua`），新增 6 项测试 |
| `web/routes.py` 用 `WriteRefused` 却没 import | "游戏正在运行"时会 500 而不是 409 | 补 import，新增 4 项接口错误码测试 |
| `glyphs._decode_dds` 里 `from . import dds` 指向不存在的模块 | 非 BC7 符文贴图静默退回位图字体 | 改用 `texture2ddecoder` 的 BC1/BC3 |
| `selfcheck --no-write` 被 argparse 收下但忽略 | 参数无效 | 真正传给 `run(include_write=...)` |
| `selfcheck` 排障提示写 `nmsforge.log` | 引导到不存在的文件 | 改为真实的 `starforge.log`；并加路径自愈（K21） |
| `system.available()` 只认设置里的 `game_dir` | CLI/CI 只给 `NMS_DIR` 时假失败 | 增加 `NMS_DIR` 兜底 |
| `test_write_gate_opens_then_needs_confirm` 依赖"本机没存档" | 设了 `STARFORGE_SAVES` 就红 | 显式固定"无存档" |


### T8 的 Data 字段定性 + 收尾

- **T8 最后一块定性了（仍未解，但有了确切结构和步长）**：`cGcCreatureData.Data`（+0，16 B）实测是
  **TkDynamicArray 头**：`offset(u32) + pad + count(u32) + 0xAAAAAA01 魔数`。
  · entry0 的 `Data` → 文件 `0x45e0`、`count=2`；下一条目 `Data` 在 `0x4758`，跨度 **0x178 = 376 B**（≈188 B/元素）；
  · 元素类型在 `NMS.exe` 反射里 **classptr=0**（没有类布局），所以"外观"仍未解；
  · 与 `Data` 同级的 `Tags` / `MoveSets` 是能解析的（`cGcCreatureTagAndRarity` / `cGcPetBattlerMoveSetSelection`），
    说明反射本身没问题，是 `Data` 的字段类型偏"不透明"。
  → 下一步（明确的活）：按 188 B 步长反推元素结构，或从 `cGcPlanetGenerator::GenerateCreatureRoles` 的调用侧看它怎么消费 `Data`。
- 手册与能力矩阵同步更新；同伴 3D 仍标 ❌（不画饼）。

### T8-3 收尾 + 银河索引导出 CSV

- **T8-3 收尾：角色表 86 条条目全部解出**（关键发现：`Id` **不是哈希**，是 **16 字节定长 ASCII**）：
  · 实测名字：`FISH / FISHFLOCK / SWIMCOW / SWIMRODENT / JELLYFISH / CRAB / SEASNAKE / SHARK / BIRD /
    FLYINGSNAKE / FLYINGLIZARD / BUTTERFLY …` 共 86 条；
  · 每条还带 `force_type`（如 7）、`real_type`、`min_scale/max_scale`（如 0.6–1.2）、`eco_system`、
    `can_be_female`、`forced_only`；`rarity` 按 float 是垃圾值（2.8e-45）→ 按 int 存为 `rarity_raw` 并标注语义未确认；
  · 仍未解：`Data`（+0，16 B）指向生物外观数据 —— 这是"同伴 3D"的下一块，不是名字问题。
  · `creature.role_table()` 现在直接返回 86 条 `items`；界面点「我的同伴」表头即可看到整张角色表。
- **银河索引导出 CSV**：`GET /api/galaxy/export.csv`（支持同一套筛选参数），星球页新增「导出 CSV」按钮；
  一个星系多行星命中会展开成多行（`planet_index/biome/sentinels/weather`），Excel 直接可读。
- 新增测试 2 项（CSV 行数与筛选、角色条目名字与数值）；全量 **223 项**。

### T8-3 续：角色表结构解出来了

- **`CreatureDataTable.mbin` 结构级解析成功**（用 `NMS.exe` 反射反查类布局，不是猜）：
  · MBIN 头 `name_hash=0x58f2caec` / `guid=0x37d55099b13b9f9c` → 反射里精确对应 **`cGcCreatureDataTable`**（`matches=True`）；
  · 该类只有 1 个字段 `Table`，元素是 **`cGcCreatureData`（208 B / 29 字段）**；
  · 列表头在 `0x20`：`i64 rel=16` → 数据 `0x30`、`i32 count=86`，即 **86 条 × 208 B = 0x4610**，与文件下一个结构正好接上；
  · 字段名已解出（`Id`@+48、`ForceType`@+144、`RealType`@+196、`CanBeFemale`@+200、`EcoSystemCreature`@+202 …）。
- 新增 `creature.role_table()` + `GET /api/creatures/table`；`capabilities(deep=1)` 里带 `structure`。
- **仍未解**：条目里的 `Id` 是 **TkID（128 位哈希）**，角色名在另一张名字表里——把 ID 映射回名字需要名字表索引，
  这是 T8-3 的最后一步（也是"角色→模型/部件"的前置）。同伴 3D 仍判 ❌。
- 新增测试 2 项（结构自证 + API 契约）；全量 **221 项**。

### T8-3：生物角色表通了

- **`CreatureDataTable.mbin` 已抽出并读出角色名**：258,712 B、版本 `0xCE4`、字符串表 1962 条，
  启发式提取出 **378 个角色名**（`FISH / SWIMCOW / CRAB / SEASHORSE… / SHARK / BIRD / FLYINGLIZARD /
  BUTTERFLY / ANTELOPE / TRICERATOPS / RODENT / COW / CAT / PLANTCAT / BONECAT / STRIDER / TREX …`）。
- **关键交叉验证**：存档里 29 只同伴的 `CreatureID`（`PLANTCAT` / `HERMITCRAB` / `SCUTTLER_PET` /
  `LARGEBUTTERFLY` / `WEIRDFLOAT` …）**全部命中了这张角色表**（29/29）——说明"同伴 ↔ 角色表"这条链是通的。
- 新增 `creature.role_names()` 与 `GET /api/creatures/roles`；`/api/creatures` 的每条同伴多一个 `role_known`。
- **仍未解**：字段名在 MBIN 里是哈希编码（文件里没有 `GcCreatureData` / `Filename` 这类明文），
  要拿角色→模型/部件结构，需要实现"通用 MBIN 字段读取器 + 反射类名映射"——这是 T8-3 的后续，不是一次 spike 能完的。
  所以同伴 3D 依然标 ❌（`preview_possible=false`），只是现在知道下一步该写什么工具。
- 新增测试 3 项（角色表规模与必备角色、API 契约、同伴 CreatureID 命中角色表）；全量 **219 项**。

### T8-2 探路 + 能力矩阵卷

- **T8 第二阶段探路（反射取证）**：`NMS.exe` 反射字符串里实测命中
  `cGcPlanetGenerator::GenerateCreatureRoles(cGcPlanetData&, u64 const&)`（决定行星刷哪些生物角色的函数，
  与 `systemgen` 同级、**有机会外部化**）、`Metadata/Simulation/Ecosystem/CreatureDataTable.mbin`（角色表）、
  `cGcCreatureData` / `cGcEcosystemCreatureData` / `eCreatureType` / `eCreatureRole`。
  → 封装为 `creature.scan_exe_symbols()` 与 `GET /api/creatures/capabilities?deep=1`（默认不扫 89 MB 的 exe）。
  结论：**角色生成有入口，外观网格那条链仍未定位**。
- **手册新增第 09 卷「能力矩阵快照」**：每条能力的状态（✅实测/⚠️待实机/❌判负）+ 证据 + 复验命令 + 失效条件；
  另有「三条负结果 + 什么条件下会翻正」与「待实机清单」。交接第 1 天看这一卷就够。
- 新增测试 2 项（符号扫描命中 + deep 开关不影响轻量调用）；全量 **216 项**。

### T8 spike：生物 3D 可行性 + 能力盘点

- **T8 spike 做完，结论一半正一半负**（数据都在本机实测）：
  · **正向**：`NMSARC.Precache.pak` 里有 **287 个 `.descriptor.mbin`**（77 个目录、`anteloperig`…`trexrig` 等骨架族），
    每个 rig 的 descriptor 里带该 rig 的部件词表（实测 antelope：`_BODY_DEER/_BODY_FAT/_BODY_SKINNY`、
    `_HEAD_DEER/_HEAD_BUFF`；flyinglizard：`_WINGS_EAGLE/_BODY_LIZARD`）——说明**描述符可解析**；
    几何在 `NMSARC.MeshPlanetCREATURES.pak`（661 条 `<rig>/<mesh>.geometry.mbin.pc`），贴图在 26 个 `TexCreature*` 包。
  · **负向**：存档里同伴用的是**另一套词**（`_BODY_PLANT` / `_SHAPE_XRARE` / `_HEAD_PLANT1` / `_MESH_PLANT`），
    在这些静态 rig descriptor 里**一个都找不到**（`antelope`/`flyinglizard` 全文检索无 `PLANT`），
    `gccreatureglobals.mbin` 里也没有 —— 它们是运行时生物生成器的产物。
  · **判定**：同伴 3D 与"按外观搜同伴"必须先拿到生物生成器（等同行星的 `systemgen`），属 T8 第二阶段；
    现在**不做假预览**，界面如实写"3D 需运行时生物生成器"。
- 新增 `creature.capabilities()` + `GET /api/creatures/capabilities`：把上述盘点做成机读结果
  （`descriptors / rigs / geometry_pak / texture_paks / preview_possible / reason`），
  同伴列表表头会显示"游戏里有 N 个生物描述符 / M 个骨架族 · 3D 需运行时生物生成器"。
- 新增测试 2 项（能力盘点自证 + API 契约）；全量 **214 项**。

### T9 行星字段 + M8-lite 同伴只读

- **T9 结论（部分负结果，如实记录）**：离线**能**拿到 biome / sentinels / 4 个哨兵预设 / 种子；
  **拿不到**天气 / 植被 / 生物 / 资源清单——上游 `systemgen._planets()` 只读 `+0x34CC` 起的
  4 个哨兵等级，天空/天气表是占位（`systemgen.py:75`）。已在 `system.capabilities()["planet_fields"]`
  里把"离线可得/需游戏内"分开标出，界面不再假装有天气；行星卡片新增「预设 none/low/aggressive/corrupted」。
- **M8-lite 同伴只读**：新增 `starforge/creature.py` + `GET /api/creatures`，
  从存档 `PlayerStateData.Pets[]` 读出每只同伴的 描述符 / 四个种子（个体/次生/物种/属）/ 类型 /
  群系 / 体型 / 掠食 / 有毛 / UA / 信任度，空槽自动跳过。实测这份存档 **29 只**。
- 界面：我的船页新增「我的同伴 N 只」列表，点开看种子与描述符并一键复制物种种子；
  明确标注"3D 预览要等生物生成器（T8 第二阶段）"。
- 新增 `tests/test_planet_creature.py` 7 项；并修掉一条**会跟环境漂的旧测试**
  （`test_write_gate_opens_then_needs_confirm` 在本机设了 `STARFORGE_SAVES` 时会走到 400 而非 404，
  现改为显式固定"无存档"）。全量 **212 项**，带/不带 `STARFORGE_SAVES` 都全绿。

### PLAN-V4 · M3 界面 + M4 准备

- **星球页接上银河索引**：新增「扫入库并查」与「查索引」两个按钮 + 最少行星数/查多少条；
  扫完立刻按当前条件从库里查（不再重扫），结果表给出星系 UA / 符文 / 命中行星 / 群系 / 哨兵，
  每行可一键出符文面板。库内统计（星系/行星数/更新时间）直接显示在按钮下。
- **`starforge agent hello`**：游戏内代理（M4）的握手入口先固定下来——输出 13 项能力表
  （每项 `available / reason / risk`）+ `attached` + 下一步提示，stdout 是纯 JSON，便于实机整段回报。
- **新增 `docs/VERIFY-AGENT-WINDOWS.md`**：两轮实机验证单（第一轮只读 8 分钟：指纹 + `live probe` +
  游戏内对照；第二轮 15 分钟：agent 安装/握手/只读五命令对表/卸载），含红线与回报模板。

### PLAN-V4 · M3：银河索引

- **starship 之外的"银河"落地层**：新增 `starforge/galaxy.py`——SQLite 索引（`cache/galaxy.db`），
  表 `systems`（ua/坐标/符文/种族/经济/冲突/行星数/dissonant/拦截机/行星 JSON）+ `planets`
  （逐行星 biome/哨兵/天气/植被/生物），带 biome/哨兵/行星数/dissonant 索引。
- `galaxy.scan()`：扫一片区域并**落库**（重复扫同一 UA 是刷新，不膨胀），可注入 `provider`
  以便测试不跑 unicorn；`galaxy.GalaxyStore.query()` 支持
  `biome / sentinels / race / dissonant / has_interceptor / min_planets`，返回"星系 + 命中的行星行"。
- API：`POST /api/galaxy/scan`（任务化）、`GET /api/galaxy/query`、`GET /api/galaxy/stats`。
- 实测：当前星系周围 5 个系统 4.9 s 扫完落库（27 颗行星），`dissonant=1` 查到
  `0x200F19BDCE5 / 1002F19BDCE5`，`min_planets>=4` 查到 `0x100F19BDCE5`（5 颗）。
- 顺带修：`system.available()` 现在也认 `NMS_DIR` 环境变量（此前只认设置里的 `game_dir`，
  CLI/CI 会假失败，K21 同类问题）。新增 `tests/test_galaxy.py` 9 项。

### PLAN-V4 · M2：按涂装筛种子

- **按真实配色筛飞船**：`SearchQuery.look` 支持两种模式——
  · 索引模式 `{"primary": [3,17]}`：交给上游 `textures.look_mask`，与搜索同速（向量化）；
  · **RGB 模式** `{"primary":[0.95,0.78,0.10], "tol":0.18}`：上游只按部件筛，命中后用
    `paint.look()` 解出**这艘船的真实配色**再比距离。带 `max_candidates` 预算（默认 4000），
    到顶会明确说明"没扫完"，不会假装搜完了。
- 界面：搜索页新增「按涂装筛（主色/副色）」——两个取色器 + 主/副色开关 + 四档容差；
  结果卡片显示 `Δ` 距离（越小越像）。**只按涂装搜**也成立（不必先选部件）。
- 实测：目标 `#f2c744`（黄）× fighter × 容差 0.30 → 2 个结果，实测距离 0.1516 / 0.1878，
  8.2 s（含 12 个候选验色）；单元测试 6 项（含"结果必须真的落在容差内"的自证）。

### PLAN-V4 · M1：种子反查星系 + 改船级

- **种子 → 星系反查（A4）**：`system.locate_seed()` + `POST /api/locate` + 详情面板「在哪（反查星系）」。
  先 `locate` 出候选（欠定，会撞假地址），再用 `systemgen.confirm` **真的把星系生成出来**，
  只有里面确实有这艘船才算命中；返回星系名/坐标/12 符文/出处（坠毁点、空间站…）/是否到过。
  实测：存档里的船种子 `0x494CE787241EBCB2` → `0x10400F19BDCE5`、`04E4:0070:01BC:0104`、
  符文 `1104F19BDCE5`、出处「space station · hauler」，4.8 s（含生成器冷启动）。
- **改船级/属性（C3）**：`writer.apply_class()` + `POST /api/saves/class` + 详情面板「改级/属性…」。
  与写回同一套铁律（备份 → 原子写 → 重解码核对 → 失败回滚），额外两条：
  属性必须落在"这艘船这个等级游戏会给的区间"内；写完核对**其它船种子一个没动**。
  支持 `best=true`（拉到该等级上限）与 `copy=true`（写副本，原档字节级不动）。
- 新增测试 `tests/test_locate_class.py`（9 项：反查自证、拒绝非法等级、C→S→回读、
  其它船不受影响、best 落在区间、副本模式原档不动）。
- **修符文换算的真 bug（`glyphs.digits_for`）**：传 UA 整数时原来"取低 12 位十六进制"，
  `0x10400F19BDCE5` 会得到 `0400F19BDCE5`（丢 system 最高半字节、不插行星位）；
  现在按位段重排成 `1104F19BDCE5`（与上游 `locate.describe` 一致）。12 位十六进制串保持历史兼容。
  新增 `tests/test_glyphs_ua.py`（6 项）。
- **`selfcheck` 路径自愈（K21）**：开始前清 `gamepath.find` 缓存并 `settings.autodetect()`，
  避免"游戏装着但设置空 → 直接 4/10"；排障提示里的日志名 `nmsforge.log` 改为真实的 `starforge.log`。
- **`selfcheck --no-write` 真的生效**（此前被 argparse 收下但 `main()` 硬编码 `include_write=True`）。
- **修两个接口层隐患（04 卷审计发现）**：`web/routes.py` 用了 `WriteRefused` 却未 import
  （"游戏正在运行"时会退化成 500 而不是 409）；`glyphs._decode_dds` 里 `from . import dds`
  指向一个不存在的模块（非 BC7 的符文 DDS 会 ImportError 并静默退回位图字体），
  改为直接用 `texture2ddecoder` 的 BC1/BC3 解码；新增 `tests/test_api_errors.py`（4 项）。
- **文档纠错**：`data/gshi.py` 头部注释的 `u16 version` 改为实测的 `u32 version + u32 count`
  （12 字节头，u16 后有 2 字节填充）；`THIRD_PARTY_NOTICES.md` 补齐逐组件许可表，
  并新增 **unicorn 是 GPL-2.0** 的合规说明与 A/B/C/D 四个方案。
- **补"备份/恢复"界面**（此前只有 API，没有入口——能写档却不能回滚是安全缺口）：
  我的船页新增「备份/恢复…」，列出每次写入前的自动备份（时间/大小），一键恢复并给当前状态留快照。
- **文档与包元数据对齐**：`glyphs.py` 模块说明改成"按位段重排"（原文写"12 位十六进制"，与实现相反）；
  `pyproject.toml` 补上漏掉的 `starforge.live`（`packaging/entry.py` 依赖它）；`docs/DESIGN.md`/`docs/MANUAL.md`
  里的 `/api/save/apply` → `/api/saves/apply`、去掉未实现的 `?current=1`；`errors.py` 提示里的
  不存在的 `--yes-write` 改为真实做法（设置页 `write_enabled` + `confirm=true`）。
- 手册：本地 `handbook/` 九卷 / 7612 行（原理/上游解剖/格式/架构/踩坑/PLAN-V4/代码索引/交接），不随包发布。


## v0.12.2-beta
- **修打包环境的 500**：没有游戏/数据时 `/api/catalog/<ship>` 现在返回**带原因的 404**
  （此前上游抛 `GamePathError` 变成 500，CI 的 webcheck 因此失败）
- `parts.tree()` 把上游异常统一成可读的 `ValueError`
- webcheck 对"依赖游戏文件"的两个接口允许 404（必须是 JSON），其余仍要求 200

## v0.12.1-beta
- **打包可靠性**：`packaging/entry.py` 显式导入 zh/tex/parts/export/warm/render/preview 等模块，
  保证它们一定进 PYZ（v0.12.0 无法确认中文化模块是否被打进去）
- **webcheck 扩展**：逐项验证 `/api/textures/status`、`/api/catalog/<ship>`、
  `/api/part-thumb/...`、`/api/desktop`、`/api/warm`（12 项全过才算打包成功）

## v0.12.0-beta（重构 v2）
中文化 + 更接近真实建模的渲染 + 部件级预览 + 贴图管线 + 零配置自愈。
详见 [docs/PLAN-V2.md](docs/PLAN-V2.md)。

- **中文化**：插槽组与部件词根中英映射（编号保留、重名加序号），群系/哨兵/种族/船池类别
  全部中文；原名保留在 tooltip
- **渲染**：点云 → 三角光栅化（z-buffer + 背面剔除 + 漫反射）；网格 340px、详情 520px；
  搜索结果后台预取，缓存命中 0ms
- **部件级 3D 预览**：`/api/part-thumb`，与固定件求差集单独取部件几何；
  失败三级兜底（3D → 游戏图标 → 占位图）
- **贴图管线**：`tex` 模块取 DDS/解码/UV 采样；`/api/texture`；`/api/textures/status`
  诊断（报告材质描述符是否可用）
- **零配置**：路径自愈（GAMEDATA/Binaries/Steam 根）、注册表与 libraryfolders 检测
- 界面：卡片网格、属性条、收藏夹、URL 直达（`?demo=search` / `?glyph=`）、应用内对话框

## v0.11.1-beta
- **修复 3D 黑屏**（v0.11.0 的核心功能回归）：改用 WebGL2 上下文；WebGL1 下强制启用
  `OES_element_index_uint`（否则 `drawElements(UNSIGNED_INT)` 静默失败）；
  着色器不再使用非法的 `mat3(mat4)`，法线矩阵单独传
- 新增**画布自检**：画 3 帧后采样像素，若与背景完全一致则自动退回服务端渲染图（永不出现黑框）
- 用无头 Chromium + SwiftShader 做过真实渲染验证（截图见 docs/img）

## v0.11.0-beta
- 真机修复：pywebview 内部参数导致的控制台报错、`BIOSHIP_PROC` 被误判成异星、
  未知类型缩略图 400、游戏目录大小写不匹配、设置页无校验反馈
- 存档：类型/等级/属性（S/A/B/C + 伤害/护盾/超光速/机动）、固定模型占位图、
  写回支持"写到副本"（原档不动）、读存档缓存（2.79s → 1.12s，命中 1–2ms）
- 性能：部件图标改为懒解码（首次 3.96s → 0.01s）；启动后台预热（pak/几何/系统）
- 功能：批量导出 zip（glb+png+manifest）、分享码导入、收藏夹、只看可预览、
  船池点开 3D、当前行星高亮、应用内唤起符文置顶窗口
- 交互：一步式配置向导（能自动检测就不弹）、应用内对话框替代 prompt/confirm、
  快捷键（Ctrl+Enter / j·k / 1–4 / Esc）、记住上次查询
- 工程：界面↔接口契约测试、路径自愈（GAMEDATA/Binaries/Steam 根）、
  GUI 版 `--windowed`（无黑控制台）+ 独立 `starforge-cli.exe`

## v0.10.0-beta
- **桌面应用**：双击即开**原生窗口**（pywebview + Edge WebView2），不再弹浏览器；
  窗口大小/位置记忆；设置页与存档页有**原生「浏览…」选择框**，不用手打路径
- **3D 用种子真实配色**：从游戏数据解出主色/副色/底漆（`paint.py`），
  缩略图与 glb 都应用；同一艘船不再是灰蓝占位色
- 部件树在缺 Gagarin 数据时从游戏资源推导（已在上版），`/api/catalog` 会回报来源
- CI：打包 `pywebview`，新增 `app` 命令存在性检查

## v0.9.7-beta
- **界面重做**：左侧导航栏 + 三栏工作区（条件 / 结果 / 3D）、就绪状态芯片、
  一键配置、行星卡片、船池表格、Toast 提示；不再是一堆裸表单
- **不依赖外部数据也能用**：部件树优先读 Gagarin 的 `catalog.txt`，**缺失时从游戏 pak
  的场景描述符自己推导**（实测 53 组 / 272 部件，0 秒），搜索校验随之不再要求 GAGARIN
- 星球页打开即自动加载当前星系（不用手动扫描）；我的船列表带缩略图
- CI 修复：内置上游的断言只匹配 `Shipwright:` 行（此前被 `GAMEDATA: 未找到` 误判）

## v0.9.6-beta
- **打包版自带上游**：CI 在构建时把 NMS-Shipwright（MIT）的 `nms_save`/`nms_procgen`/
  `data/mapping.json` vendor 进包（约 0.5 MB），**用户不再需要安装 Shipwright 仓库**
  - 此前打包版读不了存档（`nms_save` 不在包里），只有命令行能跑
  - 运行时缓存 `NMS_TOOL_CACHE` 默认外置到 `~/.starforge/cache`，不往安装目录写
- 新增 `THIRD_PARTY_NOTICES.md`（含 Shipwright 的 MIT 许可说明，产物内附全文）
- `selftest` 会写明上游是"内置(打包版)"还是"同机仓库"

## v0.9.5-beta
- **修复致命打包缺陷**：此前 exe 里没有 `starforge/web/static`（漏了 `--add-data`），
  命令行能用但网页 404。现在静态资源随包发布，并新增「网页冒烟」步骤（起服务→请求首页与 app.js）
- 静态资源缺失时页面给出可读提示（而不是裸 404 / 空白），命令行功能不受影响

## v0.9.4-beta
- **首次启动自动检测路径**：游戏目录（`NMS_DIR` → Steam/GOG → 注册表）、存档目录、数据目录；
  只填空项，不覆盖已填；设置页也有「自动检测路径」按钮
- **探测增加结构兜底**：除出厂种子外，额外报告 `ShipLayout{Slots,1,1}` 结构候选（**只报告不写入**），
  用于诊断"种子被游戏归一化"的情况
- README 增加「为什么杀毒软件可能报警」

## v0.9.3-beta
- **兼容 Super Ship Hunter**：自动复用其 `R_TEMP_ROBOT`/`R_TEMP_EXOTIC` 两个模板槽，
  没装我们的模板 Mod 也能立刻验证实时通道（探测里标 `[SSH兼容]`）
- 模板槽扫描支持两条来源，自家模板优先；歧义保护不变（宁可不写）
- 修复 `icon_rgb` 会缓存失败结果、导致后续拿到位图字体的问题

## v0.9.2-beta
- **符文用游戏原图**：从 `NMSARC.TexUI.pak` 解码 BC7（texture2ddecoder），缺依赖自动退位图字体
- **一键自检 `selfcheck`**：10 步端到端，写入只在存档副本上进行
- 搜索页显示「约 1/N 的种子满足 · 预计 X 秒」

## v0.9.1-beta
- **只读探测 `live probe`**：单次遍历内存报告 8 种模板槽的候选与得分，用于远程排障
- 设置页「探测模板槽（只读）」

## v0.9.0-beta
- **实时通道**：内存定位 → 写 8 字节种子 → 回读校验；单飞/歧义拒绝/地址缓存
- **模板 Mod 生成器**：8 种 `_PROC` 各一槽，`Slots=120..127` 互不相同
- **符文置顶窗口**：`glyph-overlay`，Windows 上点击穿透、不抢焦点
- 打包修正：补 numpy/flask，产物冒烟测试

## v0.2.0-alpha
- 四页网页（搜索/我的船/星球/设置）+ 浏览器内 WebGL glb 查看器
- 服务端缩略图（点云 + 法线着色 + 2× 超采样）
- 星球/系统搜索与扇扫 API、符文弹层

## v0.1.0-alpha
- 搜索（按部件/涂装）、L1 真 3D、存档图鉴、同型换种子写回（备份/原子写/读回/回滚）
- 首次 Windows 构建；修复 cp1252 控制台下中文输出崩溃
