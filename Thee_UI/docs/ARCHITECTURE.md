# ARCHITECTURE — 2D to 3D CAD

Front end for the MTI 2D drawing → SolidWorks part pipeline. The app lives in `Thee_UI/nebula-cad/`. This document is enough to rebuild the UI together with `DESIGN_SPEC.md` and `API_CONTRACT.md`.

## 1. Goals, in priority order

1. **Make a quietly wrong model impossible to miss.** A count mismatch, a low-confidence reading or an unverified result is always louder than a success.
2. Let a reviewer compare the source drawing and the generated model, review every extracted item, and sign off.
3. Show the cost of a run and a grade for the part.
4. Look and move like the Nebula Prime art direction without ever competing with the model.

## 2. Stack (versions verified 2026-11-16 with `npm view` and the GitHub API)

| Area | Package | Version |
|---|---|---|
| Framework | next (App Router, Turbopack) / react | 16.4.6 / 19.3 |
| Styling | tailwindcss v4, shadcn CLI | 4.3 / 4.23 |
| Motion | motion, gsap, @gsap/react | 14.14 / 3.15 / 2.1 |
| State and data | zustand, @tanstack/react-query, zod | 5.1 / 5.107 / 4.6 |
| Tables, lists | @tanstack/react-table, @tanstack/react-virtual | 9.3 / 3.14 |
| Forms, upload | react-hook-form, react-dropzone | 7.92 / 20.2 |
| Charts | recharts | 3.10 |
| 3D | three, @react-three/fiber, @react-three/drei, @react-three/postprocessing | 0.187 / 9.8 / 10.7 / 3.2 |
| CAD import | occt-import-js (LGPL-2.1, WASM) | 0.0.23 |
| Documents | pdfjs-dist, @react-pdf/renderer | 6.5 / 4.9 |
| UI utilities | lucide-react, sonner, cmdk | 1.73 / 2.0 / 1.1 |
| Tests | vitest, @playwright/test, @axe-core/playwright | 5.1 / 1.65 / 4.14 |

Repo check results: all 38 links resolve. Not archived and pushed within the last 6 months: shadcn/ui, Magic UI, React Bits, Lucide, Sonner, react-dropzone, react-hook-form, TanStack Table/Query/Virtual, Zustand, Zod, Recharts, pdf.js, react-pdf, Motion, GSAP, Lenis, tsParticles, rive-react, three.js, R3F, drei, react-postprocessing, three-cad-viewer, Online3DViewer, Playwright, Vitest, axe-core, Storybook, visx, Arwes.

Exceptions:

| Repo | Finding | Action |
|---|---|---|
| `tsparticles/react` | **archived** (last push 2026-04) | Not used. Stars are a CSS layer. |
| `theatre-js/theatre` | last push 2024-08 | Not used. Camera moves are done in R3F. |
| `donalffons/opencascade.js` | last push 2023-08 | Not used. No client-side kernel operations are needed. |
| `kovacsv/occt-import-js` | last push 2024-12, v0.0.23 | Used. It is small, stable, and the only maintained browser STEP importer in the list. LGPL notice is on the Docs page. |
| `dip/cmdk` | last push 2025-10 | Used through shadcn Command. Stable. |
| `greensock/GSAP` | no SPDX license | Standard GSAP license; noted on the Docs page. |

## 3. Route map

| Route | Purpose |
|---|---|
| `/` | redirects to `/dashboard` |
| `/dashboard` | Hero, KPIs, viewer, pipeline, workspace tabs, quick actions, right rail (the mockup) |
| `/projects` | Project list (grid/table), search, status filter |
| `/projects/[id]` | **The workstation**: compare, viewer, extraction review, build plan, pipeline, six tabs |
| `/automation` | New run wizard: upload file or folder → options → estimate → run → live progress |
| `/models` | Generated parts with grade, validation, cost, revision |
| `/pipelines` | Queue and run history, filters, retry, cancel, drill-down |
| `/viewer/[id]` | Full-screen model viewer; also loads a local STL/STEP file |
| `/library` | Parameter presets, rubric templates, materials, rate cards |
| `/docs` | In-app docs: pipeline, validation checks, rubric guide, cost formulas, shortcuts, licenses |
| `/settings` | Units, materials, cost rates, budget, rubric defaults, density, motion, API base URL |
| `/welcome` | Stretch landing page |

