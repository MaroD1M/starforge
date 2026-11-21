"""模板 Mod 的「可领取」部分：表情菜单 + 玩家实体触发器的结构与一致性。

重点不是"能生成 XML"，而是三份文件描述的是**同一组 8 个模板 id**：
  REWARDTABLE（奖励） ↔ EMOTEMENU（入口） ↔ PLAYERCHARACTER（动画 + 触发器）。
任何一处漏写/写错 id，玩家在游戏里都点不出奖励。
"""
import os
import xml.etree.ElementTree as ET

from starforge.live import exml


def _props(el: ET.Element, name: str) -> list[ET.Element]:
    """取直接子节点里指定 name 的 Property（EXML 用属性表达字段名）。"""
    return [p for p in el.findall("Property") if p.get("name") == name]


def _first(el: ET.Element, name: str) -> ET.Element:
    found = _props(el, name)
    assert found, f"缺少字段 {name}"
    return found[0]


def _reward_ids(root: ET.Element) -> list[str]:
    return [p.get("_id") for p in root.iter("Property")
            if p.get("value") == "GcGenericRewardTableEntry"]


def _emote_ids(root: ET.Element) -> list[str]:
    return [p.get("_id") for p in root.iter("Property")
            if p.get("value") == "GcPlayerEmote"]


def _anim_ids(root: ET.Element) -> list[str]:
    out = []
    for anims in root.iter("Property"):
        if anims.get("name") == "Anims" and anims.get("value") == "TkAnimationData":
            out.append(_first(anims, "Anim").get("value"))
    return out


def _trigger_pairs(root: ET.Element) -> list[tuple[str, str]]:
    """(GcAnimFrameEvent.Anim, GcRewardAction.Reward) 配对。"""
    pairs = []
    for trig in root.iter("Property"):
        if trig.get("value") != "GcActionTrigger":
            continue
        event = _first(trig, "Event")
        frame = _first(event, "GcAnimFrameEvent")
        action = _first(trig, "Action")
        inner = _first(action, "Action")
        reward = _first(inner, "GcRewardAction")
        pairs.append((_first(frame, "Anim").get("value"),
                      _first(reward, "Reward").get("value")))
    return pairs


# ---------------------------------------------------------------- 三份 XML 基础


def test_three_documents_are_well_formed():
    for text in (exml.rewardtable_xml(), exml.emotemenu_xml(),
                 exml.playercharacter_xml()):
        root = ET.fromstring(text)
        assert root.tag == "Data" and root.get("template")


def test_template_ids_are_consistent_and_eight():
    expected = set(exml.template_ids())
    assert len(exml.template_ids()) == len(expected) == 8

    reward = _reward_ids(ET.fromstring(exml.rewardtable_xml()))
    emote = _emote_ids(ET.fromstring(exml.emotemenu_xml()))
    player_root = ET.fromstring(exml.playercharacter_xml())
    anims = _anim_ids(player_root)
    pairs = _trigger_pairs(player_root)

    assert len(reward) == len(emote) == len(anims) == len(pairs) == 8
    assert set(reward) == set(emote) == set(anims) == expected
    assert {a for a, _r in pairs} == expected
    assert {r for _a, r in pairs} == expected


# ---------------------------------------------------------------- 表情菜单字段


def test_emote_entries_follow_ssh_sample():
    root = ET.fromstring(exml.emotemenu_xml())
    emotes = [p for p in root.iter("Property") if p.get("value") == "GcPlayerEmote"]
    assert len(emotes) == 8
    for e in emotes:
        tid = e.get("_id")
        assert tid in exml.template_ids()
        assert _first(e, "EmoteID").get("value") == tid
        assert _first(e, "AnimationName").get("value") == tid
        assert _first(e, "RidingAnimationName").get("value") == tid
        assert _first(e, "CloseMenuOnSelect").get("value") == "false"
        assert _first(e, "MoveToCancel").get("value") == "true"
        assert _first(e, "NeverShowInMenu").get("value") == "false"
        # 标题用自己的 Loc key（由 LocTable.mxml 提供），不再复用占位 key
        assert _first(e, "Title").get("value") == exml.emote_title_key(tid.split("_", 1)[1].lower())
        icon = _first(_first(e, "Icon"), "Filename").get("value")
        assert icon.startswith("TEXTURES/UI/FRONTEND/ICONS/STARFORGE/TEMPLATE.")
        assert icon.endswith(".DDS")


def test_emote_icons_are_all_distinct():
    """8 个表情必须各有不同图标（曾经探索舰/穿梭机撞成同一张）。"""
    root = ET.fromstring(exml.emotemenu_xml())
    icons = [_first(_first(e, "Icon"), "Filename").get("value")
             for e in root.iter("Property") if e.get("value") == "GcPlayerEmote"]
    assert len(icons) == 8
    assert len(set(icons)) == 8, f"图标重复：{icons}"


