# Test Report: 2026-10-28 — SB14306 and A00161E explained, rebuild and re-score, merge of the benchmark scorer

**Project:** mti-2d-3d · **Date:** 2026-10-28 · **Operator:** ggould, with Claude Code
**Branch:** `feat/openai-extractor-sw2025` · **Host:** Windows 11, SolidWorks 2025 SP5
**API spend today: $7.52**: the last 7 PDF parts ($6.63) and the SB11488 re-plan ($0.89). Everything else was rebuilt from saved plans at $0. Ledger **$39.16 → $46.68 of $50** (the cap was raised to $50 today). An expired OpenAI key caused one failed attempt at $0.

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
| 4C1229 | ✅ | 0.938 | 0.955 | 4.26 / 0.26 | not clocking: see the correction in §10 |
| SB14306 | ✅ | 0.744 | 1.273 | 50.8 / 2.76 | MTI's model ≠ drawing (§2) |

**4C1229:**

- ~~The 4.26 mm peaks are slot clocking, an orientation choice.~~ **Corrected in §10:** holes
  and slots have the same relative arrangement in our part, MTI's model and the drawing, and
  rotations about the axis don't raise the score. The 0.938 (4.5% light) is a different, still
  unexplained difference.
- The 1.4 mm points are the groove-lip edge breaks (F011, F012). The ≤ .010 default (D2) doesn't
  model them.

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

---

## 7. Callout defaults: vague callouts are built by rule, not skipped ($0)

**Spec:** `docs/superpowers/specs/2026-10-28-callout-defaults-design.md`. **Code:** `pipeline/ir/defaults.py`,
which is applied after planning. `plan.json` stays the planner's own output; switch the rules off
with `MTI_CALLOUT_DEFAULTS=0`.

**Why:**

- 36 features across the audit plans were `unresolved`, and so skipped.
- Most were the same vague callouts: ".030 R MAX", "C/R", "BREAK ALL SHARP CORNERS", and a tap
  with a thread depth only.
- All of them already carried full geometry in the plan.
- In production only the drawing is given, so each needs one documented answer.

**Rules, with values measured from MTI's own models:**

| Rule | Callout | Action | MTI's models |
|---|---|---|---|
| D1 | ".030 R MAX", "ALL RADII .047 MAX" | fillet at the max value | R.030, R.047 ×9 |
| D2 | break ≤ .010 (".005 C/R MAX") | not modelled | not modelled |
| D3 | "C/R" | 45° chamfer | both forms used |
| D4 | no printed size ("BREAK ALL SHARP CORNERS", unsized corners) | not modelled | not modelled on plates |
| D5 | "#10-32 TAP .38 DEEP" (no drill depth) | drill = thread + 5 pitches | .536 = .38 + 5/32 exactly |
| D6 | thread class only (8-32-**2A** internal) | build it; threads are cosmetic | n/a |
| D7 | "ALL CHAMFERS .06 × 45° U.O.S.", "... TYP." | apply to the planned edges | .06 × 45° ×14 |

**Result:**

- **Unresolved features: 36 → 16** across the audit plans. 11 parts are now fully resolved.
- The 16 left are real drawing questions: bevel vs tip conflicts, "TO SUIT", low-head
  counterbore, SB11488's unread profile, and SB14306's blend.
- **All 11 rebuilt parts build and verify in SolidWorks.**
- **17 of 18 defaulted features are built.** The exception, 2N2664 F025 (D6), turned out to have a
  hole position off the part ("cut removed no material"); the thread-class question had been
  hiding that plan error.

| Part | Defaults | IoU before → after | Deviation max / mean (mm) |
|---|---|---|---|
| SB12006 | D5, D1 | 0.9998 → **1.0000** | 1.00 / 0.007 |
| 2N2664 | D3, D7, D1, D6 | 0.988 → **0.993** | 6.03 / 0.10 |
| SB12007 | D1, D5 | 0.9998 → 0.9999 | 1.20 / 0.07 |
| SB12010 | D5, D1 | 0.9992 → 0.9994 | 1.19 / 0.02 |
| SB12008 | D7 | 0.9997 (same) | 5.17 / 0.44 |
| SB12095 | D1 | 0.9975 (same) | 7.63 / 0.18 |
| A00115E, A00116E | D4 | same (0.985, 0.995) | 3.4 / 0.30, 3.7 / 0.18 |
| 4C1229 | D2 ×2 | 0.938 (same) | 4.26 / 0.26 |
| SB12009, SB12050 | D5 + D1, D1 | 0.0 (MTI model ≠ drawing) | n/a |

No score went down.

**Follow-ups:**

- On SB12006 one D5 tap fell back from Hole Wizard to a plain cut. Hole Wizard's placement didn't
  match the reference; the fallback is volume-verified, so the geometry is correct.
- 2N2664 F025's position.
- **SB11488 (the only real miss, +26% volume)** is three large unresolved cuts the planner couldn't
  read (F018–F020) on a multi-detail sheet. It needs a re-plan with a tighter crop (~$0.75), which
  is budget-blocked.

