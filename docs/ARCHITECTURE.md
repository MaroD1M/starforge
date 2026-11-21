# Starforge 真实架构

> **事实来源**：本文件以当前工作区代码为准（`starforge/`、`tests/`、`pyproject.toml`、`scripts/`、`.github/workflows/release.yml`），统计时版本为 `0.15.0`。
> 上一版架构文档（`archive/ARCHITECTURE-2026-11-18.md`）与旧网页设计（`archive/DESIGN-2026-11-18.md`）只作历史参考，**不作为事实来源**；`PACKAGING.md` 仍是当前的打包专题文档。旧架构文档里的 `application/`、`ui/` 两层在当前代码中不存在，`desktop.py` 也不存在。
> 本轮（2026-11-21～22）对 build 185034 做了只读/传送/热重载实机验证，相关结论在
> `docs/LESSONS.md` 与 `docs/AGENT-INJECT-CRASH.md` 标注了证据；没有运行发布打包，
> 打包相关结论仍来自 CI 配置与 `packaging/` 脚本。

---

## 0. 结论摘要

- 实际包：`core`、`data`、`save`、`live`、`agent`、`services`、`app`、`web`，外加仓库根下的算法/领域模块（`search.py`、`system.py`、`preview.py`、`galaxy.py` 等）。
- 实际入口：`starforge/__main__.py`（CLI/默认原生窗口）、`starforge/app/main.py`（Qt 启动）、`starforge/web/app.py`（可选 Flask JSON API）。
- 实际的“应用层”是 **`services/__init__.py` 一个 1460 行的门面类**（`Services`，约 78 个方法），不是旧文档描述的 `application/` 包。
- 实际的 UI 层是 `app/`（PySide6），不是 `ui/`。`app/context.py` 的 `AppContext` 只在 `shell.py` 里发布健康状态/导航，**页面并没有通过它取服务**，页面仍然直接 `get_services()`。
- 实际存在依赖方向违规：
  - `web/routes.py` 直接 import `save.library`、`save.writer`、`live.*`、`jobs`、`search`、`system`、`galaxy`，并自己再编排一遍。
  - `app/` 有直接 import 领域模块的情况：`pages/fleet.py` → `export.export_zip`，`pages/ship_lab.py` / `pages/settings.py` → `core.settings` / `core.paths`，`widgets/game_push.py` → `live.exml`。
- 游戏内存通道和 pymhf agent 通道是**两条独立通路**：
  - 内存通道：`live/exml`（模板 Mod）+ `live/mem` + `live/writer`，只写模板槽的 8 字节种子。
  - agent 通道：`agent/starforge_agent.py`（pymhf + NMSpy Python Mod）+ `live/agent_install` + `live/agent_client`，通过本机 HTTP 调用。
- 当前 `live/builds/185034.json` 的 `status` 是 `unverified`，按 `live/build.py` 的闸门，这版默认只允许只读能力。

---

## 1. 代码地图与体量

### 1.1 按目录统计

行数用当前工作区 `.py` 文件实际统计；行数会随代码变化，引用时请以“文件 + 函数/类名”为准，行号只是定位帮助。

| 目录 | 文件数 | 约行数 | 真实职责 |
|---|---:|---:|---|
| `starforge/app/` | 41 | 12983 | PySide6 外壳、页面、对话框、控件、主题、置顶浮窗 |
| `starforge/live/` | 10 | 2844 | 内存读写、模板槽定位/写入、模板 Mod 生成、模板图标生成、agent 安装/客户端、build 指纹 |
| `starforge/services/` | 4 | 2494 | 用例门面、收藏、历史、存档编辑扩展 |
| `starforge/save/` | 5 | 1007 | 存档分类/读取缓存、写事务、备份/回滚、额外编辑 |
| `starforge/agent/` | 2 | 861 | 游戏内 pymhf Mod（独立运行时加载，不在主进程 import） |
| `starforge/web/` | 3 | 855 | 可选 Flask JSON API + 本机 Host/Origin 防护 |
| `starforge/core/` | 8 | 605 | 路径、设置、日志、错误、单实例锁、控制台编码、文案 |
| `starforge/data/` | 5 | 516 | `ShipRef` 数据模型、Gagarin catalog/icons、GSHI |
| 仓库根模块 | 19 | 约 4032 | 搜索、系统/星球生成、预览、渲染、星系索引、生物、符文等 |

总计约 27000 行 Python（含 agent，不含测试/脚本/打包脚本）。测试另有 56 个 `test_*.py` 文件、约 6000 行。

### 1.2 关键文件（当前真实行数）

| 文件 | 行数 | 关键内容 |
|---|---:|---|
| `starforge/services/__init__.py` | 1460 | `class Services`、`SERVICES`、`get_services()`；设置/目录/搜索/存档/预览/星系/生物/agent/诊断全在这里 |
| `starforge/app/pages/galaxy.py` | 1504 | 星图、地址工作台、扫描、银河索引 |
| `starforge/app/pages/ship_lab.py` | 1221 | 搜索、结果卡片、3D 查看、收藏、写回、送进游戏 |
| `starforge/app/pages/game_link.py` | 1149 | 游戏内代理安装/连接/传送/扫描 |
| `starforge/app/pages/fleet.py` | 912 | 存档船队、3D、扩展编辑、备份 |
| `starforge/app/pages/ship_designer.py` | 900 | 部件设计、写入新船/替换槽 |
| `starforge/agent/starforge_agent.py` | 1375 | pymhf 单文件 Mod，15 个 HTTP 端点 |
| `starforge/__main__.py` | 792 | CLI 分发、`_internal` 子进程、doctor/selftest/webcheck |
| `starforge/live/agent_install.py` | 738 | runtime 探测、安装 Mod、安装依赖、启动/停止/等待 agent |
| `starforge/web/routes.py` | 749 | 44 条 API 路由，包含与 services 重复的编排 |
| `starforge/live/exml.py` | 548 | 8 槽模板 Mod：REWARDTABLE / EMOTEMENU / PLAYERCHARACTER / LocTable |
| `starforge/live/writer.py` | 411 | 全内存扫描模板槽、结构自洽评分、写 8 字节、回读 |
| `starforge/live/mem.py` | 327 | Windows `ReadProcessMemory` / `WriteProcessMemory` / `VirtualQueryEx`；`FakeProcess` |
| `starforge/live/build.py` | 255 | NMS.exe sha256 + 版本指纹、地址书、写闸门 |
| `starforge/live/agent_client.py` | 202 | 本机 HTTP 客户端，token 查询参数，GET→PUT 兼容 |
| `starforge/save/writer.py` | 323 | `apply_seed` / `apply_class` / `restore`，四步铁律 |
| `starforge/save/transaction.py` | 107 | 通用写事务 `transact_save` |
| `starforge/save/library.py` | 189 | 存档分类、读船、`_SHIPS_CACHE` |
| `starforge/jobs.py` | 103 | `Job` / `JobRegistry` / `run_in_thread` |
| `starforge/core/errors.py` | 64 | 领域异常与 HTTP 码 |
| `starforge/web/app.py` | 89 | Flask 工厂、Host/Origin 防护、异常映射 |

