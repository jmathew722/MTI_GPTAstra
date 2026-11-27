# Solid Flow v8 backend report: drawing replication + cost/runtime accounting

Branch `ImprovementsV7`. Contract for the UI agent: `V8_CONTRACT.md`. Evidence: `v8-evidence/` (13 MB, every file < 5 MB).
SOLIDWORKS 2025 SP5 (33.5.0), Student/Educational licence (every exported PDF carries the licence watermark; detected and excluded from collisions, not hidden).
Honest summary: **no part reaches `Verified`.** All four real parts end `Needs Review` with measured reasons. View centres, sheet scale, title-block scale, sheet size, notes (title block
and general notes) and sheet geometry now match the source by measurement; dimension placement, GD&T glyphs, section/detail views and per-page dimensions do not.

## Root causes found and fixed (live, SOLIDWORKS 2025)
| Defect | Root cause (measured) | Fix |
|---|---|---|
| (a) Title block SCALE `2:1` on a `1:2` sheet | `ISheet.SetScale(num,den)` DOES drive the field (`SetScale(1,2)` prints `1:2`, `SetScale(2,1)` prints `2:1`). **Creating a drawing view afterwards silently resets the sheet scale** (probe: set 1:2, add view -> sheet became 1:5). v7 set the scale before the views. | `DrawingDoc.set_sheet_scale()` runs after the views exist and again before every save/export for every sheet (`reassert_sheet_scales`), reads back `GetProperties2` items 2/3, and the REOPENED drawing's value is the evidence. Source scale text `1"=2"` was also unparsed (the planner then picked its own scale); `parse_scale` now reads imperial notation. |
| Rotated pages: text boxes wrong | **PyMuPDF `get_text` boxes are in UNROTATED page space** (proved by `tests/test_v8_srcmap.py`: identical boxes for rotation 0/90/180/270). | `srcmap.fitz_displayed_rect` (via `page.rotation_matrix`) used by text evidence and vector clusters; `PageBox` raw<->displayed math tested for 4 rotations x 3 crop boxes against real PyMuPDF output. |
| Native sheet lines drawn at half size / offset | Sketch geometry created on a sheet is multiplied by the **sheet scale** when displayed (1:2 drew a title block at 0.5x position and size). | `DrawingDoc.sheet_lines` divides coordinates by the sheet scale and draws before any view exists; verified by registered overlay (grid lines coincide with the source). |
| Thin ring seen from two sides took the planner layout (`ambiguous_shape`) | Two roles (top/right) had the same silhouette. | In replication the projection geometry decides (third angle: right of the front = right, above = top; first angle mirrors); label type stays a tie-breaker. |
| Extra isometric / hole views / sections added | Forward-pipeline defaults. | Replication creates only views the source shows (`omitted_not_in_source` recorded). |

## What was built (all under `2D-3D-CAD-Test-Generation/`)
| File | Role |
|---|---|
| `reverse/srcmap.py` | Raw/displayed/sheet coordinate frames, `PageBox` (rotation + crop), `SheetFrame` (physical-size frame, Y inversion, centring or recorded uniform fit), standard-sheet naming. |
| `reverse/drawingspec.py` | DrawingSpec `drawingspec/1` (page ids, boxes, rotation, physical size, units, projection, views with scale/parent/alignment, annotations with verbatim text, type, value, units, precision, tolerance, symbols, font/height, anchor/bbox, leader vertices, view/geometry refs, provenance, confidence, review status; explicit `present / missing / unreadable / not_applicable`), completeness, reuse rule (hash + schema + completeness, else supplement the missing pages), tiling + coordinate merge. |
| `reverse/refextract.py` | Multi-page extraction (up to 12 pages, cache written after every page, partial cache supplemented, hit = zero calls and a recorded cache-hit row), fonts from the text layer, optional overlapping tile pass (`options.tiles_per_page`, each tile a recorded budgeted call). |
| `reverse/replicate.py` | Sheet from source physical size (snaps to a standard sheet within 3 %, else its own size), raster/vector line detection -> native border and title-block grid, verbatim editable notes at source positions, scale checks, verbatim check on the exported PDF, `decide_status`, registered side-by-side / overlay / difference images. |
| `reverse/refrun.py`, `engine.py`, `drawing.py`, `planner.py`, `reflayout.py`, `compare.py` | `plan_replication`, scale inference (labelled `inferred`), mixed view scales, source-coordinate placement of dimensions with measured minimal displacement (every displacement + reason recorded), bounded closed loop (default 3, stop on pass / no improvement / cap), multi-sheet reconstruction (`NewSheet4`), reopen verification (per-sheet scale, per-view scale, model refs, notes, dimensions), replication report + QA gate (`passed` only if `Verified`). |
| `reverse/costs.py`, `service.py`, `state.py`, `pipeline/token_tracker.py`, `pipeline/openai_adapter.py`, `config/pricing.json` | Cost/usage/runtime accounting and `ReverseService.estimate_run` (below). |
| `tools/v8_accept.py`, `tools/v8_fixtures.py` | Live acceptance driver, labelled fixtures. |
| `tests/test_v8_costs.py` (18), `test_v8_srcmap.py` (27), `test_v8_replicate.py` (23), `test_v8_service.py` (5) | Offline tests. |

