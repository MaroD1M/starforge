# 包体削减与体积报告

> **2026-11-22 更新**：v0.16 起发布资产改为 **Inno Setup LZMA2 安装包**，新的
> PyInstaller 排除清单、实测体积与 70 MiB / 55 MiB 预算见
> [SIZE-BUDGET.md](SIZE-BUDGET.md)。本文的“131 MB”和“110 MiB zip 预算”是 v0.14
> 的历史口径，保留用于追溯。

本文记录 `v0.14.x` 的 Windows 绿色包（`starforge-*-win64.zip`）为什么大、这次砍了什么、怎么验证，以及下一阶段 60–80 MB 需要哪些产品取舍。

> 本次只改打包配置与报告脚本，没有改业务代码；没有在 Linux 上执行 Windows 打包。
> 最终数字以 GitHub Actions 的 `体积报告与预算（最终 zip）` 输出为准。

## 1. 目标

| 阶段 | 目标 zip | 说明 |
|---|---:|---|
| 当前 | 131 MB | PySide6/Qt、agent runtime、unicorn、numpy 的收集策略造成 |
| 本次（P1） | **90–100 MB** | 只删除运行时确定不需要的开发/静态文件；保留 selftest / doctor / webcheck / serve 冒烟 |
| 下一阶段（P2） | **60–80 MB** | 需要把 agent runtime、Flask/web、unicorn 或 3D 做成可选组件，属于产品/代码改动，不在本次范围 |

脚本按 `1 MiB = 1024²` 显示体积；文中“MB”沿用日常说法，与脚本的 MiB 数值接近。

## 2. 131 MB 的主要构成（估算）

| 组成 | 估计压缩后 | 依据 |
|---|---:|---|
| PySide6 / Qt（Core/Gui/Widgets/OpenGL + 插件、翻译、opengl32sw） | 55–70 MB | `PySide6-Essentials` Windows wheel 约 82 MB；`opengl32sw.dll` 20.6 MB、translations 14.1 MB（未压缩） |
| agent runtime（Python embeddable + NMSpy + pymhf + FastAPI/Uvicorn/Pydantic） | 25–40 MB | `packaging/build_agent_runtime.py` 下载 Python 3.11.9，再 `pip --target` 安装 NMSpy/pymhf |
| unicorn | 12–20 MB | Windows wheel 15.9 MB；其中 `unicorn/lib/unicorn.lib` 49.9 MB、`unicorn.dll` 9.6 MB、`include/` 头文件 |
| numpy 2.2.6 | 8–15 MB | Windows wheel 12.9 MB（解压 43 MB）；`--collect-all numpy` 会带 tests/f2py/头文件/静态库 |
| Flask / Werkzeug / Jinja2 / click 等 | 3–6 MB | 原生窗口默认不访问网页，但 `serve`/webcheck 仍要保留 |
| vendored NMS-Shipwright | 1–2 MB | `packaging/vendor.py` 只复制运行必需文件 |
| lz4 / hgpaktool / texture2ddecoder / pefile | 2–5 MB | 必需 |
| 其它（Python stdlib、VC runtime、web static） | 5–10 MB | PyInstaller 默认 |

结论：131 MB 不是功能必需，而是 **`--collect-all` 把链接期静态库、头文件、测试、Qt 翻译和 agent 的开发依赖一起收进来了**。

## 3. 本次已实施的削减

实现位置：

- `.github/workflows/release.yml`：PyInstaller 之后、冒烟测试之前裁剪 `dist/starforge/_internal`；并在 agent runtime 和 `_internal` 的裁剪前后各跑一次体积报告；
- `packaging/build_agent_runtime.py`：两阶段安装（NMSpy `--no-deps` + `pymhf[http_api]`），安装后裁剪整个 runtime；
- `scripts/size_report.py`：目录/zip 体积排行，支持 `--by dir|package|category` 和 `--compare`（纯 stdlib）；
- 本文件：依据、验证与回滚方式。

### 3.1 agent runtime 安装策略（本轮重点）

从 PyPI 元数据（Linux 上可直接核对，不需要 Windows）确认：

