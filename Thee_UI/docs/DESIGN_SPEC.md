# DESIGN SPEC — 2D to 3D CAD

Visual identity comes from `CLAUDE_NEBULA_PRIME.md`. Semantics for pipeline state, stamps and numerals come from `DESIGN.md` (see ARCHITECTURE D3). Tokens live in `nebula-cad/app/globals.css`; motion tokens in `nebula-cad/lib/motion/index.ts`.

## 1. Research notes (Phase 0)

**What was checked live.** All repo links and package versions (see ARCHITECTURE §2). Five reference pages were fetched (Linear, Vercel, Raycast, Stripe; Onshape's features page returned 404). The fetch returns rendered text, not stylesheets, so **fonts, spacing values, colors, gradients and motion timings could not be measured** from those pages. Only content-level patterns were observable. Framer, Apple, Fusion and Figma were not fetched.

**Observed patterns that are applied here**

1. Group rows by state and put the count in the group header (Linear). → Extraction review and Validation headers show counts per status.
2. Compact IDs and relative timestamps as default row metadata (Linear). → `EX-014`, `CHK-03`, `RUN-0007`, "2m ago" with the absolute time in a tooltip.
3. State is written as text, not only color (Linear). → Every stamp has a word and a glyph.
4. Keyboard shortcuts appear as key chips next to their actions (Raycast). → Command palette rows and the shortcuts dialog use `<kbd>` chips.
5. A summary metric is a large number with a small label and explicit unit (Stripe). → KPI cards and cost totals.
6. Mock data is labeled as what it is ("Usage meter", "last 30 days") (Stripe). → SAMPLE DATA badges and labeled assumptions.
7. One primary and one secondary call to action per section (Vercel). → Generate CAD (gold) + Upload Drawing (outline).

**Principles applied from the brief (§9.2), not measured from the sites:** one focal point per screen (the model), 8px grid, 12–16px radii, one accent system, progressive disclosure, skeletons over spinners, numbers animate once, every state designed.

**Mockup read (`reference/nebula-mockup.png`, 1672×941).** Three columns: sidebar ≈ 15%, center ≈ 60%, rail ≈ 22%. Center stack: hero → 4 KPI cards → viewer (≈ 64%) + pipeline (≈ 36%) → tabs (≈ 64%) + quick actions. Gold appears on the active nav pill, the primary button, the "CAD" word, icons, focus rings and completed pipeline nodes. Violet appears only as edge tracers, corner arcs and the hero wave.

## 2. Color tokens

```css
:root {
  /* Nebula Prime (authoritative) */
  --bg: #0B0814;            --surface: #1A1328;       --surface-raised: #2E2250;
  --gold: #D6AF6B;          --gold-highlight: #F5E6CB; --violet: #A67CFF;
  --text: #F7F3FA;          --text-muted: #ABA1BD;
  --border: rgba(214,175,107,.18);  --border-violet: rgba(166,124,255,.32);
  --success: #55DFA0;
  /* additions */
  --text-faint: #7F7694;    /* disabled, skipped; 4.6:1 on --bg */
  --on-gold: #1B1206;       /* text on gold fills */
  --danger: #FF6680;        --warn: #FF9A3D;          --notice: #E8D06A;
  --danger-dim: rgba(255,102,128,.12); --warn-dim: rgba(255,154,61,.12);
  --success-dim: rgba(85,223,160,.12); --gold-dim: rgba(214,175,107,.10);
  --violet-dim: rgba(166,124,255,.12);
  --well: #07050D;          /* viewer canvas, drawing well, log ground: opaque */
  /* glass */
  --glass-bg: rgba(26,19,40,.56);   --glass-bg-raised: rgba(46,34,80,.52);
  --glass-blur: 12px;
  --glass-highlight: inset 0 1px 0 rgba(245,230,203,.08);
  --glass-shadow: 0 8px 32px rgba(0,0,0,.45);
}
```

### Usage rules

| Color | Means | Never |
|---|---|---|
| Gold | priority, active control, selected feature/edge, completed operation, focus ring | warnings; large fills other than the one primary button |
| Violet | atmosphere: tracers, arcs, haze, hover border, sparklines | status; text smaller than 14px |
| Success green | a check that **ran and passed**; Approved | "probably fine", not-run |
| Warn orange | needs review, low confidence, warning check, assumption notices | completed states |
| Danger red | conflict, failed check, blocked export, Needs rework | decoration |
| Notice yellow | medium severity only | — |

Severity ladder (stamps): CRITICAL `--danger` · HIGH `--warn` · MEDIUM `--notice` · LOW `--text-muted`.
Confidence: ≥ 0.90 neutral (muted bar), 0.75–0.90 warn, < 0.75 danger. A high confidence is never colored green: confidence is not verification.

## 3. Typography

Inter (`--font-sans`) for UI; JetBrains Mono (`--font-mono`) for dimensions, parameters, units, filenames, IDs, logs, costs, timings — always `tabular-nums`.

| Token | Size / line | Weight | Use |
|---|---|---|---|
| hero | 44 / 48 (32 on mobile) | 700, -0.02em | dashboard headline |
| h1 | 24 / 32 | 650 | page titles |
| h2 | 16 / 24 | 600 | card titles |
| control | 14 / 20 | 500 | nav, buttons, tabs |
| body | 13 / 20 | 400 | default dense text |
| small | 12 / 16 | 400–500 | metadata |
| caption | 11 / 16, uppercase, +0.12em | 600 | eyebrows, table headers, stamps |
| stat | 24 / 28 mono | 600 | KPI numbers |

## 4. Spacing, radii, elevation

- 8px grid (4px half-step inside controls): 4 · 8 · 12 · 16 · 24 · 32 · 48.
- Page gutter 16 (≥1024: 20). Card padding 16 (compact density 12). Gap between cards 16.
- Radii: panel 16 · raised 14 · control 10 · chip 6 · pill 999.
- Elevation is three steps only: well (opaque, below) → glass → glass raised. Shadows are part of the glass recipe; nothing else casts one.
- Control heights: 36 default, 32 compact, 28 table inline, 44 hero CTA. Minimum hit area 32×32 (44 on touch widths).

## 5. Glass tiers

| Tier | Recipe | Used by |
|---|---|---|
| `.glass` | `--glass-bg`, blur 12 + saturate 140%, 1px `--border-violet`, radius 16, highlight + shadow | top nav, sidebar, hero, KPI cards, pipeline, workspace, rail cards, page panels |
| `.glass-raised` | `--glass-bg-raised`, radius 14, **no backdrop-filter** | tab list, inputs, quick action buttons, viewer toolbar buttons, nested cards |
| `.glass-active` | gold border + 24px soft gold glow | active nav, selected sidebar item, focused project card |
| `.well` | opaque `--well`, 1px border | viewer canvas, drawing canvas, log stream |

Changes from `NEBULA_PRIME_STACK.md`, recorded as required:

1. `.glass--raised` no longer blurs. Raised elements always sit inside a `.glass` panel, and nesting blur is against the stack's own rule.
2. BEM `--` modifiers became `-` suffixes to sit well with Tailwind utilities.
3. Fill alpha rises to .72 (`.glass-solid`) for any panel whose text sits over the hero wave or a corner arc.
4. Blur budget is enforced by structure: the shell owns 3 blurred elements (nav, sidebar, rail container), the page owns up to 7.

Fallbacks: no `backdrop-filter` support → fill alpha .94. `prefers-reduced-transparency` → opaque `--surface`, no blur.

## 6. Components and states

- **Stamp** (`StatusStamp`): outlined chip, caption type, tinted 12% fill, leading glyph. Variants: `passed ✓`, `failed ✕`, `warning !`, `not_run ○` (dashed border, faint text), `verified`, `needs_review`, `conflict`, `running`, `skipped` (dashed), `blocked`.
- **SAMPLE DATA badge:** violet outline, caption type. Placed in every card header fed by mock data, plus one persistent chip in the top nav.
- **Demo tag:** dashed warn outline `DEMO`, attached to any control that cannot do real work in the current mode.
- **Failure banner:** full-width, danger border + 12% fill, icon, plain statement with numbers ("Drawing calls out 10 holes. Extraction found 8. Model has 8."), actions (Review items, Open validation). Persistent until resolved or overridden; never auto-dismisses.
- **Buttons:** primary (gold fill, `--on-gold` text; one per view), outline (gold border), ghost, danger. Hover lifts 1px with border glow; press scales .98; focus ring 2px gold with 2px offset.
- **Inputs:** `.glass-raised` ground, mono for numbers, gold focus ring; invalid = danger border + message below; out-of-range = warn border + message, value kept.
- **Tables:** 36px rows (compact 30), caption headers, hairline separators, numbers right-aligned mono, row hover raises fill. Selected row has a 2px gold left rule.
- **Tabs:** gold pill slides between triggers (`layoutId`); content cross-fades.

### State design (every list and panel)

| State | Design |
|---|---|
| Loading | Skeleton blocks matching final layout. No spinners except inside a running pipeline node. |
| Empty | Icon, one sentence saying what will appear and why it is empty, one action. |
| Error | Danger outline card: what failed, the adapter message, **Retry**. Offline is detected and named. |
| Not run | Dashed neutral treatment and the words "Not run". Never green, never hidden. |
| Blocked | Danger stamp on the control, reason listed beside it. |

## 7. Motion tokens (`lib/motion`)

| Token | Value |
|---|---|
| `dur.micro` | 0.16s |
| `dur.standard` | 0.22s |
| `dur.entrance` | 0.5s |
| `dur.ambient` | 8–16s loops |
| `ease.out` | cubic-bezier(.22, 1, .36, 1) |
| `ease.inOut` | cubic-bezier(.65, 0, .35, 1) |
| `spring` | stiffness 380, damping 32, mass 0.9 |
| `stagger` | 0.07s per child |

Choreography: page-load sequence once per session (nav → sidebar stagger → hero → KPI rise + count-up → viewer fade + camera ease → pipeline stagger); route cross-fade with 6px shift; tab pill; card hover lift; pipeline line fill, soft pulse on the active node, single gold sweep on completion; row enter/exit; gold flash on an edited cell; chart draw-in; camera tweens for Fit/Reset/focus; one subtle shake when a validation failure banner first appears.

Tool per job: Motion for components and layout, GSAP for the SVG energy waves and lightning tracers, R3F `useFrame` for the camera. Reduced motion: `MotionConfig reducedMotion="user"`, `gsap.matchMedia`, CSS media queries, plus Settings → Motion intensity (`full` | `reduced`) which sets `data-motion` on `<html>` and is honored by all three. Ambient loops pause when the document is hidden.

## 8. Wireframes

### Dashboard (1440)

```
┌ TopNav: [cube] NEBULA CAD   Dashboard Projects Automation Models Pipelines Docs   [SAMPLE] ⌕ 🔔 (JM) ┐
├ Sidebar ─┬ Hero: From Drawings to CAD  [Generate CAD] [Upload Drawing]   ~waves~   ┬ Rail ─────────┤
│ nav ×7   ├ KPI │ KPI │ KPI │ KPI                                                   │ Project        │
│          ├ Model Viewer (focus) ──────────────┬ Automation Pipeline ──────────────┤ Overview       │
│ recent   │  canvas · toolbar · triad          │  ● Analyze ● Extract ● Generate ● │ Performance    │
│ projects ├ Tabs: Parameters Features Validation Cost Logs Rubric ┬ Quick Actions ─┤ Activity       │
│ status   │  tab content                                          │ New Clone Export│                │
└──────────┴───────────────────────────────────────────────────────┴────────────────┴────────────────┘
```

### Workstation `/projects/[id]`

```
┌ Header: FL-2210 Flange_Adapter · Rev A · [NEEDS REWORK]            [Rerun] [Export ▣ blocked] ┐
├ ██ FAILURE BANNER: Drawing calls out 10 holes. Extraction found 8. Model has 8.  [Review] ██ ┤
├ Compare [Split|Overlay|Diff] [Heatmap] [Link zoom] ───────────┬ Review ─────────────────────┤
│  Drawing (pdf.js)        ║        Model (R3F)                 │ [Extraction|Build plan|      │
│  regions, pins, outline  ║  toolbar: fit reset section       │  Comments|Revisions|Audit]   │
│                          ║  measure fullscreen load file     │ count strip: 10 / 8 / 8      │
│                          ║                                    │ rows sorted by risk          │
├ Pipeline (horizontal on wide, vertical card on dashboard) ────┴──────────────────────────────┤
├ Tabs: Parameters | Features | Validation | Cost | Logs | Rubric                               ┤
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Automation wizard

```
1 Upload (drop files or a folder · or use a sample drawing) → 2 Options (material, units, preset)
→ 3 Estimate (cost, time, assumptions) → 4 Run (live stage timeline, log tail) → Open project
```

### Lists (Projects, Models, Pipelines, Library)

Page header (title, count, primary action) → filter bar (search, status chips with counts, grid/table toggle) → content → designed empty state.

## 9. Responsive behavior

| Width | Behavior |
|---|---|
| ≥ 1440 | sidebar 232 · fluid center · rail 320 |
| 1024–1439 | rail collapses to a sheet opened from the top nav; center keeps two columns |
| 768–1023 | sidebar collapses to a 64px icon rail; viewer/pipeline and tabs/quick actions stack |
| < 768 | sidebar becomes a drawer; top nav tabs move into it; single column, viewer first after the hero; tables scroll horizontally inside their card; compare switches to a Drawing/Model toggle |

## 10. Accessibility

AA contrast for all text on glass (verified with axe on every route). Focus ring always visible. Tabs, tree, tables and dialogs use the Radix/ARIA patterns. Color is never the only signal. Canvas elements have text alternatives (feature tree, extraction table) and labeled toolbars. Motion and transparency preferences are honored.
