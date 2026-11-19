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
    unrepresented: list = field(default_factory=list)   # intent fields Hole Wizard cannot store (kept on the intent, reported)
    path: str = "definition"                              # definition | holewizard5

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
        # The main bore. The bare "Diameter" property reads 0 on 2025 SP5 (live); a blind bore is HoleDiameter and a through
        # bore is ThruHoleDiameter (HoleDiameter reads 0 on a through type, live).
        put("ThruHoleDiameter" if intent.end in ("through", "up_to_next") else "HoleDiameter", intent.diameter)
    if intent.end == "blind" and intent.depth is not None and v.family not in ("straight_tap", "pipe_tap"):
        put("HoleDepth", intent.depth)
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
        put("TapDrillDepth", intent.drill_depth if intent.drill_depth is not None else (intent.depth if intent.end == "blind" else None))
        cls = (intent.thread or {}).get("class")
        if cls and not _is_metric(res):          # a metric Hole Wizard thread has no class property (reads ""): see unrepresented()
            if "ThreadClass" not in allowed:
                raise _NotAllowed("ThreadClass")
            want["ThreadClass"] = str(cls)
    if v.family in ("slot", "counterbore_slot", "countersink_slot"):
        # Hole Wizard's Length is the CENTER-TO-CENTER distance of the two end arcs (live: Length 20 mm, width 6.4 removes
        # pi*r^2 + w*20); the intent's slot_length is the OVERALL length.
        if intent.slot_length is not None and intent.slot_width is not None:
            put("Length", max(intent.slot_length - intent.slot_width, 0.0))
    return want


def _is_metric(res: Resolution) -> bool:
    return str(res.standard_name or "").endswith("Metric")


def unrepresented(intent: HoleIntent, res: Resolution) -> list:
    """Intent fields the installed Hole Wizard cannot store, so they are NOT set and NOT compared: they stay on the intent
    and are reported (an info finding), never silently dropped. Verified live on SOLIDWORKS 2025 SP5."""
    out = []
    if res.variant.family in ("straight_tap", "pipe_tap") and (intent.thread or {}).get("class") and _is_metric(res):
        out.append({"field": "thread_class", "value": str((intent.thread or {}).get("class")),
                    "reason": "a metric Hole Wizard thread has no class property (ANSI Metric reads back an empty class)"})
    return out


