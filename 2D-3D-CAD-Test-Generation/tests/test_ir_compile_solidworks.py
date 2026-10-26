"""Feature IR v2, Task 6: SolidWorks compiler, the parts that run on any OS.

The COM build itself is verified live (ir_build.py --solidworks; all 5 golden plans
match the CadQuery reference feature by feature, 2026-10-04). These tests pin the
plane-map math measured on that SW 2025 template.
"""
import pytest

from pipeline.ir.compile_solidworks import PlaneMap

# Measured by probe_plane_map on the SW 2025 SP5 template (Z-up): Front = model YZ, +X normal.
SW2025 = PlaneMap({
    "Front Plane": ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
    "Top Plane": ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
    "Right Plane": ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
})


def test_ir_frame_is_the_front_sketch():
    assert SW2025.to_model((1.0, 2.0, 3.0)) == (3.0, 1.0, 2.0)   # IR z = Front normal = model X


@pytest.mark.parametrize("axis, plane, sign", [("Z", "Front Plane", 1), ("Y", "Top Plane", 1),
                                               ("X", "Right Plane", 1)])
def test_plane_for_each_ir_axis(axis, plane, sign):
    assert SW2025.plane_for_ir_axis(axis) == (plane, sign)


def test_revolve_profile_point_lands_in_the_top_sketch():
    # IR (r=2, y=0, z=5) on the Top plane: sketch u = model Y = r, v = -model X = -z
    m = SW2025.to_model((2.0, 0.0, 5.0))
    assert SW2025.sketch_coords("Top Plane", m) == (2.0, -5.0)


# --------------------------------------------------------------------------- #
# MTI modeling convention (spec 2026-10-11-mti-modeling-standards-design.md)
# --------------------------------------------------------------------------- #
from pipeline.ir.compile_solidworks import (  # noqa: E402
    END_MID_PLANE, END_THROUGH_ALL, END_UP_TO_NEXT, _det, base_axis, origin_centered)
from pipeline.ir.model import BuildPlan  # noqa: E402


@pytest.mark.parametrize("axis", ["X", "Y", "Z"])
def test_mti_base_axis_maps_to_the_top_plane(axis):
    pm = SW2025.oriented(axis)
    assert pm.plane_for_ir_axis(axis) == ("Top Plane", 1)


@pytest.mark.parametrize("axis", ["X", "Y", "Z"])
def test_mti_orientation_is_a_rotation_never_a_mirror(axis):
    assert _det(*SW2025.oriented(axis).ir_basis) == pytest.approx(1.0)


def test_mti_orientation_refuses_a_left_handed_top_plane():
    bad = PlaneMap({**SW2025.planes, "Top Plane": ((1, 0, 0), (0, 1, 0), (0, 0, -1))})
    with pytest.raises(RuntimeError, match="mirrored"):
        bad.oriented("Z")


def test_origin_centered_checks_all_three_planes():
    assert origin_centered([-0.05, -0.02, -0.01, 0.05, 0.02, 0.01])
    assert not origin_centered([0.0, -0.02, -0.01, 0.1, 0.02, 0.01])   # corner origin (old frame)


def _plate_plan():
    return BuildPlan.model_validate({
        "part": "P", "frame": {"origin_kind": "corner", "units": "inch"},
        "features": [
            {"id": "F001", "kind": "prism", "on": "plane(front)", "profile": {"shape": "rect", "w": "D001", "h": "D002"},
             "depth": "D003"},
            {"id": "F002", "kind": "hole", "on": "face(F001,+Z)", "u": "D001 / 2", "v": "D002 / 2",
             "spec": {"type": "thru", "d": "D004"}}]})


def test_reference_records_the_base_body_and_its_axis():
    from pipeline.ir.compile_cadquery import build
    dims = {"D001": 4.0, "D002": 2.0, "D003": 0.5, "D004": 0.25}
    plan = _plate_plan()
    fmap = build(plan, dims).feature_map
    assert fmap["base"] == {"fid": "F001", "bbox": [0.0, 0.0, 0.0, 4.0, 2.0, 0.5]}
    assert base_axis(plan, fmap) == "Z"


def test_revolve_base_sketches_on_the_top_plane():
    plan = BuildPlan.model_validate({
        "part": "R", "frame": {"origin_kind": "axis_end", "units": "inch"},
        "features": [{"id": "F001", "kind": "revolve", "outer": [{"z": "0", "r": "D001"}, {"z": "D002", "r": "D001"}]}]})
    assert base_axis(plan, {"base": {"fid": "F001"}, "starts": {}}) == "Y"


