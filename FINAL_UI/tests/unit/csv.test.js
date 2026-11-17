'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const C = H.logic('csv.js');

test('quoted fields with commas, doubled quotes and newlines', () => {
  const rows = C.parseRows('a,b,c\n"x, y","say ""hi""","line1\nline2"\n');
  assert.deepEqual(rows, [['a', 'b', 'c'], ['x, y', 'say "hi"', 'line1\nline2']]);
});
test('CRLF, missing final newline, BOM, blank lines', () => {
  assert.deepEqual(C.parseRows('a,b\r\n1,2'), [['a', 'b'], ['1', '2']]);
  assert.deepEqual(C.parseRows('﻿a,b\n1,2\n\n3,4\n'), [['a', 'b'], ['1', '2'], ['3', '4']]);
  assert.deepEqual(C.parseRows('a,b\n1,\n'), [['a', 'b'], ['1', '']]);
});
test('header mapping on the real summary format', () => {
  const rows = C.parse(H.text('summary_notready.csv'));
  assert.equal(rows.length, 1);
  assert.equal(rows[0].status, 'NOT READY');
  assert.equal(rows[0].n_needs_review, '2');
  assert.equal(rows[0].detail, 'overview check: 1 CRITICAL gap, "hole pitch" unmet');
  assert.equal(C.parse(H.text('summary_ready.csv'))[0].detail, '');
  assert.deepEqual(Object.keys(C.parse(H.text('summary_ready.csv'))[0]),
    ['source', 'part', 'status', 'macro_readiness', 'geometry_completeness', 'dimension_completeness', 'consistency',
     'feature_confidence', 'n_macros', 'n_needs_review', 'n_skipped', 'detail']);
});
test('empty file and header-only file', () => {
  assert.deepEqual(C.parse(''), []);
  assert.deepEqual(C.parse(null), []);
  assert.deepEqual(C.parseRows(''), []);
  assert.deepEqual(C.parse('a,b\n'), []);
});
test('short rows are padded with empty strings', () => {
  assert.deepEqual(C.parse('a,b,c\n1\n'), [{ a: '1', b: '', c: '' }]);
});
test('summaryRow picks the part row or the only row', () => {
  const two = 'source,part,status\nA,A,READY\nB,B,BLOCKED\n';
  assert.equal(C.summaryRow(two, 'B').status, 'BLOCKED');
  assert.equal(C.summaryRow(two, 'zzz'), null);
  assert.equal(C.summaryRow('source,part,status\nA,A,READY\n', 'other').status, 'READY');
  assert.equal(C.summaryRow('', 'A'), null);
});
