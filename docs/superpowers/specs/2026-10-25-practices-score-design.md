# MTI Best-Practices Score: Design (spec 2b)

**Date:** 2026-10-25 · **Status:** draft for user review
**Sub-project:** 2b. It fills the `practices` slot left by the
[benchmark scorer](2026-10-24-benchmark-scorer-design.md).
**Source:** MTI's best-practices folder in the MTI dataset (read only, outside git):
- `Modeling Best Practices.txt` (from MTI's Logan Foerch)
- `Solidworks Feature Guide.txt`
- six `.swp` macros

The macros were recovered: they are selection and display hotkeys (Front/Top/Right plane by tree position, multi-face select, cosmetic-thread display toggle). They add no new rules, but they confirm that MTI models on the standard planes and keeps threads cosmetic.
**Branch:** `feat/mti-benchmark` (local, never pushed without the user's say-so).

## Goal

A second number per part, from 0 to 100: **how well the SolidWorks part follows MTI's modeling
practices**. It is reported **as a separate column next to the geometry score and never blended into it**
(user decision 2026-10-25). This way a well-modeled but wrong part can't look good.

MTI calls these "general best practices, not hard rules". So the score is advice to the
pipeline, not a pass/fail gate.

**User rule.** A practice that the pipeline violates *systematically, by design* is **not scored**. It is
recorded as a "real big problem" in [docs/mti-practices-big-problems.md](../../mti-practices-big-problems.md)
to fix in the pipeline later.

## Practices: scored, excluded or deferred

The pipeline audit (2026-10-25, code evidence in the big-problems doc) sorted the practices into three groups:

| Id | Check | Pipeline today | Source of truth |
|---|---|---|---|
| C1 | Origin centered: base body symmetric about Front/Top/Right before cuts | follows | `ir_report.json` conventions ("origin centered", measured by the compiler after the base feature); for parts without a report, the final-body box centre (marked *proxy*) |
| C2 | Base sketch on the Top plane, Mid Plane extrude | follows | `ir_report.json` conventions (*self-reported*) |
| C3 | All sketches fully defined | mostly (29/30) | SLDPRT via COM: each `ProfileFeature` → `GetSpecificFeature2` → `GetConstrainedStatus() == 3`; credit = fraction fully defined |
| C4 | Fillets and chamfers after every cut, extrude and hole | not enforced | SLDPRT via COM: feature order (`FirstFeature`/`GetNextFeature`, `GetTypeName2`) |
| C5 | Hole Wizard placed from 2D sketches (no `3DProfileFeature`) | follows | SLDPRT via COM: sub-feature type names |
| C6 | One Hole Wizard feature per hole size per face | partial | `plan.json` hole signatures, using the compiler's own `hole_signature`, plus `ir_report.json` `mti_review` `mti_hole_grouping` |
| C7 | No "avoid" features (sweep, loft, boundary, shell, draft, rib, move face/body, surfaces); threads cosmetic | follows | SLDPRT via COM: `GetTypeName2` against an allow/avoid list in config |

**Excluded as big problems** (not scored):
- **P12:** features are located from model edges and the drawing's scheme isn't copied.
- **P7:** through holes use "Up To Next".
- **P10/P4:** pattern features are used, and copies aren't separate extrudes.
- **P11:** symmetry and mirror are used.
- **P5:** Hole Wizard is used for all bolt holes, including countersinks.

**Deferred (judgement):**
- **P6** (bolt vs plain hole, inch vs metric). Later it can be scored against MTI's own Hole Wizard features in the bench SLDPRTs.
- **"Fewer features"**, which needs a baseline such as MTI's model feature count.
- **"Relations over dimensions"**.

**Not checked by API until verified (hard rule 1).** C1 and C2 read the compiler's own report, because an independent SLDPRT check needs APIs this repo hasn't verified (`IExtrudeFeatureData2` end condition, `ISketch.GetReferenceEntity`, `EditRollback`). Once one of those is checked against the SolidWorks API docs or a recorded macro, its check moves to the SLDPRT. A *self-reported* label is shown on each such row until then.

## Scoring

- Each check gives a credit in [0, 1]:
  - C3 gives the fraction of sketches that are fully defined.
  - C6 gives 1 − duplicates / Hole Wizard features.
  - The others are 1 or 0.
  - A check that doesn't apply (e.g. C5 with no Hole Wizard holes) is dropped.
- Practices score = 100 × Σ wᵢ cᵢ / Σ wᵢ over the applicable checks. Weights live in `bench/score_config.yaml` (`practices:` section); the default is equal weight.
- Each failed check gets a blame stage:
  - planner: C4 (order is planned), C6 (signatures in the plan)
  - solidworks: C1, C2, C3, C5
  - C7 is planner if the plan has the kind, else solidworks.
- Each failure also has a one-line reason, e.g. "Fillet1 before Cut-Extrude3" or "Sketch5 under-defined".

## Architecture

| Module | Responsibility |
|---|---|
| `bench/practices.py` | `check_part(feature_tree, ir_report, plan, cfg) -> PracticeScore`: pure, testable without SolidWorks |
| `bench/sw_tree.py` | `read_tree(sw, sldprt) -> list[dict]`: opens the part read-only via `bench/sw_tasks.connect()`, walks the tree, records each feature's name, type, order, sketch status and sub-feature types, then closes it. Only APIs already used in the repo |
| `bench/score.py` | adds `practices` (score, rows, blame) to each part and a practices column / mean to the summary and `report.html`; `--no-sw` skips the SLDPRT checks (marked *not checked*) |

The feature tree is cached as `<part>/feature_tree.json` beside the SLDPRT, so a re-score needs no SolidWorks.

## Validation and tests (all $0)

1. **Units.** Each check runs on hand-made feature trees, ir_reports and plans. Cases:
   - passes and fails
   - not-applicable
   - weights
   - blame
2. **MTI's own models.** Run the COM tree reader and checks C3, C4, C5 and C7 on the 21 MTI reference SLDPRTs in `MTI_BENCH_DATA`, read only. MTI's engineers wrote these practices, so their models should mostly pass. Every failure is reviewed with the user. Either the check is wrong (fix the check) or MTI's own models don't follow it (lower its weight or drop it).
3. **Golden parts.** Score the 4 golden SolidWorks parts already in `output/sw2024_check/combined/` end to end.

## Out of scope

- Fixing the big problems: those are pipeline work, tracked in the big-problems doc.
- Sheet metal practices, since the IR has no sheet metal.
