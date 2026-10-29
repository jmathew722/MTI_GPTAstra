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
from pipeline.ir.model import BuildPlan, EdgeOp, Hole

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
    if not f.on.replace(" ", "").startswith(("face(", "plane(")):
        return None   # e.g. a radial hole on wall(...): the IR can't start a hole there (SB12059 F005)
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


def apply_defaults(plan: BuildPlan, dims: dict[str, float]) -> tuple[BuildPlan, list[str]]:
    if not enabled():
        return plan, []
    out, applied = [], []
    for f in plan.features:
        res = None
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
    return plan.model_copy(update={"features": out}), applied
