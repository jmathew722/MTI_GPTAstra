'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { logic } = require('./_helpers');
const T = logic('resulttone.js');

const P = (c) => ({ has_any: true, categories: c });
const tone = (id, c, extra) => T.sectionTone(id, P(c), extra, (l) => (/ERR/.test(l) ? 'error' : /WARN/.test(l) ? 'warning' : 'info'));

test('build plan: green when everything built, red/orange when not, amber for fallbacks and open questions', () => {
  const bp = { present: true };
  assert.deepEqual(tone('build_plan', { build_plan: bp, ir_report: { sw_features: { F1: 'built', F2: 'built (2 edges)' } } }), { tone: 'green', word: 'all built' });
  assert.equal(tone('build_plan', { build_plan: bp, ir_report: { sw_features: { F1: 'built', F2: 'skipped: n/a' } } }).tone, 'orange');
  assert.equal(tone('build_plan', { build_plan: bp, ir_report: { sw_features: { F1: 'failed' } } }).tone, 'red');
  assert.equal(tone('build_plan', { build_plan: bp, ir_report: { sw_features: { F1: 'built (plain cut fallback)' } } }).tone, 'amber');
  assert.equal(tone('build_plan', { build_plan: bp, ir_report: { sw_features: { F1: 'built' }, questions: ['F2?'] } }).word, '1 open question');
  assert.equal(tone('build_plan', { build_plan: bp, ir_report: {} }).tone, 'blue');
  assert.equal(tone('build_plan', { build_plan: { present: false } }).tone, 'none');
});

test('engineering flags: the worst severity wins; practice advisories never colour it', () => {
  assert.equal(tone('flags', { review: { present: true, items: [{ severity: 'HIGH' }, { severity: 'LOW' }] } }).tone, 'orange');
  assert.equal(tone('flags', { review: { present: true, items: [{ severity: 'CRITICAL' }] } }).tone, 'red');
  assert.equal(tone('flags', { review: { present: true, items: [{ severity: 'MEDIUM' }] } }).tone, 'amber');
  assert.equal(tone('flags', { review: { present: true, items: [] } }).word, 'no flags');
  assert.equal(tone('flags', { flags: { present: true, findings: [{ severity: 'info', category: 'practice_advisory' }] } }).tone, 'green');
  assert.equal(tone('flags', { flags: { present: true, findings: [{ severity: 'error', category: 'x' }] } }).tone, 'red');
  assert.equal(tone('flags', {}).tone, 'none');
});

test('verification and model check read the verdict or the report text', () => {
  assert.equal(tone('verification', { verification: { present: true, text: 'x' } }, { verdict: 'passed' }).tone, 'green');
  assert.equal(tone('verification', {}, { verdict: 'failed' }).tone, 'red');
  assert.equal(tone('verification', {}, { verdict: 'flags' }).tone, 'amber');
  assert.equal(tone('verification', { verification: { present: true, text: 'Result: PASS' } }).tone, 'green');
  assert.equal(tone('verification', { verification: { present: true, text: 'BLOCKED: missing view' } }).tone, 'red');
  assert.equal(tone('model_check', { model_check: { present: true, text: 'all checks OK' } }).tone, 'green');
  assert.equal(tone('model_check', { model_check: { present: true, text: 'volume MISMATCH' } }).tone, 'red');
  assert.equal(tone('model_check', {}).tone, 'none');
});

test('recording, must-meet, cost, files and console tones', () => {
  assert.deepEqual(['ready', 'partial', 'failed', 'skipped', 'stale', 'recording'].map((s) => tone('recording', { recording: { present: true, status: s } }).tone), ['green', 'amber', 'red', 'amber', 'amber', 'blue']);
  assert.equal(tone('recording', { recording: { present: false } }).tone, 'none');
  assert.equal(tone('must_meet', { must_meet: { present: true, results: [{ status: 'PASS' }, { status: 'FAIL' }] } }).word, '1 failed');
  assert.equal(tone('must_meet', { must_meet: { present: true, results: [{ status: 'PASS' }] } }).tone, 'green');
  const cost = (s) => tone('cost', { usage: { present: true, ledger: { scopes: { part: { pricing_status: s } } } } }).tone;
  assert.deepEqual([cost('priced'), cost('partial'), cost('unpriced')], ['green', 'amber', 'orange']);
  assert.equal(tone('files', { files: { present: true }, sldprt: { present: true }, stl: { present: true, source: 'solidworks' } }).tone, 'green');
  assert.equal(tone('files', { files: { present: true }, stl: { present: true, source: 'prevalidation' } }).tone, 'amber');
  assert.equal(tone('console', {}, { lines: ['a', 'WARN x', 'ERR y', 'ERR z'] }).word, '2 errors');
  assert.equal(tone('console', {}, { lines: ['a', 'WARN x'] }).tone, 'amber');
  assert.equal(tone('console', {}, { lines: ['a'] }).tone, 'green');
  assert.equal(tone('console', {}, { lines: [] }).tone, 'none');
});

test('overview follows the verdict; unknown sections have no tone; worst() ranks tones', () => {
  assert.equal(tone('overview', {}, { verdict: 'failed' }).tone, 'red');
  assert.equal(T.sectionTone('overview', null, {}).tone, 'none');
  assert.equal(tone('nope', {}).tone, 'none');
  assert.equal(T.worst('green', 'amber'), 'amber');
  assert.equal(T.worst('red', 'blue'), 'red');
});

test('fileTone: one colour per kind of deliverable', () => {
  assert.deepEqual(['a.SLDPRT', 'a.stl', 'x.json', 'm.pdf', 'p.png', 'v.mp4', 'run.log', 'no_ext'].map(T.fileTone), ['blue', 'violet', 'amber', 'red', 'green', 'orange', 'none', 'none']);
});
