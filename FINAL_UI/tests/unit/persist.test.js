'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('./_helpers').core('persist.js');

function mem(initial) {
  const m = new Map(Object.entries(initial || {}));
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => { m.set(k, String(v)); }, removeItem: (k) => { m.delete(k); },
           key: (i) => Array.from(m.keys())[i] ?? null, get length() { return m.size; }, _m: m };
}
test.beforeEach(() => P.useStorage(mem()));
test.after(() => P.useStorage(null));

test('round trip and fallbacks', () => {
  assert.equal(P.get(P.KEYS.session, 'x'), 'x');
  assert.equal(P.set(P.KEYS.session, 'abc123'), true);
  assert.equal(P.get(P.KEYS.session, 'x'), 'abc123');
  P.remove(P.KEYS.session);
  assert.equal(P.get(P.KEYS.session, 'x'), 'x');
});

test('invalid JSON and schema violations fall back', () => {
  P.useStorage(mem({ 'mca.session': '{broken', 'mca.ui.split': '5', 'mca.ui.sidebar': '"sideways"',
    'mca.activeRun': '{"id":"r"}', 'mca.selected': '"nope"', 'mca.ui.drawer': '{"open":true,"height":10,"section":"a"}' }));
  assert.equal(P.get('mca.session', 'fb'), 'fb');
  assert.equal(P.get('mca.ui.split', 0.5), 0.5);
  assert.equal(P.get('mca.ui.sidebar', 'expanded'), 'expanded');
  assert.equal(P.get('mca.activeRun', null), null);
  assert.equal(P.get('mca.selected', null), null);
  assert.equal(P.get('mca.ui.drawer', null), null);
});

test('valid structured values pass their schema', () => {
  const run = { id: 'r1', kind: 'part', session: 's', part: 'A', startedAt: 123 };
  P.set(P.KEYS.activeRun, run); assert.deepEqual(P.get(P.KEYS.activeRun, null), run);
  const demo = { id: 'r2', kind: 'demo', startedAt: 5 };
  P.set(P.KEYS.activeRun, demo); assert.deepEqual(P.get(P.KEYS.activeRun, null), demo);
  P.set(P.KEYS.selected, { session: 's', part: 'A' }); assert.deepEqual(P.get(P.KEYS.selected, null), { session: 's', part: 'A' });
  P.set(P.KEYS.batch, { queue: ['A'], index: 0, results: {} }); assert.equal(P.get(P.KEYS.batch, null).queue[0], 'A');
});

test('ui defaults, save and load, reset clears only mca.ui.* keys', () => {
  const d = P.loadUi();
  assert.deepEqual(d, P.uiDefaults());
  const ui = Object.assign(P.uiDefaults(), { sidebarCollapsed: true, splitRatio: 0.35, drawerOpen: true, drawerHeight: 410, drawerSection: 'flags',
    inspectorCollapsed: true, inspectorOpen: { setup: false, actions: true, export: false }, resultsSection: 'cost' });
  P.saveUi(ui);
  P.set(P.KEYS.session, 'keepme');
  const back = P.loadUi();
  assert.deepEqual(back, Object.assign({}, ui, { drawerOpen: false }), 'drawer open flag is never restored (v6)');
  P.resetUi();
  assert.deepEqual(P.loadUi(), P.uiDefaults());
  assert.equal(P.get(P.KEYS.session, null), 'keepme');
});

test('correction drafts are per part and an empty draft removes the key', () => {
  P.corr.set('s1', 'A', 'move hole 2');
  assert.equal(P.corr.get('s1', 'A'), 'move hole 2');
  assert.equal(P.corr.get('s1', 'B'), '');
  P.corr.set('s1', 'A', '');
  assert.equal(P.corr.get('s1', 'A'), '');
  P.corr.set('s1', 'A', 'x'); P.corr.clear('s1', 'A'); assert.equal(P.corr.get('s1', 'A'), '');
});

test('storage failures never throw', () => {
  P.useStorage({ getItem() { throw new Error('denied'); }, setItem() { throw new Error('quota'); }, removeItem() { throw new Error('x'); } });
  assert.equal(P.get('mca.session', 'fb'), 'fb');
  assert.equal(P.set('mca.session', 'a'), false);
  assert.doesNotThrow(() => P.remove('mca.session'));
  assert.doesNotThrow(() => P.resetUi());
  P.useStorage(null);
  assert.equal(P.set('mca.session', 'a'), false);
  assert.equal(P.get('mca.session', 'fb'), 'fb');
});

test('drawer size state round-trips; invalid size or heights fall back to the defaults', () => {
  const ui = Object.assign(P.uiDefaults(), { drawerOpen: true, drawerSize: 'max', drawerHeights: { wide: 480, narrow: 300 } });
  P.saveUi(ui);
  const back = P.loadUi();
  assert.equal(back.drawerSize, 'max');
  assert.deepEqual(back.drawerHeights, { wide: 480, narrow: 300 });
  // junk in storage never reaches the UI
  P.set('mca.ui.drawer', { open: true, height: 320, section: 'a', size: 'huge', heights: { wide: 'x', bogus: 400, medium: 10, narrow: 250 } });
  const bad = P.loadUi();
  assert.equal(bad.drawerSize, 'remembered');
  assert.deepEqual(bad.drawerHeights, { narrow: 250 });
  P.resetUi();
});
