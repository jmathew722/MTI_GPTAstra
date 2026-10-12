# Test Report: 2026-10-11 — MTI's modeling standards in the pipeline

**Project:** mti-2d-3d (MTI 2D drawing → SolidWorks, iNDustry Labs / AILOT)
**Date:** 2026-10-11 · **Operator:** ggould (MalteseWarrior), with Claude Code
**Branch:** `feat/openai-extractor-sw2025` · **Host:** Windows 11, SolidWorks 2025 SP5, Python 3.13
**API spend today: $0.00.** All builds reused saved GPT-6 Astra plans. The ledger is unchanged at $11.70 of the $20 cap (`~/.mti-2d-3d/budget_ledger.jsonl`).

> **Trigger.** After the live demo, MTI's lead engineer sent their modeling practices, feature guide, six macros and Std 202.02.0003 (tap and hole specifications).
> What MTI wants, item by item: [docs/mti-modeling-standards.md](../mti-modeling-standards.md).
> Design: [specs/2026-10-11-mti-modeling-standards-design.md](../superpowers/specs/2026-10-11-mti-modeling-standards-design.md).

## 1. Overall statement

Every part the pipeline builds is now modeled the way MTI asked:

- the base body is **centered on the origin**;
- the base sketch is on the **Top plane**;
- plate bases are **Mid Plane** extrusions;
- through holes are **Up To Next**.

All of it is verified feature by feature against the CadQuery reference. **All 9 dev parts and all 5 golden plans build and verify** in SolidWorks under the new convention, the same coverage as on 2026-10-04.

**Hole check.** A new deterministic review compares every hole with MTI's own hole standard:

- **12** hole features are bolt holes → Hole Wizard candidates (named screw, inch).
- **10** are not standard sizes → plain cut-extrudes.
- **4** pairs or groups of identical holes on one face should be **one** Hole Wizard feature.
- **3** parts have a fillet or chamfer before other features. MTI wants those last.

**Failure and fix.** One new SolidWorks behaviour appeared: inference snapping near the new origin. It was found, fixed and logged as **E020**.

## 2. What was run

| # | Run | Command | Result |
|---|---|---|---|
| 1 | Unit tests | `python -m pytest tests/` | **373 passed** (340 → 373: +16 SW compiler / MTI convention, +17 MTI table and review) |
| 2 | Golden plans, live SW, MTI convention | `ir_build.py tests/golden/ir/*.json --solidworks` → `output/mti_conv2/` | **5/5 ok**, origin centered on all 5 |
| 3 | Dev set, live SW, MTI convention, first pass | `ir_run.py --split dev --solidworks --reuse-plans` (first pass; not kept) | **8/9.** 115-C F006 mismatch (§3) |
| 4 | 115-C, both conventions | `ir_build.py ... --convention drawing / mti` | Reproduced: fine in the old frame, wrong in MTI's |
| 5 | Dev set after the E020 fix | same as 3 → `output/ir_runs_mti2/` | **9/9 ok**, origin centered on all 9, no fallbacks used |

### Per part (run 5)

"Built" counts exclude features skipped as open human questions. Those are the same 9 questions as on 2026-10-04.

