# PROGRESS

Task list for the 2D to 3D CAD build. Updated at every milestone. The last task is always verification.

## Task list

| # | Task | Status |
|---|---|---|
| 0.1 | Verify every repo link, maintenance status, current version | done |
| 0.2 | Study reference sites, write research notes | done (limited, see DESIGN_SPEC "Research notes") |
| 0.3 | Pipeline improvement: save an STL beside every generated `.sldprt` | done |
| 1.1 | `docs/ARCHITECTURE.md` | done |
| 1.2 | `docs/DESIGN_SPEC.md` | done |
| 1.3 | `docs/API_CONTRACT.md` | done |
| 1.4 | `docs/QA_CHECKLIST.md` | done |
| 2.1 | Scaffold, tokens, fonts, nebula background, glass system | done |
| 2.2 | App shell: TopNav, Sidebar, ContextRail, routing | done |
| 2.3 | Command palette, toasts, shortcuts dialog | done |
| 2.4 | Schemas, adapter (mock + http), seeded sample data, generated sample drawing PDFs and STLs | done |
| 3.1 | Dashboard (hero, KPIs, viewer, pipeline, workspace tabs, quick actions, rail) | done |
| 3.2 | Workstation: drawing/model compare, viewer tools, extraction review, build plan | done |
| 3.3 | Tabs: Parameters, Features, Validation, Cost, Logs, Rubric | done |
| 3.4 | Automation wizard, Pipelines, Models, Projects, Library, Docs, Settings, Viewer | done |
| 3.5 | Extras: notifications, audit trail, revisions, comments, export center, onboarding | done |
| 4.1 | Motion system | done |
| 4.2 | Polish passes 1–6 | done |
| 5.1 | Unit tests (cost, rubric), e2e smoke, axe, screenshots at 3 viewports | done |
| 5.2 | Reviewer subagent audit, fixes | done |
| 5.3 | Final verification: build, typecheck, lint, tests; docs final | done |

## Milestone log

### M0 — Research, setup, pipeline change
- Brief files were not in `Thee_UI/`. Copied `CLAUDE.md` (master brief), `CLAUDE_NEBULA_PRIME.md`, `NEBULA_PRIME_STACK.md` from `~/Downloads`. The mockup was found as `~/Downloads/a_detailed_high_contrast_dark_sci_fi_ui_for_a_cad.png` and copied to `reference/nebula-mockup.png`.
- The earlier pipeline-UI guidance that lived at `Thee_UI/CLAUDE.md` is kept as `PIPELINE_UI_CONTRACT.md`.
- Work happens on branch `feat/nebula-cad-ui` of the existing repo (see ARCHITECTURE decision D2).
- Pipeline: `export_stl()` added to `pipeline/solidworks_builder.py`, called after both COM save sites. 3 new tests pass. Not run against SolidWorks (this machine is macOS).

### M1 — Foundation, features, tests (commits 1619515, f727ba9)
- Built: tokens, nebula background (gradients + 12 CSS stars + GSAP-drawn corner arcs), glass tiers, shell (top nav, sidebar, rail, command palette, shortcuts, notifications, onboarding tour), schemas, mock + http adapters, seeded projects (flange 10-vs-8 failing, bearing plate clean, spacer ring with a not-run check), all routes, six workspace tabs (Rubric last), export center, failure banner, PDF/STEP/STL viewers.
- Tests: 32 Vitest (cost, rubric incl. hard-fail cap, gating, seed schema), 32 Playwright (smoke per route, axe per route, navigation, tabs, parameters, palette, loud-failure end to end).
- Lint (React Compiler rules) clean; production build passes.

