"""MTI Standard 202.02.0003 (tap and hole specifications): the shop's own table.

MTI's modeling practice (docs/mti/mti-modeling-standards.md) is Hole Wizard for every bolt
hole, and many legacy prints give only a plain diameter ("Ø.281 THRU") without saying
"clearance for 1/4 SHCS". This module answers which screw a plain hole is for, from
MTI's table: a diameter that equals a clearance, tap-drill or counterbore size.

The table is **proprietary and confidential**, so it is not in the repo. It is read
from a local file (``MTI_STANDARD_PATH``, default ``config/mti/202.02.0003.local.json``,
gitignored); without it every function returns None and callers fall back to the
generic chart in :mod:`pipeline.fasteners`. It is used only by deterministic local
code, never put in a model prompt.

Every match is a *proposal* with its source, flagged for review (CLAUDE.md rule 6).
A value printed on the drawing always wins over the table.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "mti" / "202.02.0003.local.json"
SOURCE = "MTI Std 202.02.0003"
MM_PER_INCH = 25.4
# A drawing diameter matches a table size within this (drawing units). Hardware of the
# other system must match its exact conversion (to the printed precision): Ø.218 on an
# inch print is not a metric clearance hole just because it is within .0015 of one.
TOL = {"inch": 0.0015, "mm": 0.05}
CROSS_TOL = {"inch": 0.0006, "mm": 0.015}
# Which hole a diameter can be, in priority order (a clearance hole is the common case).
# A counterbore diameter is matched only as part of a counterbored hole (``cbore_d``).
ROLES = ("clearance_normal", "clearance_loose", "tap_drill")
ALL_ROLES = ROLES + ("cbore_d",)


@dataclass(frozen=True)
class HoleMatch:
    size: str            # "1/4", "M8"
    system: str          # "inch" | "metric"
    role: str            # clearance_normal | clearance_loose | tap_drill | cbore_d
    table_value: float   # in the table's own units
    error: float         # |drawing - table| in drawing units
    preferred: bool      # MTI marks preferred sizes

    @property
    def note(self) -> str:
        what = {"clearance_normal": "clearance (normal)", "clearance_loose": "clearance (loose)",
                "tap_drill": "tap drill", "cbore_d": "counterbore"}[self.role]
        return f"STANDARD-DERIVED: {what} for {self.size} ({self.system}), {SOURCE}"


def path() -> Path:
    return Path(os.getenv("MTI_STANDARD_PATH") or DEFAULT_PATH)


@lru_cache(maxsize=4)
def _load(p: str) -> Optional[dict]:
    f = Path(p)
    if not f.is_file():
        return None
    data = json.loads(f.read_text(encoding="utf-8"))
    out = {}
    for system in ("inch", "metric"):
        t = data[system]
        out[system] = [dict(zip(t["columns"], row)) for row in t["rows"]]
    return out


def table() -> Optional[dict]:
    """``{"inch": [row, ...], "metric": [row, ...]}`` or None when the local file is absent."""
    return _load(str(path()))


def available() -> bool:
    return table() is not None


def match_hole(diameter: float, units: str, roles: tuple[str, ...] = ROLES) -> list[HoleMatch]:
    """Every MTI table entry a drawing hole diameter equals, best first.

    Ranking: the drawing's own unit system first (an inch print is usually inch
    hardware), then role order (clearance before tap drill), then MTI-preferred sizes,
    then the smallest error.
    """
    t = table()
    if t is None:
        return []
    found = []
    for system, rows in t.items():
        same = (system == "inch") == (units == "inch")
        tol = TOL[units] if same else CROSS_TOL[units]
        to_drawing = 1.0 if same else (1 / MM_PER_INCH if units == "inch" else MM_PER_INCH)
        for row in rows:
            for role in roles:
                v = row.get(role)
                if v is None:
                    continue
                err = abs(diameter - v * to_drawing)
                if err <= tol:
                    found.append(HoleMatch(row["size"], system, role, v, round(err, 6), bool(row["preferred"])))
    native = "inch" if units == "inch" else "metric"
    found.sort(key=lambda m: (m.system != native, ALL_ROLES.index(m.role), not m.preferred, m.error))
    return found


def nearest(diameter: float, units: str, roles: tuple[str, ...] = ROLES) -> Optional[HoleMatch]:
    """The closest table entry in the drawing's own system (a hint when nothing matches)."""
    t = table()
    if t is None:
        return None
    system = "inch" if units == "inch" else "metric"
    best = None
    for row in t[system]:
        for role in roles:
            v = row.get(role)
            if v is not None and (best is None or abs(diameter - v) < best.error):
                best = HoleMatch(row["size"], system, role, v, round(abs(diameter - v), 6), bool(row["preferred"]))
    return best


def row(size: str) -> Optional[dict]:
    """The table row for a screw size ("1/4", "#10", "M8")."""
    t = table()
    if t is None:
        return None
    key = size.replace(" ", "").upper()
    for rows in t.values():
        for r in rows:
            if r["size"].upper() == key:
                return r
    return None


def shcs_counterbore_inch(nominal: float) -> Optional[tuple[float, float, float]]:
    """(clearance drill, cbore diameter, cbore depth) for an inch SHCS, from MTI's table."""
    t = table()
    if t is None:
        return None
    for r in t["inch"]:
        if abs(r["nominal"] - nominal) <= 0.003 and r["cbore_d"] is not None:
            return (r["clearance_normal"], r["cbore_d"], r["cbore_depth"])
    return None
