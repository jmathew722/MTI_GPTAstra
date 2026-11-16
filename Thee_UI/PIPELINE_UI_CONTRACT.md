# CLAUDE.md — Thee_UI (MTI 2D→3D Pipeline UI)

Guidance for Claude Code (and humans) building the UI for the MTI 2D→3D pipeline. Read [DESIGN.md](DESIGN.md) before writing any markup or CSS. Keep this file current: when a rule here turns out wrong, fix it in the same change.

## What this is

A web UI that drives the MTI 2D→3D pipeline. The pipeline converts 2D engineering drawings (PDF/PNG/JPG/DWG/DXF/eDrawings) into SolidWorks 2024 parts: Claude Vision extraction → ambiguity resolution → verification → VBA macros → `.sldprt`/`.stl` (COM, Windows-only).

The UI does four things:

1. **Intake** — upload or crop a drawing into a part.
2. **Setup** — name the part, enter must-meet specs, preview the 3D result.
3. **Run** — launch the pipeline and stream its progress.
4. **Review** — show every output artifact, the READY verdict, what needs human attention, and the cost.

**The UI never reimplements pipeline logic.** The backend runs `main.py` as a subprocess and streams its console. The CLI is the single source of truth for pipeline behavior. If the UI needs a new fact, read it from an artifact file. Do not recompute it in JS.

## Where things live

All pipeline code is in `2D-3D-CAD-Test-Generation/`. The prototype web app is `2D-3D-CAD-Test-Generation/webapp/` (FastAPI `app.py`, single `index.html`, `bridge.js`, vendored `photoapp/` cropper, `vendor/` Three.js + STLLoader, `static/design-tokens.css`). This folder (`Thee_UI/`) is the finalized UI. Build it to the same backend contract below so it can replace or sit beside the prototype.

## Commands

Run pipeline commands from `2D-3D-CAD-Test-Generation/`. On the Windows build machine `python` is often NOT on PATH, so use `webapp\.venv\Scripts\python.exe`.

```powershell
# Tests
python -m pytest tests/ -q

# Full pipeline on a batch of part folders
python main.py --views-folder ..\Test2 --output ..\Test2\output

# Extract+verify only (no SolidWorks, cheapest live check)
python main.py --drawing path\to\drawing.pdf --validate-only --debug

# Rebuild from a saved extraction (zero API cost)
python main.py --from-json <Part>_extraction.json --output .\output

# Prototype web UI (FastAPI on http://127.0.0.1:8092/)
cd webapp; .\run.ps1
```

`main.py` flags the UI exposes or depends on:

| Flag | UI meaning |
|---|---|
| `--views-folder <part>` + `--output <part>/output` | the normal UI run |
| `--no-sldprt` | "Preview only: macros and reports, no SolidWorks" toggle (the only mode that works off Windows) |
| `--no-export` | skip the copy to `~/Downloads/SolidWorksModel_Parts` |
| `--no-extract-cache` | forced by "Re-run with correction" (paid) |
| `--skip-overview-check` / `--skip-requirements-check` | advanced: bypass the final READY gates |
| `--strict-gate` | advanced: block on failing verification |
| `--no-resolve` | skips Stage 2.5 and therefore Stage 10.5 |

**Exit codes drive the final banner:** `0` = all parts READY · `8` = completed but not all READY · `2` = bad args · `9` = API budget exceeded (if the budget guard is present). Never infer READY from the process alone. Read the artifacts (below).

Env the UI should surface read-only in the header: `ANTHROPIC_API_KEY` present or not (never show the value), `EXTRACTION_MODEL` (default `claude-sonnet-5`), `SOLIDWORKS_TEMPLATE_PATH` valid or not. Never commit `.env` or a real key. `.env.template` stays keyless.

**Dev gotcha:** after editing `webapp/app.py` or pipeline code, restart uvicorn on 8092 or it serves stale endpoints.

## Pipeline stages (this drives the UI's stage strip)

The stage strip is a numbered `OP nn` traveler. One chip per stage, in this order. Detect the running stage by parsing the console stream's stage banners, and derive the done state from artifact files. Do not hard-code timings.

