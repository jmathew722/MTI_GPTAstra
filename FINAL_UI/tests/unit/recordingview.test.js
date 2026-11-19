'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const RV = H.logic('recordingview.js');

const CH = [{ id: 'F001', label: 'F001 prism: built', status: 'built', t: 2.27 },
            { id: 'F002', label: 'F002 hole: built', status: 'built', t: 8.18 },
            { id: 'F005', label: 'F005 hole: built', status: 'built', t: 15.07 }];
const rec = (o = {}) => ({ present: true, status: 'ready', has_video: true, duration_s: 33, width: 1520, height: 856, bytes: 1100000,
  chapters: CH, dropped_frames: 0, code: '', reason: '', ...o });

test('describe: no recording is "Not recorded" with the way to turn it on', () => {
  for (const r of [null, undefined, { present: false, status: 'none' }]) {
    const d = RV.describe(r);
    assert.equal(d.kind, 'none');
    assert.equal(d.playable, false);
    assert.match(d.detail, /Record pipeline run/);
  }
});

test('describe: ready and partial are playable; partial explains the gap', () => {
  assert.deepEqual([RV.describe(rec()).kind, RV.describe(rec()).playable, RV.describe(rec()).tone], ['ready', true, 'ok']);
  const p = RV.describe(rec({ status: 'partial', code: 'REC_COVERED', dropped_frames: 12 }));
  assert.equal(p.kind, 'partial');
  assert.equal(p.playable, true);
  assert.equal(p.tone, 'warn');
  assert.match(p.detail, /covered SolidWorks/);
});

test('describe: failed, skipped, stale, interrupted and recording never claim a video', () => {
  const f = RV.describe(rec({ status: 'failed', has_video: false, code: 'REC_NO_WINDOW' }));
  assert.equal(f.kind, 'failed');
  assert.equal(f.tone, 'err');
  assert.equal(f.playable, false);
  assert.match(f.detail, /SolidWorks window was not found/);
  assert.equal(RV.describe(rec({ status: 'skipped', has_video: false, code: 'REC_NOT_REACHED', reason: 'Extraction failed' })).kind, 'skipped');
  assert.equal(RV.describe(rec({ status: 'stale', has_video: false })).kind, 'stale');
  assert.equal(RV.describe(rec({ status: 'interrupted', has_video: false, code: 'REC_INTERRUPTED' })).kind, 'interrupted');
  const live = RV.describe(rec({ status: 'recording', has_video: false }));
  assert.equal(live.kind, 'recording');
  assert.equal(live.playable, false);
});

test('describe: a ready status without a video file is a failure, never a blank player', () => {
  const d = RV.describe(rec({ has_video: false }));
  assert.equal(d.kind, 'failed');
  assert.equal(d.playable, false);
});

test('codeText falls back to the manifest reason for an unknown code', () => {
  assert.equal(RV.codeText('REC_NOPE', 'because'), 'because');
  assert.equal(RV.codeText('REC_NOPE'), '');
  assert.ok(Object.keys(RV.CODE_TEXT).length >= 9);
});

test('formatting: duration, size and the facts line', () => {
  assert.equal(RV.fmtDuration(33), '0:33');
  assert.equal(RV.fmtDuration(125.4), '2:05');
  assert.equal(RV.fmtDuration(-4), '0:00');
  assert.equal(RV.fmtDuration('x'), '0:00');
  assert.equal(RV.fmtBytes(500), '500 B');
  assert.equal(RV.fmtBytes(2048), '2 KB');
  assert.equal(RV.fmtBytes(1100000), '1.0 MB');
  assert.equal(RV.facts(rec()), '0:33 · 1520×856 · 1.0 MB · 3 features');
  assert.match(RV.facts(rec({ dropped_frames: 4 })), /4 dropped$/);
  assert.equal(RV.facts(null), '');
});

test('chapterAt: the chapter playing now; -1 before the first; stable at the boundary', () => {
  assert.equal(RV.chapterAt(CH, 0), -1);
  assert.equal(RV.chapterAt(CH, 2.27), 0);
  assert.equal(RV.chapterAt(CH, 8.0), 0);
  assert.equal(RV.chapterAt(CH, 8.2), 1);
  assert.equal(RV.chapterAt(CH, 999), 2);
  assert.equal(RV.chapterAt([], 5), -1);
  assert.equal(RV.chapterAt(null, 5), -1);
});

test('seekTime: just before the chapter, clamped to the video', () => {
  assert.equal(RV.seekTime(CH[1], 33), 7.88);
  assert.equal(RV.seekTime({ t: 0.1 }, 33), 0);
  assert.equal(RV.seekTime({ t: 40 }, 33), 32.9);
  assert.equal(RV.seekTime(null, 0), 0);
});

test('speedOf only offers 1x, 2x and 4x', () => {
  assert.deepEqual(RV.SPEEDS, [1, 2, 4]);
  assert.equal(RV.speedOf('2'), 2);
  assert.equal(RV.speedOf(4), 4);
  assert.equal(RV.speedOf(3), 1);
  assert.equal(RV.speedOf('fast'), 1);
});

test('checkbox: disabled with a concrete reason until recording is possible', () => {
  const on = { available: true, backend: 'wgc', encoder: 'h264', reason: '' };
  assert.deepEqual(RV.checkbox(on, { reachable: true, running: false }).disabled, false);
  assert.match(RV.checkbox(on, { reachable: true }).hint, /only the SolidWorks window/);
  assert.equal(RV.checkbox(on, { reachable: true, running: true }).disabled, true);
  assert.equal(RV.checkbox(on, { reachable: true, running: true }).reason, 'A run is in progress.');
  assert.equal(RV.checkbox(on, { reachable: false }).reason, 'Server unreachable.');
  const loading = RV.checkbox(null, { reachable: true });
  assert.equal(loading.disabled, true);
  assert.match(loading.reason, /Checking/);
  const off = RV.checkbox({ available: false, reason: 'Recording needs Windows.' }, { reachable: true });
  assert.equal(off.disabled, true);
  assert.equal(off.hint, 'Not available: Recording needs Windows.');
  assert.match(RV.checkbox({ available: false }, { reachable: true }).reason, /not available on this machine/);
});

test('shouldRecord: ticked AND available; a locked-while-running box still records later batch parts', () => {
  const on = { available: true };
  assert.equal(RV.shouldRecord(true, on), true);
  assert.equal(RV.shouldRecord(false, on), false);
  assert.equal(RV.shouldRecord(true, { available: false }), false);
  assert.equal(RV.shouldRecord(true, null), false);
});
