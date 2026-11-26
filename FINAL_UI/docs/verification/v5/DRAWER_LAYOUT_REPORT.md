# Pipeline Results drawer layout report (2026-11-26)

## Symptom
Workspace drawer, when expanded, looked like a shallow strip (header, part of the nav, a little content) with a large empty dark area below it.

## Root cause (reproduced and traced in Chromium, port 8218, isolated data)
Not a height-state problem: at 1440x900 the page, `#ws-main` and the drawer were correctly sized (drawer 320px, bottom flush with the page bottom). The real defect:
`.sr-only` status spans (`.res-link .res-st`, `position:absolute`) in the drawer nav had no positioned ancestor inside the nav's scroll box, so they were positioned against an outer ancestor and escaped the nav's `overflow:auto` clipping. They sat at y=918..1289, so `#main` had scrollHeight 1289 vs clientHeight 900: about 390px of dead scrollable space under the drawer. Scrolled down, the drawer appears as a strip above a large empty area (`before-scrolled-1440x900.png`). Same at 1920x1080 (+389) and 1280x720.

## Fix (controlling layout, no fixed heights or spacers)
- `results.css`: `.res-link { position: relative }` (the nav items contain their own sr-only spans).
- `workspace.css`: `.dr-secs, .dr-pane, .dr-tools { position: relative }`; `.page-ws { overflow: clip }` at >=800px so nothing can widen the bounded desktop workspace again. Below 800px the page deliberately flows and scrolls.
- `logic/drawersize.js`: new pure `sanitize(v, fallback)`; `ui/drawer.js` uses it for the legacy `drawerHeight` fallback, so a stale collapsed-header/tiny/junk height is never restored on expand.
- Existing behaviour verified unchanged: collapse (header only, `hidden` body, `height:auto`), Fit, Maximize/Restore (`data-dr-max`), drag + keyboard resize (clamped to measured maximum and MIN 160), per-viewport-class remembered height, ResizeObserver re-measure, aria-expanded.
- 3D -> 2D page (`reverse.js`, `reverse.css`): its results panel is its own flowing section (no drawer height, no shared nav), so it does not have this defect; spec 31 passes unchanged.

## Files
web/static/css/results.css, web/static/css/workspace.css, web/static/js/logic/drawersize.js, web/static/js/ui/drawer.js, tests/unit/drawersize.test.js, tests/e2e/tests/32-v5-results-drawer-layout.spec.ts, docs/PROGRESS.md, this report, screenshots in docs/verification/v5/drawer/.

## Commands run and results
- `node --test` in tests/unit: drawersize tests all pass (incl. new sanitize test). 3 unrelated failures exist on the base too (missing `tests/fixtures/part_full.log`: logparse, status/source, run/finalized).
- Playwright against an isolated server (MCAGENT_DATA/MCAGENT_FINAL_OUTPUTS temp dirs, port 8218): 29 + 30 + 31 + 28 + 32 = 27 passed, 13 skipped (all of 30-v5-materials: skipped by the suite in this environment), 1 failed.
- New spec 32: 7/7 pass (six sizes incl. 1152x720, 960x600, 720x450 as zoom stand-ins, sidebar expanded and collapsed; repeated collapse/expand; stale/junk/huge persisted values; Fit/Maximize/Restore/drag/keyboard/reload; every section's navigation with horizontal-overflow checks; Open full page; Tools mode, project switch; accent audit; empty workspace).
- Failure: `28-v4 ... 86 Projects: Open is solid violet` (`open.boundingBox()` null on the Projects page). Not in code touched here; the isolated data dir holds no saved project rows. Not verified against the base.

## Known limits
- Before/after: the visible expanded drawer is pixel-similar before and after at scroll top; the proof is the computed `#main` scroll overflow (389 before, 0 after), not the screenshot.
- Spec 32 was not re-run against the pre-fix CSS (did not revert files in the shared tree); the before numbers come from the probe runs.
- In-progress runs were not driven (no paid pipeline was started); only idle/completed seeded parts were used. Long Engineering Flags content was exercised through the seeded `badhole` part only if it is the selected session part.
- Browser zoom is emulated by smaller CSS viewports, not real zoom.
