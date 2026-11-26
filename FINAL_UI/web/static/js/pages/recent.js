/* Recent Files: run history newest first, real data only. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  McA.pages = McA.pages || {};
  var h = function () { return McA.dom.h.apply(null, arguments); };

  function render() {
    var s = McA.store.get(), body = document.getElementById('recent-body');
    body.replaceChildren();
    if (s.history.error) { body.append(h('div', { class: 'banner is-err', role: 'alert' }, McA.icons.get('warn', 18), 'Could not load run history: ' + s.history.error)); return; }
    var runs = (s.history.runs || []).slice().sort(function (a, b) { return (b.epoch || 0) - (a.epoch || 0); });
    if (!s.history.loaded) { body.append(h('p', { class: 'reason', text: 'Loading…' })); return; }
    if (!runs.length) {
      body.append(h('div', { class: 'empty' }, h('span', { class: 'empty-ic' }, McA.icons.get('recent', 30)), h('p', { class: 'empty-t', text: 'No recent files' }),
        h('p', { class: 'empty-d', text: 'Parts that have been run appear here, newest first.' }), h('a', { class: 'btn secondary sm', href: '#/home', text: 'Create a model' })));
      return;
    }
    var rows = runs.map(function (r) {
      var pres = r.present || {};
      return h('tr', null,
        h('td', null, h('strong', { text: r.part })),
        h('td', { class: 'num', text: r.timestamp || McA.dom.fmtTime(r.epoch) }),
        h('td', null, McA.materials ? McA.materials.materialCell(r.session + '|' + r.part) : null),
        h('td', null, McA.materials ? McA.materials.costCell(r.session + '|' + r.part) : null),
        h('td', null, h('div', { class: 'acts' },
          h('button', { class: 'btn act act-open', type: 'button', text: 'Open in Workspace', onclick: function () { McA.openPart(r.session, r.part); } }),
          h('button', { class: 'btn act act-gold', type: 'button', text: 'Open results', onclick: function () { McA.openPart(r.session, r.part, 'results'); } }),
          pres.stl ? h('a', { class: 'btn ghost sm', href: McA.api.partStlURL(r.session, r.part), download: r.part + '.stl' }, McA.icons.get('download', 14), 'Download STL') : null)));
    });
    var mline = McA.materials ? McA.materials.batchLine(runs.map(function (r) { return r.session + '|' + r.part; })) : '';
    if (mline) body.append(h('p', { class: 'mat-batch-line', role: 'status', text: mline }));
    body.append(h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' }, h('caption', { class: 'sr-only', text: 'Recent runs, newest first' }),
      h('thead', null, h('tr', null, ['Part', 'Run time', 'Material', 'Material cost (estimate)', 'Actions'].map(function (t) { return h('th', { scope: 'col', text: t }); }))), h('tbody', null, rows))));
  }
  McA.pages.recent = { init: function () { McA.store.subscribe(function (s) { return s.history; }, render); if (McA.materials) McA.materials.onChange(function () { var pg = document.getElementById('page-recent'); if (pg && !pg.hidden) render(); }); render(); }, enter: render };
})();
