# 发布前敏感信息与误导性内容审查（2026-11）

> 审查时点：2026-11-21（工作区版本以 `starforge/__init__.py` 为准）。
> 审查方式：**只读扫描**；没有启动游戏、没有注入、没有读写游戏进程内存、没有执行打包。
> 本轮只修改了两个文件：`.gitignore` 与本文。文档与代码中的问题**只列清单、不就地改**，由文档代理统一处理，避免并发覆盖。
> 行号说明：扫描期间其他代理仍在编辑文档，行号可能漂移；**请按“文件 + 片段/章节”定位**。
>
> **处理状态（2026-11-22）**：`docs/` 下的本机路径、存档派生数据、dump/PID 已按本报告
> §5 脱敏；`CHANGELOG.md` 与根 `README.md` 不在本轮“只改 docs/”的范围内，仍未处理，
> 发布前需单独复核。结构性事实（空槽哨兵 `0xFFFFFFFFFFFFFFFF`、`0xC0000005` 等错误码、
> 字段名/槽位数）保留。

---

## 0. 结论

- 未发现真实凭据（GitHub token、`gho_`、真实 agent token、`?token=<值>` 明文）。仓库中的 `token=` / `STARFORGE_AGENT_TOKEN` 都是**参数名或文档说明**，不是凭据值。
- 未发现 SteamID（17 位）、邮箱地址或账号密码。
- 主要风险是 **文档里的本机路径、真实存档派生数据（种子/UA/坐标/星系名）和崩溃 dump 的 PID/时间线**；这些内容会随 `git add -A` 一起进远端。
- `.gitignore` 原先已覆盖 `artifacts/`、`NMS存档/`、`*.hg`，但**漏了 `*.dmp`、`.starforge/`、`agent-runtime/`、`*.log`、`.ruff_cache/`、`.env`**；本轮已补齐，并验证不会误伤 `starforge/live/assets/icons/*.dds` 与 `starforge/live/builds/*.json`。
- 当前文档索引与 `archive/` 的关系基本正确：现行文档没有把归档文档当“当前依据”；遗留问题集中在归档文档内部的旧链接，以及 `docs/AUDIT-2026-11.md` 对已重命名文件的引用。

---

## 1. 扫描范围与方法

### 1.1 范围

- 仓库全部受版本控制与未跟踪文本文件（217 个，排除 `.git/`）。
- 目录：`starforge/`、`tests/`、`scripts/`、`packaging/`、`.github/`、`docs/`（含 `docs/archive/`、`docs/research/`）、根目录文档与配置。
- 运行产物目录（若存在）：`artifacts/`、`NMS存档/`、`.starforge/`、`agent-runtime/`、`build/`、`dist/`、缓存目录。本次扫描时仓库内**不存在**这些目录（`starforge/live/builds/` 是源码数据目录，不是运行产物）。

### 1.2 方法

1. 全仓文本匹配：
   - 本机路径：盘符路径、`%LOCALAPPDATA%`、`%USERPROFILE%`、旧工作区路径。
   - 凭据：`gho_`、`ghp_`、`github_pat_`、`sk-`、`token=<长值>`、`STARFORGE_AGENT_TOKEN=<值>`、`Authorization: Bearer <值>`、`password=`。
   - 账号：17 位 SteamID（`7656…`）、邮箱正则、`SteamID` 关键字。
   - 存档派生数据：`0x` + 12–16 位十六进制（种子/UA/坐标）、已知星系名。
   - 临时信息：`NMS.exe.<pid>.dmp`、`CrashDumps`、`pid=<数字>`、运行时目录。
2. `git grep` 复核已跟踪文件；`git log --all -S <模式>` 检查历史提交是否曾带入凭据/SteamID/本机路径。
3. `git check-ignore -v` 验证忽略规则；`git ls-files -ci --exclude-standard` 检查是否有已跟踪文件被新规则误伤。
4. Markdown 相对链接检查（`](...)` 目标是否存在），并区分“现行文档”与“一次性审计/归档文档”。

