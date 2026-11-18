# Starforge 差距分析（GAP-ANALYSIS）

> 分析日期：2026-11-18  
> 分析对象：`/workspace/nms/starforge`（`main` @ `3e2a7a5` + 工作区未提交改动）  
> 分析方式：**只读**。未修改代码、未 commit/push、未构建。本文是唯一新增文档。  
> 参考项目：`/workspace/nms/Gagarin_Titov`、`/workspace/nms/NMS-Shipwright`、`/workspace/nms/NMS-Super-Ship-Hunter`；社区资料见文末“参考来源”。

---

## 0. 执行摘要

当前 starforge 已经完成“离线搜索 + 原生 3D 几何 + 存档读写 + 星系生成 + 符文解码 + 应用内 agent 雏形”的主干，但**产品闭环仍缺三块**：

1. **界面没有接完后端**：`services` 里已有 `apply_class`、`creatures`、`live_push`、`live_template_mod`、`start_galaxy_scan`、`diagnostics` 等能力，但原生页面没有入口；README/PLAN 宣称的“送进游戏”“同伴”“船级修改”在 UI 上并不存在。
2. **星系扫描与银河索引断开**：`GalaxyPage._scan` 调的是 `start_system_scan`（只返回命中、不落库），而“银河索引”查询/CSV 读的是 `galaxy.db`。用户扫完再查索引通常会为空（除非此前通过 API/CLI 写过库）。这是当前最影响可信度的功能 bug。
3. **agent 只有“代码”没有“实机证明”**：`starforge_agent.py` 的 `teleport/restore/scan` 已写好，但 `live/builds/185034.json` 仍是 `unverified`，`live_capabilities` 却按 agent `hello` 的 `true` 显示可用；没有 build 闸门、没有多人模式强制、没有 token/端口防护，也没有 Windows 实机回归记录。

此外，131 MB 包体存在明确可削减项（尤其 `--collect-all unicorn` 很可能把 50 MB 的 `unicorn.lib` 和头文件收进包），UI 的空态/错误态/键盘/可访问性仍停留在“能点”的水平，3D 只有“几何 + 平涂配色”，没有游戏贴图。

**结论：P0 应先修正确性与安全，P1 再补离线闭环，P2 才进入实机 agent 深水区；未实机校准的传送/扫描/建造不能标记为完成。**

---

## 1. 方法与状态定义

### 1.1 已阅读范围

- `starforge/app/pages/*.py`、`starforge/app/widgets/*.py`、`starforge/app/dialogs/*.py`、`app/shell.py`、`app/theme.py`、`app/overlay.py`
- `starforge/services/__init__.py`、`services/favorites.py`
- `starforge/agent/starforge_agent.py`
- `starforge/live/*.py`（`build.py`、`agent_install.py`、`agent_client.py`、`writer.py`、`exml.py`、`mem.py`、`scan.py`、`compat.py`）
- `starforge/save/*.py`、`starforge/search.py`、`preview.py`、`parts.py`、`galaxy.py`、`system.py`、`creature.py`、`glyphs.py`、`data/*.py`、`core/*.py`、`web/*.py`、`__main__.py`、`selfcheck.py`
- `docs/PLAN-V4.md`、`ARCHITECTURE.md`、`UI-REDESIGN.md`、`FEATURE-MAP.md`、`AGENT.md`、`AGENT-PROTOCOL.md`、`CAPABILITIES.md`、`MANUAL.md`、`CHANGELOG.md`
- `pyproject.toml`、`requirements.txt`、`packaging/*`、`.github/workflows/release.yml`
- 参考项目 README 与关键源码：Shipwright 的 `nms_save/{ships,items,extras,corvette,quests,player}.py`、`nms_procgen/{fastsearch,systemgen,model3d,corvette_parts,textures}.py`、`webapp/routes/*`；Gagarin README；SSH README 与 `hook1.4-zh.py` 的模板思路；社区工具资料。

### 1.2 状态标记

| 标记 | 含义 |
|---|---|
| ✅ | 端到端可用，当前代码路径完整，至少有一层测试或真实数据验证 |
| 🟡 | 部分实现：后端有/UI 未接、只读、只在 CLI/网页可用，或代码存在但**未实机验证** |
| ⬜ | 未实现（有明确可行路径） |
| 🔬 | R&D：依赖逆向/生成器，当前不能承诺 |
| ⛔ | 不可做/产品明确不做（技术或政策原因） |

### 1.3 重要前提与声明

- 仓库里没有 `dist/`，无法逐字节核对 131 MB 包。本文的包体构成按 `.github/workflows/release.yml` 的 PyInstaller 参数 + Windows wheel 体积**估算**，并给出可验证的削减方法；最终应以 `pyi-archive_viewer` 或解压目录实测为准。
- 当前工作区有未提交改动（`ship_lab.py` 收藏/分享、`favorites.py`、`backup.py`、`galaxy.py` 银河索引、`settings.py` 重构等）。本文按**当前工作区**实现判断，不按 `HEAD` 判断；因此 `FEATURE-MAP.md` 的“占位”描述已经部分过时。
- “守卫舰”在本文按三种可能分别讨论：**哨兵拦截机（Sentinel Interceptor）**、**护卫舰 Corvette**、**舰队护卫舰 Frigate / 货船 Freighter**。请在后续需求中明确具体指哪一个。

---

## 2. 功能矩阵（当前已实现 / 部分实现 / 未实现 / 不可做）

### 2.1 搜索

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| 按部件/涂装搜种子 | ✅ | `starforge/search.py:run` → `nms_procgen.fastsearch.fast_search`；`starforge/app/pages/ship_lab.py:_start_search` | 搜索主链可用；搜索预算/时间限制有 UI |
| 想要/不要条件 | ✅ | `ShipLabPage._checked`、`SearchQuery.want/avoid`、`search.validate` | 同插槽组多选只在提交时由后端拒绝，UI 无即时提示 |
| 涂装筛选（主色/副色） | 🟡 | `search.look_kind/colour_matches`；UI `ShipLabPage._pick_color` | **UI 只把主色传给 `look`**，副色按钮存在但 `_start_search` 未使用；无索引模式、undercoat、mode、容差滑块 |
| 多核搜索 | 🟡 | `fast_search(workers=...)` | `Services._query` 默认 `workers=1`，UI 不传 `workers`；实际基本单核 |
| 搜索进度/ETA/取消 | 🟡 | `jobs.Job.update`、`fast_search(should_stop)`、`ShipLabPage._poll_job` | 有进度；**UI 没有取消按钮**，`JobDock` 也不能取消 |
| 搜索估算 | 🟡 | `services.search_estimate`、`search.explain` | 后端有，原生 UI 未调用 |
| 结果网格/列表 | ✅ | `QListWidget` + `ShipCardDelegate` + `install_card_delegate` | 无排序、筛选、多选、对比 |
| 缩略图 | ✅ | `services.preview_png` → `render.ship_png`；`_next_thumb` | 串行排队，30–50 ms 一个；无并发/取消 |
| 原生 3D | 🟡 | `ShipViewer`、`services.preview_mesh` | 有几何/旋转/缩放/预设视角/自转/截图；**无贴图、无部件高亮、无 LOD** |
| 复制种子 | ✅ | `ShipLabPage._copy_seed` | — |
| 收藏 | 🟡 | `services/favorites.py`、`ShipLabPage._toggle_fav` | 可收藏/取消；**没有收藏列表页/管理/导入导出 UI** |
| 分享码 | 🟡 | `favorites.encode_share/decode_share`、`_copy_share/_import_share` | 可用；无批量分享、无二维码、无版本迁移 |
| 写回存档 | ✅ | `WriteBackDialog` → `services.apply_seed` → `save/writer.apply_seed` | 仅同型、单槽；批量/新建槽未接 |
| 导出 glb | ✅ | `services.glb_path`、`_export_glb` | 只有路径提示，没有“打开所在文件夹” |
| 批量导出 | 🟡 | `starforge/export.py:export_zip` | 后端完整；Fleet“导出全部”仍 `setEnabled(False)` |
| 种子→星系反查 | 🟡 | `services.locate`、`system.locate_seed` | 后端完整；ShipLab“更多”禁用，**无 UI 入口** |
| 设计器/任意部件组合 | ⬜ | `nms_procgen.generator`、`model3d` 可用 | 无“设计器”页面；只能搜索，不能逐部件拼装并反求 seed |
| 对比托盘/分享码导入结果 | 🟡 | 分享码导入有；对比无 | 无多选/对比视图 |

### 2.2 3D

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| 原生 OpenGL 视口 | ✅ | `starforge/app/widgets/ship_viewer.py:ShipViewer` | GL 2.1 Compatibility；4x MSAA；失败回退 PNG |
| 从游戏 pak 读几何 | ✅ | `services.preview_mesh` → `nms_procgen.model3d.ship_model` | 需游戏目录；无游戏走 L0 PNG |
| 真实配色 | 🟡 | `starforge/paint.py:look` → `nms_procgen.textures.ship_look` | 按材质类取主色/副色/底漆；不是贴图 |
| 游戏贴图/UV 材质 | ⬜ | `gltf.py` 保留 `TEXCOORD_0`；`ship_viewer._upload` 不使用 UV | 3D 是“几何 + 平涂 + 光照”，与游戏内/缩略图有差距 |
| 视角预设/自转/截图 | ✅ | `ShipViewer.set_view/set_spin/snapshot_png` | — |
| 服务端渲染兜底 | ✅ | `services.preview_png`、`ShipLabPage._show_fallback` | 3D 初始化失败 1.5 s 后才检测，略慢 |
| glb 导出 | ✅ | `preview.glb_for` → `gltf.build_glb` | glb 无贴图/无 image，仅 PBR baseColor |
| 部件级 3D | 🟡 | `preview.part_model`、`part_png` | 只用于 26/48 px 小图标；无大图/爆炸图 |
| 多船对比 3D | ⬜ | — | Fleet“加入对比”禁用 |
| Corvette 3D | ⬜ | Shipwright `model3d.corvette_model` 可用 | 无服务/页面 |
| 生物 3D | 🔬 | `creature.capabilities` 已判定当前不可画 | 见 2.8 |
| LOD/实例化/大模型内存 | ⬜ | `ShipViewer._upload` 用 `glDrawArrays` 展开索引 | 索引展开使顶点内存约 ×1，但丢失复用；无 LOD/分块 |

### 2.3 存档

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| 扫描存档目录 | ✅ | `save/library.scan_dir`、`probe/classify` | 能区分 player/account/manifest；UI 未使用完整扫描 |
| 读船列表/属性 | ✅ | `save/library.open_ships`、`nms_save.ships.list_ships/ship_stats` | 带缓存；固定模型有警告 |
| 同型换种子写回 | ✅ | `save/writer.apply_seed` | 备份→原子写→读回→回滚；跨型拒绝 |
| 船级/属性写回 | 🟡 | `save/writer.apply_class`、`services.apply_class` | **后端完整，无 UI**；Fleet/ShipLab 都没有入口 |
| 备份列表/恢复 | ✅ | `save/writer.backups/restore`、`app/dialogs/backup.py` | 新增对话框已接；无保留策略/批量清理 |
| 默认存档选择 | 🟡 | `save/library.default_save_path` | 只优先 `save.hg/save2.hg`；UI 不能切换多个存档槽 |
| 新建/删除/改名飞船 | ⬜ | Shipwright `ships.create_ship/remove_ship/set_ship_name` | 无服务封装/UI |
| 涂装写回/清除 | ⬜ | Shipwright `ships.set_ship_paint/clear_ship_paint/set_texture_options` | 无 UI；`paint.look` 只读 |
| 库存/物品编辑 | ⬜ | Shipwright `items.edit_inventory/list_inventories` | 未接 |
| 解锁/词语/任务/奖励 | ⬜ | Shipwright `extras.learn_all/learn_words`、`quests.skip_quests`、`extras.rewards` | 未接 |
| 多工具/货船/护卫舰/中队 | ⬜ | Shipwright `extras.multitools/edit_multitool`、`frigates/edit_frigate`、`ships.get_freighter/set_freighter` | 未接 |
| 同伴写回 | ⬜ | Shipwright `extras.edit_companion` | 未接；当前 `creature` 只读 |
| JSON 导出/导入/原始编辑 | ⬜ | Shipwright `extras.browse/get_path/set_path` | 未接 |
| 冷传送（改存档位置） | ⬜ | NMSCoordinates 路线；Shipwright 无 setter | 需逆向/验证玩家位置字段；有存档损坏风险 |
| Steam Cloud 覆盖检测 | ⬜ | — | 写后可能被云存档回滚；需检测/提示 |
| 游戏运行中写入拦截 | ✅ | `save/writer.game_running` | Windows Toolhelp；Linux /proc 兜底 |

