"""Answer key <-> drawing cross-check (spec 2026-10-23). Flags, never fixes.

The goal is to catch keygen mistakes and wrong drawing<->model pairings, not to nitpick:
every false flag costs a person time, every missed one corrupts the benchmark. The checks:

key -> drawing
  * every hole diameter is stated (diameter/radius dimension or a hole callout). A hole that
    fits a TAP callout's tap drill is relabelled ``tapped_hole`` and gets ``thread``; a
    counterbore/countersink covered by a "FOR #10 SOC. HD. CAP SCR." callout needs no printed
    size. A counterbore's ``cbore_d`` / ``cbore_depth`` are checked against the callout too.
  * every in-plane coordinate of every hole is explained by some drawing distance (from an
    envelope face, the part centre, another hole, or a bolt-circle radius/diameter).
drawing -> key
  * every linear/aligned/diameter/radius/ordinate value equals some key quantity.
  * every hole callout's count equals the number of key holes it describes.
  * the drawing's units hint (if any) equals the key's units.

Tolerance: each drawing value carries its own tolerance -- the general tolerance for its
number of decimals, else FALLBACK_TOL for the key's units.
"""
from __future__ import annotations

import dataclasses as _dc
import datetime as _dt
import math
import re
from typing import Optional

from bench.callouts import Callout
from bench.dxfread import Dim, Drawing
from bench.features import HOLE_TYPES, Feature, Flag, Key

FALLBACK_TOL = {"inch": 0.005, "mm": 0.1}
ALWAYS_REVIEW = {"1807408E"}       # provisional pairing (spec): a person always reviews it

_EPS = 1e-9                        # float slack so 3.00 - 2.99 == .01 counts as within .01
_DIA_MARK = re.compile(r"%%C|\u00d8|DIA", re.IGNORECASE)
_BOLT_CIRCLE = re.compile(r"B\.?\s*C\b|BOLT\s*CIRCLE", re.IGNORECASE)
_NUM = re.compile(r"\d*\.\d+|\d+")
_EDGE_BREAK = re.compile(r"CHAM|X\s*45|BREAK", re.IGNORECASE)
SMALL_EDGE = {"inch": 0.07, "mm": 2.0}    # largest edge-break/chamfer dim that is never flagged

Stated = list[tuple[float, float]]   # (value, tolerance)


# ---- tolerance -------------------------------------------------------------------------------

def _tol(drawing: Drawing, units: str, decimals: Optional[int] = None) -> float:
    if decimals is not None and decimals in drawing.general_tol:
        return drawing.general_tol[decimals]
    return FALLBACK_TOL[units]


def _callout_decimals(c: Callout, value: float) -> Optional[int]:
    """Decimals of the number in the callout text that spells `value` (".47" -> 2)."""
    for tok in _NUM.findall(c.text):
        if "." in tok and abs(float(tok) - value) < _EPS:
            return len(tok.split(".")[1])
    return None


def _near(v: float, pool: Stated) -> bool:
    return any(abs(v - p) <= t + _EPS for p, t in pool)


# ---- what the drawing states -----------------------------------------------------------------

def _dim_values(d: Dim) -> list[float]:
    """Values a dimension can explain: a radius also states its diameter and vice versa."""
    if d.kind == "radius":
        return [d.shown, 2 * d.shown]
    if d.kind == "diameter":
        return [d.shown, d.shown / 2]
    return [d.shown]


def _usable(d: Dim) -> bool:
    return d.kind != "angular" and d.shown is not None and d.shown > _EPS


