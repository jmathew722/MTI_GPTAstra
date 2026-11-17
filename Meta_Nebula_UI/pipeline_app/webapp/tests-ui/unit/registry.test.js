'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const G = H.logic('registry.js');

test('every categories key maps to exactly one section', () => {
  const cov = G.coverage();
  assert.deepEqual(cov.unmapped, []);
  assert.deepEqual(cov.duplicated, []);
  assert.deepEqual(cov.unknown, []);
  assert.equal(Object.keys(cov.map).length, G.CATEGORY_KEYS.length);
  // and against a real payload's keys
  const real = Object.keys(H.payload().categories);
  assert.deepEqual(G.coverage(real).unmapped, []);
  assert.deepEqual(real.slice().sort(), G.CATEGORY_KEYS.slice().sort());
});

test('five groups in the required order, thirteen sections with required fields', () => {
  assert.deepEqual(G.GROUPS.map((g) => g.label), ['Overview', 'Extraction', 'Build & Verification', 'Automation & Files', 'Diagnostics']);
  assert.equal(G.sections.length, 13);
  assert.deepEqual(G.sections.map((s) => s.id), ['overview', 'extraction', 'resolved', 'overview_analysis', 'build_plan',
    'verification', 'flags', 'model_check', 'macros', 'files', 'cost', 'console', 'events']);
  const order = G.GROUPS.map((g) => g.id);
  let last = -1;
  for (const s of G.sections) {
    const gi = order.indexOf(s.group);
    assert.ok(gi >= 0, s.id); assert.ok(gi >= last, 'sections are ordered by group: ' + s.id); last = gi;
    assert.equal(typeof s.label, 'string'); assert.ok(s.emptyText.length > 0); assert.ok(Array.isArray(s.tools));
    assert.equal(typeof s.source, 'function'); assert.equal(typeof s.status, 'function');
    assert.equal(s.render, undefined, 'render is added by the UI, not the registry');
  }
  assert.equal(new Set(G.sections.map((s) => s.id)).size, 13);
  for (const g of G.GROUPS) assert.ok(G.inGroup(g.id).length >= 1);
});

test('status and source over a full payload and over nothing', () => {
  const p = H.payload();
  for (const s of G.sections) {
    const live = ['console', 'events'].includes(s.id) ? { lines: H.lines('part_full.log') } : undefined;
    if (s.id === 'model_check') { assert.equal(s.status(p, live), 'absent'); continue; }
    assert.equal(s.status(p, live), 'present', s.id);
    assert.notEqual(s.source(p, live), undefined);
  }
  for (const s of G.sections) assert.equal(s.status(null), 'absent', s.id);
  for (const s of G.sections) assert.equal(s.status({ has_any: false, categories: {} }), 'absent', s.id);
});

test('flags: empty text depends on whether a review exists', () => {
  assert.equal(G.emptyText('flags', { categories: { review: { present: true, items: [], text: 'none' } } }), 'No assumptions or manual steps were recorded.');
  assert.equal(G.emptyText('flags', { categories: { review: { present: false, items: [], text: null } } }), 'No engineering review yet.');
  assert.equal(G.emptyText('flags', null), 'No engineering review yet.');
  assert.equal(G.get('flags').status({ categories: { review: { present: true, items: [], text: 'none' } } }), 'absent');
  assert.equal(G.emptyText('extraction'), 'No extraction yet.');
  assert.equal(G.emptyText('nope'), '');
});

test('console prefers live lines; events parse them', () => {
  const p = H.payload();
  const live = { lines: ['[STAGE] Done', 'x'] };
  assert.equal(G.get('console').source(p, live).source, 'live');
  assert.equal(G.get('console').source(p).source, 'file');
  assert.equal(G.get('console').source({ categories: {} }).source, 'none');
  const big = { categories: { console: { present: true, name: 'ui_console.log', text: null } } };
  assert.equal(G.get('console').source(big).tooLarge, true);
  assert.equal(G.get('events').source(p, live).events.length, 1);
  assert.equal(G.get('events').status(null, { lines: [] }), 'absent');
  assert.equal(G.get('events').source(null, { lines: ['[STAGE] Done'], exit: 0 }).events.length, 2);
});

test('resolveFile finds nested paths by basename', () => {
  const p = H.payload();
  assert.equal(G.resolveFile(p, '117C_extraction.json').name, '117C/117C_extraction.json');   // shortest of the two matches
  assert.equal(G.resolveFile(p, '117C/117C_build_plan.json').name, '117C/117C_build_plan.json');
  assert.equal(G.resolveFile(p, 'missing.json'), null);
  assert.equal(G.resolveFile(null, 'x'), null);
  assert.equal(G.resolveFile(p, ''), null);
  assert.equal(G.resolveFile({ categories: { files: { list: [{ name: 'a\\b\\c.txt', size: 1 }] } } }, 'c.txt').name, 'a\\b\\c.txt');
  assert.equal(G.downloadRel(p, 'extraction'), '117C/117C_extraction.json');
  assert.equal(G.downloadRel(p, 'verification'), null);       // report file is not in the list
  assert.equal(G.downloadRel(p, 'macros'), null);
  assert.deepEqual(G.filesWithExt(p, '.vba').map((f) => f.name), ['117C/macros/01_base.vba']);
  assert.deepEqual(G.filesWithExt(p, '.SLDPRT').map((f) => f.name), ['117C/117C.SLDPRT']);
});

test('isTooLarge is true only for a present category with null text', () => {
  assert.equal(G.isTooLarge({ present: true, text: null }), true);
  assert.equal(G.isTooLarge({ present: true, text: '' }), false);
  assert.equal(G.isTooLarge({ present: false }), false);
  assert.equal(G.isTooLarge(undefined), false);
});

test('files section source carries delivered folders', () => {
  const p = H.payload();
  const s = G.get('files').source(p);
  assert.equal(s.delivered, '/srv/UI_Output/117C'); assert.equal(s.macroCount, 2); assert.equal(s.sldprt, true);
});
