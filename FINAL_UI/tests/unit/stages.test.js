'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const S = H.logic('stages.js');

const ids = (t) => Array.from(t.seen).sort((a, b) => a - b);

/* Real captured lines (pipeline/ir_pipeline.py run_part + pipeline/ir/compile_solidworks.py),
   through utils.logger: a timestamp/level prefix before the tag, CRLF line endings (hence the
   trailing "\r" on several lines below -- a real transcript carries it; dropping it here would
   hide the exact bug that was fixed: a "$"-anchored regex does not match a bare CR). */
function partLines(part, opts) {
  opts = opts || {};
  const n = opts.questions || 0;
  const L = [
    `           INFO     [stage] extraction: reading 1 image(s) for ${part}        \r`,
    `           INFO     [stage] resolution: resolving ambiguous references for     \r`,
    `                    ${part}                                                    \r`,
    `           INFO     [stage] build_plan_start: planning ${part}                 \r`,
    `           INFO     [stage] build_plan_gate1: gate1=OK planned=3 questions=${n} \r`,
  ];
  if (opts.gate1 === 'REJECT') {
    L[4] = `           INFO     [stage] build_plan_gate1: gate1=REJECT planned=0 questions=0\r`;
    return L;
  }
  L.push(`           INFO     [stage] generation_start: building the CadQuery reference\r`);
  L.push(`[09:26:08] INFO     [stage] generation_reference: reference built, volume=1.0\r`);
  if (opts.noFeatureLine !== true) {
    L.push(`           INFO       F001: SW volume 1.000000 vs reference 1.000000 (ok, attempt 1)\r`);
  }
  if (opts.sw !== false) {
    L.push(`[09:26:12] INFO     [stage] verification: sw_ok=${opts.sw === undefined ? 'True' : opts.sw} bbox_ok=True\r`);
  }
  return L;
}
function irReport(over) { return Object.assign({ present: true, gate1: 'OK', questions: [], sw_ok: true, error: '' }, over); }
function payload(ir, stl) { return { categories: Object.assign({ ir_report: ir }, {}), stl_source: stl ? stl.source : null, stl_mtime: stl ? stl.mtime : 0 }; }

test('parseMarker: tag name alone determines k, case-insensitive, immune to a trailing CR', () => {
  assert.equal(S.parseMarker('[09:00:00] INFO     [stage] extraction: reading 1 image(s) for X\r').k, 0);
  assert.equal(S.parseMarker('  info [STAGE] RESOLUTION: resolving ambiguous references for X').k, 1);
  assert.equal(S.parseMarker('INFO [stage] build_plan_start: planning X').k, 2);
  assert.equal(S.parseMarker('INFO [stage] build_plan_gate1: gate1=OK planned=7 questions=0').k, 3);
  assert.equal(S.parseMarker('INFO [stage] generation_start: building the CadQuery reference').k, 4);
  assert.equal(S.parseMarker('INFO [stage] generation_reference: reference built, volume=1').k, 5);
  assert.equal(S.parseMarker('INFO   F003: SW volume 1.0 vs reference 1.0 (ok, attempt 2)').k, 6);
  assert.equal(S.parseMarker('INFO [stage] verification: sw_ok=True bbox_ok=True').k, 7);
  assert.equal(S.parseMarker('INFO     SolidWorks revision: 33.5.0'), null);
  assert.equal(S.parseMarker('INFO [stage] unknown_tag: whatever'), null);
  assert.equal(S.parseMarker(null), null);
});

test('out-of-order and duplicate markers do not move k backward, but repeats of k=6 are tracked', () => {
  let t = S.initial('part');
  t = S.reduce(t, '[stage] build_plan_start: x');
  assert.equal(t.k, 2);
  t = S.reduce(t, '[stage] extraction: x');     // an earlier marker arriving late
  assert.equal(t.k, 2, 'k never moves backward');
  t = S.reduce(t, '  F001: SW volume 1 vs reference 1 (ok, attempt 1)');
  assert.equal(t.k, 6);
  const before = t.seen.size;
  t = S.reduce(t, '  F002: SW volume 2 vs reference 2 (ok, attempt 1)');   // a second feature line
  assert.equal(t.k, 6);
  assert.equal(t.seen.size, before, 'k=6 was already recorded; a repeat changes nothing new');
});

