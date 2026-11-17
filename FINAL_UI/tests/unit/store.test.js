'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const Store = H.core('store.js');
const S = H.logic('stages.js');
const CSV = H.logic('csv.js');
const tick = () => new Promise((r) => setImmediate(r));
const fresh = () => Store.createStore(Store.initialState());

test('initial state has the ARCH 4.2 shape and persisted ui defaults', () => {
  const s = Store.initialState();
  for (const k of ['route', 'server', 'session', 'parts', 'intake', 'markup', 'run', 'batch', 'history', 'outputs', 'viewer3d', 'ui']) assert.ok(k in s, k);
  assert.equal(s.run.state, 'idle');
  assert.equal(s.server.model, null);
  assert.deepEqual(s.ui.inspectorOpen, { setup: true, actions: true, corrections: true, export: true });
  assert.equal(s.ui.splitRatio, 0.5);
  assert.equal(s.ui.drawerMode, 'results'); assert.equal(s.ui.maximized, null); assert.equal(s.ui.narrowTab, '2d');
  assert.notEqual(Store.initialState().ui.inspectorOpen, s.ui.inspectorOpen);   // fresh objects
});

test('get / set shallow-merge / update by path', () => {
  const st = fresh();
  st.set({ session: { id: 'abc' } });
  assert.equal(st.get().session.id, 'abc');
  const before = st.get().parts;
  st.update('parts.loading', () => true);
  assert.equal(st.get().parts.loading, true);
  assert.notEqual(st.get().parts, before);               // new object along the path
  assert.equal(before.loading, false);                   // old one untouched
  st.update(['ui', 'inspectorOpen', 'export'], (v) => !v);
  assert.equal(st.get().ui.inspectorOpen.export, false);
  assert.equal(st.get().ui.inspectorOpen.setup, true);
});

test('subscribe fires only when the selected value changes, batched in a microtask', async () => {
  const st = fresh(); const seen = [];
  const off = st.subscribe((s) => s.session.id, (n, o) => seen.push([n, o]));
  st.set({ session: { id: 'a' } }); st.set({ session: { id: 'b' } }); st.set({ session: { id: 'c' } });
  assert.deepEqual(seen, []);                            // not synchronous
  await tick();
  assert.deepEqual(seen, [['c', null]]);                 // one notification for three sets
  st.set({ route: { page: 'x', params: {} } });
  await tick();
  assert.equal(seen.length, 1);                          // unrelated change: no call
  st.set({ session: { id: 'c' } }); await tick();
  assert.equal(seen.length, 1);                          // same value: no call
  off(); st.set({ session: { id: 'd' } }); await tick();
  assert.equal(seen.length, 1);
});

test('subscribe accepts a path string; flush() runs pending notifications now', () => {
  const st = fresh(); const seen = [];
  st.subscribe('run.state', (n) => seen.push(n));
  st.dispatch('run/queued', { kind: 'part', session: 's', part: 'p' });
  st.flush();
  assert.deepEqual(seen, ['queued']);
});

test('a throwing subscriber does not stop the others', async () => {
  const st = fresh(); const seen = []; const origErr = console.error; console.error = () => {};
  st.subscribe('session.id', () => { throw new Error('boom'); });
  st.subscribe('session.id', (n) => seen.push(n));
  st.set({ session: { id: 'z' } }); await tick();
  console.error = origErr;
  assert.deepEqual(seen, ['z']);
});

test('dispatch uses the reducer table; register extends it; unknown types throw', () => {
  const st = fresh();
  st.register('test/inc', (s, p) => ({ session: { id: (s.session.id || 0) + p } }));
  st.dispatch('test/inc', 2); st.dispatch('test/inc', 3);
  assert.equal(st.get().session.id, 5);
  assert.throws(() => st.dispatch('nope/none', {}), /no reducer/);
  st.register('test/noop', () => null);
  const before = st.get(); st.dispatch('test/noop'); assert.equal(st.get(), before);
});

test('parts/select resets outputs to the new ctx', () => {
  const st = fresh();
  st.dispatch('parts/select', { session: 's', part: 'A' });
  assert.deepEqual(st.get().parts.selected, { session: 's', part: 'A' });
  assert.deepEqual(st.get().outputs.ctx, { kind: 'part', session: 's', part: 'A' });
  st.dispatch('parts/select', null);
  assert.equal(st.get().parts.selected, null); assert.equal(st.get().outputs.ctx, null);
});

test('outputs: stale responses for a different ctx are dropped', () => {
  const st = fresh();
  st.dispatch('parts/select', { session: 's', part: 'A' });
  const ctxA = { kind: 'part', session: 's', part: 'A' };
  st.dispatch('parts/select', { session: 's', part: 'B' });
  st.dispatch('outputs/loaded', { ctx: ctxA, payload: { stale: true } });          // A answered after B was selected
  assert.equal(st.get().outputs.payload, null);
  st.dispatch('outputs/loaded', { ctx: { kind: 'part', session: 's', part: 'B' }, payload: { ok: 1 } });
  assert.deepEqual(st.get().outputs.payload, { ok: 1 });
  st.dispatch('outputs/error', { ctx: ctxA, error: 'x' });
  assert.equal(st.get().outputs.error, null);
  st.dispatch('outputs/ctx', { ctx: { kind: 'run', runId: 'r1' } });
  st.dispatch('outputs/loaded', { ctx: { kind: 'run', runId: 'r1' }, payload: { r: 1 } });
  assert.deepEqual(st.get().outputs.payload, { r: 1 });
});

