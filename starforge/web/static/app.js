/* starforge · 前端逻辑（原生 JS，无框架、无网络依赖） */
(() => {
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  async function api(path, opts) {
    const r = await fetch(path, opts);
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) throw new Error(j.error?.message || `HTTP ${r.status}`);
    return j;
  }
  const post = (p, body) => api(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

  const S = {
    ship: 'fighter', catalog: null, want: new Set(), avoid: new Set(), mode: 'want',
    results: [], selected: null, writing: false, mine: [], mineSel: null,
    glyphs: '', viewer: null, jobTimer: null,
  };

  // ---------------------------------------------------------------- 顶栏 / 标签
  $$('.tabs button').forEach(b => b.onclick = () => {
    $$('.tabs button').forEach(x => x.classList.toggle('on', x === b));
    $$('.tab').forEach(t => t.classList.toggle('on', t.id === 'tab-' + b.dataset.tab));
  });

  async function boot() {
    try {
      const c = await api('/api/capabilities');
      $('#lvBadge').textContent = c.preview_level === 'L1' ? 'L1 真 3D' : 'L0 部件图';
      $('#lvBadge').className = 'pill ' + (c.preview_level === 'L1' ? 'ok' : '');
      if (!c.system.available) $('#sysMsg').textContent = '未检测到游戏目录：星球搜索需要 NMS.exe';
      const h = await api('/api/health');
      $('#ver').textContent = 'v' + h.version;
      if (h.gamedata) await loadCatalog(S.ship);
      else $('#searchMsg').textContent = '未配置部件目录（GAMEDATA）：请到设置页指定';
      await loadSettings();
    } catch (e) { $('#searchMsg').textContent = '启动失败：' + e.message; }
  }

  // ---------------------------------------------------------------- 搜索：船型与部件
  async function loadCatalog(ship) {
    const cat = await api('/api/catalog');
    const sel = $('#shipSel');
    if (!sel.options.length) {
      sel.innerHTML = Object.keys(cat.ships).map(s => `<option value="${s}">${s}（${cat.ships[s].parts} 个部件）</option>`).join('');
      sel.onchange = () => { S.ship = sel.value; S.want.clear(); S.avoid.clear(); renderParts(); };
    }
    S.ship = ship;
    await renderParts();
  }

  async function renderParts() {
    const cat = await api('/api/catalog/' + S.ship);
    S.catalog = cat;
    $('#partCount').textContent = `（${cat.groups.reduce((n, g) => n + g.options.length, 0)} 项）`;
    const q = ($('#partFilter').value || '').toLowerCase();
    $('#partTree').innerHTML = cat.groups.map(g => {
      const opts = g.options.filter(o => !q || o.part.toLowerCase().includes(q));
      if (!opts.length) return '';
      return `<div class="grp"><div class="grptitle">${esc(g.group)}</div><div class="opts">` +
        opts.map(o => {
          const cls = S.want.has(o.part) ? 'want' : S.avoid.has(o.part) ? 'avoid' : '';
          return `<span class="opt ${cls}" data-part="${esc(o.part)}" title="权重 ${o.weight}">${esc(o.part.replace(/^_|_$/g, ''))}</span>`;
        }).join('') + '</div></div>';
    }).join('');
    $$('.opt').forEach(el => el.onclick = () => {
      const p = el.dataset.part;
      if (S.mode === 'want') { S.want.has(p) ? S.want.delete(p) : (S.want.add(p), S.avoid.delete(p)); }
      else { S.avoid.has(p) ? S.avoid.delete(p) : (S.avoid.add(p), S.want.delete(p)); }
      renderParts();
    });
  }
  $('#partFilter').oninput = () => renderParts();
  $('#modeWant').onclick = () => { S.mode = 'want'; $('#modeWant').classList.add('on'); $('#modeAvoid').classList.remove('on'); };
  $('#modeAvoid').onclick = () => { S.mode = 'avoid'; $('#modeAvoid').classList.add('on'); $('#modeWant').classList.remove('on'); };

  // ---------------------------------------------------------------- 搜索执行
  $('#goSearch').onclick = async () => {
    if (!S.want.size && !S.avoid.size) { $('#searchMsg').textContent = '至少选一个「想要」或「不要」的部件'; return; }
    $('#searchMsg').textContent = '';
    $('#grid').innerHTML = '';
    $('#resultInfo').textContent = '搜索中…';
    try {
      const r = await post('/api/search', {
        ship: S.ship, want: [...S.want], avoid: [...S.avoid],
        limit: +$('#limit').value || 12, max_seeds: +$('#maxSeeds').value, time_limit: 30, workers: 1,
      });
      pollJob(r.job_id, onSearchDone);
    } catch (e) { $('#searchMsg').textContent = e.message; $('#resultInfo').textContent = '失败'; }
  };

  function pollJob(id, done) {
    clearInterval(S.jobTimer);
    S.jobTimer = setInterval(async () => {
      try {
        const j = await api('/api/jobs/' + id);
        const p = j.progress || {};
        const rate = p.rate ? (p.rate / 1e6).toFixed(1) + 'M/s' : '';
        $('#jobbar').classList.remove('hide');
        $('#jobbar').textContent = `${j.kind} ${j.status} · 测试 ${(p.tested || 0).toLocaleString()} · ${rate}` +
          (p.found != null ? ` · 命中 ${p.found}` : '') + (p.scanned != null ? ` · 已扫 ${p.scanned}` : '');
        if (j.status !== 'running') {
          clearInterval(S.jobTimer); $('#jobbar').classList.add('hide');
          done(j);
        }
      } catch (e) { clearInterval(S.jobTimer); $('#jobbar').classList.add('hide'); }
    }, 500);
  }

  function onSearchDone(j) {
    if (j.status === 'failed') { $('#searchMsg').textContent = '搜索失败：' + j.error; return; }
    S.results = j.result || [];
    $('#resultInfo').textContent = `${S.results.length} 个结果`;
    $('#grid').innerHTML = S.results.map((r, i) => `
      <div class="card" data-i="${i}">
        <img loading="lazy" src="/api/thumb/${r.type}/${r.seed}.png?size=300" alt="${r.seed}">
        <div class="cap"><span class="seed">…${r.seed.slice(-8)}</span>
          <span class="badge ok">3D</span></div>
      </div>`).join('');
    $$('.card').forEach(el => el.onclick = () => { $$('.card').forEach(x => x.classList.remove('on')); el.classList.add('on'); showShip(S.results[+el.dataset.i], 'searchDetail'); });
    if (S.results.length) { $$('.card')[0].click(); }
    else $('#searchMsg').textContent = '没有命中。放宽条件，或把「最多搜索」调大。';
  }

  // ---------------------------------------------------------------- 3D 查看器
  function ensureViewer() {
    if (S.viewer) return S.viewer;
    const canvas = $('#viewerCanvas');
    S.viewer = StarforgeViewer.mount(canvas);
    $('#vIso').onclick = () => { S.viewer.setView('iso'); markView('#vIso'); };
    $('#vTop').onclick = () => { S.viewer.setView('top'); markView('#vTop'); };
    $('#vSide').onclick = () => { S.viewer.setView('side'); markView('#vSide'); };
    $('#vSpin').onclick = () => { const on = !$('#vSpin').classList.contains('on'); $('#vSpin').classList.toggle('on', on); S.viewer.spin(on); };
    return S.viewer;
  }
  const markView = sel => { ['#vIso', '#vTop', '#vSide'].forEach(s => $(s).classList.toggle('on', s === sel)); };

  async function showShip(ref, panel) {
    S.selected = ref;
    const parts = ref.parts || [];
    const q = parts.length ? '?parts=' + encodeURIComponent(parts.join(',')) : '';
    const host = $('#' + panel);
    host.innerHTML = `
      <div class="viewerWrap"><canvas id="viewerCanvas"></canvas>
        <div class="viewerbar"><span id="viewerInfo" class="muted">载入中…</span><span class="grow"></span>
          <button id="vIso" class="mini on">等轴</button><button id="vTop" class="mini">俯视</button>
          <button id="vSide" class="mini">侧视</button><button id="vSpin" class="mini">自动旋转</button>
          <a id="vGlb" class="mini" href="/api/model/${ref.type}/${ref.seed}.glb${q}" download>下载 glb</a></div></div>
      <h3>${esc(ref.type)} · <code>${esc(ref.seed)}</code></h3>
      <div class="actions">
        <button class="mini" id="copySeed">复制种子</button>
        <button class="mini" id="copyShare">复制分享码</button>
        ${panel === 'searchDetail' ? '<button class="mini primary" id="applyBtn">写回存档…</button>' : ''}
      </div>
      <div id="kv"></div>
      <div class="parts" id="partIcons"></div>`;
    S.viewer = null;
    try {
      const v = ensureViewer();
      const info = await v.load(`/api/model/${ref.type}/${ref.seed}.glb${q}`);
      $('#viewerInfo').textContent = `${info.prims} 组网格 · ${(info.bytes / 1e6).toFixed(1)} MB`;
    } catch (e) {
      $('.viewerWrap').innerHTML = `<img src="/api/thumb/${ref.type}/${ref.seed}.png?size=520${parts.length ? '&parts=' + encodeURIComponent(parts.join(',')) : ''}" style="width:100%;display:block">`;
      const hint = document.createElement('div'); hint.className = 'msg';
      hint.textContent = '3D 加载失败（' + e.message + '），已用服务端渲染图代替';
      $('.viewerWrap').after(hint);
    }
    $('#copySeed').onclick = () => copy(ref.seed);
    $('#copyShare').onclick = () => copy('nsh1:' + btoa([ref.type, ref.seed, (parts || []).join('|')].join(';')));
    const preview = await api(`/api/preview/${ref.type}/${ref.seed}`).catch(() => ({}));
    $('#kv').innerHTML = [
      ['档位', preview.level || '—'], ['顶点', (preview.verts || 0).toLocaleString()],
      ['三角', (preview.tris || 0).toLocaleString()], ['部件数', parts.length],
      ['来源', ref.source || '—'],
    ].map(([k, v]) => `<div class="kvrow"><span>${k}</span><span>${esc(v)}</span></div>`).join('');
    if (parts.length) {
      $('#partIcons').innerHTML = parts.map(p => `<img loading="lazy" title="${esc(p)}" src="/api/icons/${encodeURIComponent(p)}.png?ship=${ref.type}">`).join('');
    }
    if (panel === 'searchDetail') $('#applyBtn').onclick = () => openApply(ref);
  }

  async function copy(text) {
    try { await navigator.clipboard.writeText(text); $('#jobbar').classList.remove('hide'); $('#jobbar').textContent = '已复制'; setTimeout(() => $('#jobbar').classList.add('hide'), 1200); }
    catch { prompt('手动复制：', text); }
  }

  // ---------------------------------------------------------------- 我的船
  async function openSave() {
    const path = $('#savePath').value.trim();
    $('#saveMsg').textContent = '读取中…';
    try {
      const r = await api('/api/ships' + (path ? '?path=' + encodeURIComponent(path) : ''));
      S.mine = r.ships;
      $('#saveMsg').textContent = `${r.count} 艘${r.warnings?.length ? ' · ' + r.warnings.join('；') : ''}`;
      $('#shipList').innerHTML = r.ships.map((s, i) => `
        <div class="row" data-i="${i}"><span class="idx">${s.slot}</span>
          <span>${esc(s.type)}<br><span class="muted">${esc(s.seed)}${s.name ? ' · ' + esc(s.name) : ''}</span></span>
        </div>`).join('');
      $$('#shipList .row').forEach(el => el.onclick = () => {
        $$('#shipList .row').forEach(x => x.classList.remove('on')); el.classList.add('on');
        S.mineSel = S.mine[+el.dataset.i]; showShip(S.mineSel, 'mineDetail');
        $('#tab-mine .content').innerHTML = detailHtml(S.mineSel);
      });
      if (r.ships.length) $$('#shipList .row')[0].click();
    } catch (e) { $('#saveMsg').textContent = e.message; }
  }
  $('#openSave').onclick = openSave;
  $('#pickDefault').onclick = () => { $('#savePath').value = ''; openSave(); };

  function detailHtml(s) {
    return `<h3>槽位 ${s.slot} · ${esc(s.type)}</h3>
      <div class="kvrow"><span>种子</span><code>${esc(s.seed)}</code></div>
      <div class="kvrow"><span>模型</span><span>${esc((s.model || '').split('/').pop())}</span></div>
      <div class="kvrow"><span>可换外观</span><span>${s.procedural ? '是' : '否（固定模型）'}</span></div>
      <div class="actions"><a class="mini" href="/api/model/${s.type}/${s.seed}.glb" download>下载 glb</a>
      <button class="mini" onclick="navigator.clipboard.writeText('${esc(s.seed)}')">复制种子</button></div>`;
  }

  // 写回对话框（简单实现：同型目标槽 + 当前选中源）
  function openApply(src) {
    const same = S.mine.filter(m => m.type === src.type);
    if (!same.length) { alert(`存档里没有 ${src.type} 的船，无法同型换种子。\n（跨型不可移植：不同船型的部件树不同）`); return; }
    const slot = prompt(`把 ${src.type} ${src.seed} 写到哪个槽位？可选：` +
      same.map(m => `${m.slot}(${m.seed})`).join(' / '), String(same[0].slot));
    if (slot === null) return;
    const ok = confirm(`将把槽位 ${slot} 的外观换成 ${src.seed}\n会先自动备份存档。继续？`);
    if (!ok) return;
    post('/api/saves/apply', { slot: +slot, type: src.type, seed: src.seed, parts: src.parts, confirm: true })
      .then(r => { alert(`写入成功，已通过读回校验。\n备份：${r.backup}`); openSave(); })
      .catch(e => alert('写入失败：' + e.message + '\n（已自动回滚，备份保留）'));
  }

  // ---------------------------------------------------------------- 星球
  $('#centerMode').onchange = () => $('#centerInput').classList.toggle('hide', $('#centerMode').value !== 'glyphs');
  $('#goScan').onclick = async () => {
    $('#sysMsg').textContent = '扫描中…';
    const center = $('#centerMode').value === 'glyphs' ? $('#centerInput').value.trim() : null;
    try {
      const r = await post('/api/system/scan', {
        center, radius: +$('#radius').value, systems: +$('#sysCount').value, limit: +$('#sysLimit').value,
        filters: { biome: $('#biomeSel').value || null, sentinels: $('#sentSel').value || null, dissonant: $('#dissChk').checked },
      });
      pollJob(r.job_id, onScanDone);
    } catch (e) { $('#sysMsg').textContent = e.message; }
  };

  function onScanDone(j) {
    if (j.status === 'failed') { $('#sysMsg').textContent = '扫描失败：' + j.error; return; }
    const rows = j.result || [];
    $('#sysMsg').textContent = `命中 ${rows.length} 条`;
    $('#sysTable').classList.toggle('hide', !rows.length);
    $('#sysTable tbody').innerHTML = rows.map((r, i) => `
      <tr data-i="${i}"><td>${i + 1}</td><td>${r.index}</td><td>${esc(r.biome_name)}</td>
        <td>${esc(r.sentinels)}${r.dissonant ? ' <span class="badge ok">D</span>' : ''}</td>
        <td><code>${esc(r.ua)}</code></td><td><code>${esc(r.glyphs)}</code></td>
        <td><button class="mini" data-glyph="${esc(r.glyphs)}" data-target="${esc(r.coords)}">符文</button></td></tr>`).join('');
    $$('#sysTable button[data-glyph]').forEach(b => b.onclick = () => showGlyphs(b.dataset.glyph, b.dataset.target));
  }

  $('#curSystem').onclick = async () => {
    $('#sysMsg').textContent = '生成中…';
    try {
      const s = await api('/api/system');
      renderSystem(s);
      $('#sysMsg').textContent = `${s.elapsed_ms} ms`;
    } catch (e) { $('#sysMsg').textContent = e.message; }
  };

  function renderSystem(s) {
    const ships = (s.ships || []).slice(0, 40);
    $('#sysInfo').innerHTML = `
      <div><b>${esc(s.ua)}</b> · ${esc(s.coords)} · glyphs <code>${esc(s.glyphs)}</code></div>
      <div class="muted" style="margin-top:4px">
        <span class="kv"><b>星系</b>${esc(s.galaxy_name)}</span>
        <span class="kv"><b>种族</b>${esc(s.race || '—')}</span>
        <span class="kv"><b>行星</b>${s.planets}</span>
        <span class="kv"><b>卫星</b>${s.moons}</span>
        <span class="kv"><b>dissonant</b>${s.dissonant ? '是' : '否'}</span>
        <span class="kv"><b>拦截机</b>${esc(s.interceptor || '—')}</span>
      </div>
      <div style="margin-top:8px"><button class="mini" onclick="(function(){})()" id="sysGlyph">显示本星系符文</button></div>`;
    $('#sysGlyph').onclick = () => showGlyphs(s.glyphs, s.coords + ' · ' + (s.galaxy_name || ''));
    $('#sysDetail').innerHTML = `<h3>本星系船池（${(s.ships || []).length} 条）</h3>` +
      ships.map(sh => `<div class="kvrow"><span>${esc(sh.kind)}</span><code>${esc(sh.seed)}</code></div>`).join('') +
      ((s.planet_list || []).length ? `<h3 style="margin-top:14px">行星</h3>` + s.planet_list.map(p =>
        `<div class="kvrow"><span>#${p.index} ${esc(p.biome_name)}</span><span>${esc(p.sentinels)}</span></div>`).join('') : '');
  }

  // ---------------------------------------------------------------- 符文
  async function showGlyphs(glyphs, target) {
    try {
      const p = await post('/api/glyph-panel', { glyphs, target });
      S.glyphs = p.glyphs;
      $('#glyphImg').src = `/api/glyphs/${p.glyphs}.png`;
      $('#glyphDigits').textContent = p.glyphs;
      $('#glyphTarget').textContent = (target || '') + '　（逐个对照游戏内传送门输入即可）';
      $('#glyphModal').classList.remove('hide');
    } catch (e) { alert('符文生成失败：' + e.message); }
  }
  $('#glyphClose').onclick = () => $('#glyphModal').classList.add('hide');
  $('#glyphCopy').onclick = () => copy(S.glyphs);
  $('#glyphPop').onclick = () => {
    const w = window.open('', 'starforge-glyphs', 'width=760,height=210');
    if (!w) { alert('浏览器拦截了弹窗，请允许后重试'); return; }
    w.document.write(`<title>符文 ${S.glyphs}</title><body style="margin:0;background:#06080d;color:#dfe8ff;font-family:system-ui">
      <img src="/api/glyphs/${S.glyphs}.png" style="width:100%;display:block;image-rendering:pixelated">
      <div style="padding:6px 10px;font:12px ui-monospace,monospace">${S.glyphs}</div></body>`);
    w.document.close();
  };

  // ---------------------------------------------------------------- 设置
  async function loadSettings() {
    const s = await api('/api/settings');
    $('#gameDir').value = s.settings.game_dir || '';
    $('#savesDir').value = s.settings.saves_dir || '';
    $('#gameData').value = s.settings.gamedata_dir || '';
    $('#writeChk').checked = !!s.settings.write_enabled;
    await fillBiomes();
  }
  async function fillBiomes() {
    try {
      const c = await api('/api/capabilities');
      $('#biomeSel').innerHTML = '<option value="">不限</option>' +
        (c.system.biomes || []).map(b => `<option>${b}</option>`).join('');
    } catch { /* 忽略 */ }
  }
  $('#saveSettings').onclick = async () => {
    try {
      await post('/api/settings', {
        game_dir: $('#gameDir').value.trim(), saves_dir: $('#savesDir').value.trim(),
        gamedata_dir: $('#gameData').value.trim(), write_enabled: $('#writeChk').checked,
      });
      $('#setMsg').textContent = '已保存';
      const c = await api('/api/capabilities');
      $('#lvBadge').textContent = c.preview_level === 'L1' ? 'L1 真 3D' : 'L0 部件图';
      if (!$('#shipSel').options.length) await loadCatalog(S.ship);
    } catch (e) { $('#setMsg').textContent = e.message; }
  };
  $('#runDiag').onclick = async () => {
    $('#diagOut').textContent = '自检中…';
    try { $('#diagOut').textContent = JSON.stringify(await api('/api/diagnostics'), null, 1); }
    catch (e) { $('#diagOut').textContent = '失败：' + e.message; }
  };

  boot();
})();
