# 经验与踩坑（LESSONS）

> 本文只记录**本轮（2026-11-21～22）实机验证过、或能由当前代码直接证明**的经验。
> 每条按同一结构写：**现象 → 根因 → 证据 → 正确做法**。
> 事实以代码为准；代码变了就回来改这里，不要把本文当成永久结论。

## 0. 来源标注约定

| 标注 | 含义 | 写法 |
|---|---|---|
| `[代码]` | 当前工作区代码/测试/配置可直接证明 | `[代码] starforge/agent/starforge_agent.py:1054-1106` |
| `[实测]` | 本机 build 185034 上实际跑过，有日志/存档对照 | `[实测] 2026-11-21 22:49 GET /ships 200` |
| `[参考]` | 上游文档/社区资料，只作旁证 | `[参考] https://…` |

脱敏约定：本文不写本机绝对路径、账号/SteamID、token、真实存档种子或完整 UA。
需要复现时用 `<游戏目录>`、`<存档>`、`<种子>` 占位，原始值只留在本机日志里。

---

## 1. 注入：三次崩溃与二分

### 1.1 三次 `0xC0000005` 不是三个 bug

**现象**：三个不同入口注入后，`NMS.exe` 都在 `python311.dll+0xC2B87`
（符号落在 `PyImport_GetModule` 附近）访问冲突退出；dump 里没有 `starforge_agent`、
`nmspy`、`pymhf` 的痕迹，说明崩溃发生在加载我们的 Mod 之前。

**根因**：注入时机，不是运行时版本。embeddable Python 被注入时解释器尚未完成初始化，
模块导入机制解引用了空状态。

**证据**：

- `[实测] docs/AGENT-INJECT-CRASH.md §1` 的三份 dump（2026-11-18 / 11-21），崩溃偏移一致；
- `[实测] docs/AGENT-INJECT-CRASH.md §8`：同一套 embeddable runtime，只把
  `start_paused` 改为 `True`，注入成功并连续存活 120 秒；
- `[代码] starforge/live/agent_install.py:648-664`：`start_paused=True`、`start_exe=not attach`；
- `[代码] starforge/live/agent_install.py:591-610`：`attach=True` 默认拒绝，理由写在异常文本里。

**正确做法**：

1. 默认走 `start_paused=True` 的“先创建/暂停进程，再注入”路径；
2. 不要用“换 Python 版本”“换 embeddable/完整版”解释这类崩溃——二分已经排除了版本；
3. 一次只改一个变量（注入时机、hook、启动方式），否则无法归因；
4. `STARFORGE_ALLOW_ATTACH_INJECT=1` 只用于调试，不是产品路径。

### 1.2 “每帧补绑 hook”是回归，不是修复

**现象**：带 `@nms.cGcApplication.Update.before` 每帧 `map_struct` 的版本，注入后游戏以
“模组冲突”退出，且日志里 `延迟绑定成功` 一次都没打印。

**根因**：hook 要么没注册成功，要么在错误的 `this` 上解析；每帧 `map_struct` 把一次性的
绑定问题变成了持续风险。

**证据**：

- `[实测] docs/AGENT-INJECT-CRASH.md §13.1`：同一份 agent，仅去掉每帧补绑即恢复；
- `[代码] starforge/agent/starforge_agent.py:926-946`：当前只保留
  `@one_shot @cTkFSM.StateChange.after`，注释明确写了“不要重新引入每帧 `map_struct`”。

**正确做法**：保留 one-shot 状态切换补绑；注入后进/出一次存档或开关菜单触发
`cTkFSM.StateChange`。one-shot 路径“已实现”，但“注入时已在存档、之后只做正常操作”的
自然场景仍未反复验证，按“待复验”看待。

### 1.3 “模组冲突”是特定场景，不是 NMS 一律关闭注入

**现象**：游戏弹“检测到潜在模组冲突问题 / 是否禁用所有模组”，退出后无 dump、
不写 `DISABLEMODS.TXT`，但退出前 HTTP 仍可用。

**根因**：游戏侧检测。已确认出现在“每帧补绑 hook”“pymhf 直接拉起 `NMS.exe` 被 Steam
接管控权重启”等场景；不是所有注入都会触发。

