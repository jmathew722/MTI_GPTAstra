# 3D -> 2D workspace, reference viewer and export (v7, UI half)

Date: 2026-11-27. Scope: `FINAL_UI/` only (3D -> 2D page and shared components). No SOLIDWORKS was started and no paid API call was made. Backend contract: `docs/solidflow-upgrades/V7_CONTRACT.md`.

## 1. The blank band under the viewers: root cause and fix

Measured on the unchanged page (`before-*.png`, isolated server, job with 3 parts), distance from the bottom of the viewers to the top of the Batch Queue:

| size | viewers bottom | queue top | gap |
|---|---|---|---|
| 1280x720 | 725 | 1030 | **305 px** |
| 1440x900 | 826 | 1210 | **384 px** (rail 876 px high next to 504 px viewers) |
| 1920x1080 | 833 | 1159 | **326 px** |

Cause: `.rv-main` was a two-column grid (`viewers | setup rail`, `align-items: start`) holding only one row. The setup rail was the tallest item, so the row took its height and the Batch Queue started below the rail, leaving the space under the viewers empty. Not a spacer, `margin-top:auto` or min-height.

Fix (`css/reverse.css`, `pages/reverse.js`): one grid with areas `"split rail" / "queue rail"`. The rail cell is `contain: size` (it has no intrinsic height) and the aside is sticky inside it, so its height is the part of the cell that is on screen (`fitRail()` sets `--rv-rail-h` on scroll/resize/observer; pure layout, no state). The rail can never make the row taller; it scrolls its own content, and Run and Export sit pinned at its bottom. Queue rows scroll inside `.rv-qbody` (max `max(220px, 36vh)`) under a sticky table header; the queue header with the active job status never scrolls away. Below 1100 px the rail stays the existing drawer (Setup button, scrim, Escape), the viewers and queue stack, no horizontal overflow.

After: **12 px at all 24 combinations** (1280x720, 1440x900, 1920x1080, 2560x1100 x zoom 80/100/125% x sidebar open/rail), see `gap-matrix.txt`; also 12 px with an empty queue, a running job and a 5-row batch (spec 34 tests 110, 111).

## 2. What was built

| Area | Files |
|---|---|
| Setup rail (template, parts, reference, advanced, runtime and cost, run, export), reference flow, export actions | `web/static/js/pages/reverse-rail.js` (new) |
| Page: layout, left viewer toggle, queue reference badge, verification block, stage vocabulary | `web/static/js/pages/reverse.js`, `css/reverse.css` |
| Reusable PDF viewer (pages, zoom, fit, drag-pan, loading/error/empty, Retry) | `web/static/js/features/pdfpane.js` (new) |
| Pure rules (artifacts, export state, reference rows, payload, provenance, source availability, usage text) | `web/static/js/logic/referenceview.js` (new), `logic/reverseview.js` (v7 stage list, `na` state) |
| HTTP: capabilities, stage, candidates, confirm, reference upload, export (SLDDRW/PDF/ZIP), reference payload on submit | `server/reverse_v7.py` (new), `server/reverse_api.py` |

**Rail order** (right, scrolls independently): Drawing template (selected + Change), Part selection, Reference drawing, Advanced settings (collapsed), Runtime and cost (collapsed, summary visible), Run controls, Export (bottom). Accordions are `<button aria-expanded aria-controls>`; Enter/Space work natively; toggling only flips `hidden`, so no re-render, no state loss, no accidental run. State is per workspace (sessionStorage). File inputs are created once and never re-created. Nothing opens the reference panel on a poll tick (spec 34 test 114); it opens when the user selects Match, or when a run is blocked on a reference.

**Reference drawing.** `Standard | Match reference` radiogroup (arrow keys). Match: `Auto-find / Upload PDF / Select saved source`, a one-line status (`1 of 3 matched · 1 need confirmation · 1 unmatched`), per-part rows (candidate select with project/run/date/pages/confidence/reasons, explicit **Confirm**, per-part **Upload PDF** override, per-part **Use Standard**, Reset). Run is blocked, with the reason, until every row is matched, confirmed, uploaded or explicitly Standard. No silent fallback: the backend `fallback_standard` flag is sent only when a row chose Standard. Provenance and extraction accordion shows what the selected finished part used (source kind, file, SHA-256 prefix, link, confidence, extraction cache hit/supplemented/fresh, OpenAI usage). Match is disabled with the reason when `GET /api/reverse/capabilities` says the backend lacks it.