### 1.3 仓库根模块

这些模块不是包，但承担了真实领域逻辑：

| 文件 | 行数 | 职责 |
|---|---:|---|
| `starforge/search.py` | 246 | 把上游 `fast_search` 包成可取消、带 ETA 的搜索 |
| `starforge/system.py` | 263 | 系统/星球生成，调用 `nms_procgen` / unicorn |
| `starforge/preview.py` | 228 | L0/L1 预览、glb、网格 |
| `starforge/render.py` | 359 | 服务端 PNG 渲染 |
| `starforge/gltf.py` | 247 | glTF/glb 写出 |
| `starforge/galaxy.py` | 248 | SQLite 银河索引、扫描、查询 |
| `starforge/creature.py` | 345 | 生物角色表/同伴 |
| `starforge/glyphs.py` | 259 | 传送门符文面板/图标 |
| `starforge/parts.py` | 88 | 部件目录来源/汇总 |
| `starforge/paint.py` | 46 | 种子配色 |
| `starforge/tex.py` | 137 | 贴图解码状态 |
| `starforge/export.py` | 66 | 批量导出 zip |
| `starforge/warm.py` | 95 | 启动预热（pak 元数据/一艘几何/系统生成） |
| `starforge/selfcheck.py` | 181 | 端到端自检（写只在副本） |
| `starforge/locate_game.py` | 159 | 跨平台游戏目录发现 |
| `starforge/zh.py` | 151 | 中文标签映射 |

---

## 2. 真实分层与依赖方向

### 2.1 分层图（按现有目录）

```text
┌────────────────────────────────────────────────────────────────────┐
│ 入口层                                                             │
│  __main__.py（CLI，默认 app）  app/main.py（Qt 引导）  web/app.py   │
└───────────────┬──────────────────────────┬─────────────────────────┘
                │                          │
    ┌───────────▼───────────┐   ┌──────────▼───────────────┐
    │ app/  PySide6          │   │ web/  Flask JSON API     │
    │ shell.py               │   │ app.py（防护/异常映射）  │
    │ pages/ widgets/        │   │ routes.py（44 条路由）   │
    │ dialogs/ theme/        │   │                          │
    │ context.py（信号）     │   │  ── 直接 import save/    │
    └───────────┬───────────┘   │     live/jobs/search/…   │
                │               └──────────┬───────────────┘
                │ get_services()           │ 部分绕过
    ┌───────────▼──────────────────────────▼───────────────┐
    │ services/  用例门面                                   │
    │ Services（1460 行，78 个方法）                        │
    │ favorites.py / history.py / save_edit.py              │
    └───────────┬──────────────────────────────────────────┘
                │ 运行时延迟 import
    ┌───────────▼──────────────────────────────────────────┐
    │ 领域/平台层                                           │
    │ core/  data/  save/  live/  agent/                    │
    │ search.py system.py preview.py galaxy.py creature.py  │
    │ glyphs.py render.py gltf.py export.py …               │
    └───────────┬──────────────────────────────────────────┘
                │
    ┌───────────▼──────────────────────────────────────────┐
    │ 外部依赖                                               │
    │ NMS-Shipwright：nms_save / nms_procgen                │
    │ Gagarin GAMEDATA：catalog.txt / icons.bin             │
    │ 游戏：NMS.exe / PCBANKS / .hg 存档                    │
    │ pymhf + NMSpy（仅 agent 运行时）                      │
    │ PySide6 / Flask / numpy / unicorn                     │
    └──────────────────────────────────────────────────────┘
```

### 2.2 期望的依赖方向（现有代码的“应然”）

```text
入口 → app/web → services → 领域（core/data/save/live/agent + 根模块） → core
```

- `core` 不依赖上层。
- `agent` 是独立运行时，不能被主进程 import；打包时也显式排除了 `pymhf` / `nmspy` / `starforge.agent.starforge_agent`。
- `app` 只应依赖 `services` 和 `core` 的纯工具，不应直接碰 `save/live/nms_*`。
- `web` 只应依赖 `services`，不应自己写业务编排。

### 2.3 实际存在的依赖方向违规（带代码位置）

| 编号 | 违规 | 证据 | 影响 |
|---|---|---|---|
| V1 | `web` 直接依赖存档/实时/任务/搜索/系统/星系 | `web/routes.py:20` `from ..save import library`；`:177`、`:198`、`:390` `from ..save import writer`；`:716`、`:723`、`:733`、`:746` `from ..live import …`；`:220`/`:479`/`:509` import `jobs, search, system, galaxy` | 同一用例有两套实现；审计、脱敏、闸门容易分叉 |
| V2 | `web` 自己造任务，不走 services | `/api/search` 在 `routes.py:218-234` 直接 `jobs.REGISTRY.create` + `search.run`；`/api/system/scan` `:507-538`；`/api/galaxy/scan` `:476-504` | 与 `Services.start_search/start_system_scan/start_galaxy_scan` 行为可能不同 |
| V3 | `web` 写接口绕过 `Services.apply_seed/apply_class/live_push` | `routes.py:173-186`、`:386-400`、`:744-765` | 少了 `_record` 历史、统一错误包装、agent build 闸门等 |
| V4 | `app` 直接 import 领域模块 | `pages/fleet.py:29` `from ...export import export_zip`；`pages/ship_lab.py:15` `from ...core import settings as settings_core`；`pages/settings.py:24` `from ...core import paths`；`widgets/game_push.py:15` `from ...live import exml` | UI 与领域耦合；换壳/复用困难；单测必须拉 Qt |
| V5 | `AppContext` 名义上是跨页通道，实际基本未使用 | `app/shell.py:62` 创建 `AppContext`；只有 `shell.py:405` 发布健康、`:447` 发布任务；页面各自 `self.svc = get_services()`（如 `pages/fleet.py:121`、`pages/galaxy.py:37`、`pages/game_link.py:38`） | 没有真正的全局状态/信号总线；页面状态各自为政 |
| V6 | `services` 是“上帝门面”，依赖被延迟 import 隐藏 | `services/__init__.py:15-17` 顶层只 import `core` 和 `.history`；其余全部在方法内 `from ..save…` / `from ..live…` / `from .. import system` | 依赖图工具看不到真实耦合；任何用例改动都集中到 1460 行单文件 |

补充：`services/__init__.py` 的模块级 import 很少，并不代表它只依赖 core；运行时它几乎调用所有领域模块，属于“动态依赖”。

---

## 3. 各层职责与关键文件

### 3.1 入口与外壳

- `starforge/__main__.py`：
  - `cmd_app` 启动原生 Qt；`--browser` 已移除（`__main__.py:33-49`）。
  - `cmd_serve` 启动 Flask API，默认随机空闲端口，使用同一个单实例锁（`:52-70`）。
  - `cmd_internal` 是隐藏子进程入口（`:452-511`），只允许 `system`、`locate`、`system-scan`、`galaxy-scan`。
  - `cmd_doctor`、`cmd_webcheck`、`cmd_selftest`、`cmd_agent`、`cmd_live`（`:514-790`）。
