# MTI modeling standards: what MTI wants, and where the pipeline stands

**Source:** material MTI's lead engineer provided after the 2026-10 demo. It covers:

- *Modeling Best Practices* (contact: Logan Foerch);
- *SolidWorks Feature Guide*;
- six of MTI's SolidWorks macros (`SelectPlane1/2/3`, `SelectPlaneNext`, `SelectFaces`, `ToggleCosmeticThreads`);
- MTI Standard **202.02.0003** *Tap and Hole Specifications*.

**Design:** [specs/2026-10-11-mti-modeling-standards-design.md](../superpowers/specs/2026-10-11-mti-modeling-standards-design.md).

> MTI's own framing: these are *general best practices, not hard and fast rules*.
> The engineer decides case by case. The pipeline therefore **applies** a practice
> where it can verify the result, and otherwise **reports** it for review. It never
> blocks a part over a practice.

Status key:

- ✅ **done:** applied automatically and verified in SolidWorks.
- 🔎 **reported:** shown to the reviewing engineer.
- 🗓 **planned:** see the spec's phases.

## 1. Modeling best practices

| # | MTI practice | Pipeline status |
|---|---|---|
| 1 | **Origin centered in all directions:** before cuts and holes, the base body is symmetric about the Front, Top and Right planes. | ✅ The IR compiler centers the base body on the origin and checks it (`origin_ok`). It replaces the old lower-left-corner origin (CLAUDE.md rule 3, updated). |
| 2 | **Base sketch on the Top plane** (body extruded along the Top normal). | ✅ The plan is rotated rigidly so that the base sketch lands on Top. The base extrusion is **Mid Plane** (prism bases). A revolved base has its profile on Top. |
| 3 | **All sketches fully defined;** relations are often better than dimensions. | ✅ Every sketch goes through SolidWorks' own **Fully Define Sketch**: exact relations only (horizontal, vertical, midpoint, coincident) plus regular dimensions. The status of each sketch is in the build report: **29/30 dev-set sketches fully defined** (2026-10-12). A Hole Wizard placement sketch may stay under-defined (reported). |
| 4 | **Uncluttered tree:** base body, then cut away holes and pockets. Fillets and chamfers go toward the end. | 🔎 `mti_edge_ops_last` flags a fillet or chamfer placed before other features. Plans already build the base first, then cut. |
| 5 | **Hole Wizard for every bolt hole;** non-bolt holes are cut-extrudes. | ✅ **Bolt holes are Hole Wizard features**: clearance and SHCS counterbore (screw from MTI Std 202.02.0003), and **tapped holes with a cosmetic thread** (from the thread callout). They use the drawing's exact diameters and are volume-verified, with a plain-cut fallback. Blind ones end in a 118° drill point that is credited exactly in the check. 🔎 `mti_hole_wizard` reports every hole. 🗓 Pipe taps (NPT). |
| 5a | Legacy prints rarely say "clearance for X bolt". The AI must map plain diameters to Hole Wizard sizes, inch or metric. | 🔎 Matching against the drawing's own system comes first. Other-system hardware must match its exact conversion. Holes with no match show the nearest standard size. |
| 5b | **Through holes are "Up To Next",** not "Through All". | ✅ Through cuts try Up To Next first and keep it when the volume matches the reference. Otherwise (a hole crossing a pocket) they fall back to Through All, and the fallback is logged. Hole Wizard counterbores are Up To Next too. |
| 5c | Hole Wizard holes come from a **2D sketch**. | ✅ All sketches are 2D. |
| 5d | **One Hole Wizard feature per hole size per face.** | ✅ Consecutive identical holes on one face are built as **one** feature (Hole Wizard or plain cut). 🔎 `mti_hole_grouping` flags the rest. |
| 5e | **Patterned holes sit on sketch geometry** (circle, rectangle, line), not on individually dimensioned points. | ✅ A hole and its pattern are **one** Hole Wizard feature whose points sit, with coincident relations, on a construction **bolt circle** (circular), **line** (linear) or **rectangle** (grid). Identical holes planned one by one get a circle or line when they form one. |
| 6 | **Use symmetry and mirror** (sketches, features, bodies). | 🗓 Phase 3: an IR `mirror` feature, plus symmetric sketch relations. |
| 7 | **Dimension features from model edges** (datum edges) rather than the origin, planes or holes. *Drawings show how to machine, not how to model.* | ✅ Fully Define uses the face's leftmost and lowest **model edges** as datums. Where SolidWorks can't (base-plane sketches), an anchor tied to the origin is used. The IR keeps *what* (drawing dimensions) apart from *how it is modeled* (the compiler). 🔎 Open question 5: the drawing's datums or a fixed MTI choice? |

