# 文档

| 文件 | 内容 |
|---|---|
| [USAGE.md](USAGE.md) | **逐屏使用指南**：安装 → 搜船 → 我的船 → 写回 → 星球 → 送进游戏 → 排障 |
| [VERIFY-WINDOWS.md](VERIFY-WINDOWS.md) | Windows 真机验收清单（A–E 分段，含通过标准与常见报错） |
| [MANUAL.md](MANUAL.md) | **软件手册**：产品定位、13 项功能、五页界面线框、符文浮窗规范、接口、运维、验收、里程碑 |
| [DESIGN.md](DESIGN.md) | 设计方案：架构与进程模型、七个关键决策（含实测数据）、API 契约、性能预算、风险登记 |
| [CAPABILITIES.md](CAPABILITIES.md) | 能力清单与实机效果：每项功能的判定（可用 / 需实现 / 需游戏内）与真实跑出的结果 |
| [FEATURE-MAP.md](FEATURE-MAP.md) | **功能地图**：界面 → 服务 → 后端状态，标出已接/占位/待实现 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | **架构研究与重构方案**：分层、AppContext、任务模型、Strangler 迁移、测试与打包 |
| [UI-REDESIGN.md](UI-REDESIGN.md) | **界面重构设计**：Command Deck 布局、设计令牌、组件库、六个页面与迁移计划 |
| [PLAN-V4.md](PLAN-V4.md) | **全功能路线图**：离线 / 存档 / 外部实时 / 进程内 agent 四条线，M0–M8 阶段与 Windows 实测轮次 |
| [AGENT.md](AGENT.md) | **agent 是什么**：为什么传送/扫描必须在进程内、DLL 代理如何工作、build 绑定与安全边界 |
| [AGENT-PROTOCOL.md](AGENT-PROTOCOL.md) | agent 命名管道协议 v1：帧格式、命令表、错误码、能力协商 |

## 快速事实

* **实测性能**（4 核开发机）：系统生成 0.039 s/系统；单船 3D 0.4–1.2 s（热）；搜索 13–20 M seeds/s。
* **传送门符文 = 系统地址的 12 位十六进制**；图标在 `NMSARC.TexUI.pak` 的 `textures/ui/frontend/icons/update3/portalsymbol.<0-f>.dds`（BC7）。
* **默认不做**：注入改游戏代码、跨型移植外观、改玩家资产、多人写入。
* **可选 agent**：进程内 DLL 才能做游戏内传送/扫描/建造；按 build 指纹绑定，默认不安装、可完整卸载。
