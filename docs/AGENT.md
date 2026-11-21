# 游戏内通道（agent）

> 事实基线：**2026-11-21 的代码 + 本机实测日志**。
> 本文只写能由代码或实测记录支撑的结论；没有实测的项明确标“未验证”，
> `hello` 自报的能力不等于应用层允许的能力。
>
> 主要代码位置：
> - Mod：`starforge/agent/starforge_agent.py`
> - 安装/启动/状态：`starforge/live/agent_install.py`
> - 本机 HTTP 客户端：`starforge/live/agent_client.py`
> - build 指纹与写闸门：`starforge/live/build.py`、`starforge/live/builds/185034.json`
> - 服务层闸门：`starforge/services/__init__.py`
> - 实测记录：`docs/AGENT-INJECT-CRASH.md`（第 8、9、12、13、14 节）

---

## 0. 结论速览

| 问题 | 结论 |
|---|---|
| 它是什么 | pymhf 注入 `NMS.exe` 的 **Python Mod**，用 NMSpy 结构体读写游戏对象；**不是 DLL**，不写 `winmm.dll`，不是 PCBANKS Mod |
| 通信 | pymhf HTTP API；客户端基址 `http://127.0.0.1:5000/StarforgeAgent` |
| 端点数量 | 当前源码 **15 个**（含 `/admin/reload`；只读 GET 10 个、写入 PUT 5 个） |
| 只读 / 写入 | 只读端点显式 `GET`；写入端点 `PUT`；`/scan` 是例外（`PUT` + `mode=read/discover`） |
| 认证 | 一次性 token，通过 `?token=` 传；`auth: token-query` 表示启用，`disabled` 表示未读到 token |
| 默认写权限 | **关闭**：build `185034` 在地址书里是 `unverified`，高风险写被服务层拦住 |
| 今天实测可用 | `hello`、`player`、`system`、`planet`、`planet/scan`、`ships`、`multitool`、`freighter`、`pets` |
| 今天实测写入 | `teleport` 机制可执行、`restore` 可执行；`teleport/portal?stage=prepare_warp` 可传送到目标行星（2026-11-21）；**`teleport` 持久性未定** |
| 已知不可用 | `scan.discover`（未实现）；`teleport/portal` 的 `full` 档未测 |
| 最大风险 | 特定注入场景（每帧补绑、pymhf 直接拉起进程被 Steam 接管等）会让游戏以“模组冲突”退出；不要反复重试，也不要把个别场景推广成“一律” |

---

## 1. 它是什么

### 1.1 形态

`starforge_agent.py` 是一个 pymhf 单文件 Mod：

```text
# /// script
# dependencies = ["NMSpy==185034.0", "pymhf[http_api]==0.2.5"]
# [tool.pymhf]
# exe = "NMS.exe"
# steam_gameid = 275850
# start_exe = false
# start_paused = false
# ///
```

（`starforge/agent/starforge_agent.py:1-18`）

它运行在 `NMS.exe` 进程内，通过 NMSpy 的 `gameData`、`cGcApplication`、
`cGcPlayerState`、`cGcSolarSystem` 等结构体读取/写入游戏状态；
通过 pymhf 的 `@endpoint` 暴露本机 HTTP 端点。

**不是**：

- 不是 C/C++ DLL；
- 不是 `winmm.dll` 代理；
- 不是 `DISABLEMODS.TXT` / PCBANKS 的 pak Mod；
- 不改游戏安装目录里的 pak 文件（安装只写 `~/.starforge/agent/`）。

### 1.2 版本绑定

`starforge/live/agent_install.py:76-81` 的运行时矩阵：

```python
AGENT_RUNTIME_MANIFEST = {
    "python": "3.11.9",
    "nmspy_default": "185034.0",
    "nmspy_by_build": {"185034": "185034.0"},
    "pymhf": "0.2.5",
}
```

- Python：3.11.9（embeddable 运行时也可，关键是注入时机，见第 4 节）；
- NMSpy：必须跟游戏 build 对齐（当前 `185034.0`）；
- pymhf：`0.2.5`，需要 `pymhf[http_api]`（依赖 fastapi/uvicorn）。

安装/修复由 `install_deps()` 执行：
`pip install --upgrade NMSpy==<build>.0 pymhf[http_api]==0.2.5`
（`agent_install.py:527-572`）。
`runtime_report()` 只查 dist-info / 模块源码里的 `__version__`，**不 import** nmspy/pymhf，
避免 Windows Defender 冷启动导致“运行时明明在、却报缺少组件”的假阴性
（`agent_install.py:309-412`）。

### 1.3 线程模型

HTTP 请求不在游戏主线程执行。只读/写端点统一经过：

```python
@_game_thread
def wrapper(...):
    return self._run_on_game_thread(lambda: fn(...))
```

（`starforge_agent.py:151-156`）

请求被放进 `_game_queue`，由 `cGcApplication.Update.after` 的
`_drain_game_queue` 在游戏主线程取出执行（`starforge_agent.py:442-468`）。
因此：

- 游戏主线程忙/未进入场景时，端点会等最多 6 秒，然后返回 `E_GAME_BUSY`；
- 如果 `GcApplication` 没绑定，队列可能没人消费，表现就是“HTTP 连上了但请求超时”。

`/admin/reload` 是例外：它**没有** `@_game_thread`，直接在 HTTP 线程里安排后台重载
（`starforge_agent.py:687-719`）。

### 1.4 安装位置

| 项 | 路径 |
|---|---|
| 已安装 Mod | `~/.starforge/agent/starforge_agent.py`（或 `$STARFORGE_HOME/agent/...`） |
| 一次性 token | `~/.starforge/agent/token` |
| 启动状态 | `~/.starforge/agent/state.json` |
| 快照 | `~/.starforge/agent/snapshots.json` |
| pymhf 日志 | `~/.starforge/agent/pymhf-*.log` |
| launcher 日志 | `~/.starforge/agent/launcher.log` |

安装逻辑见 `agent_install.py:45-70`（`mod_source()` / `agent_dir()` / `installed_mod()`）
和 `agent_install.py:511-517`（`install_mod()`）。

> 注意：agent 自己解析 token/state.json 时固定用 `Path.home()/.starforge/agent`
> （`starforge_agent.py:68-88`），而安装器用 `paths.app_home()`（会读 `STARFORGE_HOME`）。
> 如果设置了 `STARFORGE_HOME`，两边可能不是同一个目录，详见第 3.4 节。

---

## 2. 端点表

客户端基址：`http://127.0.0.1:5000/StarforgeAgent`。
下表路径均为基址后的完整路径。

通用参数：

- `token`：所有端点都接受；启用认证时必填，否则返回 `E_AUTH`（HTTP 状态仍是 200，错误在 JSON 里）。

