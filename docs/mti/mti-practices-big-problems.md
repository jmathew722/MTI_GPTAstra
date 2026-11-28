# MTI best practices the pipeline breaks by design ("real big problems")

**Started:** 2026-10-25. **Source:** MTI's best-practices notes (in the MTI dataset folder, outside git;
summarised here, not copied) and a code audit of the Feature-IR pipeline on `feat/mti-benchmark`.

**User rule:** a practice the pipeline violates systematically is not a scoring detail. It is excluded from the
practices score ([spec 2b](../superpowers/specs/2026-10-25-practices-score-design.md)) and fixed in the pipeline.
Each entry gives the practice, what the pipeline does, the cause, and a fix sketch. `cs` is
`2D-3D-CAD-Test-Generation/pipeline/ir/compile_solidworks.py`; line numbers are as of 2026-10-25.

## 1. Features are located from planes and the origin, not model edges (P12)

- **MTI:** dimension for future edits by locating features from model edges, reusing datum edges, with regular
  (not ordinate) dimensions. The drawing's dimensioning shows how to *machine* the part and shouldn't be
  copied into the model.
- **Pipeline:**
  - Every prism, plain hole and revolve is sketched on a **base reference plane**, with an offset start
    (`sketch_on` → `select_plane`, cs:235-240; `t0=3`, cs:383).
  - Because a base-plane sketch can't reference model edges (error log E023), Fully Define anchors it **to the
    origin** (cs:279-284).
  - Only Hole Wizard placement sketches sit on faces and use model-edge datums (cs:324-362).
- **Cause:** CLAUDE.md hard rule 3 (one drawing frame, edge-referenced like the drawing) and the IR rule "one
  part frame; global coordinates; no per-face local sketch frames".
- **Fix sketch:**
  - Keep the IR global.
  - In the compiler, open each non-base sketch on its actual start face. Ray-select the face, as
    `hole_wizard` already does at cs:584, and use a From Sketch Plane start.
  - Dimension from that face's model edges.
  - The choice of datum edges is still an open question (docs/mti/mti-modeling-standards.md, Q5).

## 2. Through cuts are not "Up To Next" (P7)

- **MTI:** a through hole is "Up To Next", not "Through All".
- **Pipeline:**
  - `thru_cut` tries Up To Next first, then falls back to Through All (cs:395-412).
  - But the planner prompt's "CUTS MUST OVERSHOOT" rule (planner.py:86-90) makes many break-through cuts
    **Blind with an oversize depth**, built as Blind (cs:482).
  - CLAUDE.md hard rule 5 ("ThroughAllBoth") is the old v1 rule and is out of date for the IR path.
- **Fix sketch:**
  - The planner emits `depth: "thru"` for break-through cuts, or the compiler turns a Blind cut that exits
    the body (checked against the CadQuery reference) into Up To Next.
  - Reword rule 5 for the IR path.

## 3. No pattern features; prism copies are separate extrudes (P10, P4)

- **MTI:** patterned holes sit on construction geometry (circle, line, rectangle) and use pattern tools. Keep
  the feature tree lean.
- **Pipeline:**
  - Hole Wizard holes do sit on construction geometry (cs:620-718).
  - But the IR path never makes a SolidWorks pattern feature: a prism pattern becomes **one extrude per copy**
    (`prism_pattern`, cs:752-775).
  - The plain-cut hole fallback draws bare circles with no layout geometry (cs:514-519).
- **Fix sketch:**
  - Compile `pattern` to `FeatureLinearPattern` or a circular pattern on the seed feature. The verified v1
    recipe is in `solidworks_builder.py:909-932`.
  - Draw layout geometry in the plain-cut fallback too.

## 4. No mirror (P11)

- **MTI:** use symmetry and mirror (sketches, features, bodies) where reasonable.
- **Pipeline:** the IR has no mirror kind (`pipeline/ir/model.py:351`, prism/revolve/hole/pattern/edge_op).
  Symmetry shows up only as centered values, the centered base rectangle and midpoint relations.
- **Fix sketch:** an IR `mirror` feature (Phase 3 in the IR spec), plus symmetric sketch relations.

## 5. Hole Wizard doesn't cover every bolt hole (P5)

- **MTI:** use Hole Wizard for every bolt hole, and a regular cut for non-bolt holes.
- **Pipeline:**
  - **Countersinks never use Hole Wizard** (cs:928; `from_v1.py:192` marks them unresolved).
  - Clearance-hole Hole Wizard depends on a git-ignored local table, `202.02.0003.local.json`
    (`mti_standards.py:85-87`). Without it, only tapped holes get Hole Wizard, and nothing says so.
    *2026-10-26:* the source is `Bolt Hole Standards.png` in MTI's best-practices folder. It was re-transcribed
    into the local file on this machine, so it is present now. The silent fallback remains.
- **Fix sketch:**
  - Add a countersink Hole Wizard type.
  - Make benchmark runs fail loudly when the MTI hole table is missing.

## Smaller systematic gaps (scored, but worth fixing)

- **Fillets and chamfers stay in plan order;** they are flagged (`mti_edge_ops_last`), never moved to the end.
  This is scored as practice C4.
- **Identical holes merge into one Hole Wizard feature only when they are adjacent in the plan** (cs:1018-1029).
  This is scored as practice C6.
