# AI CAD Roadmap — Design (umbrella)

**Date:** 2026-09-28 · **Status:** approved in brainstorming, specs A–C written, D placeholder
**Author:** ggould (MalteseWarrior) with Claude · **Builds on:** [2026-06-11 pipeline design](2026-06-11-2d-to-3d-solidworks-pipeline-design.md)

## Problem

The v2 pipeline reads drawing dimensions well but **places features badly**, and
nothing catches it:

- On the 5 parts built to `.SLDPRT`, **10 of 26** extracted features were built
  (see `STATE.md` §2).
- Bolt-circle holes are never auto-placed, and fillets/chamfers always fail in the
  COM path. Turned parts (SB11780) collapse to a single cylinder.
- `model_validator` reported **PASSED** on all 5, because it only checks the
  envelope and volume.
- `run_models.py` auto-accepts its best guess on ambiguous dimensions, which
  bypasses the READY/BLOCKED gate.

We also want to know **which frontier model is best at CAD with correct relative
placement and dimensioning**: Claude Opus 5.5 or OpenAI GPT-6 Astra
(`gpt-6-astra`). Public numbers don't answer this. Astra's reported 95.9% on
BenchCAD (vs. Opus 5 at 82.1%, Fable 5.1 at 84.3%) is scored by voxel IoU,
Chamfer/Hausdorff distance and Feature-F1. Those metrics barely penalize a hole
that's in the wrong place or an opening that was wrongly closed.

## Decisions (from brainstorming, 2026-09-28)

| # | Decision | Chosen | Rejected |
|---|---|---|---|
| 1 | Deliverable | **Both, staged:** a CadQuery/STEP reference solid first, then a native SolidWorks part checked against it | SW-only; geometry-only |
| 2 | What the LLM produces | **A constrained feature IR** (typed build plan) compiled deterministically | Free-form CadQuery/VBA code |
| 3 | Benchmark ground truth | **MTI reference models** (exported to STEP) | Hand-built key; synthetic parts |
| 4 | Auditor gates | **Plan + built geometry** (two gates) | Plan only; geometry only |
| 5 | Benchmark ↔ auditor | **One fixed shared auditor; each generator scored raw and audited** | Self-audit; cross-audit |
| 6 | Architecture | **Evolve the current pipeline in place** | Greenfield package; wrap Adam's Astra MCP |
| 7 | Retry budget | **2 retries per gate**, with the full rejection history fed back | Shared budget |
| 8 | UX | **MCP connector** usable from the team's Claude IDE (sub-project D) | — |

### Why these

- **The IR (2):** every coordinate becomes an expression over drawing dimension
  IDs. That makes placement inspectable field by field, auditable against the
  drawing, and compilable to *both* CadQuery and SolidWorks from a single source.
  Free-form code hides placement errors inside code, and the result is different
  for every backend.
- **The staged deliverable (1):** a headless CadQuery reference can be measured on
  any OS. That's what makes the auditor's Gate 2 and the benchmark objective.
  SolidWorks stays the delivery target, and the native build is scored against
  the reference.
- **Evolving in place (6):** keeps the runtime-hardened SolidWorks emitters
  (error log E001–E010), the static macro audit, golden tests, the extraction
  cache and the verification gate. A greenfield rewrite would relearn those
  failures on a real machine.
- **Jev's role:** Jev (TypeSafe AI decision model) takes **text** and returns
  typed probabilistic answers: yes/no, choice, score. Its own docs say it is weak
  with numbers, and it doesn't promise the same answer on every run. So it is used
  only for **bounded discrete decisions**: callout classification, plan-consistency
  questions, and the retry-vs-escalate call. Every numeric check stays
  deterministic, and a deterministic failure can't be overruled.

## Architecture

