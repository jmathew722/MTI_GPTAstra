'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { logic } = require('./_helpers');
const R = logic('reverseview.js');

const st = (status, extra) => Object.assign({ status, warnings: [], errors: [], seconds: 2 }, extra || {});

test('eight stages in the required order with the required labels', () => {
  assert.deepEqual(R.STAGES.map((s) => s.label), ['Preflight', 'STL export', 'Geometry inventory', 'View planning', 'Native drawing', 'Dimensions', 'Verification', 'Publish']);
});

test('stage tracker maps real stage records only (no time guesses)', () => {
  const part = { state: 'dimensioning', stages: { preflight: st('succeeded'), mesh_export: st('succeeded'), inventory: st('warning'), planning: st('succeeded'), drawing: st('succeeded'), dimensioning: st('running') } };
  const n = R.stageStates(part);
  assert.deepEqual(n.map((x) => x.state), ['succeeded', 'succeeded', 'warning', 'succeeded', 'succeeded', 'running', 'pending', 'pending']);
  assert.equal(R.stageCaption(part), 'Dimensions (running)');
  assert.ok(n.every((x) => R.stateWord(x.state)));
  assert.deepEqual(R.stageStates(null).map((x) => x.state), Array(8).fill('pending'));
  assert.equal(R.stageCaption({ state: 'queued', stages: {} }), 'Waiting in the queue');
});

test('failed and canceled stages', () => {
  const failed = { state: 'failed', stages: { preflight: st('succeeded'), mesh_export: st('failed', { errors: ['boom'] }) } };
  assert.equal(R.stageStates(failed)[1].state, 'failed');
  assert.equal(R.stageCaption(failed), 'STL export failed');
  const canceled = { state: 'canceled', stages: { preflight: st('succeeded'), mesh_export: st('failed', { errors: ['canceled'] }) } };
  assert.equal(R.stageStates(canceled)[1].state, 'skipped');
  const canceledRunning = { state: 'canceled', stages: { preflight: st('running') } };
  assert.equal(R.stageStates(canceledRunning)[0].state, 'skipped');
  assert.equal(R.stageCaption({ state: 'completed', stages: {} }), 'All stages done');
});

test('every part state has label, icon and tone; unknown is its own state', () => {
  ['queued', 'preflight', 'mesh_export', 'inventory', 'planning', 'drawing', 'dimensioning', 'verification', 'publishing', 'completed', 'review_required', 'failed', 'canceled'].forEach((s) => {
    const i = R.partStateInfo(s); assert.ok(i.label && i.icon && i.tone, s);
  });
  assert.equal(R.partStateInfo('wat').label, 'Unknown');
  assert.equal(R.partStateInfo('review_required').tone, 'amber');
  assert.equal(R.summaryLabel('completed_with_failures'), 'Completed with failures');
  assert.equal(R.isTerminal('failed'), true); assert.equal(R.isTerminal('drawing'), false);
});

test('progress text and percent are measured; never 100 while active; null without data', () => {
  const p = { stages_done: 12, stages_total: 16, parts_done: 1, parts_total: 2 };
  assert.equal(R.percent(p, 'running'), 75);
  assert.equal(R.progressText(p, 'running'), '1 of 2 parts done · 75% of stages (12/16)');
  assert.equal(R.percent({ stages_done: 15, stages_total: 15 }, 'running'), 99);
  assert.equal(R.percent({ stages_done: 15, stages_total: 15 }, 'completed'), 100);
  assert.equal(R.percent({ stages_done: 0, stages_total: 0 }, 'queued'), null);
  assert.equal(R.percent(null, 'queued'), null);
  assert.equal(R.percent({ stages_done: 7, stages_total: 8 }, 'completed'), 87, 'floors, never rounds up');
  assert.equal(R.progressText({ parts_total: 0 }), 'No parts');
  assert.equal(R.progressText({ stages_done: 0, stages_total: 8, parts_done: 0, parts_total: 1 }, 'queued'), '0 of 1 part done · 0% of stages (0/8)');
});