### 2.4 船队

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| 自动找存档/读船 | ✅ | `FleetPage._auto/_load`、`services.default_save/ships` | 只能用一个默认存档 |
| 卡片/列表切换 | ✅ | `FleetPage._apply_view_mode`、`ShipCardDelegate` | — |
| 缩略图/3D/属性 | ✅ | `_next_thumb`、`_select` → `preview_mesh` | 串行缩略图；3D 同 2.2 |
| 备份/恢复 | ✅ | `FleetPage._open_backups` → `BackupDialog` | 新增；无“保留 N 份”设置 |
| 批量导出 | 🟡 | `export.export_zip` 后端 | 按钮禁用 |
| 多船对比 | ⬜ | — | 对比按钮禁用 |
| 船级/改名/涂装编辑 | ⬜ | `apply_class` 后端 | 无 UI |
| 多选/排序/筛选 | ⬜ | — | 只能单选 |
| 护卫舰/货船标签页 | ⬜ | Shipwright `extras.frigates`、`ships.get_freighter` | 无页面 |
| 同伴标签页 | ⬜ | `services.creatures` 后端 | 无页面；见 2.8 |
| 中队/僚机 | ⬜ | NMSSaveEditor 路线 | 未做 |

### 2.5 星球

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| 当前星系/行星表 | ✅ | `GalaxyPage._load_current` → `services.system`（子进程） | 群系/哨兵/资源/dissonant 有；天气/动植物缺 |
| 按条件扫描 | 🟡 | `GalaxyPage._scan` → `services.start_system_scan` → `system.scan` | 能出结果；**不落库**；radius 固定 0；无中心/半径选择 |
| 扫描进度 | ⬜ | `GalaxyPage._poll_scan` 读 `job.progress` | `start_system_scan` 在子进程里没有 `job`，**进度直到结束才更新** |
| 扫描取消 | ⬜ | `Job.cancel` 只设事件 | 子进程不读事件；UI 无取消按钮 |
| 银河索引查询 | ✅ | `GalaxyPage._query_index` → `services.galaxy_query` → `GalaxyStore.query` | 新增；但索引通常为空，见下 |
| 扫描入库 | ⬜ | `services.start_galaxy_scan` → `galaxy.scan` | **后端存在但 UI 未调用**；这是索引空白的根因 |
| CSV 导出 | 🟡 | `services.galaxy_export_csv`、`GalaxyPage._export_*` | 导出的是 `galaxy.db`；扫描不入库时导出空 |
| 行星详情（天气/资源/动植物） | 🟡 | `system.PLANET_FIELDS` 明确 `need_game` | 离线拿不到；只能 agent `planet` 补 |
| 行星 3D/地表/资源分布 | ⬜ | Shipwright `systemgen`/`model3d` 无行星地表 | 需新生成器/agent；不在当前范围 |
| 种子→星系反查 | 🟡 | `system.locate_seed` | 无 UI 入口 |
| 传送地址/航线提示 | 🟡 | `system.locate_seed` 返回 `portal_hint` | UI 未显示 |
| 符文置顶浮窗 | 🟡 | `app/overlay.py`、CLI `glyph-overlay` | 页面无按钮；见 2.6 |
| nmsce 社区坐标导入 | ⬜ | — | 网络/第三方；可选 P3 |
| 星系图/银河地图 | ⬜ | — | 无可视化地图；仅表格 |

### 2.6 符文

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| UA/地址→12 位符文 | ✅ | `glyphs.digits_for/glyphs_for_ua` | 按位段重排；有测试 |
| 游戏原版图标（BC7） | ✅ | `glyphs.icon_rgb/_decode_dds` | 缺 `texture2ddecoder`/pak 时退回位图字体 |
| 12 联符文图 | ✅ | `glyphs.panel_png/panel_payload` | 页面可显示/复制 |
| 复制符文 | 🟡 | `GalaxyPage._copy_glyph` 从 badge 文本按 `·` 分割 | 脆弱；应保存 `glyphs` 字段而不是解析 UI 文本 |
| 置顶浮窗（Qt） | ✅ | `app/overlay.py:GlyphOverlay`、`__main__.cmd_glyph_overlay` | 仅 CLI；点击穿透/透明度/缩放只有 CLI 参数 |
| 页面内“置顶显示” | ⬜ | — | 无按钮；`services` 没有 overlay 方法 |
| 跟随选中自动更新 | ⬜ | — | 浮窗是一次性快照 |
| 多显示器/位置记忆 | ⬜ | `GlyphOverlay` 只用 `primaryScreen` 居中 | 无记忆/多屏选择 |
| 透明度/大小设置 | 🟡 | CLI `--alpha/--scale` | 无设置页/持久化 |

### 2.7 游戏内 agent

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| 运行时检测/安装 | 🟡 | `live/agent_install.runtime_python/bootstrap_runtime` | 正常包内置；损坏时联网下载；版本不一致（见 6） |
| Mod 安装/注入/停止 | 🟡 | `install_mod/launch/stop` | `launch` 是 pymhf 子进程；`stop` 只杀 launcher，未必解注入 |
| 连接状态/能力表 | 🟡 | `GameLinkPage.refresh`、`services.live_capabilities`、`agent.hello` | 能显示三步状态；能力表信任 agent 的 `true` |
| 读玩家/星系/行星/船槽 | 🟡 | `agent.player/system/planet/ships`、`GameLinkPage._read` | 代码存在；**未实机验证** |
| 传送/还原 | 🟡 | `agent.teleport/restore`、`GameLinkPage._teleport` | 代码存在；快照仅内存；无多人/ build 闸门；未实机验证 |
| 扫描读取/即时扫描 | 🟡 | `agent.scan/scan_instant` | `scan.discover` 明确 `false`；未实机验证 |
| 扫描发现写入 | ⬜ | `agent.scan` 只读 | 需发现管理器偏移 |
| 位置传送（x,y,z/落点） | ⬜ | 协议有 `teleport.position` | agent 未实现 |
| 任意建造/改色/解上限/HUD | ⬜ | `PLAN-V4` M7 | 未实现 |
| 多人模式强制禁用 | ⬜ | `hello` 返回 `multiplayer` | 命令没有检查；文档说会禁用，代码未做 |
| build 校验/未知 build 只读 | ⬜ | `live/build.py` 有 `write_allowed` | `agent_call`/UI 未使用；`185034.json` 仍 `unverified` |
| 本机 HTTP 安全 | ⬜ | `AgentClient.DEFAULT_BASE` 固定 5000 | 无 token、无 Host/Origin 校验；同机任意进程可调用 |
| agent 日志/健康 | 🟡 | `launcher.log` | UI 不展示；无 tail/copy |
| 卸载/还原 | 🟡 | `uninstall_mod` 存在 | 无 UI；不涉及 winmm.dll（与部分文档描述不一致） |

### 2.8 生物/同伴

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| 读存档同伴 | ✅ | `creature.companions`、`services.creatures` | 后端完整；**无 UI 页面** |
| 生物角色表/结构 | ✅ | `creature.role_names/role_table` | 后端可读 86 条；无 UI |
| 能力边界诚实报告 | ✅ | `creature.capabilities` | 明确 `preview_possible=False` |
| 同伴写回（名字/体型/种子/描述符） | ⬜ | Shipwright `extras.edit_companion` | 未接 |
| 按外观搜同伴 | ⬜ | NMSCD Creature Builder 路线 | 需要描述符/生成器 |
| 同伴 3D | 🔬 | `creature.capabilities` 已判定当前不可 | 描述符词表与静态 rig 不同源；需运行时生成器 |
| 蛋/性状/信任/情绪编辑 | ⬜ | 社区/NMSSaveEditor | 未做 |
| Creature Builder 导入/导出 | ⬜ | NMSCD JSON | 未做 |

### 2.9 设计器

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| 逐部件拼装飞船 | ⬜ | `parts.tree`、`model3d.ship_model` 可用 | 无设计器页面；ShipLab 只能勾条件搜索 |
| 选型即时 3D | ⬜ | `ShipViewer.set_mesh` 可复用 | 无“未选 seed 的部件组合”预览 |
| 由设计反求 seed | 🟡 | `fastsearch`/`generator` 可支持 | 无 UI/服务编排 |
| 新建飞船到存档槽 | ⬜ | Shipwright `ships.create_ship` | 未接 |
| 设计保存/载入 | ⬜ | Shipwright `designs`/webapp routes | 未接 |
| 设计分享码 | 🟡 | `favorites` 分享 seed/parts | 不是完整设计文件；无版本 |
| 改色/涂装 | ⬜ | Shipwright `set_ship_paint` | 未接 |
| Corvette 设计器 | ⬜ | `corvette_parts`、`corvette_model`、`nms_save.corvette` | 未接 |
| 货船/护卫舰拼装 | ⬜ | Shipwright 提供部分数据 | 未接 |

### 2.10 守卫舰 / 护卫舰 / 货船

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| 哨兵拦截机搜索 | ✅ | `search.SEARCHABLE` 含 `sentinel`；`fastsearch` | 已有 |
| 哨兵拦截机外观/种子 | ✅ | `ShipRef`/`model3d` | 已有 |
| Corvette 读取 | ⬜ | `nms_save.corvette.layouts/modules` | 无 UI/服务 |
| Corvette 建造/写回 | ⬜ | `nms_save.corvette.place/move/replace/write_both` | 无 UI |
| Frigate 列表/属性/修复 | ⬜ | `nms_save.extras.frigates/edit_frigate` | 无 UI |
| Freighter 读取/写入 | ⬜ | `nms_save.ships.get_freighter/set_freighter` | 无 UI |
| 中队/僚机 | ⬜ | NMSSaveEditor 路线 | 无 |
| 游戏内实机验证 | ⬜ | — | 全部未验证 |

### 2.11 设置

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| 游戏/存档/数据路径 | ✅ | `SettingsPage._load/_save`、`settings.update` | 有原生目录选择 |
| 自动检测 | ✅ | `settings.autodetect`、`locate_game` | 有 |
| 写入开关 | ✅ | `settings.require_write` | 有 |
| 二次确认配置 | 🟡 | `settings.confirm_writes` | 无 UI；写回对话框硬编码确认 |
| 备份保留数 | 🟡 | `settings.backup_keep` | 无 UI；`writer` 也没实现清理 |
| 主题/外观 | ⬜ | `settings.theme` 字段 | 无主题切换；QSS 固定深色 |
| 端口 | 🟡 | `settings.port` | Web 用；原生/agent 未用 |
| 性能（workers/缓存） | ⬜ | — | 无 |
| 实验性开关 | ⬜ | — | 传送/扫描/建造没有统一开关 |
| 缓存清理/重置 | ⬜ | — | 无 |
| 更新检查 | ⬜ | README 提到“检查更新” | 未实现 |
| 语言 | ⬜ | `core/strings.py` 单点中文 | 仅中文；无切换 |
| 关于/许可 | 🟡 | `SettingsPage` 有简短 About | 无第三方许可全文/版本列表 |

### 2.12 诊断

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| 环境体检 | ✅ | `Services.doctor`、`__main__.cmd_doctor` | 依赖/unicorn/systemgen/health |
| 端到端自检 | 🟡 | `selfcheck.run`、`Services.diagnostics` | 后端完整；**Settings 未接 `diagnostics`** |
| 路径检查 | 🟡 | `web/routes._path_checks` | 只在 Web API；原生设置没有逐项红/绿 |
| 诊断导出 | 🟡 | `SettingsPage._export_diag` | 只导出 JSON（health/settings/doctor）；无日志/崩溃栈/build/agent 日志 |
| 崩溃日志 | 🟡 | `app/main._enable_crash_log` | 写 `faulthandler.log`；UI 无入口查看 |
| 日志查看/复制 | 🟡 | 打开日志目录 | 无内置 tail/搜索/复制诊断 |
| webcheck/selfcheck UI | ⬜ | CLI 有 | 无按钮 |
| build 指纹显示 | 🟡 | `live/build.py` | GameLink 状态里间接有，设置/诊断无明确展示 |
| 一键诊断包（zip） | ⬜ | — | 无 |

### 2.13 打包

| 功能 | 状态 | 现有实现（文件:函数） | 缺口/说明 |
|---|---|---|---|
| Windows onedir + zip | ✅ | `.github/workflows/release.yml` | PyInstaller onedir；Release zip |
| 内置 Shipwright | ✅ | `packaging/vendor.py` | 只复制运行必需部分（~1.5 MB） |
| 内置 agent runtime | 🟡 | `packaging/build_agent_runtime.py` | 构建 3.11.9；应用运行时期待 3.12.8（不一致） |
| 原生 Qt 依赖 | ✅ | release.yml 检查 `Qt6Core/Widgets/OpenGLWidgets` | — |
| 安装包/签名 | ⬜ | — | 只有 zip；无 MSI/安装器/代码签名 |
| 自动更新 | ⬜ | — | 无 |
| 体积控制 | 🟡 | 131 MB；CI 无体积断言 | `--collect-all unicorn` 等存在明显浪费 |
| 干净机器冒烟 | 🟡 | CI `--help/selftest/doctor/webcheck/serve` | 只覆盖 CLI/网页，不覆盖原生 UI/3D |
| 可复现依赖 | 🟡 | `requirements.txt` 部分 pin | `unicorn>=2.0`、`pymhf>=0.2.5`、`PySide6>=6.7` 未锁定 |
| 图标/版本资源 | ⬜ | — | 未见 `.ico`/版本信息注入；需确认 |
| 非 Windows | ⛔ | 目标平台 Windows 10/11 | 不作为当前目标；离线核心可跑 Linux，但不承诺 |

