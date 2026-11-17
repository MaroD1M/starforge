"""全部界面文案集中在这里（决策：界面仅中文，但文案单点化，将来加语言只改这一处）。"""

APP_NAME = "starforge"
APP_TITLE = "无人深空 · 飞船猎人"

# --- 预览降级态（对应决策单 §3） ---
PREVIEW_L0 = "L0 部件缩略图（未检测到游戏文件，非 3D）"
PREVIEW_L1 = "L1 真 3D（已从游戏 pak 读取几何）"
PREVIEW_L2 = "L2 游戏内实物（通过模板槽送进游戏查看）"
PREVIEW_L1_DEGRADED = "L1 部分降级：{reason}"

# --- 错误提示 ---
ERR_NO_SAVE = "没有找到存档。请在设置里选择存档目录。"
ERR_NO_GAMEDATA = "找不到 Gagarin 的 GAMEDATA（catalog.txt / icons.bin），缩略图不可用。"
ERR_WRITE_OFF = "写入功能当前关闭，请先到设置页开启。"
ERR_SAVE_FORMAT = "这个文件不是玩家存档，或游戏版本已变更导致解析失败。"
ERR_GAME_RUNNING = "游戏正在运行，请先退出游戏再写入存档。"

# --- 页面 ---
NAV_SEARCH = "搜飞船"
NAV_MYSHIPS = "我的船"
NAV_PREVIEW = "预览"
NAV_SETTINGS = "设置"

BTN_SEARCH = "开始搜索"
BTN_CANCEL = "取消"
BTN_EXPORT_GLB = "导出 glb"
BTN_APPLY_SAVE = "写回存档"
BTN_PUSH_GAME = "送进游戏"

CONFIRM_WRITE = "确认要写入吗？会先自动备份存档。"
CONFIRM_PUSH = "确认要写入游戏内模板吗？只改模板种子，不动你的船。"
