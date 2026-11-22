# Starforge 文档索引

> **唯一入口。** 文档按「用户 / 开发 / 实验记录 / 研究 / 归档」分组，canonical 文件名不带版本后缀。
> 事实以代码为准：`starforge/`、`tests/`、`scripts/`、`pyproject.toml`、`.github/workflows/` 与任何文字冲突时，以代码为准并回来改文档。
> 最后核对：2026-11-22，工作区版本 **0.15.0**（`starforge/__init__.py`、`pyproject.toml`）。

## 用户

| 文档 | 一句话 | 最后核对 |
|---|---|---|
| [MANUAL.md](MANUAL.md) | 用户手册：安装、4 个工作区（旧 7 页兼容）、CLI、存档写入与备份/回滚、模板 Mod 一键安装、传送到星球、实时资产 | 2026-11-22 / 0.15.0 |

## 开发

| 文档 | 一句话 | 最后核对 |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | as-built 架构：目录职责、调用链、体量、依赖违规与技术债（不是重构提案） | 2026-11-22 / 0.15.0 |
| [UX-DESIGN.md](UX-DESIGN.md) | 界面规范：一屏一任务、结果优先、渐进披露、组件（TaskFlow/FilterChips/FilterPanel）、审计清单与开源参考 | 2026-11-22 / 0.15.0 |
| [AGENT.md](AGENT.md) | 游戏内通道：pymhf Python Mod 形态、15 个 HTTP 端点、认证、build 闸门、`SaveToData` 只读解析 | 2026-11-22 / 0.15.0 |
| [LESSONS.md](LESSONS.md) | 经验与踩坑：注入三次崩溃与二分、`/ships` 两套结构、portal 三档、token 三源、热重载、图标、写闸门、文档漂移 | 2026-11-22 / 0.15.0 |
| [DEV-GUIDE.md](DEV-GUIDE.md) | 开发/测试/打包：环境、fixture、约定、PyInstaller 与 vendor、自检、新增页面/端点 | 2026-11-22 / 0.15.0 |
| [PACKAGING.md](PACKAGING.md) | 包体构成与削减：CI 裁剪项、体积报告脚本、发布自检（预算口径已更新为 [SIZE-BUDGET.md](SIZE-BUDGET.md)） | 2026-11-22 / 0.15.0 |
| [SIZE-BUDGET.md](SIZE-BUDGET.md) | 体积预算与实测：基线构成、PyInstaller 排除清单、Inno Setup LZMA2、v0.16 ≤70 MiB / v1.0 ≤55 MiB、零额外下载 | 2026-11-22 / 0.15.0 |
| [ROADMAP-2026-11.md](ROADMAP-2026-11.md) | 全景规划：现状能力、可扩展方向、体积精简、版本兼容、UI/UX 规范、维护与里程碑 | 2026-11-22 / 0.15.0 |

## 实验记录

| 文档 | 一句话 | 最后核对 |
|---|---|---|
| [AGENT-INJECT-CRASH.md](AGENT-INJECT-CRASH.md) | 注入实验记录：结论置顶，下面是 2026-11-18～21 的崩溃 dump、对照实验与写通道实测时间线 | 2026-11-22 |
| [AUDIT-2026-11.md](AUDIT-2026-11.md) | 2026-11 文档审计（一次性）：逐篇结论、错误清单、归档映射与断链风险 | 2026-11-21 |
| [SECURITY-REVIEW-2026-11.md](SECURITY-REVIEW-2026-11.md) | 发布前敏感信息审查：本机路径、存档派生数据、dump/PID、`.gitignore` 与脱敏待办 | 2026-11-22 |

## 研究

| 文档 | 一句话 | 最后核对 |
|---|---|---|
| [research/FEATURE-GAPS.md](research/FEATURE-GAPS.md) | 功能缺口审计（快照）：已实现/只读/占位/缺失清单、UI 断点与修复状态 | 2026-11-22 |
| [research/CREATURE-SEARCH.md](research/CREATURE-SEARCH.md) | 生物建模与“按特征搜索 → 传送”研究：存档字段、上游方案、分阶段落地 | 2026-11-22 |
| [research/OSS-PLANET-SEARCH.md](research/OSS-PLANET-SEARCH.md) | 星球检索开源项目评估：nms-copilot/nms-core/APF 的可借鉴点与不可用项 | 2026-11-22 |
| [research/OSS-SAVE-INDEX.md](research/OSS-SAVE-INDEX.md) | 存档发现索引：3,240 条记录、schema 草案、增量与查询场景 | 2026-11-22 |
| [research/OSS-DATA-PIPELINE.md](research/OSS-DATA-PIPELINE.md) | 数据/模型管线：HGPAKtool/MBINCompiler/nms-archive/NMSDK 的许可与边界 | 2026-11-22 |