---

## 3. 关键缺口逐项（参考来源 / 方案 / 依赖 / 风险 / 验收）

> 本节只列“需要动的缺口”。已完成项不重复。每个缺口都给出可执行的落点和验收口径；验收必须能在 CI 或 Windows 实机上复现。

### G01 搜索涂装/多核/估算未接完

- **参考来源**：NMS-Shipwright `nms_procgen/textures.py:ship_look/look_mask`、`fastsearch.py` 多进程；Gagarin 的按颜色筛船；nmsce 按颜色/部件筛选。
- **可行方案**：`ShipLabPage._start_search` 把 `self.secondary`、`self.look_on`、`tol`、`workers` 一起写入 payload；`Services._query` 默认 `workers=os.cpu_count()`（可设置覆盖）；启动前调 `services.search_estimate` 显示“1 in N / 预计秒数”；RGB 模式预算/候选数显示在状态栏。
- **依赖**：`fastsearch.fast_search` 已支持 `workers`；`search.validate` 已支持主/副色；无需新库。
- **风险**：多核在小机器上可能拖慢 UI；RGB 后置过滤可能返回不足；需要明确“已扫候选/预算”。
- **验收**：同一条件在 4 核机器上吞吐 ≥ 单核 1.5×；勾选副色后结果中每艘的 `look_match.secondary` 距离 ≤ tol；估算值与实测偏差 < 50%；UI 状态栏显示估算和 worker 数。

### G02 任务取消/JobDock 不可操作

- **参考来源**：`jobs.Job.should_stop`；Shipwright webapp 的 job cancel API；UI-REDESIGN 的 JobDock。
- **可行方案**：`JobDock` 增加“取消”按钮 → `services.cancel_job`；`Services._internal` 改为 `Popen` 并保存句柄，取消时 `terminate()`；`start_system_scan/start_galaxy_scan` 把 job 的取消映射到子进程；搜索任务保持协作式取消。
- **依赖**：`subprocess.Popen`；Windows `CREATE_NO_WINDOW`；无需新库。
- **风险**：强杀 Unicorn 子进程可能留下缓存半成品；需只清理临时文件。
- **验收**：系统扫描中点取消 1 s 内 UI 显示“已取消”，子进程退出；搜索取消后 `job.status == "cancelled"`；再次扫描可正常开始。

### G03 种子→星系反查没有 UI

- **参考来源**：Shipwright `nms_procgen/locate.locate` + `systemgen.confirm`；NMSCoordinates 的坐标反查/传送地址。
- **可行方案**：ShipLab Inspector 的“更多”菜单加“查它在哪个星系”；调用 `services.locate`（子进程），结果表显示坐标/符文/where/what/visited；提供“复制符文”“置顶显示”。
- **依赖**：游戏 `NMS.exe` + PCBANKS；`system.locate_seed` 已实现。
- **风险**：反查本身欠定（只有部分种子能反解）；`max_steps` 大时慢；需明确“候选/已证实”。
- **验收**：用存档中已知船的 seed 反查到自身星系（已有 `test_locate_real_save_ship_hits_own_system` 路线）；UI 区分“候选”和“已证实”；无结果时提示“反查欠定”而不是报错。

### G04 批量导出/对比

- **参考来源**：Shipwright webapp `designer`/`ships` 导出；NMS-Shipwright README 的“保存设计/分享”；NMSCoordinates 的 location JSON 分享。
- **可行方案**：Fleet 多选 + “导出所选”调用 `export.export_zip`；对比托盘最多 3 艘，复用 `ShipViewer` 小视口 + 属性差异表；ShipLab 结果支持多选加入对比。
- **依赖**：`export.export_zip` 已完整；`ShipViewer` 可多实例（注意 GL 上下文数量）。
- **风险**：多 GL 视口显存/驱动；批量导出大 glb 占内存；需限制并发。
- **验收**：导出 zip 含 `manifest.json` + glb/png；对比 3 艘属性差异高亮；取消/失败有明确提示。

### G05 3D 没有游戏贴图

- **参考来源**：Shipwright `nms_procgen/textures.py`、`model3d.py`、`shiptex.py`；`tex.py` 已有 DDS 采样；`render.rasterize` 已用贴图。
- **可行方案**：`ShipViewer` 增加纹理路径：按 `(class, tex)` 从 `tex.ship_textures`/pak 解出 DDS，上传 GL 纹理，片元着色器采样 `uv`；`gltf.build_glb` 增加 `images/textures/samplers`（或至少把贴图作为外部 png 写入导出包）；保留平涂降级。
- **依赖**：`texture2ddecoder`、`hgpaktool`、游戏 `NMSARC.Tex*.pak`；`tex.py` 已有 `dds_bytes/describe/rgba/sample`。
- **风险**：贴图格式/材质映射不稳；显存；GL 2.1 纹理格式限制；可能拖慢首次加载。
- **验收**：同一艘船原生 3D 与服务端渲染图的主色/贴图区域一致（截图对比）；无贴图时自动平涂并说明；glb 在外部查看器能看到贴图或明确“无贴图”。

### G06 3D 部件高亮/拆解/对比/LOD

- **参考来源**：Gagarin 的 ship builder 逐部件预览；Shipwright `model3d._picked_meshes`/`corvette_model`；UI-REDESIGN 的“3D 是主体”。
- **可行方案**：`ShipViewer` 支持按 `(class, tex)`/部件 id 高亮/隐藏/爆炸位移；ShipLab 部件树 hover/选中联动；大模型按组拆分 VBO + 简单 LOD（按屏幕占比降采样）。
- **依赖**：`preview.part_model` 已能取单部件几何；需把部件 id 与 group 关联。
- **风险**：几何组与部件不是一一对应；爆炸图可能误导；LOD 实现复杂。
- **验收**：选中部件树节点，3D 对应部件高亮且其它部件变暗；隐藏/显示可逆；100k 三角模型旋转 ≥ 30 FPS（目标机器）。

### G07 多存档槽/备份策略

- **参考来源**：NMSCoordinates 的 Save Manager（多存档备份/恢复）；NMSSaveEditor 的备份/恢复；Shipwright 的备份策略。
- **可行方案**：Fleet 顶部加存档下拉（`services.saves` 返回 `usable` 列表）；设置加 `backup_keep` 并在 `writer._backup` 后清理旧备份；恢复前展示“当前快照”。
- **依赖**：`library.scan_dir` 已返回 `usable`；`settings.backup_keep` 已有字段。
- **风险**：误删备份；多存档路径识别；Steam Cloud。
- **验收**：能在 `save.hg/save2.hg` 间切换并读船；设置保留 N 份后旧备份按时间清理；恢复后读回成功。

### G08 船级/属性/改名/涂装写回 UI

- **参考来源**：Shipwright `ships.set_ship_stats/set_ship_name/set_ship_paint`；NMSSaveEditor 的 Ships 页。
- **可行方案**：Fleet Inspector 增加“编辑”面板：船级 C/B/A/S、属性只读区间校验、改名、主/副色；调用 `services.apply_class` 和新增 `services.apply_name/apply_paint`；所有写入复用 `writer` 的备份/原子写/读回/回滚。
- **依赖**：`writer.apply_class` 已完整；`ships.set_ship_name/set_ship_paint` 上游可用；需新增服务封装。
- **风险**：属性超出游戏区间会造不可能船；涂装对部分拦截机无效（seed colour only）；跨型不可移植。
- **验收**：C→S→C 写回读回一致（已有测试）；其它船 seed 未变；改名/涂装进游戏可见；失败自动回滚。

### G09 通用存档编辑器（安全字段优先）

- **参考来源**：NMSSaveEditor（货币/库存/飞船/货船/护卫舰/同伴/奖励/原始 JSON）；Shipwright `items/extras/quests`；NoMansConnect 的备份/恢复。
- **可行方案**：先做“安全字段”：货币（`player.get/set_currencies`）、船级/属性（已有）、同伴名字/体型（`extras.edit_companion`）、多工具/护卫舰只读；再做库存编辑（`items.list_inventories/edit_inventory`）与解锁/词语/任务（`extras.learn_all`、`quests.skip_quests`）。所有写入统一走 `save/writer` 的备份/原子写/读回/回滚，并加字段级白名单。
- **依赖**：Shipwright 上游 API；存档版本兼容；`nms_save.mapping`。
- **风险**：库存越界/任务状态损坏；账号数据（`accountdata.hg`）不应混入；产品“不修改玩家资产”与编辑器冲突，需要产品决策。
- **验收**：每个字段有“改前/改后/读回”JSON；只改目标字段；失败回滚；在真实存档副本上通过；文档明确“不支持 accountdata”。

### G10 库存/解锁/任务/奖励

- **参考来源**：NMSSaveEditor；Shipwright `items.py`、`extras.py`、`quests.py`。
- **可行方案**：分页面：库存网格（拖拽/堆叠/修复/充能）、解锁（技术/产品/词语/符文）、任务跳过、奖励（远征/Twitch/平台）。先只读渲染，再逐项开放写。
- **依赖**：`items.inventory_caps/stat_ranges` 做区间校验；`quests.list_quests/skip_quests`。
- **风险**：库存上限/槽位扩展可能导致存档不加载；任务跳过可能卡剧情；奖励 ID 随版本变化。
- **验收**：库存移动/添加/修复后读回一致；任务状态只改目标 key；奖励解锁在游戏内可见；每个操作有备份。

### G11 多工具/货船/护卫舰/中队

- **参考来源**：NMSSaveEditor；Shipwright `extras.multitools/edit_multitool`、`frigates/edit_frigate`、`ships.get_freighter/set_freighter`。
- **可行方案**：Fleet 增加“货船/护卫舰/多工具/中队”标签；先只读列表+属性，再开放改名/等级/属性/修复；货船种子/模型写回复用 `set_freighter`。
- **依赖**：上游 API；存档字段版本。
- **风险**：货船/护卫舰槽位结构随版本变；中队涉及 NPC 数据；写错可能丢船。
- **验收**：只读列表与游戏内一致；写回读回一致；失败回滚；至少一艘实机验证。

### G12 同伴写回/搜索/3D

- **参考来源**：NMSSaveEditor 同伴页；NMSCD Creature Builder 的部件兼容/JSON；`creature.role_table`；Shipwright `extras.edit_companion`。
- **可行方案**：
  - P2：Fleet 增加“同伴”只读表（名字/类型/群系/体型/种子/描述符/角色表匹配），复用 `services.creatures`。
  - P2：写回名字/体型/信任（`extras.edit_companion` 或直接 JSON 字段），统一备份/读回。
  - P3/R&D：按 NMSCD 的部件兼容表做“同伴设计器”；3D 需运行时生物生成器或描述符→网格链，当前 `creature.capabilities` 已判定不可。
- **依赖**：存档 `Pets[]`；NMSCD 数据（可选）；游戏 `CreatureDataTable.mbin`。
- **风险**：描述符与静态 rig 不同源；写坏导致“无实体”同伴；3D 可能永远无法离线。
- **验收**：只读 29 只同伴与存档一致；改名/体型写回进游戏可见；3D 未实现时 UI 明确显示“需运行时生成器”，不画饼。

### G13 飞船设计器

- **参考来源**：Shipwright webapp `routes/designer.py`（design tree、model、designs、install）、`generator.py`、`fastsearch.py`；Gagarin 的 ship builder；nmsce 的按部件浏览。
- **可行方案**：新增 `app/pages/designer.py`（或在 ShipLab 加“设计模式”）：左侧部件树（同 `parts.tree`），中间 `ShipViewer` 实时组装（需要“无 seed 的部件组合”几何：`model3d.ship_model(seed=?, parts=...)` 的 seed 取任意/0 可能不合法，需要上游支持按 parts 直接取网格；可先用 `_picked_meshes`），右侧“找这个设计”的 seed 搜索 + “写进存档”槽位选择；设计保存为 JSON（`type/parts/name`）。
- **依赖**：`model3d` 的 parts 组装；`fastsearch` 反求；`ships.create_ship`；上游是否支持“无 seed 组装”需 spike。
- **风险**：不是所有部件组合都合法；同型限制；几何组装/法线/贴图；写新船可能影响槽位。
- **验收**：选 5 个部件能实时显示；搜索到 seed 后重新生成外观与设计一致；写入副本后读回/进游戏一致；设计 JSON 可保存/载入。

### G14 Corvette / 货船 / 护卫舰拼装

- **参考来源**：Shipwright `nms_save/corvette.py`、`nms_procgen/corvette_parts.py`、`model3d.corvette_model`、webapp `routes/corvette.py`；NMSSaveEditor 的货船/护卫舰页。
- **可行方案**：先只读 Corvette：读 `layouts/modules`，用 `model3d.corvette_model` 渲染，列出模块名/位置；再做拖拽/旋转/镜像/撤销（参考 Shipwright builder.js 的交互）；写回前校验槽位/模块/碰撞，备份/读回。货船/护卫舰先做列表/属性/修复。
- **依赖**：上游 corvette API；`nms_save.corvette.write_both` 的备份；UI 3D 交互。
- **风险**：Corvette 模块/吸附规则复杂；写坏可能丢船；版本绑定。
- **验收**：只读模块与游戏内一致；移动/旋转/镜像后模型同步；写回副本读回一致；实机至少验证一艘。