## 2. Feature guide

**Very common (the pipeline should be able to produce these):**

| Feature | Status |
|---|---|
| Boss / cut extrude | ✅ IR `prism` (add/cut) |
| Revolved boss | ✅ IR `revolve` |
| Hole Wizard | ✅ clearance + counterbore (2026-10-11); 🗓 tapped |
| Fillets, chamfers | ✅ IR `edge_op` |
| Linear / circular patterns | ✅ IR `pattern` (hole patterns, linear/grid prism patterns) |
| Mirror (bodies, features) | 🗓 Phase 3 |
| Basic sketch shapes (circle, rectangle, line, point, arc, slot) | ✅ rect, circle, slot, polyline |
| Sheet metal: base flange/tab, edge flange, hem | 🗓 Phase 4 (no sheet-metal parts in the dev set yet) |
| Cosmetic threads | ✅ On every tapped Hole Wizard hole, never real threads; display turned on as in MTI's `ToggleCosmeticThreads` macro. |

**Generally avoid** (MTI's list): sweep, loft, boundary, shell, draft, weld beads, gussets, ribs, move face, move/copy bodies, sketch ellipse/polygon/text/spline/sketch fillets and chamfers, surfacing, and sheet-metal miter flange, jog, sketched bend, cross-break, corners and forming tools.

Real threads are also on the list; use cosmetic threads instead.

The pipeline's prohibited list (CLAUDE.md rule 7) already covers the solid-modeling items. The IR cannot express any of the others. `mti_avoid` keeps it that way as the IR grows.

## 3. MTI's macros: what they teach us

| Macro | What it does | What we took from it |
|---|---|---|
| `SelectPlane1/2/3` | Walks the feature tree (`FirstFeature`, `GetTypeName2 = "RefPlane"`, `GetNextFeature`) and selects the n-th reference plane. | ✅ `select_ref_plane()` (Python builders) falls back to the tree position when a plane name is not found (renamed or localized templates). The VBA generator already does this (`SelectRefPlane`). |
| `SelectPlaneNext` | Cycles the selection to the next plane. | UI helper; nothing to adopt. |
| `SelectFaces` | Interactive Shift-click face selection. | UI helper; nothing to adopt. |
| `ToggleCosmeticThreads` | Toggles `swDisplayCosmeticThreads` / `swDisplayShadedCosmeticThreads` via `Extension.Set/GetUserPreferenceToggle`. | 🗓 With Phase 2 cosmetic threads, turn shaded display on so reviewers see them. |

## 4. MTI Standard 202.02.0003 (tap and hole specifications)

This standard is **proprietary and confidential**, so it is **not in the repository**.

- **Local copy.** A transcription lives at `2D-3D-CAD-Test-Generation/config/mti/202.02.0003.local.json`. It is gitignored, and a test checks that it stays ignored. See [config/mti/README.md](../../2D-3D-CAD-Test-Generation/config/mti/README.md).
- **Who uses it.** Only deterministic local code reads it: `pipeline/mti_standards.py`, the counterbore fallback in `run_models.py`, and the MTI review. It is never put into a model prompt; the planner still sees only the generic SHCS chart.
- **Contents.** Inch rows #6 to 1-1/2, and metric rows M3 to M48. Columns: pitch, preferred, hex key, tap drill, standard tap depth, clearance (normal and loose), FHCS countersink, counterbore diameter and depth, SHCS countersink.
- **Where MTI differs from the generic chart.** MTI's SHCS counterbores are **deeper** than the generic "depth = nominal" rule (the values stay in the local file). When the local table is present, MTI's values win; a depth printed on the drawing still wins over both.
- **Verification status:** ⚠ UNVERIFIED. The values were transcribed from a 385×727 px screenshot. Before production use, check them against the source document, or replace the file with an export of it.
