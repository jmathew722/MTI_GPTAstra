# Implementation report: Solid Flow v5 (material upgrade + 3D -> 2D drawing pipeline)

Branch `ImprovementsV5`. Environment: Windows 11, SOLIDWORKS **2025 SP5 (33.5.0) Student Edition**, Python 3.12, Node, Playwright. Written 2026-11-26.
Phase 1 detail: `PHASE_1_REPORT.md`. API proof: `api_validation.md`. Dependencies and licenses: `DEPENDENCY_REGISTER.md`. Test day: `docs/test-reports/2026-11-25-v5-report.md`.

> **Every generated drawing is PRELIMINARY / FOR REVIEW.** Software QA is not engineering approval. Tolerances, surface finish, thread specifications, datum
> scheme / GD&T and any manufacturing intent that the part geometry cannot supply are never invented: they are `review_required` items and read `NOT SPECIFIED`.

## 1. What exists now

### Phase 1 (2D -> 3D materials)
`pipeline/materials/{extraction,catalog,resolver,costing,native,runner}.py`, server `FINAL_UI/server/materials_api.py`, UI `features/materials.js` + `logic/materialview.js`
(library folder control directly below *Upload folder*, Material results section, viewer appearance guard, Projects / Recent columns, batch totals).

### Phase 2 (3D -> 2D)
| Area | Files | Evidence |
|---|---|---|
| Safety, durable job state (cancel flag, locked atomic IO), serialized CAD queue, watchdog, lazy CAD connect, CLI | `reverse/{safety,state,jobs,cli}.py` | unit + live |
| CAD worker (session, silent read-only open of a hashed working copy, STL export + validation, stale-document sweep) | `reverse/worker.py` | live |
| B-rep inventory (holes, stacks, counterbores, rectangular grids, bolt circles, bosses, tori, cones) | `reverse/inventory.py` | live |
| View / sheet planner (front choice, standard scale, third / first angle, padded layout, scaled iso and extra views) | `reverse/planner.py` | live |
| Native associative drawing, black layer, per-view scale, SLDDRW + all-sheets vector PDF | `reverse/drawing.py` | live |
| Native section views for blind / counterbored holes with their own verified dimensions | `reverse/sections.py`, `reverse/section_views.py` | live |
| Feature-aware dimensioning, coverage ledger, read-back verification, layout repair | `reverse/dimension.py`, `reverse/qa.py` | live |
| Native default templates `.drwdot` + `.slddrt` (ANSI B default, ANSI C, metric A3) | `reverse/template_gen.py`, `config/drawing_templates/` | live |
| Service, template catalog, audited review workflow | `reverse/{service,templates}.py` | unit + live |
| HTTP API + `3D -> 2D` page (reverse jobs also appear in Projects / Recent) | `FINAL_UI/server/reverse_api.py`, `web/static/js/pages/reverse.js`, `css/reverse.css` | unit + browser + live HTTP |

## 2. Gate status (test plan `06_TEST_AND_ACCEPTANCE.md`)
| Gate | Result |
|---|---|
| A Static / unit | **Done.** `tests/test_materials.py` 59, `tests/test_reverse.py` 58 (+1 skipped: symlinks not permitted), full Python suite 1448 passed / 67 skipped / 0 failed. |
| B Installed API | **Done.** `api_validation.md`: revision `33.5.0` recorded, every member proven by a live call, gotchas listed. No mock was used as evidence of live CAD. |
| C Integration | **Done for the generated fixture set** (section 3); **not done** for customer-supplied parts or engineer-prepared reference drawings. |
| D Visual | Sheets rasterised and inspected (`docs/phase2-evidence/`); UI screenshots at 1280 / 1440 / 1920 in `FINAL_UI/docs/verification/v5/`. Layout audit (accent clearance, truncated labels, clipped text, sideways scroll) passes on every page including the new Material section, at 1920 / 1440 / 1366 / 1100 / 800 / 390 with the sidebar open and collapsed. |
| E Regression | Existing Python suite passes; node unit 259 pass / 3 fail (identical to the pre-v5 baseline); server tests 136+ pass; browser `27`, `28`, `29`, `30`, `31` pass (see section 6). Older browser files `01-05`, `15-17`, `20` fail on stale Home copy and a Workspace upload helper selector that predate this work; they were not fixed. |
| F Engineering review | **NOT RUN.** Needs an authorized engineer; outputs stay `review_required`. |

## 3. Live evidence
* `tools/material_e2e.py` (Phase 1: six scenarios + reopen proof + injected failure): `docs/phase1-evidence/`.
* `python -m reverse.cli fixtures` over **18 generated parts** (plates, flanges, revolves, radial holes, patterns, tapped Hole Wizard holes): `docs/phase2-evidence/batch18/`.
  18/18 produced `model.stl`, `drawing.slddrw`, `drawing.pdf`, inventory, plan, coverage ledger, QA, manifest and previews; **0 crashes, 0 dimension value mismatches, 0 clipped
  text**; all `review_required` as designed; median coverage 73.7 % (best 89.7 %, worst 8.3 % on a 1.95 m revolved shaft); median 105 s per part (sections and the drawing
  reopen proof dominate: drawing 30-70 s, verification 30-60 s).
