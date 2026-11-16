# MTI Pipeline UI — Design System (final)

Single source of truth for values: **`static/design-tokens.css`**, linked by every document in the UI (the host page and the cropper iframe), so all surfaces share the same tokens and component recipes. This file documents the decisions and holds the canonical token block below. If you change a value, change it in the tokens file and here, never in a page style.

---

## Direction — BLUEPRINT ROOM

The product converts 2D engineering drawings into SolidWorks parts, so the interface is built from the drawing's own world: **the drawing office**. Deep Prussian-navy surfaces (a cyanotype print at night), cool drafting-white ink, ONE blueprint-cyan accent (the line color of a print), hairline rules, inspection-stamp semantics, and monospace numerals wherever a value is a measurement. The reference points are a cyanotype blueprint and a CAD viewport, not SaaS dashboards.

Depth is **borders only**: no drop shadows. Dark is the only theme. The app is dependency-free vanilla HTML/CSS/JS with a strict no-CDN, vendored-assets rule, so patterns are shared CSS classes, not components.

This is an operations tool for engineers who need to trust a number. Density is welcome, ornament is not. Every screen answers "what happened, is it READY, what needs my attention".

## Tokens (canonical block)

```css
:root {
  /* surfaces — one hue, lightness steps only */
  --well: #0A0F16;  --bg: #0D131C;  --bg-raised: #111927;
  --surface: #16202F;  --surface-2: #1B2738;  --input-bg: #090E15;
  /* ink */
  --ink: #E7EDF5;  --ink-2: #AEBACB;  --ink-3: #7D8A9E;  --ink-4: #4E5A6C;
  /* blueprint cyan (the one interactive accent) */
  --blueprint: #3FA9D4;  --blueprint-bright: #5FBFE4;  --blueprint-text: #7ECFEE;
  --blueprint-dim: rgba(63,169,212,.12);  --on-blueprint: #04191F;
  /* steel (secondary / informational) */
  --steel: #5C7690;  --steel-text: #9FB6CC;  --steel-dim: rgba(92,118,144,.14);
  /* status: accept / reject / hold */
  --ok: #3EAF7C;  --err: #E5484D;  --warn: #E3A93C;
  /* severity ladder */
  --sev-critical: #F0545C;  --sev-high: #E3A13C;  --sev-medium: #D2C355;  --sev-low: #8DA4BE;
  /* lines */
  --line: rgba(185,212,240,.10);  --line-soft: rgba(185,212,240,.06);
  --line-strong: rgba(185,212,240,.20);  --ring: 0 0 0 1px var(--blueprint);
  /* type */
  --sans: "Segoe UI Variable","Segoe UI",system-ui,-apple-system,sans-serif;
  --mono: "Cascadia Mono",Consolas,"SF Mono",Menlo,monospace;
  --fs-caption: 11px; --fs-small: 12px; --fs-body: 13px; --fs-control: 14px;
  --fs-h2: 16px; --fs-stat: 20px; --fs-display: 30px;
  /* spacing (4px grid) and radius */
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-5: 24px; --sp-6: 32px;
  --r-sm: 2px; --r-md: 4px; --r-lg: 6px;
}
```

Each `-text` status variant (`--ok-text`, `--err-text`, `--warn-text`) and each `-dim` tint (8–12% alpha of the base) is defined in the tokens file and used for chip fills and strip backgrounds. Do not introduce hexes outside this file.

## Color

### Surfaces (Prussian navy)

| Token | Use |
|---|---|
| `--well` | deepest: canvas wells, console, 3D viewport, list boxes |
| `--bg` | page background |
| `--bg-raised` | toolbars, tab rails, panel captions, status bars |
| `--surface` | cards, chips, secondary buttons |
| `--surface-2` | hover on surfaces |
| `--input-bg` | inputs, inset *below* their surroundings |

### Ink (4 tiers)

`--ink` primary · `--ink-2` secondary · `--ink-3` labels/muted · `--ink-4` faint/disabled/skipped.

### Accents

- **Blueprint cyan, the one interactive accent (~10% of any screen).** Primary buttons, active tab underline + sheet number, selection (part card, crop marquee), focus ring, links, the **running** stage chip.
- **Steel, secondary/informational.** Format badges, **completed** stage chips, tier chips. Never for primary actions.
- **Status (accept / reject / hold):** `--ok` / `--err` / `--warn`. Used for PASS/FAIL, READY/NOT READY, built/failed.

### Severity ladder (functional, never decorative)

