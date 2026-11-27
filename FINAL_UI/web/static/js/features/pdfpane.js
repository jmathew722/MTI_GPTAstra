/* McA.pdfpane.create(opts): a reusable PDF sheet viewer (pdf.js) with pages, zoom, fit, drag-to-pan and its own loading / error / empty states.
   Used by the 3D -> 2D page for the left "Source PDF" view (the right generated-drawing viewer keeps its own code). It owns its pdf.js document and
   destroys it on clear/load, so nothing from a previous part is ever shown after a switch.
   opts: { label, icon(name,size), onView(view), onRendered() }   (onView fires only for user-driven page / zoom / pan changes, so a synchronised pane never echoes;
          view = {page, zoom, sx, sy} where sx, sy are the scroll position as fractions 0..1 of the scrollable range)
   pane:  { el, tools, load(url, key), clear(), message(kind, title, text, retry), getView(), setView({page,zoom,sx,sy}), numPages(), resize(), isReady(), key(),
            canvas(), wrap(), isIdle(), mark(box|null), markBox(), locate(page, text), doc() }
   McA.pdfpane.attachMark(wrap, paper) / locateIn(doc, page, text) are the same helpers for a viewer that is not a pdfpane (the generated sheet). */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var h = function () { return McA.dom.h.apply(null, arguments); };

  function create(opts) {
    opts = opts || {};
    var icon = opts.icon || function (n, s) { return McA.icons.get(n, s || 16); };
    var P = { doc: null, page: 1, zoom: 1, task: null, rendering: false, again: false, key: '', ready: false, token: 0, pend: null, expect: null };
    var paper = h('canvas', { class: 'rv-paper', 'aria-label': (opts.label || 'PDF') + ' sheet' });
    var wrap = h('div', { class: 'rv-paperwrap rv-pan', tabindex: '0', role: 'region', 'aria-label': (opts.label || 'PDF') + ' sheet (scrollable; drag to pan)', hidden: true }, paper);
    var box = h('div', { class: 'vp-empty rv-pempty' });
    var el = h('div', { class: 'rv-pdfpane' }, wrap, box);
    var pageLbl = h('span', { class: 'rv-pagelbl', 'aria-live': 'polite' }), zoomLbl = h('span', { class: 'rv-zoomlbl' });
    function tb(attrs, ic, label, fn) { return h('button', Object.assign({ class: 'ibtn', type: 'button', title: label, 'aria-label': label, onclick: fn }, attrs || {}), icon(ic, 18)); }
    var prev = tb({}, 'chevron-left', 'Previous page of ' + (opts.label || 'PDF'), function () { go(P.page - 1, true); });
    var next = tb({}, 'chevron-right', 'Next page of ' + (opts.label || 'PDF'), function () { go(P.page + 1, true); });
    var zout = tb({}, 'zoom-out', 'Zoom out ' + (opts.label || 'PDF'), function () { zoomTo(P.zoom - 0.25, true); });
    var zin = tb({}, 'zoom-in', 'Zoom in ' + (opts.label || 'PDF'), function () { zoomTo(P.zoom + 0.25, true); });
    var fit = tb({}, 'fit', 'Fit ' + (opts.label || 'PDF') + ' to view', function () { zoomTo(1, true); wrap.scrollLeft = wrap.scrollTop = 0; });
    var tools = h('div', { class: 'vp-tools', role: 'toolbar', 'aria-label': (opts.label || 'PDF') + ' tools' }, prev, pageLbl, next, zout, zoomLbl, zin, fit);
    var btns = [prev, next, zout, zin, fit];

    var marker = McA.pdfpane.attachMark(wrap, paper);
    function frac() { var C = McA.compareview; return C ? { sx: C.scrollFraction(wrap.scrollLeft, wrap.scrollWidth, wrap.clientWidth), sy: C.scrollFraction(wrap.scrollTop, wrap.scrollHeight, wrap.clientHeight) } : { sx: 0, sy: 0 }; }
    function view() { var f = frac(); return { page: P.page, zoom: P.zoom, sx: f.sx, sy: f.sy }; }
    function applyScroll(v) {
      var C = McA.compareview; if (!C || !v) return;
      if (typeof v.sx === 'number') wrap.scrollLeft = C.scrollFromFraction(v.sx, wrap.scrollWidth, wrap.clientWidth);
      if (typeof v.sy === 'number') wrap.scrollTop = C.scrollFromFraction(v.sy, wrap.scrollHeight, wrap.clientHeight);
      P.expect = { l: wrap.scrollLeft, t: wrap.scrollTop };           // the scroll event this causes is an echo, recognised by its position (a time window would also swallow a real user scroll)
    }
    function isEcho() { var e = P.expect; if (!e) return false; P.expect = null; return Math.abs(wrap.scrollLeft - e.l) <= 1 && Math.abs(wrap.scrollTop - e.t) <= 1; }
    function emit() { if (opts.onView) opts.onView(view()); }
    function go(n, user) {
      if (!P.doc) return;
      n = Math.max(1, Math.min(P.doc.numPages, Math.round(n) || 1));
      if (n === P.page) return;
      P.page = n; render(); if (user) emit();
    }
    function zoomTo(z, user) {
      z = Math.max(0.25, Math.min(6, Math.round(z * 100) / 100));
      if (z === P.zoom && !user) return;
      P.zoom = z; render(); if (user) emit();
    }
    function labels() {
      pageLbl.textContent = P.doc ? 'Page ' + P.page + ' of ' + P.doc.numPages : '';
      zoomLbl.textContent = P.doc ? Math.round(P.zoom * 100) + '%' : '';
      prev.disabled = !P.doc || P.page <= 1; next.disabled = !P.doc || P.page >= P.doc.numPages;
      btns.forEach(function (b) { if (b !== prev && b !== next) b.disabled = !P.ready; });
    }
    function render() {
      if (!P.doc) { labels(); return; }
      if (P.rendering) { P.again = true; return; }
      P.rendering = true;
      var doc = P.doc, n = P.page;
      doc.getPage(n).then(function (pg) {
        if (doc !== P.doc) { P.rendering = false; return; }
        var v1 = pg.getViewport({ scale: 1 }), aw = Math.max(80, wrap.clientWidth - 24), ah = Math.max(80, wrap.clientHeight - 24);
        var fitScale = Math.min(aw / v1.width, ah / v1.height) || 1, scale = fitScale * P.zoom, dpr = Math.min(window.devicePixelRatio || 1, 2);
        var vp = pg.getViewport({ scale: scale * dpr });
        paper.width = Math.floor(vp.width); paper.height = Math.floor(vp.height);
        paper.style.width = Math.floor(vp.width / dpr) + 'px'; paper.style.height = Math.floor(vp.height / dpr) + 'px';
        var ctx = paper.getContext('2d');
        ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, paper.width, paper.height);
        P.task = pg.render({ canvasContext: ctx, viewport: vp });
        return P.task.promise.then(function () { P.task = null; });
      }).catch(function (e) { if (e && e.name === 'RenderingCancelledException') return; message('error', 'The page could not be drawn', (e && e.message) || ''); })
        .then(function () {
          P.rendering = false; labels();
          if (P.again) { P.again = false; render(); return; }
          if (P.pend) { var pv = P.pend; P.pend = null; applyScroll(pv); }
          marker.reposition();
          if (opts.onRendered) opts.onRendered();
        });
    }
    function release() {
      if (P.task) { try { P.task.cancel(); } catch (e) { /* ignore */ } P.task = null; }
      if (P.doc && P.doc.destroy) { try { P.doc.destroy(); } catch (e) { /* ignore */ } }
      P.doc = null; P.ready = false; P.rendering = false; P.again = false;
      try { var c = paper.getContext('2d'); c.clearRect(0, 0, paper.width, paper.height); } catch (e) { /* ignore */ }
      paper.width = paper.height = 0;
    }
    function message(kind, title, text, retry) {
      wrap.hidden = kind !== 'ready'; box.hidden = kind === 'ready';
      box.replaceChildren();
      if (kind === 'ready') { labels(); return; }
      if (kind === 'loading') box.append(h('span', { class: 'rv-spin' }, icon('spinner', 24)), h('p', { class: 'empty-t', text: title || 'Loading...' }));
      else if (kind === 'error') box.append(icon('warn', 26), h('p', { class: 'empty-t', text: title || 'The PDF could not be shown' }), text ? h('p', { class: 'empty-d', text: text }) : null,
        retry ? h('button', { class: 'btn secondary sm', type: 'button', text: 'Retry', onclick: retry }) : null);
      else box.append(icon('file', 28), h('p', { class: 'empty-t', text: title || 'Nothing to show' }), text ? h('p', { class: 'empty-d', text: text }) : null);
      box.setAttribute('data-kind', kind);
      labels();
    }
    function clear() { P.token++; release(); P.key = ''; P.page = 1; P.zoom = 1; P.pend = null; marker.set(null); message('empty', 'Nothing to show', ''); }
    function load(url, key, start) {
      var lib = typeof pdfjsLib !== 'undefined' ? pdfjsLib : null;
      var tokn = ++P.token;
      release(); P.key = ''; P.page = 1; P.zoom = 1;
      if (!lib) { message('error', 'The PDF reader did not load', ''); return Promise.resolve(false); }
      if (lib.GlobalWorkerOptions) lib.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.js';
      message('loading', 'Loading ' + (opts.label || 'PDF') + '...');
      var task = lib.getDocument(url);
      return task.promise.then(function (doc) {
        if (tokn !== P.token) { try { doc.destroy(); } catch (e) { /* ignore */ } return false; }     // a newer load or clear won: this document is stale
        P.doc = doc; P.key = key || url; P.ready = true; P.pend = null; marker.set(null);
        P.page = start && start.page ? Math.max(1, Math.min(doc.numPages, start.page)) : 1;
        P.zoom = start && start.zoom ? Math.max(0.25, Math.min(6, start.zoom)) : 1;
        message('ready'); render();
        return true;
      }, function (e) {
        if (tokn !== P.token) return false;
        message('error', 'The PDF could not be read', (e && e.message) || 'unknown error', function () { load(url, key, start); });
        return false;
      });
    }
    // drag to pan (pointer capture; keyboard scrolling comes from the focusable region)
    var drag = null;
    wrap.addEventListener('pointerdown', function (e) {
      if (e.button !== 0 || (wrap.scrollWidth <= wrap.clientWidth && wrap.scrollHeight <= wrap.clientHeight)) return;
      drag = { x: e.clientX, y: e.clientY, l: wrap.scrollLeft, t: wrap.scrollTop, id: e.pointerId };
      try { wrap.setPointerCapture(e.pointerId); } catch (er) { /* ignore */ }
      wrap.classList.add('is-panning');
    });
    wrap.addEventListener('pointermove', function (e) { if (!drag) return; wrap.scrollLeft = drag.l - (e.clientX - drag.x); wrap.scrollTop = drag.t - (e.clientY - drag.y); });
    function endDrag() { if (drag) { drag = null; wrap.classList.remove('is-panning'); } }
    var scrollQ = false;
    wrap.addEventListener('scroll', function () {
      if (!opts.onView || scrollQ || !P.doc || isEcho()) return;
      scrollQ = true;
      requestAnimationFrame(function () { scrollQ = false; if (P.doc) emit(); });
    }, { passive: true });
    wrap.addEventListener('pointerup', endDrag); wrap.addEventListener('pointercancel', endDrag);
    wrap.addEventListener('keydown', function (e) {
      if (!P.doc || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === 'PageDown') { e.preventDefault(); go(P.page + 1, true); } else if (e.key === 'PageUp') { e.preventDefault(); go(P.page - 1, true); }
      else if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomTo(P.zoom + 0.25, true); } else if (e.key === '-') { e.preventDefault(); zoomTo(P.zoom - 0.25, true); } else if (e.key === '0') { e.preventDefault(); zoomTo(1, true); }
    });
    var ro = null;
    if (typeof ResizeObserver !== 'undefined') { ro = new ResizeObserver(function () { if (P.doc && wrap.offsetParent) render(); }); ro.observe(wrap); }
    message('empty', 'Nothing to show', '');
    return {
      el: el, tools: tools, load: load, clear: clear, message: message, getView: view, numPages: function () { return P.doc ? P.doc.numPages : 0; }, isReady: function () { return P.ready; },
      key: function () { return P.key; }, resize: function () { if (P.doc) render(); },
      setView: function (v) {
        if (!P.doc || !v) return;
        var pg = Math.max(1, Math.min(P.doc.numPages, Math.round(v.page) || 1)); var z = Math.max(0.25, Math.min(6, v.zoom || 1));
        var hasScroll = typeof v.sx === 'number' || typeof v.sy === 'number';
        if (pg === P.page && z === P.zoom) { if (hasScroll) applyScroll(v); return; }
        P.page = pg; P.zoom = z; if (hasScroll) P.pend = { sx: v.sx, sy: v.sy }; render();
      },
      canvas: function () { return paper; }, wrap: function () { return wrap; }, isIdle: function () { return !!P.doc && !P.rendering && !P.again; }, doc: function () { return P.doc; },
      mark: function (box, label) { marker.set(box, label); }, markBox: function () { return marker.box(); },
      locate: function (page, text) { return McA.pdfpane.locateIn(P.doc, page, text); },
      destroy: function () { P.token++; release(); if (ro) ro.disconnect(); }
    };
  }
  /** A highlight rectangle over a sheet canvas, inside its scrolling wrapper (so it scrolls with the sheet and follows zoom). box = {x0,y0,x1,y1} page fractions. */
  function attachMark(wrap, paper) {
    var el = h('div', { class: 'rv-mark', 'aria-hidden': 'true', hidden: true }), cur = null;
    wrap.appendChild(el);
    function reposition() {
      if (!cur) { el.hidden = true; return; }
      var w = paper.offsetWidth, hh = paper.offsetHeight;
      if (!w || !hh) { el.hidden = true; return; }
      el.hidden = false;
      el.style.left = Math.round(paper.offsetLeft + cur.x0 * w - 3) + 'px'; el.style.top = Math.round(paper.offsetTop + cur.y0 * hh - 3) + 'px';
      el.style.width = Math.max(10, Math.round((cur.x1 - cur.x0) * w + 6)) + 'px'; el.style.height = Math.max(10, Math.round((cur.y1 - cur.y0) * hh + 6)) + 'px';
    }
    return {
      el: el, reposition: reposition, box: function () { return cur; },
      set: function (box, scroll) {
        cur = box || null; reposition();
        if (cur && scroll && !el.hidden) { try { el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'auto' }); } catch (e) { /* ignore */ } }
      }
    };
  }
  /** Where `text` sits on page `page` of a pdf.js document, as page fractions, or null (not found, or the page has no text layer). */
  function locateIn(doc, page, text) {
    if (!doc || !text || !McA.compareview) return Promise.resolve(null);
    var n = Math.max(1, Math.min(doc.numPages, Math.round(page) || 1));
    return doc.getPage(n).then(function (pg) {
      var vp = pg.getViewport({ scale: 1 });
      if (vp.rotation) return null;
      return pg.getTextContent().then(function (tc) { return McA.compareview.locateText(tc.items, { width: vp.width, height: vp.height, scale: 1, transform: vp.transform }, text); });
    }).catch(function () { return null; });
  }
  McA.pdfpane = { create: create, attachMark: attachMark, locateIn: locateIn };
})();
