'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { logic } = require('./_helpers');
const C = logic('costview.js');

const EST = { duration: { low_s: 90, expected_s: 150, high_s: 330, source: 'history', basis: 'median of 7' },
  cost: { low: 0.04, expected: 0.21, high: 0.62, currency: 'USD', rate_version: '2026-11-27', model: 'gpt-6-astra', unavailable_reason: null },
  tokens: { input: { low: 0, expected: 20000, high: 0 }, output: { low: 0, expected: 4000, high: 0 }, cached_input: 0 },
  by_stage: { extraction: { cost: { expected: 0.09 }, calls: { expected: 1 }, duration_s: { expected: 20 } }, local_generation: { cost: { expected: 0 }, duration_s: { expected: 60 } } },
  assumptions: ['1 page'], labels: [] };

test('money: unknown is never $0.00, sub-cent keeps four decimals', () => {
  assert.equal(C.money(null), 'unavailable'); assert.equal(C.money(undefined), 'unavailable'); assert.equal(C.money(NaN), 'unavailable'); assert.equal(C.money(-1), 'unavailable');
  assert.equal(C.money(0), '$0.00'); assert.equal(C.money(0.0043), '$0.0043'); assert.equal(C.money(0.00004), '<$0.0001');
  assert.equal(C.money(0.6691), '$0.6691'); assert.equal(C.money(12.345), '$12.35');
  assert.equal(C.moneyEst(0.21), '$0.21'); assert.equal(C.moneyEst(0.04), '$0.0400'); assert.equal(C.moneyEst(null), 'unavailable');
});
test('duration formatting', () => {
  assert.equal(C.dur(0.4), '<1 s'); assert.equal(C.dur(45), '45 s'); assert.equal(C.dur(141.7), '2 min 22 s'); assert.equal(C.dur(3725), '1 h 2 min'); assert.equal(C.dur(null), '');
  assert.equal(C.durRange(90, 330), '1.5 min – 5.5 min'); assert.equal(C.durRange(40, 40), '40 s'); assert.equal(C.durRange(null, 3), '');
});
test('estimate: ready with range, model and rate date', () => {
  const v = C.estimateView(EST);
  assert.equal(v.state, 'ready'); assert.equal(v.duration.text, 'About 2.5 min (range 1.5 min – 5.5 min)'); assert.equal(v.duration.rough, false);
  assert.equal(v.cost.state, 'ready'); assert.equal(v.cost.text, '$0.21'); assert.match(v.cost.range, /low \$0\.0400 .* expected \$0\.21 .* high \$0\.62/);
  assert.equal(v.modelLine, 'Model gpt-6-astra · rates of 2026-11-27'); assert.match(v.tokens, /20,000 in/);
  assert.deepEqual(v.stages.map(s => s.key), ['extraction', 'local_generation']); assert.equal(v.stages[1].note, 'no token cost');
});
test('estimate: fallback duration is labelled rough', () => {
  const v = C.estimateView(Object.assign({}, EST, { duration: { low_s: 30, expected_s: 60, high_s: 200, source: 'fallback' } }));
  assert.match(v.duration.text, /^Rough estimate: /);
});
test('estimate: unknown rate is unavailable with the reason, never zero', () => {
  const v = C.estimateView(Object.assign({}, EST, { cost: { low: null, expected: null, high: null, model: 'x', unavailable_reason: 'No rate for model x' } }));
  assert.equal(v.cost.state, 'unknown'); assert.equal(v.cost.text, 'Cost unavailable'); assert.equal(v.cost.reason, 'No rate for model x'); assert.ok(!/\$0/.test(v.cost.text + v.cost.range));
});
test('estimate: standard mode zero is a real zero ("no model call"), absent estimate is unknown', () => {
  const z = C.estimateView(Object.assign({}, EST, { cost: { low: 0, expected: 0, high: 0, model: 'gpt-6-astra', rate_version: 'v', unavailable_reason: null } }));
  assert.equal(z.cost.state, 'none'); assert.equal(z.cost.text, 'No OpenAI cost expected');
  assert.equal(C.estimateView(null).state, 'none'); assert.equal(C.estimateView(null).cost.text, 'unavailable'); assert.equal(C.estimateView({}).cost.state, 'unknown');
});

