# Weekly status: Monday 2026-11-02

**Project:** mti-2d-3d (2D drawing → SolidWorks part for MTI) · **Covers:** sessions of 2026-10-26 → 2026-10-28
**Branch:** `feat/openai-extractor-sw2025` → PR #6 (merged upstream before this copy was taken; the upstream repo is no longer referenced by this one)
**API budget:** $46.68 of $50 spent (ledger `~/.mti-2d-3d/budget_ledger.jsonl`), **$3.32 left**

## Where we are

- **All 38 PDF drawings in MTI's 63-part test set have been run, and all 38 build and verify in
  SolidWorks.**
- 28 overlap MTI's own models at IoU ≥ 0.979. Several are exact: SB12006, SB12051, A00142E and
  others are at 1.000.
- **The remaining low scores are mostly MTI data issues, not pipeline errors:**
  - MTI's models for **SB12050 and SB12051 are swapped** in Drive.
  - **SB12009, SB14306 and A00161E:** MTI's model doesn't match its own drawing. We build to the
    drawing, which is the rule now.
  - **SB12059:** the drawing has four separate pads; MTI modelled one uncut ring.
- **Two real pipeline gaps remain:**
  - **SB11488:** the central profile on a noisy scan is never read.
  - **4C1229:** 4.5% light; the cause is not yet found.
- **The 24 DWG drawings are converted to PDF**, and MTI's models are exported. They are ready to run
  once there is budget (~$17).

## Completed in the last sessions

**Test runs on MTI's parts audit** (Drive folder, read-only, via Composio):

- Batch 1 (10 parts), batch 2 (21) and batch 3 (7 + the SB11488 re-plan): all 38 PDF parts.
- Every part is scored against MTI's model with `mti_score.py`: IoU, volume, size, and surface
  deviation in mm.

**Compiler and reference fixes** (each logged in `docs/solidworks/solidworks-macro-error-log.md`):

| Entry | Fix |
|---|---|
| E028 | Slots (`CreateSketchSlot`) and native circular patterns (`FeatureCircularPattern5`) |
| E029 | Through-tapped holes, trimmed-cylinder crash, seam-edge selection (fixed 4C1229 and SB14306) |
| E030 | Tight bounding box via `GetExtremePoint` (`GetBodyBox` is loose on curved faces) |
| E031 | Multi-body parts (sawcut pads) verify; defaults never mark an unbuildable feature planned |
| E032 | Radial-hole COM casts (`ISketchLine`, `IFeature` for new reference planes) |

**New capabilities:**

- **Callout defaults** (`pipeline/ir/defaults.py`):
  - Vague callouts are built by documented rules instead of being skipped: R MAX, C/R, unsized
    breaks, a tap given only a thread depth, thread class.
  - The rule values were measured from MTI's own models.
  - Unresolved features across the audit fell from 60 to 29.
  - A tap and its pilot drill now merge into one Hole Wizard tap, as MTI models them.
  - Switch: `MTI_CALLOUT_DEFAULTS=0`.
- **Radial holes** (drilled into the OD of turned parts):
  - In both the CadQuery reference and SolidWorks.
  - Verified for handedness on a chiral test part: IoU 1.000 with no mirroring.
  - SB12095's radial taps now build.
- **Scoring:**
  - `mti_score.py` reports surface deviation in mm (IoU misleads on thin sheet parts) and
    `iou_clocked` for turned parts.
  - Checks are fixed for multi-body parts and loose bounding boxes.

**Repo and process:**

- Merged smcanuff's benchmark scorer (`bench/`) from `main`. Error-log numbers were reconciled:
  ours are E028–E032; E026/E027 are reserved for smcanuff.
- PR #6 has its title and description; review was requested from smcanuff-sudo.
- MTI model-vs-drawing summary written: `docs/mti/mti-questions/2026-10-28-model-vs-drawing-mismatches.md`.
- Rule recorded: **the 2D drawing is the ground truth.** Production runs only get the drawing.
- Budget raised by the user: $20 → $40 → $50. An expired OpenAI key was replaced on 2026-10-28.
- **Tests:** 1008 passing, 66 skipped (they need `MTI_BENCH_DATA`).

## Not committed yet (do first)

These are in the worktree only:

- radial holes (spec, code, golden part, tests);
- tap + pilot merges;
- `iou_clocked`;
- the 4C1229 correction;
- test report §9–§10, E032, STATE;
- this note.

**Action:** commit and push to PR #6.

## Next steps

**This week (free):**

1. **Commit and push** the uncommitted work above to PR #6, then get smcanuff's review and merge
   PR #6 into `main`.
2. **Get `MTI_BENCH_DATA`** (answer keys) from smcanuff. Then run `python -m bench.score` on our
   audit runs. That gives a feature-level score plus stage blame, and replaces IoU as the headline
   number.
3. **4C1229:** find the 4.5% volume gap (groove profile or slot depth) by comparing sections, as was
   done for SB14306.
4. **Radial Hole Wizard taps:** MTI uses `HoleWzd` on curved faces; we cut plain holes. This needs
   a 3D placement sketch.
5. **SB18461:** pair its 5 drawing sheets with its model by detail number.

**Needs budget (ask before spending):**

6. **The 23 converted DWG parts:** ~$17 at ~$0.75 each (PDFs are already in `output/<part>/source/`).
7. **Re-plan SB12059, SB12054 and 2N2664** (~$2.10) so their radial holes get real angles. These
   plans were written before the angle field existed.

**Needs MTI** (send `docs/mti/mti-questions/2026-10-28-model-vs-drawing-mismatches.md`):

8. Swap back the SB12050/SB12051 models, or confirm.
9. Is the drawing or the model current for SB12009, SB14306 and A00161E?
10. Intended geometry for the SB14306 .375 R blend, and "BREAK ALL SHARP CORNERS" sizes.
11. **Where are MTI's `.swp` macros?** CLAUDE.md says to run them via `RunMacro2`; they still aren't
    in the repo.

**Open decisions:**

- **Origin convention for SB turned parts:** MTI's SB models put the origin at an end face; ours is
  centred, which MTI's written practice asks for. Ask MTI which they want.
- **SB11488:** its central profile needs a human reading of the section or a better scan. The
  planner won't commit on this scan.

## Where to look

- **Daily detail:** `docs/test-reports/2026-10-26-test-report.md`, `docs/test-reports/2026-10-28-test-report.md`
- **Current state:** `STATE.md`
- **Specs this week:**
  - `docs/superpowers/specs/2026-10-28-callout-defaults-design.md`
  - `docs/superpowers/specs/2026-10-28-radial-holes-design.md`
- **Results:** `2D-3D-CAD-Test-Generation/output/mti_audit_batch1..3/` (our outputs only; no MTI
  source files)
