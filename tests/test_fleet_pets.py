"""同伴页纯逻辑：表头、空态、行整理；不依赖真实游戏或存档。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from starforge.app.widgets.pets_view import (  # noqa: E402
    FAUNA_PREVIEW_LIMIT,
    PET_TABLE_HEADERS,
    fauna_preview_rows,
    fauna_state_text,
    format_trust_traits,
    pet_rows,
    pet_seed,
    pet_table_headers,
    pets_empty_text,
    pets_preview_note,
)


def test_table_headers_are_chinese_and_complete():
    headers = pet_table_headers()
    assert headers == ["名称", "生物类型", "群系", "CreatureID", "来源", "种子",
                       "信任/特征数量"]
    assert tuple(headers) == PET_TABLE_HEADERS
    headers.append("临时")
    assert pet_table_headers() == list(PET_TABLE_HEADERS)


def test_empty_state_without_save_or_companions():
    assert "存档" in pets_empty_text(None, "")
    assert pets_empty_text(None, "/tmp/save.hg") == "暂无同伴数据。"
    assert "没有同伴" in pets_empty_text({"creatures": [], "note": ""}, "/tmp/save.hg")
    assert pets_empty_text({"creatures": [], "note": "Pets 为空"}, "/tmp/save.hg") == "Pets 为空"
    assert pets_empty_text({"creatures": [{"name": "小蓝"}]}, "/tmp/save.hg") == ""


def test_pet_rows_normalize_missing_values():
    creatures = [
        {
            "name": "小蓝",
            "type_zh": "飞行",
            "biome_zh": "茂盛",
            "creature": "BIRD",
            "seeds": {"creature": "0x12", "species": "0x34"},
            "trust": 2,
            "traits": 3,
        },
        {"name": "", "type": "Prey", "biome": "Lush", "creature": "DEER",
         "seeds": {"species": "0xAB"}, "trust": None},
        {"name": "坏数据", "seeds": None, "traits": "不是数字"},
        "不是字典",
    ]
    rows = pet_rows(creatures)
    assert len(rows) == 3
    assert all(len(row) == len(PET_TABLE_HEADERS) for row in rows)
    assert rows[0] == ["小蓝", "飞行", "茂盛", "BIRD", "未知", "0x12", "2 / 3"]
    assert rows[1] == ["(未命名)", "Prey", "Lush", "DEER", "未知", "0xAB", "— / 0"]
    assert rows[2] == ["坏数据", "未知", "未知", "未知", "未知", "—", "— / 0"]


def test_seed_and_trust_helpers():
    assert pet_seed({"seeds": {"creature": "", "genus": "0xGEN"}}) == "0xGEN"
    assert pet_seed({}) == "—"
    assert format_trust_traits(0, 0) == "0 / 0"
    assert format_trust_traits("", None) == "— / 0"


def test_preview_note_never_claims_generated_3d():
    note = pets_preview_note({"preview": ""})
    assert "生成器" in note
    assert "不伪造" in note
    assert pets_preview_note({"preview": "需要生物生成器"}) == "需要生物生成器"


def _fauna(count: int) -> list[dict]:
    return [{"name": f"动物{i}", "creature_seed": f"0x{i:X}",
             "discoverer": "旅行者" if i == 1 else ""}
            for i in range(1, count + 1)]


def test_fauna_preview_only_first_n_rows():
    rows = fauna_preview_rows(_fauna(9))
    assert len(rows) == FAUNA_PREVIEW_LIMIT
    assert rows[0] == "1. 动物1 · 种子 0x1 · 发现者 旅行者"
    assert rows[1] == "2. 动物2 · 种子 0x2"
    assert fauna_preview_rows(_fauna(2), limit=1) == [
        "1. 动物1 · 种子 0x1 · 发现者 旅行者"]
    assert fauna_preview_rows(None) == []
    assert fauna_preview_rows([None, "坏数据", {}]) == ["1. (未命名) · 种子 —"]


def test_fauna_state_three_states_are_readable():
    kind, text = fauna_state_text({"ok": True, "count": 5, "fauna": _fauna(5)})
    assert kind == "ok"
    assert "前 3/5 条" in text
    assert "动物1" in text and "动物4" not in text

    kind, text = fauna_state_text(
        {"ok": True, "count": 0, "fauna": [], "reason": "没有找到该行星的动物发现记录"})
    assert kind == "empty"
    assert "暂无动物记录" in text
    assert "没有找到" in text

    kind, text = fauna_state_text(
        {"ok": False, "count": 0, "fauna": [], "reason": "读取存档失败：坏文件"})
    assert kind == "error"
    assert "联查失败" in text and "坏文件" in text

    assert fauna_state_text(None)[0] == "error"
