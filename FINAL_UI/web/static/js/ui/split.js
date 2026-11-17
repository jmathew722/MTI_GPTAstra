/* Split canvas: splitter (pointer + keyboard), narrow tabs, maximize, fullscreen. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var canvas, splitter, tabs, mqNarrow;
  var MIN = 0.2, MAX = 0.8;
  var clamp = function (r) { return Math.min(MAX, Math.max(MIN, r)); };
  function ui() { return McA.store.get().ui || {}; }
  function setRatio(r) { McA.dom.setUi({ splitRatio: Math.round(clamp(r) * 1000) / 1000 }); }

  function renderRatio() {
    var r = clamp(ui().splitRatio || 0.5);
    canvas.style.setProperty('--sl', r + 'fr');
    canvas.style.setProperty('--sr', (1 - r) + 'fr');
    splitter.setAttribute('aria-valuenow', String(Math.round(r * 100)));
    splitter.setAttribute('aria-valuetext', Math.round(r * 100) + '% drawing, ' + Math.round((1 - r) * 100) + '% model');
  }
  function renderLayout() {
    var narrow = mqNarrow.matches;
    tabs.hidden = !narrow;
    var tab = ui().narrowTab === '3d' ? '3d' : '2d';
    canvas.setAttribute('data-tab', tab);
    [['2d', 'tab-2d'], ['3d', 'tab-3d']].forEach(function (p) {
      var b = document.getElementById(p[1]); var on = p[0] === tab;
      b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1;
    });
    var max = !narrow && ui().maximized ? ui().maximized : '';
    canvas.setAttribute('data-max', max);
    document.querySelectorAll('#canvas .vp-max').forEach(function (b) {
      var panel = b.closest('.vpanel').id === 'vp-2d' ? '2d' : '3d';
      var on = max === panel;
      b.setAttribute('aria-pressed', String(on));
      b.title = on ? 'Restore panel size' : 'Maximize panel';
      b.setAttribute('aria-label', (on ? 'Restore ' : 'Maximize ') + (panel === '2d' ? 'drawing' : 'model') + ' panel');
      b.replaceChildren(McA.icons.get(on ? 'restore' : 'maximize', 18));
    });
  }
  function renderFs() {
    var fs = document.fullscreenElement;
    document.querySelectorAll('#canvas .vp-fs').forEach(function (b) {
      var on = !!fs && fs === b.closest('.vpanel');
      b.setAttribute('aria-pressed', String(on));
      b.title = on ? 'Exit fullscreen' : 'Fullscreen';
    });
  }

  McA.split = {
    init: function () {
      canvas = document.getElementById('canvas'); splitter = document.getElementById('splitter');
      tabs = canvas.querySelector('.canvas-tabs'); mqNarrow = window.matchMedia('(max-width: 1099.98px)');

      splitter.addEventListener('pointerdown', function (e) {
        e.preventDefault(); splitter.setPointerCapture(e.pointerId); splitter.classList.add('is-drag');
        document.body.style.cursor = 'col-resize';
      });
      splitter.addEventListener('pointermove', function (e) {
        if (!splitter.hasPointerCapture(e.pointerId)) return;
        var rc = canvas.getBoundingClientRect();
        setRatio((e.clientX - rc.left - 4) / (rc.width - 8));
      });
      var end = function (e) {
        if (splitter.hasPointerCapture(e.pointerId)) splitter.releasePointerCapture(e.pointerId);
        splitter.classList.remove('is-drag'); document.body.style.cursor = '';
      };
      splitter.addEventListener('pointerup', end); splitter.addEventListener('pointercancel', end);
      splitter.addEventListener('dblclick', function () { setRatio(0.5); });
      splitter.addEventListener('keydown', function (e) {
        var r = ui().splitRatio || 0.5, step = e.shiftKey ? 0.1 : 0.02;
        if (e.key === 'ArrowLeft') setRatio(r - step);
        else if (e.key === 'ArrowRight') setRatio(r + step);
        else if (e.key === 'Home') setRatio(MIN);
        else if (e.key === 'End') setRatio(MAX);
        else if (e.key === 'Enter') setRatio(0.5);
        else return;
        e.preventDefault();
      });

      tabs.addEventListener('click', function (e) {
        var b = e.target.closest('[role="tab"]'); if (b) McA.dom.setUi({ narrowTab: b.id === 'tab-3d' ? '3d' : '2d' });
      });
      tabs.addEventListener('keydown', function (e) {
        if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].indexOf(e.key) < 0) return;
        e.preventDefault();
        var next = e.key === 'ArrowLeft' || e.key === 'Home' ? '2d' : '3d';
        McA.dom.setUi({ narrowTab: next });
        document.getElementById(next === '2d' ? 'tab-2d' : 'tab-3d').focus();
      });

      canvas.addEventListener('click', function (e) {
        var b = e.target.closest('.vp-max, .vp-fs'); if (!b) return;
        var panel = b.closest('.vpanel');
        if (b.classList.contains('vp-max')) {
          var id = panel.id === 'vp-2d' ? '2d' : '3d';
          McA.dom.setUi({ maximized: ui().maximized === id ? null : id });
          var nb = panel.querySelector('.vp-max'); if (nb) nb.focus();
        } else if (document.fullscreenElement === panel) {
          document.exitFullscreen();
        } else if (panel.requestFullscreen) {
          panel.requestFullscreen().catch(function () { McA.toast.show('Fullscreen was blocked by the browser.', 'warn'); });
        }
      });
      if (!document.fullscreenEnabled) document.querySelectorAll('#canvas .vp-fs').forEach(function (b) { b.hidden = true; });
      document.addEventListener('fullscreenchange', renderFs);
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && ui().maximized && !document.fullscreenElement && !McA.dialog.isOpen() && document.getElementById('focus').hidden) {
          McA.dom.setUi({ maximized: null });
        }
      });

      mqNarrow.addEventListener('change', renderLayout);
      McA.store.subscribe(function (s) { return s.ui && s.ui.splitRatio; }, renderRatio);
      McA.store.subscribe(function (s) { return (s.ui && s.ui.maximized || '') + '|' + (s.ui && s.ui.narrowTab); }, renderLayout);
      renderRatio(); renderLayout(); renderFs();
    },
    reset: function () { McA.dom.setUi({ splitRatio: 0.5, maximized: null }); },
  };
})();
