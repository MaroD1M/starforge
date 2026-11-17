"""把所有 GET 路由都打一遍：不允许出现 500（未处理异常）。

这是"界面某处点下去就崩"的兜底：只要路由自身有 bug（KeyError/TypeError/None 解引用），
这里就会红。
"""
from __future__ import annotations

import pytest


def _get_routes(app):
    out = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static" or "<path:filename>" in rule.rule:
            continue
        if "GET" not in (rule.methods or ()):
            continue
        path = rule.rule
        path = (path.replace("<int:", "<").replace("<string:", "<").replace("<path:", "<")
                    .replace("<job_id>", "nonexistent").replace("<ship>", "sentinel")
                    .replace("<seed>", "0x884609884CD21A5C").replace("<name>", "1043FEE69929")
                    .replace("<part>", "_PIT_A").replace("<type_>", "sentinel"))
        out.append(path)
    return sorted(set(out))


def test_no_route_returns_500(client, game_env, saves_dir):
    from starforge.core import settings as settings_mod
    settings_mod.update(saves_dir=str(saves_dir))
    app = client.application
    bad = []
    for path in _get_routes(app):
        if "<" in path:                      # 还有没替换掉的变量，跳过
            continue
        r = client.get(path)
        if r.status_code == 500:                 # 503 是设计内的降级（如非 Windows 的实时通道）
            bad.append((path, r.status_code, (r.get_json(silent=True) or {}).get("error", {}).get("message", "")[:80]))
    assert not bad, f"这些路由崩了：{bad}"


def test_unknown_routes_are_json_404(client):
    for path in ("/api/nope", "/api/ships/xyz", "/"):
        r = client.get(path)
        assert r.status_code in (200, 404)
        if r.status_code == 404:
            assert r.mimetype == "application/json"