- `NMSpy==185034.0` 声明 `pymhf[gui,http_api]==0.2.5`；`gui` extra 才会拉入 `dearpygui`；
- `pymhf` 的基础依赖包含 `pywin32`、`pywinctl`、`pymem`、`cyminhook`、`keyboard`、`pymem[speed]` 等，这些是注入/窗口检测硬依赖，不能省；
- `pywin32` 是单个大 wheel（312：6.7 MB wheel / 15.2 MB 解压），没有官方“只装 win32gui”的子包，只能安装后裁剪；
- `dearpygui` win_amd64/cp311 wheel 约 1.9 MB（解压 5.4 MB），pymhf GUI 字体约 0.3 MB。

因此 `build_agent_runtime.py` 改为：

1. `pip install --no-deps NMSpy==<build>`，绕过 NMSpy 的 `pymhf[gui]` 依赖声明；
2. `pip install pymhf[http_api]==0.2.5`（**不带 `gui` extra**），保留 FastAPI/Uvicorn 与注入依赖，不安装 DearPyGUI；
3. 安装后无论走哪条路径都执行 import 自检：`nmspy`、`pymhf`、`fastapi`、`uvicorn`、`pymhf.core.mod_loader`、`pymhf.core.http_api`、`pymhf.core.utils`、`nmspy.data.types`、`nmspy.common`，以及 pywin32 核心 `win32gui/win32process/win32com.client`；
4. 回滚开关：`STARFORGE_AGENT_WITH_GUI=1` 会安装 `pymhf[gui,http_api]` 并保留 DearPyGUI/字体。

| # | 削减项 | 做法 | 实测/预期收益 | 风险与验证 | 回滚方式 |
|---|---|---|---|---:|---|
| 1 | unicorn 静态库/头文件 | 删除 `_internal/unicorn/lib/*.lib`、`_internal/unicorn/include`；保留 `lib/unicorn.dll` + Python 包 | **10–16 MB**（预期） | 运行时只通过 `unicorn/lib/unicorn.dll` 加载；CI `doctor` 真建 `Uc` 验证 | 去掉工作流对应裁剪行，重新打包 |
| 2 | Qt 翻译 | 删除 `_internal/PySide6/translations` | **2–4 MB**（预期） | 应用没有 `QTranslator`，界面中文在 Python/QSS；标准对话框按钮可能显示英文 | 去掉裁剪行；或从 PyInstaller 原始输出恢复 |
| 3 | Qt 未用插件 | 删除 designer、qmltooling、sqldrivers、tls、networkinformation、vectorimageformats、platforminputcontexts、generic；imageformats 只留 `qico.dll`；platforms 只留 `qwindows.dll`、`qoffscreen.dll` | **2–6 MB**（预期） | 应用只用 QtCore/Gui/Widgets/OpenGL；PNG 解码在 Qt6Gui 内置。CI 原生 Qt 检查 + 冒烟 | 去掉工作流对应裁剪行 |
| 4 | QML/Quick 残留 | 删除 `_internal/PySide6/qml`、`pyside6qml.abi3.dll` 及被插件带回的 `Qt6Qml/Quick/Designer/Sql/Network/...` DLL | **0–6 MB**（预期） | 已 `--exclude-module`；若实际未收集则为 0 | 去掉裁剪行 |
| 5 | Qt 软件 OpenGL | 默认删除 `opengl32sw.dll`（20.6 MB 未压缩） | **4–7 MB**（预期） | **唯一有功能降级的项**：安全模式/无 GPU/远程桌面下 3D 退回服务端 PNG | `STARFORGE_KEEP_SOFTWARE_OPENGL=1` |
| 6 | numpy 开发文件 | 删除 `f2py`、`distutils`、`_core/include`、`tests/`、`*.pyi`、`*.lib`、`*.a` | **1–3 MB**（预期） | 搜索/3D/渲染只 import 运行模块；CI `selftest`、`doctor`、网页冒烟覆盖 | 去掉工作流对应裁剪行 |
| 7 | agent 的 DearPyGUI | 安装阶段 `NMSpy --no-deps` + 只装 `pymhf[http_api]`；兜底删除 `dearpygui*` 和 pymhf GUI 字体 | **2–3 MB**（单 wheel 实测：DearPyGUI 1.9 MB、字体 0.3 MB） | starforge 固定 `gui.shown=False`；pymhf 的 injected 对 GUI 缺失有兜底；自检断言 `find_spec('dearpygui') is None` | `STARFORGE_AGENT_WITH_GUI=1` 重建 runtime |
| 8 | agent 的 pywin32 开发件 | 删除 `pythonwin/`、`isapi/`、`adodbapi/`、`PyWin32.chm`、win32/win32com 的 test/Demos/scripts/HTML/静态库，以及 `win32comext/` | **2–4 MB**（pywin32 312 wheel 实测：解压 15.2 MB → 保留约 4.2 MB） | 保留 `win32/`、`win32/lib/`、`win32com.client`、`win32com.server`、`pywin32_system32/`；自检实际 import `win32gui/win32process/win32com.client/win32gui_struct` | `STARFORGE_AGENT_KEEP_PYWIN32_EXT=1` 保留 `win32comext`；必要时整段去掉裁剪 |
| 9 | agent 的测试/头文件/示例/字节码 | `pip --no-compile`；对整个 runtime 删除 `__pycache__`、`tests/test`、`examples/demos/samples/docs`、`include/headers`、`*.pyc/*.pyo/*.pyi/*.pdb/*.lib/*.a/*.exp/*.h/*.c`、pip 的 `Scripts/` | **1–3 MB**（预期） | 保留 `.pyd/.dll`、`python311.zip` 标准库和许可证；首次导入会重新生成 pyc | 删除通用裁剪清单后重装；`--no-prune` 可跳过 |

