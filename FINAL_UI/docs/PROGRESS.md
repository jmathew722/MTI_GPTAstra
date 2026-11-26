
## Steps 1-2

Step 1 (tokens) and step 2 (core and logic modules with unit tests) are done. Paths are relative to `web/`.

### Step 1: tokens
- `index.legacy.html` already existed as a copy of the old `index.html` (reference only).
- `static/design-tokens.css` retokened per ARCH section 7. New: `--accent*`, `--on-accent`, `--gold*`, `--on-gold`, `--ctl-h` (38px), `--scroll-thumb*`, `--model-*`, `--fs-h1`, radii 4/8/12px, `--fs-body` 14px. Every legacy token (`--blueprint*`, `--copper*`, `--teal*`, `--steel*`, `--on-copper`, and all names `photoapp/index.html` uses) stays defined as an alias. `.btn` height uses `--ctl-h`, `.btn.sm` is 30px, new `.btn.gold`, focus ring is 2px with 2px offset, scrollbars and `.console-c` use tokens. Drafting signatures (`--centerline-*`, `--ruler`) removed (unused by photoapp). Served OK at `/static/design-tokens.css`.

### Step 2: core and logic
- `static/js/core/`: `util.js`, `persist.js`, `store.js`, `api.js`. Load order in `index.html`: util, persist, store, api (store reads persisted ui at load; it calls `McA.stages` and `McA.runstate` only when a run action is dispatched).
- `static/js/logic/`: `stages.js`, `runstate.js`, `selectors.js`, `logparse.js`, `jsontree.js`, `csv.js`, `registry.js`.
- All use a UMD wrapper, so they load as classic scripts (attach to `window.McA`) and `require` in node.
- Marker strings were verified against `main.py` (`_run_views_folder`, demo brackets), `pipeline/batch.py` (`process_drawing_data`) and `server/app.py` (`[launch error]`, `[reader error]`, `[cancel requested by user]`, `[delivered outputs to]`). Endpoint shapes were checked against `app.py`.
- Notes: the `Exporting` marker is always printed, so it does not prove Verification ran (stage "work" markers are 8 and 9). After a failed part, `Exporting` and `Done` still print, so the failed stage is found from the highest work marker seen, not from the last marker.

### Tests
- `tests/unit/unit/*.test.js` (node:test, no dependencies) plus `tests/unit/fixtures/` (transcripts and CSV rows written from the real marker formats, and one outputs payload).
- Run from FINAL_UI: `node --test "tests/unit/*.test.js"` (Node 24 does not accept a bare directory argument). Also `cd tests/unit && npm test`.
- Result: 111 tests, 111 passing.

## Steps 3-5, 13 (app shell and layout)

Done: new `index.html` shell (`index.legacy.html` kept as the old copy), `static/css/{base,shell,workspace,pages}.css`, `static/js/core/router.js`, `ui/{icons,toast,dialog,sidebar,split,inspector,drawer}.js`, `pages/{home,workspace,projects,recent,help,settings}.js`, `main.js`. Placeholders (one-line comment) for files owned by others: `features/*.js`, `ui/tracker.js`, `ui/results.js`, `pages/resultsPage.js`, `css/results.css`.

Behavior: hash router (7 pages, title, aria-current, h1 focus after first load); sidebar 240/64 persisted at 1440+, overlay 800-1439, off-canvas below 800; Workspace header with real chips; static tracker markup (tracker.js owner drives `data-state`, a MutationObserver in `pages/workspace.js` injects the state icons); split canvas with pointer/keyboard splitter, narrow tabs under 1100, maximize and fullscreen; inspector accordion (docked at 1440+, moved into drawer Tools below); drawer toggle/resize/modes with header summary from `run` and `outputs`; Projects, Recent, Help, Settings built from store state with empty states; dialog and toast; main.js boot (session reuse via `mca.session`, status, history, parts, selection restore, 30 s status refresh).

