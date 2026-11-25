# Extraction-to-Model Fidelity (EMF): the scoring rubric

**Audience:** engineers and reviewers who need to understand, run or change the score. Code: `2D-3D-CAD-Test-Generation/bench/fidelity.py`.
Every number lives in `bench/fidelity_config.yaml`. UI: the **Scoring** sidebar tab. Version 1.0 (2026-11-25).

## What it answers

*How closely does the real SolidWorks part match what the drawing's extraction asked for?* The extraction JSON is the contract: its overall
dimensions, hole callouts, features and its own confidence. The **actual 3D part** is the other side: it is measured on the STL that SolidWorks
exported from the `.SLDPRT` (the same file the 3D viewer shows), never on the plan or the CadQuery reference. A wrong, stale or half-built model
cannot score well, and no answer key is needed, so every built part gets a score. It is free: no API calls, no SolidWorks session.

The older answer-key benchmark (`bench.score`, `docs/…/scoring.md`) still exists as an optional second measure for the 19 benchmark parts that
have signed keys. It is shown separately and never blended in.

## The score: 100 points, six categories, colour banded

| # | Category | Points | Question | How it is measured |
|---|---|---|---|---|
| 1 | Build integrity | 15 | Did SolidWorks build every planned feature, and does the exported mesh belong to this build? | build record + mesh |
| 2 | Overall size | 20 | Does the real part's bounding box match the drawing's overall dimensions? | STL bounding box vs extraction dimensions |
| 3 | Feature coverage | 20 | Is every feature the extraction asked for actually in the model? | extraction features vs build status, weighted by importance |
| 4 | Hole and bore accuracy | 20 | Do the holes measured in the real part have the drawn diameters, depths and types? | holes found in the mesh vs hole callouts |
| 5 | Placement and patterns | 15 | Are the holes the right distance apart and concentric? | frame-free pattern spacing, counterbore concentricity |
| 6 | Extraction reliability | 10 | How much of the score rests on unclear, assumed or defaulted input? | confidence, ambiguity, assumptions, flags |

**Colour bands (out of 100).** Each band also has a word and a glyph, so colour is never the only cue.

| Band | Range | Label |
|---|---|---|
| Green | 90 to 100 | Matches the drawing |
| Amber | 75 to under 90 | Review recommended |
| Orange | 60 to under 75 | Significant deviations |
| Red | under 60 | Does not match |

### How a score is computed

```
item credit      = 1 if e <= 1, else 0.5 x exp(-(e - 1) / 4.48)        e = |measured - drawing| / tolerance
category %       = 100 x sum(item weight x item credit) / sum(item weight)
score            = 100 x sum(category weight x category %) / sum(weights of the categories that could be checked)
```

* **Tolerance** is the drawing's own (`tolerance_plus` / `tolerance_minus`); if none, 0.005 in or 0.1 mm. Nothing is judged tighter than the mesh
  floor (0.0015 in / 0.04 mm), the STL tessellation noise.
* A category with **nothing checkable** is dropped and the rest are rescaled; the report shows the coverage. Below 50% checkable, **no score is given**.
* **Missing evidence is never 0.** No STL is *Incomplete: No exported STL*; no SolidWorks part is *Build failed or no part*; a crashed scorer is
  *Scoring failed*. A real zero stays a real zero.
* **Critical gate:** any critical issue caps the score at 49.9 (red).

## What is checked

1. **Build integrity (15):** SolidWorks build completed (4); every planned feature built (4); no fallback or substituted features (2); the exported
   mesh is a closed solid (2); the exported mesh is the model that was built (3): its size matches the build record within 2% and it is not older
   than the SLDPRT. A mismatch is **critical**: it means a stale or wrong export, and every measurement would describe the wrong shape.
2. **Overall size (20):** expected sizes come only from dimensions explicitly named overall, plate/block/sheet thickness or outside diameter on the
   base feature. The real part's sorted bounding box is matched to them. More than 10% off is **critical**.