# Properties whose setter raises a COM exception on SOLIDWORKS 2025 SP5 although the value is taken (seen live); the
# definition readback after CreateFeature is what verifies them.
SPURIOUS_SET_EXCEPTION = {"HoleDepth", "ThruHoleDepth", "TapDrillDepth", "ThruTapDrillDepth", "Length"}
# HoleWizard5 recipes: options that only take effect at creation (error log E022) go in through its Value arguments.
HW5_VARIANTS = {"swTapBlindCosmeticThread"}
# Slots: the definition flow's InitializeHole turns a slot into a round hole (live: Type 22/25), HoleWizard5 makes the slot.
# Value1/Value2 = counterbore diameter/depth, or countersink diameter/angle(rad) (mapped live with marker values).
HW5_FAMILIES = {"slot", "counterbore_slot", "countersink_slot"}
HW5_VALUE_THREAD_DEPTH, HW5_VALUE_COSMETIC = 0, 6          # Value1 = thread depth (m), Value7 = swCosmeticThreadWithCallout (1)


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
        if res.variant.name in HW5_VARIANTS or res.variant.family in HW5_FAMILIES:
            return self._create_hw5(intent, res, k, want, select_face, place_points)
        try:
            defn = self.fm.CreateDefinition(SW_FM_HOLE_WIZARD)
            data = self.typed(defn, "IWizardHoleFeatureData2")
            if not select_face():
                return HoleOutcome("failed", "HW_PLACEMENT_FAILED", "no start face could be selected")
            # IWizardHoleFeatureData2.InitializeHole is a VOID method in the 2025 type library (returns None through COM);
            # only an explicit False (test doubles, other bindings) is a refusal. A bad combination then shows up as a null
            # CreateFeature or a readback mismatch, both structured failures.
            if data.InitializeHole(res.variant.general, res.standard, res.fastener, res.size, END_COND[end]) is False:
                return HoleOutcome("failed", "HW_INIT_REFUSED", "InitializeHole returned False for this combination")
            # InitializeHole derives the type from the general family and end condition; assigning Type is refused by COM
            # for some variants, so only try when it differs and let the definition readback decide.
            try:
                cur = data.Type
            except Exception:
                cur = None
            if cur != res.variant.value:
                try:
                    data.Type = res.variant.value
                except Exception:
                    pass
            set_ok = {}
            for name, value in want.items():
                try:
                    setattr(data, name, value)
                except Exception as e:
                    try:
                        got = getattr(data, name)
                    except Exception:
                        got = None
                    if name in SPURIOUS_SET_EXCEPTION:
                        pass                                    # taken despite the exception; the readback after creation decides
                    elif got is None or compare({name: value}, {name: got}):
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
        return HoleOutcome("created", feature=feat, properties_set=set_ok, readback=back, unrepresented=unrepresented(intent, res))

    def _create_hw5(self, intent: HoleIntent, res: Resolution, k: float, want: dict, select_face, place_points) -> HoleOutcome:
        """HoleWizard5 recipe for options the definition flow cannot set (cosmetic thread type). Same verification as the
        definition flow: readback, delete on mismatch, no plain-cut fallback."""
        values = [-1.0] * 12
        fam = res.variant.family
        slot = fam in HW5_FAMILIES
        blind = intent.end == "blind"
        diameter, length, check = -1.0, -1.0, None
        if slot:
            diameter = (intent.slot_width if intent.slot_width is not None else intent.diameter or -1.0) * (k if intent.slot_width or intent.diameter else 1.0)
            if intent.slot_length is not None and intent.slot_width is not None:
                length = max(intent.slot_length - intent.slot_width, 0.0) * k
            if fam == "counterbore_slot":
                values[0], values[1] = (intent.cbore_diameter or -1.0) * k, (intent.cbore_depth or -1.0) * k
            elif fam == "countersink_slot":
                values[0] = (intent.csink_diameter or -1.0) * k
                values[1] = math.radians(intent.csink_angle) if intent.csink_angle is not None else -1.0
            depth = (intent.depth or 0.0) * k if blind else 0.0
            end_code = 0 if blind else END_COND["through"]
            check = dict(want)
        else:
            if intent.thread_depth is not None:
                values[HW5_VALUE_THREAD_DEPTH] = intent.thread_depth * k
            values[HW5_VALUE_COSMETIC] = 1.0
            depth = (intent.drill_depth or intent.depth or 0.0) * k if blind else 0.0
            end_code = 0 if blind else END_COND["up_to_next"]
        try:
            if not select_face():
                return HoleOutcome("failed", "HW_PLACEMENT_FAILED", "no start face could be selected", path="holewizard5")
            feat = self.fm.HoleWizard5(res.variant.general, res.standard, res.fastener, res.size, end_code,
                                       diameter, depth, length, *values, "", False, True, True, True, True, False)
        except Exception as e:
            return HoleOutcome("failed", "HW_COM_ERROR", f"{type(e).__name__}: {str(e)[:120]}", path="holewizard5")
        if feat is None:
            return HoleOutcome("failed", "HW_CREATE_NULL", "HoleWizard5 returned no feature", path="holewizard5")
        if place_points is not None and not place_points(feat):
            self.delete_feature(feat)
            return HoleOutcome("failed", "HW_PLACEMENT_FAILED", "the placement points could not be set; feature removed", path="holewizard5")
        if check is None:
            check = {n: x for n, x in want.items() if n in ("ThreadDepth", "TapDrillDepth", "ThreadClass")}
            check["CosmeticThreadType"] = 1
        back = self.read_back(feat, list(check) + ["Type"])
        mism = compare(check, back)
        if back.get("Type") != res.variant.value:
            mism.append({"property": "Type", "wanted": res.variant.value, "got": back.get("Type")})
        if mism:
            self.delete_feature(feat)
            return HoleOutcome("failed", "HW_READBACK_MISMATCH", f"{len(mism)} property(ies) differ; feature removed",
                               properties_set=check, readback=back, mismatches=mism, path="holewizard5")
        return HoleOutcome("created", feature=feat, properties_set=check, readback=back, path="holewizard5",
                           unrepresented=unrepresented(intent, res))

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
