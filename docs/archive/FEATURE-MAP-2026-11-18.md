# 功能地图：界面 → 服务 → 后端状态

> 用途：前端交互先定稿，后端按这张表逐项补齐，避免“页面有了但后端没接口”。
> 状态：✅ 代码已接（离线链路有测试/真实数据验证）· 🟡 代码已接、未实机验证 · ⬜ 仍缺后端/入口 · 🔴 需 Windows 实机校准。
> 说明：✅/🟡 只代表当前工作区代码状态，**不代表 Windows 实机通过**。

## 1. 概览 Home

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 数据层/存档/游戏状态 | 四张状态卡 | `Services.health` | ✅ |
| 游戏内连接摘要 | 第四张卡 | `Services.agent_status` | ✅ |
| 快速跳转 | 四个按钮 | Shell `navigate` | ✅ |
| 最近活动 | 活动列表 + 清空 | `services.history` | ✅ |
| 最近状态摘要 | 状态卡 | `Services.health` / `agent_status` | ✅ |

## 2. 飞船实验室 Ship Lab

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 船型选择 | `QComboBox` | `catalog_ship` | ✅ |
| 部件树/过滤/勾选 | `QTreeWidget` | `catalog_ship` | ✅ |
| 想要/不要 | 模式切换 | `start_search` | ✅ |
| 涂装筛选（主色/副色/容差） | 颜色按钮 + 容差 | `start_search` | ✅ |
| 搜索预算/并行线程 | 预算框 + 线程数 | `start_search`（`workers`） | ✅ |
| 搜索估算 | 条件栏文案 | `search_estimate` | ✅ |
| 搜索取消 | JobDock / 状态栏 | `cancel_job` / `jobs` | ✅ |
| 结果网格/列表 | `QListWidget` | `search` | ✅ |
| 缩略图 | 异步图标 | `preview_png` | ✅ |
| 原生 3D | `ShipViewer` | `preview_mesh` | ✅ |
| 复制种子 | Inspector | 剪贴板 | ✅ |
| 收藏 / 收藏夹 | Inspector + 收藏夹对话框 | `services.favorites` | ✅ |
| 分享码导入/导出 | Inspector + `nsh1:` | `favorites.encode/decode_share` | ✅ |
| 2–3 艘并排对比 | 加入对比 / `CompareDialog` | `compare` 对话框 | ✅ |
| 种子→星系反查 | `LocateDialog` | `Services.locate` | ✅ |
| 导出 glb | Inspector | `glb_path` | ✅ |
| 写回存档 | `WriteBackDialog` | `apply_seed` | ✅（副本/读回/回滚；未实机验证） |
| 可访问性（卡片名称/描述） | 结果卡片 | `set_card_accessibility` | ✅ |

## 3. 设计器 Designer

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 逐部件拼装 + 实时 3D | 部件树 + `ShipViewer` | `catalog_ship` / `preview_mesh` | ✅ |
| 用当前部件搜索种子 | 搜索按钮 + 结果列表 | `start_search` | ✅ |
| 本地设计文件 | 保存/载入 `.nmsdesign.json` | 本地 JSON | ✅ |
| 写入新船槽 | `DesignWriteDialog` | `apply_design(slot="new")` | ✅（未实机验证） |
| 替换现有槽 | 槽位下拉 | `apply_design(slot=N)` | ✅（未实机验证） |
| 同时涂装 | 主色/副色/调色板 | `set_ship_paint`（槽位 0–11） | ✅（未实机验证） |
| 备份/确认/读回/回滚 | 写入对话框 | `transact_save` | ✅ |

## 4. 我的船队 Fleet

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 自动找存档 | 左侧卡 | `default_save` | ✅ |
| 读取船列表 | 网格/列表 | `ships` | ✅ |
| 缩略图/3D | 网格 + Inspector | `preview_png` / `preview_mesh` | ✅ |
| 等级/属性 | Inspector | `ships` 已带 stats | ✅ |
| 船级/属性编辑 | `ClassEditorDialog` | `apply_class` | ✅（未实机验证） |
| 货币/改名/涂装编辑 | `SaveEditDialog` | `services.save_edit` | ✅（未实机验证） |
| 备份/恢复 | `BackupDialog` | `backups` / `restore` | ✅ |
| 批量导出 | 按钮已启用 | `export.export_zip` | ✅ |
| 多船对比 | 预留 | ShipLab 有对比，Fleet 暂无 | ⬜ |
| 同伴只读 | 标签页 | `creatures` | ✅ |
| 护卫舰只读 | 标签页 | `fleet_extras` | ✅ |
| 多用途工具只读 | 标签页 | `fleet_extras` | ✅ |
| 货船只读 | 标签页 | `fleet_extras` | ✅ |
| 扩展编辑（库存/词语/知识/任务/奖励） | `SaveExtrasDialog` | `save/extras.py` | ✅（未实机验证） |
| 货船/护卫舰/中队写回 | — | 无稳定 API | ⬜ |
| 同伴写回/3D | — | 需 Shipwright/运行时生成器 | ⬜ |

