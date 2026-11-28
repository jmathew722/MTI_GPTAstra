# Repository map

Where every major component lives. Start with [README.md](README.md); rules for working here are in [CLAUDE.md](CLAUDE.md); status in [STATE.md](STATE.md).
Run Python commands from `2D-3D-CAD-Test-Generation/` with `PYTHONUTF8=1` set. Resolve repo locations through `2D-3D-CAD-Test-Generation/utils/paths.py`, never from the current directory.

## Why this is not the "ideal" tree

The reorganisation request proposed a `frontend/ backend/ pipelines/ solidworks/ ai/ scoring/` layout. It was adapted rather than imposed: the Python packages and the UI server are imported by name by 1600+ tests, golden macro snapshots, stored project records and documented commands, so renaming their packages would be a rewrite, not a cleanup. The table at the end maps each proposed area to where it actually is. See [FILE_MIGRATION_REPORT.md](FILE_MIGRATION_REPORT.md) for what moved and what deliberately did not.

## Top level

| Path | Contents |
|---|---|
| `README.md`, `CLAUDE.md`, `STATE.md`, `CHANGELOG.md` | project entry points |
| `REPOSITORY_MAP.md`, `FILE_MIGRATION_REPORT.md`, `ARCHIVE_MANIFEST.md`, `REGRESSION_TEST_REPORT.md` | reorganisation deliverables |
| `.env.example` | environment template (no secrets). Real keys live in `2D-3D-CAD-Test-Generation/.env` (gitignored) |
| `2D-3D-CAD-Test-Generation/` | **all pipeline code** (Python) |
| `FINAL_UI/` | Solid Flow UI: FastAPI server + vanilla-JS front end + browser tests |
| `data/inputs/` | source engineering drawings and the MTI test-set table (inputs only) |
| `FINAL_OUTPUTs/` | live generated parts shown in the UI (written by the app, kept in place on purpose) |
| `docs/` | all documentation, by topic (below) |
| `scripts/` | repository maintenance scripts (`scripts/maintenance/check_md_links.py`) |
| `archive/` | superseded files kept for history, see [ARCHIVE_MANIFEST.md](ARCHIVE_MANIFEST.md) |
| `graphify-out/` | knowledge graph of the repo (tool output) |
| `reference-repos/` | untracked research clones (gitignored) |

## Pipeline code: `2D-3D-CAD-Test-Generation/`

| Path | Role |
|---|---|
| `main.py`, `ir_run.py`, `ir_build.py`, `ir_plan.py`, `make_part.py`, `run_models.py`, `rebuild_from_json.py` | command-line entry points (2D to 3D) |
| `pipeline/extractor.py`, `openai_adapter.py`, `schema.py`, `view_ingest.py` | drawing extraction and the shared data contract |
| `pipeline/validator.py`, `model_validator.py`, `findings.py`, `hole_callouts.py` | resolution and verification |
| `pipeline/planner.py`, `pipeline/ir/` | build planning (Feature IR) and the SolidWorks compiler |
| `pipeline/macro_generator.py`, `solidworks_builder.py` | VBA and COM generation |
| `pipeline/solidworks_recorder.py`, `solidworks_camera.py` | build recording and camera policy |
| `pipeline/materials/` | material catalog, resolver, native assignment, cost |
| `pipeline/token_tracker.py`, `budget.py`, `usage_log.py`, `token_report.py` | AI cost tracking and the dollar budget guard |
| `reverse/` | 3D to 2D: reference matching (`reference.py`), extraction reuse (`refextract.py`), layout, drawing generation, dimensioning, comparison, replication (`replicate.py`, `drawingspec.py`, `srcmap.py`), costs, jobs and service |
| `bench/` | benchmark data prep and the geometry/practices scoring (`bench.score`, `bench.fidelity`) |
| `config/` | `models.json`, `pricing.json`, `materials/`, `drawing_templates/`, `mti/` (confidential local tables, gitignored) |
| `utils/` | image prep, units, logger, **`paths.py`** (central paths) |
| `tools/` | acceptance, evidence and diagnostic scripts |
| `tests/` | pytest suite (`tests/golden/` holds macro and IR snapshots) |
| `output/`, `Deliverables/` | CLI run packages and hand-off copies |

## UI: `FINAL_UI/`

| Path | Role |
|---|---|
| `server/app.py` + `server/*.py` | FastAPI app and API routers (`reverse_api.py`, `reverse_v7.py`, `materials_api.py`, `scoring_hub.py`, `estimates.py`, `costs.py`) |
| `web/index.html`, `web/static/js/{pages,features,logic}`, `web/static/css` | pages, feature panels, pure logic modules, styles |
| `web/vendor/`, `web/pdf*.js` | vendored viewers (3D, PDF) |
| `data/` | local UI state: uploads, runs, projects, material settings (gitignored) |
| `tests/server`, `tests/unit`, `tests/e2e` | pytest server tests, node unit tests, Playwright browser specs (`run_v5..v8_all.sh`) |
| `start-ui.ps1`, `run.ps1`, `run.sh`, `run.bat` | launchers (port 8200) |

## Documentation: `docs/`

| Folder | Contents |
|---|---|
| `docs/README.md` | documentation index |
| `docs/product/` | PRD and hosting options (AWS, Azure) |
| `docs/guides/` | demo guide and runbook |
| `docs/mti/` | MTI modeling standards, practices, open questions |
| `docs/scoring/` | scoring rubrics |
| `docs/solidworks/` | macro error log, Hole Wizard research |
| `docs/solidflow-upgrades/` | v4 to v8 contracts, reports, evidence, API validation |
| `docs/superpowers/` | design specs and plans (dated) |
| `docs/test-reports/` | dated test-day records |
| `docs/weekly/` | weekly status |
| `docs/phase1-evidence/`, `docs/phase2-evidence/` | historical evidence (read-only) |
| `docs/reorg/` | before/after trees from this reorganisation |

## Proposed area to actual location

| Proposed | Actual |
|---|---|
| `frontend/` | `FINAL_UI/web/` |
| `backend/` | `FINAL_UI/server/` |
| `pipelines/2d_to_3d/` | `2D-3D-CAD-Test-Generation/pipeline/` |
| `pipelines/3d_to_2d/` | `2D-3D-CAD-Test-Generation/reverse/` |
| `solidworks/` | `pipeline/solidworks_*.py`, `pipeline/ir/compile_solidworks.py`, `pipeline/materials/native.py`, `config/drawing_templates/`, `docs/solidworks/` |
| `ai/` | `pipeline/extractor.py`, `openai_adapter.py`, `token_tracker.py`, `budget.py`, `config/models.json`, `config/pricing.json` |
| `scoring/` | `bench/` and `docs/scoring/` |
| `data/` | `data/inputs/` (inputs), `FINAL_UI/data/` (UI state) |
| `outputs/` | `FINAL_OUTPUTs/` (UI) and `2D-3D-CAD-Test-Generation/output/` (CLI) |
| `tests/` | `2D-3D-CAD-Test-Generation/tests/`, `FINAL_UI/tests/` |
| `scripts/` | `scripts/maintenance/` plus the launch scripts in `FINAL_UI/` |
| `docs/` | `docs/` |
| `archive/` | `archive/` |