test('intake reducers: add assigns ids, update by id, remove, reset', () => {
  const st = fresh();
  st.dispatch('intake/add', [{ dataURL: 'a', orientation: 'front' }, { dataURL: 'b' }]);
  const [a, b] = st.get().intake.items;
  assert.ok(a.id && b.id && a.id !== b.id); assert.equal(b.orientation, '');
  st.dispatch('intake/update', { id: b.id, patch: { orientation: 'top' } });
  assert.equal(st.get().intake.items[1].orientation, 'top');
  st.dispatch('intake/update', { patch: { nameDraft: 'P1' } });
  assert.equal(st.get().intake.nameDraft, 'P1');
  st.dispatch('intake/remove', { id: a.id });
  assert.equal(st.get().intake.items.length, 1);
  st.dispatch('intake/reset');
  assert.equal(st.get().intake.items.length, 0); assert.equal(st.get().intake.nameDraft, '');
});

test('run lifecycle: queued, started, lines feed the tracker, stale lines are dropped', () => {
  const st = fresh();
  st.dispatch('run/queued', { kind: 'part', session: 's', part: 'A' });
  assert.equal(st.get().run.state, 'queued');
  st.dispatch('run/started', { id: 'r1', startedAt: 1700000000500 });
  assert.equal(st.get().run.state, 'running');
  st.dispatch('run/line', { id: 'r1', line: '[stage] extraction: reading 1 image(s) for A' });
  st.dispatch('run/line', { id: 'other', line: '[stage] verification: sw_ok=True' });   // stale: wrong run id
  assert.equal(st.get().run.lines.length, 1);
  assert.equal(st.get().run.track.k, 0);
  st.dispatch('run/lines', { id: 'r1', lines: ['[stage] resolution: x', '[stage] build_plan_start: x'] });
  assert.equal(st.get().run.track.k, 2); assert.equal(st.get().run.lines.length, 3);
  st.dispatch('run/cancelPending');
  assert.equal(st.get().run.cancelPending, true);
});

test('run/finalized computes track, state and verdict together', () => {
  const st = fresh();
  st.dispatch('run/queued', { kind: 'part', session: 's', part: '117C' });
  st.dispatch('run/started', { id: 'r1', startedAt: 1700000000500 });
  H.lines('part_full.log').forEach((l) => st.dispatch('run/line', { id: 'r1', line: l }));
  const summary = CSV.summaryRow(H.text('summary_ready.csv'), '117C');
  st.dispatch('run/finalized', { id: 'r1', exit: 0, summary, payload: H.payload() });
  const r = st.get().run;
  assert.equal(r.state, 'succeeded'); assert.equal(r.verdict, 'passed'); assert.equal(r.exit, 0);
  assert.equal(S.percent(r.track), 100);
  assert.ok(r.finishedAt > 0);
  // a ready part whose STL is stale is not "passed"
  const st2 = fresh();
  st2.dispatch('run/queued', { kind: 'part', session: 's', part: '117C' });
  st2.dispatch('run/started', { id: 'r2', startedAt: 1700000000500 });
  H.lines('part_full.log').forEach((l) => st2.dispatch('run/line', { id: 'r2', line: l }));
  const stale = H.payload(); stale.stl_mtime = 10;
  st2.dispatch('run/finalized', { id: 'r2', exit: 0, summary, payload: stale });
  assert.equal(st2.get().run.verdict, 'passed_unbuilt');
  assert.equal(st2.get().run.track.final.stages[3].state, 'failed');
  // finalize for another run id is ignored
  const before = st2.get().run;
  st2.dispatch('run/finalized', { id: 'zzz', exit: 0 });
  assert.equal(st2.get().run, before);
});

test('cancelled run ends cancelled with an unknown verdict', () => {
  const st = fresh();
  st.dispatch('run/queued', { kind: 'part', session: 's', part: 'A' });
  st.dispatch('run/started', { id: 'r1', startedAt: 1000 });
  st.dispatch('run/line', { id: 'r1', line: '[STAGE] Extracting A' });
  st.dispatch('run/finalized', { id: 'r1', exit: -15, cancelled: true, summary: null, payload: null });
  assert.equal(st.get().run.state, 'cancelled'); assert.equal(st.get().run.verdict, 'unknown');
  assert.equal(S.percent(st.get().run.track), null);
});

test('batch and history reducers', () => {
  const st = fresh();
  st.dispatch('batch/start', { queue: ['A', 'B'] });
  st.dispatch('batch/result', { part: 'A', result: { state: 'succeeded', exit: 0 } });
  st.dispatch('batch/next');
  assert.equal(st.get().batch.index, 1); assert.equal(st.get().batch.active, true);
  assert.ok(st.get().batch.results.A);
  st.dispatch('batch/stop'); assert.equal(st.get().batch.active, false);
  st.dispatch('history/loaded', { runs: [{ key: 'a|b' }] });
  assert.equal(st.get().history.loaded, true); assert.equal(st.get().history.runs.length, 1);
});

test('server/status and unreachable', () => {
  const st = fresh();
  st.dispatch('server/status', { live: true, samples: ['117C'], model: 'm' });
  assert.deepEqual([st.get().server.reachable, st.get().server.live, st.get().server.model], [true, true, 'm']);
  st.dispatch('server/unreachable');
  assert.equal(st.get().server.reachable, false); assert.equal(st.get().server.live, true);
});
