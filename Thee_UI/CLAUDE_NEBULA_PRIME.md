# CLAUDE.md — Nebula Prime CAD Automation UI

## Objective
Implement a production-quality CAD design automation website using the **Nebula Prime** visual identity. The aesthetic is a premium sci-fi gaming engineering workstation: dark cosmic atmosphere, restrained violet lightning, warm champagne-gold lighting, glass-like panels, and precise CAD-focused information hierarchy.

## Critical art direction
**Do not use a planet, moon, globe, or large celestial body anywhere in the background.** Create the space atmosphere through layered near-black/violet gradients, sparse tiny star particles, soft nebula fog, flowing energy filaments, and fine branching violet lightning confined mostly to corners, edges, and decorative hero regions. The backdrop must never compete with text, controls, or the CAD model.

## Color tokens
```css
:root {
  --bg: #0B0814;
  --surface: #1A1328;
  --surface-raised: #2E2250;
  --gold: #D6AF6B;
  --gold-highlight: #F5E6CB;
  --violet: #A67CFF;
  --text: #F7F3FA;
  --text-muted: #ABA1BD;
  --border: rgba(214,175,107,.18);
  --border-violet: rgba(166,124,255,.32);
  --success: #55DFA0;
}
```

## Page structure
Desktop-first responsive layout with top navigation, left workspace sidebar, central workspace and optional right context rail.

1. **Top navigation**: glowing geometric gold cube logo, NEBULA CAD wordmark, Dashboard / Projects / Automation / Models / Pipelines / Docs, search, notification, avatar. Active tab has subtle warm gold illumination.
2. **Left sidebar**: Dashboard, Projects, Automation, CAD Viewer, Pipelines, Library, Settings; recent projects with small model thumbnails; bottom System Online status. Sidebar is a dark translucent panel with quiet violet outline.
3. **Hero**: 'From Drawings to CAD' headline, AI-driven extraction/parametric modeling/validation subtitle, gold Generate CAD primary CTA and outlined Upload Drawing secondary CTA. On the right, use flowing violet/gold energy waves and faint particle stars, **not a planet**.
4. **KPIs**: four compact glass cards for models generated, validation rate, average build time, and pipeline errors; gold outline icons, subtle violet micro-sparklines. Demo values must be labeled sample data or replaced with real data.
5. **Model viewer**: dominant centerpiece, dark technical grid, high-quality metallic CAD assembly with realistic reflections, gold rim lighting, dimension callouts, XYZ triad, orbit/zoom/fullscreen controls. If no 3D engine is available, use a clearly labeled static preview instead of pretending it is interactive.
6. **Automation pipeline**: vertical timeline with Analyze Drawing, Extract Features, Generate CAD Model, Validate Geometry. Show real statuses and timings when connected; otherwise demo states.
7. **Lower workspace**: Parameters / Features / Validation / Logs tabs, editable engineering dimension table with units, tolerances and input focus rings; Quick Actions for New Model, Clone, Export.
8. **Right rail**: Project Overview, Performance, Activity. Keep it compact and optional on smaller widths.

## Lighting and effects
- Gold lighting indicates priority, active controls, selected CAD edges, and completed operations.
- Violet is atmospheric: thin circuit-like border tracers, subtle lightning arcs, hazy gradients, and fine energy waves.
- Keep stars extremely sparse and tiny. No bright starfield behind paragraphs.
- Use 1px borders, restrained outer glows, subtle inset highlights, and rounded corners around 12–16px.
- Glass surfaces may use `backdrop-filter: blur(12px)` and translucent violet-black backgrounds, but maintain readable contrast.
- Motion: hover transitions 180–250ms; gentle energy movement 8–16s; respect `prefers-reduced-motion` and disable decorative motion accordingly.
- Do not use strobing, intense flashing, thick neon outlines everywhere, or distracting particle storms.

## Typography and engineering UX
Use Inter for headings, navigation and UI labels; JetBrains Mono for dimensions, parameters, filenames, units, logs and numerical readouts. Preserve high contrast, keyboard focus, semantic HTML and accessible labels. Keep numerical alignment consistent and never fake actual model validation.

## Implementation guidance
Prefer Next.js + React + Tailwind CSS + shadcn/ui; use lightweight CSS gradients and SVG for most atmospheric effects. Use Three.js / React Three Fiber only if a functional 3D CAD viewer is required and the project stack supports it. Organize the layout into reusable components (TopNav, Sidebar, Hero, KpiCard, ModelViewer, Pipeline, ParameterTable, QuickActions, ContextRail). Avoid heavy full-screen video backgrounds. Optimize for desktop, then collapse right rail and sidebar appropriately on tablets/mobile.

## Acceptance criteria
- No visible planet or celestial globe in any scene.
- The page is immediately recognizable as a CAD automation tool, not a generic gaming landing page.
- Dark violet cosmic mood, restrained gold highlights, and fine violet lightning are evident.
- CAD model is the visual focus, not background effects.
- All controls that appear interactive actually work or are explicitly identified as demos.
- Good contrast, responsive layout, and reduced-motion accessibility.
