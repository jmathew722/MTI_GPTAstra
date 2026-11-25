'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { logic } = require('./_helpers');
const V = logic('estimateview.js');

const est = (o = {}) => ({ inputs: 1,
  time: { available: true, low: 120, high: 240, n_runs: 12, limited: false },
  cost: { available: true, low: '0.120000', high: '0.200000', n_runs: 12, limited: false },
  concurrency: 1, serialized_reason: 'one at a time', ...o });

test('time and money formatting, units and range', () => {
  assert.equal(V.fmtDur(45), '45 s');
  assert.equal(V.fmtDur(120), '2 min');
  assert.equal(V.fmtDur(3600 * 2 + 600), '2 h 10 min');
  assert.equal(V.fmtDur(-1), '');
  assert.equal(V.fmtRange(120, 240), '2–4 min');
  assert.equal(V.fmtRange(30, 200), '30 s – 3.3 min');
  assert.equal(V.fmtRange(100, 101), '1.7 min');
  assert.equal(V.usd('0.12'), '$0.12');
  assert.equal(V.usd(1.234), '$1.23');
  assert.equal(V.usdRange('0.120000', '0.200000'), '$0.12–$0.20');
});

test('small charges never collapse to $0.00; a true zero stays a zero; garbage is blank', () => {
  assert.equal(V.usd('0.000123'), '$0.0001');
  assert.equal(V.usd('0.004'), '$0.0040');
  assert.equal(V.usd(0.00000123), '$0.0000012');
  assert.equal(V.usd(0), '$0.00');
  assert.equal(V.usd(null), '');
  assert.equal(V.usd('abc'), '');
});

test('describe: ready shows both ranges and the basis', () => {
  const d = V.describe(est());
  assert.equal(d.time, 'Estimated time: 2–4 min');
  assert.equal(d.cost, 'Estimated cost: $0.12–$0.20');
  assert.match(d.detail, /1 input/);
  assert.match(d.detail, /12 finished runs/);
  assert.equal(d.state, 'ready');
});

test('describe: unknown is never zero', () => {
  const d = V.describe(est({ time: { available: false, reason: 'No finished runs to estimate from yet.' }, cost: { available: false, reason: 'No priced runs to estimate from yet (cost is unavailable, not zero).' } }));
  assert.equal(d.time, 'Estimated time: insufficient history');
  assert.equal(d.cost, 'Estimated cost: unavailable');
  assert.equal(d.state, 'unavailable');
  assert.ok(!/\$0/.test(d.cost));
});

test('describe: batch totals, limited history, empty, loading and error states', () => {
  const b = V.describe(est({ inputs: 4, time: { available: true, low: 480, high: 960, n_runs: 2, limited: true } }));
  assert.match(b.detail, /4 inputs/);
  assert.match(b.detail, /one at a time/);
  assert.match(b.detail, /limited history/);
  assert.equal(V.describe(est({ inputs: 0 })).state, 'empty');
  assert.equal(V.describe(null).state, 'loading');
  const e = V.describe(null, 'Server unreachable');
  assert.equal(e.state, 'error');
  assert.match(e.cost, /unavailable/);
});

test('remaining: only with reliable history, never negative, overrun is honest', () => {
  assert.equal(V.remaining(est({ time: { available: true, low: 120, high: 240, limited: true } }), 1000), null);
  assert.equal(V.remaining(est({ time: { available: false } }), 1000), null);
  const r = V.remaining(est(), 60000);
  assert.equal(r.overrun, false);
  assert.equal(r.text, '1–3 min left');
  const over = V.remaining(est(), 600000);
  assert.equal(over.overrun, true);
  assert.equal(over.text, 'taking longer than usual');
});

test('actual: live elapsed, final from the store, final from the persisted last run, unknown cost stays unknown', () => {
  const live = V.actual({ state: 'running', startedAt: 1000 }, null, 66000);
  assert.deepEqual([live.kind, live.elapsed], ['live', '1.1 min']);
  const fin = V.actual({ state: 'succeeded', startedAt: 1000, finishedAt: 126000 }, null, 0);
  assert.deepEqual([fin.kind, fin.elapsed], ['final', '2.1 min']);
  const persisted = V.actual({}, { run: { state: 'succeeded', finished_at: 'x', seconds: 207.2, cost_usd: '0.260560', cost_status: 'priced' } });
  assert.deepEqual([persisted.kind, persisted.elapsed, persisted.cost], ['final', '3.5 min', '$0.26']);
  const unpriced = V.actual({}, { run: { state: 'succeeded', finished_at: 'x', seconds: 10, cost_usd: null, cost_status: 'unpriced' } });
  assert.equal(unpriced.cost, '');
  assert.equal(unpriced.costStatus, 'unpriced');
  assert.equal(V.actual({}, null), null);
});
