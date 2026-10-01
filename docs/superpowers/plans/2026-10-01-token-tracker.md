# Token Tracker Implementation Plan

> Executed inline (TDD) on branch `feat/token-tracker`. Spec:
> [2026-10-01-token-tracker-design.md](../specs/2026-10-01-token-tracker-design.md).

**Goal:** Record tokens and cost for every model completion, per role, model,
provider, part, arm, gate and attempt, and report cost per part and per role.

**Architecture:** An append-only JSONL ledger written by `TokenTracker`, populated
through context-scoped `record_completion()` calls. `token_report` aggregates the
ledger into terminal tables, CSV and an offline HTML dashboard. Prices live in
`config/pricing.json`.

**Tech stack:** Python 3.10+ stdlib (json, contextvars, dataclasses, csv, html),
`rich` (already a dependency), pytest.

## Global constraints

- No new dependencies.
- Code lives in `2D-3D-CAD-Test-Generation/`. Run tests with
  `PYTHONUTF8=1 python -m pytest tests -q`.
- Unknown prices → `cost_usd: null` + `priced: false`. Never silently fall back.
- `input_tokens` in a record always means **uncached** input.
- Recording must never break a pipeline run. With no active tracker it does
  nothing; a ledger write error is logged as a warning and not raised.
- The dashboard HTML makes no network requests: no `http(s)://` asset references.
- The existing 149 tests keep passing. Legacy `usage_log` behavior is unchanged
  (including its fallback).

## Tasks

### Task 1: Pricing + normalization + record type
- Create `config/pricing.json`, `pipeline/token_tracker.py`
  (`UsageRecord`, `normalize_usage`, `Pricing`).
- Interfaces:
  - `normalize_usage(usage_or_response) -> dict[str, int]` with keys `input_tokens`,
    `output_tokens`, `cache_read_tokens`, `cache_write_tokens`.
  - `Pricing.load(path=None)`.
  - `Pricing.cost(provider, model, norm) -> float | None`.
  - `Pricing.price_for(provider, model) -> dict | None`.
- Tests (`tests/test_token_tracker.py`):
  - Anthropic object; OpenAI Responses (cached tokens subtracted); OpenAI Chat;
    Bedrock Converse dict; plain dict; `None`.
  - Pricing: priced cost exact; unknown model → `None`; a nonzero token class with
    a `null` price → `None`; zero tokens → `0.0`.

### Task 2: TokenTracker + scopes
- Interfaces:
  - `TokenTracker(ledger_path, pricing=None, run_id=None)`
  - `.activate(**fields)` (context manager)
  - `.record(norm, *, role, model, provider, latency_ms=None, cache_hit=False, ok=True, note="", **fields) -> UsageRecord`
  - module-level `scope(**fields)`, `current_tracker()`,
    `record_completion(response, *, model, provider, role=None, latency_ms=None, **fields) -> UsageRecord | None`,
    `record_cache_hit(*, model, provider, role=None, **fields)`
- Tests:
  - A row is appended as JSON.
  - Scope fields merge, and inner fields override outer ones.
  - With no active tracker, the helpers return `None` and write no file.
  - A write failure doesn't raise.
  - Cache-hit rows cost 0.

### Task 3: Wire into the pipeline
- Modify `pipeline/extractor.py`:
  - In `_call`, time the call and record it (role default `extractor`, provider
    `anthropic`).
  - Record both cache-hit paths.
- Modify `main.py` and `run_models.py`: activate a tracker at
  `<output>/usage/usage_ledger.jsonl`, with a per-part `scope`.
- Modify `pipeline/usage_log.py`: `PRICING` is built from the `anthropic` provider
  entries in `pricing.json`.
- Modify the code `.gitignore`: ignore the ledger, CSV and report HTML.
- Tests:
  - The extractor writes one row per API call with a mocked client, and one row on
    a cache hit.
  - Existing `test_usage_log` stays green.

### Task 4: Report (aggregation, terminal, CSV)
- Create `pipeline/token_report.py`.
- Interfaces:
  - `load_rows(paths) -> list[dict]`
  - `filter_rows(rows, part=None, arm=None, role=None, since=None)`
  - `reprice(rows, pricing)`
  - `aggregate(rows, keys: tuple[str, ...]) -> list[dict]`
  - `summary(rows) -> dict`
  - `write_csv(rows, path)`
  - `main(argv=None) -> int`
- Tests:
  - Aggregate sums and counts by role and by (role, model).
  - Per-part cost and average.
  - Unpriced rows are counted, not summed as 0.
  - Filters work.
  - The CSV round-trips.
  - The CLI exit code is 0 on an empty ledger, with a clear message.

### Task 5: HTML dashboard
- `render_html(rows, title=...) -> str` in `token_report.py`. Self-contained:
  inline CSS with light/dark tokens, inline SVG bars.
- Tests:
  - The output contains the totals and every role.
  - No `http://` or `https://` in `src`/`href`.
  - HTML-escaped part names.

### Task 6: Docs
- Update CLAUDE.md (commands, rule: every model call goes through
  `record_completion`; the Opus 5.5 forced-`tool_choice` caveat on rule 10),
  STATE.md, README, and spec A (planner uses `auto` + `strict`).