test('full transcript replay gives the same track as a single pass', () => {
  const lines = partLines('A040911E');
  const once = H.replay(S, 'part', lines);
  let twice = S.initial('part');
  for (const l of lines) twice = S.reduce(twice, l);
  assert.deepEqual(ids(once), ids(twice));
  assert.equal(once.k, twice.k);
});

test('reduce is pure: the input track is not mutated', () => {
  const t0 = S.initial('part');
  const snapshotK = t0.k, snapshotSeenSize = t0.seen.size;
  S.reduce(t0, '[stage] extraction: x');
  assert.equal(t0.k, snapshotK);
  assert.equal(t0.seen.size, snapshotSeenSize);
});

test('live states: pending before any marker, running at the current stage, succeeded behind it', () => {
  let t = S.initial('part');
  assert.deepEqual(S.view(t).stages.map((s) => s.state), ['pending', 'pending', 'pending', 'pending', 'pending']);
  t = S.reduce(t, '[stage] extraction: x');
  assert.deepEqual(S.view(t).stages.map((s) => s.state), ['running', 'pending', 'pending', 'pending', 'pending']);
  t = S.reduce(t, '[stage] resolution: x');
  assert.deepEqual(S.view(t).stages.map((s) => s.state), ['succeeded', 'running', 'pending', 'pending', 'pending']);
  t = S.reduce(t, '[stage] build_plan_gate1: gate1=OK planned=1 questions=0');
  assert.deepEqual(S.view(t).stages.map((s) => s.state), ['succeeded', 'succeeded', 'running', 'pending', 'pending']);
});

test('percent: null before the first marker, floor(100*k/7), capped at 99, 100 only on a clean exit', () => {
  let t = S.initial('part');
  assert.equal(S.percent(t), null);
  t = S.reduce(t, '[stage] extraction: x');
  assert.equal(S.percent(t), 0);
  t = S.reduce(t, '[stage] verification: sw_ok=True');
  assert.equal(S.percent(t), 99, 'k=7 of 7 still caps at 99 until finalize');
  const okFinal = S.finalize(t, { exit: 0, payload: payload(irReport()) });
  assert.equal(S.percent(okFinal), 100);
  const failFinal = S.finalize(S.initial('part'), { exit: 7, payload: payload(irReport({ gate1: 'REJECT', error: 'hard:F001' })) });
  assert.equal(S.percent(failFinal), null);
  const cancelFinal = S.finalize(t, { exit: null, cancelled: true });
  assert.equal(S.percent(cancelFinal), null);
});

test('percent never decreases while replaying a transcript', () => {
  let t = S.initial('part');
  let last = -1;
  for (const l of partLines('X')) {
    t = S.reduce(t, l);
    const p = S.percent(t);
    if (p !== null) { assert.ok(p >= last, `percent went backward: ${last} -> ${p}`); last = p; }
  }
});

test('finalize: a clean IR success marks every stage succeeded', () => {
  const t = H.replay(S, 'part', partLines('A040911E'));
  const f = S.finalize(t, { exit: 0, payload: payload(irReport({ sw_ok: true }), { source: 'solidworks', mtime: 2000000000 }), startedAt: 0 });
  assert.deepEqual(S.view(f).stages.map((s) => s.state), ['succeeded', 'succeeded', 'succeeded', 'succeeded', 'succeeded']);
  assert.equal(S.percent(f), 100);
});

test('finalize: open IR questions warn Build Plan without failing anything (never guessed, not a defect)', () => {
  const t = H.replay(S, 'part', partLines('SB11033', { questions: 2 }));
  const f = S.finalize(t, { exit: 0, payload: payload(irReport({ questions: ['F003: a', 'F005: b'] }), { source: 'solidworks', mtime: 2000000000 }), startedAt: 0 });
  const v = S.view(f);
  assert.equal(v.stages[2].state, 'warning');
  assert.match(v.stages[2].detail, /2 open questions/);
  assert.equal(v.stages[4].state, 'succeeded', 'verification is unaffected by open questions');
});

