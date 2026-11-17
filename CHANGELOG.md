# 更新记录

## v0.12.1-beta
- **打包可靠性**：`packaging/entry.py` 显式导入 zh/tex/parts/export/warm/render/preview 等模块，
  保证它们一定进 PYZ（v0.12.0 无法确认中文化模块是否被打进去）
- **webcheck 扩展**：逐项验证 `/api/textures/status`、`/api/catalog/<ship>`、
  `/api/part-thumb/...`、`/api/desktop`、`/api/warm`（12 项全过才算打包成功）

## v0.12.0-beta（重构 v2）
中文化 + 更接近真实建模的渲染 + 部件级预览 + 贴图管线 + 零配置自愈。
详见 [docs/PLAN-V2.md](docs/PLAN-V2.md)。

- **中文化**：插槽组与部件词根中英映射（编号保留、重名加序号），群系/哨兵/种族/船池类别
  全部中文；原名保留在 tooltip
- **渲染**：点云 → 三角光栅化（z-buffer + 背面剔除 + 漫反射）；网格 340px、详情 520px；
  搜索结果后台预取，缓存命中 0ms
- **部件级 3D 预览**：`/api/part-thumb`，与固定件求差集单独取部件几何；
  失败三级兜底（3D → 游戏图标 → 占位图）
- **贴图管线**：`tex` 模块取 DDS/解码/UV 采样；`/api/texture`；`/api/textures/status`
  诊断（报告材质描述符是否可用）
- **零配置**：路径自愈（GAMEDATA/Binaries/Steam 根）、注册表与 libraryfolders 检测
- 界面：卡片网格、属性条、收藏夹、URL 直达（`?demo=search` / `?glyph=`）、应用内对话框

## v0.11.1-beta
- **修复 3D 黑屏**（v0.11.0 的核心功能回归）：改用 WebGL2 上下文；WebGL1 下强制启用
  `OES_element_index_uint`（否则 `drawElements(UNSIGNED_INT)` 静默失败）；
  着色器不再使用非法的 `mat3(mat4)`，法线矩阵单独传
- 新增**画布自检**：画 3 帧后采样像素，若与背景完全一致则自动退回服务端渲染图（永不出现黑框）
- 用无头 Chromium + SwiftShader 做过真实渲染验证（截图见 docs/img）

## v0.11.0-beta
- 真机修复：pywebview 内部参数导致的控制台报错、`BIOSHIP_PROC` 被误判成异星、
  未知类型缩略图 400、游戏目录大小写不匹配、设置页无校验反馈
- 存档：类型/等级/属性（S/A/B/C + 伤害/护盾/超光速/机动）、固定模型占位图、
  写回支持"写到副本"（原档不动）、读存档缓存（2.79s → 1.12s，命中 1–2ms）
- 性能：部件图标改为懒解码（首次 3.96s → 0.01s）；启动后台预热（pak/几何/系统）
- 功能：批量导出 zip（glb+png+manifest）、分享码导入、收藏夹、只看可预览、
  船池点开 3D、当前行星高亮、应用内唤起符文置顶窗口
- 交互：一步式配置向导（能自动检测就不弹）、应用内对话框替代 prompt/confirm、
  快捷键（Ctrl+Enter / j·k / 1–4 / Esc）、记住上次查询
- 工程：界面↔接口契约测试、路径自愈（GAMEDATA/Binaries/Steam 根）、
  GUI 版 `--windowed`（无黑控制台）+ 独立 `starforge-cli.exe`

## v0.10.0-beta
- **桌面应用**：双击即开**原生窗口**（pywebview + Edge WebView2），不再弹浏览器；
  窗口大小/位置记忆；设置页与存档页有**原生「浏览…」选择框**，不用手打路径
- **3D 用种子真实配色**：从游戏数据解出主色/副色/底漆（`paint.py`），
  缩略图与 glb 都应用；同一艘船不再是灰蓝占位色
- 部件树在缺 Gagarin 数据时从游戏资源推导（已在上版），`/api/catalog` 会回报来源
- CI：打包 `pywebview`，新增 `app` 命令存在性检查