CRITICAL `#F0545C` · HIGH `#E3A13C` · MEDIUM `#D2C355` · LOW `#8DA4BE` (red → amber → yellow → slate). Severity renders as **inspection stamps**: outlined, letterspaced chips (color border + 8–10% tint), identical everywhere: Engineering Review flags, left rails, requirement chips, resolver confidence tags, Learning Loop links.

The resolver's confidence tags (`HIGH/MEDIUM/LOW/CRITICAL`) deliberately reuse the ladder, because a LOW-confidence value is the same kind of "look at this" as a LOW flag. Confidence uses the stamp **with a leading `CONF` micro-label** so the two are never confused. Example: `CONF · LOW`.

### Pipeline-state semantics

| State | Treatment |
|---|---|
| pending | `--ink-4` text, hairline border |
| running | cyan-tinted chip, cyan text, subtle 1.2s opacity pulse (disabled under `prefers-reduced-motion`) |
| done | steel chip + ✓ |
| skipped | `--ink-4`, dashed border, text "skipped" (not an error) |
| failed | `--err` outline + ✕ |
| aborted | `--warn` outline + "aborted" (e.g. pre-validation stopped the build) |

## Typography

- **Sans (UI text):** `--sans`. No webfonts; everything is vendored.
- **Mono (technical content):** `--mono`. Dimensions, units, file names/paths, JSON, console, token counts and costs, sheet/OP numbers, feature ids (`F001`), constraint ids (`MM-001`), tier and disposition chips. Always `tabular-nums` for dynamic numbers.

Scale (px): caption 11 (uppercase micro-labels) · small 12 · body 13 (dense tool default) · control 14 · h2 16 · stat 20 · display 30 (reserved for hero numbers). Hierarchy comes from weight (400/500/600/700) and ink tier first, size second.

## Spacing, radius, depth

4px grid only (`--sp-1..6` = 4/8/12/16/24/32). Radius: `--r-sm 2` chips/stamps · `--r-md 4` buttons/inputs · `--r-lg 6` cards/panels.

**Borders only.** `--line` standard · `--line-soft` row separators · `--line-strong` secondary button edges · `--ring` cyan focus. The only box-shadows are the 1px cyan ring on the selected part card and the soft glow on the API status dot. Elevation = surface lightness step.

## Component recipes (in design-tokens.css)

| Class | Recipe |
|---|---|
| `.btn` | 36px h · 0 16px pad · r-md · 14px/600 · cyan fill; `.secondary` (surface + strong border), `.ghost`, `.danger` (outline red), `.running`, `.on` (tinted active state for toggles), sizes `.sm` 28px / `.xl` 46px; `:active` scale(.97) |
| `.ibtn` | 26px square quiet icon button |
| `.badge-c` | bordered chip, 11px/600, r-sm; tints `.blueprint .steel .ok .err .warn`, `.mono` |
| `.badge-sev` | OUTLINED severity stamp, 10px/700 uppercase tracked: `.critical .high .medium .low` |
| `.badge-conf` | `.badge-sev` with a leading `CONF` micro-label (resolver confidence) |
| `.badge-tier` | steel mono chip `TIER 0/1/2` (who decided this value) |
| `.badge-disp` | feature disposition chip: `.built` (ok), `.derived` (warn, "BUILT · DERIVED"), `.excluded` (err, "EXCLUDED") |
| `.badge-pos` | hole `position_source` chip (steel, mono: `vector` / `callout` / `raster`) with confidence as a trailing tabular number |
| `.stamp-verdict` | bordered mono verdict stamp on a status-tinted strip: `.ready`, `.open` (warn), `.notready` (err) |
| `.input-c` | inset field: `--input-bg`, quiet border, cyan focus border |
| `.tab-c` | underline tab: 2px cyan underline + full-ink text when `.active`; `.sm` for sub-tabs |
| `.cap-c` | 11px/600 uppercase tracked panel caption |
| `.progress-c` | 6px track (`--well`) + cyan fill |
| `.console-c` | `--well` ground, 12px mono, cool-gray text; ANSI stripped; auto-scroll that pauses when the user scrolls up |
| `.card-c` | surface + line border + r-lg |
| `.seg-c` | segmented control: inset ground, cyan-filled active segment |
| `.table-c` | dense data table: 28px rows, `--line-soft` separators, mono numeric columns right-aligned, sticky header on `--bg-raised` |
| `.empty-c` | empty/skipped state: `--ink-3` text with the reason on one line, no illustration |
| `.disclosure-c` | collapsible panel with `.cap-c` header and a chevron glyph (used for Overview Analysis) |
| `.amber-box` | the must-meet spec input: `.input-c` with a `--warn` left rule and `--warn-dim` caption, because it is the one tier-0 authority |

