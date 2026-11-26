"""Geometry and feature inventory of a native part: B-rep faces -> holes, bores, patterns, outline.

Two layers: ``read_brep`` (SOLIDWORKS COM) turns the exact B-rep into plain dicts; the clustering functions below are pure geometry and are unit
tested without SOLIDWORKS.  The inventory never infers manufacturing intent: it reports what the geometry is (a cylinder of this radius along this
axis, through or blind), marks uncertainty, and leaves tolerance / thread / datum intent to the engineering review.
"""
from __future__ import annotations

import math
from typing import Optional

TOL = 1e-6                # metres: 1 micrometre geometry tolerance
AXIS_TOL = 1e-4           # direction cosine tolerance
AXES = ("x", "y", "z")


def _norm(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / n for c in v]


def axis_name(a) -> Optional[str]:
    """'x' | 'y' | 'z' when the (unit) direction is a principal axis, else None."""
    a = _norm(a)
    for i, nm in enumerate(AXES):
        if abs(abs(a[i]) - 1.0) < AXIS_TOL:
            return nm
    return None


# ---------------------------------------------------------------- SOLIDWORKS B-rep reader

def read_brep(session, doc) -> dict:
    """{"bbox_m":[x0,y0,z0,x1,y1,z1], "bodies":n, "cylinders":[...], "cones":[...], "planes":[...], "others":n} in metres."""
    T = session.typed
    bodies = T(doc, "IPartDoc").GetBodies2(0, False) or ()
    out: dict = {"bodies": len(bodies), "cylinders": [], "cones": [], "planes": [], "tori": 0, "others": 0, "bbox_m": session.body_box(doc)}
    for bi, body in enumerate(bodies):
        for fi, f in enumerate(T(body, "IBody2").GetFaces() or ()):
            tf = T(f, "IFace2")
            surf = T(tf.GetSurface(), "ISurface")
            box = [float(v) for v in tf.GetBox()]
            area = float(tf.GetArea())
            rev = bool(tf.FaceInSurfaceSense())
            rec = {"body": bi, "face": fi, "box_m": box, "area_m2": area, "edges": len(tf.GetEdges() or ())}
            if surf.IsPlane():
                p = [float(v) for v in surf.PlaneParams]
                # PlaneParams = (nx,ny,nz, px,py,pz) of the SURFACE; the face normal is reversed when the sense flag is set
                n = [-c for c in p[:3]] if rev else p[:3]
                rec.update(normal=n, point=p[3:6])
                out["planes"].append(rec)
            elif surf.IsCylinder():
                cp = [float(v) for v in surf.CylinderParams]
                rec.update(origin=cp[0:3], axis=_norm(cp[3:6]), radius=cp[6], concave=rev)   # reversed sense => face normal points at the axis => a hole
                out["cylinders"].append(rec)
            elif surf.IsCone():
                cp = [float(v) for v in surf.ConeParams]
                rec.update(origin=cp[0:3], axis=_norm(cp[3:6]), radius=cp[6], half_angle=cp[7] if len(cp) > 7 else None, concave=rev)
                out["cones"].append(rec)
            elif surf.IsTorus():
                out["tori"] += 1
            else:
                out["others"] += 1
    return out


# ---------------------------------------------------------------- pure geometry

def axial_interval(cyl: dict) -> tuple[float, float]:
    """The cylinder's extent along its own axis (metres, in absolute model coordinates along the principal axis)."""
    nm = axis_name(cyl["axis"])
    if nm is None:
        return (0.0, 0.0)
    i = AXES.index(nm)
    return (cyl["box_m"][i], cyl["box_m"][i + 3])


def _line_key(cyl: dict) -> Optional[tuple]:
    """Identity of the axis LINE for a principal-axis cylinder: (axis, the two perpendicular coordinates rounded to 10 micrometres)."""
    nm = axis_name(cyl["axis"])
    if nm is None:
        return None
    i = AXES.index(nm)
    perp = [cyl["origin"][j] for j in range(3) if j != i]
    return (nm, round(perp[0] / 1e-5), round(perp[1] / 1e-5))