class _FakeFM:
    def __init__(self, doc):
        self.doc = doc

    def _make(self, end):
        self.doc.history.append(self.doc.vol)
        self.doc.vol = self.doc.outcome.get(end, self.doc.vol)
        self.doc.ends.append(end)
        return object()

    def FeatureCut4(self, *a):
        return self._make(a[3])

    def FeatureExtrusion3(self, *a):
        return self._make(a[3])


class _FakeDoc:
    def __init__(self, vol, outcome):
        self.vol, self.outcome, self.history, self.ends = vol, outcome, [], []
        self.FeatureManager = _FakeFM(self)
        self.SketchManager = type("SM", (), {"AddToDB": False})()

    def EditUndo2(self, n):
        self.vol = self.history.pop()


@pytest.fixture
def fake_sw(monkeypatch):
    import pipeline.solidworks_builder as sb
    from pipeline.ir import compile_solidworks as cs

    def make(outcome, ref, vol=10.0, convention="mti"):
        doc = _FakeDoc(vol, outcome)
        monkeypatch.setattr(sb, "create_new_part", lambda app, t: doc)
        monkeypatch.setattr(sb, "_total_volume", lambda d: d.vol * 0.0254 ** 3)
        monkeypatch.setattr(sb, "_reselect_last_sketch", lambda d: None)
        fmap = {"volume_after": {"F001": ref, "F002": ref}, "starts": {"F001": {"axis": "Z"}},
                "base": {"fid": "F001", "bbox": [0, 0, 0, 4, 2, 0.5]}}
        return cs._SW(None, _plate_plan(), {}, fmap, SW2025, None, convention), doc
    return make


def test_through_cut_uses_up_to_next_when_it_matches(fake_sw):
    sw, doc = fake_sw({END_UP_TO_NEXT: 9.0, END_THROUGH_ALL: 9.0}, ref=9.0)
    res = sw.thru_cut("F002", lambda fl, end: sw.extrude(cut=True, reverse=fl, depth=None, start=0.0,
                                                          thru=True, end=end))
    assert (res.status, res.note, doc.ends) == ("built", "Up To Next", [END_UP_TO_NEXT])
    assert sw.report.conventions == []


def test_through_cut_falls_back_to_through_all_when_up_to_next_stops_short(fake_sw):
    # e.g. a hole that crosses a pocket: Up To Next ends at the pocket floor
    sw, doc = fake_sw({END_UP_TO_NEXT: 9.5, END_THROUGH_ALL: 9.0}, ref=9.0)
    res = sw.thru_cut("F002", lambda fl, end: sw.extrude(cut=True, reverse=fl, depth=None, start=0.0,
                                                          thru=True, end=end))
    assert (res.status, res.note, doc.vol) == ("built", "Through All", 9.0)
    assert doc.ends == [END_UP_TO_NEXT, END_UP_TO_NEXT, END_THROUGH_ALL]   # both directions tried first
    assert "used Through All" in sw.report.conventions[0]


def test_drawing_convention_keeps_through_all_and_the_drawing_origin(fake_sw):
    sw, doc = fake_sw({END_THROUGH_ALL: 9.0}, ref=9.0, convention="drawing")
    res = sw.thru_cut("F002", lambda fl, end: sw.extrude(cut=True, reverse=fl, depth=None, start=0.0,
                                                          thru=True, end=end))
    assert (res.note, doc.ends, sw.shift) == ("Through All", [END_THROUGH_ALL], (0.0, 0.0, 0.0))


def test_mti_shifts_the_origin_to_the_base_body_center(fake_sw):
    sw, _ = fake_sw({}, ref=9.0)
    assert sw.shift == (2.0, 1.0, 0.25)
    assert sw.local((2.0, 1.0, 0.25)) == (0.0, 0.0, 0.0)


def test_mid_plane_base_falls_back_when_the_volume_disagrees(fake_sw):
    sw, doc = fake_sw({END_MID_PLANE: 3.0}, ref=4.0, vol=0.0)
    assert sw.mid_plane("F001", 0.0127) is None and doc.vol == 0.0       # undone
    assert "Mid Plane did not match" in sw.report.conventions[0]
    sw2, doc2 = fake_sw({END_MID_PLANE: 4.0}, ref=4.0, vol=0.0)
    assert sw2.mid_plane("F001", 0.0127).note == "Mid Plane"


def test_sketches_bypass_inference_snapping(fake_sw):
    # E020: with a centered origin, a hole .005" off the origin snapped onto it (115-C F006)
    _, doc = fake_sw({}, ref=9.0)
    assert doc.SketchManager.AddToDB is True


def test_volume_check_credits_hole_wizard_drill_points(fake_sw):
    # E022: blind Hole Wizard holes end in a 118 deg point the reference doesn't model
    sw, doc = fake_sw({}, ref=9.0, vol=8.4)
    assert not sw.check("F002", 1)
    sw.extra_removed = 0.5
    assert sw.check("F002", 1, extra=0.1)


