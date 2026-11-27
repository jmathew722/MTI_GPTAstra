/* McA.estimateview: pure presentation of the run estimate (no DOM, no network, no prices).
   The server (GET /api/estimate) is the single source of truth: seconds and USD strings. This module only formats
   them and keeps UNKNOWN distinct from ZERO: no history shows "insufficient history", no price shows "unavailable". */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).estimateview = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var DASH = '–';

  function fmtDur(sec) {
    if (typeof sec !== 'number' || !isFinite(sec) || sec < 0) return '';
    if (sec < 60) return Math.max(1, Math.round(sec)) + ' s';
    var m = sec / 60;
    if (m < 90) return (m < 10 ? Math.round(m * 10) / 10 : Math.round(m)) + ' min';
    var h = Math.floor(m / 60), mm = Math.round(m - h * 60);
    return h + ' h' + (mm ? ' ' + mm + ' min' : '');
  }
  /** "2–4 min" (shared unit when both ends use it), or a single value when the ends round alike. */
  function fmtRange(lo, hi) {
    if (typeof lo !== 'number' || typeof hi !== 'number') return '';
    var a = fmtDur(lo), b = fmtDur(hi);
    if (a === b) return a;
    var ua = a.replace(/^[\d.]+ /, ''), ub = b.replace(/^[\d.]+ /, '');
    if (ua === ub) return a.replace(/ .*$/, '') + DASH + b;
    return a + ' ' + DASH + ' ' + b;
  }
  /** USD with enough decimals that a small charge never shows as $0.00. v is a number or a decimal string. */
  function usd(v) {
    var n = typeof v === 'string' ? parseFloat(v) : v;
    if (typeof n !== 'number' || !isFinite(n) || n < 0) return '';
    if (n === 0) return '$0.00';
    if (n < 0.01) return '$' + (n < 0.0001 ? n.toPrecision(2) : n.toFixed(4));
    return '$' + n.toFixed(2);
  }
  function usdRange(lo, hi) {
    var a = usd(lo), b = usd(hi);
    if (!a || !b) return '';
    return a === b ? a : a + DASH + b;
  }

  /** est: the /api/estimate payload (or null while loading / on error). Returns text for each line. */
  function describe(est, err) {
    if (err) return { state: 'error', time: 'Estimated time: unavailable', cost: 'Estimated cost: unavailable', detail: err, inputs: 0 };
    if (!est) return { state: 'loading', time: 'Estimated time: calculating', cost: 'Estimated cost: calculating', detail: '', inputs: 0 };
    var n = est.inputs || 0;
    if (!n) return { state: 'empty', time: 'Estimated time: ' + DASH, cost: 'Estimated cost: ' + DASH, detail: 'Select a part to see an estimate.', inputs: 0 };
    var t = est.time || {}, c = est.cost || {};
    var time = t.available ? 'Estimated time: ' + fmtRange(t.low, t.high) + (typeof t.expected === 'number' ? ' (expected ' + fmtDur(t.expected) + ')' : '') : 'Estimated time: insufficient history';
    var cost = c.available ? 'Estimated cost: ' + usdRange(c.low, c.high) + (c.expected !== undefined && usd(c.expected) ? ' (expected ' + usd(c.expected) + ')' : '') : 'Estimated cost: unavailable';
    var modelLine = est.model ? 'Model ' + est.model + (est.rate_version ? ' \u00b7 rates of ' + est.rate_version : '') : '';
    var bits = [n + ' input' + (n === 1 ? '' : 's')];
    if (n > 1 && (t.available || c.available)) bits.push('one at a time');
    if (t.available) bits.push('based on ' + t.n_runs + ' finished run' + (t.n_runs === 1 ? '' : 's') + (t.limited ? ' (limited history)' : ''));
    var detail = bits.join(' · ');
    if (!t.available && t.reason) detail += ' · ' + t.reason;
    if (!c.available && c.reason) detail += ' · ' + c.reason;
    return { state: t.available || c.available ? 'ready' : 'unavailable', time: time, cost: cost, detail: detail, inputs: n, modelLine: c.available ? modelLine : '',
             serialized: est.serialized_reason || '' };
  }

  /** Remaining time while running, only when the estimate is reliable (not limited). Never negative. */
  function remaining(est, elapsedMs) {
    var t = est && est.time;
    if (!t || !t.available || t.limited || typeof elapsedMs !== 'number') return null;
    var el = elapsedMs / 1000;
    var lo = Math.max(0, t.low - el), hi = Math.max(0, t.high - el);
    if (hi <= 0) return { overrun: true, text: 'taking longer than usual' };
    return { overrun: false, lo: lo, hi: hi, text: fmtRange(lo, hi) + ' left' };
  }

  /** Live / final line for a run. run: store.run; last: /last-run payload; costText: measured part cost text or ''. */
  function actual(run, last, now) {
    run = run || {};
    var running = run.state === 'running' || run.state === 'queued';
    if (running && run.startedAt) {
      return { kind: 'live', elapsed: fmtDur(Math.max(0, ((now || Date.now()) - run.startedAt) / 1000)) };
    }
    if (run.startedAt && run.finishedAt && run.state && run.state !== 'idle') {
      return { kind: 'final', elapsed: fmtDur((run.finishedAt - run.startedAt) / 1000), state: run.state };
    }
    if (last && last.run) {
      var r = last.run;
      return { kind: r.finished_at ? 'final' : 'unknown', elapsed: typeof r.seconds === 'number' ? fmtDur(r.seconds) : '',
               state: r.state, cost: r.cost_usd !== null && r.cost_usd !== undefined ? usd(r.cost_usd) : '', costStatus: r.cost_status };
    }
    return null;
  }

  return { fmtDur: fmtDur, fmtRange: fmtRange, usd: usd, usdRange: usdRange, describe: describe, remaining: remaining, actual: actual };
});
