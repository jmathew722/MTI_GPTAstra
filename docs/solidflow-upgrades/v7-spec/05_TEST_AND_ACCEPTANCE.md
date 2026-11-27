# Acceptance tests and execution plan

## Phase gates
A: inventory real repo and 2025 API probes; baseline screenshots/tests. B: reference resolution/extraction cache and schema; unit/integration tests. C: native drawing reconstruction/styles and layout; actual SolidWorks fixtures. D: frontend/export/queue; browser tests. E: full regression and round trip; report results. Checkpoint each stage, preserve user changes; no destructive reset. If native environment unavailable, run independent tests and mark native gates blocked, not passed.

## Reference fixtures (authorized only)
- Forward-generated part with exact linked original PDF and compatible cached extraction: no new extraction calls; same reference hash and correct provenance.
- Legacy extraction missing layout positions: supplement or fresh extraction; record usage.
- Manually uploaded PDF overrides history; unrelated PDF detected; ambiguous same-name revisions require confirmation.
- Part without reference in Standard mode; explicit Match mode missing reference blocks or requires explicit fallback.
- Batch with mixed references, multi-sheet, scanned PDF, rotated/cropped pages, missing or corrupted source, mismatched configuration and units.
- Reference with exact dimensions, tolerances, notes, symbols, title block, multiple view types. Compare all source items and placements; intentional source overlaps trigger safe deviation, not copied defects.
- Geometry mismatch: native true measured value retained; discrepancy flagged; no fake override or source part mutation.

## Native layout tests
Use simple block, hole pattern, stepped/revolved shaft, internal bore requiring section, complex dense multi-sheet part. Verify actual isometric Shaded With Edges in native and PDF; applicable broken leaders/horizontal text. Record verified API signature and native property evidence. Check before/after auto-arrangement dimension IDs, values, associations and required coverage. Verify zero unintended collision/clipping for accepted fixtures; inspect rendered full pages and close-ups. Test odd sheet sizes, title block clearance, different scales, long notes and crowded reference layout. Failure or exhausted iteration budget produces review_required with evidence. Reopen SLDDRW with linked SLDPRT and all sheets, export and inspect PDF. No lost annotations, no wrong displayed values. Confirm input hashes unchanged.

## UI tests
At 1280x720, 1440x900, 1920x1080 and screenshot-like wide layouts, at 80/100/125% zoom: setup rail compact and readable; accordions collapse/reopen without losing state; source toggle uses correct file; page navigation and controls work; generated viewer unchanged; batch queue immediately adjacent to viewers with no unexplained blank gap (target normal spacing 8–16 px); no horizontal overflow/overlap; batch controls usable. Test keyboard focus/ARIA, live polling without reset, part/run switching, missing reference and error paths. Capture screenshots before/after. Download PDF and SLDDRW, validate signatures/size/content and current run identity; test stale IDs, missing artifacts, unauthorized paths, review status, optional ZIP.

## End-to-end and reporting
Run actual PDF → SLDPRT → STL → reference-driven SLDDRW → PDF for an authorized previously generated part. Compare source and new drawings semantically and spatially; record discrepancies and correction iterations. Run Standard mode independently and a mixed batch. Preserve forward material assignment/cost, recording isolation/camera cadence, scoring and Pipeline Results. Run existing test suite plus new unit, contract, browser and native integration tests. Save artifacts per run: source hash/link, extraction JSON/provenance, plan, native drawing, PDF, STL, QA ledger, collision report, comparison screenshots/overlays, test logs, timing/token usage. Update README/changelog and persistent progress log. Final report lists passed/failed/blocked tests, actual commands, files changed, native version, known limitations and exact launch instructions. No claims of perfect identity or manufacturing readiness without evidence.
