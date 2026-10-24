# Benchmark Dataset from MTI Drawing–Model Pairs — Design

**Date:** 2026-10-23 · **Status:** design approved in brainstorming; spec under review
**Sub-project:** 1 of 3 (1 dataset → 2 scorer + stage blame → 3 official run)
**Updates:** [Placement benchmark (C)](2026-09-28-placement-benchmark-design.md). This spec
replaces C's *Dataset* and *Answer key* sections. C's scoring design carries into sub-project 2.
C's model arms are obsolete: the project now uses GPT-6 Astra only (STATE.md).

## Goal

Turn MTI's new drawing–model pairs into a frozen, confidential, answer-keyed benchmark,
at no API cost. When this is done we have:
- a fixed dev / held-out split
- for every part: a drawing the pipeline can read, MTI's model as STEP, and a checked answer key
- a profile of which feature types the benchmark contains, so later improvements can be
  checked for bias

## Source data

MTI's dataset (delivered 2026-10-11) has 150 AutoCAD DWGs and 25 SLDPRT plus 1 SLDASM
models. 21 drawings pair with a model by file name. Of those:

| Group | Parts | Decision |
|---|---|---|
| **Clean (14)** | Simple: A050071E, A050181E, A050211E, A050221E, A050291E, A050311E, A050381E, A050411E, A050471E, A050481E, A050511E. Complex: 1801901E, 1807408E, 1901001E | **Benchmark parts** |
| **M twins (3)** | A050031M, A050081M, A050381M | **Parked.** Re-drawn for metric hardware, but the only model is the inch (E) part, so hole sizes disagree |
| **Obsolete (4)** | A050031E, A050061E, A050081E_OLD, A050131M | **Parked.** Sheet says "OBSOLETE… SEE SOLIDWORKS DRAWING", so the model may be a later revision |

Parked parts are listed in the manifest with their reason and are never scored. A parked
part can be promoted only through a reviewed manifest change, after a person confirms its
model matches its drawing.

**Provisional pairing:** `1807408E.DWG` (titled *Tailstock Assembly*) is paired by name with
`1807408-021(A).SLDPRT`, which may be one component. The key cross-check (below) confirms or
rejects the pairing before the part counts.

## Split

| Split | Parts | Rule |
|---|---|---|
| `dev` (existing) | the 9 parts from 2026-10-04 | unchanged |
| `dev` (format dev, new) | **3** of the 11 clean simple parts | `random.Random(20261023).sample(candidates, 3)` over the 9 simple parts excluding A050471E and A050481E. That near-duplicate pair always stays together in held-out. May be used to debug DWG→PDF ingestion and the pipeline |
| `held_out` | the other **11**, including all 3 complex parts | never used for tuning, debugging or prompt examples (PRD C4) |
| `parked` | the 7 above | not scored |

The split is written once by the prep tool and then changed only through a reviewed manifest
change. The seed, date and decider are recorded in the manifest.

## Storage and configuration

- **In git:** code in `2D-3D-CAD-Test-Generation/bench/`, and `bench/manifest.yaml`. The
  manifest holds part names, splits, units, family labels and file names relative to the
  data root. No dimensions or geometry.
- **Outside git:** a data root named by `MTI_BENCH_DATA`, read through `python-dotenv`. A real
  environment variable wins over `.env`. The line is documented in `.env.template`. Nothing
  machine-specific is hard-coded. If the variable is missing or the folder doesn't exist, tools
  stop with a message naming the variable and the `.env` line to add.
- Data root layout:

```
<MTI_BENCH_DATA>/
  source/                 untouched copies of the paired DWGs and SLDPRTs
  <part>/
    drawing.pdf           black & white, cropped (pipeline input)
    drawing.dxf           ODA conversion (dimension objects for the cross-check)
    reference.step        exported from a COPY of MTI's SLDPRT
    key.json              answer key + cross-check result + sign-off
    review.html           one-page review sheet
  profile.html            feature-type profile of the benchmark
  prep_log.jsonl          one line per step per part (status, time, tool versions)
```

## Preparation (`bench/prep.py`, resumable, all local)

Each step is skipped for a part whose output already exists, unless `--force` is given.
SolidWorks steps run in short batches and reconnect, because the SolidWorks COM connection
drops after idle periods on this machine (observed repeatedly since 2026-10-08, cause
unknown).

1. **Copy sources** from the MTI dataset folder (given by `--source`) into `source/`.
   MTI's originals are only read.
2. **DWG → PDF** (SolidWorks). The method proven on 2026-10-12: import with
   `GetImportFileData`, ImportMethod = new drawing, user-defined 4.5 m paper, 1:1, centered,
   then `LoadFile4`, then `SaveAs3` to PDF with black & white and high quality set only for
   the run and restored. Then crop to content with PyMuPDF and drop empty pages. Every API
   call is already verified against `sldworks.tlb`/`swconst.tlb` (CLAUDE.md rule 1).
   `SaveAs3` results are checked as error codes (E025).
3. **DWG → DXF** with the ODA File Converter (free; a one-time install, approved by the
   user). The converter path comes from `ODA_CONVERTER` in `.env`.
4. **SLDPRT → STEP** (SolidWorks): open the copy in `source/` read-only
   (`swOpenDocOptions_ReadOnly` = 2, verified) and export STEP AP214. Record the units.
   The STEP export call is verified against the type library before first use.
