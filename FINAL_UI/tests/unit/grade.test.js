'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { logic } = require('./_helpers');
const G = logic('grade.js');

const EXACT = { poor: '#D95763', below: '#D98B55', fair: '#D6AF6B', good: '#B5C76B', excellent: '#8DD49A', perfect: '#4CB782' };

test('the six grades carry the exact HEX values, words and ranges', () => {
  assert.deepEqual(G.GRADES.map((g) => [g.id, g.label, g.min, g.max, g.color]), [
    ['poor', 'Poor', 0, 39, '#D95763'], ['below', 'Below Average', 40, 59, '#D98B55'], ['fair', 'Fair', 60, 79, '#D6AF6B'],
    ['good', 'Good', 80, 89, '#B5C76B'], ['excellent', 'Excellent', 90, 99, '#8DD49A'], ['perfect', 'Perfect', 100, 100, '#4CB782']]);
  assert.equal(new Set(G.GRADES.map((g) => g.glyph)).size, 6, 'a distinct glyph per grade: colour is never the only cue');
});

test('every threshold boundary: integers and the values just either side of it', () => {
  const at = (s) => G.gradeOf(s).id;
  const cases = [[0, 'poor'], [1, 'poor'], [38.99, 'poor'], [39, 'poor'], [39.5, 'poor'], [39.999, 'poor'],
    [40, 'below'], [41, 'below'], [58, 'below'], [59, 'below'], [59.999, 'below'],
    [60, 'fair'], [60.001, 'fair'], [79, 'fair'], [79.999, 'fair'],
    [80, 'good'], [80.001, 'good'], [89, 'good'], [89.999, 'good'],
    [90, 'excellent'], [90.001, 'excellent'], [99, 'excellent'], [99.9, 'excellent'], [99.999, 'excellent'], [99.99999, 'excellent'],
    [100, 'perfect']];
  cases.forEach(([s, id]) => assert.equal(at(s), id, `score ${s}`));
});

test('a score below 100 is never promoted to Perfect, and a fractional score keeps its own grade', () => {
  assert.equal(G.gradeOf(99.9999999).id, 'excellent');
  assert.notEqual(G.gradeOf(99.5).color, EXACT.perfect);
  assert.equal(G.gradeOf(39.9999).id, 'poor');
  assert.equal(G.gradeOf(59.9999).id, 'below');
  assert.equal(G.gradeOf(100).color, EXACT.perfect);
});

test('missing, unavailable and invalid scores are neutral grey, never red', () => {
  [null, undefined, NaN, Infinity, -Infinity, -0.01, -5, 100.01, 250, '90', {}, []].forEach((v) => {
    const g = G.gradeOf(v);
    assert.equal(g.id, 'none', String(v));
    assert.equal(g.color, '#92949E');
    assert.notEqual(g.color, EXACT.poor);
    assert.equal(g.label, 'Not scored');
  });
  assert.equal(G.classOf(null), 'grade-none');
  assert.equal(G.format(null), '–');
  assert.equal(G.formatFull(undefined), '–');
});

test('formatting never rounds a score up into a grade it did not earn', () => {
  assert.equal(G.format(99.96), '99.9');
  assert.equal(G.format(99.99), '99.9');
  assert.equal(G.format(100), '100.0');
  assert.equal(G.format(89.99), '89.9');
  assert.equal(G.format(39.99), '39.9');
  assert.equal(G.format(0), '0.0');
  assert.equal(G.format(83.14), '83.1');
  assert.equal(G.format(99.96, 0), '99');
  assert.equal(G.format(100, 0), '100');
  assert.equal(G.formatFull(93.45), '93.4 / 100');
  assert.equal(G.format(0.1 + 0.2, 1), '0.3', 'floating-point noise does not truncate a real 0.3');
});

test('credits (0..1) grade like percentages', () => {
  assert.equal(G.gradeOfCredit(1).id, 'perfect');
  assert.equal(G.gradeOfCredit(0.999).id, 'excellent');
  assert.equal(G.gradeOfCredit(0.8).id, 'good');
  assert.equal(G.gradeOfCredit(0.4).id, 'below');
  assert.equal(G.gradeOfCredit(0.39).id, 'poor');
  assert.equal(G.gradeOfCredit(null).id, 'none');
  assert.equal(G.gradeOfCredit(NaN).id, 'none');
});

test('classOf / colorOf / byId agree with gradeOf', () => {
  [0, 39, 40, 59, 60, 79, 80, 89, 90, 99, 100].forEach((s) => {
    assert.equal(G.classOf(s), 'grade-' + G.gradeOf(s).id);
    assert.equal(G.colorOf(s), G.gradeOf(s).color);
    assert.equal(G.byId(G.gradeOf(s).id), G.gradeOf(s));
  });
  assert.equal(G.byId('nope').id, 'none');
});

test('the spectrum is a smooth gradient through all six colours in order, 0 to 100', () => {
  const css = G.gradientCSS();
  assert.match(css, /^linear-gradient\(to right, /);
  const hexes = css.match(/#[0-9A-F]{6}/g);
  assert.deepEqual(hexes, G.GRADES.map((g) => g.color));
  assert.match(css, /#4CB782 100%/);
  assert.match(G.gradientCSS('to top'), /^linear-gradient\(to top/);
  assert.equal(G.spectrumPos(83.2), 83.2);
  assert.equal(G.spectrumPos(null), null);
});

test('distribution counts by grade, ignores invalid scores, percentages add up', () => {
  const d = G.distribution([100, 99.9, 95, 85, 70, 50, 10, null, NaN, 140]);
  assert.deepEqual(d.map((x) => [x.id, x.count]), [['poor', 1], ['below', 1], ['fair', 1], ['good', 1], ['excellent', 2], ['perfect', 1]]);
  assert.equal(Math.round(d.reduce((a, x) => a + x.pct, 0)), 100);
  assert.deepEqual(G.distribution([]).map((x) => x.count), [0, 0, 0, 0, 0, 0]);
  assert.deepEqual(G.distribution(null).map((x) => x.pct), [0, 0, 0, 0, 0, 0]);
  assert.equal(G.rangeText(G.byId('perfect')), '100');
  assert.equal(G.rangeText(G.byId('good')), '80–89');
});

test('every grade colour is readable on the dark theme (WCAG AA for text, 4.5:1)', () => {
  ['#101114', '#191B20'].forEach((bg) => G.GRADES.forEach((g) => assert.ok(G.contrast(g.color, bg) >= 4.5, `${g.id} on ${bg}: ${G.contrast(g.color, bg).toFixed(2)}`)));
  assert.ok(G.contrast(G.NONE.color, '#191B20') >= 3, 'the neutral grey is still legible');
});

test('the CSS tokens mirror the utility exactly (one source of truth)', () => {
  const css = fs.readFileSync(path.resolve(__dirname, '../../web/static/design-tokens.css'), 'utf8');
  Object.keys(EXACT).forEach((id) => {
    const m = new RegExp('--grade-' + id + ':\\s*(#[0-9A-Fa-f]{6})').exec(css);
    assert.ok(m, 'token --grade-' + id);
    assert.equal(m[1].toUpperCase(), EXACT[id]);
  });
  assert.match(css, /--grade-none:\s*#92949E/i);
});