Action contracts the feature agents must register with `McA.store.register` (UI dispatches them; if absent the UI toasts "not available in this build", never a silent no-op):
- `intake/files` `{files: File[], source: 'home'|'workspace'}`, `intake/folder` `{files: File[], source}` (folder upload, `webkitRelativePath`).
- `run/demo` `{sample}`, `batch/request` (UI asks; run.js owns the confirm dialog).
- Existing reducers used: `ui/set`, `ui/inspectorSection`, `parts/select`, `intake/reset`, `route/set`, `server/status`, `history/loaded`, `parts/loaded`.

Slots (all disabled with a visible reason until their owner enables them): intake `#part-name #intake-file #batch-folder #open-cropper-btn #mark-regions-btn #pull-crops-inline-btn #orient-gallery #req-warn #save-part-btn #part-notes #save-notes-btn`; run `#run-btn #cancel-btn #run-reason #run-all-btn #demo-btn #demo-sample #no-cache #feedback-text #open-editor-btn #rerun-feedback-btn`; export `#exp-sldprt #exp-stl #exp-vba #export-btn #zip-btn #delivered`; viewers `#ov-box #ov-img #ov-empty #vp-2d-state #vp-2d-fmt #vp-2d-file #vp-2d-pages #stl-canvas-wrap #stl-empty #vp-3d-state #vp-3d-view` and the toolbar buttons `[data-act=crop|mark|zoom-in|zoom-out|fit|reset]` (disabled, owner removes `disabled`); tracker `.trk-step[data-state] #trk-stage #trk-caption #trk-batch #trk-pct`; drawer Results `.dr-secs .dr-pane`; results page mount `#res-root`; focus overlay `#focus` (crop `#photoapp`, mark `#mark-view`).

Notes: `persist` must load before `store` (store reads it at load; fixed in the script order). Store persistence is debounced 150 ms, so a reload within that window loses the last layout change. Screenshots: `docs/screenshots/shell-<viewport>.png` (1920x1080, 1440x900, 1366x768, 1024x768, 390x844). No horizontal overflow at any of them; no console errors. Results page has one h1 supplied by the shell; the results owner should not add a second.

## Steps 6-8: viewers, intake, cropper overlay, markup

Files (under `web/static/`): `js/features/{viewer2d,viewer3d,intake,cropper,markup}.js`, new `css/features.css` (linked from `index.html`).

- **viewer2d**: source from `selectors.drawingSource`; pan (drag), cursor-centred wheel zoom, fit (dblclick / `0` / button), arrow keys pan, `+`/`-` zoom; page strip for multi-page drafts; Overview / Marked switch when `has_marked`; error state with Retry; empty state with Upload. File, state and format chips sit in the viewport corner (the panel header is too narrow beside the inspector).
- **viewer3d**: only `model.stl` bytes; mesh swapped after a successful load; a failed load keeps the same part's mesh and shows an error bar with Retry; changing part clears the mesh first; chips Generated / Pre-validated (CadQuery) / Previous run; fit, reset, view presets (animated unless reduced motion), keyboard orbit; colors from CSS tokens. It also fetches `partOutputs` for the selected part when nothing else has (`outputs/loading|loaded|error`, stale-ctx guarded), and refetches shortly after a run reaches a terminal state.
- **intake**: `intake/files` and `intake/folder` handlers; PDF (12 pages, 200 DPI), images, CAD convert with sheet-picker dialog, eDrawings static-preview label; Add / New / Cancel dialog for an existing draft; gallery (view type, rotate, remove, duplicate badge); validation; save part with duplicate, unassigned and replace-existing dialogs; must-meet notes (new part and update saved part); parts folder upload. Never starts a run.
- **cropper**: focus overlay (iframe created once, never reloaded), `hookCadIntake`, `collect`, `sendImage`, `cad-open`/`src-open` listener with source check, echo drop, "Load this drawing into the cropper" (explicit button), Escape and Shift+Escape (inside the frame), `inert` on the page behind.
- **markup**: regions, datums, origin with lock, color groups, roles, region list editing, 600 ms autosave to `POST .../regions`, marked view upload, Add to Part Setup, Clear (confirm dialog). Regions drawn on a draft move to the part on save. Fix over legacy: regions key to the draft whenever the markup image comes from the draft (legacy keyed to the selected part).
- Verified in Chromium (Playwright, scratch dir): Home upload to workspace, view assignment, save, Projects list and reload persistence, PDF pages, Add/New/Cancel dialog, unsupported format toast, replace dialog, DXF convert, cropper crop + queue + pull, mark draw + POST regions + origin lock + marked view served, parts folder upload, notes update, STL load / view presets / failure keeps mesh. No console errors (headless WebGL ReadPixels driver warnings excluded).
- Gaps: region boxes can only be drawn with a pointer (list editing is keyboard accessible); no real SolidWorks STL available to test, a hand-made cube STL was used and removed; viewer3d outputs fetch may duplicate run.js's own fetch (harmless, same ctx guard).