保守估计新增合计 **25–40 MB**（本轮 agent 安装策略再贡献约 **4–7 MB**），即 **131 → 约 88–102 MB**。若 CI 实测 Qt QML/资源本来就没进包，收益会偏向下限；若 `unicorn.lib`、translations、opengl32sw 都确实在包里，会靠近上限甚至更低。最终以 CI 的裁剪前后报告和 110 MiB 预算为准。

### 明确没有动的

- 业务代码、`starforge/agent/starforge_agent.py`、Selftest/doctor/webcheck/serve 流程；
- `numpy` 的 `_core`/`random` 运行二进制、numpy.libs 的 OpenBLAS；
- `unicorn/lib/unicorn.dll`（删了系统生成会失效）；
- `PySide6` 的 `Qt6Core/Gui/Widgets/OpenGL/OpenGLWidgets` 与 `qwindows.dll`；
- agent 的 NMSpy/pymhf/FastAPI/Uvicorn/Pydantic、pywin32 的 `win32/` + `win32/lib/` + `win32com.client/server` + `pywin32_system32/`；
- agent runtime 的 `python311.dll`、`python311.zip` 标准库、`.pyd/.dll` 运行二进制和许可证；
- vendored `nms_save` / `nms_procgen` / `mapping.json`；
- Qt `resources/icudtl.dat`（当前 PyInstaller 一般不会为 QtCore 收集；若某次出现在包里，先确认 QtCore 的 ICU 加载方式再删，不要盲删）。

## 4. 体积报告脚本

`scripts/size_report.py` 只用标准库，支持目录和发布 zip，并可切换聚合方式：

```bash
# 默认按顶层目录（兼容旧用法）
python scripts/size_report.py dist/starforge/_internal --top 25 --by dir

# 按 Python 包/组件：定位 agent 里到底是哪个依赖占空间
python scripts/size_report.py dist/starforge --top 25 --by package

# 按类别：Qt、numpy、unicorn、agent runtime、开发/测试冗余、原生库、数据/资源
python scripts/size_report.py dist/starforge --top 25 --by category

# 最终发布 zip：按归档实际大小做预算；超过 110 MiB 退出码 1
python scripts/size_report.py dist/starforge-v0.14.4-win64.zip \
  --top 25 --by category --fail-over 110

# CI/其它脚本可读的 JSON（包含 groups_all，便于后续对比）
python scripts/size_report.py dist/starforge --json > before.json

# 读取裁剪前 JSON，报告总解压体积与各目录/包/类别的变化
# 对比时保持与生成基线相同的 --by（CI 两边都用 package）
python scripts/size_report.py dist/starforge --by package --compare before.json

# 不依赖 dist 的自检（临时目录 + 临时 zip，覆盖 dir/package/category/compare）
python scripts/size_report.py --self-test
```

输出会按 `_internal/PySide6`、`_internal/numpy`、`_internal/unicorn`、`agent-runtime/dearpygui` 这样的粒度聚合，并列出最大文件。`--by category` 下 `开发/测试冗余` 的占比可以直接判断还有哪些死文件没裁干净。

CI 中：

