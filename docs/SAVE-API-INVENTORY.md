# 存档 API 盘点：NMS-Shipwright → starforge

> 研究日期：2026-11-18  
> 范围：`NMS-Shipwright/nms_save/*.py`、`starforge/save/*.py`、`starforge/services/*.py`、`starforge/web/routes.py`、原生页面与对话框。  
> 性质：**只读研究，未改代码、未提交、未构建**。  
> 结论口径：只讨论“存档文件编辑”；不把游戏内内存修改（agent / pymhf / Unicorn）算进本清单。

相关本地依据：

- `NMS-Shipwright/nms_save/{save,codec,mapping,ships,items,player,extras,quests,corvette}.py`
- `NMS-Shipwright/webapp/routes/{ships,inventory,player,corvette}.py`
- `NMS-Shipwright/README.md`、`Gagarin_Titov/README.md`、`NMS-Super-Ship-Hunter/README.md`
- `starforge/save/{library,writer}.py`
- `starforge/services/__init__.py`、`starforge/services/favorites.py`、`starforge/services/history.py`
- `starforge/web/routes.py`
- `starforge/app/pages/{fleet,ship_lab,ship_designer,game_link}.py`
- `starforge/app/dialogs/{write_back,class_editor,backup}.py`
- `starforge/tests/test_writer.py`
- 既有差距文档：`docs/GAP-ANALYSIS.md`、`docs/FEATURE-MAP.md`（部分状态已过时，以本文件代码事实为准）

---

## 0. 结论先行

### 0.1 现在的真实状态

starforge 当前只接入了 Shipwright 的 **两类存档写操作**：

1. **同型换种子**：`writer.apply_seed` → `ships.set_ship_seed`，入口 `ShipLab → WriteBackDialog`、`POST /api/saves/apply`。
2. **船级/属性**：`writer.apply_class` → `ships.set_ship_stats`，入口 `Fleet → ClassEditorDialog`、`POST /api/saves/class`。

另有 **备份列表/恢复**：`writer.backups` / `writer.restore`，入口 `Fleet → BackupDialog`、`GET /api/saves/backups`、`POST /api/saves/restore`。

读侧只接入了：存档目录扫描/分类、船只列表、船级/属性摘要、同伴列表、备份列表；没有接入库存、货船、护卫舰、多工具、任务、解锁、奖励、Corvette、基地、发现、定居点、中队、原始 JSON。

### 0.2 最重要的判断

- **Shipwright 的领域函数绝大多数是“内存树编辑”**，本身不负责备份、原子写、读回、回滚。它们不能直接暴露成 starforge 写接口。
- **Shipwright 的 `OpenSave.write()` 不是原子写**，也没有读回校验和回滚；starforge 的 `writer.py` 已经明确不用它，这是正确的。
- **`corvette.write_both()` 用了 `OpenSave.write()`**，因此它也不满足 starforge 的写入铁律；Corvette 写回必须先改造成多文件事务。
- **可以直接接、且用户价值最高的是货币、改名、涂装、库存“修/充/补”和安全数量的物品编辑**；最危险的是扩容/解锁槽位、造删船、直接写部件树、原始 JSON、基地结构、Corvette 双文件写。
- **“其他项目有”不等于“能安全接”**。NMSSaveEditor 的基地结构、定居点、账号奖励、中队、发现/里程碑，Shipwright 没有对应 API；Gagarin 的强项是基地/Corvette 结构、游戏内传送/扫描，不是通用存档编辑器。

### 0.3 推荐的第一批（只做这 4 件）

1. 通用安全写入事务（所有新写操作的唯一入口）。
2. 货币（Units / Nanites / Quicksilver）。
3. 飞船改名 + 涂装（含清除涂装）。
4. 库存只读 + `fill / recharge / repair / 安全 amount / set`（先不做扩容/解锁槽位）。

---

## 1. 已存在且已接入的 API

### 1.1 读 API

| 能力 | 实际函数（文件:函数） | starforge 入口 | 参数 | 返回 | 主要异常 |
|---|---|---|---|---|---|
| 存档目录扫描/分类 | `save/library.py:classify`、`probe`、`scan_dir` | `Services.saves`、`GET /api/saves` | `folder`（可空） | `{dir, found, files[], usable[]}` | `OSError`；单个文件错误写进 `error` |
| 打开存档/解码 | `nms_save/save.py:open_save` → `codec.decode` → `mapping.deobfuscate` | 被 `library.open_ships`、`creature`、`system` 间接使用 | `path` | `OpenSave(path, readable, _chunked, _trailing_nul)` | `SaveFormatError`、`json.JSONDecodeError`、`OSError`、`lz4.block.LZ4BlockError` |
| 玩家存档判定 | `save/library.py:classify`、`PLAYER_SAVE_RE`、`ACCOUNT_RE`、`MANIFEST_RE` | `library.resolve`、`probe` | 文件名/头 4 字节 | `player` / `account` / `manifest` / `unknown` | 不抛；`accountdata.hg`、`mf_*.hg` 明确不适用 |
| 船只列表 + 属性摘要 | `nms_save/ships.py:list_ships` + `ship_stats`；`library.open_ships`；`ShipRef.from_save_ship` | `Services.ships`、`GET /api/ships`、`FleetPage._load` | `path` | `(list[ShipRef], warnings[])`；`ShipRef` 含 `type/seed/slot/name/model/procedural/ship_class/stats`（`parts` 只在搜索/设计里用，不从存档读） | `SaveNotFound`、`SaveFormatError`；单船转换失败进 `warnings` |
| 默认存档选择 | `save/library.py:default_save_path` | `Services.default_save`、`WriteBackDialog._load_default` | 无 | `Path` | `SaveNotFound` |
| 备份列表 | `nms_save/save.py:backups_of`；`save/writer.py:backups` | `Services.backups`、`GET /api/saves/backups`、`BackupDialog.refresh` | `path` | `[{"path","bytes","mtime"}]` | `OSError` |
| 同伴只读（更丰富） | `starforge/creature.py:companions`（直接读 `PlayerStateData.Pets`，不是 `extras.companions`） | `Services.creatures`、`GET /api/creatures`、`FleetPage → PetsView` | `save_path`（可空） | `{path,count,creatures[],note,preview}`；每条含 `creature/descriptors/seeds/scale/biome/trust/...` | `SaveNotFound`、`SaveFormatError`、`KeyError` |
| 当前位置/已知星系读取 | `starforge/system.py` 调用 `nms_save.save.open_save` | Galaxy / 地址工作台 | `save_path` | 位置/已知系统 | 同 `open_save` |
| 备份保留策略（只读） | `nms_save/save.py:keep_count` | 未接入 | 无 | `int` | 读设置失败时退回 20 |

### 1.2 写 API

| 能力 | 实际函数（文件:函数） | starforge 入口 | 参数 | 返回 | 主要异常 |
|---|---|---|---|---|---|
| 同型换种子 | `nms_save/ships.py:set_ship_seed`；`starforge/save/writer.py:apply_seed` | `ShipLab → WriteBackDialog`、`POST /api/saves/apply`、`Services.apply_seed` | `save_path, slot, ShipRef, confirm, copy` | `{ok,path,original,copy,slot,type,before,after,backup,bytes,verified}` | `WriteDisabled`、`BadRequest`、`WriteRefused`、`ShipLookupError`、`ValueError` |
| 船级/属性 | `nms_save/ships.py:set_ship_stats`；`starforge/save/writer.py:apply_class` | `Fleet → ClassEditorDialog`、`POST /api/saves/class`、`Services.apply_class` | `save_path, slot, ship_class(C/B/A/S), values, best, confirm, copy` | `{ok,path,original,copy,slot,backup,bytes,before,after,ships_untouched,verified}` | `WriteDisabled`、`BadRequest`、`WriteRefused`、`ShipLookupError`、`ValueError` |
| 从备份恢复 | `starforge/save/writer.py:restore` | `Fleet → BackupDialog._restore`、`POST /api/saves/restore`、`Services.restore` | `save_path, backup_path, confirm` | `{ok,path,restored_from,safety_copy}` | `WriteDisabled`、`BadRequest`、`WriteRefused`、`OSError` |
| 备份列表 | `starforge/save/writer.py:backups` | `Fleet → BackupDialog` | `save_path` | `[{path,bytes,mtime}]` | `OSError` |

### 1.3 codec / mapping 的接入方式