test('finalize: Gate 1 REJECT fails Build Plan and Generation/Verification are never reached', () => {
  const t = H.replay(S, 'part', partLines('X', { gate1: 'REJECT' }));
  const f = S.finalize(t, { exit: 7, payload: payload(irReport({ gate1: 'REJECT', error: 'hard:F001:bad reference' })) });
  const v = S.view(f);
  assert.equal(v.stages[0].state, 'succeeded');
  assert.equal(v.stages[1].state, 'succeeded');
  assert.equal(v.stages[2].state, 'failed');
  assert.equal(v.stages[2].detail, 'hard:F001:bad reference');
  assert.equal(v.stages[3].state, 'skipped');
  assert.equal(v.stages[3].detail, 'Not reached');
  assert.equal(v.stages[4].state, 'skipped');
});

test('finalize: NO PLAN (the planner itself failed) fails Build Plan', () => {
  const t = H.replay(S, 'part', ['[stage] extraction: x', '[stage] resolution: x', '[stage] build_plan_start: x']);
  const f = S.finalize(t, { exit: 7, payload: payload(irReport({ gate1: 'NO PLAN', error: 'planner timed out' })) });
  assert.equal(S.view(f).stages[2].state, 'failed');
  assert.equal(S.view(f).stages[2].detail, 'planner timed out');
});

test('finalize: sw_ok false fails Verification specifically, not Generation', () => {
  const t = H.replay(S, 'part', partLines('X', { sw: 'False' }));
  const f = S.finalize(t, { exit: 7, payload: payload(irReport({ sw_ok: false })) });
  const v = S.view(f);
  assert.equal(v.stages[3].state, 'succeeded', 'the CadQuery reference still built fine');
  assert.equal(v.stages[4].state, 'failed');
  assert.match(v.stages[4].detail, /did not verify/);
});

test('finalize: CadQuery-only run (no SolidWorks engine) gives a Generation warning, not success or failure', () => {
  const lines = partLines('X').filter((l) => !/\[stage\] verification/.test(l));
  const t = H.replay(S, 'part', lines);
  const f = S.finalize(t, { exit: 0, payload: payload(irReport({ sw_ok: null }), { source: 'prevalidation', mtime: 2000000000 }), startedAt: 0 });
  const v = S.view(f);
  assert.equal(v.stages[3].state, 'succeeded', 'the reference itself built');
  assert.equal(v.stages[4].state, 'warning');
  assert.match(v.stages[4].detail, /not used for this run/);
});

test('finalize: no ir_report at all falls back to exit-code-only failure (process crashed before the pipeline ran)', () => {
  const t = S.initial('part');   // nothing was ever seen
  const f = S.finalize(t, { exit: 1, payload: null });
  const v = S.view(f);
  assert.equal(v.stages[0].state, 'failed');
  assert.match(v.stages[0].detail, /Exited with code 1/);
  for (let i = 1; i < v.stages.length; i++) assert.equal(v.stages[i].state, 'skipped');
});

test('finalize rule 1: cancelled mid-run marks the running stage Cancelled and the rest Not reached', () => {
  const t = H.replay(S, 'part', ['[stage] extraction: x', '[stage] resolution: x', '[stage] build_plan_start: x']);
  const f = S.finalize(t, { exit: null, cancelled: true });
  const v = S.view(f);
  assert.equal(v.stages[0].state, 'succeeded');
  assert.equal(v.stages[1].state, 'succeeded');
  assert.equal(v.stages[2].state, 'skipped');
  assert.equal(v.stages[2].detail, 'Cancelled');
  assert.equal(v.stages[3].state, 'skipped');
  assert.equal(v.stages[3].detail, 'Not reached');
});

