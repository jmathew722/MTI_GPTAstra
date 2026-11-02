"""Callout defaults (spec docs/superpowers/specs/2026-10-28-callout-defaults-design.md).

The planner leaves a feature ``unresolved`` when the drawing doesn't settle it, but it still
writes the feature's full geometry. For the recurring vague callouts (".030 R MAX", "C/R",
"BREAK ALL SHARP CORNERS", a tap with a thread depth only) these rules give the documented
answer instead of skipping the feature. The rule values were measured from MTI's own models of the
audit parts. Every rule applied is recorded on the feature (``DEFAULT Dn`` in its justification)
and returned for the report. A default sets a size, never a position (CLAUDE.md rule 6).

    plan, applied = apply_defaults(plan, dims)

``MTI_CALLOUT_DEFAULTS=0`` turns the rules off (every vague callout stays a question).
"""
from __future__ import annotations

import os
import re
from typing import Optional

from pipeline.ir.expr import ExprError, evaluate
from pipeline.ir.model import BuildPlan, EdgeOp, Hole, edge_selector

TINY_BREAK = 0.010          # inch; at or below this an edge break is not modelled (D2)
TAP_EXTRA_PITCHES = 5       # drill depth beyond the thread (D5): MTI's #10-32 x .38 holes are .536 deep

_R_MAX = re.compile(r"\bR\.?\s*MAX|RADI(?:I|US)\b.*\bMAX", re.I)
_C_OR_R = re.compile(r"\bC\s*/\s*R\b", re.I)
_GENERAL_OR_TYP = re.compile(r"\bALL\s+CHAMFERS\b|\bTYP\b", re.I)
_TAP_DEPTH = re.compile(r"(?:TAP|THD|TH'D)\b[^0-9.]*?(\d*\.\d+|\d+)\s*(?:DEEP|DP)\b", re.I)
_THREAD = re.compile(r"(M\d+(?:\.\d+)?(?:\s*[xX×]\s*\d+(?:\.\d+)?)?|#?\d+(?:/\d+)?-\d+|\.\d+-\d+)")


def enabled() -> bool:
    return os.environ.get("MTI_CALLOUT_DEFAULTS", "1") != "0"


def _value(expr, dims: dict[str, float]) -> Optional[float]:
    try:
        return evaluate(expr, dims).value
    except (ExprError, KeyError, TypeError, ValueError):
        return None


def _text(f) -> str:
    return " ".join(f.source_callouts)


def _flag(f, rule: str, note: str) -> str:
    return (f.justification + " " if f.justification else "") + f"DEFAULT {rule}: {note}"


def _thread(text: str) -> Optional[str]:
    """First thread size in a callout, written the way parse_thread reads it ("8-32" -> "#8-32")."""
    m = _THREAD.search(text.upper())
    if not m:
        return None
    t = m.group(1).replace(" ", "")
    if re.fullmatch(r"\d+-\d+", t) and int(t.split("-")[0]) <= 12:   # numbered screw size
        t = "#" + t
    return t


def _pitch_expr(thread: str) -> Optional[str]:
    """TAP_EXTRA_PITCHES pitches as an expression: inch "5 / tpi", metric "5 * pitch" (mm parts)."""
    m = re.fullmatch(r"M\d+(?:\.\d+)?[xX×](\d+(?:\.\d+)?)", thread)
    if m:
        return f"{TAP_EXTRA_PITCHES} * {m.group(1)}"
    m = re.search(r"-(\d+)$", thread)
    return f"{TAP_EXTRA_PITCHES} / {m.group(1)}" if m else None


def _edge(f: EdgeOp, dims) -> tuple[Optional[EdgeOp], str] | None:
    """(new feature or None to drop it, report note), or None when no rule applies."""
    text, size = _text(f), _value(f.size, dims)
    if not size:
        return None, "D4 not modelled: edge break with no printed size"
    if size <= TINY_BREAK:
        return None, f"D2 not modelled: {size:g} break is at or below {TINY_BREAK:g}"
    if _R_MAX.search(text) and not _C_OR_R.search(text):
        note = f"D1 fillet at the max value {size:g}"
        return f.model_copy(update={"status": "planned", "operation": "fillet",
                                    "justification": _flag(f, "D1", "max-only radius built at the max value")}), note
    if _C_OR_R.search(text):
        note = f"D3 chamfer {size:g} x 45 (C/R)"
        return f.model_copy(update={"status": "planned", "operation": "chamfer", "angle": "45",
                                    "justification": _flag(f, "D3", "chamfer-or-radius built as a 45 deg chamfer")}), note
    if _GENERAL_OR_TYP.search(text):
        note = f"D7 {f.operation} {size:g} on the {len(f.edges)} planned edge(s)"
        return f.model_copy(update={"status": "planned",
                                    "justification": _flag(f, "D7", "general/TYP callout applied to the planned edges")}), note
    return None