## 4. Component tree

```
app/layout.tsx                 fonts, <Nebula/>, <Providers/> (QueryClient, MotionConfig, Toaster)
  components/shell/AppShell    TopNav · Sidebar · <main> · ContextRail · CommandPalette · ShortcutsDialog · NotificationCenter · OnboardingTour
  app/dashboard                Hero · KpiRow · ModelViewerCard · PipelineCard · WorkspaceTabs · QuickActions
  app/projects/[id]            ProjectHeader · FailureBanner · ComparePanel(DrawingViewer | ModelViewer) · ReviewPanel(ExtractionReview | BuildPlan | Comments | Revisions | Audit) · PipelineCard · WorkspaceTabs
components/
  shell/      TopNav Sidebar ContextRail CommandPalette ShortcutsDialog NotificationCenter Nebula CornerLightning OnboardingTour
  hero/       Hero EnergyWaves
  kpi/        KpiCard Sparkline NumberTicker
  viewer/     ModelViewer (R3F scene, lazy) ViewerToolbar FeatureMarkers DimensionCallout MeasureTool
  compare/    ComparePanel DrawingViewer (pdf.js, lazy) RegionOverlay ModelOutlineOverlay
  extraction/ ExtractionReview BuildPlanReport CommentsPanel RevisionsPanel AuditPanel
  pipeline/   PipelineTimeline PipelineStep
  workspace/  WorkspaceTabs ParametersTab FeaturesTab ValidationTab LogsTab QuickActions ExportCenter
  cost/       CostTab RunCostPanel ManufacturingPanel RoiPanel
  rubric/     RubricTab CriterionCard SignOff RubricPdf (lazy)
  shared/     Glass SampleBadge DemoTag StatusStamp ConfidenceBar EmptyState ErrorState Skeletons PageHeader
  ui/         shadcn primitives
lib/
  schemas/    Zod schemas (single source of types)
  api/        adapter.ts (interface) · mock.ts · http.ts · index.ts (selects by env) · hooks.ts (TanStack Query)
  data/       part-specs.json · seed.ts (sample projects) · generated/*.json (written by the sample generator)
  cost/       pure cost math + tests
  rubric/     pure rubric math + tests
  validation/ pure helpers (gating, summaries) + tests
  motion/     tokens and variants
  cad/        loaders (STL, STEP via occt-import-js), part geometry from specs
  store/      zustand stores (ui, selection, settings)
scripts/gen-samples.mjs        writes synthetic drawing PDFs, STL files and region metadata
tests/        unit (vitest) · e2e (playwright + axe)
```

## 5. State and data flow

- **Server state** (projects, extraction, validation, runs, rubric, audit…) goes through `lib/api` only. Components call hooks in `lib/api/hooks.ts`; hooks call the active adapter; every response is parsed with its Zod schema, so a malformed backend payload becomes a visible error state, never a silently wrong screen.
- **Adapter selection:** `NEXT_PUBLIC_API_MODE=mock|http` (default `mock`). `http` reads `NEXT_PUBLIC_API_BASE_URL`. Both implement the same `ApiAdapter` interface.
- **Mock adapter:** an in-memory database seeded from `lib/data/seed.ts`, persisted to `localStorage` so reviews, overrides and sign-offs survive a reload. Settings has "Reset sample data". Every object it returns carries `isSample: true`, and the UI shows a SAMPLE DATA badge wherever `isSample` is set.
- **UI state** (zustand): `selection` (selected extraction item, feature, check — shared by the drawing, viewer, tables), `ui` (rail open, palette open, active tab, compare mode), `settings` (units, density, motion, cost rates, rubric defaults; persisted).
- **Derived state is pure.** Cost, rubric scores, export gating and validation summaries are computed by pure functions in `lib/cost`, `lib/rubric`, `lib/validation`. Components never do this math inline.
- **Selection sync:** selecting an extraction item sets `selection.itemId` and, when the item has one, `selection.featureId`. The drawing viewer pans to the item's region; the model viewer shows a gold marker at the feature locator from the build plan.

