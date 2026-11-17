/* Home: heading, real file input dropzone, Create 3D Model, small links, recent runs. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  McA.pages = McA.pages || {};
  var picked = [];

  function sendFiles(files, action) {
    var list = Array.prototype.slice.call(files || []);
    if (!list.length) return;
    if (!McA.store.has(action)) { McA.toast.show('Drawing intake is not available in this build.', 'err'); return; }
    McA.dom.dispatch(action, { files: list, source: 'home' });
    if (action === 'intake/files') {
      picked = list;
      renderPicked();
    }
  }
  function renderPicked() {
    var n = document.getElementById('home-picked');
    if (!picked.length) { n.hidden = true; n.textContent = ''; return; }
    n.hidden = false;
    n.textContent = picked[0].name + (picked.length > 1 ? ' + ' + (picked.length - 1) + ' more' : '');
  }
  function renderCreate() {
    var s = McA.store.get();
    var ready = !!(s.intake && s.intake.items && s.intake.items.length > 0);
    var btn = document.getElementById('home-create'), why = document.getElementById('home-create-reason');
    btn.setAttribute('aria-disabled', String(!ready));
    why.textContent = ready ? 'Opens the workspace to name, save and run. Nothing is run automatically.' : (picked.length ? 'Reading the drawing…' : 'Add a drawing first.');
  }
  function renderRecent() {
    var runs = (McA.store.get().history.runs || []).slice().sort(function (a, b) { return (b.epoch || 0) - (a.epoch || 0); }).slice(0, 5);
    var ul = document.getElementById('home-recent-list');
    ul.replaceChildren();
    if (!runs.length) { ul.append(McA.dom.h('li', { class: 'reason', text: 'No runs yet. Runs appear here after the pipeline has produced output.' })); return; }
    runs.forEach(function (r) {
      ul.append(McA.dom.h('li', null, McA.dom.h('a', { href: McA.router.href('workspace', { part: r.part, session: r.session }) },
        McA.icons.get('cube', 16), McA.dom.h('span', { text: r.part }), McA.dom.h('span', { class: 't', text: r.timestamp || McA.dom.fmtTime(r.epoch) }))));
    });
  }
  function demoDialog() {
    var h = McA.dom.h, samples = McA.store.get().server.samples || [];
    var sel = h('select', { class: 'input-c', id: 'demo-pick', 'aria-label': 'Sample' }, samples.map(function (n) { return h('option', { value: n, text: n }); }));
    var body = h('div', null,
      h('p', null, 'Uses a saved extraction. No API call is made and no model is generated. ', h('span', { class: 'badge-c', text: 'Demo' })),
      samples.length ? sel : h('p', { class: 'reason', text: 'The server reports no sample extractions.' }));
    McA.dialog.open({ title: 'Open sample / Run demo', body: body, initial: '#demo-pick', actions: [{ id: 'cancel', label: 'Cancel' }, { id: 'run', label: 'Run demo', kind: 'primary', disabled: !samples.length }] })
      .then(function (r) {
        if (r !== 'run') return;
        if (!McA.store.has('run/demo')) { McA.toast.show('The demo runner is not available in this build.', 'err'); return; }
        McA.dom.dispatch('run/demo', { sample: sel.value });
        McA.router.go('workspace');
      });
  }

  McA.pages.home = {
    init: function () {
      var input = document.getElementById('home-file'), drop = document.getElementById('home-drop');
      input.addEventListener('change', function () { sendFiles(input.files, 'intake/files'); input.value = ''; });
      ['dragenter', 'dragover'].forEach(function (t) { drop.addEventListener(t, function (e) { e.preventDefault(); drop.classList.add('is-over'); }); });
      ['dragleave', 'drop'].forEach(function (t) { drop.addEventListener(t, function () { drop.classList.remove('is-over'); }); });
      drop.addEventListener('drop', function (e) { e.preventDefault(); sendFiles(e.dataTransfer && e.dataTransfer.files, 'intake/files'); });
      var folder = document.getElementById('home-folder');
      folder.addEventListener('change', function () { sendFiles(folder.files, 'intake/folder'); folder.value = ''; });
      var lbl = document.getElementById('home-folder-lbl');
      lbl.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); folder.click(); } });
      document.getElementById('home-demo').addEventListener('click', demoDialog);
      document.getElementById('home-create').addEventListener('click', function (e) {
        if (e.currentTarget.getAttribute('aria-disabled') === 'true') return;
        McA.dom.dispatch('ui/inspectorSection', { id: 'setup', open: true });
        McA.router.go('workspace');
      });
      McA.store.subscribe(function (s) { return s.intake.items; }, function (items, prev) {
        if (!items.length && prev && prev.length) { picked = []; renderPicked(); }
        renderCreate();
      });
      McA.store.subscribe(function (s) { return s.history.runs; }, renderRecent);
      renderCreate(); renderRecent();
    },
    enter: function () { renderRecent(); },
  };
})();
