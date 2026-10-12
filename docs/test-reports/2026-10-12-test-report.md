# Test Report: 2026-10-12 — MTI Phase 2: tapped holes, drill points, hole layouts

**Project:** mti-2d-3d (MTI 2D drawing → SolidWorks, iNDustry Labs / AILOT)
**Date:** 2026-10-12 · **Operator:** ggould (MalteseWarrior), with Claude Code
**Branch:** `feat/openai-extractor-sw2025` · **Host:** Windows 11, SolidWorks 2025 SP5
**API spend today: $0.00.** All builds reused saved GPT-6 Astra plans; the ledger is unchanged at $11.70 of $20.
**Previous day:** [2026-10-11](2026-10-11-test-report.md): MTI conventions and Phase 2a (Hole Wizard for clearance and counterbore holes).

## 1. Overall statement

The rest of MTI's hole practices are in. Bolt holes, **including tapped holes**, are now native Hole Wizard features:

- tapped holes get a cosmetic thread, never real threads;
- blind holes end in SolidWorks' 118° drill point;
- **a hole and its pattern are one feature** whose points sit on a construction bolt circle, line or rectangle.

That is MTI's "patterned holes sit on sketch geometry" and "fewer features" in one step.

**All 9 dev parts and all 5 golden plans still build and verify**, feature by feature, against the CadQuery reference.

## 2. What was run

| # | Run | Result |
|---|---|---|
| 1 | Type-library reads: `IWizardHoleFeatureData2` members; enums for tap types, cosmetic threads, thread end conditions, constrained status | Option names and values confirmed |
| 2 | Live probe: tapped hole, `TapType` / `CosmeticThreadType` changed through `ModifyDefinition` | **No effect on the cut**: options must go in at creation |
| 3 | Live probe: each of `Value1..12` set to 0/1/2 on a through tap | `Value1` = thread depth, `Value7` = cosmetic thread (1 → cuts exactly the tap drill), `Value8` = thread end (unsafe without a depth) |
| 4 | Live: blind tap, through tap, blind clearance, non-standard tap drill, metric "M8x1.25" vs "M8" | 5/6 exactly as computed (cylinder + 118° point). Bare "M8" refused |
| 5 | Live: Hole Wizard + construction circle / line / rectangle + coincident relations | Construction geometry adds **no** holes. Rectangle with relations to every edge → invalid sketch (fixed: only the edges a point lies on) |
| 6 | Dev set + golden after tapped holes | A040911E crashed: a tap's cosmetic-thread sub-feature isn't a sketch (fixed) → 3/3 parts ok |
| 7 | A040911E with auto bolt circle | Point check failed: the circle snapped 7 µm onto the origin (fixed: construction drawn with `AddToDB` on) |
| 8 | **Record run** → `output/ir_runs_p2_final/`, `output/p2_golden_final/` | **9/9 dev, 5/5 golden verified**, origin centered on all |
| 9 | Unit tests | **403 passed** (384 → 403: thread parsing, tap choice, MTI thread depth, drill point, layouts, volume credit) |

## 3. Hole Wizard on the dev set (record run)

| Part | Hole Wizard features |
|---|---|
| 115-C | 3/8 clearance: **4 holes in one feature on a construction rectangle** (was seed + pattern = 2 features) |
| 117-C | 5/8 clearance: 4 holes on a construction rectangle. 1/4 clearance pair: **blind + drill point** (was a plain cut) |
| 135-A | 5/16 SHCS counterbore: 2 holes on a construction line (was 2 features) |
| A040911E | 1/4 SHCS counterbore: 3 holes on a **construction bolt circle**. **3/8-16 tapped, cosmetic thread**, blind + drill point, 2 holes |
| SB11842 | 5/16 SHCS counterbore: 4 holes on a construction bolt circle |
| golden A040911E | same as A040911E |

**Totals:** 7 Hole Wizard features covering 17 holes on the dev set, against 13 features for 25 holes yesterday. The holes are all still there: yesterday's count included the separate pattern copies, and each seed plus pattern is now a single feature, as MTI asks.