def cluster_holes(brep: dict) -> dict:
    """Group concave cylinders that share an axis line into hole stacks; classify through / blind and counterbore steps.

    Returns {"holes":[...], "bosses":[...], "unsupported":[...]}.  Each hole: id, axis, center_m (the two perpendicular coords + the axis name),
    steps [{radius, d0, d1}] ordered from the entry face inward, diameter (smallest), counterbore (largest step > smallest), depth, through,
    entry_side ('+'|'-'), cone (drill point / countersink seen), confidence."""
    bbox = brep.get("bbox_m")
    groups: dict[tuple, list[dict]] = {}
    unsupported: list[dict] = []
    bosses: list[dict] = []
    for c in brep.get("cylinders", []):
        key = _line_key(c)
        if key is None:
            unsupported.append({"kind": "cylinder_off_axis", "face": c["face"], "radius_m": c["radius"], "note": "axis is not a principal axis; semantics need review"})
            continue
        if not c["concave"]:
            bosses.append({"axis": key[0], "radius_m": c["radius"], "box_m": c["box_m"], "face": c["face"]})
            continue
        groups.setdefault(key, []).append(c)
    cones_by_line: dict[tuple, list[dict]] = {}
    for k in brep.get("cones", []):
        key = _line_key(k)
        if key is not None:
            cones_by_line.setdefault(key, []).append(k)
    holes = []
    for gi, (key, cyls) in enumerate(sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][1]))):
        nm = key[0]
        i = AXES.index(nm)
        ivs = sorted(((*axial_interval(c), c["radius"]) for c in cyls), key=lambda t: t[0])
        lo, hi = ivs[0][0], max(t[1] for t in ivs)
        # split a stack that is really two separate holes on the same line (a gap between intervals)
        segs: list[list[tuple]] = []
        for iv in ivs:
            if segs and iv[0] - max(t[1] for t in segs[-1]) > 1e-4:
                segs.append([iv])
            else:
                if not segs:
                    segs.append([])
                segs[-1].append(iv)
        for si, seg in enumerate(segs):
            slo, shi = min(t[0] for t in seg), max(t[1] for t in seg)
            perp_idx = [j for j in range(3) if j != i]
            c0 = cyls[0]
            center = [c0["origin"][j] for j in perp_idx]
            ext_lo, ext_hi = (bbox[i], bbox[i + 3]) if bbox else (slo, shi)
            touches_lo, touches_hi = abs(slo - ext_lo) < 1e-4, abs(shi - ext_hi) < 1e-4
            through = touches_lo and touches_hi
            entry = "-" if touches_lo and not touches_hi else "+" if touches_hi and not touches_lo else ("both" if through else "?")
            ordered = sorted(seg, key=lambda t: (t[0] if entry in ("-", "both", "?") else -t[1]))
            steps = [{"radius_m": s[2], "d0_m": s[0], "d1_m": s[1], "length_m": s[1] - s[0]} for s in ordered]
            radii = sorted({round(s["radius_m"], 7) for s in steps})
            small = min(radii)
            line_cones = [k for k in cones_by_line.get(key, []) if slo - 1e-4 <= k["box_m"][i] and k["box_m"][i + 3] <= shi + 1e-4 or
                          (slo - 5e-3 <= k["box_m"][i] <= shi + 5e-3)]
            hole = {"id": f"H{len(holes) + 1:03d}", "axis": nm, "center_m": center, "center_axes": [AXES[j] for j in perp_idx], "steps": steps,
                    "diameter_m": 2 * small, "through": through, "entry_side": entry, "depth_m": (shi - slo) if not through else (ext_hi - ext_lo),
                    "counterbore": ({"diameter_m": 2 * max(radii), "depth_m": max(s["length_m"] for s in steps if abs(s["radius_m"] - max(radii)) < 1e-7)}
                                    if len(radii) > 1 else None),
                    "cone": bool(line_cones), "faces": [c["face"] for c in cyls], "confidence": "high" if (touches_lo or touches_hi) else "medium",
                    "source": "geometry_derived"}
            holes.append(hole)
    return {"holes": holes, "bosses": bosses, "unsupported": unsupported}


def hole_patterns(holes: list[dict], tol: float = 5e-5) -> list[dict]:
    """Group identical holes (same axis, diameter, depth class) and detect rectangular grids. A pattern needs >= 2 holes; positions are given as the
    sorted distinct coordinates in each of the two perpendicular axes (so spacing is dimensioned once per direction, never per hole)."""
    sig: dict[tuple, list[dict]] = {}
    for h in holes:
        sig.setdefault((h["axis"], round(h["diameter_m"], 6), bool(h["through"]), round(h["depth_m"], 5), bool(h.get("counterbore"))), []).append(h)
    out = []
    for k, hs in sig.items():
        if len(hs) < 2:
            continue
        u = sorted({round(h["center_m"][0] / tol) * tol for h in hs})
        v = sorted({round(h["center_m"][1] / tol) * tol for h in hs})
        grid = len(u) * len(v) == len(hs)
        out.append({"ids": [h["id"] for h in hs], "count": len(hs), "axis": k[0], "diameter_m": k[1], "axes": hs[0]["center_axes"], "u_m": u, "v_m": v,
                    "rectangular_grid": grid, "u_pitch_m": (u[1] - u[0]) if len(u) > 1 else None, "v_pitch_m": (v[1] - v[0]) if len(v) > 1 else None,
                    "uniform_u": all(abs((u[j + 1] - u[j]) - (u[1] - u[0])) < tol * 4 for j in range(len(u) - 1)) if len(u) > 1 else True,
                    "uniform_v": all(abs((v[j + 1] - v[j]) - (v[1] - v[0])) < tol * 4 for j in range(len(v) - 1)) if len(v) > 1 else True})
    return out


