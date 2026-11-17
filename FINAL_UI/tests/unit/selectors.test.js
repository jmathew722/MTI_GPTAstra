'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./_helpers');
const S = H.logic('selectors.js');

function base(over) {
  const st = {
    server: { reachable: true, live: true },
    parts: { list: [{ name: 'A', n_views: 2, views: ['A_front.png', 'A_top.png'] }], selected: { session: 's1', part: 'A' } },
    intake: { items: [], source: null, previewOverride: false, nameDraft: '' },
    run: { state: 'idle' }, outputs: { payload: null }, batch: { queue: [], results: {} }
  };
  return Object.assign(st, over || {});
}

test('runDisabledReason order', () => {
  assert.equal(S.runDisabledReason(base()), null);
  // 1 beats everything
  assert.equal(S.runDisabledReason(base({ server: { reachable: false, live: false }, run: { state: 'running' } })), 'Server unreachable.');
  // 2 running/queued beats 3-6
  assert.equal(S.runDisabledReason(base({ run: { state: 'running' }, parts: { list: [], selected: null } })), 'A run is in progress.');
  assert.equal(S.runDisabledReason(base({ run: { state: 'queued' } })), 'A run is in progress.');
  // 3 draft with no selected part beats 4
  assert.equal(S.runDisabledReason(base({ intake: { items: [{}] }, parts: { list: [], selected: null } })), 'Save the part first (Part Setup).');
  // 4
  assert.equal(S.runDisabledReason(base({ parts: { list: [], selected: null } })), 'Select or create a part.');
  // 5 no API key: the message names whichever key the server actually needs
  assert.equal(S.runDisabledReason(base({ server: { reachable: true, live: false, keyName: 'OPENAI_API_KEY' },
    parts: { list: [{ name: 'A', n_views: 0 }], selected: { session: 's', part: 'A' } } })),
    'OPENAI_API_KEY is not set on the server. Live extraction is unavailable; use Run Demo.');
  // ...and falls back to a generic phrase when the server has not reported one
  assert.match(S.runDisabledReason(base({ server: { reachable: true, live: false },
    parts: { list: [{ name: 'A' }], selected: { session: 's', part: 'A' } } })),
    /^The extraction API key is not set/);
  // A part with no assigned views still runs: the pipeline reads the full sheet.
  assert.equal(S.runDisabledReason(base({ parts: { list: [{ name: 'A', n_views: 0, views: [] }], selected: { session: 's', part: 'A' } } })), null);
  // draft present but part selected: ok
  assert.equal(S.runDisabledReason(base({ intake: { items: [{}] } })), null);
});

test('runNote never blocks: view assignment was removed', () => {
  assert.equal(S.runNote(base()), null);
  assert.equal(S.runNote(base({ parts: { list: [{ name: 'A', n_views: 1, views: ['A_top.png'] }], selected: { session: 's', part: 'A' } } })), null);
  assert.equal(S.runNote(base({ parts: { list: [], selected: null } })), null);
});

test('deliverables chips', () => {
  assert.deepEqual(S.deliverables(base()), { sldprt: false, stl: { present: false, source: null }, vba: { present: false, count: 0 }, any: false });
  const p = H.payload();
  const d = S.deliverables(base({ outputs: { payload: p } }));
  assert.equal(d.sldprt, true);
  assert.deepEqual(d.stl, { present: true, source: 'solidworks' });
  assert.deepEqual(d.vba, { present: true, count: 2 });
  assert.equal(d.any, true);
  p.categories.sldprt.present = false; p.categories.stl = { present: true, name: 'p.stl', source: 'prevalidation' }; p.categories.macros = { present: false, files: [] };
  const d2 = S.deliverables(base({ outputs: { payload: p } }));
  assert.equal(d2.sldprt, false); assert.equal(d2.stl.source, 'prevalidation'); assert.equal(d2.vba.present, false);
});

test('drawingSource precedence', () => {
  const draft = { items: [{ id: 'a', orientation: 'front', dataURL: 'data:front' }, { id: 'b', orientation: 'overview', dataURL: 'data:ov' }], source: 'data:src', previewOverride: false };
  // previewOverride wins over a selected part, overview item wins over raw source
  assert.deepEqual(S.drawingSource(base({ intake: Object.assign({}, draft, { previewOverride: true }) })), { kind: 'draft', url: 'data:ov' });
  // no override: selected part's overview
  const part = S.drawingSource(base({ intake: draft }));
  assert.equal(part.kind, 'part');
  assert.equal(part.url, '/api/parts/s1/A/overview.jpg');
  // no part: draft
  assert.deepEqual(S.drawingSource(base({ intake: draft, parts: { list: [], selected: null } })), { kind: 'draft', url: 'data:ov' });
  assert.deepEqual(S.drawingSource(base({ intake: { items: [], source: 'data:src' }, parts: { list: [], selected: null } })), { kind: 'draft', url: 'data:src' });
  // override without a draft falls through to the part
  assert.equal(S.drawingSource(base({ intake: { items: [], source: null, previewOverride: true } })).kind, 'part');
  assert.deepEqual(S.drawingSource(base({ parts: { list: [], selected: null } })), { kind: 'empty', url: null });
  // names are URL encoded
  assert.equal(S.drawingSource(base({ parts: { list: [], selected: { session: 's 1', part: 'A/B' } } })).url, '/api/parts/s%201/A%2FB/overview.jpg');
});

test('intakeValidation: a drawing and a name are the only requirements', () => {
  const v = (items, name, run) => S.intakeValidation(base({ intake: { items, nameDraft: name || '' }, run: { state: run || 'idle' } }));
  const it = (o) => ({ id: o, orientation: o });
  assert.equal(v([]).empty, true);
  assert.equal(v([]).message, '');
  // One unassigned image is enough: the pipeline reads the full sheet.
  const bare = v([{ id: 'x', orientation: '' }], 'P');
  assert.equal(bare.ok, true); assert.equal(bare.canSave, true); assert.equal(bare.level, 'ok');
  // A name is still needed.
  assert.match(v([it('top')], '  ').message, /Name the part/);
  assert.equal(v([it('top')], '  ').ok, false);
  // Any orientation, or none, saves; duplicates are no longer a warning.
  for (const o of ['front', 'top', 'bottom', 'left', 'right', 'back', 'overview', 'marked']) {
    assert.equal(v([it(o)], 'P').ok, true, o);
  }
  const dup = v([it('front'), it('front')], 'P');
  assert.equal(dup.ok, true); assert.equal(dup.level, 'ok'); assert.deepEqual(dup.duplicates, []);
  // cannot save while a run is active
  const busy = v([it('front')], 'P', 'running');
  assert.equal(busy.ok, true); assert.equal(busy.canSave, false);
});

test('flagSummary, batchProgress, runtimeMs', () => {
  const p = H.payload();
  assert.equal(S.flagSummary(p).text, '1 high, 1 low');
  assert.equal(S.flagSummary(null).text, 'None');
  const b = S.batchProgress(base({ batch: { active: true, queue: ['A', 'B', 'C'], results: { A: { state: 'succeeded' } } } }));
  assert.equal(b.text, '1 of 3 parts complete');
  assert.equal(S.batchProgress(base()), null);
  assert.equal(S.runtimeMs(base({ run: { state: 'running', startedAt: 1000 } }), 4500), 3500);
  assert.equal(S.runtimeMs(base({ run: { state: 'succeeded', startedAt: 1000, finishedAt: 3000 } }), 9999), 2000);
  assert.equal(S.runtimeMs(base({ run: { state: 'idle' } })), null);
});