### 2.1 总表

| # | 路径 | 方法 | 主要参数 | 返回要点 | 风险 |
|---:|---|---|---|---|---|
| 1 | `/hello` | `GET` | `token` | `agent`、`nmspy`、`game_attached`、`in_game`、`multiplayer`、`auth`、`snapshots`、`capabilities`、`portal.calibrated` | 无 |
| 2 | `/player` | `GET` | `token` | `location`（`planet` 1-based、`system`、`voxel_x/y/z`、`reality`）、`ua`、`stats`、`position`、`system_name` | 只读 |
| 3 | `/system` | `GET` | `token` | `location`、`ua`、`system_name`、`planets[]`（每颗行星的基础档案） | 只读 |
| 4 | `/planet` | `GET` | `token` | 当前行星 `_planet_info`：名称、类型、天气、动植物、资源、哨兵、极端天气等 | 只读 |
| 5 | `/planet/scan` | `GET` | `token` | 当前行星完整档案：在 `/planet` 基础上加 `creature_ids`、三种物质 ID、`extra_resource_hints`、`complete`、`unsupported`、`field_errors` | 只读（服务层标 `mid`） |
| 6 | `/ships` | `GET` | `token` | `primary`、`count`、`ships[]`（`slot`/`filename`/`seed`/`type`）、`raw[]` | 只读 |
| 7 | `/admin/reload` | `PUT` | `token` | `ok`、`scheduled[]`、`note`；后台重载已加载的 starforge Mod | 中（会短暂移除/重注册端点与 hook） |
| 8 | `/teleport` | `PUT` | `glyphs`（12 位十六进制）、`galaxy`（可选，`-1`=当前）、`token` | `before`、`after`、`glyphs`、`snapshot`、`snapshot_file`、`confirmed:false`、`confirmation:"pending"` | **高** |
| 9 | `/teleport/portal` | `PUT` | `glyphs`、`galaxy`、`stage`（`warp_only`/`prepare_warp`/`full`，默认 `prepare_warp`）、`token` | `ok`、`stage`、`before`、`after`、`snapshot`；`prepare_warp` 已实测可传送到目标行星（2026-11-21） | **高 / 实验** |
| 10 | `/restore` | `PUT` | `token` | `restored`、`from_disk`、`confirmed:false`、`confirmation:"pending"` | 中高（写回位置并触发加载） |
| 11 | `/scan/instant` | `PUT` | `on`（默认 `true`）、`token` | `instant_scan`、说明“只拉满扫描条，不写发现列表” | 中（改 hook 行为） |
| 12 | `/scan` | `PUT` | `mode`（`read`/`discover`，默认 `read`）、`token` | `read` 实际返回 `/planet` 的基础字段；`discover` 未开放，只返回说明 | 读模式低；`discover` 高但禁用 |
| 13 | `/multitool` | `GET` | `token` | 6 个工具槽（`name`/`class`/`seed`/库存/`empty`）、当前槽、`raw[]` | 只读 |
| 14 | `/freighter` | `GET` | `token` | 货船名称/型号/种子/等级/库存摘要、`FleetFrigates[]`、`frigate_count` | 只读 |
| 15 | `/pets` | `GET` | `token` | `Pets[30]` 有效条目（名字/物种/描述符/6 组种子/UA/信任度）；`active` 目前 `null` + `active_supported:false` | 只读 |

### 2.2 关键端点说明

#### `/hello`

`starforge_agent.py:478-510`。它是“我连上了吗 + 游戏对象绑上了吗”的唯一握手：

```json
{
  "ok": true,
  "agent": "0.1.0",
  "nmspy": "185034.0",
  "game_attached": true,
  "in_game": true,
  "multiplayer": false,
  "auth": "token-query",
  "snapshots": "<用户目录>\\.starforge\\agent\\snapshots.json",
  "capabilities": {
    "player": true, "system": true, "planet": true,
    "planet.scan": true, "ships": true,
    "multitool": true, "freighter": true, "pets": true,
    "teleport": true, "teleport.portal": true,
    "portal.calibrated": true,
    "portal.api": {"available": true, "calibrated": true},
    "scan": "read", "scan.discover": false,
    "scan.instant": true, "restore": true
  }
}
```

容易误读的点：

- `teleport: true` 只表示“不是多人 + 代码路径存在”，**不代表 build 已验证**；
- `teleport.portal: true` 表示 API 存在**且**当前不是多人；
- `portal.calibrated: true` 表示 `prepare_warp` 路径已实机校准；`full` 仍标未测；
- `scan.discover: false` 是硬编码，不是暂时读不到；
- `game_attached` 是 `gameData.GcApplication is not None`，`in_game` 是 `player_state is not None`。

#### `/player`

`starforge_agent.py:512-544`。

- `location.planet` 是 **1-based**（`_location()` 直接取 `ga.PlanetIndex`，`starforge_agent.py:194-210`）；
- `ua` 由 `_pack_ua()` 打包，只用于展示/日志；
- `stats`：units/nanites/quicksilver/health/shield/ship_health；
- `position`：`GetNodeAbsoluteTransMatrix(player.mRootNode).pos`；
- `system_name`：`simulation.mpSolarSystem.contents.GetName()`。

加载刚触发时 `position` 可能是 `(0,0,0)`，这是瞬时值，不是传送成功/失败判据。

#### `/ships`

`starforge_agent.py:546-598`。数据源是

```python
ps.mShipResources[12]
ps.miPrimaryShip
```

字段取值要点（已实测校准，见 `AGENT-INJECT-CRASH.md` 13.2）：

- `cGcResourceElement.Seed` 是 `basic.GcSeed` 结构体，不是 int；取 `.Seed`；
- `Filename` 是 `VariableSizeString`，字符串在 `.value`；
- 空槽种子是 `0xFFFFFFFFFFFFFFFF`（-1 哨兵）；
- `slot` 是 `mShipResources` 下标，`primary` 是 `miPrimaryShip`；
- `raw[]` 保留 12 槽原始值，便于后续校准；`ships[]` 会跳过空槽。

实测 4 艘船的种子与 `<存档>` 的 `ShipOwnership` 逐位一致（见 13.2），
但**运行时 `mShipResources` 与存档层 `ShipOwnership` 不能混用**。

#### `/multitool`、`/freighter`、`/pets`：用 `SaveToData()` 读存档结构

这三个端点**不**解引用运行时 `cGcPlayerState` 的偏移。原因（`starforge_agent.py:195-210`）：
运行时 `cGcPlayerState` 是 nmspy 的 partial struct，只声明了 `mInventories`、
`mShipResources` 等字段，**没有** `Multitools` / `Pets` / `FreighterFleet`；这些字段只在
存档结构 `cGcPlayerStateData` 里。

