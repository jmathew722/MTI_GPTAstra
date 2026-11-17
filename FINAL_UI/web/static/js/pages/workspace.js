/* Workspace page: header (part name, real chips, part switcher), tracker icon sync, empty-state upload. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  McA.pages = McA.pages || {};
  var $ = function (id) { return document.getElementById(id); };

  function openPart(session, part, page) {
    McA.dom.dispatch('parts/select', { session: session, part: part });
    McA.router.go(page || 'workspace', page === 'results' ? { run: session + '|' + part } : { part: part, session: session });
  }
  McA.openPart = openPart;

  function chipText(chip, text, cls) {
    chip.classList.remove('is-ok', 'is-warn', 'is-err');
    if (cls) chip.classList.add(cls);
    chip.querySelector('.chip-v').textContent = text;
  }
  function renderChips() {
    var s = McA.store.get(), sv = s.server;
    var api = $('hdr-api');
    if (!sv.loaded) chipText(api, 'Checking…');
    else if (!sv.reachable) chipText(api, 'Server unreachable', 'is-err');
    else if (sv.live) chipText(api, 'API key set', 'is-ok');
    else chipText(api, 'No API key (demo only)', 'is-warn');

    var payload = s.outputs && s.outputs.payload, cats = (payload && payload.categories) || {};
    var model = sv.model || (cats.usage && cats.usage.last_run && cats.usage.last_run.model) || null;
    chipText($('hdr-engine'), model || 'Not reported');

    var has = { sldprt: !!(cats.sldprt && cats.sldprt.present), stl: !!(cats.stl && cats.stl.present), vba: !!(cats.macros && cats.macros.present) };
    document.querySelectorAll('#hdr-deliv .dv').forEach(function (d) {
      var k = d.getAttribute('data-k');
      d.classList.toggle('is-present', has[k]);
      d.title = has[k] ? (k === 'stl' && cats.stl.source ? 'Produced (' + cats.stl.source + ')' : 'Produced') : 'Not produced yet';
    });
  }
  function renderTitle() {
    var sel = McA.store.get().parts.selected;
    var h = $('ws-part');
    h.textContent = sel ? sel.part : 'No part selected';
    document.title = (sel ? sel.part + ' · ' : '') + 'Workspace · McAgent';
  }

  /* Part switcher: listbox with "This session" and "Other runs". */
  var listOpen = false;
  function options() {
    var s = McA.store.get(), sess = s.session.id, out = [];
    (s.parts.list || []).forEach(function (p) { out.push({ group: 'This session', session: sess, part: p.name, meta: (p.n_views || 0) + ' view' + (p.n_views === 1 ? '' : 's') + (p.has_output ? ', ran' : '') }); });
    var seen = {};
    (s.history.runs || []).forEach(function (r) {
      var k = r.session + '|' + r.part;
      if (r.session === sess || seen[k]) return;
      seen[k] = 1; out.push({ group: 'Other runs', session: r.session, part: r.part, meta: r.timestamp || '' });
    });
    return out;
  }
  function renderList() {
    var list = $('part-list'), h = McA.dom.h, sel = McA.store.get().parts.selected;
    list.replaceChildren();
    var opts = options(), group = null;
    if (!opts.length) list.append(h('li', { class: 'pl-empty', role: 'presentation', text: 'No parts yet. Upload a drawing to create one.' }));
    opts.forEach(function (o, i) {
      if (o.group !== group) { group = o.group; list.append(h('li', { class: 'pl-group', role: 'presentation', text: group })); }
      var on = sel && sel.part === o.part && sel.session === o.session;
      var li = h('li', { class: 'pl-opt', role: 'option', tabindex: '-1', 'aria-selected': String(!!on), 'data-i': i },
        h('span', { class: 'pl-n', text: o.part }), h('span', { class: 'hint', text: o.meta }));
      li.addEventListener('click', function () { choose(o); });
      list.append(li);
    });
  }
  function setList(open) {
    listOpen = open; $('part-list').hidden = !open; $('part-switch').setAttribute('aria-expanded', String(open));
    if (open) { renderList(); var o = $('part-list').querySelector('[aria-selected="true"]') || $('part-list').querySelector('.pl-opt'); if (o) o.focus(); }
  }
  function choose(o) { setList(false); $('part-switch').focus(); openPart(o.session, o.part); }

  function syncTrackerIcons() {
    var steps = document.querySelector('.trk-steps');
    var map = { succeeded: 'check', warning: 'warn', failed: 'x', skipped: 'dash' };
    var apply = function (li) {
      var node = li.querySelector('.trk-node'), ic = map[li.getAttribute('data-state')];
      node.replaceChildren(); if (ic) node.append(McA.icons.get(ic, 14));
    };
    steps.querySelectorAll('.trk-step').forEach(apply);
    new MutationObserver(function (ms) {
      ms.forEach(function (m) { if (m.target.classList && m.target.classList.contains('trk-step')) apply(m.target); });
    }).observe(steps, { attributes: true, attributeFilter: ['data-state'], subtree: true });
  }

  McA.pages.workspace = {
    init: function () {
      var sw = $('part-switch');
      sw.addEventListener('click', function () { setList(!listOpen); });
      $('part-list').addEventListener('keydown', function (e) {
        var opts = Array.prototype.slice.call(this.querySelectorAll('.pl-opt')), i = opts.indexOf(document.activeElement);
        if (e.key === 'ArrowDown') { e.preventDefault(); (opts[i + 1] || opts[0]).focus(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); (opts[i - 1] || opts[opts.length - 1]).focus(); }
        else if (e.key === 'Home') { e.preventDefault(); opts[0].focus(); }
        else if (e.key === 'End') { e.preventDefault(); opts[opts.length - 1].focus(); }
        else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (document.activeElement.classList.contains('pl-opt')) choose(options()[+document.activeElement.getAttribute('data-i')]); }
        else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setList(false); sw.focus(); }
        else if (e.key === 'Tab') setList(false);
      });
      document.addEventListener('click', function (e) { if (listOpen && !e.target.closest('#part-list, #part-switch')) setList(false); });

      var file = $('ws-file');
      file.addEventListener('change', function () {
        var list = Array.prototype.slice.call(file.files); file.value = '';
        if (!list.length) return;
        if (!McA.store.has('intake/files')) { McA.toast.show('Drawing intake is not available in this build.', 'err'); return; }
        McA.dom.dispatch('intake/files', { files: list, source: 'workspace' });
      });

      McA.store.subscribe(function (s) { return s.server; }, renderChips);
      McA.store.subscribe(function (s) { return s.outputs.payload; }, renderChips);
      McA.store.subscribe(function (s) { return s.parts.selected; }, function () { renderTitle(); if (listOpen) renderList(); });
      McA.store.subscribe(function (s) { return s.parts.list; }, function () { if (listOpen) renderList(); });
      syncTrackerIcons(); renderChips(); renderTitle();
    },
    enter: function (params) {
      var s = McA.store.get();
      if (params.part) {
        var sel = s.parts.selected, session = params.session || s.session.id;
        if (!sel || sel.part !== params.part || sel.session !== session) McA.dom.dispatch('parts/select', { session: session, part: params.part });
      }
      renderTitle();
    },
  };
})();
