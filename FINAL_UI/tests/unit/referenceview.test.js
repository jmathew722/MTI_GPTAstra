'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { logic } = require('./_helpers');
const F = logic('referenceview.js');
const R = logic('reverseview.js');

const st = (status, extra) => Object.assign({ status, warnings: [], errors: [], seconds: 1 }, extra || {});

test('artifacts: aliases and legacy names, unavailable entries are absent', () => {
  const part = { files: { 'drawing.pdf': { bytes: 5, url_path: 'a/b/drawing.pdf' }, slddrw: { bytes: 9, url_path: 'a/b/drawing.slddrw', available: true }, source_pdf: { bytes: 3, url_path: 'a/b/reference/source.pdf', available: false } } };
  assert.deepEqual(F.artifactOf(part, 'pdf'), { rel: 'a/b/drawing.pdf', bytes: 5 });
  assert.deepEqual(F.artifactOf(part, 'slddrw'), { rel: 'a/b/drawing.slddrw', bytes: 9 });
  assert.equal(F.artifactOf(part, 'source_pdf'), null);
  assert.equal(F.artifactOf(null, 'pdf'), null);
  assert.equal(F.artifactOf({ files: { pdf: { url_path: '' } } }, 'pdf'), null);
  assert.deepEqual(F.comparisonImages({ files: { comparison_images: { available: true, files: [{ name: 'page-001.png', bytes: 4, url_path: 'x/comparison/page-001.png' }, { name: 'bad' }] } } }).map((x) => x.name), ['page-001.png']);
  assert.deepEqual(F.comparisonImages({ files: { comparison_images: { available: false, files: [{ url_path: 'x' }] } } }), []);
});

const INFO = (over) => Object.assign({ status: { key: 'review_required', label: 'Draft: review required', tone: 'amber', requires_ack: true, reasons: ['r'] },
  downloads: { slddrw: { available: true, bytes: 10, filename: 'a-drawing.slddrw' }, pdf: { available: true, bytes: 20, filename: 'a-drawing.pdf' }, zip: { available: true, bytes: 30, filename: 'a-drawing.zip' } } }, over || {});

test('export: enabled only for real artifacts, acknowledgement gates unapproved drafts, busy blocks', () => {
  let v = F.exportView(INFO(), false, false);
  assert.ok(v.buttons.every((b) => !b.enabled && /acknowledg/i.test(b.reason)));
  v = F.exportView(INFO(), true, false);
  assert.ok(v.buttons.every((b) => b.enabled));
  assert.ok(F.exportView(INFO(), true, true).buttons.every((b) => !b.enabled && /progress/.test(b.reason)));
  const noPdf = INFO(); noPdf.downloads.pdf = { available: false, reason: 'The drawing PDF was not produced for this part.' }; noPdf.downloads.zip = { available: false, reason: 'Both must exist.' };
  v = F.exportView(noPdf, true, false);
  assert.deepEqual(v.buttons.map((b) => b.enabled), [true, false, false]);
  assert.match(v.buttons[1].reason, /not produced/);
  const clean = INFO({ status: { key: 'draft', label: 'Draft: for review (not approved for manufacture)', tone: 'blue', requires_ack: false, reasons: [] } });
  assert.ok(F.exportView(clean, false, false).buttons.every((b) => b.enabled), 'a verified draft needs no acknowledgement');
  assert.ok(F.exportView(null, true, false).buttons.every((b) => !b.enabled));
  assert.equal(F.exportView(null, true, false).ready, false);
});

test('export key changes with selection, state and artifact size (stale acknowledgements are dropped)', () => {
  const job = { job_id: 'j1' };
  const p = (over) => Object.assign({ part_id: 'a', state: 'completed', files: { slddrw: { bytes: 1, url_path: 'x' }, pdf: { bytes: 2, url_path: 'y' } } }, over);
  const k = F.exportKey(job, p());
  assert.notEqual(k, F.exportKey(job, p({ part_id: 'b' })));
  assert.notEqual(k, F.exportKey({ job_id: 'j2' }, p()));
  assert.notEqual(k, F.exportKey(job, p({ state: 'review_required' })));
  assert.notEqual(k, F.exportKey(job, p({ files: { slddrw: { bytes: 7, url_path: 'x' }, pdf: { bytes: 2, url_path: 'y' } } })));
  assert.equal(k, F.exportKey(job, p()));
  assert.equal(F.exportKey(null, p()), '');
});

