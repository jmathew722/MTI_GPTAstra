/* McA.scoringview: pure presentation rules for the Scoring tab (no DOM, no network, no grading).
   The engine (bench.fidelity) decides every number; this module labels states and formats what the server stored. Colours and grades
   come ONLY from McA.grade (logic/grade.js): fixed thresholds on the actual number, never rounded up, neutral grey when there is no score.
   A failed BUILD, an INCOMPLETE input and a failed SCORER are three different things and never share a label. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./grade.js'));
  else (root.McA = root.McA || {}).scoringview = factory(root.McA.grade);
})(typeof self !== 'undefined' ? self : this, function (G) {
  'use strict';
  var DASH = G.DASH;
  var SEVERITY = {
    critical: { label: 'Critical', glyph: '✕', rank: 0 }, high: { label: 'High', glyph: '▲', rank: 1 },
    medium: { label: 'Medium', glyph: '!', rank: 2 }, low: { label: 'Low', glyph: '•', rank: 3 }, info: { label: 'Note', glyph: 'i', rank: 4 } };
  var REASON = {
    no_mesh: 'No exported STL', no_extraction: 'No extraction', mesh_unreadable: 'STL unreadable', low_coverage: 'Too little to check', no_model: 'No SolidWorks part' };

  /** The grade object of a score ({id, label, color, glyph, ...}); neutral grey when there is no valid score. */
  function gradeOf(score) { return G.gradeOf(score); }
  /** Grade of a 0..1 credit. */
  function creditGrade(c) { return G.gradeOfCredit(c); }

  /** row: one /api/scoring part row. The grade comes from the score itself, never from a server-supplied band. */
  function statusOf(row, batch) {
    row = row || {};
    if (row.state === 'scored' && !G.valid(row.score)) return { kind: 'invalid', label: 'Score unavailable', tone: 'none', glyph: DASH, color: G.NONE.color };
    if (row.state === 'scored') { var g = gradeOf(row.score); return { kind: 'scored', label: g.label, tone: g.id, glyph: g.glyph, color: g.color }; }
    var none = G.NONE;
    if (row.state === 'scoring_failed') return { kind: 'scoring_failed', label: 'Scoring failed', tone: 'none', glyph: DASH, color: none.color };
    if (row.state === 'no_model') return { kind: 'no_model', label: 'Build failed or no part', tone: 'none', glyph: DASH, color: none.color };
    if (row.state === 'incomplete') return { kind: 'incomplete', label: 'Incomplete: ' + (REASON[row.reason] || 'missing evidence'), tone: 'none', glyph: DASH, color: none.color };
    if (batch && batch.state === 'failed') return { kind: 'generation_failed', label: 'Generation failed', tone: 'none', glyph: DASH, color: none.color };
    if (row.state === 'pending') return { kind: 'pending', label: 'Pending evaluation', tone: 'none', glyph: DASH, color: none.color };
    if (row.state === 'no_output') return { kind: 'no_output', label: 'Not run yet', tone: 'none', glyph: DASH, color: none.color };
    return { kind: 'pending', label: 'Pending evaluation', tone: 'none', glyph: DASH, color: none.color };
  }
  function scoreText(row) { return row && row.state === 'scored' && G.valid(row.score) ? G.format(row.score) : DASH; }
  function scoreFull(row) { return row && row.state === 'scored' && G.valid(row.score) ? G.formatFull(row.score) : DASH; }
  function avgText(avg) { return G.formatFull(avg); }
  function severityMeta(s) { return SEVERITY[s] || SEVERITY.info; }
  function issueSummary(counts) {
    var c = counts || {}, out = [];
    ['critical', 'high', 'medium', 'low'].forEach(function (k) { if (c[k]) out.push(c[k] + ' ' + SEVERITY[k].label.toLowerCase()); });
    return out.join(' · ');
  }
  function groupIssues(issues) {
    var by = {};
    (issues || []).forEach(function (i) { (by[i.severity] = by[i.severity] || []).push(i); });
    return Object.keys(by).sort(function (a, b) { return severityMeta(a).rank - severityMeta(b).rank; })
      .map(function (k) { return { severity: k, label: severityMeta(k).label, glyph: severityMeta(k).glyph, items: by[k] }; });
  }
  function filter(rows, q) {
    var t = String(q || '').trim().toLowerCase();
    if (!t) return (rows || []).slice();
    return (rows || []).filter(function (r) { var st = statusOf(r); return String(r.part).toLowerCase().indexOf(t) >= 0 || st.label.toLowerCase().indexOf(t) >= 0 || String(r.run_id || '').toLowerCase().indexOf(t) >= 0; });
  }
  /** Worst scores first (needs attention); only scored parts. Ties by name. */
  function byAttention(rows) {
    return (rows || []).filter(function (r) { return r.state === 'scored' && G.valid(r.score); }).slice().sort(function (a, b) { return a.score - b.score || (a.part < b.part ? -1 : 1); });
  }
  function evalBlocker(row) { return !row || !row.has_output ? 'Run the part first: there is no output to score.' : ''; }

  function catRows(rec) {
    return ((rec && rec.categories) || []).map(function (c) {
      var g = c.checked ? gradeOf(c.score) : G.NONE;
      return { id: c.id, label: c.label, weight: c.weight, checked: !!c.checked, score: c.score, earned: c.earned, max: c.max, grade: g,
               n: c.n_checked + ' of ' + c.n_total + ' checked', question: c.question };
    });
  }
  function itemRows(cat) {
    return ((cat && cat.items) || []).map(function (i) {
      var g = creditGrade(i.credit);
      var err = typeof i.error === 'number' ? (i.error > 0 ? '+' : '') + i.error + (i.unit ? ' ' + (i.unit === 'inch' ? 'in' : i.unit) : '') + (typeof i.e === 'number' ? ' (' + i.e + '× tol)' : '') : '';
      return { id: i.id, label: i.label, expected: i.expected == null ? '' : String(i.expected), measured: i.measured == null ? '' : String(i.measured), error: err,
               credit: typeof i.credit === 'number' ? G.format(i.credit * 100, 0) + '%' : DASH, grade: g, note: i.note || '', weight: i.weight };
    });
  }
  /** The overview distribution over the scored parts' ACTUAL scores (six grades). */
  function distribution(rows) { return G.distribution((rows || []).filter(function (r) { return r.state === 'scored'; }).map(function (r) { return r.score; })); }

  return { GRADES: G.GRADES, SEVERITY: SEVERITY, gradeOf: gradeOf, creditGrade: creditGrade, statusOf: statusOf, scoreText: scoreText, scoreFull: scoreFull, avgText: avgText,
           severityMeta: severityMeta, issueSummary: issueSummary, groupIssues: groupIssues, filter: filter, byAttention: byAttention, evalBlocker: evalBlocker,
           catRows: catRows, itemRows: itemRows, distribution: distribution, DASH: DASH };
});