## Cost and runtime accounting
* Every model request is a ledger row (`<job>/usage/usage_ledger.jsonl`) with provider usage, response id (`record_completion` captures `response.id`; the OpenAI adapter now returns it), stage (`extraction` / `tiles` / `validation` / `correction`), attempt. A response with no usage is flagged `usage_missing` (unknown, never free). A local cache hit writes a $0 row without a call.
* `costs.aggregate` recomputes cost with Decimal from the recorded token classes and the configured rate (a rate change re-prices history), dedupes by response id, keeps attempts separate, and reports `cost_status` priced / partial / unpriced / none. Unknown rate => `null`, never 0.
* Rates: `config/pricing.json` now carries tier, effective date, source URL, verification note. **I could not re-verify the GPT-6 Astra rate on https://openai.com/api/pricing/** (the fetched page lists seat pricing only and no per-token price for that model), so the rate stays at $10 / $50 per M (cached input charged at the full input rate, an upper bound) from the Azure GA post, `as_of` 2026-11-27, with that caveat written into the row. Re-check before using the numbers for billing.
* `ReverseService.estimate_run(part_paths, reference, options)`: per-part and total low/expected/high for cost, tokens and duration, from page count, rendered image size, text-layer item count (scans use a labelled fallback), tiles, cache state (a confirmed complete cache hit = $0), history when >= 3 comparable calls exist; budget block (`would_block` when the high scenario exceeds the remaining cap). Fallback constants were calibrated on the four observed reads (10.2k-11.2k input tokens per scanned C-size page); the documented tile rule alone under-counts images.
* `job_view` adds `estimate`, `usage`, `timing`, `estimate_vs_actual` at job and part level. Timing uses monotonic clocks (`state.begin_stage/end_stage/mark_started`); queue time is separate.
* Budget: `budget.preflight` already refuses a NEW call whose worst case exceeds the remaining cap (unchanged). No model call is made in validation/correction (deterministic comparison first); those stages report zero.
* Spend this task: ring extraction **$0.3206** (10,230 in / 4,365 out) and A001171E extraction **$0.2329**; total **$0.5535** (ledger 17.009 -> 17.563). The pre-run estimate for A001171E was expected $0.2517 (range $0.149-$0.845); actual $0.2329 fell inside it.

## Live results (SOLIDWORKS 2025; evidence in `v8-evidence/`)
All runs use `reference.mode = match`, the source PDF supplied as an upload (hash recorded), parts and PDFs hashed before/after (`inputs_unchanged: true` in every run).
Ring: `Simple Parts/A001651E.PDF` (sha256 `57977f7f...`, scan 1580x1216 pt, `1" = 2"`) with `FINAL_OUTPUTs/A001651E/165-C_ir.SLDPRT`; the title block reads part 165-C / model 180 B, and the geometry check is `uncertain` (only some printed dimensions are found on the forward model, see the critical mismatches below), so the pairing rests on the title block and the part number, not on a proven geometric match.