- `starforge/save/writer.py:_nms()` 延迟导入 `nms_save.codec`、`nms_save.mapping`、`nms_save.save`、`nms_save.ships`。
- `writer._encode(opened)` 使用 `mapping.obfuscate(opened.readable)` + `json.dumps` + `codec.encode(text, opened._chunked, opened._trailing_nul)`。
- 读路径由 `nms_save.save.open_save` 内部使用 `codec.decode` + `mapping.deobfuscate`。
- **没有使用** `OpenSave.write()`；这是有意的安全选择。

### 1.4 已接入写操作的安全能力对照

| 写入口 | 写开关 | 二次确认 | 游戏运行检测 | 备份 | 原子写 | 读回校验 | 失败回滚 | 其它不变量校验 |
|---|---|---|---|---|---|---|---|---|
| `writer.apply_seed` | ✅ `settings.require_write` | ✅ `confirm` | ✅ `game_running` | ✅ `_backup` | ✅ `.part` + `fsync` + `os.replace` | ✅ 目标槽 `seed` | ✅ 原始字节 | ❌ 其它船/其它字段未校验 |
| `writer.apply_class` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 目标 `class` + 全船 `seed` 映射 | ✅ 原始字节 | ✅ 其它船种子不变；❌ 库存/名称/涂装未校验 |
| `writer.restore` | ✅ | ✅ | ✅ | ✅ 恢复前 safety copy | ✅ | ⚠️ 只 `open_save` 能打开 | ❌ 没有“读回失败后回滚” | ⚠️ 只校验备份文件名前缀 |
| `nms_save.save.OpenSave.write` | ❌ | ❌ | ❌ | ✅ 默认备份 | ❌ 直接 `open(path,"wb")` | ❌ | ❌ | ❌ |
| `nms_save.corvette.write_both` | ❌ | ❌ | ❌ | ✅ 每个文件 | ❌ 走 `OpenSave.write` | ❌ | ❌ | ❌ 多文件无事务 |

> 结论：**starforge 现在的两个写用例是安全的，但这种安全来自 `writer.py`，不是来自 Shipwright 的领域函数。任何新功能都不能绕过 `writer.py` 直接调用 `OpenSave.write()`。**

### 1.5 已接入项的关键字段（便于对照）

| 已接入能力 | 关键字段 |
|---|---|
| 船只列表读 | `BaseContext.PlayerStateData.ShipOwnership[].Name`、`.Resource.Filename`、`.Resource.Seed[1]`、`.Inventory.BaseStatValues[].BaseStatID/Value`、`.Inventory.Class.InventoryClass` |
| 同型换种子写 | `ShipOwnership[slot].Resource.Seed = [原 flag, 新 seed]`；**不改** `.Resource.Filename`，因此父级船型/槽位不变 |
| 船级/属性写 | `ShipOwnership[slot].Inventory`、`Inventory_TechOnly`、`Inventory_Cargo` 的 `.BaseStatValues[].BaseStatID/Value`；每个存在的 `.Class.InventoryClass`；并校验其它船 `.Resource.Seed` 未变 |
| 备份列表 | `<save>.<YYYYmmdd-HHMMSS-micros>.bak` 文件名；`bytes`/`mtime` 只用于展示 |
| 恢复 | 整文件字节覆盖；恢复前另写一份 `<save>.<stamp>.bak` safety copy |
| 同伴只读 | `BaseContext.PlayerStateData.Pets[].CreatureID/CustomName/Descriptors/CreatureSeed/...`（只读，不写） |

---

## 2. 已存在但未接入的 API

### 2.0 其他项目已有能力 → Shipwright API → starforge 接入判断

| 能力 | NMSSaveEditor | Gagarin 系 | Shipwright API | starforge 现状 | 判断 |
|---|---|---|---|---|---|
| 货币 Units/Nanites/Quicksilver | ✅ | ❌（游戏内 mod 不做存档货币） | `player.get_currencies/set_currencies` | ❌ | ✅ 可直接接 |
| 飞船改名 | ✅ | 部分（builder 内） | `ships.set_ship_name` | ❌ | ✅ 可直接接 |
| 飞船涂装/清除 | 部分 | ✅ 颜色/材质预览 | `ships.get/set/clear_ship_paint`、`set_sentinel_paint` | ❌ | 🟡 普通涂装；🔴 sentinel 实验 |
| 船级/属性 | ✅ | ❌ | `ships.ship_stats/set_ship_stats` | ✅（Fleet 对话框） | 已接入 |
| 船型/模型/种子 | ✅ | ✅ 搜索/建造 | `ships.set_ship_model`、`set_ship_seed` | 种子 ✅；模型 ❌ | 种子已接入；模型 🔴 |
| 造新船/删船/特殊船 | ✅ | 部分 | `ships.create_ship/remove_ship/install_special_ship` | ❌ | 🔴 高风险 |
| 船部件树 | 部分 | ✅ builder | **无直接 setter**；部件由 seed 生成 | ❌ | 🟡 只能“设计→搜 seed→写 seed” |
| 库存物品 | ✅ | ❌ | `items.list_inventories/get_inventory/edit_inventory` | ❌ | 🟡 读 + 安全操作；扩容 🔴 |
| 货船 | ✅ | 部分（基地/货船结构） | `ships.get_freighter/set_freighter` + `items` 的 `FreighterInventory*` | ❌ | 🟡 种子/库存；结构 🔴 |
| 护卫舰 | ✅ | ❌ | `extras.frigates/edit_frigate` | ❌ | 🟡 改名/等级/修复；任意属性 🔴 |
| 多工具 | ✅ | ❌ | `extras.multitools/edit_multitool` + `Multitools.N.Store` | ❌ | 🟡 改名/等级；种子需实测 |
| 同伴 | ✅ | ❌ | `extras.companions/edit_companion` | 只读更丰富（starforge 自有） | 🟡 名字/体型 |
| 任务 | 部分（raw） | ❌ | `quests.list_quests/skip_quests` | ❌ | 🟡 读/跳过；关键任务 🔴 |
| 解锁/词语/奖励 | ✅ | ❌ | `extras.knowledge/learn_words/learn_all/rewards/set_rewards` | ❌ | 🟡 只做加白名单；账号奖励 ⛔ |
| 基地结构 | ✅ 备份/恢复 | ✅ Builder 读写基地/货船/Corvette | **无通用基地 API**（只有 Corvette 的 `PersistentPlayerBases` 筛选） | ❌ | 🔴/⛔ 不建议近期做 |
| 基地库存 | ✅ | 部分 | `items` 的 `Chest1..10Inventory` 等 | ❌ | 🟡 |
| Corvette | 部分（新版本） | ✅ Builder | `corvette.layouts/modules/place/move/replace/remove/write_both` | ❌ | 读 ✅；写 🟡（需多文件事务） |
| 发现/里程碑/符文 | ✅ | 部分（扫描/传送） | **无 API**（只有词语/科技/产品） | ❌ | 🔴 需逆向/raw |
| 定居点 | ✅ | ❌ | **无 API** | ❌ | 🔴/⛔ |
| 中队/僚机 | ✅ | ❌ | **无 API** | ❌ | 🔴 需逆向 |
| 账号奖励/accountdata | ✅ | ❌ | **无 API**；`library` 明确拒绝 `accountdata.hg` | ❌ | ⛔ 不做 |
| 原始 JSON | ✅ 高级 | ❌ | `extras.browse/get_path/set_path`；webapp 的 save export/import | ❌ | 🔴 仅隐藏诊断，不做普通功能 |
| 备份保留/清理 | ✅ | ✅ | `save.backups_of/keep_count/prune_backups` | 只列/恢复，不清理 | 🟡 低风险 |

> Gagarin 说明：本地 `Gagarin_Titov` 是**游戏内 mod**（行星/飞船搜索、传送、任意建造、开发者选项），不是通用存档编辑器；新版 Gagarin Builder 才是基地/Corvette 结构编辑器。把它当作“结构编辑”参考，不要当作“所有字段都有安全 API”的依据。

### 2.1 船级/属性/名称/涂装/模型

