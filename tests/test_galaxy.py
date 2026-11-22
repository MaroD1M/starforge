"""M3：银河索引（落库 + 条件查询 + 断点式扫描）。

重点不是"能扫"，而是：
  · 扫过的星系**真的进库**，重复扫同一地址是刷新而不是重复行；
  · 条件查询在库里完成（不需要游戏在跑）；
  · 扫描用可注入的 `provider`，所以这些断言不依赖 unicorn。
"""
import json
import os

import pytest

from starforge import galaxy


def _sys(ua, *, planets=3, dissonant=False, race="Korvax", interceptor=None, biome="Lush",
         sentinels="none"):
    return {"ua": "0x%X" % ua, "coords": "04E4:0070:01BC:0104", "glyphs": "1112F19BDCE5",
            "galaxy": 0, "race": race, "economy": "Trading", "conflict": "low",
            "planets": planets, "moons": 0, "dissonant": dissonant,
            "interceptor": interceptor, "region_valid": True,
            "planet_list": [{"index": i, "biome_name": biome, "sentinels": sentinels,
                             "weather": "Clear", "flora": "Abundant", "fauna": "Sparse"}
                            for i in range(planets)]}


@pytest.fixture()
def store(tmp_path):
    s = galaxy.GalaxyStore(str(tmp_path / "g.db"))
    yield s
    s.close()


def test_upsert_is_idempotent(store):
    row = _sys(0xABC)
    store.upsert_system(row)
    store.upsert_system(row)                       # 再扫一次同一星系
    st = store.stats()
    assert st["systems"] == 1
    assert st["planets"] == 3                      # 行星行也不重复


def test_query_by_biome_and_sentinels(store):
    store.upsert_system(_sys(0x1, biome="Lush", sentinels="none"))
    store.upsert_system(_sys(0x2, biome="Frozen", sentinels="high"))
    lush = store.query({"biome": "Lush"})
    assert [r["ua"] for r in lush] == ["0x1"]
    assert lush[0]["matched_planets"][0]["biome"] == "Lush"
    hostile = store.query({"sentinels": "high"})
    assert [r["ua"] for r in hostile] == ["0x2"]


def test_query_by_dissonant_and_interceptor(store):
    store.upsert_system(_sys(0x10, dissonant=True, interceptor="0xDEAD"))
    store.upsert_system(_sys(0x11))
    assert [r["ua"] for r in store.query({"dissonant": True})] == ["0x10"]
    assert [r["ua"] for r in store.query({"has_interceptor": True})] == ["0x10"]
    assert store.query({"dissonant": True})[0]["dissonant"] is True


def test_query_min_planets(store):
    store.upsert_system(_sys(0x20, planets=2))
    store.upsert_system(_sys(0x21, planets=6))
    assert [r["ua"] for r in store.query({"min_planets": 4})] == ["0x21"]


def test_query_dedupes_system_rows(store):
    """一个星系 3 颗行星都命中时，只应返回一条星系（matched_planets 里带 3 条）。"""
    store.upsert_system(_sys(0x30, planets=3, biome="Lush"))
    rows = store.query({"biome": "Lush"})
    assert len(rows) == 1 and len(rows[0]["matched_planets"]) == 3


def test_planet_list_stored_as_json(store):
    store.upsert_system(_sys(0x40, planets=2))
    raw = store.conn.execute("SELECT planet_list FROM systems WHERE ua='0x40'").fetchone()[0]
    assert isinstance(json.loads(raw), list) and len(json.loads(raw)) == 2


def test_scan_uses_injected_provider_and_persists(tmp_path):
    """扫描主流程：provider 注入 → 全部落库 → 命中按条件筛。"""
    seen = []

    def provider(ua):
        seen.append(ua)
        n = len(seen)
        return _sys(ua, planets=n % 4 + 1, dissonant=(n % 2 == 0),
                    interceptor="0xBEEF" if n % 2 == 0 else None)

    st = galaxy.GalaxyStore(str(tmp_path / "scan.db"))
    out = galaxy.scan(center_ua=0x11200F19BDCE5, radius=0, systems_per_region=6,
                      filters={"dissonant": True}, limit=10, provider=provider, store=st)
    assert out["scanned"] == len(seen) == 6
    assert out["store"]["systems"] == 6
    assert all(h["dissonant"] for h in out["hits"])
    assert st.query({"dissonant": True})           # 库里有，且不用再生成
    st.close()


def test_scan_respects_limit(tmp_path):
    def provider(ua):
        return _sys(ua, planets=4)

    st = galaxy.GalaxyStore(str(tmp_path / "cap.db"))
    out = galaxy.scan(center_ua=0x11200F19BDCE5, radius=0, systems_per_region=20,
                      filters={}, limit=3, provider=provider, store=st)
    assert len(out["hits"]) == 3 and out["scanned"] == 3      # 到量即停，不多扫
    st.close()


def test_api_galaxy_query_and_stats(client, monkeypatch, tmp_path):
    monkeypatch.setenv("STARFORGE_HOME", str(tmp_path))
    from starforge.core import settings
    settings._CURRENT = None
    settings.update(saves_dir="/tmp/nonexistent")
    st = galaxy.GalaxyStore()
    st.upsert_system(_sys(0x50, planets=5, dissonant=True, interceptor="0x11"))
    st.close()
    j = client.get("/api/galaxy/query?dissonant=1&min_planets=4").get_json()
    assert j["ok"] and j["count"] == 1 and j["rows"][0]["ua"] == "0x50"
    s = client.get("/api/galaxy/stats").get_json()
    assert s["ok"] and s["systems"] >= 1