| Scenario | Evidence | Status | Measured |
|---|---|---|---|
| Ring (regression) | `ring_b4028/165-C_ir/` | **Needs Review** | sheet ANSI C 558.8x431.8 (source 557.4x429.0 mm), sheet scale 1:2 = source, title block 1"=2" = source, both view scales 0.5 (explicit), view centres 0.0 / 0.21 mm (limit 1), 42/48 notes verbatim in the export (6 are GD&T-glyph / diameter-glyph lines), no clipping, 36 native border + title-block segments registered on the source, 2 of 29 source dimensions are associative matches (anchors 8-12 mm after minimal displacement), 22 source callouts reproduced as non-associative notes, 5 critical mismatches (the forward model has different hole sizes, e.g. counterbore holes: true values shown, nothing overridden), Section V2 stands in as a plain right view, Detail V3 not reproduced. 2 correction iterations, stop `no_improvement`. |
| A040281E block (4028-B, tolerances, section) | `ring_b4028/4028-B_ir/` | **Needs Review** | scale 1:1 exact (title block `1"=1"`), view centres 0.11 / 0.22 mm, 33/33 notes verbatim, 0 clipping, 3 critical mismatches, one source view not reproduced, anchor max 108 mm (dimensions kept at generated positions because source positions would add collisions). |
| A001171E counterbores (paid read, $0.2329) | `cbore/117-C_ir/` | **Needs Review** | view centre 0.0 mm, 31/32 notes verbatim, 0 clipping, 5 critical mismatches, 2 source views (bottom, side) not reproduced, anchors up to 267 mm (source positions rejected for collisions). |
| Batch of 2 (ring + 4028-B in one job) | `ring_b4028/` | both Needs Review | per-part results above; job-level usage/timing/estimate present in `job_view.json` (0 calls, cache hits recorded; elapsed 224.5 s). |
| Multi-page (FIXTURE) | `multipage/165-C_ir/` | **Needs Review** | `ring_2page.pdf` = the ring page twice; page 2's extraction is the page-1 extraction copied (zero calls, labelled fixture in `_fixtures/README.txt`). Verified: 2 sheets in order, reopened drawing has Sheet1 + Sheet2 each 558.8x431.8 mm at 1:2, page 2 views/notes/lines built, per-page overlay images. It does NOT test reading a different second page. |
| Rotated pages | `tests/test_v8_srcmap.py`, `test_v8_service.py` | unit-tested | No rotated drawing with a matching model was run live (`A001291E.PDF` is rotated 180 but has no model in the repo). |

Images to inspect: `<scenario>/<part>/comparison/page-001_overlay.png` (source red, generated blue, both black), `_side_by_side.png`, `_diff.png`; `replication/report.json` has the numbers, issue list (`R###`), displacement records.

## Limitations / blockers (not hidden)
* **Dimensions**: only the dimensions the existing dimensioner can create associatively are placed; source dimensions it cannot create become verbatim, editable, NON-associative notes (status `source_note`, needs engineer review). Moving a matched dimension to its source position is accepted only when measured collisions do not rise; otherwise the generated position stays and a `position_deviation` is reported. This is why anchors are far from the 1 mm threshold.
* **Model vs drawing**: the forward-built models differ from the drawings in places (ring holes). Those are reported as `value_differs`; the model geometry is never changed to hide it.
* **GD&T / frame glyphs** (position, runout, perpendicularity) and the diameter glyph are not printed by the export font; those notes are flagged `symbols_unverified` / `text_mismatch`. Not solved.
* **Section / detail / auxiliary views** of the source are not rebuilt (flagged). Per-page dimensions are not generated on extra sheets (all dimension-like text there is a source note).
* **Scans**: positions come from OCR boxes (`position_source`); hand lettering is not CAD text, so pixel similarity is low by nature and is only a diagnostic. Leader polylines are not vectorised from scans (end point only, recorded as such). Font family/height of scans is `not_available_for_scans`; note height is derived from the box.
* **Line detection** is raster morphology on scans (vector pages use the same raster path at 100 dpi; vector-path extraction is not implemented); it draws only strokes on the page edge and inside the detected title block.
* Verified status exists in code and tests (`decide_status`) but was never reached on real data; no run claims it.
* Tile extraction is implemented and unit-tested for the transform/merge (`test_tiles_*`, `test_merge_*`) but was not exercised live (budget).
* UI work, `scoring.MD` integration: not touched (no `scoring.MD` found in the repo; fidelity diagnostics stay separate and labelled as such).

## Commands
`cd 2D-3D-CAD-Test-Generation; $env:PYTHONUTF8=1`
`python -m pytest tests -q`  -> **1600 passed, 67 skipped** (2:26)
`python tools/v8_fixtures.py; python tools/v8_accept.py ring b4028` / `cbore` / `multipage` (SOLIDWORKS 2025 required; `--cache` defaults to the saved extractions in `v8-evidence/_cache`, so only a PDF without a cached extraction costs a call)