| API（文件:函数） | 参数 | 字段/路径 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|---|
| `ships.set_ship_name(readable_json, slot, name)` | `slot:int, name:str` | `BaseContext.PlayerStateData.ShipOwnership[slot].Name` | `None` | `ShipLookupError` | ✅ | 最简单、最安全；上游不截断，UI 应 `name[:64]` 并读回 |
| `ships.get_ship_paint(readable_json, slot)` | `slot:int` | `CharacterCustomisationData[customisation_index(slot)].CustomData.PaletteID/Colours` | `dict 或 None`（`palette/primary/accent/primary_index/accent_index/channels`） | `ShipLookupError`、`KeyError` | ✅ 读 | 只读无风险；槽位 0–11 才有自定义项 |
| `ships.set_ship_paint(readable_json, slot, primary=(0,0,0), accent=None, palette_id="FREIGHTER", primary_index=None, accent_index=None, channels=None)` | 颜色 RGB、调色板、槽位索引、按通道 | `CustomData.PaletteID = "^"+palette_id`；`CustomData.Colours[]`（`Palette.Palette="Paint"`、`ColourAlt`、`Index`、`Colour`） | `{palette,primary_index,accent_index,channels}` | `ShipLookupError`、`ValueError`、`OSError`（Shipwright `data/palettes/customisation.json` 缺失） | 🟡 | 需校验 `palette_id` 存在；未知 palette 当前会写成 `^UNKNOWN` 且 `index=-1`。Sentinel 可能“种子决定车身色”，涂装只到钳子/局部；UI 要提示 |
| `ships.clear_ship_paint(readable_json, slot, texture=True, customisation=True)` | `slot:int` | `ShipOwnership[slot].Resource.ProceduralTexture={"Samplers":[]}`；`CustomData.PaletteID="^"`、`Colours=[]` | `None` | `ShipLookupError` | ✅/🟡 | 安全；注意不会清 `TextureOptions` |
| `ships.set_texture_options(readable_json, slot, options)` | `[(group,name)]` | `CustomData.TextureOptions[]` | `list` | `ShipLookupError` | ⛔ | 文件内已实测“不选择图层”，作者明确写“不要基于它做功能” |
| `ships.get_texture_options(readable_json, slot)` | `slot:int` | `CustomData.TextureOptions` | `list` | 无 | ✅ 读/低价值 | 只适合诊断 |
| `ships.set_sentinel_paint(readable_json, index, colour=(0,0,0), overlay="4", fixed="1", customisation=True, palette_id="SHIP")` | 颜色、overlay 1–4、fixed 1/2 | `Resource.ProceduralTexture.Samplers[].Options[]`（`FIXED/OVERLAY/BASE`、`Group/Layer/Palette/OverrideColour`） | `dict` | `ShipLookupError`、`ValueError` | 🔴 | 文件内标注 experimental；无参考存档的 sentinel 涂装样本；容易写出游戏不认的结构 |
| `ships.set_ship_model(readable_json, slot, filename, seed=None)` | `slot, filename, seed` | `ShipOwnership[slot].Resource.Filename`、`Seed`；若跨越 sentinel/普通船还会 `set_core_tech` | `None` | `ShipLookupError`、`ValueError` | 🔴 | 换型会牵动部件树/库存/科技/拦截机标记；必须有“目标型号合法 + 备份 + 副本默认 + 回滚” |
| `ships.set_core_tech(readable_json, slot, sentinel)` | `slot, sentinel:bool` | `Inventory_TechOnly`/`Inventory` 的 `Slots[].Id/Amount/MaxAmount/DamageFactor/FullyInstalled`；`BaseStatValues`；`Class.InventoryClass`；`KnownTech` | `[(old,new)]` | `ShipLookupError`、`ValueError`、`KeyError` | 🟡 | 同型“补全原厂科技”风险可控；会改库存和 `KnownTech`，需要精确读回 |
| `ships.wrong_core_tech(entry)` | 单个 ship entry | 对比 `CORE_TECH`、`ROBOT_SHIP` 标记 | `list[str]` | 无 | ✅ 读/诊断 | 低价值，适合 Inspector 诊断徽标 |
| `ships.ship_stats(readable_json, slot)` | `slot` | `Inventory.BaseStatValues`、`Inventory.Class.InventoryClass` | `{slot,class,stats[],sentinel}` | `ShipLookupError` | ✅ 已接入 | `writer.apply_class` 使用 |
| `ships.set_ship_stats(readable_json, slot, values=None, ship_class=None, best=False)` | 属性字典、C/B/A/S、best | 三个 `SHIP_INVENTORIES` 的 `BaseStatValues`、`Class.InventoryClass` | `dict` | `ShipLookupError`、`ValueError` | ✅ 已接入 | 有区间校验；但只有目标 class 和全船 seed 被写后核对 |

### 2.2 船槽/创建/删除/归档/特殊船

| API（文件:函数） | 参数 | 字段/路径 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|---|
| `ships.list_archived(readable_json)` | 无 | `PlayerStateData.ArchivedShipOwnership[]`；每个 `Ownership` + `ArchivedName` | `list[Ship]` | 无（缺路径返回 `[]`） | ✅ 读 | 只读展示很安全；注意 `Ship.index` 是归档列表下标，**不是** `ShipOwnership` 槽位，不能直接传给 `set_ship_seed` |
| `ships.create_ship(readable_json, slot, filename, seed, name, clone_from, standard=False)` | `slot` 必须空；`clone_from` 必须是已有船；`standard` 清空所有 `Slots` | `ShipOwnership[slot] = deepcopy(donor)`；`Resource.Filename/Seed/ProceduralTexture`；`Name`；`set_core_tech`；`clear_ship_paint`；`ShipUsesLegacyColours` | `None` | `ShipLookupError`、`ValueError`、`KeyError` | 🔴 | 新建船会继承/清空库存与科技；写错槽位/克隆源会丢东西；需要“空槽 + 目标型号 + 备份 + 副本 + 读回库存/科技” |
| `ships.remove_ship(readable_json, slot)` | `slot` | 用另一个空槽 deepcopy，或 `_blanked()`；清 `Resource.Filename/AltId/Seed/ProceduralTexture`；三个库存缩成 1×1；`ShipUsesLegacyColours=false` | `None` | `ShipLookupError` | 🔴 | 数据丢失型操作；备份可救，但 UI 要强确认、默认副本 |
| `ships.install_special_ship(readable_json, slot, entry, name=None)` | 完整 entry、可选名 | 整个 `ShipOwnership[slot] = deepcopy(entry)`；`_learn_tech`；`clear_ship_paint` | `None` | `ShipLookupError`、`KeyError` | 🔴 | 完全信任外部 JSON；Shipwright 只有 `data/special_ships/starborn_phoenix.json` 一个样本；版本/字段漂移风险高 |

### 2.3 船部件/设计（关键事实）

| 需求 | 现有 API | 事实 | 可行性 | 说明 |
|---|---|---|---|---|
| “把选中的部件写进存档” | **没有** `set_parts` / `set_part_tree` | 存档只存 `Resource.Filename` + `Resource.Seed`；部件是程序化生成结果 | 🟡 | 正确路线只能是：设计部件 → 搜索匹配 seed → `set_ship_seed`（或 `create_ship`）。不能直接写 `parts[]` |
| 设计器写回 | `ShipRef.parts` 只用于搜索/预览 | `ShipLab` 的 `WriteBackDialog` 写的是 seed；`ship_designer.py` 的写按钮被禁用 | 🟡 | 先做“设计 → 搜 seed → 确认外观 → 同型写 seed”；不要承诺“任意部件组合直接写” |
| 换船型 | `ships.set_ship_model` | 改 `Filename/Seed`，可能触发 `set_core_tech` | 🔴 | 跨型部件树不同，`writer.apply_seed` 已有“跨型不可移植”拒绝；换型是另一类高风险功能 |

### 2.4 库存/物品

`items.py` 的库存地址示例：`Inventory`、`Inventory_TechOnly`、`ShipOwnership.3.Inventory_TechOnly`、`Multitools.0.Store`、`FreighterInventory`、`Chest1Inventory`、`VehicleOwnership.0.Inventory`、`CorvetteStorageInventory`。

