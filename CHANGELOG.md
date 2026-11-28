# Changelog

## v8 reorganisation (2026-11-27, branch `ImprovementsV8`): repository structure only, no feature changes

- Input drawings moved to `data/inputs/` (`drawing_pdfs`, `verified_drawings`, `view_defined_drawings`, `simple_parts`, `mti_test_set.csv`); docs grouped by topic (`product`, `guides`, `mti`, `scoring`, `solidworks`); two legacy extractions and a stray job id moved to `archive/`.
- New `utils/paths.py` (central locations, `resolve_input` for the pre-v8 folder names), `scripts/maintenance/check_md_links.py` (0 broken links), `docs/README.md`, root `.env.example`.
- 18 tracked SolidWorks lock/autosave files untracked and gitignored.
- New deliverables: `REPOSITORY_MAP.md`, `FILE_MIGRATION_REPORT.md`, `ARCHIVE_MANIFEST.md`, `REGRESSION_TEST_REPORT.md`; `CLAUDE.md` and `README.md` updated.
- Deliberately not moved: the Python packages, `FINAL_UI/`, `FINAL_OUTPUTs/` (see `FILE_MIGRATION_REPORT.md`).

## v8 (2026-11-27, on `ImprovementsV7`): drawing replication and cost accounting
### Added
- **Replication:** sheet at the source's physical size; title-block scale equals the source (root cause: creating a view resets the sheet scale, now re-applied before every save and export); source-coordinate placement with rotation/crop transforms; verbatim editable notes and title block; multi-sheet reconstruction; mixed view scales; versioned `drawingspec/1`; closed loop with side-by-side, overlay and difference images; statuses Verified / Needs Review / Blocked / Failed. Nothing reached Verified in the live runs (ring, 4028-B, counterbores): see `docs/solidflow-upgrades/V8_BACKEND_REPORT.md`.
- **Cost and runtime:** per-request usage with Decimal arithmetic, config-versioned pricing (the GPT-6 Astra rate could not be re-verified against the public price page), pre-run estimates (low/expected/high), monotonic elapsed time, estimate vs actual; shown on the 3D -> 2D rail and the 2D -> 3D workspace.
- **UI:** synchronized side-by-side source/generated viewer, Overlay/Difference, Comparison tab with issue list, validation-report download. See `FINAL_UI/docs/verification/v8/WORKSPACE_V8_REPORT.md`.
### Fixed
- The 3D -> 2D job watchdog compared a monotonic stage timestamp with wall-clock time and cancelled every running stage within seconds (found by the first live run through the UI; regression test added).

## v7 (2026-11-27, branch `ImprovementsV7`)
### Added
- **3D -> 2D reference-driven reconstruction:** Standard vs Match-reference mode; source PDF resolved from an explicit upload or a content-hash-confirmed 2D -> 3D forward run (a filename alone is only a candidate; ambiguous matches are never auto-selected); extraction reuse (zero API calls on a cache hit), supplemental or fresh OpenAI extraction through the budget guard; coverage ledger, spatial/semantic comparison, bounded layout loop, QA gate (`review_required`, never a false pass). See `docs/solidflow-upgrades/V7_BACKEND_REPORT.md`, `V7_CONTRACT.md`.
- **Drawing standards (SolidWorks 2025 APIs verified):** isometric Shaded With Edges, broken leaders on leadered dimensions (notes have no such style in the API: reported), native Auto Arrange with before/after verification, collision detector.
- **Workspace:** compact Setup rail (Template, Parts, Reference, Advanced, Runtime & Cost, Run, Export), `3D Model | Source PDF` toggle, SLDDRW / PDF / ZIP downloads bound to the selected part and run, Batch Queue directly under the viewers (12 px, was 305-384 px). See `FINAL_UI/docs/verification/v7/WORKSPACE_V7_REPORT.md`.
### Known limits
- Every reconstruction ends `review_required`; some drawings keep measured collisions; title-block SCALE reads 2:1 on a 1:2 sheet; only sheet 1 of a multi-page reference is rebuilt; student-licence watermark on PDFs.

