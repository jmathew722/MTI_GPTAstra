# Sub-project C — Placement-Aware CAD Benchmark — Design

**Date:** 2026-09-28 · **Status:** design approved; implementation plan after A + B
**Parent:** [AI CAD roadmap](2026-09-28-ai-cad-roadmap-design.md) · **Depends on:** [IR v2](2026-09-28-feature-ir-v2-design.md), [Auditor](2026-09-28-auditor-loop-design.md)

## Goal

Measure which model, **Claude Opus 5.5** or **OpenAI GPT-6 Astra**
(`gpt-6-astra`), produces MTI parts with **correct relative placement and
dimensioning**, both on its own and inside our auditor loop.

## Why not just use BenchCAD

BenchCAD (17,900 CadQuery parts, 106 families) scores voxel IoU at 256³,
Chamfer/Hausdorff distance and Feature-F1. These are volume and shape metrics.
A 0.25" hole misplaced by 0.05" barely moves IoU. Published critiques of Astra
also describe misaligned holes from stale face selection, frame errors, and an
opening wrongly closed at 96.1% IoU. The Astra scores (95.9%; Opus 5 82.1%;
Fable 5.1 84.3%) are also vendor-reported. We report IoU and Chamfer only for
comparability. **The headline metrics are placement metrics.**

## Dataset

| Split | Parts | Rationale |
|---|---|---|
| **dev** (prompt/IR tuning allowed) | 115-C, 116-C, 117-C, 135-A | Already used to harden the generator (error log E001–E010); they can't be "unseen" |
| **held-out** (never tuned on) | A040911E, A040921E, SB11033, SB11780, SB11842 | Clean multi-view drawings in `ViewDefinedDrawings/`; they cover turned, flanged, bolt-circle, bearing and tie-rod geometry |
| **held-out, later** | curated `NewVerifiedDrawings/` parts | Only after human view labeling (see STATE.md §2) |

The split is **fixed in `bench/manifest.yaml` before any tuning** and changed only
by a reviewed PR.

Per part, the manifest records:
- the drawing view images
- `reference.step` (MTI model exported to STEP)
- units and the tolerance source (dimension tolerance or the title-block general
  tolerance)
- `split`

## Answer key from reference models

`bench/keys/<part>.json` is generated from the reference STEP with OCP (the kernel
CadQuery is built on):

- **Cylindrical features:** group coaxial cylindrical faces into holes, bores,
  counterbores, bosses and turned diameters. For each: axis, center (the axis
  point at its start face), diameter(s), depth(s), thru/blind.
- **Planar features:** step and pocket faces, with normal and offset.
- **Envelope:** the bounding box.
- **Links to the drawing:** each key feature is linked to the D-IDs that dimension
  it. This is done semi-automatically, suggested by value match, then confirmed by
  a human.

**A human signs off each key once** (`signed_off_by`, date). An unsigned key is
excluded from scoring.

## Scoring (`bench/score.py`)

1. **Alignment.** The candidate STEP (from `compile_cadquery`) may use a
   different origin or orientation. Try the 24 axis-aligned rotations. For each,
   translate by bounding-box alignment, then refine the translation by minimizing
   matched feature-center distance. Keep the lowest-cost pose. If a symmetric part
   gives several equal poses, any one is fine.
2. **Matching.** Optimal assignment (Hungarian algorithm) between candidate and
   key features, with cost = center distance + diameter difference. Pairs beyond
   a gating distance don't match.
3. **Metrics** per part:

| Metric | Definition |
|---|---|
| **Placement pass rate** | matched features with center error ≤ position tolerance, ÷ key features |
| **Relative placement** | over all key feature pairs (i, j): \|‖cᵢ−cⱼ‖ − ‖rᵢ−rⱼ‖\|. Report the median, p95, and % within tolerance. Independent of datum choice. |
| **Dimensional pass rate** | matched features whose diameter/depth are within the drawing tolerance |
| **Completeness** | recall = matched ÷ key features (missing features); precision = matched ÷ candidate features (phantom features) |
| **Exact-part** | 1 if every key feature is matched and passes placement + dimensional checks, else 0 |
| **Build success** | the CadQuery build ran; for the SolidWorks track, the SW build too |
| **Shape (comparability)** | voxel IoU at 256³ and Chamfer distance vs. the reference |
| **Cost** | input/output tokens, $, wall time, planner calls, retries used, escalated? |

