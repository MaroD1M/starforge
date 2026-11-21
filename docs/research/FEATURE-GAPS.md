# 功能缺口审计（以代码为唯一事实来源）

> **审计时点快照**：本文统计于 2026-11-21 晚，版本 `0.14.9`；当前工作区已是 `0.15.0`，
> 部分缺口已在同日晚些时候修复。**状态以 §0.1 的复核更新和当前代码为准**，不要把下文
> 的“缺失/占位”当成永久结论。

- 审计对象：`<仓库>`，审计时版本 `0.14.9`（`starforge/__init__.py`），build **185034**。
- 审计方式：只读阅读 `starforge/`、`tests/`、`README.md`；**没有修改代码、没有注入、没有读写游戏进程内存**。
- 审计时机器状态（仅被动观察，未调用 agent）：
  - `NMS.exe` 正在运行（`<pid>`，启动于 `<时间>`）；
  - 本机 `127.0.0.1:5000` 处于监听，属主进程正是 `NMS.exe`（说明 pymhf agent 已注入并在游戏进程内提供 HTTP）；
  - `~/.starforge/agent/state.json` 记录 `build_id=<build-id>`、`attach=false`、`port=5000`；
  - `starforge/live/builds/185034.json` 的 `status` 仍是 `unverified`，`capabilities` 全为 `pending`；
  - 审计时模板 Mod 已存在（`<游戏目录>/GAMEDATA/MODS/starforge-templates/`），但应用内没有生成入口；该缺口已于 2026-11-21 修复（见 §0.1）；
  - 存档目录有 4 份玩家存档（`<存档目录>`，文件名不在此复录）。

## 0.1 复核更新（2026-11-22）

| 审计项 | 审计时 | 当前 | 证据 |
|---|---|---|---|
| 模板 Mod 生成/安装 | 缺失（只有 Web API） | **已修**：游戏内页有“安装模板 Mod”，写 `<游戏目录>/GAMEDATA/MODS` | `[代码] app/pages/game_link.py:303-311`、`:984-1012`；`services/__init__.py:1262-1289` |
| 连接已运行的游戏 | 占位（传 `attach=True`） | **已修**：先检测 `NMS.exe`，再走 `attach=False` | `[代码] services/__init__.py:1291-1312`；`game_link.py:772-774` |
| 附近兴趣点 `scan.poi` | 占位（按钮可点但必失败） | **已下线**：按钮禁用并标注“未实现” | `[代码] game_link.py:278-292`、`:1026-1035` |
| 传送门效果 | 实验 | **`prepare_warp` 已实测**；服务层默认仍被 build 闸门挡住 | `[代码] agent/starforge_agent.py:838-909`；`[实测] AGENT-INJECT-CRASH.md §14` |
| 实时资产（工具/货船/同伴） | 未列 | **已实现**：`/multitool`、`/freighter`、`/pets` + 游戏内页卡片 | `[代码] agent/starforge_agent.py:1110-1168`；`widgets/live_assets.py` |
| 多存档切换 | 缺失 | **仍缺失** | `services.saves()` 无页面调用 |
| 传送快照历史 | 缺失 | **仍缺失** | `services.agent_snapshots()` 无页面调用 |
| selfcheck / agent 热重载入口 | 缺失 | **仍缺失**（服务层有方法） | `services.diagnostics()` / `agent_reload()` 无页面调用 |

> 与 `docs/AUDIT-2026-11.md` 的分工：那份审“文档是否准确”；本文只审“功能是否存在、
> 是否接通、是否有门槛”。脱敏与发布前检查见 `docs/SECURITY-REVIEW-2026-11.md`。

## 0. 口径与统计

| 现状 | 定义 |
|---|---|
| 已实现 | 页面/CLI 有入口，且代码路径能完成该功能（含“默认被安全闸门关闭”的写操作） |
| 只读 | 能读取/展示，但没有对应的写回或编辑能力 |
| 占位 | 有按钮或文案，但点击后是禁用、空实现、或必然失败 |
| 缺失 | 没有入口；**包括“服务层已实现但页面完全没接”**（在 §2 单列） |

**统计：已实现 44 · 只读 5 · 占位 3 · 缺失 25（共 77 项）。**

> 说明：本表把“服务层有能力、页面没入口”算作**缺失**，因为从用户视角该功能在应用里不存在。若按“服务层是否有实现”统计，缺口数会显著下降——这正是 §2 要解决的问题。

---

## 1. 功能清单