| API（文件:函数） | 参数 | 字段/路径 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|---|
| `items.list_inventories(readable)` | 无 | 遍历 `PlayerStateData` 的 `Inventory*`、`ShipOwnership[].Inventory*`、`FreighterInventory*`、`Multitools[].Store`、`VehicleOwnership[].Inventory*`、`Chest1..10Inventory`、`ChestMagic*`、`CookingIngredientsInventory`、`CorvetteStorageInventory`、`FishPlatformInventory`、`FishBaitBoxInventory`、`FoodUnitInventory` | `[{path,name,group,used,slots,width,height,class}]` | `ItemError`、`KeyError`（个别条目缺 `Store` 时） | ✅ 读 | **不包含** `ArchivedShipOwnership` 的库存；基地区域只覆盖“基地库存”，不覆盖基地结构 |
| `items.get_inventory(readable, path)` | `path` | 目标 inventory 的 `Width/Height/ValidSlotIndices/Class/Slots[]` | `{path,width,height,valid,class,slots,max_slots}` | `ItemError`、`KeyError`、`IndexError` | ✅ 读 | `slots[]` 含 `x,y,id,name,type,amount,max,damaged` |
| `items.edit_inventory(readable, path, op, **kw)` | `op` 及 `x,y,id,amount,count` | 见下各 op | 最新 `get_inventory` | `ItemError`、`KeyError`、`IndexError` | 🟡/🔴 | 所有操作都是内存修改；没有备份/原子写/读回 |
| `items.catalogue()` / `items.item(iid)` / `items.search_items(query,kind,limit)` | 物品 id/查询 | 游戏表 `nms_reality_gc{substance,product,technology}table.mbin` + `gamemeta` | 物品元数据 / 搜索结果 | `ItemError`、`OSError`、`struct.error` | ✅ 读 | 依赖游戏文件；缺文件时 `item()` 会退化为裸 id，但 `_new_slot` 可能因 `type` 为空而 `ItemError` |
| `items.inventory_caps()` | 无 | `inventorytable.mbin` 的 `ShipInventoryMaxUpgradeSize` / `WeaponInventoryMaxUpgradeSize` | `{ship:{row:{general,tech}},weapon}` | `ItemError`、`OSError`、`struct.error` | ✅ 读 | 用于扩容上限；游戏文件缺失时 `max_slots` 返回 `None` |
| `items.stat_ranges()` | 无 | `inventorytable.mbin` 的 `ShipBaseStatsData/BaseStatsPerClass` | `{ships:{row:{class:[{id,name,min,max}]}}}` | `ItemError`、`OSError`、`struct.error` | ✅ 读 | `set_ship_stats` 的区间来源 |
| `items.max_slots(readable,path,inv)` | `path, inv` | 按 `path` 前缀判断 ship/freighter/multitool | `int 或 None` | 捕获 `inventory_caps` 异常；`_resolve_parent` 可能 `KeyError` | ✅ 读 | `None` 表示“游戏表没说”，不要当成无限 |

`edit_inventory` 各 op 的单独判断：

| op | 参数 | 行为 | 可行性 | 风险/要求 |
|---|---|---|---|---|
| `set` | `x,y,id,amount?` | 在已解锁槽位放一个物品，替换原物品；`amount` 夹到 stack/charge | 🟡 | 必须只用 `list_inventories` 返回的 path；校验 id 存在；`amount` 只允许 ≤ `MaxAmount` |
| `amount` | `x,y,amount` | 改堆叠；技术最低 0，物品最低 1；**会把 `MaxAmount` 提高到 `amount`** | 🟡/🔴 | 当前可造出超过游戏 stack 的 `MaxAmount`；必须加“≤ 原 MaxAmount/目录 stack”限制 |
| `remove` | `x,y` | 删除槽位物品 | ✅/🟡 | 安全；确认是用户要删的那一格 |
| `fill` | 无 | 所有非技术物品补满 | ✅/🟡 | 安全、用户价值高；不会改槽位数 |
| `recharge` | 无 | 所有技术充满 | ✅/🟡 | 安全、用户价值高 |
| `repair` | 无 | `DamageFactor=0`、`FullyInstalled=True` | ✅/🟡 | 安全、用户价值高 |
| `expand` / `slots` | `count?` | 按 `max_slots` 或指定数量增减槽位；已占用槽位被删会拒绝 | 🟡/🔴 | `max_slots=None` 时会用当前 grid；游戏版本/存档可能拒绝；必须先备份、默认副本、只允许“向 cap 扩”不允许缩 |
| `unlock` | `x,y` | 增加一个 `ValidSlotIndices`，可扩 `Width/Height` | 🟡/🔴 | 可绕过游戏上限（`cap` 为 None 时）；可能造出游戏不认的槽位 |
| `lock` | `x,y` | 删除一个空槽 | 🟡/🔴 | 必须空格；会改变 `ValidSlotIndices`；不建议首批开放 |

> 重要：`edit_inventory` 没有“总负重/任务物品/已装备 tech 依赖”校验；`amount` 还会主动抬高 `MaxAmount`。所以不能把上游 op 原样映射成 UI 按钮。

### 2.5 单位/纳米/水银

| API（文件:函数） | 参数 | 字段/路径 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|---|
| `player.get_currencies(readable_json)` | 无 | `PlayerStateData.Units`、`Nanites`、`Specials` | `{"units","nanites","quicksilver"}` | `KeyError` | ✅ 读 | 简单 |
| `player.set_currencies(readable_json, **values)` | `units=, nanites=, quicksilver=` | 同上 | 最新值 | `ValueError`（未知币种/越界） | ✅ 可直接接 | 上游限制 `0..2**31-1`（有符号 32 位）；社区工具常写 4,294,967,295，需以实机为准，不要盲目改成无符号上限 |
| `player.primary_ship(readable_json)` | 无 | `PlayerStateData.PrimaryShip` | `int` | `KeyError` | ✅ 读/低价值 | 可在 Fleet 标“主舰” |

`accountdata.hg` 不是玩家存档：`library.classify` 标为 `account`，`open_ships` 明确拒绝。账号级奖励/解锁不要试图从这里接。

### 2.6 货船

| API（文件:函数） | 参数 | 字段/路径 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|---|
| `ships.get_freighter(readable_json)` | 无 | `PlayerStateData.CurrentFreighter.Filename/Seed`、`CurrentFreighterHomeSystemSeed` | `{filename,seed,home}` | `KeyError` | ✅ 读 | 只读展示很安全 |
| `ships.set_freighter(readable_json, kind, seed, home_ua=None)` | `kind` ∈ `freighter/capital_freighter` | `CurrentFreighter.Filename/Seed`；`CurrentFreighterHomeSystemSeed` | `None` | `ValueError`（无货船/类型/种子） | 🟡 | 必须已有货船；只改模型/种子/家乡星系种子，不改货船库存/科技/基地；颜色由 home system seed 驱动，写错会变颜色 |
| `items.list_inventories` + `edit_inventory` 的 `FreighterInventory*` | 见库存 | `FreighterInventory`、`_TechOnly`、`_Cargo` | 见库存 | 见库存 | 🟡 | 货船库存可编辑；`max_slots` 对货船按 row 0 处理 |
| 货船基地结构/房间/货舱建造 | **无** | `PersistentPlayerBases` 只被 Corvette 用来筛 `PlayerShipBase` | — | — | 🔴/⛔ | Gagarin/NMSSaveEditor 有，但 Shipwright 没有通用基地 API；不要近期做 |

### 2.7 护卫舰 / 中队

| API（文件:函数） | 参数 | 字段/路径 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|---|
| `extras.frigates(readable)` | 无 | `PlayerStateData.FleetFrigates[]`：`CustomName`、`FrigateClass.FrigateClass`、`InventoryClass.InventoryClass`、`Stats[]`、`DamageTaken`、`TotalNumberOfExpeditions`、`ResourceSeed` | `list[dict]` | `KeyError` | ✅ 读 | 只读列表安全；字段与 `FRIGATE_STATS` 的 11 项顺序绑定 |
| `extras.edit_frigate(readable, index, name=None, cls=None, stats=None, repair=False, reroll=False)` | `index,C/B/A/S,stats,repair,reroll` | `FleetFrigates[index].CustomName/InventoryClass.InventoryClass/Stats[]/DamageTaken/NumberOfTimesDamaged/ResourceSeed` | `None` | `ValueError`、`KeyError`、`IndexError` | 🟡/🔴 | 改名/等级/修复 🟡；任意 `stats` 没有区间校验（只 `int`）🔴；`reroll` 只换 64-bit 种子，不校验模型/属性 |
| 中队/僚机 | **无** | NMSSaveEditor 有 `Squadron`/NPC race/seed/pilot rank 等 | — | — | 🔴 | 需要字段/Schema 逆向；不要凭 NMSSaveEditor 的字段名猜 |

### 2.8 基地

