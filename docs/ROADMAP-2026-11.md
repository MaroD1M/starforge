# starforge 全景规划（2026-11 · v0.15.0）

> 本文是**面向长期维护的产品与技术规划**，不是功能许愿单。
> 所有“现状”以代码与实测为准；每条结论标注来源类型：
> `[代码]` 代码位置、`[实测]` 本机验证、`[发布]` Release 产物、`[规划]` 尚未实现。

---

## 0. 定位与设计原则

**一句话**：本地运行的“无人深空情报台 + 存档工坊”——搜船、看 3D、找星球、写存档、把种子送进游戏领取。

五条原则（后续所有决策都以此为准）：

1. **可视化**：任何能力都要有界面入口，不要求用户记命令行。
2. **易操作**：高频动作 ≤ 3 步；危险动作必须“预览 → 确认 → 可回滚”。
3. **不繁琐**：默认零配置（自动发现游戏/存档/数据），缺东西时给出“下一步”而不是报错堆栈。
4. **易维护**：一个功能 = 一个服务方法 + 一个页面区块 + 一组测试；文档以代码为准。
5. **优先用游戏自身资源**：**不打包任何游戏资产**；运行时从玩家本机 `pak`/`MBIN`/存档/内存读取，
   解析结果本地缓存。这样既不触碰版权，也不会因上游项目无许可而失去能力。

---

## 1. 当前能力现状（v0.15.0）

### 1.1 离线（不启动游戏）

| 能力 | 状态 | 证据 |
|---|---|---|
| 按部件/涂装搜种子（8 船型） | ✅ 13–20 M seeds/s | `[代码] services.search` / `nms_procgen.fastsearch` |
| 真 3D 预览（读本机 pak）+ glb 导出 | ✅ | `[代码] preview.py / gltf.py / render.py` |
| 服务端缩略图（点云 + 光栅） | ✅ | `[代码] render.ship_png` |
| 存档读/写/备份/回滚（同型换种子、改等级/属性、库存/科技） | ✅ 四步铁律 | `[代码] save/writer.py / save/transaction.py` |
| 飞船设计器（任意部件组合 + 校验 + 写入） | ✅ | `[代码] app/pages/ship_designer.py` |
| 星系/行星离线扫描（unicorn 跑 systemgen） | ✅ 实测 25 系统/秒级 | `[代码] galaxy.py / system.py` |
| **已发现星球检索**（群系/虫蚀/命名/距离/CSV） | ✅ v0.15 新增 | `[代码] discoveries.py`；`[实测] 814 行星/831 记录/83 虫蚀` |
| 传送门符文（游戏原图 BC7 解码）+ 置顶浮窗 | ✅ | `[代码] glyphs.py / app/overlay.py` |
| 模板 Mod 生成 + 一键安装 + 表情领取 | ✅ 实测领取成功 | `[代码] live/exml.py`；`[实测] 写种子→领取→存档一致` |
| 蓝图风表情图标（自渲，BC1/DDS） | ✅ | `[代码] live/iconart.py` |
| 诊断：doctor / selftest / selfcheck / webcheck | ✅ | `[代码] __main__.py / selfcheck.py` |

### 1.2 运行中游戏（外部内存，只读优先）

| 能力 | 状态 | 说明 |
|---|---|---|
| 模板槽定位（8 模板，多候选拒绝） | ✅ 实测 8/8，~14–20 s | `live/writer.py` |
| 8 字节种子写入 + 回读 | ✅ | 写前 `write_enabled` + `confirm` |
| 传送（写位置 + 触发加载） | ✅ 机制验证 | `agent /teleport`，快照 + restore |
| portal warp（`prepare_warp`） | ✅ 实测可传送到目标行星 | `agent /teleport/portal` |
| 只读实时状态（玩家/星系/行星/船/工具/货船/同伴） | ✅ 15 个 agent 端点 | `agent/starforge_agent.py` |

### 1.3 已知限制（必须诚实展示）

- 地址书 `builds/185034.json` 仍为 `unverified`：高风险写需显式开启 `allow_unverified_agent`。
- 进程内 agent 依赖 pymhf 注入，**特定场景**会被游戏以“模组冲突”关闭（详见 `AGENT-INJECT-CRASH.md`）。
- 传送落点“持久性”需多次校准；`restore` 目前不读回位置。
- 生物外观**不能**从种子离线复现；只能按描述符渲染（见 `research/CREATURE-SEARCH.md`）。

---

## 2. 架构与数据来源（四通道模型）

```
① 离线 pak/MBIN ── hgpaktool + Shipwright ── 部件目录/贴图/模型/生成算法
② 存档 .hg ─────── LZ4 分块 + JSON 树 ────── 船队/发现记录/同伴/工具/货船
③ 外部内存 ─────── ReadProcessMemory ─────── 模板槽读写、（可扩展）AOB 读实时状态
④ 进程内 agent ─── pymhf + NMSpy ─────────── 传送/扫描/深度状态；受注入检测约束
```

**关键取舍**：能用 ③ 完成的，不轻易上 ④；能用 ② 完成的，不依赖游戏进程。
理由：③ 不需要注入、不会触发“模组冲突”；② 完全离线、最稳定。

