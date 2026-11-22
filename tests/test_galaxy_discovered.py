"""星图「已发现」页签：索引加载/查询/筛选/传送/CSV 全部打桩。

这些用例只验证界面编排：首次/刷新时先建索引，筛选变化只查索引；
``max_distance`` 由服务层 ``discovered_filter`` 再筛一次。传送复用现有
「传送到此星球」确认流程，入口是顶部唯一的主按钮。
"""
from __future__ import annotations

import csv
import io
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from starforge.app.pages import galaxy as page_mod

SYSTEM_UA = 0x100 << 40
SYSTEM_UA_TEXT = f"0x{SYSTEM_UA:X}"
SYSTEM_COORDS = "07FF:007F:07FF:0100"
PLANET_3_UA = SYSTEM_UA | (3 << 52)
PLANET_3_TEXT = f"0x{PLANET_3_UA:X}"
GLYPHS_P3 = "310000000000"
GLYPHS_P4 = "410000000000"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class FakeServices:
    """只实现页面用到的服务；绝不创建 AgentClient / 真实存档读取。"""

    def __init__(self, discovered: dict | None = None,
                 query_result: dict | None = None,
                 query_error: Exception | None = None,
                 index_result: dict | None = None,
                 filter_result: dict | None = None,
                 filter_error: Exception | None = None,
                 fallback_result: dict | None = None):
        self.discovered = discovered if discovered is not None else _payload([])
        self.query_result = query_result
        self.query_error = query_error
        self.index_result = index_result
        self.filter_result = filter_result
        self.filter_error = filter_error
        self.fallback_result = fallback_result
        self.index_calls = 0
        self.query_calls: list[dict] = []
        self.filter_calls: list[dict] = []
        self.warp_calls: list[dict] = []

    def discoveries_index(self, path: str | None = None) -> dict:
        return self.discoveries_index_all()

    def discoveries_index_all(self) -> dict:
        self.index_calls += 1
        if self.index_result is not None:
            return dict(self.index_result)
        rows = self.discovered.get("planets") or []
        return {"ok": True, "count": len(rows), "rebuilt": True, "cached": False,
                "saves": [{"save_id": "synthetic-save", "name": "save.hg",
                           "count": len(rows), "rebuilt": True, "cached": False}],
                "errors": [], "path": "/synthetic/save.hg"}

    def discoveries_query(self, **kw) -> dict:
        self.query_calls.append(dict(kw))
        if self.query_error is not None:
            raise self.query_error
        if self.query_result is not None:
            return dict(self.query_result)
        rows = list(self.discovered.get("planets") or [])
        if kw.get("biome"):
            rows = [row for row in rows if row.get("biome") == kw["biome"]]
        if kw.get("infested") is not None:
            rows = [row for row in rows if bool(row.get("infested")) == bool(kw["infested"])]
        if kw.get("named") is not None:
            rows = [row for row in rows if bool(row.get("named")) == bool(kw["named"])]
        return {"ok": True, "count": len(rows), "planets": rows}

    def discovered_planets(self, path: str | None = None) -> dict:
        if self.fallback_result is not None:
            return dict(self.fallback_result)
        return dict(self.discovered)

    def discovered_filter(self, planets: list[dict] | None = None, **kw) -> dict:
        self.filter_calls.append({"planets": planets, "kwargs": dict(kw)})
        if self.filter_error is not None:
            raise self.filter_error
        if self.filter_result is not None:
            return dict(self.filter_result)
        rows = list(planets or [])
        if kw.get("max_distance") is not None:
            limit = float(kw["max_distance"])
            rows = [row for row in rows
                    if row.get("distance_ly") is not None
                    and float(row["distance_ly"]) <= limit]
        return {"ok": True, "count": len(rows), "planets": rows}

    def warp_portal(self, glyphs: str, galaxy: int | None = None,
                    stage: str = "prepare_warp") -> dict:
        self.warp_calls.append({"glyphs": glyphs, "galaxy": galaxy, "stage": stage})
        return {"ok": True, "confirmed": True}

    def glyph_strip_png(self, glyphs: str) -> bytes:
        return b""


def _sync_worker(fn, on_done=None, on_error=None, *args, **kwargs):
    try:
        res = fn(*args, **kwargs)
    except Exception as e:                                  # noqa: BLE001 - 与真实 worker 一致
        if on_error is not None:
            on_error(f"{type(e).__name__}: {e}")
        return
    if on_done is not None:
        on_done(res)