实现方式（`starforge_agent.py:665-683`）：

```python
data = nmse.cGcPlayerStateData()
ps.SaveToData(ctypes.byref(data))   # 只写本地缓冲，不修改游戏状态
```

然后用 `Inventory.Slots.Size <= 0 and TotalPlayTime <= 0` 判断“函数没真正填充”，
避免把全零缓冲当成真实数据。每个端点返回 `source` 字段，明确写的是
`SaveToData() → cGcPlayerStateData.*`。

**`/multitool`**（`starforge_agent.py:337-416`，端点 `:1110-1128`）：

- 读 `data.Multitools[]`（6 槽），每槽含 `name`/`seed`/`model`/`class`/`slot_level`/
  `inventory`/`empty`；
- `current` 来自 `data.CurrentWeapon.Filename` + `GenerationSeed`，并反查槽位；
- 空槽把 `class`/`slot_level` 置空，避免把零值展示成“C 级”。

**`/freighter`**（`starforge_agent.py:419-566`，端点 `:1130-1148`）：

- 货船：`PlayerFreighterName`、`CurrentFreighter.Filename/Seed`、
  `FreighterInventory*`、`FreighterLayout.Level`；
- 货船槽：`FreighterFleet[8]`（固定槽，空槽过滤）；
- 舰队：`FleetFrigates[]`（动态数组），每条含 `FrigateClass`/`Race`/`Stats`/
  `TraitIDs`/`DamageTaken`/远征计数；
- 读不到的字段写 `unsupported`，不用默认值填。

**`/pets`**（`starforge_agent.py:569-662`，端点 `:1150-1168`）：

- 遍历 `data.Pets[30]`，空槽（`CreatureID` 为空）跳过；
- 每只含 `species`、`name`、`type/biome`、`predator`、`has_fur`、`trust`、`scale`、
  `ua`、`descriptors[]`、`seeds{creature, creature_secondary, species, genus,
  bone_scale, colour_base}`、`traits/moods`、`has_been_summoned`；
- **`active` 恒为 `null` 且 `active_supported:false`**：存档结构没有“当前出战”索引，
  只能读 `HasBeenSummoned`，不要把它当成“没出战”。

字段示例（值为示例，已脱敏）：

```json
{
  "ok": true,
  "count": 2,
  "current_slot": 0,
  "slots": [
    {"slot": 0, "name": "示例工具", "seed": "0x0123456789ABCDEF",
     "class": "A", "slot_level": 3, "empty": false}
  ],
  "source": "cGcPlayerState.SaveToData() → cGcPlayerStateData.Multitools[6]"
}
```

```json
{
  "ok": true,
  "freighter": {"name": "示例货船", "seed": "0x0123456789ABCDEF",
                "class": "B", "owned": true},
  "fleet_count": 1,
  "frigate_count": 3,
  "frigates": [{"slot": 0, "class": "Combat", "race": "Traders",
                "seed": "0x0123456789ABCDEF"}]
}
```

```json
{
  "ok": true,
  "count": 1,
  "pets": [{"index": 0, "species": "TREX", "name": "示例同伴",
            "type": "Dino", "biome": "Lush", "trust": 0.5, "scale": 1.2,
            "ua": "0x0011223344556677",
            "descriptors": ["_BODY_EXAMPLE"],
            "seeds": {"creature": "0x0123456789ABCDEF"},
            "has_been_summoned": true,
            "active": null, "active_supported": false}]
}
```

#### `/teleport`

`starforge_agent.py:721-755`。

流程：

1. 校验 12 位十六进制 glyphs（`_decode_glyphs()`，`starforge_agent.py:240-262`）：
   - 第 1 位行星 1..6；
   - 系统索引不能是 `000` / `FFF`；
   - Y 不能是 `0x80`；
   - X/Z 不能是 `0x800`。
2. `galaxy < 0` 时沿用当前 `reality`，否则 clamp 到 0..254；
3. **先写快照到 `snapshots.json`**；写不进去就取消传送（`E_SNAPSHOT`）；
4. 写 `player_state.mLocation.GalacticAddress` + `RealityIndex`；
5. 调 `GcApplication.StateChange("APPLOCALLOAD")`；
6. 返回 `confirmed:false / confirmation:"pending"`，由应用层轮询 `/player` 读回。

它**不是**传送门效果，只是“改 UA + 强制本地加载”。不保证落点在地表、不保证飞船/前位置同步，
也不保证存档后仍然一致。

#### `/teleport/portal`

`starforge_agent.py:838-909`（实现）与 `:1327-1367`（端点）。当前
`_PORTAL_WARP_CALIBRATED = True`，`stage` 有三档：

| stage | 行为 | 状态 |
|---|---|---|
| `warp_only` | 只设 `mTargetUA/mbActive` 后 `WarpPlayer()` | **无效**（位置不变），不崩 |
| `prepare_warp` | 先 `Prepare()` 再 `WarpPlayer()` | **已实测成功**：传送到目标行星，UA/位置改变，日志出现 `APPVIEW` |
| `full` | `OnAttached()` + `Prepare()` + `WarpPlayer()` | **未测** |

要点：

- 默认档就是 `prepare_warp`（`_PORTAL_DEFAULT_STAGE`）；
- 传送前仍先写 `snapshots.json`，写不进去就取消（`E_SNAPSHOT`）；
- 返回 `confirmed` 由服务层轮询 `/player` 决定，portal 的确认窗口是 **40 秒**
  （普通 `teleport` 是 3 秒），因为 `APPVIEW` 后 UA 更新通常要 15–25 秒；
- 服务层 `Services.warp_portal()` 仍受 build 闸门约束：默认 `E_BUILD_UNVERIFIED`，
  显式打开 `allow_unverified_agent` 后才作为实验写放行；
- `full` 档未测，不要写“三档都可用”。

证据：`[代码] starforge_agent.py:838-909`；`[代码] services/__init__.py:1058-1073`；
`[实测] docs/AGENT-INJECT-CRASH.md §14`。

#### `/restore`

`starforge_agent.py:799-821`。

- 优先用内存里的 `self._snapshot`；
- 没有则读 `snapshots.json` 的最后一条 `location`；
- 写回位置并触发 `APPLOCALLOAD`；
- 返回 `from_disk` 区分来源；
- 同样 `confirmed:false / pending`，需要读回确认。

#### `/scan` 与 `/scan/instant`

- `/scan?mode=read` **不是**完整档案：它调用 `self.planet()`，只有基础字段
  （`starforge_agent.py:838-860`）。完整档案请用 `/planet/scan`。
