'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const S = H.logic('stages.js');
const CSV = H.logic('csv.js');

const ids = (t) => Array.from(t.seen).sort((a, b) => a - b);

test('longest prefix: "Verifying must-meet constraints" is k=8, "Verifying" is k=4', () => {
  assert.equal(S.parseMarker('[STAGE] Verifying must-meet constraints').k, 8);
  assert.equal(S.parseMarker('[STAGE] Verifying').k, 4);
  assert.equal(S.parseMarker('[STAGE] Building .sldprt').k, 7);
  assert.equal(S.parseMarker('[STAGE] Building macros').k, 5);
  assert.equal(S.parseMarker('[STAGE] Pre-validating (CadQuery)').k, 6);
  assert.equal(S.parseMarker('[STAGE] Unknown thing'), null);
  assert.equal(S.parseMarker('plain line'), null);
});

test('markers with a part-name suffix', () => {
  assert.equal(S.parseMarker('[STAGE] Extracting 117C').k, 1);
  assert.equal(S.parseMarker('[STAGE] Extracting 117C').rest, '117C');
  assert.equal(S.parseMarker('[STAGE] Overview analysis 117C').k, 0);
  const t = S.reduce(S.initial('part'), '[STAGE] Extracting 117C');
  assert.equal(t.k, 1);
});

test('out-of-order and duplicate markers do not move backward', () => {
  let t = S.initial('part');
  for (const l of ['[STAGE] Verifying', '[STAGE] Extracting X', '[STAGE] Verifying', '[STAGE] Resolving']) t = S.reduce(t, l);
  assert.equal(t.k, 4);
  assert.deepEqual(ids(t), [4]);
  const before = S.percent(t);
  t = S.reduce(t, '[STAGE] Extracting X');
  assert.equal(S.percent(t), before);
});

test('full transcript replay gives the same track as a single pass', () => {
  const lines = H.lines('part_full.log');
  const a = H.replay(S, 'part', lines);
  const b = H.replay(S, 'part', lines);
  assert.deepEqual(ids(a), ids(b));
  assert.equal(a.k, b.k);
  assert.deepEqual(a.signals, b.signals);
  // replay of a replay (reconnect: lines delivered again from index 0 after a partial)
  let c = S.initial('part');
  lines.slice(0, 12).forEach((l) => { c = S.reduce(c, l); });
  lines.forEach((l) => { c = S.reduce(c, l); });
  assert.deepEqual(ids(c), ids(a));
  assert.deepEqual(c.signals, a.signals);
});

test('reduce is pure: the input track is not mutated', () => {
  const t0 = S.initial('part');
  const t1 = S.reduce(t0, '[STAGE] Extracting A');
  assert.equal(t0.k, -1);
  assert.equal(t0.seen.size, 0);
  assert.equal(t1.k, 1);
});

test('skipped sub-steps: no overview, no specs, no SolidWorks', () => {
  const t = H.replay(S, 'part', H.lines('part_nosw.log'));
  assert.deepEqual(ids(t), [1, 3, 4, 5, 6, 9, 10, 11]);
  const v = S.view(t);
  const stageStates = v.stages.map((s) => s.state);
  // finished markers (k=11) with no finalize: extraction done, resolution done, build plan done,
  // generation work was seen (6) so succeeded, verification work seen (9)
  assert.deepEqual(stageStates, ['succeeded', 'succeeded', 'succeeded', 'succeeded', 'succeeded']);
  const gen = v.stages[3].substeps.map((s) => s.state);
  assert.deepEqual(gen, ['succeeded', 'skipped']);       // 6 ran, 7 (.sldprt) skipped
  const ext = v.stages[0].substeps.map((s) => s.state);
  assert.deepEqual(ext, ['skipped', 'succeeded']);       // overview skipped
});

test('live states while running part_full', () => {
  const lines = H.lines('part_full.log');
  const upTo = (marker) => {
    const i = lines.findIndex((l) => l === marker);
    return H.replay(S, 'part', lines.slice(0, i + 1));
  };
  let v = S.view(upTo('[STAGE] Building macros'));
  assert.deepEqual(v.stages.map((s) => s.state), ['succeeded', 'warning', 'running', 'pending', 'pending']);
  assert.equal(v.currentIndex, 2);
  assert.equal(v.stageNumber, 3);
  assert.equal(v.caption, 'Building macros…');
  v = S.view(upTo('[STAGE] Extracting 117C'.replace('117C', '117C')));
  assert.equal(v.stages[0].state, 'running');
  assert.equal(v.stages[1].state, 'pending');
  v = S.view(S.initial('part'));
  assert.equal(v.currentIndex, -1);
  assert.equal(v.caption, 'Starting…');
  assert.ok(v.stages.every((s) => s.state === 'pending'));
});