```
user action → hook (mutation) → adapter → (mock db | fetch) → Zod parse → query cache → components
                                   ↘ audit event appended for every approve/edit/reject/override/sign-off
```

## 6. Honesty rules as code

| Rule | Mechanism |
|---|---|
| Mock values are labeled | `isSample` on every mock entity → `<SampleBadge/>`; a persistent "Sample data mode" chip in the top nav |
| No Passed without a run | `ValidationCheck.status` has `not_run`; summaries count it separately; the rubric scores a not-run auto criterion as 0 "missing" |
| Critical failures block export | `lib/validation/gating.ts → exportGate(checks)`; ExportCenter and Quick Actions read it; override needs a reason and writes an audit event |
| Rubric cap | `lib/rubric → releaseStatus()` caps at Needs rework while any hard-fail gate is un-overridden |
| No fake interactivity | Viewer shows "Static preview" until geometry is loaded; controls that cannot work in mock mode carry `<DemoTag/>` |
| Simulated runs | A run started in mock mode is labeled "Simulated run". An uploaded user drawing gets no fabricated extraction. |

## 7. Performance budget

- Dynamic imports: `ModelViewer` (three, R3F, postprocessing), `DrawingViewer` (pdf.js), `RubricPdf`/report export (@react-pdf), Recharts panels. GSAP is imported only by `EnergyWaves` and `CornerLightning`.
- At most 10 `backdrop-filter` elements per screen, never nested, never on the canvas container.
- Ambient animation: 3 at once at most, `transform`/`opacity` only, paused on `visibilitychange`.
- R3F `frameloop="demand"`: the canvas renders only when the camera or scene changes.
- Logs are virtualized.
- Targets: Lighthouse Performance ≥ 90 on `/welcome`, Accessibility ≥ 95 on `/dashboard`.

## 8. Testing strategy

| Layer | Tool | Scope |
|---|---|---|
| Unit | Vitest | `lib/cost` (formulas, quantity breaks, ROI), `lib/rubric` (weights, bands, hard-fail cap, override), `lib/validation` (gating), schema parsing of the seed |
| E2E smoke | Playwright | each route renders without console errors; the loud-failure flow end to end |
| Accessibility | axe via Playwright | each route, serious and critical violations fail |
| Visual | Playwright screenshots | every route at 1440×900, 1024×768, 390×844 into `docs/screenshots/` |

## 9. Security and safety

- No secrets in the client. `NEXT_PUBLIC_API_BASE_URL` is a URL, not a credential. The backend owns model API keys.
- Uploads: allow-list of extensions (`pdf png jpg jpeg dxf dwg stl step stp iges igs brep`), 50 MB per file, 200 files per folder. PDFs render client-side only.
- Sample drawings and models are synthetic and generated by `scripts/gen-samples.mjs`. No MTI drawing is shipped.