def _capture_notify(monkeypatch) -> dict[str, list[str]]:
    captured: dict[str, list[str]] = {"success": [], "error": [], "warn": [], "toast": []}
    for name in list(captured):
        def record(text, _name=name, **_kwargs):
            captured[_name].append(str(text))

        monkeypatch.setattr(page_mod.notify, name, record)
    return captured


def _accept_confirm(monkeypatch) -> list[dict]:
    from PySide6.QtWidgets import QMessageBox

    seen: list[dict] = []

    def warn(parent, title, text, *args, **kwargs):
        seen.append({"title": title, "text": text})
        return QMessageBox.Yes

    monkeypatch.setattr(page_mod.QMessageBox, "warning", staticmethod(warn))
    return seen


def _row(*, index: int | None = 3, name: str | None = None,
         biome: str | None = "Lush", infested: bool | None = False,
         discoverer: str | None = None,
         discovered_at: int | None = 1_700_000_000,
         source: str | None = None, pending: bool = False,
         glyphs: str | None = GLYPHS_P3, distance_ly=None,
         system_ua: str | None = SYSTEM_UA_TEXT) -> dict:
    ua = None
    if index is not None and system_ua is not None:
        ua = f"0x{SYSTEM_UA | (index << 52):X}"
    row = {
        "ua": ua,
        "planet_ua": ua,
        "system_ua": system_ua,
        "system_key": f"0:{system_ua}" if system_ua else None,
        "planet_index": index,
        "galaxy": 0,
        "biome": biome,
        "biome_index": 0 if biome else None,
        "infested": infested,
        "named": bool(name),
        "name": name,
        "discoverer": discoverer,
        "discovered_at": discovered_at,
        "system_name": "Synthetic System" if system_ua else None,
        "glyphs": glyphs,
        "coords": SYSTEM_COORDS if system_ua else None,
        "source": source,
        "pending": pending,
    }
    if distance_ly is not None:
        row["distance_ly"] = distance_ly
    return row


def _payload(rows: list[dict], **overrides) -> dict:
    out = {
        "ok": True,
        "path": "/synthetic/save.hg",
        "count": len(rows),
        "records": len(rows),
        "duplicates": 0,
        "planets": rows,
        "warnings": [],
        "version": 4746,
        "stats": {},
    }
    out.update(overrides)
    return out


def _make_page(monkeypatch, svc: FakeServices):
    monkeypatch.setattr(page_mod, "get_services", lambda: svc)
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    page = page_mod.GalaxyPage()
    page.view_stack.setCurrentWidget(page.discovered_page)
    return page


def _load(page, monkeypatch, svc: FakeServices, captured=None) -> dict[str, list[str]]:
    captured = captured if captured is not None else _capture_notify(monkeypatch)
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    page._load_discovered()
    return captured


def _select_row(page, index: int) -> None:
    for row in range(page.disc_table.rowCount()):
        item = page.disc_table.item(row, 0)
        data = item.data(page_mod.Qt.UserRole) if item else None
        if isinstance(data, dict) and data.get("planet_index") == index:
            page.disc_table.selectRow(row)
            return
    raise AssertionError(f"没有找到行星序号 {index} 的行")


def _combo_index(combo, value) -> int:
    found = combo.findData(value)
    assert found >= 0, f"{value!r} 不在下拉框里"
    return found


# ---------------------------------------------------------------- 页签与加载


def test_discovered_is_a_separate_view_not_a_tab(qapp, monkeypatch):
    page = _make_page(monkeypatch, FakeServices())
    labels = [page.tabs.tabText(i) for i in range(page.tabs.count())]
    assert "已发现" not in labels
    assert "地址工作台" not in labels
    assert page.view_stack.indexOf(page.discovered_page) >= 0
    page.show_section("已发现")
    assert page.view_stack.currentWidget() is page.discovered_page
    page.show_section("行星")
    assert page.view_stack.currentWidget() is page.tabs
    assert page.tabs.tabText(page.tabs.currentIndex()) == "行星"


def test_primary_is_teleport_on_discovered_tab(qapp, monkeypatch):
    page = _make_page(monkeypatch, FakeServices())
    assert page.primary_btn.text() == "传送到此星球"
    assert page.warp_btn.isHidden() is True