test('resolveWarn from [SPEC] HIGH marks Resolution as warning once complete; extractWarn marks Extraction', () => {
  const t = H.replay(S, 'part', H.lines('part_full.log'));
  assert.equal(t.signals.resolveWarn, true);
  const states = S.view(t).stages.map((s) => s.state);
  assert.equal(states[1], 'warning');
  const b = H.replay(S, 'part', H.lines('part_blocked.log'));
  assert.equal(b.signals.extractWarn, true);
});

test('percent: null before first marker, floor(100*k/11), 99 cap, 100 only for exit 0 or 8, removed on failure and cancel', () => {
  let t = S.initial('part');
  assert.equal(S.percent(t), null);
  const pct = [];
  for (const l of ['[STAGE] Overview analysis A', '[STAGE] Extracting A', '[STAGE] Resolving', '[STAGE] Verifying',
    '[STAGE] Building macros', '[STAGE] Pre-validating (CadQuery)', '[STAGE] Building .sldprt',
    '[STAGE] Verifying must-meet constraints', '[STAGE] Final checks', '[STAGE] Exporting', '[STAGE] Done']) {
    t = S.reduce(t, l); pct.push(S.percent(t));
  }
  assert.deepEqual(pct, [0, 9, 27, 36, 45, 54, 63, 72, 81, 90, 99]);
  for (let i = 1; i < pct.length; i++) assert.ok(pct[i] >= pct[i - 1]);
  assert.equal(S.percent(S.finalize(t, { exit: 0 })), 100);
  assert.equal(S.percent(S.finalize(t, { exit: 8 })), 100);
  assert.equal(S.percent(S.finalize(t, { exit: 2 })), null);
  assert.equal(S.percent(S.finalize(t, { exit: 127 })), null);
  assert.equal(S.percent(S.finalize(t, { exit: -15, cancelled: true })), null);
  assert.equal(S.percent(S.finalize(t, { exit: 0, cancelled: true })), null);
});

test('percent never decreases and is not time based', () => {
  let t = H.replay(S, 'part', ['[STAGE] Building macros']);
  const p = S.percent(t);
  t = S.reduce(t, '[STAGE] Extracting Z');
  assert.equal(S.percent(t), p);
});

const NOW = 1700000000;
function sw(over) {
  const p = H.payload();
  Object.assign(p, over || {});
  return p;
}

test('finalize: success with a fresh SolidWorks STL', () => {
  const t = S.finalize(H.replay(S, 'part', H.lines('part_full.log')), {
    exit: 0, summary: CSV.summaryRow(H.text('summary_ready.csv'), '117C'), payload: sw(), startedAt: 1700000000.5 });
  assert.deepEqual(H.states(t), ['succeeded', 'warning', 'succeeded', 'succeeded', 'succeeded']);
  assert.equal(t.done, true);
  assert.equal(S.view(t).caption, 'Complete');
});

test('finalize: stale SolidWorks STL means Generation failed', () => {
  const t = S.finalize(H.replay(S, 'part', H.lines('part_full.log')), {
    exit: 0, summary: CSV.summaryRow(H.text('summary_ready.csv'), '117C'),
    payload: sw({ stl_mtime: 1699999000 }), startedAt: 1700000000.5 });
  assert.equal(t.final.stages[3].state, 'failed');
});

test('finalize: sub-step 7 seen and build failed reports the summary detail', () => {
  const t = S.finalize(H.replay(S, 'part', H.lines('part_full.log')), {
    exit: 8, summary: { status: 'NOT READY', detail: 'sldprt build failed: COMError', n_needs_review: '0', n_skipped: '0' },
    payload: sw({ stl_source: 'prevalidation' }), startedAt: 1700000000.5 });
  assert.equal(t.final.stages[3].state, 'failed');
  assert.match(t.final.stages[3].detail, /sldprt build failed/);
  assert.equal(t.final.stages[4].state, 'warning');
});

