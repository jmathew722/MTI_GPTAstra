'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { logic } = require('./_helpers');
const SV = logic('scoringview.js');

test('statusOf: generation failed, scoring failed and incomplete are three different states', () => {
  assert.equal(SV.statusOf({ state: 'scored', exact: true }).label, 'Scored, exact');
  assert.equal(SV.statusOf({ state: 'scored' }).tone, 'ok');
  assert.deepEqual([SV.statusOf({ state: 'scoring_failed' }).kind, SV.statusOf({ state: 'scoring_failed' }).tone], ['scoring_failed', 'err']);
  assert.equal(SV.statusOf({ state: 'incomplete' }).tone, 'warn');
  const gen = SV.statusOf({ state: 'no_output' }, { state: 'failed' });
  assert.equal(gen.kind, 'generation_failed');
  const kinds = new Set([SV.statusOf({ state: 'scoring_failed' }).kind, SV.statusOf({ state: 'incomplete' }).kind, gen.kind]);
  assert.equal(kinds.size, 3);
});

test('statusOf: pending, no part, not run yet', () => {
  assert.equal(SV.statusOf({ state: 'pending', has_output: true, has_part: true }).kind, 'pending');
  assert.equal(SV.statusOf({ state: 'pending', has_output: true, has_part: false }).kind, 'no_part');
  assert.equal(SV.statusOf({ state: 'no_output' }).kind, 'no_output');
  assert.equal(SV.statusOf(null).kind, 'pending');
});

test('a missing score is a dash, never 0; a real zero is shown as 0.0', () => {
  assert.equal(SV.scoreText({ state: 'incomplete', score: null }), '–');
  assert.equal(SV.scoreText({ state: 'scoring_failed' }), '–');
  assert.equal(SV.scoreText({ state: 'scored', score: 0 }), '0.0 / 100');
  assert.equal(SV.scoreText({ state: 'scored', score: 91.04 }), '91.0 / 100');
  assert.equal(SV.scoreText({ state: 'scored', score: NaN }), '–');
  assert.equal(SV.avgText(null), '–');
  assert.equal(SV.avgText(87.456), '87.5 / 100');
  assert.equal(SV.practicesText({}), '–');
  assert.equal(SV.practicesText({ practices_score: 71.4 }), '71 / 100');
});

test('filter searches part, status label and run id; empty query keeps everything', () => {
  const rows = [{ part: 'Alpha', state: 'scored', run_id: 'run_a' }, { part: 'Beta', state: 'incomplete', run_id: 'run_b' }, { part: 'Gamma', state: 'scoring_failed' }];
  assert.equal(SV.filter(rows, '').length, 3);
  assert.deepEqual(SV.filter(rows, 'alp').map((r) => r.part), ['Alpha']);
  assert.deepEqual(SV.filter(rows, 'incomplete').map((r) => r.part), ['Beta']);
  assert.deepEqual(SV.filter(rows, 'RUN_B').map((r) => r.part), ['Beta']);
  assert.equal(SV.filter(rows, 'zzz').length, 0);
});

test('evalBlocker needs output', () => {
  assert.match(SV.evalBlocker({ has_output: false }), /Run the part first/);
  assert.equal(SV.evalBlocker({ has_output: true }), '');
});

test('breakdown and awarded points reconcile: awarded + lost = max, and the maxima sum to 100', () => {
  const rec = { rows: [
    { feature_id: 'BASE', type: 'base_body', weight: 10, status: 'matched', attr_credits: { size: 1 }, credit: 1, points_lost: 0, blame: '', reason: '' },
    { feature_id: 'H1', type: 'thru_hole', weight: 2.5, status: 'matched', attr_credits: { position: 0.4, size: 1, depth: 1, type: 1 }, credit: 0.67, points_lost: 4.125, blame: 'planner', reason: 'position 2x tolerance' },
    { feature_id: 'H2', type: 'thru_hole', weight: 2.5, status: 'missing', attr_credits: {}, credit: 0, points_lost: 12.5, blame: 'planner', reason: 'missing' },
    { feature_id: 'H3', type: 'thru_hole', weight: 5, status: 'matched', attr_credits: { position: 1, size: 1, depth: 1, type: 1 }, credit: 1, points_lost: 0, blame: '', reason: '' } ] };
  const b = SV.breakdown(rec);
  assert.equal(b[1].position, '40%');
  assert.equal(b[2].position, '–');
  const a = SV.awarded(rec);
  assert.equal(a.reduce((x, r) => x + r.max, 0).toFixed(2), '100.00');
  a.forEach((r) => assert.ok(Math.abs(r.awarded + r.lost - r.max) < 0.02));
  assert.deepEqual(SV.stageRollup({ blame: { H1: { stage: 'planner', points: 4.125 }, H2: { stage: 'planner', points: 12.5 }, X: { stage: 'solidworks', points: 1 } } }),
    [{ stage: 'planner', points: 16.63 }, { stage: 'solidworks', points: 1 }]);
  assert.deepEqual(SV.breakdown(null), []);
});
