# 体积预算与实测（v0.16 / v1.0）

> 范围：只改打包配置与体积报告，没有改业务代码；没有 git commit / push。
> 所有数字都标注 **实测** 或 **估算**。本文的 MB/MiB 按脚本口径 `1 MiB = 1024²` 显示。
> 用户下载的是 **一个 Inno Setup 安装包**；安装包内已包含 Qt、numpy、unicorn、
> NMS-Shipwright 数据层和 agent 的独立 Python 运行时，**不需要再下载任何依赖或组件**。

## 1. 结论

| 指标 | 旧 release.yml（实测） | 本次（实测） | 变化 |
|---|---:|---:|---:|
| `_internal` PyInstaller 刚产出 | 205.1 MiB | 137.7 MiB | **-67.4 MiB（-32.9%）** |
| `_internal` 裁剪后 | 115.3 MiB | 105.3 MiB | **-10.0 MiB（-8.7%）** |
| agent runtime（裁剪后） | 49.6 MiB | 46.1 MiB | **-3.5 MiB（-7.1%）** |
| 发布下载体积 | 72.2 MiB（zip） | **46.6 MiB（安装包）** | **-25.6 MiB（-35.5%）** |
| 同一份 payload：zip → 安装包 | 68.8 MiB | **46.6 MiB** | **-22.2 MiB（-32.3%）** |

- **v0.16 目标 ≤70 MiB 已达成**：安装包 46.6 MiB（实测）。
- **v1.0 目标 ≤55 MiB 已提前达成**：46.6 MiB，仍有约 8.4 MiB 余量（实测）。
- 若坚持发布“绿色 zip”，当前是 68.8 MiB；它不满足 v1.0 的 55 MiB，但本次发布
  资产已改为安装包，zip 只作为内部体积对照（实测）。

> 说明：`docs/PACKAGING.md` 里“131 MB → 90–100 MB、预算 110 MiB”是 v0.14 的
> 历史估算/口径。本机用旧配置重新构建后实测 zip 是 72.2 MiB，说明之前的裁剪已经
> 生效；本次在这个基线上继续削减，并把下载格式从 Deflate zip 换成 LZMA2 solid。

## 2. 测量环境与口径

| 项 | 值 |
|---|---|
| 系统 | Windows 10.0.26300（本机） |
| Python | 3.11.9 |
| PyInstaller | 6.22.3（hooks-contrib 2026.10） |
| PySide6-Essentials | 6.12.0 |
| numpy | 2.2.6 |
| NMSpy / pymhf | 185034.0 / 0.2.5 |
| Inno Setup | 6.7.3 |
| 统计脚本 | `python scripts/size_report.py <dir|zip|exe> --by category` |

`size_report.py` 的“解压体积”是文件大小合计；“zip 实际大小/安装包大小”是下载体积。
类别占比按解压体积计算，不等于压缩后的占比。

> 本机测量时工作区还有其它未提交改动（不是本次产生的，也未由本次修改）；它们可能让
> PYZ/CLI exe 的字节数有少量波动，但不影响 Qt/numpy/unicorn/agent runtime 的收集结论。

## 3. 基线构成（旧 release.yml，实测）

发布 zip：**72.2 MiB**；解压后 **178.0 MiB**。

| 类别 | 解压体积 | 占比 | 主要文件 |
|---|---:|---:|---|
| Qt/PySide6 | 51.2 MiB | 28.8% | `Qt6Core.dll` 10.0、`Qt6Gui.dll` 9.2、`QtOpenGL.pyd` 8.3、`Qt6Widgets.dll` 6.2 |
| agent runtime | 49.6 MiB | 27.9% | `python311.dll` 5.5、`pydantic_core.pyd` 5.5、`libcrypto-3.dll` 5.0、`python311.zip` 4.1 |
| numpy | 32.2 MiB | 18.1% | `numpy.libs` 的 OpenBLAS 19.4、`_multiarray_umath.pyd` 4.0 |
| 原生库/可执行文件 | 20.8 MiB | 11.7% | `python311.dll`、`libcrypto`、VC runtime、`sqlite3.dll` |
| 启动器/脚本 | 13.1 MiB | 7.4% | `starforge-cli.exe`（PYZ 里带了 numpy tests/pytest） |
| unicorn | 9.0 MiB | 5.0% | `unicorn/lib/unicorn.dll` 8.8 |
| 数据/资源 | 1.5 MiB | 0.8% | vendor `mapping.json`、资产 |
| 其它 | 0.6 MiB | 0.3% | 纯 Python 模块 |

