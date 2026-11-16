# CLAUDE.md: Build the Nebula CAD UI (master brief for Claude Fable 5.2)

You are Claude Fable 5.2 working autonomously in this folder (`Thee_UI/`). Your job is to architect, design, build, polish and finalize the complete UI for a 2D-to-3D CAD automation product. Work through the whole brief in this session. Do not stop at a first draft. Keep improving until every item in the Definition of Done (section 16) is met.

---

## 1. What the product is

The product (working name **Nebula CAD**) is the front end for an AI pipeline built at MTI (Manufacturing Technology Incorporated). The pipeline:

1. Takes a scanned legacy 2D engineering drawing (PDF, some up to 40 years old, no matching 3D model).
2. Reads it with a Claude vision model and extracts structured geometry (dimensions, holes, features, tolerances, units).
3. Produces an executable **build plan**.
4. Drives SolidWorks in a batch pipeline to construct the part and output a complete **feature tree**.
5. Hands the result to a human for verification (download, inspect, edit if needed).

The UI must support the full loop: drawing intake, live side-by-side comparison of the original drawing and the resulting model, real-time visibility into extraction, a build plan report, validation, human sign-off, cost, and grading.

**The central UX lesson of this project:** the tool does not fail loudly. It fails quietly and hands you a confident but wrong model (for example, an incorrect hole count on a part). Every screen you design must make mismatches, low confidence and unverified results impossible to miss. Treat "looks right but is wrong" as the main risk and design against it.

---

## 2. Files in this folder (read all of them first)

| File | Role |
|---|---|
| `CLAUDE.md` | This master brief. Highest authority on scope, process and deliverables. |
| `CLAUDE_NEBULA_PRIME.md` | Art direction and visual identity (colors, lighting, effects, typography, acceptance criteria). Authoritative for look and feel. |
| `NEBULA_PRIME_STACK.md` | Design addendum: glassmorphism CSS system, repo stack with links, component map, tab definitions, setup commands. Treat as a strong starting point, not a cage. You may improve it and must record changes. |
| `reference/nebula-mockup.png` | Target composition. Match its layout and mood, then exceed its polish. |
| `docs/` | You write here: `ARCHITECTURE.md`, `DESIGN_SPEC.md`, `API_CONTRACT.md`, `PROGRESS.md`, `QA_CHECKLIST.md`. |

If documents conflict: this file wins on scope and process, `CLAUDE_NEBULA_PRIME.md` wins on visual identity, `NEBULA_PRIME_STACK.md` wins on implementation detail. Log any conflict and your resolution in `docs/ARCHITECTURE.md` under "Decisions".

Hard art-direction rules that never change: no planet, moon, globe or large celestial body anywhere. Violet is atmospheric only. Gold marks priority, active and completed states. Keep stars extremely sparse. No strobing, no particle storms, no thick neon outlines.

---

## 3. How to work (process rules)

1. Create a task list at the start and keep it current. The last task is always verification.
2. Think through the architecture deeply before writing UI code. Write the docs in Phase 1, then build.
3. Make reasonable decisions yourself and record them. Only stop to ask the user if a decision is irreversible and could reasonably go either way.
4. Look at your own work. Run the dev server, open it in a browser (Claude in Chrome or the built-in browser, whichever is available, plus Playwright for repeatable screenshots), and compare against `reference/nebula-mockup.png`. Never judge a UI from code alone.
5. Work in a project subfolder: the app lives in `Thee_UI/nebula-cad/`. Docs stay in `Thee_UI/docs/`.
6. Use `git init` in `Thee_UI/` and make local commits at each milestone. Never push. Never commit `.env` files or secrets.
7. Prefer your file tools for file work. Run long builds and installs in the shell.
8. Keep `docs/PROGRESS.md` updated at every milestone: what is done, what was changed in polish passes, what is left.
9. For the final audit, use a separate reviewer (a subagent that has not seen your work) to check the app against `docs/QA_CHECKLIST.md` and this brief. Fix what it finds.

---

## 4. Phases and exit criteria

