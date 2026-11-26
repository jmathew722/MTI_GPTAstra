# Changelog

## v6 (2026-11-26, branch `Improvementsv6`)
### Added
- **SolidWorks build recording, window-only:** the desktop/screen-rectangle fallback is gone; capture is `PrintWindow(PW_RENDERFULLCONTENT)` of the one validated SolidWorks window (Windows Graphics Capture + overlap
  privacy gate as fallback). Windows covering SolidWorks (Chrome, VS Code, Explorer) never appear in the video. 15 fps (measured ceiling), H.264 MP4, verified before publish.
- **Camera and presentation** (`pipeline/solidworks_camera.py`): maximize the owned window, hide the FeatureManager tree (native `Hide/Show Tree Area` command), standard isometric + fit + margin + centring after
  every committed feature, verified on the rendered picture and native orientation; 3.2 s final hold; everything restored on completion, failure and cancel. `camera_log.json` per run, `camera` block in the manifest.
- **Workspace layout:** see `FINAL_UI/docs/verification/v6/WORKSPACE_REPORT.md` (collapsible Material and Runtime & cost sections, Pipeline Results closed by default and filling to the workspace bottom).
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
