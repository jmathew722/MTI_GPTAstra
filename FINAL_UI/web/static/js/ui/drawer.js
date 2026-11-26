/* Pipeline Results drawer: toggle, resize, Results/Tools modes, header summary, inspector relocation below 1440. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var DS = McA.drawerSize, DEF = DS.DEFAULT, MIN = DS.MIN;
  var el = {}, mqWide, mqFlow, clock = null, lastRunState = null, curH = DEF, fitTimer = null;

  var STATE = {
    idle: ['No run yet', null], queued: ['Queued', 'spinner'], running: ['Running', 'spinner'], succeeded: ['Completed', 'check'],
    succeeded_with_warnings: ['Completed with warnings', 'warn'], failed: ['Failed', 'x'], cancelled: ['Cancelled', 'dash'],
  };
  var VERDICT = {
    passed: ['Passed', 'is-ok', 'check'], passed_unbuilt: ['Checks passed, model not built', 'is-muted', 'info'],
    flags: ['Review flags', 'is-warn', 'warn'], failed: ['Failed', 'is-err', 'x'], unknown: ['Not available', 'is-muted', null],
  };
  function ui() { return McA.store.get().ui || {}; }
  /* Real measurements, never a viewport fraction: the maximum is the space left under the header and tracker. */
  function metrics() {
    var page = document.getElementById('page-workspace'), cs = getComputedStyle(page);
    var pad = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
    var head = page.querySelector('.ws-head'), trk = page.querySelector('.tracker');
    return { flow: mqFlow.matches, pageH: page.clientHeight - pad, headH: head ? head.offsetHeight : 0,
             trackerH: trk ? trk.offsetHeight : 0, gap: parseFloat(cs.rowGap) || 12,
             viewportH: (el.scroller || document.documentElement).clientHeight };
  }
  function maxH() { return DS.maxHeight(metrics()); }
  function clampH(h) { return DS.clamp(h, MIN, maxH()); }
  /* Height that shows the whole current content (header + the tallest of rail / pane / tools), capped at the maximum. */
  function fitH() {
    var tools = !el.tools.hidden, body = tools ? el.tools : el.pane;
    var need = el.head.offsetHeight + 2 + Math.max(body.scrollHeight, tools ? 0 : el.secs.scrollHeight);
    return need;
  }
  function sizeState() { var z = ui().drawerSize; return DS.SIZES.indexOf(z) >= 0 ? z : 'remembered'; }

  function renderLayout() {
    var u = ui(), wide = mqWide.matches;
    var open = !!u.drawerOpen;
    var mode = !wide && u.drawerMode === 'tools' ? 'tools' : 'results';
    el.drawer.setAttribute('data-open', String(open));
    el.toggle.setAttribute('aria-expanded', String(open));
    el.body.hidden = !open;
    el.modeTools.hidden = wide;
    [['results', el.modeResults, el.results], ['tools', el.modeTools, el.tools]].forEach(function (m) {
      var on = m[0] === mode; m[1].setAttribute('aria-selected', String(on)); m[1].tabIndex = on ? 0 : -1; m[2].hidden = !on;
    });
    if (!el.page.offsetParent) return;                       // workspace page not shown: nothing to measure
    var size = sizeState(), max = maxH();
    var remembered = DS.rememberedFor(u.drawerHeights, DS.viewportClass(window.innerWidth), DS.sanitize(u.drawerHeight, DEF));
    var h = DS.resolve({ size: size, remembered: remembered, fit: open ? fitH() : DEF, min: MIN, max: max });
    curH = h;
    el.drawer.style.setProperty('--dr-h', h + 'px');
    el.page.setAttribute('data-dr-max', String(open && h >= max - 1));
    el.resize.setAttribute('aria-valuemin', String(MIN)); el.resize.setAttribute('aria-valuemax', String(max));
    el.resize.setAttribute('aria-valuenow', String(h));
    el.fit.setAttribute('aria-pressed', String(size === 'fit')); el.max.setAttribute('aria-pressed', String(size === 'max'));
    el.max.querySelector('span').textContent = size === 'max' ? 'Restore' : 'Maximize';
    el.sizeBox.hidden = !open;
  }
  function placeInspector() {
    var insp = document.getElementById('inspector');
    if (mqWide.matches) { if (insp.parentNode !== el.main) el.main.appendChild(insp); }
    else if (insp.parentNode !== el.tools) el.tools.appendChild(insp);
    renderLayout();
  }

  function sevCounts(items) {
    var c = {}; items.forEach(function (i) { var s = String(i.severity || '').toLowerCase(); c[s] = (c[s] || 0) + 1; });
    return c;
  }
  function setKv(node, text, cls, icon) {
    var v = node.querySelector('.v'); v.className = 'v' + (node.id === 'dr-runtime' ? ' mono' : '') + (cls ? ' ' + cls : '');
    v.replaceChildren(); if (icon) v.append(McA.icons.get(icon, 14)); v.append(document.createTextNode(text));
  }
  function renderSummary() {
    var s = McA.store.get(), run = s.run || {};
    var st = STATE[run.state] || STATE.idle;
    el.state.setAttribute('data-state', run.state || 'idle');
    el.state.replaceChildren(); if (st[1]) el.state.append(McA.icons.get(st[1], 14)); el.state.append(document.createTextNode(st[0]));
    var v = VERDICT[run.verdict] || VERDICT.unknown;
    setKv(el.verdict, v[0], v[1], v[2]);

    var payload = s.outputs && s.outputs.payload, rev = payload && payload.categories && payload.categories.review;
    if (rev && rev.present) {
      var items = rev.items || [];
      if (!items.length) setKv(el.flags, 'None', 'is-ok', 'check');
      else {
        var c = sevCounts(items);
        var txt = ['critical', 'high', 'medium', 'low'].filter(function (k) { return c[k]; }).map(function (k) { return c[k] + ' ' + k; }).join(', ');
        setKv(el.flags, txt, c.critical ? 'is-err' : c.high ? 'is-warn' : '', 'warn');
      }
    } else setKv(el.flags, 'Not available', 'is-muted');

    var busy = run.state === 'running' || run.state === 'queued';
    if (busy && run.startedAt) setKv(el.runtime, McA.dom.fmtDur(Date.now() - run.startedAt), '');
    else if (run.startedAt && run.finishedAt) setKv(el.runtime, McA.dom.fmtDur(run.finishedAt - run.startedAt), '');
    else setKv(el.runtime, 'Not recorded', 'is-muted');
    if (busy && !clock) clock = setInterval(renderSummary, 1000);
    if (!busy && clock) { clearInterval(clock); clock = null; }
  }

  /* A user resize: remember it for this viewport class and leave fit/maximum. */
  function setHeight(h) {
    var cls = DS.viewportClass(window.innerWidth), v = clampH(h);
    var map = Object.assign({}, ui().drawerHeights || {}); map[cls] = v;
    McA.dom.setUi({ drawerHeight: v, drawerHeights: map, drawerSize: 'remembered', drawerOpen: true });
  }
  function scheduleFit() {            // content changed while "fit" is active: follow it
    if (sizeState() !== 'fit' || !ui().drawerOpen) return;
    if (fitTimer) return;
    fitTimer = setTimeout(function () { fitTimer = null; renderLayout(); }, 60);
  }

  McA.drawer = {
    init: function () {
      var $ = function (id) { return document.getElementById(id); };
      el = { drawer: $('drawer'), toggle: $('dr-toggle'), body: $('dr-body'), resize: $('dr-resize'), state: $('dr-state'), verdict: $('dr-verdict'),
        flags: $('dr-flags'), runtime: $('dr-runtime'), modeResults: $('dr-mode-results'), modeTools: $('dr-mode-tools'),
        results: $('dr-results'), tools: $('dr-tools'), main: $('ws-main'), page: $('page-workspace'), head: document.querySelector('#drawer .dr-head'),
        secs: document.querySelector('#dr-results .dr-secs'), pane: document.querySelector('#dr-results .dr-pane'),
        fit: $('dr-fit'), max: $('dr-max'), sizeBox: $('dr-size'), scroller: document.querySelector('.main') };
      mqWide = window.matchMedia('(min-width: 1250px)');
      mqFlow = window.matchMedia('(max-width: 799.98px)');

      el.toggle.addEventListener('click', function () { McA.dom.setUi({ drawerOpen: !ui().drawerOpen }); });
      document.getElementById('dr-toggle2').addEventListener('click', function () { McA.dom.setUi({ drawerOpen: !ui().drawerOpen }); });
      [el.modeResults, el.modeTools].forEach(function (b) {
        b.addEventListener('click', function () { McA.dom.setUi({ drawerMode: b === el.modeTools ? 'tools' : 'results', drawerOpen: true }); });
        b.addEventListener('keydown', function (e) {
          if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
          if (el.modeTools.hidden) return;
          e.preventDefault();
          var t = b === el.modeResults ? el.modeTools : el.modeResults; t.click(); t.focus();
        });
      });

      el.fit.addEventListener('click', function () { McA.dom.setUi({ drawerSize: sizeState() === 'fit' ? 'remembered' : 'fit', drawerOpen: true }); });
      el.max.addEventListener('click', function () { McA.dom.setUi({ drawerSize: DS.toggleMax(sizeState()), drawerOpen: true }); });
      el.resize.addEventListener('pointerdown', function (e) {
        e.preventDefault(); el.resize.setPointerCapture(e.pointerId); el.resize.classList.add('is-drag');
        el.resize._y = e.clientY; el.resize._h = curH; document.body.style.cursor = 'row-resize';
      });
      el.resize.addEventListener('pointermove', function (e) {
        if (!el.resize.hasPointerCapture(e.pointerId)) return;
        setHeight(el.resize._h + (el.resize._y - e.clientY));
      });
      var end = function (e) {
        if (el.resize.hasPointerCapture(e.pointerId)) el.resize.releasePointerCapture(e.pointerId);
        el.resize.classList.remove('is-drag'); document.body.style.cursor = '';
      };
      el.resize.addEventListener('pointerup', end); el.resize.addEventListener('pointercancel', end);
      el.resize.addEventListener('keydown', function (e) {
        var h = curH, step = e.shiftKey ? 64 : 16;
        if (e.key === 'ArrowUp') setHeight(h + step);
        else if (e.key === 'ArrowDown') setHeight(h - step);
        else if (e.key === 'Enter') McA.dom.setUi({ drawerSize: DS.toggleMax(sizeState()), drawerOpen: true });
        else if (e.key === 'Home') setHeight(MIN);
        else if (e.key === 'End') McA.dom.setUi({ drawerSize: 'max', drawerOpen: true });
        else return;
        e.preventDefault();
      });

      mqWide.addEventListener('change', placeInspector);
      window.addEventListener('resize', McA.util.debounce(renderLayout, 60));
      /* the tracker and header change height (wrapping caption, narrow chips): re-measure the maximum */
      if (window.ResizeObserver) {
        var ro = new ResizeObserver(McA.util.debounce(renderLayout, 30));
        [el.page, el.page.querySelector('.ws-head'), el.page.querySelector('.tracker')].forEach(function (n) { if (n) ro.observe(n); });
      }
      if (window.MutationObserver) new MutationObserver(scheduleFit).observe(el.body, { childList: true, subtree: true });
      McA.store.subscribe(function (s) { var u = s.ui || {}; return [u.drawerOpen, u.drawerHeight, u.drawerSize, JSON.stringify(u.drawerHeights || {}), u.drawerMode].join('|'); }, renderLayout);
      McA.store.subscribe(function (s) { return s.route; }, function () { setTimeout(renderLayout, 0); });
      McA.store.subscribe(function (s) { return s.run; }, function (run) {
        renderSummary();
        var prev = lastRunState; lastRunState = run && run.state;
        if ((prev === 'running' || prev === 'queued') && (lastRunState === 'failed' || lastRunState === 'succeeded_with_warnings') && !ui().drawerOpen) {
          McA.dom.setUi({ drawerOpen: true, drawerMode: 'results' });
        }
      });
      McA.store.subscribe(function (s) { return s.outputs && s.outputs.payload; }, renderSummary);
      lastRunState = (McA.store.get().run || {}).state;
      placeInspector(); renderSummary();
    },
    open: function (mode) { McA.dom.setUi({ drawerOpen: true, drawerMode: mode || 'results' }); },
    reset: function () { McA.dom.setUi({ drawerOpen: false, drawerHeight: DEF, drawerHeights: {}, drawerSize: 'remembered', drawerMode: 'results' }); },
  };
})();
