/* McA.selectors: PURE derived values over the store state. No DOM, no fetch. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).selectors = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var ORIENTATIONS = [
    ['front', 'Front View'], ['back', 'Back View'], ['left', 'Left Side View'],
    ['right', 'Right Side View'], ['top', 'Top View'], ['bottom', 'Bottom View'],
    ['overview', 'Full Overview View'], ['marked', 'Marked View']
  ];
  /* Views that satisfy "one more orthographic view" alongside the mandatory FRONT view. */
  var ORTHO = ['top', 'bottom', 'left', 'right', 'back'];

  function isRunning(state) {
    var s = state.run && state.run.state;
    return s === 'running' || s === 'queued';
  }

  function selectedPart(state) {
    var sel = state.parts && state.parts.selected;
    if (!sel) return null;
    var list = state.parts.list || [];
    for (var i = 0; i < list.length; i++) if (list[i].name === sel.part) return list[i];
    return null;
  }

  /** Why the Run Pipeline button is disabled, or null when it is enabled. First match wins (ARCH 8.3). */
  function runDisabledReason(state) {
    var sel = state.parts && state.parts.selected;
    if (!state.server || !state.server.reachable) return 'Server unreachable.';
    if (isRunning(state)) return 'A run is in progress.';
    if (state.intake && state.intake.items && state.intake.items.length > 0 && !sel) return 'Save the part first (Part Setup).';
    if (!sel) return 'Select or create a part.';
    if (!state.server.live) return 'No ANTHROPIC_API_KEY on the server. Live extraction is unavailable; use Run Demo.';
    var part = selectedPart(state);
    if (!part || !(part.n_views >= 1)) return 'This part has no saved views.';
    return null;
  }

  /** Non-blocking amber note shown beside an enabled Run button, or null. */
  function runNote(state) {
    var part = selectedPart(state);
    if (!part || !(part.n_views >= 1)) return null;
    var views = part.views || [];
    var hasFront = views.some(function (v) { return String(v).toLowerCase().indexOf('front') !== -1; });
    return hasFront ? null : 'No FRONT view found; the base profile cannot be built without it.';
  }

  /** Deliverable chips for the header: from outputs.payload (the selected part's outputs). */
  function deliverables(state) {
    var p = state.outputs && state.outputs.payload;
    var c = (p && p.categories) || {};
    var macros = (c.macros && c.macros.files) || [];
    var stl = c.stl || {};
    var sld = !!(c.sldprt && c.sldprt.present);
    var vba = macros.length;
    return {
      sldprt: sld,
      stl: { present: !!stl.present, source: stl.present ? (stl.source || null) : null },
      vba: { present: vba > 0, count: vba },
      any: sld || !!stl.present || vba > 0
    };
  }

  function enc(s) { return encodeURIComponent(s); }

  /** Which image the 2D viewer shows (the old updateOverviewBox rule):
      a draft with previewOverride wins, else the selected part's overview, else the draft, else empty. */
  function drawingSource(state) {
    var intake = state.intake || { items: [] };
    var ovItem = null;
    for (var i = 0; i < (intake.items || []).length; i++) if (intake.items[i].orientation === 'overview') { ovItem = intake.items[i]; break; }
    var draftUrl = ovItem ? ovItem.dataURL : (intake.source || null);
    var sel = state.parts && state.parts.selected;
    if (intake.previewOverride && draftUrl) return { kind: 'draft', url: draftUrl };
    if (sel) return { kind: 'part', url: '/api/parts/' + enc(sel.session) + '/' + enc(sel.part) + '/overview.jpg',
                      session: sel.session, part: sel.part };
    if (draftUrl) return { kind: 'draft', url: draftUrl };
    return { kind: 'empty', url: null };
  }

  /** Duplicate orientations among the draft items. */
  function duplicateOrientations(items) {
    var seen = {}, dups = [];
    (items || []).forEach(function (it) {
      if (!it.orientation) return;
      if (seen[it.orientation] && dups.indexOf(it.orientation) === -1) dups.push(it.orientation);
      seen[it.orientation] = true;
    });
    return dups;
  }

  /** Part Setup validation: FRONT required, one more orthographic view, a name; duplicates allowed with a warning. */
  function intakeValidation(state) {
    var intake = state.intake || { items: [] };
    var items = intake.items || [];
    var assigned = items.map(function (i) { return i.orientation; }).filter(Boolean);
    var hasFront = assigned.indexOf('front') !== -1;
    var hasOther = assigned.some(function (o) { return ORTHO.indexOf(o) !== -1; });
    var named = !!String(intake.nameDraft || '').trim();
    var dups = duplicateOrientations(items);
    var out = { empty: !items.length, hasFront: hasFront, hasOther: hasOther, named: named, duplicates: dups,
                ok: false, canSave: false, level: 'info', message: '' };
    if (!items.length) return out;
    if (!hasFront) { out.level = 'warn'; out.message = 'Assign a FRONT view. The base profile cannot be built without it.'; }
    else if (!hasOther) { out.level = 'warn'; out.message = 'Assign at least one more orthographic view (Top, Bottom, Left, Right or Back) so depth can be read.'; }
    else if (!named) { out.level = 'info'; out.message = 'Name the part to save it.'; }
    else {
      out.ok = true;
      if (dups.length) { out.level = 'warn'; out.message = 'Duplicate orientation(s): ' + dups.join(', ') + '. You can save, but confirm the override.'; }
      else { out.level = 'ok'; out.message = 'Ready to save.'; }
    }
    out.canSave = out.ok && !isRunning(state);
    return out;
  }

  /** Counts of engineering flags by severity from outputs.payload.categories.review.items. */
  function flagSummary(payload) {
    var items = (payload && payload.categories && payload.categories.review && payload.categories.review.items) || [];
    var c = { critical: 0, high: 0, medium: 0, low: 0, total: items.length };
    items.forEach(function (it) {
      var s = String(it && it.severity || '').toLowerCase();
      if (s in c && s !== 'total') c[s]++;
    });
    var parts = ['critical', 'high', 'medium', 'low'].filter(function (k) { return c[k] > 0; })
      .map(function (k) { return c[k] + ' ' + k; });
    c.text = parts.length ? parts.join(', ') : 'None';
    return c;
  }

  /** "N of M parts complete" from batch state, or null when no batch is active/known. */
  function batchProgress(state) {
    var b = state.batch;
    if (!b || !b.queue || !b.queue.length) return null;
    var done = 0;
    b.queue.forEach(function (p) { if (b.results && b.results[p]) done++; });
    return { done: done, total: b.queue.length, text: done + ' of ' + b.queue.length + ' parts complete', active: !!b.active };
  }

  /** Elapsed milliseconds of the tracked run (live clock while running), or null when not recorded. */
  function runtimeMs(state, now) {
    var r = state.run;
    if (!r || !r.startedAt) return null;
    if (r.finishedAt) return Math.max(0, r.finishedAt - r.startedAt);
    return isRunning(state) ? Math.max(0, (now === undefined ? Date.now() : now) - r.startedAt) : null;
  }

  return { ORIENTATIONS: ORIENTATIONS, ORTHO: ORTHO, isRunning: isRunning, selectedPart: selectedPart,
           runDisabledReason: runDisabledReason, runNote: runNote, deliverables: deliverables,
           drawingSource: drawingSource, duplicateOrientations: duplicateOrientations,
           intakeValidation: intakeValidation, flagSummary: flagSummary, batchProgress: batchProgress,
           runtimeMs: runtimeMs };
});