**证据**：

- `[实测] docs/AGENT-INJECT-CRASH.md §12`、`§13.1`；
- `[代码] starforge/live/agent_install.py:729-737`：Popen 后观察约 6 秒，进程不在就返回
  `E_GAME_EXITED`，不报告“注入成功”。

**正确做法**：不要反复重试；记录发生场景（哪个 hook、谁启动的进程）；优先用离线通道。
不要把“某次注入被关闭”推广成“注入永远不可用”。

### 1.4 `attach` 与 `start_exe` 的张力

**现象**：文档说“Steam 正常启动 → 再注入”，但 `launch(attach=False)` 仍然
`start_exe=True` 让 pymhf 启动游戏；而 `attach=True` 又被默认拒绝。

**根因**：pymhf 的受支持路径是“先创建进程、再注入”，Steam 可能接管并重启进程。

**证据**：`[代码] starforge/live/agent_install.py:591-610`、`:648-664`；
`[实测] docs/AGENT-INJECT-CRASH.md §10.3`。

**正确做法**：现场以 pid/端口为准。先确认 5000 端口属主是不是当前 `NMS.exe`；
不要假设“点了连接就一定注入到了你看的那个进程”。这条张力目前仍未完全消除，
属于已知限制，不是文档笔误。

---

## 2. `/ships`：运行时结构与存档结构是两套

### 2.1 现象：同一个“飞船列表”，字段对不上

**现象**：按存档结构去读运行时对象，得到空列表/错位；`primary` 能读到，`ships[]` 为空。

**根因**：`cGcPlayerState`（运行时，nmspy partial struct）与
`cGcPlayerStateData`（存档导出结构）不是同一套偏移。飞船在运行时是
`mShipResources[12]` + `miPrimaryShip`，在存档层是 `ShipOwnership`。
两者内容可能一致，但**不能混用字段/偏移**。

**证据**：

- `[代码] starforge/agent/starforge_agent.py:1054-1106`：`/ships` 明确读
  `ps.mShipResources` 和 `ps.miPrimaryShip`；
- `[代码] starforge/agent/starforge_agent.py:195-210`：文件顶部注释说明运行时结构
  “没有 Multitools / Pets / FreighterFleet”，这些字段只在 `cGcPlayerStateData`；
- `[实测] docs/AGENT-INJECT-CRASH.md §13.2`：运行时读到的船槽与同会话存档逐位一致
  （文档不复录具体种子）。

### 2.2 取值细节（三个最容易踩的点）

| 字段 | 真实类型 | 错误写法 | 正确写法 |
|---|---|---|---|
| `cGcResourceElement.Seed` | `basic.GcSeed` 结构体 | `int(res.Seed)` | `int(res.Seed.Seed) & 0xFFFFFFFFFFFFFFFF` |
| `Filename` | `VariableSizeString` | `str(res.Filename)` | `str(res.Filename.value)` |
| 空槽 | `-1` 哨兵 | 用“数值小”判断空槽 | `seed == 0xFFFFFFFFFFFFFFFF` 或 filename 为空 |

补充：

- 小种子也是合法值，不要用“数值小”判断空槽（示例见 `AGENT.md` §5.2）；
- `slot` 是 `mShipResources` 下标，`primary` 是 `miPrimaryShip`，两者不一定相同；
- `type` 由文件名 token 推断（`[代码] starforge/agent/starforge_agent.py:187-203`），
  不是游戏内权威船型。

**正确做法**：读运行时状态就用运行时结构；读存档字段就用
`SaveToData()` 序列化后的 `cGcPlayerStateData`。不要“猜一个中间偏移”同时服务两边。

### 2.3 `SaveToData()`：只读地拿到存档结构

**现象**：`/multitool`、`/freighter`、`/pets` 需要的字段在运行时 partial struct 里没有。

**根因**：nmspy 的 `cGcPlayerState` 只声明了部分字段；完整字段在
`nmspy.data.exported_types.cGcPlayerStateData`。

**证据**：

- `[代码] starforge/agent/starforge_agent.py:665-683`：分配本地
  `cGcPlayerStateData()`，调用 `ps.SaveToData(ctypes.byref(data))`，只写本地缓冲；
