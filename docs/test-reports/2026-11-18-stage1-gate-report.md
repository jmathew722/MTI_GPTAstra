# Stage 1 gate report — structured progress and cost telemetry (2026-11-18)

Branch `Improvements`. Evidence files: `docs/test-reports/stage1-evidence/`.

## Commits

| Task | Commit | Subject |
|---|---|---|
| 1.1 + 1.2 | `6853f8b` | versioned run event stream and observable-work progress engine |
| 1.3 | `f6d813c` | emit detailed progress for every run phase |
| 1.4 | `9c47a21` | expose run, part and session ledger scopes with live cost events |
| 1.5 | `345408e` | serve live structured progress and cost snapshots (FastAPI) |
| 1.6 | `f44cf9c` | consume structured progress telemetry (UI reducer) |

## Schema

Event envelope `schema_version: 1` (`pipeline/run_events.py`); stdout prefix `[gptastra-event] `; durable
`run_events.jsonl` (one file per part, attempts append, each event carries `run_id` + `attempt`).
Kinds emitted: `run.started`, `progress.updated`, `cost.updated`, `operation.failed`, `run.completed`,
`run.failed`, `run.cancelled`. Real stream: `stage1-evidence/run_events.sb11033.attempts1-2.jsonl`
(38 events, two attempts of SB11033, both ending `run.completed`, `seq` strictly increasing per run,
percent reaches 100.0 only on the `terminal: completed` event, 99.9 before it).

## Commands and results

| Command | Result |
|---|---|
| `cd 2D-3D-CAD-Test-Generation; python -m pytest -q` | **1044 passed, 66 skipped**, exit 0 (baseline 1019 / 66) |
| `cd FINAL_UI; python -m pytest tests/server -q` | **16 passed**, exit 0 (new) |
| `cd FINAL_UI; node --test "tests/unit/*.test.js"` | **117 pass / 3 fail of 120**, exit 1 (baseline 107 / 3 of 110) |
| `cd FINAL_UI/tests/e2e; npx playwright test` | **11 passed, 13 failed, 6 skipped**, exit 0 |

### Baseline failures (pre-existing; not hidden, not weakened)

* **UI unit, 3:** `logparse` "events over a real transcript…", `selectors` "status and source over a full
  payload…", `runstate` "run/finalized computes track…". Cause: missing fixture
  `FINAL_UI/tests/fixtures/part_full.log` (ENOENT). Identical at the baseline commit `698e8a7`.
* **Playwright, 13:** tests 1, 4, 5, 6, 10, 11, 13, 15, 16, 17, 18, 19, 20. I re-ran the whole suite
  against a clean checkout of `698e8a7` (served on a separate port, isolated data dir): the **same 13**
  fail there. Test 1 and 20 expect the old home heading "What would you like to create?"; the app says
  "Your vision, Our blueprint" since rebrand commit `fb5305f`. The 13 therefore are stale tests, not
  regressions from this stage. They are *not* fixed here.

## Gate checklist

| Requirement | Evidence |
|---|---|
| Stream from start through artifact finalization | `run_events.sb11033.attempts1-2.jsonl` |
| No time-based updates | `ProgressEngine` never reads a clock; `tests/test_progress.py` |
| No backward progress | engine high-water mark; server and UI reducers refuse regressions; tests in all three layers |
| Run/part/session cost reconciles for a retry | `cost_reconciliation_retry.json`: rows 0.145 + 0.245; run2 = 0.245, part = session = 0.390 = sum of rows |
| Legacy readable | `legacy_state()` / `legacy_markers` source; `test_saved_events_are_replayed_and_old_runs_are_labeled_legacy`; legacy ledger rows counted in `legacy_rows` |
| Stale events cannot overwrite active attempt | `test_stale_run_cannot_overwrite_active_attempt…` (server) and the JS equivalent |
| Failed/cancelled stop at last truthful % | `test_terminal_events_and_percent_stop_on_failure`; JS `failed and cancelled runs stop…` |
| Unpriced stays visible, never `$0.00` | `test_unpriced_rows_are_visible_not_zero` (`cost_usd: null`, `pricing_status`) |

## Known limitations

* **Cost evidence uses fixture pricing and synthetic ledger rows.** The events and progress come from a real
  `run_part`; no paid model call was made for the gate. Real-pricing reconciliation needs a paid run.
* **In that harness, `cost.updated` seq 1 precedes `run.started`**: the harness wrote the synthetic ledger
  row before calling `run_part`. Consumers adopt a run from whichever event arrives first.
* **No per-feature events for the CadQuery reference build.** The reference is built by running a generated
  script, so it publishes one unit ("reference solid built"), not one per feature. Per-feature events exist
  for the SolidWorks generation phase (callback-driven), which was not exercised live in this gate.
* **The UI tracker does not yet render the new data** (operation name, unit counts, cost). The reducer
  exposes it as `view().progress`; Stage 2 renders it.
* **`_usage_summary` still reads the legacy `token_usage_log.jsonl`**, not the IR `usage_ledger.jsonl`.
  Stage 2 task 2.3 addresses the Results cost data.
* `GPTASTRA_STRUCTURED_EVENTS` is on by default for runs launched by the UI server (set via the child
  process env); CLI runs need it set to `1`.