旧配置的 `_internal` 在裁剪前是 **205.1 MiB**，其中 `--collect-all numpy` 带进了
tests/f2py/头文件，并把 pytest/pygments 拖进了 PYZ；`--collect-all unicorn` 带进了
49.9 MB 的链接期 `unicorn.lib`。

## 4. 本次裁剪清单

### 4.1 PyInstaller 排除/收集策略（`packaging/starforge.spec`）

**Qt（排除）**：WebEngine/Core/Widgets/Quick、Qml/Quick/Quick3D/QuickControls2/
QuickWidgets、Multimedia/MultimediaWidgets、Pdf/PdfWidgets、Designer/UiTools、
3D 全家桶、Charts、DataVisualization、Network/NetworkAuth、PrintSupport、Sql、
Test、Help、Svg/SvgWidgets、DBus、Xml、Concurrent、Bluetooth/Nfc/SerialPort/
SerialBus、Positioning/Location、Sensors、TextToSpeech、RemoteObjects、Scxml/
StateMachine、HttpServer、WebSockets/WebChannel、Graphs、SpatialAudio、WebView。

**Qt（保留）**：`QtCore`、`QtGui`、`QtWidgets`、`QtOpenGL`、`QtOpenGLWidgets`，
以及 Windows/offscreen 平台插件和 `qico`/原生样式插件。应用页面与对话框只 import
这些模块；没有 QTranslator、QNetwork、QML/Quick、WebEngine、打印、SQL、SVG。

**Python（排除）**：`tkinter`/`_tkinter`、`unittest`/`unittest.mock`、`pydoc`、
`doctest`、`test`/`tests`、`lib2to3`、`ensurepip`、`venv`、`idlelib`、`turtle`/
`turtledemo`、`curses`、`setuptools`、`pip`、`wheel`、`pytest`/`_pytest`/`pluggy`/
`iniconfig`/`py`/`pygments`。

**numpy（排除）**：`numpy.f2py`、`numpy.distutils`、`numpy.tests`、`numpy.testing`、
`numpy.conftest`、`numpy.typing.mypy_plugin`、`numpy._pyinstaller`，以及
`scipy`/`pandas`/`matplotlib`。numpy 改为走 PyInstaller 官方 hook，只带运行二进制
（含 OpenBLAS），不再 `--collect-all`。

**agent 侧（排除）**：`pymhf`、`nmspy`、`NMSpy`、`capstone`、`iced_x86`、`pymem`、
`cyminhook`、`keyboard`、`pywinctl`、`pymonctl`、`pywinbox`、`psutil`、`questionary`、
`prompt_toolkit`、`win32*`、`pythoncom`、`pywintypes`、`pythonwin`、`pywin32_system32`、
`pyrun_injected`。这些在独立的 `agent-runtime/` 里，由 agent 自己使用。

**必须保留（踩坑）**：`distutils`。unicorn 的 `unicorn.py` 在 import 期调用
`distutils.sysconfig`；第一次尝试把它排除后，`doctor` 里 unicorn 直接
`ModuleNotFoundError: No module named 'distutils'`。现在保留 `distutils`，只排除
numpy 自带的 `numpy.distutils`。

**收益（实测）**：`_internal` 刚产出 **205.1 → 137.7 MiB（-67.4 MiB）**。这是
spec + 排除清单的合计收益，未单独拆分每一项；其中最大项是 `unicorn.lib`（47.6 MiB
不再收集）、numpy tests/f2py/头文件、pytest/pygments PYZ。

### 4.2 PyInstaller 之后的安全裁剪（`packaging/prune_bundle.py`）

只删除运行时确定不加载的文件：

- Qt `translations/`、`qml/`；未使用插件目录（designer/qmltooling/sqldrivers/tls/
  network*/vectorimageformats/platforminputcontexts/generic/iconengines）；
- `imageformats` 只留 `qico.dll`，`platforms` 只留 `qwindows.dll` + `qoffscreen.dll`；
- 被插件依赖带回的 `Qt6Network/Qt6Svg/...` DLL；
- `opengl32sw.dll`（19.7 MiB，默认删除；`STARFORGE_KEEP_SOFTWARE_OPENGL=1` 可保留）；
- `unicorn/include`、`unicorn/lib/*.lib`；
- numpy `f2py`/`distutils`/`_core/include`/`tests`/`*.pyi`/`*.lib`/`*.a`；
- `__pycache__`、`*.pyc`、`*.pyo`、`*.pdb`。