test('finalize: pre-validation only (no SolidWorks) gives a Generation warning', () => {
  const p = sw({ stl_source: 'prevalidation' });
  p.categories.sldprt.present = false;
  const t = S.finalize(H.replay(S, 'part', H.lines('part_nosw.log')), {
    exit: 8, summary: CSV.summaryRow(H.text('summary_notready.csv'), 'Bracket'), payload: p, startedAt: 1700000000.5 });
  assert.equal(t.final.stages[3].state, 'warning');
  assert.match(t.final.stages[3].detail, /pre-validation model only/);
  assert.equal(t.final.stages[2].state, 'warning');            // n_needs_review > 0
  assert.equal(t.final.stages[4].state, 'warning');            // NOT READY
  assert.equal(S.percent(t), 100);
});

test('finalize: no SolidWorks and no pre-validation STL gives Generation skipped', () => {
  const p = sw({ stl_source: null, stl_mtime: 0 });
  const t = S.finalize(H.replay(S, 'part', H.lines('part_nosw.log')), {
    exit: 0, summary: { status: 'READY', n_needs_review: '0', n_skipped: '0' }, payload: p, startedAt: NOW });
  assert.equal(t.final.stages[3].state, 'skipped');
  assert.equal(t.final.stages[4].state, 'succeeded');
});

test('finalize: BLOCKED fails Build Plan and later stages are not reached', () => {
  const t = S.finalize(H.replay(S, 'part', H.lines('part_blocked.log')), {
    exit: 8, summary: CSV.summaryRow(H.text('summary_blocked.csv'), 'Flange'),
    payload: sw({ stl_source: null, stl_mtime: 0 }), startedAt: NOW });
  assert.deepEqual(H.states(t), ['warning', 'succeeded', 'failed', 'skipped', 'skipped']);
  assert.match(t.final.stages[2].detail, /no FRONT view/);
  assert.equal(t.final.stages[3].detail, 'Not reached');
  assert.equal(t.final.stages[4].detail, 'Not reached');
});

test('finalize: ERROR after extraction (summary ERROR, Extraction failed line)', () => {
  const t = S.finalize(H.replay(S, 'part', H.lines('part_extract_failed.log')), {
    exit: 8, summary: CSV.summaryRow(H.text('summary_error.csv'), 'Shaft'), payload: null, startedAt: NOW });
  assert.deepEqual(H.states(t), ['failed', 'skipped', 'skipped', 'skipped', 'skipped']);
  assert.match(t.final.stages[0].detail, /APIConnectionError/);
});

test('live view after Extraction failed: Exporting does not make Verification run', () => {
  const t = H.replay(S, 'part', H.lines('part_extract_failed.log'));
  const v = S.view(t);
  assert.equal(v.stages[0].state, 'failed');
  assert.equal(v.stages[4].state, 'skipped');
  assert.ok(!v.stages.some((s) => s.state === 'running'));
});

test('finalize: processing error fails the stage that was working, not the last marker', () => {
  const live = S.view(H.replay(S, 'part', H.lines('part_process_failed.log')));
  assert.equal(live.stages[2].state, 'failed');
  const t = S.finalize(H.replay(S, 'part', H.lines('part_process_failed.log')), {
    exit: 8, summary: CSV.summaryRow(H.text('summary_process_error.csv'), 'Gear'), payload: null, startedAt: NOW });
  assert.deepEqual(H.states(t), ['succeeded', 'succeeded', 'failed', 'skipped', 'skipped']);
});

test('finalize: must-meet post_build failure fails Verification', () => {
  const p = sw();
  p.categories.must_meet = { present: true, stage: 'post_build', ok: false, failed: ['MM1 hole count: required 4, measured 3'], results: [] };
  const t = S.finalize(H.replay(S, 'part', H.lines('part_full.log')), {
    exit: 8, summary: { status: 'NOT READY', detail: '', n_needs_review: '0', n_skipped: '0' }, payload: p, startedAt: 1700000000.5 });
  assert.equal(t.final.stages[4].state, 'failed');
  assert.match(t.final.stages[4].detail, /MM1/);
});

test('finalize: verification without a summary is a warning, never a success', () => {
  const t = S.finalize(H.replay(S, 'part', H.lines('part_full.log')), { exit: 0, summary: null, payload: sw(), startedAt: 1700000000.5 });
  assert.equal(t.final.stages[4].state, 'warning');
});

