# Test Report: 2026-10-28 — SB14306 and A00161E explained, rebuild and re-score, merge of the benchmark scorer

**Project:** mti-2d-3d · **Date:** 2026-10-28 · **Operator:** ggould, with Claude Code
**Branch:** `feat/openai-extractor-sw2025` · **Host:** Windows 11, SolidWorks 2025 SP5
**API spend today: $0.** Everything was rebuilt from saved plans. Ledger unchanged at **$39.16 of $40**.

## 1. Overall statement

The two worst audit scores were investigated, SB14306 (IoU 0.74, +27% volume) and A00161E
(IoU 0.29). **Neither is a pipeline error: in both, our part follows the drawing and MTI's model
does not.** Three real defects turned up along the way and are fixed:

- the nose fillet that matched no edge;
- an over-strict bounding-box check in SolidWorks (E030);
- IoU being the wrong measure for sheet-metal parts.

Also merged today: smcanuff's benchmark scorer from `main` (§5).

## 2. SB14306 (collet): MTI's model doesn't match its drawing

The axial section (profile vertices at four angles) and the list of coaxial cylinder
diameters were compared for both models:

| | Diameters on the part |
|---|---|
| **Drawing** | 18.250 (datum A), 18.625, 18.125, 19.500, 19.999, and **6.00** (centre bore of the web) |
| **Ours** | 18.25, 18.625, 18.125, 19.5, 19.999, 6.0, exactly the drawing |
| **MTI's model** | 18.5, 19.0, 19.625, 19.999, **10.0**, 20.0 |

- Only **19.999** is common to MTI's model and the drawing. MTI's model has a Ø10 web bore where the
  drawing has Ø6.00 (checked on the drawing: the centre circle in the front view scales to Ø6), and
  a Ø20 × .375 entry counterbore that isn't drawn.
- The web bore alone is ~75 in³, about half of the +27%. The surface deviation is **50.8 mm max**,
  which is exactly 2.0", the Ø6/Ø10 radius difference.
- **Conclusion:** a drawing-versus-model question for MTI, like SB12050 and SB12009. Under the
  benchmark policy (**the drawing is the ground truth**), it is a `drawing-wins` case.

**Fixes found on the way:**

1. **F003** (".12 R" at the tapered nose) "matched no edges": `wall(F001, r)` only matched
   cylinders, but the nose is a 12° cone dimensioned at its rim. `wall(F, r)` now also matches a
   cone rim; an exact cylinder still wins.
2. After (1), every feature built with matching volumes, but the part failed the final
   bounding-box check. `GetBodyBox` is loose on the filleted rim (10.7281" against an exact
   10.7218"). It is replaced by `IBody2.GetExtremePoint` along ±X/±Y/±Z, verified in the typelib
   and live (**E030**).

**SB14306 rebuild ($0): builds and verifies.**

- 26 of 28 features are built and volume-matched in SolidWorks, including F003, 8 tapped holes
  (Hole Wizard, cosmetic threads) and 9 native circular patterns.
- 13/13 sketches are fully defined.
- Only F005 and F028 are skipped; both are MTI questions.

## 3. A00161E (drip pan, 16 ga sheet): a 0.036" radius difference, not a placement error

| | Arc centres | End radius (inside) | Wall |
|---|---|---|---|
| Drawing | 32.25 apart | **3.00 R** | 16 ga (.060) |
| Ours | 32.25 apart | 3.000 | .060 |
| MTI's model | 32.25 apart | **3.036** | .0598 |

- MTI's slightly larger radius pushes the tangent 15° sides out by about 0.9 mm.
- On a 1.5 mm wall, a 0.9 mm offset alone drops IoU to 0.29, even though volume and size agree
  to 0.1%.
- **IoU is the wrong measure for thin sheet parts.** `mti_score.py` now also reports the
  **surface deviation** in mm (sampled, symmetric). A00161E reads **0.91 mm max, 0.35 mm mean**.
  That is the honest number: 0.036", just outside the ±.02 two-place tolerance, and on MTI's side.

## 4. Re-scores ($0)

| Part | Builds & verifies | IoU vs MTI | Volume ratio | Deviation max / mean (mm) | Reading |
|---|---|---|---|---|---|
| A00161E | ✅ | 0.291 | 1.001 | 0.91 / 0.35 | MTI's radius is 3.036 vs drawn 3.00 |
| 4C1229 | ✅ | 0.938 | 0.955 | 4.26 / 0.26 | max is slot clocking (below) |
| SB14306 | ✅ | 0.744 | 1.273 | 50.8 / 2.76 | MTI's model ≠ drawing (§2) |

**4C1229:**

- The 4.26 mm peaks are the closed ends of its three slots: ours point at −90°/30°/150°, MTI's
  at 180°/±60°.
- The tip radius is identical (0.953"). The clocking about the axis differs by 30°, and the
  scorer's 90° alignments can't line up a 3-fold pattern.
- That is an orientation choice, not a misplaced feature. The 1.4 mm points are the groove-lip
  edge breaks we skip as MTI questions (F011, F012).

## 5. Merged `origin/main`: smcanuff's benchmark scorer

- **What came in:** 83 commits, including `bench/`:
  - signed answer keys from MTI's models;
  - a weighted feature-level 0–100 score;
  - a rigid fit that scores a uniform offset as an error instead of hiding it;
  - stage blame (extraction → planner → reference → SolidWorks);
  - a separate MTI practices score from the feature tree;
  - a calibration table of planted errors.
- **How to run it:** `python -m bench.score <run_dir>`. It needs `MTI_BENCH_DATA` (answer keys,
  outside git; not on this PC).
- **Conflicts:**
  - Both sides had fixed the trimmed-cylinder crash in `cq_runtime`, so one `_cylinder` was
    kept.
  - Both sides' tests were kept.
- **Error-log numbering:** `main` had already claimed E026 (silent `SaveAs3`) and E027 (makepy
  byref) in code. This branch's entries became **E028** (slots and circular patterns) and **E029**
  (reference fixes); E026/E027 are reserved stubs until smcanuff adds them.
- **Tests: 976 passed, 66 skipped** (the skips need `MTI_BENCH_DATA`).

## 6. Decisions and next steps

1. **Questions for MTI** (drawing versus model):
   - SB14306: bores and Ø10 web bore;
   - A00161E: R3.036 vs R3.00;
   - SB12050, SB12009.
   
   Under the benchmark policy the drawing wins, so these should become `drawing-wins` overrides in
   the answer keys.
2. Run `bench.score` on the audit runs once the answer keys (`MTI_BENCH_DATA`) are available
   here. Its feature-level score and stage blame replace IoU as the headline.
3. Free, small: let the IoU alignment also try the part's own pattern angles about the axis
   (4C1229's 3-fold slots).
