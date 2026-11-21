# Starforge 开发 / 测试 / 打包指南

> 适用版本：当前工作区 `0.15.0`。本指南以代码和 `scripts/`、`packaging/`、`.github/workflows/release.yml` 为准。
> `PACKAGING.md` 是打包专题（体积构成/预算），本指南 §5 是开发视角的流程主线；旧网页设计（`archive/DESIGN-2026-11-18.md`）只作历史参考。打包命令、路径、依赖以本文列出的实际文件为准。
> 本次没有启动游戏、没有注入、没有执行发布打包；涉及实机和产物的地方标为“未验证”。

---

## 1. 环境准备

### 1.1 Python

- 推荐 **Python 3.11.x**。`pyproject.toml:5` 写的是 `requires-python = ">=3.10"`，但 CI 和 agent runtime 实际固定 **3.11.9**（`.github/workflows/release.yml:38`、`packaging/build_agent_runtime.py:26`）；3.10 没有 CI 依据，按“未验证”处理。
- 本机验证环境：Python 3.11.9、ruff 0.17.6、PySide6 6.12.0、numpy 2.2.6、Flask 3.1.3（仅代表本次检查环境）。

### 1.2 安装依赖

`requirements.txt` 是发布/开发实际使用的完整清单；`pyproject.toml` 的 `dependencies` 只有 `flask/numpy/lz4`，**不要只 `pip install .` 就以为装全了**。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
pip install -e . --no-deps        # 让 `starforge` 命令指向当前工作区
```

各依赖的作用（对应 `requirements.txt`）：

| 依赖 | 作用 | 缺失时 |
|---|---|---|
| `NMSpy==185034.0`（Windows） | 游戏内结构体/函数签名 | agent 通道不可用 |
| `pymhf[http_api]>=0.2.5`（Windows） | 注入 + 本机 HTTP API | agent 通道不可用 |
| `PySide6-Essentials>=6.7`（Windows） | 原生 Qt 界面 | `app` 不可用；测试会 skip |
| `flask>=3.0` | 可选 JSON API | `serve`/`webcheck` 不可用 |
| `numpy==2.2.6` | 搜索/几何/渲染 | 大部分功能失败 |
| `lz4>=4.0` | 存档解压 | 存档读取失败 |
| `hgpaktool>=1.1.3` | 游戏 pak 解包 | 3D/贴图/系统生成降级 |
| `unicorn==2.0.1.post1`（非 Darwin） | 执行游戏生成器代码 | 星系/行星生成、种子反查失败 |
| `texture2ddecoder>=1.0.6` | BC7 贴图解码 | 符文图标退回内置位图 |
| `pefile>=2023.2.7` | 读 PE 版本/反射数据 | build 版本号、生物角色表降级 |
| `setuptools<81`（非 Darwin） | unicorn 2.0.1 依赖 `pkg_resources` | unicorn 可能导入失败 |

`pyproject.toml` 的可选组：

```toml
[project.optional-dependencies]
search = ["unicorn>=2.0"]        # systemgen / 星球扇扫
dev    = ["pytest>=8.0"]
agent  = ["NMSpy==185034.0; platform_system == 'Windows'",
          "pymhf[http_api]>=0.2.5; platform_system == 'Windows'"]
```

注意：`unicorn` 在 `requirements.txt` 里固定为 `2.0.1.post1`，可选组写的是 `>=2.0`；以 `requirements.txt` 的发布组合为准。

### 1.3 外部数据 / 路径

仓库不包含 NMS-Shipwright 的源码副本，也不包含 Gagarin 数据或游戏文件。开发布局默认找“与仓库并列”的目录（`core/paths.py:50-97`）：

```text
父目录/
  starforge/                 # 本仓库
  NMS-Shipwright/            # 上游 nms_save / nms_procgen
  Gagarin_Titov/GAMEDATA/    # 含 Gagarin/ships/catalog.txt