5. **Manifest:** add the 14 + 7 entries and the split. Refuse to change an already-frozen split.

## Answer keys (`bench/keygen.py`)

From `reference.step`, using OCP (the kernel under CadQuery, already installed):

- **Cylindrical features:** group coaxial cylindrical faces into thru holes, blind holes,
  counterbores, bores, bosses and turned diameters. Each gets an axis, a center (the axis
  point at its start face), diameter(s), depth(s), and thru/blind.
- **Cones:** countersinks and chamfers on round edges.
- **Planar features:** steps, pockets, slots and flats, each with a normal and an offset.
- **Envelope:** the bounding box.
- **Patterns:** holes sharing size and spacing on a circle or line are grouped as a
  pattern. They are still listed one by one.
- All values are stored in the drawing's units, in a part frame with its origin at the
  bounding-box minimum. The scorer (sub-project 2) aligns frames, so this choice is only for
  readability.

## Cross-check and sign-off (`bench/crosscheck.py`)

The user chose "I check, you spot-check".

- **Read the drawing** from `drawing.dxf` with `ezdxf`:
  - `DIMENSION` entities: type (linear, aligned, angular, diameter, radius, ordinate),
    measured value, and displayed text. Legacy drawings often override the text, and the
    **displayed text is what the drawing says**. A text that differs from the measurement is
    recorded as "not to scale", not as an error.
  - `TEXT`/`MTEXT` hole callouts (e.g. `.500-13 TAP THRU (3) HLS.`, `DR. & C'BORE FOR #10
    SOC. HD. CAP SCR.`), parsed for diameter, thread, depth and count.
  - The title-block general tolerance, by number of decimals.
- **Match key ↔ drawing:**
  - every key diameter, depth and position offset should equal some drawing value within
    tolerance
  - every drawing size and callout should explain at least one key feature
  - tolerance: the printed one, else the title-block general tolerance, else ±0.005 in / ±0.1 mm
- **Flags** (written to `key.json` and `review.html`): key value with no drawing match;
  drawing value with no key feature; callout count ≠ key count (e.g. "3 HLS" vs 4 holes);
  units mismatch. Each flag has a short reason.
- **Sign-off:** a part with no flags is signed `auto-verified` (tool version, date). A part
  with flags waits for the user, who corrects or accepts each flag in `key.json` and signs
  `human` (name, date). **A key with no sign-off is not scored.** 1807408E is always reviewed
  by a person because of its provisional pairing.
- `review.html`: the drawing image, a model picture, the key table and the flags, on one page.

## Feature profile (`bench/profile.py` → `profile.html`)

Requested so that later changes can be checked for bias toward common feature types.

- **Counts** of each feature type (thru hole, tapped hole, counterbore, countersink, blind
  hole, bore, boss / turned diameter, slot, pocket / step, flat, chamfer, fillet, hole
  pattern), per split (format dev / held-out) and in total, with each type's share.
- **Comparison columns:** the 9 old dev parts (from their golden plans and extractions) and
  the 150-drawing archive (from the DWG keyword scan, labeled approximate).
- **Flags:** any type above 30% of features; any type present in dev but absent from
  held-out, or the reverse.
- Sub-project 2 reuses these feature types to report scores per type.

## Error handling

- Every step writes a line to `prep_log.jsonl`. A failed part is skipped and listed at the
  end, and the run never stops halfway through the manifest.
- Missing data root, missing ODA converter, or no SolidWorks COM connection: stop before
  starting, with what to fix.
- Benchmark files never enter git: the data root is outside the repo, and a test checks
  that no tracked file path contains the data root.

## Testing

- **keygen:** compile the existing golden plans (`tests/golden/ir/`) to STEP with the
  CadQuery compiler, run keygen, and assert it recovers exactly the planned holes, bores and
  diameters (positions within 1e-6).
- **crosscheck:** a small synthetic DXF made with ezdxf (a plate, 4 holes, dimensions):
  clean → no flags; one dimension text changed → exactly one flag; one callout count
  changed → exactly one flag.
- **manifest:** extend `test_bench_manifest.py`:
  - splits are disjoint
  - every `held_out` part has its data files. The count is not hard-coded, because a part
    whose pairing the cross-check rejects (possibly 1807408E) moves to `parked` through a
    reviewed manifest change
  - parked parts each have a reason
  - the seed and decision date are recorded
  - `views` paths are checked in the repo for repo parts, and under the data root for
    `MTI_BENCH_DATA` parts, skipped when the data root is absent
- **profile:** counts on a fixture of two small keys.
- No test needs SolidWorks, MTI data or an API key. Tests that need the data root skip
  without it.

## Out of scope (later sub-projects)

- Scoring, alignment, metrics and stage blame: sub-project 2.
- Running the pipeline on held-out parts: sub-project 3.
- Weldments, multi-component drawings, the 8 models without a matching drawing, and
  `MTI009126.SLDASM`.

## Open questions

1. **ODA File Converter install:** the user approved the approach. The install happens at
   the start of implementation, with the user's go-ahead on the download.
2. **1807408E pairing:** decided by the cross-check and the user's review.
3. **Parked parts:** promoting any of the 7 needs MTI's confirmation (M twins) or a
   feature-by-feature comparison (obsolete sheets).