def test_load_builds_index_then_queries_it(qapp, monkeypatch):
    rows = [
        _row(index=3, name="Synthetic Planet", infested=True),
        _row(index=1, biome="Frozen", glyphs="110000000000", distance_ly=1234.0),
    ]
    svc = FakeServices(_payload(rows))
    page = _make_page(monkeypatch, svc)
    captured = _load(page, monkeypatch, svc)

    assert svc.index_calls == 1
    assert svc.query_calls
    assert page.disc_table.rowCount() == 2
    assert page.export_action.isEnabled() is True
    assert page.disc_empty.isHidden() is True
    assert "已发现：2 颗" in page.disc_stats.text()
    assert "显示 2 颗" in page.disc_stats.text()
    assert captured["error"] == []

    _select_row(page, 3)
    detail = page.detail.text()
    assert "Synthetic Planet" in detail
    assert "发现者：—" in detail
    assert "来源：索引" in detail
    assert "符文：310000000000" in detail
    assert SYSTEM_COORDS in detail


def test_query_covers_all_saves_and_can_be_narrowed(qapp, monkeypatch):
    rows = [_row(index=3)]
    svc = FakeServices(_payload(rows))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc)

    # 默认汇总全部存档：查询不带 save_id / save_ids。
    assert "save_id" not in svc.query_calls[-1]
    assert "save_ids" not in svc.query_calls[-1]
    assert page.disc_save.count() >= 2          # 全部存档 + save.hg
    svc.query_calls.clear()
    page.disc_save.setCurrentIndex(1)
    assert svc.query_calls[-1]["save_ids"] == ["synthetic-save"]


def test_empty_payload_shows_readable_empty_state(qapp, monkeypatch):
    svc = FakeServices(_payload([]))
    page = _make_page(monkeypatch, svc)
    captured = _load(page, monkeypatch, svc)

    assert page.disc_table.rowCount() == 0
    assert page.disc_empty.isHidden() is False
    assert "没有已发现的星球" in page.disc_empty.title_label.text()
    assert "Planet" in page.disc_empty.description_label.text()
    assert page.export_action.isEnabled() is False
    assert "0 颗" in page.disc_stats.text()
    assert captured["error"] == []


def test_failed_read_shows_explanation_without_error_popup(qapp, monkeypatch):
    svc = FakeServices(
        _payload([]),
        index_result={"ok": False, "error": "索引数据库不可写"},
        fallback_result={
            "ok": False,
            "count": 0,
            "planets": [],
            "warnings": ["读取存档失败：FileNotFoundError: 没有找到存档"],
        },
    )
    page = _make_page(monkeypatch, svc)
    captured = _load(page, monkeypatch, svc)

    assert page.disc_empty.isHidden() is False
    assert "没有可用的已发现数据" in page.disc_empty.title_label.text()
    assert "FileNotFoundError" in page.disc_empty.description_label.text()
    assert "设置页" in page.disc_empty.description_label.text()
    assert page.disc_stats.text() == "已发现：不可用"
    assert captured["error"] == []


def test_index_failure_falls_back_to_direct_read(qapp, monkeypatch):
    rows = [_row(index=3)]
    svc = FakeServices(
        _payload(rows),
        index_result={"ok": False, "error": "索引数据库不可写"},
    )
    page = _make_page(monkeypatch, svc)
    captured = _load(page, monkeypatch, svc)

    assert page.disc_table.rowCount() == 1
    assert svc.filter_calls, "回退读取必须由服务层筛选"
    assert "直接读取" in page.disc_stats.text()
    assert "索引不可用" in page.disc_stats.toolTip()
    assert captured["error"] == []

    before = len(svc.filter_calls)
    page.disc_biome.setCurrentIndex(_combo_index(page.disc_biome, "Lush"))
    assert len(svc.filter_calls) == before + 1
    assert page.disc_stats.text().startswith("已发现：")


def test_worker_exception_shows_failure_explanation(qapp, monkeypatch):
    class Boom(FakeServices):
        def discoveries_index_all(self) -> dict:
            raise RuntimeError("synthetic read boom")

    svc = Boom()
    page = _make_page(monkeypatch, svc)
    captured = _load(page, monkeypatch, svc)

    assert page.disc_empty.isHidden() is False
    assert "synthetic read boom" in page.disc_empty.description_label.text()
    assert captured["error"] == []
    assert captured["warn"]


