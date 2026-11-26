"""Section-view planning (pure geometry): which blind / counterbored holes need a section, and where the cutting line goes.

A hole whose depth or counterbore cannot be read from its circular end gets a section through its axis (standard drafting practice).  The cut runs along one
of the two axes perpendicular to the hole, through the row of similar holes that contains the most of them, so one section covers a whole row.
"""
from __future__ import annotations

from typing import Optional

LABELS = "ABCDEFGH"


def needs_section(h: dict) -> bool:
    return (not h["through"]) or bool(h.get("counterbore"))


def plan_sections(holes: list[dict], max_sections: int = 3) -> list[dict]:
    """[{label, axis, entry_side, cut_along, at_axis, at_m, covers[], hole_ids[]}] - at most ``max_sections``, biggest groups first."""
    need = [h for h in holes if needs_section(h)]
    groups: dict[tuple, list[dict]] = {}
    for h in need:
        groups.setdefault((h["axis"], h["entry_side"]), []).append(h)
    plans = []
    for (axis, entry), hs in groups.items():
        u_axis, v_axis = hs[0]["center_axes"]
        # rows along u share the same v; pick the row with the most holes
        rows: dict[int, list[dict]] = {}
        for h in hs:
            rows.setdefault(round(h["center_m"][1] / 1e-5), []).append(h)
        row = max(rows.values(), key=len)
        plans.append({"axis": axis, "entry_side": entry, "cut_along": u_axis, "at_axis": v_axis, "at_m": row[0]["center_m"][1],
                      "covers": [h["id"] for h in row], "hole_ids": [h["id"] for h in hs], "count": len(hs)})
    plans.sort(key=lambda p: -len(p["covers"]))
    plans = plans[:max_sections]
    for i, p in enumerate(plans):
        p["label"] = LABELS[i]
    return plans


def uncovered(holes: list[dict], plans: list[dict]) -> list[str]:
    """Holes that still need a section but are not on any planned cutting line (they stay review items)."""
    cov = {i for p in plans for i in p["covers"]}
    return [h["id"] for h in holes if needs_section(h) and h["id"] not in cov]
