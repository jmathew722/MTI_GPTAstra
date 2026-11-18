"""Hole Wizard adapter (fake COM), placement policy and CadQuery reference geometry (Stage 4, tasks 4.7-4.10)."""
import math

import pytest

from pipeline.hole_callouts import parse
from pipeline.ir.solidworks import hole_adapter as ad
from pipeline.ir.solidworks import hole_catalog as cat
from pipeline.ir.solidworks import hole_intent as hi
from pipeline.ir.solidworks import hole_placement as pl
from pipeline.ir.solidworks import hole_reference as ref
from pipeline.ir.solidworks.hole_capabilities import BY_NAME


@pytest.fixture(autouse=True)
def _synthetic_mti_table(tmp_path, monkeypatch):
    from tools.run_hole_wizard_matrix import use_synthetic_standard
    use_synthetic_standard(tmp_path)
    monkeypatch.setenv("MTI_STANDARD_PATH", str(tmp_path / "synthetic_standard.local.json"))


# ---- fake COM ---------------------------------------------------------------------------------------------------------
class FakeData:
    def __init__(self, init_ok=True, corrupt=None):
        object.__setattr__(self, "_p", {})
        self.init_ok, self.corrupt, self.init_args = init_ok, corrupt or {}, None

    def InitializeHole(self, *a):
        self.init_args = a
        return self.init_ok

    def __setattr__(self, k, v):
        if k in ("init_ok", "corrupt", "init_args"):
            object.__setattr__(self, k, v)
        else:
            self._p[k] = v

    def __getattr__(self, k):
        if k in self._p:
            return self.corrupt.get(k, self._p[k])
        raise AttributeError(k)

    def AccessSelections(self, *a):
        pass

    def ReleaseSelectionAccess(self):
        pass


class FakeFeature:
    def __init__(self, data):
        self.data, self.deleted = data, False

    def GetDefinition(self):
        return self.data

    def Select2(self, *a):
        pass


class FakeFM:
    def __init__(self, data, null=False):
        self.data, self.null, self.calls = data, null, []

    def CreateDefinition(self, n):
        self.calls.append(("CreateDefinition", n))
        return self.data

    def CreateFeature(self, d):
        self.calls.append(("CreateFeature",))
        return None if self.null else FakeFeature(d)


class FakeDoc:
    def __init__(self):
        self.Extension = self
        self.deleted = 0

    def ClearSelection2(self, *a):
        pass

    def DeleteSelection2(self, *a):
        self.deleted += 1


def _setup(text="Ø.266 THRU ⌴ Ø.438 X .25 DEEP", units="inch", **kw):
    i = hi.from_callout(parse(text), units)
    sel = hi.select_variant(i)
    assert sel.ok, sel
    r = cat.resolve(i, sel.variant)
    assert r.ok, r.reason
    data = FakeData(**kw)
    return i, r, data, FakeFM(data), FakeDoc()


K = 0.0254


def test_create_follows_the_documented_sequence_and_reads_back_exactly():
    i, r, data, fm, doc = _setup()
    out = ad.HoleWizardAdapter(doc, fm).create(i, r, K, lambda: True)
    assert out.ok and out.mismatches == [] and doc.deleted == 0
    assert fm.calls == [("CreateDefinition", 25), ("CreateFeature",)]
    assert data.init_args == (0, r.standard, r.fastener, r.size, 1)         # counterbore (general 0), through (1)
    assert out.properties_set["CounterBoreDiameter"] == pytest.approx(0.438 * K)
    assert out.readback["Type"] == BY_NAME["swCounterBoreThru"].value and out.status == "created"


def test_a_readback_mismatch_removes_the_feature_and_is_a_failure_never_a_fallback():
    i, r, data, fm, doc = _setup(corrupt={"CounterBoreDiameter": 0.5})
    out = ad.HoleWizardAdapter(doc, fm).create(i, r, K, lambda: True)
    assert out.status == "failed" and out.code == "HW_READBACK_MISMATCH" and doc.deleted == 1
    assert out.mismatches[0]["property"] == "CounterBoreDiameter"


