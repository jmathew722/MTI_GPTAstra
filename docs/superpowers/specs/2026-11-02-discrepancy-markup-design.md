# Discrepancy analysis and drawing markups: closing the last percent

**Date:** 2026-11-02 · **Status:** implemented 2026-11-02 (D8, D9, OCR markups; see the test report) · **Owner:** ggould + Claude Code

## Goal

Most MTI audit parts now overlap MTI's own models at 98–99.9%. The user wants to close the rest.
For every part with a small gap:

1. **Explain the gap automatically:** what differs, where, how big, and which drawing callout or
   plan feature it belongs to.
2. **Mark it up on the drawing,** so an engineer sees the cause at a glance. The first example is
   `output/2N2664/2N2664_problem1_markup.pdf`.
3. **Fine-tune the pipeline** in the order the ranked causes say, and measure each change against
   MTI's models.

## 1. `mti_discrepancy.py` (no API cost)

For `<out>/<part>/`, with `reference.step`, `ground_truth.step`, `plan.json` and `ir_report.json`:

1. **Align:** ours onto MTI's with `score.iou` → `aligned` → `clocked` (as `mti_score.py` does).
2. **Diff:** `ours − MTI` (material we have that MTI doesn't) and `MTI − ours` (material we
   lack). Fuzzy booleans, `tol` = 0.01 mm (E033). Each result is split into solids.
3. **Classify** each piece over 0.0005 in³:
   - **ring:** two bbox extents equal (± 1%) and the third thin (≤ .1"). An edge treatment around
     a turned diameter.
     - "ours only": a **chamfer or break MTI has and we don't**.
     - "MTI only": a **fillet (concave) MTI has and we don't**.
     - Size ≈ the thin extent.
   - **pocket / slot / hole:** a compact piece. Report its size and position, and match it to
     skipped or unresolved plan features by callout and nearest reference position.
   - **slab / other.**
4. **Attribute** each piece to a cause:
   - an `unresolved` question (its feature id and rationale);
   - a general note ("ALL CHAMFERS …", "ALL RADII … MAX", "BREAK …") when it's a ring and such a
     note exists;
   - a `skipped` feature;
   - unattributed.
5. **Output:** `<part>/discrepancies.json` (pieces, causes, the share of the union each one costs)
   and one summary row. Ranking across parts: `python mti_discrepancy.py --all --out <dir>` →
   `discrepancy_summary.json`, causes ranked by the total overlap they cost.

## 2. Markup PDFs (`mti_markup.py`, no API cost)

A **copy** of MTI's drawing (never committed; MTI's file) is saved as
`<part>/<part>_discrepancy_markup.pdf`:

- **Page 1, the drawing:**
  - a summary panel in a free corner, listing each cause with its share of the gap;
  - **precise boxes** where callout positions are known. `<part>/markup_positions.json` holds
    `[{label, rect, shape}]` in PDF points. I place them by reading the sheet for now; OCR could
    automate this later, which needs an install and is the user's decision.
- **Page 2, the report:** the full discrepancy table, the questions for MTI, and the default rules
  that were applied.

## 3. Fine-tuning loop

Take causes in ranked order. Each fix is a rule or compiler change, verified by:

1. unit tests;
2. $0 rebuilds from saved plans;
3. the before/after overlap vs MTI on every affected part (no regressions allowed).

**First candidate (2N2664):** general notes apply to *all* eligible edges, not just the ones the
plan lists.

- "ALL CHAMFERS .06 × 45° U.O.S." becomes a chamfer on every convex circular edge still sharp at
  the end of the build.
- "ALL RADII .047 MAX" becomes a fillet on every concave one.
- This needs an edge selector in the IR (`edges(convex)` / `edges(concave)`), a spec addendum and
  tests. Measured on 2N2664 it is worth about 0.28% of overlap.

## Sync

Fetch and merge `origin/main` before each step; commit and push to `feat/openai-extractor-sw2025`
(PR #6) after each.
