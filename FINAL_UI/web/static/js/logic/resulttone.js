/* McA.resulttone: pure health colour of each Pipeline Results section (no DOM, no network).
   One tone per section, from what the section actually holds, so the navigation tells you at a glance where to look:
     green  = good / complete        amber  = review      orange = significant      red = failed / wrong
     blue   = informational / present, nothing to judge     violet = holes and patterns     none = absent
   Every tone also gets a word, so colour is never the only cue. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).resulttone = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var RANK = { none: 0, blue: 1, green: 2, amber: 3, orange: 4, red: 5 };
  var SEV = { critical: 'red', error: 'red', high: 'orange', medium: 'amber', warning: 'amber', low: 'blue', info: 'blue' };

  function cats(p) { return (p && p.categories) || {}; }
  function worst(a, b) { return RANK[b] > RANK[a] ? b : a; }
  function mk(tone, word) { return { tone: tone, word: word }; }

  function planTone(p) {
    var c = cats(p), ir = c.ir_report || {}, sw = ir.sw_features;
    if (!c.build_plan || !c.build_plan.present) return mk('none', 'not available');
    if (!sw) return mk('blue', 'present');
    var vals = Object.keys(sw).map(function (k) { return String(sw[k]).toLowerCase(); });
    var bad = vals.filter(function (v) { return !/^built/.test(v); }).length, fb = vals.filter(function (v) { return /fallback|substitut|plain cut/.test(v); }).length;
    if (bad) return mk(bad === vals.length ? 'red' : 'orange', bad + ' not built');
    if (fb || (ir.questions || []).length) return mk('amber', fb ? fb + ' fallback' : (ir.questions || []).length + ' open question' + ((ir.questions || []).length === 1 ? '' : 's'));
    return mk('green', 'all built');
  }
  function flagsTone(p) {
    var c = cats(p), items = (c.review && c.review.items) || [], finds = (c.flags && c.flags.findings) || [], t = 'none', n = 0;
    items.forEach(function (i) { var s = SEV[String(i.severity || '').toLowerCase()]; if (s && s !== 'blue') { t = worst(t, s); n++; } else t = worst(t, 'blue'); });
    finds.forEach(function (f) { if (f.category === 'practice_advisory') return; var s = SEV[String(f.severity || '').toLowerCase()]; if (s) { t = worst(t, s); if (s !== 'blue') n++; } });
    if (t === 'none') return (c.review && c.review.present) || (c.flags && c.flags.present) ? mk('green', 'no flags') : mk('none', 'not available');
    return mk(t, n ? n + ' flag' + (n === 1 ? '' : 's') : 'notes');
  }
  function textTone(cat, failRe, okRe) {
    if (!cat || !cat.present) return mk('none', 'not available');
    var t = String(cat.text || '');
    if (failRe.test(t)) return mk('red', 'failed');
    if (okRe.test(t)) return mk('green', 'passed');
    return mk('blue', 'present');
  }
  function recTone(p) {
    var r = cats(p).recording || {};
    if (!r.present && r.status !== 'stale') return mk('none', 'not recorded');
    return { ready: mk('green', 'recorded'), partial: mk('amber', 'partial'), failed: mk('red', 'failed'), skipped: mk('amber', 'skipped'), stale: mk('amber', 'out of date'),
             interrupted: mk('amber', 'interrupted'), recording: mk('blue', 'recording') }[r.status] || mk('blue', 'present');
  }
  function costTone(p) {
    var u = cats(p).usage;
    if (!u || !u.present) return mk('none', 'not available');
    var s = u.ledger && u.ledger.scopes && u.ledger.scopes.part ? u.ledger.scopes.part.pricing_status : null;
    return s === 'priced' ? mk('green', 'priced') : s === 'partial' ? mk('amber', 'partial') : s === 'unpriced' ? mk('orange', 'unpriced') : mk('blue', 'present');
  }
  function mustTone(p) {
    var m = cats(p).must_meet;
    if (!m || !m.present) return mk('none', 'not available');
    var res = m.results || [], fail = res.filter(function (r) { return r.status === 'FAIL'; }).length;
    return fail ? mk('red', fail + ' failed') : res.length ? mk('green', 'all met') : mk('blue', 'present');
  }
  function consoleTone(lines, level) {
    if (!lines || !lines.length) return mk('none', 'not available');
    var err = 0, warn = 0;
    for (var i = 0; i < lines.length && i < 20000; i++) { var l = level(lines[i]); if (l === 'error') err++; else if (l === 'warning') warn++; }
    return err ? mk('red', err + ' error' + (err === 1 ? '' : 's')) : warn ? mk('amber', warn + ' warning' + (warn === 1 ? '' : 's')) : mk('green', 'clean');
  }
  function filesTone(p) {
    var c = cats(p);
    if (!(c.files && c.files.present)) return mk('none', 'not available');
    var sw = c.sldprt && c.sldprt.present, stl = c.stl && c.stl.present;
    if (sw && stl && c.stl.source === 'solidworks') return mk('green', 'complete');
    if (stl && c.stl.source !== 'solidworks') return mk('amber', 'pre-validation STL only');
    return sw || stl ? mk('amber', 'partial') : mk('blue', 'present');
  }
  function verdictTone(v) {
    return v === 'passed' ? mk('green', 'passed') : v === 'failed' ? mk('red', 'failed') : v === 'flags' ? mk('amber', 'review flags') : null;
  }

  /** {tone, word} of a section. extra: {verdict, lines}. levelFn: McA.logparse.level. */
  function sectionTone(id, payload, extra, levelFn) {
    var c = cats(payload);
    extra = extra || {};
    switch (id) {
      case 'overview': return verdictTone(extra.verdict) || (payload && payload.has_any ? mk('blue', 'present') : mk('none', 'not available'));
      case 'extraction': case 'resolved': case 'overview_analysis': return c[id] && c[id].present ? mk('green', 'present') : mk('none', 'not available');
      case 'build_plan': return planTone(payload);
      case 'verification': return verdictTone(extra.verdict) || textTone(c.verification, /\b(FAIL(ED)?|BLOCKED|ERROR)\b/, /\b(PASS(ED)?|READY|OK)\b/);
      case 'flags': return flagsTone(payload);
      case 'model_check': return textTone(c.model_check, /\b(FAIL(ED)?|ERROR|MISMATCH)\b/, /\b(PASS(ED)?|OK|MATCH)\b/);
      case 'recording': return recTone(payload);
      case 'must_meet': return mustTone(payload);
      case 'macros': return c.macros && c.macros.present ? mk('green', 'generated') : mk('none', 'not available');
      case 'files': return filesTone(payload);
      case 'cost': return costTone(payload);
      case 'console': { var ls = extra.lines && extra.lines.length ? extra.lines : (c.console && typeof c.console.text === 'string' ? c.console.text.split('\n') : []); return consoleTone(ls, levelFn || function () { return 'info'; }); }
      case 'scoring_rubric': return mk('none', '');
      default: return mk('none', '');
    }
  }
  /** Tone of a file by extension (Files table). */
  function fileTone(name) {
    var e = String(name).toLowerCase().replace(/^.*\./, '');
    return ({ sldprt: 'blue', stl: 'violet', step: 'violet', json: 'amber', jsonl: 'amber', pdf: 'red', png: 'green', jpg: 'green', mp4: 'orange', webm: 'orange', vba: 'blue', log: 'none', txt: 'none', py: 'none', csv: 'green' })[e] || 'none';
  }
  return { sectionTone: sectionTone, fileTone: fileTone, worst: worst, RANK: RANK };
});
