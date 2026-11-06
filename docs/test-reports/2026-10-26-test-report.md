# Test Report: 2026-10-26 — first batch from MTI's parts audit (10 parts), scored against MTI's own models

**Project:** mti-2d-3d · **Date:** 2026-10-26 · **Operator:** ggould, with Claude Code
**Branch:** `feat/openai-extractor-sw2025` · **Host:** Windows 11, SolidWorks 2025 SP5
**API spend today: $7.65** (ledger $11.70 → **$19.35 of the $20 cap**). The budget guard stopped the batch before part 9's planning call, as designed.

## 1. Overall statement

MTI's Google Drive audit holds **63 parts that have both a drawing and MTI's own SolidWorks model**. That gives the pipeline an answer key for the first time. We ran 10 of them.

- **All 8 that ran build and verify, and match their drawings.**
- **Against MTI's models:**
  - **7 of 8 overlap at IoU ≥ 0.985:** A00142E 1.000, SB12006 1.000, A00121E 0.999, A00121M 0.998, SB12095 0.998, A00173E 0.990, A00115E 0.985.
  - **The 8th (SB12050) matches its drawing but not MTI's model.** The drawing says 2.12" overall; MTI's model is 3.5" long. This is a data question for MTI.
- **One compiler gap was found and fixed:** polygon (L-shaped) base outlines. It cost nothing to rebuild.
- **Two parts didn't run:**
  - SB14306: the budget stopped it after extraction, which is saved.
  - 4C1229: not started.

## 2. Setup (all read-only on Drive)

- **Drive access.** Google Drive for desktop is not installed on this PC, so the folder was read through the **Composio Google Drive** connection (as ggould@nd.edu). Folder id `10wfwK0XK_IjcvvU84tfB7NDq0WqhpaKw`.
- **Inventory**, excluding `_Needs Review`:
  - 301 part folders: 242 A, 56 SB, 3 Other.
  - 443 files: 186 PDF, 142 DWG, 114 SLDPRT, 1 SLDASM.
- **The 63-part test set:**
  - 34 A-Series, 27 SB-Series, 2 Other-Series.
  - Drawings: 39 PDF, 24 DWG.
  - Listed in `bench/mti_test_set.csv`: Drive paths, file ids, notes.
- **Family folders need pairing by detail number:**
  - SB13674: 12 sheets, 45 models.
  - SB01783: 2 sheets, 5 models.
  - SB12052: 2 sheets, 3 models.
  - SB18461: 5 sheets, 1 model.
- **Batch:** 10 clean one-drawing-to-one-model PDF parts.
  - A-Series: A00115E, A00121E, A00121M, A00142E, A00173E.
  - SB-Series: SB12006, SB12050, SB12095, SB14306.
  - Other-Series: 4C1229.
