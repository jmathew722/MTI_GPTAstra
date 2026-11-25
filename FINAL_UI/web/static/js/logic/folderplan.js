/* McA.folderplan: pure planning of a chosen folder into batch jobs (no DOM, no network).
   Rules:
   - Only the folder's IMMEDIATE files are scanned by default; { recursive: true } also scans subfolders for files.
   - Every PDF / JPG / JPEG / PNG (any letter case; also WebP, BMP, TIFF) is ONE job, however many pages it has.
   - A SUBFOLDER that holds view images is still one multi-view part (the "Upload Parts Folder" layout; see batchgroup.js).
   - Everything else is skipped WITH a reason, never silently: unsupported types, empty files, hidden/system files.
   - Job names are safe, unique and stable: the same input always plans to the same name. A name that would lose
     every character (e.g. all-Unicode) gets a short hash so two such files never collide.
   - Magic bytes decide what a file REALLY is (detect()), so a renamed file cannot slip through. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).folderplan = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var PDF_RE = /\.pdf$/i;
  var IMG_RE = /\.(jpe?g|png|webp|bmp|tiff?)$/i;
  var HIDDEN = /^(\.|~\$|thumbs\.db$|desktop\.ini$)/i;

  function comps(path) { return String(path || '').replace(/\\/g, '/').split('/').filter(function (c) { return c && c !== '.' && c !== '..'; }); }
  function extOf(n) { var m = /\.([^.\/\\]+)$/.exec(String(n)); return m ? m[1].toLowerCase() : ''; }
  function hash(s) { var h = 5381; s = String(s); for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0; return (h >>> 0).toString(36); }
  /** File-safe stem. Unicode is kept readable when it is plain letters/digits; anything that would collapse to nothing is hashed. */
  function stemOf(name) {
    var base = String(name).replace(/\.[^.]+$/, '');
    var clean = base.replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '');
    return clean || ('drawing_' + hash(base));
  }
  function uniqueName(base, taken) {
    var set = {}; (taken || []).forEach(function (t) { set[String(t).toLowerCase()] = 1; });
    if (!set[String(base).toLowerCase()]) return base;
    for (var i = 2; i < 1000; i++) if (!set[(base + '_' + i).toLowerCase()]) return base + '_' + i;
    return base + '_' + hash(base + Date.now());
  }
  /** Stable id of one input: its path, size and modified time. The same file always gets the same id. */
  function inputId(e) { return 'in-' + hash((e.path || e.name) + '|' + (e.size || 0) + '|' + (e.lastModified || 0)); }

  /** entries: [{ name, path, size?, lastModified? }]. Returns { jobs, parts, skipped, root }. */
  function plan(entries, opts) {
    opts = opts || {};
    var jobs = [], skipped = [], subdirs = {}, order = [];
    var taken = {};
    (entries || []).forEach(function (e, index) {
      var c = comps(e.path || e.name);
      var fname = c[c.length - 1] || '';
      if (!fname) return;
      var depth = c.length;                         // 1 = bare file, 2 = root/file, >=3 = inside a subfolder
      if (HIDDEN.test(fname) || c.some(function (x, i) { return i < c.length - 1 && /^\./.test(x); })) {
        skipped.push({ name: fname, reason: 'hidden or system file', index: index, silent: true });
        return;
      }
      var immediate = depth <= 2;
      if (!immediate) {
        var sub = c[c.length - 2];
        var isView = IMG_RE.test(fname) || /\.txt$/i.test(fname);
        if (!opts.recursive) {
          if (isView) { if (!subdirs[sub]) { subdirs[sub] = []; order.push(sub); } subdirs[sub].push({ index: index, fname: fname, path: c.join('/') }); }
          else if (PDF_RE.test(fname)) skipped.push({ name: c.slice(1).join('/'), reason: 'inside a subfolder (subfolders are scanned only for view images; pick the folder itself or enable recursive scanning)', index: index });
          else skipped.push({ name: c.slice(1).join('/'), reason: 'unsupported file type in a subfolder', index: index });
          return;
        }
      }
      if (e.size === 0) { skipped.push({ name: fname, reason: 'empty file (0 bytes)', index: index }); return; }
      var ext = extOf(fname);
      var kind = PDF_RE.test(fname) ? 'pdf' : IMG_RE.test(fname) ? 'image' : '';
      if (!kind) { skipped.push({ name: fname, reason: ext ? 'unsupported type .' + ext : 'no file extension', index: index }); return; }
      var stem = stemOf(fname);
      var name = uniqueName(stem, Object.keys(taken)); taken[name] = 1;
      jobs.push({ id: inputId(e), kind: 'file', type: kind, ext: ext, name: name, label: fname, index: index, path: c.join('/') });
    });
    var parts = order.map(function (n) {
      var items = subdirs[n]; var views = items.filter(function (i) { return IMG_RE.test(i.fname); }).length;
      return { id: 'in-' + hash('part|' + n), kind: 'part', name: stemOf(n), label: n + '/', views: views, items: items };
    }).filter(function (p) { return p.views > 0; });
    return { jobs: jobs, parts: parts, skipped: skipped, total: jobs.length + parts.length };
  }

  /** The kind of a file from its first bytes: 'pdf' | 'png' | 'jpeg' | 'webp' | 'bmp' | 'tiff' | null. */
  function detect(bytes) {
    var b = bytes || [];
    function at(i, s) { for (var k = 0; k < s.length; k++) if (b[i + k] !== s.charCodeAt(k)) return false; return true; }
    if (at(0, '%PDF-')) return 'pdf';
    if (b[0] === 0x89 && at(1, 'PNG')) return 'png';
    if (b[0] === 0xFF && b[1] === 0xD8 && b[2] === 0xFF) return 'jpeg';
    if (at(0, 'RIFF') && at(8, 'WEBP')) return 'webp';
    if (at(0, 'BM')) return 'bmp';
    if ((b[0] === 0x49 && b[1] === 0x49 && b[2] === 0x2A && b[3] === 0) || (b[0] === 0x4D && b[1] === 0x4D && b[2] === 0 && b[3] === 0x2A)) return 'tiff';
    return null;
  }
  /** Does the real content agree with the extension? Returns '' when fine, else the reason. */
  function mismatch(job, bytes) {
    var real = detect(bytes);
    if (!real) return 'the content is not a PDF or image (the file may be corrupt or renamed)';
    var expect = job.type === 'pdf' ? 'pdf' : null;
    if (job.type === 'pdf' && real !== 'pdf') return 'named .pdf but the content is ' + real.toUpperCase();
    if (job.type === 'image' && real === 'pdf') return 'named .' + job.ext + ' but the content is a PDF';
    return expect === null ? '' : '';
  }
  /** Short summary line for skipped files, ignoring silent ones (hidden/system). */
  function skippedSummary(skipped) {
    var shown = (skipped || []).filter(function (s) { return !s.silent; });
    if (!shown.length) return '';
    var byReason = {};
    shown.forEach(function (s) { (byReason[s.reason] = byReason[s.reason] || []).push(s.name); });
    return Object.keys(byReason).map(function (r) {
      var names = byReason[r];
      return names.length + ' skipped (' + r + '): ' + names.slice(0, 3).join(', ') + (names.length > 3 ? ', and ' + (names.length - 3) + ' more' : '');
    }).join('; ');
  }

  return { plan: plan, detect: detect, mismatch: mismatch, skippedSummary: skippedSummary, stemOf: stemOf, uniqueName: uniqueName, inputId: inputId, extOf: extOf };
});
