'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { logic } = require('./_helpers');
const SV = logic('scoringview.js');

test('bands: inclusive lower bounds, one colour per band, a word and a glyph each', () => {
  const ids = [100, 90, 89.9, 75, 74.9, 60, 59.9, 0].map((s) => SV.bandOf(s).id);
  assert.deepEqual(ids, ['green', 'green', 'amber', 'amber', 'orange', 'orange', 'red', 'red']);
  SV.BANDS.forEach((b) => { assert.ok(b.label); assert.ok(b.glyph); });
  assert.equal(new Set(SV.BANDS.map((b) => b.glyph)).size, 4, 'glyphs differ, so colour is never the only cue');
  assert.equal(SV.bandOf(null).id, 'none');
  assert.equal(SV.bandOf(NaN).label, 'Not scored');
  assert.equal(SV.bandOf(80, [{ id: 'x', min: 50, label: 'X', glyph: 'x' }, { id: 'y', min: 0, label: 'Y', glyph: 'y' }]).id, 'x', 'server bands win');
});

test('statusOf: a failed build, an incomplete input and a failed scorer are three different states', () => {
  const scored = SV.statusOf({ state: 'scored', score: 95, band: { id: 'green', label: 'Matches the drawing', glyph: '✓' } });
  assert.deepEqual([scored.kind, scored.tone, scored.label], ['scored', 'green', 'Matches the drawing']);
  const noModel = SV.statusOf({ state: 'no_model' });
  const inc = SV.statusOf({ state: 'incomplete', reason: 'no_mesh' });
  const fail = SV.statusOf({ state: 'scoring_failed' });
  assert.deepEqual([noModel.kind, inc.kind, fail.kind], ['no_model', 'incomplete', 'scoring_failed']);
  assert.equal(new Set([noModel.label, inc.label, fail.label]).size, 3);
  assert.match(inc.label, /No exported STL/);
  assert.equal(inc.tone, 'amber');
  assert.equal(SV.statusOf({ state: 'pending' }).kind, 'pending');
  assert.equal(SV.statusOf({ state: 'no_output' }).kind, 'no_output');
  assert.equal(SV.statusOf({ state: 'no_output' }, { state: 'failed' }).kind, 'generation_failed');
  assert.equal(SV.statusOf(null).kind, 'pending');
});

test('a missing score is a dash, never 0; a real 0 is shown', () => {
  assert.equal(SV.scoreText({ state: 'incomplete', score: null }), '–');
  assert.equal(SV.scoreText({ state: 'no_model' }), '–');
  assert.equal(SV.scoreText({ state: 'scored', score: 0 }), '0.0');
  assert.equal(SV.scoreFull({ state: 'scored', score: 91.04 }), '91.0 / 100');
  assert.equal(SV.scoreFull({ state: 'scored', score: NaN }), '–');
  assert.equal(SV.avgText(null), '–');
  assert.equal(SV.avgText(87.456), '87.5 / 100');
});

test('issues are grouped worst first and summarised', () => {
  const g = SV.groupIssues([{ severity: 'low', code: 'a' }, { severity: 'critical', code: 'b' }, { severity: 'high', code: 'c' }, { severity: 'critical', code: 'd' }]);
  assert.deepEqual(g.map((x) => [x.severity, x.items.length]), [['critical', 2], ['high', 1], ['low', 1]]);
  assert.equal(SV.issueSummary({ critical: 2, high: 1, medium: 0, low: 3, info: 9 }), '2 critical · 1 high · 3 low');
  assert.equal(SV.issueSummary({}), '');
  assert.equal(SV.severityMeta('nope').label, 'Note');
});

test('filter searches part, status, band and run id; needs-attention lists the worst scores first', () => {
  const rows = [{ part: 'Alpha', state: 'scored', score: 95, band: { label: 'Matches the drawing' }, run_id: 'run_a' }, { part: 'Beta', state: 'incomplete', reason: 'no_mesh' },
    { part: 'Gamma', state: 'scored', score: 40, band: { label: 'Does not match' } }, { part: 'Delta', state: 'scored', score: 40 }];
  assert.equal(SV.filter(rows, '').length, 4);
  assert.deepEqual(SV.filter(rows, 'alp').map((r) => r.part), ['Alpha']);
  assert.deepEqual(SV.filter(rows, 'no exported').map((r) => r.part), ['Beta']);
  assert.deepEqual(SV.filter(rows, 'does not match').map((r) => r.part), ['Gamma', 'Delta']);   // a score with no stored band still gets its band label
  assert.deepEqual(SV.filter(rows, 'RUN_A').map((r) => r.part), ['Alpha']);
  assert.deepEqual(SV.byAttention(rows).map((r) => r.part), ['Delta', 'Gamma', 'Alpha']);
});

test('evalBlocker needs output', () => {
  assert.match(SV.evalBlocker({ has_output: false }), /Run the part first/);
  assert.equal(SV.evalBlocker({ has_output: true }), '');
});

test('category rows and item rows keep expected, measured, error and a coloured credit', () => {
  const rec = { categories: [{ id: 'envelope', label: 'Overall size', weight: 20, checked: true, score: 82.5, earned: 16.5, max: 20, n_checked: 3, n_total: 3, band: { id: 'amber' },
    items: [{ id: 'D1', label: 'overall length', weight: 1, credit: 0.5, expected: 6, measured: 6.02, unit: 'inch', error: 0.02, tol: 0.01, e: 2 },
            { id: 'D2', label: 'width', weight: 1, credit: 1, expected: 4, measured: 4 }, { id: 'D3', label: 'x', weight: 1, credit: null }] },
    { id: 'placement', label: 'Placement', weight: 15, checked: false, score: null, n_checked: 0, n_total: 0 }] };
  const c = SV.catRows(rec);
  assert.deepEqual([c[0].id, c[0].score, c[0].band.id, c[0].n], ['envelope', 82.5, 'amber', '3 of 3 checked']);
  assert.equal(c[1].checked, false);
  assert.equal(c[1].band.id, 'none');
  const it = SV.itemRows(rec.categories[0]);
  assert.equal(it[0].error, '+0.02 in (2× tol)');
  assert.deepEqual([it[0].credit, it[0].band.id], ['50%', 'red']);
  assert.deepEqual([it[1].credit, it[1].band.id, it[1].error], ['100%', 'green', '']);
  assert.deepEqual([it[2].credit, it[2].band.id], ['–', 'none']);
  assert.deepEqual(SV.catRows(null), []);
});

test('distribution: segments over scored parts only, percentages add up', () => {
  const d = SV.distribution({ distribution: { green: 2, amber: 1, orange: 0, red: 1 } });
  assert.deepEqual(d.map((x) => [x.id, x.count, x.pct]), [['green', 2, 50], ['amber', 1, 25], ['orange', 0, 0], ['red', 1, 25]]);
  assert.deepEqual(SV.distribution({ distribution: {} }).map((x) => x.pct), [0, 0, 0, 0]);
  assert.deepEqual(SV.distribution(null).map((x) => x.count), [0, 0, 0, 0]);
});

test('sym: server glyph names become symbols, symbols pass through', () => {
  assert.deepEqual(['check', 'alert', 'warn', 'x', 'dash'].map(SV.sym), ['✓', '!', '▲', '✕', '–']);
  assert.equal(SV.sym('✓'), '✓');
  assert.equal(SV.sym(undefined), '–');
});
