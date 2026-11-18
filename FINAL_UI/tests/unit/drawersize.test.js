'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const D = H.logic('drawersize.js');

test('maximum is the real space left under the header and tracker, not a fraction of the viewport', () => {
  // 1440x900: 868px of page, 66px header, 68px tracker, 12px gaps x3
  assert.equal(D.maxHeight({ pageH: 868, headH: 66, trackerH: 68, gap: 12 }), 868 - 66 - 68 - 36);
  // the old cap was 70% of the window: the new maximum must beat it at every supported size
  for (const [w, h] of [[1920, 1080], [1440, 900], [1366, 768]]) {
    const pageH = h - 17, m = D.maxHeight({ pageH, headH: 66, trackerH: 68, gap: 12 });
    assert.ok(m > Math.round(h * 0.7), `${w}x${h}: ${m} should exceed ${Math.round(h * 0.7)}`);
  }
});

test('flow layout (narrow): the drawer may fill the visible scroll area', () => {
  assert.equal(D.maxHeight({ flow: true, viewportH: 640 }), 640 - 16);
});

test('maximum never drops below the minimum', () => {
  assert.equal(D.maxHeight({ pageH: 200, headH: 66, trackerH: 68, gap: 12 }), D.MIN);
  assert.equal(D.maxHeight({ flow: true, viewportH: 100 }), D.MIN);
});

test('resolve: remembered is clamped, fit follows content up to the maximum, max is the maximum', () => {
  const base = { min: 160, max: 700 };
  assert.equal(D.resolve(Object.assign({ size: 'remembered', remembered: 320 }, base)), 320);
  assert.equal(D.resolve(Object.assign({ size: 'remembered', remembered: 9999 }, base)), 700);   // re-clamped after a smaller viewport
  assert.equal(D.resolve(Object.assign({ size: 'remembered', remembered: 20 }, base)), 160);
  assert.equal(D.resolve(Object.assign({ size: 'fit', fit: 420 }, base)), 420);
  assert.equal(D.resolve(Object.assign({ size: 'fit', fit: 5000 }, base)), 700);
  assert.equal(D.resolve(Object.assign({ size: 'fit', fit: 50 }, base)), 160);
  assert.equal(D.resolve(Object.assign({ size: 'max' }, base)), 700);
  assert.equal(D.resolve(Object.assign({ size: 'bogus', remembered: 320 }, base)), 320);       // invalid state falls back
});

test('remembered height is stored per viewport class and only valid values are used', () => {
  assert.equal(D.viewportClass(1920), 'wide');
  assert.equal(D.viewportClass(1440), 'wide');
  assert.equal(D.viewportClass(1366), 'medium');
  assert.equal(D.viewportClass(1099), 'narrow');
  assert.equal(D.rememberedFor({ wide: 500 }, 'wide', 320), 500);
  assert.equal(D.rememberedFor({ wide: 500 }, 'narrow', 320), 320);       // other class: default
  assert.equal(D.rememberedFor({ wide: 'x' }, 'wide', 320), 320);          // junk ignored
  assert.equal(D.rememberedFor({ wide: -5 }, 'wide', 320), 320);
  assert.equal(D.rememberedFor(null, 'wide', 320), 320);
});

test('nextSize cycles sensibly and Enter on the handle toggles maximum', () => {
  assert.equal(D.toggleMax('remembered'), 'max');
  assert.equal(D.toggleMax('fit'), 'max');
  assert.equal(D.toggleMax('max'), 'remembered');
});
