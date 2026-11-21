# agent 注入实验记录（build 185034）

> **最终结论（2026-11-21）**
>
> 1. **形态**：`starforge_agent.py` 是 pymhf 单文件 Python Mod（NMSpy + pymhf `http_api`），
>    通过 `http://127.0.0.1:5000/StarforgeAgent` 与 `live/agent_client.py` 通信。不是 DLL、
>    不走命名管道、不写 `winmm.dll`；`install_mod()` 只写 `~/.starforge/agent/`，不改游戏目录。
> 2. **支持路径**：应用实际用 `attach=False` + `start_paused=True` 启动并注入
>    （`live/agent_install.py`）。`launch(attach=True)`（对已运行实例 attach）**默认直接拒绝**，
>    只有设置 `STARFORGE_ALLOW_ATTACH_INJECT=1` 才放行，仅供调试。
> 3. **注入时机的硬要求**：注入时进程必须已暂停在可安全初始化的状态（`start_paused=True`），
>    且注入后 nmspy 需要完成一次状态切换/绑定才能拿到 `GcApplication`。当前实测稳定路径是
>    「Steam 启动 → 主菜单注入 → 进存档」；**"什么时候注入都行"没有代码支持**。
> 4. **NMS 的失败模式**：在部分注入场景（每帧补绑 hook、`pymhf` 直接拉起 `NMS.exe` 被 Steam
>    接管等）游戏会弹「模组冲突」并退出，无崩溃转储、不写 `DISABLEMODS.TXT`。这只适用于这些
>    场景，**不是"NMS 一律关闭注入"**：去掉每帧补绑、attach 到已运行实例后，注入可存活并完成
>    只读/传送/还原。
> 5. **已实测可用**：只读（`/player`、`/system`、`/planet`、`/ships`）、`prepare_warp` 传送、
>    `restore` 还原、`scan` 只读档案、模板槽外部读写。写能力默认仍受 build 闸门限制
>    （`live/builds/185034.json` 未标 `verified`），"实测过"≠"build 地址书已验证"。
>
> 下文 §1–§7 是 2026-11-18～21 的历史排查，其中 §3 的"运行时版本必崩"判断已被 §8 推翻；
> §8–§13 是后续对照实验与当前基线。与本节冲突的旧小节以本节为准，各节内也已标注修正。

## 1. 现象

注入后游戏短暂卡顿，随后 `NMS.exe` 访问冲突退出（`0xC0000005`）。
三次不同入口、两套不同运行时目录，崩溃位置**完全一致**。

| 转储 | 时间 | 入口 | 运行时目录 | 崩溃点 |
|---|---|---|---|---|
| `<crash-1>.dmp` | 2026-11-18 22:18 | 桌面版应用（v0.14.5） | `<发行包目录>\agent-runtime` | `python311.dll+0xC2B87` |
| `<crash-2>.dmp` | 2026-11-21 22:02 | `pymhf.load_mod_file`（attach） | `~\.starforge\agent\runtime` | `python311.dll+0xC2B87` |
| `<crash-3>.dmp` | 2026-11-21 21:32 | `pymhf run`（CLI，误用 Steam 启动） | `~\.starforge\agent\runtime` | `python311.dll+0xC2B87` |

崩溃参数：`ExceptionInformation = [0, 0x10]` → **读地址 0x10**（空指针 + 0x10）。

## 2. 符号级定位

`0xC2B87` 落在 `python311.dll` 导出符号：

```
PyImport_GetModule + 0x73
```

即：在**模块导入机制**里解引用了解释器状态（`sys.modules` / interpreter 结构）。
这通常意味着 **解释器尚未完成初始化就被调用**。

崩溃时已加载的注入侧模块：

```
python311.dll  ·  python3.dll  ·  pythoncom311.dll  ·  _dearpygui.pyd
```

而 dump 里**没有** `starforge_agent` / `nmspy` / `pymhf` / `load_mod_file` 的痕迹，
说明崩溃发生在**加载我们的 Mod 之前**。

