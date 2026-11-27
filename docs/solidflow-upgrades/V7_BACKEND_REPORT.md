# Solid Flow v7 backend report (3D -> 2D reference-driven reconstruction)

Branch `ImprovementsV7`. Contract for the UI agent: `V7_CONTRACT.md`. API evidence: `api_validation.md` ("v7 drawing standards"). Evidence: `v7-evidence/` (9 MB, every file < 5 MB).
SOLIDWORKS 2025 SP5 (33.5.0), Student/Educational licence (every PDF carries the licence watermark; detected and excluded from collisions, not hidden).

## What was built (files, all under `2D-3D-CAD-Test-Generation/`)
| File | Role |
|---|---|
| `reverse/reference.py` | Standard vs match request validation; PDF validation (signature, size, pages, encryption); history index of forward runs and PDFs; candidates with confidence+reasons; hash-based links; confirmed-link sidecar `<data>/reference/links.json`; per-part resolver (upload > artifact/confirmed > auto > blocked / `fallback_standard`); `ReferenceServices`. |
| `reverse/refextract.py` | Normalized `ref/1` extraction: deterministic text layer / local OCR + vector clusters, one budgeted structured model call (model pinned in `config/models.json` key `reference_extractor`, `budget.preflight/charge`, `record_completion`, one schema repair), positions taken from text evidence not the model, cache keyed by PDF SHA/schema/prompt version (hit = zero calls). |
| `reverse/reflayout.py` | Sheet format from reference proportions, printed scale (incl. HALF/FULL), view placement by silhouette proportions with projection alignment; any placement that would overlap / leave the sheet is not copied and a deviation is recorded. |
| `reverse/standards.py` | Isometric Shaded With Edges, Broken-leader/Horizontal-text on leadered dimensions, black check, native Auto Arrange with before/after inventory and integrity check. |
| `reverse/layout.py` | PDF-measured text boxes + strokes + native outlines in one sheet frame; collision/clipping detector with documented exemptions; overlay renderer. |
| `reverse/compare.py` | Semantic ledger (matched / matched_shared / value_differs / missing / tolerance_not_applied / unit_unknown / preserved_note ...) and spatial deltas in sheet mm; side-by-side evidence image. |
| `reverse/refrun.py`, `engine.py`, `jobs.py`, `service.py`, `state.py`, `drawing.py`-adjacent | Stage orchestration (11-stage state machine, reference stages `not_applicable` in Standard), compatibility (unrelated-reference) check, reference notes, bounded layout loop (default 3), comparison loop, QA gate, publish (+ linked model copy so the SLDDRW reopens). |
| `tools/v7_accept.py`, `tools/v7_env.py`, `tools/v7_mock.py` | Live acceptance driver; throw-away service env; mock client (unit tests / dry runs ONLY). |
| `tests/test_reference_v7.py` (44 tests), `tests/test_reverse.py` (updated) | Offline tests. |

## Results (live, SOLIDWORKS 2025; real OpenAI model for extraction)
Run: `python tools/v7_accept.py <scenario...>` from `2D-3D-CAD-Test-Generation` with `PYTHONUTF8=1`. Paid model reads: 3 (A001151E supplement $0.2085, unrelated A001351E $0.1731, A040281E $0.2346) = **$0.62**; ledger moved 15.55 -> ~16.2 of 20.