const cand = (id, over) => Object.assign({ artifact_id: id, filename: id + '.pdf', project: 'P', run: 'R', date: '2026-11-20T10:00', pages: 1, confidence: 0.98, needs_confirmation: false }, over || {});
const row = (over) => Object.assign({ key: 'p0', name: 'a.sldprt', source: 'auto', upload: null, artifactId: '', confirmed: false, lookup: null, looking: false }, over || {});

test('row resolution: auto, ambiguous, unmatched, upload, saved, fallback', () => {
  assert.equal(F.rowResolution(row(), false).status, 'unknown');
  assert.equal(F.rowResolution(row({ looking: true }), false).status, 'checking');
  const ok = F.rowResolution(row({ lookup: { selected: cand('pdf_1'), candidates: [cand('pdf_1')] } }), false);
  assert.equal(ok.status, 'ready'); assert.match(ok.label, /Auto-matched: pdf_1\.pdf · 1 page · P \/ R · 2026-11-20 · 98% confidence/);
  const amb = F.rowResolution(row({ lookup: { selected: null, candidates: [cand('a', { needs_confirmation: true }), cand('b', { needs_confirmation: true })] } }), false);
  assert.equal(amb.status, 'needs_confirmation'); assert.match(amb.label, /2 possible matches/);
  assert.equal(F.rowResolution(row({ lookup: { selected: null, candidates: [] } }), false).status, 'unmatched');
  assert.equal(F.rowResolution(row({ lookup: { selected: null, candidates: [] } }), true).status, 'unmatched', 'no silent fallback: Standard must be chosen per row');
  assert.equal(F.rowResolution(row({ source: 'upload' }), false).status, 'unmatched');
  assert.equal(F.rowResolution(row({ source: 'upload', upload: { upload_id: 'x'.repeat(64), filename: 'm.pdf', pages: 2 } }), false).label, 'Uploaded: m.pdf (2 pages)');
  const lk = { selected: null, candidates: [cand('a', { needs_confirmation: true })] };
  assert.equal(F.rowResolution(row({ source: 'artifact', artifactId: 'a', lookup: lk }), false).status, 'needs_confirmation');
  assert.equal(F.rowResolution(row({ source: 'artifact', artifactId: 'a', confirmed: true, lookup: lk }), false).status, 'ready');
  assert.equal(F.rowResolution(row({ source: 'artifact', artifactId: 'zzz', lookup: lk }), false).status, 'unmatched');
  assert.equal(F.rowResolution(row({ source: 'none' }), false).status, 'standard');
});

test('run block: standard never blocks; match blocks on unmatched, needs confirmation and capability, with actionable rows', () => {
  const caps = { reference: true };
  assert.equal(F.referenceRunBlock({ mode: 'standard', rows: [row()], caps: null }).reason, '');
  assert.match(F.referenceRunBlock({ mode: 'match', rows: [row()], caps: { reference: false } }).reason, /not available/);
  const ready = row({ key: 'p0', lookup: { selected: cand('a'), candidates: [cand('a')] } });
  const none = row({ key: 'p1', lookup: { selected: null, candidates: [] } });
  const amb = row({ key: 'p2', lookup: { selected: null, candidates: [cand('x', { needs_confirmation: true })] } });
  assert.equal(F.referenceRunBlock({ mode: 'match', rows: [ready], caps }).reason, '');
  let b = F.referenceRunBlock({ mode: 'match', rows: [ready, none], caps });
  assert.match(b.reason, /1 part has no reference\. Upload one or choose Standard for it/); assert.deepEqual(b.actionable, ['p1']);
  b = F.referenceRunBlock({ mode: 'match', rows: [ready, none, amb], caps });
  assert.match(b.reason, /confirm the reference for 1 part/); assert.deepEqual(b.actionable, ['p1', 'p2']);
  assert.equal(F.referenceRunBlock({ mode: 'match', rows: [ready, row({ key: 'p1', source: 'none' })], caps }).reason, '', 'an explicit per-row Standard choice unblocks the run');
  assert.match(F.referenceRunBlock({ mode: 'match', rows: [row()], caps }).reason, /Checking/);
  assert.equal(F.referenceLine({ mode: 'match', rows: [ready, none, amb] }), '1 of 3 matched · 1 need confirmation · 1 unmatched');
  assert.match(F.referenceLine({ mode: 'standard' }), /Standard layout/);
});