**Tests:** 13 in `tests/test_ir_defaults.py`. **Suite: 989 passed, 66 skipped.**

---

## 8. The last 7 PDF parts, the SB11488 re-plan, and a model swap ($7.52)

**Run:** `mti_batch.py` on SB12011 (plan only; its extraction was saved), SB12051, SB12053, SB12054,
SB12055, SB12059 and SB12108. The first attempt failed at $0 on an expired OpenAI key; after
the key was replaced it ran clean. **Results:** `output/mti_audit_batch3/`.

| Part | Cost | Builds & verifies | Questions | IoU vs MTI | Deviation max / mean (mm) | Note |
|---|---|---|---|---|---|---|
| SB12011 | $0.18 | ✅ | 0 | **0.9999** | 1.20 / 0.07 | |
| SB12055 | $0.45 | ✅ | 1 | **0.9993** | 0.76 / 0.17 | |
| SB12053 | $1.73 | ✅ | 3 | **0.9977** | 11.8 / 0.30 | 14 features |
| SB12054 | $2.08 | ✅ | 3 | **0.9949** | 14.9 / 0.53 | 22 features |
| SB12059 | $0.67 | ✅ (after E031) | 2 | **0.9901** | 10.5 / 0.46 | four collet pads; see below |
| SB12108 | $0.79 | ✅ | 4 | 0.783 | 31.8 / 0.12 | MTI's model is a weldment; 4 open questions |
| SB12051 | $0.73 | ✅ | 0 | 0.000 → **1.000** | 0.0 / 0.0 | **MTI's models of SB12050 and SB12051 are swapped** |

**MTI's SB12050 and SB12051 models are swapped in Drive.**

