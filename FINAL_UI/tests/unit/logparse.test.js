'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const L = H.logic('logparse.js');

test('[STAGE]', () => {
  assert.deepEqual(L.parse('[STAGE] Extracting 117C'), { kind: 'stage', text: 'Extracting 117C', name: 'Extracting 117C' });
});
test('[SPEC] with and without a severity', () => {
  assert.equal(L.parse('[SPEC] HIGH: Callout is ambiguous').severity, 'HIGH');
  assert.equal(L.parse('[SPEC] CRITICAL: x').kind, 'spec');
  const e = L.parse('[SPEC] Stage 2.6: 2 constraint(s) parsed');
  assert.equal(e.kind, 'spec'); assert.equal(e.severity, null); assert.equal(e.text, 'Stage 2.6: 2 constraint(s) parsed');
});
test('[PREVAL]', () => {
  assert.equal(L.parse('[PREVAL] PASS — watertight pre-validated solid').pass, true);
  assert.equal(L.parse('[PREVAL] MM1 hole count mismatch').pass, null);
});
test('[MM] constraint and error forms', () => {
  const e = L.parse('[MM] MM2 PASS: required 0.250 in, measured 0.250 in');
  assert.deepEqual([e.kind, e.id, e.status, e.required, e.measured], ['mm', 'MM2', 'PASS', '0.250 in', '0.250 in']);
  const f = L.parse('[MM] MM1 FAIL: required 4 holes, measured 3 holes');
  assert.equal(f.status, 'FAIL');
  const err = L.parse('[MM] verification error: trimesh failed');
  assert.equal(err.error, true); assert.equal(err.text, 'trimesh failed');
});
test('[OVERVIEW]', () => {
  assert.equal(L.parse('[OVERVIEW] HIGH: Hole pitch differs').kind, 'overview');
});
test('[delivered outputs to]', () => {
  const e = L.parse('[delivered outputs to] /srv/UI_Output/117C');
  assert.equal(e.kind, 'delivered'); assert.equal(e.path, '/srv/UI_Output/117C');
});
test('[cancel requested by user]', () => {
  assert.equal(L.parse('[cancel requested by user]').kind, 'cancel');
});
test('[launch error], [reader error], extraction and processing failures', () => {
  assert.deepEqual([L.parse('[launch error] FileNotFoundError: x').kind, L.parse('[launch error] FileNotFoundError: x').source], ['error', 'launch error']);
  assert.equal(L.parse('[reader error] UnicodeDecodeError: y').kind, 'error');
  assert.equal(L.parse('  Extraction failed: APIConnectionError: boom').source, 'extraction');
  assert.equal(L.parse('  Processing failed: ValueError: z').source, 'processing');
});
test('ordinary lines return null; CR is stripped', () => {
  assert.equal(L.parse('Multi-view build: 1 part(s)'), null);
  assert.equal(L.parse(''), null);
  assert.equal(L.parse('[STAGE] Done\r').text, 'Done');
});
test('events over a real transcript, with indexes and an exit event', () => {
  const lines = H.lines('part_full.log');
  const ev = L.events(lines, { exit: 0 });
  const kinds = new Set(ev.map((e) => e.kind));
  for (const k of ['stage', 'spec', 'preval', 'mm', 'overview', 'delivered', 'exit']) assert.ok(kinds.has(k), k);
  assert.equal(ev.filter((e) => e.kind === 'stage').length, 12);
  assert.equal(ev.filter((e) => e.kind === 'delivered').length, 2);
  assert.equal(ev[0].index, lines.findIndex((l) => l.startsWith('[STAGE]')));
  const last = ev[ev.length - 1];
  assert.deepEqual([last.kind, last.exit], ['exit', 0]);
  assert.equal(L.events(lines).some((e) => e.kind === 'exit'), false);
  assert.deepEqual(L.events([]), []);
  assert.equal(L.events(H.lines('part_cancelled.log'), { exit: -15 }).filter((e) => e.kind === 'cancel').length, 1);
});
test('level classification for console filters', () => {
  assert.equal(L.level('[STAGE] Verifying'), 'stage');
  assert.equal(L.level('[3/4] Verifying extracted data...'), 'stage');
  assert.equal(L.level('  Extraction failed: x'), 'error');
  assert.equal(L.level('[MM] MM1 FAIL: required 4, measured 3'), 'error');
  assert.equal(L.level('[SPEC] HIGH: foo'), 'warning');
  assert.equal(L.level('  warning: No FRONT view'), 'warning');
  assert.equal(L.level('[MM] MM1 PASS: required 4, measured 4'), 'info');
});
