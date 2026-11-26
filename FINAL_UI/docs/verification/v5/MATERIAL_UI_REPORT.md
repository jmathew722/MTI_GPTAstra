# Phase 1 material UI: verification report (2026-11-25)

All commands were run from `FINAL_UI/` unless stated. The e2e server was a private one on port 8211 (never 8200) with `MCAGENT_DATA` and `MCAGENT_FINAL_OUTPUTS` pointing at temp folders, so no real output was read or written. No SolidWorks and no paid call was made.

## What was built

| Area | Files |
|---|---|
| Server | `server/materials_api.py` (new, installed by one line in `server/app.py`; `SOLIDFLOW_MATERIAL_SETTINGS` is added to every pipeline subprocess env in `_start_run`) |
| Pure rules | `web/static/js/logic/materialview.js` |
| UI | `web/static/js/features/materials.js`, `web/index.html` (library control, legend), `web/static/css/features.css`, `core/api.js`, `core/persist.js`, `logic/registry.js`, `logic/resulttone.js`, `ui/results.js`, `pages/projects.js`, `pages/recent.js`, `features/run.js`, `features/viewer3d.js`, `main.js` |
| Tests | `tests/server/test_v5_materials.py`, `tests/unit/materialview.test.js`, `tests/e2e/tests/30-v5-materials.spec.ts`, `tests/e2e/helpers/materials.ts`, `tests/unit/registry.test.js` (17 -> 18 sections) |

Design choices

- Appearance guard: the server hashes the STL it would serve (sha256, cached by path/mtime/size) and `GET /api/parts/{s}/{p}/appearance` returns the sidecar plus `stl_matches` and `viewer_apply` (verified AND same file). The viewer paints a colour only when `viewer_apply` is true; the colour string is regex-checked and metalness/roughness clamped. Part switch, a new STL load and a part with no STL all reset to the default look immediately.
- Routes are added with `app.router.routes.append` (not `include_router`) because the installed FastAPI wraps included routers lazily and an existing test that lists `app.routes` broke.
- Material data is not in `GET .../outputs`; the Material section reads `GET .../material` (cached in `McA.materials`). Absolute server paths inside pipeline JSON are reduced to file names; `<data>`, `<repo>`, `<outputs>`, `<home>` are scrubbed from error text.
- A refresh with no saved extraction reuses the earlier result's own drawing reading; with neither it answers 409 instead of inventing "not specified". (Found when the first e2e run showed a refresh erasing a verified result.)

## Results (real runs)

| Command | Result |
|---|---|
| `python -m pytest tests/server -q` (PYTHONUTF8=1) | 112 passed (15 new in `test_v5_materials.py`) |
| `node --test tests/unit/*.test.js` | 241 passed, 3 failed. The 3 failures (`logparse` events, `registry` status over a payload, `stages` run/finalized) fail identically on the tree before my changes (verified with the changes stashed). 12 new `materialview` tests pass |
| `npx playwright test tests/30-v5-materials.spec.ts` (BASE_URL=http://127.0.0.1:8211, MCAGENT_FINAL_OUTPUTS and MCAGENT_DATA set) | 13 passed |
| `STAGE2_OUT=... npx playwright test tests/27-... 28-... 29-v4-layout-audit` | 14 passed (the layout audit now also crawls the new Material section) |
| `python -m pytest tests/test_materials.py` in `2D-3D-CAD-Test-Generation` | 59 passed |
| Older e2e files `01-05`, `09-11`, `15-16`, `17`, `18`, `19` | 16 passed, 10 failed. The failures are stale tests, not caused by this work: they expect the old Home heading "What would you like to create" (the page now says "Your vision, Our blueprint") and `#orient-gallery select.oselect`, which no longer exists. Full output: `e2e-run.txt` |

Covered by `30-v5-materials`: folder control after Upload folder in DOM order and on screen; catalog preview (search, price basis, Escape, focus return); folder upload, rejected count, persistence across reload, refresh, demo fallback, user files untouched; bad path and empty folder errors; workspace card for verified / not specified / not evaluated; Material section content, tone and no absolute path leak; ambiguous, unpriced and legacy states; override flow (reason required, label, who/when, clear); refresh without SolidWorks; Projects and Recent columns and totals line (unknown never zero); viewer legend, Default grey toggle, part-switch and replaced-STL guard; axe serious/critical clean and the layout audit at 1920, 1440, 1366, 1100 and 390 wide with the sidebar open and collapsed.

Screenshots: this folder (`results-material-*`, `part-setup-library-*`, `catalog-preview-*`, `viewer-*`, `projects-material-*`, `workspace-material-*`).

## NOT RUN / limits

- Run All Parts dialog (`#run-mat-line`, "Change material library"): the test server has no API key, so the dialog does not open there. The test records a note and returns; the wording is covered by the `runCatalogLine` unit test. NOT RUN live.
- Real SolidWorks build with the new settings file: NOT RUN (forbidden). The env var is passed in `_start_run`; the other pipeline launch paths in `app.py` all go through `_start_run`.
- The installed SolidWorks library catalog preview (`source=standard`) is exercised only for its 404 when absent in pytest; on the dev machine the endpoint returned `standard_available: true` but its table was not opened in a browser. NOT RUN.
- The full older e2e suite was not run to completion (stale tests above).