### 1.3 不在本次范围

- 二进制文件内容（`.dds`、`.png`、`.zip`、`.dmp`）与游戏 pak 资源。
- 远端仓库设置、GitHub Actions secrets、发布产物本身。
- 改写 Git 历史（只做检测与建议）。

---

## 2. 发现项

风险口径：**高**＝可直接定位到个人/本机或真实存档；**中**＝暴露使用痕迹或误导发布说明；**低**＝公开身份/开发约定，通常可保留。
处理口径：**已加忽略**＝本轮 `.gitignore` 已覆盖；**待文档代理**＝只列清单、未改；**无需处理**＝确认非敏感或有意保留。

### 2.1 本机绝对路径

| # | 位置 | 类型 | 风险 | 处理 |
|---|---|---|---|---|
| A1 | `docs/archive/PLAN-V4-2026-11-18.md:8` | 实测机器上的游戏安装路径 | 高 | **已处理**：改为 `<游戏目录>\Binaries\NMS.exe` |
| A2 | `docs/archive/VERIFY-AGENT-WINDOWS-2026-11-18.md:30` | 命令示例中的游戏安装路径 | 高 | **已处理**：改为 `<游戏目录>\Binaries\NMS.exe` |
| A3 | `docs/research/FEATURE-GAPS.md:3` | 审计对象仓库路径 | 中 | **已处理**：改为 `<仓库>` |
| A4 | `docs/research/FEATURE-GAPS.md:349` | 游戏 Mods 目录 | 高 | **已处理**：改为 `<游戏目录>\GAMEDATA\MODS\...` |
| A5 | `docs/MANUAL.md:876` | 存档路径样例 | 中 | **已处理**：改为 `<存档目录>` |
| A6 | `docs/AGENT.md:174` | 用户目录下的 snapshots 路径 | 中 | **已处理**：改为 `<用户目录>\.starforge\agent\snapshots.json` |
| A7 | `docs/AUDIT-2026-11.md:63`、`:188`；`docs/DEV-GUIDE.md:72`、`:201`、`:203`；`docs/archive/CAPABILITIES-2026-11-18.md:78`；`docs/archive/CLEANUP-AUDIT-2026-11-18.md:3`；`docs/archive/GAP-ANALYSIS-2026-11-18.md:4`、`:7` | 旧工作区/容器路径（部分为引用旧文或图片） | 低–中 | **已处理**：改为 `<工作区>`；断链图片已删除 |
| A8 | `starforge/core/paths.py:5`、`:56`、`:96`；`tests/conftest.py:11`、`:12` | 代码中的旧工作区兼容回退路径 | 低 | 无需处理（CI/容器约定，非个人路径；但发布说明可提示可用环境变量覆盖） |

### 2.2 真实存档派生数据（种子 / UA / 坐标 / 星系名）

> 说明：以下位置是**疑似来自本机存档**的数值。发布文档建议保留“方法/字段”，把具体值换成 `<seed>`、`<ua>`、`<coords>` 并标注“示例”。
> 判定依据：同一组数值在实测记录、旧手册、能力快照中反复出现，且与“存档里的船种子”“当前星球/星系”等上下文绑定；不是算法测试用的随机值。