def _hole_diameters(drawing: Drawing, units: str) -> Stated:
    """Values that may state a hole DIAMETER: callout sizes, diameter/radius dims, and linear
    dims marked with a diameter symbol (section views). A bolt-circle diameter is excluded so it
    cannot explain a hole size by coincidence."""
    out: Stated = []
    for d in drawing.dims:
        if not _usable(d) or _BOLT_CIRCLE.search(d.text or ""):
            continue
        t = _tol(drawing, units, d.decimals)
        if d.kind == "diameter" or (d.kind in ("linear", "aligned") and _DIA_MARK.search(d.text or "")):
            out.append((d.shown, t))
        elif d.kind == "radius":
            out.append((2 * d.shown, t))
    for c in drawing.callouts:
        for v in (c.d, c.cbore_d):
            if v:
                out.append((v, _tol(drawing, units, _callout_decimals(c, v))))
    return out


def _distances(drawing: Drawing, units: str) -> Stated:
    """Values that may locate a hole or match a key quantity: every non-angular dimension."""
    return [(v, _tol(drawing, units, d.decimals)) for d in drawing.dims if _usable(d)
            for v in _dim_values(d)]


def _positions(drawing: Drawing, units: str) -> Stated:
    """Distances that may locate a hole: every dimension plus each callout's bolt-circle
    diameter and radius ("(6) HLS. EQ. SP. ON 3.000 B.C.")."""
    out = _distances(drawing, units)
    for c in drawing.callouts:
        if c.bc_d:
            t = _tol(drawing, units, _callout_decimals(c, c.bc_d))
            out += [(c.bc_d, t), (c.bc_d / 2, t)]
    return out


# ---- what the key contains -------------------------------------------------------------------

def _centre_radius(h: Feature, env: list[float], tol: float) -> Optional[float]:
    """Radial distance of hole `h` from the part centre, only when the envelope seen along the
    hole axis is round/square (a bolt circle about the part centre is likely). Not used on
    rectangular plates, where a radial distance would match some stated value by coincidence
    and hide a misplaced hole."""
    if h.center is None or h.axis is None:
        return None
    plane = [i for i in range(3) if abs(h.axis[i]) <= 0.5]
    if len(plane) != 2 or abs(env[plane[0]] - env[plane[1]]) > tol:
        return None
    return math.sqrt(sum((h.center[i] - env[i] / 2) ** 2 for i in plane))


def _key_quantities(key: Key) -> list[float]:
    q = list(key.envelope)
    holes = [f for f in key.features if f.center is not None]
    for f in key.features:
        for v in (f.d, f.depth, f.cbore_d, f.cbore_depth, f.csink_d, f.offset):
            if v:
                q.append(v)
                if f.type in ("bore", "turned_diameter", "boss", "fillet", "slot"):
                    q.append(v / 2)
        if f.pattern and f.pattern.get("radius"):
            q += [f.pattern["radius"], 2 * f.pattern["radius"]]
        if f.size:
            q += [s for s in f.size if s]
    tol = FALLBACK_TOL[key.units]
    for f in holes:
        for i in range(3):
            q += [f.center[i], key.envelope[i] - f.center[i], abs(f.center[i] - key.envelope[i] / 2)]
        r = _centre_radius(f, key.envelope, tol) if f.type in HOLE_TYPES else None
        if r:
            q += [r, 2 * r]
    for i in range(3):
        q += _chain_steps(_unique_coords(holes, i, tol))
    return [x for x in q if x > _EPS]


def _unique_coords(holes: list[Feature], i: int, tol: float) -> list[float]:
    """Sorted hole-centre coordinates along axis i, merging values within tol."""
    out: list[float] = []
    for c in sorted(h.center[i] for h in holes if h.center is not None):
        if not out or c - out[-1] > tol:
            out.append(c)
    return out


def _chain_steps(coords: list[float]) -> list[float]:
    """Hole-to-hole distances a drawing states: chain dims (neighbouring coordinates) and
    baseline dims from a datum hole (the outermost coordinate at either end to every other).
    O(n) values; all-pairs differences would give O(n^2) and on a hole-dense part explain
    almost any number."""
    steps = [b - a for a, b in zip(coords, coords[1:])]
    if len(coords) > 2:
        steps += _baseline(coords, coords[0]) + _baseline(coords, coords[-1])
    return steps


