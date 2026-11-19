# Stage 3 (fix) gate report — automatic PDF Engineering Markup (2026-11-18)

Branch `Improvements_2`. Evidence: `docs/test-reports/stage3-markup-evidence/`.

## Confirmed root cause

Flags reached Results, but the drawing the viewer showed was never a *marked PDF*:

- the viewer's `Marked` source (`FINAL_UI/web/static/js/features/viewer2d.js`) shows `full_marked_view.jpg`, the **human, pre-run** reference
  image (`server/app.py` `MARKED_VIEW_FILENAME`, `/marked-view.jpg`);
- the only post-run markup, `engineering_flags_annotated.pdf`, was a download link and drew on page 1 with labels over the drawing;
- `mti_markup.py` was a standalone command tied to MTI comparison pieces and copied `src[0]` only;
- `maybe_write_flags` swallowed every error, so a failed generation looked like a clean run, and nothing was published to the viewer.

## What now happens on every flagged run (no human positioning)

```
run_part (before the terminal event)
  -> pipeline/engineering_markup.py  finalize_markup(out, drawing, run_id)
       collect   findings -> engineering_findings.json  (written FIRST, so flags survive any later failure)
       localize  text layer / OCR -> flag_locator (exact -> normalized -> fuzzy -> region -> page-only -> unlocated)
       render    <part>_engineering_markup.pdf : every source page unmodified + a scaled right-hand label rail;
                 red boxes, number badges, leader lines, label cards (EF-nnn, severity word, expected/actual/action)
                 drawn as visible vector content; UNLOCATED cards for anything not placed; report pages appended;
                 engineering_markup_pages/page-NNNN.png rendered from the FINAL marked PDF
       publish   engineering_markup.json  (status not_needed | ready | partial | failed, per-finding page, location_status,
                 confidence, rect_pdf_points, rect_normalized, rect_marked_pt, card, manual_action, failure code)
  -> FINAL_UI/server/flags.py  load_markup (validated, bounded, no absolute paths, stale when the drawing hash changed)
  -> GET /api/parts/{s}/{p}/engineering-markup | .pdf | /page/{n}.png   (ETag = generation key; allowlisted paths only)
  -> viewer: "Engineering Markup" source, auto-selected once per artifact, page strip, clickable regions, focusIssue
  -> Results flag cards: "Show on drawing" / "Show on page" / "Location not confirmed", region click selects the card
```

Distinct from the human artifact: separate files, endpoints (`/engineering-markup*` vs `/marked-view.jpg`), UI name
(`Engineering Markup` vs `Marked`), state. `full_marked_view.jpg` is never read or written by the new stage (tested).

Failure codes: `MARKUP_SOURCE_PDF_MISSING`, `MARKUP_FINDINGS_INVALID`, `MARKUP_LOCALIZATION_PARTIAL` (warning on `partial`),
`MARKUP_GENERATION_FAILED`, `MARKUP_PREVIEW_FAILED`. Progress: four new operations (`markup.collect|localize|render|publish`) are
counted as real work units of artifact finalization (denominator 5).

Behaviour by case: **located** red box + badge + label card + clickable region · **page_only / unlocated** red `UNLOCATED` card, no
box, no zoom, listed on the report page · **failed** flags stay in Results, viewer says "Engineering flags exist, but the marked PDF
could not be generated (CODE)", nothing stale is served · **no findings** `not_needed`, stale artifacts deleted, viewer stays on Overview.

Rotated sheets: `show_pdf_page` ignores `/Rotate`, so the stage draws an unrotated copy rotated by `(360 - rotation) % 360`; verified at
0/90/180/270. Large sheets: type, strokes and rail width scale with the sheet (a 36 x 24 in D-size page gets a rail ~3x wider).

## Tests

| Suite | Result |
|---|---|
| `tests/test_engineering_markup.py` (2 pages, previews from the final PDF, rotations, unlocated, clean/stale, failure, missing drawing, unicode, overflow, large sheet, human-view untouched, progress ticks) | 16 passed |
| `FINAL_UI/tests/server/test_app_markup.py` (payload, endpoints, ETag/304, traversal, foreign file in manifest, stale hash, failed, clean, human view) | 8 passed; `tests/server` total 56 passed |
| `FINAL_UI/tests/unit/markupview.test.js` + api/registry additions | unit 159 pass, 3 fail (pre-existing: missing `part_full.log`) |
| `FINAL_UI/tests/e2e/tests/23-engineering-markup.spec.ts` | 6 passed (auto-open + red pixels, sheet 2 navigation + centring, region -> card, unlocated, failure, clean, Overview respected, axe on `#vp-2d`, keyboard) |
| Full Python suite (`python -m pytest -q`, includes the Stage 4 work) | 1279 passed, 66 skipped, 0 failed |
| Full Playwright suite (56 tests) | 36 passed, 6 skipped (opt-in), 14 failed on the first run: the 13 pre-existing stale-after-rebrand failures plus one of mine (an accessible-name change to the *Show on drawing* button), fixed in the same change; specs 21, 22 and 23 then pass together (26 passed). The 13 pre-existing failures are unchanged |

## Evidence

- `engineering-markup-auto-1440x900.png` — the viewer after a flagged fixture run opened Engineering Markup by itself.
- `show-on-drawing-sheet2.png` — Show on drawing opened sheet 2 and centred the region.
- (not committed: customer drawing) a run on the real SB10024_1 scan with the pipeline's own findings. Both findings were
  placed honestly as `UNLOCATED` (one callout text is ambiguous on the scan, one finding has no source callout): the stage refuses to draw a
  precise box it cannot justify. Generated in ~1.3 s with no API call.

## Limits

- Scanned drawings depend on local OCR quality; ambiguous matches stay unlocated by design.
- The rail text is small on a small viewport; zoom the vector PDF or the preview. The previews are capped at 4000 px.
- `full_marked_view.jpg` (human, pre-run) is unchanged.
