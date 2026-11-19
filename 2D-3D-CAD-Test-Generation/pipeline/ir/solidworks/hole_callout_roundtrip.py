"""Drawing Hole Callout round trip (Stage 4, task 4.11).

A part with a native Hole Wizard feature is put in a drawing, SOLIDWORKS inserts its own Hole Callout, and the callout's
text is parsed back to semantics and compared with the intent that created the feature. Formatting is not compared:
only the meaning (diameters, depths, through, countersink angle, thread designation and class).

The text format below was captured live from SOLIDWORKS 2025 SP5 (``IDisplayDimension.GetText``): the first part holds
the treatment (``<HOLE-SPOT>`` counterbore, ``<HOLE-SINK>`` countersink, a thread ``M6x1.0 - 6H`` or ``1/4 NPT``) and the
second the main bore (``<MOD-DIAM> 0.25 THRU ALL`` / ``<MOD-DIAM> 0.25 <HOLE-DEPTH> 0.47``). Values are in the drawing
document's units at its precision (two decimals of an inch here), so comparisons allow the rounding.

``parse_callout`` and ``compare_callout`` are pure and tested without SolidWorks; ``round_trip`` drives the live drawing.
APIs used (all present in the installed sldworks.tlb): ``ISldWorks.NewDocument``, ``IDrawingDoc.CreateDrawViewFromModelView3``,
``IView.GetVisibleEntities2``, ``IDrawingDoc.AddHoleCallout2``, ``IDisplayDimension.GetText`` / ``IsHoleCallout``.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

NUM = r"(\d+(?:\.\d+)?)"
SW_DEFAULT_TEMPLATE_DRAWING = 10          # swUserPreferenceStringValue_e (read from swconst.tlb)
SW_DWG_PAPER_USER_DEFINED = 12            # swDwgPaperSizes_e
SW_VIEW_ENTITY_EDGE = 1                   # swViewEntityType_e
TEXT_PREFIX, TEXT_ABOVE = 1, 3            # swDimensionTextParts_e (prefix, callout above)
INCH_ROUNDING = 0.0051                    # the drawing prints two decimals of an inch
ANGLE_TOL_DEG = 0.5


def _f(m) -> Optional[float]:
    return float(m.group(1)) if m else None


def parse_callout(first: str, second: str = "") -> dict:
    """Semantics of a SOLIDWORKS hole callout from its two text parts (lengths in the drawing's units)."""
    a, b = (first or "").strip(), (second or "").strip()
    if not b:                                   # a plain hole has the bore alone in the first part
        a, b = "", a
    out: dict = {"raw": [first, second]}
    bore_dia = re.search(r"<MOD-DIAM>\s*" + NUM, b)
    out["main_diameter"] = _f(bore_dia)
    slot = re.match(r"^\s*" + NUM + r"\s*X\s*" + NUM, b)           # a slot: "0.25 X 0.79 THRU ALL" (width X overall length)
    if slot:
        out["slot_width"], out["slot_length"] = float(slot.group(1)), float(slot.group(2))
    out["through"] = bool(re.search(r"THRU\s*ALL", b, re.I))
    depth = re.search(r"<HOLE-DEPTH>\s*" + NUM, b)
    out["main_depth"] = None if out["through"] else _f(depth)
    if "<HOLE-SPOT>" in a:
        out["counterbore_diameter"] = _f(re.search(r"<HOLE-SPOT>\s*(?:<MOD-DIAM>)?\s*" + NUM, a))
        out["counterbore_depth"] = _f(re.search(r"<HOLE-DEPTH>\s*" + NUM, a))
    elif "<HOLE-SINK>" in a:
        out["countersink_diameter"] = _f(re.search(r"<HOLE-SINK>\s*(?:<MOD-DIAM>)?\s*" + NUM, a))
        out["countersink_angle"] = _f(re.search(r"X\s*" + NUM + r"\s*°", a))
    elif a:
        pipe = re.match(r"^(\S+)\s+(NPTF|NPT|BSPT|BSPP|NPS|PTF)\b", a, re.I)
        thread = re.match(r"^(\S+?)\s*-\s*(\S+)", a)
        if pipe:
            out["pipe_size"], out["pipe_standard"] = pipe.group(1), pipe.group(2).upper()
        elif thread:
            out["thread_designation"], out["thread_class"] = thread.group(1), thread.group(2)
            out["thread_depth"] = _f(re.search(r"<HOLE-DEPTH>\s*" + NUM, a))
    return out


def _designation_key(d: str) -> str:
    m = re.match(r"^M(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)$", (d or "").replace(" ", ""), re.I)
    return f"M{float(m.group(1)):g}x{float(m.group(2)):g}" if m else (d or "").replace(" ", "")


def compare_callout(intent, parsed: dict, tap_drill_in: Optional[float] = None) -> list:
    """Mismatches (``{field, intent, callout}``) between the intent and the parsed callout. Lengths are compared in
    inches within the printed precision."""
    k = 1 / 25.4 if intent.units == "mm" else 1.0
    bad: list = []

    def num(field, want, got, tol=INCH_ROUNDING):
        if want is None:
            return
        if got is None or abs(got - want * k) > tol:
            bad.append({"field": field, "intent": round(want * k, 4), "callout": got})

    if intent.family in ("hole", "counterbore", "countersink"):
        num("main_diameter", intent.diameter, parsed.get("main_diameter"))
    if intent.family in ("slot", "counterbore_slot", "countersink_slot"):
        num("slot_width", intent.slot_width, parsed.get("slot_width"))
        num("slot_length", intent.slot_length, parsed.get("slot_length"))
    if intent.family in ("straight_tap", "pipe_tap") and tap_drill_in is not None:
        num("tap_drill_diameter", tap_drill_in / k, parsed.get("main_diameter"))
    if intent.end in ("through", "up_to_next"):
        if not parsed.get("through"):
            bad.append({"field": "end_condition", "intent": "through", "callout": "blind" if parsed.get("main_depth") is not None else "?"})
    elif intent.end == "blind":
        if parsed.get("through"):
            bad.append({"field": "end_condition", "intent": "blind", "callout": "through"})
        else:
            depth = intent.drill_depth if intent.family in ("straight_tap", "pipe_tap") and intent.drill_depth else intent.depth
            num("main_depth", depth, parsed.get("main_depth"))
    if intent.family in ("counterbore", "counterbore_slot"):
        num("counterbore_diameter", intent.cbore_diameter, parsed.get("counterbore_diameter"))
        num("counterbore_depth", intent.cbore_depth, parsed.get("counterbore_depth"))
    if intent.family in ("countersink", "countersink_slot"):
        num("countersink_diameter", intent.csink_diameter, parsed.get("countersink_diameter"))
        if intent.csink_angle is not None and (parsed.get("countersink_angle") is None
                                               or abs(parsed["countersink_angle"] - intent.csink_angle) > ANGLE_TOL_DEG):
            bad.append({"field": "countersink_angle", "intent": intent.csink_angle, "callout": parsed.get("countersink_angle")})
    if intent.family == "straight_tap":
        th = intent.thread or {}
        want = _designation_key(th.get("designation") or "")
        if want and _designation_key(parsed.get("thread_designation") or "") != want:
            bad.append({"field": "thread_designation", "intent": want, "callout": parsed.get("thread_designation")})
        if th.get("class") and (parsed.get("thread_class") or "").upper() != str(th["class"]).upper():
            bad.append({"field": "thread_class", "intent": th["class"], "callout": parsed.get("thread_class")})
        if intent.end == "blind":
            num("thread_depth", intent.thread_depth, parsed.get("thread_depth"))
    if intent.family == "pipe_tap":
        th = intent.thread or {}
        size = str(th.get("size") or th.get("designation") or "").split("-")[0].strip()
        if size and parsed.get("pipe_size") != size:
            bad.append({"field": "pipe_size", "intent": size, "callout": parsed.get("pipe_size")})
        if th.get("standard") and (parsed.get("pipe_standard") or "").upper() != str(th["standard"]).upper():
            bad.append({"field": "pipe_standard", "intent": th["standard"], "callout": parsed.get("pipe_standard")})
    return bad


def round_trip(app: Any, doc: Any, part_path: str, intent, typed: Callable[[Any, str], Any],
               tap_drill_in: Optional[float] = None) -> dict:
    """Live: drawing of ``part_path``, the smallest circular edge selected, SOLIDWORKS' own Hole Callout inserted, its text
    parsed and compared. Returns ``{"status": "ok"|"failed", "parsed": ..., "mismatches": [...], "detail": ...}``.
    The drawing is closed without saving. ``doc`` is only used to keep the caller's part open."""
    template = app.GetUserPreferenceStringValue(SW_DEFAULT_TEMPLATE_DRAWING)
    if not template:
        return {"status": "failed", "detail": "no default drawing template is configured"}
    drw = app.NewDocument(template, SW_DWG_PAPER_USER_DEFINED, 0.42, 0.297)
    if drw is None:
        return {"status": "failed", "detail": "NewDocument returned no drawing"}
    try:
        dd = typed(drw, "IDrawingDoc")
        view = dd.CreateDrawViewFromModelView3(part_path, "*Top", 0.2, 0.15, 0)
        if view is None:
            return {"status": "failed", "detail": "the drawing view could not be created"}
        edges = typed(view, "IView").GetVisibleEntities2(None, SW_VIEW_ENTITY_EDGE) or ()
        circles = []
        for e in edges:
            try:
                curve = typed(typed(e, "IEdge").GetCurve(), "ICurve")
                if curve.IsCircle():
                    circles.append((curve.CircleParams[6], e))
            except Exception:   # noqa: BLE001 - a non-circular edge is simply not a candidate
                continue
        if not circles:
            return {"status": "failed", "detail": "no circular edge is visible in the drawing view"}
        circles.sort(key=lambda c: c[0])
        typed(drw, "IModelDoc2").ClearSelection2(True)
        if not typed(circles[0][1], "IEntity").Select4(False, None):
            return {"status": "failed", "detail": "the hole edge could not be selected in the drawing"}
        callout = dd.AddHoleCallout2(0.25, 0.2, 0)
        if callout is None:
            return {"status": "failed", "detail": "AddHoleCallout2 returned no callout"}
        cd = typed(callout, "IDisplayDimension")
        if not cd.IsHoleCallout():
            return {"status": "failed", "detail": "the inserted annotation is not a hole callout"}
        parsed = parse_callout(cd.GetText(TEXT_PREFIX), cd.GetText(TEXT_ABOVE))
        bad = compare_callout(intent, parsed, tap_drill_in)
        return {"status": "ok" if not bad else "failed", "parsed": parsed, "mismatches": bad,
                "detail": "" if not bad else f"{len(bad)} field(s) differ"}
    finally:
        try:
            title = typed(drw, "IModelDoc2").GetTitle
            app.CloseDoc(title() if callable(title) else title)
        except Exception:   # noqa: BLE001
            pass
