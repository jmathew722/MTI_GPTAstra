/* McA.markup: reference regions, datums, origin and the composited marked view (focus overlay, Mark mode).
   Ported from index.legacy.html (REGION_PALETTE ... saveMarkedViewNow). Coordinates are normalized 0..1 of the
   drawing; boxes sharing a color form one feature group. Every change autosaves (600 ms debounce) through
   POST /api/parts/{s}/{p}/regions and the marked view through POST .../marked-view. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var $ = function (id) { return document.getElementById(id); };
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var store = function () { return McA.store; };

  /* Group colors are persisted user data (the saved JSON carries the hex), so they stay a constant here. */
  var REGION_PALETTE = [
    { hex: '#E5484D', label: 'red' }, { hex: '#F76B15', label: 'orange' },
    { hex: '#D9A514', label: 'amber' }, { hex: '#7CB342', label: 'lime' },
    { hex: '#1B7F3B', label: 'green' }, { hex: '#12A594', label: 'teal' },
    { hex: '#00A2C7', label: 'cyan' }, { hex: '#0090FF', label: 'azure' },
    { hex: '#3E63DD', label: 'indigo' }, { hex: '#6E56CF', label: 'violet' },
    { hex: '#AB4ABA', label: 'purple' }, { hex: '#E93D82', label: 'pink' },
    { hex: '#8E5B3C', label: 'brown' }, { hex: '#64748B', label: 'slate' },
    { hex: '#1F2937', label: 'charcoal' }
  ];
  var REGION_ROLES = ['center', 'x-dimension', 'y-dimension', 'tolerance', 'other'];
  var DATUM_KINDS = [['origin', 'Origin (0,0)'], ['datum_a', 'Datum A'], ['datum_b', 'Datum B'], ['datum_c', 'Datum C'], ['datum_hole', 'Datum hole']];
  var INTAKE_KEY = '__intake__';
  var GLYPH = { origin: '0,0', datum_a: 'A', datum_b: 'B', datum_c: 'C', datum_hole: '⌀' };

  var M = { regions: {}, origin: {}, datums: {}, dirty: {} };
  var tool = 'draw';                       // draw | datum | pan
  var color = REGION_PALETTE[0].hex, role = 'center', datumKind = 'origin';
  var z = { s: 1, tx: 0, ty: 0 };
  var draw = null, resize = null, pan = null;
  var saveTimer = null, savingNow = false, imgKey = null, imgBust = Date.now();
  var box, img, layer, emptyEl, bodyEl;

  function S() { return store().get(); }
  function esc(v) { return McA.util.esc(v); }
  function glyph(k) { return GLYPH[k] || '•'; }
  function datumName(k) { for (var i = 0; i < DATUM_KINDS.length; i++) if (DATUM_KINDS[i][0] === k) return DATUM_KINDS[i][1]; return k; }
  function groupLabel(hex) {
    for (var i = 0; i < REGION_PALETTE.length; i++) if (REGION_PALETTE[i].hex.toLowerCase() === String(hex).toLowerCase()) return 'Group ' + (i + 1) + ' · ' + REGION_PALETTE[i].label;
    return String(hex);
  }

  /* The key regions belong to: the draft while the markup image comes from the draft, else the selected part. */
  function usingDraft() {
    var it = S().intake;
    return it.items.some(function (i) { return i.orientation === 'overview'; }) || !!it.source;
  }
  function ctxKey() {
    if (usingDraft()) return INTAKE_KEY;
    var sel = S().parts.selected;
    return sel ? sel.part : INTAKE_KEY;
  }
  function list(k) { k = k || ctxKey(); return M.regions[k] || (M.regions[k] = []); }
  function datums(k) { k = k || ctxKey(); return M.datums[k] || (M.datums[k] = []); }
  function origin(k) { return M.origin[k || ctxKey()] || null; }
  function sessionFor(key) {
    var sel = S().parts.selected;
    return sel && sel.part === key ? sel.session : S().session.id;
  }
  function groups(regions) {
    var order = [], by = {};
    regions.forEach(function (r) { if (!by[r.color]) { by[r.color] = []; order.push(r.color); } by[r.color].push(r); });
    return order.map(function (c) { return { color: c, label: groupLabel(c), regions: by[c] }; });
  }

  /* ── Image and geometry ──────────────────────────────────────────────── */
  function drawingURL() {
    var s = S(), it = s.intake, ov = null;
    for (var i = 0; i < it.items.length; i++) if (it.items[i].orientation === 'overview') { ov = it.items[i]; break; }
    if (ov && ov.dataURL) return ov.dataURL;
    if (it.source) return it.source;
    var sel = s.parts.selected;
    return sel ? McA.api.overviewURL(sel.session, sel.part, imgBust) : null;
  }
  function updateImage() {
    var url = drawingURL();
    imgKey = ctxKey();
    if (!url) { img.hidden = true; emptyEl.hidden = false; img.removeAttribute('src'); syncLayer(); return; }
    img.onload = function () { img.hidden = false; emptyEl.hidden = true; fitView(); };
    img.onerror = function () { img.hidden = true; emptyEl.hidden = false; emptyEl.textContent = 'The drawing could not be loaded.'; syncLayer(); };
    emptyEl.textContent = 'No drawing loaded yet. Upload a drawing or select a saved part, then mark regions here.';
    img.src = url;
  }
  function contentRect() {
    if (img.hidden || !img.naturalWidth) return null;
    var bw = box.clientWidth, bh = box.clientHeight, nw = img.naturalWidth, nh = img.naturalHeight;
    var k = Math.min(bw / nw, bh / nh), w = nw * k, hh = nh * k;
    return { left: (bw - w) / 2, top: (bh - hh) / 2, width: w, height: hh };
  }
  function applyT() {
    var t = 'translate(' + z.tx + 'px,' + z.ty + 'px) scale(' + z.s + ')';
    img.style.transform = t; layer.style.transform = t;
  }
  function syncLayer() {
    var r = contentRect();
    layer.hidden = !r;
    if (r) { layer.style.left = r.left + 'px'; layer.style.top = r.top + 'px'; layer.style.width = r.width + 'px'; layer.style.height = r.height + 'px'; }
    applyT();
  }
  function fitView() { z.s = 1; z.tx = 0; z.ty = 0; syncLayer(); renderAll(false); }
  function zoomAt(f, cx, cy) {
    var s2 = Math.min(12, Math.max(0.2, z.s * f)); if (s2 === z.s) return;
    var r = box.getBoundingClientRect();
    var mx = cx - (r.left + r.width / 2), my = cy - (r.top + r.height / 2), k = s2 / z.s;
    z.tx = mx - k * (mx - z.tx); z.ty = my - k * (my - z.ty); z.s = s2; applyT();
  }
  function layerPoint(ev) {
    var r = layer.getBoundingClientRect();           // post-transform, so zoom-proof
    if (!r.width || !r.height) return null;
    return { x: Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height)) };
  }

  /* ── Rendering ───────────────────────────────────────────────────────── */
  function renderBoxes() {
    layer.querySelectorAll('.mark-box, .origin-mark, .datum-mark').forEach(function (n) { n.remove(); });
    var drawing = tool === 'draw', placing = tool === 'datum';
    list().forEach(function (r) {
      var bb = r.boundingBox;
      var el = h('div', { class: 'mark-box', 'data-id': r.id });
      el.style.left = (bb.x * 100) + '%'; el.style.top = (bb.y * 100) + '%';
      el.style.width = (bb.width * 100) + '%'; el.style.height = (bb.height * 100) + '%';
      el.style.borderColor = r.color; el.style.background = r.color + '2E';
      if (drawing) {
        var del = h('button', { type: 'button', class: 'mb-del', title: 'Delete this region', 'aria-label': 'Delete region' , text: '×' });
        del.addEventListener('pointerdown', function (e) { e.stopPropagation(); });
        del.addEventListener('click', function (e) { e.stopPropagation(); deleteRegion(r.id); });
        var rs = h('span', { class: 'mb-resize', title: 'Drag to resize' });
        rs.style.background = r.color;
        rs.addEventListener('pointerdown', function (e) { beginResize(e, r.id); });
        el.append(del, rs);
      }
      layer.append(el);
    });
    var o = origin();
    if (o) {
      var om = h('div', { class: 'origin-mark' }, h('span', { class: 'oh' }), h('span', { class: 'ov' }), h('span', { class: 'odot' }),
        h('span', { class: 'olabel', text: '0,0' + (o.locked ? ' locked' : '') }));
      om.style.left = (o.x * 100) + '%'; om.style.top = (o.y * 100) + '%';
      if (placing && !o.locked) {
        var od = h('button', { type: 'button', class: 'odel', title: 'Remove origin', 'aria-label': 'Remove origin', text: '×' });
        od.addEventListener('pointerdown', function (e) { e.stopPropagation(); });
        od.addEventListener('click', function (e) { e.stopPropagation(); delete M.origin[ctxKey()]; changed(); });
        om.append(od);
      }
      layer.append(om);
    }
    datums().forEach(function (dm) {
      var el = h('div', { class: 'datum-mark' }, h('span', { class: 'dm-dot' }), h('span', { class: 'dm-lab', text: glyph(dm.kind) }));
      el.style.left = (dm.x * 100) + '%'; el.style.top = (dm.y * 100) + '%';
      if (placing) {
        var dd = h('button', { type: 'button', class: 'dm-del', title: 'Remove ' + datumName(dm.kind), 'aria-label': 'Remove ' + datumName(dm.kind), text: '×' });
        dd.addEventListener('pointerdown', function (e) { e.stopPropagation(); });
        dd.addEventListener('click', function (e) {
          e.stopPropagation();
          M.datums[ctxKey()] = datums().filter(function (d) { return d.id !== dm.id; }); changed();
        });
        el.append(dd);
      }
      layer.append(el);
    });
    var lock = $('origin-lock');
    lock.hidden = !o;
    lock.textContent = o && o.locked ? 'Locked' : 'Unlocked';
    lock.classList.toggle('on', !!(o && o.locked));
    lock.setAttribute('aria-pressed', String(!!(o && o.locked)));
  }

  function fmt3(n) { return Number(n).toFixed(3); }
  function renderPanel() {
    var regions = list(), o = origin(), ds = datums();
    $('regions-count').textContent = regions.length ? regions.length + ' region' + (regions.length === 1 ? '' : 's') + ', ' + groups(regions).length + ' group' + (groups(regions).length === 1 ? '' : 's') : '';
    $('mark-clear').hidden = !regions.length;
    bodyEl.replaceChildren();
    bodyEl.append(o
      ? h('div', { class: 'rg-origin set', text: 'Origin datum ' + (o.locked ? '(locked)' : '(unlocked)') + ' at (' + fmt3(o.x) + ', ' + fmt3(o.y) + '). The fixed (0,0) for model orientation: bottom-left of the top view.' })
      : h('div', { class: 'rg-origin', text: 'Origin not set. Choose Origin (0,0), turn on Place datum, then click the bottom-left corner of the top view so every model shares the drawing\'s orientation.' }));
    if (ds.length) {
      var wrap = h('div', { class: 'rg-datums' }, h('div', { class: 'rg-datums-t', text: 'Datum reference points' }));
      ds.forEach(function (d) {
        var val = h('input', { class: 'input-c dm-val', placeholder: 'value (e.g. ⌀.406)', 'aria-label': 'Value of ' + datumName(d.kind), value: d.value || '' });
        val.value = d.value || '';
        val.addEventListener('change', function () { d.value = val.value; changed(); });
        var rm = h('button', { type: 'button', class: 'rg-del', title: 'Remove this datum', 'aria-label': 'Remove ' + datumName(d.kind), text: '×' });
        rm.addEventListener('click', function () { M.datums[ctxKey()] = datums().filter(function (x) { return x.id !== d.id; }); changed(); });
        wrap.append(h('div', { class: 'rg-drow' }, h('span', { class: 'dm-chip', text: glyph(d.kind) }), h('span', { text: datumName(d.kind) }), val,
          h('span', { class: 'rg-coords', text: '(' + fmt3(d.x) + ', ' + fmt3(d.y) + ')' }), rm));
      });
      bodyEl.append(wrap);
    }
    if (!regions.length) {
      bodyEl.append(h('div', { class: 'ms-empty' }, h('p', { text: 'No regions marked yet.' }),
        h('p', { text: 'Pick a group color and a role in the toolbar, then drag on the drawing to highlight a dimension callout, a hole center, or an offset dimension line. All boxes of one color form one feature group.' })));
      return;
    }
    var f = function (n) { return Number(n).toFixed(3).replace(/^0/, ''); };
    groups(regions).forEach(function (g) {
      var sw = h('span', { class: 'mark-swatch' }); sw.style.background = g.color;
      var grp = h('div', { class: 'rg-group' }, h('div', { class: 'rg-head' }, sw, h('span', { text: g.label }), h('span', { class: 'grow' }),
        h('span', { class: 'hint', text: g.regions.length + (g.regions.length === 1 ? ' region' : ' regions') })));
      g.regions.forEach(function (r) {
        var rsel = h('select', { class: 'input-c rg-role', 'aria-label': 'Role of this box' }, REGION_ROLES.map(function (ro) { return h('option', { value: ro, text: ro }); }));
        rsel.value = r.role;
        rsel.addEventListener('change', function () { r.role = rsel.value; changed(); });
        var val = h('input', { class: 'input-c rg-val', placeholder: 'value, e.g. 2.500 ± .005', 'aria-label': 'Value of this region', value: r.value || '' });
        val.value = r.value || '';
        val.addEventListener('change', function () { r.value = val.value; changed(); });
        var rm = h('button', { type: 'button', class: 'rg-del', title: 'Delete this region', 'aria-label': 'Delete this region', text: '×' });
        rm.addEventListener('click', function () { deleteRegion(r.id); });
        var bb = r.boundingBox;
        grp.append(h('div', { class: 'rg-row' }, rsel, val, rm,
          h('span', { class: 'rg-coords', text: 'x ' + f(bb.x) + ' · y ' + f(bb.y) + ' · w ' + f(bb.width) + ' · h ' + f(bb.height) })));
      });
      bodyEl.append(grp);
    });
  }

  function renderTool() {
    window.__markOn = tool !== 'pan';
    layer.classList.toggle('marking', tool !== 'pan');
    $('mark-toggle').classList.toggle('on', tool === 'draw'); $('mark-toggle').setAttribute('aria-pressed', String(tool === 'draw'));
    $('origin-toggle').classList.toggle('on', tool === 'datum'); $('origin-toggle').setAttribute('aria-pressed', String(tool === 'datum'));
    $('mark-hint').textContent = tool === 'datum' ? 'Datum mode: click the drawing to place the chosen datum. Origin goes at the bottom-left of the top view; lock it when set.'
      : tool === 'draw' ? 'Drag to draw. Corner handle resizes, the cross deletes. Boxes sharing a color form one feature group.'
      : 'Tools off: drag pans the drawing, scroll zooms. Turn on Draw or Place datum to mark.';
    box.classList.toggle('is-pan', tool === 'pan');
    renderBoxes();
  }

  function renderSaveState() {
    var st = S().markup.saveState, el = $('mark-save-state'), k = ctxKey();
    var txt = '', cls = '';
    var hasData = list(k).length || origin(k) || datums(k).length;
    if (k === INTAKE_KEY) txt = hasData ? 'Not saved yet. Regions are stored when you save the part.' : '';
    else if (st === 'saving') txt = 'Saving…';
    else if (st === 'saved') { txt = 'Saved'; cls = ' is-ok'; }
    else if (st === 'error') { txt = 'Save failed. It retries on the next change.'; cls = ' is-err'; }
    el.className = 'focus-save' + cls; el.textContent = txt;
  }

  function renderAll(save) {
    renderBoxes(); renderPanel();
    var add = $('mark-addview'), has = !!contentRect();
    add.disabled = !has; add.title = has ? 'Add this marked drawing to Part Setup as a Marked View' : 'No drawing loaded';
    if (save) { markDirty(ctxKey()); scheduleSave(); }
    renderSaveState();
  }
  function changed() { renderAll(true); }

  /* ── Region edits ────────────────────────────────────────────────────── */
  function deleteRegion(id) { M.regions[ctxKey()] = list().filter(function (r) { return r.id !== id; }); changed(); }
  function beginResize(ev, id) {
    ev.stopPropagation(); ev.preventDefault();
    var r = list().filter(function (x) { return x.id === id; })[0]; if (!r) return;
    resize = { region: r };
    layer.setPointerCapture(ev.pointerId);
  }
  function uid(p) { return p + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }

  function onLayerDown(ev) {
    if (ev.button !== 0 || ev.target !== layer) return;
    var p = layerPoint(ev); if (!p) return;
    if (tool === 'datum') {
      var kind = datumKind || 'origin';
      if (kind === 'origin') {
        var cur = origin();
        if (cur && cur.locked) { McA.toast.show('The origin is locked. Unlock it to move it.', 'warn'); return; }
        M.origin[ctxKey()] = { x: p.x, y: p.y, locked: false, view: 'top' };
      } else {
        var l = datums();
        if (kind !== 'datum_hole') { var i = -1; l.forEach(function (d, ix) { if (d.kind === kind) i = ix; }); if (i >= 0) l.splice(i, 1); }
        l.push({ id: uid('dm'), x: p.x, y: p.y, kind: kind, value: '' });
      }
      changed(); return;
    }
    if (tool !== 'draw') return;
    var region = { id: uid('rg'), color: color, colorLabel: groupLabel(color), role: role || 'other',
      boundingBox: { x: p.x, y: p.y, width: 0, height: 0 }, value: '', createdAt: new Date().toISOString() };
    draw = { region: region, ax: p.x, ay: p.y };
    list().push(region);
    layer.setPointerCapture(ev.pointerId);
    renderBoxes(); ev.preventDefault();
  }
  function onLayerMove(ev) {
    var st = draw || resize; if (!st) return;
    var p = layerPoint(ev); if (!p) return;
    var bb = st.region.boundingBox;
    if (draw) { bb.x = Math.min(st.ax, p.x); bb.y = Math.min(st.ay, p.y); bb.width = Math.abs(p.x - st.ax); bb.height = Math.abs(p.y - st.ay); }
    else { bb.width = Math.max(0.004, p.x - bb.x); bb.height = Math.max(0.004, p.y - bb.y); }
    renderBoxes();
  }
  function onLayerUp() {
    if (draw) {
      var bb = draw.region.boundingBox;
      if (bb.width < 0.003 || bb.height < 0.003) { var id = draw.region.id; M.regions[ctxKey()] = list().filter(function (r) { return r.id !== id; }); }
      draw = null; changed();
    } else if (resize) { resize = null; changed(); }
  }

  /* ── Persistence ─────────────────────────────────────────────────────── */
  function markDirty(k) { M.dirty[k] = true; store().dispatch('markup/set', { dirty: Object.keys(M.dirty) }); }
  function setSave(v) { store().dispatch('markup/set', { saveState: v }); }
  function scheduleSave() { if (saveTimer) clearTimeout(saveTimer); saveTimer = setTimeout(saveNow, 600); }
  function saveNow() {
    saveTimer = null;
    var keys = Object.keys(M.dirty).filter(function (k) { return k !== INTAKE_KEY; });
    if (!keys.length) { renderSaveState(); return Promise.resolve(); }
    if (!S().session.id) return Promise.resolve();
    setSave('saving');
    return Promise.all(keys.map(function (k) {
      var session = sessionFor(k);
      var body = { regions: M.regions[k] || [], origin: M.origin[k] || null, datums: M.datums[k] || [] };
      return McA.api.saveRegions(session, k, body).then(function () {
        delete M.dirty[k]; saveMarkedView(session, k); return true;
      }, function () { return false; });
    })).then(function (rs) {
      store().dispatch('markup/set', { dirty: Object.keys(M.dirty), saveState: rs.every(Boolean) ? 'saved' : 'error' });
      if (!rs.every(Boolean)) McA.toast.show('Could not save the marked regions. They will be retried on the next change.', 'err');
    });
  }

  function hexToRgba(hex, a) {
    var m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return tk('--ink-3');
    var n = parseInt(m[1], 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  }
  function tk(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function buildCanvas(regions, org, dts) {
    if (!img || img.hidden || !img.naturalWidth) return null;
    var W = img.naturalWidth, H = img.naturalHeight;
    var c = document.createElement('canvas'); c.width = W; c.height = H;
    var ctx = c.getContext('2d');
    try { ctx.drawImage(img, 0, 0, W, H); } catch (e) { return null; }
    var lw = Math.max(2, Math.round(Math.max(W, H) / 700));
    var datum = tk('--datum'), outline = tk('--well');
    regions.forEach(function (r) {
      var bb = r.boundingBox, x = bb.x * W, y = bb.y * H, w = bb.width * W, hh = bb.height * H;
      ctx.fillStyle = hexToRgba(r.color, 0.18); ctx.fillRect(x, y, w, hh);
      ctx.lineWidth = lw; ctx.strokeStyle = r.color; ctx.strokeRect(x, y, w, hh);
    });
    if (org) {
      var ox = org.x * W, oy = org.y * H, L = Math.max(16, Math.round(Math.max(W, H) / 38));
      ctx.strokeStyle = datum; ctx.lineWidth = Math.max(2, lw);
      ctx.beginPath(); ctx.moveTo(ox - L, oy); ctx.lineTo(ox + L, oy); ctx.moveTo(ox, oy - L); ctx.lineTo(ox, oy + L); ctx.stroke();
      ctx.fillStyle = datum; ctx.beginPath(); ctx.arc(ox, oy, Math.max(3, lw * 1.6), 0, 6.29); ctx.fill();
      ctx.font = '700 ' + Math.max(12, Math.round(W / 85)) + 'px sans-serif';
      ctx.fillText('(0,0)', ox + L + 3, oy - 5);
    }
    (dts || []).forEach(function (d) {
      var dx = d.x * W, dy = d.y * H, R = Math.max(6, Math.round(Math.max(W, H) / 90));
      ctx.fillStyle = datum; ctx.beginPath(); ctx.arc(dx, dy, R, 0, 6.29); ctx.fill();
      ctx.strokeStyle = outline; ctx.lineWidth = Math.max(1, lw - 1); ctx.beginPath(); ctx.arc(dx, dy, R, 0, 6.29); ctx.stroke();
      ctx.fillStyle = outline; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.font = '700 ' + Math.max(10, Math.round(R * 1.2)) + 'px sans-serif';
      ctx.fillText(glyph(d.kind), dx, dy + 1);
      ctx.textAlign = 'start'; ctx.textBaseline = 'alphabetic';
    });
    return c;
  }
  function composeDataURL() {
    var k = ctxKey(), c = buildCanvas(list(k), origin(k), datums(k));
    try { return c ? c.toDataURL('image/jpeg', 0.92) : null; } catch (e) { return null; }
  }
  /* Keeps full_marked_view.jpg in sync. The server drops a stale marked view when everything is cleared. */
  function saveMarkedView(session, k, retried) {
    var regions = M.regions[k] || [], org = M.origin[k] || null, dts = M.datums[k] || [];
    if (!regions.length && !org && !dts.length) return;
    if (imgKey !== k) return;                 // the loaded image belongs to another context
    var c = buildCanvas(regions, org, dts);
    if (!c) { if (!retried) setTimeout(function () { saveMarkedView(session, k, true); }, 500); return; }
    try {
      c.toBlob(function (blob) {
        if (!blob) return;
        McA.api.saveMarkedView(session, k, new File([blob], 'full_marked_view.jpg', { type: 'image/jpeg' })).then(function () {
          if (McA.boot && McA.boot.refreshParts) McA.boot.refreshParts();   // has_marked drives the Overview / Marked switch
        }, function () { /* the next change retries */ });
      }, 'image/jpeg', 0.92);
    } catch (e) { /* tainted canvas: skip */ }
  }

  function loadRegionsFor(sel) {
    if (!sel) return;
    var name = sel.part;
    if (M.dirty[name]) { renderAll(false); return; }
    McA.api.getRegions(sel.session, name).then(function (d) {
      if (M.dirty[name]) return;
      M.regions[name] = d.regions || []; M.origin[name] = d.origin || undefined; M.datums[name] = d.datums || [];
      renderAll(false);
    }, function () { M.regions[name] = M.regions[name] || []; });
  }

  /* ── Public helpers used by intake.js ────────────────────────────────── */
  function transferIntake(part) {
    var r = M.regions[INTAKE_KEY] || [], o = M.origin[INTAKE_KEY], d = M.datums[INTAKE_KEY] || [];
    if (!r.length && !o && !d.length) return;
    if (r.length) M.regions[part] = r;
    if (o) M.origin[part] = o;
    if (d.length) M.datums[part] = d;
    clearIntake();
    imgKey = part;
    markDirty(part); scheduleSave();
  }
  function clearIntake() {
    delete M.regions[INTAKE_KEY]; delete M.origin[INTAKE_KEY]; delete M.datums[INTAKE_KEY]; delete M.dirty[INTAKE_KEY];
    store().dispatch('markup/set', { dirty: Object.keys(M.dirty) });
    if (box && !$('mark-view').hidden) renderAll(false);
  }

  McA.markup = {
    REGION_PALETTE: REGION_PALETTE, REGION_ROLES: REGION_ROLES,
    transferIntake: transferIntake, clearIntake: clearIntake, composeDataURL: composeDataURL, flush: saveNow,
    onShow: function () { updateImage(); renderTool(); renderPanel(); renderSaveState(); },
    init: function () {
      var root = $('mark-view');
      var colorSel = h('select', { class: 'input-c', id: 'mark-color', 'aria-label': 'Group color', title: 'Active color: every box drawn with this color belongs to the same feature group' },
        REGION_PALETTE.map(function (p, i) { return h('option', { value: p.hex, text: 'Group ' + (i + 1) + ' · ' + p.label }); }));
      var swatch = h('span', { class: 'mark-swatch', id: 'mark-swatch', 'aria-hidden': 'true' });
      swatch.style.background = color;
      var roleSel = h('select', { class: 'input-c', id: 'mark-role', 'aria-label': 'Role for the next box' }, REGION_ROLES.map(function (r) { return h('option', { value: r, text: r }); }));
      var kindSel = h('select', { class: 'input-c', id: 'datum-kind', 'aria-label': 'Datum kind', title: 'What to place: the (0,0) origin, a lettered datum, or a datum hole' },
        DATUM_KINDS.map(function (k) { return h('option', { value: k[0], text: k[1] }); }));
      var drawBtn = h('button', { class: 'btn secondary sm on', id: 'mark-toggle', type: 'button', 'aria-pressed': 'true', title: 'Draw mode: drag to draw a highlight box over a dimension callout, hole center or offset dimension' }, McA.icons.get('mark', 16), 'Draw');
      var datumBtn = h('button', { class: 'btn secondary sm', id: 'origin-toggle', type: 'button', 'aria-pressed': 'false', title: 'Place a reference datum: choose the kind, then click the drawing' }, McA.icons.get('pan', 16), 'Place datum');
      var lock = h('button', { class: 'btn secondary sm', id: 'origin-lock', type: 'button', hidden: true, 'aria-pressed': 'false', title: 'Lock or unlock the origin so it cannot be moved by accident', text: 'Unlocked' });
      var add = h('button', { class: 'btn secondary sm', id: 'mark-addview', type: 'button', disabled: true, text: 'Add to Part Setup' });
      var clr = h('button', { class: 'btn danger sm', id: 'mark-clear', type: 'button', hidden: true, title: 'Delete every marked region for this part', text: 'Clear regions' });
      var bar = h('div', { class: 'mark-bar', role: 'toolbar', 'aria-label': 'Markup tools' }, drawBtn, datumBtn, kindSel, lock,
        h('span', { class: 'mb-sep', 'aria-hidden': 'true' }), h('span', { text: 'Group color' }), swatch, colorSel,
        h('span', { class: 'mb-sep', 'aria-hidden': 'true' }), h('span', { text: 'Role' }), roleSel,
        h('span', { class: 'mb-sep', 'aria-hidden': 'true' }), h('span', { class: 'hint', id: 'mark-hint' }),
        h('span', { class: 'grow' }), add, clr);

      img = h('img', { id: 'mk-img', alt: 'Drawing for region markup', hidden: true });
      layer = h('div', { id: 'ov-mark-layer', class: 'marking' });
      emptyEl = h('div', { class: 'mk-empty', id: 'mk-empty', text: 'No drawing loaded yet. Upload a drawing or select a saved part, then mark regions here.' });
      box = h('div', { id: 'mk-box', tabindex: '0', 'aria-label': 'Markup drawing. Drag to draw boxes with a mouse or pen; edit values in the list.' }, img, layer, emptyEl);
      bodyEl = h('div', { class: 'ms-scroll regions-body', id: 'regions-body' });
      var side = h('aside', { class: 'mark-side', 'aria-label': 'Marked reference regions' },
        h('div', { class: 'ms-head' }, h('span', { text: 'Marked reference regions' }), h('span', { class: 'grow' }), h('span', { class: 'hint', id: 'regions-count' })),
        bodyEl,
        h('div', { class: 'ms-foot', text: 'Boxes sharing a color are one feature group, for example a hole center with its X and Y dimensions. Tag each box\'s role and transcribe its value. Everything saves automatically.' }));
      root.replaceChildren(bar, h('div', { class: 'mark-split' }, box, side));

      colorSel.addEventListener('change', function () { color = colorSel.value; swatch.style.background = color; });
      roleSel.addEventListener('change', function () { role = roleSel.value; });
      kindSel.addEventListener('change', function () { datumKind = kindSel.value; });
      drawBtn.addEventListener('click', function () { tool = tool === 'draw' ? 'pan' : 'draw'; renderTool(); });
      datumBtn.addEventListener('click', function () { tool = tool === 'datum' ? 'pan' : 'datum'; renderTool(); });
      lock.addEventListener('click', function () { var o = origin(); if (!o) return; o.locked = !o.locked; changed(); });
      clr.addEventListener('click', function () {
        var n = list().length; if (!n) return;
        McA.dialog.confirm('Clear all regions?', 'Delete all ' + n + ' marked region' + (n === 1 ? '' : 's') + ' for this part? This autosaves.', 'Clear regions', true).then(function (ok) {
          if (!ok) return; M.regions[ctxKey()] = []; changed();
        });
      });
      add.addEventListener('click', function () {
        var url = composeDataURL();
        if (!url) { McA.toast.show('No drawing loaded to add. Open a drawing first.', 'err'); return; }
        store().dispatch('intake/add', { items: [{ dataURL: url, orientation: 'marked', label: 'Marked drawing' }] });
        McA.cropper.close(true);
        McA.toast.show('Added the marked drawing to Part Setup as a Marked View. Name the part and save.', 'ok');
      });

      layer.addEventListener('pointerdown', onLayerDown);
      layer.addEventListener('pointermove', onLayerMove);
      layer.addEventListener('pointerup', function (e) { if (layer.hasPointerCapture(e.pointerId)) layer.releasePointerCapture(e.pointerId); onLayerUp(); });
      layer.addEventListener('pointercancel', onLayerUp);
      box.addEventListener('wheel', function (e) { if (img.hidden) return; e.preventDefault(); zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY); }, { passive: false });
      box.addEventListener('pointerdown', function (e) {
        if (tool !== 'pan' || img.hidden || e.button !== 0 || e.target.closest('button')) return;
        pan = { x: e.clientX - z.tx, y: e.clientY - z.ty }; box.setPointerCapture(e.pointerId);
      });
      box.addEventListener('pointermove', function (e) { if (!pan) return; z.tx = e.clientX - pan.x; z.ty = e.clientY - pan.y; applyT(); });
      var endPan = function (e) { if (!pan) return; pan = null; if (box.hasPointerCapture(e.pointerId)) box.releasePointerCapture(e.pointerId); };
      box.addEventListener('pointerup', endPan); box.addEventListener('pointercancel', endPan);
      box.addEventListener('dblclick', function (e) { if (tool === 'pan' || e.target === box || e.target === img) fitView(); });
      new ResizeObserver(function () { syncLayer(); }).observe(box);

      var st = store();
      st.subscribe(function (s) { return s.parts.selected; }, function (sel) {
        imgBust = Date.now(); loadRegionsFor(sel);
        if (!$('mark-view').hidden) { updateImage(); renderTool(); renderPanel(); }
      });
      st.subscribe(function (s) { return s.session.id; }, function () { loadRegionsFor(st.get().parts.selected); });
      st.subscribe(function (s) { return s.markup.saveState; }, renderSaveState);
      st.subscribe(function (s) { return s.intake.source; }, function () { if (!$('mark-view').hidden) { updateImage(); renderTool(); renderPanel(); } });
      st.subscribe(function (s) { return s.intake.items.length === 0 && !s.intake.source; }, function (empty) { if (empty) clearIntake(); });
      var sel0 = st.get().parts.selected; if (sel0) loadRegionsFor(sel0);
      renderTool(); renderPanel();
    }
  };
})();