| 能力 | 现有 API | 可行性 | 说明 |
|---|---|---|---|
| 基地库存（Chest/Storage） | `items.list_inventories` + `edit_inventory` 的 `Chest1..10Inventory`、`ChestMagic*` 等 | 🟡 | 可做“基地仓库物品管理”；与基地结构无关 |
| 基地建造部件解锁 | `extras.learn_all(readable, "base")` | 🟡 | 只是 `KnownProducts` 加白名单；不建基地 |
| 基地结构读取/编辑/备份/删除 | **无** | 🔴/⛔ | Shipwright 没有通用 `PersistentPlayerBases` 结构编辑器；Corvette 的 `layouts()` 只筛 `BaseType.PersistentBaseTypes == "PlayerShipBase"`。Gagarin Builder 是专门产品，复刻成本高、版本绑定强 |
| 基地传送点/残骸清理 | **无** | 🔴 | 需要额外字段，不建议 |

### 2.9 发现 / 里程碑 / 解锁 / 奖励

| API（文件:函数） | 参数 | 字段/路径 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|---|
| `extras.knowledge(readable)` | 无 | `KnownWordGroups`、`KnownTech`、`KnownProducts`、`KnownRefinerRecipes` + 游戏表 | `{words,groups}` | `ItemError`、`QuestDataError`、`OSError` | ✅ 读 | 依赖游戏文件 |
| `extras.learn_words(readable, races=None)` | `races` 名称列表/None | `KnownWordGroups[].Group/Races[]` | `int` 新增数 | `KeyError` | 🟡 | 只增不减、幂等；适合“学词语” |
| `extras.learn_all(readable, what)` | `tech/products/base/customisation/refiner/cooking` | `KnownTech`、`KnownProducts`、`KnownRefinerRecipes` | `int` 新增数 | `ValueError`、`ItemError`、`OSError` | 🟡 | 只加白名单；`UNLOCKS` 的 id 来自游戏目录；版本更新会新增/改名 |
| `extras.rewards(readable, group="", query="", limit=400)` | `expedition/twitch/special/shop` | `KnownSpecials`、`RedeemedSeasonRewards`、`RedeemedTwitchRewards` | `{groups,items,shown}` | `ItemError`、`OSError` | ✅ 读 | shop id 来自 `purchaseablespecials.mbin` |
| `extras.set_rewards(readable, group, ids=None, unlock=None, redeemed=None)` | 组、id、unlock/redeemed | 同上 | `{changed}` | `ValueError`、`KeyError` | 🟡 | `unlock=True` 只是加 `KnownSpecials`；`redeemed=False` 可能允许重复领取；账号级奖励不在玩家存档 |
| 发现/里程碑/声誉/符文解锁 | **无** | NMSSaveEditor 有 `Milestones/Reputation/KnownGlyphs` 等 | — | — | 🔴 | 不要用 `extras.set_path` 猜字段；需 schema/实机验证 |

### 2.10 同伴

| API（文件:函数） | 参数 | 字段/路径 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|---|
| `extras.companions(readable)` | 无 | `PlayerStateData.Pets[]` 的 `CreatureID/CustomName/Scale/Predator/Biome/CreatureSeed` | 6 字段列表 | `KeyError` | ✅ 读/可忽略 | starforge 已有更丰富的 `creature.companions`，不必接这个 |
| `extras.edit_companion(readable, index, name=None, scale=None)` | `index,name,scale` | `Pets[index].CustomName`、`Pets[index].Scale` | `None` | `KeyError`、`IndexError`、`ValueError` | 🟡 | 名字 `[:31]`、体型夹到 `0.1..10.0`；只改这两个字段，安全；进游戏需验证 `CustomName` 是否需要 `^` 前缀（读侧会 `lstrip("^")`） |
| 同伴种子/描述符/外观/物种 | **无写 API** | `Pets[].Descriptors/CreatureSeed/SpeciesSeed/GenusSeed/Biome/Predator/...` | — | — | 🔴 | 需要生物生成器/描述符兼容表；星港 `creature.py` 明确只读、3D 未实现 |

### 2.11 任务

| API（文件:函数） | 参数 | 字段/路径 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|---|
| `quests.list_quests(readable)` | 无 | `MissionProgress[].Mission/Seed/Progress`、`MissionVersion`、`CurrentMissionID` | `list[dict]`（`key/id/seed/title/step/progress/final/status/current/known/recurring/critical`） | `QuestDataError`、`KeyError` | 🟡 读 | 需要游戏 `missions` 表 + 英文语言表；游戏更新可能 `QuestDataError` |
| `quests.skip_quests(readable, keys)` | `keys` 来自 `list_quests` | 目标 `MissionProgress[].Progress = final_stage`；清 `CurrentMissionID/CurrentMissionSeed` | `[{key,id,title,from,to}]` | `ValueError`（空/不存在）、`QuestDataError` | 🟡/🔴 | 只改任务进度，算法是游戏自己的 `FinalStageVersions`；但关键任务/剧情物品/后续 flag 可能受影响；`final_stage=None` 会写 `2**31-1` |
| 任务开始/放弃/重置/删除 | **无** | — | — | — | 🔴 | 只有“跳过”，没有“重置/开始” |

### 2.12 多工具

| API（文件:函数） | 参数 | 字段/路径 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|---|
| `extras.multitools(readable)` | 无 | `PlayerStateData.Multitools[]`：`Name/Seed/Resource.Filename/Store.Class.InventoryClass/Store.ValidSlotIndices`；`ActiveMultioolIndex`（游戏字段拼写） | `list[dict]` | `KeyError` | ✅ 读 | 只读列表安全 |
| `extras.edit_multitool(readable, index, name=None, seed=None, cls=None)` | `index,name,seed,C/B/A/S` | `Multitools[index].Name`、`Seed=[True,"0x..."]`、`Layout.Seed`、`Store.Class.InventoryClass` | `None` | `ValueError`、`KeyError`、`IndexError` | 🟡 | 改名/等级安全；换 seed 会同时写 `Seed` 和 `Layout.Seed`，但不换 `Resource.Filename` 模型，需实测外观是否一致 |
| 多工具库存 | `items.list_inventories` + `edit_inventory` 的 `Multitools.N.Store` | `Store.Slots/ValidSlotIndices/Class` | 见库存 | 见库存 | 🟡 | `max_slots` 对 `Multitools` 走 `caps["weapon"]` |
| 新增/删除多工具 | **无** | — | — | — | 🔴 | 不冒这个险 |

### 2.13 Corvette（护卫舰）

| API（文件:函数） | 参数 | 字段/路径 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|---|
| `corvette.layouts(readable)` | 无 | `PlayerStateData.PersistentPlayerBases[]` 中 `BaseType.PersistentBaseTypes == "PlayerShipBase"` | `list[dict]` | 无 | ✅ 读 | 只读 Corvette 列表；不影响普通基地 |
| `corvette.modules(entry)` | `entry` | Corvette `entry.Objects[]` | `list[dict]` | 无 | ✅ 读 | 每个 module 含 `Timestamp/ObjectID/UserData/Position/Up/At` |
| `corvette.place(entry, part_id, position, *, yaw=None, up=(0,1,0), at=(0,0,1), user_data=99, timestamp=None)` | 部件 id、位置、朝向 | 追加 `Objects[]` | `obj` | 无 | 🟡/🔴 | 不做建造规则校验（这是设计目的）；可以重叠/悬空；游戏加载时不复查规则，但仍需实机验证 |
| `corvette.move(obj, position=None, *, yaw=None, up=None, at=None)` | 位置/朝向 | 改 `Position/Up/At` | `obj` | 无 | 🟡/🔴 | 纯内存；无校验 |
| `corvette.replace(entry, wanted)` | `(part_id, position, up, at[, timestamp])[]` | 重写 `Objects`，保留 `HULL=^U_PARAGON` | `list[dict]` | `ValueError`（hull） | 🟡/🔴 | 整体替换容易丢时间戳/模块；必须保留原时间戳 |
| `corvette.remove(entry, obj)` | `obj` | 从 `Objects` 删除；hull 不能删 | `None` | `ValueError` | 🟡/🔴 | 删模块不可逆（除非备份） |
| `corvette.halves(path)` | `path` | `save.hg` ↔ `save2.hg`（按文件名奇偶） | `list[str]` | 无 | ✅ 读 | 只返回存在的文件 |
| `corvette.write_both(path, mutate, *, backup=True)` | `mutate(readable)` | 对两个 half 分别 `open_save → mutate → OpenSave.write` | `list[str]` | 上游 `OSError`、`SaveFormatError`、`ValueError` | 🔴 | **当前实现不能直接接**：第二份失败时第一份已写；`OpenSave.write` 非原子；没有读回/回滚 |