| # | 位置 | 类型 | 风险 | 处理 |
|---|---|---|---|---|
| B1 | `docs/AGENT.md:611-614` | 存档飞船种子列表（4 行，含主船槽） | 高 | 待文档代理：改为 `<seed>`，并注明“示例/已脱敏” |
| B2 | `docs/AGENT-INJECT-CRASH.md:321-324` | 同上（实测记录中的重复） | 高 | 待文档代理：同上 |
| B3 | `docs/AGENT-INJECT-CRASH.md:142` | 玩家当前 UA + 星系名 + 行星序号 | 高 | 待文档代理：改为 `<ua>` / `<星系名>` / `行星 #<n>` |
| B4 | `CHANGELOG.md:395` | “存档里的船种子” + UA + 坐标 | 高 | 待文档代理：改为 `<seed>` / `<ua>` / `<coords>` 示例 |
| B5 | `docs/archive/PLAN-V3.md:52-55` | 本星系 UA、两个船种子 | 高 | 待文档代理：脱敏为 `<ua>` / `<seed>` |
| B6 | `docs/archive/CAPABILITIES-2026-11-18.md:42`、`:52`、`:60`、`:61`、`:62`、`:74` | UA/坐标/符文/星系种族/行星种子 | 高 | 待文档代理：脱敏为占位符；保留字段名 |
| B7 | `docs/archive/MANUAL-2026-11-18.md:278`、`:395` | UA/坐标/符文/星系属性（界面验收样例） | 高 | 待文档代理：脱敏 |
| B8 | `docs/archive/AGENT-PROTOCOL-2026-11-18.md:25`、`:30` | 写入种子 + UA/坐标/符文 的协议示例 | 高 | 待文档代理：脱敏（保留 JSON 结构） |
| B9 | `docs/archive/INGAME-SCAN-FEASIBILITY-2026-11-18.md:352` | 行星 `VP` 种子样本 | 中 | 待文档代理：脱敏 |
| B10 | `docs/research/CREATURE-SEARCH.md:101-102` | 生物 `VP` 种子数组 | 中 | 待文档代理：脱敏 |
| B11 | `CHANGELOG.md:252`、`:404`；`README.md:40` | 同一 UA 被用作“符文按位段重排”的算法示例 | 低–中 | 待文档代理确认：若该 UA 来自本机存档，替换为明确的虚构示例（如 `0x…` 占位） |
| B12 | `docs/AGENT.md:219`、`:620`、`:807`；`docs/AGENT-INJECT-CRASH.md:333` | `0xFFFFFFFFFFFFFFFF` 空槽哨兵 | 低 | 无需处理（游戏约定的 -1 哨兵，非存档内容） |
| B13 | `docs/MANUAL.md:1057` | CLI 示例种子 | 低 | 无需处理（明显是示例值） |
| B14 | `tests/**` 中的十六进制种子 | 测试 fixture | 低 | 无需处理（合成数据，用于断言；抽查未见真实 UA/星系名） |

### 2.3 临时运行信息（dump / PID / 时间线 / 运行时目录）

| # | 位置 | 类型 | 风险 | 处理 |
|---|---|---|---|---|
| C1 | `docs/AGENT-INJECT-CRASH.md:32`、`:33`、`:34` | 崩溃文件名含 `NMS.exe.<pid>.dmp`、精确到分钟的时间、桌面版解压目录名 | 中 | 待文档代理：改为 `NMS.exe.<pid>.dmp`、`<时间>`、`<发行包目录>` |
| C2 | `docs/AGENT-INJECT-CRASH.md:100`、`:125` | 通用 CrashDumps 路径 + 注入进程 PID 列表 | 中 | 待文档代理：路径保留为 `%LOCALAPPDATA%\CrashDumps\...`；PID 改为 `<pid>` |
| C3 | `docs/AGENT.md:820`、`:821` | 本机 CrashDumps 时间点（21:22/21:32/21:37） | 中 | 待文档代理：改为相对时间线或 `<时间>` |
| C4 | `docs/AGENT.md:882` | 通用 CrashDumps 位置 | 低 | 无需处理（无 PID/时间） |
| C5 | `docs/MANUAL.md:945` | 通用 CrashDumps 位置 | 低 | 无需处理 |
| C6 | `docs/research/FEATURE-GAPS.md:6`、`:227` | 游戏 PID、启动时间、端口监听属主 | 中 | 待文档代理：PID/时间改为 `<pid>` / `<时间>` |
| C7 | `tests/test_agent_cli.py:43`、`:177` | 测试桩 PID | 低 | 无需处理（固定测试夹具） |

### 2.4 凭据与账号标识