- `mode=discover` 不会写发现列表；代码只返回 `note: "discover 暂未开放；read 已返回实时行星字段"`。
- `/scan/instant` 只设置 `self.instant_scan`，由
  `cGcBinoculars.UpdateScanBarProgress.before` 把进度拉到 1
  （`starforge_agent.py:470-474`），不产生发现记录。
- 多人模式下 `/scan/instant` 被 `_multiplayer_block()` 拒绝。

### 2.3 GET → PUT 回退

`starforge/live/agent_client.py:117-130`：

```python
def _read(...):
    try:
        return self._call(path, method="GET", ...)
    except AgentError as e:
        if "HTTP 405" not in str(e):
            raise
        return self._call(path, method="PUT", ...)
```

原因：pymhf 0.2.5 在**没有显式声明 method** 时会把路由注册成 `PUT`。
旧版 agent 的只读端点全是 `PUT`，客户端用 `GET` 会收到 `405`。

本机日志证据：

- `pymhf-20261121T214123.log`：`GET /StarforgeAgent/hello` → `405`，
  紧接着 `PUT /StarforgeAgent/hello` → `200`；
- `pymhf-20261121T221646.log`：显式 GET 后 `GET /hello` → `200`。

因此：

- 新 agent：只读端点显式 `GET`；
- 旧 agent：客户端自动回退 `PUT`；
- 自己写脚本时，如果遇到 `405`，先试 `PUT`，不要以为端点不存在。

---

## 3. 认证

### 3.1 token 从哪里来

启动时 `agent_install.launch()` 用 `secrets.token_urlsafe(32)` 生成一次性 token
（`agent_install.py:673`），然后：

1. 写入 `~/.starforge/agent/token`（`agent_install.py:676-684`）；
2. 注入子进程环境变量 `STARFORGE_AGENT_TOKEN`（`agent_install.py:685-689`）；
3. 写入 `state.json` 的 `"token"` 字段（`agent_install.py:712-724`）。

agent 进程内按以下顺序解析（`starforge_agent.py:68-88`）：

```text
环境变量 STARFORGE_AGENT_TOKEN
  → ~/.starforge/agent/token
  → ~/.starforge/agent/state.json 的 token
```

三个都为空 → `_AGENT_TOKEN = ""` → `hello.auth = "disabled"`，所有端点**不校验 token**。
这不是“认证成功”，而是“认证未启用”。

### 3.2 `auth: token-query` 的含义

pymhf 的 endpoint 没有稳定的 request header 读取接口，所以 token 走查询参数：

```text
GET /StarforgeAgent/hello?token=<token>
PUT /StarforgeAgent/teleport?glyphs=...&galaxy=-1&token=<token>
```

`hello.auth`：

- `"token-query"`：agent 读到了 token，后续请求必须带 `?token=`；
- `"disabled"`：agent 没读到 token，不校验（只监听本机也不能当成安全）。

校验用 `hmac.compare_digest`（`starforge_agent.py:92-98`）。
缺失/错误时返回：

```json
{"ok": false, "code": "E_AUTH", "error": "agent token 无效或缺失（通过 ?token= 传递）"}
```

注意：这是 **JSON 级错误**，HTTP 状态码仍可能是 200；客户端必须看 `ok/code`。

副作用：token 会出现在本机 URL 和 pymhf/uvicorn 访问日志里
（实测日志里能看到完整的 `?token=...`）。它只适合本机短生命周期使用，
不要把日志原样发给别人。

绑定范围备注：客户端/本文约定使用 `127.0.0.1:5000`；但本机 pymhf 0.2.5 的 uvicorn
日志显示 `Uvicorn running on http://0.0.0.0:5000`。是否真的对所有网卡可达，未单独验证；
不要仅依赖“只绑 loopback”的假设，token 仍是必要防线。

### 3.3 为什么 Steam 启动时环境变量会丢

`launch()` 设置的环境变量只对**它创建的子进程**有效。
如果游戏最终是由 Steam 客户端拉起的（`steam://rungameid/275850`、或 pymhf 启动后
Steam 接管/重启进程），新进程不会继承 starforge 的 `STARFORGE_AGENT_TOKEN`，
agent 就会退化为 `auth=disabled`（代码注释见 `starforge_agent.py:60-67`；
`agent_install.py:673-684`）。

所以 token 文件是环境变量的兜底。正确现象是：

```json
{"ok": true, "auth": "token-query"}
```

如果看到 `disabled`，先查 token 文件，而不是怀疑客户端。

### 3.4 `STARFORGE_HOME` 的目录错位（代码事实）

- `agent_install.agent_dir()` 用 `paths.app_home()`，会跟随 `STARFORGE_HOME`；
- `starforge_agent._resolve_agent_token()` 固定用 `Path.home() / ".starforge" / "agent"`，
  **不读** `STARFORGE_HOME`；
- 快照 `_snapshot_path()` 又读 `STARFORGE_HOME`。

因此如果设置了 `STARFORGE_HOME`，可能出现：

- 安装器把 token 写到 `$STARFORGE_HOME/agent/token`；
- agent 却去 `~/.starforge/agent/token` 找 → 找不到 → `auth=disabled`。

规避：要么不设置 `STARFORGE_HOME`，要么把 token 同时放到
`~/.starforge/agent/token`，或直接用环境变量注入 token。
这一点未做专门回归测试，按“未验证的已知风险”处理。

---

## 4. 注入流程与已实测的坑

### 4.1 推荐顺序（按最新实测基线）

`AGENT-INJECT-CRASH.md` 13.3 给出的稳定顺序：

```text
1. Steam 正常启动游戏，停在主菜单
2. 注入 agent（pymhf）
3. 进入存档 → 触发一次 StateChange → 绑定 GcApplication
4. 读取 /hello /player /system /planet /ships
```

为什么第 3 步不能省：nmspy 的 `_INTERNAL_LoadSingletons` 用 `@one_shot`
在**下一次** `cTkFSM.StateChange` 时绑定 `gameData.GcApplication`。
如果注入时已经在存档内、又不再切状态，`GcApplication` 会一直是 `None`，
所有读取为空或超时。

### 4.2 代码实际走哪条路

`agent_install.launch(attach=True)` **默认拒绝**：

```python
if attach and os.environ.get("STARFORGE_ALLOW_ATTACH_INJECT") != "1":
    raise RuntimeError(...)
```

理由（`agent_install.py:591-610`）：实测在 build 185034 上，对已初始化的游戏进程注入
会让 `NMS.exe` 在 `python311.dll` 里访问冲突（`0xC0000005`）。
只有调试时可用 `STARFORGE_ALLOW_ATTACH_INJECT=1` 强制。

`attach=False`（应用启动）才是代码支持的路径：

```python
overrides = {
    "pid": None,
    "exe": exe,
    "start_exe": True,
    "start_paused": True,
    "steam_gameid": 275850,
    ...
}
```

