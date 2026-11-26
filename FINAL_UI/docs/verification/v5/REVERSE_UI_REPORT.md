# 3D -> 2D UI: verification report (2026-11-25)

Scope: server `server/reverse_api.py`, frontend `web/static/js/pages/reverse.js` (+ `logic/reverseview.js`, `css/reverse.css`), Projects / Recent Files integration.
Backend under test: `2D-3D-CAD-Test-Generation/reverse/*` (`ReverseService`), driven unchanged.

**Evidence level.** Everything below used TEST-ONLY fixtures: a fake engine for the API tests, and fixture jobs written into an isolated data dir for the browser tests.
Fixture artifacts are labelled (`"demo": true` in `manifest.json`, the PDF says "TEST FIXTURE - not a SOLIDWORKS drawing", the STL header says it is a box fixture).
**Nothing here proves that SOLIDWORKS produced a native drawing.** SOLIDWORKS was not started and no paid API call was made.

## Commands run and results

| What | Command (from `FINAL_UI/`) | Result |
|---|---|---|
| API + queue + safety (fake engine) | `PYTHONUTF8=1 python -m pytest tests/server/test_v5_reverse.py -q` | 24 passed, repeated 8 times with no flake |
| All server tests | `PYTHONUTF8=1 python -m pytest tests/server -q` | 136 passed |
| Pure logic | `node --test tests/unit/reverseview.test.js` | 18 passed |
| All unit tests | `cd tests/unit && node --test "*.test.js"` | 259 passed, 3 failed (see below, not from this work) |
| Browser, page under test | `tests/e2e/run31.sh tests/31-v5-reverse.spec.ts` (server on :8212 with isolated `MCAGENT_DATA`) | 14 passed (51 s) |

Unit failures (pre-existing, missing fixture `tests/fixtures/part_full.log`): `events over a real transcript...`, `status and source over a full payload...`, `run/finalized computes track...`.

Existing browser suites run against the :8212 test server after the sidebar change (`01-05-basics`, `15-16-responsive-a11y`, `17-keyboard`, `20-home`): see "Regression" below.

## What the browser spec covers (31-v5-reverse.spec.ts)

- Route, nav order (Home, Workspace, 3D -> 2D, Projects), `aria-current`, collapsed-rail tooltip attribute, Workspace page unaffected.
- Default (no runs, route-mocked empty list): empty states for both viewers, Run disabled with its reason, 8 pending stages.
- Processing: tracker nodes equal the real stage records, caption "Dimensions (running)", progress below 100, STL shown as soon as it exists, drawing absent, queued part shows empty states.
- Review required: both viewers load (PDF canvas has non-white pixels, "Sheet 1 of 2"), issue cards carry severity label + icon, observed/expected, next action; accept/reject disabled with a reason until a note is entered; accepted issue shows who/when/note and sorts after open ones; reopen needs no note; the review overlay does not change the PDF canvas.
- Complete: engine text from the detected revision, `$0.00 API usage (CAD automation; licence/compute excluded)` only because the job recorded 0, coverage "12 of 12 applicable characteristics verified", Files tab lists only existing files.
- Mixed batch: success, review and failure rows side by side; selecting a row updates both viewers; the failed part shows its STL (stage 2 ran) and no drawing; Retry only on the failed row.
- Stale guard: a deliberately slow STL for part A never appears after switching to part B.
- Pickers: recursive toggle, case-insensitive extension, duplicate names flagged, run buttons disabled with reasons, nothing submitted (job count unchanged).
- Template task running (route-mocked): upload and generate disabled with a reason; validation status for generated / failed / stock templates.
- Projects and Recent Files: badge "3D -> 2D", real timestamps, preview thumbnail from `preview/page-001.png`.
- Keyboard: tab arrows / Home / End, Escape closes the setup drawer and returns focus, collapse results panel (`aria-expanded`).
- Layout audit (no accent within 8 px of text, no clipped labels, no horizontal scroll) at 1920, 1440, 1366, 1100, 800 and 390, sidebar expanded and collapsed (>= 1440), on the Overview, Review and Files tabs, plus the setup drawer below 1100.
- axe: no serious or critical violations on default, review (5 tabs), processing, 390 and the 390 drawer.
- Honesty: no placeholder wording, no `null`/`undefined`/`NaN` text, every button has an accessible name.

