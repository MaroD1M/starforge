# 游戏内代理协议（Agent IPC）· v1 草案

> 目的：把「UI 想读/想写游戏内东西」和「真正在游戏进程里的 DLL」之间的接口**先定死**，
> 这样 Python 侧和 C++ 侧可以并行开发，Windows 实机验证时只需按本文对表。
> 对应 PLAN-V4 的 M4；本文件是契约，改它必须同时改两侧与 `handbook/06` 的 T 专题。
>
> **当前实现说明（2026-11）**：已改用 **pymhf + NMSpy** 注入 Python Mod，
> 通信是 `http://127.0.0.1:5000/StarforgeAgent` 的 JSON GET/PUT，不是下面的命名管道。
> 本文件保留为未来编译型 agent（更低注入痕迹/更高性能）的协议草案；命令表可复用。

---

## 1. 传输与帧格式

| 项 | 约定 |
|---|---|
| 传输 | Windows 命名管道 `\\.\pipe\starforge-agent-v1`；单客户端（应用独占） |
| 编码 | UTF-8 JSON，一行一帧，`\n` 结尾；单帧上限 4 MiB |
| 方向 | 应用→代理：请求；代理→应用：响应（同 `id` 回） |
| 超时 | 应用侧 5 s（写类命令 15 s）；超时即视为失败，**不重试写命令** |

请求：
```json
{"v":1,"id":"c1a2","cmd":"player.ua","args":{}}
{"v":1,"id":"c1a3","cmd":"ship.write_seed","args":{"slot":2,"type":"sentinel","seed":"0x0123456789ABCDEF"},"risk":"mid"}
```

响应：
```json
{"v":1,"id":"c1a2","ok":true,"data":{"ua":"0x0011223344556677","coords":"<coords 示例>","glyphs":"123456789ABC"},"ms":3}
{"v":1,"id":"c1a3","ok":false,"err":"E_SIGNATURE_MISSING","msg":"这版游戏没找到写飞船的签名","ms":11}
```

---

## 2. 握手与能力协商

1. 应用连上后先发 `hello`，带自身 `proto` 与 `app` 版本。
2. 代理回 `hello`：`proto`、`agent` 版本、`game_build`（`NMS.exe` 指纹）、`capabilities` 表。
3. **主版本不等即断开**（避免错配去写内存）；次版本不等时以代理能力表为准。
4. 能力表每项：`{"available":true|false,"reason":"...","risk":"low|mid|high","experimental":true|false}`。

```json
{"v":1,"id":"h1","cmd":"hello","args":{"proto":1,"app":"0.13.0"}}
{"v":1,"id":"h1","ok":true,"data":{
  "proto":1,"agent":"1.0.0","game_build":"NMS-5.x-1a2b3c4d",
  "capabilities":{
    "player.ua":            {"available":true,"risk":"low"},
    "player.position":      {"available":true,"risk":"low"},
    "system.current":       {"available":true,"risk":"low"},
    "planet.current":       {"available":true,"risk":"low"},
    "ship.read":            {"available":true,"risk":"low"},
    "ship.write_seed":      {"available":true,"risk":"mid"},
    "ship.write_class":     {"available":true,"risk":"mid"},
    "ship.write_parts":     {"available":false,"reason":"本版部件数组布局未确认","risk":"high","experimental":true},
    "teleport.system":      {"available":true,"risk":"high"},
    "teleport.position":    {"available":false,"reason":"落点预检不可用","risk":"high"},
    "scan.planet":          {"available":true,"risk":"mid"},
    "scan.discover":        {"available":false,"reason":"未验证","risk":"high","experimental":true},
    "debug.flags":          {"available":false,"reason":"未验证","risk":"high","experimental":true}
  }}}
```

---

## 3. 命令表 v1

> `risk`：low=只读；mid=可回滚的写（效果局限在船/存档对象）；high=改世界状态或不可预期。
> 所有写命令在代理侧**必须**先做快照（原值），并在响应里返回 `snapshot` 句柄，供 `restore` 使用。

