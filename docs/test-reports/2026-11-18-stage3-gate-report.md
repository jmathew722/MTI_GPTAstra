# Stage 3 gate report — automatic engineering flags over the drawing (2026-11-18)

Branch `Improvements`. Evidence: `docs/test-reports/stage3-evidence/`.

## Pipeline (all automatic; nothing here is positioned by a person)

```
run artifacts (ir_report.json, plan.json, discrepancies.json)
  -> pipeline/findings.py        evidence-linked findings (stable IDs, expected/actual/consequence/repair)
  -> pipeline/flag_locator.py    page-aware placement: exact -> normalized -> constrained fuzzy -> small extraction region
                                 -> view-level -> honest "not located"
  -> pipeline/flag_overlays.py   engineering_findings.json, engineering_flag_overlays.json (SHA-256 of the drawing,
                                 normalized unrotated rectangle, page rotation, method, confidence), annotated PDF
  -> FINAL_UI/server/flags.py    validate (schema, run, source hash, geometry), bound, whitelist keys; review state
  -> web/.../engineering-flags.js + logic/flagview.js   overlay layer + linked Results list
```

Hooked into `run_part` behind `GPTASTRA_AUTO_ENGINEERING_FLAGS=1` (the UI server sets it for runs it launches).
Text comes from the PDF **text layer**, with local OCR (RapidOCR, no API cost) for scanned pages.

## Commits

`4ca72fb` findings · `fb18928` locator · `681830a` overlays + annotated PDF + developer-only legacy positions · `40b8f45` API, pipeline hook,
review state · `d8d7a60` viewer, panel, acceptance fixture.

## Results

| Command | Result |
|---|---|
| `python -m pytest tests/test_findings.py tests/test_flag_locator.py tests/test_flag_overlays.py tests/test_mti_markup_override.py` | 10 + 21 + 29 + 3 passed |
| `python -m pytest tests/server` (FINAL_UI) | 48 passed |
| `node --test tests/unit` | 150 pass / 3 fail of 153 (the 3 pre-existing `part_full.log` failures) |
| `npx playwright test tests/22-stage3-flags.spec.ts` | **11 passed** |
| `npx playwright test` (full) | **31 passed, 13 failed, 6 skipped**; the 13 are exactly the baseline set (11 baseline + 9 Stage 2 + 11 Stage 3 pass) |
| axe (`#ov-flag-layer`, `.dfl`) | 0 serious/critical (`axe-stage3.json`) |

## Gate checklist

| Requirement | Evidence |
|---|---|
| **No human positioned an overlay** | Spec 31 reads the artifact the pipeline wrote: every overlay has `provenance: automatic`, no `markup_positions*.json` exists, and the production path (`write_flags`) never reads one (test `test_write_flags_ignores_manual_position_files`). The legacy tool only reads it behind `--developer-override-positions`, labeled `developer_override`. |
| Known mismatch -> red box over the right callout | Specs 31/32: each box encloses its callout, judged against an **independent oracle** (PyMuPDF text search through the page rotation), at rotations 0/90/180/270 |
| Source drawing hash | artifact `source_pdf_sha256` == SHA-256 of the PDF (spec 31); a new revision withholds overlays and shows a banner (spec 37; server tests) |
| Low-confidence / ambiguous -> no misleading box | Spec 33: a callout that appears twice (`ambiguous`, 2 candidates) and one not on the sheet (`no_match`) get **no box** and are listed under "Not located on the drawing" with the reason; 2 blue duplicate blocks have no box on them |
| Calibrated threshold | `BOX_THRESHOLD = 0.70`; `test_box_threshold_separates_the_calibration_fixtures`: every true fixture >= threshold (weakest 0.78), every near-miss (changed numbers, duplicates, different thread) is refused. Mutation check: disabling the numeric guard fails 2 tests. |
| Alignment after zoom/pan/rotation/resize/DPR | Spec 34 (wheel zoom, drag pan, resize), spec 32 (rotation), spec 39 (2x device pixel ratio) |
| Keyboard, non-colour severity, forced colours, reduced motion | Spec 35 (Tab/arrows/Enter/Escape, visible focus ring), badges say `n ERR/WARN/INFO` with distinct shapes, spec 38 (forced-colors border, ~0 transition, narrow 390x844) |
| Text escaped | Spec 33: hostile callout text `<img src=x onerror=alert(1)>` shows as literal text, no `<img>` in the list, no dialog fired |
| Flag list <-> drawing both ways, filters | Specs 31, 35, 36: box -> card (drawer opens to Engineering flags), card -> "Show on drawing" zooms and centres the box; severity/category/feature/review-state/location filters, which also hide boxes |
| Review without altering evidence | Spec 36: dismissal needs a reason; review states saved; the findings file is byte-identical afterwards. `verified_corrected` can only be set by a re-run that no longer produces the finding (server test). |
| Annotated PDF from the same contract | Spec 31 fetches it through the file route (`%PDF`); `test_annotated_pdf_puts_the_red_box_over_the_callout_at_every_rotation` checks red pixels over the callout at 4 rotations; report page carries expected/actual/consequence/repair |

## Defects found by inspecting screenshots or failing tests (all fixed)

1. Labels ran off the page edge on rotated sheets and near the right margin -> labels are placed in the displayed page, flipped left when needed.
2. The Results list never re-rendered on a filter change (`dflFilter` was not a render trigger) -> subscribed.
3. A half-made review choice was lost when the panel re-rendered -> drafts kept across re-renders.
4. White-on-red badges were 3.91:1 -> darker red; the badge's accessible name did not contain its visible text -> now starts with it.
5. "Show on drawing" zoomed only 1.3x -> 35% target.
6. A PDF text layer clips text past the page edge, so a fixture callout near the margin could not be found (fixture issue, not a defect).

## Known limitations

* **Only page 1 of the saved overview is displayed by the viewer** (`overview.jpg` is a single raster). Flags on other pages are listed with their page number but cannot be drawn there. A PDF-page viewer is needed to draw on every page.
* The viewer displays a raster of the sheet, not the PDF itself; alignment assumes the raster is the **whole page** with the page's rotation applied (true for the app's pdf.js render).
* Findings come from `ir_report.json` features (unbuilt, unresolved, SolidWorks-unverified, volume mismatch, MTI advisories) and `discrepancies.json`; there is no *dimension-level* comparison yet (e.g. thread depth 8 vs 12 mm), so the architecture's "tapped hole depth" example is represented by the **fixture**, not by a mismatch the pipeline can detect from a live build today.
* `GPTASTRA_AUTO_ENGINEERING_FLAGS` is on by default only for runs launched by the UI server; CLI runs need it set.
* Not exercised: a full live paid run producing real flags from a real part (no paid run was made).
