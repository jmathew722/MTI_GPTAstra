"""HoleIntentV2 (schema_version 2): the normalized, provenance-carrying hole record (Stage 4, Slice B).

One record per detected callout group. It keeps SEPARATE the four questions the build plan must answer:

1. what manufacturing geometry the callout describes (``general_family`` + ``geometry`` + ``thread``),
2. its end condition (``end_condition``: through_all | blind | up_to_next | unresolved),
3. which native feature should represent it (``creation_method``: hole_wizard | advanced_hole | hole_series | cut_extrude |
   unresolved) and, when the registry can say, the exact ``specific_type`` (an ``swWzdHoleTypes_e`` member name),
4. which values are explicit, inferred by a named rule, supplied by the catalog, supplied by policy, or unresolved
   (``provenance``, ``unresolved_fields``, ``conflicts``).

"THRU" is an end condition; it never decides Hole Wizard vs plain cut. The creation method comes from the callout's family
and a versioned policy (``POLICY_VERSION``) and is recorded as a policy field. Nothing missing is invented: a thread depth,
thread class, tap-drill depth, standard, or quantity the drawing does not state stays in ``unresolved_fields`` and the
record is ``needs_review``.

``from_parsed`` lifts a ``ParsedCallout``; ``from_v1`` / ``migrate`` lift the schema-1 ``HoleIntent`` (v1 stays the working
form for variant selection and catalog resolution; ``to_v1`` bridges back).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

from pipeline.ir.solidworks import hole_intent as v1

SCHEMA_VERSION = 2
POLICY_VERSION = "mti-hole-policy-1"
CREATION_METHODS = ("hole_wizard", "advanced_hole", "hole_series", "cut_extrude", "unresolved")
STATUSES = ("ready", "needs_review", "unsupported")
END_MAIN = ("through_all", "blind", "up_to_next", "unresolved")
GENERAL_FAMILIES = ("simple", "counterbore", "countersink", "straight_tap", "pipe_tap", "slot", "counterbore_slot",
                    "countersink_slot", "legacy", "unresolved")
_V1_TO_V2_FAMILY = {"hole": "simple"}
_V2_TO_V1_FAMILY = {"simple": "hole"}
_END_V1_TO_V2 = {"through": "through_all", "blind": "blind", "up_to_next": "up_to_next", None: "unresolved"}
_END_V2_TO_V1 = {"through_all": "through", "blind": "blind", "up_to_next": "up_to_next", "unresolved": None}
TAP_FAMILIES = ("straight_tap", "pipe_tap")


class IntentV2Error(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass
class HoleIntentV2:
    schema_version: int = SCHEMA_VERSION
    feature_id: str = ""
    units: str = "inch"                              # unit of every length below (the source unit is retained)
    source: dict = field(default_factory=lambda: {"document_id": "", "page": None, "view_id": None, "leader_targets": [],
                                                  "raw_lines": [], "bounding_boxes": [], "field_spans": {},
                                                  "ocr_engine": None, "ocr_confidence": None})
    creation_method: str = "unresolved"
    general_family: str = "unresolved"
    specific_type: Optional[str] = None              # swWzdHoleTypes_e member name, only when the registry selects exactly one
    standard: Optional[str] = None
    fastener_type: Optional[str] = None
    size_designation: Optional[str] = None
    quantity: Optional[int] = None
    side: Optional[str] = None                       # near | far | both | None (not stated)
    placement: dict = field(default_factory=lambda: {"face_reference": None, "centers": [], "pattern": None})
    end_condition: dict = field(default_factory=lambda: {"main": "unresolved", "main_depth": None})
    geometry: dict = field(default_factory=lambda: {
        "main_diameter": None, "counterbore_diameter": None, "counterbore_depth": None, "countersink_diameter": None,
        "countersink_angle": None, "drill_point_angle": None, "slot_length": None, "slot_width": None})
    thread: dict = field(default_factory=lambda: {
        "designation": None, "normalized_designation": None, "thread_kind": None, "series": None, "class": None,
        "handedness": None, "thread_depth": None, "tap_drill_depth": None, "standard": None, "size": None})
    tolerances: list = field(default_factory=list)
    datum: Optional[dict] = None                     # {"label": "A", "role": "datum_hole"}: association, not a hole family
    fit: Optional[str] = None
    provenance: dict = field(default_factory=lambda: {"explicit_fields": [], "inferred_fields": [], "catalog_fields": [],
                                                      "policy_fields": []})
    unresolved_fields: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    selection: dict = field(default_factory=lambda: {"code": None, "reason": ""})   # outcome of the variant registry
    status: str = "needs_review"
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def dimension(self, name: str) -> Optional[float]:
        """A length in millimetres (canonical), whatever the source unit."""
        v = self.geometry.get(name)
        if v is None:
            v = {"main_depth": self.end_condition.get("main_depth"), "thread_depth": self.thread.get("thread_depth"),
                 "tap_drill_depth": self.thread.get("tap_drill_depth")}.get(name)
        return None if v is None else float(v) * (25.4 if self.units == "inch" else 1.0)


def from_dict(d: dict) -> HoleIntentV2:
    ver = d.get("schema_version")
    if ver != SCHEMA_VERSION:
        raise IntentV2Error("HW_INTENT_VERSION", f"hole-intent schema_version {ver!r} is not v2; use migrate()")
    unknown = set(d) - set(HoleIntentV2.__dataclass_fields__)
    if unknown:
        raise IntentV2Error("HW_INTENT_FIELD", f"unknown field(s): {sorted(unknown)}")
    i = HoleIntentV2(**{k: d[k] for k in HoleIntentV2.__dataclass_fields__ if k in d})
    if i.creation_method not in CREATION_METHODS:
        raise IntentV2Error("HW_INTENT_METHOD", f"unknown creation_method {i.creation_method!r}")
    if i.general_family not in GENERAL_FAMILIES:
        raise IntentV2Error("HW_INTENT_FAMILY", f"unknown general_family {i.general_family!r}")
    if i.status not in STATUSES:
        raise IntentV2Error("HW_INTENT_STATUS", f"unknown status {i.status!r}")
    if i.end_condition.get("main") not in END_MAIN:
        raise IntentV2Error("HW_INTENT_END", f"unknown end condition {i.end_condition.get('main')!r}")
    return i


def migrate(d: dict) -> HoleIntentV2:
    """Accept a v2 dict as is, or lift a schema-1 hole-intent dict. Anything else is rejected."""
    if d.get("schema_version") == SCHEMA_VERSION:
        return from_dict(d)
    if d.get("schema_version") == v1.SCHEMA_VERSION:
        return from_v1(v1.from_dict(d))
    raise IntentV2Error("HW_INTENT_VERSION", f"cannot migrate hole-intent schema_version {d.get('schema_version')!r}")


# ---- creation method policy ------------------------------------------------------------------------------------
def _default_clearance_match(diameter: float, units: str) -> Optional[bool]:
    """True/False when the (confidential, optional) MTI table was consulted; None when it is absent."""
    try:
        from pipeline import mti_standards
        if mti_standards.table() is None:
            return None
        return bool(mti_standards.match_hole(diameter, units, ("clearance_normal", "clearance_loose")))
    except Exception:   # noqa: BLE001 - an unreadable table is "not consulted", never a crash or a guess
        return None


def creation_method_for(family: str, mode: str = "hole_wizard", diameter: Optional[float] = None, units: str = "inch",
                        clearance_match: Optional[Callable] = None) -> tuple:
    """(method, policy record). ``THRU`` plays no part. Families that are Hole Wizard families by nature use it; a plain bore
    uses Hole Wizard only when its diameter is a recorded fastener clearance, else a cut-extrude (MTI practice: "Hole Wizard for
    bolt holes, cut-extrude for the rest"). The record says whether the clearance table was actually consulted."""
    rec = {"policy": POLICY_VERSION, "field": "creation_method"}
    if mode in ("advanced_hole", "hole_series"):
        return mode, {**rec, "rule": f"callout_is_{mode}"}
    if family in ("legacy", "unresolved", None):
        return "unresolved", {**rec, "rule": "no_family"}
    if family != "simple":
        return "hole_wizard", {**rec, "rule": "wizard_family"}
    if diameter is None:
        return "unresolved", {**rec, "rule": "plain_bore_without_diameter"}
    match = (clearance_match or _default_clearance_match)(diameter, units)
    if match:
        return "hole_wizard", {**rec, "rule": "plain_bore_matches_fastener_clearance", "clearance_consulted": True}
    return "cut_extrude", {**rec, "rule": "plain_non_fastener_bore_is_cut_extrude", "clearance_consulted": match is not None}


# ---- lifting a parsed callout -----------------------------------------------------------------------------------
_FIELD_TO_PATH = {
    "quantity": "quantity", "diameter": "geometry.main_diameter", "end": "end_condition.main", "depth": "end_condition.main_depth",
    "cbore_diameter": "geometry.counterbore_diameter", "cbore_depth": "geometry.counterbore_depth",
    "csink_diameter": "geometry.countersink_diameter", "csink_angle": "geometry.countersink_angle",
    "slot_width": "geometry.slot_width", "slot_length": "geometry.slot_length", "thread_depth": "thread.thread_depth",
    "drill_depth": "thread.tap_drill_depth", "fit": "fit", "datum": "datum", "slot_scheme": "slot_scheme"}
_INFERRED_RULES = ("implied_by_depth",)


def _tol_field(name: str) -> str:
    return {"counterbore_diameter": "geometry.counterbore_diameter", "counterbore_depth": "geometry.counterbore_depth",
            "diameter": "geometry.main_diameter"}.get(name, name)


def from_parsed(pc: Any, units: str, *, feature_id: str = "", document_id: str = "", page: Optional[int] = None,
                view_id: Optional[str] = None, leader_targets: Optional[list] = None, bounding_boxes: Optional[list] = None,
                ocr_engine: Optional[str] = None, ocr_confidence: Optional[float] = None,
                clearance_match: Optional[Callable] = None) -> HoleIntentV2:
    if pc.family is None:
        raise IntentV2Error("HW_INTENT_FAMILY", "the text is not a hole or thread callout")
    i = HoleIntentV2(feature_id=feature_id, units=units, confidence=pc.confidence)
    lines = pc.raw.split("\n")
    i.source.update(document_id=document_id, page=page, view_id=view_id, leader_targets=list(leader_targets or []),
                    raw_lines=lines, bounding_boxes=list(bounding_boxes or []), ocr_engine=ocr_engine, ocr_confidence=ocr_confidence)
    explicit: list = []
    inferred: list = []

    def note(fname: str, f: Any) -> None:
        path = _FIELD_TO_PATH[fname]
        i.source["field_spans"][path] = {"span": list(f.span), "line": pc.raw[:int(f.span[0])].count("\n"), "rule": f.rule,
                                         "confidence": f.confidence}
        (inferred if f.rule in _INFERRED_RULES else explicit).append(
            {"field": path, "rule": f.rule, "confidence": f.confidence} if f.rule in _INFERRED_RULES else path)

    for fname in ("quantity", "diameter", "depth", "cbore_diameter", "cbore_depth", "csink_diameter", "csink_angle",
                  "slot_width", "slot_length", "thread_depth", "drill_depth", "fit", "slot_scheme"):
        f = getattr(pc, fname)
        if f is None:
            continue
        note(fname, f)
        if fname == "quantity":
            i.quantity = int(f.value)
        elif fname == "diameter":
            i.geometry["main_diameter"] = f.value
        elif fname == "depth":
            i.end_condition["main_depth"] = f.value
        elif fname == "cbore_diameter":
            i.geometry["counterbore_diameter"] = f.value
        elif fname == "cbore_depth":
            i.geometry["counterbore_depth"] = f.value
        elif fname == "csink_diameter":
            i.geometry["countersink_diameter"] = f.value
        elif fname == "csink_angle":
            i.geometry["countersink_angle"] = f.value
        elif fname == "slot_width":
            i.geometry["slot_width"] = f.value
        elif fname == "slot_length":
            i.geometry["slot_length"] = f.value
        elif fname == "thread_depth":
            i.thread["thread_depth"] = f.value
        elif fname == "drill_depth":
            i.thread["tap_drill_depth"] = f.value
        elif fname == "fit":
            i.fit = f.value
    if pc.end is not None:
        note("end", pc.end)
        i.end_condition["main"] = {"through": "through_all", "blind": "blind"}.get(pc.end.value, pc.end.value)
    if pc.datum is not None:
        i.datum = {"label": pc.datum.value, "role": "datum_hole"}
        note("datum", pc.datum)
    i.general_family = _V1_TO_V2_FAMILY.get(pc.family, pc.family)
    # thread block ------------------------------------------------------------------------------------------------
    if pc.thread:
        t = pc.thread
        i.thread.update(designation=t.get("designation"), normalized_designation=t.get("normalized_designation") or t.get("designation"),
                        thread_kind="tapered_pipe" if t["kind"] == "pipe" else "straight", series=t.get("series"),
                        **{"class": t.get("class")}, standard=t.get("standard"), size=t.get("size_normalized") or t.get("size"))
        i.size_designation = i.thread["normalized_designation"]
        explicit.append("thread.designation")
        if t.get("series"):
            explicit.append("thread.series")
        if t.get("class"):
            explicit.append("thread.class")
        if t.get("standard"):
            explicit.append("thread.standard")          # the THREAD standard (NPT, ...); the Hole Wizard standard is separate
        if i.units in ("inch", "mm") and t.get("system") in ("inch", "metric"):
            cand = "ANSI Inch" if t.get("system") == "inch" else "ANSI Metric"
            inferred.append({"field": "standard", "value": cand, "rule": "thread_system_candidate", "confidence": 0.6,
                             "note": "candidate only; confirm against the installed catalog"})
        if t.get("inferred"):
            inferred.append({"field": "thread.series", "value": t["inferred"]["series"], "rule": t["inferred"]["rule"],
                             "confidence": t["inferred"]["confidence"], "note": "candidate only; the drawing did not write it"})
    if "advanced_hole_candidate" in pc.ambiguities:
        i.creation_method = "advanced_hole"
        i.side = "both"
    elif pc.sides:
        i.side = "both" if set(pc.sides) >= {"near", "far"} else pc.sides[0]
    # tolerances ---------------------------------------------------------------------------------------------------
    for tl in pc.tolerances:
        i.tolerances.append({"field": _tol_field(tl["field"]), "kind": tl["kind"], "plus": tl["plus"], "minus": tl["minus"],
                             "units": units, "span": tl["span"], "rule": tl["rule"]})
    if pc.tolerance is not None and not pc.tolerances:
        i.tolerances.append({"field": "unspecified", "kind": "bilateral", "plus": pc.tolerance.value, "minus": pc.tolerance.value,
                             "units": units, "span": list(pc.tolerance.span), "rule": pc.tolerance.rule})
    # creation method: family + policy, never THRU ------------------------------------------------------------------
    mode = "advanced_hole" if i.creation_method == "advanced_hole" else "hole_wizard"
    method, pol = creation_method_for(i.general_family, mode, i.geometry["main_diameter"], units, clearance_match)
    i.creation_method = method
    i.provenance["policy_fields"].append(pol)
    i.provenance["explicit_fields"], i.provenance["inferred_fields"] = explicit, inferred
    _finish(i, pc.ambiguities)
    return i


def _finish(i: HoleIntentV2, ambiguities: list) -> None:
    """unresolved_fields, conflicts, specific_type and status. Nothing here fills a value in."""
    unresolved: list = []
    if i.end_condition["main"] == "unresolved":
        unresolved.append("end_condition.main")
    if i.end_condition["main"] == "blind" and i.end_condition["main_depth"] is None and i.thread["thread_depth"] is None \
            and i.thread["tap_drill_depth"] is None:
        unresolved.append("end_condition.main_depth")
    if i.quantity is None:
        unresolved.append("quantity")
    fam = i.general_family
    if fam in TAP_FAMILIES:
        if not i.thread["designation"]:
            unresolved.append("thread.designation")
        if i.thread["thread_depth"] is None:
            unresolved.append("thread.thread_depth")
        if fam == "straight_tap" and i.thread["class"] is None:
            unresolved.append("thread.class")
        if i.end_condition["main"] == "blind" and i.thread["tap_drill_depth"] is None and i.end_condition["main_depth"] is None:
            unresolved.append("thread.tap_drill_depth")
        if i.standard is None:
            unresolved.append("standard")               # a catalog-confirmed Hole Wizard standard is required, never assumed
        if fam == "straight_tap" and i.end_condition["main"] == "blind" and i.thread["tap_drill_depth"] is None \
                and i.end_condition["main_depth"] is not None and "thread.tap_drill_depth" not in unresolved:
            unresolved.append("thread.tap_drill_depth")
    if fam == "counterbore":
        for n, p in (("counterbore_diameter", "geometry.counterbore_diameter"), ("counterbore_depth", "geometry.counterbore_depth")):
            if i.geometry[n] is None:
                unresolved.append(p)
    if fam in ("countersink", "countersink_slot") and i.geometry["countersink_angle"] is None:
        unresolved.append("geometry.countersink_angle")
    if fam in ("slot", "counterbore_slot", "countersink_slot") and "slot_length_scheme_unspecified" in ambiguities:
        unresolved.append("slot_length_scheme")
    if fam not in TAP_FAMILIES and fam != "unresolved" and fam not in ("slot", "counterbore_slot", "countersink_slot") \
            and i.geometry["main_diameter"] is None:
        unresolved.append("geometry.main_diameter")
    for a in ambiguities:
        if a in ("depth_applies_to_thread_or_drill", "pipe_standard_unspecified", "thread_size_not_a_standard_fraction",
                 "metric_pitch_unspecified"):
            unresolved.append(f"ambiguity:{a}")
    i.unresolved_fields = list(dict.fromkeys(unresolved))
    # conflicts: contradictions in the stated values (kept, never resolved by picking one) -----------------------------
    d = i.geometry["main_diameter"]
    if i.end_condition["main"] == "through_all" and i.end_condition["main_depth"] is not None:
        i.conflicts.append({"fields": ["end_condition.main", "end_condition.main_depth"], "code": "through_with_depth",
                            "detail": "the callout states THRU and also a main depth"})
    if fam == "counterbore" and d is not None and i.geometry["counterbore_diameter"] is not None \
            and i.geometry["counterbore_diameter"] <= d:
        i.conflicts.append({"fields": ["geometry.counterbore_diameter", "geometry.main_diameter"], "code": "counterbore_not_larger",
                            "detail": "counterbore diameter is not larger than the main bore"})
    if fam == "countersink" and d is not None and i.geometry["countersink_diameter"] is not None \
            and i.geometry["countersink_diameter"] <= d:
        i.conflicts.append({"fields": ["geometry.countersink_diameter", "geometry.main_diameter"], "code": "countersink_not_larger",
                            "detail": "countersink diameter is not larger than the main bore"})
    # the registry's answer (a variant is named only when exactly one matches) -------------------------------------------
    if i.creation_method == "hole_wizard":
        sel = v1.select_variant(to_v1(i))
        i.selection = {"code": sel.code, "reason": sel.reason, "missing": list(sel.missing)}
        i.specific_type = sel.variant.name if sel.ok else None
    elif i.creation_method == "advanced_hole":
        i.selection = {"code": "HW_ADVANCED_HOLE", "reason": "separate native feature; no basic Hole Wizard substitute", "missing": []}
    elif i.creation_method == "hole_series":
        i.selection = {"code": "HW_HOLE_SERIES_NO_API", "reason": "Hole Series is a separate native feature", "missing": []}
    if i.creation_method in ("advanced_hole", "hole_series") or fam == "legacy":
        i.status = "unsupported"
    elif i.unresolved_fields or i.conflicts or i.creation_method == "unresolved":
        i.status = "needs_review"
    elif i.creation_method == "hole_wizard" and i.specific_type is None:
        i.status = "needs_review"
    else:
        i.status = "ready"


# ---- bridges to / from schema 1 ----------------------------------------------------------------------------------
def to_v1(i: HoleIntentV2) -> v1.HoleIntent:
    """The schema-1 working form (variant selection, catalog resolution, adapter). Lossy by design: provenance, tolerances,
    conflicts and source spans stay on the v2 record."""
    t = i.thread
    thread = None
    if t.get("designation"):
        thread = {"designation": t["designation"], "size": t.get("size"), "kind": "pipe" if t["thread_kind"] == "tapered_pipe" else "straight",
                  "system": "inch" if i.units == "inch" else "metric", "class": t.get("class"), "series": t.get("series"),
                  "standard": t.get("standard")}
    if thread and thread["kind"] == "straight" and i.units == "inch":
        import re
        m = re.search(r"-\s*(\d+)", t.get("normalized_designation") or "")
        if m:
            thread["tpi"] = int(m.group(1))
    fam = _V2_TO_V1_FAMILY.get(i.general_family, i.general_family)
    g = i.geometry
    main = i.end_condition["main"]
    mode = {"advanced_hole": "advanced_hole", "hole_series": "hole_series"}.get(i.creation_method, "hole_wizard")
    return v1.HoleIntent(
        family=fam if fam != "unresolved" else "hole", units=i.units, end=_END_V2_TO_V1.get(main),
        diameter=g["main_diameter"], depth=i.end_condition["main_depth"], cbore_diameter=g["counterbore_diameter"],
        cbore_depth=g["counterbore_depth"], csink_diameter=g["countersink_diameter"], csink_angle=g["countersink_angle"],
        slot_width=g["slot_width"], slot_length=g["slot_length"], thread=thread,
        thread_mode=("plain" if fam == "pipe_tap" else "cosmetic" if fam == "straight_tap" else None),
        thread_depth=t.get("thread_depth"), drill_depth=t.get("tap_drill_depth"), quantity=i.quantity or 1, fit=i.fit, mode=mode,
        source="v2", confidence=i.confidence, ambiguities=list(i.unresolved_fields))


def from_v1(old: v1.HoleIntent, *, feature_id: str = "", clearance_match: Optional[Callable] = None) -> HoleIntentV2:
    """Lift a schema-1 intent. Everything v1 carried becomes an explicit field of unknown provenance ("migrated_v1"); nothing is
    added. A v1 'through' stays an end condition and does not decide the creation method."""
    i = HoleIntentV2(feature_id=feature_id, units=old.units, confidence=old.confidence)
    i.source["raw_lines"] = []
    i.general_family = _V1_TO_V2_FAMILY.get(old.family, old.family)
    i.quantity = old.quantity
    i.end_condition = {"main": _END_V1_TO_V2.get(old.end, "unresolved"), "main_depth": old.depth}
    i.geometry.update(main_diameter=old.diameter, counterbore_diameter=old.cbore_diameter, counterbore_depth=old.cbore_depth,
                      countersink_diameter=old.csink_diameter, countersink_angle=old.csink_angle, slot_width=old.slot_width,
                      slot_length=old.slot_length)
    if old.thread:
        t = old.thread
        i.thread.update(designation=t.get("designation"), normalized_designation=t.get("normalized_designation") or t.get("designation"),
                        thread_kind="tapered_pipe" if t.get("kind") == "pipe" else "straight", series=t.get("series"),
                        **{"class": t.get("class")}, standard=t.get("standard"), size=t.get("size"))
        i.size_designation = i.thread["normalized_designation"]
    i.thread.update(thread_depth=old.thread_depth, tap_drill_depth=old.drill_depth)
    i.fit = old.fit
    i.standard = old.standard
    if old.treatments:
        i.side = "both" if {"near", "far"} <= set(old.treatments) else next(iter(old.treatments))
    mode = old.mode if old.mode in ("advanced_hole", "hole_series") else "hole_wizard"
    method, pol = creation_method_for(i.general_family, mode, old.diameter, old.units, clearance_match)
    i.creation_method = method
    i.provenance["policy_fields"].append(pol)
    i.provenance["explicit_fields"] = ["migrated_v1:all"]
    _finish(i, [a for a in old.ambiguities])
    return i
