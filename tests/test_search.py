

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