```

可用环境变量覆盖：

| 变量 | 用途 | 默认/说明 |
|---|---|---|
| `STARFORGE_HOME` | 设置、日志、缓存、锁、agent 状态 | `~/.starforge` |
| `STARFORGE_SHIPWRIGHT` | NMS-Shipwright 仓库根 | 同机 `../NMS-Shipwright`、`<工作区>/nms/NMS-Shipwright` |
| `STARFORGE_GAMEDATA` | Gagarin GAMEDATA 根 | 开发布局 / 发布包 `vendor/gamedata` |
| `STARFORGE_SAVES` | 存档目录 | 平台默认路径 |
| `NMS_DIR` | 游戏根目录（含 `Binaries/NMS.exe`） | 自动发现/注册表 |
| `NMS_TOOL_CACHE` | 上游游戏缓存 | 自动设为 `<STARFORGE_HOME>/cache/gamecache` |
| `STARFORGE_NO_WARM` | 禁止启动预热 | 测试里设为 `1` |
| `STARFORGE_SAFE` / `QT_OPENGL` | 安全模式/软件 OpenGL | `app --safe` 会设置 |

`GAMEDATA` 是否有效只有一个判据：必须存在 `Gagarin/ships/catalog.txt`（`core/settings.py:50-66`）。Steam 原版只有 `PCBANKS/INPUT/MODS` 的 `GAMEDATA` 会被判为无效。

### 1.4 首次验证

```powershell
python -m starforge doctor          # 依赖/unicorn/Qt/上游/GAMEDATA；失败退出码 7
python -m starforge selftest        # 轻量数据自检；缺游戏数据也会返回 0
python -m starforge selfcheck       # 端到端（写入只在临时副本上）
```

如果 `doctor` 报 `gamedata.valid=false`，先修路径，不要继续排查 3D/搜索。

---

## 2. 运行与调试

### 2.1 命令

| 命令 | 作用 | 备注 |
|---|---|---|
| `python -m starforge app` | 打开原生 Qt 窗口（默认） | 无子命令时也走这里 |
| `python -m starforge app --safe` | 软件 OpenGL 安全模式 | 排查显卡/远程桌面崩溃 |
| `python -m starforge serve --port 8765` | 启动本机 JSON API | 仅 API，不提供静态网页；占用单实例锁 |
| `python -m starforge doctor` | 环境体检 | 输出 JSON；退出码 7 表示不满足 |
| `python -m starforge selftest` | 轻量数据自检 | 不要求游戏，始终返回 0 |
| `python -m starforge selfcheck` | 端到端自检 | 写入只发生在临时副本；关键步骤失败返回 1 |
| `python -m starforge selfcheck --no-write` | 跳过写副本 | 只读排查 |
| `python -m starforge webcheck` | 进程内 API 冒烟 | 不占端口、不起子进程 |
| `python -m starforge agent hello` | 检查 agent Mod/runtime/HTTP | 连不上返回 5 |
| `python -m starforge live probe` | 只读模板槽诊断 | 非 Windows 3，游戏未运行 4 |
| `python -m starforge live push --type fighter --seed 0x... --json` | 写模板槽 8 字节 | **直接写游戏内存**；非 Windows 3、未运行 4、写入失败 5 |
| `python -m starforge glyph-overlay 123456789ABC --click-through` | 独立 Qt 符文置顶窗 | 不注入游戏 |
| `python -m starforge ships --path save.hg` | 列存档船 | 只读 |
| `python -m starforge saves` | 扫描存档目录 | 只读 |
| `python -m starforge catalog --ship sentinel` | 部件目录 | 只读 |
| `python -m starforge icon _PIT_A -o out.png` | 导出部件图 | 只读 |
| `python -m starforge settings` | 查看/修改设置 | `--write true` 会改设置文件 |

Windows 开发辅助：

```powershell
scripts\run-native.bat     # 双击/命令行启动 python -m starforge app
scripts\run-safe.bat       # STARFORGE_SAFE=1 + QT_OPENGL=software
```

`app --browser` 已经移除；传入会返回 2 并提示改用 `app` 或 `serve`（`__main__.py:33-39`）。

### 2.2 日志与状态文件

| 路径（相对 `STARFORGE_HOME`） | 内容 |
|---|---|
| `logs/starforge.log` | 主日志，2 MiB × 3 滚动（`core/log.py:24`） |
| `logs/faulthandler.log` | 原生崩溃栈（`app/main.py:37-47`） |
| `agent/launcher.log` | agent 启动子进程 stdout/stderr（`agent_install.launcher_log_path`） |
| `agent/` | pymhf 自身日志目录（`agent_install.py:663`） |
| `settings.json` | 设置 |
| `native-window.ini` | Qt 窗口几何/分栏（`shell.py:65`） |
| `instance.lock` | 单实例锁 PID |
| `cache/preview/` | 预览 glb 缓存 |
| `cache/galaxy.db` | SQLite 银河索引 |
| `cache/gamecache/` | 上游 `NMS_TOOL_CACHE` |
| `agent/state.json` | agent base/port/token/pid 状态 |
| `agent/token` | 一次性 token（尽量 0600） |
| `agent/snapshots.json` | 传送前快照（最多 20 条） |

`STARFORGE_HOME` 指向临时目录即可做“干净环境”复现：

```powershell
$env:STARFORGE_HOME = "$env:TEMP\sf-debug"
python -m starforge doctor
```

### 2.3 调试要点

- 原生窗口崩溃先看 `faulthandler.log`；驱动/远程桌面问题用 `app --safe`。
- 不想等启动预热：`$env:STARFORGE_NO_WARM = "1"`。预热在 `warm.py`，会做 pak 元数据、一艘几何、系统生成。
- 无头环境跑 Qt 测试：`$env:QT_QPA_PLATFORM = "offscreen"`。
- `serve` 失败先看是否已有实例：单实例锁与 `app` 共用 `instance.lock`；`serve` 冲突返回 2。
- **不要**为了调试随便用 `STARFORGE_ALLOW_ATTACH_INJECT=1`。代码注释明确记录：对已初始化的 build 185034 进程注入会崩（`agent_install.py:598-610`）；正常路径是让应用启动游戏（`attach=False`）。
- 内存通道的 `live probe` 是只读的；`live push` 是写操作。现已统一走
  `Services.live_push` → `require_live_write()`（`write_enabled` + `confirm`）：
  CLI 需 `--yes`，UI 先弹确认，Web 传 `confirm=true`（`services/__init__.py:1135-1174`）。
  仍要注意：agent 高风险写与“一键安装模板 Mod”不是同一套闸门，见
  `ARCHITECTURE.md` 的 D1（待合并）。

---

## 3. 测试

### 3.1 命令

```powershell
python -m pytest -q                       # 全量；当前收集 532 项
python -m pytest --collect-only -q        # 只收集，检查导入/参数化
python -m pytest tests/test_live.py -q    # 单文件
python -m pytest tests/test_web.py::test_health_ok -q
python -m pytest -q -k "not slow"         # 跳过 slow 标记
python -m pytest -q -m slow               # 只跑 slow
```

本次检查结果：

- `python -m pytest --collect-only -q` 收集 **532** 项（56 个 `test_*.py` 文件）。
- `python -m pytest tests/test_services.py tests/test_web.py -q` 本次 20 项通过。
- 全量是否能全绿取决于本机是否有游戏/存档/GAMEDATA；缺这些时相关用例是 **skip**，不是 fail。

`pytest` 配置在 `pyproject.toml:26-28`：`testpaths = ["tests"]`、`addopts = "-q"`。`tests/conftest.py:132-133` 注册了 `slow` 标记。

### 3.2 fixture 设计（`tests/conftest.py`）

| fixture | 作用域 | 行为 |
|---|---|---|
| `isolated_home` | function，autouse | 为每个测试建 `tmp_path/home`，设 `STARFORGE_HOME`；`STARFORGE_NO_WARM=1`；测试前后重置 `settings._CURRENT`，避免污染真实 `~/.starforge` |
| `no_game_running` | function，autouse | 把 `starforge.save.writer.game_running` 打桩为 `False`；`transaction` 内部也调用这个函数，所以两条写路径都被覆盖 |
| `gamedata` | session | `paths.gagarin_gamedata()`；找不到就 `pytest.skip` |
| `_global_game_env` | session，autouse | 发现游戏目录后设置 `NMS_DIR`，并 `nms_save.gamepath.find.cache_clear()`；避免上游 `lru_cache` 把空结果缓存住 |
| `nms_dir` | session | 跨平台发现游戏根；没有 `Binaries/NMS.exe` 就 skip |
| `game_env` | function | 设 `NMS_DIR` 并 `settings.update(game_dir=...)` |
| `saves_dir` | session | `STARFORGE_SAVES` → `paths.default_save_dirs()` → 老布局兜底；没有 `*.hg` 就 skip |
| `client` | function | 用 `starforge.web.app.create_app()` 的 Flask test client |

跨平台游戏目录发现顺序（`conftest.py:24-38`）：

1. `NMS_DIR` 环境变量（先经 `locate_game.normalize` 校验）；
2. `locate_game.find()`（Steam/GOG/注册表等）；
3. 老 CI 布局 `<工作区>/nms/No Man's Sky`。

