/* McA.viewer2d: the 2D drawing panel. Source rule comes from selectors.drawingSource
   (a draft with previewOverride wins, else the selected part's overview, else the draft, else empty).
   Pan by drag, wheel zoom at the cursor, double click or 0 to fit, arrows pan, + and - zoom. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var $ = function (id) { return document.getElementById(id); };
  var h = function () { return McA.dom.h.apply(null, arguments); };

  var MIN = 0.2, MAX = 12;
  var img, box, emptyEl, retryBtn, sw, strip;
  var view = 'overview';              // 'overview' | 'marked' (human pre-run) | 'engmarkup' (automatic post-run)
  var MV = null;                      // McA.markupview (pure logic)
  var mkLayer = null, mkNote = null;
  var mkPage = 1;                     // selected page of the Engineering Markup
  var seenKey = {}, userOverview = {}; // per part: the generation key already auto-selected / the one the user overrode
  var pendingFocus = null;
  var pageId = null;                  // selected page of a multi-page draft
  var bust = Date.now();
  var loadedKey = null, imgOk = false, imgErr = false, lastKind = 'empty';
  var z = { s: 1, tx: 0, ty: 0 };
  var drag = null;

  function apply() {
    img.style.transform = 'translate(' + z.tx + 'px,' + z.ty + 'px) scale(' + z.s + ')';
    if (McA.engFlags) McA.engFlags.syncTransform(z);     // the flag layer pans and zooms with the drawing
    if (mkLayer) { mkLayer.style.transform = 'translate(' + z.tx + 'px,' + z.ty + 'px) scale(' + z.s + ')'; mkLayer.style.setProperty('--zs', String(z.s)); }
  }
  function fit() { z.s = 1; z.tx = 0; z.ty = 0; apply(); }
  function zoomAt(factor, cx, cy) {
    var s2 = Math.min(MAX, Math.max(MIN, z.s * factor));
    if (s2 === z.s) return;
    var r = box.getBoundingClientRect();
    var mx = (cx === undefined ? r.left + r.width / 2 : cx) - (r.left + r.width / 2);
    var my = (cy === undefined ? r.top + r.height / 2 : cy) - (r.top + r.height / 2);
    var k = s2 / z.s;
    z.tx = mx - k * (mx - z.tx); z.ty = my - k * (my - z.ty);
    z.s = s2; apply();
  }

  /* ── automatic Engineering Markup ─────────────────────────────────────────── */
  function markupCtx() {
    var s = McA.store.get(), sel = s.parts.selected, ctx = s.outputs && s.outputs.ctx, p = s.outputs && s.outputs.payload;
    if (!sel || !ctx || ctx.part !== sel.part || !p || !p.categories) return null;
    return { session: sel.session, part: sel.part };
  }
  function markupModel() {
    var s = McA.store.get(), c = markupCtx();
    if (!c || !MV) return { state: 'none' };
    return MV.model(s.outputs.payload.categories.engineering_markup);
  }
  function partKey() { var c = markupCtx(); return c ? c.session + '/' + c.part : ''; }
  function setView(v, byUser) {
    var m = markupModel();
    if (byUser && v === 'overview' && m.key) userOverview[partKey() + '|' + m.key] = true;
    view = v; loadedKey = null;
    if (v === 'engmarkup' && MV && MV.usable(m)) {
      var pg = MV.pageInfo(m, mkPage) ? mkPage : MV.firstPage(m); mkPage = pg;
    }
    render();
  }
  function maybeAutoSelect() {
    var m = markupModel(), k = partKey();
    if (!k || !MV || !MV.exists(m)) return;
    var uo = !!userOverview[k + '|' + m.key];
    if (MV.autoSelect(m, seenKey[k], uo)) {
      seenKey[k] = m.key;
      mkPage = MV.firstPage(m);
      view = 'engmarkup'; loadedKey = null; render();
    } else if (m.state === 'failed' && seenKey[k] !== m.key && !uo) {
      seenKey[k] = m.key; view = 'engmarkup'; loadedKey = null; render();       // show the honest failure, not a clean drawing
    } else if (m.key) seenKey[k] = seenKey[k] || m.key;
  }
  function hitLayout() {
    if (!mkLayer) return;
    var m = markupModel();
    var on = view === 'engmarkup' && imgOk && MV && MV.usable(m) && img.naturalWidth > 0;
    mkLayer.hidden = !on;
    if (!on) { mkLayer.replaceChildren(); return; }
    var fit = McA.flagview.fitContain(box.clientWidth, box.clientHeight, img.naturalWidth, img.naturalHeight);
    var sel = McA.store.get().ui.flagSelected;
    mkLayer.replaceChildren();
    MV.hitBoxes(m, mkPage).forEach(function (b) {
      var px = MV.fracPx(b.frac, fit);
      var el = h('button', { type: 'button', class: 'mk-hit', 'data-finding': b.findingId, 'data-kind': b.kind, 'aria-label': MV.label(b), title: b.id + ': ' + b.title });
      el.style.left = px.left + 'px'; el.style.top = px.top + 'px'; el.style.width = px.width + 'px'; el.style.height = px.height + 'px';
      if (b.findingId === sel) el.setAttribute('aria-current', 'true');
      el.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); if (McA.engFlags) McA.engFlags.select(b.findingId, { reveal: true, from: 'box' }); });
      mkLayer.append(el);
    });
    applyPendingFocus();
  }
  function applyPendingFocus() {
    if (!pendingFocus || !imgOk || !MV) return;
    var m = markupModel(), t = MV.focusTarget(m, pendingFocus.id);
    var id = pendingFocus.id;
    if (!t || t.page !== mkPage) return;
    pendingFocus = null;
    if (t.zoom && t.frac) {
      var fit = McA.flagview.fitContain(box.clientWidth, box.clientHeight, img.naturalWidth, img.naturalHeight);
      var px = MV.fracPx(t.frac, fit);
      var tr = McA.flagview.focusTransform(px, { w: box.clientWidth, h: box.clientHeight }, { min: MIN, max: MAX });
      z.s = tr.s; z.tx = tr.tx; z.ty = tr.ty; apply();
    } else fit();                                                     // page-only / unlocated: open the page, no fake zoom
    var hit = mkLayer.querySelector('.mk-hit[data-finding="' + id + '"]');
    if (hit) hit.classList.add('is-pulse');
  }
  /** Switch to the Engineering Markup page of a flag and zoom to its region. Returns false when there is no markup for it. */
  function focusIssue(id) {
    var m = markupModel();
    if (!MV || !MV.usable(m) || !MV.hasFlag(m, id)) return false;
    var t = MV.focusTarget(m, id);
    if (!t) return false;
    pendingFocus = { id: id };
    if (view === 'engmarkup' && mkPage === t.page && imgOk) { applyPendingFocus(); return true; }
    mkPage = t.page; view = 'engmarkup'; loadedKey = null; render();
    return true;
  }
  function renderMarkupStrip(m) {
    strip.hidden = false;
    strip.setAttribute('aria-label', 'Pages of the engineering markup');
    strip.replaceChildren();
    var c = markupCtx();
    m.pages.forEach(function (pg) {
      var cur = pg.page === mkPage;
      var th = h('img', { alt: '' }); th.src = McA.api.engineeringMarkupPageURL(c.session, c.part, pg.page, m.key);
      var n = pg.finding_ids.length;
      var vis = 'Page ' + pg.page + (n ? ', ' + n + ' flag' + (n === 1 ? '' : 's') : ', no flags');   // the accessible name starts with the visible text
      var b = h('button', { type: 'button', class: 'vp-pg', 'aria-current': cur ? 'true' : null, 'aria-label': vis + ': show this marked page' },
        th, h('span', { text: vis }));
      b.addEventListener('click', function () { mkPage = pg.page; loadedKey = null; render(); });
      strip.append(b);
    });
  }

  function sourceInfo() {
    var s = McA.store.get();
    var src = McA.selectors.drawingSource(s);
    var out = { kind: src.kind, url: null, name: '', stateText: '', fmt: '', alt: '', missing: null, marked: false, emptyTitle: '', markup: null };
    if (src.kind === 'draft') {
      var items = s.intake.items;
      var pg = null;
      for (var i = 0; i < items.length; i++) if (items[i].id === pageId) pg = items[i];
      out.url = pg ? pg.dataURL : src.url;
      out.name = (s.intake.originalFile && s.intake.originalFile.name) || s.intake.stem || 'Unsaved drawing';
      out.stateText = 'Unsaved draft';
      out.fmt = s.intake.format || '';
      out.alt = 'Unsaved drawing ' + out.name;
    } else if (src.kind === 'part') {
      var p = null, list = s.parts.list || [];
      var isSession = s.session.id === src.session;
      for (var j = 0; j < list.length; j++) if (list[j].name === src.part) p = list[j];
      out.name = src.part; out.stateText = 'Saved';
      out.fmt = (p && p.source_format) ? String(p.source_format) : '';
      out.alt = 'Drawing of ' + src.part;
      out.marked = !!(p && p.has_marked);
      var mm = markupModel();
      out.markup = mm;
      if (view === 'engmarkup' && MV && !MV.exists(mm)) view = 'overview';
      if (view === 'engmarkup' && mm.state === 'failed') {
        out.missing = MV.banner(mm); out.emptyTitle = 'Engineering markup could not be generated';
      } else if (view === 'engmarkup' && MV && MV.usable(mm)) {
        out.url = McA.api.engineeringMarkupPageURL(src.session, src.part, mkPage, mm.key);
        out.stateText = 'Engineering Markup'; out.fmt = 'page ' + mkPage + ' of ' + mm.pages.length;
        out.alt = 'Engineering markup of ' + src.part + ', page ' + mkPage;
        return out;
      } else
      if (isSession && p && !p.has_overview && !(view === 'marked' && p.has_marked)) out.missing = 'No overview image is saved for this part.';
      else if (view === 'marked' && out.marked) out.url = McA.api.markedViewURL(src.session, src.part, bust);
      else out.url = McA.api.overviewURL(src.session, src.part, bust);
    }
    return out;
  }

  function setEmpty(title, desc, showRetry) {
    emptyEl.hidden = false;
    emptyEl.querySelector('.empty-t').textContent = title;
    emptyEl.querySelector('.empty-d').textContent = desc;
    retryBtn.hidden = !showRetry;
    box.classList.add('is-empty');
  }

  function loadImage(url) {
    imgOk = false; imgErr = false;
    img.hidden = true;
    var probe = new Image();
    probe.onload = function () {
      if (loadedKey === null || img.getAttribute('data-want') !== url) return;
      img.src = url; img.hidden = false; imgOk = true; imgErr = false;
      emptyEl.hidden = true; box.classList.remove('is-empty');
      fit(); renderTools();
      if (McA.engFlags) McA.engFlags.relayout();
      hitLayout();
    };
    probe.onerror = function () {
      if (img.getAttribute('data-want') !== url) return;
      imgErr = true; img.hidden = true;
      setEmpty('The drawing could not be loaded', 'The server returned no image for this drawing. Retry, or upload a drawing.', true);
      renderTools();
    };
    img.setAttribute('data-want', url);
    probe.src = url;
  }

  function renderStrip(items, show) {
    if (!show) { strip.hidden = true; strip.replaceChildren(); return; }
    strip.hidden = false;
    strip.setAttribute('aria-label', 'Pages of the unsaved drawing');
    strip.replaceChildren();
    items.forEach(function (it, i) {
      var cur = (pageId || items[0].id) === it.id;
      var th = h('img', { alt: '' }); th.src = it.dataURL;
      var b = h('button', { type: 'button', class: 'vp-pg', 'aria-current': cur ? 'true' : null, 'aria-label': 'Show ' + (it.label || 'page ' + (i + 1)) },
        th, h('span', { text: it.label || 'page ' + (i + 1) }));
      b.addEventListener('click', function () { pageId = it.id; render(); });
      strip.append(b);
    });
  }

  function renderNote(info) {
    if (!mkNote) return;
    var m = info.markup, txt = '', kind = '';
    if (view === 'engmarkup' && m && MV) { txt = MV.banner(m); kind = m.state; }
    mkNote.hidden = !txt || (m && m.state === 'failed');                 // a failure fills the empty state instead
    mkNote.textContent = txt; mkNote.setAttribute('data-kind', kind);
  }
  function renderSwitch(info) {
    var hasEng = !!(info.markup && MV && MV.exists(info.markup));
    sw.hidden = !info.marked && !hasEng;
    sw.querySelector('[data-v="marked"]').hidden = !info.marked;
    sw.querySelector('[data-v="engmarkup"]').hidden = !hasEng;
    if (!info.marked && view === 'marked') view = 'overview';
    if (sw.hidden) return;
    sw.querySelectorAll('button').forEach(function (b) {
      var on = b.getAttribute('data-v') === view;
      b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on));
    });
  }

  function renderTools() {
    var t = document.querySelectorAll('#vp-2d .vp-tools [data-act]');
    var has = imgOk;
    t.forEach(function (b) {
      var a = b.getAttribute('data-act');
      if (a === 'zoom-in' || a === 'zoom-out' || a === 'fit') { b.disabled = !has; b.title = has ? b.getAttribute('aria-label') : 'No drawing loaded'; }
      if (a === 'mark') { b.disabled = !has; b.title = has ? 'Mark regions' : 'No drawing loaded'; }
      if (a === 'crop') { b.disabled = false; b.title = 'Open the cropper'; }
    });
  }

  function render() {
    var info = sourceInfo();
    lastKind = info.kind;
    var s = McA.store.get();
    var items = s.intake.items;
    var multi = info.kind === 'draft' && items.length > 1;
    $('vp-2d-file').textContent = info.name;
    $('vp-2d-file').title = info.name;
    $('vp-2d-state').textContent = info.stateText;
    $('vp-2d-state').classList.toggle('warn', info.kind === 'draft');
    $('vp-2d-fmt').textContent = info.fmt;
    $('vp-2d-state').title = info.fmt ? 'Format: ' + info.fmt : '';
    img.alt = info.alt || '';
    renderSwitch(info);
    if (view === 'engmarkup' && info.markup && MV && MV.usable(info.markup)) renderMarkupStrip(info.markup); else renderStrip(items, multi);
    renderNote(info);
    if (info.kind === 'empty') {
      loadedKey = null; imgOk = false; img.hidden = true; img.removeAttribute('src'); img.removeAttribute('data-want');
      setEmpty('No drawing loaded', 'Upload a PDF, image or CAD drawing to start.', false);
      renderTools(); return;
    }
    if (info.missing) {
      loadedKey = 'missing|' + info.name; imgOk = false; img.hidden = true; img.removeAttribute('data-want');
      if (info.emptyTitle) setEmpty(info.emptyTitle, info.missing, false);
      else setEmpty('No overview image', info.missing + ' Upload a drawing or open the cropper to add one.', false);
      renderTools(); return;
    }
    var key = info.kind + '|' + info.url;
    if (key !== loadedKey) { loadedKey = key; loadImage(info.url); }
    if (McA.engFlags) McA.engFlags.relayout();
    hitLayout();
  }

  function retry() { bust = Date.now(); loadedKey = null; render(); }

  McA.viewer2d = {
    fit: fit, retry: retry, focusIssue: focusIssue, relayoutMarkup: hitLayout,
    hasMarkup: function (id) { var m = markupModel(); return !!(MV && MV.usable(m) && MV.hasFlag(m, id)); },
    showMarkup: function () { var m = markupModel(); if (MV && MV.usable(m)) setView('engmarkup', true); },
    /* What the flag layer needs: the pan/zoom, whether a real drawing is shown, and its natural size. */
    getView: function () { return { z: { s: z.s, tx: z.tx, ty: z.ty }, imgOk: imgOk, kind: lastKind, view: view, nw: img ? img.naturalWidth : 0, nh: img ? img.naturalHeight : 0 }; },
    setView: function (s, tx, ty) { z.s = Math.min(MAX, Math.max(MIN, s)); z.tx = tx; z.ty = ty; apply(); },
    init: function () {
      img = $('ov-img'); box = $('ov-box'); emptyEl = $('ov-empty'); strip = $('vp-2d-pages');
      MV = McA.markupview || null;
      retryBtn = h('button', { class: 'btn secondary sm', type: 'button', text: 'Retry', hidden: true });
      retryBtn.addEventListener('click', retry);
      emptyEl.insertBefore(retryBtn, emptyEl.querySelector('label'));

      /* Overview / Marked switch (only when the part has a marked view). */
      sw = h('div', { class: 'seg-c vp-src-sw', role: 'group', 'aria-label': 'Drawing version', hidden: true },
        h('button', { type: 'button', 'data-v': 'overview', text: 'Overview', 'aria-pressed': 'true' }),
        h('button', { type: 'button', 'data-v': 'marked', text: 'Marked', 'aria-pressed': 'false', title: 'Your own pre-run markup of the drawing' }),
        h('button', { type: 'button', 'data-v': 'engmarkup', text: 'Engineering Markup', 'aria-pressed': 'false', hidden: true,
          title: 'Automatic red-box flags generated by the pipeline after the run' }));
      sw.addEventListener('click', function (e) {
        var b = e.target.closest('button'); if (!b) return;
        setView(b.getAttribute('data-v'), true);
      });
      box.append(sw);
      mkLayer = h('div', { id: 'ov-mk-layer', class: 'mk-layer', role: 'group', 'aria-label': 'Engineering markup flags on the marked drawing', hidden: true });
      box.append(mkLayer);
      mkNote = h('p', { class: 'mk-note', role: 'status', hidden: true });
      box.append(mkNote);
      box.addEventListener('wheel', function (e) {
        if (!imgOk) return;
        e.preventDefault();
        zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY);
      }, { passive: false });
      box.addEventListener('pointerdown', function (e) {
        if (!imgOk || e.button !== 0 || e.target.closest('button, label')) return;
        drag = { x: e.clientX - z.tx, y: e.clientY - z.ty };
        box.setPointerCapture(e.pointerId); box.classList.add('is-pan');
      });
      box.addEventListener('pointermove', function (e) {
        if (!drag) return;
        z.tx = e.clientX - drag.x; z.ty = e.clientY - drag.y; apply();
      });
      var end = function (e) {
        if (!drag) return;
        drag = null; box.classList.remove('is-pan');
        if (box.hasPointerCapture(e.pointerId)) box.releasePointerCapture(e.pointerId);
      };
      box.addEventListener('pointerup', end); box.addEventListener('pointercancel', end);
      box.addEventListener('dblclick', function () { if (imgOk) fit(); });
      box.addEventListener('keydown', function (e) {
        if (!imgOk || e.target !== box) return;
        var step = e.shiftKey ? 120 : 40, used = true;
        if (e.key === 'ArrowLeft') z.tx += step; else if (e.key === 'ArrowRight') z.tx -= step;
        else if (e.key === 'ArrowUp') z.ty += step; else if (e.key === 'ArrowDown') z.ty -= step;
        else if (e.key === '+' || e.key === '=') { zoomAt(1.25); used = false; }
        else if (e.key === '-' || e.key === '_') { zoomAt(1 / 1.25); used = false; }
        else if (e.key === '0') { fit(); used = false; }
        else return;
        e.preventDefault(); if (used) apply();
      });
      box.setAttribute('aria-label', 'Drawing viewport. Arrow keys pan, plus and minus zoom, 0 fits.');

      $('vp-2d').querySelector('.vp-tools').addEventListener('click', function (e) {
        var b = e.target.closest('[data-act]'); if (!b || b.disabled) return;
        var a = b.getAttribute('data-act');
        if (a === 'zoom-in') zoomAt(1.25); else if (a === 'zoom-out') zoomAt(1 / 1.25);
        else if (a === 'fit') fit();
        else if (a === 'crop') McA.cropper.open('crop', b);
        else if (a === 'mark') McA.cropper.open('mark', b);
      });

      var st = McA.store;
      st.subscribe(function (s) { return s.intake.items; }, function () {
        var items = st.get().intake.items;
        if (pageId && !items.some(function (i) { return i.id === pageId; })) pageId = null;
        render();
      });
      st.subscribe(function (s) { return s.intake.source; }, render);
      st.subscribe(function (s) { return s.intake.previewOverride; }, render);
      st.subscribe(function (s) { return s.intake.format; }, render);
      st.subscribe(function (s) { return s.parts.selected; }, function () { view = 'overview'; mkPage = 1; pendingFocus = null; bust = Date.now(); render(); });
      st.subscribe(function (s) { return s.outputs; }, function () { maybeAutoSelect(); render(); });
      st.subscribe(function (s) { return s.ui.flagSelected; }, function () { if (view === 'engmarkup') hitLayout(); });
      if (window.ResizeObserver) new ResizeObserver(McA.util.debounce(hitLayout, 30)).observe(box);
      st.subscribe(function (s) { return s.parts.list; }, function () { bust = Date.now(); render(); });
      st.subscribe(function (s) { return s.markup.saveState; }, function (v) { if (v === 'saved' && view === 'marked') { bust = Date.now(); render(); } });
      render();
    }
  };
})();