# ---------------------------------------------------------------- 筛选


def test_filter_is_delegated_with_expected_parameters(qapp, monkeypatch):
    rows = [_row(index=3), _row(index=1)]
    svc = FakeServices(_payload(rows))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc)

    page._current_info = {"ua": SYSTEM_UA_TEXT, "coords": SYSTEM_COORDS}
    page.disc_center_btn.click()                 # 以当前星系为中心
    page.disc_biome.setCurrentIndex(_combo_index(page.disc_biome, "Lush"))
    page.disc_infested.setCurrentIndex(_combo_index(page.disc_infested, True))
    page.disc_named.setCurrentIndex(_combo_index(page.disc_named, False))
    page.disc_distance.setValue(500)

    assert page._discovered_origin_ua == SYSTEM_UA_TEXT
    assert page.disc_distance.isEnabled() is True
    assert page.disc_origin_hint.text() == f"距离中心：{SYSTEM_COORDS}"

    assert svc.query_calls[-1] == {
        "biome": "Lush",
        "infested": True,
        "named": False,
        "near_ua": SYSTEM_UA_TEXT,
        "order": "distance",
        "limit": None,
    }
    assert svc.filter_calls[-1]["kwargs"] == {
        "near_ua": SYSTEM_UA_TEXT,
        "max_distance": 500.0,
        "limit": 500,
    }


def test_filter_result_drives_table_and_empty_state(qapp, monkeypatch):
    rows = [_row(index=3), _row(index=1)]
    svc = FakeServices(_payload(rows))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc)

    svc.query_result = {"ok": True, "count": 1, "planets": [rows[0]]}
    page.disc_biome.setCurrentIndex(_combo_index(page.disc_biome, "Lush"))

    assert svc.query_calls, "筛选变化必须查询索引服务"
    assert page.disc_table.rowCount() == 1
    assert "显示 1 颗" in page.disc_stats.text()

    svc.query_result = {"ok": True, "count": 0, "planets": []}
    page.disc_biome.setCurrentIndex(_combo_index(page.disc_biome, "Frozen"))
    assert page.disc_table.rowCount() == 0
    assert page.disc_empty.isHidden() is False
    assert "没有匹配的已发现星球" in page.disc_empty.title_label.text()
    assert page.export_action.isEnabled() is False


def test_distance_without_center_does_not_query(qapp, monkeypatch):
    svc = FakeServices(_payload([_row(index=3)]))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc)
    before = len(svc.query_calls)

    page.disc_distance.setValue(250)

    assert len(svc.query_calls) == before
    assert "设为中心" in page.disc_stats.text()


def test_filter_failure_shows_readable_empty_state(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    svc = FakeServices(_payload([_row(index=3)]))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc, captured)

    svc.query_error = RuntimeError("synthetic filter boom")
    page.disc_biome.setCurrentIndex(_combo_index(page.disc_biome, "Lush"))

    assert page.disc_table.rowCount() == 0
    assert page.disc_empty.isHidden() is False
    assert "筛选已发现星球失败" in page.disc_empty.title_label.text()
    assert "synthetic filter boom" in page.disc_empty.description_label.text()
    assert captured["error"] == []
    assert captured["warn"]


# ---------------------------------------------------------------- 传送


def test_warp_enabled_for_discovered_planet_and_reuses_confirm(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    confirmed = _accept_confirm(monkeypatch)
    svc = FakeServices(_payload([_row(index=3)]))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc, captured)
    _select_row(page, 3)

    assert page.primary_btn.isEnabled() is True
    assert GLYPHS_P3 in page.primary_btn.toolTip()
    assert page.warp_btn.isHidden() is True

    page._warp_selected_planet()

    assert svc.warp_calls == [
        {"glyphs": GLYPHS_P3, "galaxy": 0, "stage": "prepare_warp"}]
    assert captured["success"][-1] == "已传送到 Synthetic System/行星 #3"
    assert "会调用游戏内传送门机制，落到目标星球；失败可用「还原」回滚" \
        in confirmed[0]["text"]
    assert page.primary_btn.isEnabled() is True


