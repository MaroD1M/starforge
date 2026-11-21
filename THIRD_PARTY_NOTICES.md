# 第三方组件与许可

starforge 自身以 **MIT** 发布。发布的 Windows 包内还包含下列第三方组件，各自保留其许可：

| 组件 | 许可 | 用途 | 是否随包分发 |
|---|---|---|---|
| [NMS-Shipwright](https://github.com/S-T-0-7/NMS-Shipwright) | MIT（© 2026 Shikhar Tiwari） | 存档读写、种子生成、几何/涂装、系统生成 | ✅ 以 vendor 形式打包（`nms_save/`、`nms_procgen/`、`data/mapping.json`），许可全文见包内 `THIRD_PARTY_SHIPWRIGHT_LICENSE.txt` |
| [Gagarin_Titov](https://github.com/autoeme/Gagarin_Titov) | 数据文件随游戏分发；字体 SIL OFL 1.1 | 部件目录 `catalog.txt`、缩略图 `icons.bin` | ❌ 不含；由用户本地游戏目录读取 |
| [NMS-Super-Ship-Hunter](https://github.com/beihaixingchen/NMS-Super-Ship-Hunter) | MIT | "模板槽 + 外部写"思路；兼容其两个模板槽的种子常量 | ❌ 不含代码，仅按公开数据做兼容 |
| numpy | BSD-3-Clause | 数值计算 | ✅ 打包 |
| Flask / Werkzeug / Jinja2 | BSD-3-Clause | 可选 JSON API 调试 | ✅ 打包（仅 API，不含静态网页） |
| lz4 | BSD-2-Clause | 存档 LZ4 block | ✅ 打包 |
| texture2ddecoder | MIT | BC1–BC7 贴图解码 | ✅ 打包 |
| hgpaktool | MIT | pak 解包（子进程） | ✅ 打包 |
| **unicorn** | **GPL-2.0** | 用 unicorn 引擎执行 `NMS.exe` 的星系生成器（`nms_procgen/systemgen.py`） | ✅ 打包（**见下方 GPL 说明**） |

> 本仓库**不包含**任何游戏原始文件（pak / MBIN / 贴图 / 存档），也不包含上述上游的源码副本；
> vendor 只在 CI 构建时进行，产物带许可说明，源码仓库保持干净。

## GPL 合规说明（unicorn）

`unicorn` 采用 **GPL-2.0**，而本项目的发布产物是"把 unicorn 与 starforge 一起打进同一个
PyInstaller 目录"的形式。这不是一句"依赖各不相同"就能打发的：GPL 的传染性取决于"是否构成
单一作品"。目前的口径与可选方案如下（**未做最终决定，交接时必须重新评估**）：

| 方案 | 做法 | 代价 |
|---|---|---|
| A 现状（打包在一起） | 继续随包分发，同时提供完整对应源码 + GPL 全文 + 构建脚本 | 需要对外明确"产物含 GPL 组件"，发布页与包内都要声明；主机版分发要一并提供源码 |
| B 运行期可选 | 只把 unicorn 作为"可选依赖"，首次用到星系生成时才下载/安装到用户目录 | 包体变小、许可边界清晰；代价是离线用户首次需联网，Windows 新手体验变差 |
| C 替换引擎 | 换 Unicorn 之外的 x86-64 模拟器（需非 GPL）或自己做子集解释器 | 工期大，`systemgen` 依赖 unicorn 的 hook/内存 API 较深 |
| D 拆分进程 | 把 `systemgen` 做成独立小工具（单独 GPL 发布），主程序通过子进程调用 | 边界干净、可分开发布；需要改打包与调用方式 |

**当前建议**：短期按 A 执行（发布页 + 包内都声明 GPL 组件并提供源码链接），中期评估 D
（进程隔离最干净，且与 agent 独立进程的方向一致）。