def test_refusals_are_structured_codes():
    i, r, data, fm, doc = _setup(init_ok=False)
    assert ad.HoleWizardAdapter(doc, fm).create(i, r, K, lambda: True).code == "HW_INIT_REFUSED"
    i, r, data, fm, doc = _setup()
    fm.null = True
    assert ad.HoleWizardAdapter(doc, fm).create(i, r, K, lambda: True).code == "HW_CREATE_NULL"
    i, r, data, fm, doc = _setup()
    assert ad.HoleWizardAdapter(doc, fm).create(i, r, K, lambda: False).code == "HW_PLACEMENT_FAILED"
    i, r, data, fm, doc = _setup()
    assert ad.HoleWizardAdapter(doc, fm).create(i, r, K, lambda: True, place_points=lambda f: False).code == "HW_PLACEMENT_FAILED"
    assert doc.deleted == 1


def test_a_com_exception_becomes_a_code_and_an_unresolved_hole_is_never_attempted():
    i, r, data, fm, doc = _setup()

    def boom(n):
        raise RuntimeError("COM died")
    fm.CreateDefinition = boom
    assert ad.HoleWizardAdapter(doc, fm).create(i, r, K, lambda: True).code == "HW_COM_ERROR"
    bad = cat.Resolution(r.variant, r.general, code="HW_FASTENER_UNMAPPED", reason="x")
    fm2 = FakeFM(FakeData())
    assert ad.HoleWizardAdapter(doc, fm2).create(i, bad, K, lambda: True).code == "HW_FASTENER_UNMAPPED"
    assert fm2.calls == []


def test_properties_outside_the_variant_are_refused_not_set():
    i, r, data, fm, doc = _setup("Ø.266 THRU")
    i.treatments["near"] = {"diameter": 0.5, "angle": 90}      # a plain hole variant has no near countersink
    out = ad.HoleWizardAdapter(doc, fm).create(i, r, K, lambda: True)
    assert out.code == "HW_PROPERTY_NOT_ALLOWED" and "NearCounterSink" in out.detail and data._p == {}


def test_angles_are_radians_and_property_set_failures_are_reported():
    i, r, data, fm, doc = _setup("Ø.266 THRU ⌵ Ø.500 X 82°")
    w = ad.expected_properties(i, r, K)
    assert w["CounterSinkAngle"] == pytest.approx(math.radians(82)) and w["CounterSinkDiameter"] == pytest.approx(0.5 * K)

    class Strict(FakeData):
        def __setattr__(self, k, v):
            if k == "Diameter":
                raise ValueError("read-only for this variant")
            super().__setattr__(k, v)
    data2 = Strict()
    assert ad.HoleWizardAdapter(doc, FakeFM(data2)).create(i, r, K, lambda: True).code == "HW_PROPERTY_SET_FAILED"


def test_compare_uses_tolerances_and_exact_strings():
    assert ad.compare({"Diameter": 0.00635, "ThreadClass": "2B"}, {"Diameter": 0.00635 + 5e-8, "ThreadClass": "2B"}) == []
    assert len(ad.compare({"Diameter": 0.00635}, {"Diameter": 0.0064})) == 1
    assert len(ad.compare({"ThreadClass": "2B"}, {"ThreadClass": "3B"})) == 1
    assert len(ad.compare({"Diameter": 1.0}, {})) == 1


# ---- 4.8 placement ----------------------------------------------------------------------------------------------------
def test_planar_checks_flag_off_face_edge_and_overlap():
    ok = pl.check_planar([(20, 20), (60, 20)], (0, 0), (100, 50), 6.0)
    assert ok == []
    codes = {x.code for x in pl.check_planar([(1, 20), (120, 20), (20, 20), (22, 20)], (0, 0), (100, 50), 6.0)}
    assert codes == {"HW_HOLE_BREAKS_EDGE", "HW_POINT_OFF_FACE", "HW_HOLES_OVERLAP"}
    assert pl.check_planar([(5, 5)], (0, 0), (100, 50), 6.0, treatment_d=12.0)[0].code == "HW_HOLE_BREAKS_EDGE"   # treatment counts