test('payload: sends exactly what the user saw; upload ids and confirmed artifact ids only', () => {
  const ready = row({ key: 'p0', lookup: { selected: cand('pdf_a'), candidates: [cand('pdf_a')] } });
  const up = row({ key: 'p1', source: 'upload', upload: { upload_id: 'f'.repeat(64), filename: 'x.pdf', pages: 1 } });
  const sv = row({ key: 'p2', source: 'artifact', artifactId: 'pdf_b', confirmed: true });
  const none = row({ key: 'p3', source: 'none' });
  assert.deepEqual(F.buildReferencePayload('standard', [ready]), { mode: 'standard' });
  assert.equal(F.buildReferencePayload('match', [ready, up]).fallback_standard, false, 'the backend fallback flag is sent only when a row chose Standard');
  const pl = F.buildReferencePayload('match', [ready, up, sv, none]);
  assert.deepEqual(pl, { mode: 'match', fallback_standard: true, per_part: { p0: { source: 'artifact', artifact_id: 'pdf_a' }, p1: { source: 'upload', upload_id: 'f'.repeat(64) },
    p2: { source: 'artifact', artifact_id: 'pdf_b' }, p3: { source: 'none' } } });
  assert.ok(!JSON.stringify(pl).includes('pdf_path'), 'the browser never names a server path');
});

test('provenance and source view: never fall back to the generated PDF, name what is missing', () => {
  const ref = { mode: 'match', status: 'resolved', source_kind: 'history', filename: 'A001151E.pdf', sha256: 'ab'.repeat(32), pages: 2, link: 'part_hash', confidence: 0.98, extraction_cache: 'hit', api_usage: { usd: 0, calls: 0 } };
  const rows = Object.fromEntries(F.provenanceRows(ref));
  assert.equal(rows.Source, 'Forward run history'); assert.equal(rows['SHA-256'], 'abababababab'); assert.match(rows.Extraction, /no new model call/); assert.match(rows['OpenAI usage'], /No OpenAI call/);
  assert.deepEqual(F.provenanceRows({ mode: 'standard' }), []);
  const part = { files: { pdf: { bytes: 1, url_path: 'g.pdf' }, source_pdf: { bytes: 2, url_path: 'reference/source.pdf' } }, reference: ref };
  const sv = F.sourceView(part);
  assert.equal(sv.available, true); assert.equal(sv.rel, 'reference/source.pdf'); assert.match(sv.provenance, /A001151E\.pdf · 2 pages · Forward run history · SHA-256 abababababab/);
  const std = F.sourceView({ files: { pdf: { bytes: 1, url_path: 'g.pdf' } }, reference: { mode: 'standard', status: 'not_applicable' } });
  assert.equal(std.available, false); assert.match(std.reason, /Standard mode/); assert.equal(std.rel, undefined);
  assert.match(F.sourceView({ files: {}, reference: { mode: 'match', status: 'blocked' } }).reason, /blocked/);
  assert.match(F.sourceView({ files: {}, reference: { mode: 'match', status: 'fallback_standard' } }).reason, /Standard mode/);
  assert.match(F.sourceView({ files: {}, reference: { mode: 'match', status: 'resolved' } }).reason, /not available/);
  assert.match(F.sourceView({ files: { pdf: { bytes: 1, url_path: 'g.pdf' } } }).reason, /No source PDF is recorded/);
  assert.equal(F.sourceView(null).available, false);
});

