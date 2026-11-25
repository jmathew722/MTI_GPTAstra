/* McA.scoringview: pure presentation rules for the Scoring tab (no DOM, no network, no grading).
   The engine (bench.fidelity) decides every number and every band; this module only labels states and formats what the
   server stored. A failed BUILD, an INCOMPLETE input and a failed SCORER are three different things and never share a
   label. A missing score is a dash, never 0. Every colour also has a word and a glyph, so colour is never the only cue. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).scoringview = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var DASH = '–';
  var BANDS = [
    { id: 'green', min: 90, label: 'Matches the drawing', glyph: '✓' },
    { id: 'amber', min: 75, label: 'Review recommended', glyph: '!' },
    { id: 'orange', min: 60, label: 'Significant deviations', glyph: '▲' },
    { id: 'red', min: 0, label: 'Does not match', glyph: '✕' }];
  var SEVERITY = {
    critical: { label: 'Critical', glyph: '✕', rank: 0 }, high: { label: 'High', glyph: '▲', rank: 1 },
    medium: { label: 'Medium', glyph: '!', rank: 2 }, low: { label: 'Low', glyph: '•', rank: 3 }, info: { label: 'Note', glyph: 'i', rank: 4 } };
  var REASON = {
    no_mesh: 'No exported STL', no_extraction: 'No extraction', mesh_unreadable: 'STL unreadable', low_coverage: 'Too little to check',
    no_model: 'No SolidWorks part' };

  /** The server names glyphs (check, alert, warn, x, dash); the page draws symbols. A symbol passes through unchanged. */
  var SYM = { check: '✓', alert: '!', warn: '▲', x: '✕', dash: DASH };
  function sym(g) { return Object.prototype.hasOwnProperty.call(SYM, g) ? SYM[g] : (g || DASH); }

  function bandOf(score, bands) {
    if (typeof score !== 'number' || !isFinite(score)) return { id: 'none', label: 'Not scored', glyph: DASH };
    var list = (bands && bands.length ? bands : BANDS).slice().sort(function (a, b) { return b.min - a.min; });
    for (var i = 0; i < list.length; i++) if (score >= list[i].min) return list[i];
    return list[list.length - 1];
  }
  /** Band for a 0..1 credit or a 0..100 percentage of a single check/category (same thresholds). */
  function pctBand(p, bands) { return bandOf(typeof p === 'number' ? p : null, bands); }
  function creditBand(c, bands) { return typeof c === 'number' ? bandOf(c * 100, bands) : { id: 'none', label: 'Not scored', glyph: DASH }; }

  /** row: one /api/scoring part row. */
  function statusOf(row, batch) {
    row = row || {};
    if (row.state === 'scored') { var b = row.band && row.band.id ? row.band : bandOf(row.score); return { kind: 'scored', label: b.label, tone: b.id, glyph: b.glyph }; }
    if (row.state === 'scoring_failed') return { kind: 'scoring_failed', label: 'Scoring failed', tone: 'red', glyph: '✕' };
    if (row.state === 'no_model') return { kind: 'no_model', label: 'Build failed or no part', tone: 'red', glyph: '✕' };
    if (row.state === 'incomplete') return { kind: 'incomplete', label: 'Incomplete: ' + (REASON[row.reason] || 'missing evidence'), tone: 'amber', glyph: '!' };
    if (batch && batch.state === 'failed') return { kind: 'generation_failed', label: 'Generation failed', tone: 'red', glyph: '✕' };
    if (row.state === 'pending') return { kind: 'pending', label: 'Pending evaluation', tone: 'none', glyph: DASH };
    if (row.state === 'no_output') return { kind: 'no_output', label: 'Not run yet', tone: 'none', glyph: DASH };
    return { kind: 'pending', label: 'Pending evaluation', tone: 'none', glyph: DASH };
  }
  function scoreText(row) {
    if (!row || row.state !== 'scored' || typeof row.score !== 'number' || !isFinite(row.score)) return DASH;
    return row.score.toFixed(1);
  }
  function scoreFull(row) { var t = scoreText(row); return t === DASH ? DASH : t + ' / 100'; }
  function avgText(avg) { return typeof avg === 'number' && isFinite(avg) ? avg.toFixed(1) + ' / 100' : DASH; }
  function severityMeta(s) { return SEVERITY[s] || SEVERITY.info; }
  function issueSummary(counts) {
    var c = counts || {}, out = [];
    ['critical', 'high', 'medium', 'low'].forEach(function (k) { if (c[k]) out.push(c[k] + ' ' + SEVERITY[k].label.toLowerCase()); });
    return out.join(' · ');
  }
  /** Issues grouped worst-first: [{severity, label, glyph, items}]. */
  function groupIssues(issues) {
    var by = {};
    (issues || []).forEach(function (i) { (by[i.severity] = by[i.severity] || []).push(i); });
    return Object.keys(by).sort(function (a, b) { return severityMeta(a).rank - severityMeta(b).rank; })
      .map(function (k) { return { severity: k, label: severityMeta(k).label, glyph: severityMeta(k).glyph, items: by[k] }; });
  }
  function filter(rows, q) {
    var t = String(q || '').trim().toLowerCase();
    if (!t) return (rows || []).slice();
    return (rows || []).filter(function (r) {
      var st = statusOf(r);
      return String(r.part).toLowerCase().indexOf(t) >= 0 || st.label.toLowerCase().indexOf(t) >= 0 || String(r.run_id || '').toLowerCase().indexOf(t) >= 0
        || (r.band && String(r.band.label).toLowerCase().indexOf(t) >= 0);
    });
  }
  /** Worst scores first (needs attention), unscored last; ties by name. */
  function byAttention(rows) {
    return (rows || []).filter(function (r) { return r.state === 'scored'; }).slice().sort(function (a, b) { return a.score - b.score || (a.part < b.part ? -1 : 1); });
  }
  function evalBlocker(row) { return !row || !row.has_output ? 'Run the part first: there is no output to score.' : ''; }

  function catRows(rec) {
    return ((rec && rec.categories) || []).map(function (c) {
      return { id: c.id, label: c.label, weight: c.weight, checked: !!c.checked, score: c.score, earned: c.earned, max: c.max, band: c.band || bandOf(c.score),
               n: c.n_checked + ' of ' + c.n_total + ' checked', question: c.question };
    });
  }
  /** One table line per checked item: expected, measured, error (and error / tolerance), credit % with its own band. */
  function itemRows(cat) {
    return ((cat && cat.items) || []).map(function (i) {
      var cb = creditBand(i.credit);
      var err = typeof i.error === 'number' ? (i.error > 0 ? '+' : '') + i.error + (i.unit ? ' ' + (i.unit === 'inch' ? 'in' : i.unit) : '') + (typeof i.e === 'number' ? ' (' + i.e + '× tol)' : '') : '';
      return { id: i.id, label: i.label, expected: i.expected == null ? '' : String(i.expected), measured: i.measured == null ? '' : String(i.measured), error: err,
               credit: typeof i.credit === 'number' ? Math.round(i.credit * 100) + '%' : DASH, band: cb, note: i.note || '', weight: i.weight };
    });
  }
  /** Stacked-bar segments: [{id, count, pct}] over the scored parts only. */
  function distribution(summary, bands) {
    var d = (summary && summary.distribution) || {}, total = 0;
    var list = (bands && bands.length ? bands : BANDS);
    list.forEach(function (b) { total += d[b.id] || 0; });
    return list.map(function (b) { return { id: b.id, label: b.label, count: d[b.id] || 0, pct: total ? Math.round(1000 * (d[b.id] || 0) / total) / 10 : 0 }; });
  }
  return { BANDS: BANDS, SEVERITY: SEVERITY, sym: sym, bandOf: bandOf, pctBand: pctBand, creditBand: creditBand, statusOf: statusOf, scoreText: scoreText, scoreFull: scoreFull,
           avgText: avgText, severityMeta: severityMeta, issueSummary: issueSummary, groupIssues: groupIssues, filter: filter, byAttention: byAttention,
           evalBlocker: evalBlocker, catRows: catRows, itemRows: itemRows, distribution: distribution, DASH: DASH };
});
