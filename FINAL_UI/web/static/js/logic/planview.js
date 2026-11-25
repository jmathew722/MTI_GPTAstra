/* McA.planview: pure reading of a build plan (no DOM, no network).
   Two plan shapes exist. The legacy v1 plan has a top-level "steps" array. The Feature-IR plan (every current build) is
   { dims, reference_ids, plan: { ir_version, part, frame, features: [...], notes } } with NO "steps" array: a viewer that
   only knew v1 showed an empty Build Plan for every IR build. This module reads the IR shape: the operations in build
   order, their numbers resolved from the dimension table, and the status SolidWorks reported for each one (ir_report.sw_features).
   Numbers are resolved by a tiny arithmetic parser (D### ids, numbers, + - * / and parentheses): never eval. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).planview = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var HIDE = { id: 1, rationale: 1, source_callouts: 1, status: 1, justification: 1, kind: 1, op: 1 };

  function detect(obj) {
    if (obj && typeof obj === 'object') {
      if (obj.plan && Array.isArray(obj.plan.features)) return 'ir';
      if (Array.isArray(obj.steps)) return 'v1';
    }
    return 'unknown';
  }

  /** Evaluate "D010 / 2 - D009" against {D010: 3.501, ...}. Returns a number, or null when it is not plain arithmetic or an id is unknown. */
  function evalExpr(expr, dims) {
    if (typeof expr === 'number') return isFinite(expr) ? expr : null;
    if (typeof expr !== 'string' || !expr.trim()) return null;
    var toks = expr.match(/\s*(\d+\.?\d*|\.\d+|D\d+|[-+*\/()])\s*/g);
    if (!toks || toks.join('').replace(/\s+/g, '') !== expr.replace(/\s+/g, '')) return null;
    toks = toks.map(function (t) { return t.trim(); });
    var i = 0, bad = false;
    function val(tok) { if (/^D\d+$/.test(tok)) { var v = dims && dims[tok]; if (typeof v !== 'number') { bad = true; return 0; } return v; } return parseFloat(tok); }
    function prim() {
      var t = toks[i++];
      if (t === '(') { var v = sum(); if (toks[i++] !== ')') bad = true; return v; }
      if (t === '-') return -prim();
      if (t === '+') return prim();
      if (t === undefined || /^[*\/)]$/.test(t)) { bad = true; return 0; }
      return val(t);
    }
    function prod() { var v = prim(); while (toks[i] === '*' || toks[i] === '/') { var o = toks[i++], r = prim(); v = o === '*' ? v * r : v / r; } return v; }
    function sum() { var v = prod(); while (toks[i] === '+' || toks[i] === '-') { var o = toks[i++], r = prod(); v = o === '+' ? v + r : v - r; } return v; }
    var out = sum();
    if (bad || i !== toks.length || !isFinite(out)) return null;
    return Math.round(out * 1e6) / 1e6;
  }

  /** Colour family of an operation. */
  function kindMeta(f) {
    var kind = String((f && f.kind) || 'feature'), op = String((f && f.op) || '');
    var labels = { prism: 'Extrude', revolve: 'Revolve', hole: 'Hole', pattern: 'Pattern', edge_op: 'Edge treatment' };
    var label = labels[kind] || kind.replace(/_/g, ' ');
    if (kind === 'hole') return { label: label, tone: 'violet' };
    if (kind === 'pattern') return { label: label, tone: 'violet' };
    if (kind === 'edge_op') return { label: label, tone: 'amber' };
    if (op === 'cut') return { label: label + ' (cut)', tone: 'orange' };
    return { label: label + (op === 'add' ? ' (add)' : ''), tone: 'blue' };
  }

  /** What SolidWorks reported for one feature id. sw: ir_report.sw_features. */
  function statusOf(fid, sw, f, questions) {
    var s = sw && sw[fid] !== undefined ? String(sw[fid]) : '';
    if (s) {
      var low = s.toLowerCase();
      if (/^built/.test(low)) return /fallback|substitut|plain cut/.test(low) ? { id: 'fallback', label: 'Built with a fallback', tone: 'amber', detail: s } : { id: 'built', label: 'Built', tone: 'green', detail: s };
      if (/skip/.test(low)) return { id: 'skipped', label: 'Skipped', tone: 'red', detail: s };
      return { id: 'failed', label: 'Not built', tone: 'red', detail: s };
    }
    var asked = (questions || []).some(function (q) { return new RegExp('\\b' + fid + '\\b').test(String(q)); });
    if (asked) return { id: 'decision', label: 'Needs a decision', tone: 'orange', detail: 'The planner asked a question instead of guessing.' };
    var ps = String((f && f.status) || '');
    if (/skip|prohibit/.test(ps)) return { id: 'skipped', label: 'Skipped', tone: 'red', detail: ps };
    return { id: 'planned', label: sw ? 'No build status' : 'Planned', tone: sw ? 'orange' : 'none', detail: sw ? 'SolidWorks reported nothing for this operation.' : 'No build has run for this plan yet.' };
  }

  /** Flatten a feature into [{key, raw, value}] rows: every scalar, numbers resolved through the dimension table. */
  function params(f, dims) {
    var rows = [];
    (function walk(path, v) {
      if (v === null || v === undefined) return;
      if (Array.isArray(v)) { v.forEach(function (x, i) { walk(path + '[' + (i + 1) + ']', x); }); return; }
      if (typeof v === 'object') { Object.keys(v).forEach(function (k) { walk(path ? path + '.' + k : k, v[k]); }); return; }
      var raw = String(v), num = evalExpr(v, dims);
      rows.push({ key: path, raw: raw, value: num !== null && raw !== String(num) ? num : null });
    })('', Object.keys(f || {}).reduce(function (o, k) { if (!HIDE[k]) o[k] = f[k]; return o; }, {}));
    return rows.filter(function (r) { return r.key; });
  }

  function notesFor(fid, lines) {
    var re = new RegExp('^\\s*' + fid + '\\s*[:\\-]\\s*'), out = [];
    (lines || []).forEach(function (l) { if (re.test(String(l))) out.push(String(l).replace(re, '')); });
    return out;
  }

  /** How many operations reference each dimension id. {D001: 3, ...}; ids never referenced have 0. */
  function dimUsage(plan, dims) {
    var use = {}; Object.keys(dims || {}).forEach(function (k) { use[k] = 0; });
    var text = JSON.stringify((plan && plan.features) || []);
    (text.match(/D\d+/g) || []).forEach(function (id) { if (id in use) use[id] += 1; });
    return use;
  }

  /** The whole reading. obj = parsed plan.json, ir = categories.ir_report (sw_features, flagged, defaults, questions). */
  function read(obj, ir) {
    var kind = detect(obj);
    if (kind !== 'ir') return { kind: kind };
    var plan = obj.plan, dims = obj.dims || {}, sw = ir && ir.sw_features ? ir.sw_features : null;
    var qs = (ir && ir.questions) || [], flags = (ir && ir.flagged) || [], defs = (ir && ir.defaults) || [];
    var feats = plan.features.map(function (f, i) {
      var st = statusOf(f.id, sw, f, qs), km = kindMeta(f);
      return { seq: i + 1, id: f.id, kind: f.kind, op: f.op, kindLabel: km.label, tone: km.tone, rationale: f.rationale || '', justification: f.justification || '',
               callouts: f.source_callouts || [], status: st, params: params(f, dims), flags: notesFor(f.id, flags), defaults: notesFor(f.id, defs), raw: f };
    });
    var count = function (id) { return feats.filter(function (x) { return x.status.id === id; }).length; };
    var use = dimUsage(plan, dims);
    return { kind: 'ir', part: plan.part || '', units: (plan.frame && plan.frame.units) || '', irVersion: plan.ir_version || '', frame: plan.frame || {}, notes: plan.notes || [],
             features: feats, dims: dims, referenceIds: obj.reference_ids || [], usage: use,
             summary: { total: feats.length, built: count('built'), fallback: count('fallback'), skipped: count('skipped') + count('failed'), decision: count('decision'),
                        planned: count('planned'), noStatus: feats.filter(function (x) { return x.status.label === 'No build status'; }).length,
                        dims: Object.keys(dims).length, unusedDims: Object.keys(use).filter(function (k) { return use[k] === 0 && (obj.reference_ids || []).indexOf(k) < 0; }).length } };
  }

  /** Does a feature match a search query (id, kind, rationale, callouts, parameters)? */
  function matches(feat, q) {
    var t = String(q || '').trim().toLowerCase();
    if (!t) return true;
    var hay = [feat.id, feat.kindLabel, feat.rationale, feat.justification, feat.status.label, (feat.callouts || []).join(' '), feat.params.map(function (p) { return p.key + ' ' + p.raw; }).join(' ')].join(' ').toLowerCase();
    return hay.indexOf(t) >= 0;
  }

  return { detect: detect, evalExpr: evalExpr, kindMeta: kindMeta, statusOf: statusOf, params: params, notesFor: notesFor, dimUsage: dimUsage, read: read, matches: matches };
});
