'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const J = H.logic('jsontree.js');

test('number lexemes are preserved exactly', () => {
  const n = J.parse('{"a": 1.50, "b": 1e-7, "c": 12345678901234567890, "d": -0.0, "e": 2E+3, "f": 0}');
  const raws = n.children.map((c) => c.raw);
  assert.deepEqual(raws, ['1.50', '1e-7', '12345678901234567890', '-0.0', '2E+3', '0']);
  assert.ok(n.children.every((c) => c.type === 'number'));
  // JSON.parse would lose these
  assert.notEqual(String(JSON.parse('12345678901234567890')), '12345678901234567890');
  assert.equal(J.toText(n).includes('1.50'), true);
});

test('nested structures, key order and duplicate keys are kept', () => {
  const n = J.parse('{"z": [1, {"k": null, "t": true, "f": false}, []], "a": {}, "z": "again"}');
  assert.equal(n.type, 'object');
  assert.deepEqual(n.children.map((c) => c.key), ['z', 'a', 'z']);
  const arr = n.children[0];
  assert.equal(arr.type, 'array'); assert.equal(arr.value, 3);
  assert.deepEqual(arr.children.map((c) => c.key), [0, 1, 2]);
  const obj = arr.children[1];
  assert.deepEqual(obj.children.map((c) => [c.key, c.type, c.value]), [['k', 'null', null], ['t', 'boolean', true], ['f', 'boolean', false]]);
  assert.equal(arr.children[2].type, 'array');
  assert.equal(J.summary(n), '{3}'); assert.equal(J.summary(arr), '[3]');
});

test('string escapes are decoded; raw keeps the source', () => {
  const n = J.parse('{"s": "a\\"b\\\\c\\n\\u00e9\\u0041\\/"}');
  assert.equal(n.children[0].value, 'a"b\\c\nÃ©A/'.replace('Ã©', 'é'));
  const p = J.parse('"line\\tbreak"');
  assert.equal(p.type, 'string'); assert.equal(p.value, 'line\tbreak'); assert.equal(p.raw, '"line\\tbreak"');
});

test('scalars at the root, whitespace, BOM and Python NaN / Infinity', () => {
  assert.equal(J.parse('  42 ').raw, '42');
  assert.equal(J.parse('﻿{"a":1}').type, 'object');
  const n = J.parse('{"a": NaN, "b": Infinity, "c": -Infinity}');
  assert.deepEqual(n.children.map((c) => c.raw), ['NaN', 'Infinity', '-Infinity']);
});

test('invalid JSON returns an error node carrying the raw text', () => {
  for (const bad of ['{"a": }', '{"a": 1,}', '[1 2]', '{"a": "x', '', 'nope', '{"a": 1} extra', '{"a": 01}', '"bad \\q"']) {
    const n = J.parse(bad);
    assert.equal(n.type, 'error', JSON.stringify(bad));
    assert.equal(n.raw, bad);
    assert.ok(n.message.length > 0);
    assert.ok(n.line >= 1 && n.column >= 1);
  }
  assert.equal(J.parse(null).type, 'error');
  const multi = J.parse('{\n  "a": 1,\n  "b": ?\n}');
  assert.equal(multi.line, 3);
});

test('deep nesting is rejected instead of overflowing the stack', () => {
  const deep = '['.repeat(2000) + ']'.repeat(2000);
  assert.equal(J.parse(deep).type, 'error');
  const ok = '['.repeat(100) + ']'.repeat(100);
  assert.equal(J.parse(ok).type, 'array');
});

test('toText round-trips lexemes and find searches keys and values', () => {
  const src = '{"thickness": 0.250, "holes": [{"d": 1e-3}], "name": "Plate"}';
  const n = J.parse(src);
  assert.deepEqual(JSON.parse(J.toText(n)), JSON.parse(src));
  assert.ok(J.toText(n).includes('0.250') && J.toText(n).includes('1e-3'));
  const r = J.find(n, 'hole');
  assert.equal(r.length, 1); assert.equal(r[0].where, 'key'); assert.deepEqual(r[0].path, ['holes']);
  const v = J.find(n, 'plate');
  assert.deepEqual([v.length, v[0].where], [1, 'value']);
  assert.deepEqual(J.find(n, ''), []);
});

test('the recorded extraction fixture parses with its lexemes intact', () => {
  const n = J.parse(H.payload().categories.extraction.text);
  const raws = Object.fromEntries(n.children.map((c) => [c.key, c.raw]));
  assert.equal(raws.thickness, '0.250'); assert.equal(raws.scale, '1e-7'); assert.equal(raws.big, '12345678901234567890');
});