| 命令 | 参数 | 返回 | risk | 备注 |
|---|---|---|---|---|
| `hello` | `proto, app` | 能力表 | — | 见上 |
| `ping` | — | `{pong:true}` | low | 连接存活 |
| `capabilities` | — | 同 hello | low | 可随时刷新（游戏切场景后重解析） |
| `player.ua` | — | `{ua, coords, glyphs, galaxy}` | low | 玩家当前系统 |
| `player.position` | — | `{x,y,z,planet,ua}` | low | 世界坐标 |
| `player.stats` | — | `{units,nanites,quicksilver,health}` | low | 只显示 |
| `system.current` | — | `{ua, ships[], planets[], dissonant, interceptor}` | low | 结构与 `system.system()` 对齐 |
| `planet.current` | — | `{index, biome, weather, sentinels, flora, fauna, resources[]}` | low | 游戏内实时值 |
| `ship.read` | `{slot}` | `{type, seed, class, stats{}, parts[]}` | low | |
| `ship.write_seed` | `{slot, type, seed}` | `{ok, readback}` | mid | 同型校验由应用侧先做 |
| `ship.write_class` | `{slot, class, values?, best?}` | `{ok, readback}` | mid | 区间校验在应用侧 |
| `ship.write_parts` | `{slot, parts[]}` | `{ok, readback}` | high | **实验性**，部件 id 必须存在于 catalog |
| `teleport.system` | `{ua}` | `{ok, ua_after, snapshot}` | high | 星系跳转；应用侧先备份存档 |
| `teleport.position` | `{x,y,z,planet}` | `{ok, snapshot}` | high | **实验性**，默认关闭 |
| `scan.planet` | `{mode:"read"\|"discover"\|"reward"}` | `{entries[], written}` | mid | `reward` 需 `experimental:true` |
| `debug.flags` | `{flags{}, on}` | `{ok, snapshot}` | high | **实验性** |
| `restore` | `{snapshot}` | `{ok}` | mid | 用快照句柄还原原值 |
| `overlay.ping` | — | `{visible, fps}` | low | 菜单状态 |

### 应用侧白名单（硬约束）

UI **不得**直接调 `ctypes`/内存，只能走 `AgentClient.call(cmd, args)`；
`AgentClient` 只放行上表命令，未知命令本地即拒（`E_UNKNOWN_CMD`），不发到代理。

---

## 4. 错误码

| 码 | 含义 | 应用侧动作 |
|---|---|---|
| `E_UNKNOWN_CMD` | 命令不在白名单 | 报缺陷，不重试 |
| `E_NO_GAME` | 进程不存在 | 界面显示"未连接"，等用户启动游戏 |
| `E_SIGNATURE_MISSING` | 该版游戏没找到签名 | 标该能力不可用，提示"这版未验证" |
| `E_AMBIGUOUS` | 签名多处命中且无法排序 | **宁可不写**，提示用户升级/回报 |
| `E_VERIFY_FAILED` | 写后读回不符 | 自动 `restore` 快照，报失败 |
| `E_MULTIPLAYER` | 检测到多人 session | 屏蔽 high risk 命令 |
| `E_EXPERIMENTAL_OFF` | 实验性能力未开启 | 引导到设置页开关 |
| `E_BAD_ARGS` | 参数非法 | 前端校验提示 |

---

## 5. 安全与日志

1. 每次写命令在代理侧记一行：`ts, cmd, args 摘要（种子/坐标进日志，长数组只记长度）, snapshot 句柄, 结果`。
2. 日志写到 `%LOCALAPPDATA%\starforge\logs\agent-<game_build>.log`，滚动 5 份。
3. **不记录**玩家账号名、邮箱、存档路径以外的个人信息；不上传任何数据。
4. 多人 session 检测：`system.current` 返回 `players_other>0` 时，应用侧把 high risk 命令全部变灰。

---

## 6. 版本路线

| 阶段 | 目标 |
|---|---|
| v1（M4） | `hello`/`ping` + 只读 5 条（`player.ua`、`player.position`、`system.current`、`planet.current`、`ship.read`） |
| v1.1（M5） | `teleport.system` + `snapshot/restore` |
| v1.2（M6） | `scan.planet` read/discover |
| v1.3（M7） | `ship.write_seed/class/parts`、`debug.flags` |
| v2 | 叠加菜单命令通道（`overlay.*`）、事件推送（`event.bus` 单向流） |

---

## 6.5 当前实现状态（避免把"有入口"当成"有代理"）

| 项 | 状态 |
|---|---|
| 协议文本（本文件） | ✅ 定稿 v1 草案 |
| `starforge agent hello` | ✅ **已有**：打印 13 项能力表（全部 `available=false` + `reason`），stdout 纯 JSON；Windows 上会先尝试 `mem.attach("NMS.exe")` 并如实报告 `attached` |
| agent DLL（`hello` 的真实对端） | ⬜ M4 待开发（C/C++，独立目录，不进 Python 包） |
| 命名管道服务端 | ⬜ M4 |
| 安装/卸载器 | ⬜ M4（备份 `winmm.dll` → 放代理 → manifest；卸载可完全还原） |

实机操作单见 `docs/VERIFY-AGENT-WINDOWS.md`。

## 7. 对表清单（Windows 实机第一轮要产出）

- [ ] `game_build` 指纹算法跑通，两个 build 的值不同
- [ ] `hello` 成功，能力表 13 项都给出 available/reason
- [ ] `player.ua` 与应用里"当前星系"一致（人工对照截图）
- [ ] `system.current` 的 50 条船池与离线 `system.system()` 一致率 ≥ 95%
- [ ] 断开游戏后应用 1 s 内显示"未连接"，不卡死
- [ ] 日志落在预期目录、体积可控