test('engine text uses the actual revision; never hard-codes one', () => {
  assert.equal(R.engineText({ solidworks: { revision: '33.5.0', service_pack: 'SP5.0', is_2025: true } }), 'SOLIDWORKS 2025 · 33.5.0 SP5.0');
  assert.equal(R.engineText({ solidworks: { revision: '32.1.0', service_pack: 'SP1.0', is_2025: false } }), 'SOLIDWORKS · 32.1.0 SP1.0');
  assert.equal(R.engineText(null, null), 'SOLIDWORKS · not detected yet');
  assert.equal(R.engineText({ solidworks: {} }, { solidworks: { detected: false, revision: '' } }), 'SOLIDWORKS · not detected yet');
  assert.match(R.engineText({}, { solidworks: { detected: true, revision: '' } }), /running/);
  assert.match(R.engineText({}, { solidworks: { revision: '33.1.0', service_pack: 'SP1', is_2025: true } }), /33\.1\.0/);
});

test('cost: zero only when measured as zero, otherwise honest', () => {
  assert.equal(R.costText({ actual_api_cost_usd: 0 }), '$0.00 API usage (CAD automation; licence/compute excluded)');
  assert.equal(R.costText({ actual_api_cost_usd: 0.1234 }), '$0.12 API usage (measured)');
  assert.equal(R.costText({}), 'API usage not recorded');
  assert.equal(R.costText(null), 'API usage not recorded');
  assert.equal(R.costText({ actual_api_cost_usd: null }), 'API usage not recorded');
});

test('runtime is the sum of measured seconds, empty when none', () => {
  assert.equal(R.runtimeText([{ seconds: 52 }, { seconds: 61.5 }]), '1 min 54 s');
  assert.equal(R.runtimeText([{ seconds: 12.34 }]), '12.3 s');
  assert.equal(R.runtimeText([{ seconds: 30 }, { seconds: null }]), '30 s (finished parts only)');
  assert.equal(R.runtimeText([{ seconds: null }]), '');
  assert.equal(R.runtimeText([]), '');
});

test('estimate text: a range with its basis, or not enough data', () => {
  assert.equal(R.estimateText({ available: false, basis: '1 completed part(s) in history; at least 3 are needed' }), 'Not enough data to estimate (1 completed part(s) in history; at least 3 are needed)');
  assert.equal(R.estimateText({ available: true, low_s: 90, high_s: 300, basis: 'basis X' }), 'About 1.5 min to 5 min (basis X)');
  assert.equal(R.estimateText({ available: true, low_s: 20, high_s: 40, basis: 'b' }), 'About 20 s to 40 s (b)');
  assert.equal(R.estimateText(null), 'Estimate unavailable');
});

test('issue labels and sorting: open first, then severity; severity has label + icon', () => {
  ['critical', 'high', 'medium', 'low', 'info'].forEach((s) => { const i = R.severityInfo(s); assert.ok(i.label && i.icon); });
  assert.equal(R.severityInfo('zzz').label, 'Unrated');
  const sorted = R.sortIssues([
    { id: 'c', severity: 'low' }, { id: 'a', severity: 'high', disposition: 'accepted' }, { id: 'b', severity: 'critical' }, { id: 'd', severity: 'medium', disposition: 'open' }, { id: 'e', severity: 'high', disposition: 'rejected' }]);
  assert.deepEqual(sorted.map((i) => i.id), ['b', 'd', 'c', 'a', 'e']);
  assert.equal(R.openIssueCount(sorted), 3);
  assert.equal(R.issueLocation({ view: 'Front', sheet: 1 }), 'View Front, Sheet 1');
  assert.equal(R.issueLocation({ view: '', sheet: null }), 'Whole drawing');
  assert.equal(R.issueLocation({ sheet: 0 }), 'Sheet 0');
  assert.equal(R.dispositionInfo({}).label, 'Open'); assert.equal(R.dispositionInfo({ disposition: 'accepted' }).label, 'Accepted');
});

