# QA_RESULTS.md

Checklist: CLAUDE.md sections Hard rules, Palette, Information architecture, Tracker, Run button, Viewers, Corrections, Results, Batch, Quality, Process. Evidence: Playwright suite in `e2e/tests` (18 passed), unit tests (111 passed), screenshots in `docs/screenshots/final-*`.

| # | Item | Result | Evidence |
|---|---|---|---|
| H1 | Frontend-only; backend routes and payloads preserved | PASS | `app.py`, `photoapp/`, `bridge.js` untouched; endpoints in FEATURE_INVENTORY section 10 all used (`grep` of `static/js`) |
| H2 | Feature inventory; nothing dropped | PASS | Every row walked; every `#id` named in the "New location" column exists in `index.html` or JS (scripted check, 0 missing); endpoint use verified |
| H3 | `design-tokens.css` single token source | PASS | Color-literal grep returns only `REGION_PALETTE`/`hexToRgba` (D25) and a `#acc-actions` selector false positive |
| H4 | No inert buttons, fake Connected, fake success | PASS | Tests 3, 5, 18; disabled controls carry `aria-describedby` reasons |
| H5 | Engine name not hard-coded | PASS | Tests 3, 18 (no opus/sonnet/haiku/claude-/gpt- in scripts or DOM); grep clean |
| P1 | Palette and gold discipline | PASS | Test 18: one `.btn.gold`; gold only on run button and tracker; tracker caption gold only while running |
| P2 | WCAG AA / axe | PASS | Test 16: no serious or critical violations on Home, Workspace, Results, Projects, Recent, Settings, Help (after fixing 2 findings) |
| N1 | Sidebar items, collapse, persistence | PASS | Tests 1, 17; 1366 screenshot shows icon rail |
| N2 | Home: dropzone, Create 3D Model, demo, folder, recent | PASS | Tests 4, 6; screenshot `final-home-*` |
| N3 | Workspace layout, header, tracker, split, inspector, drawer | PASS | Tests 9, 15; screenshots. Layout matches the mockup structure; the mockup's parts-folder path field is a button (D17) |
| N4 | Pipeline Results page, five groups | PASS | Test 6 (sections present for a demo run) |
| N5 | Projects/Recent from real data only; Clear all models scoped | PASS | Tests 4, 6, 14 |
| T1 | Tracker states; percent only from work units; completed is not verified | PASS | Tests 6, 8; unit tests stages/runstate |
| T2 | Reconnect after refresh, no duplicate run | PASS | Test 7 (one POST /api/demo) |
| R1 | Run button gating with reasons | PASS | Tests 5, 17 |
| V1 | 2D viewer and focus overlay; crops preserved | PASS | Test 10 (same iframe node after reopen) |
| V2 | 3D: real STL only, empty state | PASS (empty state) / N-A (real STL) | Screenshots show "No model generated yet"; no real SolidWorks STL available here |
| C1 | Corrections draft/re-run | N-A for live | Re-run needs a key; draft handling covered earlier (PROGRESS steps 9-12) |
| X1 | Results: 13 sections, empty/loading/error states | PASS | Test 6; Learning Loop disabled with reason (test 18) |
| B1 | Batch folder upload; Run All confirm | PASS | Test 12 (confirm dialog only reachable with a key; gated reason asserted otherwise); loop itself code-reviewed only |
| Q1 | Breakpoints and no horizontal overflow | PASS | Test 15 at 1920, 1440, 1366, 1024, 390; inspector location and canvas tabs asserted |
| Q2 | Keyboard, ARIA, focus return, Escape | PASS | Test 17 (skip link, sidebar toggle, run reason, splitter, drawer, accordions, overlay, dialog) |
| Q3 | XSS safety | PASS | Test 13 |
| Q4 | Stale responses ignored | PASS | Test 19 |
| Q5 | No console errors or warnings | PASS | Tests 1, 2, 4, 13, 15, 17, 18 (headless WebGL driver noise excluded) |
| Q6 | Demo data isolated | PASS | Tests 6, 18 |
| Q7 | Reduced motion respected | PASS (CSS) | `prefers-reduced-motion` rules unchanged; not automated |
| M1 | Live paid run and SolidWorks build | N-A | No API key or SolidWorks on this machine; manual check required (ARCH 14.2 note) |
| M2 | `index.legacy.html` removal | PASS | Removed; no uncovered inventory rows |

Uncovered inventory rows: none.

## Calibration pass
Unit: node --test tests-ui/unit: all passing after updating the store default test. Playwright (e2e): 19 passed, 4 skipped (opt-in CAL/SHOTS specs). Screenshots: docs/screenshots/calibrated-{idle,part,demo}-{1672x941,1920x1080,1440x900,1280x800,1024x768,768x1024,390x844}.png, calibrated-3d-fixture-*.png (synthetic mesh, not CAD output), compare-1672x941.png. Remaining discrepancies are listed in PROGRESS.md "Calibration pass". Live paid runs and a real SolidWorks STL were not exercised.
