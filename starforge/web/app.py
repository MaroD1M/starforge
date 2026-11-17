"""Flask 应用：安全中间件 + 错误协议 + 页面。

S0 验收项全部在这里：
  · Host/Origin 校验（Shipwright 缺这一环）
  · NmsHunterError -> {"ok":false,"error":{kind,message,hint}} + 对应 HTTP 码
  · 写开关闸门（写接口先过 require_write）
"""
from __future__ import annotations

from urllib.parse import urlsplit

import os

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from ..core import log, settings, strings
from ..core.errors import NmsHunterError

log = log.get("web")

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _host_only(value: str) -> str:
    if not value:
        return ""
    if "://" in value:
        return (urlsplit(value).hostname or "").lower()
    return value.split(":")[0].strip("[]").lower()


def create_app() -> Flask:
    from ..core import console
    console.setup_console()
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False

    @app.before_request
    def _guard():                                     # noqa: ANN202
        host = _host_only(request.host)
        if host and host not in ALLOWED_HOSTS:
            return jsonify({"ok": False, "error": {
                "kind": "bad_host", "message": f"拒绝来自 {request.host} 的请求",
                "hint": "本工具只监听本机 127.0.0.1"}}), 403
        origin = request.headers.get("Origin")
        if origin and _host_only(origin) not in ALLOWED_HOSTS:
            return jsonify({"ok": False, "error": {
                "kind": "bad_origin", "message": f"拒绝跨站来源 {origin}",
                "hint": "防 CSRF / DNS rebinding"}}), 403
        return None

    @app.errorhandler(NmsHunterError)
    def _biz(err: NmsHunterError):                    # noqa: ANN202
        log.warning("%s: %s", err.kind, err.message)
        return jsonify({"ok": False, "error": err.as_dict()}), err.status

    @app.errorhandler(HTTPException)
    def _http(err):                                   # noqa: ANN202
        """werkzeug 的 404/403 等按原状态码返回，别被兜底成 500。"""
        return jsonify({"ok": False, "error": {
            "kind": (err.name or "http").lower().replace(" ", "_"),
            "message": err.description or err.name, "hint": ""}}), err.code

    @app.errorhandler(FileNotFoundError)
    def _missing(err: FileNotFoundError):             # noqa: ANN202
        return jsonify({"ok": False, "error": {
            "kind": "missing", "message": str(err),
            "hint": "检查设置里的 gamedata_dir / saves_dir"}}), 503

    @app.errorhandler(Exception)
    def _boom(err: Exception):                        # noqa: ANN202
        log.exception("unhandled")
        return jsonify({"ok": False, "error": {
            "kind": "internal", "message": f"{type(err).__name__}: {err}",
            "hint": "看日志：~/.starforge/logs/starforge.log"}}), 500

    from .routes import bp
    app.register_blueprint(bp)

    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

    @app.get("/")
    def index():                                      # noqa: ANN202
        return send_from_directory(static_dir, "index.html")

    @app.get("/static/<path:filename>")
    def static_file(filename: str):                   # noqa: ANN202
        return send_from_directory(static_dir, filename)

    @app.errorhandler(404)
    def _missing(err):                                # noqa: ANN202
        if os.path.exists(os.path.join(static_dir, "index.html")):
            return jsonify({"ok": False, "error": {
                "kind": "not_found", "message": getattr(err, "description", "404"), "hint": ""}}), 404
        return Response(
            "<!doctype html><meta charset='utf-8'><title>starforge</title>"
            "<body style='background:#0c0e13;color:#d7dce5;font:14px system-ui;padding:40px'>"
            "<h2>网页资源缺失</h2>"
            "<p>这个打包版本里没有 <code>starforge/web/static</code>（打包时漏了 --add-data）。</p>"
            "<p>命令行仍可用：<code>starforge.exe ships</code> / <code>selftest</code> / <code>selfcheck</code>。</p>"
            "<p>请换用较新的 Release，或把 <code>starforge/web/static</code> 复制到程序目录下的同名路径。</p>"
            "</body>", status=500, mimetype="text/html")

    @app.get("/favicon.ico")
    def favicon():                                    # noqa: ANN202
        return Response(status=204)

    return app
