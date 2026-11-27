# Solid Flow v8 backend contract (drawing replication + cost/runtime accounting)

Audience: the UI/server agent (`FINAL_UI/server/reverse_api.py`). Backend owner: `2D-3D-CAD-Test-Generation/reverse/*`.
Additive to `V7_CONTRACT.md`: every v7 field keeps its meaning. Fields below marked `(new)` are new; the UI must tolerate their absence on old jobs
(old jobs return `estimate: null`, `usage` with `calls: 0`, `timing` with `null` members, `replication: null`).
Money is always a JSON number in USD **or `null` when unknown** (never `0` for unknown). Display `null` as "unavailable" (never `$0.00`).
Sub-cent values are real: show at least 4 decimals below $0.01.

## 1. Pre-run estimate (new)

```python
ReverseService.estimate_run(part_paths, reference=None, options=None) -> dict
```

`part_paths` are the same server paths as `submit`. `reference` is the same object as `submit`. Cheap, COM-free, makes no model call and no network call.
Safe to call on every change of selection / mode / PDF; the result is deterministic for the same inputs and the same pricing file.

```json
{
  "schema_version": 1,
  "mode": "standard" | "match",
  "model": "gpt-6-astra",
  "parts": [ { "part": "<str(path) as passed>", "name": "A001651E.SLDPRT",
               "reference": { "status": "none" | "resolved" | "blocked" | "pending", "pages": 1, "extraction_cache": "hit" | "fresh" | "supplemented" | "none" },
               "estimate": <Estimate> } ],
  "total": <Estimate>,
  "budget": { "cap_usd": 20.0, "spent_usd": 16.2, "remaining_usd": 3.8, "would_block": false, "note": "A new call is refused when projected spend exceeds the remaining budget; an in-flight request can exceed its estimate." }
}
```

`<Estimate>` (also attached to `job_view` as `job.estimate` and `parts[i].estimate`, frozen at submit time so it can be compared with actuals):

```json
{
  "duration": { "low_s": 90, "expected_s": 150, "high_s": 330, "source": "history" | "fallback", "basis": "median of 7 completed parts (1 page) ..." },
  "cost": { "low": 0.04, "expected": 0.21, "high": 0.62, "currency": "USD", "rate_version": "2026-11-27", "model": "gpt-6-astra",
            "unavailable_reason": null },
  "tokens": { "input": {"low": 0, "expected": 0, "high": 0}, "output": {"low": 0, "expected": 0, "high": 0}, "cached_input": 0 },
  "by_stage": { "extraction": {"cost": {"low":..,"expected":..,"high":..}, "tokens": {...}, "duration_s": {...}, "calls": {"low":0,"expected":1,"high":3}},
                "tiles": {...}, "validation": {...}, "correction": {...}, "local_generation": {"cost": {"low":0,"expected":0,"high":0}, "duration_s": {...}} },
  "assumptions": ["1 page, no tiling", "extraction reused from cache (hash+schema+completeness match): $0", "..."],
  "labels": ["fallback_duration", "fallback_tokens"]
}
```

* Standard mode (no reference): cost is `{"low":0,"expected":0,"high":0}` (no model call exists in that path), `unavailable_reason: null`.
* If the rate for the configured model is missing from `config/pricing.json`: every `cost.*` is `null` and `unavailable_reason` explains it (tokens are still estimated).
* `source: "fallback"` means no comparable history; the UI must label the figure "rough estimate".
* `labels` lists every estimate component that used a fallback (for a visible caveat).
* Extraction savings (`extraction_cache: "hit"`) appear only when reuse is confirmed (same PDF sha256 + schema version + completeness).

## 2. Job view additions (new)

`job_view(job_id)` adds, at the job level and (same shape) on each `parts[i]`:

```json
{
  "estimate": <Estimate> | null,
  "usage": {
    "calls": 3, "cache_hits": 1, "unpriced_calls": 0, "unknown_usage_calls": 0,
    "input_tokens": 41234, "cached_tokens": 0, "output_tokens": 5120,
    "cost_usd": 0.6691 | null,
    "cost_status": "priced" | "partial" | "unpriced" | "none",
    "currency": "USD", "model": "gpt-6-astra", "rate_version": "2026-11-27",
    "by_stage": { "extraction": {"calls": 1, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "cost_usd": 0.0 | null, "attempts": 1},
                  "tiles": {...}, "validation": {...}, "correction": {...} },
    "attempts": [ { "stage": "extraction", "attempt": 0, "response_id": "resp_..." | null, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0,
                    "cost_usd": 0.0 | null, "ok": true, "cache_hit": false } ],
    "historical_usd": 0.2 | null
  },
  "timing": {
    "queued_s": 3.2, "elapsed_s": 141.7, "running": true,
    "by_stage": { "preflight": 1.2, "stl_export": 9.0, "extraction": 20.1, "native_drawing": 40.0, ... },
    "remaining_s": { "low": 10, "expected": 55, "high": 120, "source": "history" | "fallback" } | null
  },
  "estimate_vs_actual": { "cost_usd": {"expected": 0.21, "actual": 0.19, "within_range": true} | null, "duration_s": {...} | null }
}
```

* `usage` is aggregated from the per-request ledger (Decimal arithmetic, dedupe by provider response id, attempts listed separately, local cache hit = `$0` and
  `calls` not incremented, a response without usage counts as `unknown_usage_calls` and makes `cost_usd`/`cost_status` partial or `null`, never free).