## 3. 根因判断

starforge 的 agent runtime 来自：

```
https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip
```

这是 **embeddable（嵌入式）发行版**，带 `python311._pth`：

```
python311.zip
.
Lib\site-packages
import site
```

embeddable 发行版按设计用于"独立 exe 运行"：它禁用常规 site 逻辑、忽略 `PYTHONPATH`，
路径解析依赖宿主可执行文件位置。被注入到 `NMS.exe` 之后，宿主 exe 是游戏，
解释器的路径/初始化假设不再成立，`PyImport_GetModule` 拿到空状态即崩。

**不是**我们 agent 逻辑的问题，也不是 build 签名问题——崩溃早于 Mod 加载。

## 4. 已验证 / 未验证

已验证：
- 直接 `load_mod_file`（attach）→ 崩（11-21 17600）
- `pymhf run` CLI → 崩（11-21 7332）
- 同一运行时注入 `notepad.exe`：**没有**成功加载 python（runner 卡在 `pyRunner`，目标进程无 python 模块），因此**未取得有效对照**

未验证（下一轮应做，且需要接受一次崩溃风险）：
- 使用**完整安装版 Python 3.11.9**（非 embeddable）+ pymhf/NMSpy 注入
- 使用 Python 3.12 / 3.10 完整版（pymhf 要求 `>=3.10`）

## 5. 已知的坑（不要再踩）

1. **attach 注入**：`pymhf` 对已初始化的游戏进程注入会与游戏线程竞争；实测在同一 build 上
   与 embeddable 运行时叠加时必崩。已由 `agent_install.launch()` 默认拒绝，
   仅 `STARFORGE_ALLOW_ATTACH_INJECT=1` 可强制。
2. **`pymhf run` 单文件 Mod 不读 `pymhf.toml`**：本次实验里 CLI 使用了默认的 Steam 启动，
   直接把游戏拉起来并注入（第三次崩溃）。若要用 CLI，必须使用内联脚本元数据
   （`# /// script` 块）或注册为插件库，不要依赖旁置 `pymhf.toml`。
3. 崩溃转储位置：`%LOCALAPPDATA%\CrashDumps\NMS.exe.<pid>.dmp`；
   用仓库外的一次性脚本 + `minidump` 包可离线解析，不必启动调试器。

## 6. 产品侧处置

- `launch(attach=True)` 默认拒绝并给出可读原因（含实测崩溃码与模块）。
- agent 能力表（`starforge agent hello`）如实反映 `installed / runtime / reachable`，
  不再硬编码 "需要 agent（M4）"。
- 在换用完整版运行时并实测通过之前，**不要**把 build 标记为 `verified`。

## 7. 复现实验的最小安全步骤（下次）

1. 安装完整版 Python 3.11.9（非 embeddable），并在其中 `pip install pymhf[http_api] NMSpy==185034.0`。
2. 把该 Python 作为 agent runtime（设置或环境变量指向它）。
3. 先用 `notepad.exe` 验证注入链路能真正加载 Python（目标进程模块里应出现 `python311.dll`）。
4. 只有第 3 步通过后，才在**可丢弃存档**上尝试注入 NMS。

---

## 8. 已解决（2026-11-21 晚，实测）

**崩溃的直接原因是注入时机，不是运行时版本。** 把 `start_paused` 改为 `True`
（注入完成前保持进程暂停）后，同一套 embeddable runtime 成功注入 NMS：

```
pid=<pid>  python 注入=['python3.dll','python311.dll','pythoncom311.dll','dll.cp311-win_amd64.pyd']
连续 120 秒存活，无崩溃转储
```

`GET /openapi.json` 确认 11 个端点全部注册成功；`PUT /hello` 返回：

```json
{"ok": true, "nmspy": "185034.0", "game_attached": true, "in_game": true,
 "multiplayer": false,
 "capabilities": {"player": true, "system": true, "planet": true, "planet.scan": true,
                  "ships": true, "teleport": true, "teleport.portal": true,
                  "scan": "read", "scan.instant": true, "restore": true}}
```

