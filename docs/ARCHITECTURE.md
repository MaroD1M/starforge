# Starforge 架构研究与重构方案

> 本文是“完整研究 → 规划 → 设计 → 重构”的工程基线。
> 目标不是修一个页面，而是把项目从“能跑的脚本集合”整理成可长期维护的桌面应用。

---

## 1. 现状研究

### 1.1 分层现状

```
starforge/
├── core/        路径、设置、日志、错误、锁、文案        —— 稳定
├── data/        catalog/icons/gshi/shipref              —— 只读领域数据
├── save/        存档读写（Shipwright 封装）              —— 稳定，需原子写
├── live/        内存扫描/模板槽/agent 客户端/安装器       —— 与平台强耦合
├── agent/       pymhf 游戏内 Mod                         —— 独立运行时
├── services/    应用用例门面                             —— 目前是“上帝对象”
├── app/         PySide6 界面                             —— 页面直接调 services
├── web/         旧 Flask API（兼容/调试）                —— 与 services 有重复逻辑
├── desktop.py   旧 pywebview 外壳                        —— 历史包袱
└── __main__.py  CLI + 命令分发                           —— 入口过多
```

### 1.2 主要问题

| 问题 | 证据 | 影响 |
|---|---|---|
| `services/__init__.py` 565 行、方法过多 | 搜索/预览/存档/星系/agent/设置全在一个类 | 难测试、难复用、改一处牵全身 |
| 页面直接调 services，且各自持有状态 | `SearchPage`/`MinePage`/`SystemsPage` | 页面难复用，跨页状态不同步 |
| web 路由与 services 两套编排 | `web/routes.py` 782 行 | 行为可能分叉 |
| 旧 web/pywebview 仍参与打包 | `desktop.py`、`webview/pythonnet` | 体积、崩溃面、误导 |
| 任务模型分散 | `jobs.py` + 页面自轮询 | 无法全局查看/取消/恢复 |
| 3D/缩略图/agent 依赖导入时机不稳 | NumPy/PySide6 在启动期导入 | 单点 DLL 问题导致整包无法启动 |
| 错误语义不统一 | 领域异常、字符串、UI 文本混用 | 用户看到 Python traceback |

### 1.3 代码体量（重构前）

| 文件 | 行数 |
|---|---:|
| `web/routes.py` | 782 |
| `services/__init__.py` | 565 |
| `live/agent_install.py` | 401 |
| `app/pages/live.py` | 393 |
| `agent/starforge_agent.py` | 345 |
| `app/pages/search.py` | 280 |

---

## 2. 目标架构

### 2.1 分层与依赖方向

```
┌──────────────────────────────────────────────────────┐
│ ui/            PySide6 页面、组件、控制器              │
│  只能依赖 application，不得直接 import nms_* / ctypes │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│ application/   用例编排、任务、状态、错误映射         │
│  search / preview / saves / galaxy / game_link / jobs │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│ domain/        core / data / save / live / agent      │
│  纯逻辑、平台封装、无 UI/HTTP 依赖                     │
└──────────────────────────────────────────────────────┘
```

**硬规则**：

1. UI 不直接 import `nms_save` / `nms_procgen` / `ctypes` / `pymhf`。
2. application 不 import Qt / Flask。
3. domain 不 import application / ui / web。
4. web 只调用 application，不再自己写业务逻辑。

### 2.2 目标目录

```
starforge/
  application/
    __init__.py          # AppServices 聚合（兼容旧 get_services）
    search.py
    preview.py
    saves.py
    galaxy.py
    creatures.py
    game_link.py
    settings.py
    jobs.py
    diagnostics.py
  ui/
    app.py               # QApplication 引导
    context.py           # AppContext：services + 全局状态 + Qt 信号
    theme/
      tokens.py          # 颜色/间距/字体
      qss.py             # QSS
    shell/
      main_window.py
      command_bar.py
      nav_rail.py
      job_dock.py
      command_palette.py
    pages/
      home.py
      ship_lab.py
      fleet.py
      galaxy.py
      game_link.py
      settings.py
    components/
      ship_card.py
      part_tree.py
      ship_viewer.py
      planet_card.py
      glyph_bar.py
      agent_steps.py
      toast.py
  domain/  (保留现有 core/data/save/live/agent，逐步迁移)
  web/     (兼容层，最终降级为可选)
```

