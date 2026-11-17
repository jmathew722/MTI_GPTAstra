/* McA.batchgroup: pure grouping of a chosen folder into parts (no DOM, no network).
   Rules (mirrors POST /api/parts/upload-batch, plus one UI rule for loose files):
   - a file inside a subfolder belongs to the folder that directly contains it (= one part);
   - when the folder has subfolders, loose files at its top level become one part each (named by file stem);
   - when it has no subfolders, the folder itself is one part (the server's own grouping);
   - only view images and .txt specs are usable; dotfiles are skipped; views = image files. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).batchgroup = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var IMG_RE = /\.(jpe?g|png|webp|bmp|tiff?)$/i;
  var TXT_RE = /\.txt$/i;

  function comps(path) { return String(path || '').replace(/\\/g, '/').split('/').filter(function (c) { return c && c !== '.' && c !== '..'; }); }
  function stemOf(n) { return String(n).replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_-]+/g, '_') || 'part'; }

  /** entries: [{ name, path }] (path = webkitRelativePath). Returns [{ name, views, items:[{index, uploadPath}] }]. */
  function groupFolder(entries) {
    var usable = [];
    (entries || []).forEach(function (e, index) {
      var c = comps(e.path || e.name);
      var fname = c[c.length - 1] || '';
      if (c.length < 2 || fname.charAt(0) === '.') return;
      if (!IMG_RE.test(fname) && !TXT_RE.test(fname)) return;
      usable.push({ index: index, c: c, fname: fname });
    });
    var hasSub = usable.some(function (u) { return u.c.length >= 3; });
    var parts = {}, order = [];
    usable.forEach(function (u) {
      var name, upath;
      if (u.c.length >= 3) { name = u.c[u.c.length - 2]; upath = u.c.join('/'); }
      else if (hasSub) {
        if (!IMG_RE.test(u.fname)) return;           // a loose spec file has no part to belong to
        name = stemOf(u.fname); upath = u.c[0] + '/' + name + '/' + u.fname;
      } else { name = u.c[0]; upath = u.c.join('/'); }
      if (!parts[name]) { parts[name] = { name: name, views: 0, items: [] }; order.push(name); }
      if (IMG_RE.test(u.fname)) parts[name].views += 1;
      parts[name].items.push({ index: u.index, uploadPath: upath });
    });
    return order.map(function (n) { return parts[n]; }).filter(function (p) { return p.views > 0; });
  }

  /** A name not in `taken` (case-insensitive): base, base_2, base_3 ... */
  function uniqueName(base, taken) {
    var set = {}; (taken || []).forEach(function (t) { set[String(t).toLowerCase()] = 1; });
    if (!set[String(base).toLowerCase()]) return base;
    for (var i = 2; i < 1000; i++) if (!set[(base + '_' + i).toLowerCase()]) return base + '_' + i;
    return base + '_' + Date.now();
  }

  return { groupFolder: groupFolder, uniqueName: uniqueName, stemOf: stemOf };
});
