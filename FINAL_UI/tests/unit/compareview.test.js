'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { logic } = require('./_helpers');
const K = logic('compareview.js');

const REP = (over) => Object.assign({ status: 'needs_review', status_label: 'Needs Review', reason: '2 annotations are missing', spec: { extraction_reuse: 'hit', completeness: 0.96, pages: 2 },
  scales: { sheet: { source: '1:2', generated: '1:2', title_block: '1:2', match: true }, views: [{ id: 'V1', source: '1:2', generated: '1:4', match: false }] },
  iterations: { used: 1, max: 3, best: 1, stop_reason: 'iteration_cap' },
  sheets: [{ page: 1, annotations: { source: 41, generated: 39, matched: 37, missing: 2, extra: 0, mismatched: 2 } }],
  issues: [{ id: 'R002', kind: 'extra_annotation', severity: 'low', page: 1, text: 'NOTE 9' }, { id: 'R001', kind: 'missing_annotation', severity: 'high', page: 1, text: 'R12', detail: 'not found' }, { id: 'R003', kind: 'scale_mismatch', severity: 'critical', page: 2, text: 'V1' }],
  images: { side_by_side: ['p/comparison/side_by_side-page-001.png'], overlay: ['p/comparison/overlay-page-001.png'], difference: ['p/comparison/diff-page-001.png'] } }, over || {});