### 2.3 AppContext 与状态流

```python
class AppContext(QObject):
    healthChanged = Signal(dict)
    jobChanged = Signal(dict)
    agentChanged = Signal(dict)
    navigateRequested = Signal(str)

    def __init__(self):
        self.services = AppServices()
        self.health = {}
        self.agent = {}
```

- 页面只接收 `AppContext`，不自己 new 服务。
- 健康/agent/任务变化通过信号广播，页面不做轮询。
- 导航由 `navigateRequested` 统一控制。

### 2.4 任务模型

统一 `JobService`：

- `submit(kind, fn, meta)`；
- `progress` / `cancel` / `result` / `error`；
- 全局 `JobDock` 展示；
- UI 离开页面不取消任务；
- 写操作必须带 `snapshot`/`backup` 元数据。

---

## 3. 重构策略（Strangler Pattern）

不一次性删除旧代码，按“先包一层、再替换、最后删除”：

| 步骤 | 动作 | 风险 |
|---|---|---|
| R1 | 新建 `application/`，把 `services/__init__.py` 按模块拆开，旧 `get_services()` 委托 | 低 |
| R2 | 新建 `ui/context.py`，页面改为接收 context | 中 |
| R3 | 新 Shell（Command Deck）+ Home + JobDock + CommandPalette | 中 |
| R4 | Ship Lab / Fleet / Galaxy / Game Link 逐页迁移 | 中 |
| R5 | web 路由改为调用 application；删除重复逻辑 | 中 |
| R6 | 旧 `desktop.py`/webview 降级为可选，最终移除 | 高（需确认） |
| R7 | 打包瘦身、启动预检、错误页、诊断包 | 低 |

---

## 4. 关键设计决策

### 4.1 错误模型

- domain 抛类型化异常（`SaveFormatError`/`GameFilesMissing`/`AgentError`）；
- application 统一映射为 `{kind, message, hint, retryable}`；
- UI 只显示“原因 + 下一步”，不显示 traceback；
- 诊断日志保留完整栈。

### 4.2 线程与生命周期

- CPU 密集：`ProcessPoolExecutor` / 现有 multiprocessing；
- IO/预览：`QThreadPool`；
- UI 线程只做渲染；
- 关闭窗口：等待/取消任务，写操作必须完成或回滚；
- agent 注入：独立子进程，退出不杀游戏。

### 4.3 版本适配

- 外部内存：AOB + 结构校验 + 多候选拒绝；
- 游戏内：NMSpy 按 build 选择，地址书只做诊断/回退；
- 未知 build：只读或拒绝写；
- 所有能力表由 agent `hello` 返回，UI 不 hardcode。

### 4.4 打包

- PyInstaller onedir；
- 主进程只带运行必需依赖；
- agent 运行时独立目录（Python embeddable + NMSpy + pymhf）；
- 不在 `_internal` 放重复 agent runtime；
- 启动预检：NumPy/PySide6/运行时/游戏路径；
- 失败时给可复制诊断，不直接崩。

---

## 5. 测试策略

| 层 | 测试 |
|---|---|
| domain | 现有 243 项 pytest 全保留 |
| application | 每个 service 的契约测试（输入/输出/错误） |
| ui | pytest-qt 冒烟 + 关键页面截图 |
| agent | 假 HTTP 服务契约测试；Windows 实机轮次 |
| packaging | 干净 Windows 机器 + `doctor` + 启动冒烟 |

---

## 6. 里程碑

| 阶段 | 内容 | 完成标准 |
|---|---|---|
| **A 基础** | application 拆分、AppContext、错误模型 | 旧 API 不变，测试全绿 |
| **B Shell** | Command Deck、Home、JobDock、CommandPalette | 空壳可跑，截图确认 |
| **C 页面** | Ship Lab / Fleet / Galaxy / Game Link 迁移 | 全流程可操作 |
| **D 清理** | web/desktop 降级、打包瘦身、诊断包 | 安装包更小，启动更稳 |
| **E 发布** | 单一 beta 包 + Windows 实测 | 用户验收 |

**发布纪律**：A–D 全部本地通过后才打一个包；不再为单个修复发版。