存档目录顺序（`conftest.py:107-120`）：`STARFORGE_SAVES` → `paths.default_save_dirs()`（Windows `%APPDATA%\HelloGames\NMS\st_*`；Linux/Proton 的 compatdata 路径；`~/NMS`）→ `<工作区>/nms/NMS存档`。

“游戏在跑就拒绝写入”的测试必须显式把桩改回 `True`：

```python
def test_refuses_when_game_running(save_copy, monkeypatch):
    monkeypatch.setattr(writer, "game_running", lambda: True)
    with pytest.raises(WriteRefused):
        writer.apply_seed(...)
```

参考 `tests/test_env_fixtures.py:31-44`；它同时断言拒绝发生在任何字节写入之前。

### 3.3 测试文件地图

| 范围 | 文件 |
|---|---|
| 存档读/写/事务 | `test_save.py`、`test_writer.py`、`test_writer_copy_paths.py`、`test_env_fixtures.py` |
| 服务门面 | `test_services.py`、`test_history.py`、`test_favorites.py`、`test_save_edit.py` |
| Web/API | `test_web.py`、`test_web_ui.py`、`test_routes_health.py`、`test_api_errors.py` |
| 实时通道 | `test_live.py`、`test_scan_parallel.py`、`test_build_fingerprint.py`、`test_exml_*` |
| agent | `test_agent_cli.py`、`test_agent_runtime.py`、`test_agent_gating.py`、`test_agent_portal_gate.py` |
| UI/Qt | `test_native_smoke.py`、`test_ship_lab.py`、`test_fleet_extras.py`、`test_job_dock.py`、`test_accessibility.py`、`test_theme.py` 等 |
| 数据/渲染 | `test_data.py`、`test_export.py`、`test_texture_spike.py`、`test_paint.py`、`test_glyphs_ua.py` |

### 3.4 加新测试

1. 放在 `tests/test_<领域>.py`，文件名以 `test_` 开头。
2. 优先用 `tmp_path` 和真实存档的**副本**；不要写真实 `save.hg`。
3. 需要写开关时 `settings.update(write_enabled=True)`；测试结束由 `isolated_home` 隔离设置文件。
4. 写路径测试依赖 `no_game_running` 的桩；如果你自己 monkeypatch，记得只影响当前测试。
5. 内存通道用 `starforge.live.mem.FakeProcess`（合成内存），不要 attach 真游戏；参考 `test_live.py:106-140`。
6. Web 用 `client` fixture；不要在测试里起真实端口。
7. agent 用本地 `HTTPServer` 或 monkeypatch `agent_install.status`，不要启动游戏；参考 `test_services.py:64-103`、`test_agent_runtime.py`。
8. 需要游戏/存档才能跑的用例，让 fixture skip；不要 `xfail` 成“假通过”。
9. 长耗时用例标 `@pytest.mark.slow`。

