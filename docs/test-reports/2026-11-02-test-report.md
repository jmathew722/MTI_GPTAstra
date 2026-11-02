# Test Report: 2026-11-02 — discrepancy analysis, drawing markups and the first fine-tuning rules

**Project:** mti-2d-3d · **Date:** 2026-11-02 · **Operator:** ggould, with Claude Code
**Branch:** `feat/openai-extractor-sw2025` (PR #6) · **Host:** Windows 11, SolidWorks 2025 SP5
**API spend today: $0.86**, the 2N2664 re-plan (see the 2026-10-28 report, §11). Everything below
is $0. Ledger **$47.54 of $50**.

## 1. Overall statement

The user asked to start fine-tuning on parts whose overlap with MTI's own models falls just short
of 100%, and to mark the discrepancies up on the drawings. Delivered:

- **Automatic discrepancy analysis** (`mti_discrepancy.py`): why each part differs from MTI's model,
  where, and how much each cause costs. For example, 2N2664's 0.43% resolved into 0.26% general-note
  edge treatments and 0.15% the recess question.
- **Drawing markups** (`mti_markup.py`): a copy of MTI's drawing with a cause panel, numbered boxes
  on the callouts (found automatically by OCR, `rapidocr`) and a report page. Generated for **21
  parts**. They are local only: they're MTI's drawings and never committed.
- **Two fine-tuning rules, both measured against MTI's models with no regressions:**
  - **D9:** two-place prints of 1/16" fractions on plates are the fraction. **A00122E 0.9865 →
    1.0000.**
  - **D8:** general notes ("ALL CHAMFERS .06 × 45°", "ALL RADII .047 MAX") apply to every eligible
    edge of a turned part. **2N2664 0.9957 → 0.9980.**
- **Scoring made trustworthy (E034).** OpenCascade's parallel booleans were non-deterministic, and
  some modes return impossible results. Every boolean in scoring and analysis is now checked and
  falls through modes until it gives a possible answer.

## 2. Discrepancy analysis (`mti_discrepancy.py`, $0)

The analysis:

1. aligns our part onto MTI's model (`iou` → `aligned` → `clocked`);
2. splits the difference into pieces, both "material only we have" and "material only MTI has";
3. classifies each piece as a ring (edge treatment), pocket or slab;
4. attributes it to an open question, a general note or a skipped feature;
5. checks that the pieces add up to the gap, and marks the part `reliable`.

Results are in `<part>/discrepancies.json` plus `discrepancy_summary.json`, which ranks causes and
leaves out the known model-vs-drawing mismatch parts.

**First run, which found the next fixes:**

- **A00122E 1.25%:** our plate was 0.380" thick, MTI's 0.375". The drawing prints ".38" for 3/8"
  stock, which led to D9.
- **2N2664 0.26%:** chamfer and fillet rings at five diameters, from the general notes. This led to
  D8.
- **A00115E 0.96%:** MTI kept a 2.2 × 0.58 × 1.0" block that we cut. Still to investigate.
- **A00135E, A00173E ~0.7%:** explicit edge treatments. Still to investigate.

## 3. Markups (`mti_markup.py` + `pipeline/ocr_locate.py`, $0)

- **Page 1:** the drawing, untouched, with a summary strip added to its right and numbered boxes on
  the callouts behind each cause.
- **Page 2:** the full report.
- **Positions:** a hand-made `markup_positions.json` wins if present (2N2664 has one). Otherwise
  RapidOCR finds the callouts.
- **OCR matching:** OCR on these scans is close but not exact (".377" reads "377", ".188 R" reads
  "R~", "ALL RADII" reads "ALL RADH"), so matching is fuzzy. A number matches by value, or by its
  digits with the point lost ("7.50" is not ".75"). A number that appears several times is
  resolved near the unique matches.
- **Accuracy:** on 2N2664 the automatic boxes agree with the hand placement to within a few points.
- **Generated for 21 parts:** A00155E, A00115E, A00122E, SB12059, A00173E, A00135E, 2N2664 (both
  plans), A00116E, A00143E, A00134E, SB12053, A00144E, A00121M, SB12095, A00121E, SB12055, SB12010,
  A00127E, SB12008, SB12054, A00129E.

## 4. Fine-tuning rules (`pipeline/ir/defaults.py`)

### D9: two-place prints of 1/16" fractions, on plates

- **Evidence:** MTI uses the fraction on every A-Series plate checked (A00121E/M 6.875, A00122E
  34.375 and 0.375, A00134E 5.125, A00143E 5.375). Turned SB12055 keeps its printed 6.12, so turned
  parts are excluded.
- **Two-place is read from the dimension's tolerance,** which must equal the drawing's 2-place
  general tolerance. So ".440" (±.010) is never rounded; an earlier version that ignored this cost
  A00160E 0.05%. Reference and derived values are excluded, and so are drawings whose tolerance
  block can't be read.

| Part | Before | After (SolidWorks verified) |
|---|---|---|
| **A00122E** | 0.9865 | **1.0000** |
| A00121E | 0.9987 | **0.99999** |
| A00121M | 0.9984 | 0.9995 |
| A00115E | 0.9854 | 0.9875 |
| A00143E | 0.9958 | 0.9968 |
| A00155E | 0.98361 | 0.98365 |

### D8: general notes on every eligible edge (turned parts)

- **What it does:** a new IR edge selector, `edges(convex)` / `edges(concave)`: every still-sharp
  circular edge coaxial with the part axis whose corner is outside or inside. The corner is judged
  by a 4-point test in the profile plane.
- **Robustness:**
  - D8 is added after all other features.
  - If the edges can't all be treated in one operation, they're done one at a time.
  - Every result must be one valid solid, changed in the right direction, by no more than a ring of
    that size could hold. One unchecked fillet had taken 2.3 in³.
- **Result:** 2N2664 re-plan **0.9957 → 0.9980**; earlier plan 0.9926 → 0.9945.
  - SolidWorks verifies both D8 features: a chamfer on 6 edges and a fillet on 3.
  - It triggers on no other audit part; 2N2664 is the only turned part with such notes.

## 5. Scoring fixes (E034)

- **Problem:** OpenCascade's parallel booleans were non-deterministic (the same part scored 0.00075,
  then 0.994). Serial fuzzy booleans once returned an intersection larger than the part (A00173E,
  1.21).
