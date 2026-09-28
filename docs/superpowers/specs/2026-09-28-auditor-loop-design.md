# Sub-project B — Auditor Loop + Jev Decision Layer — Design

**Date:** 2026-09-28 · **Status:** design approved; implementation plan after A lands
**Parent:** [AI CAD roadmap](2026-09-28-ai-cad-roadmap-design.md) · **Depends on:** [Feature IR v2](2026-09-28-feature-ir-v2-design.md)

## Goal

An agentic auditor that **approves or rejects** each design at two gates. It keeps
a persistent **history of every rejection and the reason for it**, and gives the
planner **up to 2 retries per gate** with that history as feedback before it
escalates to a human. It replaces two things:
- `run_models.py`'s silent "90%-confidence defaults"
- `model_validator`'s envelope-only PASS

## Principles

1. **Deterministic first, and final.** An error-severity deterministic finding
   can never be approved. Jev and the LLM reviewer can **add** findings, never
   remove them.
2. **Findings are structured data,** not prose, so the planner can act on them,
   the ledger can be queried, and rollups can be computed.
3. **Every numeric judgment is deterministic.** Jev only answers bounded discrete
   questions over text.
4. **One shared auditor.** The auditor configuration is fixed and versioned, and
   the same one serves every generator (this is required for benchmark C).

## Components

```
pipeline/audit/
  findings.py     Finding / Verdict models
  checks_plan.py  Gate 1 deterministic checks (BuildPlan + DrawingData)
  checks_geom.py  Gate 2 deterministic checks (feature_map + reference.step vs DrawingData)
  decisions.py    DecisionClient protocol; JevClient; LLMDecisionClient (fallback)
  overlay.py      draw plan / built geometry onto each drawing view at scale
  reviewer.py     pinned vision-LLM reviewer (overlay + renders vs drawing)
  ledger.py       append-only JSONL ledger + rollup
  loop.py         orchestrator: plan → Gate 1 → build → Gate 2, retries, escalation
```

## Finding and verdict

```python
Finding:  id, gate (1|2), source (deterministic|jev|reviewer), check (e.g. "coverage.unused_dimension"),
          severity (error|warning), feature_ids[], dimension_ids[], expected, actual, message
Verdict:  APPROVE | REJECT | ESCALATE, findings[], reason, decided_by (rule|jev|reviewer|human)
```

`Finding.id` is stable across attempts: a hash of check + feature_ids +
dimension_ids. That's what makes regression detection possible.

## Gate 1 — plan audit (before anything is built)

**Deterministic checks (`checks_plan.py`):**

| Check | Catches |
|---|---|
| `expr.resolves` | unknown D-IDs, bad syntax, division by zero |
| `expr.grounded` | literals without a justification |
| `coverage.unused_dimension` | a non-REF dimension used by no feature. **This catches "10 of 26 built"** |
| `coverage.unplanned_callout` | a hole callout with no hole/pattern feature, or instance count ≠ qty |
| `position.unresolved` | features with `status=unresolved` |
| `envelope.contains` | feature centers/profiles outside the part envelope |
| `chain.closure` | dimension chains that don't close (reuses `validator._check_dimensional_closure`) |
| `pattern.feasible` | pattern extent exceeds the envelope; grid vs. linear mismatches (E009 class) |
| `refs.valid` | `on:`/axis refs point at earlier features; face refs have the right orientation |
| `prohibited` | an unsupported feature kind is planned as buildable |

