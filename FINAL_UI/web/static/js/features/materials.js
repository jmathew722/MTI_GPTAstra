/* McA.materials: Phase 1 material features on top of the server's /api/materials/* and /api/parts/.../material routes.
   - Part Setup: "Material Library Folder" control (browse/upload, path, refresh, demo, read-only catalog preview) + the part's material card
   - Pipeline Results: the Material section (renderSection)
   - Projects / Recent: per-part compact records and batch totals (batchFor)
   - Run All dialog: which catalog will be used (runCatalogNode)
   Every string from the server reaches the DOM through textContent (McA.dom.h text:). Wording and rules live in logic/materialview.js. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var $ = function (id) { return document.getElementById(id); };
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var MV = function () { return McA.materialview; };
  var HELP_FILES = ['material_resolution.json', 'material_native.json', 'material_costing.json', 'appearance.json'];

  var S = { settings: null, error: '', busy: false };
  var cache = {};                 // 'session|part' -> {state, data, error, seq}
  var batch = { keys: '', data: null, state: 'idle' };
  var options = { sig: '', list: null };
  var listeners = [];
  var seq = 0;

  function emit() { listeners.forEach(function (fn) { try { fn(); } catch (e) { if (window.console) console.error(e); } }); }
  function err(e) { return (e && e.detail) || (e && e.message) || 'Something went wrong.'; }
  function ckey(ctx) { return ctx && ctx.kind !== 'run' && ctx.session && ctx.part ? ctx.session + '|' + ctx.part : ''; }
  function selectedCtx() { var sl = McA.store.get().parts.selected; return sl ? { kind: 'part', session: sl.session, part: sl.part } : null; }
  function toast(t, k) { if (McA.toast) McA.toast.show(t, k || 'info'); }
  function announce(t) { if (McA.toast && McA.toast.announce) McA.toast.announce(t, 'info'); }

  /* ── settings + library control ────────────────────────────────────────── */
  function loadSettings() {
    return McA.api.materialSettings().then(function (r) { S.settings = r; S.error = ''; try { McA.persist.set(McA.persist.KEYS.materialLibrary, { name: r.library.active ? r.library.name : '', entries: r.library.entries || 0 }); } catch (e) { /* storage unavailable */ } },
      function (e) { S.error = err(e); }).then(function () { renderLibrary(); emit(); });
  }
  function setBusy(on, text) { S.busy = on; if (on && text) $('mat-lib-line').textContent = text; renderLibrary(); }
  function libraryChanged(r, msg) {
    S.settings = r; S.error = ''; cache = {}; options.sig = ''; batch.keys = '';
    try { McA.persist.set(McA.persist.KEYS.materialLibrary, { name: r.library.active ? r.library.name : '', entries: r.library.entries || 0 }); } catch (e) { /* ignore */ }
    S.busy = false; renderLibrary(); emit(); loadSelected(true);
    if (msg) { toast(msg, 'ok'); announce(msg); }
  }
  function failed(e) { S.busy = false; S.error = err(e); renderLibrary(); announce('Material library: ' + S.error); }

  function ext(n) { var m = /\.[^./\\]+$/.exec(n || ''); return m ? m[0].toLowerCase() : ''; }
  function pickFolder(files) {
    if (!files.length) return;
    var rel = function (f) { return String(f.webkitRelativePath || f.name).replace(/\\/g, '/'); };
    var top = rel(files[0]).split('/')[0] || 'Material library';
    var usable = files.filter(function (f) { var p = rel(f).split('/'); return p.length <= 2 && ['.json', '.csv', '.sldmat'].indexOf(ext(f.name)) >= 0; });
    if (!usable.length) { failed({ detail: 'That folder holds no materials.json, .csv or .sldmat file.' }); return; }
    var fd = new FormData();
    usable.forEach(function (f) { fd.append('files', f, rel(f)); });
    fd.append('folder_name', top);
    setBusy(true, 'Reading ' + usable.length + ' file' + (usable.length === 1 ? '' : 's') + ' from ' + top + '…');
    McA.api.uploadMaterialLibrary(fd).then(function (r) {
      libraryChanged(r, 'Material library loaded: ' + r.library.entries + ' material' + (r.library.entries === 1 ? '' : 's') + (r.library.rejected ? ', ' + r.library.rejected + ' rejected' : '') + '.');
    }, failed);
  }
  function usePath() {
    var v = $('mat-lib-path').value.trim(); if (!v) return;
    setBusy(true, 'Reading the folder…');
    McA.api.setMaterialLibraryPath(v).then(function (r) { $('mat-lib-path').value = ''; $('mat-lib-path-go').disabled = true; libraryChanged(r, 'Material library loaded: ' + r.library.entries + ' materials.'); }, failed);
  }
  function renderLibrary() {
    var line = $('mat-lib-line'); if (!line) return;
    var st = S.settings, lib = st && st.library, e = $('mat-lib-err');
    if (!S.busy) line.textContent = !st ? (S.error ? 'Material library unavailable.' : 'Loading material library…') : MV().libraryLine(lib);
    e.hidden = !S.error; e.textContent = S.error;
    var has = !!(lib && lib.active) || !!(lib && lib.error);
    $('mat-lib-refresh').disabled = !has || S.busy; $('mat-lib-clear').disabled = !has || S.busy;
    $('mat-lib-view').disabled = !st;
    $('mat-lib-why').textContent = !st ? '' : has ? (lib.origin === 'upload' ? 'Uploaded copy. Refresh needs the folder picked again.' : 'Reads the folder again after you edit its files.') : 'No company library set: refresh and demo are not needed.';
    $('mat-lib-lbl').setAttribute('aria-disabled', String(S.busy));
  }

  /* ── catalog preview dialog (read-only) ────────────────────────────────── */
  function openCatalog(startSource) {
    var st = S.settings || {}, lib = st.library || {};
    var sources = [];
    if (lib.active) sources.push(['company', 'Company library']);
    sources.push(['demo', 'Demo catalog']);
    if (st.standard_available) sources.push(['standard', 'Installed SolidWorks']);
    var cur = { source: startSource && sources.some(function (s) { return s[0] === startSource; }) ? startSource : sources[0][0], q: '', offset: 0, rows: [], total: 0, info: null, error: '', loading: false };
    var tabs = h('div', { class: 'seg-c', role: 'group', 'aria-label': 'Catalog source' });
    var search = h('input', { type: 'search', class: 'input-c', placeholder: 'Search materials', 'aria-label': 'Search catalog' });
    var meta = h('p', { class: 'reason', role: 'status' });
    var note = h('p', { class: 'reason' });
    var tbody = h('tbody'), more = h('button', { type: 'button', class: 'btn ghost sm', text: 'Show more' });
    var rej = h('div');
    var wrap = h('div', { class: 'tbl-wrap mat-prev-wrap', tabindex: '0', role: 'region', 'aria-label': 'Materials in this catalog' }, h('table', { class: 'tbl mat-prev' }, h('caption', { class: 'sr-only', text: 'Catalog materials' }),
      h('thead', null, h('tr', null, ['Material', 'Aliases', 'Density', 'Price per kg', 'Native in SolidWorks'].map(function (c) { return h('th', { scope: 'col', text: c }); }))), tbody));
    function drawTabs() {
      tabs.replaceChildren();
      sources.forEach(function (s) {
        var b = h('button', { type: 'button', 'aria-pressed': String(cur.source === s[0]), class: cur.source === s[0] ? 'on' : '', text: s[1] });
        b.addEventListener('click', function () { cur.source = s[0]; cur.offset = 0; cur.rows = []; fetchPage(true); drawTabs(); });
        tabs.append(b);
      });
    }
    function draw() {
      tbody.replaceChildren();
      cur.rows.forEach(function (m) {
        tbody.append(h('tr', null,
          h('td', null, h('strong', { text: m.label }), h('div', { class: 'mono mat-id', text: m.id })),
          h('td', { text: (m.aliases || []).join(', ') || '-' }),
          h('td', { class: 'num', text: MV().density(m.density_kg_m3) }),
          h('td', { class: 'num', text: MV().price(m.price_per_kg, m.currency) }),
          h('td', { text: MV().nativeWord(m, cur.source) })));
      });
      if (!cur.rows.length && !cur.loading) tbody.append(h('tr', null, h('td', { colspan: '5', class: 'reason', text: cur.error || 'No materials match.' })));
      var info = cur.info;
      meta.textContent = cur.loading ? 'Loading…' : cur.error ? '' : 'Showing ' + cur.rows.length + ' of ' + cur.total + ' material' + (cur.total === 1 ? '' : 's') + '.';
      note.textContent = info ? 'Currency ' + info.currency + (info.price_basis ? ' · price basis: ' + String(info.price_basis).replace(/_/g, ' ') : '') + (info.sha256 ? ' · catalog hash ' + String(info.sha256).slice(0, 12) : '') : '';
      more.hidden = cur.rows.length >= cur.total;
      rej.replaceChildren();
      if (info && info.rejected) {
        rej.append(h('p', { class: 'reason is-warn', text: info.rejected + ' record' + (info.rejected === 1 ? ' was' : 's were') + ' rejected and are not used:' }),
          h('ul', { class: 'mat-rej' }, (info.rejected_records || []).slice(0, 8).map(function (r) { return h('li', { class: 'mono', text: (r.id || '?') + ': ' + (r.reason || '') }); })));
      }
    }
    function fetchPage(reset) {
      var mine = ++seq; cur.loading = true; cur.error = ''; draw();
      McA.api.materialCatalog({ source: cur.source, q: cur.q || undefined, offset: reset ? 0 : cur.offset, limit: 100 }).then(function (r) {
        if (mine !== seq) return;
        cur.loading = false; cur.info = r; cur.total = r.total; cur.rows = reset ? r.materials : cur.rows.concat(r.materials); cur.offset = cur.rows.length; draw();
      }, function (e) { if (mine !== seq) return; cur.loading = false; cur.error = err(e); cur.rows = []; cur.total = 0; draw(); });
    }
    search.addEventListener('input', McA.util.debounce(function () { cur.q = search.value.trim(); cur.offset = 0; fetchPage(true); }, 220));
    more.addEventListener('click', function () { fetchPage(false); });
    var body = h('div', { class: 'mat-prev-body' }, h('p', { class: 'reason', text: 'Read-only preview. The pipeline reads this catalog at run time; nothing here changes the files.' }), tabs, search, meta, wrap, more, note, rej);
    drawTabs(); fetchPage(true);
    var p = McA.dialog.open({ title: 'Material catalog', body: body, actions: [{ id: 'close', label: 'Close', kind: 'primary' }] });
    if (p.element) p.element.classList.add('dlg-wide');
    return p;
  }

  /* ── per-part material (cache) ─────────────────────────────────────────── */
  function loadPart(ctx, force) {
    var k = ckey(ctx); if (!k) return Promise.resolve(null);
    var e = cache[k];
    if (e && !force && (e.state === 'ready' || e.state === 'loading')) return Promise.resolve(e.data);
    var mine = ++seq;
    cache[k] = { state: 'loading', data: e ? e.data : null, error: '', seq: mine };
    emit();
    return McA.api.partMaterial(ctx.session, ctx.part).then(function (d) {
      if (cache[k] && cache[k].seq === mine) { cache[k] = { state: 'ready', data: d, error: '', seq: mine }; emit(); }
      return d;
    }, function (er) {
      if (cache[k] && cache[k].seq === mine) { cache[k] = { state: 'error', data: null, error: err(er), seq: mine }; emit(); }
      return null;
    });
  }
  function loadSelected(force) { var c = selectedCtx(); if (c) loadPart(c, force); }
  function setData(ctx, d) { var k = ckey(ctx); cache[k] = { state: 'ready', data: d, error: '', seq: ++seq }; emit(); }
  function entry(ctx) { return cache[ckey(ctx)] || null; }
  function cached(ctx) { var e = entry(ctx); return e && e.state === 'ready' ? e.data : null; }

  /* ── small widgets ─────────────────────────────────────────────────────── */
  function statusChip(info) {
    return h('span', { class: 'badge-c mat-chip ' + (info.kind || ''), 'data-tone': info.tone, 'data-status': info.id || '' }, McA.icons.get(info.icon || 'info', 14), h('span', { text: info.label }));
  }
  function costChip(text, ill) { return h('span', { class: 'mat-cost' }, h('span', { class: 'mono', text: text }), ill ? h('span', { class: 'mat-ill', text: 'illustrative' }) : null); }
  function btn(label, icon, fn, attrs) {
    var b = h('button', Object.assign({ type: 'button', class: 'btn ghost sm' }, attrs || {}), icon ? McA.icons.get(icon, 14) : null, h('span', { text: label }));
    if (fn) b.addEventListener('click', fn); return b;
  }
  function row(k, v, cls) { return h('div', { class: 'ov-line' }, h('span', { class: 'k', text: k }), h('span', { class: 'v' + (cls ? ' ' + cls : ''), text: v === null || v === undefined || v === '' ? 'not reported' : String(v) })); }
  function sub(t) { return h('h3', { class: 'sub-h', text: t }); }
  function fnum(n, u, dg) { return typeof n === 'number' && isFinite(n) ? n.toLocaleString('en-US', { maximumFractionDigits: dg === undefined ? 4 : dg }) + (u ? ' ' + u : '') : ''; }

  /* ── Part Setup material card ──────────────────────────────────────────── */
  function renderPart() {
    var box = $('mat-part'); if (!box) return;
    box.replaceChildren();
    var ctx = selectedCtx();
    if (!ctx) { box.hidden = true; return; }
    box.hidden = false;
    var e = entry(ctx), t = h('div', { class: 'cap-c', text: 'Material of this part' });
    box.append(t);
    if (!e || (e.state === 'loading' && !e.data)) { box.append(h('p', { class: 'reason', text: 'Reading material…' })); return; }
    if (e.state === 'error') { box.append(h('p', { class: 'reason is-warn', role: 'alert', text: 'Could not read the material: ' + e.error })); return; }
    var d = e.data, sum = MV().summary(d);
    box.append(h('div', { class: 'mat-part-t', text: sum.title }), h('div', { class: 'mat-part-s' }, statusChip(sum.status)));
    if (!d.evaluated) {
      box.append(h('p', { class: 'reason', text: MV().NOT_EVALUATED_DETAIL }));
      if (d.has_extraction) box.append(btn('Resolve from saved extraction', 'refresh', function () { refreshPart(ctx); }, { class: 'btn secondary sm' }));
    } else {
      var c = sum.cost;
      box.append(h('div', { class: 'mat-part-c' }, h('span', { class: 'k', text: 'Material cost' }), c.available ? costChip(c.text, c.illustrative) : h('span', { class: 'mat-unavail', text: MV().UNAVAILABLE })));
      if (d.from_saved_extraction) box.append(h('p', { class: 'reason', text: 'From the saved extraction, not yet built.' }));
      if (d.stale) box.append(h('p', { class: 'reason is-warn', text: 'The material library changed since this result. Refresh it in Pipeline Results.' }));
    }
    box.append(btn('Open material details', 'results', function () { McA.router.go('results', { run: ctx.session + '|' + ctx.part, sec: 'material' }); }));
  }

  /* ── actions ───────────────────────────────────────────────────────────── */
  function refreshPart(ctx) {
    return McA.api.refreshPartMaterial(ctx.session, ctx.part).then(function (d) { setData(ctx, d); batch.keys = ''; toast('Material re-read from the saved extraction. Mass and cost are from the last build.', 'ok'); }, function (e) { toast('Could not refresh the material: ' + err(e), 'err'); });
  }
  function applyOverride(ctx, id, catalogId, reason) {
    return McA.api.setMaterialOverride(ctx.session, ctx.part, { material_id: id, catalog_id: catalogId || undefined, reason: reason, user: '' }).then(function (d) { setData(ctx, d); batch.keys = ''; toast('Manual override saved. It takes effect on the next run.', 'ok'); return true; },
      function (e) { toast('Override not saved: ' + err(e), 'err'); return false; });
  }
  function clearOverride(ctx) {
    return McA.api.clearMaterialOverride(ctx.session, ctx.part).then(function (d) { setData(ctx, d); batch.keys = ''; toast('Manual override cleared.', 'ok'); }, function (e) { toast('Could not clear the override: ' + err(e), 'err'); });
  }
  function ensureOptions() {
    var lib = (S.settings && S.settings.library) || {}, sig = (lib.active ? lib.sha256 || lib.name : 'demo');
    if (options.sig === sig && options.list) return Promise.resolve(options.list);
    var jobs = [McA.api.materialCatalog({ source: 'demo', limit: 500 })];
    if (lib.active) jobs.unshift(McA.api.materialCatalog({ source: 'company', limit: 500 }));
    return Promise.all(jobs).then(function (rs) { options = { sig: sig, list: rs }; return rs; }, function () { return []; });
  }

  /* ── Pipeline Results: Material section ────────────────────────────────── */
  function evidenceBlock(res) {
    var dr = res.drawing || {}, box = h('div', { class: 'mat-block' });
    box.append(sub('What the drawing says'));
    var evs = dr.evidence || [];
    if (dr.status === 'not_specified' || (!evs.length && !dr.raw_text)) {
      box.append(h('div', { class: 'banner' }, McA.icons.get('info', 18), h('span', { text: dr.status === 'unreadable' ? 'The material text could not be read. That is not the same as no material.' : 'No material specified on drawing. No material was assumed.' })));
      if (dr.review_reason) box.append(h('p', { class: 'reason', text: dr.review_reason }));
      return box;
    }
    box.append(row('Drawing status', dr.status), row('Text as written', dr.raw_text, 'mono'));
    evs.forEach(function (ev, i) {
      box.append(h('blockquote', { class: 'mat-quote' }, h('span', { text: '“' + String(ev.quote || '') + '”' }), h('footer', { class: 'reason', text: 'Evidence ' + (i + 1) + ': page ' + (ev.page === undefined ? '?' : ev.page) + ', region ' + (ev.region || 'not reported') })));
    });
    [['coating', 'Coating'], ['heat_treatment', 'Heat treatment'], ['finish', 'Finish'], ['hardness', 'Hardness'], ['stock_form', 'Stock form'], ['condition_or_temper', 'Condition or temper'], ['specification', 'Specification']].forEach(function (k) { if (dr[k[0]]) box.append(row(k[1], dr[k[0]])); });
    box.append(h('div', { class: 'mat-infer' }, h('span', { class: 'cap-c', text: 'Interpretation (inferred, not quoted)' }), row('Read as', dr.normalized_candidate, 'mono'), dr.confidence !== undefined && dr.confidence !== null ? row('Confidence', String(dr.confidence)) : null));
    if ((dr.alternatives || []).length) box.append(row('Other readings', dr.alternatives.join('; ')));
    return box;
  }
  function catalogBlock(d) {
    var res = d.resolution, ch = res.chosen, box = h('div', { class: 'mat-block' });
    box.append(sub('Catalog match'));
    if (!ch) { box.append(h('p', { class: 'reason', text: 'No catalog material is selected.' })); return box; }
    box.append(row('Material', ch.label), row('Catalog entry', ch.material_id, 'mono'), row('Catalog', (ch.catalog_id || '') + ' (' + (ch.catalog_source || 'unknown source') + ')'),
      row('Catalog hash', ch.catalog_sha256 ? String(ch.catalog_sha256).slice(0, 12) : '', 'mono'), row('Density', MV().density(ch.density_kg_m3)), row('Price', MV().price(ch.price_per_kg, ch.currency, ch.price_basis)),
      row('SolidWorks material', ch.sw_material_name || 'assigned at build'));
    if (d.stale) box.append(h('div', { class: 'banner is-warn', role: 'status' }, McA.icons.get('warn', 18), h('span', { text: 'Out of date: ' + (d.stale_reasons || []).join(' ') + ' Use Refresh to re-read the material with the current library.' })));
    return box;
  }
  function nativeBlock(d) {
    var nv = d.native, box = h('div', { class: 'mat-block' });
    box.append(sub('Native read-back (SolidWorks)'));
    if (!nv) { box.append(h('p', { class: 'reason', text: 'Not built yet: nothing was read back from SolidWorks.' })); return box; }
    var rq = nv.requested || {}, ac = nv.actual || {};
    box.append(row('Status', nv.status), row('Requested material', rq.name), row('Requested library', rq.database), row('Actual material', ac.name), row('Actual library', ac.database),
      row('Density read back', nv.density_kg_m3 === null || nv.density_kg_m3 === undefined ? '' : MV().density(nv.density_kg_m3)), row('Density matches catalog', nv.density_ok === null || nv.density_ok === undefined ? '' : (nv.density_ok ? 'yes' : 'no')));
    (nv.errors || []).forEach(function (x) { box.append(h('p', { class: 'reason is-warn', text: x })); });
    box.append(h('p', { class: 'reason', text: 'From the last SolidWorks build.' }));
    return box;
  }
  function costBlock(d) {
    var box = h('div', { class: 'mat-block' }), c = d.costing, ci = MV().costInfo(c), nv = d.native || {}, ms = nv.mass || {};
    box.append(sub('Mass and material cost'));
    if (!c) { box.append(h('p', { class: 'reason', text: 'No mass or cost yet. They are measured on the SolidWorks part during a build.' })); box.append(h('div', { class: 'mat-line' }, h('span', { class: 'k', text: 'Net material cost' }), h('span', { class: 'mat-unavail', text: MV().UNAVAILABLE }))); return box; }
    var disp = c.display || {};
    box.append(row('Volume', disp.volume || (ms.volume_m3 ? fnum(ms.volume_m3 * 1e6, 'cm³', 4) : '')), row('Mass', disp.mass || (ms.mass_kg ? fnum(ms.mass_kg, 'kg', 4) : '')),
      row('Price per kg', MV().price(c.inputs && c.inputs.price_per_kg, c.currency, c.price_basis)));
    box.append(h('div', { class: 'ov-line mat-net' }, h('span', { class: 'k', text: 'Net material cost' }), ci.available ? costChip(ci.text, ci.illustrative) : h('span', { class: 'mat-unavail', text: MV().UNAVAILABLE })));
    if (!ci.available) box.append(h('p', { class: 'reason', text: ci.reason }));
    if (ci.available && c.stock_cost !== null && c.stock_cost !== undefined) box.append(row('Stock cost (with yield)', disp.stock_cost));
    if (ci.label) box.append(h('p', { class: 'mat-ill-label', text: ci.label }));
    box.append(h('p', { class: 'reason', text: c.excludes || MV().CAVEAT }));
    (c.warnings || []).forEach(function (w) { box.append(h('p', { class: 'reason is-warn', text: w })); });
    box.append(h('p', { class: 'reason', text: 'From the last SolidWorks build.' }));
    return box;
  }
  function overrideBlock(ctx, d, root) {
    var res = d.resolution, ov = d.override, box = h('div', { class: 'mat-block mat-ov' });
    box.append(sub('Review and override'));
    (res.review_reasons || []).forEach(function (r) { box.append(h('div', { class: 'banner is-warn' }, McA.icons.get('warn', 18), h('span', { text: r }))); });
    if (ov || res.selection_source === 'manual_override') {
      var o = res.override || ov || {};
      box.append(h('div', { class: 'banner is-warn mat-ov-banner', role: 'status' }, McA.icons.get('warn', 18), h('div', null,
        h('strong', { text: 'Manual override - differs from the drawing' }), h('div', { text: 'Drawing says: ' + (o.drawing_text || (res.drawing && res.drawing.raw_text) || 'no material') }),
        h('div', { text: 'Override: ' + ((res.chosen && res.chosen.label) || (ov && ov.material_id) || '') }), h('div', { text: 'Reason: ' + (o.reason || (ov && ov.reason) || '') }), h('div', { class: 'reason', text: MV().overrideLine(ov || o) }))));
      if (d.needs_rebuild) box.append(h('p', { class: 'reason', text: 'Takes effect on the next run. The mass, cost and model colour shown are from the last build.' }));
    }
    var sug = (res.suggestions || []).concat((res.standard_candidates || []).map(function (x) { return { id: x.id, label: x.label, catalog_id: x.catalog_id, source: x.source, similarity: null, standard: true }; }));
    var pick = { id: '', cat: '' };
    var sel = h('select', { class: 'input-c', id: 'mat-ov-sel', 'aria-label': 'Catalog material' }, h('option', { value: '', text: 'Choose a catalog material' }));
    var reason = h('textarea', { class: 'input-c', id: 'mat-ov-reason', rows: '2', maxlength: '500', 'aria-label': 'Reason for the override', placeholder: 'Why this material (for example: customer email, revised drawing)' });
    var apply = h('button', { type: 'button', class: 'btn secondary sm', id: 'mat-ov-apply', text: 'Apply override' });
    var why = h('p', { class: 'reason', id: 'mat-ov-why' });
    function sync() { var b = MV().overrideBlock(sel.value, reason.value); apply.setAttribute('aria-disabled', String(!!b)); why.textContent = b; }
    sel.addEventListener('change', function () { var o = sel.selectedOptions[0]; pick = { id: sel.value, cat: o ? o.getAttribute('data-cat') || '' : '' }; sync(); });
    reason.addEventListener('input', sync);
    apply.addEventListener('click', function () {
      if (apply.getAttribute('aria-disabled') === 'true') { toast(why.textContent, 'warn'); return; }
      apply.setAttribute('aria-disabled', 'true'); applyOverride(ctx, sel.value, pick.cat, reason.value.trim());
    });
    ensureOptions().then(function (rs) {
      rs.forEach(function (r) {
        var g = h('optgroup', { label: r.source === 'company' ? 'Company library: ' + (r.label || r.catalog_id) : 'Demo catalog (synthetic prices)' });
        r.materials.forEach(function (m) { g.append(h('option', { value: m.id, 'data-cat': r.catalog_id, text: m.label + ' (' + m.id + ')' + (m.price_per_kg === null ? ' - no price' : '') })); });
        sel.append(g);
      });
      if (!rs.length) sel.append(h('option', { value: '', disabled: true, text: 'Catalogs could not be loaded' }));
      if (pick.id) sel.value = pick.id;
    });
    if (sug.length) {
      box.append(h('p', { class: 'cap-c', text: 'Suggestions - approval required, never applied automatically' }));
      var ul = h('ul', { class: 'mat-sug' });
      sug.forEach(function (s) {
        var b = btn('Use as override', null, function () { sel.value = s.id; var o = sel.selectedOptions[0]; pick = { id: sel.value, cat: o ? o.getAttribute('data-cat') || '' : '' }; if (sel.value !== s.id) { toast('That entry is only in the installed SolidWorks library. Add it to your catalog to use it.', 'warn'); return; } sync(); reason.focus(); }, { 'aria-label': 'Use ' + s.label + ' as the override' });
        ul.append(h('li', null, h('span', null, h('strong', { text: s.label }), h('span', { class: 'mono mat-id', text: ' ' + s.id + ' · ' + (s.source || '') }),
          s.different_grade ? h('span', { class: 'badge-c warn', text: 'different grade' }) : null, s.different_temper_or_condition ? h('span', { class: 'badge-c warn', text: 'different temper' }) : null,
          s.similarity !== null && s.similarity !== undefined ? h('span', { class: 'reason', text: ' similarity ' + s.similarity }) : null), b));
      });
      box.append(ul);
    }
    box.append(h('div', { class: 'fld' }, h('label', { for: 'mat-ov-sel', text: 'Override material' }), sel), h('div', { class: 'fld' }, h('label', { for: 'mat-ov-reason', text: 'Reason (required)' }), reason), why,
      h('div', { class: 'row2' }, apply, ov ? btn('Clear override', 'x', function () { clearOverride(ctx); }, { id: 'mat-ov-clear' }) : null));
    sync();
    return box;
  }
  function filesBlock(d, ctx) {
    var box = h('div', { class: 'mat-block' }), any = false;
    box.append(sub('Files'));
    var names = HELP_FILES.concat(['material_override.json']);
    var ul = h('ul', { class: 'mat-files' });
    names.forEach(function (n) {
      if (!(d.files && d.files[n])) return; any = true;
      ul.append(h('li', null, h('span', { class: 'mono', text: n }), h('a', { class: 'btn ghost sm', href: McA.api.partFileURL(ctx.session, ctx.part, n), download: n, 'aria-label': 'Download ' + n }, McA.icons.get('download', 14), 'Download')));
    });
    box.append(any ? ul : h('p', { class: 'reason', text: 'No material files for this part yet.' }));
    return box;
  }

  function renderSection(body, tools, dd) {
    var ctx = dd.ctx;
    if (!ctx || ctx.kind !== 'part') { body.append(h('div', { class: 'empty' }, McA.icons.get('info', 28), h('p', { class: 'empty-t', text: 'Saved parts only' }), h('p', { class: 'empty-d', text: 'Material review is available for saved parts, not demo runs.' }))); return; }
    var e = entry(ctx);
    if (!e) { loadPart(ctx); e = entry(ctx); }
    if (!e || (e.state === 'loading' && !e.data)) { for (var i = 0; i < 4; i++) body.append(h('div', { class: 'skel', style: 'width:' + (90 - i * 15) + '%' })); body.setAttribute('aria-busy', 'true'); return; }
    if (e.state === 'error') { body.append(h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), h('span', { text: 'Could not read the material: ' + e.error }))); body.append(btn('Retry', 'refresh', function () { loadPart(ctx, true); }, { class: 'btn secondary sm' })); return; }
    var d = e.data, st = MV().statusInfo(d);
    tools.append(btn('Refresh', 'refresh', function () { refreshPart(ctx); }, { 'aria-label': 'Refresh material from the saved extraction' }));
    if (!d.evaluated) {
      body.append(h('div', { class: 'mat-head' }, statusChip(st)));
      body.append(h('div', { class: 'empty' }, McA.icons.get('layers', 28), h('p', { class: 'empty-t', text: MV().NOT_EVALUATED }), h('p', { class: 'empty-d', text: MV().NOT_EVALUATED_DETAIL })));
      if (d.has_extraction) body.append(h('div', { class: 'row2' }, btn('Resolve from saved extraction', 'refresh', function () { refreshPart(ctx); }, { class: 'btn secondary sm', id: 'mat-resolve' }), h('span', { class: 'reason', text: 'Reads the saved extraction only. No SolidWorks, no API call.' })));
      body.append(overrideBlock(ctx, { resolution: { review_reasons: [], suggestions: [], standard_candidates: [] }, override: null }, body));
      return;
    }
    var res = d.resolution;
    body.append(h('div', { class: 'mat-head' }, statusChip(st), h('strong', { class: 'mat-title', text: MV().titleOf(d) }),
      res.selection_source === 'manual_override' ? h('span', { class: 'badge-c warn', text: 'Manual override' }) : null));
    if (d.from_saved_extraction) body.append(h('div', { class: 'banner' }, McA.icons.get('info', 18), h('span', { text: 'Resolved from the saved extraction, not yet built. Native read-back, mass and cost appear after the next run.' })));
    else body.append(h('p', { class: 'reason', text: 'Native read-back, mass, cost and colour are from the last build.' }));
    body.append(evidenceBlock(res), catalogBlock(d), nativeBlock(d), costBlock(d), overrideBlock(ctx, d, body), filesBlock(d, ctx));
    (res.catalog_warnings || []).forEach(function (w) { body.append(h('p', { class: 'reason is-warn', text: w })); });
  }

  /* ── Projects / Recent / Run All ───────────────────────────────────────── */
  function batchFor(keys) {
    var sig = keys.slice().sort().join(',');
    if (!keys.length) return null;
    if (batch.keys === sig) return batch.data;
    batch.keys = sig; batch.state = 'loading';
    McA.api.materialBatch(keys).then(function (r) { if (batch.keys === sig) { batch.data = r; batch.state = 'ready'; emit(); } }, function () { if (batch.keys === sig) { batch.state = 'error'; batch.data = null; emit(); } });
    return batch.data && batch.keys === sig ? batch.data : null;
  }
  function compactOf(key) { return batch.data && batch.data.parts ? batch.data.parts[key] || null : null; }

  /* Table cells: material (status chip with icon + name) and material cost, kept apart from the run (API) cost. */
  function materialCell(key) {
    var c = compactOf(key);
    if (!c) return h('span', { class: 'reason', text: batch.state === 'error' ? 'unavailable' : 'Loading…' });
    var i = MV().compactInfo(c);
    return h('span', { class: 'mat-cell' }, statusChip({ id: c.status || 'not_evaluated', label: i.label, icon: i.icon, tone: i.tone, kind: i.kind }), i.evaluated ? h('span', { class: 'mat-cell-t', text: i.title }) : null);
  }
  function costCell(key) {
    var c = compactOf(key);
    if (!c) return h('span', { class: 'reason', text: batch.state === 'error' ? 'unavailable' : 'Loading…' });
    var i = MV().compactInfo(c);
    return i.costText === MV().UNAVAILABLE ? h('span', { class: 'mat-unavail', text: MV().UNAVAILABLE }) : costChip(i.costText, i.illustrative);
  }
  function batchLine(keys) {
    var d = batchFor(keys);
    if (!d) return batch.state === 'error' ? 'Material totals unavailable.' : '';
    var t = MV().batchText(d), api = d.api_cost && d.api_cost.parts_with_cost ? ' Run (API) cost for these parts is reported separately in Pipeline Results > Cost.' : '';
    return t ? t + api : '';
  }
  function runCatalogNode() {
    var line = h('p', { class: 'dlg-mat', id: 'run-mat-line', text: S.settings ? MV().runCatalogLine(S.settings) : 'Material library: not loaded yet.' });
    return line;
  }
  function focusControl() {
    McA.router.go('workspace', {});
    McA.dom.dispatch('ui/inspectorSection', { id: 'setup', open: true });
    setTimeout(function () { var l = $('mat-lib-lbl'); if (l && l.scrollIntoView) l.scrollIntoView({ block: 'center' }); if (l) l.focus(); }, 200);
  }

  McA.materials = {
    cached: cached, entry: entry, load: loadPart, onChange: function (fn) { listeners.push(fn); }, batchFor: batchFor, compactOf: compactOf, renderSection: renderSection,
    openCatalog: openCatalog, materialCell: materialCell, costCell: costCell, batchLine: batchLine, runCatalogNode: runCatalogNode, focusControl: focusControl, settings: function () { return S.settings; }, statusChip: statusChip,
    reloadSettings: loadSettings,
    init: function () {
      var rem = McA.persist.get(McA.persist.KEYS.materialLibrary, null);
      if (rem && rem.name) $('mat-lib-line').textContent = rem.name + ' · ' + rem.entries + ' material' + (rem.entries === 1 ? '' : 's');
      var inp = $('mat-lib-folder');
      inp.addEventListener('change', function () { var a = Array.prototype.slice.call(inp.files); inp.value = ''; pickFolder(a); });
      var lbl = $('mat-lib-lbl'); lbl.tabIndex = 0;
      lbl.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); inp.click(); } });
      $('mat-lib-view').addEventListener('click', function () { openCatalog(); });
      $('mat-lib-refresh').addEventListener('click', function () { setBusy(true, 'Reading the library again…'); McA.api.refreshMaterialLibrary().then(function (r) { libraryChanged(r, 'Material library refreshed.'); }, failed); });
      $('mat-lib-clear').addEventListener('click', function () { setBusy(true, 'Switching to the demo catalog…'); McA.api.clearMaterialLibrary().then(function (r) { libraryChanged(r, 'Using the demo catalog. Your library files were not touched.'); }, failed); });
      var pin = $('mat-lib-path');
      pin.addEventListener('input', function () { $('mat-lib-path-go').disabled = !pin.value.trim(); });
      pin.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); usePath(); } });
      $('mat-lib-path-go').addEventListener('click', usePath);
      McA.store.subscribe(function (s) { return s.parts.selected; }, function () { renderPart(); loadSelected(false); });
      McA.store.subscribe(function (s) { return s.run.state; }, function (v) {
        if (v === 'succeeded' || v === 'succeeded_with_warnings' || v === 'failed') { var c = selectedCtx(); if (c) setTimeout(function () { loadPart(c, true); batch.keys = ''; }, 1200); }
      });
      listeners.push(renderPart);
      renderLibrary(); renderPart(); loadSettings(); loadSelected(false);
    }
  };
})();
