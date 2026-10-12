# MTI modeling standards in the pipeline: design

**Date:** 2026-10-11
**Status:** Phase 1 implemented and verified. Phases 2–4 proposed.
**Inputs:** MTI's *Modeling Best Practices*, *SolidWorks Feature Guide*, six MTI macros, and MTI Std 202.02.0003. These are summarized, with per-item status, in [docs/mti-modeling-standards.md](../../mti-modeling-standards.md).

## Problem

The pipeline builds a part that is *geometrically* right: verified per feature against the CadQuery reference. MTI also cares *how* the part is modeled, because its engineers maintain these models for years:

- where the origin sits;
- which plane the base sketch is on;
- Hole Wizard instead of plain cuts;
- Up To Next instead of Through All;
- fully defined sketches;
- symmetry;
- dimensions from model edges.

Our old convention (lower-left corner at the origin, Front-plane base, Through All, CLAUDE.md rule 3) contradicts several of these.

## Principle

**Separate *what* from *how*.**

- **What (unchanged).** The BuildPlan, its drawing-frame expressions over dimension IDs, and the CadQuery reference. Positions stay edge-referenced exactly as the drawing gives them, and that is what keeps placement grounded (rule 6).
- **How (new).** The SolidWorks compiler, which maps the plan into MTI's modeling convention:
  - It applies a rigid transform: a rotation plus a translation, **never a mirror**.
  - It picks MTI-preferred end conditions and feature types.
  - It verifies each choice by volume against the reference, the same check every feature already gets.
  - If SolidWorks disagrees, it falls back to the previous construction and logs the fallback.

MTI says the practices are *not hard and fast rules*. Practices the compiler can verify are **applied**. Practices that need judgement are **reported** to the reviewing engineer (advisory findings) and never block a build.

## Phase 1 (done 2026-10-11)

| Change | Where | How it is verified |
|---|---|---|
| **Centered origin.** The model origin is the center of the base body's bounding box. | `cq_runtime` records `base` (first body's fid and bbox). `_SW.shift`; `_SW.local()`. | `origin_centered()` on the SolidWorks body after the base feature → `SwBuildReport.origin_ok`. `ok` fails if it is False. |
| **Base sketch on the Top plane.** `PlaneMap.oriented(base_axis)` cyclically permutes the IR axes so the base sketch normal (prism axis, or IR Y for a revolve) is Top's normal. | `compile_solidworks.py` | A determinant check rejects a left-handed Top plane, so the transform is never a mirror. Unit tests cover all 3 axes. |
| **Mid Plane base extrusion.** Sketch on Top through the origin, `swEndCondMidPlane` (6). | `_SW.mid_plane` | Volume vs the reference. On a mismatch: undo, then an offset-start Blind extrude, logged. |
| **Center rectangle** for a base rectangle centered on the origin. | `_SW.prism` | Volume. |
| **Up To Next** for through cuts (`swEndCondUpToNext` = 2). | `_SW.thru_cut` | Volume. On a mismatch, both directions are tried, then Through All, and the fallback is logged. |
| **Plane selection by tree position** (MTI `SelectPlane` macros, rule 4). | `solidworks_builder.select_ref_plane`, used by both Python builders | Live: plane probe and builds. |
| **MTI Std 202.02.0003, local and confidential.** | `config/mti/*.local.json` (gitignored), `pipeline/mti_standards.py` | Synthetic-table unit tests; a test that the real file stays gitignored. |
| **MTI counterbores win** over the generic SHCS chart when the table is present. | `fasteners.shcs_counterbore`, `table_source()` | Unit tests. |
| **Advisory MTI review:** `mti_hole_wizard` (screw match or plain cut), `mti_hole_grouping`, `mti_edge_ops_last`, `mti_avoid`. | `pipeline/ir/mti_review.py`, in `ir_report.json` / `ir_build_summary.json` | Unit tests. Run on the golden plans. |

`convention="drawing"` keeps the old behaviour (for comparison and debugging). `"mti"` is the default.

**Unchanged on purpose:**

- The IR frame (`corner` / `axis_end`) and every expression.
- The CadQuery reference and the IoU scorer (both work in the drawing frame).
- The VBA macro path (v1). It keeps its rule-3 frame until it is retired or ported; the IR is the path forward.
- The planner prompt. It does not get the confidential table; Hole Wizard mapping is deterministic and local.

**Live result (SW 2025 SP5, $0):**

- **Golden plans:** all 5 build and verify with the origin centered.
  - The plate (DEMO-PLATE-001) uses Mid Plane, and its 3 through-hole features use Up To Next.
  - The 4 revolved parts put their profile on Top.
- **Dev set:** see the 2026-10-11 test report.

## Phase 2 (proposed): Hole Wizard and fully defined sketches

1. **Hole Wizard emission.** `FeatureManager.HoleWizard5` (to be verified live and recorded first, per rule 1).
   - Standard, type and size come from the `mti_hole_wizard` match: clearance → "Hole" with SHCS clearance fit; tap drill → "Tapped hole"; counterbore → "Counterbore".
   - End condition: Up To Next. One feature per (face, size), with every sketch point of that size.
   - Cosmetic threads on tapped holes, with shaded display on (`ToggleCosmeticThreads`).
   - Verified by volume against the reference. The reference itself needs no change: a Hole Wizard clearance hole is the same cylinder.
2. **Pattern sketches on construction geometry.** A bolt circle becomes a construction circle with points on it. A grid becomes a construction rectangle.
3. **Fully defined sketches.**
   - Relations first: coincident to origin, midpoint, symmetric, horizontal/vertical.
   - Then dimensions from model edges (datum edges), using regular dimensions, not ordinate.
   - Check `ISketch.GetConstrainedStatus` = fully defined before each feature; report anything not fully defined.
4. **Counterbore drills Up To Next.** This needs an intermediate reference volume (drill-only) so the drill can be checked alone.

**Open questions for MTI:**

- **Normal vs loose clearance:** which is the default?
- **Inch vs metric:** when a plain hole matches neither exactly, which hardware system should the AI assume for a legacy inch print?
- **Hole Wizard standard:** which standard and fastener-type names does MTI's SolidWorks use (ANSI Inch "Socket Head Cap Screw", ...)?
- **Datum edges:** should the AI follow the drawing's datums, or MTI's own (e.g. always the lower-left edges after centering)?

## Phase 3 (proposed): symmetry

- An IR `mirror` feature: mirror a feature about a base plane. With a centered origin, the base planes *are* the symmetry planes.
- `plan_from_v1` and the planner propose mirrors when features are symmetric about the base body center.
- Symmetric sketch relations.

## Phase 4 (proposed): sheet metal

Base flange/tab, edge flange and hem are "very common" at MTI. This needs drawings with flat patterns in the benchmark first.

## Risks

- **Up To Next on stacked bodies.** It may stop at an internal face. Handled by the volume check and the Through All fallback.
- **Mid Plane depth semantics.** Verified live: D1 is the total depth.
- **Confidential table drift.** The transcription is unverified until MTI supplies the source. Every use is labeled `STANDARD-DERIVED` and reviewed.