Screenshots (`docs/verification/v5/reverse/`): `default-`, `processing-`, `review-required-`, `review-required-issues-`, `complete-` at 1280, 1440 and 1920, plus `projects-1440.png`.

## Bugs found and fixed during verification

1. Panel headers printed the word "null" (`replaceChildren(a, null)`), caught from a screenshot, now asserted against in the spec.
2. axe: scrollable tables lacked keyboard focus (`scrollable-region-focusable`); low-contrast counters inside the selected row.
3. The layout audit flagged the tracker node border as an accent 3 px from its icon; nodes are now a uniform ring.

## Backend gaps found (not fixed in the backend; mitigated in the API layer where noted)

1. `JobStore.load()` reads `job.json` unlocked while `save()` replaces it (`os.replace`); on Windows a poll during a save raises `PermissionError` (seen as intermittent 500s and a crashed submit). Same for `TemplateCatalog._load/_save` and `index.json`. Mitigated by wrapping both with the store lock in `reverse_api.service()`.
2. A cancel can be lost: the worker holds its own `Job` and every `store.save(job)` rewrites `cancel_requested=False`, so a queued part later runs. Mitigated in the API (`_CANCEL_PENDING` preserves the flag on save); the real fix belongs in `JobStore.save` (merge `cancel_requested`).
3. `ReverseService.retry()` leaves failed parts in state `failed` until the worker reaches them, so a poll right after Retry shows the old state and the job still looks finished. The API resets the retried parts to `queued` first.
4. `review_action()` rewrites the whole job file from a fresh load while a worker may be saving its own copy of the same job; a decision on a running job would be overwritten. The API returns 409 for review on a running job.
5. `ReverseService.history()` omits the thumbnail and SOLIDWORKS info the UI needs; the API composes its own listing from the store.

## Not run / not verified

- NOT RUN: any real SOLIDWORKS job from the UI (submit with real parts, template generate / upload through the CAD worker). The upload and generate endpoints are covered only with the service methods replaced by test doubles.
- NOT RUN: the 500 MB upload cap with a real 500 MB file (the cap logic is the only thing exercised, with small files in the API tests).
- NOT RUN: browsers other than Chromium; physical zoom levels (window widths stand in for 125% to 300% zoom).
- The "Run a folder on the server" control is exercised in API tests (authorized and refused roots) but not submitted from the browser.
- The 3D viewer is a separate, smaller three.js scene (same vendored libraries and colour tokens) rather than a reuse of `features/viewer3d.js`, which is bound to the Workspace DOM and store.
- A second `.btn.gold` now exists in the document (Run selected on the 3D -> 2D page, as specified); the older Boot test `01-05 #1` asserts exactly one, and already fails earlier on a stale Home heading.

## Regression

See the bottom of this file for the existing-suite results.

### Regression results (existing browser suites on the :8212 test server)

`01-05-basics`, `15-16-responsive-a11y`, `17-keyboard`, `20-home`: 6 passed, 7 failed.
- Failed: `01-05 #1` (expects the Home heading "What would you like to create", the committed heading is "Your vision, Our blueprint"), `01-05 #4`, `#5`, `15-16 #15`, `#16`, `17 #17` (all time out inside the `createPart` helper at `#orient-gallery select.oselect`, a Workspace upload flow this work does not touch), `20-home #20` (Home copy assertion).
- Passed: routing (`01-05 #2`, which loops over pages and still passes with the new route), status honesty, `20-home #21` to `#24`.
- I did not run these against a tree without my change, so "pre-existing" is an inference from the failure sites (Home copy, `createPart`), not a measured fact.