| OP | Stage | Module | Key artifact | What the UI shows |
|---|---|---|---|---|
| 01 | Image prep | `utils/image_prep.py` | — | thumbnails |
| 02 | Holistic overview analysis (1.5) | `overview_analysis.py` | `overview_analysis.json` | collapsible **Overview Analysis** panel |
| 03 | Extraction | `extractor.py` | `<Part>_extraction.json` | cache-hit badge, token/USD line |
| 04 | Vector hole positions | `vector_extract/`, `hole_resolution.py` | in extraction | `position_source` / `position_confidence` chips per hole |
| 05 | Spec reconciliation (2.6) | `must_meet.py` | `must_meet_constraints.json` | MM-001… constraint list, conflicts |
| 06 | Ambiguity resolution (2.5) | `resolver.py` | `<Part>_resolved_extraction.json` | resolutions with confidence + tier |
| 07 | Verification | `validator.py` | `<Part>_verification_report.txt` | advisory pass/warn list |
| 08 | Build sequencer (6.5) | `build_sequencer.py` | `<Part>_build_dispositions.json` | per-feature disposition table |
| 09 | Macro generation + audit | `macro_generator.py`, `macro_audit.py` | `macros/`, `<Part>_audit_report.json` | macro list, manual-step callouts |
| 10 | CadQuery pre-validation | `cq_prevalidate.py` | `prevalidation_report.json`, `prevalidation.stl` | pass/fail, **aborts the build on fail** |
| 11 | SolidWorks build | `solidworks_builder.py`, `model_validator.py` | `.SLDPRT`, `.STL`, `macro_result.json`, `<Part>_model_check.txt` | 3D viewer, per-feature success/fail |
| 12 | Constraint verification | `constraint_verify.py` | `constraint_verification.json` | PASS/FAIL, measured vs required |
| 13 | Reconciliation pass (10.5) | `reconciliation.py` | `<Part>_reconciliation_report.json` | checklist vs built, loop passes, unresolved |
| 14 | Final checks | `overview_check.py`, `requirements_check.py` | `<Part>_requirements.json` | met / partial / unmet |
| 15 | Engineering review | `engineering_review.py` | `<Part>_engineering_review.txt` | severity-ranked flags (read-first surface) |
| 16 | Learning loop | `learning_loop.py` | repo-root `Learning Loop/<Part>__<ts>.txt` | link to the failure report |

Rules the UI must respect:

- **The pipeline never blocks on ambiguity.** A run always produces a complete approximate model. The UI never presents a blocking "fix this to continue" modal. Ambiguities show as resolved values with confidence tags, plus flags.
- **Stages can be skipped, and that is not an error.** No API key or a failed overview call skips Stage 1.5. `--no-resolve` skips 2.5 and 10.5. No `cadquery` makes pre-validation a no-op. No SolidWorks (non-Windows) skips the COM build. Render skipped chips as skipped (`--ink-4`, "skipped"), never as failed.
- **Pre-validation failure aborts the SolidWorks build** and surfaces the exact constraint (`MM-001 FAILED: …`). Show that string verbatim.
- **Stage 10.5 reconciliation does not hot-patch the built `.sldprt`.** A recovered feature is spliced into `build_plan.json` and a new `RECONCILE_pass<N>_*.vba` is added. A full rebuild is needed to pick it up. The UI must say so, never claim the part was fixed.

## Priority tiers (show them, they explain every override)

| Tier | Owner | Owns |
|---|---|---|
| 0 | Operator must-meet specs (Stage 2.6) | overrides any vision-extracted value |
| 1 | Per-view extraction | dimension values |
| 2 | Overview analysis (Stage 1.5) | cross-view relationships (through vs blind, counts, symmetry) |

Every resolution and flag carries `resolved_by_tier`. Render it as a small mono chip (`TIER 0/1/2`) next to the value. Spec overrides also appear in `<output>/lessons_learned.jsonl` with `resolution: spec_override`.

## READY verdict (the one banner)

A part is **READY** only when all of these hold. The UI computes none of it. It reads the result.

- every must-meet constraint PASSes in `constraint_verification.json` (when constraints exist);
- reconciliation `final_status == READY` (else `READY_WITH_OPEN_ITEMS`, which counts as not READY);
- overview check finds no missing visible feature;
- no requirements line is `unmet`.

Three verdict states: **READY**, **READY WITH OPEN ITEMS** (reconciliation unresolved), **NOT READY** (exit code 8). All three still deliver outputs. Under the banner, list the exact gate reasons (the same ones the Learning Loop report records).

