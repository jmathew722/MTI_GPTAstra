'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const MV = H.logic('markupview.js');

const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} vs ${b}`);

const PAGES = [
  { page: 1, width_pt: 890, height_pt: 400, finding_ids: ['EF-001'], has_preview: true },
  { page: 2, width_pt: 890, height_pt: 400, finding_ids: ['EF-002', 'EF-003'], has_preview: true },
];
const FINDINGS = [
  { id: 'EF-001', number: 1, finding_id: 'flag_a', severity: 'ERROR', title: 'Hole not built', location_status: 'located', page: 1,
    regions: [{ page: 1, rect_marked_pt: [89, 40, 178, 80] }], card: { page: 1, rect: [608, 8, 882, 120] } },
  { id: 'EF-002', number: 2, finding_id: 'flag_b', severity: 'WARNING', title: 'Counterbore depth', location_status: 'located', page: 2,
    regions: [{ page: 2, rect_marked_pt: [300, 200, 400, 230] }], card: { page: 2, rect: [608, 8, 882, 100] } },
  { id: 'EF-003', number: 3, finding_id: 'flag_c', severity: 'ERROR', title: 'Thread depth not specified', location_status: 'unlocated', page: 2,
    regions: [], card: { page: 2, rect: [608, 110, 882, 200] } },
];
const cat = (over = {}) => ({ present: true, status: 'partial', generation_key: 'k1', finding_count: 3, located_count: 2, unlocated_count: 1,
  has_pdf: true, pages: PAGES, findings: FINDINGS, warnings: [], report_pages: 1, ...over });

test('model: ready/partial with pages is usable; none/not_needed/zero findings show nothing', () => {
  assert.equal(MV.model(cat()).state, 'partial');
  assert.equal(MV.model(cat({ status: 'ready' })).state, 'ready');
  assert.equal(MV.model(null).state, 'none');
  assert.equal(MV.model({ present: false, status: 'none' }).state, 'none');
  assert.equal(MV.model(cat({ status: 'not_needed', finding_count: 0, pages: [] })).state, 'none');
  assert.equal(MV.model(cat({ pages: [] })).state, 'none');
  assert.ok(MV.usable(MV.model(cat())) && !MV.usable(MV.model(null)));
});

test('model: a failed generation with flags is still shown (never a clean state); stale is withheld', () => {
  const failed = MV.model({ present: true, status: 'failed', finding_count: 2, failure: { code: 'MARKUP_GENERATION_FAILED', detail: 'x' } });
  assert.equal(failed.state, 'failed');
  assert.ok(MV.exists(failed) && !MV.usable(failed));
  assert.match(MV.banner(failed), /Engineering flags exist, but the marked PDF could not be generated \(MARKUP_GENERATION_FAILED\)/);
  assert.equal(MV.model({ present: true, status: 'failed', finding_count: 0 }).state, 'none');
  const stale = MV.model({ present: true, status: 'stale', finding_count: 2, generation_key: 'k' });
  assert.equal(stale.state, 'stale');
  assert.match(MV.banner(stale), /different revision/);
});

test('autoSelect: once per generated artifact, and never over an explicit choice of Overview', () => {
  const m = MV.model(cat());
  assert.equal(MV.autoSelect(m, undefined, false), true);
  assert.equal(MV.autoSelect(m, 'k1', false), false);          // already auto-selected for this artifact
  assert.equal(MV.autoSelect(m, undefined, true), false);      // the user went back to Overview
  assert.equal(MV.autoSelect(MV.model(cat({ generation_key: 'k2' })), 'k1', false), true);   // a new run's artifact
  assert.equal(MV.autoSelect(MV.model(null), undefined, false), false);
  assert.equal(MV.autoSelect(MV.model({ present: true, status: 'failed', finding_count: 1 }), undefined, false), false);
});

test('page of a flag: its region page, else its card page; the first page is the first located flag', () => {
  const m = MV.model(cat());
  assert.equal(MV.pageOf(m, 'flag_a'), 1);
  assert.equal(MV.pageOf(m, 'flag_b'), 2);
  assert.equal(MV.pageOf(m, 'EF-003'), 2);                     // unlocated: its card's page
  assert.equal(MV.pageOf(m, 'nope'), null);
  assert.equal(MV.firstPage(m), 1);
  const onlyP2 = MV.model(cat({ findings: FINDINGS.slice(1) }));
  assert.equal(MV.firstPage(onlyP2), 2);
});

test('hitBoxes: fractions of the marked page, regions and cards only on their own page', () => {
  const m = MV.model(cat());
  const p1 = MV.hitBoxes(m, 1);
  assert.deepEqual(p1.map((b) => [b.id, b.kind]), [['EF-001', 'region'], ['EF-001', 'card']]);
  near(p1[0].frac.x, 89 / 890); near(p1[0].frac.y, 40 / 400); near(p1[0].frac.w, 89 / 890); near(p1[0].frac.h, 40 / 400);
  const p2 = MV.hitBoxes(m, 2);
  assert.deepEqual(p2.map((b) => b.id + ':' + b.kind), ['EF-002:region', 'EF-002:card', 'EF-003:card']);   // the unlocated flag has NO region
  assert.deepEqual(MV.hitBoxes(m, 9), []);
});

test('focusTarget: a located flag zooms to its box; an unlocated one opens the page without a fake zoom', () => {
  const m = MV.model(cat());
  const a = MV.focusTarget(m, 'flag_b');
  assert.equal(a.page, 2); assert.equal(a.zoom, true); near(a.frac.x, 300 / 890);
  const u = MV.focusTarget(m, 'flag_c');
  assert.equal(u.page, 2); assert.equal(u.zoom, false); assert.equal(u.status, 'unlocated');
  assert.equal(MV.focusTarget(m, 'missing'), null);
});

test('fracPx maps a fraction into the fitted image box; label text starts with the visible id and severity', () => {
  const px = MV.fracPx({ x: 0.1, y: 0.2, w: 0.3, h: 0.4 }, { x: 50, y: 10, w: 1000, h: 500 });
  assert.deepEqual(px, { left: 150, top: 110, width: 300, height: 200 });
  const b = MV.hitBoxes(MV.model(cat()), 1)[0];
  assert.match(MV.label(b), /^EF-001 ERROR: Hole not built\./);
});

test('banner for a partial run names the unlocated count; a ready run says nothing', () => {
  assert.match(MV.banner(MV.model(cat())), /1 of 3 flags could not be placed precisely/);
  assert.equal(MV.banner(MV.model(cat({ status: 'ready', unlocated_count: 0 }))), '');
});

test('the category is a known payload key and the new URL builders exist', () => {
  const R = H.logic('registry.js');
  assert.ok(R.CATEGORY_KEYS.includes('engineering_markup'));
  assert.equal(R.coverage().unmapped.length, 0);
});
