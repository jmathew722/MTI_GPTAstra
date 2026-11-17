/* McA.results: renders all 13 registry sections (ARCH 8.7, 11) for the Results page and the drawer.
   mount({nav, pane, mode:'page'|'drawer', getSection, setSection, isVisible}) -> {render, destroy}.
   Payload text only reaches the DOM through textContent; class names come from whitelists. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var SEV = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
  var LOCAL = { search: {}, open: {}, follow: true, macroIdx: 0, eventKind: 'all', more: {} };
  var summaryCache = {};      // ctx key -> {state, row}
  var regionsCache = {};
  var mounts = [];

  function wl(v, allowed, fb) { return McA.util.whitelist(v, allowed, fb); }
  function ctxKey(c) { return c ? (c.kind === 'part' ? c.session + '|' + c.part : 'run:' + c.runId) : ''; }
  function fileURL(ctx, rel) { return ctx.kind === 'part' ? McA.api.partFileURL(ctx.session, ctx.part, rel) : McA.api.runDownloadURL(ctx.runId, rel); }
  function toastCopy(ok) { McA.toast.announce(ok ? 'Copied' : 'Copy failed', ok ? 'info' : 'err'); }

  function getData() {
    var s = McA.store.get(), o = s.outputs, ctx = o.ctx, run = s.run;
    var match = !!(run.id && ctx && ((ctx.kind === 'run' && ctx.runId === run.id) ||
      (ctx.kind === 'part' && run.kind === 'part' && run.session === ctx.session && run.part === ctx.part)));
    return { s: s, ctx: ctx, payload: o.payload, loading: o.loading, error: o.error, run: run, runMatch: match,
      demo: !!(ctx && ctx.kind === 'run'),
      extra: match ? { lines: run.lines, runState: run.state, verdict: run.verdict, summary: run.summary, exit: run.exit }
                   : { lines: [], runState: null, verdict: null, summary: null } };
  }
  function secState(sec, d) {
    if (!d.ctx) return 'none';
    if (d.loading && !d.payload) return 'loading';
    if (d.error && !d.payload) return 'error';
    return sec.status(d.payload, d.extra) === 'present' ? 'present' : 'absent';
  }
  function cats(d) { return (d.payload && d.payload.categories) || {}; }

  /* ── small widgets ─────────────────────────────────────────────────────── */
  function btn(label, icon, fn, attrs) {
    var b = h('button', Object.assign({ type: 'button', class: 'btn ghost sm' }, attrs || {}), icon ? McA.icons.get(icon, 14) : null, label ? h('span', { text: label }) : null);
    if (fn) b.addEventListener('click', fn);
    return b;
  }
  function copyBtn(getText) {
    var b = btn('Copy', 'copy', function () {
      McA.util.copyText(getText()).then(function (ok) { toastCopy(ok); var sp = b.querySelector('span'); sp.textContent = ok ? 'Copied' : 'Failed'; setTimeout(function () { sp.textContent = 'Copy'; }, 1500); });
    });
    return b;
  }
  function blobDownload(name, text) {
    var url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
    McA.util.downloadURL(url, name); setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }
  function downloadBtn(d, rel, fallbackName, getText) {
    var attrs = { 'aria-label': 'Download ' + (rel || fallbackName) };
    if (rel && d.ctx) return btn('Download', 'download', function () { McA.util.downloadURL(fileURL(d.ctx, rel), rel.split('/').pop()); }, attrs);
    return btn('Download', 'download', function () { blobDownload(fallbackName, getText()); }, attrs);
  }
  function searchBox(id, onChange) {
    var inp = h('input', { type: 'search', class: 'input-c rsec-search', placeholder: 'Search', 'aria-label': 'Search ' + id, value: LOCAL.search[id] || '' });
    inp.value = LOCAL.search[id] || '';
    inp.addEventListener('input', McA.util.debounce(function () { LOCAL.search[id] = inp.value; onChange(); }, 180));
    return inp;
  }
  function segToggle(id, labels, isRaw) {
    var wrap = h('div', { class: 'seg-c', role: 'group', 'aria-label': 'View mode' });
    [[false, labels[0]], [true, labels[1]]].forEach(function (x) {
      var b = h('button', { type: 'button', 'aria-pressed': String(isRaw === x[0]), class: isRaw === x[0] ? 'on' : '', text: x[1] });
      b.addEventListener('click', function () {
        var raw = Object.assign({}, McA.store.get().ui.raw); raw[id] = x[0]; McA.dom.setUi({ raw: raw });
      });
      wrap.append(b);
    });
    return wrap;
  }
  function mark(text, q) {
    var frag = document.createDocumentFragment(); text = String(text);
    if (!q) { frag.append(text); return frag; }
    var lo = text.toLowerCase(), ql = q.toLowerCase(), i = 0, j;
    while ((j = lo.indexOf(ql, i)) !== -1) { if (j > i) frag.append(text.slice(i, j)); frag.append(h('mark', { text: text.slice(j, j + q.length) })); i = j + q.length; }
    if (i < text.length) frag.append(text.slice(i));
    return frag;
  }
  function note(text, cls) { return h('p', { class: 'rsec-note' + (cls ? ' ' + cls : ''), text: text }); }
  function tooLarge(d, rel) {
    var box = h('div', { class: 'banner' }, McA.icons.get('info', 18), h('span', { text: 'Too large to preview. Download the file.' }));
    if (rel && d.ctx) box.append(h('a', { class: 'btn secondary sm', href: fileURL(d.ctx, rel), download: rel.split('/').pop(), text: 'Download' }));
    return box;
  }
  function chip(text, kind) { return h('span', { class: 'badge-c ' + wl(kind, ['ok', 'err', 'warn', 'steel', 'mono'], ''), text: text }); }
  function table(cols, rows, caption) {
    return h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' }, h('caption', { class: 'sr-only', text: caption }),
      h('thead', null, h('tr', null, cols.map(function (c) { return h('th', { scope: 'col', text: c }); }))), h('tbody', null, rows)));
  }

  /* ── JSON tree (lossless) ──────────────────────────────────────────────── */
  function pkey(path) { return path.join('\u0001'); }
  function renderTree(root, secId, query) {
    var open = LOCAL.open[secId] || (LOCAL.open[secId] = {});
    var hits = query ? McA.jsontree.find(root, query) : [], anc = {}, hitSet = {};
    hits.forEach(function (x) { hitSet[pkey(x.path)] = true; for (var i = 0; i < x.path.length; i++) anc[pkey(x.path.slice(0, i))] = true; });
    var LIM = 200;
    function build(nd, path, depth) {
      var k = pkey(path), lab = nd.key === null ? 'root' : String(nd.key);
      if (nd.type !== 'object' && nd.type !== 'array') {
        var val = nd.type === 'string' ? nd.raw : (nd.type === 'number' ? nd.raw : String(nd.value));
        return h('div', { class: 'jt-leaf' + (hitSet[k] ? ' is-hit' : '') },
          nd.key !== null ? h('span', { class: 'jt-key' }, mark(lab, query), ':') : null, ' ',
          h('span', { class: 'jt-val t-' + wl(nd.type, ['string', 'number', 'boolean', 'null'], 'string') }, mark(val, query)));
      }
      var isOpen = open[k] !== undefined ? open[k] : (depth < 2);
      if (query && anc[k]) isOpen = true;
      var node = h('div', { class: 'jt-node' });
      var tog = h('button', { type: 'button', class: 'jt-tog', 'aria-expanded': String(isOpen) },
        McA.icons.get(isOpen ? 'chevron-down' : 'chevron-right', 14),
        nd.key !== null ? h('span', { class: 'jt-key' }, mark(lab, query), ':') : null, ' ',
        h('span', { class: 'jt-sum', text: McA.jsontree.summary(nd) }));
      node.append(tog);
      var kids = h('div', { class: 'jt-kids', role: 'group' });
      kids.hidden = !isOpen;
      var filled = false;
      function fill() {
        if (filled) return; filled = true;
        var n = Math.min(nd.children.length, LOCAL.more[k] || LIM);
        for (var i = 0; i < n; i++) { var c = nd.children[i]; kids.append(build(c, path.concat([c.key]), depth + 1)); }
        if (nd.children.length > n) kids.append(btn('Show ' + Math.min(LIM, nd.children.length - n) + ' more (of ' + (nd.children.length - n) + ' left)', null, function () {
          LOCAL.more[k] = n + LIM; var f = kids; f.replaceChildren(); filled = false; fill();
        }));
      }
      if (isOpen) fill();
      tog.addEventListener('click', function () {
        var now = tog.getAttribute('aria-expanded') !== 'true';
        open[k] = now; tog.setAttribute('aria-expanded', String(now)); kids.hidden = !now;
        tog.replaceChild(McA.icons.get(now ? 'chevron-down' : 'chevron-right', 14), tog.firstChild);
        if (now) fill();
      });
      node.append(kids);
      return node;
    }
    var box = h('div', { class: 'jt' }, build(root, [], 0));
    return { el: box, hits: hits.length };
  }
  function rawPre(text, q) { return h('pre', { class: 'rawtxt mono', tabindex: '0' }, mark(text, q || '')); }

  function codeView(text) {
    var lines = String(text).split('\n'), nums = [];
    for (var i = 1; i <= lines.length; i++) nums.push(i);
    return h('div', { class: 'code', tabindex: '0' }, h('pre', { class: 'code-ln', 'aria-hidden': 'true', text: nums.join('\n') }), h('pre', { class: 'code-tx', text: text }));
  }

  /* ── section renderers: (body, tools, d, sec) ──────────────────────────── */
  var R = {};

  function jsonSection(key, secId) {
    return function (body, tools, d) {
      var c = cats(d)[key] || {}, raw = !!d.s.ui.raw[secId], q = LOCAL.search[secId] || '';
      var rel = McA.registry.downloadRel(d.payload, secId);
      if (c.text === null || c.text === undefined) { body.append(tooLarge(d, rel)); tools.append(downloadBtn(d, rel, c.name || secId + '.json', function () { return ''; })); return; }
      var redraw = function () { McA.results.refresh(); };
      tools.append(searchBox(secId, redraw), segToggle(secId, ['Tree', 'Raw'], raw), copyBtn(function () { return c.text; }), downloadBtn(d, rel, c.name || secId + '.json', function () { return c.text; }));
      if (raw) { body.append(rawPre(c.text, q)); return; }
      var root = McA.jsontree.parse(c.text);
      if (root.type === 'error') {
        body.append(h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), h('span', { text: 'This file is not valid JSON (line ' + root.line + ', column ' + root.column + '): ' + root.message + '. Showing the raw text.' })));
        body.append(rawPre(c.text, q)); return;
      }
      var t = renderTree(root, secId, q);
      if (q) body.append(note(t.hits + ' match' + (t.hits === 1 ? '' : 'es') + ' for "' + q + '".'));
      body.append(t.el);
      body.append(note('Numbers are shown exactly as written in the file.', 'hint'));
    };
  }
  R.extraction = jsonSection('extraction', 'extraction');
  R.resolved = jsonSection('resolved', 'resolved');

  R.build_plan = function (body, tools, d) {
    var c = cats(d).build_plan || {}, raw = !!d.s.ui.raw.build_plan, q = LOCAL.search.build_plan || '';
    var rel = McA.registry.downloadRel(d.payload, 'build_plan');
    if (c.text === null || c.text === undefined) { body.append(tooLarge(d, rel)); return; }
    tools.append(searchBox('build_plan', function () { McA.results.refresh(); }), segToggle('build_plan', ['List', 'Raw'], raw), copyBtn(function () { return c.text; }), downloadBtn(d, rel, c.name || 'build_plan.json', function () { return c.text; }));
    if (raw) { body.append(rawPre(c.text, q)); return; }
    var root = McA.jsontree.parse(c.text);
    if (root.type !== 'object') { body.append(note('The build plan is not a JSON object. Showing raw text.', 'is-warn'), rawPre(c.text, q)); return; }
    var by = {}; root.children.forEach(function (n) { by[n.key] = n; });
    function scalar(k) { var n = by[k]; return n && n.type !== 'object' && n.type !== 'array' ? (n.type === 'string' ? n.value : n.raw) : null; }
    var facts = h('dl', { class: 'facts' });
    ['part', 'units', 'confidence'].forEach(function (k) { var v = scalar(k); if (v !== null) facts.append(h('div', null, h('dt', { text: k }), h('dd', { class: 'mono', text: v }))); });
    ['skipped_prohibited', 'needs_review'].forEach(function (k) {
      var n = by[k]; if (n && n.children) facts.append(h('div', null, h('dt', { text: k.replace('_', ' ') }), h('dd', { class: 'mono', text: n.children.length ? n.children.map(function (x) { return x.type === 'string' ? x.value : x.raw; }).join(', ') : 'none' })));
    });
    body.append(facts);
    var steps = by.steps;
    if (!steps || steps.type !== 'array') { body.append(note('No "steps" array found in the plan. Use Raw to read the file.', 'is-warn')); return; }
    body.append(h('p', { class: 'rsec-note', text: steps.children.length + ' operations, in build order.' }));
    var list = h('ol', { class: 'ops' });
    steps.children.forEach(function (st, i) {
      var f = {}; st.children.forEach(function (n) { f[n.key] = n; });
      function sv(k) { var n = f[k]; return n ? (n.type === 'string' ? n.value : (n.type === 'object' || n.type === 'array' ? '' : n.raw)) : ''; }
      var status = sv('status');
      var text = JSON.stringify(st.children.map(function (n) { return n.key + '=' + (n.raw || ''); })).toLowerCase();
      if (q && text.indexOf(q.toLowerCase()) === -1 && McA.jsontree.find(st, q).length === 0) return;
      var det = h('details', { class: 'op' });
      if (q) det.open = true;
      det.append(h('summary', null, h('span', { class: 'op-n mono', text: sv('seq') !== '' ? sv('seq') : String(i + 1) }), h('span', { class: 'op-t mono', text: sv('type') }),
        h('span', { class: 'op-d', text: sv('description') }), status ? chip(status, status === 'generated' ? 'ok' : (/fail|error|skip/i.test(status) ? 'err' : 'warn')) : null));
      var tree = renderTree(st, 'bp' + i, q);
      det.append(tree.el);
      list.append(h('li', null, det));
    });
    body.append(list);
  };

  R.verification = function (body, tools, d) {
    var c = cats(d), rep = c.verification || {}, mm = c.must_meet || {};
    var rel = McA.registry.downloadRel(d.payload, 'verification');
    var vd = d.extra.verdict;
    if (vd) body.append(h('p', { class: 'verdict' }, h('span', { class: 'cap-c', text: 'Verdict ' }), chip(McA.runstate.VERDICT_LABELS[vd] || vd, vd === 'passed' ? 'ok' : vd === 'failed' ? 'err' : vd === 'flags' ? 'warn' : 'steel')));
    else body.append(note('No live run is tied to this view, so no verdict is derived here. Read the checks and the report below.', 'hint'));
    if (mm.present && (mm.results || []).length) {
      var stage = mm.stage === 'post_build' ? 'Verified against the SolidWorks build' : 'Pre-validated (CadQuery); SolidWorks build pending';
      body.append(h('h3', { class: 'sub-h', text: 'Must-meet checks' }), note(stage + '.', 'hint'));
      var rows = mm.results.map(function (r) {
        var st = String(r.status || '');
        return h('tr', null, h('td', { class: 'mono', text: String(r.id) }), h('td', null, chip(st || '-', st === 'PASS' ? 'ok' : st === 'FAIL' ? 'err' : 'warn')),
          h('td', { class: 'mono', text: r.required === undefined ? '' : String(r.required) }), h('td', { class: 'mono', text: r.measured === undefined ? '' : String(r.measured) }),
          h('td', { text: r.detail === undefined ? '' : String(r.detail) }));
      });
      body.append(table(['Check', 'Status', 'Required', 'Measured', 'Detail'], rows, 'Must-meet checks'));
      if ((mm.failed || []).length) body.append(h('ul', { class: 'failed-list' }, mm.failed.map(function (f) { return h('li', null, McA.icons.get('x', 14), h('span', { text: String(f) })); })));
    }
    if (rep.present) {
      body.append(h('h3', { class: 'sub-h', text: 'Report' }));
      if (rep.text === null) body.append(tooLarge(d, rel)); else { body.append(rawPre(rep.text, '')); tools.append(copyBtn(function () { return rep.text; }), downloadBtn(d, rel, rep.name || 'verification_report.txt', function () { return rep.text; })); }
    }
  };

  R.flags = function (body, tools, d) {
    var rev = cats(d).review || {}, items = rev.items || [], raw = !!d.s.ui.raw.flags, filt = d.s.ui.flagsFilter || [];
    var counts = {}; SEV.forEach(function (x) { counts[x] = 0; });
    items.forEach(function (i) { if (counts[i.severity] !== undefined) counts[i.severity]++; });
    tools.append(segToggle('flags', ['Items', 'Raw'], raw), copyBtn(function () { return raw ? (rev.text || '') : JSON.stringify(items, null, 2); }));
    var saveWhy = h('span', { id: 'flags-save-why', class: 'reason', text: 'Not available: the server has no learning-loop endpoint (gap G3).' });
    var save = h('button', { type: 'button', class: 'btn secondary sm', 'aria-disabled': 'true', 'aria-describedby': 'flags-save-why', text: 'Save all to Learning Loop' });
    save.addEventListener('click', function (e) { e.preventDefault(); });
    body.append(h('div', { class: 'flags-bar' }, save, saveWhy));
    if (!items.length) { body.append(note('No assumptions or manual steps were recorded.')); return; }
    body.append(h('p', { class: 'rsec-note', text: items.length + ' item' + (items.length === 1 ? '' : 's') + ': ' + SEV.map(function (x) { return counts[x] + ' ' + x.toLowerCase(); }).join(' · ') + '. Most urgent first.' }));
    var chips = h('div', { class: 'flags-filter', role: 'group', 'aria-label': 'Filter by severity' });
    SEV.forEach(function (sv) {
      var on = filt.indexOf(sv) !== -1;
      var b = h('button', { type: 'button', class: 'fchip badge-sev ' + sv.toLowerCase() + (on ? ' on' : ''), 'aria-pressed': String(on), text: sv + ' ' + counts[sv] });
      b.addEventListener('click', function () {
        var cur = (McA.store.get().ui.flagsFilter || []).slice(), i = cur.indexOf(sv);
        if (i === -1) cur.push(sv); else cur.splice(i, 1);
        McA.dom.setUi({ flagsFilter: cur });
      });
      chips.append(b);
    });
    body.append(chips);
    if (raw) { body.append(rev.text ? rawPre(rev.text, '') : note('No raw review text for this run.')); return; }
    var show = function (i) { return !filt.length || filt.indexOf(i.severity) !== -1; };
    function item(i) {
      var sev = wl(i.severity, SEV, 'LOW');
      var st = i.status ? String(i.status) : '';
      return h('div', { class: 'flag-item sev-' + sev },
        h('div', { class: 'flag-head' }, h('span', { class: 'badge-sev ' + sev.toLowerCase(), text: sev }), h('span', { class: 'fid mono', text: (i.id || '') + (i.source ? ' · ' + i.source : '') }),
          st ? chip(st.replace(/_/g, ' '), /pass|met|ok/i.test(st) ? 'ok' : /fail|unmet/i.test(st) ? 'err' : 'warn') : null),
        [['What', i.what], ['Decision', i.decision], ['Why', i.why], ['Affects', i.affects]].map(function (r) { return r[1] ? h('div', { class: 'row' }, h('b', { text: r[0] }), ' ' + String(r[1])) : null; }));
    }
    function group(label, list) {
      list = list.filter(show);
      if (!list.length) return;
      if (label) body.append(h('h3', { class: 'flags-group', text: label }));
      list.forEach(function (i) { body.append(item(i)); });
    }
    var main = items.filter(function (i) { return i.source !== 'overview' && i.source !== 'requirement'; });
    group('', main);
    group('Overview Verification: features the overview drawing shows, checked against the build', items.filter(function (i) { return i.source === 'overview'; }));
    group('Human-Specified Requirements: applied during extraction and resolution, graded against the build', items.filter(function (i) { return i.source === 'requirement'; }));
    if (!items.filter(show).length) body.append(note('No items match the selected severities.'));
  };

  function textSection(key, secId, fname) {
    return function (body, tools, d) {
      var c = cats(d)[key] || {}, rel = McA.registry.downloadRel(d.payload, secId);
      if (c.text === null || c.text === undefined) { body.append(tooLarge(d, rel)); return; }
      tools.append(copyBtn(function () { return c.text; }), downloadBtn(d, rel, c.name || fname, function () { return c.text; }));
      body.append(rawPre(c.text, ''));
    };
  }
  R.model_check = textSection('model_check', 'model_check', 'model_check.txt');

  R.overview_analysis = function (body, tools, d) {
    var oa = cats(d).overview_analysis || {}, data = oa.data || {}, raw = !!d.s.ui.raw.overview_analysis;
    tools.append(segToggle('overview_analysis', ['Summary', 'Raw'], raw), copyBtn(function () { return JSON.stringify(data, null, 2); }));
    if (raw) { body.append(rawPre(JSON.stringify(data, null, 2), ''), note('Re-serialized from the parsed data; the original file is in Files.', 'hint')); return; }
    var conflicts = data.cross_view_conflicts || [];
    var nCrit = conflicts.filter(function (c) { return String(c.severity).toUpperCase() === 'CRITICAL'; }).length;
    body.append(h('p', null, conflicts.length ? chip(conflicts.length + ' conflict' + (conflicts.length === 1 ? '' : 's') + (nCrit ? ' · ' + nCrit + ' critical' : ''), 'err') : chip('views agree', 'ok')));
    if (data.overall_shape_summary) body.append(h('p', null, h('b', { text: 'Overall shape: ' }), data.overall_shape_summary));
    if ((data.views_detected || []).length) body.append(h('h3', { class: 'sub-h', text: 'Views detected' }), h('div', { class: 'vchips' }, data.views_detected.map(function (v) { return h('span', { class: 'badge-c mono', title: v.description || '', text: String(v.view_id) }); })));
    if (conflicts.length) {
      body.append(h('h3', { class: 'sub-h', text: 'Cross-view conflicts' }));
      conflicts.forEach(function (c) {
        var sev = wl(String(c.severity || 'MEDIUM').toUpperCase(), SEV, 'MEDIUM');
        body.append(h('div', { class: 'flag-item sev-' + sev }, h('div', { class: 'flag-head' }, h('span', { class: 'badge-sev ' + sev.toLowerCase(), text: sev })),
          h('div', { class: 'row', text: c.description || '' }), c.recommendation ? h('div', { class: 'row' }, h('b', { text: 'Recommendation ' }), c.recommendation) : null));
      });
    }
    function list(title, arr, fn) { if (arr && arr.length) body.append(h('h3', { class: 'sub-h', text: title }), h('ul', { class: 'plain' }, arr.map(function (x) { return h('li', { text: fn(x) }); }))); }
    list('Cross-view correspondences', data.cross_view_correspondences, function (x) { return x.feature + ' (' + (x.seen_in || []).join(' + ') + '): ' + (x.relation || ''); });
    list('Global notes', data.global_notes, function (n) { return '"' + n.note + '": ' + (n.applies_to || 'whole part') + (n.resolved_count != null ? ' (count: ' + n.resolved_count + ')' : ''); });
    if (data.symmetry && data.symmetry.type) body.append(h('h3', { class: 'sub-h', text: 'Symmetry' }), h('p', { text: data.symmetry.type + (data.symmetry.notes ? ': ' + data.symmetry.notes : '') }));
    /* marked regions (human ground truth) */
    if (d.ctx && d.ctx.kind === 'part') {
      var k = ctxKey(d.ctx), rc = regionsCache[k];
      if (!rc) { regionsCache[k] = { state: 'loading' }; McA.api.getRegions(d.ctx.session, d.ctx.part).then(function (r) { regionsCache[k] = { state: 'ok', regions: r.regions || [] }; McA.results.refresh(); }, function () { regionsCache[k] = { state: 'none', regions: [] }; McA.results.refresh(); }); }
      else if (rc.regions && rc.regions.length) {
        body.append(h('h3', { class: 'sub-h', text: 'Marked reference regions: human ground truth' }));
        var groups = {}, order = [];
        rc.regions.forEach(function (r) { var g = String(r.color || 'unassigned'); if (!groups[g]) { groups[g] = []; order.push(g); } groups[g].push(r); });
        order.forEach(function (g, gi) {
          var sw = h('span', { class: 'swatch' }); sw.style.setProperty('background', /^#[0-9a-fA-F]{3,8}$/.test(g) ? g : 'currentColor');
          body.append(h('div', { class: 'rg-mini' }, sw, h('div', null, h('b', { text: 'Group ' + (gi + 1) }), h('ul', { class: 'plain' }, groups[g].map(function (r) {
            var bb = r.boundingBox || {}, f = function (n) { return typeof n === 'number' ? n.toFixed(3) : '?'; };
            return h('li', null, (r.role || 'region') + (r.value ? ': ' : ''), r.value ? h('b', { text: String(r.value) }) : null, h('span', { class: 'mono hint', text: ' (x ' + f(bb.x) + ', y ' + f(bb.y) + ', w ' + f(bb.width) + ', h ' + f(bb.height) + ')' }));
          })))));
        });
      }
    }
  };

  R.macros = function (body, tools, d) {
    var files = (cats(d).macros || {}).files || [];
    if (!files.length) { body.append(note('The macro list is empty.')); return; }
    if (LOCAL.macroIdx >= files.length) LOCAL.macroIdx = 0;
    var cur = files[LOCAL.macroIdx];
    var tabs = h('div', { class: 'mtabs', role: 'tablist', 'aria-label': 'Macro files' });
    files.forEach(function (f, i) {
      var b = h('button', { type: 'button', role: 'tab', 'aria-selected': String(i === LOCAL.macroIdx), tabindex: i === LOCAL.macroIdx ? '0' : '-1', class: 'tab-c sm' + (i === LOCAL.macroIdx ? ' active' : ''), text: String(f.name).split('/').pop() });
      b.addEventListener('click', function () { LOCAL.macroIdx = i; McA.results.refresh(); });
      b.addEventListener('keydown', function (e) {
        var n = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0; if (!n) return;
        e.preventDefault(); LOCAL.macroIdx = (i + n + files.length) % files.length; McA.results.refresh(true);
      });
      tabs.append(b);
    });
    var rel = McA.registry.resolveFile(d.payload, cur.name);
    tools.append(copyBtn(function () { return cur.text || ''; }), downloadBtn(d, rel ? rel.name : null, String(cur.name).split('/').pop(), function () { return cur.text || ''; }));
    body.append(tabs);
    var panel = h('div', { role: 'tabpanel' });
    if (cur.text === null || cur.text === undefined) panel.append(tooLarge(d, rel ? rel.name : null)); else panel.append(codeView(cur.text));
    body.append(panel);
  };

  R.files = function (body, tools, d) {
    var c = cats(d), src = McA.registry.get('files').source(d.payload, d.extra), list = src.list;
    var rowsD = [
      ['SLDPRT', src.sldprt ? chip('Produced', 'ok') : chip('Not produced', 'steel'), src.sldprt ? '' : 'SolidWorks did not build a part for this output.'],
      ['STL', src.stl.present ? chip('Produced', 'ok') : chip('Not produced', 'steel'), src.stl.present ? 'Source: ' + (src.stl.source === 'solidworks' ? 'SolidWorks build' : src.stl.source === 'prevalidation' ? 'CadQuery pre-validation (not a SolidWorks build)' : (src.stl.source || 'unknown')) : ''],
      ['VBA macros', src.macroCount ? chip(src.macroCount + ' file' + (src.macroCount === 1 ? '' : 's'), 'ok') : chip('None', 'steel'), '']
    ];
    body.append(h('h3', { class: 'sub-h', text: 'Deliverables' }), table(['Deliverable', 'State', 'Note'], rowsD.map(function (r) { return h('tr', null, h('td', { text: r[0] }), h('td', null, r[1]), h('td', { text: r[2] })); }), 'Deliverables'));
    body.append(h('h3', { class: 'sub-h', text: 'All files (' + list.length + ')' }));
    if (!list.length) body.append(note('No output files yet.'));
    else {
      var rows = list.map(function (f) {
        return h('tr', null, h('td', { class: 'mono', text: f.name }), h('td', { class: 'num', text: McA.util.fmtBytes(f.size) }),
          h('td', null, d.ctx ? h('a', { class: 'btn ghost sm', href: fileURL(d.ctx, f.name), download: String(f.name).split('/').pop(), 'aria-label': 'Download ' + f.name }, McA.icons.get('download', 14), 'Download') : null));
      });
      body.append(table(['Path', 'Size', 'Download'], rows, 'Output files'));
    }
    var run = d.s.run;
    if (McA.run.zipAvailable(d.s)) tools.append(btn('Download all (.zip)', 'download', function () { McA.util.downloadURL(McA.api.runZipURL(run.id), (run.part || 'demo') + '.zip'); }));
    else tools.append(h('span', { class: 'hint', text: 'Zip needs a run started in this server session.' }));
    var p = d.payload || {};
    if (src.delivered || src.deliveredDownloads) {
      body.append(h('h3', { class: 'sub-h', text: 'Delivered folders' }));
      [['Output folder', src.delivered], ['Downloads folder', src.deliveredDownloads]].forEach(function (r) {
        if (r[1]) body.append(h('div', { class: 'deliv-row' }, h('span', { class: 'cap-c', text: r[0] }), h('code', { class: 'mono deliv-path', text: r[1] }), btn('Copy', 'copy', function () { McA.util.copyText(r[1]).then(toastCopy); })));
      });
    } else if (p.done) body.append(note('No delivery folder was reported for this run.', 'hint'));
  };

  R.cost = function (body, tools, d) {
    var u = cats(d).usage || {}, last = u.last_run || {}, raw = !!d.s.ui.raw.cost;
    tools.append(segToggle('cost', ['Summary', 'Ledger text'], raw), copyBtn(function () { return u.text || ''; }));
    if (raw) { body.append(u.text ? rawPre(u.text, '') : note('No ledger text.')); return; }
    function fmt(n) { return n === null || n === undefined ? '-' : Number(n).toLocaleString(); }
    function usd(n) { return n === null || n === undefined || isNaN(Number(n)) ? '-' : '$' + Number(n).toFixed(4); }
    function card(v, k, tag) { return h('div', { class: 'cost-card' }, h('div', { class: 'v mono', text: v }), h('div', { class: 'k', text: k }), tag ? h('span', { class: 'badge-c', text: tag }) : null); }
    var fallback = (u.rows || []).some(function (r) { return r.model_priced === false; });
    var estTag = fallback ? 'Estimated (fallback rate)' : 'Estimated by backend price table';
    body.append(h('div', { class: 'cost-cards' }, card(usd(u.total_cost_usd), 'Part total, all ledger entries for this part', estTag),
      u.session_total_cost_usd != null ? card(usd(u.session_total_cost_usd), 'Session total, all parts', estTag) : null,
      card(fmt(last.input_tokens), 'Input tokens, last run', 'Measured'), card(fmt(last.output_tokens), 'Output tokens, last run', 'Measured'),
      card(fmt(last.cache_read_tokens), 'Cache-read tokens, last run', 'Measured'), card(String(last.model || '-'), 'Model, as recorded', null)));
    var rows = (u.rows || []).map(function (r) {
      return h('tr', null, h('td', { class: 'mono', text: String(r.timestamp || '') }), h('td', { text: String(r.stage || '') }), h('td', { class: 'mono', text: String(r.model || '') }),
        ['input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'api_calls'].map(function (k) { return h('td', { class: 'num', text: fmt(r[k]) }); }),
        h('td', { text: r.cache_hit === undefined ? '' : String(r.cache_hit) }), h('td', { class: 'num', text: usd(r.cost_usd) + (r.model_priced === false ? ' (fallback)' : '') }));
    });
    if (rows.length) body.append(h('h3', { class: 'sub-h', text: 'Calls' }), table(['Time', 'Stage', 'Model', 'Input', 'Output', 'Cache read', 'Cache write', 'Calls', 'Cache hit', 'Cost (est.)'], rows, 'Token usage by call'));
    body.append(note('Tokens are measured by the provider response. Cost is computed by the backend from its own price table; this page holds no prices.', 'hint'));
  };

  /* console: stateful so new lines append without rebuilding */
  var CON = { box: null, shown: 0, key: '' };
  function consoleLines(d) {
    var src = McA.registry.get('console').source(d.payload, d.extra);
    if (src.source === 'live') return { lines: src.lines, live: true, name: null };
    if (src.tooLarge) return { lines: null, tooLarge: true };
    if (src.text) return { lines: src.text.replace(/\r\n/g, '\n').split('\n'), live: false, name: src.name };
    return { lines: [], live: false };
  }
  function lineNode(text, i, q) {
    var lv = wl(McA.logparse.level(text), ['stage', 'error', 'warning', 'info'], 'info');
    return h('div', { class: 'cl lv-' + lv }, h('span', { class: 'cl-n', 'aria-hidden': 'true', text: String(i + 1) }), h('span', { class: 'cl-t' }, mark(text, q)));
  }
  R.console = function (body, tools, d, sec, stateOnly) {
    var cl = consoleLines(d), filt = d.s.ui.consoleFilter || 'all', q = LOCAL.search.console || '';
    if (cl.tooLarge) { body.append(tooLarge(d, null)); return; }
    var all = cl.lines;
    var sel = h('select', { class: 'input-c rsec-sel', 'aria-label': 'Filter console lines' }, [['all', 'All lines'], ['stage', 'Stages'], ['warning', 'Warnings'], ['error', 'Errors']].map(function (o) { return h('option', { value: o[0], text: o[1], selected: filt === o[0] ? true : null }); }));
    sel.value = filt;
    sel.addEventListener('change', function () { McA.dom.setUi({ consoleFilter: sel.value }); });
    var follow = h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: LOCAL.follow ? true : null }), h('span', { text: 'Auto-scroll' }));
    follow.querySelector('input').checked = LOCAL.follow;
    follow.querySelector('input').addEventListener('change', function (e) { LOCAL.follow = e.target.checked; if (LOCAL.follow && CON.box) CON.box.scrollTop = CON.box.scrollHeight; });
    var relLog = (McA.registry.resolveFile(d.payload, 'ui_console.log') || {}).name || null;
    tools.append(searchBox('console', function () { McA.results.refresh(); }), sel, follow, copyBtn(function () { return all.join('\n'); }),
      relLog ? downloadBtn(d, relLog, 'ui_console.log', function () { return all.join('\n'); }) : btn('Download', 'download', function () { blobDownload('console.log', all.join('\n')); }));
    var box = h('div', { class: 'console-c con', tabindex: '0', role: 'log', 'aria-label': 'Console output' });
    CON.box = box;
    var LIM = 5000, ql = q.toLowerCase();
    var idx = [];
    for (var i = 0; i < all.length; i++) {
      if (filt !== 'all' && McA.logparse.level(all[i]) !== filt) continue;
      if (ql && all[i].toLowerCase().indexOf(ql) === -1) continue;
      idx.push(i);
    }
    var start = Math.max(0, idx.length - LIM - (LOCAL.more.console || 0));
    if (start > 0) box.append(btn('Show earlier lines (' + start + ' hidden)', null, function () { LOCAL.more.console = (LOCAL.more.console || 0) + 5000; McA.results.refresh(); }, { class: 'btn secondary sm con-more' }));
    var frag = document.createDocumentFragment();
    for (var j = start; j < idx.length; j++) frag.append(lineNode(all[idx[j]], idx[j], q));
    box.append(frag);
    body.append(h('p', { class: 'rsec-note hint', text: (cl.live ? 'Live stream' : 'Saved transcript' + (cl.name ? ' (' + cl.name + ')' : '')) + ' · showing ' + (idx.length - start) + ' of ' + all.length + ' lines' }), box);
    if (LOCAL.follow) requestAnimationFrame(function () { box.scrollTop = box.scrollHeight; });
  };

  R.events = function (body, tools, d) {
    var ev = McA.registry.get('events').source(d.payload, d.extra).events, kind = LOCAL.eventKind;
    var sel = h('select', { class: 'input-c rsec-sel', 'aria-label': 'Filter events by kind' }, [h('option', { value: 'all', text: 'All kinds' })].concat(McA.logparse.KINDS.map(function (k) { return h('option', { value: k, text: k }); })));
    sel.value = kind;
    sel.addEventListener('change', function () { LOCAL.eventKind = sel.value; McA.results.refresh(true); });
    var shown = ev.filter(function (e) { return kind === 'all' || e.kind === kind; });
    tools.append(sel, copyBtn(function () { return shown.map(function (e) { return e.index + '\t' + e.kind + '\t' + e.text; }).join('\n'); }));
    if (!shown.length) { body.append(note('No events of this kind.')); return; }
    body.append(table(['#', 'Kind', 'Event'], shown.map(function (e) {
      return h('tr', null, h('td', { class: 'num', text: String(e.index + 1) }), h('td', null, chip(e.kind, e.kind === 'error' ? 'err' : (e.kind === 'cancel' ? 'warn' : 'steel'))), h('td', { text: e.text + (e.severity ? ' [' + e.severity + ']' : '') }));
    }), 'Run events'));
  };

  /* overview */
  function getSummary(d) {
    if (d.runMatch && d.extra.summary) return { state: 'ok', row: d.extra.summary };
    if (!d.ctx || d.ctx.kind !== 'part') return { state: 'none', row: null };
    var k = ctxKey(d.ctx), c = summaryCache[k];
    if (c && c.stamp === (d.payload && d.payload.stl_mtime) + '|' + !!(d.payload && d.payload.has_any)) return c;
    if (!d.payload || !d.payload.has_any) return { state: 'none', row: null };
    var stamp = (d.payload.stl_mtime) + '|true';
    summaryCache[k] = { state: 'loading', row: null, stamp: stamp };
    fetch(McA.api.partFileURL(d.ctx.session, d.ctx.part, 'multiview_summary.csv')).then(function (r) { if (!r.ok) throw 0; return r.text(); })
      .then(function (t) { summaryCache[k] = { state: 'ok', row: McA.csv.summaryRow(t, d.ctx.part), stamp: stamp }; },
        function () { summaryCache[k] = { state: 'none', row: null, stamp: stamp }; })
      .then(function () { McA.results.refresh(); });
    return summaryCache[k];
  }
  R.overview = function (body, tools, d, sec) {
    var c = cats(d), src = sec.source(d.payload, d.extra), sm = getSummary(d), row = sm.row;
    var run = d.extra.runState;
    function block(title, q, content) { return h('section', { class: 'ov-block', 'aria-label': title }, h('h3', { text: title }), h('p', { class: 'ov-q', text: q }), content); }
    function line(k, v, cls) { return h('div', { class: 'ov-line' }, h('span', { class: 'k', text: k }), h('span', { class: 'v' + (cls ? ' ' + wl(cls, ['is-ok', 'is-warn', 'is-err', 'is-muted'], '') : ''), text: v })); }
    /* built */
    var built = h('div', null);
    if (run) built.append(line('Run state', McA.runstate.STATE_LABELS[run] || run, run === 'succeeded' ? 'is-ok' : run === 'failed' ? 'is-err' : run === 'succeeded_with_warnings' ? 'is-warn' : 'is-muted'));
    built.append(line('SolidWorks part (SLDPRT)', src.built.sldprt ? 'Yes' : 'No', src.built.sldprt ? 'is-ok' : 'is-muted'));
    var stl = src.built.stl;
    built.append(line('STL model', stl.present ? (stl.source === 'solidworks' ? 'Yes, built by SolidWorks' : 'Pre-validation model only (CadQuery); not a SolidWorks build') : 'No', stl.present ? (stl.source === 'solidworks' ? 'is-ok' : 'is-warn') : 'is-muted'));
    built.append(line('VBA macros', src.built.macros ? src.built.macros + ' file' + (src.built.macros === 1 ? '' : 's') : 'None', src.built.macros ? 'is-ok' : 'is-muted'));
    if (d.demo) built.append(note('Demo runs stop after the macro package. No SolidWorks build or verification happens.', 'hint'));
    /* match */
    var match = h('div', null);
    var verdict = d.extra.verdict;
    if (!verdict && row && !d.demo) verdict = McA.runstate.deriveVerdict({ summary: row, mustMeet: c.must_meet, stlSource: d.payload && d.payload.stl_source, stlFresh: !!(d.payload && d.payload.stl_source === 'solidworks'), kind: 'part' });
    var vl = verdict ? McA.runstate.VERDICT_LABELS[verdict] : 'Not available';
    match.append(line('Verification verdict', vl, verdict === 'passed' ? 'is-ok' : verdict === 'failed' ? 'is-err' : verdict === 'flags' ? 'is-warn' : 'is-muted'));
    if (!d.extra.verdict && verdict) match.append(note('Derived from the saved summary of the last output, not from a live run.', 'hint'));
    var mm = src.mustMeet, res = (mm && mm.results) || [];
    if (res.length) {
      var pass = res.filter(function (r) { return r.status === 'PASS'; }).length, fail = res.filter(function (r) { return r.status === 'FAIL'; }).length;
      match.append(line('Must-meet checks', pass + ' passed, ' + fail + ' failed, ' + (res.length - pass - fail) + ' other', fail ? 'is-err' : 'is-ok'));
    } else match.append(line('Must-meet checks', 'None recorded', 'is-muted'));
    if (sm.state === 'loading') match.append(note('Loading summary…', 'hint'));
    else if (row) {
      match.append(line('Summary status', String(row.status || ''), row.status === 'READY' ? 'is-ok' : 'is-warn'));
      ['macro_readiness', 'geometry_completeness', 'dimension_completeness', 'consistency', 'feature_confidence'].forEach(function (k) { if (row[k] !== undefined) match.append(line(k.replace(/_/g, ' '), String(row[k]) + ' (as reported)')); });
    } else if (d.demo) match.append(note('Demo runs produce no summary.', 'hint'));
    else if (d.ctx) match.append(note('No multiview_summary.csv was found for this output.', 'hint'));
    /* attention */
    var att = h('div', null), n = 0;
    function go(secId, text, kind) {
      n++; var b = h('button', { type: 'button', class: 'att-item', 'data-k': wl(kind, ['err', 'warn'], 'warn') }, McA.icons.get(kind === 'err' ? 'x' : 'warn', 14), h('span', { text: text }), h('span', { class: 'att-go', text: 'Open ' + secId }));
      b.addEventListener('click', function () { var m = McA.results.activeMount(); if (m) m.setSection(secId); });
      att.append(b);
    }
    ((mm && mm.failed) || []).forEach(function (f) { go('verification', String(f), 'err'); });
    var attN = 0;
    src.attention.forEach(function (f) { if (++attN > 5) return; go('flags', f.severity + ' ' + (f.id || '') + ': ' + (f.what || ''), f.severity === 'CRITICAL' ? 'err' : 'warn'); });
    if (attN > 5) att.append(note('+ ' + (attN - 5) + ' more critical or high flags. Open Engineering flags to see all.', 'hint'));
    src.conflicts.forEach(function (x) { go('overview_analysis', String(x.severity || '') + ' conflict: ' + (x.description || ''), String(x.severity).toUpperCase() === 'CRITICAL' ? 'err' : 'warn'); });
    if (row && (row.status === 'BLOCKED' || row.status === 'ERROR')) go('verification', row.status + ': ' + (row.detail || ''), 'err');
    if (run === 'failed' && !n) go('console', 'The run failed (exit ' + d.s.run.exit + '). Read the console.', 'err');
    if (!n) att.append(note('No critical or high flags, failed checks or conflicts were recorded. That is not proof the model is correct; check Verification.', 'hint'));
    body.append(h('div', { class: 'ov-grid' }, block('Did it build?', 'What the run produced.', built), block('Does it match?', 'What the checks say, as reported.', match), block('What needs attention?', 'Open the item to see the evidence.', att)));
  };

  /* ── frame ─────────────────────────────────────────────────────────────── */
  function srcLabel(id, d) {
    var c = cats(d), pick = function (k) { return c[k] && c[k].name ? c[k].name : ''; };
    switch (id) {
      case 'extraction': case 'resolved': case 'build_plan': case 'verification': case 'model_check': return pick(id === 'verification' ? 'verification' : id) || 'not produced';
      case 'overview_analysis': return pick('overview_analysis') || 'overview_analysis.json';
      case 'flags': return 'engineering review in build_plan.json';
      case 'macros': return ((c.macros && c.macros.files) || []).length + ' .vba files';
      case 'files': return 'outputs listing';
      case 'cost': return 'token_usage_log';
      case 'console': return d.extra.lines.length ? 'live stream' : (pick('console') || 'ui_console.log');
      case 'events': return 'parsed from console lines';
      case 'overview': return 'computed from the sections';
    }
    return '';
  }
  function frame(sec, d, condensed) {
    var st = secState(sec, d);
    var tag = condensed ? 'h3' : 'h2';
    var tools = h('div', { class: 'rsec-tools' });
    var body = h('div', { class: 'rsec-body' });
    var statusTxt = { none: 'No part selected', loading: 'Loading', error: 'Error', absent: 'Not available', present: 'Present' }[st];
    var el = h('section', { class: 'rsec', 'data-sec': sec.id, 'data-state': st, 'aria-labelledby': 'rsec-h-' + sec.id },
      h('header', { class: 'rsec-head' }, h(tag, { id: 'rsec-h-' + sec.id, text: sec.label }), h('span', { class: 'rsec-status st-' + st, text: statusTxt }),
        d.demo ? h('span', { class: 'badge-c', text: 'Demo' }) : null, st === 'present' ? h('span', { class: 'rsec-src mono', text: srcLabel(sec.id, d) }) : null, tools), body);
    if (st === 'none') body.append(h('div', { class: 'empty' }, McA.icons.get('results', 28), h('p', { class: 'empty-t', text: 'No part selected' }), h('p', { class: 'empty-d', text: 'Select a part or a run to see its results.' })));
    else if (st === 'loading') { for (var i = 0; i < 4; i++) body.append(h('div', { class: 'skel', style: 'width:' + (90 - i * 15) + '%' })); body.setAttribute('aria-busy', 'true'); }
    else if (st === 'error') {
      body.append(h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), h('span', { text: 'Could not load outputs: ' + d.error })));
      body.append(btn('Retry', 'refresh', function () { McA.dom.dispatch('outputs/load', {}); }, { class: 'btn secondary sm' }));
    } else if (st === 'absent') body.append(h('div', { class: 'empty' }, McA.icons.get(sec.id === 'files' ? 'folder' : 'file', 28), h('p', { class: 'empty-t', text: 'Not available' }), h('p', { class: 'empty-d', text: McA.registry.emptyText(sec.id, d.payload) })));
    else { try { R[sec.id](body, tools, d, sec); } catch (e) { body.append(h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), h('span', { text: 'This section could not be rendered: ' + (e && e.message) }))); if (window.console) console.error(e); } }
    return el;
  }

  /* ── mount ─────────────────────────────────────────────────────────────── */
  function mount(o) {
    var m = { mode: o.mode, destroyed: false };
    var condensed = o.mode === 'drawer';
    var navBtns = {};
    function buildNav() {
      o.nav.replaceChildren();
      if (condensed) {
        McA.registry.sections.forEach(function (sec) {
          var b = h('button', { type: 'button', class: 'res-link', role: 'tab', 'data-sec': sec.id, id: 'drs-' + sec.id }, h('span', { class: 'res-dot', 'aria-hidden': 'true' }), h('span', { text: sec.label }), h('span', { class: 'sr-only res-st' }));
          b.addEventListener('click', function () { m.setSection(sec.id); });
          b.addEventListener('keydown', function (e) {
            var ids = McA.registry.sections.map(function (x) { return x.id; }), i = ids.indexOf(sec.id), n = e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 0;
            if (!n) return; e.preventDefault(); var t = ids[(i + n + ids.length) % ids.length]; m.setSection(t); navBtns[t].focus();
          });
          navBtns[sec.id] = b; o.nav.append(b);
        });
      } else {
        McA.registry.GROUPS.forEach(function (g) {
          var ul = h('ul', null);
          McA.registry.inGroup(g.id).forEach(function (sec) {
            var b = h('button', { type: 'button', class: 'res-link', 'data-sec': sec.id }, h('span', { class: 'res-dot', 'aria-hidden': 'true' }), h('span', { text: sec.label }), h('span', { class: 'sr-only res-st' }));
            b.addEventListener('click', function () { m.setSection(sec.id); });
            navBtns[sec.id] = b; ul.append(h('li', null, b));
          });
          o.nav.append(h('div', { class: 'res-group' }, h('h3', { text: g.label }), ul));
        });
      }
    }
    m.setSection = function (id) { o.setSection(id); m.render(); };
    m.render = function (keepFocus) {
      if (m.destroyed || (o.isVisible && !o.isVisible())) return;
      var d = getData(), id = o.getSection(), sec = McA.registry.get(id) || McA.registry.sections[0];
      Object.keys(navBtns).forEach(function (k) {
        var on = k === sec.id, b = navBtns[k], s2 = McA.registry.get(k), st = secState(s2, d);
        if (condensed) { b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; if (on) b.setAttribute('aria-controls', 'dr-pane-body'); }
        else if (on) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current');
        b.setAttribute('data-st', st);
        b.querySelector('.res-st').textContent = ' ' + ({ present: 'present', absent: 'not available', loading: 'loading', error: 'error', none: 'no part' }[st]);
      });
      /* incremental console: keep the node and append */
      if (sec.id === 'console' && o.pane.firstChild && o.pane.firstChild.getAttribute && o.pane.firstChild.getAttribute('data-sec') === 'console' && o.pane.firstChild.getAttribute('data-state') === 'present' && secState(sec, d) === 'present' && CON.box && o.pane.contains(CON.box) && CON.sig) {
        var cl = consoleLines(d), sig = [d.s.ui.consoleFilter, LOCAL.search.console, LOCAL.more.console].join('|');
        if (cl.lines && sig === CON.sig && cl.lines.length >= CON.n && cl.live === CON.live && CON.n > 0) {
          var f = d.s.ui.consoleFilter || 'all', ql = (LOCAL.search.console || '').toLowerCase();
          var frag = document.createDocumentFragment();
          for (var i = CON.n; i < cl.lines.length; i++) {
            if (f !== 'all' && McA.logparse.level(cl.lines[i]) !== f) continue;
            if (ql && cl.lines[i].toLowerCase().indexOf(ql) === -1) continue;
            frag.append(lineNode(cl.lines[i], i, LOCAL.search.console || ''));
          }
          if (frag.childNodes.length) { CON.box.append(frag); while (CON.box.querySelectorAll('.cl').length > 5000 + (LOCAL.more.console || 0)) CON.box.removeChild(CON.box.querySelector('.cl')); if (LOCAL.follow) CON.box.scrollTop = CON.box.scrollHeight; }
          CON.n = cl.lines.length;
          var cnt = o.pane.querySelector('.rsec-note.hint'); if (cnt && cl.live) cnt.textContent = 'Live stream · ' + cl.lines.length + ' lines';
          return;
        }
      }
      var focusSel = keepFocus && document.activeElement && o.pane.contains(document.activeElement) ? document.activeElement.className : null;
      var scroll = o.scroller ? o.scroller.scrollTop : 0;
      var node = frame(sec, d, condensed);
      o.pane.replaceChildren(node);
      o.pane.setAttribute('aria-live', 'off');
      if (sec.id === 'console') { var c0 = consoleLines(d); CON.sig = [d.s.ui.consoleFilter, LOCAL.search.console, LOCAL.more.console].join('|'); CON.n = c0.lines ? c0.lines.length : 0; CON.live = c0.live; }
      if (o.scroller && sec.id !== 'console') o.scroller.scrollTop = scroll;
      if (focusSel && node.querySelector('.' + focusSel.split(' ')[0])) { var t = node.querySelector('.' + focusSel.split(' ')[0]); if (t && t.focus) t.focus(); }
    };
    m.destroy = function () { m.destroyed = true; mounts = mounts.filter(function (x) { return x !== m; }); (m.unsubs || []).forEach(function (u) { u(); }); };
    buildNav();
    var sched = McA.util.debounce(function () { m.render(true); }, 200);
    m.schedule = sched;
    var St = McA.store;
    m.unsubs = [
      St.subscribe(function (s) { return s.outputs; }, function () { sched(); }),
      St.subscribe(function (s) { return s.ui.raw; }, function () { m.render(); }),
      St.subscribe(function (s) { return s.ui.flagsFilter; }, function () { m.render(); }),
      St.subscribe(function (s) { return s.ui.consoleFilter; }, function () { m.render(); }),
      St.subscribe(function (s) { return s.run.state + '|' + s.run.verdict + '|' + (s.run.summary ? 1 : 0); }, function () { sched(); }),
      St.subscribe(function (s) { return s.run.lines; }, function () { var id = o.getSection(); if (id === 'console' || id === 'events') sched(); })
    ];
    mounts.push(m);
    return m;
  }

  McA.results = {
    mount: mount,
    refresh: function (keepFocus) { mounts.forEach(function (m) { m.render(keepFocus); }); },
    activeMount: function () { var vis = mounts.filter(function (m) { return m.mode === 'page'; }); return vis[0] || mounts[0]; },
    init: function () {
      var nav = document.querySelector('#dr-results .dr-secs'), pane = document.querySelector('#dr-results .dr-pane');
      if (!nav || !pane) return;
      pane.id = 'dr-pane-body'; pane.setAttribute('aria-labelledby', 'dr-mode-results'); pane.tabIndex = -1;
      var m = mount({ mode: 'drawer', nav: nav, pane: pane, scroller: pane,
        getSection: function () { return McA.store.get().ui.drawerSection || 'overview'; },
        setSection: function (id) { McA.dom.setUi({ drawerSection: id }); },
        isVisible: function () { var u = McA.store.get().ui; return !!u.drawerOpen && (u.drawerMode !== 'tools' || window.matchMedia('(min-width: 1250px)').matches); } });
      ['drawerOpen', 'drawerMode', 'drawerSection'].forEach(function (k) { McA.store.subscribe(function (s) { return s.ui[k]; }, function () { m.render(); }); });
      m.render();
    }
  };
})();
