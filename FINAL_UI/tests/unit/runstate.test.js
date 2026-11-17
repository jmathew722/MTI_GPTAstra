'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const R = require('./_helpers').logic('runstate.js');

const done = (exit, extra) => Object.assign({ hasId: true, done: true, exit, cancelled: false }, extra || {});

test('idle, queued and running', () => {
  assert.equal(R.deriveRunState({ hasId: false, done: false }), 'idle');
  assert.equal(R.deriveRunState({ hasId: false, launching: true }), 'queued');
  assert.equal(R.deriveRunState({ hasId: false, queued: true }), 'queued');
  assert.equal(R.deriveRunState({ hasId: true, done: false }), 'running');
});

test('every exit code in the table', () => {
  assert.equal(R.deriveRunState(done(0)), 'succeeded');
  assert.equal(R.deriveRunState(done(8, { summary: { status: 'NOT READY' } })), 'succeeded_with_warnings');
  assert.equal(R.deriveRunState(done(8)), 'succeeded_with_warnings');          // summary unavailable
  assert.equal(R.deriveRunState(done(8, { summary: { status: 'BLOCKED' } })), 'failed');
  assert.equal(R.deriveRunState(done(8, { summary: { status: 'ERROR' } })), 'failed');
  for (const code of [2, 3, 4, 5, 6, 7, 127, 1, -9]) assert.equal(R.deriveRunState(done(code)), 'failed', 'exit ' + code);
});

test('cancelled wins over every exit code', () => {
  for (const code of [0, 8, 2, -15, 127]) assert.equal(R.deriveRunState(done(code, { cancelled: true })), 'cancelled');
});

test('verdict rows', () => {
  const v = R.deriveVerdict;
  assert.equal(v({ summary: { status: 'READY' }, stlSource: 'solidworks', stlFresh: true, kind: 'part', exit: 0 }), 'passed');
  // READY without a built model
  assert.equal(v({ summary: { status: 'READY' }, stlSource: 'prevalidation', stlFresh: true, kind: 'part', exit: 0 }), 'passed_unbuilt');
  assert.equal(v({ summary: { status: 'READY' }, stlSource: 'solidworks', stlFresh: false, kind: 'part', exit: 0 }), 'passed_unbuilt');
  assert.equal(v({ summary: { status: 'READY' }, stlSource: null, stlFresh: false, kind: 'part', exit: 0 }), 'passed_unbuilt');
  assert.equal(v({ summary: { status: 'NOT READY' }, kind: 'part', exit: 8 }), 'flags');
  assert.equal(v({ summary: { status: 'BLOCKED' }, kind: 'part', exit: 8 }), 'failed');
  assert.equal(v({ summary: { status: 'ERROR' }, kind: 'part', exit: 8 }), 'failed');
  assert.equal(v({ summary: { status: 'READY' }, mustMeet: { stage: 'post_build', ok: false }, stlSource: 'solidworks', stlFresh: true, kind: 'part' }), 'failed');
  assert.equal(v({ summary: null, mustMeet: { stage: 'post_build', ok: false }, kind: 'part' }), 'failed');
  assert.equal(v({ summary: { status: 'READY' }, mustMeet: { stage: 'prevalidation', ok: false }, stlSource: 'solidworks', stlFresh: true, kind: 'part' }), 'passed');
  assert.equal(v({ summary: null, mustMeet: null, kind: 'part', exit: 8 }), 'unknown');
  assert.equal(v({ summary: { status: 'READY' }, cancelled: true, kind: 'part' }), 'unknown');
});

test('demo verdicts', () => {
  assert.equal(R.deriveVerdict({ kind: 'demo', exit: 0 }), 'passed_unbuilt');
  for (const e of [4, 6, 7]) assert.equal(R.deriveVerdict({ kind: 'demo', exit: e }), 'failed');
  assert.equal(R.deriveVerdict({ kind: 'demo', exit: 2 }), 'unknown');
});

test('stlFresh compares stl_mtime with floor(started)', () => {
  assert.equal(R.stlFresh({ stl_mtime: 100, started: 100.9 }), true);
  assert.equal(R.stlFresh({ stl_mtime: 99, started: 100.2 }), false);
  assert.equal(R.stlFresh({ stl_mtime: 0, started: 0 }), false);
  assert.equal(R.stlFresh(null), false);
  assert.equal(R.stlFresh({ stl_mtime: 105 }, 100.5), true);
  assert.equal(R.stlFresh({ stl_mtime: 105 }), false);
});

test('summaryFromConsole takes the last N/M READY match', () => {
  const lines = ['  Summary CSV: a.csv  (0/2 READY)', 'x', '  Summary CSV: b.csv  (2/2 READY)'];
  assert.deepEqual(R.summaryFromConsole(lines), { status: 'READY', n_ready: 2, n_total: 2, fallback: true });
  assert.equal(R.summaryFromConsole(['  (1/3 READY)']).status, 'NOT READY');
  assert.equal(R.summaryFromConsole(['nothing']), null);
  assert.equal(R.summaryFromConsole([]), null);
});