**收益（实测）**：`_internal` **137.7 → 105.3 MiB（-32.3 MiB，17 项）**。其中
`opengl32sw.dll` 19.7 MiB、Qt translations 13.4 MiB，其余是插件/DLL/测试文件。

### 4.3 agent runtime（`packaging/build_agent_runtime.py`）

原有策略保留：NMSpy `--no-deps` + `pymhf[http_api]`，不装 DearPyGUI；裁剪 pywin32
开发件、examples/tests/docs、头文件/静态库/字节码、pip 的 `Scripts/`。

本次新增（都在独立 runtime 内，不影响主程序）：

| 删除项 | 依据 | 收益 |
|---|---|---:|
| `python.cat` | Windows 目录签名，仅安装/校验用 | 0.61 MiB（实测） |
| `pythonw.exe` | 启动器固定用 `python.exe` | 0.10 MiB（实测） |
| `sqlite3.dll` + `_sqlite3.pyd` | pymhf/nmspy/FastAPI 不 import sqlite3 | 1.59 MiB（实测） |
| `wcwidth/_wcwidth_c.pyd` | wcwidth 官方纯 Python 回退；import 自检通过 | 1.23 MiB（实测） |

**合计（实测）**：agent runtime 未裁剪 **61.8 MiB** → 旧裁剪 **49.6 MiB** → 本次
**46.1 MiB**；相对旧发布再降 **3.5 MiB**。`runtime ok` import 自检通过。

### 4.4 控制台 CLI 的 PYZ

去掉 numpy tests/pytest 后，`starforge-cli.exe` 从 **13.1 MiB → 7.3 MiB**
（实测，-5.8 MiB）。窗口启动器 `starforge.exe` 仍是 onefile，约 6.8 MiB。

## 5. 压缩：zip → Inno Setup（LZMA2 solid）

- 使用 `installer/starforge.iss`，`Compression=lzma2/ultra64`、
  `SolidCompression=yes`；**没有使用 UPX**（spec 里 `upx=False`，启动器加 `--noupx`）。
- 安装包只包含 `dist/starforge` 的内容 + 卸载器；不下载任何东西。

| 同一份 payload | 体积 | 说明 |
|---|---:|---|
| Deflate zip（内部对照） | 68.8 MiB | `Compress-Archive`，仅用于比较 |
| Inno Setup LZMA2 solid | **46.6 MiB** | 正式发布资产（实测） |

**收益（实测）**：同一 payload 再降 **22.2 MiB（-32.3%）**。LZMA2 对 DLL/PYD 的
压缩率明显好于 Deflate，且 solid 模式能跨文件复用字典。

安装包行为：按用户安装到 `{localappdata}\Programs\StarForge`，不需要管理员权限；
开始菜单有“StarForge”和“安全模式”；桌面图标可选；卸载器会清理
`agent-runtime/`。

## 6. CI 改动（`.github/workflows/release.yml`）

1. 安装依赖增加 `pytest ruff`；
2. **打包前**执行 `python -m pytest -q` 与
   `python -m ruff check --select F --config packaging/ruff.toml .`，任一失败即停止；
3. PyInstaller 改为 `packaging/starforge.spec`（统一排除清单），并用
   `packaging/pyinstaller_build.py` 给 Windows 上偶发的 DLL 复制锁加重试；
4. `_internal` 裁剪改为 `packaging/prune_bundle.py`，不再在 workflow 里维护长
   PowerShell 清单；
5. 构建 Inno Setup 安装包；如果 runner 没有 ISCC，才用 Chocolatey 安装 CI 工具
   （不进入发布包）；
6. 体积预算从 110 MiB 收紧到 **70 MiB**，检查对象改为最终安装包；
7. 新增“静默安装到干净目录 → `doctor` + `webcheck`”冒烟，验证安装后的副本；
8. Release 资产只上传 `starforge-*-win64-setup.exe`。

`packaging/ruff.toml` 只对两处既有基线放行 F401：`starforge/glyphs.py` 的兼容
再导出、`starforge/app/widgets/ui.py` 的一个未用 import；其余 F 类错误照常失败。
这样不用为了过 lint 改业务代码。

## 7. 验证（本机，实测）

