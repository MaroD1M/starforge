# 功能地图：界面 → 服务 → 后端状态

> 用途：前端交互先定稿，后端按这张表逐项补齐，避免“页面有了但后端没接口”。
> 状态：✅ 已接 / 🟡 有后端未接完 / ⬜ 未实现 / 🔴 需 agent 实机。

## 1. 概览 Home

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 数据层/存档/游戏状态 | 四张状态卡 | `Services.health` | ✅ |
| 游戏内连接摘要 | 第四张卡 | `Services.agent_status` | ✅ |
| 快速跳转 | 四个按钮 | Shell `navigate` | ✅ |
| 最近活动 | 预留 | 需要事件日志 | ⬜ |

## 2. 飞船实验室 Ship Lab

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 船型选择 | `QComboBox` | `catalog_ship` | ✅ |
| 部件树/过滤/勾选 | `QTreeWidget` | `catalog_ship` | ✅ |
| 想要/不要 | 模式切换 | `start_search` | ✅ |
| 涂装筛选 | 颜色按钮 | `start_search` | ✅ |
| 搜索预算/取消 | 预算框 + JobDock | `start_search` / `jobs` | ✅ |
| 结果网格/列表 | `QListWidget` | `search` | ✅ |
| 缩略图 | 异步图标 | `preview_png` | ✅ |
| 原生 3D | `ShipViewer` | `preview_mesh` | ✅ |
| 复制种子 | Inspector | 剪贴板 | ✅ |
| 收藏 | Inspector | 需要本地收藏服务 | 🟡（按钮占位） |
| 导出 glb | Inspector | `glb_path` | ✅ |
| 写回存档 | Inspector | `apply_seed` | 🟡（按钮占位，需对话框） |
| 对比/分享码 | 预留 | 需要 compare/share 服务 | ⬜ |

## 3. 我的船队 Fleet

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 自动找存档 | 左侧卡 | `default_save` | ✅ |
| 读取船列表 | 网格 | `ships` | ✅ |
| 缩略图/3D | 网格 + Inspector | `preview_png` / `preview_mesh` | ✅ |
| 等级/属性 | Inspector | `ships` 已带 stats | ✅ |
| 备份/恢复 | 按钮 | `backups` / `restore` | 🟡 需接对话框 |
| 批量导出 | 按钮 | 需要 export 服务 | ⬜ |
| 多船对比 | 预留 | 需要 compare 服务 | ⬜ |
| 同伴/护卫舰 | 预留标签 | `creatures` / writer | ⬜ |

## 4. 星图 Galaxy

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 当前星系 | Hero 卡 | `system` | ✅ |
| 行星表 | 表格 | `system` | ✅ |
| 船池 | 表格 | `system` | ✅ |
| 扫描 | 条件条 + JobDock | `start_system_scan` | ✅ |
| 扫描结果 | 表格 | `start_system_scan` | ✅ |
| 符文显示/复制 | PNG + 剪贴板 | `glyph_strip_png` | ✅ |
| 导出 CSV | 按钮 | `galaxy_export_csv` | ✅ |
| 银河索引查询 | 预留 | `galaxy_query` | 🟡 |
| 行星 3D/资源详情 | Inspector | 需要扩展字段 | ⬜ |
| 符文置顶浮窗 | 预留 | `overlay` | 🟡 |

## 5. 游戏内 Game Link

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 三步状态 | 运行时/Mod/Agent | `agent_status` | ✅ |
| 一键连接 | 自动安装 Mod + 注入 | `agent_launch` + `agent_wait` | ✅ |
| 启动游戏并注入 | 按钮 | `agent_launch(attach=False)` | ✅ |
| 停止注入器 | 按钮 | `agent_stop` | ✅ |
| 玩家/星系/行星/船槽 | 遥测按钮 | `agent_call` | ✅ |
| 传送/还原 | 安全区 | `agent_call` | 🔴 需实机 |
| 扫描读取/即时扫描 | 安全区 | `agent_call` | 🔴 需实机 |
| 外部内存只读探测 | 按钮 | `live_probe` | ✅ |
| 修复运行时/组件 | 按钮 | `agent_install_deps` | ✅ |
| 传送落点预检 | 预留 | 需要 agent 扩展 | ⬜ |
| 任意建造/改色/解上限 | 预留 | 需要 agent M7 | ⬜ |

## 6. 设置 Settings

| 功能 | 界面 | 服务 | 状态 |
|---|---|---|---|
| 游戏/存档/数据路径 | 表单 | `settings_snapshot/update` | ✅ |
| 自动检测 | 按钮 | `autodetect` | ✅ |
| 写入开关 | 复选 | `update_settings` | ✅ |
| 环境体检 | 按钮 | `doctor` | ✅ |
| 诊断导出 | 预留 | 需要 diagnostics zip | ⬜ |
| 外观/性能 | 预留 | 需要主题设置 | ⬜ |

---

## 7. 后端补齐顺序

1. **写回对话框**：ShipLab → `apply_seed`（备份/副本/确认）。
2. **备份/恢复**：Fleet → `backups` / `restore`。
3. **收藏与分享码**：本地 JSON + `share_code`。
4. **银河索引查询**：Galaxy 过滤 + 导出。
5. **符文置顶浮窗**：Qt 原生，不使用 tkinter。
6. **同伴/护卫舰/设计器**：按 PLAN-V4 的 P2/P3。
7. **agent M5/M6/M7**：传送、扫描发现、建造/改色/上限。