### 2.14 原始 JSON / 导入导出

| API（文件:函数） | 参数 | 字段/路径 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|---|
| `extras.browse(readable, path="")` | 路径 | 任意节点下一层 | `{path,leaf,children,more}` | `KeyError`、`IndexError`、`TypeError` | ✅ 读/低价值 | 适合诊断，不适合普通用户 |
| `extras.get_path(readable, path)` | 点分路径 | 任意节点 | 任意 JSON | `KeyError`、`IndexError`、`TypeError` | ✅ 读 | 路径不能含点号 |
| `extras.set_path(readable, path, value_json)` | 点分路径、JSON 文本 | 任意节点 | `None` | `json.JSONDecodeError`、`ValueError`、`KeyError`、`IndexError`、`TypeError` | 🔴 | 只校验“新旧类型相同/数值互通”；不校验 schema、范围、枚举；可改 `BaseContext` 任何字段 |
| 整档 JSON 导出/导入 | Shipwright webapp `routes/inventory.py:api_save_export/api_save_import`（不是 `nms_save` API） | 整棵 `readable` | JSON | `ValueError`、`json.JSONDecodeError` | 🔴 | 导入只检查 `BaseContext`；绕过所有领域校验；绝不能做普通按钮 |

### 2.15 备份保留/清理

| API（文件:函数） | 参数 | 返回 | 异常 | 可行性 | 说明 |
|---|---|---|---|---|---|
| `save.backup_path_for(path)` | `path` | 新备份路径（微秒时间戳） | `OSError` | ✅ | 生成命名；不写文件 |
| `save.backups_of(path)` | `path` | 本工具命名的备份列表（旧→新） | 无 | ✅ 已接入 | 只认 `<save>.<YYYYmmdd-HHMMSS-micros>.bak` |
| `save.keep_count()` | 无 | `int`；读 `gamepath.setting("keep_backups",20)` | 无 | ✅ 读 | starforge `settings.backup_keep` 未接进来 |
| `save.prune_backups(path, keep=None, protect=())` | 保留数、保护列表 | 删除的文件列表 | `OSError`（单个删除失败被忽略） | 🟡 | `keep=0` 表示永不删；只删自己命名的备份；可在写成功后调用，`protect` 保护当前备份 |
| starforge `writer._backup` | `path` | 备份路径 | `OSError` | ✅ 写前备份 | **没有 prune**；`settings.backup_keep` 目前是“写了没用” |

---

## 3. 可行性总表（按项）

### 3.1 ✅ 可直接接（有现成、字段明确、风险低）

- `player.get_currencies` / `player.set_currencies`（0..2^31-1）
- `ships.set_ship_name`（UI 截 64 字符）
- `ships.list_archived`（只读）
- `ships.get_ship_paint`、`ships.clear_ship_paint`（普通船；sentinel 除外）
- `ships.get_freighter`（只读）
- `extras.frigates`（只读）
- `extras.multitools`（只读）
- `extras.knowledge` / `extras.rewards`（只读）
- `quests.list_quests`（只读；游戏文件齐时）
- `items.list_inventories` / `get_inventory` / `catalogue` / `search_items`（只读）
- `corvette.layouts` / `modules`（只读）
- `save.backups_of` / `save.keep_count` / `save.prune_backups`（清理要加 `protect`）
- `ships.wrong_core_tech`、`ships.get_texture_options`、`player.primary_ship`（诊断/低价值读）

### 3.2 🟡 需封装 + 测试（字段明确，但有边界/语义风险）

- `ships.set_ship_paint`（要先校验 palette、处理 sentinel “种子决定车身色”）
- `items.edit_inventory` 的 `fill` / `recharge` / `repair` / `remove` / `set`（只限已有槽位）
- `items.edit_inventory` 的 `amount`（必须先限制 ≤ 原 `MaxAmount` 或目录 stack）
- `ships.set_freighter`（必须已有货船；home seed 影响颜色）
- `extras.edit_frigate`（先只开放 name/class/repair；stats 要加区间表）
- `extras.edit_multitool`（name/class；seed 需实机确认模型不 mismatch）
- `extras.edit_companion`（name/scale；验证 `^` 前缀）
- `quests.skip_quests`（只对非 critical；明确“不清理任务物品”）
- `extras.learn_words` / `learn_all` / `set_rewards`（只做加白名单/幂等；不做账号级）
- `corvette.place/move/replace/remove` + 多文件事务（读→写两份→逐份读回→任一失败全回滚）
- `ships.set_core_tech`（同型补全原厂科技；会动库存/KnownTech）
- 备份保留策略（调用 `prune_backups`，但必须 `protect` 当前备份）

### 3.3 🔴 需逆向或高风险（不要先做）

- `ships.create_ship` / `remove_ship` / `install_special_ship`
- `ships.set_ship_model`（换型）
- `items.edit_inventory` 的 `expand` / `slots` / `unlock` / `lock`
- `ships.set_sentinel_paint`
- `corvette.write_both` 的原实现
- `extras.set_path` / 整档 JSON 导入
- 基地结构编辑/备份/删除、基地传送点
- 发现/里程碑/声誉/符文解锁
- 中队/僚机
- 冷传送（改玩家位置字段；Shipwright 无 setter）
- `extras.edit_frigate` 的任意 `stats`（在补区间表之前）
- `quests.skip_quests` 对 critical 任务（不是 API 不会，而是产品上不该默认允许）

### 3.4 ⛔ 不建议

- `accountdata.hg` 的账号奖励/解锁：`library` 已明确拒绝；不是玩家存档。
- `ships.set_texture_options`：作者实测“不选择图层”，明确“不要基于它做功能”。
- 把 `nms_save.save.OpenSave.write()` 直接用于生产写接口。
- 让用户直接填无限 `amount` / 无限 `MaxAmount` / 超过游戏 cap 的槽位。
- 未校验的 `install_special_ship` JSON（外部来源）。
- 在 `Game Running`、Steam Cloud 可能覆盖、无备份的情况下写。

---

## 4. 写操作的备份 / 原子写 / 读回 / 回滚要求

### 4.1 starforge 现有 `writer.py` 的四步铁律

`writer.apply_seed` / `apply_class` 的实际顺序：

1. `settings.require_write()`（写开关）。
2. `confirm` 必须为真。
3. `game_running()` 必须为假（Windows Toolhelp / Linux `/proc`）。
4. `os.path.exists` + `nms_save.open_save` 读取。
5. `original = open(save_path,"rb").read()`。
6. `_backup(save_path)`：`shutil.copy2` 到 `<save>.<YYYYmmdd-HHMMSS-micros>.bak`。
7. 领域函数只改 `opened.readable`（内存）。
8. `_encode`：`mapping.obfuscate` + `json.dumps` + `codec.encode`。
9. `_atomic_write`：同目录 `.part` → `flush` → `fsync` → `os.replace`。
10. `nms_save.open_save` 重新读盘，做字段校验。
11. 成功才 `library.clear_cache()`；失败则 `_atomic_write(save_path, original)` 回滚。

### 4.2 每个未接入 API 的保障缺口

| API 类别 | 备份 | 原子写 | 读回 | 回滚 | 备注 |
|---|---|---|---|---|---|
| `ships.*` / `items.*` / `player.*` / `extras.*` / `quests.*` / `corvette.*` 领域函数 | ❌ | ❌ | ❌ | ❌ | 纯内存树编辑；必须由外层事务包住 |
| `save.OpenSave.write` | ✅ 默认 | ❌ | ❌ | ❌ | 直接 `open(path,"wb")`；断电/被杀会半截 |
| `corvette.write_both` | ✅ 每文件 | ❌ | ❌ | ❌ | 第二个 half 失败时第一个已改；无跨文件事务 |
| `writer.apply_seed` | ✅ | ✅ | ✅ 目标 seed | ✅ 原始字节 | ❌ 未校验其它船/其它字段；❌ 无 mtime 乐观锁 |
| `writer.apply_class` | ✅ | ✅ | ✅ class + 全船 seed | ✅ 原始字节 | ✅ 其它船 seed；❌ 库存/名称/涂装未校验 |
| `writer.restore` | ✅ safety copy | ✅ | ⚠️ 只 `open_save` | ❌ | 备份文件损坏/格式不对时不会自动回滚；只有 safety copy |
| `extras.set_path` / 整档导入 | ❌ | ❌ | ❌ | ❌ | 完全绕过 schema；不能直接暴露 |