## v0.9.7-beta
- **界面重做**：左侧导航栏 + 三栏工作区（条件 / 结果 / 3D）、就绪状态芯片、
  一键配置、行星卡片、船池表格、Toast 提示；不再是一堆裸表单
- **不依赖外部数据也能用**：部件树优先读 Gagarin 的 `catalog.txt`，**缺失时从游戏 pak
  的场景描述符自己推导**（实测 53 组 / 272 部件，0 秒），搜索校验随之不再要求 GAGARIN
- 星球页打开即自动加载当前星系（不用手动扫描）；我的船列表带缩略图
- CI 修复：内置上游的断言只匹配 `Shipwright:` 行（此前被 `GAMEDATA: 未找到` 误判）

## v0.9.6-beta
- **打包版自带上游**：CI 在构建时把 NMS-Shipwright（MIT）的 `nms_save`/`nms_procgen`/
  `data/mapping.json` vendor 进包（约 0.5 MB），**用户不再需要安装 Shipwright 仓库**
  - 此前打包版读不了存档（`nms_save` 不在包里），只有命令行能跑
  - 运行时缓存 `NMS_TOOL_CACHE` 默认外置到 `~/.starforge/cache`，不往安装目录写
- 新增 `THIRD_PARTY_NOTICES.md`（含 Shipwright 的 MIT 许可说明，产物内附全文）
- `selftest` 会写明上游是"内置(打包版)"还是"同机仓库"

## v0.9.5-beta
- **修复致命打包缺陷**：此前 exe 里没有 `starforge/web/static`（漏了 `--add-data`），
  命令行能用但网页 404。现在静态资源随包发布，并新增「网页冒烟」步骤（起服务→请求首页与 app.js）
- 静态资源缺失时页面给出可读提示（而不是裸 404 / 空白），命令行功能不受影响

## v0.9.4-beta
- **首次启动自动检测路径**：游戏目录（`NMS_DIR` → Steam/GOG → 注册表）、存档目录、数据目录；
  只填空项，不覆盖已填；设置页也有「自动检测路径」按钮
- **探测增加结构兜底**：除出厂种子外，额外报告 `ShipLayout{Slots,1,1}` 结构候选（**只报告不写入**），
  用于诊断"种子被游戏归一化"的情况
- README 增加「为什么杀毒软件可能报警」

## v0.9.3-beta
- **兼容 Super Ship Hunter**：自动复用其 `R_TEMP_ROBOT`/`R_TEMP_EXOTIC` 两个模板槽，
  没装我们的模板 Mod 也能立刻验证实时通道（探测里标 `[SSH兼容]`）
- 模板槽扫描支持两条来源，自家模板优先；歧义保护不变（宁可不写）
- 修复 `icon_rgb` 会缓存失败结果、导致后续拿到位图字体的问题

## v0.9.2-beta
- **符文用游戏原图**：从 `NMSARC.TexUI.pak` 解码 BC7（texture2ddecoder），缺依赖自动退位图字体
- **一键自检 `selfcheck`**：10 步端到端，写入只在存档副本上进行
- 搜索页显示「约 1/N 的种子满足 · 预计 X 秒」

## v0.9.1-beta
- **只读探测 `live probe`**：单次遍历内存报告 8 种模板槽的候选与得分，用于远程排障
- 设置页「探测模板槽（只读）」

## v0.9.0-beta
- **实时通道**：内存定位 → 写 8 字节种子 → 回读校验；单飞/歧义拒绝/地址缓存
- **模板 Mod 生成器**：8 种 `_PROC` 各一槽，`Slots=120..127` 互不相同
- **符文置顶窗口**：`glyph-overlay`，Windows 上点击穿透、不抢焦点
- 打包修正：补 numpy/flask，产物冒烟测试

## v0.2.0-alpha
- 四页网页（搜索/我的船/星球/设置）+ 浏览器内 WebGL glb 查看器
- 服务端缩略图（点云 + 法线着色 + 2× 超采样）
- 星球/系统搜索与扇扫 API、符文弹层

## v0.1.0-alpha
- 搜索（按部件/涂装）、L1 真 3D、存档图鉴、同型换种子写回（备份/原子写/读回/回滚）
- 首次 Windows 构建；修复 cp1252 控制台下中文输出崩溃