（`agent_install.py:648-664`）

要点：

- `start_paused=True`：注入完成前保持进程暂停，避免“先跑起来再注入”撞上加载器锁
  （代码注释 `agent_install.py:655-659`）；
- `start_exe=True`：由 pymhf 创建/启动 `NMS.exe`；
- 启动后 `injected_game_alive()` 会等约 6 秒再检查 `NMS.exe` 是否还活着
  （`agent_install.py:740-751`）；
- 不活着就返回 `E_GAME_EXITED`，不报告“注入成功”。

### 4.3 坑 1：不要用 pymhf 直接启动 `NMS.exe`

实测（`AGENT-INJECT-CRASH.md` 10.3）：pymhf 起 `NMS.exe` 后，**Steam 会接管并重启进程**，
被注入的那个进程随即消失：没有崩溃、没有端口、agent 不可达。

这是目前代码与文档之间最大的张力：

- 文档建议“Steam 正常启动 → 再注入”；
- 但 `launch(attach=False)` 当前仍使用 `start_exe=True` 让 pymhf 启动游戏；
- `attach=True` 又被崩溃风险默认禁用。

因此现阶段没有一条“既被代码允许、又已被完整实测覆盖”的稳定路径。
实际操作时：

1. 优先按 4.1 的顺序，用 Steam 正常启动；
2. 如需注入已运行实例，只能临时设 `STARFORGE_ALLOW_ATTACH_INJECT=1`，
   并接受 `0xC0000005` 风险；
3. 如果 pymhf 启动后游戏被 Steam 重启，表现是“launcher 还在、游戏 pid 变了、
   5000 端口不可达”，不要反复重试。

> 这条“不要用 pymhf 直接启动 NMS.exe”的结论来自实测；当前 `launch()` 的
> `start_exe=True` 是否会在所有 Steam 环境触发重启，**未验证**。以现场 pid/端口为准。

### 4.4 坑 2：在存档内注入绑不上 `GcApplication`

现象：

- `hello` 返回 `game_attached: false`；
- `player/system/planet/ships` 返回空或超时；
- 游戏本身没崩，但 agent 像“没接上”。

处置：

- 进/出一次存档、开/关菜单，制造一次 `cTkFSM.StateChange`；
- 当前代码已部署 one_shot 补绑：

```python
@one_shot
@nms.cTkFSM.StateChange.after
def _bind_app_on_state_change(self, this, *args):
    if gameData.GcApplication is not None:
        return
    gameData.GcApplication = map_struct(
        get_addressof(this), nms.cGcApplication)
```

（`starforge_agent.py:429-440`）

状态：**已实现、待自然场景复验**。
即：代码路径存在，但没有在“注入时已在存档、随后只做正常游戏操作”的完整自然场景里
反复验证过；不要把它当成“注入顺序完全无所谓”的证明。

### 4.5 坑 3：每帧 hook 会把游戏弄崩（已回退）

曾经在 `cGcApplication.Update.before` 里每帧检查并 `map_struct` 补绑。
`AGENT-INJECT-CRASH.md` 13.1 的二分结果：

| 版本 | 结果 |
|---|---|
| 带每帧补绑 | 注入后游戏以“模组冲突”退出（无 dump） |
| **去掉每帧补绑** | 注入 2 秒可达，进入存档后读取正常，游戏持续存活 |

日志侧面证据：带补绑的版本里，`cGcApplication found / 延迟绑定成功` 一次都没打印，
说明 hook 要么没注册成功，要么在错误的 `this` 上解析。

**已回退**。源码只保留 `cTkFSM.StateChange.after` 的 one_shot，不要重新引入
“每帧 map_struct”。

### 4.6 坑 4：部分注入场景会被识别为“模组冲突”并退出

`AGENT-INJECT-CRASH.md` 第 12 节记录的现象（**特定场景**：每帧补绑 hook 版本、
`pymhf` 直接拉起 `NMS.exe` 被 Steam 接管等；不是所有注入都会触发）：

现象：

- 游戏内弹出 No Man's Sky 错误框：
  “禁用模组 / 崩溃ID: 185034M_-ctypes@0x63980D_… / 检测到潜在模组冲突问题 /
  是否禁用所有模组以解决问题?”；
- 游戏退出后：**无崩溃转储**、**无 Application Error 事件**、**不写 `DISABLEMODS.TXT`**；
- 退出前 HTTP 服务是可用的（日志里有 200 响应和 `New State`）。

含义：

1. 在这些场景里，不是只靠调 `start_paused`/Python 版本就能绕过（但 §4.5 的对照显示：
   去掉每帧补绑后，attach 到已运行实例可存活——所以不能推广成“NMS 一律关闭注入”）；
2. 触发方是游戏侧检测；
3. 不应在玩家真实游戏上反复触发。

代码处置：`launch()` 在 Popen 后观察约 6 秒，进程不在就返回：

```json
{"ok": false, "code": "E_GAME_EXITED",
 "error": "注入后游戏进程已退出：NMS 会把注入的 Python/ctypes 识别为模组冲突并关闭游戏…"}
```

（`agent_install.py:729-737`）

不要自动重试。重试只会再触发一次检测。

### 4.7 坑 5：端口固定 5000

pymhf 当前固定 5000（`agent_client.DEFAULT_PORT`，`agent_install.py:134-148`）。
`STARFORGE_AGENT_PORT` 只是记录来源并在启动前做冲突检测，
**不保证 pymhf 真的换端口**（代码注释 `agent_install.py:134-139`、`630-642`）。

端口被占时：

- `launch()` 先判断是不是上一次的 starforge agent；是则复用现有 token；
- 不是则报错，要求关闭占用进程或设置端口（需要 runtime 支持）。

---

## 5. 能力矩阵

判定口径：

- **已实测**：本机 build 185034 上实际返回过数据/成功；
- **未验证**：代码存在，但没有足够的实机证据；
- **已知不可用**：代码明确拒绝或未实现。