### 4.3 新写操作必须满足的验收清单

所有新写 API 都应经过**同一个**事务函数（建议在 `save/writer.py` 新增，不要把逻辑散落到服务层）：

1. **闸门**：`settings.require_write()`；`confirm=True`；`game_running()` 为假。
2. **路径**：`library.resolve()` + `classify(path) == "player"`；拒绝 `accountdata.hg`、`mf_*.hg`、目录、非 `.hg`。
3. **快照**：记录 `st_mtime_ns`、`st_size`；写前再比对一次，发现外部变化就拒绝（防止 Shipwright / 游戏 / 云同步同时写）。
4. **备份**：写前整文件备份；备份命名只使用 Shipwright 认可格式；备份失败则不写。
5. **内存变更**：只调用经过白名单校验的领域函数；不要让 UI 传任意 path/字段。
6. **编码**：保留原 `_chunked` / `_trailing_nul`；不要改变存档容器形态。
7. **原子写**：同目录临时文件 + `flush` + `fsync` + `os.replace`。
8. **读回**：重新 `open_save`，校验目标字段；同时校验不变量（其它船/槽位数量/物品总数/任务数量/目标之外的 seed 不应变化）。
9. **回滚**：任何异常（编码、写、读回、校验）都用原始字节原子写回。
10. **备份清理**：写成功后调用 `save.prune_backups(path, protect=[本次备份])`；遵守 `keep=0` 永不删。
11. **日志**：记录 `before/after/backup/bytes/target/fields`，但不记录敏感账号数据。
12. **副本优先**：高风险操作默认 `copy=True` 写 `*.edited.hg`，原档永不动。

### 4.4 多文件（Corvette）额外要求

`corvette.write_both` 不能用现有实现直接接。正确做法：

1. `halves(path)` 取所有存在的 half（manual + auto）。
2. 对每个 half 先读原始字节 + 备份。
3. 对每个 half 在内存中执行同一 `mutate`。
4. 逐个原子写；记录已写列表。
5. 逐个重新解码，校验 `Objects` 数量/关键模块/`BaseType`。
6. 任一失败：把**所有已写 half** 用原始字节原子写回；保留备份；报错。
7. 不要只写一个 half：游戏自己选 manual/auto，单边写看起来像“游戏拒绝了修改”。

### 4.5 还要补的两个外部风险

- **Steam Cloud**：写完可能被云存档覆盖。UI 要提示“关闭 Steam Cloud 或确认上传方向”，写后不要立刻启动游戏。
- **多进程**：`core/lock.py` 只保证 starforge 单实例，不阻止 Shipwright / NMSSaveEditor / 云同步同时写同一文件。需要文件级锁或 mtime/size 乐观锁。

---

## 5. 推荐接入顺序（按用户价值/风险）

### P0 · 先修基础设施（不面向用户）

| 顺序 | 工作 | 落点 | 验收 |
|---|---|---|---|
| P0-1 | 通用事务 `apply_mutation`（备份/原子写/读回/回滚/mtime 检查） | `starforge/save/writer.py` | 用真实存档副本做“故意写错→回滚字节级一致”测试 |
| P0-2 | 文件级并发保护 + Steam Cloud 提示 | `save/writer.py`、`core/lock.py`、Settings | 外部改文件后写被拒；UI 有提示 |
| P0-3 | 备份保留策略接 `settings.backup_keep` + `prune_backups(protect=...)` | `save/writer.py`、`BackupDialog` | 保留 N 份；`0` 永不删；当前备份不被删 |
| P0-4 | 读回不变量模板（其它船/槽位/数量） | `save/writer.py` | 每个新写 API 都有字段级断言 |

### P1 · 高价值、低风险（建议 1–2 周）

| 顺序 | 功能 | 使用的 API | UI 落点 | 风险 |
|---|---|---|---|---|
| P1-1 | 货币编辑（Units/Nanites/Quicksilver） | `player.get/set_currencies` | 新“角色/存档”页；Home 可放入口 | 低（只影响经济；不要超上限） |
| P1-2 | 飞船改名 | `ships.set_ship_name` | Fleet Inspector、ShipLab Inspector | 低 |
| P1-3 | 涂装读取/设置/清除（普通船） | `ships.get/set/clear_ship_paint` | Fleet Inspector、ShipLab 预览联动 | 中（palette/sentinel 语义） |
| P1-4 | 库存只读 + 安全批量操作 | `items.list_inventories/get_inventory/edit_inventory` 的 `fill/recharge/repair/remove/set` | 新“库存”页（或 Fleet 子页） | 中（必须限制 path/数量） |
| P1-5 | 备份保留 UI | `save.keep_count/prune_backups` | Settings / BackupDialog | 低 |

### P2 · 中等价值、中等风险（建议 2–4 周）

| 顺序 | 功能 | 使用的 API | UI 落点 | 风险 |
|---|---|---|---|---|
| P2-1 | 货船只读 + 货船种子/模型 | `ships.get_freighter/set_freighter` | Fleet “货船”标签 | 中（颜色由 home seed 决定） |
| P2-2 | 护卫舰只读 + 改名/等级/修复 | `extras.frigates/edit_frigate`（先不开 stats） | Fleet “护卫舰”标签 | 中 |
| P2-3 | 多工具只读 + 改名/等级 | `extras.multitools/edit_multitool` | Fleet “多工具”标签 | 中（seed 先不开） |
| P2-4 | 归档船只读 | `ships.list_archived` | Fleet “仓库/归档”标签 | 低 |
| P2-5 | 同伴改名/体型 | `extras.edit_companion` | Fleet “同伴”标签（PetsView） | 低–中 |
| P2-6 | 任务只读 + 跳过非关键任务 | `quests.list_quests/skip_quests` | 新“进度/任务”页 | 中–高（critical 默认禁用） |
| P2-7 | 解锁/词语/奖励加白名单 | `extras.learn_words/learn_all/set_rewards` | 新“进度/解锁”页 | 中（只增不减、幂等） |

### P3 · 高风险/长周期（建议 4–8 周，先做只读/实验）

| 顺序 | 功能 | 使用的 API | UI 落点 | 风险 |
|---|---|---|---|---|
| P3-1 | 库存扩容/解锁槽位 | `edit_inventory` 的 `expand/slots/unlock/lock` | 库存页“高级” | 高（可能不加载/槽位错乱） |
| P3-2 | 造新船/删船/特殊船 | `create_ship/remove_ship/install_special_ship` | Fleet/ShipLab “高级” | 高（库存/科技/槽位） |
| P3-3 | 换船型/模型 | `set_ship_model` | ShipLab “高级” | 高（部件树/科技/拦截机标记） |
| P3-4 | 设计部件 → 搜 seed → 写 seed | 搜索 + `set_ship_seed` | ShipLab / Ship Designer | 中–高（不是直接写 parts） |
| P3-5 | Corvette 只读 3D | `corvette.layouts/modules` + `model3d.corvette_model` | 新“Corvette”页 | 中 |
| P3-6 | Corvette 写回 | `place/move/replace/remove` + 新多文件事务 | 新“Corvette”页 | 高（双 half + 结构） |

### P4 · 只研究/不建议排期

- 基地结构读取/编辑/备份/删除（Gagarin Builder 级别）
- 发现/里程碑/声誉/符文解锁
- 定居点
- 中队/僚机
- 冷传送（改玩家位置）
- 账号级奖励/`accountdata.hg`
- 原始 JSON 编辑器（最多做隐藏诊断，不做普通用户功能）

### 5.1 UI 落点建议（汇总）

| 页面 | 放什么 | 不放在这里 |
|---|---|---|
| **Fleet 我的船队** | 飞船列表、主舰标记、改名、涂装、船级/属性、归档船只读、货船只读/种子、护卫舰、多工具、同伴、备份/恢复 | 库存网格、任务/解锁、原始 JSON |
| **ShipLab 飞船实验室** | 搜索、3D、写 seed、设计部件→搜 seed、涂装预览、导出 | 造/删船、Corvette、任务 |
| **新页面“角色/存档”** | 货币、库存（先只读+安全操作）、任务、解锁/奖励、备份保留；高级页签放 raw（默认折叠/隐藏） | 飞船详情（留在 Fleet/ShipLab） |
| **新页面“Corvette”** | Corvette 列表、模块 3D、拖拽/旋转、写回（多文件事务） | 普通基地结构 |
| **Settings** | 写开关、备份保留、存档槽选择、Steam Cloud 提示、游戏版本/映射诊断 | 具体编辑操作 |

