/* Home: one centered column. Dropzone, Create 3D Model, Upload parts / folder / Run demo, Recent.
   Dropzone -> the existing draft flow (Workspace to assign views and save).
   Upload parts (each file = one part) or Upload folder -> a staged list; the main button saves them as parts and opens Projects.
   Nothing here starts a pipeline run. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  McA.pages = McA.pages || {};
  var $ = function (id) { return document.getElementById(id); };
  var picked = [];      // the single drawing behind the current draft
  var staged = [];      // [{ id, kind: 'file'|'part', name, views, file | items }]
  var nextId = 1, creating = false;

  function hasDraft() { var s = McA.store.get(); return !!(s.intake && s.intake.items && s.intake.items.length); }
  function clearDraft() {
    if (McA.markup && McA.markup.clearIntake) McA.markup.clearIntake();
    McA.store.dispatch('intake/reset');
    picked = []; renderPicked();
  }

  function renderPicked() {
    var n = $('home-picked');
    if (!picked.length) { n.hidden = true; n.textContent = ''; return; }
    n.hidden = false; n.textContent = picked[0].name;
  }

  function renderStaged() {
    var ul = $('home-staged');
    ul.replaceChildren();
    ul.hidden = !staged.length;
    staged.forEach(function (it) {
      var rm = McA.dom.h('button', { class: 'ibtn', type: 'button', 'aria-label': 'Remove ' + it.name }, McA.icons.get('x', 14));
      rm.addEventListener('click', function () {
        staged = staged.filter(function (x) { return x.id !== it.id; });
        renderStaged(); renderCreate();
        $('home-parts-btn').focus();
      });
      ul.append(McA.dom.h('li', null,
        McA.dom.h('span', { class: 'st-n mono', text: it.name, title: it.name }),
        McA.dom.h('span', { class: 'st-v', text: it.views + (it.views === 1 ? ' view' : ' views') }),
        rm));
    });
  }

  function renderCreate() {
    var btn = $('home-create'), why = $('home-create-reason'), lbl = $('home-create-label');
    var n = staged.length;
    var ready = creating ? false : (n > 0 || hasDraft());
    lbl.textContent = creating ? 'Creating…' : (n > 1 ? 'Create ' + n + ' 3D models' : 'Create 3D Model');
    btn.setAttribute('aria-disabled', String(!ready));
    var reason = '';
    if (creating) reason = '';
    else if (!ready) reason = picked.length ? 'Reading the drawing…' : 'Add a drawing to continue.';
    why.textContent = reason; why.hidden = !reason;
  }

  function renderRecent() {
    var runs = (McA.store.get().history.runs || []).slice().sort(function (a, b) { return (b.epoch || 0) - (a.epoch || 0); }).slice(0, 5);
    var sec = document.querySelector('.home-recent'), ul = $('home-recent-list');
    ul.replaceChildren();
    sec.hidden = !runs.length;
    runs.forEach(function (r) {
      ul.append(McA.dom.h('li', null, McA.dom.h('a', { href: McA.router.href('workspace', { part: r.part, session: r.session }) },
        McA.icons.get('cube', 16), McA.dom.h('span', { class: 'rc-n', text: r.part }), McA.dom.h('span', { class: 't', text: r.timestamp || McA.dom.fmtTime(r.epoch) }))));
    });
  }

  /* Intake. */
  function oneDrawing(files) {
    if (!McA.store.has('intake/files')) { McA.toast.show('Drawing intake is not available in this build.', 'err'); return; }
    if (staged.length) { staged = []; renderStaged(); }
    picked = files.slice(0, 1); renderPicked(); if (files.length > 1) $('home-picked').textContent = files[0].name + ' + ' + (files.length - 1) + ' more'; renderCreate();
    McA.dom.dispatch('intake/files', { files: files, source: 'home' });
  }
  function stageFiles(files) {
    var G = McA.batchgroup;
    var go = hasDraft()
      ? McA.dialog.confirm('Discard the open draft?', 'The drawing you loaded is not saved. Selecting several parts replaces it.', 'Discard draft', true)
      : Promise.resolve(true);
    go.then(function (ok) {
      if (!ok) return;
      if (hasDraft()) clearDraft();
      files.forEach(function (f) {
        staged.push({ id: nextId++, kind: 'file', name: G.stemOf(f.name), views: 1, file: f });
      });
      renderStaged(); renderCreate();
    });
  }
  function stageFolder(files) {
    var G = McA.batchgroup;
    var entries = files.map(function (f) { return { name: f.name, path: f.webkitRelativePath || f.name }; });
    var groups = G.groupFolder(entries);
    if (!groups.length) { McA.toast.show('No view images found in that folder.', 'err'); return; }
    var go = hasDraft()
      ? McA.dialog.confirm('Discard the open draft?', 'The drawing you loaded is not saved. Selecting a folder replaces it.', 'Discard draft', true)
      : Promise.resolve(true);
    go.then(function (ok) {
      if (!ok) return;
      if (hasDraft()) clearDraft();
      groups.forEach(function (g) {
        staged.push({ id: nextId++, kind: 'part', name: g.name, views: g.views,
          items: g.items.map(function (i) { return { file: files[i.index], uploadPath: i.uploadPath }; }) });
      });
      renderStaged(); renderCreate();
    });
  }
  /* Dropzone: one drawing (several files = views of that one part). */
  function chooseDrawing(files) {
    var list = Array.prototype.slice.call(files || []);
    if (list.length) oneDrawing(list);
  }

  function commit() {
    if (creating) return;
    var fileItems = staged.filter(function (x) { return x.kind === 'file'; });
    var partItems = staged.filter(function (x) { return x.kind === 'part'; });
    creating = true; renderCreate();
    var added = [], failed = [];
    var p = Promise.resolve();
    if (partItems.length) p = p.then(function () {
      return McA.intake.uploadStagedParts(partItems).then(function (names) { added = added.concat(names); },
        function (e) { failed.push('folder parts: ' + ((e && (e.detail || e.message)) || 'upload failed')); });
    });
    if (fileItems.length) p = p.then(function () {
      return McA.intake.createParts(fileItems.map(function (x) { return x.file; })).then(function (r) {
        added = added.concat(r.added); r.failed.forEach(function (f) { failed.push(f.name + ' (' + f.why + ')'); });
      });
    });
    p.then(function () {
      creating = false; staged = []; renderStaged(); renderCreate();
      if (added.length) McA.toast.show('Added ' + added.length + ' part' + (added.length === 1 ? '' : 's') + '. Open one and press Run Pipeline.', 'ok');
      if (failed.length) McA.toast.show('Not added: ' + failed.join('; '), 'err');
      if (added.length) McA.router.go('projects');
    });
  }

  function demoDialog() {
    var h = McA.dom.h, samples = McA.store.get().server.samples || [];
    var sel = h('select', { class: 'input-c', id: 'demo-pick', 'aria-label': 'Sample' }, samples.map(function (n) { return h('option', { value: n, text: n }); }));
    var body = h('div', null,
      h('p', null, 'Replays a saved extraction. No API call. ', h('span', { class: 'badge-c', text: 'Demo' })),
      samples.length ? sel : h('p', { class: 'reason', text: 'No sample extractions found in the repo.' }));
    McA.dialog.open({ title: 'Run demo', body: body, initial: '#demo-pick', actions: [{ id: 'cancel', label: 'Cancel' }, { id: 'run', label: 'Run demo', kind: 'primary', disabled: !samples.length }] })
      .then(function (r) {
        if (r !== 'run') return;
        if (!McA.store.has('run/demo')) { McA.toast.show('The demo runner is not available in this build.', 'err'); return; }
        McA.dom.dispatch('run/demo', { sample: sel.value });
        McA.router.go('workspace');
      });
  }

  McA.pages.home = {
    init: function () {
      var input = $('home-file'), drop = $('home-drop');
      input.addEventListener('change', function () { var a = Array.prototype.slice.call(input.files); input.value = ''; chooseDrawing(a); });
      ['dragenter', 'dragover'].forEach(function (t) { drop.addEventListener(t, function (e) { e.preventDefault(); drop.classList.add('is-over'); }); });
      ['dragleave', 'drop'].forEach(function (t) { drop.addEventListener(t, function () { drop.classList.remove('is-over'); }); });
      drop.addEventListener('drop', function (e) { e.preventDefault(); chooseDrawing(e.dataTransfer && e.dataTransfer.files); });
      var parts = $('home-parts'), folder = $('home-folder');
      $('home-parts-btn').addEventListener('click', function () { parts.click(); });
      $('home-folder-btn').addEventListener('click', function () { folder.click(); });
      parts.addEventListener('change', function () { var a = Array.prototype.slice.call(parts.files); parts.value = ''; if (a.length) stageFiles(a); });
      folder.addEventListener('change', function () { var a = Array.prototype.slice.call(folder.files); folder.value = ''; if (a.length) stageFolder(a); });
      $('home-demo').addEventListener('click', demoDialog);
      $('home-create').addEventListener('click', function (e) {
        if (e.currentTarget.getAttribute('aria-disabled') === 'true') return;
        if (staged.length) { commit(); return; }
        McA.dom.dispatch('ui/inspectorSection', { id: 'setup', open: true });
        McA.router.go('workspace');
      });
      McA.store.subscribe(function (s) { return s.intake.items; }, function (items, prev) {
        if (!items.length && prev && prev.length) { picked = []; renderPicked(); }
        renderCreate();
      });
      McA.store.subscribe(function (s) { return s.history.runs; }, renderRecent);
      renderStaged(); renderCreate(); renderRecent();
    },
    enter: function () { renderRecent(); },
  };
})();