* `tools/reverse_gates.py` (awkward cases on real SOLIDWORKS): `docs/phase2-evidence/gates/gates.md`: unicode + spaces, duplicate basenames, corrupt file, assembly, batch with a
  failed item, unwritable output, cancellation, metric A3, first angle, source hash all pass; the "part already open by the user" case failed once (a same-title working copy could
  not be opened), was fixed (unique working-copy title + warning on unsaved edits) and re-verified separately.
* `tools/reverse_http_e2e.py`: a **real** uvicorn server, real multipart upload, template generated through the API, real CAD worker thread, real SOLIDWORKS, artifacts downloaded
  through the artifact endpoint with matching byte counts, traversal refused, no server paths in responses: 14/14 steps (`docs/phase2-evidence/http_e2e/`). This run found and fixed a real bug
  (a template task arriving before any job ran on an unconnected CAD session).
* `docs/solidflow-upgrades/LIVE_PDF_RUN.md`: original PDF -> live OpenAI extraction (0.371 USD, evidence + bounding box) -> company-library match -> native assignment verified after reopen -> mass and cost -> regenerated drawing with MATERIAL in the title block -> 18/18 original dimensions found. Found and fixed a stale extraction cache.
* `docs/phase2-evidence/roundtrip/ROUNDTRIP_REPORT.md`: original-vs-regenerated comparison over the 18-part batch (53 % of 631 original dimensions found by value, 45 % strictly), with discrepancies listed per part.
* Hand-checked sheets: `docs/phase2-evidence/fixture_probe/sheet-1.png`, `batch18/*/sheet-1.png`.

## 4. UI
`FINAL_UI/docs/verification/v5/MATERIAL_UI_REPORT.md` and `REVERSE_UI_REPORT.md` list the commands run and results. Both UI features were built against fixture data first and then
exercised end to end against the real CAD worker (section 3). Reproducible regression: `FINAL_UI/tests/e2e/run_v5_all.sh` (isolated throwaway server, never the live port).

## 5. Not implemented / known limits (honest list)
* **Revolved bosses / shafts, fillet radii and chamfers** are listed as `review_required`, not dimensioned automatically (the 1.95 m shaft `SB11780` shows this: 8 % coverage).
* **Radial holes on curved faces:** the visible edge is not a circle, so no callout is generated (`HOLE_EDGE_NOT_FOUND`, high severity).
* **Sections:** one section per hole row, aligned or moved to free space at a smaller labelled scale; when the sheet is too full the section becomes a `SECTION_NO_ROOM` issue (12 in the batch).
  No detail or auxiliary views are generated. No second sheet is created.
* **Layout:** a deterministic repair pass removes clipping and most collisions, but 17 `TEXT_OVERLAPS` remain across the batch (reported, never hidden); a very full sheet still needs a human to tidy it.
* **Hole Wizard callouts** keep SOLIDWORKS' own text; a pattern-count mismatch is flagged `CALLOUT_COUNT_CHECK` for review.
* **Multibody / freeform** parts are routed to review. Material per body is not mapped (Phase 1).
* **Speed:** about 1-4 minutes per part with sections (SOLIDWORKS regenerates every view); the UI estimate comes from real history.
* A hung COM call cannot be force-killed without killing a SOLIDWORKS session that may be the user's; the watchdog flags the part and requests cancellation.
* Student Edition adds a license line to every PDF; this is not part of the pipeline.
* **Live PDF run done for one drawing** (`LIVE_PDF_RUN.md`); other callout types (conflicting, unreadable, multi-page) are covered by schema / unit tests only. **NOT RUN:** comparison against engineer-prepared reference drawings; the engineering review gate.
* **NOT RUN:** a browser drive of the UI against a real job (the browser specs use fixture jobs; the HTTP end-to-end uses the real worker but no browser).

## 6. Exact commands
```powershell
# UI (latest)
powershell -ExecutionPolicy Bypass -File C:\Users\joeka\OneDrive\Desktop\UI_Astra\FINAL_UI\start-ui.ps1 "#/reverse"

# from 2D-3D-CAD-Test-Generation\  (set PYTHONUTF8=1)
python -m pytest tests/test_materials.py tests/test_reverse.py -q
python tools/material_e2e.py --part A001151E --out ..\docs\phase1-evidence\e2e
python -m reverse.cli template --out config/drawing_templates --variant solidflow-ansi-b
python -m reverse.cli fixtures --src <folder of .SLDPRT> --out <dir> --template <abs path to .DRWDOT> --own-sheet-format
python tools/reverse_gates.py --part <a .SLDPRT with holes> --out <scratch dir>
python tools/reverse_http_e2e.py --part <a .SLDPRT> --out <scratch dir> --port 8213

# browser regression (isolated server), from FINAL_UI\tests\e2e
bash run_v5_all.sh 8214
```
