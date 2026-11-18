"""多选对比的纯逻辑测试：不依赖真实游戏/存档。"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from starforge.app.dialogs import compare as compare_mod


def ship(seed: str, typ: str = "fighter", **kw) -> dict:
    return {"type": typ, "seed": seed, **kw}


def test_normalize_keeps_order_and_dedupes():
    rows = [
        ship("0xAAA", "fighter"),
        ship("0xBBB", "hauler"),
        ship("0xaaa", "FIGHTER"),
    ]
    out = compare_mod.normalize_compare(rows)
    assert [row["seed"] for row in out] == ["0xAAA", "0xBBB"]


def test_normalize_caps_at_three():
    rows = [ship(f"0x{i:X}") for i in range(1, 6)]
    out = compare_mod.normalize_compare(rows)
    assert len(out) == compare_mod.MAX_COMPARE == 3
    assert [row["seed"] for row in out] == ["0x1", "0x2", "0x3"]


def test_merge_adds_new_and_ignores_duplicate_and_overflow():
    current = [ship("0x1"), ship("0x2")]
    merged = compare_mod.merge_compare(
        current, [ship("0x1"), ship("0x3"), ship("0x4")])
    assert [row["seed"] for row in merged] == ["0x1", "0x2", "0x3"]

    full = compare_mod.add_to_compare(merged, ship("0x9"))
    assert [row["seed"] for row in full] == ["0x1", "0x2", "0x3"]


def test_normalize_ignores_invalid_rows():
    out = compare_mod.normalize_compare([
        None,
        {},
        {"type": "", "seed": ""},
        ship("0x1"),
    ])
    assert [row["seed"] for row in out] == ["0x1"]


def test_compare_fields_organizes_display_data():
    row = ship(
        "0xabc",
        "fighter",
        type_label="战斗机",
        name="黎明",
        ship_class="s",
        stats={"shield": 20, "damage": 12.5, "agility": "3"},
        parts=[" pit ", "wing", ""],
        source="save",
    )
    fields = compare_mod.compare_fields(row)
    assert fields["type_label"] == "战斗机"
    assert fields["seed"] == "0xabc"
    assert fields["ship_class"] == "S"
    assert fields["parts"] == ["PIT", "WING"]
    assert fields["parts_text"] == "PIT WING"
    assert [s["key"] for s in fields["stats"]] == ["damage", "shield", "agility"]
    assert fields["stats_text"] == "伤害 12.5 · 护盾 20 · 机动 3"
    assert fields["source"] == "save"


def test_compare_fields_handles_missing_values():
    fields = compare_mod.compare_fields({})
    assert fields["type_label"] == "未知"
    assert fields["seed"] == ""
    assert fields["ship_class"] == "—"
    assert fields["stats_text"] == "—"
    assert fields["parts_text"] == "—"


def test_compare_dialog_is_importable():
    assert compare_mod.CompareDialog.__name__ == "CompareDialog"
