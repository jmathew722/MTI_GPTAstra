/* Settings: server status, session, layout reset, data danger zone. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  McA.pages = McA.pages || {};
  var h = function () { return McA.dom.h.apply(null, arguments); };
  function row(k, v, cls) { return h('div', { class: 'kvrow' }, h('span', { class: 'k', text: k }), h('span', { class: 'v' + (cls ? ' ' + cls : ''), text: v })); }

  function render() {
    var s = McA.store.get(), sv = s.server, root = document.getElementById('settings-body');
    var api = !sv.loaded ? 'Checking…' : !sv.reachable ? 'Server unreachable' : sv.live ? 'API key set on the server' : 'No API key on the server (demo only)';
    var copy = h('button', { class: 'btn secondary sm', type: 'button', onclick: function () {
      if (!s.session.id) return;
      McA.util.copyText(s.session.id).then(function (ok) { McA.toast.show(ok ? 'Session id copied.' : 'Could not copy.', ok ? 'ok' : 'err'); });
    } }, McA.icons.get('copy', 14), 'Copy');
    if (!s.session.id) { copy.disabled = true; copy.title = 'No session yet'; }
    root.replaceChildren(
      h('section', { 'aria-labelledby': 's-srv' }, h('h2', { id: 's-srv', text: 'Server' }),
        row('Connection', !sv.loaded ? 'Checking…' : sv.reachable ? 'Reachable' : 'Unreachable', sv.reachable ? '' : 'is-err'),
        row('API key', api), row('Engine', sv.model || 'Not reported'), row('Sample extractions', String((sv.samples || []).length)),
        h('p', { class: 'hint', text: 'The key lives on the server. This page never stores or shows secrets.' })),
      h('section', { 'aria-labelledby': 's-ses' }, h('h2', { id: 's-ses', text: 'Session' }),
        h('div', { class: 'kvrow' }, h('span', { class: 'k', text: 'Session id' }), h('span', { class: 'v mono', text: s.session.id || 'None' }), copy),
        h('p', { class: 'hint', text: 'Saved parts belong to this session. The id is kept in this browser so a refresh keeps your parts.' })),
      h('section', { 'aria-labelledby': 's-lay' }, h('h2', { id: 's-lay', text: 'Layout' }),
        h('p', { text: 'Sidebar, panel split, tools panel and results drawer sizes are remembered in this browser.' }),
        h('div', null, h('button', { class: 'btn secondary', type: 'button', onclick: function () {
          McA.persist.resetUi();
          ['sidebar', 'split', 'inspector', 'drawer'].forEach(function (k) { if (McA[k] && McA[k].reset) McA[k].reset(); });
          McA.toast.show('Layout reset to defaults.', 'ok');
        } }, McA.icons.get('reset', 16), 'Reset layout'))),
      h('section', { class: 'danger-zone', 'aria-labelledby': 's-dat' }, h('h2', { id: 's-dat', text: 'Data' }),
        h('p', { text: 'Clear all models deletes the saved output of every run on this machine. Saved drawings and parts are kept.' }),
        h('div', null, h('button', { class: 'btn danger', type: 'button', onclick: function () { McA.clearAllModels(); } }, McA.icons.get('trash', 16), 'Clear all models'))));
  }
  McA.pages.settings = {
    init: function () {
      ['server', 'session'].forEach(function (k) { McA.store.subscribe(function (s) { return s[k]; }, render); });
      render();
    },
    enter: render,
  };
})();