- agent runtime：先 `--no-prune` 安装并保存裁剪前 JSON，再 `--prune-only` 裁剪 + import 自检，最后 `--compare` 输出包级对比；
- PyInstaller 后、裁剪前：保存 `_internal` 裁剪前 JSON；
- 裁剪后、冒烟前：`--by package --compare` 输出裁剪前后对比；
- 压缩后：`--by category` 报告最终 zip，并以 `STARFORGE_SIZE_BUDGET_MIB=110` 做硬预算；
- 等这次 Windows 实测通过后，可把预算逐步收紧到 100、90。

## 5. 验证命令

### Linux / 本机（不打包 Windows）

本轮已在 Linux 做完语法/报告自检，没有执行 Windows 打包或安装 Windows 依赖：

```bash
python -m compileall -q scripts/size_report.py scripts/selfcheck_release.py \
  packaging/build_agent_runtime.py packaging/entry.py
python scripts/size_report.py --self-test
# 自检覆盖 dir/package/category 三种聚合、目录/zip 和 --compare
python3 scripts/selfcheck_release.py --fail-on error
# 发布前静态自检：版本/文档/依赖/必需文件；不打包、不改代码
```

### GitHub Actions（Windows）

现有冒烟全部保留，裁剪发生在它们之前，因此验证的是“裁剪后的包”：

1. `python -m starforge selftest`
2. `vendor.py`
3. `build_agent_runtime.py --no-prune`：NMSpy `--no-deps` + `pymhf[http_api]`，保存裁剪前体积；
4. `build_agent_runtime.py --prune-only`：裁剪 + import 自检（`nmspy/pymhf/fastapi/uvicorn`、`pymhf.core.mod_loader/http_api/utils`、`nmspy.data.types`、`win32gui/win32process/win32com.client`），并输出包级裁剪前后对比；
5. PyInstaller 打包
6. **保存 `_internal` 裁剪前体积 → 裁剪 `_internal` → `--compare` 输出裁剪前后对比**
7. `starforge.exe --help`、`selftest`
8. 关键依赖磁盘检查（numpy/flask/werkzeug/lz4/hgpaktool/texture2ddecoder/mapping.json）
9. `doctor`（unicorn 真建 `Uc`、依赖、上游）
10. 原生 Qt 检查（PySide6、Qt6Core/Qt6Widgets/Qt6OpenGLWidgets）
11. `webcheck`
12. 起 `serve` 并请求 `/api/health`、首页
13. 压缩 + 最终 zip 体积报告/预算

### Windows 手工回归（仍需实测）

- 普通启动：窗口、页面切换、搜索、缩略图、3D 预览；
- `starforge-safe.bat`（安全模式）：删了 `opengl32sw` 后应能启动，3D 退回服务端 PNG，不应崩溃；
- 游戏内 agent：准备/复用 runtime → 安装 Mod → 注入 → `hello`；
- `doctor` / `webcheck` / `selftest` 在真实游戏目录下的结果；
- 星系/行星生成（unicorn）与读 `NMS.exe`（pefile）各跑一次。

## 6. 仍需实测、暂不能承诺的数字

以下都取决于 PyInstaller 的 hook 和 pip 解析结果，需看 CI 的体积报告：

- `unicorn/lib/unicorn.lib`、`unicorn/include` 是否真的进了 `_internal`（`--collect-all` 很可能收集，但以报告为准）；
- Qt `translations/`、`qml/`、`opengl32sw.dll` 是否真的存在；
- `numpy` 在 `--collect-all` 下实际带入多少 tests/头文件/静态库；
- agent runtime 的 `pymhf[http_api]` 传递依赖版本（本次固定 `==0.2.5`；未来 NMSpy 要求变化时需同步 `STARFORGE_PYMHF_VERSION`）；
- 删除 `win32comext/` 后，真实游戏注入/窗口检测是否仍正常（代码检查只用到 `win32com.client`，CI 会 import 验证）；
- 最终 zip 的压缩率（`.lib`/`.dll`/`.qm` 的可压缩性不同）。

## 7. 下一阶段 60–80 MB 需要什么

仅靠继续删除“死文件”很难稳定到 60–80 MB；剩下的大头都是有功能的。可选路线（按收益/风险排序）：

