# Sub-project A — Feature IR v2 + Compilers — Design

**Date:** 2026-09-28 · **Status:** design approved; ready for an implementation plan
**Parent:** [AI CAD roadmap](2026-09-28-ai-cad-roadmap-design.md)

## Goal

Add a typed **BuildPlan** (Feature IR v2) between reading the drawing and building
the part. The LLM *plans*. Two deterministic compilers then turn the plan into
(a) a CadQuery reference solid plus STEP, and (b) the existing SolidWorks VBA/COM
output. Placement becomes explicit, traceable to drawing dimensions, and
measurable.

## Problems with v1 this fixes

| v1 behavior | Where | IR v2 answer |
|---|---|---|
| Two coordinate frames in one schema: `HoleCallout.x_position` is "from part center/origin" while `instance_positions` is "edge-referenced from lower-left" | `pipeline/schema.py` | One part frame; all coordinates are expressions in it |
| Positions are optional (`position_known=False` → centered, `POSITION ASSUMED`) | `schema.Feature`, `macro_generator._hole_positions` | A position is required, or explicitly `unresolved` (Gate 1 rejects it) |
| No start face or axial offset (SB11033 F003 boss built with no offset) | `schema.Feature` | `on: face(...)` + a z expression; depth measured from the start face into the material |
| Circular / bolt-circle patterns can't be placed | `run_models.resolve_unknowns` | `pattern: circular` with an axis ref, count, start angle; radius comes from the seed |
| Revolves are TODO skeletons (SB11780 → one cylinder) | `macro_generator._macro_revolve_skeleton` | `revolve` with (z, r) station lists |
| Fillets/chamfers need interactive edge picks, fail in COM | `macro_generator._macro_fillet_chamfer` | Edge **queries**, resolved on the CadQuery reference to points, selected by point in SolidWorks |
| Numbers are free floats; you can't tell a read value from an invented one | everywhere | Expressions over `D###` IDs; ungrounded literals are flagged |

## Layering

```
DrawingData (unchanged v1 schema: what the drawing SAYS)
     │  planner (LLM, forced tool call, provider-agnostic)
     ▼
BuildPlan (IR v2: HOW to build it; every number is an expression over D-IDs)
     ├─► compile_cadquery  → script.py, reference.step, feature_map.json, renders
     └─► compile_solidworks (+ feature_map) → macros/*.vba | COM build
```

`DrawingData` stays the extraction contract; nothing downstream of extraction
changes in v1 mode. IR v2 is additive.

## Module layout

```
pipeline/ir/
  model.py              Pydantic BuildPlan models (non-null defaults convention, like schema.py)
  expr.py               safe expression parser/evaluator (whitelisted AST: + - * / ( ), numbers, D-IDs)
  refs.py               reference resolution: plane/face/axis/edge queries
  from_v1.py            plan_from_v1(DrawingData) -> BuildPlan (migration + baseline planner)
  compile_cadquery.py   BuildPlan -> CadQuery script text (deterministic) + run in subprocess
  compile_solidworks.py BuildPlan (+ feature_map) -> VBA package, reusing macro_generator emitters
pipeline/planner.py     Planner protocol + AnthropicPlanner, OpenAIPlanner (tool/function call; auto + strict on Opus 5.5)
```

## The part frame

- One right-handed frame per part, in drawing units. The compilers convert to
  meters, and the rule "every value through `to_meters()`" still applies.
- `frame.origin_kind` is one of:
  - `corner`: the min-x/min-y/min-z corner of the envelope. For prismatic parts.
    Matches the current drawing-frame convention (E003).
  - `axis_end`: the part axis is +Z, with the origin at the center of one end
    face. For turned parts.
- Base planes follow the SolidWorks standard: Front = XY, Top = XZ, Right = YZ.
- `frame.view_map` records which drawing view looks along which axis, e.g.
  `front: -Z`, `side: +X`. It's used for overlays (spec B) and multi-view
  consistency checks.

## Expressions

- Grammar: numbers, dimension IDs (`D007`), `+ - * /`, parentheses. Nothing else.
  They're parsed with a whitelisted AST, never `eval`.
- Every numeric field in the plan is an `Expr` string: `"D007"`,
  `"D012 - D009"`, `"D003 / 2"`.
- **Grounding rule:** literals other than `0`, `1`, `2` require a
  `justification` string on the owning feature. Gate 1 flags any ungrounded
  literal. Angles (`start_angle`, pattern angles) are degrees and may be literal
  when the drawing implies them ("EQ SP" → `360 / count`).
- The evaluator returns a value plus the set of D-IDs it used. That set is how
  dimension coverage is checked.

## References

| Ref | Meaning | Resolution rule |
|---|---|---|
| `plane(front\|top\|right)` | base plane through the origin | always exists |
| `face(F, ±X\|±Y\|±Z)` | planar face of feature F whose outward normal is that direction | must be unique, else a compile error listing the candidates |
| `axis(F)` | axis of a revolved/cylindrical feature F | F must be a revolve, a circular prism or a hole |
| `edge_between(refA, refB)` | edge(s) where two refs meet | resolved on the CadQuery solid; empty = compile error |

**Positions are always global part-frame coordinates** (`x`, `y`, `z`
expressions). `on:` only says where the feature *starts* and which way is "into
the material". There are no per-face local sketch frames. Stale local-frame
selection is a documented failure mode of LLM-written CAD code.

## Feature types

