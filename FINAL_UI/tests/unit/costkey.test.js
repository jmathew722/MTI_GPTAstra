'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const SEL = H.logic('selectors.js');

function ledger(part, status, cost, runCost, runStatus) {
  return { present: true, scopes: {
    part: { cost_usd: cost, pricing_status: status, api_calls: 3 },
    run: { cost_usd: runCost === undefined ? cost : runCost, pricing_status: runStatus || status, api_calls: 1, run_id: 'r2' } } };
}
function state(o) {
  o = o || {};
  const part = o.part === undefined ? 'P1' : o.part;
  return {
    parts: { selected: part ? { session: 's', part } : null, list: part ? [{ name: part }] : [] },
    run: o.run === undefined ? { state: 'idle', part: null, track: null } : o.run,
    outputs: { ctx: o.ctxPart === undefined ? (part ? { kind: 'part', session: 's', part } : null) : (o.ctxPart && { kind: 'part', session: 's', part: o.ctxPart }),
               payload: o.ledger ? { categories: { usage: { ledger: o.ledger } } } : null }
  };
}
const live = (cost, part) => ({ state: 'running', part: part || 'P1', track: { tel: { run_id: 'r2', cost } } });

test('no part, or nothing recorded: an em dash, never $0.00', () => {
  for (const s of [state({ part: null }), state({})]) {
    const k = SEL.costKey(s);
    assert.equal(k.state, 'empty');
    assert.equal(k.partText, '\u2014');
    assert.ok(!/\$0/.test(k.text));
  }
});

test('idle/completed shows the selected part total from the ledger', () => {
  const k = SEL.costKey(state({ ledger: ledger('P1', 'priced', '2.992104') }));
  assert.equal(k.state, 'idle');
  assert.equal(k.text, 'Part cost $2.99');
  assert.equal(k.status, 'priced');
  assert.match(k.title, /2\.992104/);
});

test('while running it shows this run and the part together, from live telemetry', () => {
  const k = SEL.costKey(state({ run: live({ run_cost_usd: '1.274381', part_total_cost_usd: '2.992104', pricing_status: 'priced', part_pricing_status: 'priced' }) }));
  assert.equal(k.state, 'running');
  assert.equal(k.text, 'This run $1.27 \u00b7 Part $2.99');
  assert.equal(k.source, 'live');
});

test('a running part before the first model call shows a dash for the run and keeps earlier attempts in the part total', () => {
  const k = SEL.costKey(state({ run: live(null), ledger: ledger('P1', 'priced', '2.00') }));
  assert.equal(k.text, 'This run \u2014 \u00b7 Part $2.00');
});

test('partial is prefixed Est. and explained; unpriced says unavailable and is never zero', () => {
  const p = SEL.costKey(state({ ledger: ledger('P1', 'partial', '1.50') }));
  assert.equal(p.text, 'Part cost Est. $1.50');
  assert.equal(p.status, 'partial');
  assert.match(p.title, /partial/i);
  const u = SEL.costKey(state({ ledger: ledger('P1', 'unpriced', null) }));
  assert.equal(u.text, 'Part cost unavailable');
  assert.equal(u.status, 'unpriced');
  assert.ok(!/\$/.test(u.text));
});

test('tiny priced costs never round down to $0.00; an explicit priced zero does show $0.00', () => {
  assert.equal(SEL.costKey(state({ ledger: ledger('P1', 'priced', '0.004') })).text, 'Part cost <$0.01');
  assert.equal(SEL.costKey(state({ ledger: ledger('P1', 'priced', '0') })).text, 'Part cost $0.00');
});

test('retries: the part total keeps accumulating while the run total restarts', () => {
  const k = SEL.costKey(state({ run: live({ run_cost_usd: '0.10', part_total_cost_usd: '3.10', pricing_status: 'priced', part_pricing_status: 'priced' }) }));
  assert.equal(k.text, 'This run $0.10 \u00b7 Part $3.10');
});

test('switching part: another part\'s live run or stale payload is ignored', () => {
  const other = SEL.costKey(state({ part: 'P2', run: live({ run_cost_usd: '9', part_total_cost_usd: '9', pricing_status: 'priced', part_pricing_status: 'priced' }, 'P1') }));
  assert.equal(other.state, 'empty');
  const stale = SEL.costKey(state({ part: 'P2', ctxPart: 'P1', ledger: ledger('P1', 'priced', '5.00') }));
  assert.equal(stale.state, 'empty');
});

test('partial/unpriced live statuses are honoured', () => {
  const k = SEL.costKey(state({ run: live({ run_cost_usd: '1.0', part_total_cost_usd: '1.0', pricing_status: 'partial', part_pricing_status: 'partial' }) }));
  assert.equal(k.text, 'This run Est. $1.00 \u00b7 Part Est. $1.00');
  const u = SEL.costKey(state({ run: live({ run_cost_usd: null, part_total_cost_usd: null, pricing_status: 'unpriced', part_pricing_status: 'unpriced' }) }));
  assert.equal(u.text, 'Part cost unavailable');
});

/* ---- progress presentation helpers (Stage 2, task 2.1) ---- */
const sp = (o) => Object.assign({ source: 'structured', percent: 61.2, indeterminate: false, phase: 'solidworks_generation',
  operation: 'create_feature', label: 'Creating feature 7 of 18', completed: 6, total: 18, unit: 'features', terminal: null }, o || {});

test('fmtPercent shows the exact backend value, no invented precision, no fake 100', () => {
  assert.equal(SEL.fmtPercent(61.2), '61.2');
  assert.equal(SEL.fmtPercent(40), '40');
  assert.equal(SEL.fmtPercent(99.9), '99.9');
  assert.equal(SEL.fmtPercent(null), null);
});

test('progressCaption names the active operation and the unit count; indeterminate says so without a number', () => {
  assert.equal(SEL.progressCaption(sp()), 'Creating feature 7 of 18 \u00b7 6 of 18 features');
  assert.equal(SEL.progressCaption(sp({ label: '', operation: 'create_feature' })), 'Creating a feature \u00b7 6 of 18 features');
  const ind = SEL.progressCaption(sp({ percent: null, indeterminate: true, label: '', operation: 'ingest_drawing', completed: null, total: null, unit: null }));
  assert.equal(ind, 'Preparing the drawing');
  assert.ok(!/\d/.test(ind));
  assert.equal(SEL.progressCaption({ source: 'legacy_markers', percent: 14 }), '');
});

test('phaseLabel gives human names for every backend phase and never throws on unknown ones', () => {
  for (const p of ['ingest', 'extraction', 'resolution', 'build_plan', 'reference_build', 'solidworks_generation', 'verification', 'artifact_finalization']) {
    assert.ok(SEL.phaseLabel(p).length > 3, p);
  }
  assert.equal(SEL.phaseLabel('zzz'), 'zzz');
  assert.equal(SEL.phaseLabel(null), '');
});