### 1.1 搜索

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 按部件 want/avoid 搜索种子 | 已实现 | `app/pages/ship_lab.py:773`；`search.py:167` | 离线 + 游戏数据 | 低 | P1 |
| 涂装筛选（RGB + 容差，命中后验色） | 已实现 | `app/pages/ship_lab.py:779`；`search.py:54` | 游戏数据 | 中（候选预算截断） | P1 |
| 搜索预算/线程/估算/取消 | 已实现 | `app/pages/ship_lab.py:249`、`:757`、`:821`；`services/__init__.py:293` | 离线 | 低 | P2 |
| 分享码 `nsh1:` 生成/导入 | 已实现 | `app/pages/ship_lab.py:1143`、`:1159`；`services/favorites.py:216` | 离线 | 低 | P2 |
| 按种子反查部件/名称/等级/槽位 | 缺失 | `search.py:27` 的 `SearchQuery` 只有 `ship/want/avoid/look`；无按种子查询入口 | 离线 | 低 | P3 |
| 在线/社区种子库 | 缺失 | 仓库无种子服务客户端；`README.md:154` 明确“默认不联网” | 网络 | 隐私/合规 | 不做 |

### 1.2 预览

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 原生 3D（贴图/四视图/自转/截图） | 已实现 | `app/widgets/ship_viewer.py:149`、`:475`、`:495`；`pages/ship_lab.py:369` | 游戏数据 | 低（无 GL 时回退 PNG） | P1 |
| 服务端光栅缩略图/渲染图 | 已实现 | `render.py:153`、`:178`；`pages/ship_lab.py:1034` | 游戏数据 | 低 | P1 |
| glb 导出（可内嵌贴图） | 已实现 | `pages/ship_lab.py:1208`；`preview.py:220`；`gltf.py:148` | 游戏数据 | 低 | P2 |
| 部件级 3D 小窗 | 已实现 | `app/dialogs/part_preview.py:62`；`preview.py:175` | 游戏数据 | 低 | P2 |
| 姿态/动画预览 | 缺失 | `preview.py:163` 返回 `posable`，但全仓无第二处使用；`ship_viewer` 只做静态网格 | 游戏数据 | 低 | P3 |

### 1.3 存档

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 自动发现/读取存档与船队 | 已实现 | `pages/fleet.py:326`、`:492`；`save/library.py:161` | 离线 | 低 | P1 |
| 同型换种子写回（备份/原子写/读回/回滚） | 已实现 | `save/writer.py:118`；`dialogs/write_back.py:118` | 离线 | 中 | P1 |
| 船级/属性编辑 | 已实现 | `save/writer.py:194`；`dialogs/class_editor.py:213` | 离线 | 中 | P1 |
| 货币/飞船改名/涂装 | 已实现 | `services/save_edit.py:155`、`:299`；`dialogs/save_edit.py:706` | 离线 | 中 | P1 |
| 备份列表/恢复 | 已实现 | `save/writer.py:292`、`:317`；`dialogs/backup.py:167` | 离线 | 中（覆盖原档） | P1 |
| 存档变化自动刷新 | 已实现 | `pages/fleet.py:386` | 离线 | 低 | P2 |
| 批量导出 ZIP（glb+png+清单） | 已实现 | `pages/fleet.py:712`；`export.py:17` | 游戏数据 | 低 | P2 |
| 存档列表/多存档切换 | 缺失 | `services/__init__.py:344` 的 `saves()` 无页面调用；舰队页只用 `default_save`（`fleet.py:332`） | 离线 | 低 | P0 |
| 存档 diff/比较 | 缺失 | 无对应模块；`dialogs/compare.py` 只比较飞船，不比较存档 | 离线 | 中 | P3 |

### 1.4 设计器

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 每组单选部件 + 实时 3D 组合 | 已实现 | `pages/ship_designer.py:472`、`:571` | 游戏数据 | 低 | P1 |
| 用这套部件搜索种子 | 已实现 | `pages/ship_designer.py:843` | 离线 + 游戏数据 | 低 | P1 |
| 保存/载入本地设计 JSON | 已实现 | `pages/ship_designer.py:632`、`:671` | 离线 | 低 | P2 |
| 写入新槽/替换槽（可选涂装） | 已实现 | `pages/ship_designer.py:723`；`services/__init__.py:437`；`dialogs/design_write.py:195` | 离线 | 中 | P1 |

> 代码注释与行为不一致：`pages/ship_designer.py:4` 写“本页不直接写存档（后端尚未验证）”，但 `:723` 已接 `DesignWriteDialog` 并写存档。属于**过期注释**，不是功能缺失。