- `starforge/app/main.py`：
  - `multiprocessing.freeze_support()`、`InstanceLock`、faulthandler 崩溃日志、`QSurfaceFormat`、安全模式（`:79-127`）。
- `starforge/app/shell.py`：
  - `MainWindow`：左侧 `NAV`（`shell.py:36-55`）、页面字典（`:109-117`）、JobDock（`:123-124`）、5 秒健康检查（`:77-81`）、关闭时等待线程池 4 秒（`:479-482`）。
- `starforge/web/app.py`：
  - `create_app` 只创建 Flask，不提供静态网页；`ALLOWED_HOSTS` 校验 Host/Origin（`:17-46`）；领域异常映射为 `{ok:false,error:{kind,message,hint}}`（`:48-70`）；启动时可选后台 warm（`:75-78`）。

### 3.2 UI 层（`starforge/app/`）

- `theme.py`：QSS 字符串 + 调色板，没有独立 qss 资源文件。
- `notify.py`：轻量通知；`widgets/feedback.py`：Toast/错误横幅/空态/加载遮罩。
- `widgets/worker.py`：把同步服务调用丢到 `QThreadPool`；worker 内禁止碰 QWidget。
- `widgets/job_dock.py`：每秒轮询 `svc.jobs()`，展示/取消任务，不持久化。
- `widgets/game_push.py`：把一条 `ShipRef` 交给 `services.live_push_ship`（先弹二次确认），成功后提示去游戏表情菜单领取。
- `widgets/live_assets.py`：游戏内页的“实时资产”卡片，展示 `/multitool`、`/freighter`、`/pets` 三个只读端点；单块失败只影响该块。
- `widgets/pets_view.py`：同伴只读表 + “传送到来源星球”（走 `Services.warp_portal`）。
- `pages/`：7 个页面（home/search/designer/mine/systems/live/settings），均直接 `get_services()`。
- `dialogs/`：写回、改级、备份、收藏、对比、地址、部件预览、设计写入等。
- `context.py`：`AppContext` 持有 `Services` 和 5 个信号；目前只被 shell 少量使用。

真实规模：页面层 5 个文件都超过 900 行（`galaxy 1504`、`ship_lab 1221`、`game_link 1149`、`fleet 912`、`ship_designer 900`），属于“页面内自带状态机 + 轮询 + 错误处理”的实现方式。

### 3.3 用例层（`starforge/services/`）

`Services` 是 UI 与 HTTP 共用的唯一门面，但这个“唯一”目前被 web 路由部分打破。

主要方法分组：

- 进程隔离：`_internal`（`:107-146`）。
- 健康/能力：`health`、`capabilities`、`live_capabilities`（`:150-192`、`:910-973`）。
- 设置：`settings_snapshot`、`update_settings`、`autodetect`（`:196-222`）。
- 目录：`catalog`、`catalog_ship`（`:226-256`）。
- 搜索/任务：`search`、`search_estimate`、`start_search`、`jobs/job/cancel_job`（`:281-340`）。
- 存档：`saves/ships/default_save/apply_seed/apply_class/apply_design/backups/restore`（`:344-595`）。
- 预览：`preview/glb_path/preview_mesh/part_thumb/part_mesh/part_icon/preview_png/glyph_*`（`:599-670`）。
- 星系/星球：`system/locate/start_system_scan/galaxy_*`（`:674-790`）。
- 生物：`creatures/creature_roles/creature_capabilities`（`:801-814`）。
- 实时/agent：`live_status/agent_*`、`live_capabilities`、`agent_call`、`live_probe/push/push_ship/template_mod`（`:818-1204`）。
- 诊断：`diagnostics/doctor/build_status/diagnostics_overview/recent_logs/export_diagnostics`（`:1208-1383`）。
- 单例：`SERVICES = Services()`、`get_services()`（`:1494-1500`）。

子模块：

- `services/favorites.py`：收藏 JSON、分享码、原子写（`:77-207`、`:330-438`）。
- `services/history.py`：最近活动 JSON、原子写（`:37-88`、`:205-231`）。
- `services/save_edit.py`：货币、船名、涂装等存档编辑；通过 `save.transaction` 写入（`:155-308`）。

### 3.4 存档领域（`starforge/save/`）

- `library.py`：
  - `classify` 只按文件名 + 头 4 字节分类（`save.hg` / `accountdata.hg` / `mf_*.hg`），`:60-74`。
  - `_SHIPS_CACHE` 以 `(绝对路径, mtime, size)` 为键（`:27-36`）；写回后调用 `clear_cache()`。
  - `open_ships` 解码一次，生成 `ShipRef` 列表与警告（`:113-158`）。
- `writer.py`：`apply_seed` / `apply_class` / `restore`，见第 4.3 节。
- `transaction.py`：通用 `transact_save(path, mutate, verify, copy)`（`:40-104`）。
- `extras.py`：库存/知识/任务/奖励编辑，全部走 `transact_save`，并要求调用方先确认（`:60-351`）。

### 3.5 实时通道（`starforge/live/`）

- `mem.py`：Windows ctypes 进程内存；`WinProcess`（`:183-241`）、`attach`（`:274-279`）、测试替身 `FakeProcess`（`:285-327`）。
- `writer.py`：只读全内存扫描 + 模板槽结构评分 + 写 8 字节 + 回读（`:175-280`）；`probe` 只读诊断（`:344-396`）；`status`（`:399-411`）。
- `exml.py`：生成 8 槽模板 Mod；`TEMPLATES` 8 种 `_PROC` 船型（`:29-38`），出厂种子 `STARFOR` + `0xA0+i`（`:105-109`），Slots `120..127`（`:112-113`），`write_mod`（`:510-541`），`manifest`（`:544-548`）。
- `build.py`：NMS.exe 指纹、地址书、写入闸门（`:54-80`、`:190-208`、`:230-255`）。
- `agent_install.py`：runtime 查找/安装、Mod 安装、依赖安装、启动/停止/等待（`:151-209`、`:419-479`、`:511-577`、`:591-709`）。
- `agent_client.py`：本机 HTTP 客户端、token、白名单（`:80-201`）。
- `compat.py`：兼容 NMS-Super-Ship-Hunter 的额外模板槽（`:1-31`）。
- `scan.py`：AOB 扫描引擎（`Pattern` / `find_all` / `pick_best` / `ScanPlan`），主要被测试与诊断使用（`:1-113`）。
- `iconart.py`：用游戏模型渲染模板表情图标，压成 BC1/DX10 DDS（154 行；`live/assets/icons` 的生成器；`tests/test_iconart.py`）。

### 3.6 游戏内 agent（`starforge/agent/`）