## Steps 9-12 (run, tracker, results, corrections, export, batch)

Files: `static/js/features/run.js`, `ui/tracker.js`, `ui/results.js`, `pages/resultsPage.js`, `css/results.css`; `index.html` got one `#cancel-mirror-btn` in Pipeline Actions.
- run.js: launch guard, SSE monitor with replay dedupe, 1.2 s outputs poll (store update only when a payload signature changes), `finalizeRun` once per id (summary CSV, then console `N/M READY` fallback), reconnect from `mca.activeRun`, cancel, demo runs (own `outputs.ctx {kind:'run'}`, never refreshes parts/history), outputs loader on `outputs.ctx` change, batch Run All with confirm dialog and resume offer (`mca.batch`), Corrections (draft in `mca.corr.*`, kept on failed launch, cleared after an id is returned), Export (real file URLs, 300 ms apart, zip only for a tracked run). Registered actions: `run/launch`, `run/demo`, `run/cancel`, `batch/request|resume|dismiss`, `outputs/load`, `history/load`.
- tracker.js: five states with icon plus text, `aria-current`, sub-step tooltips, ring percent only from `stages.percent`, indeterminate otherwise, announcements per stage change, disabled reasons via `aria-describedby`, batch aggregate and resume.
- results.js: all 13 registry sections with loading, absent, error, present states; lossless JSON tree, search, raw toggle, copy, download; flags filters with the disabled G3 learning-loop button; windowed incremental console (5000 lines); events; cost labeled Measured vs Estimated; files with real links; overview three blocks. Drawer Results mode and Results page share it.
- Tested with Playwright (scratch dir): demo run reaches Build Plan, Generation and Verification skipped, percent 100; reload mid-run reattaches with one POST; cancel gives Cancelled; run button shows the No ANTHROPIC_API_KEY reason; a temporary fixture part (removed) exercised all sections, downloads and export. No console errors.
- Limits: live runs and Run All could not be run (no API key); the batch loop is code-reviewed only. History was empty, so a seeded output copy served as "real" data.

## Steps 14-16: verification, accessibility, polish, hardening (final)

- **e2e** (`tests/e2e/`, Playwright + axe, chromium): 18 tests pass (ARCH 14.2 scenarios 1-16, plus 17 keyboard-only Workspace walkthrough, 18 honesty rules, 19 stale-response guard; screenshot capture is opt-in via `SHOTS=1`). Unit: 111 of 111 pass. Global teardown removes every session and demo-run folder the tests create. Adaptations: scenario 12 asserts Run All Parts is gated with a visible reason when the server has no key (the confirm dialog is opened and cancelled only when `live: true`); scenarios 6-8 use Demo runs; scenario 14 only cancels the confirm dialog.
- **Defects found and fixed**
  1. Skip link navigated the hash router to an unknown hash and sent the user Home (`main.js`: click handler focuses `#main`).
  2. axe color-contrast: inactive deliverable chips used `--ink-4`; now `--ink-3` (`workspace.css`).
  3. axe link-in-text-block: Results breadcrumb link had no underline (`results.css`).
  4. Tracker stage caption was gold when idle or complete; gold now only while a stage is running.
  5. Drawing panel file/state/format chips were clipped ("Save", "Multipl"); the chip row now wraps and does not shrink (`features.css`).
  6. Drawer header wrapped and orphaned its title, tab and link at 1440; now a single row, runtime label and "Open full page" hidden below 1600 px.
  7. "Update specs for <part>" button text overflowed the inspector; now wraps.
  8. Color literals: `rgba(229,72,77,...)` in features.css moved to new `--err-wash` and `--err-line` tokens; hex fallbacks in `viewer3d.js` and `markup.js` removed (colors read from tokens with `getComputedStyle`). Remaining literals: `REGION_PALETTE` and the `hexToRgba` helper in `markup.js` (documented exception D25); the grep also matches `#acc-actions` in a selector (false positive).