def _hole(f: Hole, dims) -> tuple[Hole, str] | None:
    text, spec = _text(f), f.spec
    on = f.on.replace(" ", "")
    if not (on.startswith(("face(", "plane(")) or re.fullmatch(r"wall\(F\d+,.+\)", on)):
        return None   # only starts the IR can drill from: a radial hole needs wall(F, r) (E031)
    if spec.depth is None:
        m = _TAP_DEPTH.search(text)
        thread = _thread(text)
        if not (m and thread):
            return None
        x = float(m.group(1))
        dim = next((k for k, v in sorted(dims.items()) if abs(v - x) < 1e-6), None)
        pitches = _pitch_expr(thread)
        if dim is None or pitches is None:
            return None
        new = spec.model_copy(update={"type": "tapped", "depth": f"{dim} + {pitches}", "thread": thread})
        note = f"D5 {thread} drill depth = {x:g} thread + {TAP_EXTRA_PITCHES} pitches"
        return f.model_copy(update={"status": "planned", "spec": new, "justification": _flag(
            f, "D5", f"drill depth = printed thread depth + {TAP_EXTRA_PITCHES} pitches "
                     f"(literal {pitches} is {TAP_EXTRA_PITCHES} thread pitches)")}), note
    if spec.type == "tapped" and "class" in f.rationale.lower():
        thread = _thread(spec.thread or text) or spec.thread
        new = spec.model_copy(update={"thread": thread})
        return f.model_copy(update={"status": "planned", "spec": new, "justification": _flag(
            f, "D6", "thread class doesn't change geometry; threads are cosmetic")}), f"D6 {thread}: class not needed"
    return None


def _pilot_of(f: Hole, out: list) -> Optional[int]:
    """Index in ``out`` of the planned tap that the unresolved blind hole ``f`` is the pilot
    drill of: same start, position and diameter, no depth of its own (SB12006/07/09/10:
    "#10-32 TAP .38 DEEP" planned as a tap plus an unresolved drill at the same spot)."""
    if f.spec.depth is not None or f.spec.type not in ("blind", "tapped"):
        return None
    key = (f.on.replace(" ", ""), f.u, f.v, f.spec.d)
    for i, g in enumerate(out):
        if (isinstance(g, Hole) and g.status == "planned" and g.spec.type == "tapped" and g.spec.depth
                and (g.on.replace(" ", ""), g.u, g.v, g.spec.d) == key):
            return i
    return None


def _drill_for(f: Hole, out: list, dims: dict[str, float]) -> Optional[int]:
    """Index in ``out`` of the planned drill that the unresolved tap ``f`` belongs in: same
    start, position and diameter, at least as deep."""
    if f.spec.type != "tapped" or f.spec.depth is None:
        return None
    key, depth = (f.on.replace(" ", ""), f.u, f.v, f.spec.d), _value(f.spec.depth, dims)
    for i, g in enumerate(out):
        if (isinstance(g, Hole) and g.status == "planned" and g.spec.type == "blind" and g.spec.depth
                and (g.on.replace(" ", ""), g.u, g.v, g.spec.d) == key
                and depth is not None and (_value(g.spec.depth, dims) or 0) >= depth):
            return i
    return None


def apply_defaults(plan: BuildPlan, dims: dict[str, float]) -> tuple[BuildPlan, list[str]]:
    if not enabled():
        return plan, []
    out, applied = [], []
    for f in plan.features:
        res = None
        if f.status == "unresolved" and isinstance(f, Hole) and (i := _pilot_of(f, out)) is not None:
            # D5 for a tap and its pilot: ONE tap drilled thread depth + 5 pitches (MTI: one
            # Hole Wizard tap; a second tap on top of the first can't be volume-checked as one)
            tap = out[i]
            pitches = _pitch_expr(_thread(tap.spec.thread or _text(f)) or "")
            if pitches:
                out[i] = tap.model_copy(update={
                    "spec": tap.spec.model_copy(update={"depth": f"{tap.spec.depth} + {pitches}"}),
                    "justification": _flag(tap, "D5", f"drill depth = printed thread depth + "
                                                      f"{TAP_EXTRA_PITCHES} pitches (pilot {f.id} merged)")})
                applied.append(f"{f.id}: D5 pilot drill merged into tap {tap.id} "
                               f"(drill = thread + {TAP_EXTRA_PITCHES} pitches)")
                continue
        if f.status == "unresolved" and isinstance(f, Hole) and (i := _drill_for(f, out, dims)) is not None:
            # the other way round (2N2664 F024/F025): a planned drill and an unresolved tap at the
            # same spot -> the drill becomes the tap (thread is cosmetic, D6). A tap shallower
            # than its drill cut nothing on its own ("cut removed no material").
            drill = out[i]
            thread = _thread(f.spec.thread or _text(f)) or f.spec.thread
            out[i] = drill.model_copy(update={
                "spec": drill.spec.model_copy(update={"type": "tapped", "thread": thread}),
                "justification": _flag(drill, "D6", f"tapped {thread} (tap {f.id} merged; threads are cosmetic)")})
            applied.append(f"{f.id}: D6 tap {thread} merged into drill {drill.id}")
            continue
        if f.status == "unresolved":
            if isinstance(f, EdgeOp):
                res = _edge(f, dims)
            elif isinstance(f, Hole):
                res = _hole(f, dims)
        if res is None:
            out.append(f)
            continue
        new, note = res
        applied.append(f"{f.id}: {note}")
        if new is not None:
            out.append(new)
    if plan.frame.origin_kind == "axis_end":
        out, more = _general_note_edges(plan, out, dims)
        applied += more
    return plan.model_copy(update={"features": out}), applied