| 方案 | 预计 zip 收益 | 代价 |
|---|---:|---|
| agent runtime 改为首次使用时下载，或按游戏 build 单独发布 | 15–25 MB | 破坏“解压即用/离线”；需要安装器/校验/失败回退，涉及业务代码 |
| 把 `unicorn`/systemgen 做成可选组件 | 10–12 MB | 星系/行星生成、种子反查默认不可用；需要下载与降级提示 |
| Flask/web 从原生包中拆出（保留 webcheck 或独立 `starforge-web`） | 3–6 MB | 需要改 `entry.py`、`starforge.web` 的导入策略；会影响网页调试/回退 |
| 使用 7z/LZMA 替代 zip | 3–8 MB | 发布格式/解压体验改变；GitHub Release 仍可上传，但不是“双击 zip” |
| 深度裁 numpy（自定义构建/去 OpenBLAS） | 3–6 MB | 搜索/3D 数值稳定性风险高，不建议 |
| 去掉原生 3D（保留服务端 PNG） | 8–12 MB | 功能回退，不建议 |

建议 P2 先做“agent runtime 可选 + 体积预算 90 MB”，再评估是否需要拆 web/unicorn；不要为了数字牺牲 3D、状态生成或游戏内注入。

## 8. 发布前自检（selfcheck_release.py）

`scripts/selfcheck_release.py` 只用 Python 标准库，只读仓库，不改业务代码、不打包、不联网。
建议在打 tag / 触发 Release 前先跑一次：

```bash
# 人类可读摘要（默认发现 error 时退出码 1）
python3 scripts/selfcheck_release.py

# 机器可读 JSON；CI 或发布脚本可读取 checks/summary
python3 scripts/selfcheck_release.py --json > selfcheck.json

# 显式要求 error 才失败；warning 只报告
python3 scripts/selfcheck_release.py --fail-on error

# 需要把 warning 也当作失败时
python3 scripts/selfcheck_release.py --fail-on warning
```

检查项：

| 检查 ID | 内容 | 失败级别 |
|---|---|---|
| `version.files` | `starforge/__init__.py` 与 `pyproject.toml` 版本一致（允许预发布后缀） | error |
| `version.changelog` | `CHANGELOG.md` 最新 `## vX.Y.Z` 标题与包版本一致 | error |
| `version.tag` | 最近 git tag 与包版本一致，作为发布提示 | warning |
| `files.required` | `app/shell.py`、`app/pages/*`、agent、`live/builds/*.json`、文档索引等存在 | error |
| `files.builds` | `live/builds/*.json` 可解析且为 JSON 对象 | error |
| `docs.index` | 脚本保留的历史文档名中，若仍存在于 `docs/` 却未收录进索引则告警（多数已归档，当前只剩 `PACKAGING.md` 需保持收录） | warning |
| `docs.links` | `docs/README.md` 中相对链接目标存在 | error |
| `deps.legacy` | `requirements*.txt` / CI 不再安装 pywebview/pythonnet/clr_loader/tkinter | error |
| `markers.todo` | 关键代码里的 TODO/FIXME/“待实现”数量 | 仅报告 |

说明：依赖检查会跳过注释、`pyproject.toml` 的 `legacy` extra，以及 CI 里的
`--exclude-module`（它们是显式移除项，不是安装项）。TODO 统计不会导致失败。

### 发布前检查清单

- [ ] `python3 scripts/selfcheck_release.py --json` 退出码为 0，`summary.error == 0`。
- [ ] `starforge/__init__.py`、`pyproject.toml`、`CHANGELOG.md` 版本一致；需要时已更新“未发布”段。
- [ ] 最近 tag 与版本匹配；Release 由 tag 触发，不在本地提交/推送。
- [ ] `docs/README.md` 索引包含本轮新增文档，相对链接全部可达。
- [ ] `requirements.txt` / CI 没有重新引入 pywebview、pythonnet、clr_loader、tkinter（`legacy` extra 除外）。
- [ ] `starforge/live/builds/*.json` 与 agent 版本匹配；未验证 build 的写操作仍默认关闭。
- [ ] `python -m compileall -q scripts/selfcheck_release.py scripts/size_report.py packaging`。
- [ ] `scripts/size_report.py --self-test` 通过；最终 zip 体积在 `STARFORGE_SIZE_BUDGET_MIB` 内。
- [ ] Windows 冒烟：`starforge.exe --help`、`selftest`、`doctor`、`webcheck`、原生 Qt 检查、`serve` 健康检查。
- [ ] Windows 手工回归：普通启动、安全模式、3D、存档读写、agent 安装/注入/`hello`。
