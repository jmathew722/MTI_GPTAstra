"""DXF (converted from MTI's DWG by ODA) -> what the drawing states.

A dimension's displayed text is what the drawing says. Legacy drawings often override the
text (not-to-scale views), so `shown` is the overridden number when there is one, else the
measurement times DIMLFAC.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from bench.callouts import Callout, parse

DIMTYPES = {0: "linear", 1: "aligned", 2: "angular", 3: "diameter", 4: "radius", 5: "angular", 6: "ordinate"}
_NUM = re.compile(r"(?<![\d.])(\d*\.\d+|\d+)(?![\d.])")
_GTOL = re.compile(r"\.(0{1,4}|X{1,4})\s*=?\s*(?:%%P|±|\+/-|\+-)\s*(\.\d+)")


@dataclass
class Dim:
    kind: str
    measured: float
    shown: Optional[float]
    text: str
    not_to_scale: bool
    decimals: Optional[int]


@dataclass
class Drawing:
    dims: list[Dim] = field(default_factory=list)
    callouts: list[Callout] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    general_tol: dict[int, float] = field(default_factory=dict)
    units_hint: Optional[str] = None


def _decimals(s: str) -> Optional[int]:
    m = re.search(r"\.(\d+)", s)
    return len(m.group(1)) if m else None


def _dim(e) -> Optional[Dim]:
    kind = DIMTYPES.get(e.dimtype & 7)
    if kind is None:
        return None
    try:
        lfac = float(e.override().get("dimlfac", 1.0) or 1.0)
    except Exception:
        lfac = 1.0
    measured = float(e.get_measurement()) * lfac
    raw = (e.dxf.get("text") or "").strip()
    if raw in ("", "<>") or "<>" in raw:
        return Dim(kind, measured, measured, raw, False, None)
    plain = re.sub(r"\\[A-Za-z][^;]*;|\\P|[{}]|%%[CcPpDd]", " ", raw)
    m = _NUM.search(plain)
    shown = float(m.group(1)) if m else None
    nts = shown is not None and abs(shown - measured) > 1e-6
    return Dim(kind, measured, shown, raw, nts, _decimals(m.group(1)) if m else None)


def _in_dim_block(e) -> bool:
    """True for entities inside an anonymous dimension block (*D...): copies of dim text."""
    try:
        name = e.doc.entitydb[e.dxf.owner].dxf.name
    except Exception:
        return False
    return name.upper().startswith("*D")


def read(path: Path) -> Drawing:
    import ezdxf
    doc = ezdxf.readfile(str(path))
    dr = Drawing()
    for e in doc.entitydb.values():
        t = e.dxftype()
        if t == "DIMENSION":
            d = _dim(e)
            if d is not None:
                dr.dims.append(d)
        elif t in ("TEXT", "ATTRIB", "MTEXT"):
            if _in_dim_block(e):
                continue
            dr.texts.append(e.dxf.text if t != "MTEXT" else e.plain_text())
    for s in dr.texts:
        c = parse(s)
        if c is not None:
            dr.callouts.append(c)
        for m in _GTOL.finditer(s.upper()):
            dr.general_tol[len(m.group(1))] = float(m.group(2))
    blob = " ".join(dr.texts).upper()
    if "MILLIMET" in blob or "DIMENSIONS ARE IN MM" in blob:
        dr.units_hint = "mm"
    elif "INCH" in blob:
        dr.units_hint = "inch"
    return dr