### G15 星球扫描入库/进度/取消

- **参考来源**：Shipwright `systemgen.scan`（批量生成）；`galaxy.scan`（落库）；NMSCoordinates 的坐标管理。
- **可行方案**：`GalaxyPage._scan` 改为调用 `services.start_galaxy_scan`（或提供“只列结果/写入索引”二选一）；`galaxy.scan` 在子进程内通过 stdout JSON Lines 上报 `scanned/found/seconds`；`Services._internal` 解析进度并更新 job；扫描完成刷新 `galaxy_stats`/索引页。若暂不做流式，至少扫描结束后自动刷新索引统计，并明确“已写入索引”。
- **依赖**：`galaxy.GalaxyStore.upsert_system`；`systemgen`；子进程 IPC。
- **风险**：长时间扫描/磁盘增长；Unicorn 崩溃；重复扫描去重（已有 upsert）。
- **验收**：扫描后 `galaxy_stats.systems` 增加；索引查询能查到刚扫的星系；扫描中进度每秒更新；取消后子进程退出且库不半写（事务/逐条 commit 可接受）。

### G16 行星天气/资源/动植物实时字段

- **参考来源**：Gagarin `Scan planet`/planet table；`agent.planet`；Shipwright `systemgen` 的 `PLANET_FIELDS` 明确离线不可得。
- **可行方案**：离线只显示 `biome/sentinels/seed`；连接 agent 后点“读取当前行星”补 `weather/flora/fauna/resources/sentinels`；在 UI 标注字段来源（离线/游戏内）。不要让离线表伪装成完整。
- **依赖**：agent `planet` 端点；NMSpy 结构体；游戏运行。
- **风险**：字段偏移/版本；多人；agent 不稳定。
- **验收**：离线时明确“天气/资源需连接游戏”；连接后与游戏内扫描面板一致（人工对照）；失败有原因。

### G17 行星 3D/地表/资源分布

- **参考来源**：Gagarin 的行星表/扫描；Shipwright 无行星地表生成；NoMansConnect 的银河地图（位置可视化）。
- **可行方案**：短期做“行星卡片 + 群系色带 + 资源标签”，不做地表 3D；中期若要做，需行星高度图/生物群系生成器或 agent 读取，属于新 R&D，不应放在 P1。
- **依赖**：游戏生成器/agent；或新逆向。
- **风险**：工作量巨大；版本绑定；可能无法离线。
- **验收**：若做，需有真实行星截图对照；否则 UI 明确“未实现”，不展示假 3D。

### G18 符文置顶浮窗 UI/交互

- **参考来源**：Gagarin 的 Portals 页（12 符文 + Apply）；starforge `app/overlay.py`；NMSCoordinates 的坐标分享。
- **可行方案**：Galaxy 页“复制符文”旁加“置顶显示”；调用 `app.overlay.show(digits, panel_png, alpha, click_through)`（注意 Qt 事件循环：主窗口已存在 `QApplication`，`show()` 里 `app.exec()` 会阻塞/嵌套，需要改成 `GlyphOverlay` 非阻塞实例并保存引用）；设置页加透明度/大小/点击穿透；浮窗跟随当前选中（信号更新 pixmap）。
- **依赖**：PySide6；Windows 置顶/点击穿透 API；`glyphs.panel_png`。
- **风险**：Qt 嵌套事件循环；多显示器；点击穿透后无法拖动；游戏全屏模式看不到（需无边框窗口）。
- **验收**：从 Galaxy 页一键显示 12 符文；Esc 关闭；点击穿透可开关；切换选中后浮窗更新；Windows 实机在无边框窗口可见。

### G19 模板槽“送进游戏” UI

- **参考来源**：NMS-Super-Ship-Hunter 的模板槽 + 外部写；starforge `live/exml.py`、`live/writer.py`、`services.live_push/live_template_mod`。
- **可行方案**：ShipLab Inspector 加“送进游戏（模板槽）”：先生成/安装 `starforge-templates`（`live_template_mod`），再 `live_probe` 显示候选，再 `live_push`（需写开关 + 二次确认 + 管理员提示）；GameLink 页也提供入口。明确“只写 8 字节模板种子，不碰你的船”。
- **依赖**：Windows、游戏运行、模板 Mod 已安装、`mem.attach`、写开关。
- **风险**：定位歧义拒绝写入；游戏版本/模板未装；杀软；写错模板槽。
- **验收**：`live_probe` 对每种船型给出候选/置信度；唯一可信时写入并回读；多候选时拒绝并说明；实机领取模板船外观正确。

### G20 agent build 闸门 / 安全 / 版本

- **参考来源**：NMS.py/NMSpy 的 build 绑定；Gagarin 的版本闸门（不支持版本不激活）；starforge `live/build.py`、`AGENT-PROTOCOL.md` 的 `E_SIGNATURE_MISSING/E_AMBIGUOUS`。
- **可行方案**：
  - `Services.agent_call` 对写命令（`teleport/restore/scan.instant/scan.discover`）先查 `build.summary()["write_allowed"]`；未知/未验证 build 只允许只读。
  - `agent.hello` 返回 `build_id`/`write_allowed`；`GameLinkPage` 显示 build 状态并禁用高风险按钮。
  - `AgentClient` 加随机 token（启动时生成，agent 校验）和 `Host/Origin` 校验；端口改为随机/配置，避免 5000 冲突。
  - 多人：`hello.multiplayer == true` 时拒绝所有高风险命令，UI 置灰。
- **依赖**：`live/build.py` 已有 `write_allowed`；`builds/185034.json` 需标 `verified` 才能开写；agent 改造。
- **风险**：误判导致功能不可用；token 传递；pymhf HTTP 是否支持 header 需验证。
- **验收**：未验证 build 下传送按钮禁用且 API 返回明确错误；多人模式下高风险命令拒绝；无 token 的本地请求被拒；实机 build 指纹匹配后才可写。

### G21 agent 传送/扫描可靠性

- **参考来源**：Gagarin 的传送/扫描；NMSCoordinates 的“改存档→重载”冷传送；AGENT-PROTOCOL 的 snapshot/restore。
- **可行方案**：传送前记录 `player/system` 快照并持久化（不止内存）；写入后轮询 `player` 确认 UA/坐标变化；失败自动 `restore`；`restore` 后再读回；扫描 read 先做字段存在性探测；`scan.discover` 保持关闭直到发现管理器偏移验证。
- **依赖**：NMSpy 结构体/函数；实机；`agent` 的 `_location/_pack_ua`。
- **风险**：`_trigger_load` 是否稳定未知；游戏卡死/崩溃；快照丢失；多人。
- **验收**：R4/R5/R6 按 `docs/VERIFY-AGENT-WINDOWS.md` 通过；传送后 UA/坐标与目标一致；restore 回原位置；扫描结果与游戏内面板一致；失败必回滚。

### G22 agent 建造/改色/解上限/HUD

- **参考来源**：Gagarin 的 World 页（开发者选项、任意建造、缩放、解除限制、扫描奖励）；PLAN-V4 M7。
- **可行方案**：逐项做，每项独立开关 + 快照 + 失败不影响存档；先做“只读/预览”，再做写；建造/改色需要函数地址/对象布局，必须实机校准；HUD 只读叠加可后做。
- **依赖**：NMSpy/游戏函数；实机；大量逆向。
- **风险**：高；版本更新即失效；可能崩游戏；多人不公平。
- **验收**：每项有单独开关/确认/回滚；只影响单人；实机逐项截图；失败不破坏存档；未验证默认关闭。

### G23 设置项补齐

- **参考来源**：UI-REDESIGN 的 Settings；NMSSaveEditor 的备份/恢复设置；Shipwright 的备份策略。
- **可行方案**：`SettingsPage` 增加：`confirm_writes`、`backup_keep`、主题（至少深色/高对比）、worker 数、缓存目录/清理、实验性开关（agent 写/传送/扫描）、agent 运行时状态/卸载、更新检查（可选）、语言（暂不做）。
- **依赖**：`core/settings.py` 字段；`writer` 清理备份；`services`。
- **风险**：设置项与行为不一致；需要迁移旧 settings.json。
- **验收**：每项保存后立即生效/重启生效明确；`write_enabled` 默认 false；备份保留生效；缓存清理不影响存档。

### G24 诊断包/日志

- **参考来源**：Shipwright/社区工具的“导出诊断”；starforge `doctor`/`selfcheck`；`app/main._enable_crash_log`。
- **可行方案**：设置页“导出诊断包”生成 zip：`health`、`settings`（脱敏路径）、`doctor`、`selfcheck`（可选）、`build.summary`、`agent_status`（不含 token）、最近 `starforge.log`/`faulthandler.log`/`launcher.log`、`pixmap` 截图（可选）；UI 显示 build/agent 状态；日志查看器支持 tail/copy。
- **依赖**：`zipfile`；`paths.log_file`；`build.fingerprint` 缓存。
- **风险**：隐私（路径/用户名）；日志过大；agent token 泄漏。
- **验收**：一键导出 zip；解压含上述文件；路径可脱敏；不含 token/账号；诊断信息足以定位 numpy/unicorn/agent 问题。

### G25 包体瘦身

- 见第 5 节。验收：Release zip ≤ 100 MB（P1），≤ 90 MB（P2）；启动/3D/agent 功能不回退；CI 加体积断言。

### G26 UI 信息架构/布局

- **参考来源**：`docs/UI-REDESIGN.md`；NMSCoordinates/NoMansConnect 的信息密度；Shipwright 的 Designer/Fleet 分区。
- **可行方案**：按 UI-REDESIGN 把 rail 收到 72 px（或 120 px），抽 `Inspector` 组件；Fleet 增加“飞船/同伴/护卫舰/货船”标签；Galaxy 增加“当前/扫描/索引”清晰分区；GameLink 增加“只读/写/实验”分区；增加收藏/最近活动。
- **依赖**：PySide6 布局；现有页面重构。
- **风险**：大改 UI 影响现有测试/截图；需要分阶段。
- **验收**：1920×1080 下主视口 ≥ 60% 宽度；Inspector 可折叠/记忆；页面切换不丢任务；截图对照 UI-REDESIGN。

### G27 空态/加载态/错误态/键盘/可访问性

- **参考来源**：UI-REDESIGN 的 `EmptyState/Toast/ConfirmSheet`；NMSSaveEditor/NoMansConnect 的桌面交互；Qt 可访问性指南。
- **可行方案**：新增 `app/widgets/states.py`（`EmptyState/ErrorState/LoadingOverlay`）与 `Toast`；所有异步调用统一 `run_worker` 的 `on_error` 映射为“原因+下一步+重试”；补 `Esc` 关闭 Inspector/Dock、结果网格方向键/Enter/W/E、`?` 快捷键帮助；给自定义 delegate/按钮加 `accessibleName/Description`；焦点顺序；高对比主题。
- **依赖**：PySide6；现有 `worker.py`。
- **风险**：自定义绘制 delegate 的可访问性需要额外实现；键盘冲突。
- **验收**：每个页面有空/加载/错误三态；错误不含 traceback；键盘可完成“搜船→选结果→写回”；屏幕阅读器能读出卡片种子/类型；Tab 顺序合理。

### G28 NMS 主题元素（可选）

- **参考来源**：NMS 游戏 UI（橙/青、六边形、扫描线）；Gagarin 的菜单风格；UI-REDESIGN 设计令牌。
- **可行方案**：在 `theme.py` 增加可选的 NMS 点缀：六边形边框、扫描线背景、字形/图标、NMS 字体（注意许可）；默认保持低干扰；提供“经典深色/ NMS 主题”切换。
- **依赖**：字体许可（Gagarin 的 NMS Futura Pro Book 是 SIL OFL，见 THIRD_PARTY_NOTICES）；Qt QSS/绘制。
- **风险**：主题影响可读性/性能；字体授权。
- **验收**：主题切换不重启；对比度达标；不遮挡 3D/表格；可关闭。

### G29 文档漂移

- **参考来源**：当前 `README.md`、`FEATURE-MAP.md`、`CAPABILITIES.md`、`PLAN-V4.md`、`AGENT-PROTOCOL.md` 与代码。
- **可行方案**：每次合并前更新 FEATURE-MAP 的“✅/🟡/⬜”与文件路径；明确“代码存在 ≠ 实机通过”；把 agent 能力表统一为 `live/build.py` 的 build 状态；删除“送进游戏已接”等未接描述；统一 Python runtime 版本。
- **依赖**：无。
- **风险**：文档继续画饼会误导测试者。
- **验收**：文档中每个 ✅ 都能在 UI 找到入口；每个 🔴/⬜ 都有对应 issue/阶段；`AGENT.md` 与 `AGENT-PROTOCOL.md` 的传输方式不矛盾。