- `[代码] starforge/agent/starforge_agent.py:677-680`：用
  `Inventory.Slots.Size <= 0 and TotalPlayTime <= 0` 作为“未填充”哨兵；
- `[代码] starforge/agent/starforge_agent.py:337-416`、`:419-566`、`:569-662`：
  工具/货船/同伴分别按存档结构解析，并返回 `source` 字段。

**正确做法**：

1. `SaveToData()` 只序列化到**我们自己分配的缓冲**，不修改游戏状态；
2. 读不到就返回 `unsupported` + 原因，不用默认值伪造；
3. 新字段先在 `cGcPlayerStateData` 里找，找不到就明确“未支持”，不要拿运行时偏移硬套。

---

## 3. 传送门（portal）三档：只有 `prepare_warp` 被证实

### 3.1 三档实测

| stage | 做了什么 | 结果 |
|---|---|---|
| `warp_only` | 设 `mPortalData.mTargetUA/mbActive` 后直接 `WarpPlayer()` | **无效**（位置不变），不崩 |
| **`prepare_warp`** | 先 `Prepare()`，再 `WarpPlayer()` | **成功传送到目标行星**；UA/位置改变，日志有 `APPVIEW` |
| `full` | `OnAttached()` + `Prepare()` + `WarpPlayer()` | **未测** |

**根因**：`WarpPlayer` 的语义是“warps to `PersistentData::mTargetUA`, if `mbActive`
is true”；`Prepare()` 负责把组件状态准备到可 warp，`OnAttached()` 在只构造临时组件的
场景下可能是多余的。

**证据**：

- `[代码] starforge/agent/starforge_agent.py:838-909`：三档实现与注释；
- `[代码] starforge/agent/starforge_agent.py:1327-1367`：端点先写快照，再
  `_portal_warp(dest, stage=...)`；
- `[实测] docs/AGENT-INJECT-CRASH.md §14`：`warp_only` 无效、`prepare_warp` 成功、
  `full` 未测；服务层 `warp_portal()` 在 `allow_unverified_agent=True` 时读回 `planet=1`。

### 3.2 服务层与确认窗口

**现象**：portal warp 的加载比普通 `teleport` 慢；默认 3 秒确认窗口会误报未确认。

**根因**：`APPVIEW` 之后 UA 才更新，实测通常要 15–25 秒。

**证据**：`[代码] starforge/services/__init__.py:1058-1063`：`teleport.portal`
的确认超时单独设为 40 秒；`[代码] starforge/services/__init__.py:1094-1127`：
轮询 `/player` 只做读回，不伪造成功。

**正确做法**：

1. 默认 `stage=prepare_warp`，不要用 `warp_only` 下结论；
2. 传送前备份存档，并依赖 agent 先写 `snapshots.json`；
3. 以 40 秒读回结果为准；`confirmed:false` 不等于“没执行”，失败用 `/restore` 或存档备份；
4. `full` 未测，不要写“三档都可用”。

### 3.3 闸门

`[代码] starforge/services/__init__.py:1065-1073` 的 `warp_portal()` 受 build 闸门约束：
默认 build `185034` 是 `unverified`，会返回 `E_BUILD_UNVERIFIED`；显式打开
`allow_unverified_agent` 后，`teleport.portal` 才作为“实验写”放行。
`[实测] docs/AGENT-INJECT-CRASH.md §14` 记录了这个前后对比。

---

## 4. token 三个来源：环境变量 → 文件 → state.json

### 4.1 现象：`hello.auth` 是 `disabled`

**根因**：游戏由 Steam 拉起时，starforge 设置的 `STARFORGE_AGENT_TOKEN` 不会被子进程继承。
agent 读不到环境变量就退化为“不校验”，这不是“认证成功”。

**证据**：

- `[代码] starforge/agent/starforge_agent.py:71-101`：解析顺序
  `STARFORGE_AGENT_TOKEN` → `~/.starforge/agent/token` → `state.json` 的 `token`；
- `[代码] starforge/live/agent_install.py:673-689`：每次 launch 生成
  `secrets.token_urlsafe(32)`，同时写环境变量和 token 文件；
