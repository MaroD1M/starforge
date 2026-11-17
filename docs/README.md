# 文档

| 文件 | 内容 |
|---|---|
| [USAGE.md](USAGE.md) | **逐屏使用指南**：安装 → 搜船 → 我的船 → 写回 → 星球 → 送进游戏 → 排障 |
| [VERIFY-WINDOWS.md](VERIFY-WINDOWS.md) | Windows 真机验收清单（A–E 分段，含通过标准与常见报错） |
| [MANUAL.md](MANUAL.md) | **软件手册**：产品定位、13 项功能、五页界面线框、符文浮窗规范、接口、运维、验收、里程碑 |
| [DESIGN.md](DESIGN.md) | 设计方案：架构与进程模型、七个关键决策（含实测数据）、API 契约、性能预算、风险登记 |
| [CAPABILITIES.md](CAPABILITIES.md) | 能力清单与实机效果：每项功能的判定（可用 / 需实现 / 需游戏内）与真实跑出的结果 |

## 快速事实

* **实测性能**（4 核开发机）：系统生成 0.039 s/系统；单船 3D 0.4–1.2 s（热）；搜索 13–20 M seeds/s。
* **传送门符文 = 系统地址的 12 位十六进制**；图标在 `NMSARC.TexUI.pak` 的 `textures/ui/frontend/icons/update3/portalsymbol.<0-f>.dds`（BC7）。
* **不做**：注入改游戏代码（默认）、跨型移植外观、改玩家资产、多人写入。