test('finalize rule 1: cancelled wins, running stage skipped as Cancelled', () => {
  const t = S.finalize(H.replay(S, 'part', H.lines('part_cancelled.log')), { exit: -15, cancelled: true });
  assert.deepEqual(H.states(t), ['skipped', 'skipped', 'skipped', 'skipped', 'skipped']);
  assert.equal(t.final.stages[0].detail, 'Cancelled');
  assert.equal(t.final.stages[1].detail, 'Not reached');
  assert.equal(S.view(t).caption, 'Cancelled');
  // cancelled after extraction finished keeps the finished stage
  const t2 = S.finalize(H.replay(S, 'part', ['[STAGE] Extracting A', '[STAGE] Resolving', '[STAGE] Verifying']), { exit: -15, cancelled: true });
  assert.deepEqual(H.states(t2), ['succeeded', 'succeeded', 'skipped', 'skipped', 'skipped']);
  assert.equal(t2.final.stages[2].detail, 'Cancelled');
});

test('finalize rule 2: hard failure marks the running stage failed with the exit code', () => {
  const t = S.finalize(H.replay(S, 'part', ['[STAGE] Extracting A', '[STAGE] Resolving', '[STAGE] Verifying', '[STAGE] Building macros']),
    { exit: 2 });
  assert.deepEqual(H.states(t), ['succeeded', 'succeeded', 'failed', 'skipped', 'skipped']);
  assert.equal(t.final.stages[2].detail, 'Exited with code 2');
  assert.equal(t.final.stages[3].detail, 'Not reached');
  // launch error before any marker
  const l = H.replay(S, 'part', ['$ python main.py', '[launch error] FileNotFoundError: python']);
  assert.equal(l.signals.processFailed, true);
  const f = S.finalize(l, { exit: 127 });
  assert.equal(f.final.stages[0].state, 'failed');
  assert.equal(f.final.stages[0].detail, 'Exited with code 127');
  assert.equal(S.percent(f), null);
});

test('finalize never leaves pending or running stages', () => {
  for (const exit of [0, 8, 2, 127]) {
    const t = S.finalize(H.replay(S, 'part', ['[STAGE] Extracting A', '[STAGE] Verifying']), { exit, payload: null });
    assert.ok(t.final.stages.every((s) => s.state !== 'pending' && s.state !== 'running'), 'exit ' + exit);
  }
});

test('demo transcript maps to Extraction, Resolution, Build Plan and skips the rest', () => {
  const t = H.replay(S, 'demo', H.lines('demo.log'));
  assert.deepEqual(ids(t), [0, 1, 2, 3]);
  assert.equal(S.percent(t), 75);
  const f = S.finalize(t, { exit: 0 });
  assert.deepEqual(H.states(f), ['succeeded', 'succeeded', 'succeeded', 'skipped', 'skipped']);
  assert.equal(f.final.stages[3].detail, 'Demo runs stop after the macro package');
  assert.equal(f.final.stages[4].detail, 'Demo runs stop after the macro package');
  assert.equal(S.percent(f), 100);
  const live = S.view(H.replay(S, 'demo', H.lines('demo.log').slice(0, 4)));
  assert.equal(live.stages[0].state, 'succeeded');
  assert.equal(live.stages[1].state, 'succeeded');
  assert.equal(live.stages[2].state, 'running');
  assert.equal(live.stages[3].state, 'skipped');
  assert.equal(live.caption, 'Verifying extracted data…');
  assert.deepEqual(live.stages[2].substeps.map((x) => x.label), ['Verifying extracted data', 'Generating macro package']);
});

test('demo blocked (exit 4) fails Build Plan', () => {
  const t = S.finalize(H.replay(S, 'demo', ['[1-2/4] Loading extraction', '[2.5/4] Resolving', '[3/4] Verifying']), { exit: 4 });
  assert.deepEqual(H.states(t), ['succeeded', 'succeeded', 'failed', 'skipped', 'skipped']);
  assert.equal(S.percent(t), null);
});

test('part runs ignore demo bracket lines and demo runs ignore [STAGE] lines', () => {
  assert.equal(S.reduce(S.initial('part'), '[3/4] Verifying extracted data...').k, -1);
  assert.equal(S.reduce(S.initial('demo'), '[STAGE] Verifying').k, -1);
});

test('view has five stages with substeps in order', () => {
  const v = S.view(S.initial('part'));
  assert.deepEqual(v.stages.map((s) => s.id), ['extraction', 'resolution', 'build_plan', 'generation', 'verification']);
  assert.equal(v.stageCount, 5);
  assert.deepEqual(v.stages[4].substeps.map((s) => s.k), [8, 9, 10]);
});