实测读到的数据结构（**数值为示例，已脱敏**；字段/量纲保留）：

```
UA 0x0011223344556677 · 星系 <星系名> · 行星 #<n>
位置 (<x>, <y>, <z>) · voxel (<vx>, <vy>, <vz>)
单位 <units> · 纳米 <nanites> · 生命 <hp> / 护盾 <shield>
行星 <行星名 1>（<biome 1>）· <行星名 2>（<biome 2>）· <行星名 3>（<biome 3>）
```

原始数值只留在本机日志；文档只保留“UA/位置/资源/行星档案可读”这一结论。

### 对照实验（全部零游戏风险）

| 实验 | 结果 |
|---|---|
| 完整版 Python + start 模式 → ping.exe | ✅ 注入成功、进程存活 |
| embeddable + start 模式 → ping.exe | ✅ 注入成功、进程存活 |
| embeddable + start_paused=True → ping.exe | ✅ 注入成功、进程存活 |
| `import nmspy` 的 Mod → ping.exe | ✅ `nmspy imported`，不崩 |
| **embeddable + start_paused=True → NMS.exe** | ✅ **存活，端点全部可用** |

### 两个新的已知问题

1. **pymhf 把未声明 method 的 endpoint 注册成 PUT**（`openapi.json` 里 11 个都是 `put`），
   而 starforge 客户端原来全部用 GET → 405。已修：
   - agent 的只读端点显式声明 `method="GET"`；
   - 客户端 `_read()` 先 GET，遇到 405 回退 PUT（兼容旧 agent）。
2. **token 没有生效**：`hello` 返回 `"auth": "disabled"`，说明 pymhf 启动游戏时
   没有把 `STARFORGE_AGENT_TOKEN` 传进游戏进程。目前只监听 127.0.0.1，风险有限，
   但不应把"有 token"当作已生效。
3. `/ships` 返回 `{"primary": 4, "ships": []}` —— 主飞船索引读到了，但列表为空，
   说明飞船数组遍历还没校准（下一个要修的点）。

---

## 9. 写通道实测（可丢弃存档，2026-11-21 晚）

按风险从低到高做了两步，全程未崩溃：

| 步骤 | 结果 |
|---|---|
| `scan`（mode=read，不改世界状态） | ✅ 返回实时行星档案：`UI_PARADISE_PLANET`、哨兵 `SENTINEL_RARE*`、生物列表（TRICERATOPS/COW/CAT/…）、资源 `YELLOW2/LAND3/LUSH1` |
| `teleport` 回当前星系（`glyphs_for_ua` 生成示例 `123456789ABC`） | ✅ 返回 `before.planet=0 → after.planet=1`，`confirmed: true`（应用轮询 `/player` 读回一致） |
| 快照 | ✅ `~/.starforge/agent/snapshots.json` 记录 before/destination/glyphs |
| `restore`（回滚） | ✅ 返回 `restored`，读回位置与快照一致 |

观察与注意：

- 传送后立即读 `/player` 的 `position` 为 `(0,0,0)`，属于加载中的瞬时值，属正常。
- 下一次读 `/player` 时 planet 又回到 0，说明"写位置 + 触发加载"的**持久性依赖游戏自身加载流程**，
  不能仅凭 `confirmed: true` 断言长期生效——这正是 agent 自己返回的
  `"note": "已写入并触发加载；应用会读回位置确认，未生效请用 restore 还原"` 的含义。
- 测试期间临时打开 `settings.allow_unverified_agent`，**结束后已还原为 `False`**；
  高风险写命令在默认配置下仍然被 build 闸门挡住。

---

## 10. 运维规则（2026-11-21 修正版）

### 10.1 注入顺序：硬要求与当前路径

