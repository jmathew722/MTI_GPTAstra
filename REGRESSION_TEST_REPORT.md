# Regression test report (v8 reorganisation, 2026-11-27, branch `ImprovementsV8`)

Everything below was executed on this machine (Windows 11, SolidWorks 2025 SP5). Baseline = tag `pre-reorg-v8` (the code before any move). Nothing is reported as passing that was not run.

## Summary

| Area | Baseline | After reorganisation | Verdict |
|---|---|---|---|
| Python suite (`2D-3D-CAD-Test-Generation/tests`) | 1601 passed, 67 skipped | 1601 passed, 67 skipped (run twice) | identical |
| UI server tests (`FINAL_UI/tests/server`) | 166 passed | 166 passed | identical |
| Node unit tests (`FINAL_UI/tests/unit`) | 302 passed, 2 failed (known: registry status/source, store run/finalized) | 302 passed, same 2 failed | identical |
| Browser specs 21-22, 24-26, 28-30, 32-35 (Playwright, isolated server) | not rerun at baseline | all pass (counts below) | pass |
| Browser specs 01-20, 23, 27, 31 | run at baseline, see below | same failures as baseline | identical |
| Markdown links | 0 broken | 0 broken (`scripts/maintenance/check_md_links.py`) | identical |
| Live UI (port 8200), 9 pages | not measured | all pages visible, 0 console errors, 0 HTTP >= 400 | pass |
| Real SolidWorks 2D to 3D (free path) | n/a | built, volume-verified, material assigned | pass |
| Real SolidWorks 3D to 2D (native) | n/a | SLDDRW + PDF + STL generated | pass |
| Fresh OpenAI extraction | n/a | **blocked: API key expired** | not verified |

## A regression found and fixed by testing

Two legacy extraction files (`extraction_115C/116C/117C.json`) were first moved to `archive/` as unused. The browser specs `06-08-demo` and `20-home` then failed in new ways (clicks and responses timing out) while the baseline did not. Cause: `FINAL_UI/server/app.py::_samples()` and `POST /api/demo` load `extraction_*.json` from the code folder by name; there is no Python import to find. The files were moved back, and the specs now match the baseline exactly. Lesson recorded in `ARCHIVE_MANIFEST.md`.

## Browser specs (Playwright, isolated throwaway server and data, never the live UI)

Run with `FINAL_UI/tests/e2e/run_v8_all.sh <port>` (`SPECS="..."` selects specs).

| Spec | Result |
|---|---|
| 21 stage2 | 9 passed |
| 22 stage3 flags | 11 passed |
| 23 engineering markup | 6 passed (1 failure in the first run while SolidWorks builds were running; passes alone, as at baseline) |
| 24 solidworks recording | 5 passed |
| 25 v4 scoring / projects / estimates / batch | 11 passed |
| 26 v4 colour and build plan | 5 passed |
| 27 v4 grade spectrum | 7 passed (same load-related flake as 23) |
| 28 v4 buttons | 4 passed |
| 29 v4 layout audit | 3 passed |
| 30 v5 materials | 13 passed |
| 31 v5 reverse | 14 passed (flake in the first run, 14/14 in the reruns and at baseline) |
| 32 v5 results drawer | 7 passed |
| 33 v6 workspace collapsibles | 11 passed |
| 34 v7 reverse reference | 22 passed |
| 35 v8 comparison and cost | 27 passed |

Specs 01-20 are older and no longer match the current UI copy (for example the home heading is "Your vision, Our blueprint"). They fail identically on the baseline and on the reorganised code:

| Spec | Baseline | After |
|---|---|---|
| 01-05 basics | 3 failed, 2 passed | 3 failed, 2 passed |
| 06-08 demo | 1 failed, 2 passed | 1 failed, 2 passed |
| 09-11 workspace | 2 failed, 1 passed | 2 failed, 1 passed |
| 12-14 data | 1 failed, 2 passed | 1 failed, 2 passed |
| 15-16 responsive/a11y | 2 failed | 2 failed |
| 17 keyboard | 1 failed | 1 failed |
| 18 honesty | 1 failed | 1 failed |
| 19 stale | 1 failed | 1 failed |
| 20 home | 1 failed, 4 passed | 1 failed, 4 passed, 2 skipped (rerun) |

