# DESIGN_SPEC.md: screenshot-faithful calibration brief (condensed from CLAUDE_McAgent_Exact_Design.md)

Reference: `docs/reference/mcagent-workspace-approved.png`, 1672x941. Layout authority for desktop; backend is the data authority (never hard-code 62%, Completed, Passed, 1 Warning, 42.6s, Connected, Claude Sonnet 5).

## Geometry at 1672x941 (targets)
- Sidebar x 5-276 (272 px expanded, 64-72 collapsed), y 6-917, rounded 12-16 px, thin outline. Brand "McAgent" ~23px semibold, subtitle "2D→3D SolidWorks Pipeline" with "SolidWorks Pipeline" subtly gold; collapse chevrons top right; separator; large violet "+ New Project"; Home, Workspace (violet dim fill + 1px violet outline, white label), Projects, Pipeline Results, Recent Files; Help + Settings bottom.
- Header y 7-80 (72-80 px): square folder icon ~50px, "<Part> · Workspace" ~22px semibold + subtitle; right 3 bordered capsules (Engine, Deliverables, API Status), each icon + 2 lines. Narrow: compact badges/popover.
- Tracker x 299-1630, y 92-159 (~68 px): "Run Pipeline" heading, 5 nodes (Extraction, Resolution, Build Plan, Generation, Verification) joined by one continuous track (gold running ring + gold track portion + gold label; green check done with muted green line; gray pending; amber warning; red failed), right: "Stage N of 5", caption, progress meter only from real data.
- Main row y 181-804: 2D panel x 294-850 (~556 px), STL panel x 862-1314 (~452 px), inspector x 1331-1639 (~308 px, collapsible). Panels dark charcoal, hairline border, 10-14 px radii; viewer headers ~57 px; drawing on a white sheet inset 10-12 px; STL on a black-navy stage with metallic part, XYZ triad top right, floating bottom toolbar (orbit/reset, pan, zoom ±, fit, display mode).
- Inspector accordions: Part Setup (~125 px: Part Name, Parts Folder), Pipeline Actions (~141: gold Run Pipeline + Run All Parts + Run Demo), Corrections (~145: one-line input + purple "Re-run with correction"), Export (~174: SLDPRT/STL/VBA checkboxes + subdued Export Selected). NO View Appearance card.
- Bottom Pipeline Results strip x 293-1635, y 837-900 (60-65 px closed): chevron, "Pipeline Results", state chip, Verification, Engineering Flags, Runtime, end chevron; values only from the selected run; "No runs yet" when none.
- Grid: shell `var(--sidebar-w) minmax(0,1fr)`; content rows `auto auto minmax(0,1fr) auto`; center `minmax(0,1fr) minmax(0,1fr) 308px` tuned to the screenshot ratio; min-width:0; no overflow; ResizeObserver-driven viewers.

## Tokens (approximate, shared design-tokens.css; keep legacy aliases for photoapp)
bg #101114, sidebar #171921, panel #191B20, raised #20222B, hover #24262D, viewport #10131B, input #12141B, border #30323A, soft border rgba(181,191,211,.12), text #F2F2F4, text-2 #B9BBC6, muted #92949E, purple #9B8AFB (dark #35294E, hover #B0A1FF), gold #D6AF6B (bright #EAC783, on-gold #1D1610), ok #80CF91, warn #E3A93C, error #F06B77. Radii 6/10/14. Spacing 4-24. Fonts: Inter if bundled locally (licence OK; never CDN) else Segoe UI/system stack; mono Cascadia/Consolas. Sizes 11/12/13/14/15/22. Buttons 36-41 px. Icons: 1.7-2 px outline, rounded caps, 16-20 px (Lucide style, local SVG). No neon glows, gradients on page, blur/glass, grids, planets.
## Responsive
>=1500 match screenshot; 1250-1499 inspector narrower/collapsed; 900-1249 inspector hidden -> bottom Tools; 600-899 one viewer with 2D/3D switch + tools drawer; <600 icon nav, one viewer. No feature dropped.
## Acceptance
Compare running UI vs reference at exactly 1672x941 (side-by-side, region by region: sidebar, header, tracker, panels, inspector, bottom strip), then 1920x1080, 1440x900, 1280x800, 1024x768, 768, 390. Iterate until major differences resolved. Report remaining discrepancies honestly.