Every feature has these common fields:
- `id`
- `kind`
- `on` (a ref)
- `source_dims` (D-IDs, filled by the evaluator)
- `source_callouts` (verbatim callout text)
- `rationale` (one line from the planner)
- `status` (`planned` | `unresolved` | `unsupported`)

| kind | Key fields |
|---|---|
| `prism` | `profile` (`rect`: w, h, anchor `corner\|center` at x, y · `circle`: d at x, y · `slot`: c-c length, width, angle · `polygon`: point exprs), `depth`, `op` (`add`\|`cut`) |
| `revolve` | `axis` ref (default: part axis), `outer`: [(z, r)…], `inner`: [(z, r)…] optional (bores), `op` |
| `hole` | `center` (x, y, z), `spec` (`thru\|blind\|cbore\|csink\|tapped`, diameter, depth, cbore_d/depth, csink_d/angle, thread text → cosmetic only) |
| `pattern` | `seed` feature id; `linear` (dir, count, pitch) · `grid` (dir1, n1, p1, dir2, n2, p2) · `circular` (axis ref, count, start_angle, `equal`\|angle step); `skip` indices |
| `edge_op` | `fillet\|chamfer`, size expr(s), `edges`: [edge query…] |

Prohibited features (loft, sweep, boundary, shell, draft, surfacing, helical
threads) have no IR kind. The planner must mark them `unsupported`, and they
are reported, never built.

## Compilers

### `compile_cadquery(plan) -> CadQueryResult`
- Emits a **deterministic script** (no timestamps or paths, so golden tests
  work), runs it in a subprocess with a timeout, and exports `reference.step`.
- Writes `feature_map.json`:
  - per feature: the B-rep faces/edges it created
  - per hole: its measured axis, center, diameter and depth
  - per `edge_op`: one 3D point on each target edge
  - Gate 2 and the SolidWorks compiler both read this file.
- Renders orthographic PNGs (per `frame.view_map`) for the Gate 2 visual review.

### `compile_solidworks(plan, feature_map) -> MacroPackage`
- Reuses the `macro_generator` emitters and all CLAUDE.md hard rules: recorder
  pattern, plane fallback, direction-proof cuts, static `macro_audit`.
- **Edge ops:** select each edge by the point from `feature_map`, using
  select-by-point with an empty name, then call the fillet/chamfer feature. No
  interactive step.
- **Revolves:** sketch the station polyline on a plane containing the axis, then
  revolve.
- Both of these are **new SolidWorks API usage**. Per hard rule 1 they must be
  confirmed against a recorded macro on SW2024 before they ship, and logged in
  the error log if they fail.

## Planner

- `Planner.plan(drawing_data, view_images, history=[]) -> BuildPlan`, with the
  same tool-call and Pydantic repair-retry pattern as `extractor.py`, with one
  difference. **Opus 5.5 rejects forced `tool_choice` (`any` / named tool) with a
  400**, so the planner uses `tool_choice: auto` + `strict: true` on the plan tool
  and tells the model explicitly to call it. If no tool call comes back, that
  counts as a repair-retry failure.
- Every planner completion is recorded with
  `record_completion(..., role="planner")` inside `scope(gate=..., attempt=...)`
  (see `pipeline/token_tracker.py`).
- There are two implementations, `AnthropicPlanner` (Opus 5.5) and
  `OpenAIPlanner` (`gpt-6-astra`, function calling with the same JSON schema).
  Model IDs are pinned in config, never hard-coded in call sites.
- `history` is the auditor ledger (spec B). The planner prompt tells it to change
  only the features the findings name.
- `plan_from_v1` is a **deterministic baseline planner**. It converts v1 fields,
  fixes the center-vs-corner frame mismatch, and marks missing positions
  `unresolved`. It's used for migration and as a benchmark floor.

## Testing

- `expr.py`: grammar accepts and rejects the right strings; D-ID capture;
  division by zero; unknown IDs.
- Golden plans, each hand-written and checked against the drawing:
  - `bracket` (the existing fixture)
  - `SB11033` (flange + boss with offset + bolt circle + chamfers)
  - `SB11780` (revolve stations)
  - `116-C` (2×2 grid)
  - `A040911E` (counterbored bolt circle + tapped holes)
  - For each: the golden CadQuery script text, plus feature-map measurements
    asserted against the drawing's dimensions.
- `plan_from_v1` round-trips every `output/*/*_extraction.json` in the repo
  without exceptions. The count of `unresolved` features per part matches what
  the v1 build skipped.
- SolidWorks compiler: golden VBA plus `macro_audit` clean on every golden plan.
- Cross-compiler: on the Windows host, a STEP exported from the SolidWorks build
  matches the CadQuery `feature_map` within tolerance (this is benchmark track 2).

## Out of scope

Assemblies; sheet-metal features (bends and flat patterns; the 12 GA parts are
modeled as prisms); GD&T beyond carrying the datum and tolerance through;
tapped-thread geometry (cosmetic only, as today).

## Open questions (decide during planning)

1. Does `revolve` need arc segments between stations (fillets in the profile),
   or are those `edge_op`s applied afterwards?
2. For multi-view input, should the planner get the view images directly, or
   only `DrawingData` plus overlays? (The recommendation is both. The benchmark
   ablation compares them.)
3. How are `DrawingData` dimensions with `value_unclear` passed in? Proposal: the
   plan may cite them, and Gate 1 raises a warning finding that the Jev router
   can escalate.
