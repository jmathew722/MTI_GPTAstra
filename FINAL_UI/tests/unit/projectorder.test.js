'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { logic } = require('./_helpers');
const P = logic('projectorder.js');

test('newest activity first, numerically, never alphabetical', () => {
  const l = [{ name: 'Alpha', last_activity: 100 }, { name: 'Zeta', last_activity: 300 }, { name: 'Mid', last_activity: 200 }];
  assert.deepEqual(P.sortParts(l).map((p) => p.name), ['Zeta', 'Mid', 'Alpha']);
  assert.deepEqual(l.map((p) => p.name), ['Alpha', 'Zeta', 'Mid'], 'the input is not mutated');
});

test('numeric not lexical: 9 sorts below 10', () => {
  assert.deepEqual(P.sortParts([{ name: 'a', last_activity: 9 }, { name: 'b', last_activity: 10 }]).map((p) => p.name), ['b', 'a']);
});

test('ties break on the name, stably; unknown dates go last (also tie-broken)', () => {
  const l = [{ name: 'b', last_activity: 5 }, { name: 'a', last_activity: 5 }, { name: 'z', last_activity: null }, { name: 'y' }, { name: 'c', last_activity: 7 }];
  assert.deepEqual(P.sortParts(l).map((p) => p.name), ['c', 'a', 'b', 'y', 'z']);
});

test('a rerun (newer last_activity) moves a project to the top immediately', () => {
  const before = [{ name: 'New', last_activity: 500 }, { name: 'Old', last_activity: 100 }];
  assert.equal(P.sortParts(before)[0].name, 'New');
  const after = [{ name: 'New', last_activity: 500 }, { name: 'Old', last_activity: 900 }];
  assert.equal(P.sortParts(after)[0].name, 'Old');
});

test('timestamps: local display with date and time, unknown is labelled not invented', () => {
  assert.equal(P.fmtWhen(null), 'Date unknown');
  assert.equal(P.fmtWhen(undefined), 'Date unknown');
  assert.equal(P.fmtWhen(NaN), 'Date unknown');
  assert.equal(P.fmtWhen(1763568120, 'en-US', 'UTC'), 'Nov 19, 2025, 4:02 PM');
  assert.match(P.fmtWhen(1763568120, 'en-US', 'America/New_York'), /11:02 AM/);
  assert.equal(P.isoOf(1763568120), '2025-11-19T16:02:00.000Z');
  assert.equal(P.isoOf(null), '');
});

test('whenLine keeps creation time separate from last activity', () => {
  const same = P.whenLine({ last_activity: 1763568120, created_at: 1763568120 }, 'en-US', 'UTC');
  assert.equal(same.secondary, '');
  const rerun = P.whenLine({ last_activity: 1763568120 + 86400, created_at: 1763568120 }, 'en-US', 'UTC');
  assert.match(rerun.secondary, /^Created Nov 19, 2025/);
  assert.equal(P.whenLine({}, 'en-US').primary, 'Date unknown');
});