### 1.5 星图

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 当前星系/行星/船池 | 已实现 | `pages/galaxy.py:542`；`services/__init__.py:674` | 游戏数据 | 低 | P1 |
| 附近扫描并写入银河索引 | 已实现 | `pages/galaxy.py:1170`；`galaxy.py:168` | 游戏数据（unicorn 子进程） | 中 | P1 |
| 银河索引查询/统计/CSV | 已实现 | `pages/galaxy.py:1011`、`:1057`、`:1123`；`galaxy.py:111` | 离线 | 低 | P2 |
| 地址工作台（12 位 glyphs / 0x 种子） | 已实现 | `pages/galaxy.py:658`、`:792`、`:842`；`dialogs/address.py:68` | 游戏数据 | 低 | P1 |
| 种子反查星系（候选 + 生成器证实） | 已实现 | `pages/galaxy.py:842`、`:894`；`dialogs/locate.py:82`；`system.py:131` | 游戏数据 | 中（欠定） | P2 |
| 传送到扫描结果行星 | 已实现 | `pages/galaxy.py:1383`；`services/__init__.py:1058` | agent | 高 | P1 |
| 坐标文本解析（XYZ/冒号格式） | 缺失 | `dialogs/address.py:15` 明确“暂不支持”；`pages/galaxy.py:748` 直接拒绝 | 离线 | 低 | P2 |
| 银河地图可视化 | 缺失 | 星图只有 `QTableWidget`（`pages/galaxy.py:272`、`:294`、`:372`），无地图画布 | 离线 | 低 | P3 |
| 离线天气/动植物/资源字段 | 缺失 | `system.py:23` 的 `PLANET_FIELDS` 明确这些字段需游戏运行时；UI 不展示 | agent / 游戏数据 | 低 | P2 |

### 1.6 符文

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 12 符文面板 + 置顶浮窗 | 已实现 | `glyphs.py`；`app/overlay.py:38`；`pages/galaxy.py:1451` | 游戏数据（DDS） | 低 | P1 |
| 复制符文串/坐标 | 已实现 | `pages/galaxy.py:940`、`:1445`、`:1448` | 离线 | 低 | P2 |
| 单符文图标预览 | 缺失 | `services/__init__.py:662` 的 `glyph_png()` 无页面调用；页面只用 `glyph_strip_png` | 游戏数据 | 低 | P3 |
| 游戏内自动输入/模拟点击 | 缺失 | 无输入自动化代码；`overlay.py` 只显示，`README.md:42` 明确“零注入、照着点” | — | 反作弊/ToS | 不做 |

### 1.7 联动（游戏内 agent / 模板槽）

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 启动游戏并注入 | 已实现 | `pages/game_link.py:134`；`live/agent_install.py:591`（`attach=False`） | agent | 高（NMS 可能判定模组冲突退出） | P1 |
| 连接已运行的游戏 | 已实现（2026-11-22 复核） | 先检测 `NMS.exe`，再走 `agent_connect()`（`attach=False`）；`services/__init__.py:1291-1312` | agent | 中 | P0 |
| 准备 Python 运行时 | 缺失 | `services/__init__.py:862` 的 `agent_bootstrap_runtime()` 无页面调用；UI 无“准备运行时”按钮 | 网络（首次）/ 文件 | 中 | P1 |
| 安装/更新 NMSpy+pymhf | 已实现 | `pages/game_link.py:143`；`agent_install.py:527` | 网络 + 文件 | 中 | P1 |
| 模板 Mod 生成/安装 | 已实现（2026-11-22 复核） | 游戏内页“安装模板 Mod”按钮；`game_link.py:303-311`、`services/__init__.py:1262-1289` | 文件系统 + 游戏目录 | 低 | P0 |
| 送进游戏（写模板槽 seed） | 已实现 | `app/widgets/game_push.py:81`；`services/__init__.py:1142`；`live/writer.py:266` | 外部内存 | 中（只写 8 字节 + 回读） | P1 |
| 实时遥测（player/system/planet/ships） | 已实现 | `pages/game_link.py:159`、`:728`；`agent/starforge_agent.py:527`、`:561`、`:615`、`:642` | agent | 低（只读） | P1 |
| 行星档案 `planet.scan` | 已实现 | `pages/game_link.py:794`；`agent/starforge_agent.py:661` | agent | 低（只读） | P1 |
| 扫描条即时完成 | 已实现 | `pages/game_link.py:252`；`agent/starforge_agent.py:840` | agent | 中（游戏内状态） | P2 |
| 写入发现列表 `scan.discover` | 缺失 | `agent/starforge_agent.py:853` 明确“暂不开放”；`services/__init__.py:947` 标为未开放 | agent | 高 | P3 |
| 附近兴趣点 `scan.poi` | 已下线（2026-11-22 复核） | 按钮禁用并标注“未实现”；`game_link.py:278-292` | agent（缺端点） | 低 | P0 |
| 实时资产（工具/货船/同伴） | 已实现（2026-11-22 复核） | `/multitool`、`/freighter`、`/pets` + `widgets/live_assets.py` | agent（只读） | 低 | P1 |
| 传送 / 还原（传送含写后位置确认，还原不含） | 已实现 | `pages/game_link.py:970`；`agent/starforge_agent.py:736`、`:814`；`services/__init__.py:1087` | agent | 高 | P1 |
| 还原后位置读回确认 | 缺失 | `services/__init__.py:1051` 只对 teleport/teleport.portal 触发确认；agent restore 返回 `confirmation=pending`（`agent/starforge_agent.py:833`） | agent | 中（可能误报“还原完成”） | P2 |
| 传送门效果 `teleport.portal` | 已实现 | `agent/starforge_agent.py:378`、`:772`；`pages/game_link.py:510` | agent | 高（实验） | P2 |
| 传送快照历史 | 缺失 | `services/__init__.py:834` 的 `agent_snapshots()` 无页面调用；`~/.starforge/agent/snapshots.json` 已存在 | 离线 | 低（只读） | P1 |
| agent 热重载 / 卸载 | 缺失 | `services/__init__.py:1068`（reload）无页面；`agent_install.py:520`（uninstall）无服务/UI | agent / 文件 | 中 | P2 |
| 外部内存只读探测 | 已实现 | `pages/game_link.py:680`；`services/__init__.py:1122`；`live/writer.py:344` | 外部内存 | 低（只读） | P1 |
| 自检 `selfcheck` | 缺失 | `services/__init__.py:1221` 的 `diagnostics()` 无页面调用；设置页只跑 `doctor`（`settings.py:387`） | 离线 | 低 | P2 |
| CLI 能力表与真实端点一致 | 占位 | `__main__.py:291` 的 13 个抽象名字（如 `ship.write_seed`）与 agent 的 15 个 HTTP 端点不是一一对应（审计时是 12 个） | — | 低（误导脚本） | P2 |
| 日志/诊断包 | 已实现 | `pages/settings.py:341`、`:436`；`services/__init__.py:1303`、`:1323` | 离线 | 低（已脱敏） | P1 |

