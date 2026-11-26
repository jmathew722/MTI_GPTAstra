# Phase 1 report: 2D -> 3D material extraction, assignment, costing and visualization

Branch `ImprovementsV5`. Checkpoint commits: `1fc0fe7` (core), `ca05b48` (reopen proof, failure scenario, live evidence), `8c91b28` (server + UI).
Environment: Windows 11, SOLIDWORKS **2025 SP5 (33.5.0), Student Edition**, Python 3.12. No paid API call was made for any Phase 1 evidence (saved extraction and plan were reused).

## What was built
| Spec section | Implementation |
|---|---|
| 2 OpenAI extraction contract | `pipeline/materials/extraction.py` (`MaterialExtraction`: status specified / not_specified / ambiguous / conflicting / unreadable, evidence kept apart from inference, coating / heat treatment / finish / hardness / stock form as separate fields); wired into `DrawingData` (optional, old JSON still validates) and the extraction prompt. Blank, dash, N/A are absence, not a grade. Citations are checked against the drawing's own text when available. The model name is not hard-coded. |
| 3 Catalog + folder contract | `pipeline/materials/catalog.py`: bundled demo catalog (the spec's manifest, synthetic prices), company folder (`materials.json` / CSV with explicit `density_kg_m3` / `.sldmat`), installed standard library (259 entries). XML `DOCTYPE`/`ENTITY` refused, size caps, paths kept inside the folder, per-record rejection reasons, duplicate ids rejected, missing price = `None`. UI: `server/materials_api.py` + `web/static/js/features/materials.js` (control directly below *Upload folder*). |
| 4 Resolution + review | `resolver.py`: exact id/name/spec/alias only, company beats demo/standard, fuzzy = suggestion only (never auto-assigned, grade/temper differences flagged), labelled manual override (reason, user, time, divergence warning), multi-body/conflicting = no single material applied. |
| 5 Native assignment | `native.py`: `SetMaterialPropertyName2` / `GetMaterialPropertyName2` / `CreateMassProperty2` on the installed 2025 runtime, project-owned demo `.sldmat` seeded from the installed library (installation libraries never written), database folder registered temporarily and restored, read-back before save **and after closing and reopening the saved file**, density compared with the approved record, traceability custom properties. A failed assignment keeps the geometry. |
| 6 Cost | `costing.py`: native mass authoritative within 1 % of volume x density, unknown = unavailable (never $0), "Illustrative material estimate - not a supplier quote" for demo prices, optional explicit yield, per-currency batch totals with priced/unpriced counts. |
| 7 Viewer | `appearance.json` sidecar keyed by STL hash / job / configuration / material; the viewer paints only when the served STL's hash matches and the assignment is verified, otherwise neutral grey with "Preview: material not verified"; part switch and re-run drop colours immediately. |
| 8 Results / artifacts | Material section in Pipeline Results and the drawer, workspace summary, Projects / Recent material column separate from run cost; files `material_resolution.json`, `material_native.json`, `material_costing.json`, `appearance.json`, `ir_report.json[material]`. |

## Evidence (all real SOLIDWORKS, probe part A001151E, volume 188.57 cm3)
`docs/phase1-evidence/` and `python tools/material_e2e.py`. Costs are synthetic demo prices.
| Scenario | Result |
|---|---|
| steel | `assigned_verified`, native "SolidFlow Generic Carbon Steel", density 7850.0, mass 1.4803 kg, **2.22 USD**; re-read from the reopened saved file: identical |
| copper | `assigned_verified`, 8960.0 kg/m3, 1.6896 kg, **16.90 USD** |
| PLA | `assigned_verified`, 1240.0 kg/m3, 0.2338 kg, **5.85 USD** |
| no material on the drawing | `not_specified`, nothing assigned, cost *unavailable* |
| "AISI 4140 STEEL" (no exact entry) | `unmatched`, nothing assigned, suggestions only |
| installed library "Plain Carbon Steel" | assigned natively (7800 kg/m3); no price in that library, cost *unavailable* (not $0) |
| injected failure (database present but unusable) | `assignment_failed`; SLDPRT and STL still produced; cost unavailable |
Spec worked fixtures (100 cm3): steel 0.785 kg -> 1.1775 -> **1.18**, copper **8.96**, PLA **3.10**: asserted in `tests/test_materials.py`.

## Tests
* `tests/test_materials.py`: **59 passed** (catalog security, extraction invariants, resolver precedence, costing, appearance, runner).
* Full existing Python suite (1506 tests collected): **exit 0, no failures** after the schema / extractor / pipeline / compiler changes.
* UI agent: server pytest 112 passed; node unit 241 passed, 3 failed (`logparse`, `registry status over a payload`, `stages run/finalized`: all three fail identically without the Phase 1 changes); `30-v5-materials` e2e 13 passed (axe clean, layout audit at 1920/1440/1366/1100/390 with the sidebar open and collapsed); `27`, `28`, `29` 14 passed. Older e2e files `01-05`, `09-11`, `15-19`: 16 passed, 10 failed because those stale tests expect the pre-v4 Home heading and an element that no longer exists (not caused by this work, not fixed).

## Not run / blocked / known limits
* **NOT RUN:** a full paid OpenAI extraction on a real drawing carrying a material callout (extraction, conflicting-callout, unreadable-scan and multi-page cases are covered only by schema/unit tests and the prompt contract; a live model read is the remaining Gate-C item and needs the API key and a budget go-ahead).
* **NOT RUN:** the Run All dialog's catalog line in a browser (the test server has no API key; wording is unit-tested).
* **NOT RUN:** a full real build through the UI with the new settings variable (the pipeline path was exercised via `tools/material_e2e.py`, the server path via tests).
* Per-body material mapping (multi-material parts) is detected and routed to review; per-body mesh assets / GLB are not generated.
* The demo materials need a project-owned native database that is built on demand from the installed library; on a machine without SOLIDWORKS the demo records show "At build" instead of "native".
* Student Edition watermark text appears on exported drawings and is not part of the pipeline.
* Manual override is recorded and applied on the next run / refresh; a refresh re-resolves from the saved extraction (no SOLIDWORKS) and keeps the last build's native verdict while the choice is unchanged.