- **Hardening**: XSS payloads in notes, a region value and a part name render as text and run nothing (scenario 13); the server sanitizes part names; stale outputs reply cannot overwrite the current selection (scenario 19); no console errors or warnings on any route (scenarios 1, 2, 4, 13, 15).
- **Screenshots**: `docs/screenshots/final-{home,workspace}-{1920x1080,1440x900,1366x768,1024x768,390x844}.png` and `final-workspace-demo-1440x900.png`.
- **Docs**: README.md, docs/QA_RESULTS.md written. `index.legacy.html` removed after the inventory walk.
- **Remaining**: live (paid) extraction and SolidWorks builds are not verified here (no key, no SolidWorks); a part with a real STL was not available, so the 3D viewer with a real model is covered only by the earlier hand-made STL check; the e2e drawing fixture is a synthetic rectangle with circles.

## Calibration pass (visual calibration to mcagent-workspace-approved.png)

Done: sidebar as a floating rounded card (brand 23 px, gold "SolidWorks Pipeline" in the subtitle, deep-violet New Project, violet active nav); header with 50 px folder icon, 22 px title and three 2-line capsules ("API Status"); tracker band with one continuous track, "Run Pipeline" heading, "Stage N of 5" plus caption on the right and the percent meter only when the backend gives a number; panel headers 57 px with the file and state chips moved into the header (they shrink or wrap by container width); drawing on a white sheet inset 12 px; 3D stage dark navy (transparent WebGL canvas over a CSS gradient), metallic material with a generated reflection environment, real XYZ triad (follows the camera), floating toolbar (reset view, pan toggle, zoom in/out, fit, wireframe toggle) that acts on the model and is disabled with a reason when no model is loaded; inspector with all four accordions open, Run Pipeline moved into Pipeline Actions (still the only .btn.gold), Views/specs and run options in disclosures; Pipeline Results strip 62 px closed, end chevron, Results/Tools tabs and "Open full page" only when open (Tools tab stays on narrow screens). Inspector docks from 1250 px (was 1440); below that Tools lives in the drawer and a "Tools" button in the tracker opens it.
Tests: unit store test and two e2e tests updated for intentional changes (accordions default open, 1250 breakpoint, specs disclosure). Added opt-in CAL=1 specs: calibration, compare, viewer3d-fixture (synthetic mesh written as prevalidation.stl into a throwaway part; labelled Pre-validated, removed by teardown).

Remaining differences from the reference (honest):
- Reference gold chips ("Uploaded", "Generated") and gold icons are not used: gold stays reserved for Run Pipeline and the current stage (brief and test 18). Status chips are neutral or green.
- No real SolidWorks STL available, so the metallic part in the reference could not be matched with real output; the fixture mesh is hand-made.
- Inspector scrolls: real Part Setup, reasons and demo/option controls are taller than the reference's compact cards; Corrections and Export are below the fold at 1672x941.
- No "Parts Folder" path field (the app uploads a folder instead); no Inter font bundled (none licensed on disk), system stack kept.
- Split defaults to 50/50 (brief says reset 50/50); reference is about 55/45. At 50/50 the 2D header drops the format chip into a tooltip, and wraps chips to a second row under 500 px panel width.
- Layout fills the viewport height, so the main row is taller than the reference (about 680 vs 623 px).
- Narrow: one viewer with a Drawing/3D switch below 1100 px (EXACT_DESIGN says 600-899); drawer header hides flags and runtime below 900 px.


## FINAL_UI consolidation, Home redesign, final palette