§8 的 `start_paused=True` 解决了"注入瞬间解释器未就绪"的崩溃，但**不**等于注入顺序随便。
历史版本里的 `_late_bind_app`（每帧补绑）曾让"先注入/后注入都行"看起来成立；该 hook 已在
§13.1 回退——带每帧补绑的版本反而以「模组冲突」退出，且 `cGcApplication found / 延迟绑定成功`
从未打印。因此当前**没有**"什么时候注入都行"的支持路径，只有两条硬要求：

- 注入时进程已暂停在可初始化状态（`start_paused=True`）；
- 注入后、读取前，nmspy 已完成 `cTkFSM.StateChange` 绑定（实际操作：先进主菜单再注入，然后进存档）。

当前实测稳定顺序见 §13.3。

### 10.2 改代码不必退出游戏

`PUT /StarforgeAgent/admin/reload`（服务层 `Services.agent_reload()`）会在后台线程里调用
`pymhf.core.mod_loader.mod_manager.reload(...)`：

```
1. 修改 starforge/agent/starforge_agent.py
2. 运行 starforge.live.agent_install.install_mod()（写盘）
3. 调一次 admin.reload → 数秒内新代码生效
```

注意：新增/删除**端点**仍需重启（pymhf 的路由在 reload 时按模块重新注册，通常也能生效，
但以实测为准）；仅修改已有端点逻辑是可靠的。

### 10.3 不要用 pymhf 直接启动 NMS.exe

实测：pymhf 起 `NMS.exe` 后，**Steam 会接管并重启游戏进程**，注入的那个进程随即消失
（没有崩溃、没有端口、agent 不可达）。正确流程：

```
1. 用 Steam 正常启动游戏，进入主菜单（或存档）
2. 再调用 starforge 的注入（pymhf 会“发现已运行实例”并注入）
```

### 10.4 token 传递

环境变量在 Steam 启动场景下会丢（游戏不是我们的子进程）。`launch()` 同时把 token 写到
`~/.starforge/agent/token`，agent 按“环境变量 → token 文件 → state.json”解析。
`hello` 里应看到 `"auth": "token-query"`；若为 `disabled`，说明 token 文件没读。

---

## 12. 历史判断：NMS 会以「模组冲突」退出（特定场景，2026-11-21）

> **修正**：本节最初写成"NMS 会主动关闭注入"的最终结论。§13.1 的二分之一实验表明，该现象
> 出现在「每帧补绑 hook」版本（以及 `pymhf` 直接启动 `NMS.exe` 被 Steam 接管）等特定场景；
> 去掉补绑、attach 到已运行实例后可存活。不要把本节当作普适结论。

在 build 185034 上多次实测后确认：**在这些场景下**，游戏会把注入的 Python/ctypes 识别为
“模组冲突”并主动退出。

现象：

- 游戏内弹出 No Man's Sky 错误框：「禁用模组 / 崩溃ID: 185034M_-ctypes@0x63980D_… /
  检测到潜在模组冲突问题 / 是否禁用所有模组以解决问题?」
- 退出后：**无崩溃转储**、**无 Application Error 事件**、**不写 `DISABLEMODS.TXT`**
- 注入与 HTTP 服务在退出前是可用的（日志里有 200 响应和 New State）

含义：

1. 这不是“注入时机/参数”问题，而是**游戏侧检测**，靠调 `start_paused`/Python 版本绕不过去。
2. 我们不应在玩家的真实游戏上反复触发它。

代码处置：

- `launch()` 在 Popen 之后会观察约 6 秒；游戏不在就返回
  `{"ok": false, "code": "E_GAME_EXITED", "error": "…NMS 会把注入识别为模组冲突…"}`，
  不再报告“注入成功”。
- attach 注入仍默认拒绝；`STARFORGE_ALLOW_ATTACH_INJECT=1` 仅用于调试。

仍然可用（不受影响）的通道：