test('usage: priced, sub-cent, tokens with cached input, retries from attempts', () => {
  const u = C.usageView({ calls: 3, cache_hits: 0, input_tokens: 41234, cached_tokens: 1000, output_tokens: 5120, cost_usd: 0.0043, cost_status: 'priced',
    by_stage: { extraction: { calls: 1, input_tokens: 30000, cached_tokens: 1000, output_tokens: 4000, cost_usd: 0.003, attempts: 1 }, validation: { calls: 2, input_tokens: 11234, cached_tokens: 0, output_tokens: 1120, cost_usd: 0.0013, attempts: 3 } } });
  assert.equal(u.cost.text, '$0.0043'); assert.equal(u.cost.status, 'priced'); assert.equal(u.tokens, '41,234 in · 1,000 cached · 5,120 out'); assert.equal(u.calls, 3);
  assert.equal(u.retries, 2); assert.deepEqual(u.stages.map(s => s.label), ['Extraction', 'Validation']);
});
test('usage: partial shows the known part plus unpriced calls; unpriced is unavailable', () => {
  const p = C.usageView({ calls: 2, cost_usd: 0.01, cost_status: 'partial', unpriced_calls: 1, unknown_usage_calls: 1 });
  assert.equal(p.cost.text, '$0.0100 + unpriced calls'); assert.equal(p.notes.length, 2);
  const n = C.usageView({ calls: 2, cost_usd: null, cost_status: 'unpriced', unpriced_calls: 2 });
  assert.equal(n.cost.text, 'unavailable'); assert.ok(!/\$0/.test(n.cost.text));
});
test('usage: local cache hit costs $0 with no call; savings only when reuse is confirmed', () => {
  const c = C.usageView({ calls: 0, cache_hits: 1, cost_usd: 0, cost_status: 'none', historical_usd: 0.2 });
  assert.equal(c.cost.text, '$0.00'); assert.equal(c.cost.status, 'cache'); assert.match(c.saved, /saves about \$0\.2000/);
  const d = C.usageView({ calls: 0, cache_hits: 1, cost_usd: 0, cost_status: 'none', historical_usd: null });
  assert.match(d.saved, /original cost is not recorded/);
  const none = C.usageView({ calls: 0, cache_hits: 0, cost_status: 'none', cost_usd: null });
  assert.equal(none.saved, ''); assert.equal(none.cost.text, 'No model calls recorded'); assert.equal(none.any, false);
  assert.equal(C.usageView(null).cost.text, 'Not recorded');
});
test('timing: live elapsed adds browser monotonic time only while running; remaining is hidden when absent', () => {
  const t = { elapsed_s: 100, running: true, remaining_s: { low: 10, expected: 55, high: 120, source: 'history' } };
  assert.equal(C.liveElapsed(t, 1000, 6000), 105); assert.equal(C.liveElapsed(Object.assign({}, t, { running: false }), 1000, 6000), 100); assert.equal(C.liveElapsed({ elapsed_s: null }, 0, 5), null);
  assert.equal(C.remainingText(t, 105, 1000), 'about 50 s left (5 s – 1.9 min)');
  assert.equal(C.remainingText({ elapsed_s: 100, running: true, remaining_s: null }, 100, 0), '');
  assert.equal(C.remainingText({ elapsed_s: 100, running: true, remaining_s: { low: 1, expected: 5, high: 9, source: 'fallback' } }, 200, 0), 'taking longer than estimated');
  assert.match(C.remainingText({ elapsed_s: 0, running: false, remaining_s: { expected: 60, source: 'fallback' } }, 0, null), /^rough: about 1 min left/);
});
const JOB = (over) => Object.assign({ summary_state: 'completed', estimate: EST, parts: [{ part_id: 'a', name: 'A', state: 'completed', usage: { calls: 1, cost_usd: 0.19, cost_status: 'priced' }, timing: { elapsed_s: 60 } }, { part_id: 'b', name: 'B', state: 'failed', usage: { calls: 1, cost_usd: 0.05, cost_status: 'priced' }, timing: { elapsed_s: 5 } }],
  usage: { calls: 2, input_tokens: 10, output_tokens: 5, cost_usd: 0.24, cost_status: 'priced' }, timing: { elapsed_s: 70, queued_s: 3.2, running: false, by_stage: { preflight: 1.2, extraction: 20.1 } },
  estimate_vs_actual: { cost_usd: { expected: 0.21, actual: 0.24, within_range: true }, duration_s: { expected: 150, actual: 70, within_range: false } } }, over || {});