Structure: `server/` (app.py = the original FastAPI app with ONE change: the pipeline repo comes from `MCAGENT_REPO`; data dirs `parts/ runs/ UI_Output/ .convert_cache conversion_log.jsonl` moved to `MCAGENT_DATA`, default `FINAL_UI/data/`; static mounts point at `web/`), `web/`, `tests/{unit,e2e,fixtures}`, `docs/`, launchers `run.sh / run.ps1 / run.bat`. Note: `UI_Output/` used to be written inside the repo; it now lives in the data dir (the repo is untouched). The pdf.js copies inside `photoapp/` were dropped; the app serves them from `/pdf.min.js` and `/pdf.worker.min.js` (web root).

Home: new minimal centered column (max 640 px). Dropzone = one drawing (several files = views of one part, as before). Upload parts: each file becomes its own part with its first page/image as Front (staged list with remove; main button `Create N 3D models` saves them and opens Projects; never starts a run). Upload folder: grouping in `static/js/logic/batchgroup.js` (subfolders = parts; loose files = one part each when subfolders exist; a folder with no subfolders = one part, the server grouping), uploaded through the existing `upload-batch` endpoint. Recent section hidden when empty. Formats label lists PDF, PNG, JPG, DWG, DXF (the file input also still accepts WEBP/BMP/TIFF/eDrawings static previews).

Palette: `--ok/--ok-text` #7EDB84, `--warn` #E3B24A, badge washes updated; gold and severity ladder unchanged. Workspace already matched the approved reference (see calibration above); screenshots re-shot and inspected at 1672x941, 1440x900, 1024x768, 390x844 (`docs/screenshots/final-*.png`).

Verification: unit 116 pass (5 new, batchgroup). Playwright 26 pass, 4 opt-in specs skipped (calibration, compare, screenshots, viewer3d), incl. new 20-home spec (centered boxes at 1440 and 390, copy, Upload parts, Upload folder, no demo data in Projects, invalid repo errors, launcher with explicit --repo). axe: no serious/critical on 7 routes (one unreproduced flake in a full run, passed on 3 reruns). Launcher verified with the Meta_Nebula `pipeline_app` repo and auto-detect (picked `MTI_Astra_UI/2D-3D-CAD-Test-Generation`).

Finding: that auto-detected newer repo's `main.py` has no `--no-export` flag, which `app.py` passes, so demos/runs fail on it; run.sh/run.ps1 now print a warning. Fixing it needs a one-flag change in the UI (drop the flag) or the repo; left as is ("pipeline unchanged").

Remaining gaps: no live paid run or SolidWorks build exercised; Upload parts for multi-page PDFs keeps page 1 only; CAD files with several sheets prompt for a sheet; G1-G17 integration gaps unchanged (README).

## 2026-11-18: four-stage program (Stages 1-3 in the UI)

Details and evidence: `docs/test-reports/2026-11-18-stage{1,2,3}-gate-report.md` (repo root). New modules: `server/telemetry.py`,
`server/costs.py`, `server/flags.py`; `web/static/js/ui/cost-key.js`, `logic/drawersize.js`, `logic/flagview.js`,
`features/engineering-flags.js`. New tests: `tests/server/`, `tests/unit/{costkey,drawersize,flagview,telemetry_stages}.test.js`,
`tests/e2e/tests/21-stage2.spec.ts`, `22-stage3-flags.spec.ts` (these two need `STAGE2_OUT` and a server started with
`MCAGENT_FINAL_OUTPUTS=$STAGE2_OUT`). Pre-existing failures, unchanged: 3 unit tests (missing `tests/fixtures/part_full.log`) and 13
Playwright tests (stale after the rebrand), identical on the pre-change commit.

## 2026-11-18: automatic Engineering Markup (Stage 3 fix, branch `Improvements_2`)

Report and evidence: `docs/test-reports/2026-11-18-stage3-markup-gate-report.md`, `docs/test-reports/stage3-markup-evidence/`.
Post-run, pipeline-generated marked PDF (`<part>_engineering_markup.pdf`, `engineering_markup.json`, `engineering_markup_pages/`),
separate from the human pre-run `full_marked_view.jpg`. New: `server/flags.py` `load_markup`, three `/engineering-markup*` endpoints,
`web/static/js/logic/markupview.js`, an `Engineering Markup` source in `features/viewer2d.js` (auto-selected, page strip, clickable
regions, `focusIssue`), Results card links in `features/engineering-flags.js`. Tests: `tests/server/test_app_markup.py`,
`tests/unit/markupview.test.js`, `tests/e2e/tests/23-engineering-markup.spec.ts` (needs `STAGE2_OUT`; fixture via
`make_flags_fixture.py --markup main|clean|fail`). The 3 unit and 13 Playwright pre-existing failures are unchanged.