test('review actions need a note except reopen; history line says who and when', () => {
  assert.equal(R.reviewBlock('accept', '  '), 'Enter a note to accept this issue.');
  assert.equal(R.reviewBlock('reject', ''), 'Enter a note to reject this issue.');
  assert.equal(R.reviewBlock('reopen', ''), '');
  assert.equal(R.reviewBlock('accept', 'Reviewed with designer'), '');
  assert.match(R.reviewBlock('accept', 'x'.repeat(2001)), /limited/);
  assert.equal(R.historyLine({ action: 'accept', user: 'Ana', at: '2026-11-25T10:00:00+00:00', note: 'ok' }), 'Accepted by Ana on 2026-11-25 10:00:00 UTC: ok');
  assert.equal(R.historyLine({ action: 'reopen' }), 'Reopened by unknown on time not recorded');
});

test('coverage text keeps the denominator and exclusions visible; a missing score is null', () => {
  assert.equal(R.coverageText({ covered: 11, applicable: 12, percent: 91.66, excluded: [{}, {}] }), '11 of 12 applicable characteristics verified (2 excluded, listed below)');
  assert.equal(R.coverageText({ covered: 12, applicable: 12, percent: 100, excluded: [] }), '12 of 12 applicable characteristics verified');
  assert.equal(R.coverageText({ covered: 0, applicable: 0, percent: null }), 'No applicable characteristics were identified');
  assert.equal(R.coverageText(null), 'Coverage not available');
  assert.equal(R.coverageScore({ percent: 99.9 }), 99.9);
  assert.equal(R.coverageScore({ percent: null }), null);
  assert.equal(R.coverageScore({ percent: 140 }), null);
  assert.equal(R.coverageScore(undefined), null);
});

test('file availability: only listed files; viewer sources reflect what exists', () => {
  const part = { files: { 'model.stl': { bytes: 10, url_path: 'p/active/model.stl' }, 'qa.json': { bytes: 3, url_path: 'p/active/qa.json' } } };
  const s = R.viewerSources(part);
  assert.deepEqual(s.stl, { rel: 'p/active/model.stl', bytes: 10 }); assert.equal(s.pdf, null); assert.equal(s.thumb, null);
  const full = R.viewerSources({ files: Object.assign({ 'drawing.pdf': { bytes: 5, url_path: 'x/drawing.pdf' }, 'preview/page-001.png': { bytes: 1, url_path: 'x/preview/page-001.png' }, 'preview/page-002.png': { bytes: 1, url_path: 'x/preview/page-002.png' } }, part.files) });
  assert.equal(full.pdf.rel, 'x/drawing.pdf'); assert.equal(full.previews, 2); assert.equal(full.thumb, 'x/preview/page-001.png');
  assert.deepEqual(R.viewerSources(null), { stl: null, pdf: null, previews: 0, thumb: null });
  assert.equal(R.viewerKey('j', 'p', null), ''); assert.equal(R.viewerKey('j', 'p', { rel: 'a', bytes: 2 }), 'j|p|a|2');
  const list = R.fileList(part);
  assert.deepEqual(list.map((f) => f.label), ['Model (STL)', 'QA report']);
  assert.equal(R.fileLabel('preview/page-003.png'), 'Preview, sheet 3');
});

test('drawing status never claims approval and never shows a drawing that does not exist', () => {
  assert.match(R.drawingStatus({ state: 'dimensioning', files: {} }).label, /in progress/);
  assert.match(R.drawingStatus({ state: 'failed', files: {} }).label, /failed/);
  assert.equal(R.drawingStatus({ state: 'review_required', files: { 'drawing.pdf': { bytes: 1, url_path: 'a' } } }).label, 'Draft: review required');
  assert.match(R.drawingStatus({ state: 'completed', review_status: 'none', files: { 'drawing.pdf': { bytes: 1, url_path: 'a' } } }).label, /Draft/);
  const rev = R.drawingStatus({ state: 'completed', review_status: 'resolved', files: { 'drawing.pdf': { bytes: 1, url_path: 'a' } } }).label;
  assert.match(rev, /not approved for manufacture/);
  assert.match(R.DRAFT_NOTICE, /not approved for manufacture/);
});

