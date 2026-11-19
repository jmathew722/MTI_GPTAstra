/* McA.api: one function per backend endpoint (ARCH 5). Every function returns
   parsed JSON or throws ApiError {status, detail}. status 0 = network failure.
   Endpoints and field names were checked against webapp/app.py. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(root);
  else (root.McA = root.McA || {}).api = factory(root);
})(typeof self !== 'undefined' ? self : (typeof globalThis !== 'undefined' ? globalThis : this), function (root) {
  'use strict';

  function ApiError(status, detail) {
    if (!(this instanceof ApiError)) return new ApiError(status, detail);
    this.name = 'ApiError'; this.status = status; this.detail = detail || '';
    this.message = detail || ('HTTP ' + status);
    this.stack = (new Error(this.message)).stack;
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  function enc(s) { return encodeURIComponent(s); }
  function encPath(rel) { return String(rel).split('/').map(enc).join('/'); }
  function q(params) {
    var parts = [];
    Object.keys(params || {}).forEach(function (k) {
      if (params[k] !== undefined && params[k] !== null) parts.push(enc(k) + '=' + enc(params[k]));
    });
    return parts.length ? '?' + parts.join('&') : '';
  }

  /** FastAPI errors: {detail: "text"} or {detail: [{loc,msg},...]}. */
  function detailOf(body, fallback) {
    if (body && typeof body === 'object' && 'detail' in body) {
      var d = body.detail;
      if (typeof d === 'string') return d;
      if (Array.isArray(d)) return d.map(function (x) { return (x && x.msg) || JSON.stringify(x); }).join('; ');
      return JSON.stringify(d);
    }
    return fallback;
  }

  function doFetch(url, init) {
    var f = root.fetch;
    if (typeof f !== 'function') return Promise.reject(ApiError(0, 'fetch is not available'));
    return f.call(root, url, init).catch(function (e) {
      throw ApiError(0, 'Network error: ' + (e && e.message ? e.message : 'request failed'));
    });
  }
  function fail(res) {
    return res.text().then(function (t) {
      var body = null;
      try { body = JSON.parse(t); } catch (e) { /* not JSON */ }
      throw ApiError(res.status, detailOf(body, t && t.length < 300 ? t : res.statusText || ('HTTP ' + res.status)));
    });
  }
  function json(url, init) {
    return doFetch(url, init).then(function (res) { return res.ok ? res.json() : fail(res); });
  }
  function post(url, body) { return json(url, { method: 'POST', body: body }); }
  function form(fields) {
    var fd = new root.FormData();
    Object.keys(fields).forEach(function (k) { if (fields[k] !== undefined && fields[k] !== null) fd.append(k, fields[k]); });
    return fd;
  }

  /* ── Endpoints ─────────────────────────────────────────────────────────── */
  function status() { return json('/api/status'); }                      // {live, samples[]} (+ model, provider if B1)
  function newSession() { return post('/api/session'); }                 // {session}
  function listParts(session) { return json('/api/parts' + q({ session: session })); }   // {session, parts[]}
  function savePart(fd) { return post('/api/parts', fd); }               // {part, parts[]} (FormData built by intake.js)
  function uploadBatch(fd) { return post('/api/parts/upload-batch', fd); }
  function saveNotes(s, p, notes) {
    return post('/api/parts/' + enc(s) + '/' + enc(p) + '/notes', form({ notes: notes }));
  }
  function getRegions(s, p) { return json('/api/parts/' + enc(s) + '/' + enc(p) + '/regions'); }
  function saveRegions(s, p, body) {
    return json('/api/parts/' + enc(s) + '/' + enc(p) + '/regions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  }
  function saveMarkedView(s, p, blob) {
    return post('/api/parts/' + enc(s) + '/' + enc(p) + '/marked-view', form({ file: blob }));
  }
  function recordingCapability() { return json('/api/recording/capability'); }   // {available, backend, encoder, reason}
  function partOutputs(s, p) { return json('/api/parts/' + enc(s) + '/' + enc(p) + '/outputs'); }
  function partScoring(s, p) { return json('/api/parts/' + enc(s) + '/' + enc(p) + '/scoring'); }
  /** {session, part, feedback?, no_cache?, record?}. no_cache and record are sent only when true. */
  function runPart(o) {
    var f = { session: o.session, part: o.part, feedback: o.feedback || '' };
    if (o.no_cache) f.no_cache = 'true';
    if (o.record) f.record = 'true';                                     // "Record Pipeline Run": the SolidWorks build only
    return post('/api/run-part', form(f));                               // {id, part}
  }
  function demo(sample) {
    return json('/api/demo', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sample: sample || null }) });               // {id}
  }
  function runOutputs(id) { return json('/api/runs/' + enc(id) + '/outputs'); }
  function runFiles(id) { return json('/api/runs/' + enc(id) + '/files'); }
  function cancel(id) { return post('/api/runs/' + enc(id) + '/cancel'); }
  function runHistory() { return json('/api/run-history'); }
  function clearHistory() { return post('/api/run-history/clear'); }

  /** Server-sent log. handlers: {onLine(text), onDone(exitCode), onError(event), onOpen()}.
      Every connection replays from line 0; callers de-duplicate (ARCH 6.6).
      Returns {close()}. */
  function openLog(id, h) {
    h = h || {};
    var ES = root.EventSource;
    if (typeof ES !== 'function') throw ApiError(0, 'EventSource is not available');
    var es = new ES('/api/runs/' + enc(id) + '/log');
    es.onmessage = function (ev) { if (h.onLine) h.onLine(ev.data); };
    es.addEventListener('done', function (ev) {
      var n = parseInt(ev.data, 10);
      es.close();
      if (h.onDone) h.onDone(isNaN(n) ? null : n);
    });
    if (h.onOpen) es.onopen = h.onOpen;
    es.onerror = function (ev) { if (h.onError) h.onError(ev); };
    return { close: function () { es.close(); } };
  }

  /** CAD intake. Resolves to {kind:'layouts', layouts[], sourceFormat} when the file has
      several sheets and none was chosen, else {kind:'image', blob, sourceFormat,
      staticPreview, tool, layout}. */
  function convertCad(file, layout) {
    var fd = form({ file: file, layout: layout || '' });
    return doFetch('/api/convert-dwg', { method: 'POST', body: fd }).then(function (res) {
      if (!res.ok) return fail(res);
      var ct = (res.headers.get('Content-Type') || '').toLowerCase();
      var meta = {
        sourceFormat: res.headers.get('X-Source-Format') || '',
        staticPreview: res.headers.get('X-Static-Preview') === '1',
        tool: res.headers.get('X-Conversion-Tool') || '',
        layout: res.headers.get('X-Layout') || ''
      };
      if (ct.indexOf('application/json') !== -1) {
        return res.json().then(function (j) {
          return { kind: 'layouts', layouts: j.layouts || [], sourceFormat: j.source_format || meta.sourceFormat };
        });
      }
      return res.blob().then(function (blob) { return Object.assign({ kind: 'image', blob: blob }, meta); });
    });
  }

  /* ── URL builders (no network) ─────────────────────────────────────────── */
  function t(v) { return v === undefined || v === null ? '' : '?t=' + enc(v); }
  function partBase(s, p) { return '/api/parts/' + enc(s) + '/' + enc(p); }
  var urls = {
    thumbURL: function (s, p, bust) { return partBase(s, p) + '/thumb.jpg' + t(bust); },
    overviewURL: function (s, p, bust) { return partBase(s, p) + '/overview.jpg' + t(bust); },
    markedViewURL: function (s, p, bust) { return partBase(s, p) + '/marked-view.jpg' + t(bust); },
    partStlURL: function (s, p, mtime) { return partBase(s, p) + '/model.stl' + t(mtime); },
    partFileURL: function (s, p, rel) { return partBase(s, p) + '/file/' + encPath(rel); },
    /* Automatic post-run Engineering Markup (NOT the human pre-run marked-view.jpg above). */
    engineeringMarkupURL: function (s, p, key) { return partBase(s, p) + '/engineering-markup' + t(key); },
    engineeringMarkupPdfURL: function (s, p, key) { return partBase(s, p) + '/engineering-markup.pdf' + t(key); },
    engineeringMarkupPageURL: function (s, p, page, key) { return partBase(s, p) + '/engineering-markup/page/' + (parseInt(page, 10) || 1) + '.png' + t(key); },
    /* SolidWorks build recording (Record Pipeline Run). The video URL carries the manifest key so a new run is never cached. */
    recordingURL: function (s, p, key) { return partBase(s, p) + '/recording' + t(key); },
    recordingVideoURL: function (s, p, key) { return partBase(s, p) + '/recording.video' + t(key); },
    recordingPosterURL: function (s, p, key) { return partBase(s, p) + '/recording-poster.jpg' + t(key); },
    partLedgerURL: function (s, p) { return partBase(s, p) + '/ledger.jsonl'; },
    reviewFlag: function (s, p, id, state, reason) {
      return json(partBase(s, p) + '/flags/' + enc(id) + '/review', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state: state, reason: reason || '' }) });
    },
    runStlURL: function (id, bust) { return '/api/runs/' + enc(id) + '/model.stl' + t(bust); },
    runDownloadURL: function (id, rel) { return '/api/runs/' + enc(id) + '/download/' + encPath(rel); },
    runZipURL: function (id) { return '/api/runs/' + enc(id) + '/zip'; },
    runSourceURL: function (id) { return '/api/runs/' + enc(id) + '/source.jpg'; }
  };

  var api = { ApiError: ApiError, status: status, newSession: newSession, listParts: listParts,
    savePart: savePart, uploadBatch: uploadBatch, saveNotes: saveNotes, getRegions: getRegions,
    saveRegions: saveRegions, saveMarkedView: saveMarkedView, partOutputs: partOutputs, partScoring: partScoring, runPart: runPart, recordingCapability: recordingCapability,
    demo: demo, runOutputs: runOutputs, runFiles: runFiles, cancel: cancel, openLog: openLog,
    runHistory: runHistory, clearHistory: clearHistory, convertCad: convertCad };
  Object.keys(urls).forEach(function (k) { api[k] = urls[k]; });
  return api;
});
