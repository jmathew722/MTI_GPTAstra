/* Pipeline Results drawer: toggle, resize, Results/Tools modes, header summary, inspector relocation below 1440. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var DEF = 320, MIN = 160;
  var el = {}, mqWide, clock = null, lastRunState = null;

  var STATE = {
    idle: ['No run yet', null], queued: ['Queued', 'spinner'], running: ['Running', 'spinner'], succeeded: ['Completed', 'check'],
    succeeded_with_warnings: ['Completed with warnings', 'warn'], failed: ['Failed', 'x'], cancelled: ['Cancelled', 'dash'],
  };
  var VERDICT = {
    passed: ['Passed', 'is-ok', 'check'], passed_unbuilt: ['Checks passed, model not built', 'is-muted', 'info'],
    flags: ['Review flags', 'is-warn', 'warn'], failed: ['Failed', 'is-err', 'x'], unknown: ['Not available', 'is-muted', null],
  };
  function ui() { return McA.store.get().ui || {}; }
  function maxH() { return Math.max(MIN, Math.round(window.innerHeight * 0.7)); }
  function clampH(h) { return Math.min(maxH(), Math.max(MIN, Math.round(h))); }

  function renderLayout() {
    var u = ui(), wide = mqWide.matches;
    var open = !!u.drawerOpen, h = clampH(u.drawerHeight || DEF);
    var mode = !wide && u.drawerMode === 'tools' ? 'tools' : 'results';
    el.drawer.setAttribute('data-open', String(open));
    el.drawer.style.setProperty('--dr-h', h + 'px');
    el.toggle.setAttribute('aria-expanded', String(open));
    el.body.hidden = !open;
    el.resize.setAttribute('aria-valuenow', String(h)); el.resize.setAttribute('aria-valuemax', String(maxH()));
    el.modeTools.hidden = wide;
    [['results', el.modeResults, el.results], ['tools', el.modeTools, el.tools]].forEach(function (m) {
      var on = m[0] === mode; m[1].setAttribute('aria-selected', String(on)); m[1].tabIndex = on ? 0 : -1; m[2].hidden = !on;
    });
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

  function setHeight(h) { McA.dom.setUi({ drawerHeight: clampH(h), drawerOpen: true }); }

  McA.drawer = {
    init: function () {
      var $ = function (id) { return document.getElementById(id); };
      el = { drawer: $('drawer'), toggle: $('dr-toggle'), body: $('dr-body'), resize: $('dr-resize'), state: $('dr-state'), verdict: $('dr-verdict'),
        flags: $('dr-flags'), runtime: $('dr-runtime'), modeResults: $('dr-mode-results'), modeTools: $('dr-mode-tools'),
        results: $('dr-results'), tools: $('dr-tools'), main: $('ws-main') };
      mqWide = window.matchMedia('(min-width: 1250px)');

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

      el.resize.addEventListener('pointerdown', function (e) {
        e.preventDefault(); el.resize.setPointerCapture(e.pointerId); el.resize.classList.add('is-drag');
        el.resize._y = e.clientY; el.resize._h = clampH(ui().drawerHeight || DEF); document.body.style.cursor = 'row-resize';
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
        var h = clampH(ui().drawerHeight || DEF), step = e.shiftKey ? 64 : 16;
        if (e.key === 'ArrowUp') setHeight(h + step);
        else if (e.key === 'ArrowDown') setHeight(h - step);
        else if (e.key === 'Enter') setHeight(h >= maxH() - 1 ? DEF : maxH());
        else if (e.key === 'Home') setHeight(MIN);
        else if (e.key === 'End') setHeight(maxH());
        else return;
        e.preventDefault();
      });

      mqWide.addEventListener('change', placeInspector);
      window.addEventListener('resize', McA.util.debounce(renderLayout, 120));
      McA.store.subscribe(function (s) { var u = s.ui || {}; return [u.drawerOpen, u.drawerHeight, u.drawerMode].join('|'); }, renderLayout);
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
    reset: function () { McA.dom.setUi({ drawerOpen: false, drawerHeight: DEF, drawerMode: 'results' }); },
  };
})();
