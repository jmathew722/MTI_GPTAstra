# Benchmark Scorer and Stage Blame — Design

**Date:** 2026-10-24 · **Status:** design approved in brainstorming; spec under review
**Sub-project:** 2 of 3 (1 dataset ✅ → **2 scorer + stage blame** → 3 official run). A later
spec 2b adds the engineering best-practices sub-score, which fills a slot this design leaves.
**Builds on:** [Benchmark dataset](2026-10-23-benchmark-dataset-design.md) (answer keys in
`MTI_BENCH_DATA`, `bench/keygen.py`, `bench/crosscheck.py`). Replaces the *Scoring* section of
the [2026-09-28 placement benchmark](2026-09-28-placement-benchmark-design.md).
**Branch:** `feat/mti-benchmark` (local, never pushed without the user's say-so).

## Goal

A real numerical score from 0 to 100 for each generated part that reflects **how well the part
represents its drawing**, not a percentage of dimensions correct:
- features are weighted by **importance** (the main body far above a small hole)
- mistakes are weighted by **magnitude** (relative to tolerance)

Every lost point is **blamed on the pipeline stage** that caused it. The drawing is the ground
truth (user policy 2026-10-24): where MTI's model and the drawing disagree, the drawing wins.
Scoring costs nothing: no API calls.

## What is scored

- **Headline:** the pipeline's **SolidWorks part**, exported to STEP. This is what MTI receives.
- **Blame only:** the plan's **CadQuery reference** (`reference.step`), scored the same way.
- **Answer key:** the signed `key.json` per part. An unsigned key is skipped and listed.

## Architecture (`2D-3D-CAD-Test-Generation/bench/`)

| Module | Responsibility |
|---|---|
| `align.py` | Best rigid fit of a generated part to the key frame: 24 axis-aligned orientations; for each, bounding-box alignment, then match and refine the translation by least squares on matched centres; keep the lowest cost |
| `match.py` | One-to-one assignment (Hungarian, `scipy.optimize.linear_sum_assignment`) between generated and key features within compatible families (holes ↔ holes of any hole type, turned ↔ turned, planar ↔ planar, slot ↔ slot); gated |
| `credit.py` | Attribute errors → credit in [0, 1] with the agreed curve; feature credit = weighted mix of attribute credits |
| `weights.py` | Importance = tier weight × size factor |
| `score.py` | Applies key overrides, combines credits and weights into the part score, the extra-feature penalty and the exact-part flag; leaves a `practices` term (0-weight until spec 2b) |
| `blame.py` | First stage at fault for each loss; rollups |
| `report.py` | `scores.json` + `report.html`: per-part tables and run rollups |
| `score_config.yaml` | Every tunable constant (below) |

`scipy` (already installed as a dependency of another package) is added to `requirements.txt`
explicitly.

CLI: `python -m bench.score <run_dir> [--parts ...]`. A run directory has
`<part>/<part>_ir.SLDPRT` (exported to `generated.step` by the scorer via `bench/sw_tasks`),
`reference.step`, `plan.json`, `<part>_extraction.json` and `ir_report.json` (CadQuery skip
list), as `ir_run.py` writes them. When SolidWorks is unavailable the scorer can take a
pre-exported `generated.step`.

## Key additions (small, done in this sub-project)

1. **Per-feature tolerance.** When `crosscheck` matches a key quantity to a drawing value, it
   records that value's tolerance in a new `Feature.tol` dict (`{"position": t, "size": t,
   "depth": t}`): the printed tolerance if there is one, else the title-block general tolerance
   for its decimals, else ±0.005 in / ±0.1 mm. The 19 keys are re-checked (free); human sign-offs
   and resolutions are preserved by the existing `check` rules.
2. **Structured overrides.** `Key.overrides: list[dict]`, appended to the dataclass with a default
   of `[]`, so old keys still load:
   - `{"feature": "K004", "attr": "depth", "value": 0.098, "source": "drawing", "note": ...}`: replace a key value
   - `{"type": "countersink", "expected_count": 12, ...}`: the drawing calls for more instances than the model has
   - `{"feature": "K00x", "attr": "cbore_depth", "silent": true}`: drawing-silent, so not scored

   Existing `drawing-wins` / `drawing-silent` resolutions are converted. A050481E and A050411E
   are written explicitly; the policy-accepted flags map by kind. A drawing value that can't be
   tied to a feature is listed as "drawing-only, not scored geometrically", never guessed.

## Scoring

### Features and the base body
Key features come from keygen. A synthetic **base body** feature represents the envelope plus
the main profile (bounding extents; the turned profile's diameters and lengths for turned parts;
the plate's length, width and thickness for prismatic parts). Hole patterns are scored through
their member holes; the pattern itself is used only for blame.

### Matching
- Pair cost = position distance / tolerance + size difference / tolerance + type mismatch
  (a constant).
- A pair is accepted only within `gate = min(20 × tolerance, 10% of the part's largest
  dimension)`.
- An unmatched key feature is **missing** (credit 0). An unmatched generated feature is **extra**.

### Credit (per attribute)
`e` = |error| / tolerance:
- `e ≤ 1` → **1.0**
- `e > 1` → `drop × exp(−(e − 1) / k)`, with `drop = 0.5` and `k ≈ 4.4`. That gives about 0.40
  at 2×, 0.20 at 5× and 0.07 at 10× (the curve the user approved: a sharp drop as soon as a value
  is out of tolerance, then decay).
- Type: right = 1, wrong family member (e.g. a counterbore built as a plain hole) = 0.

Attribute shares: position 0.40, size 0.30, depth 0.15, type 0.15. Missing or `silent` attributes
are dropped and the rest renormalised. Feature credit = Σ share × attribute credit.

### Weights
- Tier 1 = base body: **10**.
- Tier 2 = bores, turned diameters, thru holes (in a pattern or not), slots, steps/pockets,
  flats: **3**.
- Tier 3 = tapped holes, counterbores, countersinks, blind holes, chamfers, fillets: **1**.
- Size factor = clamp(√(feature size / part size), 0.3, 1). Feature size is its largest
  dimension (d, length or width); part size is the envelope's largest extent.
- Weight = tier × size factor.

### Part score
`score = max(0, 100 × (Σ wᵢ cᵢ − 0.5 Σ w_extra) / Σ wᵢ)`. **Exact part** = every feature has credit
1 and there are no extras. `practices` (spec 2b) will enter as a separately weighted term; its
weight is 0 now. All constants live in `score_config.yaml`, and changing them never requires a
code change.

### Run outputs
Per part:
- score, exact flag
- per-feature table (key id, type, tier, weight, matched id, each attribute error in mm or in
  and in multiples of tolerance, credit, points lost, blame)
- extras
- drawing-only items

Run rollup:
- mean and median score
- exact-part rate
- points lost by stage, by feature type and by tier

## Stage blame

For each feature with credit < 1 (and each extra), the first stage at fault:
1. **ground_truth:** the loss involves a key override or a recorded model-vs-drawing
   difference. Reported, not charged to the pipeline.
2. **unsupported:** the feature type can't be expressed in the IR (e.g. countersink, serration);
   from a fixed list in config.
3. **extraction:** the drawing values tied to this feature (recorded by crosscheck) are absent
   from, or differ beyond tolerance in, the extraction JSON.
4. **planner:** extraction correct, but the CadQuery reference already shows the same error.
5. **cadquery:** the plan has the feature, but the reference skipped it or failed to build it
   (`cq_skipped`).
6. **solidworks:** the reference is correct, but the SolidWorks part is wrong.

Each blamed loss carries a one-line reason (e.g. "hole 0.031 in off along X; plan u = D005,
expected D005 / 2") and its points lost.

## Error handling
- **No SolidWorks part** (build failed): score 0, blame = the stage that failed (from
  `ir_report.json`).
- **Unreadable STEP:** an error row, never a silent 0.
- **Multi-body generated part:** flagged; the largest body is scored and the other bodies' features count as extras.
- **Unsigned key:** the part is skipped and listed.
- **SolidWorks COM unavailable for the STEP export:** the scorer stops before scoring and says so
  (or uses a pre-exported `generated.step`).

## Testing (all free)
1. **Units:**
   - curve values and monotonicity
   - share renormalisation
   - tier × size and clamps
   - overrides replace or silence attributes
   - gate behaviour
2. **Identity, 19 real parts:** each MTI reference STEP scored against its own key gives exactly
   100 and exact = true. Repeated under all 24 orientations and random translations, including
   non-axis offsets.
3. **Planted errors** (CadQuery edits of real and synthetic parts):

   | Edit | Required result |
   |---|---|
   | hole moved by k × tolerance, k ∈ {0.5, 1, 1.5, 2, 5, 10} | position credit equals the curve within 1e-6 |
   | feature removed | the score falls by exactly that feature's weight share; blame = missing |
   | extra hole | exactly the extra penalty |
   | counterbore → plain hole | only the type credit is lost |
   | mirrored part | aligns, no false errors |
   | ±0.5 × tolerance noise on every feature | still 100 |
4. **Properties** (seeded random cases): a larger error never raises the score; feature order is
   irrelevant; the score stays in [0, 100].
5. **Blame:** fabricated stage outputs hit each of the 6 categories with the right attribution.
6. **Dry run on real pipeline output:** keys generated from the 4 golden plans (SB11033,
   A040911E, A040921E, SB11780). Their existing SolidWorks IR parts are scored end to end, at $0.
7. **Calibration:** about 6 planted-error parts with their scores go to the user. Constants are
   tuned in `score_config.yaml` until the scores feel right. Code doesn't change for this.

No test needs SolidWorks or an API key. Tests that need MTI data skip without
`MTI_BENCH_DATA`. The dry run uses the golden-part SLDPRTs only when SolidWorks is available,
and otherwise uses their pre-exported STEPs.

## Out of scope
- The best-practices sub-score (spec 2b). The data is in a subfolder of the MTI dataset folder
  (some files are `.swp`). Practices that conflict with what the pipeline currently does are
  excluded and logged as major issues, not scored.
- Running the pipeline on held-out parts (sub-project 3).
- Non-axis-aligned parts: the alignment search covers the 24 axis-aligned orientations only.
