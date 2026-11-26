# Solid Flow v5: persistent implementation checklist

Branch `ImprovementsV5`. Status legend: **DONE** = implemented and verified with the evidence named; **PARTIAL** = works with stated limits; **BLOCKED** = exact blocker; **NOT RUN** = implemented or specified but not executed.
Resume point: read this file, `IMPLEMENTATION_REPORT.md`, `git log`, then continue at the first non-DONE row.

## Phase 1: 2D -> 3D material upgrade
| Requirement | Status | Evidence |
|---|---|---|
| OpenAI extraction of material (`material_extraction`, evidence vs inference, statuses) | DONE, including a LIVE model read (CRS 1018, evidence + bbox, 0.371 USD) | `tests/test_materials.py`; `LIVE_PDF_RUN.md` |
| Drawings with no material are explicit | DONE | unit tests; live `none` scenario; UI "No material specified on drawing" |
| Company material folder control below Upload Folder | DONE | `30-v5-materials` e2e (DOM order + layout audit) |
| Demo steel / copper / PLA | DONE | `config/materials/solidflow-demo.json`; live native assignment 7850 / 8960 / 1240 kg/m3 |
| Installed SolidWorks libraries | DONE | 259 entries parsed; "Plain Carbon Steel" assigned natively |
| Exact matching, no fabricated grades | DONE | resolver tests (4140 vs 1045, 6061 vs 6061-T6, PLS not PLA) |
| Native assignment in SOLIDWORKS 2025 | DONE | `docs/phase1-evidence/` (33.5.0) |
| Verification after save + reopen | DONE | `material_native.json[reopen_verified]` |
| Volume, density, mass, cost | DONE | worked fixtures 1.18 / 8.96 / 3.10; live 2.22 / 16.90 / 5.85 USD |
| STL appearance from sidecar | DONE | sidecar + hash guard; `30-v5-materials` e2e |
| Material cost reported separately from OpenAI cost | DONE | API + UI tests |
| Material in Pipeline Results, single + batch | DONE | `30-v5-materials` e2e |

## Phase 2: 3D -> 2D
| Requirement | Status | Evidence |
|---|---|---|
| Separate `3D -> 2D` tab | DONE | `31-v5-reverse` e2e |
| Native standardized template (.drwdot + .slddrt); custom template selection | DONE | `config/drawing_templates/`; upload endpoint validated by SOLIDWORKS (code + tests; **upload of a user .drwdot not run live**) |
| Single SLDPRT and batch folder | DONE | HTTP e2e (single), CLI batch of 18, UI tests |
| Automated open + STL export, validation | DONE | `stl_validation.json`, 0 % scale error on the probe part |
| Isometric STL left / drawing right | DONE (fixture-driven browser test + real downloads) | `31-v5-reverse`; HTTP e2e |
| Geometry / feature extraction | DONE for prismatic, holes, patterns, bolt circles; PARTIAL for revolved bosses | `inventory.py`; batch18 |
| Orthographic view selection, scale, sheet layout | DONE | `planner.py`; batch18 |
| Section views where needed | PARTIAL (blind / counterbored holes; 12 `SECTION_NO_ROOM` on crowded sheets); detail / auxiliary views NOT implemented | `section_views.py` |
| Associative dimensions, hole callouts, diameters, depths, centre marks | DONE for plates / flanges; PARTIAL for revolved parts (bosses, fillets, chamfers are review items) | batch18 |
| Material in drawing (title block, verified native material) | DONE | `SF_Material` from the native read-back; see `ROUNDTRIP_REPORT.md` |
| Title block population | DONE | template + engine; `NOT SPECIFIED` for unknowns |
| Missing / redundant dimension detection, no over-dimensioning | DONE (ledger, semantic duplicates, read-back verification) | `qa.py` |
| Collision detection, black ink | DONE (PDF checks; 17 overlaps still reported in the batch) | `pdf_check.json` |
| SLDDRW + PDF, reopen check | DONE | `reopen_check.json` |
| Progress, time, cost reporting | DONE (measured stage seconds; API cost shown only when measured) | UI + manifest |
| Batch, cancel, retry, failure recovery | DONE | gates 10/10; server tests |
| Engineering verification and deliverables | DONE as review workflow (audited); engineer sign-off **NOT RUN** | `service.review_action` |

## UI / quality audit
| Requirement | Status | Evidence |
|---|---|---|
| Overlap / clipping / truncation audit across the app | DONE (automated crawl, 6 sizes, sidebar open / collapsed) | `29-v4-layout-audit` 3/3 |
| Palette + grading spectrum consistency | DONE | `27-v4-grade-spectrum` 7/7 |
| Older browser suites (`01-05`, `15-17`, `20`) | **BLOCKED / stale**: assert pre-v4 Home copy and a removed `#orient-gallery select.oselect` selector; not changed by this work | `IMPLEMENTATION_REPORT.md` |

## End-to-end and regression
| Requirement | Status | Evidence |
|---|---|---|
| SLDPRT -> STL -> SLDDRW -> PDF | DONE | batch18, HTTP e2e |
| PDF -> SLDPRT -> STL (existing pipeline) | DONE previously (v1-v4); re-checked via saved extraction rebuild | `docs/phase1-evidence/` |
| PDF -> material extraction -> native assignment (live model read) | DONE (one drawing; test catalog; reopen-verified) | `LIVE_PDF_RUN.md` |
| Material preserved into the drawing | DONE | manifest `material`, title block |
| Native file integrity, STL vs SLDPRT consistency, drawing dims vs native geometry | DONE | `reopen_check.json`, `stl_validation.json`, ledger read-back |
| Missing material / corrupt / unsupported files | DONE | gates, unit tests |
| Round trip: original drawing -> 3D part -> regenerated drawing | DONE as a documented comparison | `docs/phase2-evidence/roundtrip/ROUNDTRIP_REPORT.md` |
| Existing functionality regression | DONE | Python 1506+ exit 0; node 259/3 baseline; server 136+; browser 27 / 28 / 29 / 30 / 31 |