## 5. 星图 Galaxy

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 当前星系 | Hero 卡 | `system` | ✅ |
| 行星表 | 表格 | `system` | ✅ |
| 船池 | 表格 | `system` | ✅ |
| 条件扫描 + 取消 | 条件条 + JobDock | `start_galaxy_scan` | 🟡 扫描已接；取消按钮已接，但子进程尚未接收取消 |
| 扫描入库 | 结果表 + 索引 | `start_galaxy_scan` → `galaxy.db` | ✅ |
| 银河索引查询 | 索引标签 | `galaxy_query` | ✅ |
| 符文显示/复制 | PNG + 剪贴板 | `glyph_strip_png` | ✅ |
| 符文置顶浮窗 | 页面按钮 | `app.overlay` | ✅（Windows 实机未回归） |
| 导出 CSV | 按钮 | `galaxy_export_csv` | ✅ |
| 种子→星系反查 | 地址工作台 | `Services.locate` | ✅ |
| 地址/符文填入传送输入 | 地址工作台 | GameLink 输入框 | ✅（仅界面状态） |
| 行星天气/资源/动植物 | Inspector | 需要 agent 或新生成器 | ⬜ |
| 行星 3D/资源分布 | Inspector | 需要新生成器 | ⬜ |
| 银河地图可视化 | — | 无 | ⬜ |

## 6. 游戏内 Game Link

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 三步状态 | 运行时/Mod/Agent | `agent_status` | ✅ |
| 一键连接 | 自动安装 Mod + 注入 | `agent_launch` + `agent_wait` | ✅（未实机验证） |
| 启动游戏并注入 | 按钮 | `agent_launch(attach=False)` | ✅（未实机验证） |
| 停止注入器 | 按钮 | `agent_stop` | ✅ |
| 玩家/星系/行星/船槽 | 遥测按钮 | `agent_call` | 🟡 未实机验证 |
| 传送/还原 | 安全区 | `agent_call` | 🟡 代码已接；build/多人闸门 + 快照 + 写后读回；未实机验证 |
| 扫描读取/即时扫描 | 安全区 | `agent_call` | 🟡 未实机验证 |
| token（query） | 启动时注入 | `AgentClient` + agent `_auth_block` | ✅ |
| 端口冲突检测 | 启动状态 | `port_available` / `requested_port` | ✅（pymhf 仍固定 5000） |
| runtime manifest | 设置页状态 | `AGENT_RUNTIME_MANIFEST` / `runtime_report` | ✅ |
| 外部内存只读探测 | 按钮 | `live_probe` | ✅ |
| 修复运行时/组件 | 按钮 | `agent_install_deps` | ✅ |
| 传送落点预检 | — | 仅写后读回确认 | ⬜ |
| 任意建造/改色/解上限 | — | 需要 agent M7 | ⬜ |

## 7. 设置 Settings

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 游戏/存档/数据路径 | 表单 + 浏览 | `settings_snapshot/update` | ✅ |
| 自动检测 | 按钮 | `autodetect` | ✅ |
| 写入开关 | 复选 | `update_settings` | ✅ |
| 写入前二次确认 | 复选 | `confirm_writes` | ✅ |
| 备份保留数 | 数字框 | `backup_keep` | ✅ |
| 搜索线程数 | 数字框 | `workers` | ✅ |
| build / agent 状态 | 版本与代理卡 | `diagnostics_overview` | ✅ |
| 环境体检 | 按钮 | `doctor` | ✅ |
| 日志复制/摘要 | 按钮 | `recent_logs` / `agent_log_tail` | ✅ |
| 诊断 ZIP | 按钮 | `export_diagnostics` | ✅ |
| 外观/主题 | — | 需要主题设置 | ⬜ |

---

## 8. 剩余补齐顺序

1. **Windows 实机回归**：agent 只读 → 传送/还原 → 扫描；未通过前保持 🟡。
2. **货船/护卫舰/中队写回**：等 Shipwright 稳定 API，不伪造。
3. **同伴写回/3D**：描述符链与运行时生成器，R&D。
4. **行星天气/资源/3D**：agent 字段或新生成器；离线不画饼。
5. **银河地图/社区坐标**：可选 P3。
6. **包体/安装器/签名**：见 GAP-ANALYSIS。
