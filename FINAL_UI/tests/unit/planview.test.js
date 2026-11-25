'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { logic } = require('./_helpers');
const P = logic('planview.js');

const REAL = path.resolve(__dirname, '../../../FINAL_OUTPUTs/A040501E');
const real = (f) => JSON.parse(fs.readFileSync(path.join(REAL, f), 'utf8'));

const IR = { dims: { D001: 8, D002: 2, D010: 3.501 }, reference_ids: ['D002'],
  plan: { ir_version: '2.0', part: 'P', frame: { origin_kind: 'axis_end', units: 'inch' }, notes: ['n1'], features: [
    { id: 'F001', kind: 'revolve', op: 'add', rationale: 'Turn the shaft', outer: [{ z: '0', r: 'D010 / 2' }, { z: 'D001', r: 'D010 / 2' }], source_callouts: ['8.000'] },
    { id: 'F002', kind: 'prism', op: 'cut', rationale: 'Cut a recess', depth: 'D001 / 4', profile: { shape: 'rect', w: 'D010', h: 'D999' } },
    { id: 'F003', kind: 'hole', rationale: 'Drill', diameter: '0.3125', depth: 'D002 * 2 + 0.5' },
    { id: 'F004', kind: 'edge_op', rationale: 'Chamfer the end' },
    { id: 'F005', kind: 'pattern', rationale: 'Pattern the holes' }] } };
const SW = { F001: 'built', F002: 'built (2 edges selected)', F003: 'built (drill + counterbore)', F004: 'skipped: not applicable' };

test('detect tells the Feature-IR plan from the legacy v1 plan: the IR plan has no steps array', () => {
  assert.equal(P.detect(IR), 'ir');
  assert.equal(P.detect({ steps: [] }), 'v1');
  assert.equal(P.detect({ plan: {} }), 'unknown');
  assert.equal(P.detect(null), 'unknown');
  assert.equal(IR.steps, undefined, 'the IR shape really has no steps: this is why the old viewer was empty');
});

test('evalExpr: arithmetic over dimension ids, never eval', () => {
  const d = { D001: 8, D010: 3.501, D009: 0.5 };
  assert.equal(P.evalExpr('D010 / 2', d), 1.7505);
  assert.equal(P.evalExpr('D010 / 2 - D009', d), 1.2505);
  assert.equal(P.evalExpr('-D004 / 2', { D004: 3 }), -1.5);
  assert.equal(P.evalExpr('(D001 + 2) * 2', d), 20);
  assert.equal(P.evalExpr('0', d), 0);
  assert.equal(P.evalExpr(1.5, d), 1.5);
  assert.equal(P.evalExpr('D999', d), null, 'unknown id');
  assert.equal(P.evalExpr('axis(part)', d), null);
  assert.equal(P.evalExpr('plane(top)', d), null);
  assert.equal(P.evalExpr('D001 +', d), null);
  assert.equal(P.evalExpr('process.exit(1)', d), null);
  assert.equal(P.evalExpr('1; alert(1)', d), null);
  assert.equal(P.evalExpr('', d), null);
  assert.equal(P.evalExpr('D001 / 0', d), null, 'infinity is not a number');
});

test('kindMeta: one colour family per kind of operation', () => {
  assert.deepEqual([P.kindMeta({ kind: 'hole' }).tone, P.kindMeta({ kind: 'pattern' }).tone, P.kindMeta({ kind: 'edge_op' }).tone], ['violet', 'violet', 'amber']);
  assert.equal(P.kindMeta({ kind: 'prism', op: 'cut' }).tone, 'orange');
  assert.equal(P.kindMeta({ kind: 'revolve', op: 'add' }).tone, 'blue');
  assert.match(P.kindMeta({ kind: 'prism', op: 'cut' }).label, /Extrude \(cut\)/);
  assert.equal(P.kindMeta({ kind: 'weird_thing' }).label, 'weird thing');
});