**Phase 0: Research and verify (do this first)**
- Open every repo link in section 6. Confirm it exists, is maintained (recent commits, not archived), and check current stable versions and install commands. Swap out anything dead and note it in `docs/ARCHITECTURE.md`.
- Study the reference sites in section 9 with WebSearch, WebFetch and the browser. Extract principles (spacing, hierarchy, motion timing, hover behavior, scroll choreography). Do not copy their assets, copy, logos or exact layouts.
- Exit: a short "Research notes" section in `docs/DESIGN_SPEC.md`.

**Phase 1: Architect and design (docs before code)**
- Write `docs/ARCHITECTURE.md`: route map, component tree, state and data flow, adapter and mock strategy, folder structure, performance budget, testing strategy, decisions log.
- Write `docs/DESIGN_SPEC.md`: tokens, type scale, spacing grid, radii, elevation, glass tiers, color usage rules, motion tokens, per-screen wireframes (ASCII is fine), empty, loading and error states.
- Write `docs/API_CONTRACT.md`: the endpoints and Zod schemas the real backend (SolidWorks automation service) must implement (section 8).
- Exit: another engineer could build the UI from these three docs.

**Phase 2: Foundation**
- Scaffold, tokens, fonts, `.nebula` background, glass system, app shell (TopNav, Sidebar, ContextRail), routing, command palette, toasts, mock data layer with SAMPLE DATA badges.

**Phase 3: Features (section 7)**
- Build every screen and every tab. Wire everything through the adapter layer so mock and real data share one interface.

**Phase 4: Motion and polish (section 10)**
- Add the full motion system. Then run the polish loop (section 12).

**Phase 5: Verify and finalize (section 14, 16)**
- Tests, accessibility, performance, responsive pass, reviewer audit, docs final.

---

## 5. Stack

- Next.js (App Router) + React + TypeScript (strict) + Tailwind CSS + shadcn/ui.
- Motion (`motion/react`) for component animation, GSAP (+ `@gsap/react`) for SVG and timelines, React Three Fiber for the viewer, Zustand for UI state, TanStack Query for data, Zod for schemas.
- Fonts: Inter (headings, nav, UI) and JetBrains Mono (dimensions, parameters, filenames, units, logs, numeric readouts) via `next/font`.
- Package manager: npm unless the repo already uses another.

Use one animation tool per job: Motion for component state and layout, GSAP for SVG paths and complex timelines, R3F for anything inside the 3D canvas. Do not animate the same property from two libraries.

---

## 6. Repos and links (verify all in Phase 0)

### UI and components
| Repo | Link | Use |
|---|---|---|
| shadcn/ui | https://github.com/shadcn-ui/ui | Base primitives (Tabs, Table, Dialog, Input, Command, Tooltip, ScrollArea, Sheet, Select, Slider, Switch) |
| Magic UI | https://github.com/magicuidesign/magicui (components: https://magicui.design/docs/components) | Number Ticker, Border Beam, Animated Beam, Shimmer Button. Do NOT use its Globe component. |
| Aceternity UI | https://ui.aceternity.com (author: https://github.com/manuarora700) | Spotlight, Background Beams, tilt cards. Install example: `pnpm dlx shadcn@latest add @aceternity/background-beams` |
| React Bits | https://github.com/DavidHDev/react-bits (docs: https://reactbits.dev) | One atmospheric background, text effects. Example: `npx shadcn@latest add @react-bits/Aurora-TS-TW` |
| Arwes (reference only) | https://github.com/arwes/arwes | Inspiration for frames. Do not ship it: no React strict mode or Server Components support. |
| Lucide | https://github.com/lucide-icons/lucide | Icons (gold outline style) |
| Sonner | https://github.com/emilkowalski/sonner | Toasts |
| cmdk | https://github.com/dip/cmdk | Command palette (shadcn Command is built on it) |
| react-dropzone | https://github.com/react-dropzone/react-dropzone | Drawing upload |
| react-hook-form | https://github.com/react-hook-form/react-hook-form | Forms (settings, rates, rubric editing) |

### Data, tables, charts, documents
| Repo | Link | Use |
|---|---|---|
| TanStack Table | https://github.com/TanStack/table | Parameter and feature tables |
| TanStack Query | https://github.com/TanStack/query | Data fetching and cache |
| TanStack Virtual | https://github.com/TanStack/virtual | Virtualized log stream |
| Zustand | https://github.com/pmndrs/zustand | UI state |
| Zod | https://github.com/colinhacks/zod | Schemas and runtime validation |
| Recharts | https://github.com/recharts/recharts | Cost and performance charts (or visx: https://github.com/airbnb/visx) |
| pdf.js | https://github.com/mozilla/pdf.js | Render the source drawing PDF in the browser |
| react-pdf (renderer) | https://github.com/diegomura/react-pdf | Export rubric, cost and build-plan reports as PDF |