| 能力 | 状态 |
|---|---|
| 搜索 / 3D / 缩略图 / 符文 / 星系扫描 | ✅ 离线 |
| 存档读/写/备份/回滚、船级/属性编辑 | ✅ |
| 模板槽只读探测 + 8 字节写入（外部内存） | ✅ 实测 8/8 定位 |
| 应用内「送进游戏」→ 表情领取 | ✅ 实测领取成功（存档种子一致） |

---

## 14. Portal warp 校准（2026-11-21 23:0x）

`cGcPortalComponent`（nmspy 手工逆向结构）在 build 185034 上可用。按三档实测：

| stage | 行为 | 结果 |
|---|---|---|
| `warp_only` | 只设 `mPortalData.mTargetUA/mbActive` 后调 `WarpPlayer` | 不生效（位置不变），**不崩** |
| **`prepare_warp`** | 额外调用 `Prepare()` | ✅ **传送到目标行星**：UA 从 `0x0023…` 变 `0x0033…`，位置改变，日志出现 `New State: APPVIEW` |
| `full` | 额外调用 `OnAttached()` | 未测 |

产品路径（服务层）也已验证：

```
Services.warp_portal(glyphs)  → 默认闸门 E_BUILD_UNVERIFIED（正确）
allow_unverified_agent=True   → planet 3 → 1，confirmed=true，读回 planet=1
```

结论：**"筛选星球 → 传送" 可用**，走 `prepare_warp`；`/teleport`（写位置 + APPLOCALLOAD）仍是备选。


---

## 13. 二分结果与现有稳定基线（2026-11-21 22:45）

### 13.1 闪退是"每帧补绑 hook"引入的回归

同一份 agent，仅去掉 `_late_bind_app`（`@nms.cGcApplication.Update.before` 里每帧
`map_struct(get_addressof(this))`）后：

| 版本 | 注入结果 |
|---|---|
| 带每帧补绑 | 注入后游戏以“模组冲突”退出（无 dump） |
| **去掉补绑** | ✅ 注入 2 秒可达，进入存档后读取正常，游戏持续存活 |

日志侧面证据：带补绑的版本里，`cGcApplication found / 延迟绑定成功` **一次都没打印**，
说明这个 hook 要么没注册成功、要么在错误的 `this` 上解析。**已回退**，源码里保留说明。

### 13.2 `/ships` 已用真实数据验证

当前存档槽（`<存档>`，4 艘船）与内存读到的 4 条**种子逐位一致**。
具体种子是存档派生数据，文档不复录；结构示例（种子已脱敏）：

```
slot=0 <模型 A>.SCENE.MBIN           0x0123456789ABCDEF
slot=1 SENTINELSHIP_PROC.SCENE.MBIN  0x0123456789ABCDEF
slot=2 SENTINELSHIP_PROC.SCENE.MBIN  0x0123456789ABCDEF
slot=3 <模型 B>.SCENE.MBIN           0x0123456789ABCDEF   (primary=3)
```

“逐位一致”的判据在 `docs/LESSONS.md` §2；本机原始值留在日志/存档，不写进文档。

取值要点（校准记录）：

- `cGcPlayerState.mShipResources[12]` 是**运行时**结构；存档层对应的是
  `cGcPlayerStateData.ShipOwnership[12]`（两者不能混用）
- `cGcResourceElement.Seed` 是 `basic.GcSeed` → 取 `.Seed`（int64），不是 `int(res.Seed)`
- `Filename` 是 `VariableSizeString` → 取 `.value`
- 空槽种子为 `0xFFFFFFFFFFFFFFFF`（-1 哨兵）

### 13.3 当前实测稳定路径（顺序有要求）

```
1. Steam 启动游戏，停在主菜单
2. 注入（pymhf “发现已运行实例”分支）
3. 进入存档 → 触发 nmspy 的 StateChange → 绑定 GcApplication
4. 读取 /ships /player /system /planet 正常
```

补充：`prepare_warp` 已实测可完成传送（§9），`restore` 可回滚。"随便什么时候注入都行"
需要安全补绑，暂不引入（一次只改一件事）。