## Input model

Multi-view input is one folder per part, in the `--views-folder` layout. The UI writes it to `webapp/parts/<session>/<part>/`, so the CLI can run any saved part unchanged.

- View role comes from filename keywords (`front`/`side`/`top`…) or a leading `01`–`05`.
- A file named `full` / `overview` / `isometric`, or matching the folder name, is **overview context only** (it is never built as a plane). It is also the Stage-1.5 input (`00_full.jpg`).
- **Save gate:** a FRONT view plus one more orthographic view. The front view defines the base profile the build extrudes from. Block Save with a plain message if either is missing.
- **Sheet 1 intake is full-drawing upload/crop only.** The model reads every view from the sheet itself. There is **no region-markup tool, no datum/origin tool, no "Marked View" type, no `reference_regions.json`, no `/regions` or `/marked-view` endpoints.** The prototype's older docs mention them. They are stale, so do not rebuild them.
- DWG/DXF/eDrawings go through `/api/convert-dwg` (engine chain ezdwg → SolidWorks translator → ODA), cached in `.convert_cache/`, logged to `conversion_log.jsonl`. Show which engine converted the file.
- **Operator must-meet spec** is free text in the amber box → `must_meet_spec.txt` in the part folder (legacy `notes.txt` still works). Specs-first: they are injected into the extraction prompt, and the spec text is part of the cache key, so editing the text forces a paid re-extraction. Warn the user before Run when the spec text changed.

## Sheets (screens)

Four sheet-tabs. Keep the `SHEET n` plate styling from DESIGN.md.

1. **Crop** — upload/crop the full drawing; PDF via vendored pdf.js.
2. **Part setup** — part name, view-role assignment, must-meet box, 3D viewer, **Select Model** dropdown (backed by `/api/run-history`). Picking a model swaps the left panel to that part's overview drawing.
3. **Run** — Run / Preview-only toggle, live stage strip, console stream, live **Overview Analysis** panel, and at the foot a feedback box + **↻ Re-run with correction**.
4. **Outputs** — **Select Run** dropdown (same `/api/run-history`) and the ten output sub-tabs (see below). **✕ Clear all models** (`POST /api/run-history/clear`) deletes stored run outputs only, never saved part inputs or the delivered `UI_Output/`/Downloads copies. Make the confirm dialog say exactly that.

### Sheet 4 sub-tabs (artifact → tab)

| Sub-tab | Reads |
|---|---|
| Summary | verdict banner, gate reasons, cost, timing |
| Engineering Review | `<Part>_engineering_review.txt`, severity-ranked, CRITICAL first |
| 3D Model | `.STL` in the Three.js viewer; `prevalidation.stl` as a toggle |
| Features | `<Part>_build_dispositions.json` (BUILT / BUILT_WITH_DERIVED_VALUE / EXCLUDED_INCOMPLETE; name the missing parameter) |
| Constraints | `must_meet_constraints.json` + `constraint_verification.json` (PASS/FAIL, measured vs required) |
| Overview Analysis | `overview_analysis.json` (views, correspondences, conflicts, global notes with `resolved_count`) |
| Reconciliation | `<Part>_reconciliation_report.json` (`checklist_total`, `confirmed_built`, `loop_passes_used`, `unresolved[]`, `splices_applied[]`) |
| Macros | `macros/` file list with audit status; `NN_Fxxx_MANUAL_*.vba` for prohibited features |
| Data | raw `_extraction.json`, `_resolved_extraction.json`, `_build_plan.json` (read-only JSON) |
| Console | `ui_console.log` (persisted per run, so history works) |

If the product later needs a different tab split, keep the artifact → panel mapping.

## Backend contract (what the UI may call)

`webapp/app.py` is a FastAPI wrapper on port 8092. Known endpoints:

- `GET /api/run-history` — disk-scan of `webapp/parts/*/*/output`; survives restarts.
- `POST /api/run-history/clear` — see Sheet 4.
- `POST /api/run-part` — body takes `feedback` and `no_cache`. Feedback is appended to `must_meet_spec.txt`/`notes.txt` as a `CORRECTION (…)` line and `--no-extract-cache` is forced. That makes the run paid, so label the button accordingly.
- `POST /api/convert-dwg` — CAD conversion.
- Part input save and fetch under `/api/parts/{session}/{part}/…`.