Because a browser cannot give the server a path, Match mode first uploads the chosen parts once (`POST /stage`), then looks up candidates per part against those copies, and submits from the same stage (`POST /jobs` JSON `{stage_id, keys, reference}`); the stage is consumed by the job. The browser only ever names ids (`stage_id`, `p<n>`, `upload_id` = SHA-256, `artifact_id`); server paths and the OpenAI key never reach it. The server accepts an `artifact_id` only if it was offered for that part in that stage, and a candidate flagged `needs_confirmation` only after `POST /reference/confirm` (which calls `confirm_reference_link`, i.e. it persists the link in `<data>/reference/links.json`).

**Runtime and cost.** Two separate blocks: "Local CAD time (no token cost)" (estimate and measured runtime) and "OpenAI (reference extraction only)" (per-part measured `api_usage`, "others not recorded", never `$0` for unknown).

**Left viewer.** Beside the `3D Model (STL)` title: segmented `3D Model | Source PDF`. Source PDF shows the file the run used (`files.source_pdf`), labelled **Original** with provenance; the right viewer stays the generated PDF, labelled **Generated**. Disabled (`aria-disabled` + tooltip) for Standard, blocked, canceled, queued or missing-file parts; the generated PDF is never shown as the source. View state (mode, page, zoom) is kept per part/run; switching part resets both viewers and loads that part's own files. Optional synchronised page/zoom, offered only when both drawings have the same page count. Loading, error (with Retry) and empty states. Viewing creates no object URLs (asserted).

**Export.** At the bottom of the rail: `Download SLDDRW`, `Download PDF`, `Download both (ZIP)`, draft status chip, acknowledgement checkbox. Enabled only for artifacts the server says exist for the selected part, bound to job + part + the artifact size (`expect`), acknowledgement reset when the selection or artifacts change. Server (`GET /jobs/{job}/parts/{part}/export[/slddrw|pdf|zip]`): path resolved by `ReverseService.artifact_path`, containment and listed-artifact check, `application/pdf` / `application/octet-stream` / `application/zip` attachment, sanitised filename, content-length, `nosniff`, `X-Drawing-Status`; 404 missing / unknown part or job, 409 canceled, not finished, stale `expect`, or acknowledgement missing (unapproved drafts: verification not passed, review required/failed, open review, or verification not recorded). Never says "approved". ZIP is built from the two validated artifacts only and deleted after sending. Notifications use the existing toast system.

## 3. Tests (all against isolated servers and data dirs; ports 8251-8257, none is 8200; all stopped)

| Suite | Result |
|---|---|
| New `tests/e2e/tests/34-v7-reverse-reference.spec.ts` (`tests/e2e/run_v7_all.sh`) | **22 / 22 pass** |
| New `tests/server/test_v7_reverse.py` | 14 pass |
| `pytest tests/server` (all) | **150 pass** |
| New `tests/unit/referenceview.test.js` + updated `reverseview.test.js` | pass; `node --test`: 277 / 279, the 2 failures are the same two documented in the v6 report (`registry` status/source, `store` run/finalized) |
| E2E 25 / 26 / 29 / 30 / 32 / 33 | 11 / 5 / 3 / 13 (ran, not skipped) / 7 / 11 pass |
| E2E 31 (v5 reverse) | 14 / 14 pass **after updating it** (see below) |
| E2E 27 | 6 / 7: test 81 fails, **identically on a pristine base** (commit 4abb1d3 served separately) |
| E2E 28 | 3 / 4: test 86 is data dependent: passes on a fresh data dir and fails on later runs, **identically on the pristine base** (3 of 3 repeat runs failed there too) |

Spec 34 asserts computed boxes and real bytes: gap 8-16 px (actual 12) and no horizontal overflow over the size x zoom x sidebar matrix; viewers equal height and aligned; rail inside the row and Run/Export inside the rail; accordion roles, order and persistence; polling without reset (>= 2 polls observed, accordions, scroll, focus and typed text unchanged); reference rows for matched / ambiguous / unmatched, Confirm, explicit Standard, JSON payload (no paths); upload through the real route and real backend validation (non-PDF refused, real 2-page PDF accepted, id = SHA-256); real lookup for an unknown part ("No saved source found"); capability-missing and stage-failure paths; provenance for each seeded part; export enabled only for real artifacts and bound to the selection (flange, bracket with acknowledgement, plate not run, cover failed, canceled, running, PDF-only); downloaded PDF, SLDDRW and ZIP bytes equal the files on disk (SHA-256), filenames, request URLs name the selected part; refused downloads (stale, 409, 404, traversal, wrong job) show notifications and save nothing; Source PDF loads the original bytes (hash compared against the seeded source and against the generated PDF), painted canvas, pages/zoom/fit/pan, labels, provenance, return to 3D; unavailable-source reasons; per-part view state; sync on/off in both directions; error + Retry; N/A stages and verification block; radiogroup arrow keys, accessible names, visible focus, axe (no serious/critical), narrow drawer with Escape.

