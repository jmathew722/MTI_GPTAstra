'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const C = H.logic('collapsibles.js');

test('fmtShort: short elapsed text; unusable input is N/A, never negative', () => {
  assert.equal(C.fmtShort(42000), '42s');
  assert.equal(C.fmtShort(185000), '3m 05s');
  assert.equal(C.fmtShort(3720000), '1h 02m');
  for (const v of [-1, NaN, null, undefined, 'x', Infinity]) assert.equal(C.fmtShort(v), 'N/A');
});

test('leftText never goes negative', () => {
  assert.equal(C.leftText(null), 'N/A');
  assert.equal(C.leftText({ overrun: true, text: 'taking longer than usual' }), 'taking longer than usual');
  assert.equal(C.leftText({ overrun: false, text: '1-2 min left' }), '1-2 min');
});

test('materialSummary: no part, pending, error, not specified, verified, attention', () => {
  assert.deepEqual(C.materialSummary({ hasPart: false }), { text: 'No material specified', tone: 'none', warn: '' });
  assert.equal(C.materialSummary({ hasPart: true, entry: null }).text, 'Pending');
  assert.equal(C.materialSummary({ hasPart: true, entry: { state: 'ready', data: { evaluated: false } } }).text, 'Pending');
  const err = C.materialSummary({ hasPart: true, entry: { state: 'error', error: 'boom' } });
  assert.equal(err.text, 'Unavailable'); assert.match(err.warn, /boom/);
  const ns = C.materialSummary({ hasPart: true, entry: { state: 'ready', data: { evaluated: true } }, status: { id: 'not_specified', label: 'No material specified on drawing', tone: 'blue' }, title: 'x' });
  assert.equal(ns.text, 'No material specified'); assert.equal(ns.warn, '');
  const ok = C.materialSummary({ hasPart: true, entry: { state: 'ready', data: { evaluated: true } }, status: { id: 'assigned_verified', label: 'Verified on part', tone: 'green' }, title: 'Steel 1018' });
  assert.equal(ok.text, 'Steel 1018'); assert.equal(ok.warn, '');
  const bad = C.materialSummary({ hasPart: true, entry: { state: 'ready', data: { evaluated: true } }, status: { id: 'unmatched', label: 'Not in catalog', tone: 'amber' }, title: 'Unobtainium' });
  assert.equal(bad.tone, 'amber'); assert.match(bad.warn, /Not in catalog/);
});

test('materialSummary keeps a library error visible', () => {
  assert.match(C.materialSummary({ hasPart: false, libError: 'unreadable' }).warn, /unreadable/);
});

test('runtimeSummary: idle, running with elapsed, finished states, estimate error', () => {
  assert.equal(C.runtimeSummary({}).text, 'Idle');
  assert.deepEqual(C.runtimeSummary({ runState: 'running', elapsedMs: 72000 }), { text: 'Running · 1m 12s', tone: 'run' });
  assert.equal(C.runtimeSummary({ runState: 'running', elapsedMs: -5 }).text, 'Running');
  assert.equal(C.runtimeSummary({ runState: 'queued', elapsedMs: 1000 }).text, 'Queued · 1s');
  assert.equal(C.runtimeSummary({ runState: 'failed', lastElapsedMs: 5000 }).tone, 'err');
  assert.equal(C.runtimeSummary({ runState: 'succeeded' }).text, 'Completed');
  assert.equal(C.runtimeSummary({ estState: 'error' }).text, 'Estimate unavailable');
});
