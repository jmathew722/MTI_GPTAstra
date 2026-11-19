'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const api = H.core('api.js');

let calls;
function reply(status, body, headers) {
  const isBlob = body instanceof Uint8Array;
  const text = isBlob ? '' : (typeof body === 'string' ? body : JSON.stringify(body));
  const h = Object.assign({}, headers || {});
  if (!isBlob && typeof body !== 'string' && !h['Content-Type']) h['Content-Type'] = 'application/json';
  return { ok: status >= 200 && status < 300, status, statusText: 'S' + status,
    headers: { get: (k) => { const key = Object.keys(h).find((x) => x.toLowerCase() === k.toLowerCase()); return key ? h[key] : null; } },
    json: async () => JSON.parse(text), text: async () => text, blob: async () => ({ size: 3, blob: true }) };
}
function mock(fn) { calls = []; global.fetch = async (url, init) => { calls.push({ url, init: init || {} }); return fn(url, init || {}); }; }
test.afterEach(() => { delete global.fetch; });
test.before(() => { global.FormData = global.FormData || class { constructor() { this.m = []; } append(k, v) { this.m.push([k, v]); } }; });
const fields = (fd) => Object.fromEntries(Array.from(fd.entries ? fd.entries() : fd.m));

test('GET endpoints build the right URLs', async () => {
  mock(() => reply(200, { ok: 1 }));
  await api.status(); await api.listParts('s 1'); await api.runOutputs('r1'); await api.partOutputs('s', 'A/B');
  await api.getRegions('s', 'A'); await api.runHistory(); await api.runFiles('r1');
  assert.deepEqual(calls.map((c) => c.url), ['/api/status', '/api/parts?session=s%201', '/api/runs/r1/outputs', '/api/parts/s/A%2FB/outputs',
    '/api/parts/s/A/regions', '/api/run-history', '/api/runs/r1/files']);
  assert.ok(calls.every((c) => !c.init.method));
});

test('POST endpoints use POST and the documented bodies', async () => {
  mock(() => reply(200, { id: 'r1', part: 'A' }));
  await api.newSession(); await api.cancel('r1'); await api.clearHistory();
  assert.deepEqual(calls.map((c) => [c.init.method, c.url]), [['POST', '/api/session'], ['POST', '/api/runs/r1/cancel'], ['POST', '/api/run-history/clear']]);
  calls.length = 0;
  await api.runPart({ session: 's', part: 'A' });
  assert.deepEqual(fields(calls[0].init.body), { session: 's', part: 'A', feedback: '' });      // no_cache omitted unless true
  await api.runPart({ session: 's', part: 'A', feedback: 'move hole', no_cache: true });
  assert.deepEqual(fields(calls[1].init.body), { session: 's', part: 'A', feedback: 'move hole', no_cache: 'true' });
  await api.demo('117C'); await api.demo();
  assert.equal(calls[2].url, '/api/demo'); assert.equal(calls[2].init.body, '{"sample":"117C"}');
  assert.equal(calls[3].init.body, '{"sample":null}');
  assert.equal(calls[2].init.headers['Content-Type'], 'application/json');
  await api.saveRegions('s', 'A', { regions: [], origin: null, datums: [] });
  assert.equal(calls[4].url, '/api/parts/s/A/regions'); assert.equal(calls[4].init.method, 'POST');
  assert.equal(JSON.parse(calls[4].init.body).regions.length, 0);
  await api.saveNotes('s', 'A', 'hole d=0.25');
  assert.deepEqual(fields(calls[5].init.body), { notes: 'hole d=0.25' });
});

test('errors become ApiError with FastAPI detail', async () => {
  mock(() => reply(400, { detail: 'No ANTHROPIC_API_KEY set' }));
  await assert.rejects(api.runPart({ session: 's', part: 'A' }), (e) => e instanceof api.ApiError && e.name === 'ApiError' && e.status === 400 && e.detail === 'No ANTHROPIC_API_KEY set' && e instanceof Error);
  mock(() => reply(422, { detail: [{ loc: ['body'], msg: 'field required' }, { msg: 'bad' }] }));
  await assert.rejects(api.status(), (e) => e.status === 422 && e.detail === 'field required; bad');
  mock(() => reply(404, { detail: 'Unknown run id' }));
  await assert.rejects(api.runOutputs('zz'), (e) => e.status === 404 && /Unknown run id/.test(e.message));
  mock(() => reply(500, 'Internal Server Error'));
  await assert.rejects(api.status(), (e) => e.status === 500 && e.detail === 'Internal Server Error');
});

test('network failure is status 0', async () => {
  global.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await assert.rejects(api.status(), (e) => e.name === 'ApiError' && e.status === 0 && /Network error/.test(e.detail));
  delete global.fetch;
  await assert.rejects(api.status(), (e) => e.status === 0);
});