Seed (`tests/e2e/helpers/make_v7_fixture.py`, labelled in its docstring): `model.stl`, `drawing.pdf`, `drawing.slddrw` are **copies of a real SOLIDWORKS-generated run** found in `FINAL_UI/data/outputs/3d-to-2d` (originals only read; used only by this seed, never shipped; falls back to labelled stand-ins if absent). Source reference PDFs are hand-generated test PDFs ("ORIGINAL SOURCE <part>"). The `reference` / `verification` blocks are shaped like V7_CONTRACT section 4: they prove the UI's handling, not backend output.

### Existing tests changed (and why)
- `31-v5-reverse.spec.ts`: first run after the change had 4 failures from selectors that the redesign made ambiguous or moved (`.rv-pagelbl` and `canvas.rv-paper` now exist in both viewers; the template legend, the Generate/Upload template controls, the server-folder summary and the estimate text moved into accordions); stage counts changed from 8 to 10 (v7 vocabulary). Updated to the new structure; intent unchanged. (A 5th break, `#rv-3d .rv-vempty` matching twice, was fixed in the component by giving the PDF pane its own class, not in the test.)
- `tests/server/reverse_fixtures.py`, `test_v5_reverse.py`, `tests/unit/reverseview.test.js`: stage names/counts no longer hard-coded (the backend renamed its stages while this work was in progress).
- Also fixed (pre-existing, found on the way): `McA.dom.h` printed nested `[dt, dd]` arrays as `[object HTMLElement]` (visible in Results > Verification "PDF check" key/value blocks); it now flattens nested arrays.

## 4. Evidence (`docs/verification/v7/`)
`before-1280x720|1440x900|1920x1080.png` (the blank band), `after-flange-*.png`, `after-empty-queue-1440x900.png`, `after-reference-match-1440x900.png` (Match mode, ambiguous/unmatched rows), `after-source-pdf-1440x900.png` (Source PDF toggle), `after-export-pdf-only-1440x900.png` (export only where artifacts exist, Standard N/A stages), `after-narrow-rail-1000x800.png`, `gap-matrix.txt` (all 24 measurements). Screenshots are taken at zoom 100% with the browser's own viewport; zoom 80/125% is asserted by geometry, not by image (a screenshot drops a CDP device-metrics override).

## 5. Limitations and not tested
- **Not run end to end:** no real submit with a reference (needs the CAD worker, SOLIDWORKS and paid extraction, which this task may not touch). Specs intercept `POST /api/reverse/jobs` and assert the payload; the server-side translation and the fake-backend submit are covered by pytest. Real reference extraction, comparison, collision and round-trip checks are the backend agent's gates.
- Real candidate lookups were only exercised for the empty case (no saved source); the ambiguous / confirmed / auto-matched UI is driven by mocked `/reference/candidates` responses shaped like the contract.
- SLDDRW downloads are the file as the backend wrote it. Reopening it in SOLIDWORKS, checking its part link, and offering packaged model dependencies were not done (UI work may not touch SOLIDWORKS); the ZIP holds only the SLDDRW and the PDF and never replaces the user's part.
- Browser zoom is emulated with CDP device metrics, not real Ctrl +/-. At 1440x900 and 125% (720 px CSS height) the rail's floor of 320 px puts the Export row slightly below the fold until the page scrolls (the rail is sticky, so it stays reachable); the viewport check applies from 780 px CSS height.
- Match mode needs parts chosen in the browser (the server must hold copies it can look up); "Run a folder on the server" is Standard only and is disabled with a reason in Match mode. Staged copies are removed with their job, dropped on "Find again", or swept after 6 hours of server uptime; copies staged and abandoned before a server restart stay in `<data>/uploads/3d-to-2d/u_*` until the job/data is cleaned.
- Selecting a candidate that needs confirmation and pressing Confirm persists a link (`<data>/reference/links.json`) through `confirm_reference_link`; that is a lasting user decision, not a preview.
- A part blocked in preflight (`REFERENCE_BLOCKED`) shows the reason and the Reference badge in the queue; there is no "re-run in Standard" action (the backend retry does not take a reference); start a new run.
- Below 1100 px the rail remains the existing slide-over drawer (Setup button) rather than stacking under the viewers; the viewers and the queue do stack and nothing overflows horizontally.
- The queue table keeps its eight columns; the reference status is a line under the part name, not a ninth column.
- The backend was being edited in the same working tree while this was built (stage names moved to the v7 list); the UI reads `stage_order`, `stage_labels` and falls back to the legacy eight only when a part's records use legacy keys.