- **Fix:**
  - `score.boolean` runs serial booleans.
  - `inter_volume` accepts only a possible result, in [0, min volume], trying serial fuzzy, serial
    exact, CadQuery fuzzy and CadQuery exact in turn.
  - The discrepancy analysis requires its pieces to add up to the gap.
- **Corrections:** SB12054 reads **0.9907** (the earlier 0.9949 came from the unreliable path). The
  turned-part clocking sweep uses 27 pattern angles.

## 6. Where the remaining gap is (ranked, small-gap parts, model mismatches excluded)

| Cause | Parts (largest first) | What to do |
|---|---|---|
| Open questions | SB12059, A00155E, A00173E, 2N2664 (recess) | Answers from MTI; the markups show exactly what to ask |
| Explicit edge treatments missing | A00135E 0.73%, A00173E 0.65%, SB12059 | Next fine-tuning target: why these planned/drawn edges differ |
| Unattributed | A00115E 0.96% (a block MTI kept), A00116E, A00143E | Per-part look, as was done for A00122E |
| Skipped features | A00155E, SB12059, SB12053 | Compiler or plan gaps |

## 7. Tests and sync

- **Tests: 1018 passed, 66 skipped.** New:
  - D8, D9 and selector tests;
  - turned corner-edge selection;
  - OCR matching (4);
  - pocket-wall queries.
- **GitHub:** fetched before each step; `main` and the branch had no upstream changes. Committed
  and pushed to PR #6.
- **Dependency:** `rapidocr-onnxruntime>=1.4` (local models, no API), installed in the project venv
  with `uv pip`.

## 8. Next steps

1. **Explicit edge treatments** on A00135E and A00173E (~0.7% each): find out why they differ.
2. **A00115E's 0.96% block:** a per-part look.
3. **Send MTI the markups** for the open questions (SB12059, A00155E, A00173E, 2N2664). The
   answers become plan inputs or new rules.
4. **Re-run the ranking after each fix:**

   ```bash
   python mti_discrepancy.py --out <output> --all
   ```
