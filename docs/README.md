# 文档

| 文件 | 内容 |
|---|---|
| [FEATURE-MAP.md](FEATURE-MAP.md) | **功能地图**：界面 → 服务 → 后端状态，标出已接/占位/待实现 |
| [GAP-ANALYSIS.md](GAP-ANALYSIS.md) | **差距分析**：30 个缺口、功能矩阵、P0–P3 路线、包体/agent/UI 专项 |
| [COMMUNITY-UI-ROADMAP.md](COMMUNITY-UI-ROADMAP.md) | **社区 UI/UX 研究**：坐标/符文、存档、搜索筛选、NMS 氛围层与实施阶段 |
| [PACKAGING.md](PACKAGING.md) | **打包与体积**：131MB 构成、削减项、体积报告与目标 |
| [INGAME-SCAN-FEASIBILITY.md](INGAME-SCAN-FEASIBILITY.md) | **游戏内扫描可行性**：矿物/动植物/POI/传送门的字段、函数与实机边界 |
| [UI-TERMS.md](UI-TERMS.md) | **界面术语表**：中文/英文/使用场景，避免中英混用 |
| [SAVE-API-INVENTORY.md](SAVE-API-INVENTORY.md) | **存档 API 盘点**：读写能力、风险分级、写事务缺口与接入顺序 |
| [CREATURE-MODELING.md](CREATURE-MODELING.md) | **同伴/生物建模研究**：数据链、社区项目、3D 预览路线与边界 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | **架构研究与重构方案**：分层、AppContext、任务模型、Strangler 迁移、测试与打包 |
| [UI-REDESIGN.md](UI-REDESIGN.md) | **界面重构设计**：Command Deck 布局、设计令牌、组件库、六个页面与迁移计划 |
| [CLEANUP-AUDIT.md](CLEANUP-AUDIT.md) | **过时资源清理审计**：旧 Web/desktop/文档/依赖盘点与安全删除顺序 |
| [PLAN-V4.md](PLAN-V4.md) | **全功能路线图**：离线 / 存档 / 外部实时 / 进程内 agent 四条线，M0–M8 阶段与 Windows 实测轮次 |
| [AGENT.md](AGENT.md) | **agent 是什么**：为什么传送/扫描必须在进程内、DLL 代理如何工作、build 绑定与安全边界 |
| [AGENT-PROTOCOL.md](AGENT-PROTOCOL.md) | agent 命名管道协议 v1：帧格式、命令表、错误码、能力协商 |

## 历史参考

以下文档描述旧网页/旧版本，保留用于追溯；当前实现以 ARCHITECTURE / UI-REDESIGN / FEATURE-MAP / GAP-ANALYSIS / PLAN-V4 为准。

| 文件 | 内容 |
|---|---|
| [USAGE.md](USAGE.md) | 旧逐屏使用指南（待按 7 页原生界面重写） |
| [MANUAL.md](MANUAL.md) | 旧 nmshunter 软件手册 |
| [DESIGN.md](DESIGN.md) | 旧网页架构设计 |
| [CAPABILITIES.md](CAPABILITIES.md) | 旧能力快照 |
| [VERIFY-WINDOWS.md](VERIFY-WINDOWS.md) | 旧 Windows 验收单 |
| [VERIFY-AGENT-WINDOWS.md](VERIFY-AGENT-WINDOWS.md) | agent 验收单（需按 pymhf 更新） |
| [archive/PLAN-V2.md](archive/PLAN-V2.md) | 已归档的旧方案 |
| [archive/PLAN-V3.md](archive/PLAN-V3.md) | 已归档的旧方案 |

## 发布前自检

发布前在仓库根目录运行（纯 stdlib，只读；详细清单见 [PACKAGING.md](PACKAGING.md#8-发布前自检selfcheck_releasepy)）：

```bash
python3 scripts/selfcheck_release.py
python3 scripts/selfcheck_release.py --json
python3 scripts/selfcheck_release.py --fail-on error
```

它检查版本号/CHANGELOG/tag、必需文件、文档相对链接、已移除依赖和 TODO 统计；
默认发现 `error` 时退出码为 1。`--json` 输出适合 CI 或发布脚本消费。

## 快速事实

* **实测性能**（4 核开发机）：系统生成 0.039 s/系统；单船 3D 0.4–1.2 s（热）；搜索 13–20 M seeds/s。
* **传送门符文 = 系统地址的 12 位十六进制**；图标在 `NMSARC.TexUI.pak` 的 `textures/ui/frontend/icons/update3/portalsymbol.<0-f>.dds`（BC7）。
* **默认不做**：注入改游戏代码、跨型移植外观、改玩家资产、多人写入。
* **可选 agent**：进程内 DLL 才能做游戏内传送/扫描/建造；按 build 指纹绑定，默认不安装、可完整卸载。
