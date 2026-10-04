# Feature IR v2 Implementation Plan (sub-project A)

> Spec: [2026-09-28-feature-ir-v2-design.md](../specs/2026-09-28-feature-ir-v2-design.md).
> Executed inline (TDD) on `feat/openai-extractor-sw2025` → its own branch once A lands.
> Evidence for the scope: STATE.md §3.0 (2026-10-04 deep dive). Every remaining
> build failure on the dev parts is either IR-inexpressible geometry (R2) or missing
> drawing information (R6).

**Goal:** a typed BuildPlan in which every number is an expression over drawing
dimension IDs, compiled deterministically to (1) a CadQuery reference + STEP + measured
feature map, and (2) a native SolidWorks part.

**Architecture:** `pipeline/ir/` per the spec. `DrawingData` stays the extraction
contract. IR is additive: v1 mode keeps working unchanged until the IR path beats it on
the dev set.

**Tech stack:** Python 3.13, Pydantic v2, CadQuery (OCP) for the reference, SolidWorks
2025 SP5 over COM for the native track, pytest.

## Decisions on the spec's open questions

1. **Arcs in revolve profiles:** not in v1 of the IR. Stations are straight segments
   (z, r). Profile fillets/chamfers are `edge_op`s applied afterwards (the same edge
   machinery as prisms). Revisit if a dev part needs a true arc profile.
2. **Planner inputs:** both `DrawingData` and the view images (spec recommendation).
   The benchmark ablation (C5) measures the difference.
3. **`value_unclear` dims:** the plan may cite them. Gate 1 raises a warning finding
   that B7 (Jev router) can escalate. Never silently used as certain.

## Global constraints

- Code in `2D-3D-CAD-Test-Generation/pipeline/ir/`. Tests: `PYTHONUTF8=1 python -m pytest tests -q`.
- Expressions are parsed with a whitelisted AST, **never `eval`**.
- Compilers are deterministic: no timestamps, absolute paths or dict-order dependence
  in emitted scripts/macros (golden tests).
- Any NEW SolidWorks API call (revolve, select-by-point) is verified live on the
  SolidWorks host before it ships, and any failure is logged in the error log (hard rule 1).
- Planner model calls go through `budget.preflight/charge` and `record_completion(role="planner")`.
  Opus 5.5 uses `tool_choice: auto` + `strict: true` (CLAUDE.md rule 10).
- Tuning and golden plans use **dev** parts only (`bench/manifest.yaml`).
- The existing 243 tests keep passing. v1 output is unchanged.

## Tasks

### Task 1: Expressions (`pipeline/ir/expr.py`)
- `parse(expr: str) -> Node`, `evaluate(expr, dims: dict[str, float]) -> Evaluated(value, dim_ids)`.
- Grammar: numbers, `D\d{3,}`, `+ - * /`, unary minus, parentheses.
- `literals(expr) -> set[float]`, used for the grounding rule (literals other than 0/1/2
  need a justification).
- Tests: accepted/rejected strings, D-ID capture, divide-by-zero, unknown IDs,
  rejection of names/calls/attributes/`**`.

### Task 2: BuildPlan model (`pipeline/ir/model.py`)
- `Frame` (`origin_kind: corner|axis_end`, `units`, `view_map`), refs (`plane`, `face`,
  `axis`, `edge_between`), features: `prism` (rect/circle/slot/polygon, `op`), `revolve`
  (outer/inner stations), `hole` (thru/blind/cbore/csink/tapped), `pattern`
  (linear/grid/circular), `edge_op`. Common: `id, kind, on, rationale, source_callouts,
  status (planned|unresolved|unsupported), justification`.
- `BuildPlan.check(dims) -> list[Finding]`: unknown dim IDs, ungrounded literals,
  unresolved features, dangling refs. This is the deterministic core of Gate 1 (B1).
- Tests: round-trip JSON; JSON schema generation; every finding type.

### Task 3: Baseline planner `plan_from_v1` (`pipeline/ir/from_v1.py`)
- Deterministic DrawingData → BuildPlan. It applies the frame rules proven in F1/F6
  (round part → `axis_end`; plate → `corner`; center vs corner positions reconciled),
  converts holes/patterns/cbores, and marks anything without grounded geometry `unresolved`.
- Tests: migrates every `output/**/*_extraction.json` without exceptions. The
  unresolved count is no worse than the v1 rebuild's unbuilt features (STATE.md §2.1).

### Task 4: CadQuery compiler (`pipeline/ir/compile_cadquery.py`)
- `emit_script(plan, dims) -> str` (deterministic), `run(script, out_dir, timeout)` in a
  subprocess, producing `reference.step` plus `feature_map.json` (per hole: axis, center,
  diameter, depth; per edge_op: one point on each target edge; bbox; volume).
- Kinds in order: prism (rect, circle, slot) → hole (thru, blind, cbore) → revolve →
  pattern (circular, linear, grid) → edge_op (`edge_between` queries).
- Tests: golden script text per golden plan; measured feature map asserted against the
  drawing dims.

### Task 5: Golden plans (dev parts, hand-written, checked against the drawing)
- `demo_plate` (the known answer, 0.000 mm today), `SB11033` (stacked boss, bolt circle,
  chamfers), `SB11780` (revolve stations + necks + keyway), `A040921E` (through-wall end
  slot as `D002/2 .. D001/2`), `A040911E` (counterbored 3-hole circle). Plus the
  existing `bracket` fixture.

### Task 6: SolidWorks compiler (`pipeline/ir/compile_solidworks.py`, COM first)
- Reuse the hardened builder (placement, cuts, counterbores, inferred-edge machinery).
  New: revolve from stations, edge selection by feature-map point.
- **Live verification first** (probe scripts, as for E012). Then cross-compiler check:
  SolidWorks STEP vs CadQuery feature map within tolerance.

### Task 7: Planner (`pipeline/planner.py`)
- `AnthropicPlanner` (Opus 5.5), `OpenAIPlanner` (`gpt-6-astra`). Same tool schema;
  repair retry; budget guard; token tracker `role="planner"`. Model IDs from config.

### Task 8: Wire-up and dev-set comparison
- `main.py --ir`. Rebuild the 9 dev parts via the IR and compare with v1 (STATE.md §2.1).
  The IR path replaces v1 only when it is not worse on any dev part.

## Status
- [x] Split fixed: `bench/manifest.yaml` (9 dev parts, held-out pending)
- [ ] Task 1 · [ ] Task 2 · [ ] Task 3 · [ ] Task 4 · [ ] Task 5 · [ ] Task 6 · [ ] Task 7 · [ ] Task 8