### G30 测试/实机验收

- **参考来源**：`tests/`、`docs/VERIFY-WINDOWS.md`、`docs/VERIFY-AGENT-WINDOWS.md`、CI。
- **可行方案**：新增原生页面契约测试（不只 web）；`pytest-qt` 冒烟每个页面；`tests/test_galaxy.py` 加“扫描入库→查询”服务测试；`tests/test_live.py` 加进度/取消；Windows 实机 R2–R7 记录 JSON/截图；CI 加包体断言与原生 UI 启动冒烟（offscreen）。
- **依赖**：pytest/pytest-qt；Windows runner；真实游戏。
- **风险**：CI 无游戏文件，系统/agent 只能契约测试；实机成本。
- **验收**：CI 全绿；Windows 清单逐项签字；未通过项不得标 ✅。

---

## 4. 界面与交互缺口

### 4.1 信息架构（IA）

**设计目标**（`docs/UI-REDESIGN.md`）：Command Bar + 72 px Rail + Workspace + Inspector（360–460 px）+ 可折叠 Dock；六个一级入口；3D 是主体。

**当前实际**：

| 层 | 当前实现 | 与目标的差距 |
|---|---|---|
| Rail | `app/shell.py:_build_rail` 固定 `setFixedWidth(190)`，6 个 `QPushButton` | 比设计宽 118 px；占主视野；无图标/当前页琥珀竖线；无折叠 |
| Command Bar | `_build_command_bar`：面包屑 + 命令按钮 + 4 个状态 chip + 任务标签/进度条 | 无通知中心/账号/日志入口；chip 只有 4 项；无“写入/agent”实时状态合并 |
| Workspace | 每个页面自己 `QSplitter`：ShipLab `[300,700,420]`、Fleet `[300,720,420]`、Galaxy `[700,360]` | 没有统一 Inspector 组件；宽度写死；不记忆 splitter；不同页面选中对象不共享 |
| Inspector | ShipLab/Fleet/Galaxy 各自一个 `Card("Inspector")` | 无通用 `ShipInspector/PlanetInspector`；无折叠；无“主操作/属性/安全提示”分区 |
| Dock | `app/widgets/job_dock.py:JobDock` 每秒轮询 `services.jobs()`，只读列表 | 无取消/重试；无日志/agent 输出；无自动弹出；折叠状态不持久 |
| 页面 | Home/ShipLab/Fleet/Galaxy/GameLink/Settings 六页 | 缺 Designer、Companions、Fleet 子标签、收藏/最近活动 |
| 收藏 | `services/favorites.py` + ShipLab 按钮 | 无收藏列表页；“收藏”后无处查看/管理 |
| 最近活动 | Home 只有“第一次使用”静态提示 | 无最近搜索/写入/传送记录（`FEATURE-MAP` 已标预留） |

**建议**：

- 新增 `app/widgets/inspector.py`（`InspectorPanel`，带标题/可折叠/滚动/主操作槽），ShipLab/Fleet/Galaxy 复用。
- Fleet 增加 `QTabWidget`：飞船 / 同伴 / 护卫舰 / 货船；把 `services.creatures`、`extras.frigates` 接进来。
- Home 增加“最近活动”列表（`~/.starforge/events.jsonl`，写操作/搜索/传送各记一条）；不做数据库。
- 收藏页可放在 Fleet 的“收藏”标签，或 ShipLab 的顶部筛选。

### 4.2 布局与密度

- `ShipCardDelegate.size = QSize(208, 172)`，图标 110；在 700 px 结果区一屏约 3 列，信息密度低于 UI-REDESIGN 的“星座网格”。建议卡片宽度自适应、支持 4–6 列、双击进入大图。
- `ShipViewer` 最小 220×220，ShipLab 给 300 高；在 900 px 高窗口里 3D 只占约 1/3，不符合“3D 是主体”。建议默认 3D 占 Inspector 60% 高度，Inspector 可拉宽到 460。
- `GalaxyPage` 的 Hero + 三标签 + 过滤条在 760 px 高时表格只剩 ~300 px；建议 Hero 可折叠，过滤条收进工具栏。
- `GameLinkPage` 四张 Card 垂直堆叠，日志卡 `stretch=1`；小屏时安全区被挤；建议用 `QSplitter`/滚动区。
- `SettingsPage` 全部 `Card` 堆叠，无分组导航；建议左侧分类（路径/安全/外观/高级/诊断），右侧表单。
- 窗口只保存 `geometry`（`shell.py:_restore_geometry`），不保存 splitter/dock/页面；建议 `QSettings` 存 `splitter/<page>`、`dock/visible`、`last_page`。

### 4.3 空态 / 加载态 / 错误态

| 页面 | 空态 | 加载态 | 错误态 | 问题 |
|---|---|---|---|---|
| Home | 卡片显示“—” | 无 | `cards["live"]` 显示“不可用：msg” | 无重试；健康检查失败只进 statusBar |
| ShipLab | `self.empty` 一行文字 | `status` 文本“搜索中…” | `status` 文本 `type: msg`；3D 回退 PNG | 结果区空时没有插画/引导；错误无“重试/打开设置” |
| Fleet | `result_info` “还没有船” | `info` 文本 | `info` 文本 | 读取失败无重试；缩略图失败静默 |
| Galaxy | 表格 0 行 | `status` 文本 | `status` 文本 | 索引空时只说“没有匹配”，不提示“先扫描入库” |
| GameLink | 状态 chip + `status` | 日志追加 | 日志 JSON/`QMessageBox` | 错误是原始 JSON；无“复制诊断/打开日志” |
| Settings | 表单空 | `_log` 文本 | `_log` 文本 | 无逐项路径红/绿；无“测试连接” |

**建议**：统一 `app/widgets/states.py`：

- `EmptyState(title, hint, action_text, action)`：每个列表/表格空时显示。
- `ErrorState(kind, message, hint, retry)`：`worker.run` 的 `on_error` 统一映射。
- `LoadingOverlay`/`BusyLabel`：搜索/扫描/3D 生成时显示，不阻塞 UI。
- `Toast`：写回成功/失败、复制成功等短反馈。
- 错误对象统一 `{kind, message, hint, retryable}`（`core/errors.py` 已有 `as_dict`，但 UI 直接拿 `str(e)`）。

### 4.4 键盘

**已有**：

- `Ctrl+K` 命令面板（`shell.py`）。
- `Ctrl+1..6` 切页（`shell.py`）。
- `F5` 刷新健康。
- `Ctrl+Enter` 开始搜索、`J/K` 上下选择（`ship_lab.py`）。
- `Esc` 关闭命令面板/浮窗（`QDialog`/`GlyphOverlay`）。

**缺口**：

- 无 `Esc` 关闭 Inspector/Dock/清除选中。
- 结果网格无方向键/Enter 打开 3D/W 写回/E 导出（UI-REDESIGN 明确要求）。
- 无 `?` 快捷键帮助/快捷键列表。
- 命令面板只有 10 个固定动作，不能搜部件/种子/页面内操作；无最近命令。
- `QShortcut("J")` 绑定在 `self.results`，焦点在部件树/搜索框时无效；`K` 同。
- 无 Tab 顺序管理；自定义 delegate 卡片无法用键盘高亮内部按钮。

**建议**：用 `QAction` + `QShortcut` 统一注册；`ShipLabPage` 增加 `QListWidget.keyPressEvent` 或 `QShortcut`（Left/Right/Up/Down/Enter/W/E）；`CommandPalette` 支持动态命令（收藏、最近、当前选中操作）；`?` 弹出 `ShortcutHelpDialog`。

### 4.5 可访问性

**现状**：

- 自定义 `ShipCardDelegate.paint` 手绘文字，未设置 `Qt.AccessibleText`/`accessibleName`；屏幕阅读器只能读到 item 的 `DisplayRole`（seed），读不到类型/等级。
- 状态 chip 只用颜色 + 文本；`theme.py` 的 `QLabel#chip[state]` 颜色对比度未验证；色盲用户难以区分。
- 焦点样式只有 `QPushButton:focus` 等，`QListWidget` 自定义 delegate 选中边框不等于键盘焦点。
- 字体 `Microsoft YaHei UI` 10pt；无缩放/高 DPI 截图测试；`app/main.py` 设置 `PassThrough` 高 DPI，但无 125%/150%/200% 验收。
- 图标按钮（截图/自转/视图）无 tooltip/accessibleName 的组合；部分只有文本。

**建议**：

- 给 `QListWidgetItem` 设置 `Qt.AccessibleTextRole`/`Qt.AccessibleDescriptionRole`；`ShipCardDelegate` 在 `paint` 外提供 `displayText`。
- 所有图标按钮加 `setAccessibleName/Description` + tooltip。
- 主题增加高对比模式；chip 加图标/文字状态（✓/✗/!）。
- 增加 125%/150%/200% 截图验收；`QFont` 使用 `pointSizeF` 而非固定 px。
- 键盘可达性测试：不用鼠标完成“切页→搜船→选结果→写回”。

### 4.6 NMS 主题元素（可选）

当前 `theme.py` 只有深色 + 橙/青点缀，缺少 NMS 识别度。可选增强：

- 六边形/切角边框（`QFrame` 自绘或 QSS `border-image`）。
- 扫描线/网格背景（低透明度，不影响表格可读性）。
- NMS 字形/图标（符文、船型图标）作为导航/空态插画。
- 字体：Gagarin 的 `NMS Futura Pro Book` 为 SIL OFL 1.1（见 `THIRD_PARTY_NOTICES.md`），可用于标题；正文仍用系统字体保证中文。
- 提供“经典深色 / NMS 主题”切换；默认经典深色，避免主题影响可读性/性能。

**不要做**：全屏动画、发光干扰 3D、低对比度橙色文字。主题是可选层，不是 P0。

### 4.7 具体 UI 修复清单（按文件）

| 文件 | 改动 |
|---|---|
| `app/shell.py` | rail 宽度/折叠；Inspector 容器；Dock 状态持久化；`Ctrl+1..6` 保持；关闭时保存 splitter/dock |
| `app/widgets/job_dock.py` | 取消/重试按钮；显示 ETA/错误；点击跳转页面；日志标签 |
| `app/widgets/command_palette.py` | 动态命令、最近命令、分区（页面/操作/收藏） |
| `app/pages/ship_lab.py` | 取消搜索；副色/workers/tol；估算；键盘；收藏列表入口；种子反查；模板槽 |
| `app/pages/fleet.py` | 多选/导出；对比托盘；船级/改名/涂装；同伴/护卫舰/货船标签 |
| `app/pages/galaxy.py` | 扫描入库；进度/取消；索引空态引导；置顶浮窗；保存 glyphs 字段 |
| `app/pages/game_link.py` | build/多人状态；模板槽入口；日志 tail/复制；高风险二次确认 |
| `app/pages/settings.py` | 分类导航；confirm/backup/theme/workers/experimental；诊断 zip；缓存清理 |
| `app/theme.py` | 高对比/主题切换；focus/disabled/错误色规范 |
| 新增 `app/widgets/states.py` | Empty/Error/Loading/Toast |
| 新增 `app/dialogs/class_edit.py` | 船级/属性编辑（复用 `apply_class`） |
| 新增 `app/dialogs/compare.py` | 多船对比 |

---

## 5. 性能与包体

### 5.1 131 MB 包的主要构成（估算）

> 前提：仓库无 `dist/`。以下按 `.github/workflows/release.yml` 生成的 **Release zip** 估算；若 131 MB 指解压目录，则未压缩体积约为其 1.8–2.4 倍。最终请用 `pyi-archive_viewer dist/starforge/starforge.exe` 或解压 `dist/starforge/` 后 `du -sh` 核对。

| 组成 | 估计压缩后 | 证据 | 说明 |
|---|---:|---|---|
| PySide6 / Qt（Core/Gui/Widgets/OpenGL/Network + plugins/translations/opengl32sw/resources） | 55–70 MB | `PySide6-Essentials` Windows wheel 79 MB；CI 只排除 QML/WebEngine/Multimedia 等 | 最大头；`opengl32sw` 单文件 20.6 MB（未压缩），translations 14.1 MB，resources 10.5 MB，plugins 10.5 MB |
| agent runtime（Python embeddable + NMSpy + pymhf + FastAPI/Uvicorn/Pydantic） | 25–40 MB | `packaging/build_agent_runtime.py` 下载 Python 3.11.9 + `pip --target NMSpy/pymhf[http_api]` | 可能含 pip/setuptools/wheel、`__pycache__`、tests、重复 numpy；`requirements` 未锁 pymhf 传递依赖 |
| unicorn | 12–20 MB | Windows wheel：`unicorn/lib/unicorn.lib` 49.9 MB、`unicorn.dll` 9.6 MB、headers | `--collect-all unicorn` 很可能把 `.lib`/headers 收进包；运行时只需要 `unicorn.dll` + Python 模块 |
| numpy 2.2.6 | 8–15 MB | Windows wheel 13 MB；`--collect-all numpy` | 可能含 tests/f2py 等；`--exclude-module numpy.f2py/distutils` 已排除部分 |
| Flask / Werkzeug / Jinja2 / click / itsdangerous / MarkupSafe | 3–6 MB | `entry.py` 显式 import `starforge.web.app`；CI `--collect-all flask` | 原生 UI 不需要 Flask；只有 `serve`/`--webview` 回退需要 |
| vendored Shipwright + data | 1–2 MB | `packaging/vendor.py`；`nms_save` 560 KB + `nms_procgen` 916 KB + data | 很小；不要为省 1 MB 破坏功能 |
| lz4 / hgpaktool / texture2ddecoder / pefile / lz4 | 2–5 MB | wheels | 必需 |
| web static (`app.js/css/index.html/viewer.js`) | <0.2 MB | 112 KB | 可保留 |
| 其它（Qt 插件、VC runtime、Python stdlib、图标） | 5–10 MB | PyInstaller 默认 | — |
| **合计** | **约 131 MB** | 估算 | 误差主要来自 PySide6/agent runtime/unicorn |