- `starforge_agent.py` 是 pymhf 单文件 Mod，文件头声明 `NMSpy==185034.0`、`pymhf[http_api]==0.2.5`（`:1-18`）。
- `class StarforgeAgent(Mod)`（`:406`），15 个 `@endpoint`（见 5.3）。
- 它不进入主进程：打包时 CI 显式 `--exclude-module starforge.agent.starforge_agent`（`release.yml:100`），运行时由独立 Python 加载。

### 3.7 Web 层（`starforge/web/`）

- `app.py`：工厂、Host/Origin 防护、异常映射。
- `routes.py`：44 条路由，覆盖 health/catalog/icons/saves/ships/creatures/search/jobs/preview/glyphs/system/locate/galaxy/export/thumb/settings/diagnostics/live。
- 关键现实：它是“兼容/调试 API”，但并不是薄适配层；它复制了 services 的大量编排，并且直接 import 领域模块。

### 3.8 基础设施（`starforge/core/`）

- `paths.py`：`STARFORGE_HOME`、`STARFORGE_SHIPWRIGHT`、`STARFORGE_GAMEDATA`、`STARFORGE_SAVES`；`ensure_shipwright_importable` 延迟导入上游并设置 `NMS_TOOL_CACHE`（`:65-86`）。
- `settings.py`：JSON 设置、`write_enabled` 默认 False、`gamedata_valid` 必须含 `Gagarin/ships/catalog.txt`（`:17-66`、`:147-151`）。
- `log.py`：`starforge` logger、控制台 + 2 MiB × 3 滚动文件（`:14-30`）。
- `errors.py`：领域异常到 HTTP 码。
- `lock.py`：PID 文件单实例锁。
- `console.py`：UTF-8 标准流、Windows 隐藏控制台。
- `strings.py`：中文文案集中。

---

## 4. 关键机制

### 4.1 任务模型（`starforge/jobs.py`）

- `Job`：`kind/status/created/finished/progress/error/result/id`，状态 `running | done | cancelled | failed`（`:17-63`）。
- 进度：`update(**kw)` 用 `tested / seconds` 计算 `rate` 与 `eta`（`:39-49`）。
- 取消：协作式 `threading.Event`，worker 每批检查 `should_stop()`（`:32-36`）。
- `JobRegistry`：进程内字典，最多保留 64 个，超限只清理非 running 的旧任务（`:66-88`）。
- `run_in_thread`：daemon 线程；异常写入 `job.error`，线程不静默死（`:91-100`）。
- 使用方：
  - `Services.start_search`（`services/__init__.py:298-316`）
  - `Services.start_system_scan` / `start_galaxy_scan`（`:699-721`、`:764-790`）
  - web `/api/search`、`/api/system/scan`、`/api/galaxy/scan`（`web/routes.py:218-234`、`:476-504`、`:507-538`）
  - UI `JobDock` 每秒轮询 `svc.jobs()`（`widgets/job_dock.py:138-141`、`:253-261`）。

限制：任务只在当前进程；重启即丢；Flask `threaded=True` 时多线程访问 `Job` 的 `status/finished` 没有统一加锁；没有跨进程任务表。

### 4.2 进程隔离（unicorn 子进程）

`Services._internal(kind, payload, timeout)`（`services/__init__.py:107-146`）把高风险原生调用放到独立 Python 进程：

- 开发：`[sys.executable, "-m", "starforge", "_internal", kind, "--payload", body]`
- 冻结：`[sys.executable, "_internal", kind, "--payload", body]`
- Windows `CREATE_NO_WINDOW`；`PYTHONFAULTHANDLER=0`；`subprocess.run(..., timeout=...)`。
- 从 stdout 末尾逐行找 JSON；找不到就报错；对 `0xC0000409` 有专门错误信息。
- `cmd_internal`（`__main__.py:452-511`）在子进程里 **禁用 faulthandler**，因为 Unicorn 的 VEH 与 faulthandler 会冲突；支持 `system`、`locate`、`system-scan`、`galaxy-scan`。

覆盖范围：

- 走子进程：`Services.system`（`:674-690`）、`locate`（`:692-697`）、`start_system_scan`（`:699-721`）、`start_galaxy_scan`（`:764-790`）。
- 不走子进程：
  - 搜索：`start_search` 用普通后台线程（`:298-316`）。
  - 实时内存：`live_probe` / `live_push` 直接 `mem.attach` + `writer`（`:1109-1127`），在调用线程里执行 ctypes 内存读写。
  - 存档写：在调用线程里执行（`save.writer` / `save.transaction`）。
- 这是“部分隔离”，不是全局进程隔离。注释里“Unicorn 在 Qt 线程里出现过 access violation”只解决了 unicorn 这一条路径。

另外，agent 启动是独立子进程：`agent_install.launch` 用 `subprocess.Popen` 起 bundled runtime（`:700-708`），不是 `_internal`。

### 4.3 写事务（四步铁律）

`save/writer.py` 的注释把规则写得很明确：读 → 备份 → 原子写（`.part` + `os.replace`）→ 重新解码校验；任何一步失败都回滚。

`apply_seed`（`save/writer.py:118-191`）：

1. `settings.require_write()`；缺 `confirm` → `BadRequest`；`game_running()` → `WriteRefused`。
2. 校验源船型与 `proc_model_matches()`，目标槽存在，目标船型必须同型（跨型拒绝，`:148-152`）。
3. 先把原文件字节读入内存；`_backup` 生成 `<save>.<timestamp>.bak`，并按 `backup_keep` 清理（`:98-112`）。
4. `set_ship_seed` → `_encode` → `_atomic_write`（写 `.part`、`flush`、`fsync`、`os.replace`，`:89-95`）。
5. 重新 `open_save` 并核对种子；失败 `WriteRefused`。
6. 任何异常：原子写回原始字节，保留备份，抛 `WriteRefused`（`:182-191`）。
7. `copy=True` 时先复制为 `<save>.edited.hg`，只改副本；`_ensure_copy` 用 `abspath` 避免 Windows 上“自己复制自己”（`:269-289`）。

`apply_class`（`:194-266`）同一套铁律，额外：

- 船级只允许 C/B/A/S；至少给 `ship_class`、`values` 或 `best`。
- 写后核对目标船等级；并核对**其它船种子一个都没动**（`:248-250`）。

通用事务 `save/transaction.py:transact_save`（`:40-104`）：

- 同样 `require_write` + `game_running`，但**不检查 confirm**；confirm 由调用方负责。
- `mutate(readable)` 修改可读 JSON；`verify(readable)` 重新解码后核对；`verify` 返回 `False` 或抛异常都算失败。
- `copy=True` 时用 `writer._copy_path` 生成 `.edited.hg`，同一路径不复制。
- 失败时原子写回原字节，备份保留。

`restore`（`:292-314`）：

- 要求 `confirm`；备份文件名必须以 `<save>.` 开头；恢复前先给当前状态再做一份 `_backup`；写回后 `open_save` 能打开才算成功。

注意：`save/extras.py` 的库存/知识/任务/奖励写入走 `transact_save`，但 confirm 由各函数 `_require_confirm`（`:60-65`）检查；`services/save_edit.py` 同样先检查 confirm。