模块边界（现实版，非理想版）：

```
core/  data/  save/  live/  agent/   ← 领域层（不 import UI/HTTP）
services/                            ← 用例门面（UI 与 Web 共用）
app/                                 ← PySide6 原生界面
web/                                 ← 可选 JSON API（兼容层）
```

已知债务：`services/__init__.py` 仍偏大（≈1.4k 行）；`web/routes.py` 有重复编排；
`app/` 少数页面直接 import 领域模块。详见 `ARCHITECTURE.md` D1–D14。

---

## 3. 体积：现状、构成与精简路线

`[发布]` v0.15.0 Windows 包：**88,917,611 B ≈ 84.8 MB**（zip）。
本地未裁剪 agent runtime：**112.7 MB**（CI 会裁掉 DearPyGUI/pywin32 开发件/字节码）。

### 3.1 精简手段（按收益排序）

| 手段 | 预计收益 | 风险 | 状态 |
|---|---|---|---|
| Qt 强排除（WebEngine/Quick/翻译/多余插件） | **−67.4 MiB（实测）** | 需逐项验证页面 | ✅ 已做 |
| `_internal` 二次裁剪（unicorn 静态库/opengl32sw/numpy 测试） | **−10.0 MiB（实测）** | 低 | ✅ 已做 |
| agent runtime 深度裁剪（DearPyGUI/pywin32 开发件） | **−3.5 MiB（实测）** | 首次注入需重装组件 | ✅ 已做 |
| Inno Setup LZMA2 替代 zip | **−32.3%（实测）** | 安装步骤变化 | ✅ 已做 |
| 不额外下载任何组件（用户约束） | — | — | ✅ 明确不做“可选下载” |
| 不用 UPX（杀软误报） | — | — | 明确不做 |

### 3.2 实测结果（2026-11，本机构建）

| 指标 | 旧 | 新 |
|---|---:|---:|
| PyInstaller `_internal` 产出 | 205.1 MiB | 137.7 MiB |
| 裁剪后 `_internal` | 115.3 MiB | 105.3 MiB |
| agent runtime（裁剪后） | 49.6 MiB | 46.1 MiB |
| **发布下载体积** | 72.2 MiB（zip） | **46.6 MiB（安装包）** |

### 3.3 目标

- **v0.16**：≤ 70 MiB —— ✅ **已达成（46.6 MiB）**
- **v1.0**：≤ 55 MiB —— ✅ **已提前达成**
- 原则：**安装包内置全部组件，用户不需要额外下载任何依赖**

---

## 4. 可扩展方向（按投入产出）

### P0（后端已落地，UI 接入中）

1. **地址工作台：坐标 ↔ 符文互转**（`XXXX:YYYY:ZZZZ:SSSS`）
   - 改 `glyphs.py` + `address.py`；验收：1 万随机地址往返一致、银河中心 `000000000000 ↔ 07FF:007F:007F`
   - `[参考]` Coordinate-Converter 的交互（**GPL-3.0，只重写数学，不复制代码**）
2. **发现索引 SQLite 化**（`~/.starforge/cache/discoveries.db`）
   - schema 见 `research/OSS-SAVE-INDEX.md`：saves/systems/planets/creatures/companions/ships/tools/frigates/bases/teleports
   - 增量：`size+mtime_ns` 快路径 → `sha256` 慢路径；`extractor_ver` 变更强制重建
3. **同伴 → 行星 → 动物联查**（“我的同伴来自哪颗星，那颗星还有什么生物”）
   - 复用 `discoveries` + `creature.companions`

### P1（需要实机校准或数据验证）

4. **传送持久性校准**：连续 10 次 teleport/portal，记录 UA/位置变化与失败率；把结论写回地址书/文档
5. **生物/工具 3D（Phase 0）**：先抽本机 pak 核对描述符→场景节点名，确认“整只 rig + 显隐”方案
   - 只读本机资源；**不复制 NMSDK/Creature-Builder 的代码/数据（无 LICENSE）**
6. **AOB 外部只读**（Gagarin 路线）：不用注入读玩家 UA/位置/当前船
   - 收益大、风险低于 pymhf；需要签名 + 多候选拒绝 + 版本闸门

### P2（产品化/生态）

7. 社区坐标导入（NMSCE 类）：**先解决许可**，默认不内置数据，只提供导入接口
8. 批量导出（多艘船/多星球/gif 转盘）；分享码
9. 多存档档案库与差异对比
10. 多语言（当前中文优先，LocTable 已支持）

---

## 5. 版本兼容策略（最重要的一条工程纪律）

| 对象 | 检测 | 策略 |
|---|---|---|
| 游戏本体 | exe sha256 + size + 版本 | 地址书按 build 分文件；未知 build **只读** |
| 内存位置 | AOB 签名 + 结构自洽 | 多候选拒绝写入；签名带容错 |
| 存档格式 | 文件头/版本戳 | 识别不了拒绝写；备份名带版本 |
| 数据表 | `mapping.json` + pak 哈希 | 数据层按版本缓存；缺失降级不崩 |
| Mod（EXML） | 模板 id/动画名/贴图路径 | 自命名空间；缺资源只影响图标 |
| 缓存 | 键含 `build_id + schema + extractor_ver` | 版本变化自动失效 |