### 3.5 常见失败原因

| 现象 | 原因 | 处理 |
|---|---|---|
| 大量 skip | 没有 GAMEDATA/存档/NMS.exe | 设 `STARFORGE_GAMEDATA`、`STARFORGE_SAVES`、`NMS_DIR`，或接受 skip |
| `GameFilesMissing` / `nms_save` 不可导入 | 没有 NMS-Shipwright | 设 `STARFORGE_SHIPWRIGHT`，或把仓库放到 `../NMS-Shipwright` |
| 后续测试突然找不到游戏 | 上游 `gamepath.find` 的 `lru_cache` 缓存了空结果 | 在 import 前设 `NMS_DIR`；或 `gamepath.find.cache_clear()`（conftest 已做） |
| 写测试被“游戏在运行”拒绝 | 本机真的开着 NMS；conftest 只桩了 `writer.game_running` | 确认没在用例里改回 `True`；需要验证拒绝时显式改回 |
| Qt 报 `could not find or load the Qt platform plugin` | 无头/缺插件 | `QT_QPA_PLATFORM=offscreen`；安装 `PySide6-Essentials` |
| `unicorn` 导入/DLL 失败 | Windows 缺 VC runtime、`setuptools` 太新 | 用 `requirements.txt` 的 `unicorn==2.0.1.post1` + `setuptools<81` |
| `SameFileError`（Windows） | 对 `.edited.hg` 又执行 `copy2` | 走 `writer._ensure_copy`；已有 `test_writer_copy_paths.py` 回归 |
| 端口 5000 被占用 | agent/pymhf 固定端口 | 关占用进程；`STARFORGE_AGENT_PORT` 只是覆盖尝试（见代码注释） |
| `agent hello` 返回 5 | Mod 未安装/runtime 缺依赖/HTTP 不可达 | 先 `python -m starforge agent hello` 看 `installed/runtime/reachable`；按提示装 runtime/Mod |
| 测试污染真实设置 | 没走 pytest 或手工跑了服务 | 始终用 `python -m pytest`，`isolated_home` 才会生效 |

---

## 4. 代码风格与约定

### 4.1 基本风格

- **注释/文档字符串用中文**，标识符用英文；现有模块几乎都采用这个约定。
- 文件头 `from __future__ import annotations`；类型用 `X | None`、`list[str]` 等现代写法。
- 数据结构用 `dataclass`（`Job`、`Settings`、`ShipRef` 等）。
- 宽泛捕获必须带 `# noqa: BLE001` 并写日志；不要静默吞掉用户可见错误。
- 路径统一走 `core.paths`（`app_home`、`cache_dir`、`settings_file`），不要把绝对路径写死。
- 重依赖（numpy、nms_save、nms_procgen、PySide6 等）尽量延迟导入，保持启动/CLI 可用。
- 写游戏/存档的代码必须可回滚；不要在 UI 线程直接做重活。

### 4.2 返回协议

服务层成功统一返回扁平字典：

```python
def _ok(**kw):
    return {"ok": True, **kw}
```

- 服务方法成功：`return _ok(...)`。
- 失败：抛领域异常（`BadRequest/NotFound/WriteRefused/...`），不要返回 `{"ok": False}`。
- 例外：agent HTTP 契约用 `{"ok": False, "code": "E_...", "error": "..."}`；`Services.agent_call` / `live_push_ship` 为了 UI 方便也会返回 `ok:false`。新增服务方法时优先领域异常。
- UI 的 `run_worker` 会把异常转成字符串；服务方法不要自己弹窗、不要 import Qt/Flask。

### 4.3 错误即领域异常

- 参数错误：`BadRequest`。
- 找不到：`NotFound` / `SaveNotFound`。
- 存档格式：`SaveFormatError`。
- 缺游戏/上游：`GameFilesMissing`。
- 写开关关闭：`WriteDisabled`（由 `settings.require_write()` 抛）。
- 写失败/游戏在跑/校验失败：`WriteRefused`。
- agent 内部错误：返回 `code` 字典；不要把 `pymhf` 异常直接抛给 UI。

### 4.4 脱敏

- 日志/诊断中出现 token/secret/password/authorization 时，使用 `services._redact` / `_redact_text` 的同一套规则，或至少不要打印原值。
- `export_diagnostics` 和 `recent_logs` 已经会脱敏；新增诊断字段时不要绕过它们。
- agent token 只放在本机 `state.json`/`token` 文件，且尽量 0600；不要写进普通日志。
- 不要把真实存档、token、完整 URL（含 `?token=`）提交到仓库或贴到 issue。

### 4.5 UI 不要直连领域层

约定是：

```text
app/ 页面/对话框 → services → save/live/... → core
```

现状有少量违规（`fleet.py` 直接 `export_zip`、`game_push.py` 直接 `live.exml` 等，见 `ARCHITECTURE.md` V4）。**新增代码不要继续扩大**；新功能先加服务方法，再让 UI 调服务。