### 4.4 错误模型

领域异常（`core/errors.py`）：

| 异常 | HTTP | kind | 典型场景 |
|---|---:|---|---|
| `NmsHunterError` | 500 | `internal` | 基类 |
| `BadRequest` | 400 | `bad_request` | 参数错误、缺 confirm |
| `NotFound` | 404 | `not_found` | 船型/任务不存在 |
| `SaveNotFound` | 404 | `save_not_found` | 找不到存档 |
| `SaveFormatError` | 422 | `save_format` | accountdata/mf_/损坏 |
| `GameFilesMissing` | 503 | `game_files_missing` | 缺游戏目录/上游 |
| `WriteDisabled` | 403 | `write_disabled` | 写开关关闭 |
| `WriteRefused` | 409 | `write_refused` | 游戏在跑/校验失败/回滚 |

- web：`web/app.py:48-70` 统一转 JSON；`FileNotFoundError` → 503；未捕获异常 → 500 并记日志。
- services：大多数直接向上抛领域异常；写操作失败会先 `_record` 最近活动，再抛。
- agent：HTTP 端点返回 `{"ok": false, "code": "E_...", "error": "..."}`，不抛 Python 异常给调用方；`services.agent_call` 把异常转成 `{"ok": false, "error": ...}`。
- UI：`widgets/worker.py:34-43` 把异常转成 `TypeName: message` 文本，显示在错误横幅/Toast。

不一致点：`services.live_push` 会抛异常，`services.agent_call` 返回 `ok:false`，`services.live_push_ship` 又自己捕获并返回 `ok:false`；调用方需要同时处理两种风格。

### 4.5 缓存

| 缓存 | 位置/键 | 失效方式 | 证据 |
|---|---|---|---|
| 存档船列表 | `save/library.py:_SHIPS_CACHE`，`(path, mtime, size)` | 写回/恢复后 `clear_cache()`；mtime/size 变化自然 miss | `library.py:27-36`、`writer.py:176-177`、`transaction.py:30-37` |
| 预览 glb | `~/.starforge/cache/preview/`，sha1(`schema/level/type/seed/parts/model`) | 改 `_CACHE_SCHEMA` 或文件不存在时重建 | `preview.py:33-47` |
| 游戏缓存 | `~/.starforge/cache/gamecache`（`NMS_TOOL_CACHE`） | 上游管理 | `paths.py:65-86` |
| 模板槽地址 | `Process._sf_slots`（按进程对象） | 每次 `_still_valid` 检查附近 Slots；`fresh=True` 重扫 | `live/writer.py:65-80`、`:229-263` |
| 模板槽扫描 | `Process._sf_scan` / `_sf_scan_key` | 条目 id 变化或 `fresh=True` | `live/writer.py:188-221` |
| 银河索引 | `~/.starforge/cache/galaxy.db`（SQLite） | `upsert` 覆盖 | `galaxy.py:58-102` |
| 预热 | 进程内 `_state` | 进程生命周期 | `warm.py:20-40` |

缓存失败一般不影响主流程：`_clear_cache` 吞异常；`Process` 属性回写吞异常。代价是“什么时候失效”分散在多个模块，排查 stale 数据需要同时看这些位置。

### 4.6 单实例锁

`core/lock.py`：

- `~/.starforge/instance.lock` 存 PID。
- `acquire` 读取已有 PID；若 PID 存活且不是自己，抛 `AlreadyRunning(pid)`；否则覆盖为自己的 PID（`:44-54`）。
- `release` 只有锁内容等于自己 PID 时才删（`:56-64`）。
- `app/main.py:81-85` 捕获 `AlreadyRunning`，在 Windows 上调用 `FindWindowW` 把已有窗口拉到前台；`serve` 则返回 2（`__main__.py:58-63`）。

这是协作式 PID 锁，不是 OS 级文件锁；PID 复用、手工删锁、异常退出后锁文件残留都需要注意。

### 4.7 日志与脱敏

- `core/log.py`：logger 名 `starforge`，控制台 + `~/.starforge/logs/starforge.log`；`RotatingFileHandler(maxBytes=2 MiB, backupCount=3)`（`:14-30`）。
- 原生崩溃：`app/main.py:37-47` 打开 `~/.starforge/logs/faulthandler.log`，`faulthandler.enable(all_threads=True)`。
- 未捕获异常：`app/main.py:50-56` 记 logger 并弹 QMessageBox。
- agent 日志：`~/.starforge/agent/launcher.log`（`agent_install.launcher_log_path`），pymhf 自身 `log_dir` 也指向 `~/.starforge/agent`（`agent_install.py:663`）。
- 脱敏：
  - `services/__init__.py:43-80`：`_REDACT_KEY_HINTS`（token/secret/password/...）+ 文本正则（Bearer/Authorization/token=...）。
  - `_redact` 递归处理 dict/list/str；`_redact_text` 处理日志文本。
  - 只用于 `recent_logs`（`:1290-1308`）和 `export_diagnostics`（`:1310-1383`）；**不是所有日志在写入时就脱敏**。
  - `agent_client.py:92-98` 明确把 token 放在查询参数里（pymhf 没有稳定 header 读取接口）；本机 URL/代理日志可能包含 token，诊断导出会脱敏，但运行日志本身不一定。
- token/state：`agent_client.write_state` 原子写并尽量 `chmod 0600`（`:52-66`）；`agent_install.launch` 生成一次性 token，写环境变量和 `~/.starforge/agent/token`（`:673-688`）。

---

## 5. 游戏内通道的架构位置

### 5.1 两条独立通路

```text
A. 内存模板通道（不需要注入）
   live/exml.py  ──生成模板 Mod──> 游戏 GAMEDATA/MODS/starforge-templates
   live/mem.py   ──OpenProcess/ReadProcessMemory/WriteProcessMemory──> NMS.exe
   live/writer.py ──扫描出厂种子 + Slots 自洽──> 写 8 字节 seed → 回读

B. 游戏内 agent 通道（pymhf 注入）
   live/agent_install.py ──安装 Mod/启动 runtime/load_mod_file──> NMS.exe 内的 Python
   agent/starforge_agent.py ──pymhf @endpoint──> 127.0.0.1:5000/StarforgeAgent
   live/agent_client.py ──HTTP GET/PUT──> 读取/传送/扫描/热重载
```

两者都归 `live/`，但责任完全不同：A 只写模板槽的种子，B 在游戏进程内调用引擎读写状态。`services.live_push` 走 A，`services.agent_call` 走 B。

### 5.2 模板 Mod（`live/exml.py`）

