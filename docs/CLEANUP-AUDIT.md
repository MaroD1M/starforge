# 过时文件/文档/依赖清理审计

> 审计对象：`/workspace/nms/starforge`（main @ 3e2a7a5 + 工作区改动）
> 原则：先固定基线 → 文档/测试 → 旧 UI 代码 → 依赖/打包。不要先删代码。

## 1. 结论

- 当前默认产品是 **PySide6 原生界面**，7 个页面：概览、飞船实验室、设计器、我的船队、星图、游戏内代理、设置。
- `desktop.py`、`web/static/**`、`overlay.py`（tkinter 回退）属于旧路径；发布包已排除 pywebview/pythonnet/tkinter，实际不可用。
- Flask JSON API 仍被 15 个测试文件和 `serve/webcheck` 使用，**不能和静态 Web UI 一起立即删除**。
- 没有发现真正无引用的业务源码；`starforge.agent.starforge_agent` 是 pymhf 注入脚本，属于正常设计。
- 最大过时资产是文档漂移：旧版本号、五页/网页、nmshunter、命名管道等描述与现状不符。

## 2. 清理优先级

### Phase 0：先固定基线
- 保存当前工作区快照；不删除任何文件。
- 把本文加入 `docs/README.md` 索引。

### Phase 1：文档（已开始）
- 重写 README/docs 索引为当前 7 页原生界面。
- 归档 `PLAN-V2.md`、`PLAN-V3.md`；更新 CHANGELOG 链接。
- `MANUAL.md`/`DESIGN.md`/`CAPABILITIES.md`/`VERIFY-WINDOWS.md` 标注历史参考，合并进 USAGE/ARCHITECTURE/FEATURE-MAP 后再移除。
- `AGENT-PROTOCOL.md` 标注“未来编译型 agent 草案”，当前实现见 `AGENT.md`。
- 更新 `FEATURE-MAP.md` 的已实现/占位状态；统一 7 页。

### Phase 2：测试迁移
- 原生 UI 契约：扩展 `test_native_smoke.py`、`test_accessibility.py`。
- 删除/重写 `test_web_ui.py`、`test_ui_contract.py`（旧静态 UI）。
- 拆分 `test_desktop.py` 的 paint 用例到 `test_paint.py`，删除 desktop 专属。
- 迁移 `test_live.py` 的 tkinter overlay 用例到 Qt overlay/glyphs。
- `test_ui_labels_desktop.py` 删除 desktop/desktop-check/ensure_clr，保留船型/glb/paint。

### Phase 3：旧 UI 代码
1. 删除 `starforge/web/static/{index.html,app.js,app.css,viewer.js}`。
2. Web 改 API-only：删除静态目录/首页/静态路由/静态 404；`/` 返回 JSON 说明。
3. 删除 `starforge/desktop.py`，同步移除：
   - `__main__.py` 的 `desktop.run` 回退、`--webview`、`desktop-check`、doctor desktop 段；
   - `web/routes.py` 的 `/api/desktop`；`/api/health` 的 desktop 段改为 gui；
   - `packaging/entry.py` 的 desktop import；`pyproject` legacy extra；
   - 对应测试。
4. 删除 `starforge/overlay.py` 的 tkinter 回退；`glyph-overlay` 只走 Qt `app/overlay.py`。
5. 清理旧页面 `__pycache__`。

### Phase 4：依赖/打包
- `pyproject.toml`：删除 `psutil`、`legacy` extra；加入 `starforge.app.dialogs`；统一依赖来源。
- `requirements.txt`：Flask 标为 Web/调试可选；对齐 hgpaktool/texture2ddecoder/pefile。
- `packaging/entry.py`：移除 web/static/overlay/desktop 显式导入。
- `release.yml`：移除静态资源 `--add-data`，webcheck/serve 改 API-only 或删除；移除 legacy 排除项。
- `THIRD_PARTY_NOTICES.md`：删除 pywebview/pythonnet 行；Flask 标可选。
- `CHANGELOG.md` 追加清理条目。

### Phase 5：彻底移除 Flask（可选，最后）
只有 14 个 API 测试迁移到 services、`serve` 不再被文档/CI 依赖后再做。

## 3. 保留清单

- 原生页面：`app/pages/{home,ship_lab,ship_designer,fleet,galaxy,game_link,settings}.py`
- 当前组件/对话框：`app/widgets/**`、`app/dialogs/**`
- 服务层：`services/{__init__,favorites,history,save_edit}.py`
- 存档层：`save/{library,writer,transaction}.py`
- agent：`agent/starforge_agent.py`、`live/**`
- 当前文档：ARCHITECTURE、GAP-ANALYSIS、PLAN-V4、UI-REDESIGN、UI-TERMS、COMMUNITY-UI-ROADMAP、PACKAGING、SAVE-API-INVENTORY、INGAME-SCAN-FEASIBILITY、AGENT、CHANGELOG。
- `docs/img/*` 在 README 替换前不要删。
- Web API：`web/app.py`、`web/routes.py` 在决定保留 `serve` 前不要删。
- `app/overlay.py` 与 `glyph-overlay` 保留；只淘汰旧 `overlay.py` tkinter 回退。

## 4. 本轮已执行

- 新增本文档；
- `PLAN-V2.md`、`PLAN-V3.md` 移入 `docs/archive/`；
- 更新 `docs/README.md` 索引（当前文档 / 历史参考 / 发布自检）；
- 修复 `pyproject.toml` 缺少 `starforge.app.dialogs` 的打包缺陷；
- 删除 `starforge/app/pages/__pycache__` 旧页面缓存（不入库）；
- 删除旧静态网页：`starforge/web/static/{index.html,app.js,app.css,viewer.js}`；
- 删除 `starforge/desktop.py`（pywebview 外壳）与 `starforge/overlay.py`（tkinter 浮窗）；
- Web 改为 **API-only**：`/` 返回 JSON，不再提供首页/静态资源；
- 移除 CLI `--webview`、`desktop-check`；`doctor` 的 desktop 段改为 `gui`；
- `glyph-overlay` 统一走 Qt `app/overlay.py`；
- 删除/重写旧静态 UI 测试，新增 `test_paint.py`；API/原生测试保持全绿；
- CI 去掉静态资源打包与 `page-search` 检查，`webcheck`/serve 冒烟改为 API-only；
- 更新 README/第三方声明中的 WebView2/pywebview 描述。