def test_icon_assets_are_valid_bc1_dds():
    """随包图标必须是 128×128 的 DX10/BC1 DDS（坏文件会让表情显示空白）。"""
    import struct

    for type_, *_ in exml.TEMPLATES:
        path = exml.icon_asset(type_)
        assert os.path.isfile(path), path
        data = open(path, "rb").read()
        assert data[:4] == b"DDS "
        h = struct.unpack_from("<I", data, 12)[0]
        w = struct.unpack_from("<I", data, 16)[0]
        assert (w, h) == (128, 128), (type_, w, h)
        assert data[84:88] == b"DX10"
        dxgi = struct.unpack_from("<I", data, 128)[0]
        assert dxgi == 71, (type_, dxgi)          # BC1_UNORM
        assert len(data) == 148 + (w // 4) * (h // 4) * 8


# ---------------------------------------------------------------- 玩家实体触发器


def test_playercharacter_boot_state_and_index_kept():
    root = ET.fromstring(exml.playercharacter_xml())
    states = [p for p in root.iter("Property")
              if p.get("value") == "GcActionTriggerState"]
    assert len(states) == 1 and states[0].get("_id") == "BOOT"
    assert _first(states[0], "StateID").get("value") == "BOOT"

    for pair in _trigger_pairs(root):
        assert pair[0] == pair[1]                       # 动画名与奖励 id 同名

    # `_index="1"` 是 SSH 样本里的写法，必须原样保留
    rewards = [p for p in root.iter("Property") if p.get("value") == "GcRewardAction"]
    assert len(rewards) == 8
    assert all(p.get("_index") == "1" for p in rewards)

    frame_events = [p for p in root.iter("Property")
                    if p.get("value") == "GcAnimFrameEvent"]
    for ev in frame_events:
        inner = _first(ev, "GcAnimFrameEvent")
        assert _first(inner, "FrameStart").get("value") == "0"
        assert _first(inner, "StartFromEnd").get("value") == "false"


# ---------------------------------------------------------------- 奖励数据不许改坏


def test_rewardtable_matches_manifest_exactly():
    root = ET.fromstring(exml.rewardtable_xml())
    entries = {p.get("_id"): p for p in root.iter("Property")
               if p.get("value") == "GcGenericRewardTableEntry"}
    assert set(entries) == {m["id"] for m in exml.manifest()}

    for m in exml.manifest():
        entry = entries[m["id"]]
        assert _first(entry, "Id").get("value") == m["id"]
        # 列表项必须是 value="GcRewardTableItem"（缺类型声明会让游戏按错误结构解析）
        item = next(p for p in entry.iter("Property")
                    if p.get("name") == "List" and p.get("value") == "GcRewardTableItem")
        assert item.get("_index") == "0"
        ship = _first(item, "Reward")
        ship = _first(ship, "GcRewardSpecificShip")
        resource = _first(ship, "ShipResource")
        assert _first(resource, "Filename").get("value") == m["model"]
        assert int(_first(resource, "Seed").get("value")) == m["factory_seed"]
        layout = _first(ship, "ShipLayout")
        assert int(_first(layout, "Slots").get("value")) == m["slots"]
        # 船型必须在 ShipType.ShipClass 里（直接平铺的 ShipClass 是旧错误写法）
        ship_type = _first(ship, "ShipType")
        assert _first(ship_type, "ShipClass").get("value") == m["class"]
        # 这几项缺一个，游戏就会把奖励当成"购买货船"
        assert _first(ship, "IsRewardShip").get("value") == "true"
        assert _first(ship, "IsGift").get("value") == "true"
        assert _first(ship, "CostAmount").get("value") == "0"
        size = _first(_first(ship, "OverrideSizeType"), "SizeType").get("value")
        assert size == exml.SHIP_SIZE_TYPE[m["type"]]


# ---------------------------------------------------------------- 落盘


def test_write_mod_writes_three_exml_and_readme(tmp_path):
    out = exml.write_mod(str(tmp_path))
    assert len(out["files"]) == 13 and len(out["entries"]) == 8

    expected = {
        os.path.join("METADATA", "REALITY", "TABLES", "REWARDTABLE.EXML"),
        os.path.join("METADATA", "UI", "EMOTEMENU.EXML"),
        os.path.join("MODELS", "COMMON", "PLAYER", "PLAYERCHARACTER",
                     "PLAYERCHARACTER", "ENTITIES", "PLAYERCHARACTER.ENTITY.EXML"),
        "LocTable.mxml",
        "README.txt",
    }
    expected |= {
        os.path.join("TEXTURES", "UI", "FRONTEND", "ICONS", "STARFORGE",
                     exml.SHIP_ICON[t]) for t, *_ in exml.TEMPLATES
    }
    rels = {os.path.relpath(p, out["path"]) for p in out["files"]}
    assert rels == expected
    assert all(os.path.isfile(p) for p in out["files"])
    for rel in expected - {"README.txt"}:
        if rel.lower().endswith(".dds"):
            continue                              # 图标是二进制
        ET.parse(os.path.join(out["path"], rel))

    readme = open(os.path.join(out["path"], "README.txt"), encoding="utf-8").read()
    assert "表情" in readme and "种子" in readme
