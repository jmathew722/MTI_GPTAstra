'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const V = H.logic('flagview.js');

const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} vs ${b}`);
const R = (x, y, width, height) => ({ x, y, width, height });

/* ---- coordinates --------------------------------------------------------------------------------- */
test('toDisplayed maps the unrotated normalized rect into the page as displayed, for every rotation', () => {
  const r = R(0.1, 0.2, 0.3, 0.1);                     // near the top-left of the unrotated page
  const cases = { 0: R(0.1, 0.2, 0.3, 0.1), 90: R(1 - 0.3, 0.1, 0.1, 0.3), 180: R(1 - 0.4, 1 - 0.3, 0.3, 0.1), 270: R(0.2, 1 - 0.4, 0.1, 0.3) };
  for (const rot of [0, 90, 180, 270]) {
    const d = V.toDisplayed(r, rot);
    for (const k of ['x', 'y', 'width', 'height']) near(d[k], cases[rot][k]);
  }
});

test('toDisplayed agrees with the pipeline: the unrotated top-left box lands at the top-right of a 90 degree page', () => {
  // pipeline/flag_overlays: a box at unrotated top-left, page rotated 90 clockwise, is drawn at the top-right
  const d = V.toDisplayed(R(0, 0, 0.1, 0.2), 90);
  assert.ok(d.x + d.width > 0.79 && d.y < 0.01);
});

test('toDisplayed rejects a rotation that is not a multiple of 90 and returns a copy', () => {
  assert.throws(() => V.toDisplayed(R(0, 0, 1, 1), 45));
  const r = R(0.1, 0.1, 0.2, 0.2), d = V.toDisplayed(r, 0);
  d.x = 9;
  assert.equal(r.x, 0.1);
});

test('fitContain reproduces object-fit: contain: letterbox bars appear on the short axis', () => {
  assert.deepEqual(V.fitContain(1000, 500, 600, 400), { x: 125, y: 0, w: 750, h: 500 });     // pillarbox
  const lb = V.fitContain(500, 1000, 600, 400);                                               // letterbox bars top and bottom
  near(lb.x, 0); near(lb.y, 1000 / 3, 1e-9); near(lb.w, 500); near(lb.h, 1000 / 3, 1e-9);
  assert.deepEqual(V.fitContain(600, 400, 600, 400), { x: 0, y: 0, w: 600, h: 400 });
  assert.deepEqual(V.fitContain(0, 0, 600, 400), { x: 0, y: 0, w: 0, h: 0 });
  assert.deepEqual(V.fitContain(600, 400, 0, 0), { x: 0, y: 0, w: 0, h: 0 });                // image not loaded yet
});

test('overlayPx places a flag in container pixels (rotation + letterbox together)', () => {
  const fit = V.fitContain(1000, 500, 600, 400);                       // {125,0,750,500}
  const p = V.overlayPx(R(0.5, 0.5, 0.1, 0.2), 0, fit);
  near(p.left, 125 + 0.5 * 750); near(p.top, 0.5 * 500); near(p.width, 75); near(p.height, 100);
  const q = V.overlayPx(R(0, 0, 0.1, 0.2), 90, V.fitContain(500, 1000, 400, 600));                // a portrait display
  near(q.left, 0.8 * 500); near(q.top, 0 + (1000 - 500 * 1.5) / 2); near(q.width, 0.2 * 500); near(q.height, 0.1 * 750);
});

test('focusTransform centers a flag in the viewport at a readable zoom and clamps the zoom', () => {
  const t = V.focusTransform({ left: 400, top: 300, width: 40, height: 20 }, { w: 1000, h: 600 }, { min: 0.2, max: 12 });
  near(t.s, 8.75);                                                                           // the flag fills ~35% of the viewport's tighter axis
  assert.ok(Number.isFinite(t.tx) && Number.isFinite(t.ty));
  const big = V.focusTransform({ left: 0, top: 0, width: 990, height: 590 }, { w: 1000, h: 600 }, { min: 0.2, max: 12 });
  assert.ok(big.s >= 0.2 && big.s <= 1.01);
  const tiny = V.focusTransform({ left: 10, top: 10, width: 0.5, height: 0.5 }, { w: 1000, h: 600 }, { min: 0.2, max: 12 });
  assert.equal(tiny.s, 12);
});

test('focusTransform puts the flag center at the viewport center', () => {
  // transform is translate(tx,ty) scale(s) about the container center (cx,cy): p' = c + (p - c) * s + t
  const view = { w: 1000, h: 600 };
  const rect = { left: 700, top: 100, width: 100, height: 50 };
  const t = V.focusTransform(rect, view, { min: 0.2, max: 12 });
  const cx = view.w / 2, cy = view.h / 2, px = rect.left + rect.width / 2, py = rect.top + rect.height / 2;
  near(cx + (px - cx) * t.s + t.tx, cx, 1e-6);
  near(cy + (py - cy) * t.s + t.ty, cy, 1e-6);
});

/* ---- model, filters, selection --------------------------------------------------------------------- */
const finding = (id, o) => Object.assign({ finding_id: id, severity: 'error', category: 'feature_not_built', title: 'T ' + id, feature_ids: ['F001'],
  source_callouts: ['X'], expected: 'e', actual: 'a', consequence: 'c', recommended_action: 'r' }, o || {});
const ov = (id, n, o) => Object.assign({ overlay_id: 'ov_' + id, finding_id: id, number: n, severity: 'error', page_index: 0, rect_normalized: R(0.1, 0.1, 0.1, 0.1),
  mapping_method: 'exact_tokens', mapping_confidence: 0.97, rotation_degrees: 0 }, o || {});
const model = () => ({
  present: true, hash_verified: true, stale: false,
  findings: [finding('a'), finding('b', { severity: 'warning', category: 'feature_unresolved', feature_ids: ['F002'] }), finding('c', { severity: 'info', category: 'practice_advisory', feature_ids: [] }), finding('d')],
  overlays: [ov('a', 1), ov('b', 2, { severity: 'warning', page_index: 1 })],
  unlocated: [{ finding_id: 'c', reason: 'no_source_callout' }, { finding_id: 'd', reason: 'ambiguous', candidates: 2, likely_page: 0 }],
  review: { b: { state: 'acknowledged' } }
});

test('flagList joins findings with their overlay or unlocated reason, ordered by severity then number', () => {
  const l = V.flagList(model());
  assert.deepEqual(l.map((f) => f.finding_id), ['a', 'd', 'b', 'c']);                      // errors, then warning, then info
  assert.equal(l[0].located, true); assert.equal(l[1].located, false); assert.equal(l[1].reason, 'ambiguous');
  assert.equal(l[2].state, 'acknowledged'); assert.equal(l[0].state, 'open');
});

test('filters: severity, category, feature, review state and located/unlocated', () => {
  const m = model();
  const ids = (f) => V.filterFlags(V.flagList(m), f).map((x) => x.finding_id);
  assert.deepEqual(ids({}), ['a', 'd', 'b', 'c']);
  assert.deepEqual(ids({ severity: ['error'] }), ['a', 'd']);
  assert.deepEqual(ids({ category: ['practice_advisory'] }), ['c']);
  assert.deepEqual(ids({ feature: 'F002' }), ['b']);
  assert.deepEqual(ids({ state: ['acknowledged'] }), ['b']);
  assert.deepEqual(ids({ location: 'unlocated' }), ['d', 'c']);
  assert.deepEqual(ids({ location: 'located' }), ['a', 'b']);
  assert.deepEqual(ids({ severity: ['error'], location: 'located' }), ['a']);
});

test('overlays are drawn only when the drawing is verified, current, and on the displayed page', () => {
  const m = model();
  assert.deepEqual(V.drawable(m, 0).map((o) => o.finding_id), ['a']);                      // b is on page 2
  assert.deepEqual(V.drawable(m, 1).map((o) => o.finding_id), ['b']);
  assert.deepEqual(V.drawable(Object.assign(model(), { stale: true }), 0), []);
  assert.deepEqual(V.drawable(Object.assign(model(), { hash_verified: false }), 0), []);
  assert.deepEqual(V.drawable(null, 0), []);
  const hidden = V.drawable(m, 0, { severity: ['warning'] });
  assert.deepEqual(hidden, []);                                                           // filters hide boxes too
});

test('selection: unknown ids clear, and keyboard traversal wraps through the visible flags', () => {
  const l = V.flagList(model());
  assert.equal(V.select(l, 'a'), 'a');
  assert.equal(V.select(l, 'nope'), null);
  assert.equal(V.neighbor(l, 'a', +1), 'd');
  assert.equal(V.neighbor(l, 'c', +1), 'a');                                              // wraps
  assert.equal(V.neighbor(l, 'a', -1), 'c');
  assert.equal(V.neighbor(l, null, +1), 'a');
  assert.equal(V.neighbor([], 'a', +1), null);
});

test('location text is honest about unlocated flags and shows page, method and confidence otherwise', () => {
  const l = V.flagList(model());
  assert.equal(V.locationText(l[0]), 'Page 1 · exact match · 97% confidence');
  assert.match(V.locationText(l[1]), /Not located on the drawing/);
  assert.match(V.locationText(l[1]), /2 equally good matches/);
  assert.match(V.locationText(l[1]), /likely page 1/);
  assert.match(V.locationText(l[3]), /no drawing callout/i);
  assert.equal(V.locationText(Object.assign({}, l[0], { provenance: 'developer_override', mapping_method: 'developer_override' })).includes('developer override'), true);
});

test('severity is conveyed by text and shape, not colour alone', () => {
  for (const s of ['error', 'warning', 'info']) {
    const m = V.severityMark(s);
    assert.ok(m.text.length > 3 && m.shape && m.label);
  }
  assert.notEqual(V.severityMark('error').shape, V.severityMark('warning').shape);
  assert.equal(V.severityMark('zzz').text, 'INFO');
});

test('banner text explains stale, unverifiable and truncated artifacts', () => {
  assert.equal(V.banner(model()), null);
  assert.match(V.banner(Object.assign(model(), { stale: true, reason: 'drawing_revision_changed' })), /different revision/i);
  assert.match(V.banner(Object.assign(model(), { stale: true, reason: 'older_run' })), /earlier run/i);
  assert.match(V.banner(Object.assign(model(), { hash_verified: false, reason: 'drawing_unavailable' })), /cannot be verified/i);
  assert.match(V.banner(Object.assign(model(), { truncated: true })), /first/i);
});
