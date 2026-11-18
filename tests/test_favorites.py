"""收藏夹与分享码：本地持久化、原子写、往返与非法输入。"""
from __future__ import annotations

import base64
import json

import pytest

from starforge.services import favorites

REF = {"type": "fighter", "seed": "0x8ba812880cfaaa1c",
       "parts": ["_PIT_A", "_WING_B"], "name": "测试战斗机"}


def test_add_list_toggle_remove():
    favorites.clear()
    item = favorites.add(REF)
    assert item["type"] == "fighter"
    assert item["seed"] == "0x8BA812880CFAAA1C"
    assert item["parts"] == ["_PIT_A", "_WING_B"]
    assert item["name"] == "测试战斗机"
    assert len(favorites.list()) == 1
    assert favorites.is_fav(REF) is True

    # 同一 type+seed 重复添加不产生重复条目
    favorites.add(REF)
    assert len(favorites.list()) == 1

    assert favorites.toggle(REF) is False
    assert favorites.is_fav(REF) is False
    assert favorites.toggle(REF) is True
    assert favorites.is_fav(REF) is True

    assert favorites.remove(REF) is True
    assert favorites.remove(REF) is False
    assert favorites.list() == []


def test_persistence_to_disk(tmp_path):
    path = tmp_path / "nested" / "favorites.json"
    store = favorites.FavoritesStore(path)
    store.add(REF)

    assert path.exists()
    raw = json.loads(path.read_text("utf-8"))
    assert raw["format"] == favorites.FORMAT
    assert raw["items"][0]["seed"] == "0x8BA812880CFAAA1C"

    again = favorites.FavoritesStore(path)
    assert [x["seed"] for x in again.list()] == ["0x8BA812880CFAAA1C"]
    assert not list(path.parent.glob("*.tmp"))


def test_default_path_follows_starforge_home(isolated_home):
    assert favorites.favorites_file() == isolated_home / "favorites.json"


def test_share_code_roundtrip():
    code = favorites.encode_share(REF)
    assert code.startswith("nsh1:")
    ref = favorites.decode_share(code)
    assert ref.type == "fighter"
    assert ref.seed == "0x8BA812880CFAAA1C"
    assert ref.parts == ["_PIT_A", "_WING_B"]
    assert ref.name == "测试战斗机"
    assert ref.source == "share"
    # 兼容字典式读取
    assert ref["type"] == "fighter" and ref.get("seed") == ref.seed


def test_share_code_without_name():
    code = favorites.encode_share({"type": "sentinel", "seed": "0x1", "parts": []})
    ref = favorites.decode_share(code)
    assert ref.type == "sentinel" and ref.name == ""
    assert favorites.encode_share(ref) == code


def test_share_code_rejects_invalid_input():
    bad_json = "nsh1:" + base64.urlsafe_b64encode(
        json.dumps({"type": "dragon", "seed": "0x1"}).encode()).decode().rstrip("=")
    bad_seed = "nsh1:" + base64.urlsafe_b64encode(
        json.dumps({"type": "fighter", "seed": "nope"}).encode()).decode().rstrip("=")
    for code in ("", "nsh1:", "nsh1:!!!!", "nsh2:abc", bad_json, bad_seed,
                 "nsh1:" + base64.urlsafe_b64encode(b"not-json").decode().rstrip("=")):
        with pytest.raises(favorites.ShareCodeError):
            favorites.decode_share(code)


def test_export_import_and_duplicate_import():
    favorites.clear()
    favorites.add(REF)
    payload = favorites.export()
    assert json.loads(payload)["items"][0]["name"] == "测试战斗机"

    favorites.clear()
    first = favorites.import_(payload)
    assert first["added"] == 1 and first["skipped"] == 0
    assert favorites.is_fav(REF) is True

    second = favorites.import_(payload)
    assert second["added"] == 0 and second["skipped"] == 1
    assert len(favorites.list()) == 1


def test_import_accepts_share_codes_and_dedupes_within_batch():
    favorites.clear()
    code = favorites.encode_share(REF)
    res = favorites.import_("\n".join([code, code]))
    assert res["added"] == 1 and res["skipped"] == 1
    assert favorites.is_fav(REF) is True


def test_empty_export_import_and_clear(tmp_path):
    favorites.clear()
    assert favorites.list() == []

    payload = favorites.export()
    data = json.loads(payload)
    assert data["format"] == favorites.FORMAT
    assert data["items"] == []

    first = favorites.import_(payload)
    assert first == {"added": 0, "skipped": 0, "items": []}
    assert favorites.list() == []

    store = favorites.FavoritesStore(tmp_path / "favs.json")
    store.add(REF)
    dest = tmp_path / "exports" / "favorites.json"
    target = store.export_to(dest)
    assert target == dest
    assert json.loads(dest.read_text("utf-8"))["items"][0]["seed"] == "0x8BA812880CFAAA1C"
    assert not list(dest.parent.glob("*.tmp"))

    store.clear()
    assert store.list() == []
    assert json.loads((tmp_path / "favs.json").read_text("utf-8"))["items"] == []


def test_import_rejects_empty_and_malformed_payloads():
    for payload in ("   ", "{not json", 123):
        with pytest.raises(favorites.FavoritesError):
            favorites.import_(payload)
    assert favorites.import_("[]") == {"added": 0, "skipped": 0, "items": []}
