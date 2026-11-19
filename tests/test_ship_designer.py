"""飞船设计器的纯逻辑：每组单选、空选、搜索字段整理。不依赖真实游戏。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from starforge.app.pages.ship_designer import (  # noqa: E402
    design_document,
    design_payload,
    normalize_design_seed,
    normalize_result,
    preview_params,
    read_design_file,
    result_summary,
    selected_parts,
    selection_from_parts,
    selection_rows,
    single_choice,
    write_design_file,
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


def test_design_payload_normalizes_parts_and_seeds():
    doc = design_payload("  我的设计  ", "fighter",
                         {"_PIT_": "_PIT_A", "_WINGS_": "_WING_B"}, GROUPS,
                         ["0xabc", "0xABC", "bad"])
    assert doc["name"] == "我的设计"
    assert doc["ship"] == "fighter"
    assert doc["want"] == ["_PIT_A", "_WING_B"]
    assert doc["found_seeds"] == ["0x0000000000000ABC"]
    assert doc["made_with"] == "NMS Starforge"

    with pytest.raises(ValueError):
        design_payload("空设计", "fighter", {}, GROUPS)


def test_design_document_validates_ship_and_known_parts():
    doc = design_document({"name": "导入", "ship": "fighter",
                           "want": ["_pit_a", "_WING_B", None],
                           "found_seeds": ["0x1", "nope"]}, GROUPS)
    assert doc["want"] == ["_PIT_A", "_WING_B"]
    assert doc["found_seeds"] == ["0x0000000000000001"]

    with pytest.raises(ValueError):
        design_document({"ship": "banana", "want": ["_PIT_A"]}, GROUPS)
    with pytest.raises(ValueError):
        design_document({"ship": "fighter", "want": []}, GROUPS)
    with pytest.raises(ValueError):
        design_document({"ship": "fighter", "want": ["_NOPE"]}, GROUPS)


def test_selection_from_parts_follows_group_order_and_ignores_unknown():
    assert selection_from_parts(["_WING_B", "_PIT_A", "_NOPE"], GROUPS) == {
        "_PIT_": "_PIT_A", "_WINGS_": "_WING_B"}
    assert selection_from_parts([], GROUPS) == {}


def test_design_file_roundtrip(tmp_path):
    doc = design_payload("夜莺", "fighter", {"_PIT_": "_PIT_B"}, GROUPS,
                         ["0x1234"])
    path = tmp_path / "nightingale.nmsdesign.json"
    write_design_file(path, doc)
    loaded = read_design_file(path, GROUPS)
    assert loaded["name"] == "夜莺"
    assert loaded["want"] == ["_PIT_B"]
    assert loaded["found_seeds"] == ["0x0000000000001234"]
    assert normalize_design_seed("0xZZ") == ""