| # | Scenario | Result |
|---|---|---|
| 01 | Standard mode, 115C | PASS (reference stages `not_applicable`; iso Shaded With Edges verified by read-back AND shaded image in PDF; black text; 0 hard collisions after native arrange + moves; status review_required for pre-existing review items). |
| 02 | Match, forward part + linked PDF, legacy extraction (no positions) | PASS: link = `forward_run` (part SHA equals forward SLDPRT, PDF in the run folder), cache `supplemented`, 1 call. Real read: 13 annotations, 3 views, 19 notes, positions from OCR. Comparison found real discrepancies: reference prints `.50` and `.40 DIA` but the model's true values are 0.4375 / 0.40625: **true value shown, flagged `value_differs`**, nothing overridden. Material `CRS 1018` is reference-only (part has none assigned). |
| 03 | Same, second run | PASS: `extraction_cache=hit`, 0 calls, $0.00 (historical cost reported separately). |
| 04 | Manual upload of the same PDF | PASS: `source_kind=upload`, cache hit, no conflict warning. |
| 05 | Unrelated PDF (A001351E) uploaded for 115C | PASS: warning "differs from the drawing this part was generated from"; geometry check `incompatible` -> `rejected_unrelated`, reference NOT used for layout, issue `REFERENCE_UNRELATED` (high). |
| 06 | Ambiguous same-name PDFs (117-C) | PASS: two different drawings both `name_only` (the run-input copy named A001171E.PDF is actually byte-identical to A001131E.PDF); nothing auto-selected; part blocked `REFERENCE_AMBIGUOUS`; explicit `artifact` source or `confirm_reference_link` resolves it (unit-tested). |
| 07 | Match mode, no source | PASS: blocked with explicit reason; with `fallback_standard` runs as Standard with a warning. |
| 08 | Recorded-source-hash link (A040281E) | PASS for linkage/extraction; 2 residual measured collisions (see below). |
| 09 | Batch of 3 mixed | PASS: per-part resolution; 115C ran (cache hit), 117-C and 116-C blocked individually with reasons, no cross-contamination. |
| 10 | Corrupt / non-PDF / empty / missing upload | PASS: all rejected with messages. |
| 11 | Reopen published SLDDRW | PASS: opens, 1 sheet, every view's referenced model loaded (linked part copy published beside the drawing). |
| - | Input hashes (part + PDF) before/after | PASS in every scenario (`inputs_unchanged`). |
| - | Round trip original PDF -> existing SLDPRT/STL -> reference-driven SLDDRW -> PDF + semantic/spatial report | PASS as a run (scenario 02, `comparison/page-001.png` side-by-side, `comparison/comparison.json`). Not "identical": see limitations. |
| - | Unit tests | 162 passed, 1 skipped (`tests/test_reference_v7.py`, `test_reverse.py`, `test_materials.py`). Full repo suite and FINAL_UI suites were NOT re-run by me. |

## Standards verification (api_validation.md)
Iso: `SetDisplayMode3(False,3,False,True)` (not 7, not 5) + `GetDisplayMode2()==3` + `GetDisplayEdgesInShadedMode()`. Leaders: `SetBrokenLeader2(False,2)` verified by read-back on radial/diameter dims; linear dims have no such option (reported, 15 not applicable); notes have no broken-leader class in the API (no leadered notes are generated; reported, no fake leaders). Auto Arrange needs `SelectByID2` selection (Select3 silently does nothing); accepted only when measured collisions do not rise and every id/value/attachment is intact, else positions restored (decision recorded in `layout_report.json`).

## Known limitations / unresolved (honest)
- No part reaches `passed`: the Standard-mode ledger always carries manufacturing-intent items (tolerances, finish, thread, GD&T are never invented), and reference mode adds unresolved/differing items. Result is `review_required` with evidence. This matches the v5 behaviour; "completed" only after the existing engineering-review workflow.
- Residual measured collisions remain on some parts (116-C fallback run: 6, incl. text crossing strokes and an aligned section view overlapping; 4028-B: 2). They are reported, not hidden; sections remain the weakest area (SOLIDWORKS locks aligned section views).
- Spatial correction toward reference anchors is bounded and almost always rejected (it improves distance but adds collisions; collisions take priority). Annotation position deltas against a scan are large (median ~98 mm in scenario 02); view centres land within about 1 mm only for the base view. Positions from `model_estimate` boxes are not chased.
- Scans: the reference page size is not the physical sheet; sheet format is the nearest supported (ANSI C for the 1.35 aspect scans) and the printed scale (HALF) is applied, which makes the views small; deviation is recorded.
- Template title block SCALE field reads 2:1 on a 1:2 sheet (ISheet.SetScale does not drive it; view scales are correct). Unfixed.
- Only sheet 1 of multi-page references is extracted/reconstructed (`page_not_reconstructed`, high). Rotated/cropped pages: stored (`rotation`, crop/media box) but not exercised live. No multi-sheet or scanned-rotated fixture was run.
- Tolerances/finish/GD&T on the reference are preserved as ledger items and the reference-note block, never applied to dimensions.
- Reference-only notes are placed as one block in free space when the notes zone is too small; the legacy `text_overlaps` PDF check can still flag tightly stacked lines of that block (shown in scenario 02 `pdf_check.json`).
- Geometry-mismatch scenario was exercised on real data (02: .50 vs 0.4375) rather than on a deliberately altered part (no source part may be mutated).
- Dense multi-sheet part, odd sheet sizes, long-note and crowded-reference stress tests were not run.
- `cancelled` is spelled `canceled` (existing code); `reverse.cli` was not extended with a `--reference` option.

## Commands
`cd 2D-3D-CAD-Test-Generation; $env:PYTHONUTF8=1; python -m pytest tests/test_reference_v7.py tests/test_reverse.py -q`
`python tools/v7_accept.py standard linked_supplement linked_cache_hit upload_same unrelated ambiguous no_reference recorded_hash batch_mixed bad_inputs`