**Jev decisions (`decisions.py`):** each question is asked over text state (the
verbatim callout text, the feature's planned fields, nearby notes):

| Question | Type | Use |
|---|---|---|
| "Given callout `<text>`, is the planned hole spec `<spec>` consistent?" | yes/no | finding when p(no) > τ |
| "Callout `<text>` describes which pattern?" none/linear/grid/circular | choice | finding when it differs from the plan |
| "Is `<dim text>` a reference (non-controlling) dimension?" | yes/no | cross-check `is_reference` |
| "Is this dimension chain symmetric (offset + span + offset)?" | yes/no | E009 symmetric-chain class |

**LLM reviewer (`reviewer.py`):** a pinned vision model sees each drawing view with
the **plan overlaid at scale**, planned outlines and hole centers in color with
IDs, and returns structured findings, e.g. "H2 overlay center is ~0.4 in left of
the drawn hole". It's prompted to report only mismatches it can point to.

## Gate 2 — geometry audit (after `compile_cadquery`)

**Deterministic (`checks_geom.py`):**
- `build.success`: the script ran and STEP was exported.
- `build.feature_count`: every planned feature produced geometry (from `feature_map`).
- `geom.hole`: each hole's measured center, diameter and depth vs. its
  *drawing* dimension, within tolerance. The tolerance comes from
  `Dimension.tolerance_*`, else the title-block general tolerance, else a config
  default.
- `geom.envelope`: bounding box vs. the envelope dimensions.
- `geom.open_regions`: through features actually break through; nothing that was
  cut has been refilled by a later op.

**LLM reviewer:** orthographic renders of the solid next to each drawing view, plus
the Gate 1-style overlay of the *measured* geometry.

## The loop (`loop.py`)

```
retries = {1: 0, 2: 0}; attempt = 0
plan = planner.plan(drawing, views, history=[])
while True:
    # ---- Gate 1: plan ----
    v1 = evaluate(gate=1, plan)                       # deterministic + jev + reviewer → decide()
    ledger.append(part, attempt, 1, plan, v1)
    if v1 == ESCALATE: return escalate(part)
    if v1 == REJECT:
        if retries[1] == 2: return escalate(part)
        retries[1] += 1; attempt += 1
        plan = planner.plan(drawing, views, history=ledger.findings(part))   # FULL history
        continue
    # ---- Gate 2: geometry (only for a Gate-1-approved plan) ----
    ref = compile_cadquery(plan)
    v2 = evaluate(gate=2, plan, ref)
    ledger.append(part, attempt, 2, plan, v2)
    if v2 == APPROVE: return approved(plan, ref)      # → compile_solidworks
    if v2 == ESCALATE or retries[2] == 2: return escalate(part)
    retries[2] += 1; attempt += 1
    plan = planner.plan(drawing, views, history=ledger.findings(part))
    # the new plan goes back through Gate 1 (its Gate-1 retry count is unchanged)
```

**`decide(findings)`:**
- There are no error findings → `APPROVE`.
- Any finding whose stable ID was **resolved earlier and has come back** →
  `ESCALATE` (the model is going in circles).
- Otherwise, the Jev router asks: "Given these findings, can the planner fix them
  from the drawing, or do they reflect a drawing ambiguity needing a human?"
  - fixable → `REJECT` (retry)
  - ambiguity → `ESCALATE`
  - low confidence → `REJECT` if retries remain, else `ESCALATE`

**Escalation:**
- Writes `output/<Part>/audit/ESCALATED.md`, listing the open findings, the
  overlays, and the candidate readings (`possible_values`).
- A human answers through the CLI now and MCP `resolve` later. That's recorded
  in the ledger with `decided_by=human`, and the loop resumes.

## Ledger and rollup

- `output/<Part>/audit/ledger.jsonl`, append-only, one line per gate evaluation:
  `ts, part, attempt, gate, plan_hash, planner_model, auditor_version, findings[], verdict, tokens, cost`.
- Plans are stored alongside as `plan_v<attempt>.json`, so any rejection can be
  replayed.
- `python -m pipeline.audit.rollup` → `docs/audit-rejections.md`: the most
  frequent checks, by planner model and by part family. This is the
  institutional-memory successor to `docs/solidworks-macro-error-log.md`, the
  same way E001–E010 hardened the generator. Recurring rejection classes drive
  prompt and IR changes.

## Jev integration details

- The `DecisionClient` protocol has the method
  `ask(state: dict, questions: list[Question]) -> list[Answer]`. It returns
  probabilities for yes/no and a distribution for choice questions.
- There are two implementations:
  - `JevClient`: Jev typed questions, many questions per state in one request.
  - `LLMDecisionClient`: the same questions via a small pinned LLM with
    constrained output. This is the fallback and the calibration comparator.
- **Calibration before trust.** Build a labeled set from the repo's existing
  extractions (hole-callout texts → true type/pattern; about 100 items to start)
  and measure the accuracy of each client and each question type. For each
  question type, set τ so Jev is used only where it beats the fallback. Record the
  calibration result in the auditor version.
- **Never numeric:** Jev never produces or compares numbers. Its docs flag
  numbers as a weakness, and every tolerance comparison is deterministic.

## Replacing v1 auto-resolution

`run_models.resolve_unknowns` keeps working in v1 mode, but in IR mode it's
replaced. Ambiguous dimensions and non-closing chains become Gate 1 findings. The
planner may choose among `possible_values` with a justification, which the
auditor checks. What can't be resolved escalates instead of being guessed.

## Testing

- For each deterministic check: a fixture plan that trips it, and one that
  passes (the SB11033/SB11780/116-C golden plans from spec A, with mutations
  applied).
- A loop test with a scripted fake planner covering four cases: fixes on retry 1
  → APPROVE; never fixes → ESCALATE after 2; regresses a fixed finding → early
  ESCALATE; ambiguity → ESCALATE with no retry.
- The ledger round-trips; the rollup is deterministic.
- Decision clients are mocked in unit tests. Calibration runs as a separate,
  opt-in script that makes API calls.

## Open questions

1. Reviewer model choice. A pinned Opus 5.5 reviewer could favor Opus plans in
   benchmark C. Mitigations: deterministic checks dominate, and spec C runs a
   reviewer-swap sensitivity check.
2. The retry budget is 2 per gate (approved). Should the Gate 1 → Gate 2
   interaction share a total cap per part (for example 4) to bound cost? Decide
   from the first benchmark cost data.
