"""Typed Hole Wizard creation adapter with definition readback (Stage 4, tasks 4.7 and 4.10).

One path for every family: ``CreateDefinition`` -> ``InitializeHole`` -> set only the properties the variant allows ->
``CreateFeature`` -> read the definition back and compare. It NEVER substitutes a plain cut: every outcome is a
``HoleOutcome`` with a structured code, and a refusal, a null feature or a readback mismatch leaves no feature behind
(the feature is deleted) and is reported as a failure.

Codes: ``HW_CREATE_NULL`` (CreateFeature returned nothing), ``HW_INIT_REFUSED`` (InitializeHole returned False),
``HW_PROPERTY_NOT_ALLOWED`` (a property the variant does not have; nothing is set), ``HW_PROPERTY_SET_FAILED``,
``HW_READBACK_MISMATCH``, ``HW_PLACEMENT_FAILED``, ``HW_COM_ERROR``. ``HW_DIALOG_BLOCKED`` (InitializeHole never
returns, seen in error log E037) cannot be caught in-process; the live matrix runs each variant in a child process
with a watchdog and records it.

The COM objects are injected, so the whole flow is tested against fakes without SolidWorks.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pipeline.ir.solidworks.hole_catalog import Resolution
from pipeline.ir.solidworks.hole_intent import HoleIntent

SW_FM_HOLE_WIZARD = 25            # swFeatureNameID_e.swFmHoleWzd (verified by CreateDefinition in this session)
END_COND = {"blind": 0, "through": 1, "up_to_next": 11}    # swEndConditions_e (swconst.tlb): Blind 0, ThroughAll 1, UpToNext 11
LINEAR_TOL_M = 1e-7
ANGLE_TOL_DEG = 1e-6


@dataclass
class HoleOutcome:
    status: str                              # created | failed
    code: Optional[str] = None
    detail: str = ""
    feature: Any = None
    properties_set: dict = field(default_factory=dict)
    readback: dict = field(default_factory=dict)
    mismatches: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "created"


def expected_properties(intent: HoleIntent, res: Resolution, k: float) -> dict:
    """The IWizardHoleFeatureData2 values to set, in meters / degrees-as-radians, restricted to properties this variant
    has. ``k`` converts the intent's units to meters. A value absent from the intent is absent here: nothing is
    defaulted (the Hole Wizard default for it stays)."""
    v = res.variant
    allowed = set(v.properties)
    want: dict = {}

    def put(name, value, angle=False):
        if value is None:
            return
        if name not in allowed:
            raise _NotAllowed(name)
        want[name] = math.radians(value) if angle else value * k

    if v.family not in ("straight_tap", "pipe_tap") and intent.diameter is not None:
        put("Diameter", intent.diameter)
    if intent.end == "blind" and intent.depth is not None:
        put("Depth", intent.depth)
    if v.family in ("counterbore", "counterbore_slot"):
        put("CounterBoreDiameter", intent.cbore_diameter)
        put("CounterBoreDepth", intent.cbore_depth)
    if v.family in ("countersink", "countersink_slot"):
        put("CounterSinkDiameter", intent.csink_diameter)
        put("CounterSinkAngle", intent.csink_angle, angle=True)
    for side, key in (("near", "Near"), ("middle", "Mid"), ("far", "Far")):
        t = intent.treatments.get(side)
        if t:
            put(f"{key}CounterSinkDiameter", t.get("diameter"))
            put(f"{key}CounterSinkAngle", t.get("angle"), angle=True)
    if v.family in ("straight_tap", "pipe_tap"):
        put("ThreadDepth", intent.thread_depth)
        put("TapDrillDepth", intent.drill_depth)
        cls = (intent.thread or {}).get("class")
        if cls:
            if "ThreadClass" not in allowed:
                raise _NotAllowed("ThreadClass")
            want["ThreadClass"] = str(cls)
    if v.family in ("slot", "counterbore_slot", "countersink_slot"):
        put("Length", intent.slot_length)
    return want


class _NotAllowed(Exception):
    def __init__(self, name):
        self.name = name


def compare(want: dict, got: dict) -> list:
    out = []
    for name, w in want.items():
        g = got.get(name)
        if isinstance(w, str):
            ok = g == w
        else:
            tol = ANGLE_TOL_DEG * math.pi / 180 if "Angle" in name else LINEAR_TOL_M
            ok = isinstance(g, (int, float)) and abs(g - w) <= tol
        if not ok:
            out.append({"property": name, "wanted": w, "got": g})
    return out


class HoleWizardAdapter:
    """``fm`` = IFeatureManager, ``doc`` = IModelDoc2 (both injectable). ``typed`` converts an object to a named
    interface (``solidworks_builder.typed``); tests pass an identity function."""

    def __init__(self, doc: Any, fm: Any, typed: Optional[Callable[[Any, str], Any]] = None,
                 delete_feature: Optional[Callable[[Any], None]] = None):
        self.doc, self.fm = doc, fm
        self.typed = typed or (lambda o, i: o)
        self.delete_feature = delete_feature or self._delete

    def _delete(self, feat):
        self.doc.ClearSelection2(True)
        self.typed(feat, "IFeature").Select2(False, 0)
        self.doc.Extension.DeleteSelection2(2)

    def create(self, intent: HoleIntent, res: Resolution, k: float, select_face: Callable[[], bool],
               place_points: Optional[Callable[[Any], bool]] = None) -> HoleOutcome:
        if not res.ok:
            return HoleOutcome("failed", res.code, res.reason)
        try:
            want = expected_properties(intent, res, k)
        except _NotAllowed as e:
            return HoleOutcome("failed", "HW_PROPERTY_NOT_ALLOWED", f"{res.variant.name} has no property {e.name}")
        end = "up_to_next" if intent.end == "up_to_next" else intent.end
        try:
            defn = self.fm.CreateDefinition(SW_FM_HOLE_WIZARD)
            data = self.typed(defn, "IWizardHoleFeatureData2")
            if not select_face():
                return HoleOutcome("failed", "HW_PLACEMENT_FAILED", "no start face could be selected")
            if not data.InitializeHole(res.variant.general, res.standard, res.fastener, res.size, END_COND[end]):
                return HoleOutcome("failed", "HW_INIT_REFUSED", "InitializeHole returned False for this combination")
            data.Type = res.variant.value
            set_ok = {}
            for name, value in want.items():
                try:
                    setattr(data, name, value)
                except Exception as e:
                    return HoleOutcome("failed", "HW_PROPERTY_SET_FAILED", f"{name}: {type(e).__name__}: {str(e)[:80]}", properties_set=set_ok)
                set_ok[name] = value
            feat = self.fm.CreateFeature(data)
        except Exception as e:
            return HoleOutcome("failed", "HW_COM_ERROR", f"{type(e).__name__}: {str(e)[:120]}")
        if feat is None:
            return HoleOutcome("failed", "HW_CREATE_NULL", "CreateFeature returned no feature", properties_set=set_ok)
        if place_points is not None and not place_points(feat):
            self.delete_feature(feat)
            return HoleOutcome("failed", "HW_PLACEMENT_FAILED", "the placement points could not be set; feature removed", properties_set=set_ok)
        back = self.read_back(feat, list(want) + ["Type"])
        mism = compare(want, back)
        if back.get("Type") != res.variant.value:
            mism.append({"property": "Type", "wanted": res.variant.value, "got": back.get("Type")})
        if mism:
            self.delete_feature(feat)
            return HoleOutcome("failed", "HW_READBACK_MISMATCH", f"{len(mism)} property(ies) differ; feature removed",
                               properties_set=set_ok, readback=back, mismatches=mism)
        return HoleOutcome("created", feature=feat, properties_set=set_ok, readback=back)

    def read_back(self, feat: Any, names: list) -> dict:
        d = self.typed(self.typed(feat, "IFeature").GetDefinition(), "IWizardHoleFeatureData2")
        d.AccessSelections(self.doc, None)
        try:
            out = {}
            for n in names:
                try:
                    out[n] = getattr(d, n)
                except Exception:
                    out[n] = None
            return out
        finally:
            d.ReleaseSelectionAccess()
