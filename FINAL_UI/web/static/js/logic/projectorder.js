/* McA.projectorder: pure ordering and date formatting for Projects (no DOM).
   Newest activity first (a project's creation or its latest run/update, NEVER a thumbnail render or a page view),
   numeric on epoch seconds, stable tie-break on the name, unknown dates last. Timestamps are stored in UTC by the
   server and shown in the viewer's local time. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).projectorder = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  function num(v) { return typeof v === 'number' && isFinite(v) ? v : null; }

  function sortParts(list) {
    return (list || []).slice().sort(function (a, b) {
      var x = num(a.last_activity), y = num(b.last_activity);
      if (x === null && y === null) return String(a.name).toLowerCase() < String(b.name).toLowerCase() ? -1 : String(a.name).toLowerCase() > String(b.name).toLowerCase() ? 1 : 0;
      if (x === null) return 1;
      if (y === null) return -1;
      if (y !== x) return y - x;
      var an = String(a.name).toLowerCase(), bn = String(b.name).toLowerCase();
      return an < bn ? -1 : an > bn ? 1 : 0;
    });
  }
  /** Local date and time, e.g. "Nov 19, 2026, 4:22 PM"; "Date unknown" when there is no trustworthy timestamp. */
  function fmtWhen(epochSec, locale, tz) {
    var n = num(epochSec);
    if (n === null) return 'Date unknown';
    try {
      return new Date(n * 1000).toLocaleString(locale || undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: tz || undefined });
    } catch (e) { return new Date(n * 1000).toISOString(); }
  }
  function isoOf(epochSec) { var n = num(epochSec); return n === null ? '' : new Date(n * 1000).toISOString(); }
  /** "Last activity ..." with the creation time kept separate when it differs. */
  function whenLine(p, locale, tz) {
    var last = fmtWhen(p.last_activity, locale, tz);
    if (num(p.last_activity) === null) return { primary: last, secondary: '' };
    var created = num(p.created_at);
    return { primary: last, secondary: created !== null && Math.abs(created - p.last_activity) > 60 ? 'Created ' + fmtWhen(created, locale, tz) : '' };
  }
  return { sortParts: sortParts, fmtWhen: fmtWhen, isoOf: isoOf, whenLine: whenLine };
});
