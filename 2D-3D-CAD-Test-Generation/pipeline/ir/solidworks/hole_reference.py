"""CadQuery reference geometry for Hole Wizard families (Stage 4, task 4.9).

Builds the CUTTER a hole removes, in a local frame (start face at z=0, drilling toward -z) for any intent, and an
analytic volume for it so tests can check the geometry independently. The volume of a cosmetic-thread tap equals its tap
drill's (a cosmetic thread removes no material). A blind hole ends in a 118 deg drill point (Hole Wizard behavior,
E022); a through hole does not. Countersinks are cones; counterbores cylinders; slots are obrounds.
"""
from __future__ import annotations

import math

from pipeline.ir.solidworks.hole_intent import HoleIntent

DRILL_POINT_DEG = 118.0


class ReferenceUnsupported(ValueError):
    """The family's reference geometry is not modeled (never approximated): counterbore and countersink SLOTS, whose
    treatment outline (obround vs round) the available documentation does not define."""


def _guard(intent: HoleIntent) -> None:
    if intent.family in ("counterbore_slot", "countersink_slot"):
        raise ReferenceUnsupported(f"{intent.family}: treatment outline is not defined; no reference geometry")


def _cone_frustum_volume(r1: float, r2: float, h: float) -> float:
    return math.pi * h * (r1 * r1 + r1 * r2 + r2 * r2) / 3


def _drill_point_vol(d: float) -> float:
    r = d / 2
    return math.pi * r * r * (r / math.tan(math.radians(DRILL_POINT_DEG / 2))) / 3


def bore_diameter(intent: HoleIntent, tap_drill: float | None = None) -> float | None:
    if intent.family in ("straight_tap", "pipe_tap"):
        return tap_drill
    if intent.family in ("slot", "counterbore_slot", "countersink_slot"):
        return intent.slot_width
    return intent.diameter


def analytic_volume(intent: HoleIntent, thickness: float, tap_drill: float | None = None) -> float:
    """Removed volume for ONE hole through a plate of ``thickness`` (blind: ``intent.depth`` or the drill/thread depth).
    Slots add a rectangle of ``slot_length - width`` between two half-round ends. Treatments are cones whose depth follows
    from diameter and included angle."""
    _guard(intent)
    d = bore_diameter(intent, tap_drill)
    if d is None:
        raise ValueError("no bore diameter")
    r = d / 2
    blind = intent.end == "blind"
    depth = (intent.depth or intent.drill_depth or intent.thread_depth) if blind else thickness
    if depth is None:
        raise ValueError("blind hole without a depth")
    slot = intent.family in ("slot", "counterbore_slot", "countersink_slot")
    if slot:
        w = intent.slot_width or d
        straight = max((intent.slot_length or w) - w, 0.0)
        area = math.pi * (w / 2) ** 2 + w * straight
        vol = area * depth
        r = w / 2
    else:
        vol = math.pi * r * r * depth
    if blind and not slot:
        vol += _drill_point_vol(d)
    if intent.family in ("counterbore", "counterbore_slot") and intent.cbore_diameter and intent.cbore_depth:
        rc = intent.cbore_diameter / 2
        vol += math.pi * (rc * rc - r * r) * intent.cbore_depth * (1.0 if not slot else 1.0)
    cs_list = []
    if intent.family in ("countersink", "countersink_slot") and intent.csink_diameter:
        cs_list.append((intent.csink_diameter, intent.csink_angle or 90.0))
    cs_list += [(t["diameter"], t["angle"]) for t in intent.treatments.values() if t.get("diameter") and t.get("angle")]
    for dia, ang in cs_list:
        if dia <= 2 * r:
            continue
        h = (dia / 2 - r) / math.tan(math.radians(ang / 2))
        vol += _cone_frustum_volume(dia / 2, r, h) - math.pi * r * r * h
    return vol


def cutter(intent: HoleIntent, thickness: float, tap_drill: float | None = None):
    """A cadquery solid: the removed material of one hole, start face at z=0, material toward -z."""
    import cadquery as cq
    _guard(intent)
    d = bore_diameter(intent, tap_drill)
    if d is None:
        raise ValueError("no bore diameter")
    blind = intent.end == "blind"
    depth = (intent.depth or intent.drill_depth or intent.thread_depth) if blind else thickness
    if depth is None:
        raise ValueError("blind hole without a depth")
    slot = intent.family in ("slot", "counterbore_slot", "countersink_slot")
    wp = cq.Workplane("XY")
    if slot:
        w = intent.slot_width or d
        body = wp.slot2D(max(intent.slot_length or w, w), w).extrude(-depth)
    else:
        body = wp.circle(d / 2).extrude(-depth)
        if blind:
            tip = (d / 2) / math.tan(math.radians(DRILL_POINT_DEG / 2))
            cone = cq.Solid.makeCone(d / 2, 0.0, tip, cq.Vector(0, 0, -depth), cq.Vector(0, 0, -1))
            body = body.union(cq.Workplane("XY").add(cone))
    if intent.family in ("counterbore", "counterbore_slot") and intent.cbore_diameter and intent.cbore_depth:
        body = body.union(cq.Workplane("XY").circle(intent.cbore_diameter / 2).extrude(-intent.cbore_depth))
    cs_list = []
    if intent.family in ("countersink", "countersink_slot") and intent.csink_diameter:
        cs_list.append((intent.csink_diameter, intent.csink_angle or 90.0))
    for dia, ang in cs_list:
        h = (dia / 2 - d / 2) / math.tan(math.radians(ang / 2))
        cone = cq.Solid.makeCone(dia / 2, d / 2, h, cq.Vector(0, 0, 0), cq.Vector(0, 0, -1))
        body = body.union(cq.Workplane("XY").add(cone))
    return body