### Animation
| Repo | Link | Use |
|---|---|---|
| Motion | https://github.com/motiondivision/motion (docs: https://motion.dev) | Hover, tabs (`layoutId`), `AnimatePresence`, stagger, `MotionConfig reducedMotion="user"` |
| GSAP | https://github.com/greensock/GSAP (React guide: https://gsap.com/resources/React) | DrawSVG lightning tracers, MorphSVG energy waves, timelines. All plugins are free, but the license bars building tools that compete with Webflow's visual animation builder. |
| Lenis | https://github.com/darkroomengineering/lenis | Smooth scroll, landing route only |
| tsParticles | https://github.com/tsparticles/tsparticles (React: https://github.com/tsparticles/react) | Optional sparse stars. A few CSS or SVG dots may be enough. |
| Rive | https://github.com/rive-app/rive-react | Optional: status indicators with state machines |
| Theatre.js | https://github.com/theatre-js/theatre | Optional: choreograph the viewer reveal |

### 3D and CAD viewer
| Repo | Link | Use |
|---|---|---|
| three.js | https://github.com/mrdoob/three.js | Renderer |
| React Three Fiber | https://github.com/pmndrs/react-three-fiber | React renderer |
| drei | https://github.com/pmndrs/drei | OrbitControls, Environment, GizmoHelper (XYZ triad), Html (dimension callouts) |
| react-postprocessing | https://github.com/pmndrs/react-postprocessing | Bloom (gold rim light), Vignette, subtle Noise. Tip: bloom threshold 1, then drive glow with `toneMapped={false}` and emissive above 1. |
| occt-import-js | https://github.com/kovacsv/occt-import-js | Load real STEP, IGES and BREP in the browser via WASM. LGPL 2.1: note it in the licenses page. |
| Online 3D Viewer | https://github.com/kovacsv/Online3DViewer | Reference or embeddable engine |
| three-cad-viewer | https://github.com/bernhard-42/three-cad-viewer | Reference for clipping planes, measurement, tree navigation (MIT) |
| opencascade.js | https://github.com/donalffons/opencascade.js | Only if you need OCCT kernel operations client-side |

### Quality and testing
| Repo | Link | Use |
|---|---|---|
| Playwright | https://github.com/microsoft/playwright | Screenshots, e2e smoke tests, responsive checks |
| Vitest | https://github.com/vitest-dev/vitest | Unit tests (cost and rubric math) |
| axe-core | https://github.com/dequelabs/axe-core | Accessibility audits |
| Storybook (optional) | https://github.com/storybookjs/storybook | Component states catalog |

### Setup commands (run in order from `Thee_UI/`)
```bash
npx create-next-app@latest nebula-cad --typescript --tailwind --eslint --app
cd nebula-cad
npx shadcn@latest init
npx shadcn@latest add tabs table input button card tooltip scroll-area command sheet dialog select slider switch badge progress separator skeleton
npm install motion gsap @gsap/react zustand zod @tanstack/react-query @tanstack/react-table @tanstack/react-virtual react-hook-form react-dropzone recharts sonner lucide-react
npm install three @react-three/fiber @react-three/drei @react-three/postprocessing occt-import-js pdfjs-dist @react-pdf/renderer
npm install -D @types/three vitest @playwright/test @axe-core/playwright
cp node_modules/occt-import-js/dist/occt-import-js.wasm public/occt-import-js.wasm
npx playwright install chromium
```
Add Aceternity, React Bits and Magic UI components per their docs only as needed.

---

## 7. Screens, tabs and features (build all of it)

### 7.1 Navigation (from `CLAUDE_NEBULA_PRIME.md`, keep exactly)
- **Top nav tabs:** Dashboard, Projects, Automation, Models, Pipelines, Docs. Search, notifications, avatar. Gold cube logo, NEBULA CAD wordmark.
- **Left sidebar:** Dashboard, Projects, Automation, CAD Viewer, Pipelines, Library, Settings. Recent projects with thumbnails. System Online status (GPU, queue) at the bottom, driven by real or clearly labeled sample data.
- **Right context rail:** Project Overview, Performance, Activity. Collapsible, hidden on small screens.