- `[实测] docs/AGENT-INJECT-CRASH.md §8`：曾出现 `"auth": "disabled"`；
  后续按 token 文件兜底，正常应为 `"token-query"`。

### 4.2 正确做法

1. 先看 `/hello` 的 `auth` 字段，不要假设“有 token 就一定生效”；
2. 看到 `disabled`，先查 token 文件/`state.json`，再怀疑客户端；
3. token 走 `?token=` 查询参数，会出现在本机 URL 和 uvicorn 访问日志里；
   对外粘贴日志前必须删掉；
4. `STARFORGE_HOME` 会让安装器和 agent 的 token 路径错位（安装器跟 `app_home()`，
   agent 固定读 `Path.home()`），这是已知风险，未做专门回归测试。

---

## 5. 热重载：改代码不必退出游戏

### 5.1 现象与流程

**现象**：改了 `starforge_agent.py`，希望不重启游戏就生效。

**证据**：

- `[代码] starforge/agent/starforge_agent.py:1257-1289`：`/admin/reload` 找
  `mod_manager.mods` 里 key 含 `starforge` 的项，后台线程延迟 0.4 秒后
  `mod_manager.reload(key)`；
- `[代码] starforge/live/agent_client.py:170-172`：客户端 `admin.reload`；
- `[实测] docs/AGENT-INJECT-CRASH.md §6.2` 的日志：
  `Removed 12 endpoints ...` → `Finished reloading StarforgeAgent` → 后续
  `GET /hello`、`/player`、`/ships` 均 200。

**正确做法**：

```text
1. 修改 starforge/agent/starforge_agent.py
2. 调 agent_install.install_mod() 把新源码写到 ~/.starforge/agent/
3. PUT /StarforgeAgent/admin/reload?token=...
4. 等几秒 → GET /hello 确认新逻辑/端点
```

注意事项：

- 0.4 秒延迟是为了避免卸载“正在返回响应的这次请求”；
- 返回 `scheduled` 只代表已安排，不代表已完成；
- 重载期间不要并发调用其它端点；
- **修改已有端点逻辑已实测可靠**；新增/删除端点后以 `hello` 实际返回为准，
  必要时重启游戏。“新增端点一定热注册成功”没有独立 A/B 证据。

---

## 6. 图标：不要复用游戏里的 `TYPE.*.DDS`

### 6.1 现象：表情图标“语义不对”

**现象**：直接用游戏 pak 里的 `TYPE.*.DDS`，穿梭机显示成一对齿轮，运输舰/探索舰找不到
同名图标，整排看起来像“类别符号”而不是船。

**根因**：那组 DDS 是**船型类别符号**，不是飞船外观；不同船型还未必有同名资源。

**证据**：

- `[代码] starforge/live/iconart.py:1-11`：注释明确说明为什么不用 `TYPE.*.DDS`；
- `[代码] starforge/live/exml.py:129-154`：`ICON_DIR` 指向自己的
  `TEXTURES/UI/FRONTEND/ICONS/STARFORGE`，`icon_asset()` 指向仓库 `live/assets/icons`；
- `[代码] starforge/live/exml.py:528-535`：生成 Mod 时把 8 张 DDS 原样复制进去。

### 6.2 生成风格与实现要点

**风格（2026-11-21 定版）**：iso 视角、真实涂装做体积；船体压暗，只保留青色边缘描线 +
细网格；128×128，BC1_UNORM（DX10 头），单文件约 8 KB。

**证据**：`[代码] starforge/live/iconart.py:25-29`（尺寸/底色）、`:35-78`
（BC1 编码与 DX10 DDS 头）、`:112-137`（渲染、裁切、边缘描线、网格）。

两个实现坑：

1. 遮罩不能用 `any(axis=2)`：渲染器会整幅填底色；
   `[代码] iconart.py:84-89` 用“与 `RENDER_BG` 的差异”算遮罩。
2. `_trim` 必须在 `_fit` 之前：先按非背景像素裁掉空白，再等比放到方形画布；
   `[代码] iconart.py:92-109`。

**正确做法**：需要重生成时用仓库生成器，不要手工改 DDS：

```bash
python -c "from starforge.live import iconart; print(iconart.generate())"
```

