# Live demo guide: 2D drawing → verified SolidWorks part

A narrated, step-by-step demo (`2D-3D-CAD-Test-Generation/demo.py`) that pauses for you between
steps while SolidWorks builds the part on screen. Rehearsed 2026-10-05 on SB11033 (all features
verified) and A040911E.

## Before the meeting (10 minutes)

1. **Be on the right branch.** In the repo root: `git checkout feat/openai-extractor-sw2025`.
2. **Open SolidWorks** first and let it finish loading. The demo attaches to the running instance.
3. **Open a terminal** in `2D-3D-CAD-Test-Generation/`, make the font large, and run:
   ```bash
   set PYTHONUTF8=1
   ..\.venv\Scripts\python.exe demo.py --part SB11033 --no-pause --pace 0
   ```
   This is a full rehearsal (about 2–3 min, free). It also warms up SolidWorks and CadQuery.
4. Arrange the screen with **terminal on the left, SolidWorks on the right**.
5. Close the rehearsal part in SolidWorks (no need to save).

## In the meeting

```bash
..\.venv\Scripts\python.exe demo.py --part SB11033            # REPLAY: free, no network (recommended)
..\.venv\Scripts\python.exe demo.py --part SB11033 --live     # LIVE: Astra plans it now (~$0.20-0.50, +1-2 min)
```

Press **Enter** to advance. `--pace 2` slows SolidWorks between features if you want more time to talk.

| Step | On screen | Say |
|---|---|---|
| 1 Drawing | The scanned sheet opens | "This is a real MTI drawing, a scan. It's the only input." |
| 2 What Astra read | Table of dimensions D001… | "GPT-6 Astra reads every dimension and gives it an ID. Everything after this has to cite these IDs." |
| 3 Build plan | Features with expressions like `D001 / 2` | "This is the key idea: no free numbers. Every coordinate traces to a dimension on the drawing, so you can audit placement line by line." |
| 4 Gate 1 | PASS, questions, flagged values | "Deterministic checks reject invented numbers. Anything the drawing doesn't settle becomes a question for an engineer, never a guess." |
| 5 Reference | Volume, size, STEP file | "We build an independent reference model first. It's the yardstick." |
| 6 SolidWorks | Features appear one by one with OK marks | "SolidWorks builds it natively, and after every feature we check the volume matches the reference. A wrong direction is caught and redone automatically." |
| 7 Result | Summary panel: questions, cost | "A verified part in about a minute, with a short list of questions for the engineer. Cost per new drawing: about fifty cents to a dollar." |

## Which part

| Part | Why show it |
|---|---|
| **SB11033** (default) | Flange + pilot + boss, 4-hole bolt circle, fillet and chamfers. Looks great; 1 question (".015 MAX R") |
| **A040911E** | Bearing ring: 3 counterbored + 2 tapped holes, **0 questions**; fastener standards cited |
| **A040921E** | Ring with an end slot, the feature the old pipeline could never build |
| **115-C / 117-C** | Plate parts with ports; shows breadth |

Avoid **SB11780** live: it's a 76.88-inch shaft, so it builds fine but is a thin line on screen.

## Talking points (numbers from the 2026-10-04 test report)

- **Before:** 10 of 26 features built on 5 parts, and every incomplete part was approved anyway.
- **Now:** all 9 dev parts are verified in SolidWorks, matching hand-checked answers at IoU 0.986–1.000.
- **Honesty:** 0 false approvals; 9 written questions across 9 parts instead of guesses.
- **Cost:** about $0.50–1.00 for a new drawing, $0 to rebuild. Hard $20 test budget; $11.70 used.
- Full record: `docs/test-reports/2026-10-04-test-report.md`.

## If something goes wrong

| Problem | Do this |
|---|---|
| Network or API issue in `--live` | The demo falls back to the saved plan automatically. Or rerun without `--live` |
| SolidWorks not responding | Close it, reopen, rerun (the demo reconnects). Or run `--no-solidworks` and show `output/ir_build/<part>/<part>_ir.png` |
| Need to stop | Ctrl+C. Nothing is changed outside `output/demo/` |