### 4.6 线程/任务

- 页面里的同步服务调用统一走 `app/widgets/worker.py:run(...)`；worker 内不要碰 QWidget，返回值要是纯数据。
- 长任务用 `jobs.Job` + `REGISTRY.create` + `run_in_thread`；UI 通过 `JobDock` 轮询。
- 取消是协作式的：worker 要定期检查 `job.should_stop()`。
- 高风险原生调用（unicorn/systemgen）走 `Services._internal` 子进程；不要直接在 Qt 线程里跑。
- 写操作与游戏进程检测不要并发执行；写入前先确认游戏未运行。

### 4.7 存档写入规则

- 只用 `save.transaction.transact_save` 或 `save.writer` 的既有入口；不要直接 `open(save, "wb")`。
- 写前必须 `settings.require_write()`；需要用户确认的入口显式检查 `confirm`。
- 写后必须重新解码并核对；失败必须原子写回原始字节。
- 测试只用副本；`copy=True` 生成 `.edited.hg`，不要覆盖原档。

---

## 5. 打包

### 5.1 发布工作流概览

实际流程在 `.github/workflows/release.yml`，只由 `v*` tag 或手动触发：

1. checkout 本仓库 + 固定 commit 的 NMS-Shipwright（用于 vendor）。
2. `actions/setup-python` 3.11；`pip install -r requirements.txt pyinstaller`；`pip install .`。
3. `python -m starforge selftest`（非 0 只 warning）。
4. `python packaging/vendor.py --shipwright upstream-shipwright --dest build/vendor`。
5. `python packaging/build_agent_runtime.py --no-prune` → 体积基线；`--prune-only` → 裁剪并 import 自检。
6. PyInstaller **onedir** 构建 `dist/starforge-cli`（入口 `packaging/entry.py`）。
7. PyInstaller **onefile --windowed** 构建启动器 `dist/starforge/starforge.exe`（`packaging/launcher.py`，转发参数给 `starforge-cli.exe`）。
8. 裁剪 `_internal`（Qt 翻译/插件、unicorn 静态库/头文件、numpy tests/f2py、字节码等）。
9. 冒烟：`--help`、`selftest`、关键依赖文件、`doctor`、Qt DLL、`webcheck`、`serve /api/health`。
10. 复制 `build/agent-runtime` 到 `dist/starforge/agent-runtime`，生成 `starforge-safe.bat`，压缩 zip。
11. `scripts/size_report.py` 检查最终 zip 不超过 `STARFORGE_SIZE_BUDGET_MIB=110`，发布。

### 5.2 PyInstaller 关键参数

CI 的实际参数（`.github/workflows/release.yml:86-113`）要点：

```text
pyinstaller --noconfirm --clean --name starforge-cli --onedir
  --paths . --paths build/vendor
  --icon assets/starforge.ico
  --collect-submodules nms_save --collect-submodules nms_procgen
  --add-data "build/vendor/data;data"
  --add-data "build/vendor/THIRD_PARTY_SHIPWRIGHT_LICENSE.txt;."
  --collect-all hgpaktool --collect-all numpy --collect-all flask
  --collect-all texture2ddecoder --collect-all unicorn --collect-all pefile
  --hidden-import pkg_resources
  --collect-submodules starforge
  --add-data "starforge/agent;starforge/agent"
  --add-data "starforge/live/builds;starforge/live/builds"
  --add-data "assets;assets"
  --exclude-module numpy.f2py --exclude-module numpy.distutils
  --exclude-module pymhf --exclude-module nmspy
  --exclude-module starforge.agent.starforge_agent
  --exclude-module tkinter --exclude-module _tkinter
  --exclude-module webview --exclude-module pythonnet --exclude-module clr_loader
  ... Qt 未使用模块的 exclude ...
  packaging/entry.py
```

启动器：

```text
pyinstaller --noconfirm --clean --onefile --windowed --name starforge
  --distpath dist/launcher --workpath build/launcher --specpath build/launcher
  --icon assets/starforge.ico
  packaging/launcher.py
```

`packaging/launcher.py` 用 `subprocess.Popen([starforge-cli.exe, *args], CREATE_NO_WINDOW)`；无参数时补 `app`。`packaging/entry.py` 在模块层显式 import 延迟依赖，避免 PyInstaller 漏包。

### 5.3 package-data 与资源

`pyproject.toml:20-24`：

```toml
[tool.setuptools]
packages = ["starforge", "starforge.core", "starforge.data", "starforge.save",
            "starforge.web", "starforge.live", "starforge.services",
            "starforge.app", "starforge.app.pages", "starforge.app.widgets",
            "starforge.app.dialogs", "starforge.agent"]

[tool.setuptools.package-data]
"starforge.live" = ["builds/*.json", "assets/icons/*.dds"]
```

要点：