test('run model: batch aggregate, per part rows, actual vs estimate, failed cost kept, no remaining when finished', () => {
  const m = C.runModel({ job: JOB(), now: 5, fetchedAt: 0 });
  assert.equal(m.active, false); assert.equal(m.terminal, true); assert.deepEqual(m.parts, { done: 2, total: 2 }); assert.equal(m.batch, true);
  assert.equal(m.usage.cost.text, '$0.2400'); assert.equal(m.elapsed, '1 min 10 s'); assert.equal(m.queued, '3 s'); assert.equal(m.remaining, '');
  assert.deepEqual(m.compare, ['Cost: $0.2400 actual vs $0.21 expected (within the estimated range)', 'Time: 1 min 10 s actual vs 2.5 min expected (outside the estimated range)']);
  assert.equal(m.perPart.length, 2); assert.equal(m.perPart[1].cost, '$0.0500'); assert.match(m.keptNote, /failed or canceled/);
  assert.equal(m.timingStages[0].key, 'preflight'); assert.match(m.localNote, /no token cost/);
});
test('run model: running job shows live line; old job (no fields) is empty, not zero', () => {
  const run = JOB({ summary_state: 'running', timing: { elapsed_s: 30, running: true, queued_s: 1, remaining_s: { low: 10, expected: 20, high: 40, source: 'history' } }, parts: [{ part_id: 'a', name: 'A', state: 'native_drawing' }] });
  const m = C.runModel({ job: run, now: 4000, fetchedAt: 0 });
  assert.equal(m.active, true); assert.equal(m.elapsed, '34 s'); assert.equal(C.liveLine(m), '0 of 1 part done · elapsed 34 s · $0.2400 so far · about 16 s left (6 s – 36 s)');
  const old = C.runModel({ job: { summary_state: 'completed', parts: [{ part_id: 'a', name: 'A', state: 'completed' }], usage: { calls: 0, cost_usd: null, cost_status: 'none' }, timing: { queued_s: null, elapsed_s: null } } });
  assert.equal(old.elapsed, ''); assert.equal(old.usage.cost.text, 'No model calls recorded'); assert.equal(C.chipText({ usage: { calls: 0, cost_status: 'none', cost_usd: null } }), '');
  assert.equal(C.runModel({}).estimate.state, 'none');
});
test('chip text: calculated, partial, unpriced, cache', () => {
  assert.equal(C.chipText({ usage: { calls: 2, cost_usd: 0.0043, cost_status: 'priced' } }), '$0.0043 API usage (calculated)');
  assert.equal(C.chipText({ usage: { calls: 2, cost_usd: 0.01, cost_status: 'partial' } }), '$0.0100 + unpriced calls API usage (calculated, partial)');
  assert.equal(C.chipText({ usage: { calls: 2, cost_usd: null, cost_status: 'unpriced' } }), 'API cost unavailable (2 calls)');
  assert.equal(C.chipText({ usage: { calls: 0, cache_hits: 1, cost_usd: 0, cost_status: 'none' } }), '$0.00 API usage (extraction reused)');
});
test('concurrent jobs do not share state (pure): two models from two jobs stay independent', () => {
  const a = C.runModel({ job: JOB(), now: 0 }), b = C.runModel({ job: JOB({ usage: { calls: 1, cost_usd: 9, cost_status: 'priced' } }), now: 0 });
  assert.equal(a.usage.cost.text, '$0.2400'); assert.equal(b.usage.cost.text, '$9.0000');
});