**结论**：131 MB 不是“功能必需”，而是**收集策略**造成的；最明显的浪费是 `--collect-all unicorn` 和未裁剪的 Qt/agent runtime。

### 5.2 可削减项与预计收益

| 削减项 | 做法 | 预计 zip 收益 | 风险 |
|---|---|---:|---|
| Unicorn 静态库/头文件 | 把 `--collect-all unicorn` 改为 `--collect-binaries unicorn --collect-submodules unicorn`，并显式排除 `unicorn/lib`、`unicorn/include`；只保留 `unicorn.dll` + `unicorn/` Python | **10–16 MB** | 需确认 PyInstaller 收集到 DLL；用 `doctor` 真建 `Uc` 验证 |
| Qt translations | 只保留 `zh_CN`/`en`（或删除 translations，Qt 默认英文） | 3–5 MB | 中文界面文案在 Python 里，不依赖 Qt 翻译；文件对话框可能英文 |
| `opengl32sw` | 默认不打包，改为“安全模式组件”按需下载/旁置；或在安装包外提供 | 5–7 MB | 安全模式在无 GPU/远程桌面时不可用；需提示 |
| QML/Quick 残留 | 确认 `_internal/PySide6/qml` 不存在；CI 已排除模块，但 hook 可能仍收文件 | 4–6 MB | 无 QML 功能；低风险 |
| Agent runtime 清理 | 删除 pip/setuptools/wheel/get-pip、`__pycache__`、`*.dist-info`、tests/docs、`.pdb`；统一 Python 版本；去掉重复 numpy | 5–10 MB | 可能影响 pymhf 安装/更新；需 `import nmspy,pymhf,fastapi,uvicorn` 冒烟 |
| Flask/web 可选 | 原生默认构建不 import `starforge.web.app`；把 `serve`/`--webview` 作为 `starforge-web` 可选包/延迟导入 | 3–6 MB | 旧 Web 调试/回退不可用；需产品决定 |
| numpy 裁剪 | `--collect-binaries numpy` + `--collect-submodules numpy`，排除 `numpy.tests`、`numpy.f2py`、`numpy.distutils`、`numpy.doc` | 2–4 MB | 需跑搜索/3D/渲染测试 |
| 压缩率 | 用 7z/zip `-mx=9`；确保不重复压缩已压缩的 png/glb | 1–3 MB | 构建时间 |
| **合计（保守）** | 上述前 5 项 | **25–40 MB** | 131 → **91–106 MB** |
| **合计（激进）** | 再加 Flask 可选/numpy/Qt 资源 | **45–60 MB** | 131 → **71–86 MB** |

**建议目标**：P1 结束 ≤ 105 MB；P2 结束 ≤ 90 MB；若低于 80 MB 需确认 3D/agent 未回退。CI 增加：

```powershell
$size = (Get-Item dist/starforge-*.zip).Length / 1MB
if ($size -gt 105) { throw "包体超标：$size MB" }
```

### 5.3 运行时性能问题

| 问题 | 证据 | 影响 | 建议 |
|---|---|---|---|
| 搜索单核 | `Services._query` `workers=1`；`ShipLabPage._start_search` 不传 workers | 4 核机器浪费 ~50–60% 吞吐 | UI 传 `workers=os.cpu_count()`；设置可覆盖；默认 `min(4, cpu)` |
| 系统扫描无进度 | `start_system_scan` 在子进程里 `system.scan(job=None)`；`_internal` 只回最终 JSON | 扫描几分钟 UI 一直“0 个系统” | `cmd_internal` 输出 JSON Lines 进度；`Services._internal` 流式读 |
| 扫描不可取消 | `Job.cancel` 只设事件；子进程不读 | 用户只能等/杀进程 | `Popen` + terminate；`JobDock` 取消 |
| build 指纹重复哈希 | `build.fingerprint()` 每次读 90 MB；`agent_install.status`/`summary` 多次调用 | 打开游戏内页/刷新时 CPU/IO 峰值 | `@lru_cache` 按 `(path,mtime,size)`；status 复用 fp |
| 缩略图串行 | `_next_thumb` 每 30–50 ms 一个；`preview_png` 生成 | 50 艘船 > 5 s；切页卡顿 | 2–4 个 worker 并发；缓存命中优先；可取消 |
| 3D 索引展开 | `ShipViewer._upload` 用 `pos[idx]` 展开 | 大模型顶点内存增加；无复用 | 修好 `glDrawElements` 偏移后改用索引；或按组拆分 |
| 启动导入重 | `packaging/entry.py` 显式 import Flask/web/desktop；`app/main` import numpy | 冷启动慢；DLL 失败面大 | 原生入口延迟导入 web/desktop；numpy 仅在使用时导入（保留软失败） |
| JobDock 每秒重建 | `JobDock.refresh` `list.clear()` + 重建 | 空闲时也每秒重绘 | 只有任务变化时刷新；或 diff 更新 |
| `health` 5 s 轮询 | `shell.py` `_health_timer` 5000 ms；`health` 调 `parts.source` | 轻量但无必要 | 30 s 或事件驱动；设置页手动刷新 |

### 5.4 性能验收口径

- 冷启动（Windows，SSD，无游戏）：主窗口可交互 ≤ 3 s；有游戏 ≤ 5 s。
- 搜索：4 核 ≥ 1.5× 单核吞吐；取消 ≤ 1 s。
- 缩略图：50 艘船首次 ≤ 8 s，缓存后 ≤ 2 s。
- 系统扫描：进度至少 1 次/秒；取消 ≤ 2 s；1000 系统不崩。
- 3D：100k 三角模型旋转 ≥ 30 FPS（目标机器），内存增量 ≤ 200 MB。
- 包体：≤ 105 MB（P1），≤ 90 MB（P2）。

---

## 6. agent / Unicorn / pymhf 的稳定性与版本适配

### 6.1 当前链路（事实）

```
NMS.exe
  ↑ pymhf 注入 Python Mod
starforge/agent/starforge_agent.py  (NMSpy 结构体/函数 + pymhf HTTP endpoint)
  ↑ HTTP 127.0.0.1:5000/StarforgeAgent
starforge/live/agent_client.py
  ↑
starforge/live/agent_install.py (运行时/Mod/注入/状态)
  ↑
starforge/services/__init__.py (agent_call/live_capabilities)
  ↑
starforge/app/pages/game_link.py
```

- 传输是 **pymhf HTTP API**，不是 `docs/AGENT-PROTOCOL.md` 里的命名管道 C++ DLL；协议文档已注明，但两套说法容易让测试者误解。
- agent 能力表由 `hello` 返回，`GameLinkPage` 用 `reachable and in_game` 启用按钮；**没有使用 `live/build.py` 的 `write_allowed`**。
- `live/builds/185034.json` 的 `status` 是 `unverified`，`signatures/offsets` 为空，`capabilities` 全部 `pending`；这意味着“代码存在”但“版本未校准”。

### 6.2 稳定性/适配问题清单

| # | 问题 | 证据（文件:函数/行） | 严重度 | 建议 |
|---|---|---|---|---|
| A1 | **build 闸门未生效**：未知/未验证 build 仍可调用传送/扫描 | `services.agent_call` 只做命令白名单；`live_capabilities` 用 `hello` 的 `true`；`live/build.summary` 的 `write_allowed` 未被使用；`builds/185034.json:status=unverified` | P0 | `agent_call` 对写命令先查 build；`hello` 返回 build；UI 显示“未验证”；未验证只读 |
| A2 | **NMSpy/Python 版本不一致** | `requirements.txt: NMSpy==185034.0`；`packaging/build_agent_runtime.py:VERSION="3.11.9"`；`live/agent_install.py:RUNTIME_PY_VERSION="3.12.8"`；`pymhf>=0.2.5` 未锁 | P0 | 统一一个版本矩阵；锁 `pymhf`/`fastapi`/`uvicorn`/`pydantic`；构建与应用都读同一 manifest |
| A3 | **`install_deps` 早退，游戏更新后不会更新 NMSpy** | `agent_install.install_deps`: `if rt and _has_agent_packages(rt): return {"ok": True, "note": "运行时已内置，无需安装/更新"}` | P0 | 比较 `NMSpy` 已装版本 vs `expected_nmspy_version()`；不匹配时允许 `--force`/联网更新；内置 runtime 也要可升级 |
| A4 | **每次 status 可能重复哈希 90 MB NMS.exe** | `build.fingerprint` 无缓存；`agent_install.status` 调 `fingerprint` + `summary`；`expected_nmspy_version` 再调 | P1 | `lru_cache` 按 `(path, mtime_ns, size)`；缓存到 `~/.starforge/builds/last.json` |
| A5 | **NMSpy 私有 API 脆弱** | agent 使用 `gameData`、`basic.cTkFixedString[0x10]("APPLOCALLOAD")`、`nms.cGcBinoculars.UpdateScanBarProgress.before`、`GetNodeAbsoluteTransMatrix(gameData.player.mRootNode)`、`ps.mShipResources`、`mbMultiplayerActive` | P0 | 每个端点独立 try/except 并返回 `capability=false`；hello 做探测；锁定 NMSpy 版本；不要用未验证的私有构造 |
| A6 | **传送/还原没有可靠确认** | `agent.teleport` 写 `GalacticAddress` 后调 `_trigger_load()` 即返回；`restore` 只用内存 `_snapshot`；无写后 `player` 读回；无多人检查 | P0 | 传送后轮询 `player` 2–5 s 确认；快照持久化到 `~/.starforge/agent/snapshots`；多人拒绝；失败自动 restore；`scan.discover` 保持关闭 |
| A7 | **HTTP 无认证/固定端口** | `AgentClient.DEFAULT_BASE = http://127.0.0.1:5000/StarforgeAgent`；agent endpoint 无 token；pymhf 绑定地址需核实 | P0 | 启动时生成一次性 token；`AgentClient` 带 header/query；agent 校验；端口随机/可配置；确认只绑 127.0.0.1 |
| A8 | **多人模式只报告不拦截** | `agent.hello` 返回 `multiplayer`；`teleport/scan/scan_instant` 没有检查；文档说会禁用 | P0 | 所有 high risk 命令入口检查 `multiplayer`；UI 置灰；返回 `E_MULTIPLAYER` |
| A9 | **进程生命周期不清** | `agent_install.launch` `Popen` + `DETACHED_PROCESS`；`stop` 只 `terminate()` launcher；无 agent 进程/注入状态；`_LAUNCH` 全局非线程安全 | P1 | 记录 launcher PID + agent 连接状态；停止时先请求 `/shutdown`（若支持）再杀；UI 显示“注入器/agent”分离状态 |
| A10 | **pymhf questionary hack** | `env["PYTEST_VERSION"]="1"` 绕过 import 期提示；`build_agent_runtime.py` 同样 | P1 | 用 pymhf 官方非交互配置/CLI 参数；若必须 hack，加注释与版本测试 |
| A11 | **Unicorn VEH/faulthandler 冲突** | `services._internal` 子进程 + `PYTHONFAULTHANDLER=0`；`cmd_internal` 再 `faulthandler.disable()`；changelog 提到 `0xC0000409` | P0 | `unicorn` pin 到实测版本（如 `2.0.1.post1` 或当前验证版）；子进程隔离保留；加崩溃回归；不要在主进程跑 `systemgen` |
| A12 | **systemgen 没有 build 闸门** | `systemgen.py` 注释 “offsets are load-bearing”；`system.available()` 只查 `NMS.exe`；`exeaddr.py` 按 build 找地址但无失败即只读 | P0 | 用 `build.fingerprint` 标记 `systemgen` 支持矩阵；未知 build 只读/禁用扇扫；输出 `build_id`；实机对表 |
| A13 | **agent 日志不可见** | `launch` 写 `~/.starforge/agent/launcher.log`；GameLink 只显示 HTTP JSON | P1 | GameLink 增加日志 tail/打开/复制；诊断包包含 launcher.log |
| A14 | **卸载/还原不完整** | `uninstall_mod` 只删 `starforge_agent.py`；不涉及 pymhf 注入/运行时；文档提“还原 winmm.dll”与实际不符 | P1 | UI 提供“停止/卸载/删除运行时”；明确 pymhf 注入不会改 winmm.dll；清理 `~/.starforge/agent` |
| A15 | **agent 正常运行依赖“已进存档”** | `GameLinkPage` 用 `hello.in_game` 启用；`_location` 在 `player_state is None` 时失败 | P1 | UI 明确“载入存档后”；轮询 hello；不要显示“已连接”就以为可读 |
| A16 | **端口 5000 冲突** | 固定 5000；常见开发端口 | P1 | 随机端口 + 写入状态文件；`AgentClient` 读取 |
| A17 | **agent 代码与文档能力表不一致** | `__main__.cmd_agent` 打印 13 项全部 `available=False`（旧 DLL 路线）；实际 pymhf agent `hello` 返回 `teleport/scan=true` | P1 | CLI `agent hello` 改为读真实 HTTP（若已连接）或明确“未连接”；统一能力表 |
| A18 | **NMSpy 版本号可能不是游戏 build** | `expected_nmspy_version` 用地址书 `build` 或 PE version；185034.json 的 `build` 是 185034；PyPI NMSpy 版本号体系可能不同 | P0 | 用 `importlib.metadata.version("NMSpy")` 与 `nmspy.__version__` 双校验；建立 build→NMSpy 映射表；不要用 PE FileVersion 猜 |