### 1.8 生物

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 生物能力盘点 / 角色名表 | 只读 | `creature.py:155`、`:216`；`web/routes.py:146`、`:155`；原生 UI 只显示角色库数量（`widgets/pets_view.py:274`） | 游戏数据 | 低 | P2 |
| 生物生成器 / 生态扫描 | 缺失 | `creature.py:114` 只做符号探路；`:122` 明确“外观网格尚未定位” | 游戏数据 + 逆向 | 高 | P3 |

### 1.9 多功能工具

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 多用途工具只读列表 | 只读 | `pages/fleet.py:272`；`services/__init__.py:403` | 离线 | 低 | P2 |
| 多用途工具写回（种子/等级/槽位） | 缺失 | `save/extras.py:9` 明确“没有对应 API 的内容不伪造”；无写函数 | — | 高 | P3 |

### 1.10 货船 / 护卫舰

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 货船只读（型号/种子/母星系） | 只读 | `pages/fleet.py:277`；`services/__init__.py:426` | 离线 | 低 | P2 |
| 护卫舰只读（类型/等级/属性/种子） | 只读 | `pages/fleet.py:268`；`services/__init__.py:427` | 离线 | 低 | P2 |
| 货船/护卫舰写回（换种子/改级/远征） | 缺失 | `save/extras.py:9` 明确不做；无对应函数 | — | 高 | P3 |
| 货船/基地货舱库存编辑 | 已实现 | `save/extras.py:68`、`:91`（库存列表含货船/基地箱子） | 离线 | 中 | P2 |

### 1.11 基地

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 基地箱子库存编辑 | 已实现 | `save/extras.py:68`、`:91`；`dialogs/save_extras.py:209` | 离线 | 中 | P2 |
| 基地部件解锁（知识分组 base） | 已实现 | `save/extras.py:25`；`dialogs/save_extras.py:251` | 离线 | 中 | P2 |
| 基地建造/上传/改名/删除 | 缺失 | 全仓无基地实体读写模块；只有 `BaseContext` 作为存档根键被引用 | — | 高 | P3 |

### 1.12 任务

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 任务列表/状态 | 已实现 | `save/extras.py:242`；`dialogs/save_extras.py:288` | 离线 + 游戏语言表 | 低 | P2 |
| 标记选中任务完成 | 已实现 | `save/extras.py:253`；`dialogs/save_extras.py:511` | 离线 | 中 | P2 |
| 奖励解锁/标记领取 | 已实现 | `save/extras.py:298`、`:319`；`dialogs/save_extras.py:309` | 离线 | 中 | P2 |
| 任务链/里程碑/任务奖励编辑 | 缺失 | 无任务奖励或里程碑字段读写；奖励分组只有 expedition/twitch/special/shop | — | 中 | P3 |

