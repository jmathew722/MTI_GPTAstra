# QA CHECKLIST — Nebula CAD

Run the app (`cd Thee_UI/nebula-cad && npm run dev`, open http://localhost:3000). Mark each line PASS, FAIL (with what you saw) or N/A. A reviewer should check the running app and the code, not trust the docs.

## A. Scope
- [ ] A1 Routes exist and render: `/dashboard`, `/projects`, `/projects/[id]`, `/automation`, `/models`, `/pipelines`, `/viewer/[id]`, `/library`, `/docs`, `/settings`.
- [ ] A2 Top nav tabs are exactly: Dashboard, Projects, Automation, Models, Pipelines, Docs; plus search, notifications, avatar, cube logo, NEBULA CAD wordmark.
- [ ] A3 Sidebar items are exactly: Dashboard, Projects, Automation, CAD Viewer, Pipelines, Library, Settings; recent projects; System status at the bottom.
- [ ] A4 Right rail has Project Overview, Performance, Activity; it collapses.
- [ ] A5 Lower workspace tabs are exactly Parameters, Features, Validation, Cost, Logs, Rubric in that order, Rubric last.

## B. Workstation
- [ ] B1 Drawing (pdf.js) and model (R3F) show side by side; split slider works.
- [ ] B2 Overlay and Diff modes work or are disabled with a stated reason.
- [ ] B3 Clicking an extraction item highlights its region on the drawing and a gold marker on the model.
- [ ] B4 Viewer: orbit, zoom, fit, reset, fullscreen, section plane, measure, XYZ triad, dimension callout.
- [ ] B5 Viewer loads a local STL; STEP path exists via occt-import-js; "Static preview" label appears when nothing is loaded.
- [ ] B6 Extraction review lists every item with confidence, region, status; approve, edit, reject work; risky items sort to the top.
- [ ] B7 Build plan report is ordered, expandable, exportable.
- [ ] B8 Pipeline timeline shows four stages with statuses, timings, retries, failure state.
- [ ] B9 Quick actions: New Model, Clone, Export all do something real or are tagged Demo.

## C. Tabs
- [ ] C1 Parameters: editable, mono right-aligned, range check on blur without clamping, undo, reset to extracted, source link.
- [ ] C2 Features: tree from the build plan; selecting highlights in the viewer; extracted vs modeled counts.
- [ ] C3 Validation: seven required checks; Passed/Failed/Warning/Not run; nothing is Passed without having run.
- [ ] C4 A failed critical check blocks export until overridden with a recorded reason.
- [ ] C5 Cost A: per-stage tokens, vision calls, retries, compute seconds, per part, per batch, trend, monthly, budget guardrail; ASSUMPTION notice until rates are confirmed.
- [ ] C6 Cost B: material, machining, setup, finishing, inspection, overhead, margin; quantity breaks 1/10/100; ESTIMATE labels; formulas shown; densities 7.85 / 8.0 / 2.70 / 4.43.
- [ ] C7 Cost C: ROI with visible assumptions, per part and cumulative.
- [ ] C8 Logs: virtualized, level filter, search, copy, follow-tail; sample logs labeled.
- [ ] C9 Rubric: seven criteria, weights editable and must sum to 100, four level descriptors + 0, evidence links, comments, total, band, release status.
- [ ] C10 Rubric hard-fail cap shows with its reason; override needs a reason; sign-off records name and time; templates save/load/duplicate; history; PDF and JSON export.

## D. Honesty
- [ ] D1 Every mock-fed card shows SAMPLE DATA; a persistent sample-mode chip is visible.
- [ ] D2 No control looks interactive and does nothing. Non-functional ones are tagged Demo.
- [ ] D3 Loud-failure project: 10 holes on the drawing, 8 extracted. Banner is loud, validation fails, export blocked, rubric capped at Needs rework.
- [ ] D4 Clean project passes and can be approved.
- [ ] D5 A simulated run on a user upload does not fabricate an extraction or a pass.
- [ ] D6 High confidence is never shown as "verified".

## E. Art direction
- [ ] E1 No planet, moon, globe or large celestial body anywhere (including icons and assets in `public/`).
- [ ] E2 Violet is atmospheric only; gold marks priority, active, completed.
- [ ] E3 Stars are sparse and tiny; no strobing, particle storms or thick neon outlines.
- [ ] E4 Glass tiers are consistent; text on glass is readable; the canvas container is not blurred.
- [ ] E5 The model is the visual focus; layout matches or improves on the mockup at 1440×900.

## F. Motion
- [ ] F1 Page-load sequence runs once per session.
- [ ] F2 Tabs use a shared gold pill; content cross-fades.
- [ ] F3 Hover lift, press feedback, gold focus rings.
- [ ] F4 Pipeline progress, active pulse, completion sweep.
- [ ] F5 Reduced motion (OS setting and Settings control) removes decorative motion; reduced transparency removes blur.
- [ ] F6 Ambient animation pauses when the tab is hidden.

## G. Quality
- [ ] G1 `npm run build`, `npm run typecheck`, `npm run lint`, `npm test`, `npm run e2e` pass.
- [ ] G2 axe: no serious or critical violations on any route.
- [ ] G3 Keyboard: every control on the workstation reachable and operable; focus visible; dialogs trap and restore focus.
- [ ] G4 No console errors or hydration warnings.
- [ ] G5 Responsive at 1440×900, 1024×768, 390×844: no horizontal page scroll, nothing clipped.
- [ ] G6 3D viewer, pdf.js and the PDF report renderer are dynamically imported.
- [ ] G7 No secrets in the repo or client; uploads validated and size-limited; `.env*` ignored.
- [ ] G8 Docs page lists licenses, including LGPL-2.1 for occt-import-js and the GSAP license.

## H. Docs
- [ ] H1 ARCHITECTURE, DESIGN_SPEC, API_CONTRACT, PROGRESS, QA_CHECKLIST exist and match the code.
- [ ] H2 Decisions and added features are recorded with reasons.
