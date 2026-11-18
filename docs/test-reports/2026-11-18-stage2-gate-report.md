# Stage 2 gate report — UI progress, cost visibility, full-height Results (2026-11-18)

Branch `Improvements`. Evidence: `docs/test-reports/stage2-evidence/` (screenshots, `axe-stage2.json`).

## What changed

| Task | Change |
|---|---|
| 2.1 progress | Tracker shows the **backend's exact percent** (`61.2%`), the active operation and unit count (`Creating feature 7 of 18 · 6 of 18 features`), and an **indeterminate ring with no number** while the denominator is unknown. Announcements are per phase change, never per percent. Reduced motion stops the ring animation. A failed run keeps its last percent. |
| 2.2 key bar | New **Part cost** chip in the top bar (`This run $x · Part $y` while running; `Part cost $y` idle). `Est.` prefix for partial pricing, `Unavailable` for unpriced, `—` before any data. Never `$0.00` for unknown; a sub-cent price shows `<$0.01`. No price constants in JS. |
| 2.3 cost section | Scope cards (This run / Selected part, all attempts / Session), token and cache totals, **per-attempt expandable groups** with a semantic table (stage/role, model, calls, input, cache read, cache write, output, cost, pricing status), raw-ledger download (this part's rows only). Reads the **pipeline ledger** (`usage_ledger.jsonl`); before this the section read only the legacy `token_usage_log.jsonl`, which IR runs do not write. |
| 2.4 drawer | 70% viewport cap and the hard-coded `62px` header offset removed. Maximum = the real space under the header and tracker (measured, re-measured by ResizeObserver). States: collapsed, remembered (per viewport class), **Fit**, **Maximize/Restore**. One scroll owner (the pane). |
| 2.5 results page | Four `vh` caps removed from the standalone page (flows to its full content height). Fixed a latent bug the change exposed: the section nav's `position: sticky` had no room to move (`align-self: start`). |

## Commands and results

| Command | Result |
|---|---|
| `python -m pytest tests/server -q` (FINAL_UI) | **39 passed** |
| `node --test "tests/unit/*.test.js"` | **136 pass / 3 fail of 139** (the 3 are the pre-existing `part_full.log` failures) |
| `npx playwright test tests/21-stage2.spec.ts` | **9 passed** |
| `npx playwright test` (full) | **20 passed, 13 failed, 6 skipped**. The 13 are exactly the baseline set (tests 1,4,5,6,10,11,13,15,16,17,18,19,20), identical to a clean checkout of the pre-change commit. Baseline test 9 (drawer keyboard resize + persistence) still passes. |
| axe (`#hdr-cost`, `.tracker`, `#drawer`) | **0 violations** (`axe-stage2.json`) |

## Gate checklist

| Requirement | Evidence |
|---|---|
| Progress advances from backend units | spec 25: 61.2% / operation / "6 of 18 features"; regressions and stale runs ignored; failure keeps 61.2% |
| Top key bar cost matches the Results part total | spec 21: key `Est. $1.13` = card `$1.125` = 90 priced rows × $0.0125 |
| Every cost row reachable; totals reconcile | spec 21: all 120 rows in the DOM (collapsed groups, not dropped); the other part's `$99` row is not counted; 30 unpriced rows read `Unpriced` and no figure reads `$0.00` |
| Drawer maximum fills available height, not 70% | spec 22: drawer height > 70% of the viewport at 1920×1080, 1440×900, 1366×768; never covers header/tracker; never below the viewport |
| Last Results item reachable at every viewport | spec 22 (drawer) and spec 24 (standalone page) at 1920×1080, 1440×900, 1366×768, **390×844** |
| Standalone page has no artificial cutoff | spec 24: page itself scrolls; no capped nested scroll boxes |
| Screenshots inspected | 15 PNGs in `stage2-evidence/` were viewed; four defects found and fixed from them (below) |

## Defects found by inspecting screenshots (tests had passed)

1. Cost table too wide: wrapping timestamps, Cost/Pricing columns clipped → compact `nowrap` cells, short timestamp.
2. 390 px: the 16-item section list stacked vertically and consumed ~600 px; drawer header slid under the app bar → horizontal scrolling list, sticky header that wraps.
3. Standalone page: section nav vanished on long content (sticky had no room) → `align-self: start`.
4. Tracker caption truncated the unit count (`6 o…`) → two-line caption with full text in the tooltip.
5. An indeterminate structured run hid the ring entirely, so "not yet measurable" was never shown → ring shown without a number.

## Known limitations

* **Real run costs are unpriced.** `gpt-6-astra` has `null` rates in `config/pricing.json`, so real parts show *Unpriced* — correct and honest, but a price must be supplied by you; I did not invent one.
* The stage nodes (Extraction … Verification) are still driven by log markers, not by `progress.phase`; both are emitted by real runs so they agree, but a structured-only stream would not colour the nodes.
* Seeded cost data in the e2e spec is a **fixture** written to a temp `FINAL_OUTPUTs` (via `MCAGENT_FINAL_OUTPUTS`); the server code path is real. No paid run was made.
* The narrow (390 px) cost table scrolls horizontally inside its own focusable region (Cost/Pricing columns are to the right).
* The 13 stale baseline Playwright tests are unchanged and still fail (heading copy etc.).