- 8 个 `_PROC` 船型：`sentinel/fighter/hauler/explorer/shuttle/exotic/living/solar`（`:29-38`）。
- 每个槽的出厂种子：7 字节 ASCII `STARFOR` + 第 8 字节 `0xA0+i`，保证 u64 且每槽唯一（`:105-109`）。
- 每个槽的 `Slots`：`120+i`（`:112-113`），用于内存侧结构自洽评分。
- 生成文件：
  - `METADATA/REALITY/TABLES/REWARDTABLE.EXML`
  - `METADATA/UI/EMOTEMENU.EXML`
  - `MODELS/COMMON/PLAYER/PLAYERCHARACTER/.../PLAYERCHARACTER.ENTITY.EXML`
  - `LocTable.mxml`
  - `TEXTURES/UI/FRONTEND/ICONS/STARFORGE/*.dds`（从 `live/assets/icons` 复制）
- `write_mod(dest)` 写到 `<dest>/starforge-templates`（`:510-541`）；`manifest()` 给内存写入器提供 `type/model/label/class/id/factory_seed/slots`（`:544-548`）。

### 5.3 pymhf + NMSpy agent

- agent 文件头：`NMSpy==185034.0`、`pymhf[http_api]==0.2.5`（`starforge_agent.py:1-18`）。
- 安装：`agent_install.install_mod()` 把源文件复制到 `~/.starforge/agent/starforge_agent.py`（`agent_install.py:511-517`）。
- 启动：`launch(attach=True/False)`：
  - **默认拒绝 attach 已运行的游戏**：实测 build 185034 注入已初始化进程会让 `NMS.exe` 在 `python311.dll` 访问冲突崩溃；只有 `STARFORGE_ALLOW_ATTACH_INJECT=1` 才强制允许（`agent_install.py:598-610`）。
  - 正常路径是 `attach=False`，由应用启动游戏；`start_paused=True`、`steam_gameid=275850`、`gui.shown=False`（`:648-664`）。
  - 通过 bundled runtime 的 `pymhf.load_mod_file` 加载 Mod（`:665-708`）。
- 端口：pymhf 当前固定 `5000`；`STARFORGE_AGENT_PORT` 只能做可配置覆盖 + 占用检测，不是真正的随机端口（`agent_install.py:591-596`、`:630-642`）。
- token：
  - 每次 `launch` 生成 `secrets.token_urlsafe(32)`（`:673`）。
  - 写入子进程 env `STARFORGE_AGENT_TOKEN`，并写 `~/.starforge/agent/token`（Steam 启动时环境变量会丢，agent 按 env → token 文件 → state.json 解析，`starforge_agent.py:68-88`）。
  - 客户端把 token 作为查询参数附加到每个请求（`agent_client.py:92-98`）。
  - agent 端 `_auth_block` 用 `hmac.compare_digest` 校验（`starforge_agent.py:92-98`）。
- HTTP 端点（15 个，`starforge_agent.py` 的 15 处 `@endpoint`）：
  - GET：`/hello`、`/player`、`/system`、`/planet`、`/planet/scan`、`/ships`、
    `/multitool`、`/freighter`、`/pets`
  - PUT：`/admin/reload`、`/teleport`、`/teleport/portal`、`/restore`、
    `/scan/instant`、`/scan`
  - `/multitool` / `/freighter` / `/pets` **不读运行时 partial struct**：先
    `cGcPlayerState.SaveToData()` 序列化到本地 `cGcPlayerStateData` 缓冲，再按存档布局解析
    （`starforge_agent.py:665-683`）。只写本地缓冲，不改游戏状态。
  - `/teleport/portal` 分 `warp_only` / `prepare_warp` / `full` 三档；`prepare_warp`
    已实测可传送（`starforge_agent.py:838-909`），服务层确认窗口 40 秒
    （`services/__init__.py:1058-1063`）。
- 客户端 GET/PUT 兼容：pymhf 某些版本把未显式声明 method 的路由注册成 PUT；`_read` 在 405 时回退 PUT（`agent_client.py:117-130`）。
- 写操作安全：
  - `_multiplayer_block()`：多人模式禁用传送/还原/扫描写（`starforge_agent.py:222-226`）。
  - 传送前 `_persist_snapshot` 写 `~/.starforge/agent/snapshots.json`；失败则不传送（`:116-137`、`:723-750`）。
  - `services.agent_call` 在调用前做 build 闸门 + 多人闸门（`services/__init__.py:1018-1053`）。
- 热重载：
  - agent `admin_reload` 通过 `pymhf.core.mod_loader.mod_manager.reload(key)` 在后台线程延迟 0.4 秒重载（`starforge_agent.py:1257-1289`）。
  - `services.agent_reload` 调用 `client.call("admin.reload")`（`services/__init__.py:1075-1081`）。
  - 改 agent 代码后的正常流程：重新 `install_mod` 复制到 `~/.starforge/agent/`，再调用热重载；
    修改已有端点逻辑已实测（2026-11-21 日志 `Removed 12 endpoints` → `Finished reloading`），
    修改端点集合后以 `/hello` 实际返回为准。

### 5.4 build 指纹与写闸门（`live/build.py`）

- `fingerprint` 读 `NMS.exe` 的 sha256、size、mtime、PE FileVersion（`:54-80`）。
- 地址书：
  - 随包：`starforge/live/builds/*.json`（当前只有 `185034.json`）。
  - 用户：`~/.starforge/builds/*.json`。
- `summary`：只有 `status == "verified"` 才 `write_allowed=True`；未知/未验证 build 只允许只读（`:230-255`）。
- 当前 `185034.json`：`status: "unverified"`，`signatures: {}`、`offsets: {}`，所以默认只读。
- `services.live_capabilities` 把 hello 能力、build 闸门、多人闸门合并成 UI 能力表；未验证 build 下高风险能力会被 `blocked_by: "build"` 关闭（`services/__init__.py:914-980`）。
- `allow_unverified_agent` 只对 `_EXPERIMENTAL_WRITE_CAPABILITIES`（`teleport/restore/scan.instant/teleport.portal`）放行，`scan.discover` 仍关闭；多人模式始终关闭（`:25-32`、`:960-976`）。

### 5.5 当前状态（2026-11-22 复核）

- 内存通道：Windows only（`live/mem.py:20`、`:174-180`）；`live probe` 只读诊断；
  `live push` 现在统一走 `Services.live_push` → `require_live_write()`（`write_enabled` + `confirm`），
  CLI/UI/Web 都走同一入口（`services/__init__.py:1135-1174`）。
- agent 通道：Windows only；`attach=True` 默认拒绝，`attach=False` + `start_paused=True` 是代码路径。
- 本机 build 185034 已实测：只读端点、`/multitool`、`/freighter`、`/pets`、
  `prepare_warp` 传送、`restore`、热重载；build 地址书仍为 `unverified`，所以**默认仍只读**。
- “实机可用”不等于“地址书已验证”：`services.warp_portal()` 默认仍返回
  `E_BUILD_UNVERIFIED`，只有显式打开 `allow_unverified_agent` 才放行实验写。
- 未验证：`full` 档、跨银河传送、打包态热重载、多人 `true` 分支的完整行为。

---

## 6. 已知架构债务清单（按优先级）

### P0：安全/数据完整性

#### D1. 三类“写”的闸门仍不统一（部分已修，待合并）

