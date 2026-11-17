/* McA.csv: PURE minimal RFC 4180 parser (multiview_summary.csv). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).csv = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** Text -> array of rows (arrays of strings). Handles quoted fields with commas, doubled quotes
      and embedded newlines; CRLF or LF; a BOM; a missing final newline. Blank lines are skipped. */
  function parseRows(text) {
    var s = String(text === null || text === undefined ? '' : text);
    if (s.charCodeAt(0) === 0xFEFF) s = s.slice(1);
    var rows = [], row = [], field = '', inQ = false, i = 0, n = s.length, touched = false;
    while (i < n) {
      var c = s.charAt(i);
      if (inQ) {
        if (c === '"') {
          if (s.charAt(i + 1) === '"') { field += '"'; i += 2; continue; }
          inQ = false; i++; continue;
        }
        field += c; i++; continue;
      }
      if (c === '"') { inQ = true; touched = true; i++; }
      else if (c === ',') { row.push(field); field = ''; touched = true; i++; }
      else if (c === '\r' || c === '\n') {
        if (c === '\r' && s.charAt(i + 1) === '\n') i++;
        i++;
        if (touched || field !== '' || row.length) { row.push(field); rows.push(row); }
        row = []; field = ''; touched = false;
      } else { field += c; touched = true; i++; }
    }
    if (touched || field !== '' || row.length) { row.push(field); rows.push(row); }
    return rows;
  }

  /** Text -> [{header: value}] using the first row as header. Empty input -> []. */
  function parse(text) {
    var rows = parseRows(text);
    if (!rows.length) return [];
    var head = rows[0].map(function (h) { return h.trim(); });
    return rows.slice(1).map(function (r) {
      var o = {};
      head.forEach(function (h, j) { o[h] = r[j] === undefined ? '' : r[j]; });
      return o;
    });
  }

  /** The summary row for a part (matching `part` or `source`), else the only row, else null. */
  function summaryRow(text, partName) {
    var rows = parse(text);
    if (!rows.length) return null;
    var hit = rows.filter(function (r) { return r.part === partName || r.source === partName; })[0];
    if (hit) return hit;
    return rows.length === 1 ? rows[0] : null;
  }

  return { parseRows: parseRows, parse: parse, summaryRow: summaryRow };
});