def _baseline(coords: list[float], c: float) -> list[float]:
    """Distances from coordinate `c` to the outermost coordinates (datum holes); if `c` is itself
    a datum, to every coordinate."""
    if c in (coords[0], coords[-1]):    # exact float equality is safe: c is taken from coords itself
        return [abs(x - c) for x in coords if x != c]
    return [c - coords[0], coords[-1] - c]


# ---- taps ------------------------------------------------------------------------------------

def _thread_geometry(c: Callout, units: str) -> Optional[tuple[float, float]]:
    """(nominal major diameter, pitch) of a tap callout in key units."""
    if c.kind != "tap" or not c.nominal:
        return None
    if c.thread.startswith("M"):
        pitch_in = float(c.thread.split("X")[1]) / 25.4
    else:
        pitch_in = 1.0 / float(c.thread.rsplit("-", 1)[1])
    k = 25.4 if units == "mm" else 1.0
    return c.nominal * k, pitch_in * k


def _tap_for(h: Feature, taps: list[Callout], units: str, tol: float) -> Optional[Callout]:
    """The tap callout whose thread best fits hole `h`.

    A tapped hole is modelled either at the tap drill (~ nominal - pitch, e.g. 1/4-20 -> .201,
    3/8-16 -> .3125, M6x1 -> 5.0) or at the major diameter. The caller only asks for holes whose
    diameter no other callout/dimension states, so the major-diameter end of the window cannot
    swallow a stated plain hole. Accept d in
    [nominal - 1.3 * pitch, nominal]; this keeps a .250 drill off a .375-16 tap (whose window
    starts at .294). Among fits, the one closest to its tap drill wins."""
    best, best_err = None, math.inf
    for c in taps:
        g = _thread_geometry(c, units)
        if g is None:
            continue
        nominal, pitch = g
        if nominal - 1.3 * pitch - tol <= h.d <= nominal + tol:
            err = min(abs(h.d - (nominal - pitch)), abs(h.d - nominal)) / nominal
            if err < best_err:
                best, best_err = c, err
    return best


# ---- the check -------------------------------------------------------------------------------

def _cbore_match(h: Feature, c: Callout, tol: float) -> bool:
    return (c.kind == "cbore" and h.type == "counterbore"
            and (c.d is None or abs(h.d - c.d) <= tol + _EPS)
            and (c.cbore_d is None or (h.cbore_d is not None and abs(h.cbore_d - c.cbore_d) <= tol + _EPS)))


def _check_sizes(key: Key, drawing: Drawing, holes: list[Feature], tol: float) -> list[Flag]:
    flags: list[Flag] = []
    dias = _hole_diameters(drawing, key.units)
    depths = _distances(drawing, key.units) + [
        (c.depth, _tol(drawing, key.units, _callout_decimals(c, c.depth)))
        for c in drawing.callouts if c.depth and c.kind == "cbore"]
    taps = [c for c in drawing.callouts if c.kind == "tap"]
    screwed = {c.kind for c in drawing.callouts if c.kind in ("cbore", "csink") and c.screw}

    def need(h: Feature, name: str, v: Optional[float], pool: Stated) -> None:
        if v and not _near(v, pool):
            flags.append(Flag("unexplained_key_value", f"{h.type} {name}={v:.4f} not stated on the drawing", h.id))

    for h in holes:
        if h.d is None:
            continue
        if h.type in ("thru_hole", "blind_hole", "tapped_hole") and not _near(h.d, dias):
            # a diameter the drawing states outright (drill callout, diameter dim) is a plain
            # hole even when it falls in a tap window: a .250 dowel hole next to 1/4-20 taps,
            # a .2031 drill next to a .250-28 tap
            tap = _tap_for(h, taps, key.units, tol)
            if tap is not None:
                h.thread, h.type = tap.thread, "tapped_hole"
                continue
        if (h.type == "counterbore" and "cbore" in screwed) or (h.type == "countersink" and "csink" in screwed):
            continue                                  # sizes come from the named screw standard
        need(h, "d", h.d, dias)
        if h.type == "counterbore":
            need(h, "cbore_d", h.cbore_d, dias)
            matched = [c for c in drawing.callouts if _cbore_match(h, c, tol) and c.depth]
            if matched and h.cbore_depth:
                need(h, "cbore_depth", h.cbore_depth,
                     [(c.depth, _tol(drawing, key.units, _callout_decimals(c, c.depth))) for c in matched])
            elif h.cbore_depth and not matched:
                need(h, "cbore_depth", h.cbore_depth, depths)
        if h.type == "countersink":
            need(h, "csink_d", h.csink_d, dias)
    return flags