- **已修（2026-11-21）**：模板槽 8 字节写入统一走 `Services.live_push` →
  `require_live_write()` = `settings.require_write()` + `confirm`；
  CLI 需 `--yes`，UI 有二次确认，Web 走同一服务（`services/__init__.py:1135-1174`；
  `app/widgets/game_push.py:91-117`；`__main__.py:176-239`）。
- **仍不一致**：
  - 存档写：`write_enabled` + `confirm` + 备份/读回/回滚（`save/writer.py`）。
  - agent 高风险写（`teleport`/`teleport.portal`/`restore`/`scan.instant`）：服务层只查
    build / `allow_unverified_agent` / 多人，没有 `write_enabled` 和 `confirm` 参数
    （`services/__init__.py:1025-1073`）；确认由 UI 调用方弹窗（`game_link.py:1127-1154`、
    `galaxy.py:1381-1435`、`pets_view.py:519-566`），直接调服务/脚本可绕过。
  - 一键安装模板 Mod：只有 `confirm=True`，写的是 `<游戏目录>/GAMEDATA/MODS`，
    不检查 `write_enabled`（`services/__init__.py:1262-1289`）。
  - 游戏内页仍用 `_build_verified` 拦实验写，星图/同伴页却走服务层可放行；
    `allow_unverified_agent` 的 UI 效果不一致（`game_link.py:401-485`、`:1127-1154`）。
- **影响**：用户看到“同一个开关/同一个按钮”，实际约束不同；服务层不是统一安全边界。
- **待合并**：以 `live_capabilities` 的 `experimental/unverified_allowed/blocked_by` 为唯一依据；
  给 agent 写补 `confirm` 参数与统一审计（`history._record` 只是最近活动，不是不可篡改审计）。

#### D2. Web 路由复制并绕过了 Services 编排

- **证据**：
  - 模块级 `from ..save import library`（`web/routes.py:20`）；函数内 `from ..save import writer`（`:177`、`:198`、`:390`）；`from ..live import …`（`:716`、`:723`、`:733`、`:746`）。
  - `/api/search`、`/api/system/scan`、`/api/galaxy/scan` 各自 `jobs.REGISTRY.create` + `run_in_thread`（`:218-234`、`:476-504`、`:507-538`），与 `Services.start_*` 重复。
  - `/api/saves/apply` 直接 `writer.apply_seed`（`:173-186`），绕过 `Services.apply_seed` 的历史记录与统一错误包装。
- **影响**：
  - 行为分叉：一边加了 build 闸门/审计/脱敏，另一边可能没有。
  - 维护成本：同一功能改两处；测试容易只覆盖一边。
  - 安全边界：Web 的 live push 没有 build 闸门，Services 的 agent_call 有；两者语义不一致。

#### D3. 进程隔离只覆盖 unicorn，内存通道和存档写仍在主进程

- **证据**：
  - `_internal` 只处理 `system/locate/system-scan/galaxy-scan`（`services/__init__.py:107-146`、`__main__.py:452-511`）。
  - `live_probe` / `live_push` 直接 `mem.attach` + `writer`（`services/__init__.py:1109-1127`）。
  - `save.writer` / `save.transaction` 在调用线程执行；UI 只是用 `QThreadPool`（`widgets/worker.py:54-71`）。
- **影响**：Unicorn 崩溃被隔离了，但 ctypes 内存读写、numpy/3D、存档编码仍在主进程；一次原生访问冲突仍可能带走整个窗口。`QThreadPool` 只解决“不卡 UI”，不解决“崩进程”。

### P1：可维护性/一致性

#### D4. 能力/闸门定义分散在 4 处，容易漂移

- **证据**：
  - `services/__init__.py:21-28` `_HIGH_RISK_CAPABILITIES` / `_EXPERIMENTAL_WRITE_CAPABILITIES`；`:936-950` 能力表；`:953-969` build/多人闸门。
  - `live/build.py:24-26` `HIGH_RISK_CAPABILITIES`。
  - `__main__.py:275-289` CLI `_AGENT_CAPABILITIES`（`player.ua`、`ship.write_seed` 等另一套名字）。
  - `agent/starforge_agent.py:503-510` hello 返回的 capabilities（`teleport`、`scan.discover` 等）。
- **影响**：新增一个能力要改 4 个地方；名字/风险等级/默认值可能不一致；测试只覆盖其中一部分（`test_agent_gating.py`、`test_agent_portal_gate.py` 等）。

#### D5. 存档写入有三套实现

- **证据**：
  - `save/writer.py:118-191` `apply_seed`。
  - `save/writer.py:194-266` `apply_class`。
  - `save/transaction.py:40-104` `transact_save`。
  - `save/writer.py:292-314` `restore` 又是独立流程。
- **影响**：备份、原子写、回读、回滚、copy 路径、缓存清理的细节容易只修一处；`apply_*` 与 `transact_save` 对 confirm 的责任边界也不同（前者内部检查 `confirm`，后者不检查）。`test_writer_copy_paths.py` 已经暴露过 `.edited.hg` 自己复制自己的历史问题。

#### D6. `JobRegistry` 是进程内、无持久化、锁不完整

- **证据**：`jobs.py:66-88` 的 `create/get/all`；`Job.finish`（`:51-55`）直接改 `status/finished`，没有 `_lock`；`get`/`all` 也不加锁；Flask `serve` 是 `threaded=True`（`__main__.py:67`）。
- **影响**：多线程下读到半更新状态；重启后任务丢失；Web 与 UI 不能共享任务（虽然通常同一个进程）；没有“同一任务只跑一次”的去重。

#### D7. `Services` 是 1460 行上帝门面

- **证据**：`services/__init__.py:102` 一个类，78 个 `def`，覆盖设置/目录/搜索/存档/预览/星系/生物/agent/诊断；模块级只 import core，领域依赖全部藏在方法内。
- **影响**：单文件承担所有用例；任何功能都要改这里；无法按领域独立测试/复用；代码审查看不到真实依赖图；与旧文档“拆成 application/ 多个模块”的目标正好相反。

#### D8. 页面巨大且直接连服务/领域

- **证据**：`galaxy.py 1504`、`ship_lab.py 1221`、`game_link.py 1149`、`fleet.py 912`、`ship_designer.py 900`；每个页面自己 `get_services()`、自己 `run_worker`、自己轮询；`game_push.py` 直接 `live.exml`。
- **影响**：页面难单测；状态重复；跨页共享（收藏、任务、健康）没有统一来源；`AppContext` 形同虚设。

### P2：体验/工程化

#### D9. `AppContext` 只完成了一小半

- **证据**：`app/context.py:12-47` 有 5 个信号；`shell.py:62` 创建，`:74` 连接导航，`:405` 发布健康，`:447` 发布任务；页面没有接收 context，也没有订阅 `healthChanged/jobChanged/agentChanged`。
- **影响**：旧文档宣称的“页面只依赖 context、不自己 new 服务”没有落地；健康/任务变化仍靠页面轮询或 shell 直接调用。

