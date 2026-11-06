# MTI demo runbook (rehearsed 2026-11-02; hero updated to the 2N2664 re-plan)

**What it shows:** one of MTI's own scanned drawings goes in, and a verified, MTI-convention
SolidWorks part comes out, feature by feature. It finishes by scoring the result against **MTI's
own SolidWorks model**, which the pipeline never saw.

**Cost:** $0 in replay mode, which uses the saved extraction and plan. A live plan in front of the
room costs about $1 (see "Live option").

## The parts

| Role | Part | What it is | Built | Against MTI's model | Run time |
|---|---|---|---|---|---|
| **Hero** | **2N2664, re-plan of 2026-11-02** | Turned hub: 10-station turned profile, Hole Wizard taps and counterbores (1/4-20, 1/4 SHCS), **a radial cross-hole at 240°**, 6 fillets and chamfers | All 16 built features verified; **1 question** (the recess end: it asks instead of guessing); 3 default rules shown | **overlap 0.996**, volume 1.003, mean surface distance 0.15 mm | ~2 min |
| Fallback | 2N2664, earlier plan | The same hub, with the recess built and no radial hole | 21 planned, all built features verified; 0 questions; 4 default rules | overlap 0.993, volume 1.006, mean 0.10 mm | ~5 min |
| **Backup** | **A00122E** | Plate: 19 features, 7 Hole Wizard features (three clearance sizes + #8-32 taps) | 19/19 verified; 0 questions | overlap 0.987, mean **0.06 mm**, max **0.21 mm** | ~45 s |
| Wow, with caveat | SB14306 | 546 mm collet: 28 features, 9 native circular patterns, 8 Hole Wizard taps | 26/28 (2 MTI questions) | 0.74: **MTI's model doesn't match its drawing** (see `docs/mti-questions/`) | ~15 min |

## Before the meeting

1. **Start SolidWorks 2025** and let it finish loading. Open and close one part, so it's warmed up
   (error log E025).
2. Open a terminal in `C:\Users\gingw\Desktop\AILOTFALL\mti-2d-3d-feat\2D-3D-CAD-Test-Generation`.
3. Set the environment (PowerShell):

   ```powershell
   $env:PYTHONUTF8 = "1"; $env:API_BUDGET_USD = "50"
   ```

   Without `API_BUDGET_USD`, the summary line reads "of $20".
4. Widen the terminal to about 140 columns and arrange SolidWorks next to it.
5. Optional: run the backup once with `--no-pause --pace 0`, about 45 s, to confirm everything is
   up.

## Run it

**Hero (re-plan):**

```powershell
..\..\mti-2d-3d\.venv\Scripts\python.exe demo.py --part 2N2664 --from ..\..\mti-2d-3d\2D-3D-CAD-Test-Generation\output\2n2664_replan
```

**Fallback (earlier plan):** the same command with `--from ..\..\mti-2d-3d\2D-3D-CAD-Test-Generation\output`.

**Backup part:** `--part A00122E --from ..\..\mti-2d-3d\2D-3D-CAD-Test-Generation\output`.

Press **Enter** between steps. `--pace 1.5` (the default) slows the SolidWorks steps down for the
audience.

## The eight steps, and what to say

1. **The drawing.** "This is MTI's own scan. It's the only input." The drawing opens in the
   default viewer.
2. **What GPT-6 Astra read.** "Every dimension gets an ID. The plan may only use these IDs."
3. **The build plan.** "Every coordinate is an expression over drawing dimensions, like
   `D021 / 2`. No free numbers, so every value traces back to the drawing."
4. **Gate 1.**
   - "Invented numbers or broken references are rejected before anything is built."
   - Point at the magenta **default rules**: "'.12 C/R' becomes a 45° chamfer, and 'RADII .047
     MAX' becomes a .047 fillet. These are documented rules, with values taken from MTI's own
     models."
   - Point at the yellow **question** (re-plan): "The recess end's .377 width, .188 offset and .188
     R don't define a consistent semicircle, so it asks an engineer instead of guessing."
   - Point at the cyan flags: "Anything that isn't printed on the drawing is flagged for review."
5. **Reference model.** "An independent build of the plan: the yardstick SolidWorks has to match."
6. **SolidWorks, feature by feature.** "After every feature, the volume has to match the
   reference, or it's undone and retried."
   - Point out MTI's conventions: origin centred, base sketch on Top, Hole Wizard for bolt holes
     and taps, cosmetic threads, Up To Next, fully defined sketches.
   - **F017, the radial cross-hole at 240°:** "Drilled into the side of a turned part at the angle
     the drawing gives, '30° left of downward'."
7. **Against MTI's own model.** "This is the model your engineer drew. We never showed it to the
   pipeline. 99.6% overlap, and its volume is within 0.3%." The 12 mm maximum distance is the
   recess it asked about.
8. **Result.** "One question it refused to guess. Cost of this run: $0 in replay; about $1 live."

## Talking points backed by the audit

- **All 38 PDF drawings in MTI's test set build and verify** in SolidWorks. 28 of them overlap
  MTI's models at ≥ 97.9%; several are exact (1.000).
- **When the pipeline can't tell, it asks.** Unresolved callouts become questions; nothing is
  guessed silently.
- **Data findings for MTI** (handle tactfully):
  - the SB12050/SB12051 model files are swapped in Drive;
  - three models differ from their drawings.
  - We build to the drawing, because the drawing is all production will have.

## Known gaps (if asked)

- **2N2664:** the re-plan builds the radial cross-hole but asks about the recess end (.377 wide
  with a .188 R, inconsistent by .001). The earlier plan built the recess but couldn't place the
  cross-hole. Answering the question, or a rule for "full R" ends, would complete it.
- **Radial taps are plain cuts;** MTI uses Hole Wizard on the curved face. This is a follow-up.
- **SB11488:** one noisy scan whose central profile the planner won't commit to.

## Live option (~$1, budget-guarded)

```powershell
..\..\mti-2d-3d\.venv\Scripts\python.exe demo.py --part 2N2664 --from ..\..\mti-2d-3d\2D-3D-CAD-Test-Generation\output --live
```

- **What it does:** GPT-6 Astra plans the part in front of the room. The extraction is reused.
- **Risk:** a fresh plan can differ from the rehearsed one. The 2026-11-02 re-plan, for example,
  differs from the earlier plan on the recess. $2.46 is left of $50, enough for about two live
  runs.
