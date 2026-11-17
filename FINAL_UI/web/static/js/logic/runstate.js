/* McA.runstate: PURE run state and verification verdict (ARCH 4.4). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).runstate = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function statusOf(summary) {
    return summary && summary.status ? String(summary.status).toUpperCase() : null;
  }

  /** {hasId, done, exit, cancelled, launching, summary?} -> idle | queued | running | cancelled |
      succeeded | succeeded_with_warnings | failed.
      Exit 8 is "at least one part not READY": warnings only when the summary row says NOT READY
      (or no summary is available); BLOCKED or ERROR make it failed. */
  function deriveRunState(o) {
    o = o || {};
    if (!o.hasId) return o.launching ? 'queued' : (o.queued ? 'queued' : 'idle');
    if (!o.done) return 'running';
    if (o.cancelled) return 'cancelled';
    if (o.exit === 0) return 'succeeded';
    if (o.exit === 8) {
      var st = statusOf(o.summary);
      return st === 'BLOCKED' || st === 'ERROR' ? 'failed' : 'succeeded_with_warnings';
    }
    return 'failed';
  }

  /** Verification verdict, shown separately from the run state.
      {summary, mustMeet, stlSource, stlFresh, kind, exit, cancelled} -> passed | passed_unbuilt | flags | failed | unknown */
  function deriveVerdict(o) {
    o = o || {};
    if (o.cancelled) return 'unknown';
    var st = statusOf(o.summary);
    var mm = o.mustMeet || null;
    if (o.kind === 'demo') {
      if (o.exit === 4 || o.exit === 6 || o.exit === 7) return 'failed';
      if (o.exit === 0) return 'passed_unbuilt';
      return 'unknown';
    }
    if (st === 'BLOCKED' || st === 'ERROR') return 'failed';
    if (mm && mm.stage === 'post_build' && mm.ok === false) return 'failed';
    if (st === 'NOT READY') return 'flags';
    if (st === 'READY') return o.stlSource === 'solidworks' && o.stlFresh ? 'passed' : 'passed_unbuilt';
    return 'unknown';
  }

  /** The STL belongs to this run when it was written at or after the run started.
      startedSec is epoch seconds; defaults to payload.started. */
  function stlFresh(payload, startedSec) {
    if (!payload || typeof payload.stl_mtime !== 'number' || payload.stl_mtime <= 0) return false;
    var s = typeof startedSec === 'number' ? startedSec : payload.started;
    return typeof s === 'number' && payload.stl_mtime >= Math.floor(s);
  }

  /** Fallback when the summary CSV cannot be fetched: last "N/M READY" in the console.
      Returns {status:'READY'|'NOT READY', n_ready, n_total, fallback:true} or null.
      "NOT READY" is the most that can be said when N < M (the console does not say BLOCKED or ERROR). */
  function summaryFromConsole(lines) {
    var re = /(\d+)\/(\d+) READY/;
    for (var i = (lines || []).length - 1; i >= 0; i--) {
      var m = re.exec(lines[i]);
      if (m) {
        var n = +m[1], t = +m[2];
        return { status: n === t && t > 0 ? 'READY' : 'NOT READY', n_ready: n, n_total: t, fallback: true };
      }
    }
    return null;
  }

  var LABELS = {
    idle: 'Idle', queued: 'Queued', running: 'Running', cancelled: 'Cancelled', succeeded: 'Succeeded',
    succeeded_with_warnings: 'Succeeded with warnings', failed: 'Failed'
  };
  var VERDICT_LABELS = {
    passed: 'Passed', passed_unbuilt: 'Checks passed, model not built', flags: 'Review flags',
    failed: 'Failed', unknown: 'Not available'
  };

  return { deriveRunState: deriveRunState, deriveVerdict: deriveVerdict, stlFresh: stlFresh,
           summaryFromConsole: summaryFromConsole, STATE_LABELS: LABELS, VERDICT_LABELS: VERDICT_LABELS };
});