| # | 位置 | 类型 | 风险 | 处理 |
|---|---|---|---|---|
| D1 | `docs/AGENT.md` 中的 `?token=`、`STARFORGE_AGENT_TOKEN`；`starforge/agent/starforge_agent.py`、`starforge/live/agent_install.py` 的同名变量 | 参数名/环境变量名，**非值** | 低 | 无需处理 |
| D2 | `docs/AGENT.md:654-660` 的日志样例 | 已用 `?token=...` 省略，无明文 | 低 | 无需处理（继续保持省略） |
| D3 | 全仓 | 未发现 `gho_` / `ghp_` / `github_pat_` / `Bearer <值>` / 邮箱 / 真实 token 文件 | — | 无需处理 |
| D4 | 全仓 | 未发现 17 位 SteamID | — | 无需处理 |
| D5 | `LICENSE:3`、`README.md:78`、`docs/MANUAL.md:93`、`docs/archive/PLAN-V4-2026-11-18.md:4` | GitHub 用户名/仓库地址（公开身份） | 低 | 无需处理（MIT 署名与 clone 地址需要保留；由发布者确认是否用组织账号） |

### 2.5 误导性内容与链接

| # | 位置 | 类型 | 风险 | 处理 |
|---|---|---|---|---|
| E1 | `docs/archive/CAPABILITIES-2026-11-18.md:78` | 图片指向 旧工作区图片路径，文件不存在（断链 + 本机路径） | 中 | 待文档代理：删除该图或改成仓库内相对路径 |
| E2 | `docs/AUDIT-2026-11.md:17-18` 等 | 审计正文引用 `docs/ARCHITECTURE-V2.md`、`docs/AGENT-V2.md`、`PLAN-V4.md` 等已重命名/归档文件，读者会误以为仍存在 | 中 | 待文档代理：加“审计时点快照”说明，或统一改为 `archive/...` 路径；不要当作现行依据 |
| E3 | `docs/README.md` 索引 | 未收录 `docs/research/CREATURE-SEARCH.md`、`docs/research/FEATURE-GAPS.md` 与本文 | 低 | 待文档代理：补索引（发布自检会检查链接可达性） |
| E4 | 现行文档（`docs/README.md`、`ARCHITECTURE.md`、`AGENT.md`、`DEV-GUIDE.md`、`MANUAL.md`） | 检查是否把归档文档当“当前依据” | — | 无需处理：已明确标注 `archive/...`“只作历史参考/不作为事实来源”，未发现现行文档把归档文件当 canonical 依据 |
| E5 | `docs/archive/*` 内部相互引用旧文件名 | 归档文档之间的旧链接 | 低 | 无需处理（历史文档；如需可后续统一加日期后缀） |

---

## 3. `.gitignore` 变更（本轮已修改）

### 3.1 新增/调整

```gitignore
# 本项目运行产物
*.part                 # 原为 .part，只匹配字面文件名，改为通配

# 本机运行状态 / 凭据 / 崩溃与日志（绝不入库）
.starforge/            # token、state.json、snapshots、注入运行时
agent-runtime/         # 打包/本地 agent 运行时
*.log                  # pymhf/agent/应用日志
*.dmp
*.mdmp
*.pid
.env
.env.*

# 测试/静态检查缓存
.ruff_cache/
.coverage
htmlcov/
```

### 3.2 最终覆盖清单

