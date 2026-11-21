"""同伴页纯逻辑：表头、空态、行整理；不依赖真实游戏或存档。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from starforge.app.widgets.pets_view import (  # noqa: E402
    PET_TABLE_HEADERS,
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