test('statusOf: built, fallback, skipped, needs a decision, no status, not built yet', () => {
  const f = {};
  assert.deepEqual([P.statusOf('F1', { F1: 'built' }, f).id, P.statusOf('F1', { F1: 'built' }, f).tone], ['built', 'green']);
  assert.equal(P.statusOf('F1', { F1: 'built (plain cut fallback)' }, f).id, 'fallback');
  assert.equal(P.statusOf('F1', { F1: 'skipped: nothing to do' }, f).tone, 'red');
  assert.equal(P.statusOf('F1', { F1: 'failed: no selection' }, f).id, 'failed');
  assert.equal(P.statusOf('F7', { F1: 'built' }, f, ['F7: which edges?']).id, 'decision');
  assert.equal(P.statusOf('F7', { F1: 'built' }, f, ['F70: x']).label, 'No build status', 'F7 does not match the question about F70');
  assert.equal(P.statusOf('F9', { F1: 'built' }, f).label, 'No build status');
  assert.equal(P.statusOf('F9', null, f).label, 'Planned', 'with no build record yet it is simply planned');
  assert.equal(P.statusOf('F9', null, { status: 'skipped_prohibited' }).id, 'skipped');
});

test('read: operations in build order, status from SolidWorks, numbers resolved, counts add up', () => {
  const r = P.read(IR, { sw_features: SW, questions: [], flagged: ['F002: use the section view', 'F003: tap drill 5/16'], defaults: ['F004: D7 fillet 0.25'] });
  assert.equal(r.kind, 'ir');
  assert.deepEqual(r.features.map((f) => f.id), ['F001', 'F002', 'F003', 'F004', 'F005']);
  assert.deepEqual(r.features.map((f) => f.status.id), ['built', 'built', 'built', 'skipped', 'planned']);
  assert.equal(r.features[4].status.label, 'No build status', 'SolidWorks reported nothing for F005');
  const s = r.summary;
  assert.equal(s.total, 5);
  assert.equal(s.built + s.fallback + s.skipped + s.decision + s.planned, 5);
  assert.equal(s.built, 3); assert.equal(s.skipped, 1);
  assert.equal(r.units, 'inch'); assert.equal(r.part, 'P'); assert.deepEqual(r.notes, ['n1']);
  const f1 = r.features[0].params.find((p) => p.key === 'outer[1].r');
  assert.deepEqual([f1.raw, f1.value], ['D010 / 2', 1.7505]);
  assert.equal(r.features[2].params.find((p) => p.key === 'depth').value, 4.5);
  assert.equal(r.features[2].params.find((p) => p.key === 'diameter').value, null, 'a literal number needs no resolved value');
  assert.equal(r.features[1].params.find((p) => p.key === 'profile.h').value, null, 'unknown dimension id stays unresolved');
  assert.deepEqual(r.features[1].flags, ['use the section view']);
  assert.deepEqual(r.features[3].defaults, ['D7 fillet 0.25']);
});

test('dimension usage: unused dimensions are counted, reference ids are not "unused"', () => {
  const r = P.read(IR, { sw_features: SW });
  assert.deepEqual(r.usage, { D001: 2, D002: 1, D010: 3 });
  assert.equal(r.summary.dims, 3);
  assert.equal(r.summary.unusedDims, 0);
  const r2 = P.read({ ...IR, dims: { ...IR.dims, D050: 1 } }, null);
  assert.equal(r2.usage.D050, 0);
  assert.equal(r2.summary.unusedDims, 1);
});

test('search matches id, kind, rationale, callouts and parameters', () => {
  const r = P.read(IR, { sw_features: SW });
  const hit = (q) => r.features.filter((f) => P.matches(f, q)).map((f) => f.id);
  assert.deepEqual(hit(''), ['F001', 'F002', 'F003', 'F004', 'F005']);
  assert.deepEqual(hit('recess'), ['F002']);
  assert.deepEqual(hit('8.000'), ['F001']);
  assert.deepEqual(hit('skipped'), ['F004']);
  assert.deepEqual(hit('diameter'), ['F003']);
  assert.deepEqual(hit('zzz'), []);
});

test('a real IR build: A040501E plan.json reads into 10 operations with SolidWorks statuses', { skip: !fs.existsSync(REAL) }, () => {
  const plan = real('plan.json'), ir = real('ir_report.json');
  const r = P.read(plan, ir);
  assert.equal(r.kind, 'ir');
  assert.equal(r.features.length, 10, 'the old viewer showed 0 of these');
  assert.equal(r.summary.built, 10);
  assert.equal(r.summary.skipped, 0);
  assert.equal(r.features[0].kind, 'revolve');
  assert.ok(r.features.every((f) => f.status.id === 'built'));
  assert.ok(r.features[6].params.length > 0);
  const f6 = r.features.find((f) => f.id === 'F006');
  assert.ok(f6.flags.length >= 1 || f6.defaults.length >= 1, 'flags and defaults are attached to their operation');
});
