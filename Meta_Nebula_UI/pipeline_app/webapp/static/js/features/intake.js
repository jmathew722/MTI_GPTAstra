/* McA.intake: drawing upload (PDF rasterize, images, CAD convert with sheet picker), view gallery,
   validation, save part, must-meet notes, parts-folder upload. Logic ported from index.legacy.html.
   Never starts a pipeline run. State lives in store.intake; this module owns the side effects. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var $ = function (id) { return document.getElementById(id); };
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var store = function () { return McA.store; };
  var S = function () { return McA.store.get(); };

  var IMAGE_EXT = ['jpg', 'jpeg', 'png', 'webp', 'bmp', 'tif', 'tiff'];
  var CAD_EXT = ['dwg', 'dxf', 'edrw', 'eprt', 'easm'];
  var EDRW_EXT = ['edrw', 'eprt', 'easm'];
  var MAX_PDF_PAGES = 12;           // legacy limit
  var PDF_DPI = 200;                // legacy raster scale 200/72
  var FOLDER_RE = /\.(jpe?g|png|webp|bmp|tiff?|txt)$/i;
  var FORMATS_TEXT = 'PDF, JPG, PNG, WEBP, BMP, TIFF, DWG, DXF, eDrawings (EDRW, EPRT, EASM)';

  var busy = false;
  var saving = false;
  var notesDirty = false;

  function extOf(name) { return (String(name).split('.').pop() || '').toLowerCase(); }
  function stemOf(name) { return String(name).replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_-]+/g, '_'); }
  function errText(e) { return (e && (e.detail || e.message)) || 'unknown error'; }
  function toast(t, k, o) { return McA.toast.show(t, k, o); }

  function readDataURL(blob) {
    return new Promise(function (res, rej) {
      var r = new FileReader();
      r.onload = function () { res(r.result); };
      r.onerror = function () { rej(new Error('Could not read the file.')); };
      r.readAsDataURL(blob);
    });
  }

  /** Orientation guess from a crop name (legacy guessOrientation). */
  function guessOrientation(name) {
    var n = (name || '').toLowerCase();
    if (n.indexOf('marked') >= 0) return 'marked';
    if (n.indexOf('front') >= 0) return 'front';
    if (n.indexOf('back') >= 0 || n.indexOf('rear') >= 0) return 'back';
    if (n.indexOf('bottom') >= 0) return 'bottom';
    if (n.indexOf('top') >= 0 || n.indexOf('plan') >= 0) return 'top';
    if (n.indexOf('left') >= 0) return 'left';
    if (n.indexOf('right') >= 0 || n.indexOf('side') >= 0) return 'right';
    if (n.indexOf('iso') >= 0 || n.indexOf('overview') >= 0 || n.indexOf('full') >= 0) return 'overview';
    return '';
  }

  function rotateDataURL(dataURL) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        var c = document.createElement('canvas');
        c.width = img.naturalHeight; c.height = img.naturalWidth;
        var g = c.getContext('2d');
        g.translate(c.width / 2, c.height / 2); g.rotate(Math.PI / 2);
        g.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);
        resolve(c.toDataURL('image/jpeg', 0.95));
      };
      img.onerror = function () { reject(new Error('Could not rotate the image.')); };
      img.src = dataURL;
    });
  }

  function patchIntake(p) { store().dispatch('intake/update', { patch: p }); }
  function addItems(entries) { store().dispatch('intake/add', { items: entries }); }

  /* After a load: preview shows the draft, name defaults to the file stem. */
  function afterLoad(stem) {
    var it = S().intake;
    var patch = { previewOverride: true };
    if (!String(it.nameDraft || '').trim()) patch.nameDraft = stem;
    patchIntake(patch);
  }

  /* ── Loaders ─────────────────────────────────────────────────────────── */
  function setSource(file, stem, format, url, first) {
    var it = S().intake;
    if (first || !it.source) patchIntake({ source: url, originalFile: file, stem: stem, format: format });
    else patchIntake({ format: 'Multiple files' });
  }

  function loadPdf(file, stem, first) {
    if (typeof pdfjsLib === 'undefined') return Promise.reject(new Error('The PDF reader did not load.'));
    var t = toast('Rasterizing PDF pages…', 'info', { ms: 60000 });
    var objUrl = URL.createObjectURL(file);
    return pdfjsLib.getDocument(objUrl).promise.then(function (pdf) {
      var pages = Math.min(pdf.numPages, MAX_PDF_PAGES);
      var urls = [];
      var chain = Promise.resolve();
      var p;
      for (p = 1; p <= pages; p++) {
        (function (n) {
          chain = chain.then(function () { return pdf.getPage(n); }).then(function (page) {
            var vp = page.getViewport({ scale: PDF_DPI / 72 });
            var c = document.createElement('canvas');
            c.width = Math.round(vp.width); c.height = Math.round(vp.height);
            return page.render({ canvasContext: c.getContext('2d'), viewport: vp }).promise.then(function () {
              urls.push(c.toDataURL('image/jpeg', 0.95));
            });
          });
        })(p);
      }
      return chain.then(function () {
        var extra = pdf.numPages > MAX_PDF_PAGES ? ' (first ' + MAX_PDF_PAGES + ' of ' + pdf.numPages + ' pages)' : '';
        setSource(file, stem, 'PDF' + (pages > 1 ? ' · ' + pages + ' pages' : ''), urls[0], first);
        addItems(urls.map(function (u, i) {
          return { dataURL: u, label: pages > 1 ? 'page ' + (i + 1) : file.name, orientation: pages === 1 ? 'front' : '' };
        }));
        afterLoad(stem);
        toast('Loaded ' + pages + ' page' + (pages === 1 ? '' : 's') + ' from ' + file.name + extra + '. Assign a view type to each.', 'ok');
        return pages;
      });
    }).then(function (v) { t.dismiss(); URL.revokeObjectURL(objUrl); return v; },
            function (e) { t.dismiss(); URL.revokeObjectURL(objUrl); throw e; });
  }

  function loadImage(file, stem, ext, first) {
    return readDataURL(file).then(function (url) {
      setSource(file, stem, 'Image (' + ext.toUpperCase() + ')', url, first);
      addItems([{ dataURL: url, label: file.name, orientation: 'front' }]);
      afterLoad(stem);
      toast('Loaded ' + file.name + '. Check the view type; add more views through the cropper.', 'ok');
      return 1;
    });
  }

  /* Sheet picker for multi-sheet DWG/DXF. Resolves a layout name or null. */
  function pickSheet(file, layouts) {
    var sel = h('select', { class: 'input-c', id: 'sheet-select', 'aria-label': 'Sheet' },
      layouts.map(function (n) { return h('option', { value: n, text: n }); }));
    var body = h('div', null,
      h('p', { text: '"' + file.name + '" has ' + layouts.length + ' sheets. Choose the one to load.' }),
      h('div', { class: 'sheet-sel' }, sel));
    return McA.dialog.open({ title: 'Choose a sheet', body: body, initial: '#sheet-select',
      actions: [{ id: 'cancel', label: 'Cancel' }, { id: 'load', label: 'Load sheet', kind: 'primary' }] })
      .then(function (r) { return r === 'load' ? sel.value : null; });
  }

  /** Convert a CAD file on the server. Resolves the number of items added (0 when cancelled). */
  function loadCad(file, stem, layout, first) {
    var ext = extOf(file.name), isEdrw = EDRW_EXT.indexOf(ext) >= 0;
    var t = toast((isEdrw ? 'Extracting eDrawings preview' : 'Converting ' + ext.toUpperCase()) + ' on the server…', 'info', { ms: 120000 });
    return McA.api.convertCad(file, layout || '').then(function (r) {
      t.dismiss();
      if (r.kind === 'layouts') {
        return pickSheet(file, r.layouts).then(function (name) {
          if (!name) return 0;
          return loadCad(file, stem, name, first);
        });
      }
      return readDataURL(r.blob).then(function (url) {
        var fmt = isEdrw || r.staticPreview ? 'eDrawings (static preview)'
          : ext.toUpperCase() + ' (converted)' + (layout ? ' · ' + layout : '');
        setSource(file, stem, fmt, url, first);
        addItems([{ dataURL: url, label: file.name, orientation: 'front' }]);
        afterLoad(stem);
        /* Also open the converted image in the cropper (it cannot read CAD itself).
           The cropper mirrors loads back as src-open; flag that echo so it is dropped. */
        var iframe = $('photoapp');
        if (iframe && window.MTIBridge) {
          patchIntake({ expectEcho: stem + '.png' });
          window.MTIBridge.sendImage(iframe, url, stem + '.png').catch(function (e) { console.warn('cropper load failed', e); });
        }
        toast(isEdrw || r.staticPreview
          ? 'Extracted a STATIC preview from ' + file.name + '. It is not the interactive model. Check the view type, then save.'
          : 'Converted ' + file.name + (layout ? ' (sheet ' + layout + ')' : '') + '. Check the view type, then save.', 'ok');
        return 1;
      });
    }).catch(function (e) { t.dismiss(); throw e; });
  }

  /** Entry for every file source (Home, workspace, inspector, drag and drop). */
  function handleFiles(files, source) {
    var list = Array.prototype.slice.call(files || []);
    if (!list.length) return Promise.resolve();
    if (busy) { toast('Still reading the previous file. Try again in a moment.', 'warn'); return Promise.resolve(); }
    var ok = [], bad = [];
    list.forEach(function (f) {
      var e = extOf(f.name);
      if (e === 'pdf' || IMAGE_EXT.indexOf(e) >= 0 || CAD_EXT.indexOf(e) >= 0) ok.push(f); else bad.push(f.name);
    });
    if (bad.length) toast('Unsupported format: ' + bad.join(', ') + '. Supported: ' + FORMATS_TEXT + '.', 'err');
    if (!ok.length) return Promise.resolve();

    var existing = S().intake.items.length > 0;
    var decide = existing
      ? McA.dialog.open({ title: 'A draft is already open',
          body: 'The current draft has ' + S().intake.items.length + ' image' + (S().intake.items.length === 1 ? '' : 's') + ' that are not saved yet. Add the new drawing to it, or start over?',
          actions: [{ id: 'cancel', label: 'Cancel' }, { id: 'new', label: 'Start a new draft' }, { id: 'add', label: 'Add to current draft', kind: 'primary' }] })
      : Promise.resolve('new');
    return decide.then(function (choice) {
      if (choice !== 'add' && choice !== 'new') return;
      if (choice === 'new' && existing) {
        if (McA.markup && McA.markup.clearIntake) McA.markup.clearIntake();
        store().dispatch('intake/reset');
        notesDirty = false;
      }
      busy = true;
      var first = choice === 'new';
      var chain = Promise.resolve();
      ok.forEach(function (f, i) {
        chain = chain.then(function () {
          var ext = extOf(f.name), stem = stemOf(f.name), isFirst = first && i === 0;
          if (ext === 'pdf') return loadPdf(f, stem, isFirst);
          if (CAD_EXT.indexOf(ext) >= 0) return loadCad(f, stem, '', isFirst);
          return loadImage(f, stem, ext, isFirst);
        }).catch(function (e) { toast('Could not load ' + f.name + ': ' + errText(e), 'err'); });
      });
      return chain.then(function () { busy = false; }, function () { busy = false; });
    });
  }

  /** Pull queued crops from the cropper iframe (MTIBridge.collect). */
  function pullCrops() {
    var iframe = $('photoapp');
    if (!iframe || !window.MTIBridge) { toast('The cropper is not available.', 'err'); return Promise.resolve(0); }
    var t = toast('Reading queued views from the cropper…', 'info', { ms: 20000 });
    return window.MTIBridge.collect(iframe).then(function (payload) {
      t.dismiss();
      var it = S().intake;
      var patch = { previewOverride: true };
      if (payload.source && !it.source) patch.source = payload.source;
      if (!it.format) patch.format = 'Cropped views';
      if (!it.items.length) patch.stem = payload.stem || it.stem;
      patchIntake(patch);
      addItems(payload.crops.map(function (c) { return { dataURL: c.dataURL, label: c.name, orientation: guessOrientation(c.name) }; }));
      if (!String(S().intake.nameDraft || '').trim()) patchIntake({ nameDraft: S().intake.stem });
      McA.dom.dispatch('ui/inspectorSection', { id: 'setup', open: true });
      toast('Pulled ' + payload.crops.length + ' crop' + (payload.crops.length === 1 ? '' : 's') + '. Check each view type, then save.', 'ok');
      return payload.crops.length;
    }, function (e) { t.dismiss(); toast(errText(e), 'err'); return 0; });
  }

  /* ── Save part ───────────────────────────────────────────────────────── */
  function existingPart(name) {
    var want = String(name).trim().toLowerCase();
    var list = S().parts.list || [];
    for (var i = 0; i < list.length; i++) if (String(list[i].name).toLowerCase() === want) return list[i];
    return null;
  }

  function savePart() {
    if (saving) return Promise.resolve();
    var s = S(), v = McA.selectors.intakeValidation(s);
    if (!v.canSave) return Promise.resolve();
    var sid = s.session.id;
    if (!sid) { toast('The session is not ready yet. Try again in a moment.', 'err'); return Promise.resolve(); }
    var it = s.intake;
    var part = String(it.nameDraft || '').trim() || it.stem || 'drawing';
    var chain = Promise.resolve(true);
    if (v.duplicates.length) {
      chain = chain.then(function () {
        return McA.dialog.confirm('Duplicate view types',
          'The same view type is assigned to more than one image (' + v.duplicates.join(', ') + '). Some parts legitimately have two candidates: the pipeline keeps the first and warns. Save anyway?', 'Save anyway');
      });
    }
    var unassigned = it.items.filter(function (i) { return !i.orientation; }).length;
    if (unassigned) {
      chain = chain.then(function (go) {
        if (!go) return false;
        return McA.dialog.confirm('Images without a view type', unassigned + ' image' + (unassigned === 1 ? ' has' : 's have') + ' no view type and will be skipped. Save anyway?', 'Save anyway');
      });
    }
    var prior = existingPart(part);
    if (prior) {
      chain = chain.then(function (go) {
        if (!go) return false;
        return McA.dialog.confirm('Replace saved views?',
          'Saving replaces the saved views of "' + prior.name + '". Its outputs are kept.', 'Replace views', true);
      });
    }
    return chain.then(function (go) {
      if (!go) return;
      var fd = new FormData();
      fd.append('session', sid);
      fd.append('part', part);
      fd.append('source_format', it.format || '');
      fd.append('notes', it.notesDraft || '');
      if (it.source) fd.append('source', window.MTIBridge.dataURLtoBlob(it.source), 'source.jpg');
      if (it.originalFile) fd.append('original', it.originalFile, it.originalFile.name);
      var counts = {};
      it.items.forEach(function (item) {
        if (!item.orientation) return;
        var base = item.orientation;
        counts[base] = (counts[base] || 0) + 1;
        var name = counts[base] > 1 ? base + '_' + counts[base] : base;
        fd.append('crops', window.MTIBridge.dataURLtoBlob(item.dataURL), name + '.jpg');
      });
      saving = true; renderValidation();
      return McA.api.savePart(fd).then(function (res) {
        saving = false;
        if (!res || !res.parts) throw new Error('The server did not return the saved part.');
        store().dispatch('parts/loaded', { list: res.parts });
        if (McA.markup && McA.markup.transferIntake) McA.markup.transferIntake(res.part);
        store().dispatch('intake/reset');
        notesDirty = false;
        store().dispatch('parts/select', { session: sid, part: res.part });
        syncNotesFromPart();
        toast('Saved part "' + res.part + '". Press Run Pipeline when you are ready.', 'ok');
      }, function (e) { saving = false; renderValidation(); toast('Save part failed: ' + errText(e), 'err'); });
    });
  }

  function saveNotes() {
    var s = S(), sel = s.parts.selected;
    if (!sel || s.intake.items.length) return Promise.resolve();
    return McA.api.saveNotes(sel.session, sel.part, s.intake.notesDraft || '').then(function (d) {
      if (d && d.parts) store().dispatch('parts/loaded', { list: d.parts });
      notesDirty = false; renderNotes();
      toast('Specs for "' + sel.part + '" saved. They are graded on the next run.', 'ok');
    }, function (e) { toast('Could not save specs: ' + errText(e), 'err'); });
  }

  /* ── Parts folder upload ─────────────────────────────────────────────── */
  function handleFolder(files) {
    var list = Array.prototype.slice.call(files || []);
    if (!list.length) return Promise.resolve();
    var usable = list.filter(function (f) { return FOLDER_RE.test(f.name); });
    if (!usable.length) { toast('No view images or .txt spec files found in that folder.', 'err'); return Promise.resolve(); }
    var sid = S().session.id;
    if (!sid) { toast('The session is not ready yet. Try again in a moment.', 'err'); return Promise.resolve(); }
    var t = toast('Uploading ' + usable.length + ' file' + (usable.length === 1 ? '' : 's') + ' from the parts folder…', 'info', { ms: 120000 });
    var fd = new FormData();
    fd.append('session', sid);
    usable.forEach(function (f) { fd.append('paths', f.webkitRelativePath || f.name); fd.append('files', f, f.name); });
    return McA.api.uploadBatch(fd).then(function (d) {
      t.dismiss();
      if (d.parts) store().dispatch('parts/loaded', { list: d.parts });
      var added = d.added || [];
      if (added.length && !S().parts.selected) store().dispatch('parts/select', { session: sid, part: added[0] });
      toast('Added ' + added.length + ' part' + (added.length === 1 ? '' : 's') + ' from the folder (' + (d.n_files != null ? d.n_files : usable.length) + ' files' +
        (d.n_skipped ? ', ' + d.n_skipped + ' skipped' : '') + ')' + (added.length ? ': ' + added.join(', ') : '') + '.', added.length ? 'ok' : 'warn');
    }, function (e) { t.dismiss(); toast('Parts folder upload failed: ' + errText(e), 'err'); });
  }

  /* ── Rendering: gallery, validation, fields ──────────────────────────── */
  var gallerySig = '';
  function renderGallery() {
    var g = $('orient-gallery'); if (!g) return;
    var items = S().intake.items;
    var dups = McA.selectors.duplicateOrientations(items);
    var sig = items.map(function (i) { return i.id + ':' + (i.dataURL ? i.dataURL.length : 0); }).join('|');
    if (sig === gallerySig) { patchGallery(g, items, dups); return; }
    gallerySig = sig;
    var active = document.activeElement, keep = active && g.contains(active) ? { id: active.getAttribute('data-id'), role: active.getAttribute('data-role') } : null;
    g.replaceChildren();
    items.forEach(function (it, idx) {
      var sel = h('select', { class: 'input-c oselect', 'data-id': it.id, 'data-role': 'type', 'aria-label': 'View type for image ' + (idx + 1) });
      sel.append(h('option', { value: '', text: 'Choose view type' }));
      McA.selectors.ORIENTATIONS.forEach(function (o) { sel.append(h('option', { value: o[0], text: o[1] })); });
      sel.addEventListener('change', function () { store().dispatch('intake/update', { id: it.id, patch: { orientation: sel.value } }); });
      var rot = h('button', { class: 'ibtn', type: 'button', 'data-id': it.id, 'data-role': 'rot', title: 'Rotate 90° (scanned drawings are often rotated)', 'aria-label': 'Rotate image ' + (idx + 1) + ' by 90 degrees' });
      rot.append(McA.icons.get('rotate', 16));
      rot.addEventListener('click', function () {
        var cur = S().intake.items.filter(function (x) { return x.id === it.id; })[0];
        if (!cur) return;
        rotateDataURL(cur.dataURL).then(function (u) { store().dispatch('intake/update', { id: it.id, patch: { dataURL: u } }); },
          function (e) { toast(errText(e), 'err'); });
      });
      var del = h('button', { class: 'ibtn', type: 'button', 'data-id': it.id, 'data-role': 'del', title: 'Remove this image', 'aria-label': 'Remove image ' + (idx + 1) });
      del.append(McA.icons.get('x', 16));
      del.addEventListener('click', function () { store().dispatch('intake/remove', { id: it.id }); });
      var img = h('img', { alt: 'Preview of ' + (it.label || 'image ' + (idx + 1)), title: it.label || '' });
      img.src = it.dataURL;
      var card = h('div', { class: 'ocard', 'data-id': it.id },
        h('div', { class: 'ocard-th' }, img),
        h('div', { class: 'ocard-b' },
          h('span', { class: 'ocard-l', text: it.label || 'Image ' + (idx + 1) }),
          h('div', { class: 'ocard-c' }, sel, rot, del),
          h('span', { class: 'dupbadge', hidden: true, text: 'Duplicate view type' })));
      g.append(card);
    });
    patchGallery(g, items, dups);
    if (keep && keep.id) {
      var again = g.querySelector('[data-id="' + keep.id + '"][data-role="' + keep.role + '"]');
      if (again) again.focus();
    }
  }
  function patchGallery(g, items, dups) {
    items.forEach(function (it) {
      var card = g.querySelector('.ocard[data-id="' + it.id + '"]'); if (!card) return;
      var sel = card.querySelector('select');
      if (sel.value !== (it.orientation || '')) sel.value = it.orientation || '';
      var isDup = !!it.orientation && dups.indexOf(it.orientation) >= 0;
      card.classList.toggle('assigned', !!it.orientation);
      card.classList.toggle('dup', isDup);
      card.querySelector('.dupbadge').hidden = !isDup;
    });
  }

  function renderValidation() {
    var s = S(), v = McA.selectors.intakeValidation(s);
    var warn = $('req-warn'), save = $('save-part-btn'), why = $('save-why');
    if (!warn) return;
    warn.textContent = v.message;
    warn.className = 'req-warn' + (v.level === 'ok' ? ' is-ok' : v.level === 'info' ? ' is-info' : '');
    var running = McA.selectors.isRunning(s);
    var can = v.canSave && !saving;
    save.disabled = !can;
    save.textContent = saving ? 'Saving…' : 'Save part';
    why.classList.remove('is-warn');
    if (saving) why.textContent = 'Saving the views to this session.';
    else if (v.empty) why.textContent = 'Nothing to save yet.';
    else if (running && v.ok) why.textContent = 'A run is in progress. Save is available when it ends.';
    else if (!v.ok) why.textContent = v.message;
    else why.textContent = 'Saves the views to this session. It does not start a run.';
  }

  function renderFields() {
    var s = S(), it = s.intake, has = it.items.length > 0;
    var name = $('part-name'), why = $('part-name-why');
    var saved = !has && s.parts.selected;
    name.disabled = !has;
    why.hidden = has || !!saved;
    /* With no draft, the field shows the saved part's name (read-only) instead of an empty box. */
    var want = has ? (it.nameDraft || '') : (saved ? saved.part : '');
    if (name.value !== want && document.activeElement !== name) name.value = want;
    var sel = McA.selectors.drawingSource(s);
    var mk = $('mark-regions-btn'), views = $('views-why');
    $('open-cropper-btn').disabled = false;
    $('pull-crops-inline-btn').disabled = false;
    mk.disabled = sel.kind === 'empty';
    mk.title = mk.disabled ? 'Load a drawing or select a part first' : '';
    views.textContent = has ? 'Assign a view type to every image. FRONT plus one more orthographic view are needed.'
      : 'Upload a drawing, or open the cropper to crop views. Mark regions needs a drawing.';
    renderNotes();
  }

  function renderNotes() {
    var s = S(), it = s.intake, has = it.items.length > 0, sel = s.parts.selected;
    var ta = $('part-notes'), btn = $('save-notes-btn'), why = $('notes-why');
    var enabled = has || !!sel;
    ta.disabled = !enabled;
    if (ta.value !== (it.notesDraft || '') && document.activeElement !== ta) ta.value = it.notesDraft || '';
    var part = McA.selectors.selectedPart(s);
    var changed = !!(sel && !has && (it.notesDraft || '') !== ((part && part.notes) || ''));
    btn.disabled = !(sel && !has && changed);
    btn.textContent = sel && !has ? 'Update specs for ' + sel.part : 'Update specs';
    if (has) why.textContent = 'Authoritative: graded against the build. Sent with Save part.';
    else if (sel && changed) why.textContent = 'Press Update specs to store these for "' + sel.part + '".';
    else if (sel) why.textContent = 'Saved specs of "' + sel.part + '". Edit them, then Update specs.';
    else why.textContent = 'Add a drawing or select a saved part first.';
  }

  function syncNotesFromPart() {
    var s = S();
    if (s.intake.items.length) return;
    var part = McA.selectors.selectedPart(s);
    var txt = (part && part.notes) || '';
    if ((s.intake.notesDraft || '') !== txt) patchIntake({ notesDraft: txt });
  }

  /* ── Init ────────────────────────────────────────────────────────────── */
  McA.intake = {
    handleFiles: handleFiles, handleFolder: handleFolder, pullCrops: pullCrops, loadCad: loadCad,
    guessOrientation: guessOrientation, rotateDataURL: rotateDataURL, savePart: savePart, FORMATS_TEXT: FORMATS_TEXT,
    init: function () {
      if (typeof pdfjsLib !== 'undefined' && pdfjsLib.GlobalWorkerOptions) pdfjsLib.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.js';

      /* Actions dispatched by pages. Reducers stay pure; work is deferred. */
      store().register('intake/files', function (s, p) { setTimeout(function () { handleFiles(p && p.files, p && p.source); }, 0); return null; });
      store().register('intake/folder', function (s, p) { setTimeout(function () { handleFolder(p && p.files); }, 0); return null; });

      var file = $('intake-file');
      file.addEventListener('change', function () { var l = file.files; var a = Array.prototype.slice.call(l); file.value = ''; handleFiles(a, 'inspector'); });
      var folder = $('batch-folder');
      folder.addEventListener('change', function () { var a = Array.prototype.slice.call(folder.files); folder.value = ''; handleFolder(a); });
      $('part-name').addEventListener('input', function (e) { patchIntake({ nameDraft: e.target.value }); });
      $('part-notes').addEventListener('input', function (e) { notesDirty = true; patchIntake({ notesDraft: e.target.value }); });
      $('save-part-btn').addEventListener('click', savePart);
      $('save-notes-btn').addEventListener('click', saveNotes);
      $('pull-crops-inline-btn').addEventListener('click', pullCrops);
      ['intake-file-lbl', 'batch-folder-lbl'].forEach(function (id) {
        var lbl = $(id);
        lbl.tabIndex = 0;
        lbl.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $(id === 'intake-file-lbl' ? 'intake-file' : 'batch-folder').click(); }
        });
      });

      store().subscribe(function (s) { return s.intake.items; }, function () { renderGallery(); renderValidation(); renderFields(); });
      store().subscribe(function (s) { return s.intake.nameDraft; }, function () { renderValidation(); renderFields(); });
      store().subscribe(function (s) { return s.intake.notesDraft; }, renderNotes);
      store().subscribe(function (s) { return s.intake.source; }, renderFields);
      store().subscribe(function (s) { return s.run.state; }, renderValidation);
      store().subscribe(function (s) { return s.parts.selected; }, function () {
        if (S().intake.previewOverride) patchIntake({ previewOverride: false });
        notesDirty = false; syncNotesFromPart(); renderFields();
      });
      store().subscribe(function (s) { return s.parts.list; }, function () { if (!notesDirty) syncNotesFromPart(); renderFields(); });
      renderGallery(); renderValidation(); renderFields();
    }
  };
})();
