# NEBULA_PRIME_STACK.md

Addendum to CLAUDE.md (Nebula Prime). Append this file or keep it next to CLAUDE.md. It adds the glassmorphism system, the repo stack with links, and the component and tab architecture for the layout. Nothing here overrides the art direction in CLAUDE.md: no planet or globe, restrained violet lightning, gold only for priority and active states.

---

## 1. Glassmorphism system

Glass only reads when there is something behind it. The background is a fixed nebula layer (gradients only, no celestial body), and every panel sits on it with a translucent violet-black fill, 12px blur, a 1px border and an inset top highlight.

### 1.1 Background layer (`app/globals.css`)

```css
body { background: var(--bg); color: var(--text); }

.nebula {
  position: fixed; inset: 0; z-index: -1; pointer-events: none;
  background:
    radial-gradient(60% 50% at 88% 0%,  rgba(166,124,255,.18), transparent 60%),
    radial-gradient(50% 40% at 0% 100%, rgba(166,124,255,.12), transparent 60%),
    radial-gradient(40% 30% at 50% 0%,  rgba(214,175,107,.06), transparent 70%);
}
```

### 1.2 Glass tiers

```css
:root {
  --glass-bg:        rgba(26, 19, 40, .56);
  --glass-bg-raised: rgba(46, 34, 80, .52);
  --glass-blur:      12px;
  --glass-highlight: inset 0 1px 0 rgba(245, 230, 203, .08);
  --glass-shadow:    0 8px 32px rgba(0, 0, 0, .45);
}

.glass {
  background: var(--glass-bg);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(140%);
          backdrop-filter: blur(var(--glass-blur)) saturate(140%);
  border: 1px solid var(--border-violet);
  border-radius: 16px;
  box-shadow: var(--glass-highlight), var(--glass-shadow);
  transition: border-color .2s ease, box-shadow .2s ease;
}
.glass--raised { background: var(--glass-bg-raised); border-radius: 14px; }
.glass--active {
  border-color: var(--border);
  box-shadow: var(--glass-highlight), var(--glass-shadow), 0 0 24px rgba(214,175,107,.12);
}
.glass:hover { border-color: rgba(166,124,255,.5); }

/* Tab pill used by the Motion layoutId indicator */
.tab-pill {
  position: absolute; inset: 0; z-index: -1; border-radius: 10px;
  background: rgba(214,175,107,.10); border: 1px solid var(--border);
  box-shadow: 0 0 16px rgba(214,175,107,.14);
}

@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .glass, .glass--raised { background: rgba(26,19,40,.94); }
}
@media (prefers-reduced-transparency: reduce) {
  .glass, .glass--raised { -webkit-backdrop-filter: none; backdrop-filter: none; background: var(--surface); }
}
@media (prefers-reduced-motion: reduce) {
  .glass { transition: none; }
}
```

### 1.3 Where each tier goes

| Tier | Elements |
|---|---|
| `.glass` | Top nav, left sidebar, hero, KPI cards, pipeline, lower workspace, right rail cards |
| `.glass--raised` | Table inputs, tab list, Quick Action buttons, viewer toolbar buttons |
| `.glass--active` | Active nav tab, selected sidebar item, focused project card |
| No blur | Model viewer canvas (keep it dark and opaque so the model stays the focus) |

### 1.4 Glass rules

- Keep `backdrop-filter` to about 10 elements on screen. Never nest two blurred elements.
- Do not blur the WebGL canvas container or anything that animates every frame.
- Text on glass must hit 4.5:1 contrast. If a paragraph sits over a bright lightning arc, raise the fill alpha to .7.
- Lightning and energy waves live behind glass at the corners and hero edge only.

---

## 2. Repo stack and links

### UI layer

| Repo | Link | Role in this layout |
|---|---|---|
| shadcn/ui | https://github.com/shadcn-ui/ui | Base primitives: Tabs, Table, Input, Button, Tooltip, ScrollArea, Command |
| Magic UI | https://github.com/magicuidesign/magicui (components: https://magicui.design/docs/components) | KPI Number Ticker, Border Beam on active cards, Animated Beam between pipeline steps, Shimmer Button for Generate CAD. Skip the Globe component. |
| Aceternity UI | https://ui.aceternity.com (author: https://github.com/manuarora700) | Hero Spotlight, Background Beams (corner energy filaments), tilt card for project thumbnails |
| React Bits | https://github.com/DavidHDev/react-bits (docs: https://reactbits.dev) | One atmospheric background for the hero, text effect for the headline |
| Arwes (reference only) | https://github.com/arwes/arwes | Inspiration for corner-cut frames. Not recommended in the app: no React strict mode or Server Components support. |

