/* McA.router: hash router. parse(hash) -> {page, params}; go(page, params); start(). */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var PAGES = ['home', 'workspace', 'reverse', 'projects', 'results', 'scoring', 'recent', 'help', 'settings'];
  var TITLES = { home: 'Home', workspace: 'Workspace', reverse: '3D → 2D', projects: 'Projects', results: 'Pipeline Results', scoring: 'Scoring', recent: 'Recent Files', help: 'Help', settings: 'Settings' };
  var first = true;
  var current = null;

  function parse(hash) {
    var h = String(hash || '').replace(/^#\/?/, '');
    var qi = h.indexOf('?');
    var name = (qi < 0 ? h : h.slice(0, qi)).replace(/\/+$/, '');
    var params = {};
    if (qi >= 0) {
      try { new URLSearchParams(h.slice(qi + 1)).forEach(function (v, k) { params[k] = v; }); } catch (e) { /* ignore */ }
    }
    return { page: name, params: params, valid: PAGES.indexOf(name) >= 0 };
  }
  function href(page, params) {
    var q = params && Object.keys(params).length ? '?' + new URLSearchParams(params).toString() : '';
    return '#/' + page + q;
  }
  function go(page, params) {
    var target = href(page, params);
    if (location.hash === target) render(); else location.hash = target;
  }
  function render() {
    var r = parse(location.hash);
    if (!r.valid) { location.replace(href('home')); return; }
    var prev = current;
    if (prev && prev !== r.page && McA.pages && McA.pages[prev] && McA.pages[prev].leave) McA.pages[prev].leave();
    current = r.page;
    document.querySelectorAll('.page').forEach(function (p) { p.hidden = p.getAttribute('data-page') !== r.page; });
    document.querySelectorAll('.sb-item').forEach(function (a) {
      if (a.getAttribute('data-page') === r.page) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    document.title = TITLES[r.page] + ' · Solid Flow';
    if (McA.store) McA.store.dispatch('route/set', { page: r.page, params: r.params });
    if (McA.pages && McA.pages[r.page] && McA.pages[r.page].enter) McA.pages[r.page].enter(r.params);
    var main = document.getElementById('main');
    if (prev !== r.page) main.scrollTop = 0;
    if (!first) {
      var h1 = document.querySelector('#page-' + r.page + ' h1');
      if (h1) { h1.setAttribute('tabindex', '-1'); h1.focus({ preventScroll: true }); }
    }
    first = false;
  }
  McA.router = {
    PAGES: PAGES, TITLES: TITLES, parse: parse, href: href, go: go, current: function () { return current; },
    start: function () { window.addEventListener('hashchange', render); render(); },
  };
})();
