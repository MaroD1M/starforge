# 同伴/生物 3D 建模研究

> 结论先行：同伴 **3D 预览目前不能可靠实现**，但数据链和社区路线已经明确；当前版本只读展示同伴描述符/种子，不伪造模型。

## 1. 数据来源

| 数据 | 来源 | 当前状态 |
|---|---|---|
| 同伴条目 | 存档 `PlayerStateData.Pets[]` | ✅ 已读取 |
| 描述符 | `Descriptors`（`_BODY_*`、`_HEAD_*`、`_MESH_*`、`_SHAPE_*`） | ✅ 已读取 |
| 种子 | `CreatureSeed` / `SpeciesSeed` / `GenusSeed` | ✅ 已读取 |
| 角色表 | 游戏 `CreatureDataTable.mbin`（86 条角色） | 🟡 已能读角色名/类型，外观数据 `Data` 未解 |
| 几何/贴图 | `NMSARC.MeshPlanetCREATURES.pak`、`TexCreature*.pak` | 需要生成器决定部件组合 |
| 生物生成器 | `cGcPlanetGenerator::GenerateCreatureRoles/CreateCreatureSpawnData` | 🔴 需 agent/逆向后才能离线复现 |

## 2. 社区项目

| 项目 | 能借鉴什么 |
|---|---|
| [NMSCD/Creature-Builder](https://github.com/NMSCD/Creature-Builder) | 部件选择、合法性约束、JSON 导出；Web/Electron |
| [NMSE](https://github.com/vectorcmdr/NMSE) | Companion 编辑、生物部件/颜色/战斗数据；AGPL/游戏派生代码需注意许可 |
| [NMS Creature Builder+](https://nms-creature-builder.fun/) | 3D 预览管线：NMSDK 抽取几何/贴图，转 compressed glTF + three.js |
| NMSDK / MBINCompiler | 从游戏 pak/MBIN 抽模型、材质、骨架 |

> 注意：NMSE 的部分代码/数据是从游戏逆向而来，许可与再分发边界不同于普通 MIT；我们不能直接复制它的派生代码/资产。

## 3. 可落地路线

1. **P0（安全）**：同伴列表、描述符、种子、群系、角色表；当前已实现。
2. **P1（只读预览）**：
   - 用 NMSDK/MBINCompiler 从玩家本地游戏提取 creature rig/mesh/texture；
   - 用描述符选择部件组合，拼成 glTF；
   - 在原生 OpenGL 视口渲染；缺资源时明确降级。
3. **P2（生成器）**：
   - 解析 `GenerateCreatureRoles` / `SpawnData`，按星球 seed 列出全部物种；
   - 支持按外观/角色搜索种子。
4. **P3（编辑/写回）**：
   - 同伴改名、描述符、颜色、信任/特征；
   - 写前备份、原子写、读回、回滚；必须与 NMSE/Creature-Builder 的字段语义对齐。

## 4. 当前 UI 行为

- 同伴标签显示：名称、类型、群系、CreatureID、种子、信任/特征数量；
- 切换同伴标签时右侧不再错误显示飞船 3D，而是显示“3D 需要生物生成器”；
- 不伪造模型、不生成假缩略图。

## 5. 下一步

先做 P1 的资源提取 spike（NMSDK/本地 pak → glTF），验证一个真实同伴的几何/贴图；再决定是否内置生成器。