生成后跑 `python -m pytest tests/test_iconart.py -q`，再重装模板 Mod。
`[实测] 2026-11-21` 本机安装后的 `GAMEDATA/MODS/starforge-templates` 含 8 张
`TEMPLATE.*.DDS`，表情菜单显示 8 个独立图标。

---

## 7. 写闸门不一致：三类写操作，三套规则

### 7.1 现象

同样是“写”，不同入口的要求不一样：

| 入口 | `write_enabled` | 二次确认 | 其它闸门 |
|---|---|---|---|
| 存档写回/改级/扩展编辑 | 必须 | 必须 | 备份、原子写、读回、回滚 |
| “送进游戏”（模板槽 8 字节） | 必须 | 必须 | 只写 8 字节、候选唯一、回读 |
| agent 传送/还原/扫描写 | **不检查** | 由 UI 弹窗，服务层无参数 | build 闸门、`allow_unverified_agent`、多人闸门 |
| 一键安装模板 Mod | **不检查** | `confirm=True` | 写游戏目录 `GAMEDATA/MODS` |

**证据**：

- `[代码] starforge/services/__init__.py:1135-1174`：`require_live_write()` =
  `settings.require_write()` + `confirm`；`live_push()` 用它；
- `[代码] starforge/services/__init__.py:1025-1073`：agent 高风险写只检查
  build / `allow_unverified_agent` / 多人，没有 `write_enabled`/`confirm` 参数；
- `[代码] starforge/services/__init__.py:1262-1289`：`install_template_mod(confirm=True)`
  只检查 `confirm`，直接写 `<游戏目录>/GAMEDATA/MODS`；
- `[代码] starforge/app/pages/game_link.py:1127-1154`、`galaxy.py:1381-1435`、
  `widgets/pets_view.py:519-566`：二次确认在 UI 调用方，而不是服务契约；
- `[代码] starforge/core/settings.py:147-151`：`require_write()` 只看 `write_enabled`；
- `[代码] starforge/services/history.py:58-75`：`_record` 写“最近活动”，是审计线索，
  但不是不可篡改的审计日志。

### 7.2 更具体的 UI 不一致

**现象**：勾选“允许未验证游戏版本实验写操作”后，星图/同伴页的传送可能放行，
但游戏内页仍提示“这版未验证：高风险写操作被禁用”。

**根因**：游戏内页 `_teleport()` 直接看 `self._build_verified`，没有读取
`live_capabilities` 返回的 `experimental/unverified_allowed`；星图/同伴走
`Services.warp_portal()`，只受服务层闸门约束。

**证据**：`[代码] game_link.py:401-485`（`_apply_state` 用 `write_allowed` 决定
`_build_verified`）、`:1127-1154`（传送前仍判 `_build_verified`）；
`[代码] galaxy.py:1434`、`pets_view.py:565`（直接 `svc.warp_portal`）；
`[代码] services/__init__.py:939-972`（服务层会把实验能力标成
`experimental/unverified_allowed`）。

**正确做法（当前实际实现，待合并）**：

1. 不要把 `write_enabled` 当成“所有写的总开关”——它目前只覆盖存档写和模板槽写；
2. agent 写必须同时看 build、`allow_unverified_agent`、多人；UI 的二次确认不能省；
3. 一键安装模板 Mod 目前只有 `confirm`，没有 `write_enabled`；这是“写游戏目录”，
   应单独说明，不要和“写存档”混为一谈；
4. **待合并**：游戏内页与星图/同伴页统一以 `live_capabilities` 的
   `experimental/unverified_allowed/blocked_by` 为唯一依据；服务层给 agent 写补
   `confirm` 参数与统一审计。代码合并前，按上表描述实际行为，不要按“已统一”写。

---

## 8. 文档漂移：错得最久的往往不是代码，是结论

### 8.1 现象

同一件事在文档里有三种说法：

- 索引写“12 个端点”，代码实际 15 个；
- 用户手册写“原生界面没有一键安装模板 Mod”，页面已有安装按钮；
- AGENT.md 一处写“`prepare_warp` 已实测可传送”，另一处还写“portal 已知不可用”；
- 架构文档的行数/方法数停留在旧快照。