**Still plain cuts, each with a note:**

- 116-C Ø.400 and SB11033 Ø.218: they match no MTI size (engineer check, question 6).
- 115-C's 3/8 NPTF pipe tap.
- 117-C's larger holes: there is no face under their centers.

## 4. Failures and fixes

All are in [error log E022](../solidworks-macro-error-log.md).

1. **Taps ignore option changes after creation.** The cosmetic-thread option is passed in `HoleWizard5` (`Value7`).
2. **Taps carry a cosmetic-thread sub-feature that isn't a sketch.** The placement search now keeps `ProfileFeature` only.
3. **Over-related construction rectangle.** It gave "invalid solution". Points are related only to geometry they lie on, and bad sketch states are rejected.
4. **Bolt circle snapped onto the origin** (7 µm away). Construction geometry is drawn without inference. This is the third snapping case (E020, E021); the lesson stands that **programmatic sketches never rely on inference.**

## 5. Decisions

- **Blind Hole Wizard holes keep SolidWorks' 118° drill point.** It is what a shop drills, and its volume is credited exactly, so the check stays strict. The CadQuery reference is unchanged.
- **Thread depth.** The cosmetic thread depth is MTI's standard tap depth, capped at the drill depth (STANDARD-DERIVED). The IR has no printed thread depth yet, so adding `thread_depth` to `HoleSpec` is a candidate.
- **Metric callouts without a pitch** get the ISO 261 coarse pitch (public standard).

## 6. Questions added for MTI

7. **Turned parts:** under "base sketch on Top", a revolved part's profile is on the Top plane, so its axis lies flat. Would MTI rather have the axis vertical?
8. **Thread depth:** when a print gives none, is MTI's standard tap depth the right default?

## 7. Next steps

Last Phase 2 item: **fully defined sketches.**

- Relations first.
- Then regular dimensions from model edges.
- Check `GetConstrainedStatus` and report anything not fully defined.

After that:

- pipe taps;
- Phase 3 (mirror and symmetry);
- the roadmap items in STATE §5.

---

## 8. Addendum, same day: Phase 2c, fully defined sketches (E023), and E024

**Spend: $0. Tests: 405 pass.**

- **What was built.** Every sketch the compiler draws goes through SolidWorks' **Fully Define Sketch**:
  - exact relations only (horizontal, vertical, midpoint, coincident);
  - regular dimensions from the face's leftmost and lowest **model edges**;
  - an anchor point tied to the origin where SolidWorks can't use edges (base-plane sketches).
  
  Hole Wizard placement sketches never get an anchor. The status of each sketch goes into the build report.
- **Probes (live, scratch parts).**
  - `FullyDefineSketch` returns success even when the sketch stays under-defined, so status is always read back.
  - Base-plane sketches won't take locations from the origin or from model edges; an anchor with an explicit coincident to the origin works.
  - An anchor created with inference snapped onto an origin-centered circle instead of the origin.
  - Fully Define's relations moved nothing, even 0.0005" off.
- **Dev-set record run** (`output/ir_runs_fd3/`): **9/9 parts verified; 29/30 sketches fully defined**, up from 13/32 on the first attempt. The exception is 117-C F011, a Hole Wizard placement sketch, which is reported.
- **Golden re-run: not completed.** SolidWorks refused new documents after two days of batch runs had left **86 parts open** (E024). The fix: `compile_solidworks` now closes each part after saving it (`keep_open=False`; the demo keeps its part open). The golden plans passed in every earlier run today, so the next run needs a fresh SolidWorks session: close SolidWorks or the open output parts, then run
  `python ir_build.py tests/golden/ir/*.json --solidworks`.

## 9. State at end of day

**MTI Phase 2 is complete**, apart from:

- one Hole Wizard placement sketch (117-C F011) left under-defined;
- pipe taps;
- counterbore drills Up To Next on plain-cut counterbores.

**Next:**

1. Re-run the golden plans in a fresh SolidWorks session.
2. Phase 3: mirror and symmetry.
3. MTI's answers to questions 1–8.
