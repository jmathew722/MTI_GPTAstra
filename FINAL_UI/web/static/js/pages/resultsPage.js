/* Pipeline Results page: run selector, breadcrumb, five groups (ARCH 8.7). Content is ui/results.js. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  McA.pages = McA.pages || {};
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var mount = null, sel, crumbPart, crumbSec, demoBadge, built = false;

  function visible() { var p = document.getElementById('page-results'); return !!p && !p.hidden; }
  function section() { return McA.store.get().ui.resultsSection || 'overview'; }

  function options() {
    var s = McA.store.get(), out = [], seen = {};
    var run = s.run;
    if (run.kind === 'demo' && run.id) out.push({ value: 'demo:' + run.id, text: 'Demo run (not saved) · ' + (run.startedAt ? McA.dom.fmtTime(run.startedAt) : '') });
    (s.history.runs || []).slice().sort(function (a, b) { return (b.epoch || 0) - (a.epoch || 0); }).forEach(function (r) {
      var k = r.key || (r.session + '|' + r.part); seen[k] = 1;
      out.push({ value: k, text: (r.label || r.part) + (r.session === s.session.id ? '' : ' · other session') });
    });
    var sl = s.parts.selected;
    if (sl && !seen[sl.session + '|' + sl.part] && !(s.outputs.ctx && s.outputs.ctx.kind === 'run'))
      out.unshift({ value: sl.session + '|' + sl.part, text: sl.part + ' · no completed run saved yet' });
    return out;
  }
  function currentValue() {
    var c = McA.store.get().outputs.ctx;
    if (!c) return '';
    return c.kind === 'run' ? 'demo:' + c.runId : c.session + '|' + c.part;
  }
  function renderHead() {
    var s = McA.store.get(), opts = options(), cur = currentValue();
    sel.replaceChildren();
    if (!opts.length) sel.append(h('option', { value: '', text: 'No runs yet' }));
    else if (!cur) sel.append(h('option', { value: '', text: 'Choose a run…' }));
    opts.forEach(function (o) { sel.append(h('option', { value: o.value, text: o.text })); });
    sel.value = cur;
    sel.disabled = !opts.length;
    var c = s.outputs.ctx;
    crumbPart.textContent = c ? (c.kind === 'run' ? 'Demo run' : c.part) : 'No run selected';
    var sec = McA.registry.get(section());
    crumbSec.textContent = sec ? sec.label : '';
    demoBadge.hidden = !(c && c.kind === 'run');
  }
  function choose(v) {
    if (!v) return;
    if (v.indexOf('demo:') === 0) { McA.store.dispatch('outputs/ctx', { ctx: { kind: 'run', runId: v.slice(5) } }); return; }
    var i = v.indexOf('|');
    McA.store.dispatch('parts/select', { session: v.slice(0, i), part: v.slice(i + 1) });
  }
  function build() {
    if (built) return; built = true;
    var root = document.getElementById('res-root');
    sel = h('select', { id: 'res-run', class: 'input-c res-run' });
    sel.addEventListener('change', function () { choose(sel.value); });
    crumbPart = h('span', { id: 'res-part' }); crumbSec = h('span', { id: 'res-sec' });
    demoBadge = h('span', { class: 'badge-c', id: 'res-demo', text: 'Demo' }); demoBadge.hidden = true;
    var nav = h('nav', { class: 'res-nav', 'aria-label': 'Result sections' });
    var pane = h('article', { class: 'res-pane', id: 'res-pane', tabindex: '-1', 'aria-label': 'Selected result section' });
    root.append(
      h('header', { class: 'res-head' },
        h('nav', { class: 'crumb', 'aria-label': 'Breadcrumb' }, h('a', { href: '#/projects', text: 'Projects' }), ' / ', crumbPart, ' / ', crumbSec),
        h('div', { class: 'res-pick' }, h('label', { for: 'res-run', text: 'Run' }), sel, demoBadge)),
      h('div', { class: 'res-body' }, nav, pane));
    mount = McA.results.mount({ mode: 'page', nav: nav, pane: pane, isVisible: visible, getSection: section,
      setSection: function (id) { McA.dom.setUi({ resultsSection: id }); renderHead(); pane.focus({ preventScroll: true }); } });
  }

  McA.pages.results = {
    init: function () {
      build();
      ['history', 'parts', 'run', 'outputs'].forEach(function (k) { McA.store.subscribe(function (s) { return s[k]; }, function () { if (visible()) renderHead(); }); });
      McA.store.subscribe(function (s) { return s.ui.resultsSection; }, function () { if (visible()) { renderHead(); mount.render(); } });
    },
    enter: function (params) {
      build();
      if (params && params.sec && McA.registry.get(params.sec)) McA.dom.setUi({ resultsSection: params.sec });
      if (params && params.run) choose(params.run.indexOf(':') === 0 ? '' : params.run);
      renderHead(); mount.render();
    },
    leave: function () { /* state stays in the store */ }
  };
})();
