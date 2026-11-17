/* starforge · 前端（原生 JS；无框架、无网络依赖） */
(() => {
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf = n => (n ?? 0).toLocaleString();

  async function api(path, opts) {
    const r = await fetch(path, opts);
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) throw new Error(j.error?.message || `HTTP ${r.status}`);
    return j;
  }
  const post = (p, body) => api(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

  let toastTimer = null;
  function toast(msg, ms = 2200) {
    const t = $('#toast'); t.textContent = msg; t.classList.remove('hide');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add('hide'), ms);
  }

  const DESKTOP = { ready: false };

  function bindDesktop() {
    DESKTOP.ready = true;
    document.body.classList.add('desktop');
    $$('.desk-only').forEach(b => b.classList.remove('hide'));
    $('#shell').textContent = '桌面窗口';
    $$('[data-pick]').forEach(btn => btn.onclick = async () => {
      const kind = btn.dataset.pick;
      const p = await window.pywebview.api.pick_folder(kind);
      if (!p) return;
      ({ game: () => $('#gameDir'), saves: () => $('#savesDir'), gamedata: () => $('#gameData') }[kind]?.() || (() => null))().value = p;
      toast('已选择：' + p);
      await loadSettings(); await refreshHealth(); await loadShips();
    });
    const pickSave = $('#pickSave');
    if (pickSave) pickSave.onclick = async () => {
      const p = await window.pywebview.api.pick_file('save');
      if (!p) return;
      $('#savePath').value = p;
      openSave();
    };
  }
  window.addEventListener('pywebviewready', bindDesktop);

  const S = {
    ship: 'sentinel', catalog: null, want: new Set(), avoid: new Set(), mode: 'want',
    results: [], mine: [], viewer: null, jobTimer: null, glyphs: '', live: {},
  };

  /* ---------------- 导航 ---------------- */
  $$('.nav').forEach(b => b.onclick = () => {
    $$('.nav').forEach(x => x.classList.toggle('on', x === b));
    $$('.page').forEach(p => p.classList.toggle('on', p.id === 'page-' + b.dataset.tab));
    if (b.dataset.tab === 'mine' && !S.mine.length) openSave();
    if (b.dataset.tab === 'systems' && !$('#sysBadge').dataset.loaded) loadCurrentSystem();
  });

  /* ---------------- 就绪状态 ---------------- */
  function chips(h) {
    const items = [
      { name: '数据层', ok: !!h.shipwright, warn: !h.shipwright, tip: h.shipwright ? '内置/同机可用' : '缺少上游数据层' },
      { name: '部件目录', ok: h.data_ready, tip: h.data_ready ? '可用' : '未找到（可从游戏推导）' },
      { name: '存档', ok: h.saves_ready, tip: h.saves_ready ? h.saves_dir : '未找到' },
      { name: '游戏', ok: h.game_dir, tip: h.game_dir || '未设置（3D 只能部件图）' },
      { name: '写入', ok: h.write_enabled, warn: true, tip: h.write_enabled ? '已开启' : '默认关闭' },
    ];
    $('#chips').innerHTML = items.map(i =>
      `<span class="chip ${i.ok ? 'ok' : (i.warn ? 'warn' : 'bad')}" title="${esc(i.tip)}"><i></i>${i.name}</span>`).join('');
    $('#fixAll').classList.toggle('hide', !!(h.shipwright && h.saves_ready && h.game_dir));
  }

  async function refreshHealth() {
    const h = await api('/api/health');
    $('#ver').textContent = 'v' + h.version;
    $('#ver2').textContent = 'v' + h.version;
    chips(h);
    return h;
  }

  $('#fixAll').onclick = async () => {
    try {
      const a = await api('/api/autodetect');
      await refreshHealth(); await loadSettings();
      toast(a.applied ? '已自动填入路径' : '没找到可自动填入的路径，请到设置页手填');
    } catch (e) { toast('配置失败：' + e.message); }
  };

  /* ---------------- 启动 ---------------- */
  async function boot() {
    try {
      let h = await refreshHealth();
      if (!h.data_ready || !h.saves_ready || !h.game_dir) {
        try {
          const a = await api('/api/autodetect');
          if (a.applied) { h = await refreshHealth(); toast('已自动检测路径'); }
        } catch (e) { /* 忽略 */ }
      }
      await loadSettings();
      try { S.live = await api('/api/live/status'); renderLive(); } catch (e) { /* 忽略 */ }
      await loadShips();
    } catch (e) {
      $('#searchMsg').textContent = '启动失败：' + e.message;
    }
  }

  /* ---------------- 搜索：船型与部件 ---------------- */
  async function loadShips() {
    const cat = await api('/api/catalog');
    S.catalog = cat;
    const ships = Object.keys(cat.ships);
    $('#shipPills').innerHTML = ships.map(s =>
      `<span class="pill ${s === S.ship ? 'on' : ''}" data-ship="${s}">${s}</span>`).join('');
    $$('#shipPills .pill').forEach(el => el.onclick = () => {
      S.ship = el.dataset.ship; S.want.clear(); S.avoid.clear();
      $$('#shipPills .pill').forEach(x => x.classList.toggle('on', x === el));
      renderParts();
    });
    if (!ships.includes(S.ship)) S.ship = ships[0];
    await renderParts();
    if (cat.source === 'game') {
      $('#partCount').textContent = '（来自游戏资源）';
    }
  }

  async function renderParts() {
    let cat;
    try { cat = await api('/api/catalog/' + S.ship); }
    catch (e) { $('#partTree').innerHTML = `<div class="msg">${esc(e.message)}</div>`; return; }
    const q = ($('#partFilter').value || '').toLowerCase();
    const total = cat.groups.reduce((n, g) => n + g.options.length, 0);
    $('#partCount').textContent = `（${nf(total)} 项${cat.source === 'game' ? ' · 游戏推导' : ''}）`;
    $('#partTree').innerHTML = cat.groups.map(g => {
      const opts = g.options.filter(o => !q || o.part.toLowerCase().includes(q));
      if (!opts.length) return '';
      return `<div class="grp"><div class="grptitle">${esc(g.group)}</div><div class="opts">` +
        opts.map(o => {
          const cls = S.want.has(o.part) ? 'want' : S.avoid.has(o.part) ? 'avoid' : '';
          return `<span class="opt ${cls}" data-part="${esc(o.part)}">${esc(o.part.replace(/^_|_$/g, ''))}</span>`;
        }).join('') + '</div></div>';
    }).join('') || '<div class="tiny">没有匹配的部件</div>';
    $$('#partTree .opt').forEach(el => el.onclick = () => {
      const p = el.dataset.part;
      if (S.mode === 'want') { S.want.has(p) ? S.want.delete(p) : (S.want.add(p), S.avoid.delete(p)); }
      else { S.avoid.has(p) ? S.avoid.delete(p) : (S.avoid.add(p), S.want.delete(p)); }
      renderParts(); renderSelected(); scheduleEstimate();
    });
    renderSelected();
  }

  function renderSelected() {
    const all = [...[...S.want].map(p => [p, 'want']), ...[...S.avoid].map(p => [p, 'avoid'])];
    $('#selectedSummary').innerHTML = all.map(([p, m]) =>
      `<span class="sel" title="${m === 'want' ? '想要' : '不要'}">${m === 'want' ? '' : '✕ '}${esc(p.replace(/^_|_$/g, ''))}</span>`).join('')
      || '<span class="tiny">还没选部件</span>';
  }

  $('#partFilter').oninput = () => renderParts();
  $$('#modeSeg button').forEach(b => b.onclick = () => {
    S.mode = b.dataset.mode;
    $$('#modeSeg button').forEach(x => x.classList.toggle('on', x === b));
  });

  let estTimer = null;
  function scheduleEstimate() {
    clearTimeout(estTimer);
    estTimer = setTimeout(async () => {
      if (!S.want.size && !S.avoid.size) { $('#etaInfo').textContent = ''; return; }
      try {
        const q = new URLSearchParams({ ship: S.ship, want: [...S.want].join(','), avoid: [...S.avoid].join(',') });
        const e = await api('/api/search/estimate?' + q);
        $('#etaInfo').textContent = (e.one_in ? `约 1/${nf(e.one_in)} 的种子满足` : '难以估计')
          + (e.estimate_seconds != null ? ` · 预计 ${e.estimate_seconds} 秒` : '');
      } catch { $('#etaInfo').textContent = ''; }
    }, 320);
  }

  /* ---------------- 搜索执行 ---------------- */
  $('#goSearch').onclick = async () => {
    if (!S.want.size && !S.avoid.size) { $('#searchMsg').textContent = '先选至少一个部件（点一下变绿＝想要）'; return; }
    $('#searchMsg').textContent = ''; $('#grid').innerHTML = ''; $('#gridEmpty').classList.add('hide');
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
        $('#jobbar').classList.remove('hide');
        $('#jobbar').textContent = `${j.kind === 'search' ? '搜索' : '扫描'} · ${j.status}` +
          (p.tested != null ? ` · 测试 ${nf(p.tested)}` : '') + (p.found != null ? ` · 命中 ${p.found}` : '') +
          (p.scanned != null ? ` · 已扫 ${p.scanned}` : '');
        if (j.status !== 'running') { clearInterval(S.jobTimer); $('#jobbar').classList.add('hide'); done(j); }
      } catch (e) { clearInterval(S.jobTimer); $('#jobbar').classList.add('hide'); }
    }, 450);
  }

  function onSearchDone(j) {
    if (j.status === 'failed') { $('#searchMsg').textContent = '搜索失败：' + j.error; return; }
    S.results = j.result || [];
    $('#resultInfo').textContent = `${S.results.length} 个结果`;
    if (!S.results.length) {
      $('#grid').innerHTML = ''; $('#gridEmpty').classList.remove('hide');
      $('#gridEmpty').querySelector('p').textContent = '没有命中：放宽条件，或把「搜索预算」调大';
      return;
    }
    $('#grid').innerHTML = S.results.map((r, i) => `
      <div class="card" data-i="${i}">
        <img loading="lazy" src="/api/thumb/${r.type}/${r.seed}.png?size=340" alt="${esc(r.seed)}">
        <div class="cap"><span class="seed">…${r.seed.slice(-8)}</span><span class="badge ok">3D</span></div>
      </div>`).join('');
    $$('#grid .card').forEach(el => el.onclick = () => {
      $$('#grid .card').forEach(x => x.classList.remove('on')); el.classList.add('on');
      showShip(S.results[+el.dataset.i], 'searchDetail', true);
    });
    $$('#grid .card')[0].click();
  }

  /* ---------------- 3D ---------------- */
  function ensureViewer(host) {
    const canvas = host.querySelector('canvas');
    const v = StarforgeViewer.mount(canvas);
    const btn = k => host.querySelector(`[data-v="${k}"]`);
    const mark = sel => ['iso', 'top', 'side'].forEach(k => btn(k) && btn(k).classList.toggle('on', k === sel));
    btn('iso').onclick = () => { v.setView('iso'); mark('iso'); };
    btn('top').onclick = () => { v.setView('top'); mark('top'); };
    btn('side').onclick = () => { v.setView('side'); mark('side'); };
    btn('spin').onclick = () => { const on = !btn('spin').classList.contains('on'); btn('spin').classList.toggle('on', on); v.spin(on); };
    return v;
  }

  async function showShip(ref, panelId, withActions) {
    const host = $('#' + panelId);
    const parts = ref.parts || [];
    const qs = parts.length ? '?parts=' + encodeURIComponent(parts.join(',')) : '';
    if (host._viewer) { try { host._viewer.dispose(); } catch (e) {} host._viewer = null; }
    host.innerHTML = `
      <div class="viewerWrap"><canvas></canvas>
        <div class="viewerbar">
          <span class="vinfo tiny">载入 3D…</span><div class="spacer"></div>
          <button class="btn small on" data-v="iso">等轴</button>
          <button class="btn small" data-v="top">俯视</button>
          <button class="btn small" data-v="side">侧视</button>
          <button class="btn small" data-v="spin">自转</button>
          <a class="btn small" href="/api/model/${ref.type}/${ref.seed}.glb${qs}" download>glb</a>
        </div>
      </div>
      <h3>${esc(ref.type)} · <code>${esc(ref.seed)}</code></h3>
      <div class="actions">
        <button class="btn small" data-a="copy">复制种子</button>
        <button class="btn small" data-a="share">分享码</button>
        ${withActions ? '<button class="btn small primary" data-a="apply">写回存档…</button>' : ''}
        ${S.live.supported ? '<button class="btn small" data-a="live">送进游戏</button>' : ''}
      </div>
      <div class="kvbox"></div>
      <div class="parts"></div>`;
    try {
      const v = ensureViewer(host); host._viewer = v;
      const info = await v.load(`/api/model/${ref.type}/${ref.seed}.glb${qs}`);
      host.querySelector('.vinfo').textContent = `${info.prims} 组网格 · ${(info.bytes / 1e6).toFixed(1)} MB`;
    } catch (e) {
      host.querySelector('.viewerWrap').innerHTML =
        `<img src="/api/thumb/${ref.type}/${ref.seed}.png?size=520${parts.length ? '&parts=' + encodeURIComponent(parts.join(',')) : ''}" style="width:100%;display:block">
         <div class="viewerbar"><span class="tiny">3D 不可用（${esc(e.message)}），已用渲染图代替</span></div>`;
    }
    const kv = async () => {
      let info = {};
      try { info = await api(`/api/preview/${ref.type}/${ref.seed}`); } catch (e) { /* 忽略 */ }
      host.querySelector('.kvbox').innerHTML = [
        ['渲染档位', info.level || '—'], ['顶点', nf(info.verts)], ['三角', nf(info.tris)],
        ['部件数', parts.length], ['来源', ref.source || '—'],
      ].map(([k, v]) => `<div class="kvrow"><span>${k}</span><span>${esc(v)}</span></div>`).join('');
    };
    kv();
    host.querySelector('.parts').innerHTML = parts.map(p =>
      `<img loading="lazy" title="${esc(p)}" src="/api/icons/${encodeURIComponent(p)}.png?ship=${ref.type}"
        onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'ph',textContent:'${esc(p.replace(/^_|_$/g, '').slice(0, 8))}'}))">`
    ).join('');
    const act = a => host.querySelector(`[data-a="${a}"]`);
    act('copy') && (act('copy').onclick = () => { navigator.clipboard.writeText(ref.seed); toast('种子已复制'); });
    act('share') && (act('share').onclick = () => {
      navigator.clipboard.writeText('nsh1:' + btoa([ref.type, ref.seed, parts.join('|')].join(';')));
      toast('分享码已复制');
    });
    act('apply') && (act('apply').onclick = () => openApply(ref));
    act('live') && (act('live').onclick = () => pushLive(ref));
  }

  /* ---------------- 我的船 ---------------- */
  async function openSave() {
    const path = $('#savePath').value.trim();
    $('#saveMsg').textContent = '读取中…';
    try {
      const r = await api('/api/ships' + (path ? '?path=' + encodeURIComponent(path) : ''));
      S.mine = r.ships;
      $('#saveMsg').textContent = '';
      $('#saveHint').textContent = `${r.path} · ${r.count} 艘`;
      $('#mineInfo').textContent = `${r.count} 艘船`;
      $('#shipList').innerHTML = r.ships.map((s, i) => `
        <div class="row-item" data-i="${i}">
          <img loading="lazy" src="/api/thumb/${s.type}/${s.seed}.png?size=120" alt="">
          <div class="meta"><b>${esc(s.name || '(未命名)')}</b>
            <div>${esc(s.type)} · ${esc(s.seed)}</div></div>
        </div>`).join('') || '<div class="tiny">这个存档里没有船</div>';
      $('#mineGrid').innerHTML = S.mine.map((s, i) => `
        <div class="card" data-i="${i}">
          <img loading="lazy" src="/api/thumb/${s.type}/${s.seed}.png?size=340">
          <div class="cap"><span class="seed">${esc(s.type)}</span>
            <span class="badge ${s.procedural ? 'ok' : ''}">${s.procedural ? '可换' : '固定'}</span></div>
        </div>`).join('');
      const pick = i => { showShip(S.mine[i], 'mineDetail', false); };
      $$('#shipList .row-item').forEach(el => el.onclick = () => {
        $$('#shipList .row-item').forEach(x => x.classList.remove('on')); el.classList.add('on'); pick(+el.dataset.i);
      });
      $$('#mineGrid .card').forEach(el => el.onclick = () => pick(+el.dataset.i));
      if (S.mine.length) $$('#shipList .row-item')[0].click();
      if (r.warnings?.length) $('#saveMsg').textContent = r.warnings.join('；');
    } catch (e) {
      $('#saveMsg').textContent = e.message;
      $('#shipList').innerHTML = '<div class="tiny">读取失败。可在设置页确认存档目录，或点右上角「一键配置」。</div>';
    }
  }
  $('#openSave').onclick = openSave;

  function openApply(src) {
    const same = S.mine.filter(m => m.type === src.type);
    if (!same.length) {
      alert(`存档里没有 ${src.type} 的船，无法同型换种子。\n（不同船型的部件树不同，种子不能跨型移植）`);
      return;
    }
    const slot = prompt(`把 ${src.type} ${src.seed} 写到哪个槽？\n可选：` +
      same.map(m => `${m.slot}(${m.seed})`).join(' / '), String(same[0].slot));
    if (slot === null) return;
    if (!confirm(`将把槽位 ${slot} 的外观换成 ${src.seed}\n会先自动备份存档。继续？`)) return;
    post('/api/saves/apply', { slot: +slot, type: src.type, seed: src.seed, parts: src.parts, confirm: true })
      .then(r => { toast('已写入并通过读回校验'); alert(`写入成功。\n备份：${r.backup}`); openSave(); })
      .catch(e => alert('写入失败：' + e.message + '\n（已自动回滚，备份保留）'));
  }

  async function pushLive(ref) {
    if (!S.live.running) { alert('游戏没在运行。先启动游戏并载入存档。'); return; }
    if (!confirm(`把这艘 ${ref.type} 的外观写进游戏内模板槽？\n只改模板里的 8 字节种子，不动你的船。`)) return;
    try {
      const r = await post('/api/live/push', { type: ref.type, seed: ref.seed, confirm: true });
      alert(`已写入模板槽：0x${r.address.toString(16)}`);
    } catch (e) { alert('失败：' + e.message); }
  }

  /* ---------------- 星球 ---------------- */
  const BIOME_COLOR = { Lush: '#57c98a', Frozen: '#7fd3f2', Toxic: '#a8d24a', Scorched: '#f2834a',
    Radioactive: '#c0e04a', Barren: '#b79a6d', Dead: '#8a8f99', Exotic: '#c58bff', Weird: '#ff8bd0',
    Swamp: '#7aa05a', Volcanic: '#e2603f', Desert: '#e0b36a' };

  async function loadCurrentSystem() {
    $('#sysBadge').textContent = '读取当前星系…';
    try {
      const s = await api('/api/system?current=1');
      $('#sysBadge').dataset.loaded = '1';
      const planets = s.planet_list || [];
      $('#sysBadge').innerHTML = `
        <b>${esc(s.ua)}</b><br>
        <span class="kv">坐标 ${esc(s.coords)}</span><span class="kv">glyphs <code>${esc(s.glyphs)}</code></span><br>
        <span class="kv">${esc(s.galaxy_name)}</span><span class="kv">种族 ${esc(s.race || '—')}</span>
        <span class="kv">行星 ${s.planets}</span><span class="kv">${s.dissonant ? 'dissonant ✓' : '不刷拦截机'}</span>
        <div style="margin-top:8px"><button class="btn small" id="sysGlyph">显示本星系符文</button></div>`;
      $('#sysGlyph').onclick = () => showGlyphs(s.glyphs, s.coords);
      $('#planetCards').innerHTML = planets.map(p => {
        const c = BIOME_COLOR[p.biome_name] || '#6aa9ff';
        return `<div class="planet">
          <div class="top"><span class="dot" style="background:${c};color:${c}"></span><b>${esc(p.biome_name)}</b>
            <div class="spacer"></div><span class="tiny">#${p.index}</span></div>
          <div class="tiny">哨兵 ${esc(p.sentinels)}</div>
          <div class="glyph">${esc(s.glyphs)}</div>
          <div class="row"><button class="btn small" data-glyph="${esc(s.glyphs)}">符文</button></div>
        </div>`;
      }).join('') || '<div class="tiny">这个星系没有行星数据</div>';
      $$('#planetCards [data-glyph]').forEach(b => b.onclick = () => showGlyphs(b.dataset.glyph, s.coords));
      const ships = s.ships || [];
      $('#scanInfo').textContent = `本星系船池 ${ships.length} 条 · 生成 ${s.elapsed_ms} ms`;
      $('#sysDetail').innerHTML = `<h3>本星系船池</h3>` + ships.map(sh =>
        `<div class="kvrow"><span>${esc(sh.kind)}</span><code>${esc(sh.seed)}</code></div>`).join('') +
        (s.interceptor ? `<div class="kvrow"><span>拦截机（本星系）</span><code>${esc(s.interceptor)}</code></div>` : '');
    } catch (e) {
      $('#sysBadge').innerHTML = `<span class="msg">${esc(e.message)}</span>`;
    }
  }
  $('#reloadSystem').onclick = loadCurrentSystem;

  $('#goScan').onclick = async () => {
    $('#sysMsg').textContent = '扫描中…';
    try {
      const r = await post('/api/system/scan', {
        radius: +$('#radius').value, systems: +$('#sysCount').value, limit: 40,
        filters: { biome: $('#biomeSel').value || null, sentinels: $('#sentSel').value || null,
                   dissonant: $('#dissChk').checked },
      });
      pollJob(r.job_id, j => {
        if (j.status === 'failed') { $('#sysMsg').textContent = '扫描失败：' + j.error; return; }
        const rows = j.result || [];
        $('#sysMsg').textContent = `命中 ${rows.length} 条`;
        $('#scanInfo').textContent = `扫描结果 ${rows.length} 条`;
        $('#scanTable').innerHTML = rows.length ? `<table><thead><tr><th>行星</th><th>生物群系</th>
          <th>哨兵</th><th>glyphs</th><th></th></tr></thead><tbody>` +
          rows.map(r => `<tr><td>#${r.index}</td><td>${esc(r.biome_name)}</td>
            <td>${esc(r.sentinels)}${r.dissonant ? ' · D' : ''}</td>
            <td><code>${esc(r.glyphs)}</code></td>
            <td><button class="btn small" data-glyph="${esc(r.glyphs)}">符文</button></td></tr>`).join('') +
          '</tbody></table>' : '<div class="tiny">没有符合条件的结果，放宽条件或加大扫描数</div>';
        $$('#scanTable [data-glyph]').forEach(b => b.onclick = () => showGlyphs(b.dataset.glyph, ''));
      });
    } catch (e) { $('#sysMsg').textContent = e.message; }
  };

  /* ---------------- 符文 ---------------- */
  async function showGlyphs(glyphs, target) {
    try {
      const p = await post('/api/glyph-panel', { glyphs, target });
      S.glyphs = p.glyphs;
      $('#glyphImg').src = `/api/glyphs/${p.glyphs}.png`;
      $('#glyphDigits').textContent = p.glyphs;
      $('#glyphTarget').textContent = (target || '') + '　逐个对照游戏内传送门输入';
      $('#glyphModal').classList.remove('hide');
    } catch (e) { toast('符文生成失败：' + e.message); }
  }
  $('#glyphClose').onclick = () => $('#glyphModal').classList.add('hide');
  $('#glyphCopy').onclick = () => { navigator.clipboard.writeText(S.glyphs); toast('已复制'); };
  $('#glyphPop').onclick = () => {
    const w = window.open('', 'sf-glyphs', 'width=880,height=240');
    if (!w) { toast('浏览器拦截了弹窗'); return; }
    w.document.write(`<title>符文 ${S.glyphs}</title><body style="margin:0;background:#06080d">
      <img src="/api/glyphs/${S.glyphs}.png" style="width:100%;display:block;image-rendering:pixelated">
      <div style="padding:6px 10px;font:12px ui-monospace,monospace;color:#dbe9ff">${S.glyphs}</div></body>`);
    w.document.close();
  };

  /* ---------------- 设置 ---------------- */
  async function loadSettings() {
    const s = await api('/api/settings');
    $('#gameDir').value = s.settings.game_dir || '';
    $('#savesDir').value = s.settings.saves_dir || '';
    $('#gameData').value = s.settings.gamedata_dir || '';
    $('#writeChk').checked = !!s.settings.write_enabled;
    try {
      const c = await api('/api/capabilities');
      $('#biomeSel').innerHTML = '<option value="">不限</option>' +
        (c.system.biomes || []).map(b => `<option>${b}</option>`).join('');
    } catch { /* 忽略 */ }
  }

  function renderLive() {
    const el = $('#liveStatus');
    if (!el) return;
    if (!S.live.supported) { el.textContent = '不支持（仅 Windows）'; return; }
    el.textContent = S.live.running ? `可用 · 已连上 NMS.exe（PID ${S.live.pid}）` : '可用 · 游戏未运行';
  }

  $('#autoDetect').onclick = async () => {
    try {
      const a = await api('/api/autodetect');
      await loadSettings(); await refreshHealth(); await loadShips();
      toast(a.applied ? '路径已自动填入' : '没找到可自动填入的路径');
    } catch (e) { $('#setMsg').textContent = '检测失败：' + e.message; }
  };

  $('#saveSettings').onclick = async () => {
    try {
      await post('/api/settings', {
        game_dir: $('#gameDir').value.trim(), saves_dir: $('#savesDir').value.trim(),
        gamedata_dir: $('#gameData').value.trim(), write_enabled: $('#writeChk').checked,
      });
      $('#setMsg').textContent = '已保存';
      await refreshHealth(); await loadShips();
    } catch (e) { $('#setMsg').textContent = e.message; }
  };

  $('#runDiag').onclick = async () => {
    $('#diagOut').textContent = '自检中…';
    try { $('#diagOut').textContent = JSON.stringify(await api('/api/diagnostics'), null, 1); }
    catch (e) { $('#diagOut').textContent = '失败：' + e.message; }
  };

  $('#probeLive').onclick = async () => {
    $('#diagOut').textContent = '只读探测（不写内存）…';
    try {
      const r = await api('/api/live/probe');
      const lines = r.types.map(t => {
        const tag = t.source === 'super-ship-hunter' ? '[SSH]' : '[自身]';
        const c = t.candidates.map(x => `${x.addr}(${x.score})`).join(' ') || '—';
        return `${tag} ${t.type.padEnd(9)} 槽位${t.slots}  ${t.chosen ? '✓ ' + t.chosen : '✗'}  ${t.reason}\n     候选: ${c}`;
      });
      $('#diagOut').textContent = lines.join('\n');
    } catch (e) { $('#diagOut').textContent = '探测失败：' + e.message; }
  };

  $('#genMod').onclick = async () => {
    const dest = prompt('生成到哪个目录？（留空 = 缓存目录）', '');
    try {
      const r = await post('/api/live/template-mod', dest ? { dest } : {});
      $('#setMsg').textContent = '已生成：' + r.path;
    } catch (e) { $('#setMsg').textContent = e.message; }
  };

  boot();
})();