3. **Feature coverage (20):** each extraction feature is built (full credit), built with a fallback (0.8), skipped, unresolved (the planner asked a
   question) or missing (none). Weights: boss/revolve 10, cut and hole 5, pattern 3, fillet and chamfer 1; cosmetic threads follow their hole.
4. **Hole and bore accuracy (20):** the mesh is searched for full-circle cylinders on a principal axis. Each is classified hole/boss, blind/through
   (a floor or drill-point cone closes it) and merged with a coaxial larger cylinder as a counterbore. Callouts are matched to measured holes by
   diameter (tapped holes accept 70% to 103% of the nominal thread, i.e. any tap-drill size). Per hole: diameter, through-or-depth, counterbore size
   and depth. Missing holes score 0; holes that match no callout cost up to 25% (except those behind a callout whose size was not read).
5. **Placement and patterns (15):** frame-free, so no alignment guess: each pattern's nearest-neighbour spacing against the extraction's instance
   positions, and counterbore-to-hole concentricity. Absolute position of a single hole needs an answer key and is covered by the benchmark scorer.
6. **Extraction reliability (10):** confidence (4), unclear dimensions and unknown positions (3), assumed positions, applied defaults, open questions
   and critical or high engineering flags (3).

## Issues and warnings

Each finding has a **severity**, a stable **code**, a message, evidence and the points it cost.

| Severity | Meaning | Examples |
|---|---|---|
| Critical | The model cannot be trusted; caps the score | `STL_NOT_THIS_BUILD`, `ENVELOPE_OFF`, `NO_MODEL` |
| High | A feature or hole is missing, wrong type or built wrongly | `HOLE_MISSING`, `FEATURE_SKIPPED`, `HOLE_NOT_THROUGH`, `CBORE_MISSING`, `PATTERN_SPACING` |
| Medium | A measurable deviation, fallback or open question | `HOLE_DIAMETER`, `HOLE_DEPTH`, `FALLBACK_USED`, `HOLE_EXTRA`, `OPEN_QUESTIONS`, `CALLOUT_NOT_SCORABLE` |
| Low | Worth knowing | `DEFAULTS_APPLIED`, `POSITION_UNKNOWN`, `AMBIGUOUS_DIMENSIONS` |
| Note | Advisory only, never lowers the score | `MTI_PRACTICE`, `ENVELOPE_NOT_CHECKABLE` |

## Running it

```bash
cd 2D-3D-CAD-Test-Generation
PYTHONUTF8=1 python -m bench.fidelity ../FINAL_OUTPUTs/<Part>       # one part -> <Part>/fidelity_score.json
PYTHONUTF8=1 python -m bench.fidelity ../FINAL_OUTPUTs --all        # every part folder
PYTHONUTF8=1 python -m pytest tests/test_fidelity.py -q             # 22 tests on real CadQuery meshes
```

The pipeline writes `fidelity_score.json` after every run (never fatal). The UI persists each evaluation append-only
(`<data>/scoring/<part>.jsonl`): a rubric change never rewrites an old score, and Re-evaluate adds a new one.

## Known limits

* Holes, bores and bosses on a principal axis are measured; fillets, chamfers, slots and oblique features are checked through the build record only.
* A blind-hole floor is read from the mesh; a hole that breaks into another bore can be read as through.
* Single-hole absolute position needs an answer key (benchmark scorer).
* If the extraction names no overall dimensions on its base feature, Overall size is skipped and the score is rescaled (and the report says so).
* Threads are cosmetic: a tapped hole is graded on tap-drill size, depth and position, never thread form.

## What it found on the existing outputs (2026-11-25)

Scored from the 19 part folders in `FINAL_OUTPUTs`: A001211E 98.7, A001911E 99.3, A001921E 97.5 and A040711E 93.4 are green. Several folders hold an STL
that is not the part's own mesh (for example `A040501E`'s STL is `A040691E`'s: 4.375 x 2.25 x 5 in instead of a 3.501 in diameter, 8 in long shaft),
which the rubric reports as a critical `STL_NOT_THIS_BUILD` and scores red. Five parts have a SolidWorks part but no exported STL and are Incomplete.
That is a pipeline artifact problem to fix, found by the rubric, not a rubric problem.
