/* McA.logparse: PURE console line -> structured event parsing (ARCH 11 "events" section).
   Formats were read from main.py, pipeline/batch.py and webapp/app.py. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).logparse = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var KINDS = ['stage', 'spec', 'preval', 'mm', 'overview', 'delivered', 'cancel', 'error', 'exit'];

  /** One line -> {kind, text, ...fields}, or null when it is ordinary output. */
  function parse(line) {
    var s = String(line === null || line === undefined ? '' : line).replace(/\r$/, '');
    var m;
    if ((m = /^\s*\[STAGE\]\s+(.*?)\s*$/.exec(s))) return { kind: 'stage', text: m[1], name: m[1] };
    if ((m = /^\[SPEC\] (CRITICAL|HIGH|MEDIUM|LOW): (.*)$/.exec(s))) return { kind: 'spec', text: m[2], severity: m[1] };
    if ((m = /^\[SPEC\] (.*)$/.exec(s))) return { kind: 'spec', text: m[1], severity: null };
    if ((m = /^\[PREVAL\] (.*)$/.exec(s))) {
      return { kind: 'preval', text: m[1], pass: /^PASS\b/.test(m[1]) ? true : null };
    }
    if ((m = /^\[MM\] verification error: (.*)$/.exec(s))) return { kind: 'mm', text: m[1], error: true, status: 'ERROR' };
    if ((m = /^\[MM\] (\S+) (\S+): required (.*), measured (.*)$/.exec(s))) {
      return { kind: 'mm', text: m[1] + ' ' + m[2], id: m[1], status: m[2], required: m[3], measured: m[4], error: false };
    }
    if ((m = /^\[OVERVIEW\] (.*)$/.exec(s))) return { kind: 'overview', text: m[1] };
    if ((m = /^\[delivered outputs to\] (.*)$/.exec(s))) return { kind: 'delivered', text: m[1], path: m[1] };
    if (/^\[cancel requested by user\]/.test(s)) return { kind: 'cancel', text: 'Cancel requested by user' };
    if ((m = /^\[(launch error|reader error|cancel error)\] (.*)$/.exec(s))) return { kind: 'error', text: m[2], source: m[1] };
    if ((m = /Extraction failed.*$/.exec(s))) return { kind: 'error', text: m[0].trim(), source: 'extraction' };
    if ((m = /Processing failed:.*$/.exec(s))) return { kind: 'error', text: m[0].trim(), source: 'processing' };
    return null;
  }

  /** Lines -> events [{index, kind, text, ...}]. When opts.exit is a number an `exit` event is appended
      (the exit code comes from the SSE "done" event, it is not a console line). */
  function events(lines, opts) {
    var out = [];
    (lines || []).forEach(function (l, i) {
      var e = parse(l);
      if (e) { e.index = i; out.push(e); }
    });
    if (opts && typeof opts.exit === 'number') {
      out.push({ index: (lines || []).length, kind: 'exit', text: 'Exited with code ' + opts.exit, exit: opts.exit });
    }
    return out;
  }

  /** Console filter class of a line: 'stage' | 'error' | 'warning' | 'info'. */
  function level(line) {
    var s = String(line === null || line === undefined ? '' : line);
    if (/^\s*\[STAGE\]/.test(s) || /^\s*\[(1-2|2\.5|3|4)\/4\]/.test(s)) return 'stage';
    if (/^\[(launch|reader|cancel) error\]/.test(s) || /\b(Extraction failed|Processing failed|Traceback)\b/.test(s) ||
        /^\[MM\] \S+ FAIL\b/.test(s) || /^\[MM\] verification error/.test(s)) return 'error';
    if (/^\[SPEC\] (CRITICAL|HIGH):/.test(s) || /warning|unavailable|Could not classify|No FRONT view/i.test(s) ||
        /^\[PREVAL\] (?!PASS)/.test(s) || /^\[cancel requested/.test(s)) return 'warning';
    return 'info';
  }

  return { KINDS: KINDS, parse: parse, events: events, level: level };
});
