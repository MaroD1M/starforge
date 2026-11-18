"""最近活动：追加、上限、持久化、损坏文件容错与清空。"""
from __future__ import annotations

import json

from starforge.services import history


def test_append_newest_first_and_failed_flag():
    history.clear()
    first = history.record("search", "搜索完成", "fighter · 找到 2 个结果", ref="search")
    second = history.record("write", "写回存档失败", "槽位 1 · 模拟错误",
                            ref="mine", ok=False)

    assert first["ok"] is True and first["failed"] is False
    assert second["ok"] is False and second["failed"] is True
    assert second["result"] == "failed"
    assert first["ts"]
    items = history.list()
    assert [x["title"] for x in items] == ["写回存档失败", "搜索完成"]
    assert items[0]["ref"] == "mine"
    for item in items:
        assert {"kind", "title", "detail", "ts", "ok", "failed"} <= set(item)

    history.record("scan", "扫描完成")
    assert "ref" not in history.list()[0]


def test_limit_keeps_latest_200():
    history.clear()
    for i in range(history.MAX_ITEMS + 25):
        history.record("scan", f"#{i}")
    items = history.list()
    assert len(items) == history.MAX_ITEMS
    assert items[0]["title"] == f"#{history.MAX_ITEMS + 24}"
    assert items[-1]["title"] == "#25"
    assert len(history.recent(8)) == 8
    assert history.recent(8)[0]["title"] == f"#{history.MAX_ITEMS + 24}"


def test_persistence_and_atomic_write(tmp_path):
    path = tmp_path / "nested" / "history.json"
    store = history.HistoryStore(path)
    store.record("agent", "连接游戏成功", "hello", ref="live")
    assert path.exists()
    raw = json.loads(path.read_text("utf-8"))
    assert raw["format"] == history.FORMAT
    assert raw["items"][0]["title"] == "连接游戏成功"
    assert not list(path.parent.glob("*.tmp"))

    again = history.HistoryStore(path)
    assert [x["title"] for x in again.list()] == ["连接游戏成功"]
    assert again.recent(1)[0]["ref"] == "live"


def test_default_path_follows_starforge_home(isolated_home):
    assert history.history_file() == isolated_home / "history.json"


def test_corrupt_file_is_tolerated(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{not json", "utf-8")
    assert history.list(path=path) == []

    path.write_text(json.dumps({"items": [{"kind": "search", "title": "好条目"},
                                          "坏条目", {"foo": 1}]}), "utf-8")
    items = history.list(path=path)
    assert [x["title"] for x in items] == ["好条目"]

    history.record("search", "恢复后可写", path=path)
    assert history.recent(1, path=path)[0]["title"] == "恢复后可写"


def test_record_failure_does_not_raise(tmp_path):
    # 把“文件”指向目录：读/写都会失败，但历史异常不能影响主流程。
    item = history.record("search", "不会中断主流程", path=tmp_path)
    assert item["title"] == "不会中断主流程"
    assert history.list(path=tmp_path) == []


def test_clear_empties_file(tmp_path):
    path = tmp_path / "history.json"
    history.record("search", "搜索完成", path=path)
    history.clear(path=path)
    assert history.list(path=path) == []
    raw = json.loads(path.read_text("utf-8"))
    assert raw["items"] == []