## 归档（历史，不代表当前实现）

以下文件描述旧网页版、旧 DLL/命名管道方案或已完成的一次性工作，**只用于追溯**。新文档不要再链接它们。

| 文档 | 原主题 |
|---|---|
| [archive/ARCHITECTURE-2026-11-18.md](archive/ARCHITECTURE-2026-11-18.md) | 旧分层重构方案（`application/` + `ui/`） |
| [archive/AGENT-2026-11-18.md](archive/AGENT-2026-11-18.md) | 旧 agent 概念（winmm DLL 时代） |
| [archive/AGENT-PROTOCOL-2026-11-18.md](archive/AGENT-PROTOCOL-2026-11-18.md) | 命名管道协议草案（未实现） |
| [archive/MANUAL-2026-11-18.md](archive/MANUAL-2026-11-18.md) | 旧 11 卷软件手册（v0.9） |
| [archive/USAGE-2026-11-18.md](archive/USAGE-2026-11-18.md) | 旧逐屏使用指南（已并入 MANUAL） |
| [archive/PLAN-V4-2026-11-18.md](archive/PLAN-V4-2026-11-18.md) | 四线路线图（DLL 时代） |
| [archive/GAP-ANALYSIS-2026-11-18.md](archive/GAP-ANALYSIS-2026-11-18.md) | 2026-11-19 缺口快照 |
| [archive/FEATURE-MAP-2026-11-18.md](archive/FEATURE-MAP-2026-11-18.md) | 旧功能地图（状态已过期） |
| [archive/CAPABILITIES-2026-11-18.md](archive/CAPABILITIES-2026-11-18.md) | 旧能力快照 |
| [archive/UI-REDESIGN-2026-11-18.md](archive/UI-REDESIGN-2026-11-18.md) | Command Deck 设计提案 |
| [archive/COMMUNITY-UI-ROADMAP-2026-11-18.md](archive/COMMUNITY-UI-ROADMAP-2026-11-18.md) | 社区 UI/UX 研究与提案 |
| [archive/UI-TERMS-2026-11-18.md](archive/UI-TERMS-2026-11-18.md) | 中英界面术语表 |
| [archive/DESIGN-2026-11-18.md](archive/DESIGN-2026-11-18.md) | 旧网页产品设计（nmshunter） |
| [archive/SAVE-API-INVENTORY-2026-11-18.md](archive/SAVE-API-INVENTORY-2026-11-18.md) | 存档 API 盘点（现状列已过期） |
| [archive/INGAME-SCAN-FEASIBILITY-2026-11-18.md](archive/INGAME-SCAN-FEASIBILITY-2026-11-18.md) | 游戏内扫描/矿物/POI 可行性 |
| [archive/CREATURE-MODELING-2026-11-18.md](archive/CREATURE-MODELING-2026-11-18.md) | 同伴 3D 建模路线 |
| [archive/VERIFY-WINDOWS-2026-11-18.md](archive/VERIFY-WINDOWS-2026-11-18.md) | v0.9 网页版验收单 |
| [archive/VERIFY-AGENT-WINDOWS-2026-11-18.md](archive/VERIFY-AGENT-WINDOWS-2026-11-18.md) | winmm 代理 DLL 时代验收单 |
| [archive/CLEANUP-AUDIT-2026-11-18.md](archive/CLEANUP-AUDIT-2026-11-18.md) | 旧资源清理审计（已完成） |
| [archive/PLAN-V2.md](archive/PLAN-V2.md) | 更早的已归档方案 |
| [archive/PLAN-V3.md](archive/PLAN-V3.md) | 更早的已归档方案 |

## 发布前自检

```bash
python scripts/selfcheck_release.py --fail-on error
```

它会校验版本号/CHANGELOG/tag、必需文件、本索引的相对链接、已移除依赖与 TODO 统计；
`--json` 便于 CI 消费，`--fail-on warning` 可把告警也当失败。说明见 [DEV-GUIDE.md](DEV-GUIDE.md) §5.6 与 [PACKAGING.md](PACKAGING.md#8-发布前自检selfcheck_releasepy)。
