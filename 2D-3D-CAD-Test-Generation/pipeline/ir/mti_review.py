"""MTI modeling-practice review of a BuildPlan (docs/mti-modeling-standards.md).

Deterministic and advisory: findings are ``info`` / ``warning`` (codes ``mti_*``) for
the reviewing engineer and never block a build. MTI's practices are "general best
practices, not hard and fast rules" (Logan Foerch), so the engineer decides.

Messages name screws and roles but never print a value from the table: reports are
committed, and the table is confidential.

Checks:

* ``mti_hole_wizard``: each hole's diameter against MTI Std 202.02.0003 (local table):
  a match means a bolt hole -> Hole Wizard for that screw; no match means a plain
  cut-extrude hole. Skipped when the local table is absent.
* ``mti_hole_grouping``: identical holes on the same face should be ONE Hole Wizard
  feature (two identical M8 tapped-hole features on one face is a smell).
* ``mti_edge_ops_last``: fillets and chamfers belong at the end of the feature tree.
* ``mti_avoid``: features MTI's feature guide says to avoid (none can be planned in IR
  v2 today; the check keeps it that way as the IR grows).
"""
from __future__ import annotations

from collections import defaultdict

from pipeline import mti_standards
from pipeline.ir.expr import evaluate
from pipeline.ir.model import BuildPlan, EdgeOp, Finding, Hole, Pattern

AVOID_KINDS = {"sweep", "loft", "boundary", "shell", "draft", "rib", "gusset", "weld_bead",
               "move_face", "move_copy_body", "surface", "thread"}


def _n(e, dims):
    return evaluate(e, dims).value


def review(plan: BuildPlan, dims: dict[str, float]) -> list[Finding]:
    out: list[Finding] = []
    units = plan.frame.units
    planned = [f for f in plan.features if f.status == "planned"]
    counts = {f.seed: f for f in planned if isinstance(f, Pattern)}

    # --- Hole Wizard candidates and grouping ---------------------------------
    groups: dict[tuple, list[str]] = defaultdict(list)
    for f in planned:
        if not isinstance(f, Hole):
            continue
        try:
            d = _n(f.spec.d, dims)
        except Exception:
            continue
        groups[(f.on.replace(" ", ""), f.spec.type, round(d, 6),
                f.spec.cbore_d and round(_n(f.spec.cbore_d, dims), 6))].append(f.id)
        if not mti_standards.available():
            continue
        tapped = f.spec.type == "tapped" or bool(f.spec.thread)
        m = mti_standards.match_hole(d, units, ("tap_drill",) if tapped else mti_standards.ROLES)
        where = f"{f.id}" + (f" (+ pattern {counts[f.id].id})" if f.id in counts else "")
        if m:
            best = m[0]
            msg = (f"{where}: Ø{d:g} = {best.note} -> Hole Wizard "
                   f"({'preferred size' if best.preferred else 'non-preferred size'})")
            if f.spec.type == "cbore" and f.spec.cbore_d:
                r = mti_standards.row(best.size) or {}
                cb = _n(f.spec.cbore_d, dims)
                if r.get("cbore_d") is not None:
                    same = abs(cb - r["cbore_d"]) <= mti_standards.TOL[units]
                    msg += f"; counterbore Ø{cb:g} {'matches' if same else 'DIFFERS from'} the standard counterbore"
            if len(m) > 1:
                msg += f"; also matches {', '.join(f'{x.size} {x.role}' for x in m[1:3])}"
            out.append(Finding(severity="info", code="mti_hole_wizard", feature=f.id, message=msg))
        else:
            near = mti_standards.nearest(d, units)
            hint = (f" (close to {near.size} {near.role}: engineer check)"
                    if near and near.error <= 4 * mti_standards.TOL[units] else "")
            out.append(Finding(severity="info", code="mti_hole_wizard", feature=f.id,
                               message=f"{where}: Ø{d:g} matches no {mti_standards.SOURCE} size -> "
                                       f"plain cut-extrude unless it is a bolt hole{hint}"))
    for key, ids in groups.items():
        if len(ids) > 1:
            out.append(Finding(severity="warning", code="mti_hole_grouping", feature=ids[0],
                               message=f"{', '.join(ids)}: identical holes on {key[0]} -> one Hole Wizard "
                                       f"feature with several sketch points"))

    # --- Fillets and chamfers at the end -------------------------------------
    seen_edge = None
    for f in planned:
        if isinstance(f, EdgeOp):
            seen_edge = seen_edge or f.id
        elif seen_edge:
            out.append(Finding(severity="info", code="mti_edge_ops_last", feature=f.id,
                               message=f"{f.id} ({f.kind}) comes after {seen_edge} ({plan.feature(seen_edge).operation}); "
                                       f"MTI puts fillets and chamfers at the end of the tree"))
            break

    # --- Generally-avoid features --------------------------------------------
    for f in plan.features:
        if f.kind in AVOID_KINDS:
            out.append(Finding(severity="warning", code="mti_avoid", feature=f.id,
                               message=f"{f.id}: {f.kind} is on MTI's 'generally avoid' list"))
    return out