### 1.13 同伴

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 同伴只读列表（名称/类型/群系/种子/信任） | 只读 | `creature.py:54`；`widgets/pets_view.py:188`；`pages/fleet.py:265` | 离线 | 低 | P2 |
| 同伴 3D 预览 | 缺失 | `creature.py:106` 明确需生物生成器；`pets_view.py:18` 只显示说明 | 游戏数据 + 逆向 | 高 | P3 |
| 同伴写回（改名/换种子/特征） | 缺失 | `creature.py:8` 明确“只读”；无 writer | — | 高 | P3 |

### 1.14 多人

| 功能 | 现状 | 证据（文件:行） | 依赖 | 风险 | 建议优先级 |
|---|---|---|---|---|---|
| 多人状态检测与界面提示 | 已实现 | `agent/starforge_agent.py:213`、`:509`；`pages/game_link.py:406` | agent | 低 | P1 |
| 多人模式写入/传送 | 缺失 | `services/__init__.py:29`、`:966`；`agent/starforge_agent.py:222` 三重拒绝 | agent | 高（有意禁用） | 不做 |

---

## 2. UI 缺口：服务层有、页面没接

### 2.1 完全无入口的服务能力

| 能力 | 服务层证据 | 页面现状 | 影响 |
|---|---|---|---|
| 准备 Python 运行时 | `services/__init__.py:862`；`agent_install.py:209` | 无按钮；`game_link.py:724` 的“修复”只调 `install_deps` | 干净机器上修复会返回 `needs_runtime`（`agent_install.py:556`），用户被要求点一个不存在的按钮 |
| 生成/安装模板 Mod | `services/__init__.py:1262`；`live/exml.py:510` | **已修**：游戏内页有“安装模板 Mod”按钮（§0.1） | 仍需先配置游戏目录；装完需重启 |
| 传送快照历史 | `services/__init__.py:838` | 无入口；只提供“还原上一次” | 仍未补（§0.1） |
| agent 热重载 | `services/__init__.py:1075` | 无页面入口（服务/HTTP 可用） | 仍未补 UI（§0.1） |
| agent 卸载/删除 | `agent_install.py:520` | 无服务方法、无按钮 | 与 `README.md:141`“可随时停止/删除”不一致 |
| 存档列表扫描 | `services/__init__.py:344` | 舰队页只用 `default_save`（`fleet.py:332`） | 多份存档（本机 4 份）无法在应用内选择 |
| selfcheck 自检 | `services/__init__.py:1221` | 设置页只有 `doctor`（`settings.py:387`） | 没有端到端“数据/存档/搜索/3D/符文/写入(副本)”自检入口 |
| 生物能力深诊断 | `services/__init__.py:811`；`creature.py:155` | 同伴页只显示角色库数量 | 用户只看到“需要生物生成器”，看不到具体缺哪条链 |
| 单符文图标 | `services/__init__.py:662`、`:794` | 页面只用整条符文图（`glyph_strip_png`） | 单字符复制/预览场景缺失（低优先） |
| 全局能力表 | `services/__init__.py:187` | 首页/外壳用 `health` 自行拼芯片 | 能力状态没有单一事实来源，页面各自解释 |

### 2.2 按钮文案与实际行为不一致

| 按钮/文案 | 代码行为 | 证据 | 建议 |
|---|---|---|---|
| “连接游戏” | **已修（§0.1）**：先检测 `NMS.exe`，再走 `agent_connect()`（`attach=False`） | `services/__init__.py:1291-1312`；`game_link.py:772-774` | 保持：不要把 `attach=True` 重新设为默认 |
| “停止注入器” | 只终止本应用启动的 launcher 进程；agent 仍在游戏内 | `agent_install.py:754`、`:766` | 文案改为“停止启动器”，并说明彻底停用需重启游戏 |
| “修复运行时/游戏内组件” | 只跑 `pip install`；缺 runtime 时没有下一步入口 | `pages/game_link.py:724`；`agent_install.py:527`、`:556` | 失败时把“准备运行时”按钮亮出来，或自动串起来 |
| “附近兴趣点”（传送门/古遗迹/货船/飞船） | **已修（§0.1）**：按钮禁用并标“未实现”，不会再发 `scan.poi` | `game_link.py:278-292` | 若要恢复，需先补端点 + 白名单 + 能力表 |
| “允许未验证游戏版本实验写操作” | **仍未统一**：勾选后游戏内页传送仍被 `_build_verified` 挡住；星图/同伴传送却走服务层可放行 | `game_link.py:401-485`、`:1127-1154`；`services/__init__.py:939-972`；`galaxy.py:1434` | 两处统一用 `live_capabilities` 的 `experimental/unverified_allowed`（待合并） |
| “送进游戏”的可用性 | 安装按钮已补；但 `GamePushButton` 仍只检查“该船型有模板标题”，不检查 Mod 是否已装 | `widgets/game_push.py:22-29`、`:64-78`；`services/__init__.py:1180-1190` | 让按钮读取安装状态（目录存在/文件齐全），未装时给出可点入口 |
| 设置“搜索线程数”（tooltip：搜索/扫描的工作线程数） | 实际只有飞船实验室读取该值；设计器硬编码 `workers=1`，星图扫描不接受 `workers` 参数 | `pages/settings.py:137`；`pages/ship_lab.py:265`；`pages/ship_designer.py:853`；`services/__init__.py:764` | 要么让扫描/设计器也读该值，要么把 tooltip 改成“仅飞船实验室” |
| README：“准备运行时 → 安装/更新组件 → 安装 Mod → 注入并连接” | 实际按钮只有：连接、启动并注入、停止、刷新、修复、外部内存探测 | `README.md:137`；`pages/game_link.py:125`–`:148` | 文档与 UI 同步，或补齐按钮 |
| README：“可随时停止/删除” | 只能停止 launcher；`uninstall_mod()` 未接 | `README.md:141`；`agent_install.py:520` | 增加“卸载游戏内组件”并明确不碰存档 |