- `starforge.live` 的 `builds/*.json`（build 地址书）和 `assets/icons/*.dds`（模板 Mod 图标）是 package-data。
- `starforge/agent` 是 package，但发布包里的 agent 源文件由 PyInstaller `--add-data "starforge/agent;starforge/agent"` 额外带入；**不要只依赖 package-data**。
- 根 `assets/`（`starforge.ico`、`starforge.png`）不在 package-data，由 `--add-data "assets;assets"` 带入。
- 新增子包时，必须同时更新 `pyproject.toml` 的 `packages` 和 PyInstaller 的 `--collect-submodules`/`--add-data`；否则源码运行正常、打包后 `ModuleNotFoundError`。

### 5.4 agent runtime

- 脚本：`packaging/build_agent_runtime.py`。
- 版本：Python 3.11.9、NMSpy 185034.0、pymhf 0.2.5（`build_agent_runtime.py:26-29`）。
- 产物：`build/agent-runtime/python.exe` + `site-packages`；发布时复制到 `dist/starforge/agent-runtime`。
- 策略：
  - NMSpy `--no-deps`，避免拉 `pymhf[gui]`；
  - 只装 `pymhf[http_api]`，不装 DearPyGUI；
  - 安装后裁掉 IDE/示例/`win32comext` 等（`PYWIN32_DROP_*`）。
- 应用侧查找顺序：`agent-runtime/python.exe` → `_internal/agent-runtime` → 源码树 `agent-runtime` → `~/.starforge/agent/runtime`（`agent_install.py:162-174`）。
- 版本清单在 `agent_install.AGENT_RUNTIME_MANIFEST`（`:76-84`）；`tests/test_agent_runtime.py:39-43` 会校验它和构建脚本常量一致。

### 5.5 vendor 上游

`packaging/vendor.py` 只复制运行必需部分：

- `nms_save/`、`nms_procgen/`（含 designs/names）；
- `data/mapping.json`、`data/palettes`、`data/special_ships`；
- `LICENSE` → `THIRD_PARTY_SHIPWRIGHT_LICENSE.txt`；
- 不复制 `data/gamecache`（运行时缓存）、`__pycache__`、`.git`、`tests`。

CI 固定 NMS-Shipwright commit（`release.yml:32-33`）；本地可用：

```powershell
python packaging/vendor.py --shipwright ..\NMS-Shipwright --dest build\vendor
```

### 5.6 发布前自检（按实际脚本）

```powershell
# 1) 版本/必需文件/文档链接/遗留依赖/TODO 统计（纯 stdlib，只读）
python scripts/selfcheck_release.py
python scripts/selfcheck_release.py --json
python scripts/selfcheck_release.py --fail-on error

# 2) 包体报告（目录/zip，按 dir/package/category）
python scripts/size_report.py dist/starforge/_internal --top 25 --by package
python scripts/size_report.py dist/starforge --top 25 --by category
python scripts/size_report.py dist/starforge --by package --compare before.json
python scripts/size_report.py dist/starforge-v0.15.0-win64.zip --top 25 --by category --fail-over 110

# 3) 脚本自测
python scripts/size_report.py --self-test
```

`selfcheck_release.py` 检查：

- `starforge/__init__.py` / `pyproject.toml` / `CHANGELOG.md` 版本一致；
- 最近 git tag（缺失只 warning）；
- 必需文件（`app/shell.py`、`agent/starforge_agent.py`、`docs/README.md`、`CHANGELOG.md`、`pyproject.toml`、页面、`live/builds/*.json`）；
- `docs/README.md` 的相对链接可达、可选文档已收录；
- `requirements*.txt` / CI 不再安装 pywebview/pythonnet/clr_loader/tkinter（注释、`--exclude-module` 不算）；
- TODO/FIXME/“待实现”只统计，不影响退出码。

`size_report.py` 是只读的；`--fail-over` 超过预算返回 1。CI 最终 zip 预算 110 MiB（`release.yml:20`）。

### 5.7 打包后冒烟（CI 实际步骤）

```powershell
dist\starforge\starforge-cli.exe --help
dist\starforge\starforge-cli.exe selftest
dist\starforge\starforge-cli.exe doctor
dist\starforge\starforge-cli.exe webcheck
dist\starforge\starforge-cli.exe serve --port 8899 --no-browser
# 另一个终端：
Invoke-WebRequest http://127.0.0.1:8899/api/health
```

还要检查 `_internal` 里有 `numpy/flask/werkzeug/lz4/hgpaktool/texture2ddecoder/mapping.json`、Qt 的 `Qt6Core.dll/Qt6Widgets.dll/Qt6OpenGLWidgets.dll`；CI 会做这些断言。

**未验证**：本次没有执行 PyInstaller、没有生成 zip，以上命令来自工作流，不是本次实测产物。

---

## 6. 提交前检查清单

- [ ] `python -m ruff check --select F starforge tests scripts packaging`（当前工作区通过；仓库没有 ruff 配置，只做未定义名/语法类检查）
- [ ] `python -m pytest -q`（当前收集 532 项；缺游戏/存档/GAMEDATA 时相关项 skip）
- [ ] 改了某模块就至少跑对应子集，例如 `python -m pytest tests/test_live.py -q`
- [ ] `python -m starforge selfcheck`（写只在副本；关键步骤失败返回 1）
- [ ] `python -m starforge selftest` / `python -m starforge doctor`
- [ ] 改了 Web/API：`python -m starforge webcheck`
- [ ] 改了文档/版本/依赖：`python scripts/selfcheck_release.py --fail-on error`
- [ ] 改了打包/资源：`python scripts/size_report.py --self-test`，并检查 `pyproject` packages/package-data 与 CI 参数同步
- [ ] 没有提交真实存档、token、`~/.starforge` 内容、含 `?token=` 的完整 URL
- [ ] 新增子包已加入 `pyproject.toml` 的 `packages`，新增资源已加入 package-data 或 PyInstaller `--add-data`
- [ ] 新写操作有 `require_write`、confirm、备份、读回、回滚，且测试只用副本
- [ ] 没有把 `pymhf`/`nmspy` import 进主进程代码

