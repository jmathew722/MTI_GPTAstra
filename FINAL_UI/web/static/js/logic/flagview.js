/* McA.flagview: PURE logic for the engineering-flag overlay and panel (Stage 3). No DOM, no fetch.
   The pipeline places every flag (pipeline/flag_overlays.py) as a normalized rectangle in the UNROTATED
   page; this file turns that into container pixels over the displayed drawing image, joins flags with their
   overlay or their honest "not located" reason, filters, and drives selection. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).flagview = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var SEV_RANK = { error: 0, warning: 1, info: 2 };
  var METHOD = { exact_tokens: 'exact match', normalized: 'normalized match', fuzzy: 'close match',
                 extraction_region: 'extraction region', developer_override: 'developer override' };
  var SEV_MARK = {
    error: { text: 'ERROR', label: 'Error', shape: 'octagon', icon: 'x' },
    warning: { text: 'WARNING', label: 'Warning', shape: 'triangle', icon: 'warn' },
    info: { text: 'INFO', label: 'Info', shape: 'circle', icon: 'info' }
  };

  /* ---- coordinates --------------------------------------------------------------------------- */
  /** The unrotated normalized rect -> the page as displayed (the page's clockwise /Rotate applied). */
  function toDisplayed(r, rotation) {
    var rot = ((rotation % 360) + 360) % 360;
    if (rot % 90 !== 0) throw new Error('rotation must be a multiple of 90');
    var x = r.x, y = r.y, w = r.width, h = r.height;
    if (rot === 0) return { x: x, y: y, width: w, height: h };
    if (rot === 90) return { x: 1 - (y + h), y: x, width: h, height: w };
    if (rot === 180) return { x: 1 - (x + w), y: 1 - (y + h), width: w, height: h };
    return { x: y, y: 1 - (x + w), width: h, height: w };
  }
  /** Where an image of nw x nh sits inside a cw x ch box with object-fit: contain. */
  function fitContain(cw, ch, nw, nh) {
    if (!(cw > 0 && ch > 0 && nw > 0 && nh > 0)) return { x: 0, y: 0, w: 0, h: 0 };
    var s = Math.min(cw / nw, ch / nh), w = nw * s, h = nh * s;
    return { x: (cw - w) / 2, y: (ch - h) / 2, w: w, h: h };
  }
  /** Flag rectangle in container pixels (before the viewer's pan/zoom, which the layer applies itself). */
  function overlayPx(rectNorm, rotation, fit) {
    var d = toDisplayed(rectNorm, rotation);
    return { left: fit.x + d.x * fit.w, top: fit.y + d.y * fit.h, width: d.width * fit.w, height: d.height * fit.h };
  }
  /** translate(tx,ty) scale(s) about the container centre, chosen so the flag sits in the middle of the view. */
  function focusTransform(px, view, limits) {
    var lim = limits || { min: 0.2, max: 12 };
    var want = Math.min(0.35 * view.w / Math.max(px.width, 1e-6), 0.35 * view.h / Math.max(px.height, 1e-6));
    var s = Math.min(lim.max, Math.max(lim.min, want));
    var cx = view.w / 2, cy = view.h / 2, fx = px.left + px.width / 2, fy = px.top + px.height / 2;
    return { s: s, tx: -(fx - cx) * s, ty: -(fy - cy) * s };
  }

  /* ---- the flag model ------------------------------------------------------------------------ */
  function flagList(model) {
    if (!model || !model.present) return [];
    var byOv = {}, byUn = {};
    (model.overlays || []).forEach(function (o) { (byOv[o.finding_id] = byOv[o.finding_id] || []).push(o); });
    (model.unlocated || []).forEach(function (u) { if (!byUn[u.finding_id]) byUn[u.finding_id] = u; });
    var review = model.review || {};
    var list = (model.findings || []).map(function (f, i) {
      var ovs = byOv[f.finding_id] || [], un = byUn[f.finding_id] || null, o = ovs[0] || null;
      var out = Object.assign({}, f, {
        located: !!o, overlay: o, overlays: ovs, reason: o ? '' : (un && un.reason) || 'no_match',
        candidates: un ? un.candidates : 0, likely_page: un ? un.likely_page : null, likely_view: un ? un.likely_view : null,
        state: (review[f.finding_id] && review[f.finding_id].state) || 'open',
        reviewReason: (review[f.finding_id] && review[f.finding_id].reason) || '',
        number: (o && o.number) || (un && un.number) || i + 1, _i: i
      });
      if (o) { out.page_index = o.page_index; out.mapping_method = o.mapping_method; out.mapping_confidence = o.mapping_confidence; out.provenance = o.provenance; }
      return out;
    });
    list.sort(function (a, b) {
      var ra = SEV_RANK[a.severity] === undefined ? 2 : SEV_RANK[a.severity], rb = SEV_RANK[b.severity] === undefined ? 2 : SEV_RANK[b.severity];
      return ra - rb || a.number - b.number || a._i - b._i;
    });
    return list;
  }
  function has(arr, v) { return !arr || !arr.length || arr.indexOf(v) !== -1; }
  function filterFlags(list, f) {
    f = f || {};
    return list.filter(function (x) {
      return has(f.severity, x.severity) && has(f.category, x.category) && has(f.state, x.state) &&
        (!f.feature || (x.feature_ids || []).indexOf(f.feature) !== -1) &&
        (!f.location || f.location === 'all' || (f.location === 'located') === x.located);
    });
  }
  /** Overlays to draw on the displayed page: only for a verified, current drawing, and only the visible flags. */
  function drawable(model, displayedPage, filters) {
    if (!model || !model.present || !model.hash_verified || model.stale) return [];
    var visible = {};
    filterFlags(flagList(model), filters).forEach(function (x) { visible[x.finding_id] = true; });
    return (model.overlays || []).filter(function (o) { return o.page_index === displayedPage && visible[o.finding_id]; });
  }
  function select(list, id) { return list.some(function (x) { return x.finding_id === id; }) ? id : null; }
  function neighbor(list, id, dir) {
    if (!list.length) return null;
    var i = -1;
    list.forEach(function (x, k) { if (x.finding_id === id) i = k; });
    if (i === -1) return list[dir < 0 ? list.length - 1 : 0].finding_id;
    return list[(i + dir + list.length) % list.length].finding_id;
  }

  /* ---- words ----------------------------------------------------------------------------------- */
  var REASON = {
    ambiguous: function (f) { return (f.candidates || 2) + ' equally good matches, so none was guessed'; },
    no_match: function () { return 'the callout text was not found on the drawing'; },
    no_source_callout: function () { return 'this finding has no drawing callout to find'; },
    region_too_coarse: function () { return 'only a large region is known'; },
    view_level: function (f) { return 'only the view is known' + (f.likely_view ? ' (' + f.likely_view + ')' : ''); },
    low_confidence: function () { return 'the best match was too uncertain to draw'; },
    drawing_revision_changed: function () { return 'the drawing has changed since this run'; },
    older_run: function () { return 'these flags are from an earlier run'; },
    drawing_unavailable: function () { return 'the drawing cannot be verified'; },
    invalid_geometry: function () { return 'the stored position was invalid'; }
  };
  function locationText(f) {
    if (f.located) {
      var m = METHOD[f.mapping_method] || String(f.mapping_method || 'match').replace(/_/g, ' ');
      return 'Page ' + (f.page_index + 1) + ' · ' + m + ' · ' + Math.round((f.mapping_confidence || 0) * 100) + '% confidence';
    }
    var why = (REASON[f.reason] || function () { return String(f.reason || 'unknown').replace(/_/g, ' '); })(f);
    return 'Not located on the drawing: ' + why + (typeof f.likely_page === 'number' ? ', likely page ' + (f.likely_page + 1) : '') + '.';
  }
  function severityMark(sev) { return SEV_MARK[sev] || SEV_MARK.info; }
  function banner(model) {
    if (!model || !model.present) return null;
    if (model.stale && model.reason === 'drawing_revision_changed') return 'These flags were computed for a different revision of the drawing, so they are listed but not drawn on it. Re-run the pipeline to refresh them.';
    if (model.stale) return 'These flags are from an earlier run, so they are listed but not drawn on the drawing. Re-run the pipeline to refresh them.';
    if (model.hash_verified === false) return 'The drawing these flags belong to cannot be verified, so they are listed but not drawn on it.';
    if (model.truncated) return 'Showing the first ' + (model.findings || []).length + ' of ' + ((model.counts || {}).findings || '?') + ' flags. Download the full findings file for the rest.';
    return null;
  }

  return { toDisplayed: toDisplayed, fitContain: fitContain, overlayPx: overlayPx, focusTransform: focusTransform, flagList: flagList,
           filterFlags: filterFlags, drawable: drawable, select: select, neighbor: neighbor, locationText: locationText,
           severityMark: severityMark, banner: banner, METHOD: METHOD };
});
