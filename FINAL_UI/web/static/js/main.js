/* Boot: icons, UI modules, router, then real data (status, session, parts, history). */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var $ = function () { return McA.store; };
  var OWNED = ['tracker', 'costKey', 'results', 'resultsPage', 'run', 'intake', 'markup', 'cropper', 'viewer2d', 'viewer3d'];

  function refreshStatus() {
    return McA.api.status().then(function (r) { McA.store.dispatch('server/status', r || {}); },
      function () { McA.store.dispatch('server/unreachable'); });
  }
  function refreshHistory() {
    return McA.api.runHistory().then(function (r) { McA.store.dispatch('history/loaded', { runs: (r && r.runs) || [] }); },
      function (e) { McA.store.dispatch('history/error', { error: (e && e.detail) || (e && e.message) || 'error' }); });
  }
  function refreshParts() {
    var sid = McA.store.get().session.id;
    if (!sid) return Promise.resolve();
    McA.store.dispatch('parts/loading');
    return McA.api.listParts(sid).then(function (r) { McA.store.dispatch('parts/loaded', { list: (r && r.parts) || [] }); },
      function (e) { McA.store.dispatch('parts/error', { error: (e && e.detail) || (e && e.message) || 'error' }); });
  }
  function ensureSession() {
    var sid = McA.persist.get(McA.persist.KEYS.session, null);
    if (sid) { McA.store.dispatch('session/set', { id: sid }); return Promise.resolve(); }
    return McA.api.newSession().then(function (r) {
      McA.persist.set(McA.persist.KEYS.session, r.session); McA.store.dispatch('session/set', { id: r.session });
    }, function () { /* server unreachable: status chip reports it */ });
  }
  function restoreSelection() {
    var sel = McA.persist.get(McA.persist.KEYS.selected, null);
    var s = McA.store.get();
    if (sel && !s.parts.selected) McA.store.dispatch('parts/select', sel);
  }

  function boot() {
    if (!McA.store || !McA.api || !McA.persist || !McA.util) { console.error('Solid Flow: core modules failed to load.'); }
    McA.icons.hydrate(document);
    ['sidebar', 'split', 'inspector', 'drawer'].forEach(function (k) { McA[k].init(); });
    Object.keys(McA.pages).forEach(function (k) { if (McA.pages[k].init) McA.pages[k].init(); });
    OWNED.forEach(function (k) { if (McA[k] && typeof McA[k].init === 'function') McA[k].init(); });

    McA.store.subscribe(function (s) { return s.parts.selected; }, function (sel) {
      if (sel) McA.persist.set(McA.persist.KEYS.selected, sel); else McA.persist.remove(McA.persist.KEYS.selected);
    });
    restoreSelection();
    // The skip link must not touch the hash router (an unknown hash would send the user Home).
    var skip = document.querySelector('.skip-link');
    if (skip) skip.addEventListener('click', function (e) { e.preventDefault(); document.getElementById('main').focus(); });
    McA.router.start();

    refreshStatus();
    refreshHistory();
    ensureSession().then(refreshParts);
    setInterval(function () { if (!document.hidden) refreshStatus(); }, 30000);
    window.addEventListener('focus', refreshStatus);
    McA.boot = { refreshStatus: refreshStatus, refreshHistory: refreshHistory, refreshParts: refreshParts };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