说明：仓库没有 CI 测试 job，只有 tag 触发的 release 工作流；以上是人工门禁，不是自动强制。

---

## 7. 常见开发任务

### 7.1 加一个服务方法

位置：`starforge/services/__init__.py` 的 `class Services`。

步骤：

1. 先确定它是否只是编排；不要在服务层 import Qt/Flask。
2. 领域依赖放在方法内延迟 import（现有风格）：

```python
def ship_report(self, path: str | None = None) -> dict:
    from ..save import library
    from ..core.errors import SaveNotFound

    p = library.resolve(path)
    ships, warnings = library.open_ships(p)
    if not ships:
        raise SaveNotFound(f"存档里没有飞船：{p}")
    _record("report", "生成飞船报告", f"{len(ships)} 艘", "mine")
    return _ok(path=str(p), ships=[s.to_dict() for s in ships], warnings=warnings)
```

3. 成功用 `_ok(...)`；失败抛领域异常；用户可见动作调用 `_record(...)`（它自己吞异常，不影响主流程）。
4. 需要长任务：`REGISTRY.create(kind)` + `run_in_thread(job, fn)`，返回 `job`；调用方用 `job.id` 轮询。
5. 需要高风险原生隔离：在 `_internal` 支持的 kind 里加分支（`__main__.py:cmd_internal`），再在服务方法里 `self._internal(...)`。
6. 加契约测试到 `tests/test_services.py`；测试用 `isolated_home`，不要碰真实数据。
7. UI 侧只调用 `self.svc.ship_report(...)`，用 `run_worker` 包起来。

### 7.2 加一个页面

以新增“报告”页为例：

1. 新建 `starforge/app/pages/reports.py`：

```python
"""Reports：报告页。"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ...services import get_services
from ..widgets.page import page_layout
from ..widgets.page_header import PageHeader
from ..widgets.worker import run as run_worker


class ReportsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svc = get_services()
        # 用 page_layout/PageHeader，和现有页面保持一致

    def ensure_loaded(self) -> None:
        """首次进入页面时再加载，避免启动阻塞。"""
        run_worker(self.svc.ship_report, self._show, self._failed)
```

2. `starforge/app/shell.py`：
   - 顶部 import `ReportsPage`；
   - `NAV` 增加 `("reports", "报告")`；
   - `NAV_GROUPS` 把 `reports` 放进合适分组；
   - `pages` 字典增加 `"reports": ReportsPage()`。
3. 快捷键由 `SHORTCUT_KEYS`/`SHORTCUT_INDEX` 自动推导；注意 `designer` 的特殊排序（`shell.py:46-48`）。
4. 需要跨页跳转时：页面发 `Signal(str)`，在 shell 里连接 `goto`；不要页面之间互相 import。
5. 更新 `tests/test_native_smoke.py:26` 的预期页面集合；如果改了导航标签，检查 `tests/test_ui_labels_desktop.py`。
6. 新术语沿用现有中英对照约定（历史术语表见 `archive/UI-TERMS-2026-11-18.md`）。
7. 页面内所有阻塞调用走 `run_worker`；worker 内不碰 QWidget。

### 7.3 加一个 agent 端点

以只读 `/foo` 为例：

1. 在 `starforge/agent/starforge_agent.py` 的 `StarforgeAgent` 里加：

```python
@endpoint("/foo", method="GET")
@_game_thread
def foo(self, token: str = "") -> dict:
    blocked = _auth_block(token)
    if blocked:
        return blocked
    try:
        # 只读：从 gameData 取值
        return {"ok": True, "value": ...}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
```

   - 装饰器顺序按现有代码：`@endpoint` 在外，`@_game_thread` 在内。
   - 只读端点显式 `method="GET"`；写端点用 `PUT`。
   - 写端点还要 `_multiplayer_block()`；传送类先 `_persist_snapshot`。
   - 返回必须是可 JSON 序列化的 dict；错误用 `{"ok": False, "code": "...", "error": "..."}`。
2. `live/agent_client.py`：加 `foo()` 方法（只读用 `_read`，写用 `_call(..., method="PUT")`），并把 `"foo"` 加进 `call()` 的白名单。
3. `services/__init__.py`：
   - 在 `live_capabilities` 的 `caps` 表里加键（`:940-957`）；
   - 写能力加入 `_HIGH_RISK_CAPABILITIES` / `_EXPERIMENTAL_WRITE_CAPABILITIES`（`:25-32`）；
   - `_AGENT_TITLES` 加中文标题（`:990-1004`）；
   - 如果写命令有特殊参数，更新 `_is_high_risk_agent_cmd`（`:983-988`）。
