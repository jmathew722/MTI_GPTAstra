'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const S = H.logic('stages.js');

const P = '[gptastra-event] ';
let n = 0;
function ev(seq, kind, payload, o) {
  o = o || {};
  return P + JSON.stringify({ schema_version: 1, event_id: 'e' + (++n), run_id: o.run || 'run_a', attempt: o.attempt || 1,
    part_id: 'P1', seq, occurred_at: '2026-11-18T00:00:00.000Z', kind, payload: payload || {} });
}
function prog(pct, extra) {
  return Object.assign({ phase: 'solidworks_generation', operation: 'create_feature', label: 'Creating feature 7 of 18',
    percent: pct, indeterminate: pct === null, completed_units: 6, total_units: 18, unit: 'features', terminal: null }, extra || {});
}
function replay(lines, kind) { return lines.reduce((t, l) => S.reduce(t, l), S.initial(kind || 'part')); }

test('structured percent is the backend value, not a marker count', () => {
  const t = replay(['           INFO     [stage] extraction: reading 1 image(s) for P1', ev(1, 'run.started'), ev(2, 'progress.updated', prog(61.2))]);
  assert.equal(S.percent(t), 61);                       // integer ring; floor never rounds up to a false 100
  const v = S.view(t);
  assert.deepEqual([v.progress.source, v.progress.percent, v.progress.operation, v.progress.completed, v.progress.total, v.progress.unit],
    ['structured', 61.2, 'create_feature', 6, 18, 'features']);
  assert.equal(v.progress.indeterminate, false);
});

test('before a denominator is known the structured state is indeterminate, with no number and no marker fallback', () => {
  const t = replay(['           INFO     [stage] build_plan_gate1: gate1=OK planned=3 questions=0', ev(1, 'progress.updated', prog(null, { phase: 'ingest', operation: 'ingest_drawing', total_units: null }))]);
  assert.equal(S.percent(t), null);
  assert.equal(S.view(t).progress.indeterminate, true);
});

test('lines with a logger prefix before the event tag still parse; other lines are ignored', () => {
  const t = replay(['[09:00:00] INFO     ' + ev(1, 'progress.updated', prog(10)), P + '{bad json', 'plain text']);
  assert.equal(S.percent(t), 10);
});

test('duplicates, late events, regressions and stale runs never move the state', () => {
  let t = replay([ev(1, 'run.started', {}, { run: 'run_b', attempt: 2 }), ev(2, 'progress.updated', prog(50), { run: 'run_b', attempt: 2 })]);
  const before = t;
  for (const l of [ev(2, 'progress.updated', prog(60), { run: 'run_b', attempt: 2 }),   // duplicate seq
                   ev(1, 'progress.updated', prog(70), { run: 'run_b', attempt: 2 }),   // late
                   ev(3, 'progress.updated', prog(20), { run: 'run_b', attempt: 2 }),   // regression
                   ev(9, 'progress.updated', prog(99), { run: 'run_a', attempt: 1 })]) { // stale run
    t = S.reduce(t, l);
  }
  assert.equal(S.percent(t), 50);
  assert.equal(t.tel.last_seq, before.tel.last_seq);
});

test('a retry (run.started of a newer attempt) replaces the old attempt', () => {
  let t = replay([ev(1, 'run.started', {}, { run: 'run_a' }), ev(2, 'progress.updated', prog(80), { run: 'run_a' })]);
  t = S.reduce(t, ev(1, 'run.started', {}, { run: 'run_c', attempt: 2 }));
  assert.equal(t.tel.run_id, 'run_c');
  assert.equal(S.percent(t), null);
});

test('failed and cancelled runs stop at the last truthful percentage', () => {
  for (const [kind, exit, cancelled] of [['run.failed', 1, false], ['run.cancelled', 1, true]]) {
    let t = replay([ev(1, 'run.started'), ev(2, 'progress.updated', prog(63)), ev(3, kind, { reason: 'x' })]);
    t = S.finalize(t, { exit, cancelled, payload: null });
    assert.equal(S.percent(t), 63, kind);
    assert.equal(S.view(t).progress.percent, 63);
  }
});

test('100 appears only after the backend terminal completed event', () => {
  let t = replay([ev(1, 'run.started'), ev(2, 'progress.updated', prog(99.9))]);
  t = S.finalize(t, { exit: 0, payload: null });      // process exited 0 but the stream never completed
  assert.equal(S.percent(t), 99);
  t = replay([ev(1, 'run.started'), ev(2, 'progress.updated', prog(99.9)), ev(3, 'progress.updated', prog(100, { terminal: 'completed' })), ev(4, 'run.completed')]);
  assert.equal(S.percent(S.finalize(t, { exit: 0, payload: null })), 100);
});

test('legacy runs keep the marker count and are labeled as such', () => {
  const t = replay(['           INFO     [stage] extraction: reading 1 image(s) for P1']);
  assert.equal(S.view(t).progress.source, 'legacy_markers');
  assert.equal(S.percent(t), 0);
});

test('reduce stays pure on structured events', () => {
  const t0 = S.initial('part');
  const frozen = JSON.stringify([t0.tel, Array.from(t0.seen)]);
  S.reduce(t0, ev(1, 'progress.updated', prog(5)));
  assert.equal(JSON.stringify([t0.tel, Array.from(t0.seen)]), frozen);
});

test('applyTelemetry adopts a server snapshot (reconnect after refresh) and refuses legacy or older ones', () => {
  const snap = { source: 'structured', run_id: 'run_a', attempt: 1, last_seq: 12, terminal: null, progress: prog(40), cost: null };
  let t = S.applyTelemetry(S.initial('part'), snap);
  assert.equal(S.percent(t), 40);
  assert.equal(S.applyTelemetry(t, { source: 'legacy_log_parser', progress: null }), t);
  assert.equal(S.applyTelemetry(t, Object.assign({}, snap, { last_seq: 5, progress: prog(10) })), t);
  assert.equal(S.percent(S.applyTelemetry(t, Object.assign({}, snap, { last_seq: 20, progress: prog(55) }))), 55);
});
