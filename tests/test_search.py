

def test_same_group_parts_rejected_with_reason(game_env):
    """同一插槽组选两个部件是永远搜不到的：必须给出可读错误，而不是跑一遍空结果。"""
    import pytest
    from starforge import parts, search
    tree = parts.tree("sentinel")
    g = next(g for g in tree if len(g["options"]) >= 2)
    a, b = g["options"][0]["part"], g["options"][1]["part"]
    with pytest.raises(search.QueryError) as e:
        search.validate(search.SearchQuery(ship="sentinel", want=[a, b]))
    assert "只能选一个" in str(e.value)


def test_different_groups_accepted(game_env):
    from starforge import parts, search
    tree = [g for g in parts.tree("sentinel") if g["options"]]
    a = tree[0]["options"][0]["part"]
    b = tree[1]["options"][0]["part"]
    q = search.validate(search.SearchQuery(ship="sentinel", want=[a, b]))
    assert len(q.want) == 2


def test_explain_handles_measure_dict(game_env, monkeypatch):
    """上游 measure 返回 dict（tested/hits）时不能再拿它和 int 比较。"""
    from starforge import search
    from nms_procgen import fastsearch

    monkeypatch.setattr(fastsearch, "measure",
                        lambda *a, **k: {"tested": 1000, "hits": 2,
                                         "parts": 0, "colouring": False})
    from starforge import parts
    tree = parts.tree("sentinel")
    group = next(g for g in tree if g["options"])
    q = search.SearchQuery(ship="sentinel", want=[group["options"][0]["part"]])
    res = search.explain(q)
    assert res["one_in"] == 500.0
    assert res["estimate_seconds"] is not None