### 6.3 版本矩阵建议

| 组件 | 当前 | 建议 |
|---|---|---|
| Python（主程序） | 3.11/3.12/3.13 开发机混用 | 构建固定 3.11.x 或 3.12.x；CI 与 runtime 一致 |
| agent runtime | 构建 3.11.9；应用下载 3.12.8 | 统一为同一个 `3.11.x`（NMSpy/pymhf 验证过的版本） |
| NMSpy | `185034.0`（requirements） | 与游戏 build 一一映射；`185034` 通过实机后标 `verified`；未知 build 只读 |
| pymhf | `>=0.2.5` | 锁到实测版本（如 `0.2.x` 具体 patch）；记录 `http_api` 兼容 |
| unicorn | `>=2.0` | 锁到实测版本；Windows 优先 `2.0.1.post1` 或已验证 2.1.x；CI 真建 `Uc` |
| PySide6 | `>=6.7` | 锁到 6.8/6.9 LTS 之一；记录 Qt6Core/Gui/Widgets/OpenGL 版本 |
| numpy | `2.2.6` | 保持；验证 Windows DLL/杀软；不要随意升级 |
| Flask/web | `>=3.0` | 如果不默认打包，锁到 3.x 用于 `serve` |

### 6.4 稳定性测试/停止条件

**必须做**：

1. `doctor`：unicorn 真建 `Uc` + `mem_map`；numpy/flask/lz4/hgpaktool/texture2ddecoder/pefile 全部 import。
2. agent 单元/契约：`tests/test_agent_cli.py`、`tests/test_services.py:test_agent_client_http_contract`、`tests/test_services.py:test_agent_install_mod_and_version_mapping`。
3. Windows 实机：
   - R3：安装 runtime/Mod → 注入 → `hello` → 只读 5 项。
   - R4：对照游戏内 UA/坐标/行星/船属性。
   - R5：传送 + restore，截图前后。
   - R6：扫描 read + instant，截图发现项。
   - R7：逐项开启建造/改色/上限，失败不影响存档。
4. 每次游戏更新：重新跑 `doctor` + `agent hello` + build 指纹；未验证 build 自动只读。

**停止条件（硬）**：

- 如果 `build.summary()["verified"] == False`：**停止所有 agent 写功能**，只保留只读；不要把传送/扫描标为 ✅。
- 如果 `doctor` 的 unicorn 失败：停止星系/行星功能发布，修依赖后再发。
- 如果 R5/R6 未通过：停止 M5/M6 标完成，保留“实验性/未验证”标签。
- 如果多人模式无法可靠检测：停止所有高风险命令，默认只读。
- 如果 agent HTTP 无 token/绑定非 loopback：停止发布含 agent 的包。

---

## 7. 文档/声明与实现漂移

| 文档 | 声明 | 实际 | 建议 |
|---|---|---|---|
| `README.md` | “传送门符文独立置顶窗口 🚧” | CLI 有，UI 无入口 | 标明“仅 CLI”；P1 接 UI |
| `README.md` | “游戏内实时通道…模板 Mod 一键生成” | `services.live_template_mod` 有，UI 无按钮 | 接 UI 或改文案 |
| `README.md` | “五页：搜索/我的船/星球/设置 + 浮窗” | 六页：Home/ShipLab/Fleet/Galaxy/GameLink/Settings | 更新 |
| `FEATURE-MAP.md` | 收藏/写回/备份“占位” | 工作区已实现收藏/写回/备份 | 更新状态 |
| `FEATURE-MAP.md` | Galaxy“银河索引查询 🟡” | 工作区已接查询，但扫描不入库 | 改为“查询 ✅ / 入库 ⬜” |
| `FEATURE-MAP.md` | GameLink“传送/扫描 🔴 需实机” | 代码有，build 未验证 | 改为“🟡 代码存在，待实机” |
| `CAPABILITIES.md` | “传送 🟡/🔴” | agent 代码有 `teleport` | 明确“未实机” |
| `PLAN-V4.md` | “应用内游戏控制台 ✅ … 传送/扫描读取” | 注入/按钮有，实机未验证 | 加“代码完成/实机未完成”两列 |
| `AGENT.md` | “可卸载：完整还原 winmm.dll” | pymhf 注入不装 winmm.dll；`uninstall_mod` 只删 .py | 修正描述 |
| `AGENT-PROTOCOL.md` | 命名管道 + C++ DLL | 实际 pymhf HTTP | 保留为未来协议，但开头醒目说明 |
| `ARCHITECTURE.md` | services 565 行 / live.py 393 行 | 当前 services 628 行 / game_link 314 行 | 更新体量 |
| `PLAN-V4.md` | “P0 已完成” | P0 基础壳完成；功能闭环仍有缺口 | 区分“架构 P0”与“功能 P0” |
| `README.md` | “不修改玩家资产” | 存档写回/未来编辑器会改 | 明确“不修改游戏 pak/在线资产；只改本地存档” |

---

## 8. 分阶段路线图（P0 / P1 / P2 / P3）

> 估算前提：1 人全职；Windows 实机可随时测试；每阶段结束打一个可回退的 beta 包。  
> **纪律**：P0/P1 不依赖 agent 实机；P2 才开始实机写操作；未通过验收不得把功能标 ✅。

### P0 · 正确性与安全（约 1–2 周）

| # | 工作 | 文件级改动 | 测试方法 | 停止条件 |
|---|---|---|---|---|
| P0-1 | 星系扫描入库 + 进度/取消 | `app/pages/galaxy.py:_scan/_poll_scan` 改用 `start_galaxy_scan`；`services/__init__.py:start_galaxy_scan/start_system_scan`；`__main__.py:cmd_internal` 输出 JSON Lines；`services._internal` 流式读；`app/widgets/job_dock.py` 取消 | `tests/test_galaxy.py` 用 fake provider 验证 `upsert`；`tests/test_features.py` job cancel；手动扫描后 `galaxy_stats` 增长 | 扫描后索引可查；取消 2 s 内；无子进程残留；CI 全绿 |
| P0-2 | 搜索 UI 补全 | `app/pages/ship_lab.py:_start_search` 传 secondary/tol/workers；调 `search_estimate`；加取消按钮 | `tests/test_look_filter.py`；4 核吞吐对比；UI 手动 | 副色生效；估算误差 < 50%；取消可用 |
| P0-3 | agent build 闸门 + 安全 | `live/build.py` 缓存；`services.agent_call` 写命令查 `write_allowed`；`app/pages/game_link.py` 显示 build/多人；`agent_client.py` token/端口；`agent/starforge_agent.py` 多人检查 | `tests/test_services.py` 假 HTTP；`tests/test_live.py`；Windows 手动 | 未验证 build 写命令被拒；多人拒绝；无 token 拒绝；实机只读通过 |
| P0-4 | 版本统一 | `requirements.txt`/`pyproject.toml`/`packaging/build_agent_runtime.py`/`live/agent_install.py` 统一 Python/NMSpy/pymhf/unicorn 版本；`install_deps` 支持更新 | `doctor`；CI 安装；`agent_status` 版本对比 | 构建机/用户机/agent runtime 版本一致；`doctor` 全绿 |
| P0-5 | 诊断包 + 设置补齐（最小） | `app/pages/settings.py` 加 build/agent/日志/诊断 zip；`services.diagnostics` 接入；`core/settings.py` confirm/backup 字段 | 手动导出 zip；解压检查；`tests/test_native_smoke.py` | zip 含 health/doctor/build/logs；无 token/隐私；设置保存生效 |
| P0-6 | 包体第一刀 | `.github/workflows/release.yml` 改 unicorn 收集；Qt translations 裁剪；agent runtime 清理；体积断言 | CI 构建；`doctor`；解压 `du`；包体 ≤ 115 MB | 包体下降 ≥ 15 MB；unicorn 可用；3D/搜索不回退 |

**P0 完成定义**：`pytest -q` 全绿；原生六页冒烟；`selfcheck` 关键步骤通过；`doctor` 全绿；无未处理 `0xC0000409`；包体 ≤ 115 MB；agent 写功能默认不可用（未验证 build）。

### P1 · 离线闭环（约 3–5 周）

| # | 工作 | 文件级改动 | 测试方法 | 停止条件 |
|---|---|---|---|---|
| P1-1 | 船级/改名/涂装写回 UI | 新增 `app/dialogs/class_edit.py`；`app/pages/fleet.py`/`ship_lab.py` Inspector；`services` 新增 `apply_name/apply_paint`；`save/writer` 扩展 | `tests/test_locate_class.py` 扩展；副本写回读回；实机改名/涂装可见 | 只改目标船；其它 seed 不变；失败回滚；实机可见 |
| P1-2 | 模板槽“送进游戏” | `app/pages/ship_lab.py` 加按钮；`app/pages/game_link.py` 加模板 Mod/探测/推送；`services.live_push/live_template_mod` 接入 | `tests/test_live.py` FakeProcess；Windows 手动 | 模板生成/探测/唯一写入/回读；多候选拒绝；实机外观正确 |
| P1-3 | 符文浮窗 UI | `app/pages/galaxy.py` 加“置顶显示”；`app/overlay.py` 改为非阻塞实例；`core/settings` 存 alpha/scale/click-through | `tests/test_live.py:test_overlay_panel_spec`；Windows 手动 | 一键显示；Esc 关闭；点击穿透；切换更新 |
| P1-4 | 同伴只读 + 种子反查 UI | `app/pages/fleet.py` 加“同伴”标签；`services.creatures/creature_roles`；ShipLab“更多→查星系” | `tests/test_planet_creature.py`；UI 手动 | 29 只同伴显示；反查有候选/证实；无结果说明 |
| P1-5 | 批量导出/对比 | `app/pages/fleet.py` 多选/导出；新增 `app/dialogs/compare.py`；`export.export_zip` 接入 | `tests/test_export.py`；手动 zip 检查 | 导出 zip 完整；3 船对比可用 |
| P1-6 | 设计器 MVP | 新增 `app/pages/designer.py`；`services` 设计器 API；`model3d` 部件组装 spike；设计 JSON | 手动 5 部件组装；搜索 seed；写副本读回 | 组装/搜索/写回一致；设计保存/载入；不承诺“任意组合” |
| P1-7 | UI 状态/键盘/可访问性 | `app/widgets/states.py`；`shell.py`；`ship_lab.py`；`fleet.py`；`theme.py` | `pytest-qt` 冒烟；键盘手动；高 DPI 截图 | 每页三态；键盘闭环；AccessibleName；125%/150% 通过 |
| P1-8 | 包体第二刀 | Flask/web 可选；numpy 裁剪；Qt opengl32sw 可选；CI 体积断言 | CI；doctor/webcheck；包体 ≤ 105 MB | 包体 ≤ 105 MB；原生功能不回退 |

**P1 完成定义**：离线全流程（搜船→3D→收藏/分享→写回→备份→同伴只读→符文浮窗→批量导出）不弹浏览器；所有写操作有备份/读回/回滚；UI 三态/键盘/可访问性清单通过；包体 ≤ 105 MB。

### P2 · 存档编辑器与 Corvette（约 4–6 周）