### 7.2 Routes
`/dashboard`, `/projects`, `/projects/[id]` (the workstation), `/automation` (new run), `/models`, `/pipelines`, `/viewer/[id]` (full-screen), `/library`, `/docs`, `/settings`. Optional stretch: `/welcome` (advertising-grade landing page, see 9.3).

### 7.3 Dashboard (matches the mockup)
Hero ("From Drawings to CAD", gold Generate CAD, outlined Upload Drawing, violet and gold energy waves on the right, no planet), four KPI glass cards (models generated, validation rate, average build time, pipeline errors) with micro-sparklines, model viewer, automation pipeline, lower workspace tabs, quick actions, right rail.

### 7.4 The workstation (`/projects/[id]`)
- **Drawing and model compare** (the core feature): side-by-side original drawing (pdf.js) and resulting model (R3F). Synchronized pan and zoom where possible. Click an extracted dimension to highlight its region on the drawing and the matching feature on the model. Toggle overlay, split slider, and diff mode.
- **Model viewer:** orbit, zoom, fit, fullscreen, section plane, measure tool, XYZ triad, dimension callouts, selected-edge gold highlight. Load real STEP via occt-import-js. Until a real file loads, show a clearly labeled "Static preview" state. Never pretend a static image is interactive.
- **Extraction review:** table of every extracted item (dimension, hole, feature, tolerance, unit) with a confidence value, source region on the drawing, and a status (Verified, Needs review, Conflict). Reviewer can approve, edit or reject each item. Low-confidence and count mismatches are loud (amber and red states, banner, sorted to the top).
- **Build plan report:** ordered operations with parameters, expandable, exportable.
- **Pipeline timeline (vertical):** Analyze Drawing, Extract Features, Generate CAD Model, Validate Geometry, with real statuses and timings when connected, plus retries and failure states.
- **Quick actions:** New Model, Clone, Export (SLDPRT, STEP, PDF report, JSON build plan).

### 7.5 Lower workspace tabs (order is fixed; Rubric is the final tab)
**Parameters | Features | Validation | Cost | Logs | Rubric**

- **Parameters:** editable engineering table (Parameter, Value, Unit, Tolerance, Range, Source). JetBrains Mono, right-aligned numbers, gold focus rings, range check on blur, never silently clamp, undo and reset to extracted value.
- **Features:** feature tree from the build plan (sketch, extrude, hole, fillet and so on). Selecting a node highlights it in the viewer in gold. Shows feature count extracted vs modeled.
- **Validation:** list of real checks with Passed, Failed, Warning or Not run. Required checks: feature counts match the extraction (holes in particular), bounding box vs drawing, per-dimension deltas vs tolerance, unit consistency, rebuild errors, sketch fully defined, watertight geometry. **Never show Passed for a check that did not run.** A failed critical check blocks export until a human resolves or overrides it with a recorded reason.
- **Cost:** see 7.6.
- **Logs:** virtualized, monospace, level filters, search, copy, follow-tail toggle. Real output only, demo logs tagged Demo.
- **Rubric:** see 7.7. This is the final tab.

### 7.6 Cost (new, required)
Two clearly separated panels plus a comparison.

**A. Pipeline run cost (AI and compute):** per stage and per run: input and output tokens, vision calls, retries, compute seconds, cost per part, cost per batch, trend sparkline, monthly total, optional budget guardrail with a warning state. Rates are editable in Settings. Seed values must be labeled "ASSUMPTION: verify against current provider pricing" and a persistent notice shows until the user confirms the rates.

**B. Part manufacturing estimate:** material (from model volume, stock allowance and scrap), machining time (removed volume over a removal rate plus per-feature times for holes and so on), setup, finishing, inspection, overhead, margin, with quantity breaks (1, 10, 100). Material densities (real constants): steel 7.85, stainless 8.0, aluminum 2.70, titanium 4.43 (g/cm3). All dollar rates are editable assumptions labeled ESTIMATE. Show an expandable "How this is calculated" with the exact formulas.