| Part | SW ok | Built | Base | Through holes Up To Next | MTI review |
|---|---|---|---|---|---|
| 115-C | ✅ | 6/7 | Top, Mid Plane | 2 | 1 bolt hole (3/8 clearance), 2 non-standard |
| 116-C | ✅ | 5/6 | Top, Mid Plane | 2 | Ø.400 holes: no exact match, but close to a 3/8 clearance → **engineer check** |
| 117-C | ✅ | 13/16 | Top, Mid Plane | 2 | 4 bolt-hole features (5/8, 1-1/4, 1/4 ×2); 2 groups to merge |
| 135-A | ✅ | 3/3 | Top, Mid Plane | 0 | 5/16 SHCS counterbore, consistent with the standard |
| A040911E | ✅ | 7/7 | Top (revolve) | 0 (all counterbored) | 1/4 SHCS counterbores consistent with the standard; 3/8-16 tapped; 2 groups to merge; chamfer before holes |
| A040921E | ✅ | 3/4 | Top (revolve) | 0 | chamfer before a cut |
| SB11033 | ✅ | 6/7 | Top (revolve) | 2 | Ø.218: no exact match (nearest #10 clearance) → **engineer check**; fillet before holes |
| SB11780 | ✅ | 2/4 | Top (revolve) | 0 | — |
| SB11842 | ✅ | 4/6 | Top (revolve) | 1 | 5/16 SHCS counterbore consistent with the standard |

## 3. Failure: E020, sketch snapping near the centered origin

**115-C F006** is a 37/64 blind cross-drill. In the new frame its center sat 0.005" from the origin, and SolidWorks' sketch inference snapped it *onto* the origin. The part came out 0.016 in³ off the reference, and the volume check refused it, as designed.

**Fix:** the compiler sets `SketchManager.AddToDB = True` (no inference) for the whole build. Regression test added.

**Lesson:** centering the origin puts many features near it; programmatic sketches must never rely on inference. Full entry: [error log E020](../solidworks-macro-error-log.md).

## 4. What changed (code)

- **`pipeline/ir/compile_solidworks.py`.** `convention="mti"` is the default:
  - `PlaneMap.oriented()`, a rotation only (a determinant check refuses a mirror);
  - origin shift to the base-body center;
  - `mid_plane()`;
  - `thru_cut()` (Up To Next, falling back to Through All);
  - center rectangle for the base;
  - `origin_ok` in the report;
  - `AddToDB`.
- **`pipeline/ir/cq_runtime.py`:** records the base body (`fmap["base"]`).
- **`pipeline/solidworks_builder.py`:** `select_ref_plane()` falls back to the feature-tree position (MTI's `SelectPlane` macro pattern). Both Python builders use it.
- **`pipeline/mti_standards.py`:** loads MTI Std 202.02.0003 from a **gitignored local file** and matches hole diameters to screws.
- **`pipeline/fasteners.py`:** MTI counterbores win over the generic chart when the table is present.
- **`pipeline/ir/mti_review.py`:** advisory `mti_*` findings in `ir_report.json` and `ir_build_summary.json`.
- **`ir_build.py`:** `--convention`.
- **`tests/conftest.py`:** tests never read the machine's confidential table.

## 5. Decisions

1. **What vs how.** Plans stay in the drawing frame (grounded placement, rule 6). The SolidWorks compiler applies MTI's convention. CLAUDE.md rule 3 was rewritten to match.
2. **Apply what can be verified; report the rest.** MTI calls these "general best practices, not hard and fast rules". Nothing blocks a part over a practice.
3. **The MTI hole standard is confidential.** It stays local (gitignored, test-enforced), is never sent to the model API, and its values stay out of the repo, including tests and docs.

## 6. Open questions for MTI

1. May the transcribed Std 202.02.0003 be checked against the source document? We transcribed a low-resolution screenshot. An Excel or PDF export would remove transcription risk.
2. **Clearance fit:** is normal clearance the default, with loose clearance only when the print says so?
3. **Inch vs metric:** for a legacy inch print whose hole matches no inch size, should the AI ever propose metric hardware?
4. Which Hole Wizard standard and type names does MTI's SolidWorks use?
5. **Datum edges for dimensions** (practice 7): follow the drawing's datums, or a fixed MTI choice?
6. The two near-misses: **116-C Ø.400** (a 3/8 bolt?) and **SB11033 Ø.218** (a #10 bolt?).

## 7. Next steps

**Phase 2** (spec):

- Hole Wizard emission (`HoleWizard5`, verified live first), with one feature per size per face, plus cosmetic threads on tapped holes;
- hole patterns on construction geometry;
- fully defined sketches, dimensioned from model edges.

**Ongoing roadmap:**

- resolve-and-resume for the 9 human questions;
- Gate 2 auditor;
- MTI reference STEP for a held-out set.