### Animation layer

| Repo | Link | Role |
|---|---|---|
| Motion | https://github.com/motiondivision/motion (docs: https://motion.dev) | Hover transitions, tab indicator, `AnimatePresence`, staggered pipeline steps, `MotionConfig reducedMotion="user"` |
| GSAP | https://github.com/greensock/GSAP (React: https://gsap.com/resources/React) | Lightning tracer draw (DrawSVG), hero energy waves (MorphSVG), pipeline timeline |
| tsParticles | https://github.com/tsparticles/tsparticles (React: https://github.com/tsparticles/react) | Optional sparse star dots. A few CSS or SVG dots may be enough. |
| Rive | https://github.com/rive-app/rive-react | Optional: System Online indicator, build status icon with state machine |
| Theatre.js | https://github.com/theatre-js/theatre | Optional: choreograph the model reveal and camera move |

### 3D and CAD viewer layer

| Repo | Link | Role |
|---|---|---|
| three.js | https://github.com/mrdoob/three.js | Core renderer |
| React Three Fiber | https://github.com/pmndrs/react-three-fiber | React renderer for the viewer |
| drei | https://github.com/pmndrs/drei | OrbitControls, Environment, GizmoHelper (XYZ triad), Html (dimension callouts) |
| react-postprocessing | https://github.com/pmndrs/react-postprocessing | Bloom for gold rim light, Vignette, subtle Noise |
| occt-import-js | https://github.com/kovacsv/occt-import-js | Load real STEP, IGES and BREP in the browser (WASM). LGPL 2.1, check it fits your distribution. |
| Online 3D Viewer | https://github.com/kovacsv/Online3DViewer | Reference or embeddable engine for model loading and display |
| three-cad-viewer | https://github.com/bernhard-42/three-cad-viewer | Reference for clipping planes, measurement and tree navigation (MIT) |
| opencascade.js | https://github.com/donalffons/opencascade.js | Only if you need full OCCT kernel operations in the browser |

---

## 3. Layout architecture

```
app/
  layout.tsx            Inter + JetBrains Mono via next/font, <div className="nebula" />, <MotionConfig reducedMotion="user">
  page.tsx              Dashboard composition
components/
  shell/    TopNav.tsx  Sidebar.tsx  ContextRail.tsx
  hero/     Hero.tsx  EnergyWaves.tsx (SVG + GSAP)  CornerLightning.tsx (SVG)
  kpi/      KpiCard.tsx  Sparkline.tsx
  viewer/   ModelViewer.tsx  ViewerToolbar.tsx  AxisTriad.tsx  DimensionCallout.tsx
  pipeline/ Pipeline.tsx  PipelineStep.tsx
  workspace/ WorkspaceTabs.tsx  ParameterTable.tsx  FeatureTree.tsx  ValidationPanel.tsx  LogStream.tsx  QuickActions.tsx
lib/
  data/     sample.ts  (everything here is labeled SAMPLE DATA in the UI)
  cad/      loadStep.ts  (occt-import-js worker)
```

### Component to library map

| Component | Built from |
|---|---|
| TopNav | shadcn NavigationMenu or plain links, `.glass`, Motion `layoutId` gold underglow on the active tab, shadcn Command for search |
| Sidebar | `.glass`, Motion hover 180 to 250ms, recent projects with thumbnails, System Online status block |
| Hero | Aceternity Spotlight, GSAP SVG waves on the right, Magic UI Shimmer Button (Generate CAD), outlined Upload Drawing |
| KpiCard | `.glass`, Magic UI Number Ticker, tiny SVG sparkline, gold outline icon |
| ModelViewer | R3F Canvas, drei OrbitControls and Environment, postprocessing Bloom, drei GizmoHelper, toolbar with orbit, fit and fullscreen |
| Pipeline | Vertical timeline, Motion stagger, Magic UI Animated Beam or a plain gold connector line |
| WorkspaceTabs | shadcn Tabs with Motion indicator (see 4.2) |
| ContextRail | Three `.glass` cards: Project Overview, Performance, Activity |

---

## 4. Tabs (as defined in CLAUDE.md)

### 4.1 All tab sets

| Location | Tabs |
|---|---|
| Top navigation | Dashboard, Projects, Automation, Models, Pipelines, Docs |
| Left sidebar | Dashboard, Projects, Automation, CAD Viewer, Pipelines, Library, Settings |
| Lower workspace | Parameters, Features, Validation, Logs |
| Right rail | Project Overview, Performance, Activity |
| Pipeline steps | Analyze Drawing, Extract Features, Generate CAD Model, Validate Geometry |