def test_csv_export(client, monkeypatch, tmp_path):
    monkeypatch.setenv("STARFORGE_HOME", str(tmp_path))
    from starforge.core import settings
    settings._CURRENT = None
    settings.update(saves_dir="/tmp/nonexistent")
    st = galaxy.GalaxyStore()
    st.upsert_system(_sys(0x60, planets=2, dissonant=True, interceptor="0xCAFE"))
    st.close()
    r = client.get("/api/galaxy/export.csv?dissonant=1")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert "attachment" in r.headers.get("Content-Disposition", "")
    text = r.data.decode()
    lines = [ln for ln in text.splitlines() if ln]
    assert lines[0].startswith("ua,glyphs,coords")
    assert len(lines) == 3, f"1 个星系 × 2 颗行星 = 表头 + 2 行，实际 {len(lines)}"
    assert "0x60" in text and "Lush" in text


def test_csv_export_respects_filters(client, monkeypatch, tmp_path):
    monkeypatch.setenv("STARFORGE_HOME", str(tmp_path))
    from starforge.core import settings
    settings._CURRENT = None
    settings.update(saves_dir="/tmp/nonexistent")
    st = galaxy.GalaxyStore()
    st.upsert_system(_sys(0x70, planets=1, biome="Frozen"))
    st.upsert_system(_sys(0x71, planets=1, biome="Lush"))
    st.close()
    text = client.get("/api/galaxy/export.csv?biome=Frozen").data.decode()
    assert "0x70" in text and "0x71" not in text


# ---------------------------------------------------------------- 星图页交互重排


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class _PageServices:
    def glyph_strip_png(self, glyphs: str) -> bytes:
        return b""

    def discoveries_index_all(self) -> dict:
        return {"ok": True, "count": 0, "saves": [], "errors": []}

    def discoveries_query(self, **kw) -> dict:
        return {"ok": True, "count": 0, "planets": []}

    def discovered_planets(self, path: str | None = None) -> dict:
        return {"ok": True, "count": 0, "planets": []}

    def discovered_filter(self, planets=None, **kw) -> dict:
        return {"ok": True, "count": 0, "planets": list(planets or [])}


def _make_page(monkeypatch):
    from starforge.app.pages import galaxy as page_mod

    monkeypatch.setattr(page_mod, "get_services", lambda: _PageServices())
    return page_mod.GalaxyPage()


def test_primary_action_follows_current_tab(qapp, monkeypatch):
    page = _make_page(monkeypatch)
    try:
        assert page.primary_btn.text() == "扫描"
        page.tabs.setCurrentWidget(page.scan_page)
        assert page.primary_btn.text() == "扫描"
        page.tabs.setCurrentWidget(page.index_page)
        assert page.primary_btn.text() == "查询"
        page.show_section("已发现")
        assert page.primary_btn.text() == "传送到此星球"
        page.show_section("地址工作台")
        assert page.primary_btn.text() == "转换地址"
    finally:
        page.close()


def test_sections_have_their_own_header_and_hero_visibility(qapp, monkeypatch):
    page = _make_page(monkeypatch)
    try:
        page.show_section("已发现")
        assert page.header.title.text() == "已发现星球"
        assert page.hero.isHidden() is True
        assert page.tabs.tabBar().isVisible() in (False, True)
        page.show_section("地址工作台")
        assert page.header.title.text() == "地址工作台"
        assert page.hero.isHidden() is True
        assert page.detail_card.isHidden() is True
        page.show_section("行星")
        assert page.header.title.text() == "星图"
        assert page.hero.isHidden() is False
        assert page.detail_card.isHidden() is True      # 结果优先：未选中不展开详情
    finally:
        page.close()


def test_discovered_filters_cover_save_keyword_sort_and_limit(qapp, monkeypatch):
    page = _make_page(monkeypatch)
    try:
        page.show_section("已发现")
        assert page.disc_save.itemText(0).startswith("全部存档")
        assert page.disc_keyword.placeholderText()
        assert [page.disc_sort.itemData(i) for i in range(page.disc_sort.count())] == [
            "distance", "discovered", "biome", "name"]
        assert [page.disc_limit.itemData(i) for i in range(page.disc_limit.count())] == [
            500, 1000, 0]
    finally:
        page.close()


def test_secondary_actions_are_in_more_menu(qapp, monkeypatch):
    page = _make_page(monkeypatch)
    try:
        labels = [action.text() for action in page.more_btn.menu().actions()
                  if action.text()]
        assert "刷新当前星系" in labels
        assert "导出 CSV" in labels
        assert "浮窗显示选中符文" in labels
        assert "清空当前筛选" in labels
        assert page.header.actions.count() == 3      # primary + 取消扫描 + 更多
        assert not hasattr(page, "refresh_btn")
        assert not hasattr(page, "export_btn")
    finally:
        page.close()


def test_double_click_opens_detail_dialog(qapp, monkeypatch):
    from starforge.app.pages import galaxy as page_mod

    page = _make_page(monkeypatch)
    seen: list[dict] = []

    class FakeDialog:
        def __init__(self, title, body, *, glyphs=None, parent=None):
            seen.append({"title": title, "body": body, "glyphs": glyphs})

        def show(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(page_mod, "GalaxyDetailDialog", FakeDialog)
    try:
        page._fill_scan_rows([{
            "ua": "0x11200F19BDCE5", "index": 3, "system_name": "EOCS-1",
            "coords": "04E4:0070:01BC:0112", "glyphs": "3112F19BDCE5"}])
        page._on_table_double_click(page.scan_table, 0)
        assert seen and seen[-1]["glyphs"] == "3112F19BDCE5"
        assert "04E4:0070:01BC:0112" in seen[-1]["title"]
    finally:
        page.close()