**根因**：结论先于代码合并写死；复制旧段落时没有回代码核对；代码注释本身也会过期。

**证据**：

- `[代码] starforge/agent/starforge_agent.py` 的 15 处 `@endpoint`（`/hello`…`/scan`）；
- `[代码] starforge/app/pages/game_link.py:303-311`：安装模板 Mod 按钮；
- `[代码] starforge/live/exml.py:297-302`：注释仍说图标“用 pak 里实际存在的 DDS”，
  但同一文件 `:129-154` 已改成自己的 8 张图标——**代码注释也会漂移**；
- `[代码] starforge/app/pages/ship_designer.py:4` 的模块 docstring 仍写“不直接写存档”，
  但页面已接写入对话框。

### 8.2 正确做法

1. 每个关键结论后面写来源：`[代码] 路径:行`、`[实测] 日期 + 日志`、`[参考] URL`；
2. 行号会漂移，优先写“路径 + 函数/类名”，行号只作定位；
3. 版本、端点数量、页面能力这类“计数型事实”，每次改动后重新统计；
4. `docs/archive/` 只用于追溯，不作为“当前依据”；新文档不要把它当证据链的起点；
5. 发布前跑 `python scripts/selfcheck_release.py --fail-on error`，它至少能抓断链和
   索引遗漏，但抓不到“结论过期”。

---

## 9. UI 缺口：已修与待补

### 9.1 已修（以当前代码为准）

| 项 | 现状 | 证据 |
|---|---|---|
| 模板 Mod 一键安装 | 游戏内页有“安装模板 Mod”按钮，写 `<游戏目录>/GAMEDATA/MODS` | `[代码] game_link.py:303-311`、`:984-1012`；`services/__init__.py:1262-1289` |
| 连接已运行的游戏 | 改为“要求游戏已在运行 + `attach=False`”，不再默认 attach | `[代码] services/__init__.py:1291-1312`；`game_link.py:772-774` |
| 附近兴趣点 | 按钮已禁用并标注“未实现”；不会再发必败的 `scan.poi` | `[代码] game_link.py:278-292`、`:1026-1035` |

### 9.2 待补

| 项 | 现状 | 证据 |
|---|---|---|
| 多存档切换 | `Services.saves()` 有，页面仍只用默认存档 | `[代码] services/__init__.py:348-360`；`fleet.py` 的 `default_save` 调用 |
| 传送快照历史 | `agent_snapshots()` 有，页面无入口 | `[代码] services/__init__.py:838-855` |
| selfcheck 自检 | 设置页只有 `doctor`，`diagnostics()` 无页面调用 | `[代码] services/__init__.py:1316-1320` |
| 运行时准备/卸载 agent/热重载入口 | 服务层有，页面没有对应按钮 | `[代码] services/__init__.py:861-907`、`:1075-1081` |
| restore 读回确认 | 只对 teleport/portal 做确认，restore 仍是 `pending` | `[代码] services/__init__.py:1058-1063`；`agent/starforge_agent.py:1369-1391` |

**正确做法**：写“已支持”前先确认页面有入口；服务层有方法不等于用户能用。
`docs/research/FEATURE-GAPS.md` 是审计时点快照，状态变化以 §0.1 的复核更新为准。

---

## 10. 附：GET/PUT 405 的小坑

**现象**：旧 agent 的只读端点用 `GET` 请求返回 `405`。

**根因**：pymhf 0.2.5 在没有显式声明 `method` 时，会把路由注册成 `PUT`。

**证据**：`[代码] starforge/live/agent_client.py:117-130` 的 `GET` → 405 → `PUT`
回退；`[实测] docs/AGENT.md §2.3` 的 `pymhf-20261121T214123.log`。

**正确做法**：新端点显式写 `method="GET"`（只读）或 `PUT`（写入）；手写脚本遇到 405
先试 `PUT`，不要以为端点不存在。

---

## 11. 一句话清单

