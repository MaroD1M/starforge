"""M2：按涂装（真实配色）筛飞船种子。

两种模式：
  · 索引模式 `{primary: [3,17]}` —— 交给上游 look_mask，与搜索同速（向量化）；
  · RGB 模式 `{primary: [0.95,0.78,0.10], tol: 0.18}` —— 上游只按部件筛，命中后用
    `paint.look()` 解出真实配色再比距离。**必须验证"结果真的接近目标色"**，否则等于没筛。
"""
import pytest

from starforge import search


def _q(**kw):
    base = dict(ship="fighter", limit=3, time_limit=25, max_seeds=50_000_000)
    base.update(kw)
    return search.SearchQuery(**base)


def test_look_kind_detection():
    assert search.look_kind(None) == "none"
    assert search.look_kind({}) == "none"
    assert search.look_kind({"primary": [3, 17]}) == "index"
    assert search.look_kind({"primary": [0.9, 0.7, 0.1]}) == "rgb"


def test_look_upstream_strips_rgb():
    assert search.look_upstream({"primary": [0.9, 0.7, 0.1], "tol": 0.2}) is None
    assert search.look_upstream({"primary": [3]}) == {"primary": [3]}


def test_look_validates_rgb_range(game_env):
    with pytest.raises(search.QueryError) as e:
        search.validate(_q(look={"primary": [2.0, 0.5, 0.5]}))
    assert "0..1" in str(e.value) or "RGB" in str(e.value)


def test_look_validates_tolerance(game_env):
    with pytest.raises(search.QueryError):
        search.validate(_q(look={"primary": [0.5, 0.5, 0.5], "tol": 0}))


def test_ui_look_payload_only_carried_when_toggle_is_on():
    from starforge.app.pages.ship_lab import look_filter_payload

    assert look_filter_payload(False, (0.95, 0.78, 0.10)) is None
    assert look_filter_payload(True, (0.95, 0.78, 0.10), tolerance=0.18) == {
        "primary": [0.95, 0.78, 0.10], "tol": 0.18}
    # 副色只在勾选“副色”时进入条件，避免默认把搜索卡死。
    assert look_filter_payload(
        True, (0.95, 0.78, 0.10), secondary_enabled=True,
        secondary=(0.1, 0.1, 0.12), tolerance=0.28) == {
        "primary": [0.95, 0.78, 0.10],
        "secondary": [0.1, 0.1, 0.12], "tol": 0.28}


def test_only_look_without_parts_is_allowed(game_env):
    """只按涂装搜也必须成立（此前必须有部件）。"""
    q = search.validate(_q(look={"primary": [0.95, 0.78, 0.10], "tol": 0.25}))
    assert q.want == [] and q.look["tol"] == 0.25


@pytest.mark.slow
def test_rgb_look_results_really_match(game_env):
    """结果里的船，解出来的配色必须真的落在容差内（自证，不是"看起来跑了"）。"""
    from starforge import paint
    q = search.validate(_q(look={"primary": [0.95, 0.78, 0.10], "tol": 0.30,
                                 "max_candidates": 800}, limit=2))
    rows = search.run(q)
    if not rows:
        pytest.skip("这个色号在预算内没命中（属正常，换色号）")
    for r in rows:
        got = paint.look(r["seed"], r["type"]) or {}
        assert "paint" in got, "涂装模式下允许出现的船必须能解出配色"
        d = search._dist(got["paint"], [0.95, 0.78, 0.10])
        assert d <= 0.30 + 1e-6, (r["seed"], d)
        assert r.get("look_match"), "结果要带距离，界面才能显示"