## 2026-11-19: Record Pipeline Run (SolidWorks build recording)

Spec: `docs/superpowers/specs/2026-11-19-solidworks-recording-design.md`. New: `web/static/js/logic/recordingview.js` (pure), `features/recording.js`
(results section + checkbox state), `Run options -> Record Pipeline Run` (`#record-run`, `#record-hint`), `api.recording*URL`, `api.runPart({record})`,
registry section `recording` (Build & Verification, after Model check), `server/flags.py` `load_recording`, `GET /api/recording/capability`,
`GET /api/parts/{s}/{p}/recording[.video|-poster.jpg]`, `record` form field on `/api/run-part`. The box is disabled with the reason when recording
is unavailable, is off by default and not remembered. Tests: `tests/server/test_app_recording.py`, `tests/unit/recordingview.test.js`,
`tests/e2e/tests/24-solidworks-recording.spec.ts` (needs `STAGE2_OUT`; fixture `helpers/make_recording_fixture.py`).

## 2026-11-25: v4 (branch `Improvementsv4`)

Four areas, all verified with real browser tests (no paid calls, no SolidWorks): (1) Run All Parts / folder upload accepts PDF, JPG, JPEG, PNG,
mixed and uppercase, with content checks, page counts, a skipped-file summary, a preflight estimate and Retry failed; (2) a Scoring sidebar tab
(overview, searchable part results, methodology, labelled worked example, part detail, append-only history) over the existing `bench.score`;
(3) Projects shows real PDF/image previews and is ordered newest activity first with local timestamps; (4) the Run Pipeline section shows
estimated time and cost, live elapsed/remaining/cost, and persisted actuals. New: `server/estimates.py`, `server/scoring_hub.py`,
`web/static/js/logic/{folderplan,estimateview,projectorder,scoringview}.js`, `features/estimate.js`, `pages/scoring.js`.

### 2026-11-25 (later): Extraction-to-Model Fidelity scoring

Replaced the key-dependent Scoring tab headline with a rubric that works for every built part: six categories out of 100 (build integrity, overall
size, feature coverage, hole and bore accuracy, placement and patterns, extraction reliability), colour bands with a word and glyph per band, critical
gate, and an issues list by severity. New: `bench/fidelity.py` + `fidelity_config.yaml` (22 tests on real CadQuery meshes), server hub/endpoints
(append-only history, pipeline-written `fidelity_score.json` ingested once), `pages/scoring.js` rewrite, band tokens in `design-tokens.css`.
It immediately found real artifact problems: several `FINAL_OUTPUTs` folders hold an STL that is not the part's own mesh (for example A040501E).

### 2026-11-25 (later still): Build Plan fix and colour coding

Root cause of the empty Build Plan: the viewer only knew the v1 `steps` plan and every IR build writes `{dims, plan:{features}}`. Fixed with `logic/planview.js`
and an IR renderer (kind chips, SolidWorks status per operation, resolved numbers, flags, dimensions). Also fixed the run list's Plan presence check
(`plan.json`). Added section health tones (`logic/resulttone.js`) to Pipeline Results and more colour to the Scoring tab (row accents, item tints, severity
code chips, category accents). Tests: planview 8, resulttone 6, browser `26-v4-color-and-build-plan` 5.

### 2026-11-25 (later): standardized grading spectrum

Added `logic/grade.js` + `--grade-*` tokens and moved the Scoring tab, Projects (badge + Score column), a new Workspace header "Fidelity score" chip and Pipeline Results (fidelity section, graded
macro-readiness style metrics) onto it. Fixed thresholds, no rounding up, neutral grey for missing, Poor has no fill (AA). Also serialised server-side PyMuPDF calls (crash under parallel PDF requests).
