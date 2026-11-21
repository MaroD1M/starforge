"""表情标题的本地化表：8 个表情各自独立 key，且与 EMOTEMENU / 触发器一一对应。"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from starforge.live import exml


def _ids(root: ET.Element, key: str = "Id") -> list[str]:
    out = []
    for node in root.iter("Property"):
        if node.get("name") == key and node.get("value"):
            out.append(node.get("value"))
    return out


def test_loctable_parses_and_has_one_entry_per_template():
    root = ET.fromstring(exml.loctable_mxml())
    assert root.get("template") == "TkLocalisationTable"
    ids = _ids(root)
    assert len(ids) == len(exml.TEMPLATES) == 8
    assert len(set(ids)) == 8                       # 不再共用占位 key
    assert set(ids) == {exml.emote_title_key(t) for t, _m, _l, _c in exml.TEMPLATES}


def test_emote_title_matches_loctable_key():
    """EMOTEMENU 里每条表情的 Title 必须能在 LocTable 里找到。"""
    menu = ET.fromstring(exml.emotemenu_xml())
    loc = set(_ids(ET.fromstring(exml.loctable_mxml())))
    titles = _ids(menu, "Title")
    assert len(titles) == 8
    assert set(titles) == loc
    for type_, *_ in exml.TEMPLATES:
        assert exml.emote_title_key(type_) in loc


def test_loctable_has_chinese_and_english():
    root = ET.fromstring(exml.loctable_mxml())
    entries = [n for n in root.iter("Property") if n.get("value") == "TkLocalisationEntry"]
    assert len(entries) == 8
    first = entries[0]
    langs = {n.get("name"): n.get("value") for n in first if n.get("name") != "Id"}
    for lang in ("English", "SimplifiedChinese", "TraditionalChinese", "USEnglish"):
        assert langs.get(lang), f"{lang} 缺失"
    assert "Starforge" in langs["English"]
    assert "拦截机" in langs["SimplifiedChinese"]


def test_write_mod_includes_loctable(tmp_path):
    out = exml.write_mod(str(tmp_path))
    rels = {os.path.relpath(p, out["path"]) for p in out["files"]}
    assert "LocTable.mxml" in rels
    assert len(out["files"]) == 13                   # 4 份 XML + 8 张图标 + README
