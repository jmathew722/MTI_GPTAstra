"""DXF (converted from MTI's DWG by ODA) -> what the drawing states.

A dimension's displayed text is what the drawing says. Legacy drawings often override the
text (not-to-scale views), so `shown` is the overridden number when there is one, else the
measurement times |DIMLFAC| (not for angular dims).

Texts and dims inside block definitions are read once per definition (not once per INSERT);
ATTRIB values of INSERTs are read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from bench.callouts import Callout, parse

DIMTYPES = {0: "linear", 1: "aligned", 2: "angular", 3: "diameter", 4: "radius", 5: "angular", 6: "ordinate"}
_NUM = re.compile(r"(?<![\d.])(\d*\.\d+|\d+)(?![\d.])")
_GTOL = re.compile(r"\.(0{1,4}|X{1,4})\s*=?\s*(?:%%P|\u00b1|\+/-|\+-)\s*(\.\d+)")


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
    warnings: list[str] = field(default_factory=list)


def _decimals(s: str) -> Optional[int]:
    m = re.search(r"\.(\d+)", s)
    return len(m.group(1)) if m else None


_QTY = re.compile(
    r"\b\d+\s*X\b|\(\s*\d+\s*\)|\b\d+\s*(?:PLCS?|PLACES?|HLS?|HOLES?)\b", re.IGNORECASE)


def _shown_number(raw: str) -> Optional[str]:
    """The dimension value in an override string, ignoring quantity prefixes ("2X", "(2)", "4 PLCS")."""
    plain = re.sub(r"\\[A-Za-z][^;]*;|\\P|[{}]|%%[CcPpDd]", " ", raw)
    plain = _QTY.sub(" ", plain)
    toks = _NUM.findall(plain)
    for t in toks:
        if "." in t:
            return t
    return toks[0] if toks else None


def _dim(e) -> Optional[Dim]:
    kind = DIMTYPES.get(e.dimtype & 7)
    if kind is None:
        return None
    try:
        ov = e.override()
        lfac = abs(float(ov.get("dimlfac", 1.0) or 1.0))
        dec = ov.get("dimadec" if kind == "angular" else "dimdec")
        dec = int(dec) if dec is not None else None
    except Exception:
        lfac, dec = 1.0, None
    if kind == "angular":
        lfac = 1.0
    m = e.get_measurement()
    if kind == "ordinate":  # Vec3 of the feature relative to the origin; bit 64 = X-type
        m = m.x if (e.dxf.dimtype & 64) else m.y
    measured = float(m) * lfac
    raw = (e.dxf.get("text") or "").strip()
    if raw in ("", "<>") or "<>" in raw:
        return Dim(kind, measured, measured, raw, False, dec)
    tok = _shown_number(raw)
    shown = float(tok) if tok else None
    nts = shown is not None and abs(shown - measured) > 1e-6
    return Dim(kind, measured, shown, raw, nts, _decimals(tok) if tok else None)


def _in_dim_block(e) -> bool:
    """True for entities inside an anonymous dimension block (*D...): copies of dim text."""
    try:
        name = e.doc.entitydb[e.dxf.owner].dxf.name
    except Exception:
        return False
    return name.upper().startswith("*D")


_UNIT = r"(INCH(?:ES)?|MILLIMET(?:ER|RE)S?|MM)\b"
_UNIT_PHRASE = re.compile(
    r"(?:DIMENSIONS?\s+(?:ARE\s+)?IN|UNLESS\s+OTHERWISE\b[^\n]*?\b(?:IN|ARE))\s+" + _UNIT)
_UNIT_ANY = re.compile(r"\b" + _UNIT)


def _unit_name(word: str) -> str:
    return "inch" if word.startswith("INCH") else "mm"


def _units_hint(blob: str) -> Optional[str]:
    m = _UNIT_PHRASE.search(blob)
    if m:
        return _unit_name(m.group(1))
    found = {_unit_name(x) for x in _UNIT_ANY.findall(blob)}
    return found.pop() if len(found) == 1 else None


def _open(path: Path, dr: Drawing):
    import ezdxf
    try:
        return ezdxf.readfile(str(path))
    except FileNotFoundError:
        raise
    except (ezdxf.DXFError, OSError, UnicodeDecodeError) as first:
        try:
            from ezdxf import recover
            doc, _aud = recover.readfile(str(path))
        except FileNotFoundError:
            raise
        except Exception:
            raise ValueError(f"unreadable DXF {path}") from first
        dr.warnings.append(f"DXF structure damaged ({first}); recovered with ezdxf.recover")
        return doc


def read(path: Path) -> Drawing:
    dr = Drawing()
    doc = _open(Path(path), dr)
    for e in doc.entitydb.values():
        t = e.dxftype()
        if t == "DIMENSION":
            try:
                d = _dim(e)
            except Exception as ex:
                dr.warnings.append(f"skipped DIMENSION {e.dxf.handle}: {type(ex).__name__}: {ex}")
                continue
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
    dr.units_hint = _units_hint(" ".join(dr.texts).upper())
    return dr
