"""Flask 应用：安全中间件 + 错误协议 + 页面。

S0 验收项全部在这里：
  · Host/Origin 校验（Shipwright 缺这一环）
  · NmsHunterError -> {"ok":false,"error":{kind,message,hint}} + 对应 HTTP 码
  · 写开关闸门（写接口先过 require_write）
"""
from __future__ import annotations

from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, request

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

    @app.get("/")
    def index():                                      # noqa: ANN202
        return Response(_INDEX_HTML.replace("{{title}}", strings.APP_TITLE), mimetype="text/html")

    @app.get("/favicon.ico")
    def favicon():                                    # noqa: ANN202
        return Response(status=204)

    return app


_INDEX_HTML = """<!doctype html><meta charset="utf-8"><title>{{title}}</title>
<style>
 body{background:#0c0e13;color:#d7dce5;font:14px/1.6 system-ui,"Segoe UI",sans-serif;margin:0}
 header{padding:14px 22px;border-bottom:1px solid #1b2230;display:flex;gap:16px;align-items:baseline}
 h1{font-size:15px;margin:0;font-weight:600} .muted{color:#7d8694;font-size:12px}
 main{padding:18px 22px;max-width:1100px} table{border-collapse:collapse;width:100%}
 th,td{border-bottom:1px solid #1b2230;padding:7px 10px;text-align:left;font-size:13px}
 th{color:#8b94a3;font-weight:500;font-size:12px} code{font-family:ui-monospace,Consolas,monospace;color:#e8eef7}
 .pill{display:inline-block;padding:1px 8px;border-radius:99px;background:#1b2230;font-size:12px}
 .warn{color:#ffb86b} .bad{color:#ff8b6b} canvas{background:#151a22;border-radius:8px}
</style>
<header><h1>{{title}}</h1><span class="muted" id="ver">载入中…</span></header>
<main>
  <p class="muted" id="caps">检查能力…</p>
  <h3 style="font-size:13px;margin:18px 0 6px">存档里的船</h3>
  <table id="ships"><thead><tr><th>槽位</th><th>类型</th><th>种子</th><th>名称</th><th>模型</th></tr></thead><tbody></tbody></table>
</main>
<script>
const $ = s => document.querySelector(s);
async function api(p){ const r = await fetch(p); const j = await r.json().catch(()=>({}));
  if(!r.ok || j.ok === false){ throw new Error((j.error&&j.error.message)||r.status); } return j; }
(async () => {
  try {
    const h = await api('/api/health');
    $('#ver').textContent = `v${h.version} · 预览档位 ${h.preview_level}`;
    $('#caps').innerHTML = `数据目录 <code>${h.gamedata||'未找到'}</code> · 存档 <code>${h.saves_dir||'未找到'}</code> · 写入 <span class="pill">${h.write_enabled?'已开启':'关闭'}</span>`;
    const s = await api('/api/ships');
    const tb = $('#ships tbody');
    tb.innerHTML = s.ships.map(x => `<tr><td>${x.slot}</td><td><span class="pill">${x.type}</span></td>
      <td><code>${x.seed}</code></td><td>${x.name||'<span class=warn>未命名</span>'}</td>
      <td><code style="font-size:11px">${(x.model||'').split('/').pop()}</code></td></tr>`).join('');
    if (s.warnings && s.warnings.length) {
      $('#caps').insertAdjacentHTML('beforeend', `<div class="warn">${s.warnings.join('<br>')}</div>`);
    }
  } catch (e) {
    $('#caps').innerHTML = `<span class="bad">${e.message}</span>`;
  }
})();
</script>
"""
