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
  var skippedNote = '', stagedEst = null, estSeq = 0;
  var IMG_OK = /^(jpe?g|png|webp|bmp|tiff?)$/i;

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
      var meta = it.kind === 'part' ? it.views + (it.views === 1 ? ' view' : ' views')
        : it.status === 'checking' ? 'Checking\u2026'
        : it.problem ? 'Cannot use'
        : (it.type ? it.type.toUpperCase() : 'FILE') + (it.pages ? ' \u00b7 ' + it.pages + (it.pages === 1 ? ' page' : ' pages') : '');
      ul.append(McA.dom.h('li', { class: it.problem ? 'is-bad' : '', 'data-status': it.status || 'ok' },
        McA.dom.h('span', { class: 'st-n mono', text: it.label && it.label !== it.name ? it.name + '  (' + it.label + ')' : it.name, title: it.label || it.name }),
        it.problem ? McA.dom.h('span', { class: 'st-p', role: 'alert', text: it.problem }) : null,
        McA.dom.h('span', { class: 'st-v', text: meta }),
        rm));
    });
    renderSummary();
  }
  function usable() { return staged.filter(function (x) { return !x.problem && x.status !== 'checking'; }); }
  /* Preflight summary: counts, skipped files with reasons, page total, estimated time and cost for the batch. */
  function renderSummary() {
    var box = $('home-staged-sum'), V = McA.estimateview;
    if (!box) return;
    var n = staged.length;
    box.hidden = !(n || skippedNote);
    box.replaceChildren();
    if (!box.hidden) {
      var ok = usable(), bad = staged.filter(function (x) { return x.problem; }), chk = staged.filter(function (x) { return x.status === 'checking'; });
      var pages = ok.reduce(function (a, x) { return a + (x.pages || 0); }, 0);
      var line = ok.length + ' supported input' + (ok.length === 1 ? '' : 's') + (pages ? ' \u00b7 ' + pages + ' page' + (pages === 1 ? '' : 's') + ' in total' : '')
        + (bad.length ? ' \u00b7 ' + bad.length + ' cannot be used' : '') + (chk.length ? ' \u00b7 checking ' + chk.length + '\u2026' : '');
      box.append(McA.dom.h('p', { class: 'st-sum', text: n ? line : 'No supported files' }));
      if (stagedEst && V && ok.length) {
        var d = V.describe(stagedEst);
        box.append(McA.dom.h('p', { class: 'st-est', text: d.time + ' \u00b7 ' + d.cost + ' (for all ' + ok.length + ' when run one after another)' }));
      }
      if (skippedNote) box.append(McA.dom.h('p', { class: 'reason', text: skippedNote }));
    }
  }
  function refreshEstimate() {
    var sid = McA.store.get().session.id, names = usable().map(function (x) { return x.name; });
    var my = ++estSeq;
    if (!sid || !names.length) { stagedEst = null; renderSummary(); return; }
    McA.api.estimate(sid, names).then(function (e) { if (my === estSeq) { stagedEst = e; renderSummary(); } }, function () { if (my === estSeq) { stagedEst = null; renderSummary(); } });
  }
  /* Real-content check of one staged file: the first bytes must match its extension, and a PDF must open (and says how many pages). */
  function checkItem(it) {
    if (it.kind !== 'file' || !it.file) return Promise.resolve();
    var F = McA.folderplan, ext = F.extOf(it.file.name);
    if (!(ext === 'pdf' || IMG_OK.test(ext))) { it.status = 'ok'; return Promise.resolve(); }          // CAD files are converted later by the existing intake
    it.status = 'checking';
    return it.file.slice(0, 16).arrayBuffer().then(function (buf) {
      var why = F.mismatch({ type: ext === 'pdf' ? 'pdf' : 'image', ext: ext }, Array.prototype.slice.call(new Uint8Array(buf)));
      if (why) { it.problem = 'Cannot use: ' + why + '.'; it.status = 'bad'; return; }
      if (ext !== 'pdf') { it.pages = 1; it.status = 'ok'; return; }
      return McA.api.preflightPdf(it.file).then(function (r) {
        if (r && r.ok) { it.pages = r.pages; it.status = 'ok'; } else { it.problem = (r && r.error) || 'The PDF could not be read.'; it.status = 'bad'; }
      }, function () {
        if (typeof pdfjsLib === 'undefined') { it.status = 'ok'; return; }                               // server check unavailable: the pipeline will report any real problem
        var u = URL.createObjectURL(it.file);
        return pdfjsLib.getDocument(u).promise.then(function (pdf) { it.pages = pdf.numPages; it.status = 'ok'; }, function () { it.problem = 'The PDF could not be read (it may be corrupt or password protected).'; it.status = 'bad'; })
          .then(function () { URL.revokeObjectURL(u); });
      });
    }, function () { it.problem = 'The file could not be read.'; it.status = 'bad'; }).then(function () { renderStaged(); renderCreate(); refreshEstimate(); });
  }

  function renderCreate() {
    var btn = $('home-create'), why = $('home-create-reason'), lbl = $('home-create-label');
    var n = usable().length, waiting = staged.some(function (x) { return x.status === 'checking'; });
    var ready = creating || waiting ? false : (n > 0 || (!staged.length && hasDraft()));
    lbl.textContent = creating ? 'Creating…' : (n > 1 ? 'Create ' + n + ' 3D models' : 'Create 3D Model');
    btn.setAttribute('aria-disabled', String(!ready));
    var reason = '';
    if (creating) reason = '';
    else if (waiting) reason = 'Checking the selected files.';
    else if (staged.length && !n) reason = 'None of the selected files can be used. Remove them or choose others.';
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
      var F = McA.folderplan, taken = staged.map(function (x) { return x.name; });
      var fresh = files.map(function (f) {
        var ext = F.extOf(f.name), name = F.uniqueName(F.stemOf(f.name), taken); taken.push(name);
        var it = { id: nextId++, kind: 'file', name: name, label: f.name, views: 1, file: f, type: ext === 'pdf' ? 'pdf' : IMG_OK.test(ext) ? 'image' : ext };
        staged.push(it); return it;
      });
      skippedNote = '';
      renderStaged(); renderCreate();
      Promise.all(fresh.map(checkItem)).then(function () { renderStaged(); renderCreate(); refreshEstimate(); });
    });
  }
  function stageFolder(files) {
    var F = McA.folderplan;
    var entries = files.map(function (f) { return { name: f.name, path: f.webkitRelativePath || f.name, size: f.size, lastModified: f.lastModified }; });
    var plan = F.plan(entries);
    skippedNote = F.skippedSummary(plan.skipped);
    if (!plan.total) {
      renderSummary();
      McA.toast.show('No supported files in that folder. Add PDF, JPG, JPEG or PNG drawings.' + (skippedNote ? ' ' + skippedNote : ''), 'err', { ms: 9000 });
      return;
    }
    var groups = plan.parts;
    var go = hasDraft()
      ? McA.dialog.confirm('Discard the open draft?', 'The drawing you loaded is not saved. Selecting a folder replaces it.', 'Discard draft', true)
      : Promise.resolve(true);
    go.then(function (ok) {
      if (!ok) return;
      if (hasDraft()) clearDraft();
      var taken = staged.map(function (x) { return x.name; }), fresh = [];
      plan.jobs.forEach(function (j) {
        var name = F.uniqueName(j.name, taken); taken.push(name);
        var it = { id: nextId++, kind: 'file', name: name, label: j.label, views: 1, file: files[j.index], type: j.type };
        staged.push(it); fresh.push(it);
      });
      groups.forEach(function (g) {
        var name = F.uniqueName(g.name, taken); taken.push(name);
        staged.push({ id: nextId++, kind: 'part', name: name, label: g.label, views: g.views,
          items: g.items.map(function (i) { return { file: files[i.index], uploadPath: i.path }; }) });
      });
      renderStaged(); renderCreate();
      Promise.all(fresh.map(checkItem)).then(function () { renderStaged(); renderCreate(); refreshEstimate(); });
    });
  }
  /* Dropzone: one drawing (several files = views of that one part). */
  function chooseDrawing(files) {
    var list = Array.prototype.slice.call(files || []);
    if (list.length) oneDrawing(list);
  }

  function commit() {
    if (creating) return;
    var ok = usable();
    var fileItems = ok.filter(function (x) { return x.kind === 'file'; });
    var partItems = ok.filter(function (x) { return x.kind === 'part'; });
    if (!ok.length && staged.length) return;
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
      creating = false; staged = staged.filter(function (x) { return x.problem; }); skippedNote = ''; stagedEst = null; renderStaged(); renderCreate();
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
