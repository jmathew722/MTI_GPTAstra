/* Scoring tab: overview, part results, methodology, worked example, part detail.
   Everything shown is read from the server. The score is computed only by the pipeline's scorer (free, no API calls);
   this page never grades. Missing evidence is "Incomplete", never a zero; failed generation and failed scoring are
   different states; the average counts completed valid scores only. The worked example is labelled illustrative. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  McA.pages = McA.pages || {};
  var $ = function (id) { return document.getElementById(id); };
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var SV;
  var TABS = [['overview', 'Overview'], ['results', 'Part results'], ['method', 'Scoring methodology'], ['example', 'Worked example']];
  var st = { tab: 'overview', ov: null, meth: null, methErr: '', err: '', q: '', detail: null, detailRec: null, busy: {}, exportStep: false, loading: false };

  function api() { return McA.api; }
  function errText(e) { return (e && (e.detail || e.message)) || String(e || 'error'); }
  function empty(icon, title, text) { return h('div', { class: 'empty' }, h('span', { class: 'empty-ic' }, McA.icons.get(icon, 30)), h('p', { class: 'empty-t', text: title }), h('p', { class: 'empty-d', text: text })); }
  function chip(label, tone) { return h('span', { class: 'badge-c' + (tone ? ' ' + tone : ''), text: label }); }
  function fmtTime(iso) { try { return iso ? new Date(iso).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : SV.DASH; } catch (e) { return SV.DASH; } }

  /* ── data ─────────────────────────────────────────────────────────────── */
  function load() {
    st.loading = true; render();
    return api().scoringOverview().then(function (o) { st.ov = o; st.err = ''; }, function (e) { st.err = errText(e); })
      .then(function () { st.loading = false; render(); });
  }
  function loadMethod() {
    if (st.meth || st.methErr) return Promise.resolve();
    return api().scoringMethodology().then(function (m) { st.meth = m; }, function (e) { st.methErr = errText(e); }).then(render);
  }
  function openDetail(part) {
    st.detail = part; st.detailRec = null; render();
    api().scoringPart(part).then(function (d) { if (st.detail === part) { st.detailRec = d; render(); } },
      function (e) { if (st.detail === part) { st.detailRec = { error: errText(e) }; render(); } });
  }
  function evaluate(parts) {
    var names = parts.filter(function (p) { return !st.busy[p]; });
    if (!names.length) return Promise.resolve();
    names.forEach(function (p) { st.busy[p] = true; }); render();
    return api().scoringEvaluate(names, st.exportStep).then(function (r) {
      var done = (r.results || []).filter(function (x) { return x.state === 'scored'; }).length;
      var inc = (r.results || []).filter(function (x) { return x.state === 'incomplete'; }).length;
      var bad = (r.results || []).filter(function (x) { return x.state === 'scoring_failed'; }).length;
      McA.toast.show('Evaluated ' + names.length + ': ' + done + ' scored' + (inc ? ', ' + inc + ' incomplete' : '') + (bad ? ', ' + bad + ' failed' : '') + '.', bad ? 'warn' : 'ok');
    }, function (e) { McA.toast.show('Scoring could not run: ' + errText(e), 'err'); })
      .then(function () { names.forEach(function (p) { delete st.busy[p]; }); return load(); })
      .then(function () { if (st.detail) openDetail(st.detail); });
  }

  /* ── tabs ─────────────────────────────────────────────────────────────── */
  function renderTabs() {
    var bar = h('div', { class: 'sc-tabs', role: 'tablist', 'aria-label': 'Scoring sections' });
    TABS.forEach(function (t, i) {
      var b = h('button', { class: 'sc-tab', type: 'button', role: 'tab', id: 'sc-tab-' + t[0], 'aria-selected': String(st.tab === t[0]), 'aria-controls': 'sc-panel',
        tabindex: st.tab === t[0] ? '0' : '-1', text: t[1] });
      b.addEventListener('click', function () { st.tab = t[0]; st.detail = null; if (t[0] === 'method' || t[0] === 'example') loadMethod(); render(); });
      b.addEventListener('keydown', function (e) {
        var j = e.key === 'ArrowRight' ? (i + 1) % TABS.length : e.key === 'ArrowLeft' ? (i + TABS.length - 1) % TABS.length : -1;
        if (j < 0) return; e.preventDefault(); st.tab = TABS[j][0]; st.detail = null; if (st.tab === 'method' || st.tab === 'example') loadMethod(); render();
        var nb = $('sc-tab-' + st.tab); if (nb) nb.focus();
      });
      bar.append(b);
    });
    return bar;
  }

  /* ── overview ─────────────────────────────────────────────────────────── */
  function stat(label, value, sub) { return h('div', { class: 'sc-stat' }, h('div', { class: 'sc-stat-l', text: label }), h('div', { class: 'sc-stat-v', text: value }), sub ? h('div', { class: 'sc-stat-s', text: sub }) : null); }
  function renderOverview() {
    var o = st.ov, s = o.summary || {};
    var pend = (s.pending || 0) + (s.incomplete || 0);
    var wrap = h('div', null,
      h('div', { class: 'sc-stats' },
        stat('Scored parts', String(s.scored || 0), 'of ' + (s.parts || 0) + ' with output'),
        stat('Pending evaluations', String(pend), (s.pending || 0) + ' not evaluated · ' + (s.incomplete || 0) + ' incomplete' + (s.scoring_failed ? ' · ' + s.scoring_failed + ' failed' : '')),
        stat('Average score', SV.avgText(s.average), s.scored ? 'completed valid scores only' : 'no completed scores yet'),
        stat('Rubric version', o.version || SV.DASH, 'fingerprint of the scorer configuration')),
      h('p', { class: 'sc-note', text: 'Scores come from the pipeline scorer (no API calls, no cost). Open Part results to evaluate parts and see each criterion.' }));
    var noKey = (o.parts || []).filter(function (r) { return r.state === 'incomplete'; });
    if (noKey.length) wrap.append(h('div', { class: 'banner is-info', role: 'note' }, McA.icons.get('info', 18),
      noKey.length + ' part' + (noKey.length === 1 ? ' has' : 's have') + ' no signed answer key, so there is nothing to grade against. They are Incomplete, not zero.'));
    return wrap;
  }

  /* ── part results ─────────────────────────────────────────────────────── */
  function renderResults() {
    var o = st.ov, s = McA.store.get();
    var q = h('input', { class: 'input-c sc-search', type: 'search', placeholder: 'Search parts, status or run id', 'aria-label': 'Search part results', value: st.q });
    q.addEventListener('input', function () { st.q = q.value; var pos = q.selectionStart; render(); var nq = document.querySelector('.sc-search'); if (nq) { nq.focus(); try { nq.setSelectionRange(pos, pos); } catch (e) { /* ignore */ } } });
    var rows = SV.filter(o.parts || [], st.q);
    var wrap = h('div', null,
      h('div', { class: 'sc-tools' }, q,
        h('label', { class: 'chk' }, h('input', { type: 'checkbox', id: 'sc-export', checked: st.exportStep ? 'checked' : null, onchange: function (e) { st.exportStep = e.target.checked; } }),
          h('span', { text: 'Export the part through SolidWorks if it has no STEP yet (SolidWorks must be running)' }))));
    if (!rows.length) { wrap.append(empty('search', (o.parts || []).length ? 'No matches' : 'No parts yet', (o.parts || []).length ? 'No part matches that search.' : 'Parts appear here once they are created and run.')); return wrap; }
    var body = rows.map(function (r) {
      var bs = s.batch && s.batch.results ? s.batch.results[r.part] : undefined;
      var status = SV.statusOf(r, bs);
      var block = SV.evalBlocker(r);
      var evalBtn = h('button', { class: 'btn secondary sm', type: 'button', text: st.busy[r.part] ? 'Evaluating…' : (r.state === 'scored' || r.state === 'incomplete' || r.state === 'scoring_failed' ? 'Re-evaluate' : 'Evaluate'),
        disabled: (block || st.busy[r.part]) ? 'disabled' : null, title: block || '' });
      evalBtn.addEventListener('click', function () { evaluate([r.part]); });
      return h('tr', { 'data-part': r.part },
        h('td', null, h('strong', { text: r.part })),
        h('td', { class: 'num', text: McA.projectorder ? McA.projectorder.fmtWhen(r.last_activity) : '' }),
        h('td', { class: 'num sc-score', text: SV.scoreText(r) }),
        h('td', null, chip(status.label, status.tone), r.stale_rubric ? chip('Rubric changed', 'warn') : null, (r.flags && r.flags.length) ? chip('Check result', 'warn') : null),
        h('td', { class: 'num', text: SV.practicesText(r) }),
        h('td', null, h('div', { class: 'acts' },
          h('button', { class: 'btn ghost sm', type: 'button', text: 'Details', onclick: function () { openDetail(r.part); } }), evalBtn)));
    });
    wrap.append(h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl sc-tbl' },
      h('caption', { class: 'sr-only', text: 'Part results' }),
      h('thead', null, h('tr', null, ['Part', 'Last run', 'Score', 'Status', 'MTI practices', 'Actions'].map(function (t) { return h('th', { scope: 'col', text: t }); }))),
      h('tbody', null, body))));
    return wrap;
  }

  /* ── part detail ──────────────────────────────────────────────────────── */
  function renderDetail() {
    var part = st.detail, d = st.detailRec;
    var back = h('button', { class: 'btn ghost sm', type: 'button', text: '← All parts', onclick: function () { st.detail = null; st.tab = 'results'; render(); } });
    var wrap = h('div', { class: 'sc-detail' }, back, h('h2', { class: 'sec-h', text: part }));
    if (!d) { wrap.append(h('p', { class: 'reason', text: 'Loading the stored evaluation…' })); return wrap; }
    if (d.error) { wrap.append(h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), 'Could not load the evaluation: ' + d.error)); return wrap; }
    var rec = d.latest;
    if (!rec) { wrap.append(empty('scoring', 'Not evaluated yet', 'Press Evaluate on Part results. Nothing has been scored for this part, and no score is assumed.')); return wrap; }
    var status = SV.statusOf({ state: rec.state, exact: rec.exact });
    wrap.append(h('div', { class: 'sc-stats' },
      stat('Final score', rec.state === 'scored' ? SV.scoreText({ state: 'scored', score: rec.score }) : SV.DASH, rec.state === 'scored' ? (rec.exact ? 'exact: every feature within tolerance' : 'not exact') : status.label),
      stat('Evaluation', status.label, 'evaluated ' + fmtTime(rec.evaluated_at)),
      stat('Rubric version', rec.rubric_version || SV.DASH, rec.key_kind ? 'answer key: ' + rec.key_kind : ''),
      stat('Run', rec.run_id || SV.DASH, 'the run this evaluation belongs to')));
    if (rec.state === 'incomplete') wrap.append(h('div', { class: 'banner is-info', role: 'note' }, McA.icons.get('info', 18), (rec.reason || 'Not scored') + '. ' + (rec.explanation || '') + ' Missing evidence is never scored as 0 or 100.'));
    if (rec.state === 'scoring_failed') wrap.append(h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), 'Scoring failed: ' + (rec.error || 'unknown error') + '. This is a scoring error, not a failed model.'));
    (rec.consistency_flags || []).forEach(function (f) { wrap.append(h('div', { class: 'banner is-warn', role: 'alert' }, McA.icons.get('warn', 18), 'Inconsistent result: ' + f)); });
    if (rec.rubric_version && st.ov && rec.rubric_version !== st.ov.version) wrap.append(h('div', { class: 'banner is-info', role: 'note' }, McA.icons.get('info', 18), 'This score used rubric ' + rec.rubric_version + '. The current rubric is ' + st.ov.version + '. The stored score is kept; use Re-evaluate to score with the current rubric.'));
    if (rec.state === 'scored') {
      var aw = {}; SV.awarded(rec).forEach(function (a) { aw[a.id] = a; });
      var rows = SV.breakdown(rec).map(function (r) {
        var a = aw[r.id] || {};
        return h('tr', null, h('td', { class: 'mono', text: r.id }), h('td', { text: r.type }), h('td', { class: 'num', text: r.weight === null ? SV.DASH : String(r.weight) }),
          h('td', null, chip(r.status === 'missing' ? 'Missing' : 'Matched', r.status === 'missing' ? 'err' : 'ok')),
          h('td', { class: 'num', text: r.position }), h('td', { class: 'num', text: r.size }), h('td', { class: 'num', text: r.depth }), h('td', { class: 'num', text: r.kind }),
          h('td', { class: 'num', text: a.max == null ? SV.DASH : a.awarded.toFixed(2) + ' / ' + a.max.toFixed(2) }),
          h('td', { text: r.blame ? r.blame + (r.reason ? ': ' + r.reason : '') : (r.lost > 0.005 ? r.reason : '') }));
      });
      wrap.append(h('h3', { class: 'sec-h', text: 'Criterion breakdown' }),
        h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' },
          h('caption', { class: 'sr-only', text: 'Awarded points per feature' }),
          h('thead', null, h('tr', null, ['Feature', 'Type', 'Weight', 'Match', 'Position', 'Size', 'Depth', 'Type credit', 'Points awarded', 'Deductions and reason'].map(function (t) { return h('th', { scope: 'col', text: t }); }))),
          h('tbody', null, rows))));
      var ex = rec.extras || [];
      if (ex.length) wrap.append(h('h3', { class: 'sec-h', text: 'Extra features (deductions)' }), h('ul', { class: 'dlg-list' }, ex.map(function (x) { return h('li', { class: 'mono', text: x.feature_id + ' (' + x.type + '): −' + (+x.points_lost).toFixed(2) + ' pts' + (x.blame ? ', blamed on ' + (x.blame.stage || x.blame) : '') }); })));
      var roll = SV.stageRollup(rec);
      if (roll.length) wrap.append(h('h3', { class: 'sec-h', text: 'Where points were lost' }), h('ul', { class: 'dlg-list' }, roll.map(function (x) { return h('li', null, h('strong', { text: x.stage }), ' −' + x.points + ' pts'); })));
      if ((rec.unresolved || []).length) wrap.append(h('h3', { class: 'sec-h', text: 'Open questions the planner did not guess' }), h('ul', { class: 'dlg-list' }, rec.unresolved.map(function (u) { return h('li', { text: (u.id ? u.id + ': ' : '') + (u.question || '') }); })));
      if (rec.practices && rec.practices.rows) {
        wrap.append(h('h3', { class: 'sec-h', text: 'MTI practices (separate score, never blended)' }),
          h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' }, h('caption', { class: 'sr-only', text: 'MTI practices checks' }),
            h('thead', null, h('tr', null, ['Check', 'Practice', 'Credit', 'Note'].map(function (t) { return h('th', { scope: 'col', text: t }); }))),
            h('tbody', null, rec.practices.rows.map(function (p) { return h('tr', null, h('td', { class: 'mono', text: p.id }), h('td', { text: p.name }), h('td', { class: 'num', text: p.applicable === false ? 'n/a' : Math.round((p.credit || 0) * 100) + '%' }), h('td', { text: p.reason || '' })); })))));
      }
    }
    var ev = rec.evidence || {};
    var evRows = [['Generated STEP', ev.generated_step || rec.generated], ['Extraction found', ev.extraction_found == null ? null : String(ev.extraction_found)], ['Pose rotation', ev.pose_rotation == null ? null : JSON.stringify(ev.pose_rotation)], ['Pose translation', ev.pose_translation == null ? null : JSON.stringify(ev.pose_translation)]].filter(function (r) { return r[1]; });
    if (evRows.length) wrap.append(h('h3', { class: 'sec-h', text: 'Evidence' }), h('dl', { class: 'sc-kv' }, evRows.map(function (r) { return [h('dt', { text: r[0] }), h('dd', { class: 'mono', text: String(r[1]) })]; }).reduce(function (a, b) { return a.concat(b); }, [])));
    if ((d.history || []).length > 1) wrap.append(h('h3', { class: 'sec-h', text: 'Evaluation history (kept, never overwritten)' }),
      h('ul', { class: 'dlg-list' }, d.history.slice().reverse().map(function (x) { return h('li', null, fmtTime(x.evaluated_at) + ' · ' + x.rubric_version + ' · ' + (x.state === 'scored' ? SV.scoreText({ state: 'scored', score: x.score }) : x.state)); })));
    return wrap;
  }

  /* ── methodology and example ──────────────────────────────────────────── */
  function renderMethod() {
    if (st.methErr) return h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), 'The scoring methodology could not be loaded: ' + st.methErr);
    if (!st.meth) return h('p', { class: 'reason', text: 'Loading the methodology…' });
    var m = st.meth.methodology;
    var tbl = function (cap, heads, rows) { return h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' }, h('caption', { class: 'sr-only', text: cap }), h('thead', null, h('tr', null, heads.map(function (t) { return h('th', { scope: 'col', text: t }); }))), h('tbody', null, rows))); };
    return h('div', { class: 'sc-method' },
      h('p', { class: 'sc-note', text: 'Source: ' + m.source + '. Version ' + m.version + '. Total possible: ' + m.total_possible + ' points.' }),
      h('h3', { class: 'sec-h', text: 'Formula' }), h('p', { class: 'mono sc-formula', text: m.formula }), h('p', { class: 'mono sc-formula', text: m.feature_formula }), h('p', { class: 'mono sc-formula', text: m.credit_formula }),
      h('h3', { class: 'sec-h', text: 'Criteria' }),
      tbl('Scoring criteria', ['Criterion', 'Weight (share)', 'Evaluation method', 'Deductions'], m.criteria.map(function (c) { return h('tr', null, h('td', null, h('strong', { text: c.id })), h('td', { class: 'num', text: Math.round(c.share * 100) + '%' }), h('td', { text: c.method }), h('td', { text: c.deduction })); })),
      h('h3', { class: 'sec-h', text: 'Credit within and past tolerance (e = error / tolerance)' }),
      tbl('Credit curve', ['e', 'Credit'], m.credit_curve.map(function (c) { return h('tr', null, h('td', { class: 'num', text: String(c.e) }), h('td', { class: 'num', text: c.credit.toFixed(3) })); })),
      h('h3', { class: 'sec-h', text: 'Feature importance (tier weights)' }),
      tbl('Tier weights', ['Feature type', 'Tier weight'], m.tiers.map(function (t) { return h('tr', null, h('td', { text: t.type }), h('td', { class: 'num', text: String(t.weight) })); })),
      h('h3', { class: 'sec-h', text: 'Thresholds and rules' }),
      h('ul', { class: 'dlg-list' }, [
        'Size factor floor: ' + m.thresholds.size_floor + '. Weight = tier × clamp(√(feature size / part size), floor, 1).',
        'Missing feature: ' + m.thresholds.missing_feature + '. Extra feature: ' + m.thresholds.extra_feature + '.',
        'Match gate: ' + m.thresholds.match_gate + '.',
        'Fallback tolerance: ±' + m.thresholds.tolerance_fallback.inch + ' in / ±' + m.thresholds.tolerance_fallback.mm + ' mm when the drawing states none.',
        m.rounding, m.practices.note,
        m.unsupported_types.length ? 'Not expressible today (blamed as unsupported): ' + m.unsupported_types.join(', ') + '.' : null,
      ].filter(Boolean).map(function (t) { return h('li', { text: t }); })));
  }
  function renderExample() {
    if (st.methErr) return h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), 'The worked example could not be loaded: ' + st.methErr);
    if (!st.meth) return h('p', { class: 'reason', text: 'Loading the worked example…' });
    var x = st.meth.example, p = x.part;
    return h('div', { class: 'sc-example' },
      h('div', { class: 'banner is-info', role: 'note' }, McA.icons.get('info', 18), h('strong', { text: x.label + '. ' }), 'The numbers below are computed from the live rubric for an imaginary plate. They are not measured results of any part.'),
      h('p', { class: 'sc-note', text: 'Plate: a base body plus ' + p.holes + ' through holes of Ø' + p.hole_diameter_in + ' in on a ' + p.part_size_in + ' in part; position tolerance ±' + p.position_tolerance_in + ' in. Weights: base body ' + p.base_body_weight + ', each through hole ' + p.through_hole_weight + '.' }),
      h('p', { class: 'mono sc-formula', text: x.arithmetic }),
      h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' }, h('caption', { class: 'sr-only', text: 'Worked example cases' }),
        h('thead', null, h('tr', null, ['Case', 'Position', 'Size', 'Depth', 'Type', 'Feature credit', 'Points lost', 'Score', 'Exact'].map(function (t) { return h('th', { scope: 'col', text: t }); }))),
        h('tbody', null, x.cases.map(function (c) {
          var a = c.attribute_credits || {}, f = function (k) { return a[k] === undefined ? SV.DASH : a[k].toFixed(2); };
          return h('tr', null, h('td', { text: c.case }), h('td', { class: 'num', text: f('position') }), h('td', { class: 'num', text: f('size') }), h('td', { class: 'num', text: f('depth') }), h('td', { class: 'num', text: f('type') }),
            h('td', { class: 'num', text: c.feature_credit.toFixed(3) }), h('td', { class: 'num', text: c.points_lost.toFixed(3) }), h('td', { class: 'num', text: c.score.toFixed(2) }), h('td', { text: c.exact ? 'Yes' : 'No' }));
        })))));
  }

  /* ── page ─────────────────────────────────────────────────────────────── */
  function render() {
    var body = $('sc-body'); if (!body) return;
    var lede = $('sc-lede'), all = $('sc-eval-all');
    var active = document.activeElement, keepId = active && active.id;
    body.replaceChildren();
    if (st.loading && !st.ov) { body.append(h('p', { class: 'reason', text: 'Loading scores…' })); return; }
    if (st.err) { body.append(h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), 'Could not load scoring: ' + st.err)); lede.textContent = ''; all.setAttribute('aria-disabled', 'true'); return; }
    if (!st.ov) return;
    lede.textContent = 'Geometry score 0 to 100 against a signed answer key, plus a separate MTI practices score. Rubric ' + st.ov.version + '.';
    var evaluable = (st.ov.parts || []).filter(function (r) { return r.has_output; });
    all.setAttribute('aria-disabled', String(!evaluable.length));
    all.title = evaluable.length ? '' : 'Run a part first: there is no output to score.';
    if (st.detail) { body.append(renderDetail()); return; }
    body.append(renderTabs());
    var panel = h('div', { id: 'sc-panel', role: 'tabpanel', 'aria-labelledby': 'sc-tab-' + st.tab, class: 'sc-panel' });
    panel.append(st.tab === 'overview' ? renderOverview() : st.tab === 'results' ? renderResults() : st.tab === 'method' ? renderMethod() : renderExample());
    body.append(panel);
    if (keepId) { var again = $(keepId); if (again && again !== document.activeElement) again.focus(); }
  }

  McA.pages.scoring = {
    init: function () {
      SV = McA.scoringview;
      var all = $('sc-eval-all');
      if (all) all.addEventListener('click', function () {
        if (all.getAttribute('aria-disabled') === 'true') return;
        var parts = ((st.ov && st.ov.parts) || []).filter(function (r) { return r.has_output; }).map(function (r) { return r.part; });
        McA.dialog.confirm('Evaluate ' + parts.length + ' part' + (parts.length === 1 ? '' : 's') + '?', 'Scoring is free (no API calls). Each result is added to the part\'s history; earlier scores are kept.', 'Evaluate').then(function (ok) { if (ok) evaluate(parts); });
      });
      McA.store.subscribe(function (s) { return s.run.state; }, function (state) { if (McA.router.current() === 'scoring' && /^(succeeded|failed|cancelled)/.test(state)) setTimeout(load, 1500); });
      render();
    },
    enter: function () { st.detail = null; load(); if (st.tab === 'method' || st.tab === 'example') loadMethod(); },
  };
})();