test('run is disabled only with a concrete reason', () => {
  assert.match(R.runBlock({ count: 0 }), /Choose one or more/);
  assert.match(R.runBlock({ count: 2, templateId: '' }), /template/);
  assert.equal(R.runBlock({ count: 2, templateId: 't' }), '');
  assert.match(R.runBlock({ count: 1, templateId: 't', taskRunning: true }), /CAD worker/);
  assert.match(R.runBlock({ count: 1, templateId: 't', templateReason: 'That template failed validation.' }), /failed validation/);
  assert.match(R.templateBlock({ available: false }), /no longer on disk/);
  assert.match(R.templateBlock({ validation: { ok: false } }), /failed validation/);
  assert.equal(R.templateBlock({ available: true, validation: { ok: true } }), '');
  assert.equal(R.templateStatus({ validation: { ok: true } }).label, 'Validated in SOLIDWORKS');
  assert.equal(R.templateStatus({ source: 'stock', validation: { ok: null } }).tone, 'blue');
  assert.equal(R.templateStatus({ source: 'uploaded', validation: { ok: null } }).label, 'Not validated yet');
  assert.equal(R.sourceWord('generated'), 'Generated default');
});

test('part picker: case-insensitive extension, lock files dropped, recursive toggle, duplicates identified', () => {
  const items = [{ name: 'A.SLDPRT', rel: 'top/A.SLDPRT' }, { name: 'b.sldprt', rel: 'top/sub/b.sldprt' }, { name: 'c.sldasm', rel: 'top/c.sldasm' }, { name: '~$d.sldprt', rel: 'top/~$d.sldprt' }, { name: 'e.txt', rel: 'top/e.txt' }];
  assert.deepEqual(R.filterPicked(items, false).map((i) => i.name), ['A.SLDPRT']);
  assert.deepEqual(R.filterPicked(items, true).map((i) => i.name), ['A.SLDPRT', 'b.sldprt']);
  assert.deepEqual(R.filterPicked([{ name: 'x.SldPrt' }], false).map((i) => i.name), ['x.SldPrt'], 'multi-file picks have no folder depth');
  const d = R.markDuplicates([{ name: 'a.sldprt' }, { name: 'A.SLDPRT' }, { name: 'b.sldprt' }]);
  assert.deepEqual(d.map((i) => i.dup), [2, 2, 0]);
  assert.equal(R.pickedSummary(d, 2), '3 parts selected (2 with duplicate names; each runs separately); 2 non-part files ignored');
  assert.equal(R.pickedSummary([{ name: 'a' }], 0), '1 part selected');
  assert.equal(R.isSldprt('X.SLDPRT'), true); assert.equal(R.isSldprt('x.sldprt.txt'), false);
});

test('request guard: only the newest token is current (stale viewer results are dropped)', () => {
  const g = R.makeGuard();
  const a = g.next(); const b = g.next();
  assert.equal(g.isCurrent(a), false); assert.equal(g.isCurrent(b), true);
  assert.equal(g.current(), b);
});

test('previous run label and event helpers', () => {
  assert.equal(R.isPreviousRun({ job_id: 'a' }, ['a']), false);
  assert.equal(R.isPreviousRun({ job_id: 'a' }, ['b']), true);
  assert.equal(R.isPreviousRun(null, []), false);
  assert.equal(R.eventLine({ kind: 'stage_end', stage: 'preflight', status: 'succeeded' }), 'stage_end · preflight · succeeded');
  const m = R.mergeEvents([{ seq: 0 }, { seq: 1 }], [{ seq: 1 }, { seq: 2 }]);
  assert.deepEqual(m.map((e) => e.seq), [0, 1, 2]);
});
