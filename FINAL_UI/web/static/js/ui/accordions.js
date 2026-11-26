/* Workspace accordions (v6): "Material Selection" (inside Part Setup) and "Runtime & cost" (under Pipeline Actions).
   Collapsed by default. A header is a real <button> (aria-expanded + aria-controls; Enter and Space come from the element).
   Collapsing only toggles `hidden` on the body: no state is reset and no live update stops (estimate.js and materials.js
   keep rendering into the hidden body). The summary text comes from logic/collapsibles.js. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var $ = function (id) { return document.getElementById(id); };
  var C, clock = null;
  var DEFS = [
    { key: 'mat', btn: 'mat-acc-btn', body: 'mat-acc-body', root: 'mat-lib' },
    { key: 'rt', btn: 'rt-acc-btn', body: 'run-estimate', root: 'rt-acc' },
  ];

  function setOpen(d, on) {
    var b = $(d.btn), body = $(d.body); if (!b || !body) return;
    b.setAttribute('aria-expanded', String(on)); body.hidden = !on; $(d.root).setAttribute('data-open', String(on));
  }
  function isOpen(d) { var b = $(d.btn); return !!b && b.getAttribute('aria-expanded') === 'true'; }

  function selCtx() { var sl = McA.store.get().parts.selected; return sl && sl.part ? { kind: 'part', session: sl.session, part: sl.part } : null; }
  function renderMaterial() {
    C = C || McA.collapsibles;
    var sum = $('mat-acc-sum'), warn = $('mat-acc-warn'); if (!sum || !McA.materials || !C) return;
    var ctx = selCtx(), e = ctx ? McA.materials.entry(ctx) : null, MV = McA.materialview;
    var data = e && e.state === 'ready' ? e.data : null;
    var s = data ? MV.summary(data) : null;
    var r = C.materialSummary({ hasPart: !!ctx, entry: e, status: s && s.status, title: s && s.title, libError: McA.materials.libError ? McA.materials.libError() : '' });
    sum.textContent = r.text; sum.setAttribute('data-tone', r.tone); sum.title = r.text;
    warn.textContent = r.warn; warn.hidden = !r.warn;
  }

  function lastElapsed(s) {
    var run = s.run || {};
    return run.startedAt && run.finishedAt ? run.finishedAt - run.startedAt : null;
  }
  function renderRuntime() {
    C = C || McA.collapsibles;
    var sum = $('rt-acc-sum'); if (!sum || !C) return;
    var s = McA.store.get(), run = s.run || {}, busy = run.state === 'running' || run.state === 'queued';
    var est = $('run-estimate');
    var r = C.runtimeSummary({ runState: run.state, elapsedMs: busy && run.startedAt ? Date.now() - run.startedAt : null,
      estState: est ? est.getAttribute('data-state') : '', lastElapsedMs: lastElapsed(s) });
    sum.textContent = r.text; sum.setAttribute('data-tone', r.tone); sum.title = r.text;
    if (busy && !clock) clock = setInterval(renderRuntime, 1000);
    if (!busy && clock) { clearInterval(clock); clock = null; }
  }

  McA.accordions = {
    init: function () {
      C = McA.collapsibles; if (!C) return;
      DEFS.forEach(function (d) {
        var b = $(d.btn); if (!b) return;
        setOpen(d, false);
        b.addEventListener('click', function () { setOpen(d, !isOpen(d)); });
      });
      if (McA.materials && McA.materials.onChange) McA.materials.onChange(renderMaterial);
      McA.store.subscribe(function (s) { return s.parts.selected; }, renderMaterial);
      McA.store.subscribe(function (s) { return s.run; }, renderRuntime);
      renderMaterial(); renderRuntime();
    },
    reset: function () { DEFS.forEach(function (d) { setOpen(d, false); }); },
    isOpen: function (key) { var d = DEFS.filter(function (x) { return x.key === key; })[0]; return !!d && isOpen(d); },
    open: function (key) { DEFS.forEach(function (d) { if (d.key === key) setOpen(d, true); }); },
    refreshMaterial: renderMaterial, refreshRuntime: renderRuntime,
  };
})();