def test_warp_needs_planet_choice_when_index_missing(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    _accept_confirm(monkeypatch)
    row = _row(index=None, glyphs=None)
    svc = FakeServices(_payload([row]))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc, captured)
    _select_row(page, None)

    assert page.primary_btn.isEnabled() is True
    assert page._warp_target and page._warp_target.get("needs_planet") is True
    assert "系统级结果" in page.primary_btn.toolTip()

    monkeypatch.setattr(
        page_mod.QInputDialog, "getInt", staticmethod(lambda *a, **k: (4, True)))

    page._warp_selected_planet()

    assert svc.warp_calls == [
        {"glyphs": GLYPHS_P4, "galaxy": 0, "stage": "prepare_warp"}]
    assert captured["success"][-1] == "已传送到 Synthetic System/行星 #4"


def test_warp_disabled_when_no_address(qapp, monkeypatch):
    row = _row(index=None, system_ua=None, glyphs=None)
    svc = FakeServices(_payload([row]))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc)
    _select_row(page, None)

    assert page.primary_btn.isEnabled() is False
    assert "没有可用的门地址" in page.status.text()


def test_warp_unconfirmed_and_build_unverified_messages_are_reused(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    _accept_confirm(monkeypatch)
    svc = FakeServices(_payload([_row(index=3)]))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc, captured)
    _select_row(page, 3)

    svc.warp_calls.clear()
    svc.warp_portal = lambda glyphs, galaxy=None, stage="prepare_warp": {
        "ok": True, "confirmed": False, "confirm_error": "40 秒内未读回目标位置"}
    page._warp_selected_planet()
    assert "传送未确认" in captured["warn"][-1]

    svc.warp_portal = lambda glyphs, galaxy=None, stage="prepare_warp": {
        "ok": False, "code": "E_BUILD_UNVERIFIED",
        "error": "这版未验证：高风险写操作已禁用"}
    page._warp_selected_planet()
    assert "E_BUILD_UNVERIFIED" in captured["error"][-1]
    assert "需要先开启实验写入开关" in captured["error"][-1]


# ---------------------------------------------------------------- CSV


def test_csv_export_contains_table_columns_glyphs_and_coords(qapp, monkeypatch, tmp_path):
    row = _row(index=3, name="Synthetic Planet", infested=True,
               distance_ly=1234.0)
    svc = FakeServices(_payload([row]))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc)
    _select_row(page, 3)

    table_header = [page.disc_table.horizontalHeaderItem(i).text()
                    for i in range(page.disc_table.columnCount())]
    assert table_header == page_mod.DISCOVERED_COLUMNS

    text = page._discovered_csv_text(page._discovered_rows)
    lines = list(csv.DictReader(io.StringIO(text)))
    assert len(lines) == 1
    header = list(csv.DictReader(io.StringIO(text)).fieldnames or [])
    for column in ("行星", "星系", "群系", "虫蚀", "命名", "距离", "符文",
                   "存档", "坐标", "发现者", "发现时间", "来源"):
        assert column in header
    assert lines[0]["行星"] == "3"
    assert lines[0]["符文"] == GLYPHS_P3
    assert lines[0]["坐标"] == SYSTEM_COORDS
    assert lines[0]["发现者"] == ""
    assert lines[0]["来源"] == "索引"
    assert "距离" in lines[0] and lines[0]["距离"] == "1234.0"

    target = tmp_path / "discovered.csv"
    monkeypatch.setattr(
        page_mod.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "CSV 表格文件 (*.csv)")))
    page._export_discovered_csv()

    assert target.exists()
    exported = target.read_text("utf-8")
    assert "符文" in exported and GLYPHS_P3 in exported
    assert "坐标" in exported and SYSTEM_COORDS in exported


def test_reentering_discovered_within_window_does_not_reload(qapp, monkeypatch):
    """30 秒内重复点击「已发现」不应重新建立索引。"""
    import time as _time

    page = _make_page(monkeypatch, FakeServices())
    calls: list[dict] = []
    monkeypatch.setattr(page, "_load_discovered",
                        lambda **kw: calls.append(dict(kw)))
    page._discovered_loaded = True
    page._discovered_loaded_at = _time.monotonic()
    page.show_section("已发现")
    assert calls == []
    page._discovered_loaded_at = _time.monotonic() - 60
    page.show_section("已发现")
    assert len(calls) == 1