# --------------------------------------------------------------------------- #
# Patterned holes on construction geometry (E022)
# --------------------------------------------------------------------------- #
import math  # noqa: E402

from pipeline.ir.compile_solidworks import layout_shapes, on_shape  # noqa: E402


def test_bolt_circle_is_found_from_the_holes():
    pts = [(1 + 2 * math.cos(a), -1 + 2 * math.sin(a)) for a in (0.3, 1.9, 3.4, 5.0)]
    [(kind, ((cx, cy), r))] = layout_shapes(pts, "circle")
    assert kind == "circle" and (round(cx, 9), round(cy, 9), round(r, 9)) == (1.0, -1.0, 2.0)
    assert all(on_shape(p, "circle", ((cx, cy), r)) for p in pts)


def test_holes_not_on_one_circle_get_no_bolt_circle():
    assert layout_shapes([(0, 1), (1, 0), (0, -1), (0.5, 0.5)], "circle") == []


def test_grid_gets_a_rectangle_and_points_relate_only_to_their_own_edges():
    pts = [(0, 0), (2, 0), (0, 1), (2, 1), (1, 0)]
    edges = layout_shapes(pts, "grid")
    assert len(edges) == 4
    # a corner lies on exactly two edges, a mid-edge point on one, an interior point on none
    assert sum(on_shape((0, 0), "line", e[1]) for e in edges) == 2
    assert sum(on_shape((1, 0), "line", e[1]) for e in edges) == 1
    assert sum(on_shape((1, 0.5), "line", e[1]) for e in edges) == 0


def test_line_layout_runs_first_to_last():
    assert layout_shapes([(0, 0), (1, 1), (2, 2)], "line") == [("line", ((0, 0), (2, 2)))]
    assert not on_shape((3, 3), "line", ((0, 0), (2, 2)))     # beyond the segment


def test_auto_layout_finds_a_bolt_circle_or_a_row():
    circ = [(math.cos(a), math.sin(a)) for a in (0.1, 2.2, 4.3)]
    assert layout_shapes(circ, "auto")[0][0] == "circle"
    row = [(0, 0), (2, 0), (1, 0)]
    assert layout_shapes(row, "auto") == [("line", ((0, 0), (2, 0)))]
    assert layout_shapes([(0, 0), (1, 0)], "auto") == []          # two holes: nothing to show


def test_drawing_convention_never_touches_sketch_definition(fake_sw):
    sw, _ = fake_sw({}, ref=9.0, convention="drawing")
    sw.define_sketch("F001")   # the fake doc has no SketchManager.ActiveSketch: must not be reached
    assert sw.sketch_status == {}


def test_failed_sketch_definition_is_recorded_not_raised(fake_sw):
    sw, _ = fake_sw({}, ref=9.0)
    sw.define_sketch("F001")   # COM unavailable on the fake: recorded as 0, never fails the build
    assert sw.sketch_status == {"F001": 0}


# --------------------------------------------------------------------------- #
# Circular patterns of prisms (E026)
# --------------------------------------------------------------------------- #
def _pattern_plan(axis="axis(part)", skip=()):
    return BuildPlan.model_validate({
        "part": "P", "frame": {"origin_kind": "axis_end", "units": "inch"},
        "features": [
            {"id": "F001", "kind": "revolve", "outer": [{"z": "0", "r": "D001"}, {"z": "D002", "r": "D001"}]},
            {"id": "F002", "kind": "prism", "on": "plane(top)", "op": "cut", "depth": "thru",
             "profile": {"shape": "slot", "length": "D003", "width": "D004", "angle": "90", "u": "0", "v": "D002 / 2"}},
            {"id": "F003", "kind": "pattern", "seed": "F002", "mode": "circular", "count": "4", "step": "equal",
             "axis": axis, "skip": list(skip)}]})


def test_circular_prism_pattern_routes_to_the_native_pattern(fake_sw):
    sw, _ = fake_sw({}, ref=9.0)
    plan = _pattern_plan()
    sw.plan = plan
    res = sw.pattern(plan.feature("F003"))
    # the fake never built the seed, so the native pattern refuses cleanly (no exception)
    assert res.status == "failed" and "seed F002 was not built" in res.note


@pytest.mark.parametrize("axis, skip", [("axis(F001)", ()), ("axis(part)", (2,))])
def test_circular_prism_pattern_limits_are_reported(fake_sw, axis, skip):
    sw, _ = fake_sw({}, ref=9.0)
    plan = _pattern_plan(axis, skip)
    sw.plan = plan
    res = sw.pattern(plan.feature("F003"))
    assert res.status == "failed" and "axis(part)" in res.note