| 命令/场景 | 结果 |
|---|---|
| `python scripts/size_report.py --self-test` | 通过（dir/zip/安装包/compare） |
| `python -m pytest -q` | 退出码 0 |
| `ruff check --select F --config packaging/ruff.toml .` | All checks passed |
| `dist/starforge/starforge-cli.exe --help` | 通过 |
| `starforge-cli.exe selftest` | 通过，“内置(打包版)” |
| `starforge-cli.exe doctor` | `ok: true`；unicorn 2.0.1 `ok`；numpy/flask/lz4/hgpaktool/texture2ddecoder/pefile 均 ok；GUI PySide6 6.12.0 |
| `starforge-cli.exe webcheck` | 全部 200，接口自检通过 |
| `serve --port 8898` + `/api/health` + `/` | 健康检查通过，根路径为 API JSON |
| 静默安装到空目录 | 退出码 0；`agent-runtime/python.exe` 存在 |
| 安装后 `starforge-cli.exe doctor` | `ok: true`；unicorn/deps/GUI 正常 |
| 安装后 `webcheck` | 退出码 0 |
| 安装后 `starforge.exe webcheck`（窗口启动器转发） | 退出码 0 |

说明：

- `doctor` 里 `systemgen.available = false` 是因为本机没有配置 `GAMEDATA`，不是
  unicorn 打包问题（`unicorn.ok = true`）。
- `capstone` 不在主程序里（它是 agent 侧反汇编依赖），`doctor` 会显示“降级”，
  与旧版一致；agent runtime 里仍有自己的依赖。
- 未在本机验证：真实游戏目录下的搜索/缩略图/3D、`starforge-safe.bat` 的实际
  3D 回退、游戏内 agent 注入；这些需要游戏与桌面环境。

### 干净目录验证方法（可复现）

```powershell
# 1) 静默安装到空目录
$setup = "dist\starforge-0.16.0-win64-setup.exe"
$dir = "$env:TEMP\sf-clean"
if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
Start-Process $setup -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-","/DIR=`"$dir`"" -Wait
$env:STARFORGE_HOME = "$env:TEMP\sf-clean-home"

# 2) 安装后的 CLI 自检
& "$dir\starforge-cli.exe" doctor
& "$dir\starforge-cli.exe" webcheck

# 3) 窗口启动器转发
Start-Process "$dir\starforge.exe" -ArgumentList "webcheck" -Wait

# 4) 体积预算（安装包）
python scripts/size_report.py $setup --fail-over 70
```

## 8. 目标与后续（零额外下载）

| 阶段 | 目标下载体积 | 当前 | 结论 |
|---|---:|---:|---|
| v0.16 | ≤70 MiB | 46.6 MiB | 已达成（实测） |
| v1.0 | ≤55 MiB | 46.6 MiB | 已提前达成（实测）；仍需防未来依赖增长 |

**明确不做**：“agent runtime 首次使用再下载”“unicorn/3D 可选组件”等方案。用户
不需要额外下载；所有东西都在安装包里，体积靠裁剪 + LZMA2 压缩。

如果未来依赖增长导致安装包超过 55 MiB，按收益/风险排序的候选（均为估算）：

1. 主程序 `libcrypto-3.dll` + `libssl-3.dll` + `_ssl.pyd` 约 5.7 MiB 解压：
   仅当确认不再需要 `agent_install.py` 的 HTTPS 兜底时才能删；**当前保留**。
2. 用一个小型原生启动器替换 onefile `starforge.exe`：预计下载体积 -2～3 MiB，
   但需要 MSVC 编译步骤，本次不做。
3. 自定义 numpy/更小 BLAS：风险高，可能影响搜索/3D 数值稳定性，不建议。
4. 继续裁 agent runtime 的 pywin32 扩展/标准库：收益 1～3 MiB，需逐个 import 验证。

## 9. 回滚

- 恢复 zip：把 release.yml 的 Inno 步骤换回 `Compress-Archive`，删除预算检查中的
  安装包断言；`dist/starforge` 内容不受影响。
- 保留软件 OpenGL：`STARFORGE_KEEP_SOFTWARE_OPENGL=1`（安装包会大约多 4～7 MiB
  压缩体积，估算）。
- 恢复 unicorn 静态库/头文件：从 `packaging/prune_bundle.py` 去掉对应行；运行时不
  需要，通常不需要回滚。
- 恢复 agent 的 `sqlite3`/`wcwidth` C 扩展：从
  `packaging/build_agent_runtime.py` 的删除列表去掉对应项并重新构建 runtime。
- 恢复 Qt 模块：从 `packaging/starforge.spec` 的 `QT_EXCLUDES` 去掉对应项；
  注意同时检查页面是否真的 import 该模块。