_ALL_CHAMFERS = re.compile(r"\bALL\s+CHAMFERS\b", re.I)
_ALL_RADII = re.compile(r"\bALL\s+(RADII|FILLETS)\b", re.I)


def _general_note_edges(plan: BuildPlan, out: list, dims: dict[str, float]) -> tuple[list, list[str]]:
    """D8 (turned parts): a general note applies to EVERY edge it covers, not only the ones the plan
    names. "ALL CHAMFERS .06 x 45 U.O.S." -> a chamfer on every still-sharp outside corner;
    "ALL RADII .047 MAX" -> a fillet at the max on every still-sharp inside corner. Added last, so
    edges the drawing treats explicitly are already rounded or chamfered and are left alone.
    Measured on 2N2664: MTI's model has these on every such edge (0.26% of overlap)."""
    if any(isinstance(g, EdgeOp) and any(edge_selector(q) for q in g.edges) for g in out):
        return out, []                                   # the plan already does it
    nid = max(int(g.id[1:]) for g in plan.features) + 1
    added, notes = [], []
    for rx, op, sel, rule in ((_ALL_CHAMFERS, "chamfer", "edges(convex)", "chamfer"),
                              (_ALL_RADII, "fillet", "edges(concave)", "fillet")):
        src = next((g for g in plan.features if isinstance(g, EdgeOp) and rx.search(_text(g))), None)
        size = _value(src.size, dims) if src else None
        if not size or size <= TINY_BREAK:
            continue
        add = EdgeOp(id=f"F{nid:03d}", operation=op, size=src.size, angle=src.angle if op == "chamfer" else "45",
                     edges=[sel], source_callouts=src.source_callouts, rationale=f"general note on every {sel[6:-1]} edge",
                     justification=_flag(src.model_copy(update={"justification": ""}), "D8",
                                         f"general note applied to every still-sharp {sel[6:-1]} edge"))
        added.append(add)
        notes.append(f"{add.id}: D8 {op} {size:g} on every still-sharp {sel[6:-1]} edge (general note)")
        nid += 1
    return out + added, notes


_TWO_PLACE = re.compile(r"2\s*PLACE\s*DIM\.?\s*[±+\-]+\s*(\.\d+)", re.I)


def nominal_fractions(plan: BuildPlan, dims: dict[str, float], extraction: dict | None) -> tuple[dict[str, float], list[str]]:
    """D9 (prismatic parts): a TWO-PLACE dimension within .005 of a 1/16" fraction is that fraction.
    Old drawings print fractional stock and sizes rounded to two places (".38" for 3/8 plate,
    "34.38" for 34-3/8). MTI's models use the fraction on every A-Series plate checked (A00121E/M,
    A00122E 0.9865 -> 1.0000, A00134E, A00143E); turned SB parts keep the printed value (SB12055
    6.12), so turned parts are left alone. Two-place is read from the dimension's tolerance: it must
    equal the drawing's 2-place general tolerance (".440" is three-place, +-.010: never rounded;
    A00160E). Reference/derived values (tolerance 0) and unreadable title blocks are left alone."""
    if not enabled() or plan.frame.origin_kind != "corner" or not extraction:
        return dims, []
    m = _TWO_PLACE.search(str(extraction.get("general_tolerance") or ""))
    if not m:
        return dims, []
    two = float(m.group(1))
    tol = {d["id"]: (d.get("tolerance_plus") or 0.0, d.get("tolerance_minus") or 0.0)
           for d in extraction.get("dimensions", [])}
    out, applied = dict(dims), []
    for k, v in dims.items():
        if k not in tol or abs(tol[k][0] - two) > 1e-9 or abs(tol[k][1] - two) > 1e-9:
            continue
        f = round(v * 16) / 16
        if 0 < abs(v - f) <= 0.0051:
            out[k] = f
            applied.append(f"{k}: D9 {v:g} -> {f:g} (two-place print of a 1/16 fraction)")
    return out, applied