def _check_positions(key: Key, holes: list[Feature], stated: Stated, tol: float) -> list[Flag]:
    """Each in-plane coordinate of a hole must be explained. A coordinate is explained by a
    stated distance to an envelope face, the part centre or a neighbouring hole coordinate
    (chain dimension); by lying on the part centre or in line with another hole (implicit on
    drawings); or -- for both coordinates at once -- by a bolt-circle radius/diameter (keygen
    pattern, or radial distance from the centre of a round/square envelope) matching a dimension
    or a callout's "ON 3.000 B.C."."""
    flags: list[Flag] = []
    env = key.envelope
    chains = [_unique_coords(holes, i, tol) for i in range(3)]
    for h in holes:
        if h.center is None or h.axis is None:
            continue
        radii = [p.pattern["radius"] for p in key.features
                 if p.type == "hole_pattern" and h.id in p.members and p.pattern and p.pattern.get("radius")]
        plane = [i for i in range(3) if abs(h.axis[i]) <= 0.5]
        r = _centre_radius(h, env, tol)
        if r is not None:
            radii.append(r)
        if any(r > _EPS and (_near(r, stated) or _near(2 * r, stated)) for r in radii):
            continue
        for i in plane:
            c, e = h.center[i], env[i]
            aligned = any(abs(c - o.center[i]) <= tol for o in holes if o is not h and o.center is not None)
            if abs(c - e / 2) <= tol or aligned:
                continue
            coords = chains[i]
            k = min(range(len(coords)), key=lambda j: abs(coords[j] - c))
            neighbours = [abs(coords[j] - c) for j in (k - 1, k + 1) if 0 <= j < len(coords)]
            neighbours += _baseline(coords, coords[k])      # baseline from a datum hole
            cands = [x for x in [c, e - c, abs(c - e / 2)] + neighbours if x > _EPS]
            if not any(_near(x, stated) for x in cands):
                flags.append(Flag("unexplained_position", f"{h.type} at {[round(x, 4) for x in h.center]}: "
                                  f"coordinate {'xyz'[i]} is not located by any drawing distance", h.id))
                break
    return flags


def _check_drawing_values(key: Key, drawing: Drawing) -> list[Flag]:
    """Every dimension, and every callout bolt-circle diameter, must equal a key quantity.
    Exception: an edge-break/chamfer dim (text has CHAM, "X 45" or BREAK) no larger than
    SMALL_EDGE is never flagged -- keygen does not model small edge breaks, and they say nothing
    about placement."""
    flags: list[Flag] = []
    quantities = _key_quantities(key)
    for d in drawing.dims:
        if not _usable(d):
            continue
        if d.shown <= SMALL_EDGE[key.units] + _EPS and _EDGE_BREAK.search(d.text or ""):
            continue
        t = _tol(drawing, key.units, d.decimals)
        if d.shown <= t:
            continue
        if not any(abs(d.shown - q) <= t + _EPS for q in quantities):
            flags.append(Flag("unexplained_drawing_value",
                              f"{d.kind} {d.shown:g} ({d.text or 'measured'}) matches no key quantity"))
    for c in drawing.callouts:        # "... EQ. SP. ON 3.000 B.C." states a diameter too
        if c.bc_d:
            t = _tol(drawing, key.units, _callout_decimals(c, c.bc_d))
            if not any(abs(c.bc_d - q) <= t + _EPS for q in quantities):
                flags.append(Flag("unexplained_drawing_value",
                                  f"bolt circle {c.bc_d:g} (callout '{c.text.strip()}') matches no key quantity"))
    return flags