test('status: replication vocabulary, v7 verification mapping, never Verified without the backend saying so', () => {
  assert.equal(K.statusInfo({ replication: REP({ status: 'verified', status_label: 'Verified' }) }).label, 'Verified');
  assert.equal(K.statusInfo({ replication: REP() }).label, 'Needs Review'); assert.equal(K.statusInfo({ replication: REP() }).reason, '2 annotations are missing');
  assert.equal(K.statusInfo({ replication: REP({ status: 'blocked' }) }).tone, 'red'); assert.equal(K.statusInfo({ replication: REP({ status: 'failed' }) }).label, 'Failed');
  const v7 = K.statusInfo({ verification: { status: 'passed' } });
  assert.equal(v7.verified, false); assert.match(v7.label, /^Draft/); assert.equal(v7.source, 'verification');
  assert.equal(K.statusInfo({ verification: { status: 'review_required' } }).label, 'Needs Review'); assert.equal(K.statusInfo({ verification: { status: 'Needs Review' } }).key, 'needs_review');
  assert.equal(K.statusInfo({ verification: { status: 'not_run' } }).key, 'none'); assert.equal(K.statusInfo({}).key, 'none'); assert.equal(K.statusInfo(null).source, 'none');
  assert.equal(K.statusInfo({ verification: { status: 'Verified' } }).verified, true);
});
test('issues: grouped, severity-sorted, normalised; v7 unresolved list still works', () => {
  const l = K.issues({ replication: REP() });
  assert.deepEqual(l.map(i => i.id), ['R003', 'R001', 'R002']); assert.deepEqual(l.map(i => i.group), ['mismatch', 'missing', 'extra']);
  assert.deepEqual(K.groupCounts(l), { all: 3, missing: 1, extra: 1, mismatch: 1, other: 0 });
  assert.equal(K.evidenceSide(l[2]), 'generated'); assert.equal(K.evidenceSide(l[1]), 'source');
  const u = K.issues({ verification: { coverage: { unresolved: [{ id: 'D7', kind: 'dimension', text: 'R12 not found', reason: 'no geometry', severity: 'high' }] } } });
  assert.equal(u[0].id, 'D7'); assert.equal(u[0].group, 'other'); assert.equal(u[0].detail, 'no geometry'); assert.deepEqual(K.issues({}), []);
});
test('evidence bbox: only page fractions are accepted', () => {
  assert.deepEqual(K.bboxOf({ evidence: { bbox: [0.1, 0.2, 0.3, 0.4] } }), { x0: 0.1, y0: 0.2, x1: 0.3, y1: 0.4 });
  assert.deepEqual(K.bboxOf({ bbox: { x: 0.5, y: 0.5, w: 0.1, h: 0.1 } }), { x0: 0.5, y0: 0.5, x1: 0.6, y1: 0.6 });
  assert.equal(K.bboxOf({ bbox: [10, 20, 300, 40] }), null); assert.equal(K.bboxOf({ bbox: [0.3, 0.3, 0.3, 0.3] }), null); assert.equal(K.bboxOf({}), null);
});
test('facts: scales, reuse, corrections, annotation counts, editable output', () => {
  const p = { replication: REP(), files: { slddrw: { url_path: 'x', bytes: 1, available: true } } };
  const sl = K.scaleLines(p);
  assert.equal(sl[0].text, 'Sheet 1:2 source / 1:2 generated (title block 1:2)'); assert.equal(sl[0].match, true); assert.equal(sl[1].text, 'View V1 1:2 source / 1:4 generated'); assert.equal(sl[1].match, false);
  assert.equal(K.reuseOf(p).key, 'hit'); assert.equal(K.correctionsOf(p).text, '1 of 3 correction pass (stopped: iteration cap)');
  assert.deepEqual(K.annotationCounts(p), { source: 41, generated: 39, matched: 37, missing: 2, extra: 0, mismatched: 2, any: true });
  assert.equal(K.editable(p).available, true); assert.equal(K.editable({ files: {} }).available, false); assert.equal(K.editable({ files: { slddrw: { available: false, url_path: 'x' } } }).available, false);
  assert.ok(K.factRows(p).some(r => r[0] === 'Editable output'));
  assert.equal(K.scaleLines({ replication: REP({ scales: { sheet: { source: null, generated: '1:2' } } }) })[0].text, 'Sheet not stated source / 1:2 generated');
  assert.equal(K.scaleLines({ verification: { comparison: { scales: { source: '1:2', generated: '1:2' } } } })[0].text, 'Sheet 1:2 source / 1:2 generated');
  assert.deepEqual(K.scaleLines({}), []); assert.equal(K.reuseOf({ reference: { extraction_cache: 'fresh' } }).key, 'fresh'); assert.equal(K.correctionsOf({}), null);
});
test('images: only files the server lists, classified by kind and page', () => {
  const files = { comparison_images: { available: true, files: [
    { name: 'comparison/side_by_side-page-001.png', url_path: 'p/comparison/side_by_side-page-001.png', bytes: 5 }, { name: 'comparison/overlay-page-001.png', url_path: 'p/comparison/overlay-page-001.png', bytes: 6 },
    { name: 'comparison/diff-page-002.png', url_path: 'p/comparison/diff-page-002.png', bytes: 7 }, { name: 'comparison/other.png', url_path: 'p/comparison/other.png', bytes: 1 } ] } };
  const im = K.images({ replication: { images: { overlay: ['comparison/overlay-page-001.png', 'comparison/ghost.png'] } }, files });
  assert.equal(im.overlay.length, 1); assert.equal(im.overlay[0].page, 1); assert.equal(im.difference[0].page, 2); assert.equal(im.side_by_side.length, 1);
  assert.equal(K.pickImage(im.overlay, 1).rel, 'p/comparison/overlay-page-001.png'); assert.equal(K.pickImage(im.overlay, 2), null); assert.equal(K.pickImage([{ page: null, rel: 'x' }], 3).rel, 'x');
  assert.deepEqual(K.images({}), { overlay: [], difference: [], side_by_side: [] });
});
test('sync: only when both loaded and page counts match; scroll fractions', () => {
  assert.equal(K.syncPlan(2, 2, true).effective, true); assert.equal(K.syncPlan(2, 2, false).effective, false); assert.equal(K.syncPlan(2, 2, false).possible, true);
  assert.match(K.syncPlan(2, 1, true).reason, /2 source vs 1 generated/); assert.equal(K.syncPlan(0, 1, true).possible, false);
  assert.equal(K.scrollFraction(50, 300, 100), 0.25); assert.equal(K.scrollFraction(5, 100, 100), 0); assert.equal(K.scrollFromFraction(0.5, 500, 100), 200); assert.equal(K.scrollFromFraction(1, 100, 100), 0);
});
test('difference pixels: source-only blue, generated-only red, both grey, blank white', () => {
  const W = [255, 255, 255, 255], B = [0, 0, 0, 255];
  const src = Uint8ClampedArray.from([].concat(B, B, W, W)), gen = Uint8ClampedArray.from([].concat(B, W, B, W));
  const r = K.diffPixels(src, gen);
  assert.deepEqual(r.stats, { onlySource: 1, onlyGenerated: 1, both: 1 });
  assert.deepEqual(Array.from(r.data.slice(0, 4)), [120, 120, 120, 255]); assert.deepEqual(Array.from(r.data.slice(4, 8)), [40, 110, 255, 255]); assert.deepEqual(Array.from(r.data.slice(8, 12)), [235, 60, 60, 255]); assert.deepEqual(Array.from(r.data.slice(12, 16)), [255, 255, 255, 255]);
  const o = K.overlayPixels(src, gen);
  assert.deepEqual(Array.from(o.data.slice(0, 4)), [0, 0, 0, 255]); assert.deepEqual(Array.from(o.data.slice(4, 8)), [0, 0, 255, 255]); assert.deepEqual(Array.from(o.data.slice(8, 12)), [255, 0, 0, 255]);
  assert.deepEqual(K.diffPixels(src, src).stats, { onlySource: 0, onlyGenerated: 0, both: 2 });
});
test('locateText: finds an item and returns page fractions; not found / no text layer is null', () => {
  const vp = { width: 200, height: 100, scale: 1, transform: [1, 0, 0, -1, 0, 100] };
  const items = [{ str: 'TITLE', transform: [10, 0, 0, 10, 10, 90], width: 40, height: 10 }, { str: 'R12 TYP', transform: [10, 0, 0, 10, 100, 50], width: 40, height: 10 }];
  const b = K.locateText(items, vp, 'r12');
  assert.ok(b && b.x0 === 0.5 && b.x1 === 0.7 && b.y0 > 0.3 && b.y1 < 0.6, JSON.stringify(b));
  assert.equal(K.locateText(items, vp, 'NOT THERE'), null); assert.equal(K.locateText([], vp, 'R12'), null); assert.equal(K.locateText(items, vp, ''), null);
});
