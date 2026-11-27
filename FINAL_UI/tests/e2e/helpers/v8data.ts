import { Page } from '@playwright/test';

// Realistic V8_CONTRACT.md payload shapes (sections 1-3), injected into GET /api/reverse/jobs/<id> responses by the browser specs. TEST SEED: they prove the UI's
// handling of such payloads, not backend output (the backend computes these from its own ledger; see make_v8_fixture.py).

export const ESTIMATE = (o: any = {}) => ({
  duration: { low_s: 90, expected_s: 150, high_s: 330, source: 'history', basis: 'median of 7 completed parts (1 page)' },
  cost: { low: 0.04, expected: 0.21, high: 0.62, currency: 'USD', rate_version: '2026-11-27', model: 'gpt-6-astra', unavailable_reason: null },
  tokens: { input: { low: 10000, expected: 20000, high: 40000 }, output: { low: 2000, expected: 4000, high: 9000 }, cached_input: 0 },
  by_stage: {
    extraction: { cost: { low: 0.02, expected: 0.09, high: 0.3 }, tokens: {}, duration_s: { low: 10, expected: 20, high: 60 }, calls: { low: 0, expected: 1, high: 3 } },
    validation: { cost: { low: 0.01, expected: 0.05, high: 0.2 }, tokens: {}, duration_s: { low: 5, expected: 10, high: 30 }, calls: { low: 0, expected: 1, high: 2 } },
    local_generation: { cost: { low: 0, expected: 0, high: 0 }, duration_s: { low: 60, expected: 120, high: 240 } },
  },
  assumptions: ['1 page, no tiling', 'extraction reused from cache (hash+schema+completeness match): $0'],
  labels: [],
  ...o,
});

export const USAGE = (o: any = {}) => ({
  calls: 3, cache_hits: 0, unpriced_calls: 0, unknown_usage_calls: 0, input_tokens: 41234, cached_tokens: 1000, output_tokens: 5120, cost_usd: 0.0043, cost_status: 'priced', currency: 'USD', model: 'gpt-6-astra', rate_version: '2026-11-27',
  by_stage: {
    extraction: { calls: 1, input_tokens: 30000, cached_tokens: 1000, output_tokens: 4000, cost_usd: 0.003, attempts: 1 },
    validation: { calls: 1, input_tokens: 8000, cached_tokens: 0, output_tokens: 900, cost_usd: 0.0008, attempts: 1 },
    correction: { calls: 1, input_tokens: 3234, cached_tokens: 0, output_tokens: 220, cost_usd: 0.0005, attempts: 3 },
  },
  attempts: [], historical_usd: null, ...o,
});

export const TIMING = (o: any = {}) => ({ queued_s: 3.2, elapsed_s: 141.7, running: false, by_stage: { preflight: 1.2, stl_export: 9, native_drawing: 40, extraction: 20.1 }, remaining_s: null, ...o });

type Kind = 'verified' | 'needs_review' | 'blocked' | 'failed';
export const REPLICATION = (kind: Kind, o: any = {}) => {
  const label = { verified: 'Verified', needs_review: 'Needs Review', blocked: 'Blocked', failed: 'Failed' }[kind];
  const issues = kind === 'verified' ? [] : [
    { id: 'R001', kind: 'missing_annotation', severity: 'high', page: 1, text: 'R12', detail: 'present in the source, not generated' },
    { id: 'R002', kind: 'extra_annotation', severity: 'low', page: 1, text: 'NOTE 9', detail: 'generated but not in the source' },
    { id: 'R003', kind: 'value_mismatch', severity: 'medium', page: 1, text: 'HOLE 4X', detail: '0.25 vs 0.2500' },
    { id: 'R004', kind: 'scale_mismatch', severity: 'critical', page: 1, text: 'V1', detail: 'view scale 1:2 vs 1:4' },
  ];
  return {
    status: kind, status_label: label, reason: kind === 'verified' ? '' : kind === 'needs_review' ? '2 annotations are missing and 1 scale differs' : kind === 'blocked' ? 'The source PDF could not be read' : 'The run ended with an error',
    spec: { schema: 'drawingspec/1', pages: 1, extraction_reuse: 'hit', completeness: 0.96 },
    sheets: [{ page: 1, source: { width_mm: 431.8, height_mm: 279.4, rotation: 0, scale: '1:2' }, generated: { width_mm: 431.8, height_mm: 279.4, scale: '1:2', title_block_scale: '1:2' }, view_count: { source: 2, generated: 2 },
      annotations: { source: 41, generated: 39, matched: kind === 'verified' ? 41 : 37, missing: kind === 'verified' ? 0 : 2, extra: kind === 'verified' ? 0 : 1, mismatched: kind === 'verified' ? 0 : 2 } }],
    scales: { sheet: { source: '1:2', generated: '1:2', title_block: '1:2', match: true }, views: kind === 'verified' ? [{ id: 'V1', source: '1:2', generated: '1:2', match: true }] : [{ id: 'V1', source: '1:2', generated: '1:4', match: false }] },
    iterations: { used: 1, max: 3, best: 1, stop_reason: kind === 'verified' ? 'passed' : 'iteration_cap' },
    thresholds: { view_center_mm: 1.0, annotation_anchor_mm: 1.0, scale_ratio_pct_inferred: 0.5, scale_explicit: 'exact' },
    metrics: {}, displacements: 0, issues, images: { side_by_side: [], overlay: [], difference: [] }, fidelity_diagnostics_separate_from_scoring: true, ...o,
  };
};

