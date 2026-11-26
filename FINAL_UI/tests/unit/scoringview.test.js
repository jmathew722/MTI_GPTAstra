'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { logic } = require('./_helpers');
const SV = logic('scoringview.js');

test('statusOf: the grade comes from the actual score; unscored states are neutral, never a grade colour', () => {
  const s = SV.statusOf({ state: 'scored', score: 95 });
  assert.deepEqual([s.kind, s.tone, s.label, s.color], ['scored', 'excellent', 'Excellent', '#8DD49A']);
  assert.equal(SV.statusOf({ state: 'scored', score: 100 }).label, 'Perfect');
  assert.equal(SV.statusOf({ state: 'scored', score: 99.99 }).label, 'Excellent', 'never promoted to Perfect');
  assert.equal(SV.statusOf({ state: 'scored', score: 39.9 }).tone, 'poor');
  assert.equal(SV.statusOf({ state: 'scored', score: 50, band: { id: 'green' } }).tone, 'below', 'a server band is ignored');
  ['no_model', 'incomplete', 'scoring_failed', 'pending', 'no_output'].forEach((st) => {
    const r = SV.statusOf({ state: st, reason: 'no_mesh' });
    assert.equal(r.tone, 'none', st);
    assert.equal(r.color, '#92949E', st);
  });
});

test('a failed build, an incomplete input and a failed scorer are three different states', () => {
  const noModel = SV.statusOf({ state: 'no_model' }), inc = SV.statusOf({ state: 'incomplete', reason: 'no_mesh' }), fail = SV.statusOf({ state: 'scoring_failed' });
  assert.deepEqual([noModel.kind, inc.kind, fail.kind], ['no_model', 'incomplete', 'scoring_failed']);
  assert.equal(new Set([noModel.label, inc.label, fail.label]).size, 3);
  assert.match(inc.label, /No exported STL/);
  assert.equal(SV.statusOf({ state: 'no_output' }, { state: 'failed' }).kind, 'generation_failed');
  assert.equal(SV.statusOf(null).kind, 'pending');
});

test('a missing score is a dash, never 0; a real 0 is shown; formatting never rounds up', () => {
  assert.equal(SV.scoreText({ state: 'incomplete', score: null }), '–');
  assert.equal(SV.scoreText({ state: 'no_model' }), '–');
  assert.equal(SV.scoreText({ state: 'scored', score: 0 }), '0.0');
  assert.equal(SV.scoreText({ state: 'scored', score: 99.96 }), '99.9');
  assert.equal(SV.scoreText({ state: 'scored', score: 100 }), '100.0');
  assert.equal(SV.scoreFull({ state: 'scored', score: 91.04 }), '91.0 / 100');
  assert.equal(SV.scoreFull({ state: 'scored', score: NaN }), '–');
  assert.equal(SV.avgText(null), '–');
  assert.equal(SV.avgText(87.456), '87.4 / 100');
});

test('issues are grouped worst first and summarised', () => {
  const g = SV.groupIssues([{ severity: 'low', code: 'a' }, { severity: 'critical', code: 'b' }, { severity: 'high', code: 'c' }, { severity: 'critical', code: 'd' }]);
  assert.deepEqual(g.map((x) => [x.severity, x.items.length]), [['critical', 2], ['high', 1], ['low', 1]]);
  assert.equal(SV.issueSummary({ critical: 2, high: 1, medium: 0, low: 3, info: 9 }), '2 critical · 1 high · 3 low');
  assert.equal(SV.issueSummary({}), '');
  assert.equal(SV.severityMeta('nope').label, 'Note');
});

