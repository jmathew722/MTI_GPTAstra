# Changelog

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
