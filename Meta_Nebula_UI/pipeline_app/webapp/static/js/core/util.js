/* McA.util: small DOM-free helpers plus a few DOM helpers that touch the
   document only when called. Classic script; also loadable from node. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(root);
  else (root.McA = root.McA || {}).util = factory(root);
})(typeof self !== 'undefined' ? self : (typeof globalThis !== 'undefined' ? globalThis : this), function (root) {
  'use strict';

  var ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;' };

  /** Escape text for insertion into HTML (element content or quoted attribute). */
  function esc(v) {
    if (v === null || v === undefined) return '';
    return String(v).replace(/[&<>"'`]/g, function (c) { return ESC[c]; });
  }

  /** Return `value` only when it is in `allowed`, else `fallback`.
      Use for class names built from payload values (sev-..., st-...). */
  function whitelist(value, allowed, fallback) {
    return allowed.indexOf(value) !== -1 ? value : (fallback === undefined ? '' : fallback);
  }

  /** Bytes as "0 B", "512 B", "1.5 KB", "2.0 MB", "1.00 GB". */
  function fmtBytes(n) {
    if (typeof n !== 'number' || !isFinite(n) || n < 0) return '';
    if (n < 1024) return Math.round(n) + ' B';
    var units = ['KB', 'MB', 'GB', 'TB'];
    var v = n / 1024, i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return v.toFixed(i >= 2 ? 2 : 1) + ' ' + units[i];
  }

  /** Elapsed MILLISECONDS as "m:ss" (under one hour) or "h:mm:ss". */
  function fmtElapsed(ms) {
    if (typeof ms !== 'number' || !isFinite(ms) || ms < 0) ms = 0;
    var total = Math.floor(ms / 1000);
    var h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
    var ss = (s < 10 ? '0' : '') + s;
    if (h > 0) return h + ':' + (m < 10 ? '0' : '') + m + ':' + ss;
    return m + ':' + ss;
  }

  /** Trailing-edge debounce. The returned function has .cancel() and .flush(). */
  function debounce(fn, wait) {
    var t = null, lastArgs = null, lastThis = null;
    function run() { t = null; var a = lastArgs, th = lastThis; lastArgs = lastThis = null; fn.apply(th, a); }
    function d() {
      lastArgs = arguments; lastThis = this;
      if (t !== null) clearTimeout(t);
      t = setTimeout(run, wait);
    }
    d.cancel = function () { if (t !== null) clearTimeout(t); t = null; lastArgs = lastThis = null; };
    d.flush = function () { if (t !== null) { clearTimeout(t); run(); } };
    return d;
  }

  /** Copy text to the clipboard. Resolves true on success. Falls back to a
      hidden textarea when the async clipboard API is unavailable. */
  function copyText(text) {
    var s = String(text === null || text === undefined ? '' : text);
    var nav = root && root.navigator;
    if (nav && nav.clipboard && typeof nav.clipboard.writeText === 'function') {
      return nav.clipboard.writeText(s).then(function () { return true; }, function () { return fallback(); });
    }
    return Promise.resolve(fallback());
    function fallback() {
      var doc = root && root.document;
      if (!doc || !doc.body) return false;
      var ta = doc.createElement('textarea');
      ta.value = s; ta.setAttribute('readonly', ''); ta.setAttribute('aria-hidden', 'true');
      ta.style.position = 'fixed'; ta.style.top = '0'; ta.style.left = '-9999px';
      doc.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = !!doc.execCommand('copy'); } catch (e) { ok = false; }
      doc.body.removeChild(ta);
      return ok;
    }
  }

  /** Trigger a browser download of `url` through a hidden anchor. */
  function downloadURL(url, filename) {
    var doc = root.document;
    var a = doc.createElement('a');
    a.href = url;
    if (filename) a.download = filename; else a.setAttribute('download', '');
    a.rel = 'noopener'; a.hidden = true;
    doc.body.appendChild(a); a.click(); doc.body.removeChild(a);
  }

  /** Create an element. attrs: class/className, text, dataset{}, style{}, on<Event> fns,
      boolean attrs (true sets, false/null omits), anything else via setAttribute.
      children: strings (as text nodes), Nodes, arrays, or null/false (skipped). */
  function el(tag, attrs) {
    var doc = root.document;
    var n = doc.createElement(tag);
    var k;
    if (attrs) {
      for (k in attrs) {
        if (!Object.prototype.hasOwnProperty.call(attrs, k)) continue;
        var v = attrs[k];
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class' || k === 'className') n.className = v;
        else if (k === 'text') n.textContent = v;
        else if (k === 'dataset') { for (var d in v) n.dataset[d] = v[d]; }
        else if (k === 'style' && typeof v === 'object') { for (var s in v) n.style.setProperty(s, v[s]); }
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') n.addEventListener(k.slice(2).toLowerCase(), v);
        else if (v === true) n.setAttribute(k, '');
        else n.setAttribute(k, String(v));
      }
    }
    for (var i = 2; i < arguments.length; i++) append(n, arguments[i]);
    return n;
  }
  function append(parent, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) { for (var i = 0; i < c.length; i++) append(parent, c[i]); return; }
    parent.appendChild(typeof c === 'object' ? c : root.document.createTextNode(String(c)));
  }

  return { esc: esc, whitelist: whitelist, fmtBytes: fmtBytes, fmtElapsed: fmtElapsed,
           debounce: debounce, copyText: copyText, downloadURL: downloadURL, el: el };
});
