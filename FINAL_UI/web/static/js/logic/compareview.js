/* McA.compareview: PURE rules for the v8 source-vs-generated drawing comparison (no DOM, no network).
   Inputs are the job_view part (V8_CONTRACT.md section 3: part.replication, part.verification, part.reference, part.files). Everything is optional:
   a missing field is omitted, never invented. "Verified" is shown only when the backend says verified; a v7-only part (no replication block) is a Draft
   and is never labelled Verified. Software verification is not engineering approval, so no label here says "approved". */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).compareview = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function norm(s) { return String(s === null || s === undefined ? '' : s).trim().toLowerCase().replace(/[\s-]+/g, '_'); }

  /* ------------------------------------------------------------------ status */
  var STATUS = {
    verified: { key: 'verified', label: 'Verified', tone: 'green', icon: 'check', verified: true, draft: false },
    needs_review: { key: 'needs_review', label: 'Needs Review', tone: 'amber', icon: 'warn', verified: false, draft: true },
    blocked: { key: 'blocked', label: 'Blocked', tone: 'red', icon: 'x', verified: false, draft: true },
    failed: { key: 'failed', label: 'Failed', tone: 'red', icon: 'x', verified: false, draft: true },
    pending: { key: 'pending', label: 'Pending', tone: 'violet', icon: 'recent', verified: false, draft: true },
    draft: { key: 'draft', label: 'Draft', tone: 'blue', icon: 'info', verified: false, draft: true },
    none: { key: 'none', label: 'Not compared', tone: 'none', icon: 'dash', verified: false, draft: true }
  };
  // v7 verification.status values (and the v8 capitalised spellings) mapped onto the one vocabulary.
  var VMAP = { passed: 'draft', verified: 'verified', review_required: 'needs_review', needs_review: 'needs_review', failed: 'failed', blocked: 'blocked', pending: 'pending', not_run: 'none', unknown: 'none' };
  /** {key,label,tone,icon,verified,draft,reason,source}. source: 'replication' | 'verification' | 'none'. */
  function statusInfo(part) {
    var rep = part && part.replication, ver = part && part.verification;
    if (rep && typeof rep === 'object' && rep.status) {
      var k = STATUS[norm(rep.status)] ? norm(rep.status) : (VMAP[norm(rep.status)] || 'none');
      var s = Object.assign({}, STATUS[k]);
      if (k === 'verified' && !(rep.status_label && norm(rep.status_label) !== 'verified')) s.label = 'Verified';
      else if (rep.status_label && STATUS[k] && norm(rep.status_label) === norm(STATUS[k].label)) s.label = String(rep.status_label);
      s.reason = typeof rep.reason === 'string' ? rep.reason : ''; s.source = 'replication';
      return s;
    }
    if (ver && typeof ver === 'object' && ver.status) {
      var vk = VMAP[norm(ver.status)] || 'none', vs = Object.assign({}, STATUS[vk]);
      if (vk === 'draft') vs.label = 'Draft: checks passed (not verified against a source)';
      vs.reason = ''; vs.source = 'verification';
      return vs;
    }
    return Object.assign({}, STATUS.none, { reason: '', source: 'none' });
  }

  /* ------------------------------------------------------------------ issues */
  var KIND = {
    missing_annotation: ['missing', 'Missing annotation'], view_missing: ['missing', 'Missing view'], page_missing: ['missing', 'Missing page'],
    extra_annotation: ['extra', 'Extra annotation'],
    value_mismatch: ['mismatch', 'Value mismatch'], text_mismatch: ['mismatch', 'Text mismatch'], scale_mismatch: ['mismatch', 'Scale mismatch'], position_deviation: ['mismatch', 'Position deviation'], clipping: ['mismatch', 'Clipping'],
    unreadable_source: ['other', 'Unreadable source']
  };
  var SEV_RANK = { critical: 0, high: 1, medium: 2, low: 3 };
  function titleCase(k) { var s = String(k || 'issue').replace(/_/g, ' '); return s.charAt(0).toUpperCase() + s.slice(1); }
  /** Normalised bounding box {x0,y0,x1,y1} as fractions of the page (0..1, top-left origin) from an issue's evidence, or null. */
  function bboxOf(i) {
    var e = i && (i.evidence || i.bbox || i.box); var b = e && (e.bbox || e);
    if (!b || typeof b !== 'object') return null;
    var a = Array.isArray(b) ? b : (isNum(b.x0) ? [b.x0, b.y0, b.x1, b.y1] : (isNum(b.x) ? [b.x, b.y, b.x + (b.w || b.width || 0), b.y + (b.h || b.height || 0)] : null));
    if (!a || a.length < 4 || !a.every(isNum)) return null;
    if (a.some(function (n) { return n < 0 || n > 1; })) return null;      // only fractions are understood; anything else is not shown rather than guessed
    var x0 = Math.min(a[0], a[2]), x1 = Math.max(a[0], a[2]), y0 = Math.min(a[1], a[3]), y1 = Math.max(a[1], a[3]);
    return x1 - x0 > 0 && y1 - y0 > 0 ? { x0: x0, y0: y0, x1: x1, y1: y1 } : null;
  }
  /** Issues of a part, newest vocabulary first: replication.issues, else verification.issues, else the v7 unresolved list. */
  function issues(part) {
    var rep = part && part.replication, ver = part && part.verification, src = [], from = '';
    if (rep && Array.isArray(rep.issues) && rep.issues.length) { src = rep.issues; from = 'replication'; }
    else if (ver && Array.isArray(ver.issues) && ver.issues.length) { src = ver.issues; from = 'verification'; }
    else if (ver && ver.coverage && Array.isArray(ver.coverage.unresolved)) { src = ver.coverage.unresolved; from = 'unresolved'; }
    var out = src.filter(function (i) { return i && typeof i === 'object'; }).map(function (i, n) {
      var kind = i.kind || (from === 'unresolved' ? 'unresolved' : 'issue'), k = KIND[kind] || (from === 'unresolved' ? ['other', 'Unresolved ' + (i.kind || 'item')] : ['other', titleCase(kind)]);
      var pg = isNum(i.page) ? i.page : (isNum(i.sheet) ? i.sheet : (i.evidence && isNum(i.evidence.page) ? i.evidence.page : null));
      return { id: String(i.id || ('I' + (n + 1))), kind: kind, group: k[0], kindLabel: k[1], severity: SEV_RANK[i.severity] !== undefined ? i.severity : 'low', page: pg,
        text: String(i.text || i.message || ''), detail: String(i.detail || i.reason || ''), bbox: bboxOf(i), from: from };
    });
    out.sort(function (a, b) { return SEV_RANK[a.severity] - SEV_RANK[b.severity] || (a.page || 0) - (b.page || 0) || (a.id < b.id ? -1 : 1); });
    return out;
  }
  var GROUPS = [['all', 'All'], ['missing', 'Missing'], ['extra', 'Extra'], ['mismatch', 'Mismatched'], ['other', 'Other']];
  function groupCounts(list) {
    var c = { all: list.length, missing: 0, extra: 0, mismatch: 0, other: 0 };
    list.forEach(function (i) { c[i.group] = (c[i.group] || 0) + 1; });
    return c;
  }
  /** Which side of the comparison carries the evidence for this issue: a missing item exists in the SOURCE; an extra one exists in the GENERATED drawing. */
  function evidenceSide(i) { return i && i.group === 'extra' ? 'generated' : 'source'; }

  /* ------------------------------------------------------------------ facts */
  function scaleText(v) { return v === null || v === undefined || v === '' ? 'not stated' : String(v); }
  /** [{page|null, text, match}] e.g. "Sheet 1:2 source / 1:2 generated" (+ title block). Falls back to verification.comparison.scales. Empty when nothing is recorded. */
  function scaleLines(part) {
    var rep = part && part.replication, out = [];
    var sc = (rep && rep.scales) || (part && part.verification && part.verification.comparison && part.verification.comparison.scales) || null;
    if (sc) {
      var sh = sc.sheet || (sc.source !== undefined || sc.generated !== undefined ? sc : null);
      if (sh) out.push({ id: 'sheet', text: 'Sheet ' + scaleText(sh.source) + ' source / ' + scaleText(sh.generated) + ' generated' + (sh.title_block ? ' (title block ' + sh.title_block + ')' : ''), match: typeof sh.match === 'boolean' ? sh.match : (sh.source && sh.generated ? sh.source === sh.generated : null) });
      (Array.isArray(sc.views) ? sc.views : []).forEach(function (v) { out.push({ id: String(v.id || ''), text: 'View ' + (v.id || '') + ' ' + scaleText(v.source) + ' source / ' + scaleText(v.generated) + ' generated', match: typeof v.match === 'boolean' ? v.match : null }); });
    }
    return out;
  }
  var REUSE = { hit: 'Reused (saved extraction, no new model call)', supplemented: 'Supplemented (saved extraction plus a new call)', fresh: 'Fresh extraction', none: 'No extraction' };
  function reuseOf(part) {
    var rep = part && part.replication, ref = part && part.reference, ver = part && part.verification;
    var k = (rep && rep.spec && rep.spec.extraction_reuse) || (ref && ref.extraction_cache) || (ver && ver.extraction && ver.extraction.cache) || '';
    return k ? { key: k, text: REUSE[k] || String(k) } : null;
  }
  function correctionsOf(part) {
    var it = (part && part.replication && part.replication.iterations) || (part && part.verification && part.verification.iterations) || null;
    if (!it || !isNum(it.used)) return null;
    return { used: it.used, max: isNum(it.max) ? it.max : null, text: it.used + (isNum(it.max) ? ' of ' + it.max : '') + ' correction pass' + (it.used === 1 ? '' : 'es') + (it.stop_reason ? ' (stopped: ' + String(it.stop_reason).replace(/_/g, ' ') + ')' : '') };
  }
  function annotationCounts(part) {
    var sheets = (part && part.replication && part.replication.sheets) || [], t = { source: 0, generated: 0, matched: 0, missing: 0, extra: 0, mismatched: 0, any: false };
    sheets.forEach(function (s) {
      var a = s && s.annotations; if (!a) return; t.any = true;
      ['source', 'generated', 'matched', 'missing', 'extra', 'mismatched'].forEach(function (k) { if (isNum(a[k])) t[k] += a[k]; });
    });
    return t.any ? t : null;
  }
  function editable(part) {
    var f = (part && part.files) || {}, e = f.slddrw || f['drawing.slddrw'];
    var ok = !!(e && e.available !== false && e.url_path);
    return { available: ok, text: ok ? 'Editable SLDDRW available' : 'No editable SLDDRW for this part' };
  }
  /** Rows for the Comparison tab facts block: [label, value]. Only recorded values. */
  function factRows(part) {
    var rows = [], sl = scaleLines(part), ru = reuseOf(part), co = correctionsOf(part), an = annotationCounts(part), ed = editable(part), rep = part && part.replication;
    if (sl.length) rows.push(['Scales', sl.map(function (x) { return x.text; })]);
    if (ru) rows.push(['Extraction', [ru.text]]);
    if (co) rows.push(['Corrections', [co.text]]);
    if (an) rows.push(['Annotations', [an.matched + ' matched of ' + an.source + ' in the source · ' + an.missing + ' missing · ' + an.extra + ' extra · ' + an.mismatched + ' mismatched']]);
    if (rep && rep.spec && isNum(rep.spec.completeness)) rows.push(['Extraction completeness', [Math.round(rep.spec.completeness * 100) + '%']]);
    rows.push(['Editable output', [ed.text]]);
    return rows;
  }

  /* ------------------------------------------------------------------ comparison images */
  function kindOfName(name) {
    var n = String(name || '').toLowerCase();
    if (/overlay/.test(n)) return 'overlay';
    if (/diff/.test(n)) return 'difference';
    if (/side[_-]?by[_-]?side|sbs/.test(n)) return 'side_by_side';
    return 'other';
  }
  function pageOfName(name) {
    var m = /(?:page|p)[_-]?0*(\d+)/i.exec(String(name || '')); return m ? parseInt(m[1], 10) : null;
  }
  /** {overlay:[{name,rel,bytes,page}], difference:[...], side_by_side:[...]} from files.comparison_images (name-classified) and replication.images (rel paths). */
  function images(part) {
    var out = { overlay: [], difference: [], side_by_side: [] }, seen = {};
    var ci = part && part.files && part.files.comparison_images, list = ci && Array.isArray(ci.files) && ci.available !== false ? ci.files : [];
    var byRel = {};
    list.forEach(function (f) { if (f && typeof f.url_path === 'string') byRel[f.url_path] = f; });
    function add(kind, name, rel, bytes) {
      if (!out[kind] || !rel || seen[kind + rel]) return; seen[kind + rel] = 1;
      out[kind].push({ name: name, rel: rel, bytes: isNum(bytes) ? bytes : 0, page: pageOfName(name) });
    }
    var ri = part && part.replication && part.replication.images;
    if (ri && typeof ri === 'object') {
      ['side_by_side', 'overlay', 'difference'].forEach(function (k) {
        (Array.isArray(ri[k]) ? ri[k] : []).forEach(function (rel) {
          if (typeof rel !== 'string') return;
          var f = byRel[rel] || list.filter(function (x) { return String(x.url_path).slice(-rel.length) === rel; })[0];
          if (f) add(k, String(f.name || rel), f.url_path, f.bytes);       // only a file the server actually lists is shown
        });
      });
    }
    list.forEach(function (f) { if (f && typeof f.url_path === 'string') { var k = kindOfName(f.name || f.url_path); if (k !== 'other') add(k, String(f.name || ''), f.url_path, f.bytes); } });
    Object.keys(out).forEach(function (k) { out[k].sort(function (a, b) { return (a.page || 0) - (b.page || 0) || (a.name < b.name ? -1 : 1); }); });
    return out;
  }
  /** The backend image of a kind for a page: the one named for that page, or the only one when there is exactly one image and no page in its name. */
  function pickImage(list, page) {
    list = list || [];
    var byPage = list.filter(function (x) { return x.page === page; })[0];
    if (byPage) return byPage;
    if (list.length === 1 && list[0].page === null) return list[0];
    return null;
  }

  /* ------------------------------------------------------------------ sync */
  /** effective: both sheets loaded AND same page count. userOn is the toggle. reason names what blocks it. */
  function syncPlan(srcPages, genPages, userOn) {
    if (!srcPages || !genPages) return { possible: false, effective: false, reason: 'Both drawings must be loaded to synchronise them.' };
    if (srcPages !== genPages) return { possible: false, effective: false, reason: 'The sheets do not correspond (' + srcPages + ' source vs ' + genPages + ' generated), so they are not synchronised.' };
    return { possible: true, effective: !!userOn, reason: '' };
  }
  /** Scroll position as fractions of the scrollable range (so panes of different canvas sizes stay aligned). */
  function scrollFraction(pos, scrollSize, clientSize) { var r = scrollSize - clientSize; return r > 0 ? Math.max(0, Math.min(1, pos / r)) : 0; }
  function scrollFromFraction(f, scrollSize, clientSize) { var r = scrollSize - clientSize; return r > 0 ? Math.round(f * r) : 0; }

  /* ------------------------------------------------------------------ in-browser overlay / difference (when no backend image exists) */
  var INK = 160;                                    // luminance below this counts as drawn ink
  function lum(d, i) { return d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114; }
  /** Colour-coded difference of two same-size RGBA buffers. Ink only in the source = blue (missing from the generated drawing), only in the generated = red
      (extra), in both = grey. Returns {data, stats:{onlySource,onlyGenerated,both}}; writes into `out` when given. */
  function diffPixels(src, gen, out) {
    var n = Math.min(src.length, gen.length), res = out || new Uint8ClampedArray(n), s = { onlySource: 0, onlyGenerated: 0, both: 0 };
    for (var i = 0; i < n; i += 4) {
      var a = lum(src, i) < INK, b = lum(gen, i) < INK;
      if (a && b) { res[i] = res[i + 1] = res[i + 2] = 120; s.both++; }
      else if (a) { res[i] = 40; res[i + 1] = 110; res[i + 2] = 255; s.onlySource++; }
      else if (b) { res[i] = 235; res[i + 1] = 60; res[i + 2] = 60; s.onlyGenerated++; }
      else { res[i] = res[i + 1] = res[i + 2] = 255; }
      res[i + 3] = 255;
    }
    return { data: res, stats: s };
  }
  /** Overlay: both sheets over each other. Ink only in the source shows blue, ink only in the generated sheet shows red, ink in both is dark. */
  function overlayPixels(src, gen, out) {
    var n = Math.min(src.length, gen.length), res = out || new Uint8ClampedArray(n);
    for (var i = 0; i < n; i += 4) {
      var ls = lum(src, i), lg = lum(gen, i);
      res[i] = Math.round(ls); res[i + 1] = Math.round(Math.min(ls, lg)); res[i + 2] = Math.round(lg); res[i + 3] = 255;
    }
    return { data: res };
  }
  var LEGEND = { difference: 'Blue: in the source only (missing from the generated drawing). Red: in the generated drawing only (extra). Grey: in both.',
    overlay: 'Both sheets drawn over each other: dark where they agree, blue where only the source has ink, red where only the generated drawing has ink.' };

  /* ------------------------------------------------------------------ locating issue text in a PDF page */
  function mul(m, n) { return [m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1], m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3], m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5]]; }
  function squash(s) { return String(s || '').toLowerCase().replace(/[\s ]+/g, ' ').trim(); }
  /** Finds `text` among pdf.js text items. viewport = {width,height,transform} at scale 1. Returns a page-fraction box {x0,y0,x1,y1} or null (not found / no text layer). */
  function locateText(items, viewport, text) {
    var want = squash(text); if (!want || !items || !viewport || !viewport.width || !viewport.height) return null;
    var best = null;
    items.forEach(function (it) {
      var s = squash(it && it.str); if (!s) return;
      if (s.indexOf(want) < 0 && !(s.length >= 3 && want.indexOf(s) >= 0)) return;
      var t = mul(viewport.transform || [1, 0, 0, -1, 0, viewport.height], it.transform || [1, 0, 0, 1, 0, 0]);
      var sc = viewport.scale || 1, h = Math.abs(it.height || Math.sqrt(t[2] * t[2] + t[3] * t[3])) * (it.height ? sc : 1);
      var x0 = t[4], y0 = t[5] - h, x1 = t[4] + (it.width || 0) * sc, y1 = t[5] + h * 0.25;
      var box = { x0: Math.max(0, x0 / viewport.width), y0: Math.max(0, y0 / viewport.height), x1: Math.min(1, x1 / viewport.width), y1: Math.min(1, y1 / viewport.height) };
      if (box.x1 <= box.x0 || box.y1 <= box.y0) return;
      var exact = s === want;
      if (!best || (exact && !best.exact)) best = { box: box, exact: exact };
    });
    return best ? best.box : null;
  }

  return { STATUS: STATUS, statusInfo: statusInfo, issues: issues, GROUPS: GROUPS, groupCounts: groupCounts, evidenceSide: evidenceSide, bboxOf: bboxOf, scaleLines: scaleLines, reuseOf: reuseOf,
    correctionsOf: correctionsOf, annotationCounts: annotationCounts, editable: editable, factRows: factRows, images: images, pickImage: pickImage, kindOfName: kindOfName, pageOfName: pageOfName,
    syncPlan: syncPlan, scrollFraction: scrollFraction, scrollFromFraction: scrollFromFraction, diffPixels: diffPixels, overlayPixels: overlayPixels, LEGEND: LEGEND, locateText: locateText };
});