### 2.3 其他“看起来有、其实没有”的状态

- `pages/ship_designer.py:4` 的模块 docstring 仍写“本页不直接写存档（后端尚未验证）”，但 `:723` 已写存档——**注释过期**。
- `web/routes.py:9` 的模块 docstring 写“POST /api/saves/apply（S4 才实现；此网关先落地安全闸门）”，但 `:173` 已完整实现写回——**注释过期**（不影响功能）。
- `pages/game_link.py:50` 的初始文案“当前游戏内代理未实现传送门效果”会在 `refresh()` 前短暂显示；而 agent 已有 `teleport.portal`（`starforge_agent.py:772`）——**初始态文案滞后**。

---

## 3. 实机可验证项（build 185034 + 当前已注入 agent）

> **边界**：以下都是“建议如何验证”，本次审计**没有**调用 agent、没有 attach、没有写内存。只读项优先；写操作需用户显式同意。

当前可复现事实：

- `NMS.exe` 正在运行（`<pid>`），`127.0.0.1:5000` 的监听属主也是同一进程 → agent 已在游戏进程内；
- `~/.starforge/agent/state.json`：`build_id=185034-092236962EE0`、`attach=false`、`port=5000`；
- `~/.starforge/agent/snapshots.json` 已有 20 条以内的传送快照；
- `GAMEDATA/MODS/starforge-templates/` 已存在（含 `REWARDTABLE.EXML`、`EMOTEMENU.EXML`、`PLAYERCHARACTER.ENTITY.EXML`、`LocTable.mxml`、8 张 DDS）。
- **注意**：安装副本 `~/.starforge/agent/starforge_agent.py` 与仓库源码 SHA256 不同（`311FB4…` vs `4AB43E…`，36498 B vs 35623 B）。两者端点集合都是 12 个、都没有 `scan.poi`，但实机验证前建议先通过“修复/重新安装”把副本同步到仓库版本，避免把旧副本行为当成仓库行为。

| 可验证项 | 只读做法 | 预期证据 | 风险 |
|---|---|---|---|
| agent 已连接/在存档内 | 游戏内页点“刷新状态”（**不要**点“连接游戏”） | 步骤 3 芯片 ✓；`live_capabilities` 返回 `reachable=true`、`hello.in_game=true` | 低 |
| `/hello` 能力表 | 看日志里的 hello JSON | 15 个端点能力（审计时 12 个）、`multiplayer`、`portal.api`、`auth=token-query` | 低 |
| 玩家 UA/坐标/位置 | 点“玩家位置” | `ua`、`location`、`position`、`system_name`、`stats` | 低 |
| 当前星系/行星表 | 点“当前星系” | `system_name` + `planets[]` | 低 |
| 当前行星/完整档案 | 点“当前行星”/“读取行星档案” | 天气/资源/动植物/哨兵/CreatureIDs | 低 |
| 游戏内 12 船槽 | 点“游戏内船槽” | `count` 与 `ships[]`（空槽被过滤） | 低 |
| 外部内存只读探测 | 点“外部内存只读探测” | 每种船型的候选地址、score、`structural`、`scan` 覆盖统计；**不写内存** | 低 |
| 模板槽是否可定位 | 同上，看 `chosen`/`reason` | 8 个模板中应有可写候选；若“多个同样可信”会明确拒绝 | 低 |
| POI 按钮必失败 | 点任一“传送门/古遗迹/货船/飞船” | 客户端报“未知 agent 命令：scan.poi”，不会发 HTTP | 低（可安全复现） |
| build 闸门 | 看“游戏版本 185034 · 未验证”芯片；点传送 | 按钮禁用或返回 `E_BUILD_UNVERIFIED` | 低 |
| 快照历史（数据在、UI 无） | 只读打开 `~/.starforge/agent/snapshots.json` | 多条 `time/location/destination/glyphs` | 低 |
| 多存档（数据在、UI 无） | `python -m starforge saves`（只读扫描）或看存档目录 | 4 份 `player` 存档；应用内只能选 1 份 | 低 |
| 货船/护卫舰/多工具只读 | 读取 `<存档>` 后切到对应标签 | 表格有行；不可编辑（无写按钮） | 低 |
| 同伴只读 | 切到“同伴”标签 | 描述符/种子/群系；底部明确无 3D | 低 |
| 地址工作台离线解析 | 输入 `123456789ABC` | 星系名/坐标/UA/符文图 | 低（需游戏数据） |
| 种子反查 | 选一艘船点“查星系” | 候选数 + 已证实命中；无结果时明确“欠定” | 中（慢，只读） |