- Our SB12051 (3.5" long, to its drawing) scores IoU **1.000** with 0.0 mm deviation against
  the file in MTI's SB12050 folder.
- Our SB12050 (2.12") scores **0.996** against the file in the SB12051 folder.
- So both of our parts are right, and SB12050 is no longer a drawing-vs-model mismatch.
- The summary for MTI (`docs/mti-questions/`) is updated.

**SB12059 is four separate pieces by design (E031).**

- The drawing ("COLLET PAD") shows four .060 sawcuts running clean through, from bore to OD. The
  part is four pads; MTI's model is the uncut ring.
- Every feature was volume-matched, but the final check boxed only the first body, so the
  correct four-body part failed. It now boxes every body (`parts_box`).
- The defaults also got a guard. D5 had turned a radial tapped hole (it starts on `wall(...)`,
  which the IR can't drill from) into a planned feature, which failed in the reference. Defaults
  now never apply to a hole that doesn't start on a face or plane. The hole stays a question; the
  IR has no radial holes yet.

**SB11488 re-plan ($0.89):**

- **Inputs:** the full sheet plus 200–300 dpi crops of detail 4's front view and side section
  (`output/sb11488_replan/views/`), reusing the saved extraction.
- **Better:** all holes now build through Hole Wizard: 7 counterbores, 4 1/4-20 taps and 2
  5/8-11 taps. It builds and verifies.
- **Not fixed:** the planner still won't commit to the central profile (F004–F006: how .83, .250,
  30° and 10° attach). That profile is the +25% volume, so IoU stays 0 (size 332 vs 309 mm fails
  alignment). The scan is too noisy for the planner to read the profile; it needs a human reading
  of the section or a better scan.

**Totals across the audit (38 PDF parts run):**

- **All 38 build and verify** in SolidWorks.
- **Model-vs-drawing mismatches for MTI:** SB12009, SB14306 and A00161E. SB12050/SB12051 are a
  file swap.
- **Tests:** 991 passed, 66 skipped.

---

## 9. Radial holes ($0)

**Spec:** `docs/superpowers/specs/2026-10-28-radial-holes-design.md`. There is no schema change.

- **IR:**
  - A `hole` on `wall(F, r)` is radial: `u` is the angle in degrees about the part axis (from +X
    toward +Y), `v` the axial station, and the depth is radial ("thru" = the whole diameter).
  - The planner was already writing radial holes this way, with `u = "0"`; the prompt now
    defines `u` as the angle.
- **Reference:** `cq_runtime._radial_hole`.
- **SolidWorks:** `_SW.radial_hole`.
  - A line from the axis to a point just outside the part at the angle, then a reference plane
    perpendicular to it through that point.
  - The hole circle goes on that plane at the exact model point, then a blind cut inward.
  - A wrong direction removes nothing, so the volume check catches it.
  - Patterns of a radial seed are native circular patterns. Radial holes never join the
    face-hole grouping.
- **Defaults:** D5 can now apply to a radial tap on `wall(F, r)`.
- **E032:** two COM interface casts, found on the first live build.

**Results:**

| Check | Result |
|---|---|
| `radial_demo` golden (4 taps at 45° + cross-hole) | builds and verifies in SolidWorks |
| Chiral part (tap at 30°, cross-hole at 0°, stepped tube) | SolidWorks vs reference IoU **1.000 under proper rotations only** (mirrors: 0.996): right handedness |
| SB12095 (three #8-36 radial taps), saved plan | **0.9975 → 0.9985** vs MTI; the taps are now built |
| SB12059, saved plan | 0.990 → 0.988: the seed tap builds, but the plan predates the angle field (u = 0 is a sawcut line; the drawing has 45°) and its pattern is unresolved. Needs a re-plan. |

**Follow-ups:**

- Re-plan the parts whose radial holes were written before the angle convention: SB12059, SB12054
  and 2N2664 (~$0.70 each).
- Hole Wizard on a curved face for radial taps (MTI uses `HoleWzd`). This needs a 3D placement
  sketch.
- Radial counterbores and countersinks (SB12059's ".03 C'SINK").

**Tests:** 1005 passed, 66 skipped.

---

## 10. Free fixes: tap + pilot merges, a clocking-aware score, DWG drawings converted ($0)

**1. A tap and its pilot drill became one Hole Wizard tap (D5/D6 merges in `pipeline/ir/defaults.py`).**

- **SB12006, SB12007, SB12009, SB12010, SB12011:** "#10-32 TAP .38 DEEP" was planned as a tap
  (.38) plus an unresolved pilot drill at the same spot.
  - D5 had made the pilot a second tap on top of the first, which Hole Wizard couldn't verify,
    so it fell back to a plain cut.
  - Now the tap is deepened to thread + 5 pitches (.536, MTI's own value) and the pilot is
    dropped.
- **2N2664 F024/F025, the other way round:** a planned Ø.136 × .69 drill plus an unresolved
  8-32 × .50 tap.
  - The tap alone cut nothing ("cut removed no material"). It was not a position error, as I had
    first written.
  - Now the drill becomes the #8-32 tap.
- **Result:** all 6 rebuilt parts verify, and each tap is now **one** Hole Wizard feature with a
  cosmetic thread, as MTI models it. Scores held: SB12006 1.000, SB12011 0.9999, SB12007 0.9999,
  SB12010 0.9994, 2N2664 0.993; SB12009 stays a model mismatch.

**2. `mti_score.py` reports `iou_clocked`** (`score.clocked`): for a turned part, the best IoU
over rotations about its axis at pattern angles (360/n, n = 2–24). The strict `iou` is kept next
to it.

- A unit test shows a 5-slot part clocked 15° scoring below 0.99 strict and 1.000 clocked.
- **Correction on 4C1229:**
  - Measured from both models, the counterbores and slots are in the same relative arrangement:
    ours holes 90/210/330°, slots 30/150/270°; MTI's holes 0/120/240°, slots 60/180/300°.
  - The drawing agrees with ours.
  - So the strict alignment already lines up the clocking, and `iou_clocked` stays 0.938.
  - The 4.5% volume gap is something else, probably the groove profile or slot depth. Open.

**3. The 24 DWG drawings are converted.**

- 23 parts (SB18461 is a 5-sheet family and is left out) were downloaded read-only through
  Composio: drawing + MTI model, 46 files.
- Each drawing was converted to PDF with smcanuff's `bench.sw_tasks.dwg_to_pdf` (SolidWorks
  `LoadFile4` → `SaveAs3`; no ODA needed).
- MTI's models were exported with `mti_groundtruth.py`: **23/23 each.**
- The parts are ready to run. Extraction and planning are the only cost: about $17 at ~$0.75 a
  part, against $3.32 left.

**Deferred:** radial counterbores and countersinks. SB12059's ".03 C'SINK" is still unresolved (no
included angle), so it would change no current part.

**Tests:** 1008 passed, 66 skipped.

---

## 11. (2026-11-02) The MTI demo, and the 2N2664 re-plan ($0.86)

- **Demo:**
  - `demo.py` now runs MTI audit parts (`--part P --from <dir>`), shows the callout defaults, and
    scores the result against MTI's own model.
  - Runbook: `docs/demo/2026-11-02-mti-demo-runbook.md`.
  - Rehearsed: 2N2664, A00122E (19/19, 0.21 mm max, 45 s) and the 2N2664 re-plan.
- **2N2664 re-plan** ($0.86; ledger **$47.54 of $50**):
  - The planner used the radial-hole convention: F017 at u = 240°, matching "30° left of
    downward".
  - **E033:** the reference over-cut the hole (an exact-boolean failure); fixed with a fuzzy
    tolerance of 0.01 mm. Verified neutral on every other saved reference.
  - Result: **builds and verifies, IoU 0.9957 vs MTI** (earlier plan: 0.9926).
  - It asks one question (the recess end's .377 / .188 / .188 R inconsistency) instead of guessing,
    so the recess isn't built.
- **Also:** `face()` queries on a cut accept either normal, so a pocket's walls and opening can
  both be selected (test added).
- **Tests:** 1009 passed, 66 skipped.