```
material_cost = part_volume_cm3 * (1 + stock_allowance) * density_g_cm3 / 1000 * price_per_kg * (1 + scrap_pct)
machining_min = (stock_volume_cm3 - part_volume_cm3) / mrr_cm3_per_min + holes * t_hole_min + features * t_feature_min
unit_cost     = (material_cost + machining_min / 60 * machine_rate + setup_cost / qty + finishing + inspection) * (1 + overhead) * (1 + margin)
```

**C. Automation ROI:** manual rebuild hours times labor rate vs (pipeline cost plus human review time times labor rate). Show savings per part and cumulative, with the assumptions visible.

Put all cost math in a pure, unit-tested TypeScript module (`lib/cost/`). Charts with Recharts, animated draw-in, tooltips in JetBrains Mono.

### 7.7 Rubric (new, required, final tab)
A grading rubric for each generated part against its source drawing. Interpretation: it scores the quality of the generated 3D part. If you judge a better reading of "grading rubric", record it in `docs/ARCHITECTURE.md`.

Default criteria (weights editable, must sum to 100):

| Criterion | Weight | Scored by |
|---|---|---|
| Dimensional accuracy | 25 | Auto from validation deltas |
| Feature completeness and counts | 20 | Auto from extraction vs model counts |
| Tolerance and unit compliance | 15 | Auto |
| Geometry validity (rebuild clean, watertight, sketches defined) | 15 | Auto |
| Feature tree quality (naming, order, editable parametric dimensions) | 10 | Reviewer |
| Manufacturability | 5 | Reviewer |
| Documentation and traceability (build plan, sign-off) | 10 | Mixed |

Each criterion has four level descriptors (Exemplary 4, Proficient 3, Developing 2, Insufficient 1, with 0 for missing), an evidence list that links to the validation check or the drawing region that supports the score, and a reviewer comment box. Show a total score, a grade band (A 90+, B 80+, C 70+, below 70 Needs rework) and a release status: Approved, Approved with notes, Needs rework.

**Hard-fail gates:** any critical mismatch (wrong feature count such as hole count, a critical dimension out of tolerance, rebuild errors) caps the release status at Needs rework until a reviewer overrides it with a recorded reason. Show the cap visibly with the reason.

Reviewer sign-off with name and timestamp, rubric templates (save, load, duplicate), score history per revision, export as PDF and JSON. Rubric math lives in a pure, unit-tested module (`lib/rubric/`).

### 7.8 Other pages
- **Automation:** new run wizard (upload one or many drawings, choose material and units, choose pipeline preset, estimated cost and time before you run, then run). Live progress.
- **Pipelines:** batch queue and run history with filters, ETA, retry, cancel, per-run drill-down.
- **Models:** grid and table of generated parts with rubric grade, validation status, cost, revision, thumbnails.
- **Library:** reusable parameter presets, rubric templates, materials and rate cards.
- **Docs:** in-app documentation: how the pipeline works, what each validation check means, rubric guide, cost formulas, keyboard shortcuts, licenses (include the LGPL notice for occt-import-js).
- **Settings:** units, materials, cost rates, budget, rubric defaults, density (comfortable or compact), motion intensity (full, reduced), API base URL. Never store secrets client-side.

### 7.9 Additional features (you are expected to add what the project needs)
Add these, plus anything else that serves the product, and justify each addition in `docs/ARCHITECTURE.md`. Do not add bloat.
- Command palette (Cmd or Ctrl K): jump to project, run action, switch tab.
- Keyboard shortcuts with a cheat-sheet dialog.
- Confidence heatmap overlay on the drawing.
- Revision history with side-by-side compare of two revisions.
- Comments and annotations pinned to drawing regions.
- Audit trail (who approved, edited or overrode what, and when).
- Notifications center driven by real events (run finished, validation failed, budget warning).
- Export center (all deliverables for a part in one place).
- Onboarding tour for first run, and designed empty states for every list.
- Offline-safe error states and retry affordances everywhere.

---

## 8. Data layer and honesty rules

