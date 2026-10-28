# Model vs. drawing mismatches: questions for MTI

**From:** iNDustry Labs / AILOT, mti-2d-3d project · **Date:** 2026-10-28

## Background

We are testing our drawing-to-SolidWorks pipeline on the parts in MTI's "Parts + Drawings Audit"
folder. Each part's 2D drawing is the input, and MTI's existing SolidWorks model is used to check
the result.

So far 31 parts have been run, and all 31 build in SolidWorks. Most match MTI's models closely:
23 overlap at 97.9% or better.

For four parts, our model and MTI's model differ because **MTI's existing model doesn't match its
own drawing**. In each case we checked the drawing by eye, and our part follows it.

## Our approach: we follow the 2D drawing

In production, the pipeline will be given only the 2D drawing, so the drawing is our source of
truth. Where a drawing and an existing model disagree, we build to the drawing and record the
difference. We don't adjust the pipeline to reproduce a model that departs from its drawing.

## The four parts

| Part | What the drawing says | What MTI's model has | Size of the difference |
|---|---|---|---|
| **SB12050** | 2.12" overall length | 3.50" long | Model is 1.38" longer |
| **SB12009** | 3.343" overall length | 4.25" long | Model is 0.91" longer |
| **SB14306** (Collet, Special) | Bores Ø18.250 (datum A), Ø18.625, Ø18.125, Ø19.500, Ø19.999; web centre bore **Ø6.00** | Bores Ø18.5, Ø19.0, Ø19.625, Ø19.999, Ø20.0; web centre bore **Ø10.0**; a Ø20.0 × .375 entry counterbore that isn't drawn | Only Ø19.999 agrees. The model has about 27% less material, about half of it from the Ø10 web bore. |
| **A00161E** (Drip Pan, 161-B) | End radius **3.00 R** (inside), 16 ga (.060) | End radius **3.036** inside, .0598 wall | 0.036" larger radius moves the 15° sides out about 0.9 mm (outside the ±.02 two-place tolerance) |

## Questions

1. **For each of the four parts, is the drawing current?** Or does MTI's model reflect a later
   revision, or a different part that shares the number?
2. **SB14306:** is the web centre bore Ø6.00 (drawing) or Ø10.0 (model)? Is the Ø20.0 entry
   counterbore a real feature that is missing from the drawing?
3. **A00161E:** is the 3.00 R end radius as drawn, or should it be about 3.036, for example a
   sheet-metal bend allowance?
4. **In general, when a drawing and its model disagree, which should we treat as authoritative?**
   We currently assume the drawing.

## Smaller open items on these parts (not mismatches)

- **SB14306:**
  - one starred ".375 R" blend can't be built as a simple fillet between the 18.625 and 18.125
    bores, so we need the intended shape;
  - "BREAK ALL SHARP CORNERS" has no size, so we need the edge-break size to use.
- **SB12050 and SB12095:** the 30° bevel callout conflicts with the tip diameter, and ".030 R MAX"
  is given with no nominal radius. One general answer would settle most SB-Series parts.