export const withImages = (r: any) => ({ ...r, images: { side_by_side: ['comparison/side_by_side-page-001.png'], overlay: ['comparison/overlay-page-001.png'], difference: ['comparison/diff-page-001.png'] } });

/** Merge extra fields into the real GET /api/reverse/jobs/<id> response: patch(job) mutates it. */
export async function inject(page: Page, jobId: string, patch: (job: any) => void) {
  await page.route(new RegExp('/api/reverse/jobs/' + jobId + '(\\?.*)?$'), async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const res = await route.fetch();
    const j = await res.json();
    patch(j);
    await route.fulfill({ response: res, json: j });
  });
}

export const part = (job: any, id: string) => job.parts.find((p: any) => p.part_id === id);

/** The standard v8 enrichment of the comparison job r3d_8000000000000001. */
export function enrichComparison(job: any) {
  const set = (id: string, rep: any, over: any = {}) => { const p = part(job, id); if (p) Object.assign(p, { replication: rep }, over); };
  set('verified', REPLICATION('verified'), { usage: USAGE({ calls: 0, cache_hits: 1, cost_usd: 0, cost_status: 'none', input_tokens: 0, output_tokens: 0, cached_tokens: 0, by_stage: {}, historical_usd: 0.2 }), timing: TIMING({ elapsed_s: 60 }) });
  set('needsrev', withImages(REPLICATION('needs_review')), { usage: USAGE(), timing: TIMING() });
  set('multi', REPLICATION('verified', { spec: { schema: 'drawingspec/1', pages: 2, extraction_reuse: 'fresh', completeness: 1 } }), { usage: USAGE({ cost_usd: 0.0043 }), timing: TIMING({ elapsed_s: 80 }) });
  set('mismatchpages', REPLICATION('needs_review'), { usage: USAGE({ cost_usd: 0.012 }), timing: TIMING({ elapsed_s: 70 }) });
  set('blocked', REPLICATION('blocked'), { usage: USAGE({ calls: 0, cost_usd: null, cost_status: 'none', by_stage: {}, input_tokens: 0, output_tokens: 0, cached_tokens: 0 }), timing: TIMING({ elapsed_s: 1, by_stage: {} }) });
  set('plain', null as any, { usage: USAGE({ calls: 0, cost_usd: 0, cost_status: 'none', by_stage: {}, input_tokens: 0, output_tokens: 0, cached_tokens: 0 }), timing: TIMING({ elapsed_s: 52 }) });
  set('nosld', REPLICATION('verified'), { usage: USAGE({ cost_usd: 0.0021 }), timing: TIMING({ elapsed_s: 45 }) });
  job.estimate = ESTIMATE({ cost: { low: 0.1, expected: 0.5, high: 1.4, currency: 'USD', rate_version: '2026-11-27', model: 'gpt-6-astra', unavailable_reason: null } });
  job.usage = USAGE({ calls: 12, cost_usd: 0.0212, cache_hits: 1 });
  job.timing = TIMING({ elapsed_s: 400, queued_s: 3.2 });
  job.estimate_vs_actual = { cost_usd: { expected: 0.5, actual: 0.0212, within_range: false }, duration_s: { expected: 450, actual: 400, within_range: true } };
}