- All data goes through an **adapter** interface (`lib/api/`). Two implementations: `mock` (default) and `http` (real, using `NEXT_PUBLIC_API_BASE_URL`). A single env var switches them.
- Define Zod schemas for `Drawing`, `ExtractionItem`, `ExtractionResult`, `BuildPlan`, `PipelineRun`, `PipelineStage`, `ValidationCheck`, `CostEstimate`, `RubricTemplate`, `RubricScore`, `Revision`, `AuditEvent`. Document endpoints and payloads in `docs/API_CONTRACT.md` so the real SolidWorks service can implement them.
- Every mock value shows a visible **SAMPLE DATA** badge. Every non-functional control is tagged **Demo** or removed. No control may look interactive and do nothing.
- Seed one mock project that demonstrates the central failure: the drawing shows 10 holes, extraction found 8. Validation fails, the banner is loud, export is blocked, the rubric is capped at Needs rework. Use this as the showcase of why the tool exists. Also seed a clean, passing project.
- Never fake validation, confidence or a pass state.

---

## 9. Visual direction beyond the mockup

### 9.1 Reference companies (study, then extract principles; never copy assets, copy or exact layouts)
Linear (precision, restrained gradient borders, typographic discipline), Vercel (clarity, grid, deployment-status patterns), Stripe (depth, gradient craft, scroll-linked storytelling, excellent docs), Raycast (command palette, glass, colored glow), Framer (kinetic micro-interactions), Apple product pages (scroll choreography, product reveals). For CAD-specific patterns: Onshape, Autodesk Fusion, Figma (dense panels done well).

### 9.2 Principles to apply
Strong hierarchy with one clear focal point per screen (the model). An 8px spacing grid. Consistent radii (12 to 16px) and elevation steps. One accent system (gold for priority, violet for atmosphere). Progressive disclosure so dense engineering data stays calm. Skeleton loaders instead of spinners. Numbers always animate in once. Every state (empty, loading, error, success) designed, not defaulted.

### 9.3 Stretch: `/welcome` landing page
Advertising-grade page: scroll-choreographed hero, a "how it works" four-step sequence, a live viewer demo, an animated metrics strip, trust and process section, final call to action. Lenis for smooth scroll on this route only. Same art direction rules.

---

## 10. Motion system (throughout, not decorative sprinkles)

Define motion tokens in `DESIGN_SPEC.md` and implement them once (`lib/motion/`): durations (micro 150 to 200ms, standard 200 to 250ms, entrance 400 to 600ms, ambient 8 to 16s), easings, one spring config. Required choreography:

- **Page load sequence:** nav slides and fades in, sidebar items stagger, hero headline reveals, KPI cards rise with number count-up, viewer fades in with a slow camera ease, pipeline steps stagger. Once per session, not on every navigation.
- **Route transitions:** short cross-fade with a subtle shift.
- **Tabs:** shared-layout gold pill (`layoutId`) and content cross-fade.
- **Cards and buttons:** hover lift with border glow, press feedback, gold focus rings.
- **Pipeline:** progress line fills, active step pulses softly, completion plays a restrained gold sweep (no confetti).
- **Tables and lists:** row enter and exit with `AnimatePresence`, edited cells flash a gentle gold confirmation.
- **Charts:** draw-in on first view.
- **Viewer:** smooth camera transitions for Fit, Reset and feature focus. Selected feature glows gold.
- **Ambient:** violet energy waves and corner lightning arcs, slow and low contrast, behind glass only.
- **Feedback:** toasts slide in, validation failures shake once subtly then settle into a persistent banner.

Rules: respect `prefers-reduced-motion` and `prefers-reduced-transparency` everywhere (Motion `reducedMotion="user"`, GSAP matchMedia, CSS media queries). Ambient animation pauses when the tab is hidden. At most a few ambient animations at once. Animate only `transform` and `opacity` where possible. 60fps budget. Blur budget: roughly 10 `backdrop-filter` elements on screen, never nested, never on the WebGL canvas container. Provide a Settings control for motion intensity.

---

## 11. Quality bar

- WCAG AA contrast on glass (raise fill alpha where lightning sits behind text), full keyboard navigation, semantic HTML, labeled controls, visible focus, ARIA for custom widgets (tabs, tree, table, dialogs).
- Responsive: desktop first (1440 and 1920), then 1024 (rail collapses to a sheet), 768 (sidebar collapses to icons or drawer), mobile (single column, viewer first).
- No layout shift, no console errors or warnings, no hydration mismatches.
- Performance: dynamic-import the 3D viewer, pdf.js and report renderer. Load GSAP only where used. Landing target Lighthouse Performance 90 or better, Accessibility 95 or better on the dashboard.
- TypeScript strict, ESLint clean, no `any` without a comment.
- Tests: Vitest for cost and rubric math (including the hard-fail cap), Playwright smoke test per route, axe scan per route, screenshot capture at 1440x900, 1024x768 and 390x844.