- 注入：先 `start_paused`，再谈 hook；`attach=True` 默认拒绝。
- 飞船：运行时 `mShipResources`，存档 `ShipOwnership`，永远别混。
- 传送门：`prepare_warp` 可用，`warp_only` 无效，`full` 未测。
- token：环境变量会丢，token 文件是兜底；`disabled` ≠ 安全。
- 热重载：先写盘，再 reload，最后用 `/hello` 验收。
- 图标：自己渲、BC1/DX10、按底色差异算遮罩。
- 闸门：写存档、写模板槽、写游戏状态是三件事；统一前按实际规则写。
- 文档：每句关键结论带来源；归档只作历史，不作当前依据。
- 模板槽：**写入立即生效，不需要重载存档**（见 §12）。

---

## 12. 模板槽写入是“立即生效”的（推翻“需要重载存档”的猜测）

**现象**：早期怀疑“写模板槽后必须重载存档，游戏才读到新种子”。

**实测（2026-11-22，build 185034）**：

1. 向 sentinel 模板槽写入示例种子 `0x1111222233334444`，`writer.push` 回读一致；
2. 在游戏内直接打开表情菜单领取（**不退出、不重载、不回主菜单**）；
3. 做一次正常存档后读文件：最新自动存档新增一艘 `sentinel`，种子正是
   `0x1111222233334444`；上一份自动存档没有这艘船。

**根因**：领取时游戏读取的是模板的 `ShipResource.Seed` 字段，而外部写入改的正是同一份
内存；不存在“存档加载时把模板冻结”的行为。

**注意**：候选可能有多个（同一会话多次载入会产生多份副本，实测 sentinel 曾出现 8 个），
但 `writer.locate` 只采纳“Slots 佐证 + 出厂种子仍存在”得分最高的那份，本次写入命中的
就是领取时读取的那份。若未来出现“写入成功但领取仍是旧外观”，再考虑“多副本同时写”
或改用 ShipLayout 字节模式定位（SSH 的做法）。

**证据**：`[实测] 2026-11-22 写入 → 领取 → 存档对比`；`[代码] starforge/live/writer.py`；
`[参考] NMS-Super-Ship-Hunter 的模板槽写入路径`。

---

## 13. 注入失败的两个真实原因：重复注入 + 选错进程（2026-11-22 复盘）

**现象**：主菜单注入成功、`/hello` 持续 200；约 100 秒后游戏崩溃（`python311.dll+0xC2B87`）；
再次点「连接游戏」永远显示未连接；之后每次注入都报 `CouldNotOpenProcess`。

**证据**（`~/.starforge/agent/pymhf-*.log`）：

1. `15:16:48` 第一次注入 pid 13172 成功，agent 在 6770 端口正常响应；
2. `15:17:00` **又注入一次**同一进程 → `OSError 10048`（端口已占用）；
3. `15:17:13` 崩溃前的游戏派生了一个同名子进程（pid 10840，`ExecutablePath` 为空）；
4. `15:18` 游戏退出（dump 13172）；`15:24`/`15:28` 的注入都选中了 **10840 僵尸** → 永远打不开。

**根因**：

- `launch(attach=False)` 在游戏已运行时仍走 Steam 启动分支；Steam 把已经运行的实例交给 pymhf，
  pymhf 于是**对同一进程注入第二次**。一个进程里出现两套 Python 解释器/路由，存档加载时命中
  野指针 → 崩溃。
- 第一次注入写入了新 token，第二次注入又写了一份；旧 agent 的内存 token 和新客户端不一致，
  表现为“注入成功但一直未连接”。
- `pymem.Pymem("NMS.exe", exact_match=True)` 按**名字**找进程；崩溃残留的同名子进程会被优先选中。

**正确做法**（已落地）：

- 连接前先 `ping`：agent 可达就直接复用，**绝不重复注入**；
- 按 pid 注入前校验 `QueryFullProcessImageNameW`，跳过无路径/打不开的僵尸；
- pymhf `injected.py` 打补丁：优先 `Pymem(os.getpid())`，失败才按名字回退；
- 游戏已在运行时，`launch(attach=False)` 返回 `E_GAME_RUNNING`，由 UI 让用户选
  「附加注入（可能退出）」或「重启并注入」，不偷偷再拉一个实例。

**给用户的顺序**：启动游戏 → 停在主菜单 → 应用里连接 → 再进存档。
已进入存档时注入有让游戏退出的风险，必须二次确认。
