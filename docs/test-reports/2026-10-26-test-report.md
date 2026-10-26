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