@pytest.mark.parametrize("axis,angle,expect_p,expect_d", [
    ("Z", 0, (10, 0, 5), (-1, 0, 0)), ("Z", 90, (0, 10, 5), (0, -1, 0)),
    ("X", 0, (5, 10, 0), (0, -1, 0)), ("Y", 0, (0, 5, 10), (0, 0, -1)),
])
def test_radial_points_start_on_the_surface_and_drill_toward_the_axis(axis, angle, expect_p, expect_d):
    p, d = pl.radial_point(axis, 10.0, angle, 5.0)
    assert all(abs(a - b) < 1e-9 for a, b in zip(p, expect_p)) and all(abs(a - b) < 1e-9 for a, b in zip(d, expect_d))
    with pytest.raises(ValueError):
        pl.radial_point("W", 1, 0, 0)


def test_radial_checks_and_policy():
    assert pl.check_radial([0, 90], [10, 10], 20.0, 40.0, 6.0) == []
    assert pl.check_radial([0], [2], 20.0, 40.0, 6.0)[0].code == "HW_HOLE_BREAKS_EDGE"
    assert pl.check_radial([0, 5], [10, 10], 20.0, 40.0, 6.0)[0].code == "HW_HOLES_OVERLAP"     # 1.7 mm of arc apart
    assert (pl.policy_for("planar"), pl.policy_for("cylindrical"), pl.policy_for("cone")) == ("planar", "radial", "unsupported")


# ---- 4.9 reference geometry -------------------------------------------------------------------------------------------
cq = pytest.importorskip("cadquery")


def _vol(i, t=20.0, drill=None):
    return ref.cutter(i, t, drill).val().Volume()


@pytest.mark.parametrize("text,units", [("Ø6.5 THRU", "mm"), ("Ø6.5 X 12 DEEP", "mm"), ("Ø6.6 THRU ⌴ Ø11 X 6.5 DEEP", "mm"),
                                        ("Ø6.6 THRU ⌵ Ø12 X 90°", "mm"), ("Ø6.6 THRU ⌵ Ø12.4 X 82°", "mm"),
                                        ("Ø6.5 X 12 DEEP ⌴ Ø11 X 6.5 DEEP", "mm")])
def test_cadquery_cutter_matches_the_analytic_volume(text, units):
    i = hi.from_callout(parse(text), units)
    assert _vol(i) == pytest.approx(ref.analytic_volume(i, 20.0), rel=1e-3)


def test_blind_holes_include_the_118_degree_drill_point_and_through_holes_do_not():
    thru = hi.HoleIntent(family="hole", end="through", diameter=6.0)
    blind = hi.HoleIntent(family="hole", end="blind", diameter=6.0, depth=10.0)
    r = 3.0
    assert ref.analytic_volume(thru, 20.0) == pytest.approx(math.pi * r * r * 20)
    cyl = math.pi * r * r * 10
    cone = math.pi * r * r * (r / math.tan(math.radians(59))) / 3
    assert ref.analytic_volume(blind, 20.0) == pytest.approx(cyl + cone)


def test_tap_removes_the_tap_drill_only_and_slots_are_obrounds():
    tap = hi.from_callout(parse("M6 X 1 - 6H"), "mm")
    assert ref.analytic_volume(tap, 10.0, tap_drill=5.0) == pytest.approx(math.pi * 2.5 ** 2 * 10)
    slot = hi.HoleIntent(family="slot", end="through", slot_width=6.0, slot_length=20.0)
    exp = (math.pi * 9 + 6 * 14) * 10
    assert ref.analytic_volume(slot, 10.0) == pytest.approx(exp) and _vol(slot, 10.0) == pytest.approx(exp, rel=1e-3)


def test_unmodeled_reference_families_say_so_instead_of_approximating():
    cbs = hi.HoleIntent(family="counterbore_slot", end="through", slot_width=6, slot_length=20, cbore_depth=3)
    with pytest.raises(ref.ReferenceUnsupported):
        ref.analytic_volume(cbs, 10.0)
    with pytest.raises(ref.ReferenceUnsupported):
        ref.cutter(cbs, 10.0)
