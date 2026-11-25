/* McA.scoringview: pure presentation rules for the Scoring tab (no DOM, no network, no grading).
   The scorer decides every number; this module only labels states and formats what the server stored.
   A failed GENERATION, a failed SCORING and an INCOMPLETE evaluation are three different things and never share a label.
   A missing score is shown as a dash, never 0. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).scoringview = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var DASH = '–';

  /** row: one /api/scoring part row; batch: the store's batch result for the part ({state}) or undefined. */
  function statusOf(row, batch) {
    row = row || {};
    var genFailed = (batch && batch.state === 'failed') || (row.state === 'no_output' && batch && batch.state);
    if (row.state === 'scored') return { kind: 'scored', label: row.exact ? 'Scored, exact' : 'Scored', tone: 'ok' };
    if (row.state === 'scoring_failed') return { kind: 'scoring_failed', label: 'Scoring failed', tone: 'err' };
    if (row.state === 'incomplete') return { kind: 'incomplete', label: 'Incomplete', tone: 'warn' };
    if (genFailed) return { kind: 'generation_failed', label: 'Generation failed', tone: 'err' };
    if (row.state === 'pending' && row.has_output && !row.has_part) return { kind: 'no_part', label: 'No SolidWorks part', tone: 'warn' };
    if (row.state === 'pending') return { kind: 'pending', label: 'Pending evaluation', tone: '' };
    if (row.state === 'no_output') return { kind: 'no_output', label: 'Not run yet', tone: '' };
    return { kind: 'pending', label: 'Pending evaluation', tone: '' };
  }
  function scoreText(row) {
    if (!row || row.state !== 'scored' || typeof row.score !== 'number' || !isFinite(row.score)) return DASH;
    return row.score.toFixed(1) + ' / 100';
  }
  function avgText(avg) { return typeof avg === 'number' && isFinite(avg) ? avg.toFixed(1) + ' / 100' : DASH; }
  function practicesText(row) { return row && typeof row.practices_score === 'number' ? row.practices_score.toFixed(0) + ' / 100' : DASH; }

  function filter(rows, q) {
    var t = String(q || '').trim().toLowerCase();
    if (!t) return (rows || []).slice();
    return (rows || []).filter(function (r) {
      var st = statusOf(r);
      return String(r.part).toLowerCase().indexOf(t) >= 0 || st.label.toLowerCase().indexOf(t) >= 0 || String(r.run_id || '').toLowerCase().indexOf(t) >= 0;
    });
  }
  /** Why a part cannot be evaluated right now, or ''. */
  function evalBlocker(row) {
    if (!row || !row.has_output) return 'Run the part first: there is no output to score.';
    return '';
  }
  /** Rows of the criterion breakdown from one stored evaluation. */
  function breakdown(rec) {
    var rows = (rec && rec.rows) || [];
    return rows.map(function (r) {
      var ac = r.attr_credits || {};
      var pct = function (k) { return typeof ac[k] === 'number' ? Math.round(ac[k] * 100) + '%' : DASH; };
      return { id: r.feature_id, type: r.type, weight: typeof r.weight === 'number' ? +r.weight.toFixed(2) : null, status: r.status,
               position: pct('position'), size: pct('size'), depth: pct('depth'), kind: pct('type'),
               credit: typeof r.credit === 'number' ? r.credit : null, lost: typeof r.points_lost === 'number' ? r.points_lost : 0,
               blame: r.blame || '', reason: r.reason || '' };
    });
  }
  /** Awarded vs maximum points per row: max = 100 x weight / W, awarded = max - lost. W comes from the rows themselves. */
  function awarded(rec) {
    var rows = (rec && rec.rows) || [];
    var W = rows.reduce(function (a, r) { return a + (typeof r.weight === 'number' ? r.weight : 0); }, 0);
    return rows.map(function (r) {
      var max = W > 0 && typeof r.weight === 'number' ? 100 * r.weight / W : null;
      var lost = typeof r.points_lost === 'number' ? r.points_lost : 0;
      return { id: r.feature_id, max: max === null ? null : +max.toFixed(2), awarded: max === null ? null : +(max - lost).toFixed(2), lost: +lost.toFixed(2) };
    });
  }
  function stageRollup(rec) {
    var out = {};
    var b = (rec && rec.blame) || {};
    Object.keys(b).forEach(function (k) { var st = b[k].stage || 'unknown'; out[st] = (out[st] || 0) + (b[k].points || 0); });
    return Object.keys(out).map(function (k) { return { stage: k, points: +out[k].toFixed(2) }; }).sort(function (a, c) { return c.points - a.points; });
  }
  return { statusOf: statusOf, scoreText: scoreText, avgText: avgText, practicesText: practicesText, filter: filter,
           evalBlocker: evalBlocker, breakdown: breakdown, awarded: awarded, stageRollup: stageRollup, DASH: DASH };
});