#### D10. 缓存失效点分散

- **证据**：`save/library.py:27-36` 模块级 `_SHIPS_CACHE`；`preview.py:33-47` 磁盘 glb；`live/writer.py:65-80` / `:188-221` 直接挂在 `Process` 对象上的属性；`galaxy.py` SQLite；`warm.py` 进程内状态。
- **影响**：stale 数据排查需要同时看 5 个地方；`Process` 属性缓存随对象生命周期，重新 attach 后失效但调用方不一定知道；测试里共享 `Process` 可能串缓存（现有测试用 `fresh=True` 或新 FakeProcess 规避）。

#### D11. agent 固定端口 + token 查询参数 + attach 限制

- **证据**：`agent_install.py:591-642` 固定 5000/占用检测；`agent_client.py:92-98` token 走 query；`agent_install.py:598-610` 默认拒绝 attach 已运行游戏。
- **影响**：端口冲突只能报错；token 可能进本机 URL/代理日志；用户若已经开了游戏，必须用“由应用启动游戏”的路径，体验受限。当前 build 下 attach 崩溃是实测结论（代码注释），不是架构选择。

#### D12. 文档与代码漂移

- **证据（2026-11-18 旧文档）**：旧 `ARCHITECTURE.md:19` 说 services 565 行、`:32` 说 `web/routes.py` 782 行；实际当前为 1460/749（审计时旧文写的是 1393/765）。旧文档目标目录 `application/`、`ui/` 不存在（`Test-Path` 为 false）；旧索引曾把 `AGENT-PROTOCOL.md`（命名管道）列为 agent 协议，而当前代码是 pymhf HTTP，没有命名管道实现（全仓库没有 pipe 代码，只有 `tempfile.NamedTemporaryFile`）。
- **已处置（2026-11-21）**：旧文档全部移入 `archive/`（带日期），`docs/README.md` 重写为唯一索引；`starforge agent hello` 的回报提示改指 `docs/AGENT.md` 第 8 节。剩余风险是归档文件仍可能被外部引用。
- **影响**：新人按旧文档找目录/协议会走错；评审依据失真。

#### D13. CI 只做发布，不做测试/静态检查

- **证据**：`.github/workflows/release.yml` 只有 tag 触发的构建；没有 `pytest`/`ruff` job。`scripts/selfcheck_release.py` 检查版本/文件/文档/遗留依赖，但不跑测试（`:343-352`）。
- **影响**：回归只能靠本地；发布前“全绿”没有强制门禁；本次本地 `ruff --select F` 通过、`pytest --collect-only` 476 项，但这依赖人工执行。

#### D14. 打包配置有三份事实来源

- **证据**：`pyproject.toml:20-24` 的 `packages` / `package-data`；`.github/workflows/release.yml:86-113` 的 PyInstaller `--add-data`/`--collect-*`；`packaging/build_agent_runtime.py:26-29` 与 `live/agent_install.py:76-81` 的 runtime 版本清单。
- **影响**：新增子包/资源时容易只改一处；`package-data` 只覆盖 `starforge.live` 的 builds/assets，`starforge/agent`、根 `assets` 依赖 PyInstaller 参数；agent runtime 版本由测试 `test_agent_runtime.py` 校验，但主包资源没有同等校验。

---

## 7. 与旧文档的差异说明

| 旧文档结论 | 当前代码事实 | 证据 |
|---|---|---|
| 有 `application/` 应用层、`ui/` UI 层 | 不存在；实际是 `services/` + `app/` | `Test-Path starforge/application` / `starforge/ui` 均为 false；`services/__init__.py:102`；`app/` 目录 |
| 有 `desktop.py` 旧 pywebview 外壳 | 不存在；旧外壳已移除 | 无 `starforge/desktop.py`；`__main__.py:33-39` 明确 `--browser` 已移除 |
| `services/__init__.py` 565 行 | 1460 行，78 个方法 | 当前文件统计；`services/__init__.py:102` |
| `web/routes.py` 782 行 | 749 行、44 条路由 | 当前文件统计；路由装饰器计数 |
| `live/agent_install.py` 401 行 | 738 行 | 当前文件统计 |
| 页面是 `app/pages/live.py`、`search.py` | 实际是 `game_link.py`、`ship_lab.py`，另有 `ship_designer.py` | `shell.py:109-117` |
| “web 只调用 application，不再自己写业务逻辑” | web 直接 import save/live/jobs/search/system/galaxy 并自行编排 | `web/routes.py:20`、`:173-186`、`:218-234`、`:476-538`、`:714-765` |
| “页面只接收 AppContext，不自己 new 服务” | 页面直接 `get_services()`；AppContext 只在 shell 少量使用 | `pages/*.py` 的 `get_services`；`shell.py:62`、`:405`、`:447` |
| “统一 JobService，可全局查看/取消/恢复” | 只有进程内 `JobRegistry`，无持久化/恢复；UI 轮询 | `jobs.py:66-88`；`job_dock.py:253-261` |
| “agent 是进程内 DLL / 命名管道协议” | 实际是 pymhf + NMSpy 的 Python Mod，HTTP + token 查询参数；没有命名管道实现 | `agent/starforge_agent.py:1-18`、`:478-510`；旧协议文档已归档 |
| “未知 build 只读” | 代码确实如此，但当前 `185034.json` 是 `unverified`，所以默认只读 | `live/build.py:230-255`；`live/builds/185034.json` |
| “Python 3.10+” | `pyproject` 写 `>=3.10`；CI/runtime 实际是 3.11.9；3.10 未在 CI 验证 | `pyproject.toml:5`；`build_agent_runtime.py:26` |

结论：旧 `ARCHITECTURE.md` 更像“重构目标方案”，不是“现状说明”；旧 `docs/README.md` 里的 agent 协议描述也落后于代码。新代码评审请以本文件和 `DEV-GUIDE.md` 为准。

---

## 8. 未验证与边界

- **已实测（2026-11-21～22，build 185034）**：只读端点、`/multitool`、`/freighter`、`/pets`、
  `prepare_warp` 传送、`restore`、模板槽外部读写、热重载修改已有端点。细节见
  `docs/AGENT-INJECT-CRASH.md` 与 `docs/LESSONS.md`。
- **未验证**：`teleport/portal` 的 `full` 档、跨银河传送、新增端点后的热重载稳定性、
  打包态热重载、多人 `true` 分支的完整行为。
- **未验证**：本轮没有运行 PyInstaller/release workflow，打包产物结构、体积、agent runtime
  裁剪结果来自 `.github/workflows/release.yml` 与 `packaging/` 脚本，不是本机实测。
- **未验证**：`requires-python >=3.10` 只在 3.11.9 上验证；3.10 的兼容性没有 CI 依据。
- 上游 `nms_save` / `nms_procgen` 的具体实现不在本仓库；本文只描述本项目如何调用它们。
- 旧文档中凡与本文件冲突的结论，以本文件引用的代码位置为准。