```
drawing views ──► [READ] extractor ──► DrawingData (what the drawing says)
                                            │
                                            ▼
                  [PLAN] planner (Opus 5.5 | GPT-6 Astra) ──► BuildPlan IR v2
                                            │
                       ┌── Gate 1 audit (deterministic → Jev → LLM overlay review)
                       │     REJECT → planner retry w/ full ledger (≤2) → ESCALATE
                       ▼ APPROVE
                  compile_cadquery ──► reference solid + STEP + renders
                                            │
                       ┌── Gate 2 audit (measure STEP vs drawing, render review)
                       │     REJECT → planner retry (≤2) → ESCALATE
                       ▼ APPROVE
                  compile_solidworks ──► VBA package / COM build ──► .SLDPRT
                                            │
                  bench scorer: STEP vs MTI reference STEP (placement, dims, completeness)
```

Every stage writes its record to `output/<Part>/`: `extraction.json`,
`plan_vN.json`, `audit/ledger.jsonl`, `reference.step`, renders, and the macro
package.

## Sub-projects

Each gets its own spec → implementation plan → implementation cycle, in this order.

| | Sub-project | Spec | Depends on |
|---|---|---|---|
| A | Feature IR v2 + CadQuery & SolidWorks compilers | [2026-09-28-feature-ir-v2-design.md](2026-09-28-feature-ir-v2-design.md) | — |
| B | Auditor loop + Jev decision layer | [2026-09-28-auditor-loop-design.md](2026-09-28-auditor-loop-design.md) | A |
| C | Placement-aware benchmark (Opus 5.5 vs GPT-6 Astra) | [2026-09-28-placement-benchmark-design.md](2026-09-28-placement-benchmark-design.md) | A, B |
| D | MCP connector / IDE UX | this doc, §D below | A–C |

## D — MCP connector (placeholder; full design after A–C)

- **One MCP server made of thin wrappers** over the same functions the CLI uses:
  `extract_drawing`, `plan_build`, `audit(gate)`, `build_reference` (STEP +
  renders), `build_solidworks`, `compare(reference_step)`, `get_ledger`,
  `run_benchmark(subset, arms)`, `resolve(part, finding_id, choice)`.
- **Two hosts.** The core server runs on any OS. A **SolidWorks worker** on the
  Windows + SW2024 machine registers itself, and `build_solidworks` is offered
  only while a worker is online.
- **Human in the loop.** An escalated part shows its ledger and overlay images in
  the IDE. `resolve` records a *human* decision in the ledger and resumes the loop.
- **Pinned models.** Model calls run server-side with pinned models (reproducible,
  benchmark-comparable). "The IDE's own model acts as planner" is a later option.
- **Transport:** local stdio first.
- **Prior art to review first:** Adam's MCP server for Astra (SolidWorks /
  Onshape / Fusion, "render-measure-check loop").

## Prerequisites

- MTI reference models for the benchmark parts, exported to **STEP**.
- A human-curated view labeling for `NewVerifiedDrawings/`. Many `_front_view` /
  `_side_view` files are unrelated components (`STATE.md` §2).
- API access: Anthropic (Opus 5.5), OpenAI (`gpt-6-astra`), TypeSafe (Jev).
- `pip install cadquery` (brings in OCP) on dev machines, plus the existing
  requirements. The pytest suite must be green before A starts.
- A Windows + SolidWorks 2024 host for the SolidWorks track.

## Risks

| Risk | Mitigation |
|---|---|
| The IR can't express some real MTI geometry | Unsupported features go to `escalate` with a finding. Their frequency is tracked in the audit rollup, and the IR grows from data rather than speculation. |
| CadQuery and SolidWorks compilers diverge | The SolidWorks track scores SolidWorks STEP exports against the same reference. A shared golden-plan test suite runs through both compilers. |
| Vendor-reported Astra strength doesn't carry over to our IR | Benchmark C measures exactly this. A free-form CadQuery arm can be added later as an ablation if the IR looks like it's handicapping a model. |
| Jev is unavailable or poorly calibrated | Jev checks sit behind an interface with an LLM fallback. Calibration is measured on a labeled set of callouts before Jev is trusted (spec B). |
| Benchmark overfitting to prompts tuned on the same parts | Held-out split, fixed before any tuning (spec C). |
