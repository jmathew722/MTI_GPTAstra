# Token Tracker — Design

**Date:** 2026-10-01 · **Status:** approved; implemented on `feat/token-tracker`
**Related:** [PRD](../../product/PRD.md) (non-functional requirement "Cost visibility"), [auditor loop](2026-09-28-auditor-loop-design.md), [benchmark](2026-09-28-placement-benchmark-design.md)

## Goal

Know what the pipeline costs to run. Record the tokens and dollars of **every model
completion**, broken down by role (extractor, planner/builder, auditor reviewer,
Jev), model, provider, part, benchmark arm, gate and retry attempt. Then report
cost per converted part and per role.

## Why replace `usage_log.record_run`

The existing ledger writes **one row per extraction run**: all calls for a part,
summed. It has no role, no provider, and no per-call detail, and it prices any
unknown model at Sonnet rates, which would under-report Opus 5.5 or GPT-6 Astra.
The new tracker writes **one row per completion**. `record_run` keeps working; its
price table now comes from the same pricing file.

## Components

| File | Purpose |
| --- | --- |
| `config/pricing.json` | USD per 1M tokens, per **provider** and model (input, output, cache_write, cache_read), each with `as_of` and `source`. Unknown or `null` prices make a row **unpriced** (cost empty, flagged), never guessed |
| `pipeline/token_tracker.py` | `UsageRecord`; `normalize_usage()` for Anthropic / Foundry / Bedrock (Mantle and Converse) / OpenAI (Responses and Chat) / Jev / plain dicts; `Pricing`; `TokenTracker` with append-only JSONL; context scopes; `record_completion()` / `record_cache_hit()` helpers that do nothing when no tracker is active |
| `pipeline/token_report.py` | CLI: load ledgers, filter, aggregate, print tables, write CSV and a self-contained offline HTML dashboard |

## Record schema (one JSONL line per completion)

`ts, run_id, part, arm, role, gate, attempt, provider, model,
input_tokens (uncached), output_tokens, cache_read_tokens, cache_write_tokens,
latency_ms, cache_hit, cost_usd (null if unpriced), priced, ok, note`

**Normalization rule:** `input_tokens` always means *uncached* input. OpenAI
reports cached tokens inside its input total, so the cached part is subtracted. For
Anthropic and Bedrock, cache reads and writes are already separate.

## Usage

```python
tracker = TokenTracker(output_dir / "usage" / "usage_ledger.jsonl")
with tracker.activate(part="SB11033", arm="opus-audited"):
    with scope(role="planner", attempt=1, gate=1):
        resp = client.messages.create(...)
        record_completion(resp, model="claude-opus-5-5", provider="anthropic", latency_ms=...)
```

Wired now: `extractor._call` (role `extractor`) and the extraction cache hits.
`main.py` and `run_models.py` activate a tracker for each part. The planner,
auditor and Jev call `record_completion` with their roles when they're built (specs
A and B).

## Report

```bash
python -m pipeline.token_report output/ --html output/usage/usage_report.html --csv output/usage/usage.csv
```

Reports: totals, per role × model × provider, per part (cost per conversion),
per arm, per gate/attempt (retry cost), per run. Filters: `--part`, `--arm`,
`--role`, `--since`. `--reprice` recomputes every row from the current
`pricing.json`, for prices filled in after the run. The dashboard is one HTML file
with inline CSS/SVG and no network requests.

## Out of scope

Budget alarms or caps (can be added on top of `TokenTracker` later); hosted
dashboards; pulling actual invoices from provider billing APIs.

## Testing

- Normalizer cases for each provider shape.
- Pricing: priced, unpriced and partially priced rows.
- JSONL append and scope merging.
- `record_completion` does nothing when no tracker is active.
- Aggregation totals.
- HTML is self-contained (no `http` asset references).
- The extractor records one row per call with a mocked client, plus one row per
  cache hit.