test('convertCad: image response, layouts response, error', async () => {
  mock(() => reply(200, new Uint8Array([1, 2, 3]), { 'Content-Type': 'image/png', 'X-Source-Format': 'edrw', 'X-Static-Preview': '1', 'X-Conversion-Tool': 'preview_extract' }));
  const img = await api.convertCad({ name: 'a.edrw' }, '');
  assert.equal(img.kind, 'image'); assert.equal(img.staticPreview, true); assert.equal(img.sourceFormat, 'edrw'); assert.equal(img.tool, 'preview_extract');
  assert.equal(img.blob.blob, true);
  assert.equal(fields(calls[0].init.body).layout, '');
  mock(() => reply(200, { layouts: ['Model', 'Sheet1'], source_format: 'dxf' }));
  const lay = await api.convertCad({ name: 'a.dxf' });
  assert.deepEqual(lay, { kind: 'layouts', layouts: ['Model', 'Sheet1'], sourceFormat: 'dxf' });
  mock(() => reply(422, { detail: 'Install the ODA File Converter' }));
  await assert.rejects(api.convertCad({ name: 'a.dwg' }), (e) => e.status === 422 && /ODA/.test(e.detail));
  mock(() => reply(200, new Uint8Array([1]), { 'Content-Type': 'image/png', 'X-Source-Format': 'dxf', 'X-Layout': 'Model', 'X-Conversion-Tool': 'cache' }));
  const plain = await api.convertCad({ name: 'a.dxf' }, 'Model');
  assert.equal(plain.staticPreview, false); assert.equal(plain.layout, 'Model');
});

test('URL builders', () => {
  assert.equal(api.thumbURL('s', 'A'), '/api/parts/s/A/thumb.jpg');
  assert.equal(api.thumbURL('s', 'A', 5), '/api/parts/s/A/thumb.jpg?t=5');
  assert.equal(api.overviewURL('s', 'A B'), '/api/parts/s/A%20B/overview.jpg');
  assert.equal(api.markedViewURL('s', 'A'), '/api/parts/s/A/marked-view.jpg');
  // the automatic post-run Engineering Markup is a different artifact from the human marked view
  assert.equal(api.engineeringMarkupURL('s', 'A', 'k1'), '/api/parts/s/A/engineering-markup?t=k1');
  assert.equal(api.engineeringMarkupPdfURL('s', 'A B'), '/api/parts/s/A%20B/engineering-markup.pdf');
  assert.equal(api.engineeringMarkupPageURL('s', 'A', 2, 'k1'), '/api/parts/s/A/engineering-markup/page/2.png?t=k1');
  assert.equal(api.engineeringMarkupPageURL('s', 'A', 'x'), '/api/parts/s/A/engineering-markup/page/1.png');
  assert.notEqual(api.engineeringMarkupURL('s', 'A'), api.markedViewURL('s', 'A'));
  assert.equal(api.partStlURL('s', 'A', 1700000100), '/api/parts/s/A/model.stl?t=1700000100');
  assert.equal(api.partFileURL('s', 'A', '117C/macros/01 base.vba'), '/api/parts/s/A/file/117C/macros/01%20base.vba');
  assert.equal(api.runStlURL('r1'), '/api/runs/r1/model.stl');
  assert.equal(api.runDownloadURL('r1', 'out/a b.txt'), '/api/runs/r1/download/out/a%20b.txt');
  assert.equal(api.runZipURL('r1'), '/api/runs/r1/zip');
});

test('openLog: lines, done with exit code, error callback, close', () => {
  const made = [];
  global.EventSource = class { constructor(url) { this.url = url; this.l = {}; this.closed = false; made.push(this); }
    addEventListener(t, f) { this.l[t] = f; } close() { this.closed = true; } };
  try {
    const got = { lines: [], done: [], err: 0 };
    const h = api.openLog('r1', { onLine: (t) => got.lines.push(t), onDone: (c) => got.done.push(c), onError: () => { got.err++; } });
    const es = made[0];
    assert.equal(es.url, '/api/runs/r1/log');
    es.onmessage({ data: '[STAGE] Done' }); es.onmessage({ data: '' });
    assert.deepEqual(got.lines, ['[STAGE] Done', '']);
    es.onerror({}); assert.equal(got.err, 1);
    es.l.done({ data: '8' });
    assert.deepEqual(got.done, [8]); assert.equal(es.closed, true);
    const h2 = api.openLog('r2', {}); made[1].l.done({ data: 'x' });
    h2.close(); h.close();
  } finally { delete global.EventSource; }
  assert.throws(() => api.openLog('r', {}), (e) => e.name === 'ApiError');
});

test('every endpoint named in ARCH 5 exists as a function', () => {
  for (const n of ['status', 'newSession', 'listParts', 'savePart', 'uploadBatch', 'saveNotes', 'getRegions', 'saveRegions', 'saveMarkedView',
    'partOutputs', 'runPart', 'demo', 'runOutputs', 'runFiles', 'cancel', 'openLog', 'runHistory', 'clearHistory', 'convertCad',
    'thumbURL', 'overviewURL', 'markedViewURL', 'engineeringMarkupURL', 'engineeringMarkupPdfURL', 'engineeringMarkupPageURL', 'partStlURL', 'partFileURL', 'runStlURL', 'runDownloadURL', 'runZipURL']) {
    assert.equal(typeof api[n], 'function', n);
  }
});