配套：`selfcheck` 输出兼容矩阵；测试夹具按 build 固化；每次游戏更新先跑夹具再开发。

---

## 6. UI/UX 规范（已落地，后续遵守）

- **布局审计指标**（可量化）：控件越界 = 0、同级几何重叠 = 0、文本截断 = 0、隐藏横向溢出 = 0；
  1280×800 与 1180×760 两档 + 1.5× DPI 必测。
- **页面结构**：页头（标题/说明/操作）→ 筛选 → 内容 → 详情；长内容一律滚动，不靠固定高度。
- **风险标签**：只读 / 写存档 / 写内存 / 改世界状态；高风险按钮带二次确认与“回滚”提示。
- **空态**：说明 + 下一步按钮，不显示伪造数据。
- **快捷键**：`Ctrl+K` 命令面板、`Ctrl+1..7` 页面、`F5` 刷新、`Ctrl+Shift+T` 任务栏。
- **可访问性**：所有交互控件有 accessibleName/tooltip；Tab 顺序不跳栏。

---

## 7. 维护策略

1. **测试**：当前 528 个测试函数 / 59 文件；`pytest` 全绿是发布硬门槛。
   新增功能必须带“成功/空/失败”三路径；涉及写入的必须打桩真实内存。
2. **静态检查**：`ruff --select F` 全绿；发布前 `selfcheck_release --fail-on error`。
3. **CI**：当前只有 tag 触发的 release 构建；**建议增加 PR 上的 pytest + ruff job**（成本低、收益高）。
4. **依赖**：`requirements.txt` 固定关键版本（numpy 2.2.6、unicorn 2.0.1.post1、NMSpy build 对齐）；
   升级必须跑全量 + selfcheck。
5. **文档**：`docs/README.md` 是唯一索引；“现行文档”只以代码为准；归档只作历史。
   每篇关键结论带 `[代码]/[实测]/[参考]` 来源。
6. **发布**：版本号三处一致（`pyproject`/`__init__`/CHANGELOG）；打 tag 前跑三件套；
   Release 附 SHA256；发布后跑一次成品 `doctor/webcheck`。
7. **债务节奏**：每版最多消化 2 条架构债务（见 `ARCHITECTURE.md`），不搞“大重构周”。

---

## 8. 里程碑

| 版本 | 主题 | 交付 | 验收 |
|---|---|---|---|
| **v0.16** | 离线情报台 | 坐标/符文互转；发现索引 SQLite；同伴联查；体积 ≤65 MB | 往返一致性测试；索引增量；全量测试绿 |
| **v0.17** | 兼容与体积 | AOB 外部只读（玩家/船）；unicorn 可选；agent runtime 可选下载；CI 加 pytest | 未知 build 只读；体积 ≤55 MB |
| **v1.0** | 稳定版 | 生物/工具 3D（Phase 0 结论落地）；传送持久性报告；文档完备 | 干净机器安装即用；核心流程 0 崩溃 |

---

## 9. 合规与风险

| 项 | 结论 |
|---|---|
| 游戏资产 | **不打包**；运行时从玩家本机读取；图标自渲 |
| 上游许可 | Shipwright(MIT) 可用；HGPAKtool/MBINCompiler(LGPL) 作为工具链；nms-archive 数据含游戏资产**不可再分发** |
| 无许可项目 | NMSDK / nms-ship-customizer / AssistantNMS / Creature-Builder：**只参考思路** |
| 注入 | 默认不装；高风险写需显式开关；不做多人写入、不做反作弊规避 |
| 存档安全 | 默认只读；写入前备份、原子写、读回、回滚 |

---

## 10. 本周即可做的 5 件事

1. 坐标 ↔ 符文互转（`glyphs.py` + `address.py` + 地址工作台）
2. 发现索引 SQLite 化（按 `OSS-SAVE-INDEX.md` 的 schema）
3. 同伴联查：同伴 → 行星 → 该行星动物（UI 加一列/一卡）
4. CI 增加 `pytest + ruff` job（不改业务代码）
5. 传送持久性校准脚本 + 报告模板（可复现，不靠记忆）

---

## 附：关键文件索引

```
starforge/services/__init__.py     用例门面（含 live/warp/discoveries 封装）
starforge/discoveries.py           存档发现记录解析（VP 位布局）
starforge/live/{mem,writer,exml,iconart,agent_install,agent_client}.py
starforge/agent/starforge_agent.py 15 个 HTTP 端点（pymhf + NMSpy）
starforge/save/{writer,transaction,library,extras}.py
starforge/app/{shell,pages/*,widgets/*}  原生界面
docs/{MANUAL,ARCHITECTURE,AGENT,DEV-GUIDE,PACKAGING,LESSONS}.md
docs/research/{FEATURE-GAPS,CREATURE-SEARCH,OSS-*}.md
```