### 4.2 Lower workspace tabs component

```tsx
"use client";
import { useState } from "react";
import { motion } from "motion/react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

const TABS = ["Parameters", "Features", "Validation", "Logs"] as const;
type Tab = (typeof TABS)[number];

export function WorkspaceTabs() {
  const [tab, setTab] = useState<Tab>("Parameters");
  return (
    <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="glass">
      <TabsList className="glass--raised relative m-2 bg-transparent">
        {TABS.map((t) => (
          <TabsTrigger key={t} value={t} className="relative">
            {tab === t && (
              <motion.span layoutId="workspace-tab" className="tab-pill" transition={{ duration: 0.22 }} />
            )}
            {t}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value="Parameters">{/* <ParameterTable /> */}</TabsContent>
      <TabsContent value="Features">{/* <FeatureTree /> */}</TabsContent>
      <TabsContent value="Validation">{/* <ValidationPanel /> */}</TabsContent>
      <TabsContent value="Logs">{/* <LogStream /> */}</TabsContent>
    </Tabs>
  );
}
```

### 4.3 What each tab must do

| Tab | Content | Honesty rule |
|---|---|---|
| Parameters | Editable table: Parameter, Value, Unit, Range. JetBrains Mono, right-aligned numbers, gold focus ring on inputs, range check on blur. | Out-of-range values show a warning state, never silently clamp. |
| Features | Feature tree from the build plan (sketch, extrude, hole, fillet) with the selected feature highlighted in gold in the viewer. | Show only features that exist in the real build plan, otherwise label as sample. |
| Validation | Checks list with Passed, Failed or Not run, plus the extracted vs modeled counts (for example hole count). | Never show Passed unless a check actually ran. Quiet extraction errors are the main risk, so surface mismatches loudly. |
| Logs | Monospace, virtualized, filter by level, copy button. | Show real pipeline output only. Mark demo logs as demo. |

### 4.4 Interactivity rule

Every control that looks interactive must work or carry a visible "Demo" tag. Static viewer preview must say "Static preview" until a STEP file is actually loaded through occt-import-js.

---

## 5. Motion spec (from CLAUDE.md, made concrete)

- Hover and tab transitions: 200 to 250ms ease-out.
- Ambient energy movement: 8 to 16s loops, opacity and offset only, no strobing.
- Pipeline entrance: Motion stagger 60 to 80ms per step, run once.
- KPI numbers count up once on mount.
- Wrap the app in `<MotionConfig reducedMotion="user">`. In GSAP code, check `window.matchMedia("(prefers-reduced-motion: reduce)")` and skip decorative timelines.
- Pause ambient animation when the tab is hidden.

---

## 6. Setup commands (run in order)

```bash
npx create-next-app@latest nebula-cad --typescript --tailwind --eslint --app
cd nebula-cad
npx shadcn@latest init
npx shadcn@latest add tabs table input button card tooltip scroll-area command
npm install motion gsap @gsap/react
npm install three @react-three/fiber @react-three/drei @react-three/postprocessing
npm install occt-import-js
npm install -D @types/three
cp node_modules/occt-import-js/dist/occt-import-js.wasm public/occt-import-js.wasm
pnpm dlx shadcn@latest add @aceternity/background-beams
npx shadcn@latest add @react-bits/Aurora-TS-TW
```

Magic UI components install from each component page at https://magicui.design/docs/components. Optional extras: `npm install @tsparticles/react @tsparticles/engine @tsparticles/slim`, `npm install @rive-app/react-canvas`.

---

## 7. Build order

1. Tokens, fonts, `.nebula` and `.glass` CSS.
2. Shell: TopNav, Sidebar, ContextRail.
3. Hero with CSS gradients and SVG waves.
4. KPI cards with sample data labels.
5. ModelViewer with a static preview, then load a real STEP file through occt-import-js.
6. Pipeline timeline.
7. WorkspaceTabs and the four tab panels.
8. Motion pass, reduced-motion pass, contrast pass, responsive collapse of sidebar and rail.

## 8. Acceptance checks

- No planet, moon or globe anywhere.
- Glass panels readable over the brightest lightning region.
- Viewer is the visual focus; effects stay behind it.
- All four workspace tabs switch, and every button works or is tagged Demo.
- Reduced motion and reduced transparency both degrade cleanly.