* `cost_usd: null` and `cost_status: "unpriced"` => show "unavailable". `"partial"` => show the known part with "+ unpriced calls".
* `timing.elapsed_s` uses monotonic clocks; `queued_s` is separate (submit -> first stage). Parallel stages are never summed into elapsed.
* A canceled or failed part keeps the usage/cost it incurred.
* Job-level `usage`/`timing`/`estimate` aggregate every part (by_stage merged); per-part views stay available under `parts[i]`.
* Existing `job.actual_api_cost_usd` stays (float, may under-report when unpriced; prefer `usage.cost_usd`).

## 3. Replication (new)

`reference.mode == "match"` is the replication mode. A part view adds `parts[i].replication` (`null` for standard/old jobs):

```json
{
  "status": "verified" | "needs_review" | "blocked" | "failed" | "pending",
  "status_label": "Verified" | "Needs Review" | "Blocked" | "Failed",
  "reason": "plain-language reason (first blocker / review item)",
  "spec": { "schema": "drawingspec/1", "pages": 2, "extraction_reuse": "hit" | "supplemented" | "fresh", "completeness": 0.96 },
  "sheets": [ { "page": 1, "source": {"width_mm": 431.8, "height_mm": 279.4, "rotation": 0, "scale": "1:2" | null},
                "generated": {"width_mm": 431.8, "height_mm": 279.4, "scale": "1:2", "title_block_scale": "1:2"},
                "view_count": {"source": 2, "generated": 2}, "annotations": {"source": 41, "generated": 39, "matched": 37, "missing": 2, "extra": 0, "mismatched": 2} } ],
  "scales": { "sheet": {"source": "1:2", "generated": "1:2", "title_block": "1:2", "match": true}, "views": [ {"id": "V1", "source": "1:2", "generated": "1:2", "match": true} ] },
  "iterations": { "used": 1, "max": 3, "best": 1, "stop_reason": "passed" | "iteration_cap" | "no_improvement" | "budget" | "canceled" },
  "thresholds": { "view_center_mm": 1.0, "annotation_anchor_mm": 1.0, "scale_ratio_pct_inferred": 0.5, "scale_explicit": "exact" },
  "metrics": { "view_center_dev_mm": {"median": 0.4, "max": 0.9}, "annotation_anchor_dev_mm": {"median": 0.5, "max": 3.2},
               "notes_verbatim": {"matched": 12, "total": 12}, "unintended_clipping": 0, "critical_mismatches": 0 },
  "displacements": 4,
  "issues": [ { "id": "R001", "kind": "missing_annotation" | "extra_annotation" | "value_mismatch" | "text_mismatch" | "scale_mismatch" | "view_missing" | "position_deviation" | "clipping" | "page_missing" | "unreadable_source",
                "severity": "critical" | "high" | "medium" | "low", "page": 1, "text": "..." , "detail": "..." } ],
  "images": { "side_by_side": ["<rel path>"], "overlay": ["<rel path>"], "difference": ["<rel path>"] },
  "fidelity_diagnostics_separate_from_scoring": true
}
```

Statuses: `verified` requires zero unintended clipping, zero unresolved critical mismatches, every explicit scale exact. Anything partially matched is
`needs_review` (never "identical"). `blocked` = a precondition is missing (no source PDF, unreadable source, page unreadable). `failed` = a run error.
`part.state` mapping is unchanged (`completed` only on `verified`-quality QA; otherwise `review_required`). Job status is never `completed` for a part with
`replication.status != "verified"` unless the engineer accepted the issues through the existing review workflow.

New artifact aliases in `files` / `files_availability` (only when the file exists, otherwise omitted):

| key | file |
|---|---|
| `drawing_spec` | `reference/drawing_spec.json` |
| `replication_report` | `replication/report.json` |
| `usage_log` | `usage/usage_ledger.jsonl` (secrets-free) |
| `comparison_images` | `comparison/*.png` (side-by-side, overlay, difference per page; names contain `side_by_side`, `overlay`, `diff`) |

## 4. Stages (unchanged order; new sub-stage records)

The 10 v7 stages are unchanged. `parts[i].stages[stage]` may add `seconds`, `queued_s` and, for `comparison_correction`, `iterations`.
`timing.by_stage` and `usage.by_stage` use the same stage keys, plus the model-call stage names `extraction`, `tiles`, `validation`, `correction`.

## 5. Errors

Unchanged. `estimate_run` never raises for a bad/missing path: that part gets `reference.status: "blocked"` / `estimate: null` and a `warning` string.

## 6. Implementation notes (as built, v8)

* `replication.pages[]` (additional to `sheets[]`): one entry per page after the first with `status`, `generated_scale`, `scale_match`, `notes_verbatim {matched,total}`, `views`, `views_not_reproduced`, `warnings`.
  `replication.sheets[0].generated.title_block_scale` is the text the SHEET prints (the replicated source title-block note, e.g. `1"=2"`), compared by ratio with the sheet scale.
* `replication.metrics.notes_verbatim` counts only exact (case, symbol, digit exact; whitespace-normalised) matches read from the EXPORTED pdf. Lines that differ only by GD&T / frame glyphs the
  export did not print are listed in the report as `symbols_unverified` and make the status `needs_review`; they are not counted as verbatim.
* `estimate` is frozen at submit in `job.options["estimates"]` (per part); `estimate_vs_actual` is filled only when both sides are known.
* Pre-v8 job views are unchanged apart from the added keys (`estimate: null`, `replication: null`, `usage.calls: 0`).
* Replication is the `match` mode (`job.options.replicate`, default true); standard mode is untouched.
