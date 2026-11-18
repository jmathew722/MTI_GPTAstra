"""Versioned hole-intent IR and variant selection (Stage 4, tasks 4.3 and 4.6).

A ``HoleIntent`` says what the drawing asks for (family, end condition, diameters, treatments, thread) with the
source and confidence of every decision. ``select_variant`` maps it onto exactly one ``swWzdHoleTypes_e`` member of
the registry, or says why it cannot. Nothing is guessed: a missing required field is reported (``HW_MISSING_INTENT``),
an unreadable thread is ``HW_THREAD_UNREADABLE``, two matching variants are ``HW_AMBIGUOUS_VARIANT``.

Migration: ``from_holespec`` lifts the v1 ``HoleSpec`` (thru/blind/cbore/csink/tapped); ``from_callout`` lifts a
``ParsedCallout``. Both produce the same versioned object; ``from_dict`` rejects an unknown ``schema_version``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from pipeline.ir.solidworks.hole_capabilities import GENERAL_FAMILIES, VARIANTS, Variant

SCHEMA_VERSION = 1
FAMILY_GENERAL = {v: k for k, v in GENERAL_FAMILIES.items()}
END_CONDITIONS = ("through", "blind", "up_to_next")
MODES = ("hole_wizard", "advanced_hole", "hole_series")
# intent field -> the name the registry's REQUIRED_INTENT uses
_REQ_ALIAS = {"thread_designation": "thread", "end": "end"}


class IntentError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass
class HoleIntent:
    family: str
    schema_version: int = SCHEMA_VERSION
    end: Optional[str] = None                    # through | blind | up_to_next
    units: str = "mm"
    diameter: Optional[float] = None
    depth: Optional[float] = None
    cbore_diameter: Optional[float] = None
    cbore_depth: Optional[float] = None
    csink_diameter: Optional[float] = None
    csink_angle: Optional[float] = None
    slot_width: Optional[float] = None
    slot_length: Optional[float] = None
    slot_scheme: Optional[str] = None            # overall | center_to_center (never assumed)
    treatments: dict = field(default_factory=dict)   # side (near|middle|far) -> {"diameter":..,"angle":..}
    thread: Optional[dict] = None                # {"designation","system","size","pitch"/"tpi","class","standard"}
    thread_mode: Optional[str] = None            # cosmetic | plain | thread_through | remove (MTI default: cosmetic)
    thread_depth: Optional[float] = None
    drill_depth: Optional[float] = None
    head_clearance: Optional[bool] = None
    standard: Optional[str] = None               # explicit standard, e.g. "ISO", "AnsiMetric"
    quantity: int = 1
    fit: Optional[str] = None
    mode: str = "hole_wizard"
    source: str = "unspecified"
    confidence: float = 1.0
    ambiguities: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def from_dict(d: dict) -> HoleIntent:
    v = d.get("schema_version")
    if v != SCHEMA_VERSION:
        raise IntentError("HW_INTENT_VERSION", f"hole-intent schema_version {v!r} is not supported (expected {SCHEMA_VERSION})")
    known = {k: d[k] for k in HoleIntent.__dataclass_fields__ if k in d}
    unknown = set(d) - set(HoleIntent.__dataclass_fields__)
    if unknown:
        raise IntentError("HW_INTENT_FIELD", f"unknown hole-intent field(s): {sorted(unknown)}")
    i = HoleIntent(**known)
    if i.family not in FAMILY_GENERAL:
        raise IntentError("HW_INTENT_FAMILY", f"unknown family {i.family!r}")
    if i.end is not None and i.end not in END_CONDITIONS:
        raise IntentError("HW_INTENT_END", f"unknown end condition {i.end!r}")
    if i.mode not in MODES:
        raise IntentError("HW_INTENT_MODE", f"unknown mode {i.mode!r}")
    return i


# ---- migration from the v1 HoleSpec ----------------------------------------------------------------------------
def from_holespec(spec: Any, dims: dict, units: str) -> HoleIntent:
    """Lift a v1 ``HoleSpec`` (expressions over dimension IDs) into a hole intent. Behavior-preserving: a thru/blind/cbore
    hole stays a Hole Wizard hole of the same family; ``csink`` becomes the countersink family; ``tapped`` a straight tap
    (or a pipe tap when the callout is a pipe thread)."""
    from pipeline.hole_callouts import parse
    from pipeline.ir.expr import evaluate

    def ev(e):
        return None if e in (None, "") else float(evaluate(e, dims).value)

    t = spec.type
    intent = HoleIntent(family="hole", units=units, diameter=ev(spec.d), source="v1_holespec")
    if t == "thru":
        intent.end = "through"
    elif t == "blind":
        intent.end, intent.depth = "blind", ev(spec.depth)
    elif t == "cbore":
        intent.family, intent.cbore_diameter, intent.cbore_depth = "counterbore", ev(spec.cbore_d), ev(spec.cbore_depth)
        intent.end, intent.depth = ("blind", ev(spec.depth)) if spec.depth not in (None, "") else ("through", None)
    elif t == "csink":
        intent.family, intent.csink_diameter, intent.csink_angle = "countersink", ev(spec.csink_d), ev(spec.csink_angle)
        intent.end, intent.depth = ("blind", ev(spec.depth)) if spec.depth not in (None, "") else ("through", None)
    elif t == "tapped" or spec.thread:
        pc = parse(spec.thread or "")
        intent.family = "pipe_tap" if pc.family == "pipe_tap" else "straight_tap"
        intent.thread = dict(pc.thread) if pc.thread else None
        if not intent.thread:
            intent.ambiguities.append("thread_unreadable")
        intent.thread_mode = "plain" if intent.family == "pipe_tap" else "cosmetic"
        intent.end, intent.depth = ("blind", ev(spec.depth)) if spec.depth not in (None, "") else ("through", None)
    else:
        raise IntentError("HW_INTENT_FAMILY", f"cannot migrate hole type {t!r}")
    if intent.end == "blind" and intent.depth is None:
        intent.ambiguities.append("blind_depth_missing")
    return intent


def from_callout(pc: Any, units: str) -> HoleIntent:
    """Lift a ``ParsedCallout``. Every ambiguity the parser reported is carried, and any value with a low-confidence
    rule lowers the intent's confidence; an ambiguous callout is never silently resolved."""
    if pc.family is None:
        raise IntentError("HW_INTENT_FAMILY", "the text is not a hole or thread callout")

    def val(f):
        return None if f is None else f.value

    end = val(pc.end)
    intent = HoleIntent(
        family=pc.family, units=units, end={"through": "through", "blind": "blind"}.get(end, end), diameter=val(pc.diameter),
        depth=val(pc.depth) if pc.end and val(pc.end) == "blind" or val(pc.depth) else None,
        cbore_diameter=val(pc.cbore_diameter), cbore_depth=val(pc.cbore_depth), csink_diameter=val(pc.csink_diameter),
        csink_angle=val(pc.csink_angle), slot_width=val(pc.slot_width), slot_length=val(pc.slot_length),
        slot_scheme=val(pc.slot_scheme), thread=dict(pc.thread) if pc.thread else None, thread_depth=val(pc.thread_depth),
        drill_depth=val(pc.drill_depth), quantity=int(val(pc.quantity) or 1), fit=val(pc.fit), source="callout",
        confidence=pc.confidence, ambiguities=list(pc.ambiguities))
    for side in pc.sides:
        if side in ("near", "far", "middle"):
            intent.treatments[side] = {"diameter": intent.csink_diameter, "angle": intent.csink_angle}
    if pc.family in ("straight_tap",):
        intent.thread_mode = "cosmetic"
    if pc.family == "pipe_tap":
        intent.thread_mode = "plain"
    if "advanced_hole_candidate" in pc.ambiguities:
        intent.mode = "advanced_hole"
    if intent.end == "blind" and intent.depth is None and intent.thread_depth is None and intent.drill_depth is None:
        intent.ambiguities.append("blind_depth_missing")
    return intent


