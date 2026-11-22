"""星图「已发现」页签：加载/筛选/传送/CSV 全部打桩。

这些用例只验证界面编排：过滤逻辑必须由 `Services.discovered_filter`
完成，页面不自己筛；传送复用现有「传送到此星球」确认流程。
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
                 filter_result: dict | None = None,
                 filter_error: Exception | None = None):
        self.discovered = discovered if discovered is not None else _payload([])
        self.filter_result = filter_result
        self.filter_error = filter_error
        self.discovered_calls = 0
        self.filter_calls: list[dict] = []
        self.warp_calls: list[dict] = []

    def discovered_planets(self, path: str | None = None) -> dict:
        self.discovered_calls += 1
        return dict(self.discovered)

    def discovered_filter(self, planets: list[dict] | None = None, **kw) -> dict:
        self.filter_calls.append({"planets": planets, "kwargs": dict(kw)})
        if self.filter_error is not None:
            raise self.filter_error
        if self.filter_result is not None:
            return dict(self.filter_result)
        rows = list(planets or [])
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
         discoverer: str | None = "Synthetic Discoverer",
         discovered_at: int | None = 1_700_000_000,
         source: str = "save", pending: bool = False,
         glyphs: str | None = GLYPHS_P3, distance_ly=None,
         system_ua: str | None = SYSTEM_UA_TEXT) -> dict:
    ua = None
    if index is not None and system_ua is not None:
        ua = f"0x{SYSTEM_UA | (index << 52):X}"
    return {
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
        **({"distance_ly": distance_ly} if distance_ly is not None else {}),
    }


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
        "stats": {
            "biomes": {},
            "infested": sum(1 for row in rows if row.get("infested")),
            "named": sum(1 for row in rows if row.get("name")),
            "pending": sum(1 for row in rows if row.get("pending")),
            "unknown_biome": sum(1 for row in rows if not row.get("biome")),
        },
    }
    out.update(overrides)
    return out


def _make_page(monkeypatch, svc: FakeServices):
    monkeypatch.setattr(page_mod, "get_services", lambda: svc)
    monkeypatch.setattr(page_mod, "run_worker", _sync_worker)
    page = page_mod.GalaxyPage()
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


def test_discovered_tab_is_next_to_scan_and_index(qapp, monkeypatch):
    page = _make_page(monkeypatch, FakeServices())
    labels = [page.tabs.tabText(i) for i in range(page.tabs.count())]
    assert "已发现" in labels
    assert labels.index("已发现") > labels.index("扫描结果")
    assert labels.index("已发现") > labels.index("银河索引")


def test_load_fills_table_stats_and_detail(qapp, monkeypatch):
    rows = [
        _row(index=3, name="Synthetic Planet", infested=True),
        _row(index=1, biome="Frozen", glyphs="110000000000", distance_ly=1234.0),
    ]
    svc = FakeServices(_payload(rows))
    page = _make_page(monkeypatch, svc)
    captured = _load(page, monkeypatch, svc)

    assert svc.discovered_calls == 1
    assert page.disc_table.rowCount() == 2
    assert page.disc_export_btn.isEnabled() is True
    assert page.disc_empty.isHidden() is True
    assert "已发现：2 颗" in page.disc_stats.text()
    assert "当前显示 2 颗" in page.disc_stats.text()
    assert "已命名 1 颗" in page.disc_stats.text()
    assert "虫蚀 1 颗" in page.disc_stats.text()
    assert captured["error"] == []

    _select_row(page, 3)
    detail = page.detail.text()
    assert "Synthetic Planet" in detail
    assert "发现者：Synthetic Discoverer" in detail
    assert "来源：存档" in detail
    assert "符文：310000000000" in detail
    assert SYSTEM_COORDS in detail


def test_empty_payload_shows_readable_empty_state(qapp, monkeypatch):
    svc = FakeServices(_payload([]))
    page = _make_page(monkeypatch, svc)
    captured = _load(page, monkeypatch, svc)

    assert page.disc_table.rowCount() == 0
    assert page.disc_empty.isHidden() is False
    assert "没有已发现的星球" in page.disc_empty.title_label.text()
    assert "Planet" in page.disc_empty.description_label.text()
    assert page.disc_export_btn.isEnabled() is False
    assert "0 颗" in page.disc_stats.text()
    assert captured["error"] == []


def test_failed_read_shows_explanation_without_error_popup(qapp, monkeypatch):
    svc = FakeServices({
        "ok": False,
        "count": 0,
        "records": 0,
        "duplicates": 0,
        "planets": [],
        "warnings": ["读取存档失败：FileNotFoundError: 没有找到存档"],
    })
    page = _make_page(monkeypatch, svc)
    captured = _load(page, monkeypatch, svc)

    assert page.disc_empty.isHidden() is False
    assert "没有可用的已发现数据" in page.disc_empty.title_label.text()
    assert "FileNotFoundError" in page.disc_empty.description_label.text()
    assert "设置页" in page.disc_empty.description_label.text()
    assert page.disc_stats.text() == "已发现：不可用"
    assert captured["error"] == []


def test_worker_exception_shows_failure_explanation(qapp, monkeypatch):
    class Boom(FakeServices):
        def discovered_planets(self, path: str | None = None) -> dict:
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

    call = svc.filter_calls[-1]
    assert call["planets"] == rows
    assert call["kwargs"] == {
        "biome": "Lush",
        "infested": True,
        "named": False,
        "near_ua": SYSTEM_UA_TEXT,
        "max_distance": 500.0,
        "sort": "auto",
        "limit": 500,
    }


def test_filter_result_drives_table_and_empty_state(qapp, monkeypatch):
    rows = [_row(index=3), _row(index=1)]
    svc = FakeServices(
        _payload(rows),
        filter_result={"ok": True, "count": 1, "planets": [rows[0]]},
    )
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc)

    page.disc_biome.setCurrentIndex(_combo_index(page.disc_biome, "Lush"))

    assert svc.filter_calls, "筛选变化必须调用服务层"
    assert page.disc_table.rowCount() == 1
    assert "当前显示 1 颗" in page.disc_stats.text()

    svc.filter_result = {"ok": True, "count": 0, "planets": []}
    page.disc_biome.setCurrentIndex(_combo_index(page.disc_biome, "Frozen"))
    assert page.disc_table.rowCount() == 0
    assert page.disc_empty.isHidden() is False
    assert "没有匹配的已发现星球" in page.disc_empty.title_label.text()
    assert page.disc_export_btn.isEnabled() is False


def test_distance_without_center_does_not_call_filter(qapp, monkeypatch):
    svc = FakeServices(_payload([_row(index=3)]))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc)
    before = len(svc.filter_calls)

    page.disc_distance.setValue(250)

    assert len(svc.filter_calls) == before
    assert "以当前星系为中心" in page.disc_stats.text()


def test_filter_failure_shows_readable_empty_state(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    svc = FakeServices(_payload([_row(index=3)]),
                       filter_error=RuntimeError("synthetic filter boom"))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc, captured)

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

    assert page.disc_warp_btn.isEnabled() is True
    assert GLYPHS_P3 in page.disc_warp_hint.text()
    assert page.detail_warp_btn.isEnabled() is True

    page._warp_selected_planet()

    assert svc.warp_calls == [
        {"glyphs": GLYPHS_P3, "galaxy": 0, "stage": "prepare_warp"}]
    assert captured["success"][-1] == "已传送到 Synthetic System/行星 #3"
    assert "会调用游戏内传送门机制，落到目标星球；失败可用「还原」回滚" \
        in confirmed[0]["text"]
    assert page.disc_warp_btn.isEnabled() is True


def test_warp_needs_planet_choice_when_index_missing(qapp, monkeypatch):
    captured = _capture_notify(monkeypatch)
    _accept_confirm(monkeypatch)
    row = _row(index=None, glyphs=None)
    svc = FakeServices(_payload([row]))
    page = _make_page(monkeypatch, svc)
    _load(page, monkeypatch, svc, captured)
    _select_row(page, None)

    assert page.disc_warp_btn.isEnabled() is True
    assert page._warp_target and page._warp_target.get("needs_planet") is True
    assert "系统级结果" in page.disc_warp_hint.text()

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

    assert page.disc_warp_btn.isEnabled() is False
    assert page.detail_warp_btn.isEnabled() is False
    assert "没有可用的门地址" in page.disc_warp_hint.text()


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
    for column in ("行星序号", "星系", "群系", "虫蚀", "命名", "距离", "符文",
                   "坐标", "发现者", "发现时间", "来源"):
        assert column in header
    assert lines[0]["行星序号"] == "3"
    assert lines[0]["符文"] == GLYPHS_P3
    assert lines[0]["坐标"] == SYSTEM_COORDS
    assert lines[0]["发现者"] == "Synthetic Discoverer"
    assert lines[0]["来源"] == "存档"
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