**Headline results:** exact-part rate and relative-placement % within tolerance,
per arm, on held-out.

## Arms

| Arm | Planner | Auditor |
|---|---|---|
| `opus-raw` | Opus 5.5, single shot | off (one plan, scored as-is; a compile failure scores 0 on every geometry metric) |
| `opus-audited` | Opus 5.5 | fixed auditor, 2 retries/gate |
| `astra-raw` | GPT-6 Astra, single shot | off |
| `astra-audited` | GPT-6 Astra | fixed auditor, 2 retries/gate |
| `*-fixedread` (ablation, raw) | each model | off. **Both plan from the same `DrawingData`** made by one pinned extractor, which isolates placement skill from reading skill |

- In the normal arms, **each model does its own read (extraction) and plan**.
  In the ablation arms, reading is held constant.
- The auditor is **identical across arms**: same auditor version, same Jev
  calibration, same pinned reviewer model.
- **Reviewer-swap check:** the audited arms are re-run on held-out with the
  reviewer model swapped to the other vendor, and the difference is reported. If
  the ranking flips, the auditor result is reported as reviewer-dependent.
- An **escalated** part scores what the best non-escalated attempt produced, and
  also counts toward the escalation rate. Humans don't intervene during benchmark
  runs.

## Runs and reproducibility

- **3 runs per part per arm.** Results are reported as mean ± spread, and per-part
  variance is shown.
- Each run manifest pins: model IDs and parameters, prompt hashes, IR schema
  version, auditor version, Jev calibration ID, git SHA, and the date.
- Model calls go through the existing extraction cache only in the **ablation's
  fixed-read step**. Everything else is called fresh, so a cache hit never
  masquerades as a run.

## Tracks

1. **CadQuery track** (headless, any OS): every arm, every part.
2. **SolidWorks track** (Windows + SW2024 host): approved plans from the audited
   arms → `compile_solidworks` → build → export STEP → scored against the same
   key. This measures **compiler fidelity** (does the SW build match the CadQuery
   reference?), not model skill. It's reported separately.

## Layout

```
2D-3D-CAD-Test-Generation/bench/
  manifest.yaml          parts, splits, tolerance sources, arm definitions
  reference/<part>.step  MTI reference models (not committed if MTI-confidential; see below)
  keys/<part>.json       signed-off answer keys
  keygen.py              reference STEP → draft key
  run.py                 run arms × parts × repeats → results/<run_id>/raw/
  score.py               alignment, matching, metrics
  report.py              results/<run_id>/summary.csv + report.html
```

## Testing the benchmark itself

- **Scorer self-test.** Scoring a reference against itself gives 100% on every
  metric, under all 24 rotations and arbitrary translations.
- **Seeded perturbations.** Move one hole by 1.5× its tolerance → exactly that
  feature fails placement and the relative-placement pairs involving it degrade.
  Delete one feature → recall drops by 1/N. Add one → precision drops.
- **Key generation.** On the golden plans from spec A, compile them to STEP, run
  `keygen`, and check it recovers the planned holes exactly.

## Open questions

1. Are MTI reference models confidential? If so, `reference/` and `keys/` live
   outside git (or in a private LFS remote), and only the scores are committed.
2. Should the free-form CadQuery arm (the model writes CadQuery directly, as in
   BenchCAD) be added later, to test whether the IR constraint handicaps Astra?
   The roadmap lists this as a risk mitigation.
3. What is the position tolerance when the drawing gives none? Proposal: the
   title-block general tolerance for the number of decimal places, else ±0.005 in
   / ±0.1 mm.