test('finalize never leaves a pending or running stage behind', () => {
  const cases = [
    { lines: [], facts: { exit: 7, payload: null } },
    { lines: partLines('X'), facts: { exit: 0, payload: payload(irReport()) } },
    { lines: ['[stage] extraction: x'], facts: { exit: null, cancelled: true } },
  ];
  for (const c of cases) {
    const t = H.replay(S, 'part', c.lines);
    const v = S.view(S.finalize(t, c.facts));
    for (const st of v.stages) {
      assert.notEqual(st.state, 'pending');
      assert.notEqual(st.state, 'running');
    }
  }
});

test('demo transcript maps to Extraction, Resolution, Build Plan and skips the rest; ignores [stage] lines', () => {
  const lines = ['[1-2/4] Loading extraction from x.json (skipping API)...', '[stage] extraction: a part run marker, ignored in demo mode',
                 '[2.5/4] Resolving ambiguities...', '[3/4] Verifying extracted data...', '[4/4] Generating macro package...'];
  const t = H.replay(S, 'demo', lines);
  assert.equal(t.k, 3);
  const f = S.finalize(t, { exit: 0, payload: null });
  const v = S.view(f);
  assert.equal(v.stages[0].state, 'succeeded');
  assert.equal(v.stages[1].state, 'succeeded');
  assert.equal(v.stages[2].state, 'succeeded');
  assert.equal(v.stages[3].state, 'skipped');
  assert.equal(v.stages[3].detail, 'Demo runs stop after the macro package');
  assert.equal(v.stages[4].state, 'skipped');
});

test('demo blocked (exit 4) fails Build Plan', () => {
  const lines = ['[1-2/4] Loading extraction from x.json...', '[2.5/4] Resolving...', '[3/4] Verifying...'];
  const t = H.replay(S, 'demo', lines);
  const f = S.finalize(t, { exit: 4, payload: null });
  assert.equal(S.view(f).stages[2].state, 'failed');
});

test('part runs ignore demo bracket lines and demo runs ignore [stage] lines', () => {
  const tPart = H.replay(S, 'part', ['[1-2/4] not a part marker', '[stage] extraction: x']);
  assert.equal(tPart.k, 0);
  const tDemo = H.replay(S, 'demo', ['[stage] extraction: not a demo marker', '[1-2/4] Loading...']);
  assert.equal(tDemo.k, 0);
});

test('view has five stages with substeps grouped correctly, in order', () => {
  const v = S.view(S.initial('part'));
  assert.equal(v.stages.length, 5);
  assert.deepEqual(v.stages.map((s) => s.id), ['extraction', 'resolution', 'build_plan', 'generation', 'verification']);
  assert.deepEqual(v.stages.map((s) => s.substeps.map((x) => x.k)),
    [[0], [1], [2, 3], [4, 5, 6], [7]]);
});


/* ---- a budget stop is reported as the cost limit, against the right stage ---------------------------------------------- */
test('finalize: an IR run stopped by the API cost limit says "<stage> failed - due to cost limit"', () => {
  const ir = irReport({ gate1: '', sw_ok: null, error: 'COST_LIMIT:extraction: stopped by the API cost limit (spent $18.91 of $20.00)' });
  const f = S.finalize(S.initial('part'), { exit: 9, payload: payload(ir) });
  const st = f.final.stages;
  assert.equal(st[0].state, 'failed');
  assert.equal(st[0].detail, 'Extraction failed - due to cost limit');
  assert.ok(st.slice(1).every((x) => x.state !== 'failed'), 'later stages are not blamed');
  const plan = S.finalize(S.initial('part'), { exit: 9, payload: payload(irReport({ gate1: '', sw_ok: null, error: 'COST_LIMIT:build_plan: stopped' })) });
  assert.equal(plan.final.stages[2].detail, 'Build Plan failed - due to cost limit');
});

test('finalize: with no IR report, the console line "API budget stop" still names the cost limit', () => {
  let t = S.initial('part');
  t = S.reduce(t, '           INFO     [stage] extraction: reading 1 image(s) for P        \r');
  t = S.reduce(t, '*** STOPPED: API budget stop: spent $18.91 of $20.00; the next call could cost up to $1.12');
  const f = S.finalize(t, { exit: 9, payload: { categories: { ir_report: { present: false } } } });
  assert.equal(f.final.stages[0].detail, 'Extraction failed - due to cost limit');
});