| # | 工作 | 文件级改动 | 测试方法 | 停止条件 |
|---|---|---|---|---|
| P2-1 | 安全字段存档编辑器 | 新增 `app/pages/editor.py` 或 Fleet 子页；`services` 包装 `player/items/extras/quests`；`save/writer` 通用事务 | 副本逐字段改/读回；实机验证；`tests/test_save.py` | 只改白名单字段；失败回滚；accountdata 拒绝 |
| P2-2 | 库存/解锁/任务/奖励 | `app/pages/editor.py` 标签；`items.list_inventories/edit_inventory`；`extras.learn_all`；`quests.skip_quests` | 副本测试；实机小改动 | 库存移动/修复/扩容不崩；任务只改目标；奖励可见 |
| P2-3 | 多工具/货船/护卫舰/中队 | Fleet 子页；`extras.multitools/frigates`；`ships.get/set_freighter` | 只读对照；写回读回；实机 | 只读一致；写回成功；失败回滚 |
| P2-4 | Corvette 只读 + 构建 | 新增 `app/pages/corvette.py`；`nms_save.corvette`、`model3d.corvette_model`；`services` | `tests/test_*` 新；实机对照 | 模块/位置一致；3D 可旋转；写回副本读回 |
| P2-5 | 同伴写回/设计器 R&D | `creature` 扩展；`extras.edit_companion`；NMSCD 兼容表 | 副本；实机 | 名字/体型可见；3D 未解则明确 |
| P2-6 | 冷传送（可选） | `save/writer` 新 setter（需逆向）；`services`；UI 二次确认 | 副本→重载；实机 | 传送后可回滚；不改其它字段；默认关闭 |
| P2-7 | 包体 ≤ 90 MB | 继续裁剪 agent runtime/PySide6 | CI | 包体 ≤ 90 MB；功能不回退 |

**P2 完成定义**：安全存档编辑器可用；Corvette 只读/构建通过；同伴只读/写回通过；所有写操作有事务/回滚；包体 ≤ 90 MB。冷传送若未实机通过则保持“实验性”。

### P3 · 实机 agent 深水区 / R&D（约 6–10 周，按游戏版本可能重置）

| # | 工作 | 文件级改动 | 测试方法 | 停止条件 |
|---|---|---|---|---|
| P3-1 | M4 只读实机 | `agent/starforge_agent.py` 端点加固；`live/builds/185034.json` 标 verified；`docs/VERIFY-AGENT-WINDOWS.md` | R3/R4；对照游戏内 | 5 项只读全过；不崩；版本匹配 |
| P3-2 | M5 传送/还原 | `agent.teleport/restore`；快照持久化；`GameLinkPage` | R5；截图前后 | 传送成功；restore 回原；失败回滚 |
| P3-3 | M6 扫描 | `agent.scan` read/instant；`scan.discover` 仍关 | R6；游戏内对照 | read 一致；instant 可用；discover 不开放 |
| P3-4 | M7 建造/改色/解上限/HUD | 逐项功能开关；`agent` 新端点；`GameLinkPage` 安全区 | R7 逐项 | 每项单独开关/回滚；单人；失败不坏档 |
| P3-5 | 生物 3D/搜索 | 需生物生成器/描述符链；`creature` R&D | 先 spike | 无生成器则停止，不画饼 |
| P3-6 | 银河地图/社区坐标 | `galaxy` + 可视化；nmsce 导入（可选） | 手动 | 只读导入；不破坏离线 |
| P3-7 | 安装包/签名/更新 | PyInstaller/Inno Setup/MSIX；签名；更新检查 | 干净 Windows | 安装/卸载/升级；无残留 |

**P3 完成定义**：每个 M 阶段独立验收；未通过实机的能力保持关闭；不因“代码写了”而标完成。

---

## 9. 必须依赖游戏运行 / 实机校准的功能（不能假装完成）

### 9.1 必须游戏运行（进程内 agent）

- `agent.player/system/planet/ships` 的**真实字段值**（离线只能生成近似；天气/资源/动植物必须运行时）。
- `agent.teleport/restore`：写位置 + 触发加载 + 回读；没有实机无法证明。
- `agent.scan/scan.instant`：扫描函数/发现管理器；没有实机无法证明。
- `agent` 的建造/改色/解上限/HUD：必须进程内函数/对象布局。
- 多人模式检测与高风险命令拦截：必须运行时 `mbMultiplayerActive`。
- 模板槽“送进游戏”：必须游戏运行 + 模板 Mod + 内存定位；`live_probe` 只能证明“找到候选”，不能证明“领到船”。

### 9.2 必须 Windows 实机校准（但不一定游戏运行）

- `systemgen` 的 `exeaddr` 偏移/函数地址：每个游戏 build 不同；`NMS.exe` 指纹 + 实机生成对照。
- `agent` 的 NMSpy 版本/build 映射；pymhf 注入/HTTP 端口/权限。
- 3D OpenGL：目标 GPU/驱动/远程桌面/软件回退；截图对比。
- 符文浮窗点击穿透/置顶/多显示器。
- 打包产物：干净 Windows 10/11、无 Python、无 VC 运行库、杀软开启；安装/卸载/升级。
- 高 DPI（125%/150%/200%）、中文字体、深色标题栏。
- 存档写回：真实 `save.hg`、Steam Cloud 开启/关闭、游戏运行中拒写。

### 9.3 离线可做但依赖游戏文件（不需要游戏运行）

- 飞船搜索/3D/缩略图/glb：需要 `NMS.exe` + PCBANKS + Shipwright。
- 星系/行星生成/种子反查：需要 `NMS.exe`（Unicorn 跑生成器），不需要游戏运行。
- 符文图标：需要 `NMSARC.TexUI.pak` + BC7 解码。
- 部件树：优先游戏资源，缺游戏时可回退 Gagarin catalog。
- 存档读写：需要 Shipwright + 真实存档；写回要求游戏退出。

### 9.4 当前明确不可做/不承诺

- **多人模式写入/同步**：不同步、风险不可控；产品红线。
- **在线反作弊规避/自动刷资源/挂机**：不做。
- **跨船型种子移植**：`seed` 与 `type` 绑定；`save/writer.apply_seed` 已拒绝；不要承诺“把拦截机外观套到战斗机”。
- **离线扫描行星天气/资源/动植物**：`system.PLANET_FIELDS` 已明确不可得；只能 agent。
- **当前离线生成同伴 3D**：`creature.capabilities` 已判定描述符词表不同源；除非实现运行时生物生成器/新逆向，否则不做。
- **无 agent 的可靠热传送/任意建造/改色/解上限**：外部内存只能做模板槽 8 字节写入；不要用外部写世界状态。
- **跨版本保证 agent 可用**：每次游戏更新必须重新校准；未知 build 只读。
- **“任意部件组合”**：只在生成器允许的组合内；跨型/非法组合不可保证。

---

## 10. 验收清单（Definition of Done）

### 10.1 P0 验收

- [ ] `pytest -q` 全绿（含新增 galaxy 入库、job cancel、agent build gate 测试）。
- [ ] `python -m starforge selfcheck` 关键步骤通过；`doctor` 全绿。
- [ ] 原生六页可切换；ShipLab 搜索→3D→写回；Fleet 读档→备份/恢复。
- [ ] Galaxy 扫描后 `galaxy_stats` 增长，索引查询能查到；取消可用。
- [ ] 未验证 build 下传送/扫描按钮禁用；多人模式拒绝。
- [ ] 无未处理 `0xC0000409`/traceback；崩溃日志可导出。
- [ ] 包体 ≤ 115 MB；unicorn/numpy/PySide6 冒烟通过。

### 10.2 P1 验收

- [ ] 离线全流程不弹浏览器；收藏/分享/批量导出/对比可用。
- [ ] 符文浮窗从 UI 一键打开；点击穿透/透明度可用。
- [ ] 模板槽“送进游戏”有 UI；`live_probe` 候选/拒绝逻辑可见。
- [ ] 同伴只读、种子反查有 UI。
- [ ] 设计器 MVP：部件组装→搜索→写副本→读回一致。
- [ ] 每页空/加载/错误三态；键盘闭环；AccessibleName；125%/150% DPI 截图。
- [ ] 包体 ≤ 105 MB。

### 10.3 P2 验收

- [ ] 安全存档编辑器（货币/船级/属性/同伴/多工具/护卫舰/货船只读→写）通过副本+实机。
- [ ] Corvette 只读/构建通过实机。
- [ ] 所有写操作：备份→原子写→读回→失败回滚；只改目标字段。
- [ ] 包体 ≤ 90 MB。

### 10.4 P3/实机验收

- [ ] R3–R7 全部记录 JSON/截图；`docs/VERIFY-AGENT-WINDOWS.md` 签字。
- [ ] build 指纹 `verified`；未知 build 只读；多人拒绝。
- [ ] 传送/还原/扫描 read/instant 与游戏内一致；失败回滚。
- [ ] 建造/改色/解上限/HUD 逐项开关；未通过项保持关闭。
- [ ] 干净 Windows 安装/卸载/升级；无残留；杀软误报说明。

---

## 11. 参考来源

### 11.1 本地参考项目

- **NMS-Shipwright**（MIT）：`nms_save/{ships,items,extras,corvette,quests,player}.py`；`nms_procgen/{fastsearch,systemgen,model3d,corvette_parts,textures}.py`；`webapp/routes/{designer,ships,inventory,player,corvette}.py`；README 的功能矩阵（Designer/Save editing/Corvettes）。
- **Gagarin_Titov**（MIT）：README 的 Planet search / Starships / Portals / World；游戏内菜单、传送、扫描、任意建造、开发者选项、版本闸门。
- **NMS-Super-Ship-Hunter**（MIT）：README 的模板槽 + `ReadProcessMemory/WriteProcessMemory` 路线；`hook1.4-zh.py` 的 AOB/模板思路。

### 11.2 社区工具/资料

- **NMSCoordinates**（Kevin0M16）：存档位置管理、Move Player Here + reload、坐标/符文计算、备份、Freighter Battle、Portal Interference；`https://github.com/Kevin0M16/NMSCoordinates`。
- **NMSSaveEditor**（goatfungus）：库存、飞船/货船/多工具、护卫舰、同伴、定居点、奖励、原始 JSON、备份；`https://github.com/goatfungus/NMSSaveEditor`。
- **NMS.py / NMSpy**（monkeyman192）：pymhf + NMSpy 注入/结构体/函数；版本绑定/更新易碎；`https://github.com/monkeyman192/NMS.py`。
- **NMSCD Creature Builder**：同伴部件兼容/JSON 导出；`https://github.com/NMSCD/Creature-Builder`；`https://creature.nmscd.com/`。
- **nmsce / No Man's Sky Coordinate Exchange**：按船/货船/护卫舰/多工具/生物/星球/基地的坐标数据库与按颜色/部件筛选；`https://nmsce.com/`。
- **NoMansConnect**：位置管理器/同步/地图/备份/传送；已停止维护；`https://github.com/jaszhix/NoMansConnect`。
- **nmssavetool**（matthew-humphrey）：存档重定位/签名/坐标格式；`https://github.com/matthew-humphrey/nmssavetool`。
- **NMSE / NMS Toolkit**：更完整的存档编辑器/Corvette/定居点/基地库，作为 P2/P3 功能参考（不直接依赖）。

### 11.3 关键代码证据索引

| 主题 | 文件:函数/位置 |
|---|---|
| 搜索 | `starforge/search.py:run/validate/colour_matches`；`starforge/app/pages/ship_lab.py:_start_search` |
| 3D | `starforge/app/widgets/ship_viewer.py:ShipViewer/_upload/_paint_gl`；`starforge/preview.py:build/part_model`；`starforge/gltf.py:build_glb` |
| 存档 | `starforge/save/library.py:open_ships/scan_dir/default_save_path`；`starforge/save/writer.py:apply_seed/apply_class/restore` |
| 船队 | `starforge/app/pages/fleet.py:_load/_select/_open_backups`；`starforge/app/dialogs/backup.py` |
| 星球 | `starforge/system.py:system/scan/locate_seed/PLANET_FIELDS`；`starforge/galaxy.py:scan/GalaxyStore`；`starforge/app/pages/galaxy.py:_scan/_query_index` |
| 符文 | `starforge/glyphs.py:digits_for/glyphs_for_ua/panel_png`；`starforge/app/overlay.py`；`starforge/__main__.py:cmd_glyph_overlay` |
| agent | `starforge/agent/starforge_agent.py`；`starforge/live/agent_install.py`；`starforge/live/agent_client.py`；`starforge/live/build.py`；`starforge/live/writer.py` |
| 生物 | `starforge/creature.py:companions/role_table/capabilities` |
| 设置/诊断 | `starforge/app/pages/settings.py`；`starforge/services/__init__.py:doctor/diagnostics`；`starforge/selfcheck.py` |
| 打包 | `.github/workflows/release.yml`；`packaging/build_agent_runtime.py`；`packaging/vendor.py`；`packaging/entry.py` |

---

## 12. 最后提醒

1. **不要用“代码存在”代替“功能完成”**：尤其 agent 传送/扫描/建造，必须 R3–R7 实机证据。
2. **不要用“扫描结果”代替“索引入库”**：当前 `GalaxyPage._scan` 与 `galaxy.db` 是两条路；P0 必须合并。
3. **不要用“能显示 3D”代替“3D 正确”**：当前是几何 + 平涂，无贴图；验收要对比游戏内/服务端渲染。
4. **不要把“包体大”当作“功能多”**：131 MB 里有大量可裁剪的静态库/翻译/运行时；先剪再谈功能。
5. **每次游戏更新后重跑 build 指纹/agent 实机**；未知 build 默认只读，这是产品可信度的底线。