test('usage text: unknown is never $0; cache hit is stated; local CAD time is never a token cost', () => {
  assert.equal(F.apiUsageText(null), 'Not recorded');
  assert.equal(F.apiUsageText({}), 'Not recorded');
  assert.match(F.apiUsageText({ usd: 0.0312, calls: 2, input_tokens: 1000, output_tokens: 50 }), /\$0\.0312 OpenAI \(this run\), 2 calls, 1000 in \/ 50 out tokens/);
  const s = F.costSummary({ parts: [{ reference: { api_usage: { usd: 0.01 } } }, {}], actual_api_cost_usd: 0 }, 'About 1 min', 'match');
  assert.match(s.openai, /\$0\.0100 OpenAI across 1 part \(others not recorded\)/); assert.match(s.cad, /no token cost/);
  assert.match(F.costSummary(null, '', 'match').openai, /may use OpenAI/);
  assert.match(F.costSummary(null, '', 'standard').openai, /No OpenAI calls/);
  assert.match(F.costSummary({ parts: [], actual_api_cost_usd: 0 }, '', 'standard').openai, /\$0\.00 OpenAI/);
  assert.match(F.costSummary({ parts: [] }, '', 'standard').openai, /not recorded/);
});

test('verification: omit what is missing; passed is still a draft', () => {
  assert.match(F.verificationInfo({ status: 'passed' }).label, /not approved/);
  assert.equal(F.verificationInfo({ status: 'review_required' }).tone, 'amber');
  assert.equal(F.verificationInfo(null).tone, 'none');
  assert.deepEqual(F.verificationLines({ status: 'passed' }), []);
  assert.deepEqual(F.verificationLines({ coverage: { matched: 9, total: 10, unresolved: [{}] }, collisions: { count: 0 }, iterations: { used: 2, max: 3 } }),
    [['Items matched', '9 of 10 (1 unresolved)'], ['Overlaps', 'None found'], ['Correction passes', '2 of 3']]);
});

test('stage vocabulary: legacy eight, v7 order from the job, not_applicable is its own state', () => {
  const legacy = { state: 'dimensioning', stages: { preflight: st('succeeded'), mesh_export: st('succeeded'), dimensioning: st('running') } };
  assert.equal(R.stageStates(legacy).length, 8);
  const v7 = { state: 'native_drawing', stages: { preflight: st('succeeded'), stl_export: st('succeeded'), reference_resolution: st('not_applicable'), extraction: st('not_applicable'), view_planning: st('succeeded'), native_drawing: st('running') } };
  const n = R.stageStates(v7);
  assert.equal(n.length, 10);
  assert.deepEqual(n.slice(0, 6).map((x) => x.state), ['succeeded', 'succeeded', 'na', 'na', 'succeeded', 'running']);
  assert.equal(R.stateWord('na'), 'Not applicable');
  assert.deepEqual(R.stageProgress(n), { done: 3, total: 8 });
  assert.equal(R.stageCaption(v7), 'Native drawing (running)');
  const order = ['preflight', 'stl_export', 'verification', 'publish'];
  assert.deepEqual(R.stageStates({ state: 'queued', stages: {} }, { stage_order: order, stage_labels: { publish: 'Publish X' } }).map((x) => x.id), order);
  assert.equal(R.stageStates({ state: 'queued', stages: {} }).length, 10, 'nothing recorded: the current (v7) vocabulary');
  ['reference_resolution', 'extraction', 'view_planning', 'native_drawing', 'dimensioning_layout', 'comparison_correction', 'stl_export', 'publish'].forEach((s) => assert.ok(R.partStateInfo(s).label !== 'Unknown', s));
});