- **Copies.** Drawings and models were downloaded to `output/<part>/source/` (local only; not committed: MTI's files).
- **New tools:**
  - `mti_batch.py`: drawing PDF → Astra extract + plan → CadQuery reference → native SolidWorks.
  - `mti_groundtruth.py`: MTI's SLDPRT → STEP, plus a summary.
  - `mti_score.py`: aligned IoU, volume and size.
- **Results:** `output/mti_audit_batch1/`.

## 3. Results

| Part | Built & verified | Cost | IoU vs MTI | Volume ratio | Open questions |
|---|---|---|---|---|---|
| A00115E | ✅ | $0.61 | 0.985 | 0.994 | 1 (undimensioned corner radius) |
| A00121E | ✅ (after polygon fix) | $0.75 | 0.999 | 1.001 | 0 |
| A00121M | ✅ (after polygon fix) | $0.81 | 0.998 | 1.001 | 0 |
| A00142E | ✅ | $0.66 | **1.000** | 1.000 | 0 |
| A00173E | ✅ | $0.90 | 0.990 | 0.997 | 2 (tapped-hole depths) |
| SB12006 | ✅ | $0.58 | **1.000** | 1.000 | 2 (pilot depth, ".030 MAX" radius) |
| SB12050 | ✅ to the drawing | $0.53 | 0.000 | 0.826 | 2 (conflicting bevel callouts, "R MAX") |
| SB12095 | ✅ | $1.02 | 0.998 | 1.002 | 2 (tip conflict, "R MAX") |
| SB14306 | budget stop after extraction | ~$1.80 | — | — | — |
| 4C1229 | not run | — | — | — | — |

**MTI conventions applied** (from the build reports):

- origin centered;
- base sketch on the Top plane, Mid Plane for plates;
- Hole Wizard: 3/8 and 5/8 clearance, 1/4 SHCS counterbore (8 holes in one feature), and #10-24, M5x0.8, #10-32 and 1/4-20 taps with cosmetic threads;
- hole layouts on construction geometry;
- sketches fully defined, except Hole Wizard placement sketches (known).

**A00121E vs A00121M** are the inch and metric versions of the same plate. The pipeline gave them **#10-24** and **M5x0.8** taps respectively.

## 4. What MTI's own models show (the answer key)

- **Plates (A-Series):** Extrusion plus Hole Wizard, **origin centered**, which matches what we build.
- **Turned parts (SB-Series, 4C1229):** Revolution plus Hole Wizard, fillets, chamfers and circular patterns. The **origin is at one end face, not centered** (center offset = half the length). This answers MTI question 7. Our compiler centers turned parts, so this is a change to make.
- **SB14306** is a large turned part (546 mm diameter, 23 features: five Hole Wizard patterns, fillets and chamfers). It's a good stress test for the next batch.

## 5. Failures and fixes

1. **Polygon profiles weren't compiled for SolidWorks** (A00121E and M): "profile polygon not compiled for SolidWorks yet". The base never built, so every later feature failed. **Fixed:** closed line outlines in `_SW.prism`. Rebuilt from the saved plans at $0 → both pass, IoU 0.999 and 0.998.
2. **Opening MTI's models:** SolidWorks crashes, then file-not-found and same-title errors, then the wrong interface. **Fixed;** see error log **E025**.
3. **SB12050 drawing vs model.** Not a pipeline failure: the drawing says 2.12" overall and MTI's model is 3.5". Question for MTI.

## 6. Decisions and next steps

1. **Budget.** $0.65 is left of $20, so nothing more can be extracted until `API_BUDGET_USD` is raised. At about $0.75 per new drawing, the remaining 53 parts need roughly $40.
2. **Turned parts' origin.** Model it at the end face, matching MTI's own models, and re-score SB12006, SB12050 and SB12095.
3. **DWG drawings** (24 parts) need conversion to PDF before extraction.
4. **Family folders** need drawing-to-model pairing by detail number.
5. **Score feature trees as well as shape.** MTI's trees are available now (Hole Wizard counts, fillet and chamfer placement).

**Questions for MTI:** SB12050 (2.12" drawing vs 3.5" model); conflicting bevel callouts on SB12050 and SB12095.

---

## 7. Batch 2 (same day): 21 more parts, cap raised to $40

**Spend:** $19.81. The ledger went from $19.35 to **$39.16 of $40**. The guard stopped the run at SB12011 after its extraction, which is saved. Not run: SB12011's plan, SB12051, SB12053, SB12054, SB12055, SB12059 and SB12108.
**Results:** `output/mti_audit_batch2/`.

**18 of the 21 that ran build and verify in SolidWorks.** Against MTI's own models:

| Part | IoU | Notes |
|---|---|---|
| A00147E, A00160E, A00162E | **1.000** | |
| A00127E, SB12007, SB12008, SB12010 | 0.999–1.000 | |
| A00144E, A00134E, A00143E, A00116E, A00135E | 0.992–0.998 | |
| 2N2664 | 0.988 | 18 features; edge-break questions |
| A00122E | 0.987 | 19 features; three Hole Wizard clearance sizes plus #8-32 taps |
| A00155E | 0.984 | CadQuery reference correct; **SolidWorks failed (slots)** |
| A00129E | 0.979 | open question: 1/4 **LOW HEAD** counterbore depth |
| SB14306 | 0.740 | **SolidWorks failed**: slots, circular prism patterns, 5 cut mismatches |
| A00161E | 0.291 | volume and size match (1.001); probably scorer alignment on a thin-walled channel, to check |
| SB11488 | 0.000 | real miss: 332 mm vs 309 mm, volume +26% (a sheet from a set; placement questions) |
| SB12009 | 0.000 | **MTI's model doesn't match the drawing**: the drawing says 3.343" (checked), the model is 4.25" |
| 4C1229 | — | CadQuery reference failed at `finish` |

**Combined (31 parts run):**

- **28 build and verify.**
- **Against MTI's models, 23 of 28 scored are at IoU ≥ 0.979.** Two of the misses are drawing-versus-model mismatches (SB12050, SB12009); MTI should check those, not the pipeline.

**Findings:**

1. **Origin convention depends on the series, not the part type.** A-Series turned parts (A00129E, A00147E, A00173E) are centered, like the plates. SB-Series turned parts have the origin at an end face. MTI's written practice says centered, so the compiler stays centered. *(A change to end-face origin for all turned parts was made and reverted the same day.)* Question for MTI: should the SB models be re-originated, or do they want end-face origins for SB parts?
2. **Compiler gaps (free to fix):**
   - slot profiles (A00155E, SB14306);
   - circular patterns of prisms (SB14306);
   - SB14306's cut mismatches;
   - 4C1229's reference failure.
3. **Recurring SB drawing questions:**
   - the 30° bevel vs tip-diameter conflict (SB12050, SB12095, SB12010);
   - ".030 R MAX" with no nominal radius;
   - drill depth beyond the tapped length.
   
   One answer from MTI would settle most SB parts.

**Next:**

- Fix slots and circular prism patterns, then rebuild A00155E and SB14306 from their saved plans ($0).
- Debug 4C1229.
- Check A00161E's alignment.
- Budget for the remaining parts:
  - **≈ $6:** 7 PDF parts left plus SB12011's plan.
  - **≈ $25 more** for the 24 DWG parts, which first need converting to PDF.

---

## 8. Slots and circular patterns fixed (E028), $0

- **Slots** (`CreateSketchSlot`) and **circular patterns of prisms** (native `FeatureCircularPattern5`
  about a reference axis along the part axis) are now compiled for SolidWorks.
- **A00155E** rebuilt from its saved plan → **builds and verifies** (IoU vs MTI 0.984).
- **SB14306** rebuilt → **builds and verifies**, with 9 native circular patterns, the way MTI's own
  model does it. It is still incomplete against MTI's model (IoU 0.74): 4 holes fail in the CadQuery
  reference (`KeyError: 'depth'`), 1 edge query matches nothing, and 2 features are MTI questions.
- **Combined: 30 of 31 parts run now build and verify.** The exception is 4C1229, whose reference
  fails.
- **Next (free):**
  - the `depth` bug in `cq_runtime` hole handling (SB14306);
  - 4C1229's reference failure;
  - A00161E's score alignment.

---

## 9. Through-tapped holes and 4C1229 fixed (E029), $0

Three bugs in the CadQuery reference runtime (`cq_runtime.py`):

1. Holes with `depth: null` (".750-10 TAP THRU") crashed unless they were counterbores.
2. Hole measurement crashed on cylinders trimmed by the slot cuts.
3. An edge query paired a cylinder with itself and picked its seam line.

Rebuilt from saved plans:

| Part | Before | After | IoU vs MTI | Volume ratio |
|---|---|---|---|---|
| 4C1229 | reference failed, no build | **builds and verifies** (2 MTI questions skipped) | **0.938** | 0.955 |
| SB14306 | 4 tapped-hole families skipped | **builds and verifies**, all 8 tapped holes via Hole Wizard | 0.744 | 1.273 |

- **Combined: all 31 audit parts run now build and verify.**
- **SB14306** didn't move on IoU: the holes are small against a 546 mm part. Its +27% volume is
  elsewhere, probably the F005 blend and the F003 edge query (still "matched no edges") or a bore
  profile. That needs a look against MTI's model.
- **4C1229** is 4.5% light against MTI. F011 and F012 (groove-lip breaks, "MAX" only) are MTI
  questions.
- **Tests:** 442 passing.