test('filter searches part, status and run id; needs-attention lists the worst scores first and skips unscored', () => {
  const rows = [{ part: 'Alpha', state: 'scored', score: 95, run_id: 'run_a' }, { part: 'Beta', state: 'incomplete', reason: 'no_mesh' },
    { part: 'Gamma', state: 'scored', score: 40 }, { part: 'Delta', state: 'scored', score: 40 }, { part: 'Eps', state: 'scored', score: null }];
  assert.equal(SV.filter(rows, '').length, 5);
  assert.deepEqual(SV.filter(rows, 'alp').map((r) => r.part), ['Alpha']);
  assert.deepEqual(SV.filter(rows, 'no exported').map((r) => r.part), ['Beta']);
  assert.deepEqual(SV.filter(rows, 'below average').map((r) => r.part), ['Gamma', 'Delta']);
  assert.deepEqual(SV.filter(rows, 'RUN_A').map((r) => r.part), ['Alpha']);
  assert.deepEqual(SV.byAttention(rows).map((r) => r.part), ['Delta', 'Gamma', 'Alpha']);
});

test('evalBlocker needs output', () => {
  assert.match(SV.evalBlocker({ has_output: false }), /Run the part first/);
  assert.equal(SV.evalBlocker({ has_output: true }), '');
});

test('category rows and item rows are graded by the same spectrum', () => {
  const rec = { categories: [{ id: 'envelope', label: 'Overall size', weight: 20, checked: true, score: 82.5, earned: 16.5, max: 20, n_checked: 3, n_total: 3,
    items: [{ id: 'D1', label: 'overall length', weight: 1, credit: 0.5, expected: 6, measured: 6.02, unit: 'inch', error: 0.02, tol: 0.01, e: 2 },
            { id: 'D2', label: 'width', weight: 1, credit: 1, expected: 4, measured: 4 }, { id: 'D3', label: 'x', weight: 1, credit: null },
            { id: 'D4', label: 'y', weight: 1, credit: 0.999 }] },
    { id: 'placement', label: 'Placement', weight: 15, checked: false, score: null, n_checked: 0, n_total: 0 }] };
  const c = SV.catRows(rec);
  assert.deepEqual([c[0].id, c[0].score, c[0].grade.id, c[0].n], ['envelope', 82.5, 'good', '3 of 3 checked']);
  assert.deepEqual([c[1].checked, c[1].grade.id], [false, 'none']);
  const it = SV.itemRows(rec.categories[0]);
  assert.equal(it[0].error, '+0.02 in (2× tol)');
  assert.deepEqual([it[0].credit, it[0].grade.id], ['50%', 'below']);
  assert.deepEqual([it[1].credit, it[1].grade.id, it[1].error], ['100%', 'perfect', '']);
  assert.deepEqual([it[2].credit, it[2].grade.id], ['–', 'none']);
  assert.deepEqual([it[3].credit, it[3].grade.id], ['99%', 'excellent']);
  assert.deepEqual(SV.catRows(null), []);
});

test('distribution: six grades over the scored parts’ actual scores', () => {
  const rows = [{ state: 'scored', score: 100 }, { state: 'scored', score: 99.9 }, { state: 'scored', score: 81 }, { state: 'scored', score: 10 },
    { state: 'incomplete', score: null }, { state: 'scored', score: null }];
  const d = SV.distribution(rows);
  assert.deepEqual(d.map((x) => [x.id, x.count]), [['poor', 1], ['below', 0], ['fair', 0], ['good', 1], ['excellent', 1], ['perfect', 1]]);
  assert.equal(Math.round(d.reduce((a, x) => a + x.pct, 0)), 100);
  assert.deepEqual(SV.distribution(null).map((x) => x.count), [0, 0, 0, 0, 0, 0]);
});

test('a scored row whose score is missing or out of range is "Score unavailable" in neutral grey, never a grade', () => {
  [null, undefined, NaN, -1, 130].forEach((v) => {
    const st = SV.statusOf({ state: 'scored', score: v });
    assert.deepEqual([st.kind, st.tone, st.label, st.color], ['invalid', 'none', 'Score unavailable', '#92949E']);
    assert.equal(SV.scoreText({ state: 'scored', score: v }), '–');
  });
});
