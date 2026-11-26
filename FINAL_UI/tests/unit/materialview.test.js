'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { logic } = require('./_helpers');
const M = logic('materialview.js');

const part = (status, extra) => Object.assign({ evaluated: true, resolution: { status, label: 'Lbl', chosen: { label: 'Generic carbon steel' }, selection_source: 'drawing' } }, extra || {});

test('every status has a label, an icon and a tone (never colour alone)', () => {
  for (const s of Object.keys(M.STATUS)) {
    const i = M.statusInfo(part(s));
    assert.ok(i.label && i.icon && i.tone, s);
  }
  assert.equal(M.statusInfo(part('not_specified')).label, 'No material specified on drawing');
  assert.equal(M.statusInfo(part('assigned_verified')).tone, 'green');
  assert.equal(M.statusInfo(part('assignment_failed')).tone, 'red');
  assert.equal(M.statusInfo(part('mystery')).label, 'Status unknown');
});

test('not evaluated is its own state', () => {
  for (const m of [null, {}, { evaluated: false }, { evaluated: true, resolution: null }]) {
    const i = M.statusInfo(m);
    assert.equal(i.id, 'not_evaluated'); assert.equal(i.label, 'Not evaluated yet'); assert.equal(M.titleOf(m), 'Not evaluated yet');
  }
  assert.equal(M.sectionTone({ evaluated: false }).tone, 'none');
});

test('a manual override is always labelled as differing from the drawing', () => {
  const m = part('override_pending', { resolution: { status: 'override_pending', selection_source: 'manual_override', chosen: { label: 'Copper' } } });
  assert.match(M.statusInfo(m).label, /Manual override/); assert.match(M.statusInfo(m).label, /differs from the drawing/);
  const v = part('assigned_verified', { resolution: { status: 'assigned_verified', selection_source: 'manual_override', chosen: { label: 'Copper' } } });
  assert.match(M.statusInfo(v).label, /Manual override/); assert.equal(M.statusInfo(v).tone, 'amber');
});

test('saved-extraction results are labelled as such', () => {
  assert.equal(M.statusInfo(part('matched', { from_saved_extraction: true })).label, 'Matched from saved extraction');
});

test('cost: unknown is never zero, illustrative prices carry the label', () => {
  assert.equal(M.costInfo(null).text, 'estimate unavailable');
  assert.equal(M.costInfo({ available: false, reason: 'No material is verified' }).reason, 'No material is verified');
  assert.equal(M.costInfo({ available: true, net_material_cost: null }).available, false);
  const c = M.costInfo({ available: true, net_material_cost: 1.5, currency: 'USD', display: { net_material_cost: '1.50 USD' }, label: 'Illustrative material estimate — not a supplier quote' });
  assert.equal(c.text, '1.50 USD'); assert.equal(c.illustrative, true); assert.equal(c.label, M.ILLUSTRATIVE);
  assert.ok(!/^0(\.0+)? /.test(M.costInfo({ available: false }).text));
  assert.equal(M.costInfo({ available: true, net_material_cost: 0, currency: 'USD' }).available, true);
});

test('price and density never invent values', () => {
  assert.equal(M.price(null, 'USD'), 'price not set'); assert.equal(M.price(undefined), 'price not set');
  assert.equal(M.price(4, 'USD', 'quote_2026'), '4.00 USD/kg (quote 2026)');
  assert.equal(M.density(7850), '7,850 kg/m³'); assert.equal(M.density(null), 'density not stated');
});

test('batch text: unpriced parts are named, currencies are not summed, nothing priced is not a total', () => {
  const t = (o) => M.batchText(o);
  assert.equal(t({ total_parts: 3, priced_parts: 1, unpriced_parts: 2, totals: { USD: { value: 2, display: '2.00 USD' } } }),
    'Material cost: 2.00 USD for 1 priced part; estimate unavailable for 2 (not counted as zero).');
  assert.match(t({ total_parts: 2, priced_parts: 2, unpriced_parts: 0, totals: { USD: { value: 3, display: '3.00 USD' }, EUR: { value: 1, display: '1.00 EUR' } } }), /3\.00 USD \+ 1\.00 EUR for 2 priced parts\.$/);
  assert.equal(t({ total_parts: 2, priced_parts: 0, unpriced_parts: 2, totals: {} }), 'Material cost: estimate unavailable for 2 of 2 parts.');
  assert.equal(t(null), ''); assert.equal(t({ total_parts: 0, priced_parts: 0, unpriced_parts: 0, totals: {} }), '');
});