**不建议在当前状态实机验证的项**：

- “启动游戏并注入”——游戏已在运行，可能拉起第二个进程或注入失败；
- “送进游戏”、传送、传送门、`scan.instant`——会写游戏状态；
- 手工改 `builds/185034.json` 的 `status=verified` 来“解锁”写操作——地址书未校准，属于绕过闸门。

---

## 4. 明确不可行 / 不建议

| 项 | 结论 | 代码依据 |
|---|---|---|
| 多人模式写入/传送 | **不做**。服务层与 agent 双重拒绝，且多人下写位置没有安全语义 | `services/__init__.py:29`、`:966`；`agent/starforge_agent.py:222` |
| 反作弊/隐藏注入 | **不建议**。当前 build 下 NMS 会把注入的 Python/ctypes 判为模组冲突并主动退出；继续对抗只会增加封号/崩溃风险 | `agent_install.py:729`、`:740` |
| 默认 attach 注入 | **不做**。实测初始化后注入会在 `python311.dll` 访问冲突；仅保留环境变量调试开关 | `agent_install.py:605` |
| 跨型移植外观 | **物理不可行**。`seed` 与船型/模型绑定，跨型写只会得到另一种船 | `save/writer.py:149`；`services/__init__.py:459` |
| 同伴 3D / 同伴写回 | **暂不可行**。存档描述符不在静态 rig descriptor 里，需要运行时生物生成器；写回无验证 API | `creature.py:106`、`:155` |
| 货船/护卫舰/中队/多工具写回 | **暂不可行**。上游没有稳定写 API，代码明确不伪造 | `save/extras.py:9`；`fleet.py:463` |
| 坐标文本直接解析 | **不做**。字段宽度与输入格式不一致，硬猜会给出错误门地址 | `dialogs/address.py:15`；`pages/galaxy.py:748` |
| `scan.discover` 写发现列表 | **暂不开放**。发现管理器偏移未确认，写错会污染存档 | `agent/starforge_agent.py:853` |
| 自动输入符文/模拟按键 | **不建议**。无代码实现，且属于输入自动化，和“零注入、照着点”的产品承诺冲突 | `overlay.py`；`README.md:42` |
| 网页 UI / WebGL 查看器 | **已移除**，不要按旧文档恢复；`web/` 只提供 JSON API | `web/app.py`；`README.md:65` |
| 绕过 build 闸门写地址书 | **禁止**。`write_allowed` 只在 `status=verified` 时为真；未校准的偏移会写错对象 | `live/build.py:230`、`:241` |

---

## 5. 建议的下一批 5 个任务（按投入产出排序）

### 任务 1｜把“模板 Mod 生成/安装”接进游戏内页（P0）

- 现状：生成器与服务都已存在，但只有 Web API；`GamePushButton` 和错误文案都要求用户“先在游戏内页安装”。
- 改动面：`pages/game_link.py` 增加“生成/安装模板 Mod”按钮 + 目标目录选择；调用 `services.live_template_mod()`；安装前检测 `<game>/GAMEDATA/MODS/starforge-templates` 是否已存在并提示覆盖/跳过。
- **验收标准**：
  1. 干净目录点击后生成 `REWARDTABLE.EXML`、`EMOTEMENU.EXML`、`PLAYERCHARACTER.ENTITY.EXML`、`LocTable.mxml` 和 8 张 DDS，路径与 `live/exml.py:45` 的常量一致；
  2. 成功后 `exml.manifest()` 可读，8 个船型的“送进游戏”按钮从禁用变为可用；
  3. 目标目录不可写/游戏目录未配置时给出具体路径与原因，不抛裸异常；
  4. 全程不写游戏内存、不改存档；重复点击幂等。

### 任务 2｜修复“连接游戏”这条必失败主路径（P0）