# ---- variant selection ------------------------------------------------------------------------------------------
@dataclass
class Selection:
    variant: Optional[Variant]
    code: Optional[str] = None           # None when a variant was selected
    reason: str = ""
    candidates: tuple = ()
    missing: tuple = ()

    @property
    def ok(self) -> bool:
        return self.variant is not None


def missing_fields(intent: HoleIntent, variant: Variant) -> tuple:
    out = []
    for need in variant.required_intent:
        name = _REQ_ALIAS.get(need, need)
        if need == "thread_designation":
            if not (intent.thread and (intent.thread.get("designation") or intent.thread.get("size"))):
                out.append(need)
        elif need == "diameter" and intent.family in ("straight_tap", "pipe_tap"):
            continue
        elif need == "end":
            if intent.end is None:
                out.append(need)
        elif getattr(intent, name, None) in (None, ""):
            out.append(need)
    if intent.end == "blind" and intent.depth is None and intent.drill_depth is None and intent.thread_depth is None:
        out.append("depth")
    return tuple(out)


def select_variant(intent: HoleIntent) -> Selection:
    """The one ``swWzdHoleTypes_e`` member for this intent, or a structured reason. Never guesses."""
    if intent.mode == "advanced_hole":
        return Selection(None, "HW_ADVANCED_HOLE", "stacked near/far callout: Advanced Hole, a separate feature (not a Hole Wizard hole)")
    if intent.mode == "hole_series":
        return Selection(None, "HW_HOLE_SERIES_NO_API", "Hole Series has no hole method in the installed API")
    if intent.family == "legacy":
        return Selection(None, "HW_LEGACY_POLICY", "legacy hole types are never chosen from drawing text; an explicit policy is required")
    g = FAMILY_GENERAL.get(intent.family)
    if g is None:
        return Selection(None, "HW_INTENT_FAMILY", f"unknown family {intent.family!r}")
    if intent.end is None:
        return Selection(None, "HW_MISSING_INTENT", "no end condition", missing=("end",))
    if g in (3, 4) and not (intent.thread and (intent.thread.get("designation") or intent.thread.get("size"))):
        return Selection(None, "HW_THREAD_UNREADABLE", "tapped hole without a readable thread designation", missing=("thread_designation",))
    end = "through" if intent.end in ("through", "up_to_next") else "blind"
    treat = set(intent.treatments)
    mode = intent.thread_mode or ("plain" if g == 3 else "cosmetic" if g == 4 else None)
    head = True if g in (1, 7) and intent.head_clearance is None else intent.head_clearance
    cands = [v for v in VARIANTS.values()
             if v.general == g and v.end == end and set(v.treatments) == treat
             and (g not in (3, 4) or v.thread == mode)
             and (g not in (1, 7) or v.head_clearance == bool(head))]
    if not cands:
        return Selection(None, "HW_NO_VARIANT", f"no {intent.family} variant with end={end}, treatments={sorted(treat)}, thread={mode}, "
                         f"head_clearance={head}")
    if len(cands) > 1:
        return Selection(None, "HW_AMBIGUOUS_VARIANT", "more than one variant matches", candidates=tuple(c.name for c in cands))
    v = cands[0]
    miss = missing_fields(intent, v)
    if miss:
        return Selection(None, "HW_MISSING_INTENT", f"{v.name} needs {', '.join(miss)} from the drawing", candidates=(v.name,), missing=miss)
    return Selection(v)