## v6 (2026-11-26, branch `Improvementsv6`)
### Added
- **SolidWorks build recording, window-only:** the desktop/screen-rectangle fallback is gone; capture is `PrintWindow(PW_RENDERFULLCONTENT)` of the one validated SolidWorks window (Windows Graphics Capture + overlap
  privacy gate as fallback). Windows covering SolidWorks (Chrome, VS Code, Explorer) never appear in the video. 15 fps (measured ceiling), H.264 MP4, verified before publish.
- **Camera and presentation** (`pipeline/solidworks_camera.py`): maximize the owned window, hide the FeatureManager tree (native `Hide/Show Tree Area` command), standard isometric + fit + margin + centring after
  every committed feature, verified on the rendered picture and native orientation; 3.2 s final hold; everything restored on completion, failure and cancel. `camera_log.json` per run, `camera` block in the manifest.
- **Workspace layout:** see `FINAL_UI/docs/verification/v6/WORKSPACE_REPORT.md` (collapsible Material and Runtime & cost sections, Pipeline Results closed by default and filling to the workspace bottom).
- **Camera cadence:** whole-part zoom-out with the working orientation kept (15 % margin), isometric only after every second successfully completed feature and at the end (held >= 3 s), per-part feature counter, boundaries before each feature / after each sketch is defined / after each commit. See the cadence section of `RECORDING_CAMERA_REPORT.md` (includes what is NOT met).
- Docs: `docs/solidflow-upgrades/RECORDING_CAMERA_REPORT.md`, `RECORDING_VERIFICATION.md`, evidence in `recording-evidence*/`.

## v5 (2026-11-26, branch `ImprovementsV5`)
### Added
- **Material upgrade (2D -> 3D):** strict `material_extraction` contract; catalog loader (demo, company folder `materials.json` / CSV / `.sldmat`, installed SOLIDWORKS libraries); deterministic resolver
  (exact matches only, fuzzy = suggestion, labelled manual override); native SOLIDWORKS 2025 assignment with read-back after save and reopen; mass-based illustrative cost; STL appearance sidecar with a
  stale-colour guard; Material section in Pipeline Results, Part Setup folder control, Projects / Recent columns, batch totals.
- **3D -> 2D pipeline:** `reverse/` package (durable jobs, serialized CAD worker, B-rep inventory, view / sheet planner, native drawing, sections, feature-aware dimensioning with coverage ledger and
  read-back verification, PDF QA, template generator, audited review workflow), native `.drwdot` + `.slddrt` templates (ANSI B / ANSI C / metric A3), HTTP API, `3D -> 2D` page.
- Tools: `tools/material_e2e.py`, `tools/reverse_gates.py`, `tools/reverse_http_e2e.py`, `tools/roundtrip_compare.py`; reproducible browser regression `FINAL_UI/tests/e2e/run_v5_all.sh`.
- Docs: `docs/solidflow-upgrades/*`, `docs/test-reports/2026-11-25-v5-report.md`, evidence folders.
### Changed
- Layout: results-section accent bars no longer overlap text; viewer header badges no longer truncate; automated layout audit added.
- Store robustness: cancel flag file, locked atomic reads / writes, retry resets parts to queued.
### Known limits
- Revolved bosses / shafts, fillets and chamfers are review items; no detail / auxiliary views; a crowded sheet can leave a section without room; the engineering review gate and a comparison with
  engineer-prepared drawings were not run. See `docs/solidflow-upgrades/IMPLEMENTATION_REPORT.md`.

## v4 (2026-11-25)
- Scoring tab, Extraction-to-Model Fidelity rubric, standardized grading spectrum, colour-coded numbers, always-fresh UI assets, Projects previews and batch folders, run estimates. See `STATE.md`.