| 类别 | 规则 | 状态 |
|---|---|---|
| 归档/运行产物 | `artifacts/`、`cache/`、`toolcache/`、`build/`、`dist/` | 已覆盖（原有） |
| 备份/半成品 | `*.bak`、`*.part` | 已覆盖（`.part` 本轮修正） |
| 崩溃/日志/状态 | `*.dmp`、`*.mdmp`、`*.log`、`*.pid`、`.starforge/`、`agent-runtime/` | **本轮新增** |
| 凭据/环境 | `.env`、`.env.*` | **本轮新增** |
| 游戏与存档 | `No Man's Sky/`、`NMS存档/`、`*.hg`、`*.sav` | 已覆盖（原有） |
| Python/测试 | `__pycache__/`、`*.py[cod]`、`*.egg-info/`、`.venv/`、`venv/`、`.pytest_cache/`、`.ruff_cache/`、`.coverage`、`htmlcov/` | 已覆盖（`.ruff_cache` 等本轮新增） |
| 编辑器/系统 | `.vscode/`、`.idea/`、`.DS_Store`、`Thumbs.db` | 已覆盖（原有） |
| 打包 | `*.spec` | 已覆盖（原有） |

### 3.3 验证结果

- 下列路径确认被忽略：`artifacts/*`、`NMS存档/*.hg`、`*.dmp`、`.starforge/agent/token`、`.starforge/agent/state.json`、`agent-runtime/*`、`*.log`、`.ruff_cache/*`、`.env`、`*.pid`。
- 下列**未被忽略**（发布必需，符合要求）：
  - `starforge/live/assets/icons/*.dds`（8 个模板图标）；
  - `starforge/live/builds/185034.json`；
  - `docs/img/*.png`（`*.png` 的例外规则仍生效）。
- `git ls-files -ci --exclude-standard` 为空：没有已跟踪文件被新规则误伤。

---

## 4. 发布前人工确认项

1. **是否需要轮换本机 agent token**：仓库内没有明文 token，但本机 `~/.starforge/agent/token`、`state.json` 与历史日志可能含有效值。若这些文件曾被拷贝进工作区或附件，请删除并重新生成；无需为“仓库内容”轮换。
2. **`starforge/live/assets/icons/*.dds` 尚未被跟踪**：`git status` 显示为 `??`。发布包依赖这些图标（`pyproject.toml` 的 package-data），提交前确认 `git add` 会包含它们，且不会被 `.gitignore` 拦截。
3. **确认是否接受保留公开 GitHub 用户名**：`LICENSE`（MIT 署名）与 `README` clone 地址包含仓库所有者名字。若发布到组织账号，统一替换。
4. **确认真实存档数值的脱敏范围**：文档中的种子/UA/坐标建议全部视为“可能来自本机存档”；若发布者确认某些值来自公开种子库，可在文档中注明来源后保留。
5. **Git 历史**：`git log -S` 显示历史提交曾包含本机安装路径（非凭据）；未发现 token/SteamID。若要求“历史也不含本机路径”，需要 `git filter-repo` 改写历史并强推（会改变所有 commit hash），本轮未执行。
6. **发布包内容复核**：打包后在 `dist/` 内抽查是否带入 `agent-runtime` 的日志、`.starforge` 状态或 `CrashDumps`；`.gitignore` 只影响入库，不影响打包脚本。
7. **文档代理完成脱敏后复扫**：本文行号会随并行编辑漂移，合并前用同一组正则复扫一次（尤其 `docs/AGENT.md`、`docs/AGENT-INJECT-CRASH.md`、`docs/archive/CAPABILITIES-2026-11-18.md`）。

---

## 5. 文档代理待办清单（本轮未改文档）

共 **24 条**（按文件聚合）：