Before relying on any endpoint not listed here, read `webapp/app.py`. Do not invent endpoints. If a new one is needed, add it to `app.py` and document it here in the same change.

- **Subprocess stdout is decoded as UTF-8 with replacement.** The pipeline's `rich` output crashed a cp1252 reader once. Do not reintroduce locale decoding.
- The console stream contains ANSI/rich markup. Strip or render it. Never show raw escape codes.

## Outputs layout

Per part under `<output>/<Part>/`: `.SLDPRT`, `.STL`, `_engineering_review.txt` (read first), `_extraction.json` (raw, never lost), `overview_analysis.json`, `_resolved_extraction.json`, `_verification_report.txt`, `_requirements.json`, `_build_plan.json` (self-contained steps + flags + `dispositions`), `_build_dispositions.json`, `_reconciliation_report.json`, `_audit_report.json`, `_model_check.txt`, `macros/` (plus any `RECONCILE_pass<N>_*.vba`), `must_meet_spec.txt`, `must_meet_constraints.json`, `prevalidation.stl` + `prevalidation_report.json` + `prevalidate.py`, `constraint_verification.json`, `macro_result.json` (JSON Lines), `ui_console.log`. Cross-run: `<output>/lessons_learned.jsonl`, `token_usage_log.txt`. Repo-root: `Learning Loop/<Part>__<ts>.txt` + `Learning Loop/INDEX.md`. Delivered copies: `UI_Output/<Part>/` (gitignored) and `~/Downloads/SolidWorksModel_Parts/<Part>/`.

**Tolerant reading:** extraction JSON is backward-compatible (new fields are additive, old JSONs keep loading). Treat every artifact field as optional. A missing file means that stage was skipped or has not run yet, so show an empty state with the reason, never an error toast. Each hole may carry `position_source` and `position_confidence`.

## Cost and tokens

Every paid call is logged. Show cost on Summary and live on the Run sheet.

- `token_usage_log.txt` (appended by `usage_log.py`) holds per-stage token/USD lines. Stage 1.5 is its own line (`stage: stage_1_5_overview_analysis`).
- An identical re-run is **free** via `<output>/.extraction_cache/`. Show a "cache hit — $0" badge.
- `--from-json` rebuilds are free. Offer **Rebuild from saved extraction** as the cheap alternative next to the paid re-run.

## Environment

- Full builds (COM → `.sldprt`) are **Windows + SolidWorks 2024 only**. Everything upstream (extraction, resolution, macros, CadQuery pre-validation, reviews) runs on any OS. On macOS/Linux the UI defaults to Preview-only (`--no-sldprt`) and says why.
- All JS assets are vendored (`vendor/`: Three.js, STLLoader; `photoapp/`: pdf.js). **No CDN, no webfont, no network fetch for assets.** Python deps are pinned. Keep it that way for reproducible clones.
- Dependency-free vanilla HTML/CSS/JS. Shared patterns are CSS classes (see DESIGN.md), not a framework. Do not add a build step or a framework without asking.

## Conventions

- Guiding principle: *a complete approximate model is always the correct outcome; an incomplete model is always the wrong outcome.* The UI resolves and flags. It never blocks or silently drops.
- Numbers shown come from artifacts. Never fabricate or round a value into looking more certain. Compliance grades are never invented (non-geometric notes → `not_applicable`).
- Unit labels: the pipeline works in the drawing's units. Show the unit next to every dimension, and never convert silently.
- Severity colors mean severity only (DESIGN.md rule 3).
- Accessibility: every state is conveyed by text or glyph as well as color; focus ring on all controls; the console and flag lists are keyboard-scrollable.
- Never commit `.env` or a real key. Do not commit generated outputs from `webapp/parts/`.
- Docs: update this file and DESIGN.md whenever the pipeline gains a stage, an artifact, or a gate.

## Verify before claiming done

- Load the UI against a saved run (`GET /api/run-history`), with no API spend. Check each sub-tab with a READY run, a NOT READY run, and a run missing optional artifacts.
- Check the stage strip against a real console stream, including a skipped stage and an aborted pre-validation.
- Run `python -m pytest tests/ -q` if you touched `app.py`.
- Restart uvicorn after any backend edit.
