"""DXF (converted from MTI's DWG by ODA) -> what the drawing states.

A dimension's displayed text is what the drawing says. Legacy drawings often override the
text (not-to-scale views), so `shown` is the overridden number when there is one, else the
measurement times |DIMLFAC| (not for angular dims).

Texts and dims inside block definitions are read once per definition (not once per INSERT);
ATTRIB values of INSERTs are read.

Legacy (R12-era) drawings were often EXPLODED: a dimension is LINEs + SOLID arrowheads + a
TEXT holding its value. A modelspace TEXT/MTEXT whose whole content is a decimal dimension
value (".50", "2X 1.250", "%%C.500", ".62 R.", "1.250+.000/-.001", "3.000 B.C.") becomes a
Dim with source "text"; one that sits within _DEDUP_DIST of a real DIMENSION's text midpoint
with the same shown value is skipped (it is that dimension's text). Callouts split over
several left-aligned TEXT lines (".38-16 TAP .75 DP." / "4-HOLES") are joined into one.
"""
from __future__ import annotations

import math
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
    source: str = "dimension"   # "dimension" (DIMENSION entity) | "text" (exploded dim text)


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


_TEXT_DIM = re.compile(
    r"^(?:(?:\d+\s*X|\(\s*\d+\s*\)|\d+\s*(?:PLCS?|PLACES)\.?)\s+)?"   # count prefix
    r"(?P<dpre>%%C|\u00d8)?\s*(?P<rpre>R\.?)?\s*"
    r"(?P<num>\d*\.\d+)"
    r"\s*(?:(?P<dpost>%%C|\u00d8|DIA\b\.?)|(?P<rpost>R\b\.?))?"
    r"(?:\s*(?:%%P|\u00b1|\+/-)\s*\d*\.\d+|\s*\+\s*\d*\.\d+\s*/?\s*-\s*\d*\.\d+)?"   # tolerance
    r"(?P<tags>(?:\s*(?:TYP|REF|MAX|MIN|B\.?\s*C)\b\.?)*)\s*$")
_DEDUP_DIST = 0.5


def _plain(s: str) -> str:
    return " ".join(re.sub(r"\\[A-Za-z][^;]*;|\\P|[{}]", " ", s).upper().split())


def _text_dim(raw: str) -> Optional[Dim]:
    """A Dim if the whole string is a decimal dimension value (exploded legacy dimension)."""
    m = _TEXT_DIM.match(_plain(raw))
    if not m:
        return None
    v = float(m.group("num"))
    if v <= 0:          # ".000 %%P.010" is a general-tolerance line, not a dimension
        return None
    if m.group("rpre") or m.group("rpost"):
        kind = "radius"
    elif m.group("dpre") or m.group("dpost") or re.search(r"B\.?\s*C", m.group("tags")):
        kind = "diameter"
    else:
        kind = "linear"
    return Dim(kind, v, v, raw, False, _decimals(m.group("num")), source="text")


def _info(c: Callout) -> int:
    return ((c.count != 1) + (c.depth is not None) + c.thru + (c.bc_d is not None)
            + bool(c.screw) + (c.cbore_d is not None))


def _stacks(items):
    """Group (x, y, h, text) into left-aligned, vertically adjacent stacks, top to bottom."""
    items = sorted(items, key=lambda it: (-it[1], it[0]))
    stacks: list[list] = []
    for it in items:
        x, y, h, _ = it
        for st in stacks:
            lx, ly, lh, _ = st[-1]
            hh = max(h, lh, 1e-6)
            dy = ly - y
            if abs(lx - x) <= max(0.25 * hh, 0.05) and 0.1 * hh < dy <= 2.0 * hh + 1e-9:
                st.append(it)
                break
        else:
            stacks.append([it])
    return stacks


def _stack_items(lines: list[str], dr: Drawing, text_dims: list) -> None:
    """Text dims and callouts of one stack; a callout absorbs following lines that add info."""
    i = 0
    while i < len(lines):
        d = _text_dim(lines[i])
        if d is not None:
            text_dims.append((i, d))
            i += 1
            continue
        c = parse(lines[i])
        j = i + 1
        while c is not None and j < len(lines) and _text_dim(lines[j]) is None:
            cj = parse(" ".join(x.strip() for x in lines[i:j + 1]))
            if cj is None or _info(cj) <= _info(c):
                break
            c, j = cj, j + 1
        if c is not None:
            dr.callouts.append(c)
        i = j


def _xyh(e):
    t = e.dxftype()
    p = e.dxf.insert
    h = e.dxf.get("height", 0.0) if t == "TEXT" else e.dxf.get("char_height", 0.0)
    return float(p.x), float(p.y), float(h or 0.0)


def read(path: Path) -> Drawing:
    dr = Drawing()
    doc = _open(Path(path), dr)
    try:
        msp_owner = doc.modelspace().layout_key
    except Exception:
        msp_owner = None
    dim_marks = []          # (shown, text midpoint) of DIMENSION entities
    loose: list[str] = []   # texts outside modelspace stacks: parsed one by one
    ms_items = []           # modelspace TEXT/MTEXT: (x, y, h, text)
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
                mp = e.dxf.get("text_midpoint")
                if mp is not None and d.shown is not None:
                    dim_marks.append((d.shown, mp))
        elif t in ("TEXT", "ATTRIB", "MTEXT"):
            if _in_dim_block(e):
                continue
            txt = e.dxf.text if t != "MTEXT" else e.plain_text()
            dr.texts.append(txt)
            xyh = None
            if t != "ATTRIB" and msp_owner is not None and e.dxf.get("owner") == msp_owner:
                try:
                    xyh = _xyh(e)
                except Exception:
                    xyh = None
            if xyh is None:
                loose.append(txt)
            else:
                ms_items.append((*xyh, txt))
    for st in _stacks(ms_items):
        found: list = []
        _stack_items([it[3] for it in st], dr, found)
        for i, d in found:
            x, y = st[i][0], st[i][1]
            if any(abs(v - d.shown) < 1e-6 and math.hypot(mp.x - x, mp.y - y) <= _DEDUP_DIST
                   for v, mp in dim_marks):
                continue     # the visible text of a real DIMENSION entity
            dr.dims.append(d)
    for s in loose:
        c = parse(s)
        if c is not None:
            dr.callouts.append(c)
    for s in dr.texts:
        for m in _GTOL.finditer(s.upper()):
            dr.general_tol[len(m.group(1))] = float(m.group(2))
    dr.units_hint = _units_hint(" ".join(dr.texts).upper())
    return dr