def circular_patterns(holes: list[dict], tol: float = 1e-4) -> list[dict]:
    """Identical holes equidistant from one centre (a bolt circle). Needs >= 3 holes. Reports the pitch-circle diameter, whether the spacing is equal,
    and the opposite pairs (the pair across the centre is what a pitch-circle diameter is dimensioned between)."""
    import math as _m
    sig: dict[tuple, list[dict]] = {}
    for h in holes:
        sig.setdefault((h["axis"], round(h["diameter_m"], 6), bool(h["through"]), round(h["depth_m"], 5), bool(h.get("counterbore"))), []).append(h)
    out = []
    for k, hs in sig.items():
        if len(hs) < 3:
            continue
        cx = sum(h["center_m"][0] for h in hs) / len(hs)
        cy = sum(h["center_m"][1] for h in hs) / len(hs)
        rs = [_m.hypot(h["center_m"][0] - cx, h["center_m"][1] - cy) for h in hs]
        if min(rs) < 1e-4 or max(rs) - min(rs) > tol:
            continue
        ang = sorted(((_m.degrees(_m.atan2(h["center_m"][1] - cy, h["center_m"][0] - cx)) % 360.0), h["id"]) for h in hs)
        step = 360.0 / len(hs)
        diffs = [(ang[(i + 1) % len(ang)][0] - ang[i][0]) % 360.0 for i in range(len(ang))]
        equal = all(abs(d - step) < 0.05 for d in diffs)
        opp = []
        for a in hs:
            for b in hs:
                if a["id"] < b["id"] and abs((a["center_m"][0] + b["center_m"][0]) / 2 - cx) < tol and abs((a["center_m"][1] + b["center_m"][1]) / 2 - cy) < tol:
                    opp.append((a["id"], b["id"]))
        out.append({"ids": [h["id"] for h in hs], "count": len(hs), "axis": k[0], "diameter_m": k[1], "axes": hs[0]["center_axes"], "center_m": [cx, cy],
                    "pcd_m": 2 * sum(rs) / len(rs), "equal_spacing": equal, "angles_deg": [round(a, 3) for a, _ in ang], "opposite_pairs": opp})
    return out


def hole_axis_counts(holes: list[dict]) -> dict:
    d = {"x": 0, "y": 0, "z": 0}
    for h in holes:
        d[h["axis"]] += 1
    return d


def build_inventory(session, doc, config: str = "") -> dict:
    """The full inventory record written to ``inventory.json`` (SOLIDWORKS-dependent only through read_brep and the feature walk)."""
    T = session.typed
    brep = read_brep(session, doc)
    cl = cluster_holes(brep)
    feats = []
    f = doc.FirstFeature()
    skip = {"HistoryFolder", "SensorFolder", "DocsFolder", "DetailCabinet", "SurfaceBodyFolder", "SolidBodyFolder", "CommentsFolder", "FavoriteFolder",
            "SelectionSetFolder", "EqnFolder", "MaterialFolder", "RefPlane", "OriginProfileFeature", "MateReferenceGroupFolder", "InkMarkupFolder",
            "LiveSectionFolder", "MarkupCommentFolder", "BlockFolder", "EnvFolder", "RefAxis", "RefPoint", "AttributeFeature"}
    while f is not None:
        tf = T(f, "IFeature")
        tn = str(tf.GetTypeName2())
        if tn not in skip:
            try:
                suppressed = bool(tf.IsSuppressed2(1, [config or session.active_configuration(doc)])[0]) if False else bool(tf.IsSuppressed())
            except Exception:      # noqa: BLE001
                suppressed = False
            feats.append({"name": str(tf.Name), "type": tn, "suppressed": suppressed})
        f = tf.GetNextFeature()
    bbox = brep["bbox_m"]
    inv = {"configuration": config or session.active_configuration(doc), "bodies": brep["bodies"], "bbox_m": list(bbox) if bbox else None,
           "size_m": [bbox[i + 3] - bbox[i] for i in range(3)] if bbox else None, "features": [x for x in feats if not x["suppressed"]],
           "suppressed_features": [x["name"] for x in feats if x["suppressed"]], "faces": {"planes": len(brep["planes"]), "cylinders": len(brep["cylinders"]),
                                                                                       "cones": len(brep["cones"]), "tori": brep["tori"], "other": brep["others"]},
           "holes": cl["holes"], "bosses": cl["bosses"], "unsupported": cl["unsupported"], "patterns": hole_patterns(cl["holes"]),
           "circular_patterns": circular_patterns(cl["holes"]),
           "hole_axes": hole_axis_counts(cl["holes"]), "planes": [{"normal": p["normal"], "point": p["point"], "area_m2": p["area_m2"], "box_m": p["box_m"]}
                                                                   for p in brep["planes"]]}
    inv["freeform_or_multibody"] = brep["bodies"] > 1 or brep["others"] > 0
    inv["notes"] = []
    if brep["bodies"] > 1:
        inv["notes"].append(f"{brep['bodies']} solid bodies: body selection and interfaces need engineering review.")
    if brep["others"]:
        inv["notes"].append(f"{brep['others']} faces are neither planar nor simple revolved surfaces; freeform geometry cannot be fully dimensioned automatically.")
    return inv