### Polish passes (screenshots in docs/screenshots at 1440x900, 1024x768, 390x844)
1. **Layout and hierarchy.** Found: horizontal page overflow at 1024 and 390 (grid children not shrinking, card header not wrapping); sidebar status block cramped; KPI cards had badges colliding with values; dashboard bottom row left an empty area beside Quick Actions. Fixed: global min-width:0 on grid/flex children, wrapping CardHeader, one SAMPLE badge for the KPI row, Quick Actions moved under the pipeline.
2. **Glass and lighting.** Found: viewer labels drew as huge DOM text; custom CSS sat outside a cascade layer and overrode utilities. Fixed: canvas-texture sprite labels, `@layer components`.
3. **Motion.** Found: viewer did not re-frame on pane resize; axe sampled mid fade-in. Fixed: resize refit, longer settle wait in the audit. Reduced motion verified via emulated media and the Settings switch.
4. **Accessibility and responsive.** Found by axe: 3 accessible-name mismatches, 3 unfocusable scroll regions, one contrast flake. Fixed all; muted text lightened to #B9B0CC. Mobile failure banner reflowed (text was one word wide).
5. **Content and trust.** Diff mode opens by default when a count mismatch exists; override never changes a check's status (tested); a user's own upload gets no fabricated extraction (tested).
6. **Ideas pass.** Added: count-check strip, modeled-outline overlay, Diff mode with red/orange rings, reviewer queue ordering, link zoom, section plane, measure tool, parameter presets, revision compare, export center with gate reasons, reset sample data. Recorded in ARCHITECTURE section 11.

### Reviewer audit (independent subagent, against QA_CHECKLIST.md)
Result: no checklist item failed on structure; defects found and handled:
- **HIGH, fixed:** React error "Cannot update ComparePanel while rendering DrawingViewer" (parent `onZoom` called inside a state updater). Zoom is now reported from an effect. Regression test added (approve + zoom raises no console error).
- **Pipeline diff noise, fixed:** my edit rewrote CRLF to LF in `main.py` and `solidworks_builder.py` (thousands of changed lines). CRLF restored; the diff is 69 lines across 5 files.
- **Static preview label:** present in code for projects with no model; the reviewer only tried projects that have one. Now covered by an e2e test.
- **Upload limit:** a 40 MB file was accepted, which is correct (limit is 50 MB). Not a defect.
- **Mobile title wrap:** fixed with a minimum title width.
- **Not defects, noted:** bp-1042 ships pre-signed as sample data (labeled SAMPLE); a not-run check appears only on sr-0077 (Spacer_Ring).
- The reviewer could not run build, e2e or axe (they would disturb the live dev server). I ran them: build, lint, typecheck, 32 unit and 33 e2e tests (axe on all 12 routes) pass.

### Change request (post-audit)
- Product renamed to **2D to 3D CAD** (wordmark, page titles, welcome page, PDF footers, README, docs).
- Cost tab: **Part manufacturing estimate (B)** and **Automation ROI (C)** commented out (marked `DEFERRED`); also removed from the PDF report, Settings (rates section commented out) and the Library rate card. `lib/cost` math and its unit tests are kept for later.
- Docs page rewritten in formal technical style (numbered sections, defined terms, no marketing language).

### Folder upload, motion pass, interaction tests
- **Folder of parts:** `lib/cad/parts.ts` groups an uploaded folder into parts (sub-folder = one part with several views; loose file = one part). The Automation page lists the parts, estimates cost and time for the batch, submits one run per part in order and shows per-part and overall progress. The mock queues simulated runs one at a time. User uploads are stored, never processed or invented (sample-data mode).
- **Motion and interaction additions:** pointer-following spotlight on every card, stagger entrances (project grid, library, pipelines rows, settings sections, batch rows), animated expand/collapse (validation checks, build operations), animated numbers (rubric total, cost figures), sliding pill in segmented controls, status-stamp pop, bell ring on unread, reading progress bar and scroll-spy on Docs, animated step transitions in the wizard, KPI cards link to their pages.
- **Bugs found by the new tests and fixed:** (1) two quick rubric edits overwrote each other from a stale copy (now read from the query cache at call time); (2) the viewer's section slider could cover the toolbar and block the Measure button on narrow panes (moved to the lower left); (3) the global `?` shortcut was blocked by a closing dialog still in the DOM.
- New spec `tests/e2e/interactions.spec.ts` (14 tests): folder and batch runs, extraction review, rubric scoring/sign-off/weights, gate override, drawing and model tools, comments, library presets, pipelines, settings, shell, validation overrides, export downloads, clone.
