'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { logic } = require('./_helpers');
const G = logic('batchgroup.js');

const E = (...paths) => paths.map((p) => ({ name: p.split('/').pop(), path: p }));

test('each subfolder is one part; views count images only', () => {
  const g = G.groupFolder(E('root/A/front.png', 'root/A/top.png', 'root/A/notes.txt', 'root/B/front.jpg'));
  assert.deepStrictEqual(g.map((p) => [p.name, p.views]), [['A', 2], ['B', 1]]);
  assert.strictEqual(g[0].items.length, 3);
});
test('loose files become one part each when subfolders exist', () => {
  const g = G.groupFolder(E('root/A/front.png', 'root/solo one.png', 'root/other.pdf', 'root/spec.txt'));
  assert.deepStrictEqual(g.map((p) => p.name), ['A', 'solo_one']);
  assert.strictEqual(g[1].items[0].uploadPath, 'root/solo_one/solo one.png');
});
test('a folder with no subfolders is a single part (server grouping)', () => {
  const g = G.groupFolder(E('PartX/front.png', 'PartX/top.png'));
  assert.deepStrictEqual(g.map((p) => [p.name, p.views]), [['PartX', 2]]);
});
test('dotfiles, unsupported types and spec-only folders are dropped', () => {
  const g = G.groupFolder(E('r/A/.DS_Store', 'r/A/x.dwg', 'r/B/spec.txt', 'r/C/front.png'));
  assert.deepStrictEqual(g.map((p) => p.name), ['C']);
});
test('uniqueName', () => {
  assert.strictEqual(G.uniqueName('a', []), 'a');
  assert.strictEqual(G.uniqueName('a', ['A']), 'a_2');
  assert.strictEqual(G.uniqueName('a', ['a', 'a_2']), 'a_3');
});
