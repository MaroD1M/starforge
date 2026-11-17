"""中文化：部件 / 插槽组 / 生物群系 / 哨兵 / 种族 / 船池类别的中文名。

设计原则：
  · 游戏内部的部件名是模型节点名（`_PIT_A`），官方没有中文，所以用**词组映射**：
    `_PIT_` → 座舱、`_WINGS_` → 机翼、`_SUBWINGS_` → 副翼 …，再拼上编号（A/1/OTOP…）。
  · 保留原名作为提示（UI 里用 title），避免玩家和攻略对不上。
  · 映射表可持续扩充；查不到就原样返回，绝不报错。
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- 插槽组（198 个组名的词根）

GROUP_TOKENS: dict[str, str] = {
    "PIT": "座舱", "COCKPIT": "驾驶舱", "COCKPITB": "B 型驾驶舱", "COCKPITBNOSE": "B 型驾驶舱鼻",
    "ANOSE": "A 型机鼻", "NOSE": "机鼻", "NOSEA": "A 型机鼻", "NOSEB": "B 型机鼻",
    "WINGS": "机翼", "WINGSO": "外翼", "WINGSU": "内翼", "WINGSA": "机翼 A", "WINGSB": "机翼 B",
    "WINGSH": "机翼 H", "WINGSI": "机翼 I", "WINGSK": "机翼 K", "WINGSM": "机翼 M",
    "WINGSP": "机翼 P", "WINGSS": "机翼 S", "WINGST": "机翼 T", "WINGSV": "机翼 V",
    "WINGSA_": "机翼 A", "SUBWING": "副翼", "SUBWING1": "副翼 1", "SUBWING2": "副翼 2",
    "SUBWINGS": "副翼组", "EXTRAWINGS": "附加翼", "AXWINGS": "轴向翼", "AXWINGSS": "轴向翼组",
    "TOPFLAP": "上襟翼", "FLAP": "襟翼", "FIN": "尾鳍", "TIPS": "翼尖",
    "ENGINE": "引擎", "ENGINES": "引擎组", "JET": "推进器", "JETBOT": "下推进器",
    "JETBOTS": "下推进器组", "TOPJET": "上推进器", "TOPJETS": "上推进器组",
    "THRUSTER": "推进器", "BOOSTER": "助推器", "BOOSTERS": "助推器组",
    "SKIRT": "裙板", "SKIRTS": "裙板组", "AALTSKIRT": "A 型备用裙板", "ALTSKIRTING": "备用裙板",
    "BELLY": "腹部", "BODY": "机身", "HULL": "船体", "SAILS": "太阳帆", "SAIL": "帆",
    "MAST": "桅杆", "ROOTJNT": "根关节", "ROOTDATA": "根数据",
    "LIGHTS": "灯光", "LIGHT": "灯", "TIPLIGHTS": "翼尖灯", "TIPLIGHTS4": "四号翼尖灯",
    "DECAL": "贴花", "DECALS": "贴花组", "CORNERDECAL": "角贴花", "CORNERDECALA": "角贴花 A",
    "LOGO": "标志", "LOGOL": "左标志", "LOGOR": "右标志", "LOGOLEFT": "左标志", "LOGORIGHT": "右标志",
    "LOGO1": "标志 1", "LOGO2": "标志 2", "LETTER": "字母", "LETTERLEFT": "左字母",
    "LETTERRIGHT": "右字母", "NUMBER": "编号", "NUMBER1": "编号 1", "NUMBER2": "编号 2",
    "NUMBER3": "编号 3", "NUMBER4": "编号 4", "RECTANGLE": "矩形色块", "RECTANGLELEFT": "左侧矩形",
    "RECTANGLERIGHT": "右侧矩形", "SMALLSIGN": "小标识", "SIGN": "标识",
    "ACC": "配件", "ACCESSORY": "配件", "ACCESSORIES": "配件组", "ASIDES": "侧板",
    "AFRONT": "前部", "AENDWINGS": "端翼", "POD": "吊舱", "PODS": "吊舱组",
    "GEAR": "起落架", "GUN": "武器", "GUNS": "武器组", "LASER": "激光",
    "TYPE": "外观样式", "VAR": "变体", "VARIANT": "变体", "ALTERNATE": "替换",
    "A_": "A 型", "B_": "B 型", "C_": "C 型", "_B_": "B 型",
    "TOP": "顶部", "BOTTOM": "底部", "UNDER": "底部", "OVER": "顶部", "SIDE": "侧面",
    "LEFT": "左", "RIGHT": "右", "FRONT": "前", "BACK": "后", "REAR": "后", "TAIL": "尾部",
    "CENTER": "中央", "MID": "中部", "MAIN": "主", "SMALL": "小", "BIG": "大", "LARGE": "大",
    "BLACK": "黑", "WHITE": "白", "RED": "红", "BLUE": "蓝", "GREEN": "绿", "GOLD": "金",
    "NULL": "无", "NON": "无", "BLANK": "空", "EMPTY": "空", "NONE": "无",
    "OTOP": "顶部", "OBOT": "底部", "OFLIP": "翻转", "FLIP": "翻转",
    "DECOR": "装饰", "DETAIL": "细节", "EXTRA": "附加", "MOD": "改装",
}

# 部件名里常见的后缀/编号（保留字母数字，仅翻译词）
PART_TOKENS: dict[str, str] = {
    **GROUP_TOKENS,
    "LOD0": "", "LOD1": "", "LOD2": "",
}

BIOME_ZH = {
    "Lush": "茂盛", "Frozen": "冰封", "Toxic": "剧毒", "Scorched": "焦土",
    "Radioactive": "辐射", "Barren": "荒芜", "Dead": "死寂", "Exotic": "奇异",
    "Mega Exotic": "巨型奇异", "Weird": "异象", "Swamp": "沼泽", "Volcanic": "火山",
    "Desert": "沙漠", "Ocean": "海洋", "Gas": "气态", "Ice": "冰原",
    "Infested": "虫蚀", "Crimson": "深红", "Blue": "蔚蓝", "Red": "赤红",
    "Green": "翠绿", "Yellow": "橙黄", "Moon": "卫星",
}

SENTINEL_ZH = {
    "none": "无", "low": "低", "high": "高", "aggressive": "敌对",
    "corrupted": "腐化", "?" : "未知",
}

RACE_ZH = {"Gek": "吉克", "Korvax": "科瓦克斯", "Vy'keen": "维金", "None": "无",
           "Abandoned": "废弃", "Traveller": "旅行者", "Atlas": "阿特拉斯"}

SHIP_KIND_ZH = {
    "space station": "空间站", "freighter fleet": "货船队", "frigate": "护卫舰",
    "sentinels": "哨兵", "pirates": "海盗", "swarm": "虫群", "special": "特殊",
    "station": "空间站", "capital freighter": "主力货船", "small freighter": "小型货船",
    "tiny freighter": "微型货船", "combat frigate": "战斗护卫舰", "science frigate": "科研护卫舰",
    "industrial frigate": "工业护卫舰", "diplomatic frigate": "外交护卫舰",
    "support frigate": "支援护卫舰", "living frigate": "生物护卫舰", "ghost frigate": "幽灵护卫舰",
    "swarm hive": "虫巢", "swarm frigate": "虫群护卫舰", "swarm drone": "虫群无人机",
    "corvette": "护卫舰", "police": "警察",
}


def _tokens(name: str) -> list[str]:
    """把 `_WINGSO_OTOP12` 拆成 ['WINGSO','OTOP','12'] 之类的词块。"""
    s = name.strip("_").upper()
    return [t for t in re.split(r"_+", s) if t]


def _translate_token(tok: str) -> str:
    """翻译一个词块；**认不出就原样保留**（A / C1 / F7 / 1Q 这类编号不能丢）。"""
    if not tok:
        return ""
    if tok.isdigit():
        return tok
    if tok in PART_TOKENS:
        return PART_TOKENS[tok]
    # 词 + 编号 + 尾字母：OTOP12 / BLACK1Q / C1
    m = re.fullmatch(r"([A-Z]+)(\d+)([A-Z]?)", tok)
    if m:
        word, num, tail = m.groups()
        base = PART_TOKENS.get(word)
        if base is not None:
            return f"{base}{num}{tail}"
        for cut in range(len(word) - 1, 1, -1):
            if word[:cut] in PART_TOKENS:
                return PART_TOKENS[word[:cut]] + word[cut:] + num + tail
        return tok
    # 由已知词 + 未知尾巴组成：WINGSOOTOPS → 外翼 + OTOPS
    for cut in range(len(tok) - 1, 1, -1):
        if tok[:cut] in PART_TOKENS:
            return PART_TOKENS[tok[:cut]] + tok[cut:]
    return tok


def group_label(name: str) -> str:
    """`_SUBWINGS_` → 「副翼组」；认不出就原样返回。"""
    parts = [_translate_token(t) for t in _tokens(name)]
    out = " ".join(p for p in parts if p).strip()
    return out or name.strip("_")


def part_label(part: str) -> str:
    """`_PIT_A` → 「座舱 A」；认不出就原样返回。"""
    parts = [_translate_token(t) for t in _tokens(part)]
    out = " ".join(p for p in parts if p).strip()
    return out or part.strip("_")


def zh(mapping: dict[str, str], value: str | None, fallback: str = "") -> str:
    if not value:
        return fallback
    return mapping.get(value, value)


def biome_label(name: str | None) -> str:
    return zh(BIOME_ZH, name, "未知")


def sentinel_label(name: str | None) -> str:
    return zh(SENTINEL_ZH, name, "未知")


def race_label(name: str | None) -> str:
    return zh(RACE_ZH, name, "未知")


def kind_label(name: str | None) -> str:
    return zh(SHIP_KIND_ZH, name, name or "")