| 能力 | 状态 | 证据 / 说明 |
|---|---|---|
| `hello` | 已实测 | 2026-11-21 22:43/22:51 日志 `GET /hello` 200；返回 `game_attached/in_game` |
| `player` | 已实测 | 22:49:40 `GET /player` 200；UA/星系/位置/货币可读 |
| `system` | 已实测 | 22:49:40 `GET /system` 200；返回行星表 |
| `planet` | 已实测 | 22:49:40 `GET /planet` 200 |
| `planet/scan` | 已实测 | 22:49:40 `GET /planet/scan` 200；返回 `PlanetInfo` + 物质/生物/额外资源 |
| `ships` | 已实测 | 22:43/22:52 `GET /ships` 200；4 艘船与 `<存档>` 的 `ShipOwnership` 种子逐位一致（13.2） |
| `multitool` | 已实测 | `GET /multitool` 返回 6 槽；`SaveToData() → cGcPlayerStateData.Multitools` |
| `freighter` | 已实测 | `GET /freighter` 返回货船/固定槽/`FleetFrigates`；字段缺失会进 `unsupported` |
| `pets` | 已实测 | `GET /pets` 返回 `Pets[30]` 有效条目；`active=null` 是结构限制，不是“未出战” |
| `teleport` | 机制已实测，持久性未定 | 21:51:58 `PUT /teleport` 200；`before.planet=0 → after.planet=1`；快照写入（示例 glyphs 见 §2） |
| `restore` | 已实测 | 21:52:20 `PUT /restore` 200；读回与快照一致 |
| `teleport/portal` | **`prepare_warp` 已实测** | 2026-11-21 23:0x：传送到目标行星，UA/位置改变，日志有 `APPVIEW`；`warp_only` 无效；`full` 未测。服务层仍受 build 闸门约束 |
| `scan`（read） | 已实测 | 21:51:58 `PUT /scan?mode=read` 200；返回基础行星字段（不是完整档案） |
| `scan.discover` | **已知不可用** | `hello.scan.discover=false`；代码只返回说明，不写发现列表；服务层也不放行 |
| `scan.instant` | 未验证 | 代码/hook 存在，但没有“扫描条立即完成”的独立实测记录；多人下禁用 |
| 多人检测 | 部分实测 | `hello.multiplayer=false` 正常；`true` 分支没有完整实机样本；代码在 `mbMultiplayerActive` 读取失败时按单人处理 |
| build 验证 | **未完成** | `builds/185034.json` 的 `status` 是 `unverified`；`write_allowed=false`。“实机可用”≠“地址书已验证” |
| 注入后长期稳定 | 未验证 | 有“存活 120 秒”记录（第 8 节），也有特定场景“模组冲突退出”记录（第 12 节）；不能承诺长期稳定 |
| 修改已有端点后热重载 | 已实测 | 2026-11-21 22:51 日志 `Removed 12 endpoints` → `Finished reloading` → 后续 GET 200；端点集合变化以 `hello` 实际返回为准 |

### 5.1 `teleport` 的持久性

`AGENT-INJECT-CRASH.md` 第 9 节的观察：

- 传送后立即读 `/player` 的 `position` 是 `(0,0,0)`，属于加载中的瞬时值；
- 下一次读 `/player` 时 `planet` 又回到 0；
- 说明“写位置 + 触发加载”的持久性依赖游戏自身加载流程；
- `confirmed: true` 只代表应用层短时间轮询读回一致，不代表长期/存档后仍然一致。

因此：

- 可以把它当“强制重载到目标 UA 的尝试”；
- 不能把它当“传送门效果”；
- 失败/异常时用 `/restore`，但 restore 本身也是“写位置 + 触发加载”，同样是 pending。

### 5.2 `ships` 的字段取值

已实测 4 条（13.2）。具体种子是该存档的派生数据，文档不复录；结构如下（种子为示例）：

```text
slot=0   <模型 A>.SCENE.MBIN           0x0123456789ABCDEF
slot=1   SENTINELSHIP_PROC.SCENE.MBIN  0x0123456789ABCDEF
slot=2   SENTINELSHIP_PROC.SCENE.MBIN  0x0123456789ABCDEF
slot=3   <模型 B>.SCENE.MBIN           0x0000000000000006   (primary=3，示例)
```

注意：

- 种子值可以很小（示例 `0x0000000000000006`）也是合法值，不要用“值小”判断空槽；
- 空槽判断看 `seed == 0xFFFFFFFFFFFFFFFF` 或 filename 为空；
- `type` 由文件名 token 推断（`_MODEL_TOKENS`，`starforge_agent.py:175-191`），
  不是游戏内权威船型。

---

## 6. 热重载

### 6.1 用法

端点：`PUT /StarforgeAgent/admin/reload?token=<token>`
（`starforge_agent.py:687-719`；客户端 `agent_client.py:161-163`）。

标准流程：

```text
1. 修改 starforge/agent/starforge_agent.py
2. 调 starforge.live.agent_install.install_mod() 把源码写到 ~/.starforge/agent/
3. PUT /StarforgeAgent/admin/reload
4. 等几秒，重新 GET /hello 确认新版本/新逻辑
```

### 6.2 实现与限制

- 找 `mod_manager.mods` 里 key 含 `"starforge"` 的项；
- 找不到返回 `{"ok": false, "error": "没找到 starforge mod", "mods": [...]}`；
- 用后台线程 `time.sleep(0.4)` 后逐个 `mod_manager.reload(key)`；
- 0.4 秒是为了避免把正在返回响应的这次请求一起卸载；
- 返回 `scheduled` 列表，不代表已经完成；
- 重载期间不要并发调用其它端点。

本机实测日志（`pymhf-20261121T224304.log`）：

```text
22:51:31 PUT /StarforgeAgent/admin/reload?token=... 200
22:51:31 pymhf.core.http_api  INFO Removed 12 endpoints and 0 websockets for the mod StarforgeAgent
22:51:31 pymhf.core.mod_loader INFO Finished reloading StarforgeAgent
22:51:31 starforge.agent INFO 已热重载 StarforgeAgent
22:51:49 GET /StarforgeAgent/hello?token=... 200
22:52:05 GET /StarforgeAgent/player?token=... 200
22:52:05 GET /StarforgeAgent/ships?token=... 200
```

结论：

- **修改已有端点逻辑**：可靠，已经实测；
- **端点数量变化（新增/删除）**：pymhf 会移除并重注册路由，但“新增端点是否稳定生效”
  没有独立验证；以实测为准，必要时重启游戏；
- `/admin/reload` 本身不经过游戏主线程，所以即使游戏线程忙也能调用；
- 重载后 token 会重新按环境变量 → token 文件 → state.json 解析；
- 如果热重载后 `hello` 404/405，先确认 `install_mod()` 是否真的写了新文件，
  再考虑重启，不要连续狂调 reload。

---

## 7. 安全闸门

### 7.1 三层闸门

```text
agent 进程内：token + 多人检查 + 写前快照
        ↓
AgentClient：命令白名单 + GET→PUT 回退
        ↓
Services：build 闸门 + allow_unverified_agent + 多人闸门
```

### 7.2 build 闸门

`starforge/live/build.py:230-255`：

- `build.summary()` 读地址书；
- 只有 `status == "verified"` 才 `write_allowed=True`；
- 未知 build / `unverified` 都只允许只读；
- 返回 `reason` 说明原因。

当前 `builds/185034.json`：

```json
{"build": "185034", "status": "unverified",
 "notes": "签名/偏移待实机校准；在此之前只允许只读能力。"}
```

