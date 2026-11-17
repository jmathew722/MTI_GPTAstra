# CLAUDE.md: McAgent / Meta_Nebula_UI (condensed execution brief)

Source: the user's "CLAUDE (3).md" brief plus mockup `reference/mcagent-mockup.png`. This file keeps every requirement; wording is shortened.

## Layout of this folder
- `pipeline_app/` is a copy of the existing MTI 2D→3D pipeline (`2D-3D-CAD-Test-Generation/`): FastAPI backend `webapp/app.py`, UI `webapp/index.html` (+ `bridge.js`), cropper `webapp/photoapp/index.html`, tokens `webapp/static/design-tokens.css`, vendored three.js/pdf.js in `webapp/vendor`. No CDN, no framework: **vanilla HTML/CSS/JS only**.
- `reference/mcagent-mockup.png` is the visual target (layout and mood only; not data).
- `docs/DESIGN_ComplexUI_original.md` is the old BLUEPRINT ROOM design (superseded where this brief differs).
- Run: `cd pipeline_app/webapp && PORT=8191 ./run.sh` (Python 3.12 venv; 3.15 breaks scipy).

## Hard rules
1. Frontend/interaction redesign only. Preserve backend routes, payloads, saved formats, cropping, view assignment, SolidWorks automation, verification, outputs, batch upload, corrections, learning loop.
2. Audit first; keep a feature inventory and map every existing control/output to its new place. Nothing is silently dropped.
3. `design-tokens.css` stays the single token source shared by `index.html` and `photoapp/index.html`. No scattered hard-coded colors.
4. No inert buttons, invented endpoints, fake percentages, fake "Connected", fake success, fabricated STL. Missing backend capability = visibly disabled with reason, logged as an integration gap. Demo data is labeled **Demo** and isolated from live data.
5. Engine/model name comes from config/backend, never hard-coded.
6. Do not stop at a static mockup; wire everything, test, report.

## Palette (tokens)
bg `#101114`, raised `#191B20`, hover `#24262D`, canvas well `#0D0E11`, violet `#9B8AFB` (nav/selection/focus), champagne gold `#D6AF6B` (Run Pipeline + current stage only), text `#F2F2F4`, muted `#92949E`, border `#30323A`. Success/warning/error keep semantic green/amber/red; severity ladder CRITICAL/HIGH/MEDIUM/LOW unchanged. Gold ≠ warning ≠ verified. Fonts: Segoe UI / Cascadia stacks (vendored/system). Controls 36–40 px, body 14–15 px. Respect reduced motion. WCAG AA contrast.

## Information architecture
**Sidebar** (220–260 px, collapses to 60–72 px icon rail with tooltips, persisted): McAgent brand + subtitle, New Project, Home, Workspace, Projects, Pipeline Results, Recent Files, bottom Help + Settings. Never resets a running pipeline.
**Home**: minimal; "What would you like to create?"; one dropzone (formats per real backend support: confirm PDF/JPG/PNG/DWG/DXF/eDrawings); one **Create 3D Model** action; small links Open sample/Run demo (Demo), Upload parts folder, Recent projects. Never auto-run a paid pipeline.
**Workspace** top→bottom: thin header (part name; engine, deliverables, API status at right, all real) → full-width **five-stage tracker** (Extraction, Resolution, Build Plan, Generation, Verification) → split canvas **2D Drawing | 3D Model (STL)**, equal priority, draggable keyboard-accessible splitter, reset 50/50, maximize either → optional narrow right inspector (≤310 px, collapsible; Part Setup, Pipeline Actions, Corrections, Export; accordion; hidden <1100 px, contents move to drawer Tools) → bottom **Pipeline Results drawer** (header 44–52 px: run state, verification verdict, warning count, runtime; collapse/expand/resize; aria-expanded; persisted). **No permanent View Appearance card**; view assignment lives under Part Setup → Views / drawing toolbar.
**Pipeline Results page**: run selector + breadcrumb; five groups: Overview, Extraction (Extraction JSON, Resolved Extraction), Build & Verification (Build Plan, Verification, Engineering Flags, Model Check), Automation & Files (VBA Macros, Files), Diagnostics (Token/Cost, Console, Run Log/Events). The drawer shows the same content condensed (Tools | Results modes), one state source.
**Projects / Recent Files**: saved parts, folders/batches, runs, timestamps, open/re-run/download, only from real persisted data; safe empty states; destructive "Clear all models" lives behind Projects/Settings with scoped confirmation.

## Tracker
States per stage: pending, running, succeeded, warning, failed, skipped. Run: idle, queued, running, succeeded, succeeded_with_warnings, failed, cancelled. Gold active, green done, amber warning, red failed. Percent only from real backend work units, never time guesses, never backward. Completed ≠ Verification passed. Map existing backend stages by presentation; instrument least-invasively if needed. Tie to `run_id`/part; reconnect after refresh without duplicate runs; ignore stale events.

## Run Pipeline button
`#D6AF6B` with dark text, label "Run Pipeline". Only one dominant gold CTA visible. Disabled with concrete reason (no part, missing required views, run in progress). Running: spinner + cancel only if backend supports it. Run All Parts, Run Demo, Re-run with correction are secondary.

## Viewers
2D: full drawing with fit/pan/zoom/reset/fullscreen/crop, filename shown, all photoapp cropper features (handles, per-view crops, rotation, view types, origin) in a focus mode/overlay, multi-page PDF where supported, upload never destroys prior crops. Required views come from backend validation, not assumed.
3D: real STL only, orbit/zoom/pan/fit/fullscreen, "No model generated yet" empty state, previous-run model labeled "Previous run", update only after the artifact loads, handle missing/invalid STL. Part selector switches everything consistently.

## Corrections
Compact 1–2 line input, expands on focus/“Open editor”; Re-run with correction uses the existing endpoint; preserve prior evidence, label old STL "Previous run", keep draft on failure.

## Results content (all 10 legacy outputs + log)
Extraction JSON (tree/raw, search, copy, download, no rounding), Resolved Extraction, Build Plan (expandable ops), Verification (verdict + checks), Engineering Flags (severity filters, Save all to Learning Loop with server confirmation), Model Check (distinct from Verification), VBA Macros (code view, copy, real download), Files (artifact table, downloads only when present), Token/Cost (measured vs estimated, no hard-coded prices), Console (filter, search, copy, auto-scroll, XSS-safe), Run Log/Events. Every section: status, source, raw toggle where meaningful, designed empty/loading/error states. Overview answers: did it build, does it match, what needs attention.

## Batch
Preserve Upload Parts Folder grouping; per-part status/errors; Run All Parts with confirmation; tracker follows the selected part with an aggregate "N of M parts complete".

## Quality
Breakpoints: ≥1440 full; 1100–1439 sidebar collapsed, inspector in drawer; <1100 tabs Drawing/3D. Keyboard + ARIA (aria-expanded/controls, focus return, Escape), visible focus, status announcements. XSS-safe rendering, no CDN, no secrets. Test at 1920×1080, 1440×900, 1366×768, narrow. Tests for stage mapping, state selection, rendering; e2e smoke with a real test drawing/demo. Final report: files changed, old→new mapping, test results, limitations, integration gaps.

## Process
Fable 5.2 architects (`docs/ARCHITECTURE.md`, `docs/FEATURE_INVENTORY.md`), Sonnet 5.5 implements per those docs. Update `docs/PROGRESS.md`. Local commits only unless the user asks to push.