These are pre-existing and were not fixed here (the task forbids unrelated changes). They need their expectations updated to the current UI.

## Live UI check (port 8200, real browser)

Pages visited: home, workspace, reverse (3D to 2D), projects, results, scoring, recent, help, settings. Each rendered; console errors 0; failed network responses 0. Screenshots: `docs/reorg/screenshots/ui-<page>.png`.

## Real pipeline runs

**2D to 3D, free path (no API call), real SolidWorks:** `tools/material_e2e.py --part A001151E` read the drawing from its new location `data/inputs/drawing_pdfs/`, reused the cached extraction, built the part in SolidWorks (every feature's SolidWorks volume equal to the reference volume), passed verification (`sw_ok`, `bbox_ok`, `volume_ok`), and assigned "SolidFlow Generic Carbon Steel" (7850 kg/m3, 1.48 kg, 2.22 USD illustrative estimate). The no-material scenario correctly reports mass and cost as unavailable.

**3D to 2D, native, real SolidWorks:** `python -m reverse.cli run` on the part generated above with the `solidflow-ansi-b` template produced `drawing.slddrw`, `drawing.pdf`, `model.stl`, preview, dimension coverage, layout report, QA, reopen check and verification (exit 0).

**Reference matching, extraction reuse, comparison, cost accounting:** exercised by browser specs 34 and 35 and the Python suite (reference, refextract, replicate, costs tests), and by the live job through the UI server in the previous session. A new live match-mode job was not repeated after the move.

## Not verified (blockers)

- **Fresh OpenAI extraction.** The first run after your key swap worked (two successful calls for A001341E, 0.41 USD in the ledger). A later call returned `401 expired_secret_key`, so a fresh paid extraction could not be repeated. The key looks time-limited or revoked again. Replace `OPENAI_API_KEY` in `2D-3D-CAD-Test-Generation/.env` and rerun `python main.py --drawing ../data/inputs/drawing_pdfs/A001131E.PDF --ir --engine com --output <dir>`.
- **Output relocation to `outputs/<pipeline>/<part>/<run>/`** was not done. Native SLDDRW to SLDPRT references, stored project records and recordings use the existing `FINAL_OUTPUTs/` and `output/` paths, so moving them is a data migration needing its own plan. Existing locations are documented in `REPOSITORY_MAP.md`. Consequently "relocated outputs keep native drawing links" was not applicable and was not tested.
- **Package renames** (`pipeline/` to `pipelines/2d_to_3d/` and so on) were not done; see `REPOSITORY_MAP.md` for why.
- Batch queue, cancellation, project history persistence and material library behaviour were covered by browser specs 25, 30, 33 and the server and Python suites, not by new manual runs. SolidWorks-only recording with camera cadence was covered by spec 24 and the camera/recorder unit tests; a fresh live recorded build was not repeated after the move.
- Corrupted-input and application-restart handling: covered only by the existing automated tests.
- GitHub Actions: the repository has no workflow files, so no CI configuration needed updating.

## Commands

```powershell
# UI (http://127.0.0.1:8200)
powershell -ExecutionPolicy Bypass -File FINAL_UI\start-ui.ps1
# Python tests
cd 2D-3D-CAD-Test-Generation; $env:PYTHONUTF8=1; python -m pytest tests -q
# UI server and unit tests
cd FINAL_UI; python -m pytest tests/server -q; node --test tests/unit/*.test.js
# Browser specs on an isolated server
cd FINAL_UI/tests/e2e; SPECS="35-v8-comparison-cost" bash run_v8_all.sh 8267
# Docs links
python scripts/maintenance/check_md_links.py
```
