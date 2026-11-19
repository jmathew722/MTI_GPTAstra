/* McA.engFlags: automatic engineering flags drawn over the drawing, linked to the Results panel (Stage 3).
   The pipeline places every flag; this file only draws what the server validated and lets a person review it.
   Pipeline evidence (this layer, solid red/amber) is visually and structurally separate from the user's own
   manual markup (features/markup.js). All text goes through textContent: nothing here parses HTML. */
(function () {
  'use strict';
  var McA = (window.McA = window.McA || {});
  var FV = McA.flagview;
  var h = function () { return McA.dom.h.apply(null, arguments); };
  var layer = null, box = null, img = null;
  var FILT0 = { severity: [], category: [], feature: '', state: [], location: 'all' };
  var drafts = {};       // unsaved review choices, kept across re-renders so a filter change never loses them
  var STATES = [['open', 'Open'], ['acknowledged', 'Acknowledged'], ['corrected_pending_rerun', 'Corrected, pending re-run'],
                ['dismissed_with_reason', 'Dismissed (with reason)']];
  var STATE_LABEL = { open: 'Open', acknowledged: 'Acknowledged', corrected_pending_rerun: 'Corrected, pending re-run',
                      verified_corrected: 'Verified corrected', dismissed_with_reason: 'Dismissed' };
  var CATS = { feature_not_built: 'Feature not built', feature_unresolved: 'Needs an answer', volume_mismatch: 'Volume mismatch',
               bbox_mismatch: 'Size mismatch', plan_rejected: 'Plan rejected', hole_depth_mismatch: 'Hole depth', hole_diameter_mismatch: 'Hole diameter',
               hole_position_mismatch: 'Hole position', geometry_extra_material: 'Extra material', geometry_missing_material: 'Missing material',
               practice_advisory: 'Practice advisory', extraction_review: 'Extraction review', other: 'Other' };

  function ui() { return McA.store.get().ui || {}; }
  function filters() { return Object.assign({}, FILT0, ui().dflFilter || {}); }
  function flagsModel() {
    var s = McA.store.get(), sel = s.parts.selected, ctx = s.outputs.ctx, p = s.outputs.payload;
    if (!sel || !ctx || ctx.part !== sel.part || !p || !p.categories) return null;
    var f = p.categories.flags;
    return f && f.present ? f : null;
  }
  function selectedId() { return ui().flagSelected || null; }

  /* ── overlay layer over the drawing ─────────────────────────────────────── */
  function showing() {
    var v = McA.viewer2d && McA.viewer2d.getView && McA.viewer2d.getView();
    return !!(v && v.imgOk && v.kind === 'part' && v.view === 'overview' && v.nw > 0);
  }
  function syncTransform(z) {
    if (!layer || !z) return;
    layer.style.transform = 'translate(' + z.tx + 'px,' + z.ty + 'px) scale(' + z.s + ')';
    layer.style.setProperty('--zs', String(z.s));
  }
  /* Selection is shown on the cards without rebuilding the list (so focus and scroll position survive). */
  function markCards() {
    var sel = selectedId();
    document.querySelectorAll('.flagcard').forEach(function (c) {
      if (c.getAttribute('data-finding') === sel) c.setAttribute('aria-current', 'true'); else c.removeAttribute('aria-current');
    });
  }
  function layout() {
    markCards();
    if (!layer) return;
    var m = flagsModel(), v = McA.viewer2d.getView();
    var items = showing() && m ? FV.drawable(m, 0, filters()) : [];
    layer.hidden = !items.length;
    if (!items.length) { layer.replaceChildren(); return; }
    syncTransform(v.z);
    var fit = FV.fitContain(box.clientWidth, box.clientHeight, v.nw, v.nh);
    var list = FV.flagList(m), by = {};
    list.forEach(function (f) { by[f.finding_id] = f; });
    var sel = selectedId();
    var keep = {};
    items.forEach(function (o) {
      var f = by[o.finding_id];
      if (!f) return;
      var key = o.overlay_id;
      keep[key] = true;
      var b = layer.querySelector('[data-ov="' + key + '"]');
      if (!b) {
        b = h('button', { type: 'button', class: 'flag-box', 'data-ov': key, 'data-finding': o.finding_id });
        b.append(h('span', { class: 'flag-badge' }));
        b.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); selectFlag(o.finding_id, { reveal: true, from: 'box' }); });
        b.addEventListener('keydown', onBoxKey);
        layer.append(b);
      }
      var mk = FV.severityMark(o.severity), px = FV.overlayPx(o.rect_normalized, o.rotation_degrees || 0, fit);
      b.style.left = px.left + 'px'; b.style.top = px.top + 'px'; b.style.width = px.width + 'px'; b.style.height = px.height + 'px';
      b.setAttribute('data-sev', o.severity);
      var vis = o.number + ' ' + (o.severity === 'error' ? 'ERR' : o.severity === 'warning' ? 'WARN' : 'INFO');
      b.setAttribute('aria-label', vis + ': ' + f.title + '. ' + mk.label + ' flag. Press Enter for details.');   // starts with the visible text
      b.title = o.number + ': ' + f.title;
      if (o.finding_id === sel) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current');
      var bd = b.firstChild;
      bd.setAttribute('data-shape', mk.shape);
      bd.textContent = vis;
    });
    Array.prototype.slice.call(layer.children).forEach(function (c) { if (!keep[c.getAttribute('data-ov')]) c.remove(); });
  }
  function onBoxKey(e) {
    var m = flagsModel(); if (!m) return;
    var shown = FV.filterFlags(FV.flagList(m), filters()).filter(function (x) { return x.located; });
    var id = e.currentTarget.getAttribute('data-finding'), next = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = FV.neighbor(shown, id, +1);
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = FV.neighbor(shown, id, -1);
    else if (e.key === 'Escape') { selectFlag(null); return; }
    else return;
    e.preventDefault();
    if (next) { selectFlag(next, { from: 'box' }); var t = layer.querySelector('[data-finding="' + next + '"]'); if (t) t.focus(); }
  }

  /* ── selection, linked both ways ─────────────────────────────────────────── */
  function selectFlag(id, opts) {
    opts = opts || {};
    var patch = { flagSelected: id };
    if (id && opts.reveal) { patch.drawerOpen = true; patch.drawerSection = 'flags'; patch.drawerMode = 'results'; }
    McA.dom.setUi(patch);
    if (!id) return;
    var m = flagsModel(); if (!m) return;
    var f = FV.flagList(m).filter(function (x) { return x.finding_id === id; })[0];
    revealIfFiltered(m, id);
    if (opts.from !== 'box' && McA.viewer2d && McA.viewer2d.focusIssue && McA.viewer2d.focusIssue(id)) return;
    if (McA.viewer2d && McA.viewer2d.relayoutMarkup) McA.viewer2d.relayoutMarkup();
    if (f && f.located && opts.from !== 'box') focusOnDrawing(f);
    setTimeout(function () {
      var card = document.querySelector('.flagcard[data-finding="' + id + '"]');
      if (card && opts.from === 'box') { card.scrollIntoView({ block: 'nearest' }); }
    }, 30);
  }
  /* A flag picked on the marked drawing may be hidden by a Results filter: clear the filter and say so. */
  function revealIfFiltered(m, id) {
    var list = FV.flagList(m), shown = FV.filterFlags(list, filters());
    if (shown.some(function (x) { return x.finding_id === id; })) return;
    if (!list.some(function (x) { return x.finding_id === id; })) return;
    McA.dom.setUi({ dflFilter: {} });
    var live = document.getElementById('status-live');
    if (live) live.textContent = 'Filters cleared to show the selected flag.';
  }
  function focusOnDrawing(f) {
    if (!showing() || !f.overlay || f.overlay.page_index !== 0) return;
    var v = McA.viewer2d.getView();
    var fit = FV.fitContain(box.clientWidth, box.clientHeight, v.nw, v.nh);
    var px = FV.overlayPx(f.overlay.rect_normalized, f.overlay.rotation_degrees || 0, fit);
    var t = FV.focusTransform(px, { w: box.clientWidth, h: box.clientHeight }, { min: 0.2, max: 12 });
    McA.viewer2d.setView(t.s, t.tx, t.ty);
  }

  /* ── the Results panel ───────────────────────────────────────────────────── */
  function chipBtn(label, on, fn, cls) {
    var b = h('button', { type: 'button', class: 'fchip ' + (cls || '') + (on ? ' on' : ''), 'aria-pressed': String(on), text: label });
    b.addEventListener('click', fn);
    return b;
  }
  function setFilter(patch) { McA.dom.setUi({ dflFilter: Object.assign({}, filters(), patch) }); }
  function toggled(arr, v) { var a = (arr || []).slice(), i = a.indexOf(v); if (i === -1) a.push(v); else a.splice(i, 1); return a; }
  function optionsSelect(label, value, options, onChange) {
    var sel = h('select', { class: 'select-c sm', 'aria-label': label });
    options.forEach(function (o) { var op = h('option', { value: o[0], text: o[1] }); if (o[0] === value) op.selected = true; sel.append(op); });
    sel.addEventListener('change', function () { onChange(sel.value); });
    return sel;
  }
  function dl(rows) {
    var d = h('dl', { class: 'flag-dl' });
    rows.forEach(function (r) { if (r[1]) d.append(h('dt', { text: r[0] }), h('dd', { text: r[1] })); });
    return d;
  }

  function card(f, d, shown) {
    var mk = FV.severityMark(f.severity), sel = f.finding_id === selectedId();
    var el = h('article', { class: 'flagcard', 'data-finding': f.finding_id, 'data-sev': f.severity, 'data-state': f.state, tabindex: '0',
      'aria-labelledby': 'fc-t-' + f.finding_id, 'aria-current': sel ? 'true' : null });
    el.append(h('header', { class: 'flag-head' },
      h('span', { class: 'flag-sev', 'data-shape': mk.shape }, h('span', { 'aria-hidden': 'true', class: 'flag-shape' }), h('b', { text: mk.text })),
      h('span', { class: 'flag-n mono', text: '#' + f.number }),
      h('h4', { id: 'fc-t-' + f.finding_id, class: 'flag-title', text: f.title }),
      h('span', { class: 'badge-c ' + (f.state === 'open' ? 'warn' : f.state === 'dismissed_with_reason' ? 'mono' : 'ok'), text: STATE_LABEL[f.state] || f.state })));
    el.append(h('p', { class: 'flag-loc ' + (f.located ? '' : 'is-unloc'), text: FV.locationText(f) }));
    el.append(dl([['Expected', f.expected], ['Actual', f.actual], ['Consequence', f.consequence], ['Recommended manual repair', f.recommended_action]]));
    if ((f.source_callouts || []).length || (f.feature_ids || []).length) {
      el.append(h('p', { class: 'flag-src' }, h('b', { text: 'Source: ' }),
        h('span', { class: 'mono', text: [(f.feature_ids || []).join(', '), (f.source_callouts || []).join(' | ')].filter(Boolean).join('  —  ') })));
    }
    var actions = h('div', { class: 'flag-actions' });
    var inMarkup = !!(McA.viewer2d && McA.viewer2d.hasMarkup && McA.viewer2d.hasMarkup(f.finding_id));
    if (f.located || inMarkup) {
      var show = h('button', { type: 'button', class: 'btn secondary sm', text: f.located ? 'Show on drawing' : 'Show on page',
        'aria-label': (f.located ? 'Show on drawing' : 'Show on page') + ' (flag ' + f.number + ')' });   // starts with the visible text
      show.addEventListener('click', function () { selectFlag(f.finding_id, { reveal: false }); });
      actions.append(show);
    } else {
      actions.append(h('span', { class: 'hint flag-nolocation', text: 'Location not confirmed' }));
    }
    actions.append(reviewControls(f, d));
    el.append(actions);
    el.addEventListener('click', function (e) { if (!e.target.closest('button, select, input, textarea, a')) selectFlag(f.finding_id); });
    el.addEventListener('keydown', function (e) {
      if (e.target !== el) return;
      var next = null;
      if (e.key === 'ArrowDown') next = FV.neighbor(shown, f.finding_id, +1);
      else if (e.key === 'ArrowUp') next = FV.neighbor(shown, f.finding_id, -1);
      else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectFlag(f.finding_id); return; }
      else return;
      e.preventDefault();
      selectFlag(next);
      setTimeout(function () { var c = document.querySelector('.flagcard[data-finding="' + next + '"]'); if (c) c.focus(); }, 30);
    });
    return el;
  }

  function reviewControls(f, d) {
    var ctx = d.ctx && d.ctx.kind === 'part' ? d.ctx : null;
    var wrap = h('div', { class: 'flag-review' });
    if (!ctx) return wrap;
    if (f.state === 'verified_corrected') { wrap.append(h('span', { class: 'hint', text: 'Verified: a later run no longer produces this flag.' })); return wrap; }
    var dr = drafts[f.finding_id] || {};
    var cur = dr.state || (f.state === 'verified_corrected' ? 'open' : f.state);
    var sel = optionsSelect('Review state for flag ' + f.number, cur, STATES, function () { remember(); sync(); });
    var reason = h('input', { type: 'text', class: 'input-c sm', placeholder: 'Reason for dismissing', 'aria-label': 'Reason for dismissing flag ' + f.number, maxlength: '500', value: dr.reason !== undefined ? dr.reason : (f.reviewReason || '') });
    reason.addEventListener('input', remember);
    function remember() { drafts[f.finding_id] = { state: sel.value, reason: reason.value }; }
    var save = h('button', { type: 'button', class: 'btn ghost sm', text: 'Save review' });
    var msg = h('span', { class: 'hint', role: 'status' });
    function sync() { reason.hidden = sel.value !== 'dismissed_with_reason'; }
    sync();
    save.addEventListener('click', function () {
      if (sel.value === 'dismissed_with_reason' && !reason.value.trim()) { msg.textContent = 'A dismissal needs a reason.'; reason.focus(); return; }
      save.disabled = true; msg.textContent = 'Saving…';
      McA.api.reviewFlag(ctx.session, ctx.part, f.finding_id, sel.value, reason.value).then(function () {
        delete drafts[f.finding_id];
        msg.textContent = 'Saved.';
        return McA.run.loadOutputs();
      }, function (e) { msg.textContent = 'Not saved: ' + ((e && (e.detail || e.message)) || 'error'); }).then(function () { save.disabled = false; });
    });
    wrap.append(sel, reason, save, msg);
    return wrap;
  }

  function renderPanel(body, d) {
    var m = d.payload && d.payload.categories && d.payload.categories.flags;
    if (!m || !m.present) return;
    var list = FV.flagList(m), f = filters(), shown = FV.filterFlags(list, f);
    var located = list.filter(function (x) { return x.located; }).length;
    var wrap = h('section', { class: 'dfl', 'aria-labelledby': 'dfl-h' });
    wrap.append(h('h3', { id: 'dfl-h', class: 'sub-h', text: 'Drawing flags (automatic)' }));
    var ban = FV.banner(m);
    if (ban) wrap.append(h('div', { class: 'banner', role: 'note' }, McA.icons.get('info', 18), h('span', { text: ban })));
    wrap.append(h('p', { class: 'rsec-note', text: list.length + ' flag' + (list.length === 1 ? '' : 's') + ': ' + located + ' located on the drawing, ' + (list.length - located) + ' not located. Placed automatically by the pipeline; you review them, you do not position them.' }));
    var annotated = m.artifacts && m.artifacts.annotated_pdf, ctx = d.ctx && d.ctx.kind === 'part' ? d.ctx : null;
    if (annotated && ctx) wrap.append(h('a', { class: 'btn secondary sm', href: McA.api.partFileURL(ctx.session, ctx.part, annotated), download: annotated, text: 'Download annotated PDF' }));
    if (!list.length) { wrap.append(h('p', { class: 'rsec-note', text: 'The pipeline raised no engineering flags for this run.' })); body.append(wrap); return; }
    var bar = h('div', { class: 'flags-filter dfl-filter', role: 'group', 'aria-label': 'Filter drawing flags' });
    ['error', 'warning', 'info'].forEach(function (sv) {
      var n = list.filter(function (x) { return x.severity === sv; }).length, mk = FV.severityMark(sv);
      bar.append(chipBtn(mk.label + ' ' + n, f.severity.indexOf(sv) !== -1, function () { setFilter({ severity: toggled(f.severity, sv) }); }, 'badge-sev ' + (sv === 'error' ? 'high' : sv === 'warning' ? 'medium' : 'low')));
    });
    var cats = Object.keys(list.reduce(function (a, x) { a[x.category] = 1; return a; }, {})).sort();
    var feats = Object.keys(list.reduce(function (a, x) { (x.feature_ids || []).forEach(function (i) { a[i] = 1; }); return a; }, {})).sort();
    bar.append(
      optionsSelect('Filter by category', f.category[0] || '', [['', 'All categories']].concat(cats.map(function (c) { return [c, CATS[c] || c]; })), function (v) { setFilter({ category: v ? [v] : [] }); }),
      optionsSelect('Filter by feature', f.feature, [['', 'All features']].concat(feats.map(function (c) { return [c, c]; })), function (v) { setFilter({ feature: v }); }),
      optionsSelect('Filter by review state', f.state[0] || '', [['', 'Any review state']].concat(Object.keys(STATE_LABEL).map(function (k) { return [k, STATE_LABEL[k]]; })), function (v) { setFilter({ state: v ? [v] : [] }); }),
      optionsSelect('Filter by location', f.location, [['all', 'Located and not located'], ['located', 'Located on the drawing'], ['unlocated', 'Not located']], function (v) { setFilter({ location: v }); }));
    wrap.append(bar);
    var listEl = h('div', { class: 'flagcards', role: 'list', 'aria-label': 'Drawing flags' });
    if (!shown.length) listEl.append(h('p', { class: 'rsec-note', text: 'No flags match these filters.' }));
    shown.filter(function (x) { return x.located; }).forEach(function (x) { listEl.append(h('div', { role: 'listitem' }, card(x, d, shown))); });
    var un = shown.filter(function (x) { return !x.located; });
    wrap.append(listEl);
    if (un.length) {
      wrap.append(h('h3', { class: 'flags-group', text: 'Not located on the drawing (' + un.length + ')' }),
        h('p', { class: 'rsec-note', text: 'No red box is drawn for these: the pipeline could not place them with enough confidence, and a wrong box is worse than none.' }));
      var ul = h('div', { class: 'flagcards', role: 'list', 'aria-label': 'Flags not located on the drawing' });
      un.forEach(function (x) { ul.append(h('div', { role: 'listitem' }, card(x, d, shown))); });
      wrap.append(ul);
    }
    if ((m.resolved_history || []).length) {
      wrap.append(h('h3', { class: 'flags-group', text: 'Resolved in a later run' }),
        h('ul', { class: 'flag-hist' }, m.resolved_history.map(function (r) { return h('li', { class: 'mono', text: r.finding_id + ' · verified corrected in ' + r.verified_in_run }); })));
    }
    body.append(wrap);
  }

  McA.engFlags = {
    renderPanel: renderPanel, syncTransform: syncTransform, relayout: layout, select: selectFlag,
    init: function () {
      box = document.getElementById('ov-box'); img = document.getElementById('ov-img');
      if (!box || !img || !FV) return;
      layer = h('div', { id: 'ov-flag-layer', class: 'flag-layer', role: 'group', 'aria-label': 'Engineering flags drawn on the drawing', hidden: true });
      box.append(layer);
      var st = McA.store;
      st.subscribe(function (s) { return s.outputs; }, layout);
      st.subscribe(function (s) { return s.outputs; }, function () { if (McA.viewer2d && McA.viewer2d.relayoutMarkup) McA.viewer2d.relayoutMarkup(); });
      st.subscribe(function (s) { return s.parts.selected; }, layout);
      st.subscribe(function (s) { return [s.ui.flagSelected, JSON.stringify(s.ui.dflFilter || null)].join('|'); }, layout);
      if (window.ResizeObserver) new ResizeObserver(McA.util.debounce(layout, 30)).observe(box);
      window.addEventListener('resize', McA.util.debounce(layout, 60));
      layout();
    }
  };
})();