4. agent 的 `/hello` capabilities（`:1009-1018`）同步加键；否则 `live_capabilities` 读不到。
5. build 闸门：写能力必须只在 `status == "verified"` 的 build 上开放；不要在未验证 build 上“先跑通再说”。地址书放 `starforge/live/builds/*.json`，用户实测放 `~/.starforge/builds/*.json`。
6. 测试：
   - 客户端契约：用本地 `HTTPServer`，参考 `tests/test_services.py:64-103`；
   - 闸门：参考 `tests/test_agent_gating.py` / `tests/test_agent_portal_gate.py`；
   - agent 运行时离线逻辑：参考 `tests/test_agent_runtime.py`。
7. 安装/热重载：
   - `agent_install.install_mod()` 把源码复制到 `~/.starforge/agent/starforge_agent.py`；
   - 改完代码后可调用 `services.agent_reload()`（agent 的 `/admin/reload`，后台延迟 0.4 秒 `mod_manager.reload`）；
   - 修改已有端点逻辑已实测（2026-11-21 日志 `Removed 12 endpoints` → `Finished reloading`）；
     新增/删除端点后以 `/hello` 实际返回为准，必要时重启游戏。打包态热重载未验证。

### 7.4 加一个 CLI 子命令

1. 在 `starforge/__main__.py` 写 `cmd_foo(a) -> int`：
   - 懒 import 领域模块；
   - 人读输出走 stdout，错误走 stderr；
   - 需要机器可读时提供 `--json`；
   - 返回明确的退出码（0 成功，2 参数错误，3 不支持，4 未连接，5 操作失败等）。
2. 在 `main()` 里加子 parser：

```python
p = sub.add_parser("foo", help="做什么")
p.add_argument("--json", action="store_true")
p.set_defaults(func=cmd_foo)
```

3. `main()` 末尾 `return a.func(a)` 会自动分发；没有子命令时仍走 `cmd_app`。
4. 如果命令需要隐藏子进程隔离，给 `_internal` 加 kind，并在 `cmd_internal` 分支里实现；不要让普通 CLI 直接跑高风险原生代码。
5. 测试：参考 `tests/test_agent_cli.py` 的 CLI 断言方式；至少覆盖参数错误和成功路径。
6. 更新 `README.md` 的命令列表（发布文档）与本指南第 2.1 节；如果新增文件/协议，更新 `docs/README.md` 的索引。

### 7.5 加一个存档写操作（推荐走事务）

1. 优先用 `save.transaction.transact_save`，不要新写一套备份/原子写/回滚。
2. 在服务层检查 `confirm`、`settings.require_write()`（`transact_save` 会再检查写开关）。
3. `mutate(readable)` 做原地修改并返回 `before`；`verify(readable)` 重新解码后核对并返回 `after`；返回 `False` 或抛异常都算失败。
4. 需要只改副本时传 `copy=True`，目标会变成 `<save>.edited.hg`。
5. 写后自动清 `library` 缓存（`transaction._clear_cache`）；不要在别处再维护一份。
6. 测试：复制真实存档到 `tmp_path`，`settings.update(write_enabled=True)`，依赖 `no_game_running`；验证成功、读回、原档字节不变、失败回滚。
7. 如果修改会影响预览/船列表，确认对应的缓存失效路径（`save/library.py`、`preview.py`）。

### 7.6 重新生成模板表情图标

模板 Mod 的 8 张表情图标是 `live/iconart.py` 用游戏模型现渲的 128×128 BC1/DX10 DDS，
不用游戏自带的 `TYPE.*.DDS`（那是船型类别符号）。改动渲染或配色后：

```powershell
python -c "from starforge.live import iconart; print(iconart.generate())"
python -m pytest tests/test_iconart.py -q
```

生成目标默认是 `starforge/live/assets/icons`，会被 `pyproject.toml` 的
`package-data` 和模板 Mod 生成器一起带入。注意两个实现细节：

- 遮罩用“与渲染底色 `RENDER_BG` 的差异”，不能用 `any(axis=2)`；
- 先 `_trim` 再 `_fit`，否则留白会把船压小。

---

## 8. 快速排障顺序

1. `python -m starforge doctor`：依赖、unicorn、Qt、上游、GAMEDATA。
2. `python -m starforge selftest`：目录、catalog、icons、存档。
3. `python -m starforge selfcheck --no-write`：搜索/预览/符文/系统链路。
4. 需要写：再跑 `selfcheck`（只写临时副本）。
5. 看 `~/.starforge/logs/starforge.log`、`logs/faulthandler.log`；agent 看 `~/.starforge/agent/launcher.log`。
6. 内存通道先 `live probe`（只读），不要直接 `live push`。
7. 仍无法定位：导出诊断包（设置页“诊断 ZIP”/`Services.export_diagnostics`），它已脱敏。

**实机/未验证边界**：游戏内通道已在 build 185034 上实测只读、`prepare_warp`、`restore`
与热重载（证据见 `docs/AGENT-INJECT-CRASH.md`、`docs/LESSONS.md`）；
`full` 档、跨银河传送、打包态热重载、打包产物与发布工作流仍未验证。
打包相关章节来自 CI 配置与 `packaging/` 脚本，不是本机实测。
