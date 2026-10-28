# MTI Practices Score Implementation Plan

> **For agentic workers:** execute task by task, test-first. User preference: one implementer and one combined review, fixing blocking issues only.

**Goal:** a separate 0–100 practices score per part (spec 2b), with blame and per-check reasons, read from the SolidWorks feature tree plus `ir_report.json` / `plan.json`. No API cost.

**Spec:** `docs/superpowers/specs/2026-10-25-practices-score-design.md`. The big problems that stay out of the score are in `docs/mti-practices-big-problems.md`.

## Conventions

The same conventions as `2026-10-24-benchmark-scorer.md`:
- worktree `combined-sw2024`, branch `feat/mti-benchmark`, code in `2D-3D-CAD-Test-Generation/`
- run from the `repro-sw2024` venv with `PYTHONUTF8=1` and `-p no:cacheprovider`
- local commits only; never stage `pipeline/solidworks_builder.py`, the error log, `tests/test_save_model.py`, `output/` or `swxJRNL.*`
- the commit trailer is Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>

Baseline: 978 passed, 2 xfailed.

**Hard rule 1:** use only SolidWorks APIs already used in this repo. That means `FirstFeature`/`GetNextFeature`, `GetTypeName2`, `Name`, `GetSpecificFeature2`, `GetConstrainedStatus`, `GetFirstSubFeature`/`GetNextSubFeature`, `OpenDoc6`, `CloseDoc`, `GetBodyBox` and `bench/sw_tasks.connect()`. Read their use in `pipeline/ir/compile_solidworks.py` and `bench/sw_tasks.py` first. `GetConstrainedStatus() == 3` means fully defined (the IR mapping, E023).

## Feature-tree record (the contract between tasks)

`feature_tree.json` is a list in tree order:

```json
[{"name": "Boss-Extrude1", "type": "Extrusion", "index": 7,
  "subs": [{"name": "Sketch1", "type": "ProfileFeature", "status": 3}]}]
```

- Every feature in the tree is recorded, including the origin, the planes and the folders.
- `status` is present only on sketch sub-features (and on top-level `ProfileFeature`s); otherwise it is null.

## Task 1: config and the pure checks (`bench/practices.py`)

**Config.** Add a `practices:` section to `bench/score_config.yaml`:
- `weights` for C1–C7, all 1
- `edge_ops: [Fillet, Chamfer]`
- `solid_ops: [Extrusion, ICE, Cut, HoleWzd, Revolution, RevCut, LPattern, CirPattern]`
- `avoid: [Sweep, SweepCut, Blend, BlendCut, Shell, Draft, Rib, MoveFace, MoveCopyBody, Boundary, BoundaryCut]` (names to confirm on real trees in Task 3)
- `three_d_sketch: 3DProfileFeature`

Extend `score_config.Config` with a `practices` dict, defaulting to `{}`.

**`check_part(tree, ir_report, plan, cfg) -> PracticeScore`.** `PracticeScore` holds `score` (None if nothing applies), `rows`, and `checked` (bool).

Each row is a `Check(id, name, credit, applicable, source, stage, reason)`, where `source` is `sldprt`, `self-reported`, `plan` or `proxy`.

| Check | Rule | Blame stage on failure |
|---|---|---|
| C1 | A `conventions` string containing "origin centered: True" passes; "False" fails. No report means not applicable. | solidworks |
| C2 | A conventions string mentioning both Top and Mid Plane passes; one saying the Mid Plane fallback was used fails. Read the real strings in `ir_report.json` files under `output/sw2024_check/combined/*/`. No report means not applicable. | solidworks |
| C3 | Fraction of sketch records (top-level `ProfileFeature` + subs) with status 3. No sketches means not applicable. | solidworks |
| C4 | Pass if no edge op comes before the last `solid_ops` feature. The reason names the first offending pair. No edge ops means not applicable. | planner |
| C5 | Fail on any `three_d_sketch` sub or feature under a `HoleWzd`. No `HoleWzd` means not applicable. | solidworks |
| C6 | Group plan hole features by the compiler's `hole_signature` + start face, giving credit 1 − (HW features − groups) / HW features. Reuse `pipeline/ir/compile_solidworks.hole_signature` if it can be imported without win32com; otherwise do the equivalent in plan dict terms. Also accept the `mti_review` code `mti_hole_grouping`. No holes means not applicable. | planner |
| C7 | Fail on any `avoid` type, naming the features. Always applicable when a tree exists. | planner if the plan contains that kind, else solidworks |

**Score:** 100 × Σ w·c / Σ w over the applicable checks.

**Tests** (`tests/test_bench_practices.py`): hand-made trees and reports covering pass, fail and not-applicable for every check, plus weights and the reasons.

## Task 2: tree reader and wiring into `bench.score`

**`bench/sw_tree.py`:**
- `read_tree(sw, sldprt) -> list` opens the part read-only, the same way `sw_tasks.sldprt_to_step` does, walks it, and closes it with `CloseDoc`.
- `cached_tree(part_dir, sldprt, sw)` reads `feature_tree.json` if it is newer than the SLDPRT; otherwise it reads the tree via SolidWorks and writes the cache.
- Lazy win32com only.

**`bench/score.py`:**
- In the same export pass that already needs SolidWorks, also read or cache trees.
- Add `res["practices"]` (asdict of the `PracticeScore`) to each part, a `practices_mean` to the summary, and a practices column plus a per-part checks table to `report.html`.
- `--no-sw` uses a cached tree when there is one, and otherwise marks the SLDPRT checks "not checked".
- The geometry score is unchanged; practices is never blended in.

**Tests:** CLI tests use a fake cached `feature_tree.json` (no SolidWorks), and `read_tree` is tested with a fake COM object, following the existing fakes in the `bench` tests.

## Task 3: real-data validation (needs SolidWorks; done with the user)

1. Run `read_tree` on MTI's 21 reference SLDPRTs, read-only. Find where they are in `MTI_BENCH_DATA` (the prep `copy` step put them there).
2. Run checks C3, C4, C5 and C7 on them, printing a table: part, each check, and reason.
3. Collect every feature type name seen. Confirm or fix the `avoid` / `solid_ops` names.
4. Review the failures with the user, and adjust checks or weights only on the user's word.
5. Score the 4 golden SolidWorks parts end to end with the practices column.
6. Update STATE.md and CLAUDE.md, then commit.