---

## 12. The polish loop (use the rest of the session on this)

After the features work, run at least five full passes. Each pass: open the app, screenshot every route at the three viewports, compare against the mockup and the principles in section 9, list defects in `docs/PROGRESS.md`, fix them, re-shoot.

1. **Layout and hierarchy:** spacing, alignment, density, focal point, overflow, empty and error states.
2. **Glass and lighting:** blur levels, borders, highlights, contrast over lightning, gold vs violet discipline, anything that competes with the model.
3. **Motion:** timing consistency, easing, stagger order, reduced-motion behavior, no jank in the performance panel.
4. **Accessibility and responsiveness:** axe results, keyboard-only walkthrough, breakpoints.
5. **Content and trust:** microcopy, units, SAMPLE DATA and Demo labeling, the loud-failure showcase, docs page accuracy.
6. **Ideas pass:** look for missing features a real engineer reviewing parts all day would want, add the worthwhile ones, and cut anything that does not earn its place.

Keep going while meaningful defects remain. Stop only when the Definition of Done is fully met.

---

## 13. Folder structure (target)

```
Thee_UI/
  CLAUDE.md  CLAUDE_NEBULA_PRIME.md  NEBULA_PRIME_STACK.md
  reference/nebula-mockup.png
  docs/  ARCHITECTURE.md  DESIGN_SPEC.md  API_CONTRACT.md  PROGRESS.md  QA_CHECKLIST.md
  nebula-cad/
    app/            routes (dashboard, projects/[id], automation, models, pipelines, viewer/[id], library, docs, settings, welcome)
    components/     shell, hero, kpi, viewer, compare, extraction, pipeline, workspace (tabs), cost, rubric, shared
    lib/            api (adapter, mock, http), cost, rubric, motion, cad (occt worker), schemas, store
    public/         occt-import-js.wasm, sample drawings and models
    tests/          unit and e2e
```

---

## 14. Verification (last task on the list)

1. `npm run build`, typecheck, lint, Vitest and Playwright all pass.
2. Axe scan clean on every route.
3. Manual keyboard walkthrough of the workstation.
4. Screenshots at three viewports saved under `docs/screenshots/`.
5. Run the loud-failure showcase end to end: upload flow, mismatch, banner, blocked export, override with reason, rubric cap, audit entry.
6. Reviewer subagent audits the app against `docs/QA_CHECKLIST.md`. Fix everything it reports and record the result.

---

## 15. Constraints and safety

- No secrets in the client or the repo. Validate and size-limit uploads. Render PDFs client-side only.
- Respect licenses: GSAP standard license terms, LGPL notice for occt-import-js and OpenCASCADE, MIT for others. List them on the Docs page.
- Do not copy third-party designs, text, logos or imagery. Original work inspired by principles only.
- Do not use real customer drawings. Use synthetic sample drawings and models you create.

---

## 16. Definition of Done

- [ ] All routes and all tabs in section 7 exist and work, or are explicitly tagged Demo.
- [ ] Lower workspace tabs are exactly Parameters, Features, Validation, Cost, Logs, Rubric, with Rubric last.
- [ ] Drawing vs model compare, extraction review, build plan report, validation with blocking, cost (A, B, C) and rubric (with hard-fail cap and sign-off) are complete.
- [ ] Loud-failure showcase project and clean project both seeded and demonstrable.
- [ ] Glassmorphism system applied consistently; no planet or globe anywhere; model is the visual focus.
- [ ] Motion system implemented across the app, with reduced-motion and reduced-transparency support.
- [ ] Layout matches or improves on `reference/nebula-mockup.png` at 1440x900, and degrades cleanly at 1024, 768 and mobile.
- [ ] Docs complete: ARCHITECTURE, DESIGN_SPEC, API_CONTRACT, PROGRESS, QA_CHECKLIST.
- [ ] Build, typecheck, lint, unit, e2e and axe all pass. Reviewer audit done and fixed.
- [ ] Final message to the user: what was built, how to run it (exact commands), what is mock vs real, what the backend must implement, and any open decisions.