test('compact record for tables', () => {
  assert.equal(M.compactInfo({ evaluated: false }).costText, 'estimate unavailable');
  const c = M.compactInfo({ evaluated: true, status: 'assigned_verified', material_label: 'Steel', cost: { available: true, display: '1.50 USD', label: 'Illustrative material estimate — not a supplier quote' } });
  assert.equal(c.title, 'Steel'); assert.equal(c.costText, '1.50 USD'); assert.equal(c.illustrative, true); assert.equal(c.icon, 'check');
  assert.equal(M.compactInfo({ evaluated: true, status: 'unmatched', cost: { available: false } }).costText, 'estimate unavailable');
});

test('library and run-catalog lines', () => {
  assert.equal(M.libraryLine({ active: false }), 'No company library. Using the demo catalog.');
  assert.equal(M.libraryLine({ active: true, name: 'Acme', entries: 12, rejected: 1 }), 'Acme · 12 materials · 1 rejected');
  assert.equal(M.libraryLine({ active: true, name: 'A', entries: 1, rejected: 0 }), 'A · 1 material');
  assert.match(M.libraryLine({ active: false, error: 'boom' }), /not usable: boom/);
  assert.match(M.runCatalogLine({ library: { active: false } }), /demo catalog/);
  assert.equal(M.runCatalogLine({ library: { active: true, name: 'Acme', entries: 4 } }), 'Material library: Acme (4 materials)');
  assert.equal(M.nativeWord({ native: true }), 'Yes'); assert.equal(M.nativeWord({ native: false }, 'demo'), 'At build'); assert.equal(M.nativeWord({}, 'company'), 'No');
});

test('viewer appearance: applied only when the server says it matches and is verified', () => {
  const ok = { viewer_apply: true, color: '#A5ABB4', metalness: 0.8, roughness: 0.35, material_label: 'Steel' };
  const d = M.appearanceDecision(ok);
  assert.equal(d.apply, true); assert.equal(d.caption, 'Illustrative appearance, not a finish specification');
  const no = Object.assign({}, ok, { viewer_apply: false, stl_matches: false });
  assert.equal(M.appearanceDecision(no).apply, false);
  assert.match(M.appearanceDecision(no).caption, /different model/);
  assert.equal(M.appearanceDecision(Object.assign({}, ok, { viewer_apply: false, stl_matches: true, verified: false })).label, 'Preview: material not verified');
  assert.equal(M.appearanceDecision(null).apply, false);
  assert.equal(M.appearanceDecision(Object.assign({}, ok, { color: 'url(javascript:1)' })).apply, false);
  assert.equal(M.appearanceDecision(Object.assign({}, ok, { metalness: 5 })).metalness, 1);
});

test('section tone: stale verified is amber, not green', () => {
  assert.deepEqual(M.sectionTone(part('assigned_verified')), { tone: 'green', word: 'verified' });
  assert.deepEqual(M.sectionTone(part('assigned_verified', { stale: true })), { tone: 'amber', word: 'out of date' });
  assert.equal(M.sectionTone(part('ambiguous')).tone, 'orange');
});

test('override form rules and who/when line', () => {
  assert.equal(M.overrideBlock('', 'x'), 'Choose a catalog material.');
  assert.equal(M.overrideBlock('demo-steel', '   '), 'Enter a reason for the override.');
  assert.equal(M.overrideBlock('demo-steel', 'x'.repeat(501)), 'The reason is limited to 500 characters.');
  assert.equal(M.overrideBlock('demo-steel', 'ok'), '');
  assert.equal(M.overrideLine({ user: 'Joe', at: '2026-11-25T10:00:00+00:00' }), 'Set by Joe on 2026-11-25 10:00:00 UTC');
  assert.equal(M.overrideLine(null), '');
});