- 现状：按钮调 `attach=True`，服务默认拒绝；用户第一眼看到的就是错误。
- 改动面：`pages/game_link.py:_connect`、`live/agent_install.py:launch` 的调用策略。
- **验收标准**：
  1. agent 已注入时，点“连接游戏”直接进入“已连接/已进入存档”状态（先探测 `/hello` 或 5000 端口），不再调用 attach 注入；
  2. 未注入时，按钮给出“请用启动游戏并注入”的可操作提示，并禁用/隐藏；
  3. 任何路径都不再把 `attach=True` 作为默认值；保留 `STARFORGE_ALLOW_ATTACH_INJECT=1` 仅作调试；
  4. 状态芯片、空态文案、按钮可用性与实际状态一致。

### 任务 3｜统一高风险写闸门，让“允许未验证实验写操作”真正生效（P0）

- 现状：`allow_unverified_agent` 只影响服务层；游戏内页传送先被 `_build_verified` 挡住，星图传送却走服务层可放行。
- 改动面：`pages/game_link.py:_apply_state`、`_teleport`；以 `live_capabilities` 返回的 `experimental/unverified_allowed/blocked_by` 为唯一依据。
- **验收标准**：
  1. 未验证 build + 开关关闭：游戏内页与星图都禁用高风险写，并显示同一原因；
  2. 未验证 build + 开关开启：两处都允许“实验写”，但 UI 明确标注“未验证/实验”；
  3. 多人模式：两处都禁用，原因一致；
  4. 不允许通过 UI 绕过 `build.summary()` 的 `write_allowed` 判断。

### 任务 4｜POI 扫描：要么实现，要么明确下线（P0）

- 现状：按钮按 `scan` 能力启用，但 `scan.poi` 不在客户端白名单，也不在 agent 端点里，点击必报“未知命令”。
- 改动面（二选一）：
  - 最小改动：`pages/game_link.py:869` 的按钮统一禁用，tooltip 写“未实现，需实机校准”，并从 `_cap_buttons` 移除；
  - 完整实现：agent 增加只读 `/scan/poi`、client 白名单、`live_capabilities` 能力项与 build 闸门。
- **验收标准**：
  1. 不存在“可点击但必然报未知命令”的路径；
  2. UI 可用状态与 `/hello` 返回的能力一致；
  3. 若实现，只返回经过校验的坐标，不伪造；无结果时明确说明；
  4. 多人模式仍禁用写类 POI 操作。

### 任务 5｜把“存档列表 + 传送快照历史”这两块只读数据接出来（P1）

- 现状：`services.saves()` 与 `services.agent_snapshots()` 都已实现，页面零调用；本机有 4 份存档、20 条以内快照。
- 改动面：`pages/fleet.py` 左侧存档卡增加列表（路径/类型/大小/船数/可用性）；`pages/game_link.py` 增加只读快照时间线。
- **验收标准**：
  1. 舰队页列出全部 `*.hg`，区分 player/account/manifest，非玩家存档给出明确原因；
  2. 点击任一玩家存档可切换并读取，失败不破坏当前选择；
  3. 快照列表显示时间、目标 glyphs、来源位置，只读，不新增写路径；
  4. 不改变现有 `default_save` 行为；无存档时仍显示原空态。

---

## 6. 复核方式（本次实际使用的只读检查）

```powershell
# 版本 / 设置 / build 地址书
[System.IO.File]::ReadAllLines("starforge/__init__.py")
Get-Content "$env:USERPROFILE\.starforge\settings.json" -Raw
Get-Content "starforge/live/builds/185034.json" -Raw

# agent 是否在运行（被动观察，不 attach）
Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq 5000
Get-Process -Id <pid> | Select-Object Id,ProcessName,Path,StartTime
Get-Content "$env:USERPROFILE\.starforge\agent\state.json" -Raw
Get-Content "$env:USERPROFILE\.starforge\agent\snapshots.json" -Raw

# 模板 Mod 是否已安装（只读目录）
Get-ChildItem "<游戏目录>\GAMEDATA\MODS\starforge-templates" -Recurse -File

# 服务层方法与页面调用对比
Select-String -Path starforge/services/__init__.py -Pattern '^    def '
Select-String -Path starforge/app/**/*.py -Pattern 'svc\.([a-zA-Z_]+)' -AllMatches

# agent 端点 vs CLI 能力名
Select-String -Path starforge/agent/starforge_agent.py -Pattern '@endpoint'
Select-String -Path starforge/__main__.py -Pattern '_AGENT_CAPABILITIES'
```

**未做**：游戏注入、agent HTTP 调用、内存读写、`live push`、传送、写存档、打包、完整 pytest。凡“实机是否可用”的结论，均只引用现有代码/状态文件，并在 §3 标为“待验证”。

**行号漂移提示**：行号按 2026-11-21 工作区快照统计；后续改动后请以“路径 + 函数/类名”为准复核。
