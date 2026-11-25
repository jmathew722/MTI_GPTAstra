'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { logic } = require('./_helpers');
const F = logic('folderplan.js');

const E = (...paths) => paths.map((p) => ({ name: p.split('/').pop(), path: p, size: 100 }));

test('a PDF-only folder: every PDF is one job, whatever its page count', () => {
  const p = F.plan(E('batch/a.pdf', 'batch/b.pdf', 'batch/c.pdf'));
  assert.deepEqual(p.jobs.map((j) => [j.name, j.type]), [['a', 'pdf'], ['b', 'pdf'], ['c', 'pdf']]);
  assert.equal(p.total, 3);
  assert.deepEqual(p.skipped, []);
});

test('an image-only folder: each image is its own job (jpg, jpeg, png)', () => {
  const p = F.plan(E('imgs/one.jpg', 'imgs/two.jpeg', 'imgs/three.png'));
  assert.deepEqual(p.jobs.map((j) => j.type), ['image', 'image', 'image']);
  assert.equal(p.parts.length, 0);
});

test('a mixed folder is planned together, in order, with uppercase extensions', () => {
  const p = F.plan(E('m/A.PDF', 'm/B.JPG', 'm/C.Png', 'm/D.JPEG', 'm/e.pdf'));
  assert.deepEqual(p.jobs.map((j) => j.name), ['A', 'B', 'C', 'D', 'e']);
  assert.deepEqual(p.jobs.map((j) => j.type), ['pdf', 'image', 'image', 'image', 'pdf']);
  assert.ok(p.jobs.every((j) => j.ext === j.ext.toLowerCase()));
});

test('unsupported files are skipped with a reason; hidden files are skipped quietly', () => {
  const p = F.plan(E('m/a.pdf', 'm/notes.docx', 'm/model.step', 'm/.DS_Store', 'm/Thumbs.db', 'm/noext'));
  assert.deepEqual(p.jobs.map((j) => j.name), ['a']);
  const shown = p.skipped.filter((s) => !s.silent).map((s) => s.name).sort();
  assert.deepEqual(shown, ['model.step', 'noext', 'notes.docx']);
  assert.equal(p.skipped.filter((s) => s.silent).length, 2);
  assert.match(F.skippedSummary(p.skipped), /3 skipped|unsupported/);
  assert.equal(F.skippedSummary([{ name: '.x', reason: 'hidden', silent: true }]), '');
});

test('an empty (0 byte) file is skipped with a reason, an empty folder plans nothing', () => {
  const p = F.plan([{ name: 'z.pdf', path: 'm/z.pdf', size: 0 }, { name: 'ok.pdf', path: 'm/ok.pdf', size: 5 }]);
  assert.deepEqual(p.jobs.map((j) => j.name), ['ok']);
  assert.match(p.skipped[0].reason, /empty/);
  const none = F.plan([]);
  assert.equal(none.total, 0);
});

test('immediate files only by default; recursive scanning is explicit', () => {
  const entries = E('root/top.pdf', 'root/sub/deep.pdf', 'root/sub/deeper/x.png');
  const def = F.plan(entries);
  assert.deepEqual(def.jobs.map((j) => j.name), ['top']);
  assert.ok(def.skipped.some((s) => /subfolder/.test(s.reason)));
  const rec = F.plan(entries, { recursive: true });
  assert.deepEqual(rec.jobs.map((j) => j.name).sort(), ['deep', 'top', 'x']);
});

test('a subfolder of view images is still one multi-view part (Upload Parts Folder layout)', () => {
  const p = F.plan(E('root/PartA/front.png', 'root/PartA/top.png', 'root/PartA/notes.txt', 'root/loose.pdf'));
  assert.deepEqual(p.parts.map((x) => [x.name, x.views]), [['PartA', 2]]);
  assert.equal(p.parts[0].items.length, 3);
  assert.deepEqual(p.jobs.map((j) => j.name), ['loose']);
  assert.equal(p.total, 2);
});

test('names: spaces, Unicode, duplicates and traversal are made safe and unique', () => {
  const p = F.plan(E('r/My Part (rev 2).pdf', 'r/My Part (rev 2).PNG', 'r/图纸.pdf', 'r/图纸二.pdf', 'r/café.pdf'));
  const names = p.jobs.map((j) => j.name);
  assert.equal(new Set(names.map((n) => n.toLowerCase())).size, names.length);
  assert.equal(names[0], 'My_Part_rev_2');
  assert.equal(names[1], 'My_Part_rev_2_2');
  assert.match(names[2], /^drawing_/);
  assert.match(names[3], /^drawing_/);
  assert.notEqual(names[2], names[3]);
  assert.ok(names.every((n) => /^[A-Za-z0-9_-]+$/.test(n)));
  const evil = F.plan(E('r/../../etc/passwd.pdf', '..\\..\\evil.pdf'));
  assert.ok(evil.jobs.every((j) => !/[\\/.]/.test(j.name)));
});

test('stable ids: the same input plans to the same id, a different one does not', () => {
  const a = F.plan([{ name: 'a.pdf', path: 'r/a.pdf', size: 1, lastModified: 5 }]).jobs[0].id;
  const b = F.plan([{ name: 'a.pdf', path: 'r/a.pdf', size: 1, lastModified: 5 }]).jobs[0].id;
  const c = F.plan([{ name: 'a.pdf', path: 'r/a.pdf', size: 2, lastModified: 5 }]).jobs[0].id;
  assert.equal(a, b);
  assert.notEqual(a, c);
});

test('detect: real content decides, not the extension', () => {
  const b = (...x) => x;
  assert.equal(F.detect(b(0x25, 0x50, 0x44, 0x46, 0x2d, 0x31)), 'pdf');
  assert.equal(F.detect(b(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a)), 'png');
  assert.equal(F.detect(b(0xff, 0xd8, 0xff, 0xe0)), 'jpeg');
  assert.equal(F.detect(b(0x4d, 0x5a, 0x90, 0)), null);
  assert.equal(F.detect([]), null);
  const pdfJob = { type: 'pdf', ext: 'pdf' }, imgJob = { type: 'image', ext: 'jpg' };
  assert.equal(F.mismatch(pdfJob, b(0x25, 0x50, 0x44, 0x46, 0x2d)), '');
  assert.match(F.mismatch(pdfJob, b(0x89, 0x50, 0x4e, 0x47)), /named \.pdf but the content is PNG/);
  assert.match(F.mismatch(imgJob, b(0x25, 0x50, 0x44, 0x46, 0x2d)), /content is a PDF/);
  assert.match(F.mismatch(pdfJob, b(1, 2, 3, 4)), /not a PDF or image/);
  assert.equal(F.mismatch(imgJob, b(0xff, 0xd8, 0xff)), '');
});
