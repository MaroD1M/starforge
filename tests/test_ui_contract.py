"""UI ↔ API 契约：页面里调用到的每个接口都必须真实存在。

这条测试是给"界面重写"兜底的——v0.9.7 曾因为前端还在请求旧字段/旧路径而白屏。
做法：把 app.js 里的 `/api/...` 字面量抽出来，逐个打到测试客户端，
只要求"不是 404"（参数缺失导致 400/403/503 都算存在）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "starforge" / "web" / "static" / "app.js"

# 前端里带变量的路径，替换成安全占位后再请求
SUBST = [
    (r"\$\{[^}]+\}", "fighter"),
]

SKIP_PREFIX = ("/api/thumb/", "/api/model/", "/api/icons/", "/api/glyphs/")


def api_paths() -> list[str]:
    src = APP_JS.read_text("utf-8")
    raw = re.findall(r"['\"`](/api/[A-Za-z0-9_\-/${}.]+)['\"`]", src)
    raw += re.findall(r"/api/[A-Za-z0-9_\-/${}.]+", src)      # 模板字符串里拼出来的
    out = set()
    for p in raw:
        p = p.split("?")[0].rstrip(".,);'\"`")
        for pat, rep in SUBST:
            p = re.sub(pat, rep, p)
        if "${" in p:
            continue
        out.add(p)
    return sorted(out)


def test_app_js_calls_known_endpoints(client):
    """用 Flask 的路由表精确判断"这个路径存不存在"，比看 HTTP 状态码可靠。"""
    from werkzeug.exceptions import NotFound, MethodNotAllowed

    paths = api_paths()
    assert len(paths) >= 8, f"解析到的接口太少，可能正则失效：{paths}"
    binder = client.application.url_map.bind("127.0.0.1")
    missing = []
    for p in paths:
        if p.startswith(SKIP_PREFIX):
            continue
        path = p.rstrip("/") or "/"
        try:
            binder.match(path, method="GET")
        except MethodNotAllowed:
            try:
                binder.match(path, method="POST")
            except (NotFound, MethodNotAllowed):
                missing.append(p)
        except NotFound:
            missing.append(p)
    assert not missing, f"前端调用了不存在的接口：{missing}"


def test_app_js_uses_fields_the_api_returns(client):
    """抽查几个前端依赖的字段，避免后端改名导致界面空白。"""
    h = client.get("/api/health").get_json()
    for k in ("version", "preview_level", "write_enabled", "saves_ready", "data_ready"):
        assert k in h
    cap = client.get("/api/capabilities").get_json()
    assert "preview_level" in cap and "system" in cap
    st = client.get("/api/settings").get_json()
    assert "settings" in st and "resolved" in st


def test_viewer_uses_webgl2_and_handles_uint_indices():
    """v0.11.0 的 3D 是黑屏：WebGL1 下没启 OES_element_index_uint + GLSL 非法 mat3(mat4)。

    这里守住三条：优先 webgl2、webgl1 必须取扩展、着色器不出现 mat3(uModel)。
    """
    src = (ROOT / "starforge" / "web" / "static" / "viewer.js").read_text("utf-8")
    assert "getContext('webgl2'" in src
    assert "OES_element_index_uint" in src
    assert "mat3(uModel)" not in src
    assert "uNormal" in src                     # 法线矩阵单独传


def test_viewer_falls_back_when_canvas_empty():
    """画布没内容时必须能退回服务端渲染图，不能留黑框。"""
    viewer = (ROOT / "starforge" / "web" / "static" / "viewer.js").read_text("utf-8")
    app = (ROOT / "starforge" / "web" / "static" / "app.js").read_text("utf-8")
    assert "sf-viewer-empty" in viewer and "sf-viewer-empty" in app
    assert "readPixels" in viewer
