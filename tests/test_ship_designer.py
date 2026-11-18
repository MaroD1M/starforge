"""飞船设计器的纯逻辑：每组单选、空选、搜索字段整理。不依赖真实游戏。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from starforge.app.pages.ship_designer import (  # noqa: E402
    normalize_result,
    preview_params,
    result_summary,
    selected_parts,
    selection_rows,
    single_choice,
)

EXAMPLE_SEED = "0x992C8A47F60A6B10"

GROUPS = [
    {"group": "_PIT_", "label": "座舱", "options": [
        {"part": "_PIT_A", "label": "座舱 A"},
        {"part": "_PIT_B", "label": "座舱 B"},
    ]},
    {"group": "_WINGS_", "label": "机翼", "options": [
        {"part": "_WING_A", "label": "机翼 A"},
        {"part": "_WING_B", "label": "机翼 B"},
    ]},
]


def test_single_choice_keeps_one_part_per_group():
    selection = single_choice({}, "_PIT_", "_PIT_A")
    selection = single_choice(selection, "_PIT_", "_PIT_B")
    assert selection == {"_PIT_": "_PIT_B"}

    selection = single_choice(selection, "_WINGS_", "_WING_A")
    assert selection == {"_PIT_": "_PIT_B", "_WINGS_": "_WING_A"}

    selection = single_choice(selection, "_PIT_", None)
    assert selection == {"_WINGS_": "_WING_A"}


def test_selected_parts_follow_tree_order_and_ignore_unknown():
    selection = {"_WINGS_": "_WING_B", "_PIT_": "_PIT_A", "_BAD_": "_X"}
    assert selected_parts(selection, GROUPS) == ["_PIT_A", "_WING_B"]
    assert selected_parts({}, GROUPS) == []
    assert selected_parts({"_PIT_": "_NOPE"}, GROUPS) == []


def test_selection_rows_expose_chinese_group_and_part_labels():
    rows = selection_rows({"_PIT_": "_PIT_B"}, GROUPS)
    assert rows == [{"group": "_PIT_", "group_label": "座舱",
                     "part": "_PIT_B", "part_label": "座舱 B"}]
    assert selection_rows({}, GROUPS) == []


def test_preview_params_use_selected_parts():
    got = preview_params("fighter", "  0xABC  ",
                         GROUPS, {"_PIT_": "_PIT_A", "_WINGS_": "_WING_A"})
    assert got == {"ship": "fighter", "seed": "0xABC",
                   "parts": ["_PIT_A", "_WING_A"]}
    assert preview_params("fighter", EXAMPLE_SEED, GROUPS, {})["parts"] == []


def test_result_fields_are_stable_and_empty_safe():
    row = {"type": "fighter", "type_label": "战斗机",
           "seed": " 0x8BA812880CFAAA1C ", "parts": ["_PIT_A", "", None]}
    got = normalize_result(row)
    assert got == {"type": "fighter", "type_label": "战斗机",
                   "seed": "0x8BA812880CFAAA1C", "parts": ["_PIT_A"]}
    assert result_summary(row) == "战斗机  0x8BA812880CFAAA1C"
    assert normalize_result(None) == {"type": "", "type_label": "", "seed": "",
                                      "parts": []}
