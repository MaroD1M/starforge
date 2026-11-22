"""飞船设计器的纯逻辑：每组单选、空选、搜索字段整理。不依赖真实游戏。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


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
    write_block_reason,
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


def test_write_block_reason_explains_before_user_clicks(qapp):
    assert write_block_reason([], [EXAMPLE_SEED]) == "先选择部件"
    assert "种子" in write_block_reason(["_PIT_A"], ["bad"])
    assert write_block_reason(["_PIT_A"], [EXAMPLE_SEED]) == ""
    # 输入框暂时是示例种子，但结果列表里已有有效种子：与真实写入逻辑一致。
    assert write_block_reason(["_PIT_A"], ["bad", "0x1"]) == ""


def _designer_with_groups(qapp):
    from starforge.app.pages.ship_designer import ShipDesignerPage

    page = ShipDesignerPage()
    page._groups = list(GROUPS)
    page._populate_tree()
    page._update_summary()
    return page


def test_designer_primary_is_write_and_reason_sits_next_to_it(qapp):
    page = _designer_with_groups(qapp)
    try:
        assert page.write_design_btn.text() == "写入存档"
        assert not page.write_design_btn.isEnabled()
        assert page.write_reason.text() == "先选择部件"
        assert not page.write_reason.isHidden()

        page._selection = {"_PIT_": "_PIT_A"}
        page.seed_edit.setText("bad")
        page._update_summary()
        assert not page.write_design_btn.isEnabled()
        assert "种子" in page.write_reason.text()

        page.seed_edit.setText(EXAMPLE_SEED)
        page._update_summary()
        assert page.write_design_btn.isEnabled()
        assert page.write_reason.isHidden()
    finally:
        page.close()


def test_designer_parts_tree_has_search_and_selected_available_groups(qapp):
    from PySide6.QtCore import Qt

    page = _designer_with_groups(qapp)
    try:
        assert page.part_filter.placeholderText()
        roots = [page.tree.topLevelItem(i).text(0)
                 for i in range(page.tree.topLevelItemCount())]
        assert roots[0].startswith("已选（")
        assert roots[1].startswith("可选（")

        available = page.tree.topLevelItem(1)
        leaf = available.child(0).child(0)
        leaf.setCheckState(0, Qt.Checked)
        assert page._selection == {"_PIT_": "_PIT_A"}
        assert page.tree.topLevelItem(0).text(0) == "已选（1）"
        assert page.tree.topLevelItem(1).text(0) == "可选（3）"

        page.part_filter.setText("翼")
        hidden = []
        for i in range(page.tree.topLevelItemCount()):
            top = page.tree.topLevelItem(i)
            for j in range(top.childCount()):
                node = top.child(j)
                leaves = ([node.child(k) for k in range(node.childCount())]
                          if node.childCount() else [node])
                hidden.extend(item.isHidden() for item in leaves)
        assert any(hidden)
    finally:
        page.close()


def test_designer_summary_collapsible_and_files_menu_is_secondary(qapp):
    from PySide6.QtGui import QAction

    page = _designer_with_groups(qapp)
    try:
        assert page.summary.isHidden()
        page.summary_toggle.setChecked(True)
        assert not page.summary.isHidden()
        assert "▾" in page.summary_toggle.text()
        page.summary_toggle.setChecked(False)
        assert page.summary.isHidden()

        # 保存 / 载入不再各占一个常驻按钮，而是同一个次级菜单里的两个动作。
        assert isinstance(page.save_design_btn, QAction)
        assert isinstance(page.load_design_btn, QAction)
        assert [action.text() for action in page.files_menu.actions()] == [
            "保存设计…", "载入设计…"]
        assert page.files_btn.menu() is page.files_menu
    finally:
        page.close()
