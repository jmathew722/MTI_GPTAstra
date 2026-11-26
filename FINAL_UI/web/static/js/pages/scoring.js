/* Scoring tab: Extraction-to-Model Fidelity (EMF). Overview, part results, methodology, worked example, part detail.
   The score grades what the drawing's EXTRACTION asked for against the ACTUAL SolidWorks part (measured on the STL that
   SolidWorks exported from the SLDPRT). The engine (bench.fidelity, free) decides every number and issue; colours come only from McA.grade (fixed grade thresholds); this page
   only shows what the server stored. A failed build, an incomplete input and a failed scorer are different states; a
   missing score is a dash, never 0; every colour also has a word and a glyph. The worked example is labelled illustrative. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  McA.pages = McA.pages || {};
  var $ = function (id) { return document.getElementById(id); };
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var SV, G;
  var TABS = [['overview', 'Overview'], ['results', 'Part results'], ['method', 'Scoring methodology'], ['example', 'Worked example']];
  var st = { tab: 'overview', ov: null, meth: null, methErr: '', err: '', q: '', detail: null, detailRec: null, busy: {}, benchmark: false, loading: false };

  function api() { return McA.api; }
  function errText(e) { return (e && (e.detail || e.message)) || String(e || 'error'); }
  function empty(icon, title, text) { return h('div', { class: 'empty' }, h('span', { class: 'empty-ic' }, McA.icons.get(icon, 30)), h('p', { class: 'empty-t', text: title }), h('p', { class: 'empty-d', text: text })); }
  function fmtTime(iso) { try { return iso ? new Date(iso).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : SV.DASH; } catch (e) { return SV.DASH; } }
  /* A coloured pill: band colour + glyph + word, so colour is never the only cue. */
  function pill(tone, glyph, label, extra) { return h('span', { class: 'band-pill band-' + tone + (extra ? ' ' + extra : ''), 'data-band': tone }, h('span', { class: 'bp-g', 'aria-hidden': 'true', text: glyph }), h('span', { text: label })); }
  function sevPill(sev) { var m = SV.severityMeta(sev); return h('span', { class: 'sev-pill sev-' + sev }, h('span', { class: 'bp-g', 'aria-hidden': 'true', text: m.glyph }), h('span', { text: m.label })); }
  function bar(pct, tone, label) {
    var w = typeof pct === 'number' ? Math.max(0, Math.min(100, pct)) : 0;
    return h('div', { class: 'sc-bar band-' + tone, role: 'img', 'aria-label': label || (typeof pct === 'number' ? Math.round(pct) + ' of 100' : 'not scored') }, h('div', { class: 'sc-bar-f', style: 'width:' + w + '%' }));
  }

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
    api().scoringPart(part).then(function (d) { if (st.detail === part) { st.detailRec = d; render(); } }, function (e) { if (st.detail === part) { st.detailRec = { error: errText(e) }; render(); } });
  }
  function evaluate(parts) {
    var names = parts.filter(function (p) { return !st.busy[p]; });
    if (!names.length) return Promise.resolve();
    names.forEach(function (p) { st.busy[p] = true; }); render();
    return api().scoringEvaluate(names, st.benchmark).then(function (r) {
      var res = r.results || [], ok = res.filter(function (x) { return x.state === 'scored'; }).length, inc = res.filter(function (x) { return x.state === 'incomplete' || x.state === 'no_model'; }).length;
      var bad = res.filter(function (x) { return x.state === 'scoring_failed'; }).length;
      McA.toast.show('Scored ' + ok + ' of ' + names.length + (inc ? ', ' + inc + ' incomplete' : '') + (bad ? ', ' + bad + ' failed' : '') + '.', bad ? 'warn' : 'ok');
    }, function (e) { McA.toast.show('Scoring could not run: ' + errText(e), 'err'); })
      .then(function () { names.forEach(function (p) { delete st.busy[p]; }); if (McA.scorecache) McA.scorecache.load(); return load(); })
      .then(function () { if (st.detail) openDetail(st.detail); });
  }

  /* ── tabs ─────────────────────────────────────────────────────────────── */
  function setTab(t) { st.tab = t; st.detail = null; if (t === 'method' || t === 'example') loadMethod(); render(); }
  function renderTabs() {
    var bar_ = h('div', { class: 'sc-tabs', role: 'tablist', 'aria-label': 'Scoring sections' });
    TABS.forEach(function (t, i) {
      var b = h('button', { class: 'sc-tab', type: 'button', role: 'tab', id: 'sc-tab-' + t[0], 'aria-selected': String(st.tab === t[0]), 'aria-controls': 'sc-panel', tabindex: st.tab === t[0] ? '0' : '-1', text: t[1] });
      b.addEventListener('click', function () { setTab(t[0]); });
      b.addEventListener('keydown', function (e) {
        var j = e.key === 'ArrowRight' ? (i + 1) % TABS.length : e.key === 'ArrowLeft' ? (i + TABS.length - 1) % TABS.length : -1;
        if (j < 0) return; e.preventDefault(); setTab(TABS[j][0]); var nb = $('sc-tab-' + st.tab); if (nb) nb.focus();
      });
      bar_.append(b);
    });
    return bar_;
  }

  /* ── shared pieces ────────────────────────────────────────────────────── */
  function legend() {
    return h('ul', { class: 'sc-legend', 'aria-label': 'Score grades' }, G.GRADES.map(function (g) {
      return h('li', null, pill(g.id, g.glyph, g.label), h('span', { class: 'sc-legend-r', text: G.rangeText(g) }));
    }));
  }
  /* A smooth gradient across 0..100 (spectrum visualisation only; every individual number uses its fixed grade colour). */
  function spectrum(score) {
    var wrap = h('div', { class: 'sc-spectrum', role: 'img', 'aria-label': 'Grading spectrum from 0 to 100' }, h('div', { class: 'grade-spectrum', style: 'background:' + G.gradientCSS() }));
    var pos = G.spectrumPos(score);
    if (pos !== null) wrap.firstChild.append(h('span', { class: 'sc-spec-mark', style: 'left:' + pos + '%', title: 'Average ' + G.format(score) }));
    wrap.append(h('div', { class: 'grade-scale', 'aria-hidden': 'true' }, [0, 40, 60, 80, 90, 100].map(function (n) { return h('span', { text: String(n) }); })));
    return wrap;
  }
  function stat(label, value, sub, tone) { return h('div', { class: 'sc-stat' + (tone ? ' band-' + tone : '') }, h('div', { class: 'sc-stat-l', text: label }), h('div', { class: 'sc-stat-v', text: value }), sub ? h('div', { class: 'sc-stat-s', text: sub }) : null); }
  function scoreChip(row) {
    var s = SV.statusOf(row);
    if (row.state !== 'scored' || !G.valid(row.score)) return h('span', { class: 'sc-score-none', text: SV.DASH, title: s.label });
    return h('span', { class: 'sc-score band-' + s.tone }, h('span', { class: 'sc-score-n', text: SV.scoreText(row) }), pill(s.tone, s.glyph, s.label));
  }
  function catStrip(row) {
    var order = ['model_integrity', 'envelope', 'feature_coverage', 'hole_accuracy', 'placement', 'extraction_trust'];
    var names = { model_integrity: 'Build integrity', envelope: 'Overall size', feature_coverage: 'Feature coverage', hole_accuracy: 'Hole accuracy', placement: 'Placement', extraction_trust: 'Extraction reliability' };
    var cats = row.categories || {};
    return h('span', { class: 'sc-strip', role: 'img', 'aria-label': order.map(function (k) { var c = cats[k]; return names[k] + ' ' + (c && c.checked && typeof c.score === 'number' ? G.format(c.score, 0) : 'not checked'); }).join(', ') },
      order.map(function (k) {
        var c = cats[k], tone = c && c.checked ? SV.gradeOf(c.score).id : 'none';
        return h('span', { class: 'sc-strip-c band-' + tone, title: names[k] + ': ' + (c && c.checked && typeof c.score === 'number' ? G.format(c.score, 0) + ' / 100' : 'not checked') });
      }));
  }
  function issueBadges(counts) {
    var out = [];
    ['critical', 'high', 'medium'].forEach(function (k) { if (counts && counts[k]) out.push(h('span', { class: 'sev-pill sev-' + k, title: SV.severityMeta(k).label }, h('span', { class: 'bp-g', 'aria-hidden': 'true', text: SV.severityMeta(k).glyph }), h('span', { text: counts[k] + ' ' + SV.severityMeta(k).label.toLowerCase() }))); });
    return out.length ? out : [h('span', { class: 'reason', text: counts ? 'No major issues' : SV.DASH })];
  }

  /* ── overview ─────────────────────────────────────────────────────────── */
  function renderOverview() {
    var o = st.ov, s = o.summary || {}, avgB = SV.gradeOf(s.average), eligible = (o.parts || []).filter(function (r) { return r.has_output; }), weak = eligible.filter(function (r) { return r.state === 'scored' && r.score < 60; }).length;
    var attention = SV.byAttention((o.parts || []).filter(function (r) { return r.has_output; })).filter(function (r) { return r.score < 90 || (r.counts && r.counts.critical); }).slice(0, 8);
    var wrap = h('div', null,
      h('div', { class: 'sc-stats' },
        stat('Parts scored', String(s.scored || 0), 'of ' + (s.parts || 0) + ' with output'),
        stat('Average fidelity', SV.avgText(s.average), s.scored ? avgB.label : 'no scored parts yet', s.scored ? avgB.id : 'none'),
        stat('Need attention', String(weak), 'scored below 60 \u00b7 ' + (s.parts_with_critical || 0) + ' with a critical issue', weak ? 'poor' : 'none'),
        stat('Not scored', String((s.incomplete || 0) + (s.no_model || 0) + (s.pending || 0) + (s.scoring_failed || 0)), (s.pending || 0) + ' pending · ' + (s.incomplete || 0) + ' incomplete · ' + (s.no_model || 0) + ' no part' + (s.scoring_failed ? ' · ' + s.scoring_failed + ' failed' : '')),
        stat('Rubric', o.version || SV.DASH, o.rubric || '')),
      h('p', { class: 'sc-note', text: 'The score grades what the drawing’s extraction asked for against the real SolidWorks part. It needs no answer key and costs nothing to run.' }));
    var dist = SV.distribution(eligible);
    if (s.scored) {
      wrap.append(h('h3', { class: 'sec-h', text: 'Score distribution' }),
        h('div', { class: 'sc-dist', role: 'img', 'aria-label': dist.map(function (d) { return d.count + ' ' + d.label; }).join(', ') },
          dist.filter(function (d) { return d.count; }).map(function (d) { return h('div', { class: 'sc-dist-s band-' + d.id, style: 'flex:' + d.count, title: d.count + ' · ' + d.label }, h('span', { text: String(d.count) })); })),
        legend(), spectrum(s.average));
    } else wrap.append(legend());
    if ((s.incomplete || 0) + (s.no_model || 0) > 0) wrap.append(h('div', { class: 'banner is-warn', role: 'note' }, McA.icons.get('info', 18),
      ((s.incomplete || 0) + (s.no_model || 0)) + ' part(s) could not be scored: the SolidWorks part or its exported STL is missing. They are listed as Incomplete, never as 0.'));
    wrap.append(h('h3', { class: 'sec-h', text: 'Parts that need attention' }));
    if (!attention.length) wrap.append(h('p', { class: 'reason', text: s.scored ? 'Every scored part is Excellent or Perfect.' : 'Nothing scored yet. Open Part results and press Evaluate.' }));
    else wrap.append(h('ul', { class: 'sc-attn' }, attention.map(function (r) {
      return h('li', { class: 'band-' + SV.gradeOf(r.score).id }, h('div', { class: 'sc-attn-h' }, h('strong', { text: r.part }), scoreChip(r), issueBadges(r.counts)),
        r.top_issue ? h('p', { class: 'sc-attn-t', text: r.top_issue }) : null,
        h('button', { class: 'btn ghost sm', type: 'button', text: 'Details', onclick: function () { openDetail(r.part); } }));
    })));
    return wrap;
  }

  /* ── part results ─────────────────────────────────────────────────────── */
  function renderResults() {
    var o = st.ov, s = McA.store.get();
    var q = h('input', { class: 'input-c sc-search', type: 'search', placeholder: 'Search parts, status or run id', 'aria-label': 'Search part results', value: st.q });
    q.addEventListener('input', function () { st.q = q.value; var pos = q.selectionStart; render(); var nq = document.querySelector('.sc-search'); if (nq) { nq.focus(); try { nq.setSelectionRange(pos, pos); } catch (e) { /* ignore */ } } });
    var found = SV.filter(o.parts || [], st.q);
    var rows = found.filter(function (r) { return r.has_output; }).concat(found.filter(function (r) { return !r.has_output; }));   // parts with output first
    var wrap = h('div', null, h('div', { class: 'sc-tools' }, q,
      h('label', { class: 'chk' }, h('input', { type: 'checkbox', id: 'sc-bench', checked: st.benchmark ? 'checked' : null, onchange: function (e) { st.benchmark = e.target.checked; } }),
        h('span', { text: 'Also run the answer-key benchmark when a signed key exists' }))), legend());
    if (!rows.length) { wrap.append(empty('search', (o.parts || []).length ? 'No matches' : 'No parts yet', (o.parts || []).length ? 'No part matches that search.' : 'Parts appear here once they are created and run.')); return wrap; }
    var body = rows.map(function (r) {
      var bs = s.batch && s.batch.results ? s.batch.results[r.part] : undefined, status = SV.statusOf(r, bs), block = SV.evalBlocker(r);
      var evalBtn = h('button', { class: 'btn secondary sm', type: 'button', text: st.busy[r.part] ? 'Scoring…' : (r.state === 'pending' || r.state === 'no_output' ? 'Evaluate' : 'Re-evaluate'), disabled: (block || st.busy[r.part]) ? 'disabled' : null, title: block || '' });
      evalBtn.addEventListener('click', function () { evaluate([r.part]); });
      return h('tr', { 'data-part': r.part, 'data-state': r.state, 'data-band': status.kind === 'scored' ? SV.gradeOf(r.score).id : 'none' },
        h('td', null, h('strong', { text: r.part })),
        h('td', { class: 'num', text: McA.projectorder ? McA.projectorder.fmtWhen(r.last_activity) : '' }),
        h('td', null, status.kind === 'scored' ? scoreChip(r) : pill(status.tone, status.glyph, status.label, 'is-quiet')),
        h('td', null, status.kind === 'scored' ? catStrip(r) : h('span', { class: 'reason', text: SV.DASH })),
        h('td', null, h('div', { class: 'sc-badges' }, r.counts ? issueBadges(r.counts) : [h('span', { class: 'reason', text: SV.DASH })])),
        h('td', null, r.stale_rubric ? pill('amber', '!', 'Rubric changed', 'is-quiet') : null, r.benchmark && r.benchmark.state === 'scored' ? h('span', { class: 'badge-c', title: 'Answer-key benchmark score', text: 'Benchmark ' + r.benchmark.score.toFixed(0) }) : null),
        h('td', null, h('div', { class: 'acts' }, h('button', { class: 'btn ghost sm', type: 'button', text: 'Details', onclick: function () { openDetail(r.part); } }), evalBtn)));
    });
    wrap.append(h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl sc-tbl' }, h('caption', { class: 'sr-only', text: 'Part results' }),
      h('thead', null, h('tr', null, ['Part', 'Last run', 'Fidelity score', 'Categories', 'Issues', 'Notes', 'Actions'].map(function (t) { return h('th', { scope: 'col', text: t }); }))), h('tbody', null, body))));
    return wrap;
  }

  /* ── part detail ──────────────────────────────────────────────────────── */
  function ring(rec) {
    var b = SV.gradeOf(rec.score), pct = Math.max(0, Math.min(100, rec.score || 0));
    return h('div', { class: 'sc-ring band-' + b.id, style: '--pct:' + pct, role: 'img', 'aria-label': 'Fidelity score ' + SV.scoreFull({ state: 'scored', score: rec.score }) + ', ' + b.label },
      h('div', { class: 'sc-ring-in' }, h('div', { class: 'sc-ring-n', text: SV.scoreText({ state: 'scored', score: rec.score }) }), h('div', { class: 'sc-ring-d', text: 'out of 100' })));
  }
  function catCard(c) {
    var tone = c.grade.id;
    return h('div', { class: 'sc-cat band-' + tone, 'data-cat': c.id },
      h('div', { class: 'sc-cat-h' }, h('strong', null, h('span', { class: 'sc-cat-k', 'aria-hidden': 'true' }), c.label), h('span', { class: 'sc-cat-w', text: c.weight + ' pts' })),
      h('div', { class: 'sc-cat-s' }, h('span', { class: 'sc-cat-n', text: c.checked ? G.format(c.score, 0) : SV.DASH }), h('span', { class: 'sc-cat-of', text: c.checked ? ' / 100' : ' not checkable' }), c.checked ? pill(c.grade.id, c.grade.glyph, c.grade.label, 'is-quiet') : null),
      bar(c.checked ? c.score : null, tone),
      h('div', { class: 'sc-cat-m', text: c.checked ? (c.earned.toFixed(1) + ' of ' + c.max.toFixed(1) + ' points · ' + c.n) : c.n }),
      h('div', { class: 'sc-cat-q', text: c.question }));
  }
  function itemTable(cat) {
    var rows = SV.itemRows(cat);
    if (!rows.length) return h('p', { class: 'reason', text: 'Nothing in this category could be checked for this part.' });
    return h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl sc-items' }, h('caption', { class: 'sr-only', text: cat.label + ' checks' }),
      h('thead', null, h('tr', null, ['Check', 'Drawing / expected', 'Real part / measured', 'Error', 'Credit', 'Note'].map(function (t) { return h('th', { scope: 'col', text: t }); }))),
      h('tbody', null, rows.map(function (r) { return h('tr', { class: 'row-' + r.grade.id }, h('td', { text: r.label }), h('td', { class: 'mono', text: r.expected }), h('td', { class: 'mono', text: r.measured }), h('td', { class: 'mono', text: r.error }),
        h('td', null, h('span', { class: 'cr cr-' + r.grade.id, title: r.grade.label }, h('span', { class: 'bp-g', 'aria-hidden': 'true', text: r.grade.glyph }), h('span', { text: r.credit }))), h('td', { text: r.note })); }))));
  }
  function issuesBlock(rec) {
    var groups = SV.groupIssues(rec.issues || []);
    if (!groups.length) return h('p', { class: 'reason', text: 'No issues or warnings were raised.' });
    return h('div', { class: 'sc-issues' }, groups.map(function (g) {
      return h('section', { class: 'sc-iss-g', 'aria-label': g.label + ' issues' }, h('h4', { class: 'sc-iss-h' }, sevPill(g.severity), h('span', { class: 'reason', text: g.items.length + (g.items.length === 1 ? ' issue' : ' issues') })),
        h('ul', { class: 'sc-iss-l' }, g.items.map(function (i) {
          return h('li', { class: 'sc-iss sev-' + i.severity }, h('div', { class: 'sc-iss-m', text: i.message }),
            h('div', { class: 'sc-iss-e' }, h('span', { class: 'mono sc-code', text: i.code }), i.ref ? h('span', { class: 'mono', text: i.ref }) : null, i.category ? h('span', { text: i.category.replace(/_/g, ' ') }) : null,
              i.points ? h('span', { class: 'sc-iss-p', text: '−' + i.points + ' pts' }) : null), i.evidence ? h('div', { class: 'reason', text: i.evidence }) : null);
        })));
    }));
  }
  function renderDetail() {
    var part = st.detail, d = st.detailRec;
    var wrap = h('div', { class: 'sc-detail' }, h('button', { class: 'btn ghost sm', type: 'button', text: '← All parts', onclick: function () { st.detail = null; st.tab = 'results'; render(); } }), h('h2', { class: 'sec-h', text: part }));
    if (!d) { wrap.append(h('p', { class: 'reason', text: 'Loading the stored evaluation…' })); return wrap; }
    if (d.error) { wrap.append(h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), 'Could not load the evaluation: ' + d.error)); return wrap; }
    var rec = d.latest, row = ((st.ov && st.ov.parts) || []).filter(function (r) { return r.part === part; })[0] || {};
    var evalBtn = h('button', { class: 'btn secondary sm', type: 'button', text: st.busy[part] ? 'Scoring…' : (rec ? 'Re-evaluate' : 'Evaluate'), disabled: (!row.has_output || st.busy[part]) ? 'disabled' : null, onclick: function () { evaluate([part]); } });
    if (!rec) { wrap.append(empty('scoring', 'Not evaluated yet', 'Press Evaluate to score this part. Nothing is assumed.'), evalBtn); return wrap; }
    var stt = SV.statusOf({ state: rec.state, reason: rec.reason, score: rec.score });
    var head = h('div', { class: 'sc-head' });
    if (rec.state === 'scored') head.append(ring(rec));
    head.append(h('div', { class: 'sc-head-b' },
      h('div', { class: 'sc-head-t' }, pill(stt.tone, stt.glyph, stt.label), h('span', { class: 'sc-head-m', text: 'Evaluated ' + fmtTime(rec.evaluated_at) + ' · ' + ((rec.rubric && rec.rubric.fingerprint) || '') + (rec.run_id ? ' · run ' + rec.run_id : '') })),
      rec.state === 'scored' ? h('p', { class: 'sc-head-p', text: 'Checked ' + Math.round((rec.coverage || 0) * 100) + '% of the rubric. ' + (rec.counts && (rec.counts.critical || rec.counts.high) ? SV.issueSummary(rec.counts) + '.' : 'No critical or high issues.') }) : null, evalBtn));
    wrap.append(head);
    if (rec.state !== 'scored') wrap.append(h('div', { class: 'banner ' + (rec.state === 'scoring_failed' || rec.state === 'no_model' ? 'is-err' : 'is-warn'), role: 'alert' }, McA.icons.get('warn', 18), (rec.explanation || rec.error || 'Not scored.') + ' This is shown as ' + stt.label.toLowerCase() + ', never as 0.'));
    (rec.caps || []).forEach(function (c) { wrap.append(h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), c)); });
    if (d.current_fingerprint && rec.rubric && rec.rubric.fingerprint !== d.current_fingerprint) wrap.append(h('div', { class: 'banner is-warn', role: 'note' }, McA.icons.get('info', 18), 'This score used rubric ' + rec.rubric.fingerprint + '; the current rubric is ' + d.current_fingerprint + '. The stored score is kept; Re-evaluate to score with the current rubric.'));
    var cats = rec.categories || [];
    if (cats.length) {
      wrap.append(h('h3', { class: 'sec-h', text: 'Rubric categories' }), h('div', { class: 'sc-cats' }, SV.catRows(rec).map(catCard)));
    }
    if ((rec.issues || []).length || rec.state === 'scored') wrap.append(h('h3', { class: 'sec-h', text: 'Issues and warnings' }), issuesBlock(rec));
    if (cats.length) {
      wrap.append(h('h3', { class: 'sec-h', text: 'What was checked' }));
      cats.forEach(function (c) { var cg = c.checked ? SV.gradeOf(c.score) : G.NONE; wrap.append(h('details', { class: 'sc-det', open: c.checked && c.score !== null && c.score < 90 ? 'open' : null }, h('summary', null, h('span', { text: c.label }), c.checked ? pill(cg.id, cg.glyph, G.format(c.score, 0) + ' / 100', 'is-quiet') : h('span', { class: 'reason', text: 'not checkable' })), itemTable(c))); });
    }
    var m = rec.measured || {};
    if (m.stl_dims) {
      var u = m.units === 'inch' ? 'in' : 'mm';
      wrap.append(h('h3', { class: 'sec-h', text: 'Measured on the real SolidWorks part' }),
        h('dl', { class: 'sc-kv' }, h('dt', { text: 'Bounding box (sorted)' }), h('dd', { class: 'mono', text: m.stl_dims.join(' × ') + ' ' + u }), h('dt', { text: 'Volume' }), h('dd', { class: 'mono', text: m.stl_volume + ' ' + u + '³' }),
          h('dt', { text: 'Mesh' }), h('dd', { class: 'mono', text: m.triangles + ' triangles, ' + Math.round((m.closed_fraction || 0) * 1000) / 10 + '% closed' }), h('dt', { text: 'Holes found' }), h('dd', { class: 'mono', text: String((m.holes || []).length) })));
      if ((m.holes || []).length) wrap.append(h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' }, h('caption', { class: 'sr-only', text: 'Holes measured in the real part' }),
        h('thead', null, h('tr', null, ['Axis', 'Diameter', 'Depth', 'Type', 'Counterbore'].map(function (t) { return h('th', { scope: 'col', text: t }); }))),
        h('tbody', null, m.holes.map(function (x) { return h('tr', null, h('td', { text: x.axis }), h('td', { class: 'num', text: x.d + ' ' + u }), h('td', { class: 'num', text: x.depth + ' ' + u }), h('td', null, h('span', { class: 'sc-hole-t ' + (x.through ? 'thru' : 'blind'), text: x.through ? 'Through' : 'Blind' })), h('td', null, x.cbore ? h('span', { class: 'sc-hole-t cbore', text: '\u00d8' + x.cbore.d + ' \u00d7 ' + x.cbore.depth }) : SV.DASH)); })))));
    }
    (rec.notes || []).forEach(function (n) { wrap.append(h('p', { class: 'sc-note', text: n })); });
    var b = d.benchmark;
    wrap.append(h('h3', { class: 'sec-h', text: 'Answer-key benchmark (optional)' }),
      h('p', { class: 'sc-note', text: b && b.state === 'scored' ? 'Benchmark score ' + b.score.toFixed(1) + ' / 100 against a signed answer key (separate from the fidelity score above).' : 'No signed answer key for this drawing, so there is no benchmark score. The fidelity score above does not need one.' }));
    if ((d.history || []).length > 1) wrap.append(h('h3', { class: 'sec-h', text: 'Evaluation history (kept, never overwritten)' }), h('ul', { class: 'dlg-list sc-hist' }, d.history.slice().reverse().map(function (x) {
      var hb = x.state === 'scored' ? SV.gradeOf(x.score) : null; return h('li', null, h('span', { text: fmtTime(x.evaluated_at) }), hb ? pill(hb.id, hb.glyph, SV.scoreFull({ state: 'scored', score: x.score }) + ' \u00b7 ' + hb.label, 'is-quiet') : pill('none', SV.DASH, x.state, 'is-quiet'), h('span', { class: 'reason mono', text: x.fingerprint || '' })); })));
    return wrap;
  }

  /* ── methodology and example ──────────────────────────────────────────── */
  function tbl(cap, heads, rows) { return h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' }, h('caption', { class: 'sr-only', text: cap }), h('thead', null, h('tr', null, heads.map(function (t) { return h('th', { scope: 'col', text: t }); }))), h('tbody', null, rows))); }
  function renderMethod() {
    if (st.methErr) return h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), 'The scoring methodology could not be loaded: ' + st.methErr);
    if (!st.meth) return h('p', { class: 'reason', text: 'Loading the methodology…' });
    var m = st.meth.methodology;
    return h('div', { class: 'sc-method' },
      h('p', { class: 'sc-note', text: m.name + ', version ' + m.version + ' (' + m.fingerprint + '). Total possible: ' + m.total_possible + ' points. Free: no API calls. It grades the extraction against the real SolidWorks part, measured on the STL SolidWorks exported from the SLDPRT.' }),
      h('h3', { class: 'sec-h', text: 'Formula' }), h('p', { class: 'mono sc-formula', text: m.formula }), h('p', { class: 'mono sc-formula', text: m.credit_formula }),
      h('h3', { class: 'sec-h', text: 'Grading spectrum out of 100' }), legend(), spectrum(null),
      h('p', { class: 'sc-note', text: 'Each number, bar and badge takes its grade colour from the actual score at these fixed thresholds; a score below 100 is never shown as Perfect. A missing score is neutral grey.' }),
      h('h3', { class: 'sec-h', text: 'Categories' }),
      h('div', { class: 'sc-wbar', role: 'img', 'aria-label': 'Points per category: ' + m.categories.map(function (c) { return c.label + ' ' + c.weight; }).join(', ') }, m.categories.map(function (c) { return h('div', { class: 'sc-wbar-s cat-m-' + c.id, style: 'flex:' + c.weight, title: c.label + ': ' + c.weight + ' points', text: String(c.weight) }); })),
      tbl('Rubric categories', ['Category', 'Points', 'Question it answers', 'How it is measured'], m.categories.map(function (c) { return h('tr', null, h('td', null, h('span', { class: 'sc-m-cat cat-m-' + c.id }, h('span', { class: 'sc-cat-k', 'aria-hidden': 'true' }), c.label)), h('td', { class: 'num', text: String(c.weight) }), h('td', { text: c.question }), h('td', { text: c.how || '' })); })),
      h('h3', { class: 'sec-h', text: 'Checks inside Build integrity and Extraction reliability' }),
      tbl('Check weights', ['Category', 'Check', 'Points'], Object.keys(m.integrity_checks).map(function (k) { return h('tr', null, h('td', { text: 'Build integrity' }), h('td', { text: k.replace(/_/g, ' ') }), h('td', { class: 'num', text: String(m.integrity_checks[k]) })); })
        .concat(Object.keys(m.trust_checks).map(function (k) { return h('tr', null, h('td', { text: 'Extraction reliability' }), h('td', { text: k.replace(/_/g, ' ') }), h('td', { class: 'num', text: String(m.trust_checks[k]) })); }))),
      h('h3', { class: 'sec-h', text: 'Credit within and past tolerance (e = error / tolerance)' }),
      tbl('Credit curve', ['e', 'Credit'], m.credit_curve.map(function (c) { return h('tr', null, h('td', { class: 'num', text: String(c.e) }), h('td', { class: 'num', text: c.credit.toFixed(3) })); })),
      h('h3', { class: 'sec-h', text: 'Feature importance (Feature coverage)' }),
      tbl('Tier weights', ['Feature type', 'Weight'], Object.keys(m.tiers).map(function (k) { return h('tr', null, h('td', { text: k.replace(/_/g, ' ') }), h('td', { class: 'num', text: String(m.tiers[k]) })); })),
      h('h3', { class: 'sec-h', text: 'Gates, tolerances and thresholds' }),
      h('ul', { class: 'dlg-list' }, [
        'A critical issue caps the score at ' + m.gates.critical_cap + ' (Below Average at best): a polished breakdown cannot hide a wrong model.',
        'Overall size off by more than ' + Math.round(m.gates.envelope_off_fraction * 100) + '% is critical. A mesh that differs from the build record by more than ' + Math.round(m.gates.mesh_vs_build_fraction * 100) + '% (or is older than the SLDPRT) is a stale or wrong export and is critical.',
        'Tolerance: the drawing’s own; if none, ±' + m.fallback_tol.inch + ' in / ±' + m.fallback_tol.mm + ' mm. Nothing is judged tighter than the mesh floor (' + m.mesh_floor.inch + ' in / ' + m.mesh_floor.mm + ' mm).',
        'A category with nothing checkable is dropped and the rest are rescaled. Below ' + Math.round(m.min_coverage * 100) + '% checkable, no score is given.',
        'Missing evidence is never scored as 0: a missing STL, extraction or build is Incomplete or No part.',
        'Tapped holes accept any size from ' + Math.round(m.match.tapped_range[0] * 100) + '% to ' + Math.round(m.match.tapped_range[1] * 100) + '% of the nominal thread (tap-drill, minor or major).'].map(function (t) { return h('li', { text: t }); })),
      h('h3', { class: 'sec-h', text: 'Issue severities' }),
      tbl('Severities', ['Severity', 'Meaning'], [['critical', 'The model cannot be trusted (wrong or stale mesh, wrong overall size, no part). Caps the score.'], ['high', 'A feature or hole is missing, wrong type, or built wrongly.'], ['medium', 'A measurable deviation, fallback, or open question.'], ['low', 'Worth knowing: defaults applied, unknown positions.'], ['info', 'Advisory only (modeling practice); never lowers the score.']]
        .map(function (r) { return h('tr', null, h('td', null, sevPill(r[0])), h('td', { text: r[1] })); })),
      h('h3', { class: 'sec-h', text: 'Known limits' }), h('ul', { class: 'dlg-list' }, (m.limits || []).map(function (t) { return h('li', { text: t }); })));
  }
  function renderExample() {
    if (st.methErr) return h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), 'The worked example could not be loaded: ' + st.methErr);
    if (!st.meth) return h('p', { class: 'reason', text: 'Loading the worked example…' });
    var x = st.meth.example;
    return h('div', { class: 'sc-example' },
      h('div', { class: 'banner is-info', role: 'note' }, McA.icons.get('info', 18), h('strong', { text: x.label + '. ' }), 'These scenarios are computed with the live rubric from made-up checks. They are not measured results of any part.'),
      h('p', { class: 'sc-note', text: x.assumptions }),
      tbl('Worked example cases', ['Scenario', 'Score', 'Band', 'Build', 'Size', 'Features', 'Holes', 'Placement', 'Extraction'], x.cases.map(function (c) {
        var by = {}; c.categories.forEach(function (k) { by[k.id] = k; });
        var cell = function (id) { var k = by[id], g = k && k.score !== null ? SV.gradeOf(k.score) : null; return h('td', null, g ? h('span', { class: 'cr cr-' + g.id }, h('span', { class: 'bp-g', 'aria-hidden': 'true', text: g.glyph }), h('span', { text: G.format(k.score, 0) })) : SV.DASH); };
        var cg = SV.gradeOf(c.score); return h('tr', { class: 'sc-ex-row band-' + cg.id }, h('td', null, c.case, c.caps && c.caps.length ? h('div', { class: 'reason', text: c.caps[0] }) : null), h('td', null, h('strong', { class: 'sc-ex-s band-' + cg.id, text: G.format(c.score) })),
          h('td', null, pill(cg.id, cg.glyph, cg.label, 'is-quiet')), cell('model_integrity'), cell('envelope'), cell('feature_coverage'), cell('hole_accuracy'), cell('placement'), cell('extraction_trust'));
      })));
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
    lede.textContent = 'Extraction-to-Model Fidelity: how closely the real SolidWorks part matches what the drawing’s extraction asked for, scored out of 100. Rubric ' + st.ov.version + '.';
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
      SV = McA.scoringview; G = McA.grade;
      var all = $('sc-eval-all');
      if (all) all.addEventListener('click', function () {
        if (all.getAttribute('aria-disabled') === 'true') return;
        var parts = ((st.ov && st.ov.parts) || []).filter(function (r) { return r.has_output; }).map(function (r) { return r.part; });
        McA.dialog.confirm('Score ' + parts.length + ' part' + (parts.length === 1 ? '' : 's') + '?', 'Scoring is free (no API calls). Each result is added to the part’s history; earlier scores are kept.', 'Score').then(function (ok) { if (ok) evaluate(parts); });
      });
      McA.store.subscribe(function (s) { return s.run.state; }, function (state) { if (McA.router.current() === 'scoring' && /^(succeeded|failed|cancelled)/.test(state)) setTimeout(load, 1500); });
      render();
    },
    enter: function () { st.detail = null; load(); if (st.tab === 'method' || st.tab === 'example') loadMethod(); },
  };
})();
