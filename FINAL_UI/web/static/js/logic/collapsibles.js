/* McA.collapsibles: PURE summary text for the two workspace accordions ("Material Selection", "Runtime & cost").
   No DOM, no network, no values of its own: everything comes from the caller's real state. Unknown is "N/A" or
   "Pending", never a guess, and never a negative duration. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).collapsibles = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var NA = 'N/A';

  /** Short elapsed time for a header: 42s, 3m 05s, 1h 02m. Anything unusable (null, NaN, negative) is N/A. */
  function fmtShort(ms) {
    if (typeof ms !== 'number' || !isFinite(ms) || ms < 0) return NA;
    var s = Math.floor(ms / 1000);
    if (s < 60) return s + 's';
    var m = Math.floor(s / 60), r = s % 60;
    if (m < 60) return m + 'm ' + (r < 10 ? '0' : '') + r + 's';
    var h = Math.floor(m / 60), mm = m % 60;
    return h + 'h ' + (mm < 10 ? '0' : '') + mm + 'm';
  }

  /** Time-left text from estimateview.remaining(): never negative; "taking longer than usual" once the estimate is used up. */
  function leftText(remaining) {
    if (!remaining) return NA;
    return remaining.overrun ? 'taking longer than usual' : String(remaining.text || NA).replace(/ left$/, '');
  }

  /** Material Selection header. in: {hasPart, entry:{state,data,error}|null, status:{id,label,tone}|null, title, libError}
   *  -> {text, tone, warn}. warn is non-empty for anything that needs attention; it stays visible while collapsed. */
  function materialSummary(o) {
    o = o || {};
    var lib = o.libError ? 'Material library: ' + o.libError : '';
    if (!o.hasPart) return { text: 'No material specified', tone: 'none', warn: lib };
    var e = o.entry;
    if (!e || (e.state === 'loading' && !e.data)) return { text: 'Pending', tone: 'none', warn: lib };
    if (e.state === 'error') return { text: 'Unavailable', tone: 'amber', warn: 'Could not read the material: ' + (e.error || 'unknown error') };
    var d = e.data;
    if (!d || !d.evaluated) return { text: 'Pending', tone: 'none', warn: lib };
    var st = o.status || { label: '', tone: 'none' }, id = st.id || '';
    if (id === 'not_specified') return { text: 'No material specified', tone: 'none', warn: lib };
    var attention = st.tone === 'amber' || st.tone === 'orange' || st.tone === 'red';
    var text = o.title && (id === 'assigned_verified' || id === 'matched') ? o.title : (st.label || 'Pending');
    var warn = attention ? st.label + (o.title && o.title !== st.label ? ' (' + o.title + ')' : '') : '';
    if (d.stale && !warn) warn = 'The material library changed since this result';
    if (lib) warn = warn ? warn + '. ' + lib : lib;
    return { text: text, tone: attention ? st.tone : id === 'assigned_verified' ? 'green' : 'none', warn: warn };
  }

  /** Runtime & cost header. in: {runState, elapsedMs, estState, lastElapsedMs} -> {text, tone}. */
  function runtimeSummary(o) {
    o = o || {};
    var st = o.runState || 'idle';
    if (st === 'running' || st === 'queued') {
      var el = fmtShort(o.elapsedMs);
      return { text: (st === 'queued' ? 'Queued' : 'Running') + (el !== NA ? ' · ' + el : ''), tone: 'run' };
    }
    var t = o.lastElapsedMs !== undefined && o.lastElapsedMs !== null ? fmtShort(o.lastElapsedMs) : NA;
    var tail = t !== NA ? ' · ' + t : '';
    if (st === 'succeeded') return { text: 'Completed' + tail, tone: 'ok' };
    if (st === 'succeeded_with_warnings') return { text: 'Completed with warnings' + tail, tone: 'warn' };
    if (st === 'failed') return { text: 'Failed' + tail, tone: 'err' };
    if (st === 'cancelled') return { text: 'Cancelled' + tail, tone: 'none' };
    if (o.estState === 'error') return { text: 'Estimate unavailable', tone: 'warn' };
    return { text: 'Idle', tone: 'none' };
  }

  return { NA: NA, fmtShort: fmtShort, leftText: leftText, materialSummary: materialSummary, runtimeSummary: runtimeSummary };
});