所以默认情况下，即使 `hello.capabilities.teleport == true`，
服务层仍会拒绝高风险写，返回：

```json
{"ok": false, "code": "E_BUILD_UNVERIFIED",
 "error": "这版未验证（build 185034-...，status=unverified）：只允许只读能力"}
```

（`services/__init__.py:1018-1036`）

应用侧读取状态/能力时：

- `Services.agent_status()` → `agent_install.status()`，返回 `game_running`、`pid`、
  `mod_installed`、`nmspy_ok`、`runtime_ready`、`runtime_mismatches`、`reachable`、
  `hello`、`build`、`agent_base`、`launcher_log`、`snapshots` 等
  （`agent_install.py:419-479`）；
- `Services.live_capabilities()` 把 `hello.capabilities` 与 build/多人闸门合并，
  返回 `attached`、`reachable`、`note`、`capabilities`、`status`、`build`、
  `multiplayer`、`write_allowed`；每个能力额外带 `blocked_by`（`build`/`multiplayer`）
  （`services/__init__.py:910-973`）。

所以界面应看 `live_capabilities()` 的结果，而不是直接相信 `hello.capabilities`。

### 7.3 `allow_unverified_agent`

设置项默认 `False`（`core/settings.py:27,80`）。

显式打开后：

- 允许在未验证 build 上测试的实验性写：
  `teleport`、`restore`、`scan.instant`、`teleport.portal`
  （`services/__init__.py:24-28`）；
- **`scan.discover` 仍不放行**（会写发现列表，见 7.5）；
- 多人模式仍然一律拒绝；
- 这是“测试开关”，不是“已验证”。测试完应恢复 `False`。

### 7.4 多人闸门

agent 侧：

```python
app = gameData.GcApplication
return bool(getattr(app, "mbMultiplayerActive", False))
```

（`starforge_agent.py:213-226`）

多人时拒绝：

- `/teleport`
- `/teleport/portal`
- `/restore`
- `/scan/instant`
- `/scan?mode=discover`

返回：

```json
{"ok": false, "code": "E_MULTIPLAYER", "multiplayer": true,
 "error": "多人模式已启用：传送/还原/扫描写操作被禁用"}
```

服务层还会在每次高风险调用前 `hello` 一次，看到 `multiplayer=true` 就本地拒绝
（`services/__init__.py:1037-1046`）。

注意：`mbMultiplayerActive` 读取失败时 agent 按单人处理（代码注释 `starforge_agent.py:213-214`）。
这是已知风险；真正的写操作还有 build 闸门，但不能把“读不到”当成“确定单人”。

### 7.5 `scan.discover` 为什么禁用

- `hello` 硬编码 `"scan.discover": False`（`starforge_agent.py:508`）；
- `/scan?mode=discover` 不写发现，只返回说明（`starforge_agent.py:838-860`）；
- 服务层把 `scan.discover` 列为高风险，且不在 `_EXPERIMENTAL_WRITE_CAPABILITIES`
  里（`services/__init__.py:21-28`）；
- 根本原因：`cGcDiscoveryManager` 的 manager 指针/完整 `cGcDiscoveryData` 未校准，
  写错会污染发现列表/成就（历史调研见 `archive/INGAME-SCAN-FEASIBILITY-2026-11-18.md` 第 3.3、6.3 节）。

### 7.6 快照与回滚

`/teleport` 在写入前调用 `_persist_snapshot()`：

- 写 `~/.starforge/agent/snapshots.json`；
- 最多保留 20 条；
- 原子写 + `0600` 权限；
- 写失败就取消传送（`E_SNAPSHOT`），不会“先写了再说”。

但：

- 这不是自动回滚。`/restore` 需要手动调用；
- `restore` 也是写位置 + 触发加载，不是“读存档回滚”；
- 传送失败/掉出世界时，优先恢复存档备份，不要只依赖 `/restore`。

---

## 8. 故障排查表

| # | 症状 | 可能原因 | 下一步 |
|---:|---|---|---|
| 1 | 客户端报“连不上游戏内 agent”/`URLError` | agent 未注入；游戏已退出；5000 被占；base 不是 `127.0.0.1:5000` | 看 `agent_install.status()` 的 `reachable/game_running/pid`；看 `pymhf-*.log` 最后几行；确认端口占用 |
| 2 | `launch()` 返回 `E_GAME_EXITED` | 游戏把注入识别为“模组冲突”并主动退出；无 dump、不写 `DISABLEMODS.TXT` | 不要反复重试；改用离线通道；记录 `pymhf` 日志时间点 |
| 3 | `hello.auth` 是 `disabled` | Steam 启动丢了环境变量；token 文件没写/路径不对；`STARFORGE_HOME` 目录错位 | 检查 `~/.starforge/agent/token` 和 `state.json`；确认 agent 读的是 home 路径；重新 `launch()` 生成 |
| 4 | 返回 `E_AUTH` | 客户端用了旧 token / 没带 token / 请求 URL 漏了 `?token=` | 用当前 `state.json` 的 token；热重载后重新读取；不要把 token 贴到公开日志 |
| 5 | `game_attached:false`、`in_game:false`，或请求 `E_GAME_BUSY` 超时 | 注入时已在存档且未发生状态切换；`GcApplication` 没绑定；游戏线程没在跑 Update | 进/出一次存档或开关菜单触发 `cTkFSM.StateChange`；再 `GET /hello`；仍不行则重启注入流程 |
| 6 | 只读端点 `405` | 旧 agent 把未声明 method 的路由注册成 `PUT` | 客户端会自动 GET→PUT 回退；手写脚本直接试 `PUT`；升级/重装 agent 后恢复 `GET` |
| 7 | `/ships` 返回空列表或 `count` 不对 | 没进存档；槽位为空；数组遍历未校准 | 看 `raw[]` 的 12 槽；空槽种子是 `0xFFFFFFFFFFFFFFFF`；确认 `primary` 与游戏内主船一致 |
| 8 | 写操作返回 `E_BUILD_UNVERIFIED` | `builds/185034.json` 是 `unverified`，默认只读 | 只做只读；确需测试时显式打开 `allow_unverified_agent`，并先备份存档；`scan.discover` 仍不可用 |
| 9 | 写操作返回 `E_MULTIPLAYER` | `mbMultiplayerActive=true` | 退出多人/关闭多人 session；只读能力仍可用；不要绕过闸门 |
| 10 | `teleport` 返回 `confirmed:false`，或读回 `planet` 又变回去、`position=(0,0,0)` | 加载中的瞬时值；写位置 + `APPLOCALLOAD` 的持久性依赖游戏加载流程 | 等加载完再读 `/player`；不要凭一次读回断言成功；异常时 `/restore` 或恢复存档备份 |
| 11 | `/admin/reload` 报“没找到 starforge mod”/重载后 404 | 安装文件没更新；mod key 不匹配；新增端点未稳定注册 | 先 `install_mod()` 写盘；再 reload；看 `pymhf` 日志的 `Removed ... endpoints`；必要时重启游戏 |
| 12 | 启动时报端口 5000 被占 | 其它进程占用；上一次 agent 还在 | 先判断是否可复用现有 agent；否则关闭占用进程；`STARFORGE_AGENT_PORT` 仅在 runtime 支持时生效 |

