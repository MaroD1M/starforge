/* starforge · 前端（原生 JS；无框架、无网络依赖） */
(() => {
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf = n => (n ?? 0).toLocaleString();
  const favKey = r => `${r.type}:${r.seed}`;
  function saveFavs() { localStorage.setItem('sf.favs', JSON.stringify(S.favs)); }
  function isFav(r) { return S.favs.some(f => favKey(f) === favKey(r)); }
  function toggleFav(r) {
    const k = favKey(r);
    if (isFav(r)) S.favs = S.favs.filter(f => favKey(f) !== k);
    else S.favs.push({ type: r.type, seed: r.seed, parts: r.parts || null, name: r.name || '' });
    saveFavs();
    toast(isFav(r) ? '已收藏' : '已取消收藏');
    renderGrid();
  }

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

  function dialog({ title, body, okText = '确定', cancelText = '取消', onOk }) {
    $('#dlgTitle').textContent = title;
    $('#dlgBody').innerHTML = body;
    $('#dlgOk').textContent = okText;
    $('#dlgCancel').textContent = cancelText;
    $('#dlg').classList.remove('hide');
    const close = () => { $('#dlg').classList.add('hide'); $('#dlgOk').onclick = null; };
    $('#dlgClose').onclick = close;
    $('#dlgCancel').onclick = close;
    $('#dlgOk').onclick = async () => {
      try {
        const r = onOk ? await onOk() : true;
        if (r !== false) close();
      } catch (e) { toast(String(e.message || e)); }
    };
    return close;
  }

  const S = {
    ship: 'sentinel', catalog: null, want: new Set(), avoid: new Set(), mode: 'want',
    results: [], mine: [], viewer: null, jobTimer: null, glyphs: '', live: {},
    favs: JSON.parse(localStorage.getItem('sf.favs') || '[]'), favMode: false,
  };

  /* ---------------- 导航 ---------------- */
  function goto(tab, remember = true) {
    const b = document.querySelector(`.nav[data-tab="${tab}"]`);
    if (!b) return;
    $$('.nav').forEach(x => x.classList.toggle('on', x === b));
    $$('.page').forEach(p => p.classList.toggle('on', p.id === 'page-' + tab));
    if (remember) location.hash = tab;
    if (tab === 'mine' && !S.mine.length) openSave();
    if (tab === 'systems' && !$('#sysBadge').dataset.loaded) loadCurrentSystem();
  }
  $$('.nav').forEach(b => b.onclick = () => goto(b.dataset.tab));
  addEventListener('hashchange', () => goto((location.hash || '#search').slice(1), false));

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
      try {                                                  // 恢复上次条件
        const q = JSON.parse(localStorage.getItem('sf.query') || 'null');
        if (q?.ship) { S.ship = q.ship; S.want = new Set(q.want || []); S.avoid = new Set(q.avoid || []); }
      } catch (e) { /* 忽略 */ }
      if (!h.data_ready || !h.saves_ready || !h.game_dir) {
        try {
          const a = await api('/api/autodetect');
          if (a.applied) { h = await refreshHealth(); toast('已自动检测路径'); }
        } catch (e) { /* 忽略 */ }
      }
      await loadSettings();
      try { S.live = await api('/api/live/status'); renderLive(); } catch (e) { /* 忽略 */ }
      try {
        const d = await api('/api/desktop');
        if (!DESKTOP.ready) {
          $('#shell').textContent = d.available ? '桌面窗口（可用）' : '浏览器模式';
          if (!d.available && d.reason) $('#shell').title = d.reason;
        }
      } catch (e) { /* 忽略 */ }
      await loadShips();
      maybeOnboard(h);
      const tab = (location.hash || '').slice(1);
      if (['search', 'mine', 'systems', 'settings'].includes(tab)) goto(tab, false);
      // URL 参数直达某个状态：?demo=search / ?glyph=1043FEE69929 / ?demo=mine
      const qs = new URLSearchParams(location.search);
      if (qs.get('demo') === 'search') setTimeout(runDemo, 300);
      if (qs.get('demo') === 'mine') setTimeout(openSave, 300);
      if (qs.get('glyph')) setTimeout(() => {
        goto('systems', false);
        showGlyphs(qs.get('glyph'), qs.get('target') || '');
      }, 600);
    } catch (e) {
      $('#searchMsg').textContent = '启动失败：' + e.message;
    }
  }

  function maybeOnboard(h) {
    const need = !h.saves_ready || !h.data_ready || !h.game_dir;
    $('#onboard').classList.toggle('hide', !need);
    if (!need) return;                          // 自动检测已搞定 → 不打扰
    // 只有"没法用"时才强制弹向导；缺一项（例如只缺存档）就用横幅提示，别挡结果
    const blocked = !h.data_ready || (!h.game_dir && !h.saves_ready);
    if (!blocked) return;
    if (!sessionStorage.getItem('sf.wizard.shown')) {
      sessionStorage.setItem('sf.wizard.shown', '1');
      openWizard();
    }
  }

  // 一步式配置向导：自动检测 → 确认 → 保存
  async function openWizard() {
    const browse = async (kind, inputId) => {
      if (!DESKTOP.ready) { toast('浏览器模式下请直接粘贴路径'); return; }
      const p = await window.pywebview.api.pick_folder(kind);
      if (p && inputId) { $(inputId).value = p; }
    };
    const rowHtml = (label, id, kind, placeholder) => `
      <div class="field"><label>${label}</label>
        <div class="row">
          <input id="${id}" class="input" placeholder="${placeholder}">
          <button class="btn small" data-browse="${kind}" data-target="#${id}">浏览…</button>
        </div>
        <div class="tiny" data-check="${id}"></div>
      </div>`;
    dialog({
      title: '首次使用 · 三步配置',
      body: `
        <p>点「自动检测」通常就够用了；也可以手动选择。</p>
        <div class="row" style="margin:8px 0 4px">
          <button class="btn small primary" id="wizDetect">自动检测</button>
          <span class="tiny" id="wizHint">正在检测…</span>
        </div>
        ${rowHtml('游戏目录（含 Binaries/NMS.exe）', 'wizGame', 'game', '例如 D:\\Program Files (x86)\\Steam\\steamapps\\common\\No Man\'s Sky')}
        ${rowHtml('存档目录（含 save.hg）', 'wizSaves', 'saves', '例如 C:\\Users\\你\\AppData\\Roaming\\HelloGames\\NMS\\st_xxx')}
        <div class="tiny">数据目录可选：没有 Gagarin 数据时会从游戏资源推导部件树。</div>`,
      okText: '保存并检查', cancelText: '稍后',
      onOk: async () => {
        await post('/api/settings', {
          game_dir: $('#wizGame').value.trim(),
          saves_dir: $('#wizSaves').value.trim(),
        });
        const h = await refreshHealth();
        await loadSettings(); await loadShips();
        const bad = [];
        if (!h.game_dir) bad.push('游戏目录');
        if (!h.saves_ready) bad.push('存档目录');
        toast(bad.length ? `仍缺少：${bad.join('、')}` : '配置完成');
        return true;
      },
    });
    const setVals = s => {
      if (s.settings.game_dir) $('#wizGame').value = s.settings.game_dir;
      if (s.settings.saves_dir) $('#wizSaves').value = s.settings.saves_dir;
    };
    try { setVals(await api('/api/settings')); } catch (e) { /* 忽略 */ }
    $$('#dlgBody [data-browse]').forEach(b => b.onclick = () => browse(b.dataset.browse, b.dataset.target));
    $('#wizDetect').onclick = async () => {
      $('#wizHint').textContent = '检测中…';
      try {
        const a = await api('/api/autodetect');
        const s = await api('/api/settings');
        setVals(s);
        $('#wizHint').textContent = a.applied ? '已填入检测到的路径' : '没找到，请手动选择';
      } catch (e) { $('#wizHint').textContent = '检测失败：' + e.message; }
    };
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
    S.groupsOf = {};
    (cat.groups || []).forEach(g => g.options.forEach(o => { S.groupsOf[o.part] = g.group; }));
    S.labels = {};
    (cat.groups || []).forEach(g => {
      const seen = {};
      g.options.forEach(o => {
        const base = o.label || o.part;
        seen[base] = (seen[base] || 0) + 1;
        S.labels[o.part] = seen[base] > 1 ? `${base} #${seen[base]}` : base;
      });
    });
    const total = cat.groups.reduce((n, g) => n + g.options.length, 0);
    $('#partCount').textContent = `（${nf(total)} 项${cat.source === 'game' ? ' · 游戏推导' : ''}）`;
    $('#partTree').innerHTML = cat.groups.map(g => {
      const opts = g.options.filter(o => !q || o.part.toLowerCase().includes(q));
      if (!opts.length) return '';
      return `<div class="grp"><div class="grptitle" title="${esc(g.group)}">${esc(g.label || g.group)}<span class="raw">${esc(g.group.replace(/^_|_$/g, ''))}</span></div><div class="opts">` +
        opts.map(o => {
          const cls = S.want.has(o.part) ? 'want' : S.avoid.has(o.part) ? 'avoid' : '';
          return `<span class="opt ${cls}" data-part="${esc(o.part)}" data-label="${esc(o.label || o.part)}"
                   title="${esc(o.part)}">${esc(o.label || o.part.replace(/^_|_$/g, ''))}</span>`;
        }).join('') + '</div></div>';
    }).join('') || '<div class="tiny">没有匹配的部件</div>';
    $$('#partTree .opt').forEach(el => el.onclick = () => {
      const p = el.dataset.part;
      if (S.mode === 'want') {
        if (S.want.has(p)) { S.want.delete(p); }
        else {
          // 同一个插槽组只能出一个部件：自动替换，避免搜不到东西
          const g = S.groupsOf?.[p];
          const clash = [...S.want].filter(q => g && S.groupsOf?.[q] === g);
          clash.forEach(q => S.want.delete(q));
          S.want.add(p); S.avoid.delete(p);
          if (clash.length) toast(`同组互斥：已用「${S.labels?.[p] || p}」替换「${S.labels?.[clash[0]] || clash[0]}」`);
        }
      } else {
        if (S.avoid.has(p)) { S.avoid.delete(p); }
        else { S.avoid.add(p); S.want.delete(p); }
      }
      renderParts(); renderSelected(); scheduleEstimate();
    });
    renderSelected();
  }

  function renderSelected() {
    const all = [...[...S.want].map(p => [p, 'want']), ...[...S.avoid].map(p => [p, 'avoid'])];
    const labelOf = p => (S.labels && S.labels[p]) || p.replace(/^_|_$/g, '');
    $('#selectedSummary').innerHTML = all.map(([p, m]) =>
      `<span class="sel" title="${m === 'want' ? '想要' : '不要'}：${esc(p)}">${m === 'want' ? '' : '✕ '}${esc(labelOf(p))}</span>`).join('')
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
  async function runDemo() {
    try {
      const cat = await api('/api/catalog/' + S.ship);
      const pool = cat.groups.flatMap(g => g.options.map(o => o.part));
      const picks = [pool[0], pool[Math.floor(pool.length / 3)], pool[Math.floor(pool.length / 2)]];
      const pick = [...new Set(picks)].filter(Boolean).slice(0, 2);
      S.want = new Set(pick);
      await renderParts();
      $('#partFilter').value = '';
      $('#goSearch').click();
    } catch (e) { toast('示例失败：' + e.message); }
  }
  $('#demoBtn').onclick = runDemo;

  // 导入分享码：nsh1:<base64(type;seed;parts)>
  $('#importBtn').onclick = () => {
    dialog({
      title: '导入分享码', okText: '载入',
      body: `<p>粘贴别人发来的 <code>nsh1:…</code> 分享码。</p>
             <div class="field" style="margin-top:10px">
               <input id="shareInput" class="input" placeholder="nsh1:...">
             </div>`,
      onOk: async () => {
        const raw = ($('#shareInput')?.value || '').trim();
        if (!raw) return false;
        try {
          const payload = raw.startsWith('nsh1:') ? raw.slice(5) : raw;
          const [type, seed, partsStr] = atob(payload).split(';');
          if (!type || !seed) throw new Error('格式不对');
          S.ship = type;
          $$('#shipPills .pill').forEach(x => x.classList.toggle('on', x.dataset.ship === type));
          await renderParts();
          const ref = { type, seed, parts: (partsStr || '').split('|').filter(Boolean), source: 'share' };
          goto('search');
          await showShip(ref, 'searchDetail', true);
          toast('已载入分享码');
          return true;
        } catch (e) { toast('分享码无效：' + e.message); return false; }
      },
    });
  };
  const obFix = $('#obFix'); if (obFix) obFix.onclick = () => $('#fixAll').click();
  const obDemo = $('#obDemo'); if (obDemo) obDemo.onclick = runDemo;

  // 快捷键
  document.addEventListener('keydown', e => {
    const tag = (e.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'select' || tag === 'textarea';
    if (e.key === 'Escape') { $('#glyphModal').classList.add('hide'); return; }
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); $('#goSearch').click(); return; }
    if (typing) return;
    if (e.key === 'j' || e.key === 'k') {                       // 上下切换结果
      const cards = $$('#grid .card'); if (!cards.length) return;
      const cur = cards.findIndex(c => c.classList.contains('on'));
      const next = Math.max(0, Math.min(cards.length - 1, cur + (e.key === 'j' ? 1 : -1)));
      cards[next].click(); cards[next].scrollIntoView({ block: 'nearest' });
    }
    if ('1234'.includes(e.key)) {                              // 视角
      const v = ['iso', 'top', 'side', 'spin'][+e.key - 1];
      const b = document.querySelector(`#searchDetail [data-v="${v}"], #mineDetail [data-v="${v}"]`);
      if (b) b.click();
    }
  });

  $('#goSearch').onclick = async () => {
    if (!S.want.size && !S.avoid.size) { $('#searchMsg').textContent = '先选至少一个部件（点一下变绿＝想要）'; return; }
    $('#searchMsg').textContent = ''; $('#grid').innerHTML = ''; $('#gridEmpty').classList.add('hide');
    $('#resultInfo').textContent = '搜索中…';
    try {
      localStorage.setItem('sf.query', JSON.stringify({ ship: S.ship, want: [...S.want], avoid: [...S.avoid] }));
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

  function currentGridItems() {
    return S.favMode ? S.favs : S.results;
  }

  function renderGrid() {
    const items = currentGridItems();
    $('#resultInfo').textContent = S.favMode ? `收藏 ${items.length} 个` : `${S.results.length} 个结果`;
    $('#exportResults').classList.toggle('hide', !items.length);
    if (!items.length) {
      $('#grid').innerHTML = '';
      $('#gridEmpty').classList.remove('hide');
      $('#gridEmpty').querySelector('p').innerHTML = S.favMode
        ? '还没有收藏。搜到喜欢的船，点卡片右上角 ★'
        : '没有命中：放宽条件，或把「搜索预算」调大';
      return;
    }
    $('#gridEmpty').classList.add('hide');
    $('#grid').innerHTML = items.map((r, i) => `
      <div class="card" data-i="${i}">
        <img loading="lazy" src="/api/thumb/${r.type}/${r.seed}.png?size=340" alt="${esc(r.seed)}"
             onerror="this.style.visibility='hidden'">
        <span class="star ${isFav(r) ? 'on' : ''}" data-star="${i}" title="收藏">★</span>
        <div class="cap"><span class="seed">…${r.seed.slice(-8)}</span><span class="badge ok">3D</span></div>
      </div>`).join('');
    $$('#grid .card').forEach(el => el.onclick = e => {
      if (e.target.dataset.star !== undefined) { toggleFav(items[+e.target.dataset.star]); return; }
      $$('#grid .card').forEach(x => x.classList.remove('on')); el.classList.add('on');
      showShip(items[+el.dataset.i], 'searchDetail', true);
    });
    if (!S.favMode) $$('#grid .card')[0]?.click();
  }

  function onSearchDone(j) {
    if (j.status === 'failed') { $('#searchMsg').textContent = '搜索失败：' + j.error; return; }
    S.results = j.result || [];
    $('#resultInfo').textContent = `${S.results.length} 个结果`;
    $('#exportResults').classList.toggle('hide', !S.results.length);
    if (!S.results.length) {
      $('#grid').innerHTML = ''; $('#gridEmpty').classList.remove('hide');
      $('#gridEmpty').querySelector('p').textContent = '没有命中：放宽条件，或把「搜索预算」调大';
      return;
    }
    renderGrid();
  }

  function statsLine(st) {
    if (!st || !Object.keys(st).length) return '';
    const nm = { damage: '伤害', shield: '护盾', hyperdrive: '超光速', agility: '机动' };
    return Object.entries(st).map(([k, v]) => `${nm[k] || k} ${v}`).join(' · ');
  }

  function statsBars(st) {
    if (!st || !Object.keys(st).length) return '';
    const nm = { damage: '伤害', shield: '护盾', hyperdrive: '超光速', agility: '机动' };
    const max = { damage: 100, shield: 100, hyperdrive: 100, agility: 60 };
    return '<div class="stats">' + Object.entries(st).map(([k, v]) => {
      const pct = Math.max(4, Math.min(100, (v / (max[k] || 100)) * 100));
      return `<div class="stat"><span>${nm[k] || k}</span>
        <div class="bar"><i style="width:${pct}%"></i></div><b>${v}</b></div>`;
    }).join('') + '</div>';
  }

  async function exportShips(items, name) {
    if (!items.length) { toast('没有可导出的船'); return; }
    toast('正在打包 glb + png…', 60000);
    try {
      const r = await fetch('/api/export', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items, name, glb: true, png: true, size: 640 }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error?.message || r.status);
      const n = r.headers.get('X-Export-Count') || '0';
      const blob = await r.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = name + '.zip'; a.click();
      URL.revokeObjectURL(a.href);
      toast(`已导出 ${n} 艘（含 glb 与 png）`);
    } catch (e) { toast('导出失败：' + e.message); }
  }
  function exportFavList() {
    if (!S.favs.length) { toast('收藏夹是空的'); return; }
    const payload = { format: 'starforge-favs', version: 1, items: S.favs };
    const blob = new Blob([JSON.stringify(payload, null, 1)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'starforge-收藏.json'; a.click();
    URL.revokeObjectURL(a.href);
    toast(`已导出 ${S.favs.length} 个收藏`);
  }

  function importFavList() {
    dialog({
      title: '导入收藏清单', okText: '导入',
      body: `<p>粘贴别人分享的收藏清单（.json 内容），或每行一个 <code>nsh1:…</code> 分享码。</p>
             <div class="field" style="margin-top:10px">
               <textarea id="favInput" class="input" rows="6" placeholder='{"format":"starforge-favs","items":[…]}"'></textarea>
             </div>`,
      onOk: async () => {
        const raw = ($('#favInput')?.value || '').trim();
        if (!raw) return false;
        let items = [];
        try {
          const j = JSON.parse(raw);
          items = Array.isArray(j) ? j : (j.items || []);
        } catch (e) {
          items = raw.split(/\s+/).filter(Boolean).map(code => {
            const payload = code.startsWith('nsh1:') ? code.slice(5) : code;
            const [type, seed, partsStr] = atob(payload).split(';');
            return { type, seed, parts: (partsStr || '').split('|').filter(Boolean) };
          }).filter(x => x.type && x.seed);
        }
        const before = S.favs.length;
        items.forEach(it => {
          if (!it?.type || !it?.seed) return;
          if (!S.favs.some(f => favKey(f) === favKey(it))) S.favs.push(it);
        });
        saveFavs(); renderGrid();
        toast(`导入完成：新增 ${S.favs.length - before} 个`);
        return true;
      },
    });
  }

  $('#favToggle').onclick = () => {
    S.favMode = !S.favMode;
    $('#favToggle').classList.toggle('on', S.favMode);
    $('#favExport').classList.toggle('hide', !S.favMode);
    $('#favImport').classList.toggle('hide', !S.favMode);
    renderGrid();
  };
  $('#exportResults').onclick = () => exportShips(currentGridItems(), S.favMode ? 'starforge-favs' : 'starforge-search');
  $('#favExport').onclick = exportFavList;
  $('#favImport').onclick = importFavList;
  $('#exportMine').onclick = () => exportShips(S.mine, 'starforge-myships');

  window.addEventListener('sf-viewer-empty', e => {
    const host = $('#searchDetail canvas')?.closest('.pane') || $('#mineDetail canvas')?.closest('.pane') || $('#sysDetail');
    const ref = S.selected;
    if (!host || !ref) return;
    const wrap = host.querySelector('.viewerWrap');
    if (!wrap || wrap.dataset.fellback) return;
    wrap.dataset.fellback = '1';
    const parts = ref.parts || [];
    wrap.innerHTML = `<img src="/api/thumb/${ref.type}/${ref.seed}.png?size=520${parts.length ? '&parts=' + encodeURIComponent(parts.join(',')) : ''}" style="width:100%;display:block">
      <div class="viewerbar"><span class="tiny">WebGL 未渲染出内容（${esc(e.detail || '')}），已用服务端渲染图代替</span></div>`;
  });

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
      const rows = [
        ['渲染档位', info.level || '—'], ['顶点', nf(info.verts)], ['三角', nf(info.tris)],
        ['部件数', parts.length], ['来源', ref.source || '—'],
      ];
      if (ref.ship_class) rows.unshift(['等级', ref.ship_class]);
      host.querySelector('.kvbox').innerHTML =
        rows.map(([k, v]) => `<div class="kvrow"><span>${k}</span><span>${esc(v)}</span></div>`).join('')
        + statsBars(ref.stats);
    };
    kv();
    const partName = p => (S.labels && S.labels[p]) || p.replace(/^_|_$/g, '');
    host.querySelector('.parts').innerHTML = parts.map(p => {
      const nm = partName(p);
      return `<img loading="lazy" title="${esc(nm)}（${esc(p)}）"
        data-fallback="0"
        src="/api/part-thumb/${ref.type}/${encodeURIComponent(p)}.png?size=96"
        onerror="if(this.dataset.fallback==='0'){this.dataset.fallback='1';this.src='/api/icons/${encodeURIComponent(p)}.png?ship=${ref.type}';}else{this.replaceWith(Object.assign(document.createElement('span'),{className:'ph',title:${JSON.stringify(p)},textContent:${JSON.stringify(nm.slice(0, 6))}}))}">`;
    }).join('');
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
      $('#saveMsg').textContent = r.warnings?.length ? r.warnings.join('；') : '';
      $('#saveHint').textContent = `${r.path} · ${r.count} 艘`;
      $('#exportMine').classList.toggle('hide', !r.count);
      $('#shipList').innerHTML = r.ships.map((s, i) => `
        <div class="row-item" data-i="${i}">
          <img loading="lazy" src="/api/thumb/${s.type}/${s.seed}.png?size=120" alt=""
               onerror="this.style.visibility='hidden'">
          <div class="meta"><b>${esc(s.name || '(未命名)')}</b>
            <div>${esc(s.type_label || s.type)}${s.ship_class ? ' · ' + esc(s.ship_class) + ' 级' : ''}${s.can_preview ? '' : ' · 固定模型'}</div>
            <div>${statsLine(s.stats)}</div></div>
        </div>`).join('') || '<div class="tiny">这个存档里没有船</div>';
      $$('#shipList .row-item').forEach(el => el.onclick = () => {
        $$('#shipList .row-item').forEach(x => x.classList.remove('on'));
        el.classList.add('on');
        showShip(S.mine[+el.dataset.i], 'mineDetail', false);
      });
      renderMine();
      if (S.mine.length) $$('#shipList .row-item')[0].click();
    } catch (e) {
      $('#saveMsg').textContent = e.message;
      $('#shipList').innerHTML = '<div class="tiny">读取失败。可在设置页确认存档目录，或点右上角「一键配置」。</div>';
      $('#mineGrid').innerHTML = '';
    }
  }

  function renderMine() {
    const only = $('#onlyPreview')?.checked;
    const rows = only ? S.mine.filter(s => s.can_preview) : S.mine;
    $('#mineInfo').textContent = `${rows.length} / ${S.mine.length} 艘`;
    $('#mineGrid').innerHTML = rows.map(s => `
        <div class="card" data-slot="${s.slot}">
          <img loading="lazy" src="/api/thumb/${s.type}/${s.seed}.png?size=340" alt=""
               onerror="this.style.visibility='hidden'">
          <span class="star ${isFav(s) ? 'on' : ''}" data-star="${s.slot}" title="收藏">★</span>
          <div class="cap"><span class="seed">${esc(s.type_label || s.type)}</span>
            <span class="badge ${s.can_preview ? 'ok' : ''}">${s.can_preview ? '可预览' : '固定模型'}</span></div>
        </div>`).join('') || '<div class="tiny">没有符合条件的船</div>';
    $$('#mineGrid .card').forEach(el => el.onclick = e => {
      const s = rows.find(x => String(x.slot) === el.dataset.slot);
      if (e.target.dataset.star !== undefined) { toggleFav(s); return; }
      showShip(s, 'mineDetail', false);
    });
  }
  document.addEventListener('change', e => { if (e.target.id === 'onlyPreview') renderMine(); });
  $('#openSave').onclick = openSave;

  function openApply(src) {
    if (!S.mine.length) { toast('先在「我的船」里读取存档'); return; }
    const same = S.mine.filter(m => m.type === src.type);
    if (!same.length) {
      dialog({
        title: '无法写回',
        body: `<p>存档里没有 <code>${esc(src.type)}</code> 的船。</p>
               <div class="warnbox">不同船型的部件树不同，<b>种子不能跨型移植</b>。<br>
               想要这个外观：先买/找一艘 ${esc(src.type)}，或改用「按部件搜索」找一艘相近的。</div>`,
        okText: '知道了', cancelText: '关闭', onOk: () => true,
      });
      return;
    }
    let slot = same[0].slot;
    const body = `
      <p>把 <code>${esc(src.seed)}</code> 的外观写到哪一艘？</p>
      <div class="opt-list">${same.map(m => `
        <label class="pick ${m.slot === slot ? 'on' : ''}" data-slot="${m.slot}">
          <input type="radio" name="slot" ${m.slot === slot ? 'checked' : ''}>
          <span>槽位 ${m.slot} · ${esc(m.type)}</span>
          <span class="spacer"></span><code>${esc(m.seed)}</code>
        </label>`).join('')}</div>
      <div class="warnbox">写入前会自动备份存档；写完会重新解码核对，不符即自动回滚。</div>`;
    dialog({
      title: '写回存档', body, okText: '写入并校验',
      onOk: async () => {
        const r = await post('/api/saves/apply',
          { slot, type: src.type, seed: src.seed, parts: src.parts, confirm: true });
        toast('已写入并通过读回校验');
        dialog({
          title: '写入成功',
          body: `<p>槽位 ${r.slot} 的外观已更新。</p>
                 <p class="tiny">备份：<code>${esc(r.backup)}</code></p>
                 <p class="tiny">回到游戏重新载入存档即可看到。</p>`,
          okText: '好', cancelText: '关闭', onOk: () => true,
        });
        openSave();
        return true;
      },
    });
    $$('#dlgBody label.pick').forEach(el => el.onclick = () => {
      slot = +el.dataset.slot;
      $$('#dlgBody label.pick').forEach(x => x.classList.toggle('on', x === el));
    });
  }

  function pushLive(ref) {
    if (!S.live.running) {
      dialog({ title: '游戏未运行', okText: '知道了', cancelText: '关闭',
        body: '<p>实时通道要求游戏已启动并载入存档。</p>',
        onOk: () => true });
      return;
    }
    dialog({
      title: '送进游戏', okText: '写入模板槽',
      body: `<p>把 <code>${esc(ref.seed)}</code> 写进 <code>${esc(ref.type)}</code> 的模板槽。</p>
             <div class="warnbox">只改写模板里的 8 字节种子，<b>不会动你的船和存档</b>。
             写入后立刻回读校验；若游戏版本不匹配会拒绝写入。</div>`,
      onOk: async () => {
        const r = await post('/api/live/push', { type: ref.type, seed: ref.seed, confirm: true });
        toast('已写入模板槽');
        dialog({ title: '已写入', okText: '好', cancelText: '关闭',
          body: `<p>模板槽地址 <code>0x${r.address.toString(16)}</code></p>
                 <p class="tiny">在游戏里用对应的领取方式即可看到效果。</p>`,
          onOk: () => true });
        return true;
      },
    });
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
        <span class="kv">${esc(s.galaxy_name)}</span><span class="kv">种族 ${esc(s.race_zh || s.race || '—')}</span>
        <span class="kv">行星 ${s.planets}</span><span class="kv">${s.dissonant ? 'dissonant ✓' : '不刷拦截机'}</span>
        <div style="margin-top:8px"><button class="btn small" id="sysGlyph">显示本星系符文</button></div>`;
      $('#sysGlyph').onclick = () => showGlyphs(s.glyphs, s.coords);
      $('#planetCards').innerHTML = planets.map(p => {
        const c = BIOME_COLOR[p.biome_name] || '#6aa9ff';
        const here = (s.planet != null && p.index === s.planet + 1);
        return `<div class="planet ${here ? 'here' : ''}">
          <div class="top"><span class="dot" style="background:${c};color:${c}"></span>
            <b>${esc(p.biome_zh || p.biome_name)}</b>
            <div class="spacer"></div><span class="tiny">${here ? '你在这里' : '#' + p.index}</span></div>
          <div class="tiny">哨兵 ${esc(p.sentinels_zh || p.sentinels)}</div>
          <div class="glyph">${esc(s.glyphs)}</div>
          <div class="row"><button class="btn small" data-glyph="${esc(s.glyphs)}">符文</button></div>
        </div>`;
      }).join('') || '<div class="tiny">这个星系没有行星数据</div>';
      $$('#planetCards [data-glyph]').forEach(b => b.onclick = () => showGlyphs(b.dataset.glyph, s.coords));
      const ships = s.ships || [];
      const PREVIEWABLE = new Set(['fighter', 'hauler', 'explorer', 'shuttle', 'exotic', 'living', 'solar', 'sentinel']);
      $('#scanInfo').textContent = `本星系船池 ${ships.length} 条 · 生成 ${s.elapsed_ms} ms`;
      const rows = ships.map((sh, i) => {
        const can = PREVIEWABLE.has(sh.type) && sh.seed && !/^0x0+$/.test(sh.seed);
        return `<div class="kvrow"><span>${esc(sh.kind_zh || sh.kind)}</span>
          <span><code>${esc(sh.seed)}</code>
          ${can ? `<button class="btn small" data-ship="${i}">3D</button>` : ''}</span></div>`;
      }).join('');
      $('#sysDetail').innerHTML = `<h3>本星系船池</h3>${rows}` +
        (s.interceptor ? `<div class="kvrow"><span>拦截机（本星系）</span><code>${esc(s.interceptor)}</code></div>` : '');
      $$('#sysDetail [data-ship]').forEach(b => b.onclick = async () => {
        const sh = ships[+b.dataset.ship];
        const ref = { type: sh.type, seed: sh.seed, parts: null, source: 'system', name: sh.kind };
        await showShip(ref, 'sysDetail', false);
        const back = document.createElement('button');
        back.className = 'btn small'; back.textContent = '← 返回船池';
        back.onclick = () => loadCurrentSystem();
        $('#sysDetail').prepend(back);
      });
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
          rows.map(r => `<tr><td>#${r.index}</td><td>${esc(r.biome_zh || r.biome_name)}</td>
            <td>${esc(r.sentinels_zh || r.sentinels)}${r.dissonant ? ' · D' : ''}</td>
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
  $('#glyphOverlay').onclick = async () => {
    if (!DESKTOP.ready) { toast('仅桌面模式可用'); return; }
    const ok = await window.pywebview.api.launch_overlay(S.glyphs);
    toast(ok ? '已打开置顶符文条（Esc 关闭）' : '打开失败，见日志');
  };
  $('#glyphPop').onclick = () => {
    const w = window.open('', 'sf-glyphs', 'width=880,height=240');
    if (!w) { toast('浏览器拦截了弹窗'); return; }
    w.document.write(`<title>符文 ${S.glyphs}</title><body style="margin:0;background:#06080d">
      <img src="/api/glyphs/${S.glyphs}.png" style="width:100%;display:block;image-rendering:pixelated">
      <div style="padding:6px 10px;font:12px ui-monospace,monospace;color:#dbe9ff">${S.glyphs}</div></body>`);
    w.document.close();
  };

  /* ---------------- 设置 ---------------- */
  function showChecks(checks) {
    const map = { game_dir: '#gameDir', saves_dir: '#savesDir', gamedata_dir: '#gameData' };
    Object.entries(map).forEach(([k, sel]) => {
      const el = $(sel); if (!el || !checks?.[k]) return;
      const c = checks[k];
      el.style.borderColor = c.ok ? '#2f8b62' : '#8b3a2f';
      el.title = c.detail || '';
      const label = el.closest('.field')?.querySelector('label');
      if (label) {
        label.textContent = label.textContent.replace(/\s*[✓✗].*$/, '') + (c.ok ? '  ✓' : '  ✗');
        label.title = c.detail || '';
      }
    });
  }

  async function loadSettings() {
    const s = await api('/api/settings');
    $('#gameDir').value = s.settings.game_dir || '';
    $('#savesDir').value = s.settings.saves_dir || '';
    $('#gameData').value = s.settings.gamedata_dir || '';
    $('#writeChk').checked = !!s.settings.write_enabled;
    showChecks(s.checks);
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
    const run = async dest => {
      try {
        const r = await post('/api/live/template-mod', dest ? { dest } : {});
        $('#setMsg').textContent = '已生成：' + r.path;
        toast('模板 Mod 已生成');
      } catch (e) { $('#setMsg').textContent = e.message; }
    };
    if (DESKTOP.ready) {
      const dest = await window.pywebview.api.pick_folder('any');
      run(dest || '');
    } else {
      dialog({
        title: '生成模板 Mod', okText: '生成',
        body: `<p>生成到哪个目录？留空则放到缓存目录，生成后手动复制到
               <code>GAMEDATA/MODS/</code>。</p>
               <div class="field" style="margin-top:10px"><input id="modDest" class="input"
                 placeholder="留空 = 缓存目录"></div>`,
        onOk: async () => { await run(($('#modDest')?.value || '').trim()); return true; },
      });
    }
  };

  boot();
})();