## 10. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | The three brief files and the mockup were absent from `Thee_UI/`; they were copied from `~/Downloads`. The earlier pipeline-focused `Thee_UI/CLAUDE.md` was renamed `PIPELINE_UI_CONTRACT.md`. | The brief names itself `CLAUDE.md` in this folder. Nothing was deleted. |
| D2 | No nested `git init` in `Thee_UI/`. Commits go to a new branch `feat/nebula-cad-ui` of the existing repo. Never pushed. | `Thee_UI/` already sits inside a git repo; a nested repo would hide the UI from it. The pipeline STL change lives in the same repo. |
| D3 | **`DESIGN.md` (Blueprint Room) vs Nebula Prime.** Nebula Prime wins on everything visual (palette, glass, type, motion). `DESIGN.md` supplies the *semantics*: file/folder intake, the PDF and STL views, pipeline-state vocabulary (pending, running, done, skipped, failed, aborted), outlined inspection stamps for severity and verdicts, confidence and tier chips, "skipped is not failed", mono tabular numerals for every measurement. | The brief says `CLAUDE_NEBULA_PRIME.md` is authoritative for look and feel; the user asked for the tabs to be based on `DESIGN.md`. Both hold if the Blueprint ideas are re-skinned. |
| D4 | The viewer's primary format is **STL**, with STEP/IGES/BREP through occt-import-js as the second path. | The user asked for an STL view and for the pipeline to save an STL beside each `.sldprt`; the backend can now always serve one. STEP stays for B-rep-accurate display. |
| D5 | Magic UI, Aceternity and React Bits components are not installed from their registries. Small in-house equivalents (`NumberTicker`, `BorderBeam`, `Spotlight`, `EnergyWaves`) follow the same ideas. | They are needed in 4 places; in-house versions share the motion tokens and reduced-motion handling, and avoid three more style systems. |
| D6 | Skipped optional libraries: tsParticles, Rive, Theatre.js, Storybook, visx. Lenis only if `/welcome` ships with scroll choreography. | Not needed for any requirement; two of them are stale or archived. |
| D7 | "Grading rubric" keeps the brief's reading: it grades the generated part against its source drawing. | It matches the hard-fail gates and the sign-off flow. |
| D8 | Extraction review, build plan, comments, revisions and audit live in a **Review panel** beside the compare view, not in the lower tabs. | The lower tab set is fixed at six, with Rubric last. |
| D9 | "Overlay" compare mode draws the **modeled geometry outline as SVG over the drawing's front view**, using a registration (origin + scale) supplied by the backend. | A WebGL overlay cannot be registered pixel-exact to a scanned sheet; an outline can, and it shows an 8-vs-10 hole mismatch at a glance. Without a registration the mode is disabled with the reason. |
| D10 | Feature highlight in the viewer uses **gold markers at build-plan locators**, not per-face mesh selection. | An STL has no feature identity. Locators come from the build plan, so the highlight is exact and honest. |
| D11 | A run started in mock mode on a user's own file produces **no extraction**. Only the bundled sample drawings map to seeded results. | Never fake an extraction or a validation for a real drawing. |
| D12 | Warning color is orange-amber `#FF9A3D`, not the champagne gold. | Gold means priority/active/complete; a warning must not look like a completed state. |
| D13 | Uploaded files in mock mode are kept as in-memory object URLs and are lost on reload (stated in the UI). | No backend to store them; IndexedDB persistence is not worth the complexity for a mock. |

## 11. Features added beyond the brief's lists

| Addition | Why it earns its place |
|---|---|
| Modeled-outline overlay on the drawing (D9) | The fastest way for a human to see a quiet count error. |
| Count-check strip (drawing callout vs extracted vs modeled) above the review table | The central failure is a count mismatch; it gets a permanent, top-of-panel readout. |
| Export gate reasons listed inside the export dialog | A blocked button with no reason trains people to look for workarounds. |
| "Reset to extracted value" and per-row source link in Parameters | Every edit stays traceable to the drawing. |
| Reviewer queue ordering (conflict → needs review → verified, then lowest confidence first) | A reviewer's time goes to the riskiest items first. |
| Reviewer identity in Settings (name used for sign-off and audit) | Sign-off needs a name; mock mode has no auth. |
| "Reset sample data" in Settings | Lets a demo be re-run from a known state. |

Added during the ideas pass: link-zoom between drawing and model; section plane and measure tool in the viewer; parameter presets (Library) that apply to the focused project; revision compare dialog; confidence heatmap; Diff mode that opens automatically when a count mismatch exists; Export center rows disabled with the gate reason; `/welcome` landing page; D14: `cacheComponents` is off in next.config because every screen is client-rendered against the adapter.