真实日志对应：

- 405 → PUT 回退：`pymhf-20261121T214123.log`；
- 延迟绑定：`pymhf-20261121T223903.log` 的 `延迟绑定 cGcApplication 成功`（旧版日志文案）；
- 当前只读全通：`pymhf-20261121T224304.log` 的 22:49:40 四条 GET；
- 热重载：同一文件 22:51:31 `Removed 12 endpoints` → `Finished reloading`；
- 崩溃转储：`%LOCALAPPDATA%\CrashDumps\NMS.exe.<pid>.dmp`（早期注入崩溃共三份，
  具体 PID/时间为本机运行信息，文档不复录；第 12 节记录的模组冲突退出没有新 dump）。

---

## 9. 与旧文档的差异（作废声明）

| 旧说法 | 现状 | 依据 |
|---|---|---|
| “agent 是进程内 DLL”“卸载时完整还原 `winmm.dll`” | 实际是 pymhf Python Mod，不写 `winmm.dll`，卸载只需删除/停止注入 | `AGENT.md` 第 3、6 节；`starforge_agent.py:1-35` |
| 命名管道 `\\.\pipe\starforge-agent-v1`、JSON 行帧 | 实际是 HTTP `127.0.0.1:5000/StarforgeAgent`，GET/PUT + query token | `archive/AGENT-PROTOCOL-2026-11-18.md` 第 1 节；`agent_client.py:1-10` |
| “进游戏存档，点注入并连接 → pymhf 注入正在运行的 NMS.exe” | `attach=True` 默认被拒绝（实测 `0xC0000005`）；支持路径是 `start_paused` 注入，且注入后需要一次状态切换绑定 `GcApplication` | `agent_install.py:591-610`；`AGENT-INJECT-CRASH.md` 第 1、8、13.3 节 |
| “`_late_bind_app` 每帧补绑，所以注入顺序无所谓” | 每帧 hook 已回退；现在用 `@one_shot @cTkFSM.StateChange.after`，且标注“已实现、待自然场景复验” | `AGENT-INJECT-CRASH.md` 10.1 vs 13.1；`starforge_agent.py:420-440` |
| “`planet.scan` 属于高风险，会被 build 闸门降级” | 当前 `_HIGH_RISK_CAPABILITIES` 不包含 `planet.scan`；它是只读 `mid` | `services/__init__.py:21-23,940-942`；归档旧文仅作历史对照，不作当前依据 |
| “`/teleport/portal` 校准后会返回 `ok:true`（即使 `confirmed:false`）” | **已实测**：`stage=prepare_warp` 会真正传送到目标行星（UA/位置改变，日志有 `APPVIEW`）；`warp_only` 无效果；`full` 未测。服务层仍受 build 闸门约束 | `starforge_agent.py` `_portal_warp`；`AGENT-INJECT-CRASH.md` 第 14 节 |
| “所有写操作写后校验，失败自动回滚” | `teleport/restore` 只做快照 + 触发加载；`restore` 要手动调；返回 `confirmed:false/pending`，没有自动回滚 | `starforge_agent.py:740-752,815-819`；`AGENT.md` 第 6 节 |
| “只读端点全是 PUT；共 11 个端点” | 当前 15 个端点，只读显式 GET；客户端保留 405→PUT 回退兼容旧 agent | `starforge_agent.py` 的 15 处 `@endpoint`；`agent_client.py` |
| “pymhf 不能直接启动 NMS.exe” | 实测确实可能被 Steam 接管控权重启；但当前 `launch(attach=False)` 仍用 `start_exe=True`，两者存在张力，需现场以 pid/端口判断 | `AGENT-INJECT-CRASH.md` 10.3；`agent_install.py:648-664` |
| “多人时传送/建造/扫描奖励全部禁用；能检测其他玩家在线” | 当前只读 `mbMultiplayerActive`，没有“其他玩家数量”检测；只读端点仍允许 | `starforge_agent.py:213-226`；`AGENT.md` 第 6 节 |

---

## 10. 最小验证清单

只做只读、不改游戏状态：

```text
1. GET /StarforgeAgent/hello           → ok=true, game_attached/in_game 符合预期
2. GET /StarforgeAgent/player          → location.planet 1..N，ua 非空
3. GET /StarforgeAgent/system          → planets[] 非空
4. GET /StarforgeAgent/planet          → 当前行星名称/类型/天气
5. GET /StarforgeAgent/planet/scan     → complete=true 或明确的 unsupported[]
6. GET /StarforgeAgent/ships           → primary 在 0..11，ships[] 与游戏内一致
```

写入前必须额外确认：

```text
- hello.auth == "token-query"（不是 disabled）
- hello.multiplayer == false
- build.summary().write_allowed == true，或你明确打开了 allow_unverified_agent
- 已备份存档
- teleport 的 glyphs 是 12 位合法十六进制
- 失败时知道怎么用 /restore 或恢复存档
```

---

## 11. 证据索引

| 证据 | 位置 |
|---|---|
| 注入时机 / `start_paused` | `docs/AGENT-INJECT-CRASH.md` 第 8 节 |
| 写通道实测（scan/teleport/restore） | 同文件第 9 节 |
| 模组冲突退出 | 同文件第 12 节 |
| 每帧 hook 二分 / `/ships` 校准 / 稳定顺序 | 同文件第 13 节 |
| portal 三档（`warp_only`/`prepare_warp`/`full`） | 同文件第 14 节 |
| 端点实现 | `starforge/agent/starforge_agent.py` |
| 启动/运行时/状态 | `starforge/live/agent_install.py` |
| 客户端与 405 回退 | `starforge/live/agent_client.py` |
| build 指纹与写闸门 | `starforge/live/build.py`、`builds/185034.json` |
| 服务层闸门 | `starforge/services/__init__.py:21-31, 910-1053` |
| 运行日志 | `~/.starforge/agent/pymhf-*.log` |
| 崩溃转储 | `%LOCALAPPDATA%\CrashDumps\NMS.exe.<pid>.dmp` |

> 本文不包含任何真实 token、存档内容或账号信息。日志里的 `?token=` 属于本机一次性凭据，
> 对外粘贴前请先脱敏。