---

## 6. “好做但危险” vs “安全但价值低”

### 6.1 好做但危险（不要因为“API 已有”就做）

| 项 | 为什么好做 | 危险 | 最低护栏 |
|---|---|---|---|
| 库存 `expand/slots/unlock/lock` | 一个函数、一个 op | 超过游戏 cap、旧存档不认、槽位错乱/UI 卡死 | 只允许向 `max_slots` 扩、不缩、不锁；默认副本；实机验证；失败回滚 |
| `amount` 任意数量 | 一行改 `Amount` | 会把 `MaxAmount` 抬高，造出游戏不可能堆叠 | 只允许 ≤ 原 `MaxAmount` 或目录 stack；不自动抬 `MaxAmount` |
| `create_ship` / `remove_ship` | 上游已有完整函数 | 克隆库存/科技、清空槽位、丢船 | 只允许空槽/明确确认；默认副本；读回库存+科技+槽位数量；失败回滚 |
| `set_ship_model` 换型 | 只改 `Filename/Seed` | 部件树/库存/科技/拦截机标记不匹配；跨型不可移植 | 只允许同大类；先只读预览；副本；实机验证；否则不做 |
| `install_special_ship` | 直接写 entry | 外部 JSON 字段漂移、版本不兼容 | 只允许内置、签名的 special JSON；版本校验；副本；回滚 |
| Corvette `write_both` | Shipwright 已有函数 | 非原子、双文件、第二份失败第一份已改 | 不用原函数；写多文件事务；两份都读回；全量回滚 |
| `extras.set_path` / 整档导入 | 任意字段都能改 | 破坏 schema/任务/基地；无法读回语义 | 不做普通功能；只在诊断模式、只读或白名单字段 |
| `quests.skip_quests` critical | 一个调用 | 剧情/任务物品/后续 flag 卡死 | critical 默认禁用；只跳过非 critical；副本；明确“不清理任务物品” |
| `set_rewards(redeemed=False)` | 允许重新领取 | 重复 entitlement/账号状态异常 | 只做 `unlock=True` 加白名单；不开放 `redeemed=False` |
| `set_sentinel_paint` / `set_texture_options` | 看起来能“任意黑/任意图层” | 实验结构、实测无效、游戏忽略 | 不发布；最多隐藏实验开关 |
| 基地结构编辑/删除 | 其他工具有 | 结构复杂、版本绑定、丢基地 | 不做；至少不在 P1/P2 |

### 6.2 安全但价值低（可以延后，别占用主线）

| 项 | 为什么安全 | 为什么价值低 |
|---|---|---|
| `ships.list_archived` 只读 | 只读，空列表兜底 | 只是展示仓库船；不能写 |
| `ships.get_texture_options` | 只读 | `set_texture_options` 已证明不可用 |
| `ships.wrong_core_tech` | 只读诊断 | 只对“科技不匹配”少数船有用 |
| `player.primary_ship` | 只读 | 一个标记 |
| `ships.get_freighter` 只读 | 只读 | 不写就没法修货船 |
| `extras.companions`（6 字段） | 只读 | starforge 已有更丰富的 `creature.companions` |
| `extras.browse/get_path` | 只读 | 普通用户不需要；开发者才用 |
| `mapping.unmapped_keys` / `save.read_branch` | 只读/诊断 | 适合 preflight/诊断，不是用户功能 |
| `items.search_items` | 只读 | 需要和库存编辑一起才有价值 |
| 备份列表（已接） | 只读 | 恢复才有价值；保留策略更实用 |

### 6.3 一句话执行建议

**先把“写事务”做成唯一入口，再按“货币 → 改名/涂装 → 库存安全操作 → 货船/护卫舰/多工具/同伴只读+小改 → 任务/解锁 → 造删船/Corvette”推进；基地、发现、定居点、中队、账号奖励、原始 JSON 在没有专门逆向和实机验证前不要排期。**

---

## 7. 附：关键证据索引

| 主题 | 证据 |
|---|---|
| 存档打开/写入 | `NMS-Shipwright/nms_save/save.py:open_save/OpenSave.write/backups_of/prune_backups`；`starforge/save/writer.py:_atomic_write/_backup/apply_seed/apply_class/restore` |
| 编解码/映射 | `NMS-Shipwright/nms_save/codec.py:decode/encode`；`mapping.py:deobfuscate/obfuscate/key_for/unmapped_keys` |
| 船只 | `NMS-Shipwright/nms_save/ships.py:list_ships/list_archived/set_ship_seed/set_ship_name/set_ship_paint/get_ship_paint/clear_ship_paint/set_ship_model/create_ship/remove_ship/install_special_ship/set_core_tech/ship_stats/set_ship_stats/get_freighter/set_freighter` |
| 库存 | `NMS-Shipwright/nms_save/items.py:list_inventories/get_inventory/edit_inventory/max_slots/inventory_caps/stat_ranges/catalogue/search_items` |
| 货币 | `NMS-Shipwright/nms_save/player.py:get_currencies/set_currencies/primary_ship` |
| 解锁/护卫舰/多工具/同伴/奖励/raw | `NMS-Shipwright/nms_save/extras.py:knowledge/learn_words/learn_all/frigates/edit_frigate/multitools/edit_multitool/companions/edit_companion/rewards/set_rewards/browse/get_path/set_path` |
| 任务 | `NMS-Shipwright/nms_save/quests.py:list_quests/skip_quests/final_stage/missions` |
| Corvette | `NMS-Shipwright/nms_save/corvette.py:layouts/modules/place/move/replace/remove/halves/write_both` |
| starforge 读路径 | `starforge/save/library.py:classify/probe/scan_dir/open_ships/default_save_path/resolve` |
| starforge 写路径 | `starforge/save/writer.py:apply_seed/apply_class/restore/backups` |
| starforge 服务/路由 | `starforge/services/__init__.py:apply_seed/apply_class/backups/restore`；`starforge/web/routes.py:/api/saves/apply,/api/saves/class,/api/saves/backups,/api/saves/restore` |
| 原生 UI | `starforge/app/pages/fleet.py`、`ship_lab.py`、`ship_designer.py`；`app/dialogs/write_back.py`、`class_editor.py`、`backup.py` |
| 写回测试 | `starforge/tests/test_writer.py`（备份、原子写、读回、回滚、跨型拒绝、副本） |

### 7.1 参考的社区事实

- NMSSaveEditor 功能面：货币、船/货船/多工具/护卫舰/同伴/定居点/中队、库存、基地/货船结构备份恢复、奖励/账号、raw JSON；并明确警告“超过原版库存上限游戏可能坏档”。来源：`https://github.com/goatfungus/NMSSaveEditor`、`https://nmssaveeditor.com/features/`。
- Gagarin-Titov：游戏内行星/飞船搜索、传送、任意建造、开发者选项；新版 Gagarin Builder 做基地/Corvette 结构读写，写入前有备份/验证。来源：本地 `Gagarin_Titov/README.md`、`https://www.nexusmods.com/nomanssky/mods/4810`。
- Super Ship Hunter：内存读写 + Mod 模板槽，属于游戏内/内存路线，不是存档 API。来源：本地 `NMS-Super-Ship-Hunter/README.md`。
- 社区经验：改存档前备份、一次只改一类、不要在游戏运行时改、注意 Steam Cloud 覆盖；任务/基地/结构类字段跨版本最易坏。来源：NMSSaveEditor 文档/指南、Steam 社区讨论。

---

## 8. 维护提示

- 本文件是“接入前盘点”，不是承诺清单；任何 🔴/⛔ 项在没有实机验证前不得在 UI 标 ✅。
- 每次游戏大版本更新后，优先检查：`mapping.json`、`codec`、`items.catalogue`、`quests.missions`、`ships.stat_ranges`、`corvette` 的 `BaseType`/`ObjectID` 字段。
- 新写 API 的 PR 必须附：目标字段读回、不变量读回、失败回滚测试、真实存档副本测试、游戏内可见性验证（至少一项）。
