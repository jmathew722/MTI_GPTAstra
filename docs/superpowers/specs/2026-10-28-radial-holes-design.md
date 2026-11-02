# Radial holes: holes drilled into the outside of a turned part

**Date:** 2026-10-28 · **Status:** implemented with this spec (review on PR #6) · **Owner:** ggould + Claude Code

## Problem

Turned parts often have holes drilled **radially**, into the outside diameter toward the axis:

- SB12059 has four ".375-24 TAP .38 DEEP" at 45°;
- SB12095 has three "#8-36 TAP THRU (1) WALL";
- SB12054 has ".500-13 TAP THRU";
- 2N2664 has a radial cross-hole at 30°.

The planner already writes these consistently as `hole` with `on: "wall(F001, <radius>)"`, `v` = the
axial station, and `u` = "0", followed by a circular pattern. But:

- the IR has no angle for them (2N2664 F021: "this IR lacks angular placement");
- neither compiler can start a hole on a wall ("wall(...) can't be a start ref"), so every one is
  skipped.

## IR (no schema change)

A `hole` whose `on` is `wall(F, r)` (radius required) is **radial**:

| Field | Meaning for a radial hole |
|---|---|
| `on` | `wall(F, r)`: start on the cylinder of radius `r` of feature F |
| `u` | **angle in degrees** about the part axis, from +X toward +Y (a literal angle is allowed, like counts) |
| `v` | axial station z (frame `axis_end`, z = 0 at the end face) |
| `spec.depth` | radial depth inward from the surface; `null`/`thru` is through the whole diameter; "THRU (1) WALL" is the wall thickness |
| `spec.d`, `type`, `thread` | as for any hole (threads cosmetic) |

The frame must be `axis_end`, with the part axis along +Z. A circular `pattern` about `axis(part)`
repeats a radial seed as usual.

## CadQuery reference (`cq_runtime.hole`)

- Drill direction n = −(cos u, sin u, 0).
- The tool is a cylinder of diameter d from radius r + overshoot down to r − depth, or through the
  whole part for thru, at height z = v.
- Radial holes are not added to the axis-aligned hole measurement (`measure_holes` assumes X/Y/Z
  holes); they are verified by volume like every feature.
- `starts[fid]` records `{"radial": true, ...}` for the SolidWorks compiler.

## SolidWorks (`compile_solidworks._SW.radial_hole`)

Volume alone can't verify a radial hole on a turned body: the same hole at the wrong angle, or
mirrored, removes exactly the same volume. So the geometry is made unambiguous instead of checked
afterwards:

1. On the base plane normal to the part axis, draw a construction line from the axis to the point
   P = (R + m)·(cos u, sin u) just **outside** the part. The coordinates are explicit and read back
   (E020–E022).
2. `InsertRefPlane`: perpendicular to that line (`swRefPlaneReferenceConstraint_Perpendicular` = 2),
   through its end point P (`Coincident` = 4). This was verified in `sldworks.tlb` and
   `swconst.tlb`. The plane is tangent-parallel to the hole start and lies outside the part.
3. Sketch the hole circle on that plane at the point P + z·v, mapped with
   `ISketch.ModelToSketchTransform`.
4. Blind cut from the plane, depth m + radial depth (or m + 2R for thru), **one direction**. A
   cut aimed away from the part removes nothing, so the volume check catches the wrong direction,
   and flip-and-retry fixes it (E005).

Notes:

- The holes are plain cut-extrudes. A Hole Wizard on a non-planar face needs a 3D placement sketch;
  that is a follow-up (MTI uses `HoleWzd` for these).
- A pattern of a radial seed is a native `FeatureCircularPattern5` about the part axis (E028).
- Radial holes never join the face-hole grouping (`mergeable_holes`).

## Planner prompt

One line under REFS/FEATURES: radial holes start on `wall(F###, r)`, with `u` = the angle in
degrees from +X about the part axis and `v` = z. The callout-defaults guard (E031) now allows
`wall(F, r)` starts.

## Tests and validation

- Reference unit tests:
  - a radial blind hole and a through hole on a tube, checked by point containment at the angle
    (and not at the mirror angle);
  - a 4× circular pattern at 45°.
- SolidWorks routing unit tests (mocked).
- Live, $0: a golden synthetic plan with radial holes at 45° built in SolidWorks and checked per
  feature.
- Saved SB12095 plan rebuilt from saved plans.