Page-specific styles may **compose** these classes and bind layout rules, but every color, size and spacing value must reference a token.

## Signature elements

- **Title-block header.** The app header is an engineering drawing's title block: brand left, hairline-bordered data cells right (ENGINE · DELIVERABLES · API STATUS: micro-label over mono value), with a drafting-ruler tick strip along the bottom edge. The API cell shows key present/missing only, never the key.
- **Sheet tabs.** The four top tabs are the SHEETS of a drawing set: a mono `SHEET n` plate that lights cyan on the active tab. Sheets: 1 Crop · 2 Part setup · 3 Run · 4 Outputs.
- **Centerline dividers.** The split-view drag divider carries the drafting centerline pattern (long dash · gap · short dash).
- **Traveler stage strip (Sheet 3).** Stage chips are numbered `OP 01…` via CSS counters in mono, like operations on a shop routing sheet. States as in the pipeline-state table. Hovering a chip shows the module name, the artifact it writes and its token/USD cost if any. The strip wraps rather than scrolls horizontally.
- **Inspection stamps.** Severity chips and the post-run verdict are outlined, letterspaced stamps. The verdict has three states: **READY**, **READY · OPEN ITEMS**, **NOT READY**, and always lists its gate reasons beneath.
- **Tier ribbon.** Wherever a value was overridden, show `TIER 0 SPEC` (spec wins), `TIER 1 VIEW`, or `TIER 2 OVERVIEW` as a mono ribbon, so the reader sees who decided without opening JSON.
- **Disposition table.** The Features tab is the build's bill of materials: id, type, qty (expected vs built), disposition chip, and for `EXCLUDED_INCOMPLETE` the missing parameter named in plain text.
- **Constraint ledger.** MM-xxx rows with `required` and `measured` side by side in mono, a PASS/FAIL stamp, and the difference when failed. The ledger never rounds away a failing difference.
- **Blueprint crop marquee (Sheet 1).** The cropper's selection dash, corner handles and px-dimension readout use the same cyan as every other selection.
- **Blueprint 3D viewport (Sheet 2 and Outputs).** Navy well background, cool key light + cyan rim light, machined-aluminum part material. A toggle swaps between the built `.STL` and `prevalidation.stl`.

## Content and microcopy

- Plain declarative engineering voice. "Hole 4 resolved to Ø0.250 in (tier 1, MEDIUM)". Not "Great news!".
- Always show a unit with a dimension, and keep the drawing's unit.
- Name the exact thing: `MM-001 FAILED: 6 holes required, 5 measured`, never "constraint failed".
- Cost is stated plainly: "Paid: re-extracts with the model (≈ $x)" versus "Free: reuses saved extraction".
- A recovered-by-reconciliation feature carries the note "Recovered in the plan and macros. Rebuild to include it in the .sldprt".
- Skipped is neutral: "Skipped: no API key" and "Skipped: SolidWorks not available on this OS".

## Layout

- Desktop-first. The tool assumes a 1280px minimum width and works down to a 1024px viewport by collapsing side panels. There is no phone layout.
- Two-pane split on Sheets 2–4 (drawing/3D left, controls right) with the centerline divider. The split ratio persists per sheet.
- Every list longer than ~12 rows scrolls inside its own panel; the page itself never scrolls horizontally.

## Rules

1. No hex values in page styles. Tokens only.
2. Cyan is scarce: one primary action per view; selection + focus; the running stage.
3. Severity colors mean severity. Never reuse them decoratively.
4. Any dynamic number gets `--mono` + `tabular-nums`.
5. No drop shadows (beyond the two sanctioned rings/glows), no decorative gradients, no new hues.
6. Emoji are banned in chrome (colored glyphs break the palette); use monochrome glyphs/text (✓ ✕ ↻ ⊕ ›).
7. Color is never the only signal: every status has a glyph or word.
8. Never block the user on an ambiguity. Present the resolved value, its confidence and tier, and let them correct it via the feedback re-run.
9. Skipped is not failed. Missing optional artifacts render as `.empty-c` with the reason.
10. Destructive actions (`Clear all models`) state precisely what is and is not deleted.
11. Respect `prefers-reduced-motion`; the only animation is the running-chip pulse and the 97% button press.
12. Everything is vendored: no CDN, no webfont, no remote image.