1. `docs/archive/PLAN-V4-2026-11-18.md` —— 实测机器路径 → `<游戏目录>`。
2. `docs/archive/VERIFY-AGENT-WINDOWS-2026-11-18.md` —— PowerShell 示例中的游戏路径 → `<游戏目录>`。
3. `docs/research/FEATURE-GAPS.md` —— 审计对象路径 → `<仓库>`；MODS 命令路径 → `<游戏目录>`；两处 PID/启动时间 → `<pid>`/`<时间>`。
4. `docs/MANUAL.md` —— 存档路径样例 → `<存档目录>`（`:876`）。
5. `docs/AGENT.md` —— 用户目录路径 → `<用户目录>`（`:174`）；飞船种子列表 → `<seed>`（`:611-614`）；CrashDumps 时间点 → `<时间>`（`:820-821`）。
6. `docs/AGENT-INJECT-CRASH.md` —— 种子列表（`:321-324`）、UA/星系名（`:142`）、dump 文件名/PID/时间/发行目录（`:32-34`、`:100`、`:125`）。
7. `CHANGELOG.md` —— “存档里的船种子”与 UA/坐标（`:395`）→ 占位符；确认 `:252`、`:404` 的 UA 是否替换。
8. `README.md` —— `:40` 的 UA 若为真实存档值，改为虚构示例。
9. `docs/archive/PLAN-V3.md` —— UA/船种子（`:52-55`）→ 占位符。
10. `docs/archive/CAPABILITIES-2026-11-18.md` —— UA/坐标/符文/星系属性/行星种子（`:42`、`:52`、`:60-62`、`:74`）→ 占位符；删除或修复 `:78` 的断链图片。
11. `docs/archive/MANUAL-2026-11-18.md` —— 验收样例中的 UA/坐标/符文（`:278`、`:395`）→ 占位符。
12. `docs/archive/AGENT-PROTOCOL-2026-11-18.md` —— 协议示例中的种子/UA/坐标（`:25`、`:30`）→ 占位符。
13. `docs/archive/INGAME-SCAN-FEASIBILITY-2026-11-18.md` —— 行星 `VP` 种子（`:352`）→ 占位符。
14. `docs/research/CREATURE-SEARCH.md` —— 生物 `VP` 种子（`:101-102`）→ 占位符。
15. `docs/AUDIT-2026-11.md` —— 说明该文是审计时点快照；`ARCHITECTURE-V2.md`/`AGENT-V2.md` 等不存在文件加“已重命名/已归档”标注；旧工作区引用改为 `<工作区>`。
16. `docs/DEV-GUIDE.md` —— 旧工作区路径改为 `<工作区>` 或说明“CI 旧布局”。
17. `docs/archive/CLEANUP-AUDIT-2026-11-18.md`、`docs/archive/GAP-ANALYSIS-2026-11-18.md` —— 开头审计对象路径改为 `<仓库>`/`<工作区>`。
18. `docs/README.md` —— 补 `docs/research/*` 与本文索引。
19. 全仓文档 —— 统一占位符约定：`<游戏目录>`、`<存档目录>`、`<仓库>`、`<工作区>`、`<用户目录>`、`<seed>`、`<ua>`、`<coords>`、`<pid>`、`<时间>`。
20. 归档文档 —— 如需修内部旧链接，统一加 `-2026-11-18` 后缀或改成 `archive/` 相对路径（低优先级）。
21. 发布说明 —— 保留“实机验证于 build 185034”这类非敏感信息，不要连版本/结论一起删。
22. 发布说明 —— 若引用本次审查，链接到本文，不要复制本文的待办表。
23. `docs/AGENT.md`、`docs/MANUAL.md` 的 `?token=` 示例 —— 保持省略值，不要补真实 token。
24. 脱敏后 —— 用报告中的正则复扫，确认盘符路径、用户目录、17 位 SteamID、真实种子模式归零。

---

## 6. 附：本轮判定为“无需处理”的误报

- 代码中的 `pid` 变量、`PID` 锁、`find_pid()`、`parent_pid` 参数：业务逻辑，不是泄露。
- `tests/**` 的 PID/种子/`/tmp` 路径：测试夹具，非本机真实值。
- `0xFFFFFFFFFFFFFFFF`：空槽哨兵。
- MBIN 头哈希/GUID（`name_hash`、`guid`）：游戏资源标识，不是个人存档。
- `%APPDATA%`、`%LOCALAPPDATA%`、`~/.starforge` 等环境变量写法：跨机器可移植，非本机路径。
- `docs/AGENT.md` 中“本文不包含任何真实 token、存档内容或账号信息”的声明：意图正确，但正文仍有 2.2/2.3 列出的实测值，需按清单处理后才成立。
