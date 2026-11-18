"""Hole placement policy (Stage 4, task 4.8): pure geometry, no SolidWorks.

Planar holes sit on a face and drill along the into-material normal. Radial holes sit on a cylindrical face and drill
toward its axis. Both are validated BEFORE anything is created: every point must be inside the face, holes must not
overlap, and a hole (with its largest treatment) must not run off the face edge. A violation is returned as a structured
``PlacementIssue``; it is never silently adjusted (CLAUDE.md rule 6: never invent positions).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

Vec = tuple


@dataclass
class PlacementIssue:
    code: str
    detail: str
    index: Optional[int] = None


def radial_point(axis: str, radius: float, angle_deg: float, z: float) -> tuple[Vec, Vec]:
    """Start point on a cylinder of ``radius`` about ``axis`` (X|Y|Z) at ``angle_deg`` (counter-clockwise looking down the
    +axis, 0 deg = the first perpendicular axis in cyclic order) and axial position ``z``; plus the into-material
    direction (toward the axis)."""
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    if axis == "Z":
        p, d = (radius * c, radius * s, z), (-c, -s, 0.0)
    elif axis == "X":
        p, d = (z, radius * c, radius * s), (0.0, -c, -s)
    elif axis == "Y":
        p, d = (radius * s, z, radius * c), (-s, 0.0, -c)
    else:
        raise ValueError(f"axis must be X, Y or Z, got {axis!r}")
    return p, d


def check_planar(points: list, face_min: tuple, face_max: tuple, diameter: float, treatment_d: float = 0.0,
                 margin: float = 0.0) -> list:
    """``points`` are (u, v) in the face's own coordinates; ``face_min/max`` its rectangle. A hole needs
    ``max(diameter, treatment_d)/2 + margin`` of material to every edge and ``max(...)`` between centers."""
    r = max(diameter, treatment_d) / 2 + margin
    issues = []
    for i, (u, v) in enumerate(points):
        if not (face_min[0] <= u <= face_max[0] and face_min[1] <= v <= face_max[1]):
            issues.append(PlacementIssue("HW_POINT_OFF_FACE", f"point {i} ({u:g}, {v:g}) is outside the face", i))
        elif u - r < face_min[0] or u + r > face_max[0] or v - r < face_min[1] or v + r > face_max[1]:
            issues.append(PlacementIssue("HW_HOLE_BREAKS_EDGE", f"hole {i} would run off the face edge", i))
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            if math.dist(points[i], points[j]) < 2 * r - 1e-12:
                issues.append(PlacementIssue("HW_HOLES_OVERLAP", f"holes {i} and {j} overlap", i))
    return issues


def check_radial(angles_deg: list, z_values: list, radius: float, length: float, diameter: float) -> list:
    """Radial holes on a cylinder of ``radius`` and axial ``length`` (z in [0, length])."""
    issues = []
    r = diameter / 2
    for i, z in enumerate(z_values):
        if z - r < 0 or z + r > length:
            issues.append(PlacementIssue("HW_HOLE_BREAKS_EDGE", f"radial hole {i} at z={z:g} crosses the cylinder end", i))
    pts = [(radius * math.radians(a), z) for a, z in zip(angles_deg, z_values)]   # arc length, axial
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if math.dist(pts[i], pts[j]) < diameter - 1e-12:
                issues.append(PlacementIssue("HW_HOLES_OVERLAP", f"radial holes {i} and {j} overlap", i))
    return issues


def policy_for(face_kind: str) -> str:
    """``planar`` -> normal drilling; ``cylindrical`` -> radial; anything else is refused, not guessed."""
    if face_kind in ("planar", "plane"):
        return "planar"
    if face_kind in ("cylindrical", "cylinder"):
        return "radial"
    return "unsupported"
