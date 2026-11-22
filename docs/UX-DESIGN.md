# 界面规范（v0.16 重构）

> 目标不是“更好看”，而是**让用户一眼知道现在该做什么、下一步点哪里**。
> 所有页面共用同一套骨架；新增页面先读本文，再写代码。

---

## 1. 设计原则

1. **一屏一个任务**：搜索 / 查看 / 执行三件事不要同时抢注意力。
2. **结果优先**：表格/网格占主要空间；详情默认不出现，选中后才展开。
3. **渐进披露**：常用筛选 3 个以内；其余收进「筛选」面板；已选条件用 chips 显示。
4. **一个主操作**：每页只有 1 个 primary；其它动作降为 ghost 或进「更多」。
5. **文字只留一句**：页头说明最多 1 行；解释放 tooltip；状态不重复写三遍。
6. **空态给下一步**：一句原因 + 一个按钮，不写两段说明、不显示假数据。
7. **风险分级**：只读 / 写存档 / 写内存 / 改世界状态；危险按钮独立配色 + 二次确认。

## 2. 参考的开源设计系统（只借规则，不复制代码）

| 来源 | 借什么 |
|---|---|
| **IBM Carbon**（Apache-2.0） | 一个页面一个主操作；数据表优先；渐进披露；表单两列上限 |
| **GitHub Primer**（MIT） | 紧凑工具栏；筛选 chips；空态结构；表格密度 |
| **Shopify Polaris**（MIT） | Resource list + filters + empty state；主操作固定位置 |
| **Material 3**（Apache-2.0） | 步骤/分段控件；chip；顶部 app bar 的层级 |
| **Fluent 2 / Vercel Geist**（MIT） | 8px 网格；桌面密度；少装饰；单一强调色 |
| **Linear**（交互参考） | 列表优先；命令面板；最小化 chrome |

不引入这些库，只把它们验证过的**布局与交互规则**落到 Qt 组件里。

## 3. 页面骨架

```
PageHeader      标题（18px）+ 一行说明（11.5px）+ 右侧 primary / 更多
TaskFlow        ① ② ③ 一行步骤，标出当前位置（可选，任务型页面必须有）
Toolbar         一行：常用筛选 / 搜索框 + 「筛选」+ 状态
FilterChips     已生效条件，可单个删除（为空时隐藏）
FilterPanel     次要筛选，默认收起
Content         表格 / 网格，占剩余空间
DetailPanel     选中后才出现；右上 × 收起；不占位时不挤压结果
```

组件在 `starforge/app/widgets/ux.py`：

```python
from ..widgets.ux import TaskFlow, FilterChips, FilterPanel

flow = TaskFlow(["选条件", "搜索", "送进游戏"])
flow.set_active(1, done=(0,))       # 第 2 步高亮，第 1 步打勾
chips = FilterChips(); chips.removed.connect(on_remove)
chips.set_filters([("biome", "群系 茂盛")])
panel = FilterPanel(); panel.body.addWidget(...)
```

## 4. 文本规则

- 页头说明 ≤ 24 个汉字；超出的放 tooltip。
- 同一个状态只在一处显示：页头 / 行内 / 状态栏三选一。
- 按钮用动词：“开始搜索”“送进游戏”“传送到此星球”，不用“确定/执行”。
- 错误消息 = 原因 + 下一步，不贴堆栈。
- 数字带单位与范围（`3,225 ly`、`500 条`）。

## 5. 状态与风险

| 动作 | 颜色/文案 | 要求 |
|---|---|---|
| 只读查询 | ghost | 无确认 |
| 写存档 / 写模板槽 | danger / primary + 风险徽标 | 预览 before/after + 备份 + 可回滚 |
| 注入 / 改世界状态 | danger | 二次确认 + 明确“仅单人” |

## 6. 审计清单（每次改页面必跑）

- 1280×800、1180×760、1.25× DPI 三档截图。
- 越界 = 0；同级控件重叠 = 0；文本截断 = 0；隐藏的横向溢出 = 0。
- 每页恰好 1 个 primary。
- 空态、加载态、失败态各有明确文案与下一步。
- Tab 顺序：导航 → 顶部状态 → 页面工具条 → 内容 → 任务栏。

## 7. 已落地示例

- `starforge/app/pages/ship_lab.py`：TaskFlow + 条件卡 + 结果区；详情默认隐藏，选中/「看详情」才展开。
- `starforge/app/pages/galaxy.py::_build_discovered_page`：TaskFlow + 一行常用筛选 + 「筛选」面板 + 结果表；详情选中才出现。
- `starforge/app/pages/galaxy.py` 星图：上下文（当前星系）+ TaskFlow + 筛选 + 子标签 + 结果；详情按需。