def _callout_holes(c: Callout, holes: list[Feature], tol: float) -> int:
    """How many key holes a callout describes: taps by thread, counterbores/countersinks by
    type (and size when printed), plain drill callouts by diameter among non-counterbored holes."""
    if c.kind == "tap":
        return sum(1 for h in holes if h.thread == c.thread)
    if c.kind == "cbore":
        return sum(1 for h in holes if _cbore_match(h, c, tol))
    if c.kind == "csink":
        return sum(1 for h in holes if h.type == "countersink"
                   and (c.d is None or abs(h.d - c.d) <= tol + _EPS))
    return sum(1 for h in holes if h.type in ("thru_hole", "blind_hole", "tapped_hole")
               and h.d is not None and c.d is not None and abs(h.d - c.d) <= tol + _EPS)


def _check_counts(drawing: Drawing, holes: list[Feature], tol: float) -> list[Flag]:
    """A counted callout must match exactly; an uncounted one ("TYP." or a single hole) must
    describe at least one key hole."""
    flags: list[Flag] = []
    for c in drawing.callouts:
        n = _callout_holes(c, holes, tol)
        if (c.count > 1 and n != c.count) or (c.count <= 1 and n == 0):
            flags.append(Flag("count_mismatch", f"callout '{c.text.strip()}' says {c.count}, key has {n}"))
    return flags


def check(key: Key, drawing: Drawing) -> list[Flag]:
    """Cross-check `key` against `drawing` and return the flags; key values are never edited.

    Side effect: holes that fit a TAP callout are relabelled (type -> tapped_hole, thread set).
    Call it on a freshly loaded/generated key, not on one already cross-checked against a
    different drawing, or stale relabels carry over.

    A tap callout whose thread size is unknown gives an ``unparsed_thread`` flag and is then
    ignored (no relabel, no count check) instead of raising."""
    flags: list[Flag] = []
    tol = _tol(drawing, key.units)
    if drawing.units_hint and drawing.units_hint != key.units:
        flags.append(Flag("units_mismatch", f"drawing says {drawing.units_hint}, key is {key.units}"))
    usable = []
    for c in drawing.callouts:
        try:
            _thread_geometry(c, key.units)
        except (KeyError, ValueError, IndexError, AttributeError, ZeroDivisionError):
            flags.append(Flag("unparsed_thread", f"callout '{c.text.strip()}': thread {c.thread!r} not understood"))
            continue
        usable.append(c)
    drawing = _dc.replace(drawing, callouts=usable)
    holes = [f for f in key.features if f.type in HOLE_TYPES]
    flags += _check_sizes(key, drawing, holes, tol)
    flags += _check_positions(key, holes, _positions(drawing, key.units), tol)
    flags += _check_drawing_values(key, drawing)
    flags += _check_counts(drawing, holes, tol)
    return flags


# ---- sign-off --------------------------------------------------------------------------------

def _today() -> str:
    return _dt.date.today().isoformat()


def sign_auto(key: Key, tool: str) -> bool:
    """Auto sign-off: no flags at all and not a part that must be reviewed by a person."""
    if key.flags or key.part in ALWAYS_REVIEW:
        return False
    key.signoff = {"kind": "auto", "by": "crosscheck", "tool": tool, "date": _today()}
    return True


def sign_human(key: Key, by: str) -> bool:
    """Human sign-off: every flag must carry a resolution."""
    if key.open_flags():
        return False
    key.signoff = {"kind": "human", "by": by, "date": _today()}
    return True
