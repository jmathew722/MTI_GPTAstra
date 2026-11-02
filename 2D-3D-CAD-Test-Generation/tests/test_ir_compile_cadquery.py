"""Feature IR v2, Tasks 4-5: CadQuery reference compiler on golden plans (dev parts only)."""
import json
import math
from pathlib import Path

import pytest

pytest.importorskip("cadquery")

from pipeline.ir.compile_cadquery import build, emit_script, run_script  # noqa: E402
from pipeline.ir.model import BuildPlan  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "ir"


def load(name):
    g = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
    return BuildPlan.model_validate(g["plan"]), {k: float(v) for k, v in g["dims"].items()}


# --- demo plate: the known answer ------------------------------------------- #
def test_demo_plate_matches_ground_truth_exactly():
    plan, dims = load("demo_plate")
    assert not [f for f in plan.check(dims) if f.severity == "error"]
    r = build(plan, dims)
    fm = r.feature_map
    truth = json.loads((Path(__file__).parent.parent / "demo" / "simple_plate" / "ground_truth.json")
                       .read_text(encoding="utf-8"))["expected"]
    assert fm["bbox"] == [0, 0, 0, 100, 60, 10]
    assert fm["volume"] == pytest.approx(truth["volume_mm3"], rel=1e-4)   # chamfers included
    holes = [h for fid in ("F002", "F003", "F004") for h in fm["holes"][fid]]
    assert all(h["measured"] for h in holes)
    got = sorted((tuple(h["center"]), h["d"]) for h in holes)
    want = sorted((tuple(map(float, c["center"])), float(c["diameter"])) for c in truth["cylinders"])
    assert got == want
    assert len(fm["edge_points"]["F005"]) == 2                            # both bore mouths


def test_script_is_deterministic_and_traceable():
    plan, dims = load("demo_plate")
    a, b = emit_script(plan, dims), emit_script(plan, dims)
    assert a == b
    assert "pitch=80" in a and "# count=2, pitch=D006 - D005" in a
    assert "\\" not in a and ":\\" not in a                               # no absolute paths


def test_subprocess_run_writes_step_and_feature_map(tmp_path):
    plan, dims = load("demo_plate")
    r = run_script(emit_script(plan, dims), tmp_path, timeout=300)
    assert r.step_path.exists() and r.step_path.stat().st_size > 1000
    assert r.feature_map["volume"] == pytest.approx(54782.9, rel=1e-4)


# --- A040921E: the end slot no earlier path could build -------------------- #
def test_ring_with_end_slot_through_the_wall():
    plan, dims = load("A040921E")
    findings = plan.check(dims)
    assert [f.code for f in findings if f.severity == "error"] == ["unresolved"]   # F003 TYP edges
    r = build(plan, dims)
    m, fm = r.model, r.feature_map
    R, rb = 10.5 / 2, 9.002 / 2
    mid = (R + rb) / 2
    assert fm["bbox"] == pytest.approx([-R, -R, 0, R, R, 3.0], abs=1e-6)
    assert not m.contains(0, mid, 0.375)          # slot: wall removed at 12 o'clock within .75
    assert m.contains(0, mid, 1.5)                # beyond the slot depth: wall intact
    assert m.contains(0, -mid, 0.375)             # 6 o'clock: no slot
    assert m.contains(0.6, mid, 0.375)            # just outside the 1.062 width
    ring = math.pi * (R ** 2 - rb ** 2) * 3.0
    assert fm["volume"] < ring and fm["volume"] == pytest.approx(ring - 1.062 * 0.75 * (R - rb), rel=0.01)
    assert "F003" in fm["skipped"]


# --- SB11780: turned tie rod; necks were refused (F6b), keyway had no profile --- #
def test_tie_rod_revolve_necks_and_keyway():
    plan, dims = load("SB11780")
    assert sorted(f.feature for f in plan.check(dims) if f.code == "unresolved") == ["F003", "F004"]
    r = build(plan, dims)
    m, fm = r.model, r.feature_map
    R, rn = 2.4985 / 2, 1.734 / 2
    assert fm["bbox"] == pytest.approx([-R, -R, 0, R, R, 76.88], abs=1e-6)
    assert m.contains(1.0, 0, 0.44)                    # left collar is full diameter
    assert not m.contains(1.0, 0, 0.88 + 0.5)          # left neck turned down
    assert m.contains(0.5, 0, 0.88 + 0.5)              #   ... to Ø1.734
    assert not m.contains(1.0, 0, 76.005 - 0.5)        # right neck
    assert m.contains(1.0, 0, 76.88 - 0.44)            # right collar (.875)
    assert not m.contains(1.1, 0, 38.0)                # keyway: floor at x = 2.218 - R
    assert m.contains(0.9, 0, 38.0)                    #   ... below the floor is solid
    assert m.contains(1.1, 0, 0.44) and m.contains(-1.1, 0, 38.0)   # collars and far side intact
    body = math.pi * R ** 2 * 76.88
    necks = 2 * math.pi * (R ** 2 - rn ** 2) * 1.016
    assert fm["volume"] < body - necks                 # keyway removed material too
    assert set(fm["skipped"]) == {"F003", "F004"}


def load_ref(name):
    g = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
    return frozenset(g.get("reference_ids", []))


# --- SB11033: stepped revolve, bolt circle, faces picked by coordinate --------- #
def test_work_backup_pilot_flange_boss_holes_and_edges():
    plan, dims = load("SB11033")
    errs = [f for f in plan.check(dims, load_ref("SB11033")) if f.severity == "error"]
    assert [(f.code, f.feature) for f in errs] == [("unresolved", "F005")]   # .015 MAX R
    r = build(plan, dims)
    m, fm = r.model, r.feature_map
    assert fm["bbox"] == pytest.approx([-0.969, -0.969, 0, 0.969, 0.969, 1.971], abs=1e-6)
    assert m.contains(0, 0, 1.0) and m.contains(0, 0, 0.1)        # no bore (section fully hatched)
    assert m.contains(0.3, 0, 0.1) and not m.contains(0.4, 0, 0.1)  # pilot Ø.686
    assert m.contains(0.45, 0, 1.5) and not m.contains(0.55, 0, 1.5)  # boss Ø1.000
    holes = fm["holes"]["F002"] + fm["holes"]["F003"]
    assert len(holes) == 4 and all(h["measured"] and h["d"] == pytest.approx(0.218) for h in holes)
    assert sorted(round(math.hypot(*h["center"]), 6) for h in holes) == [0.781] * 4
    assert len(fm["edge_points"]["F004"]) == 1                      # .094 R: boss root only
    assert len(fm["edge_points"]["F006"]) == 2                      # .03: both flange OD edges
    assert len(fm["edge_points"]["F007"]) == 1                      # .06: boss end
    assert "F005" in fm["skipped"]


# --- A040911E: 3 counterbored + 2 tapped holes, chamfers TYP --------------------- #
def test_bearing_counterbores_taps_and_chamfers():
    plan, dims = load("A040911E")
    assert not [f for f in plan.check(dims, load_ref("A040911E")) if f.severity != "info"]
    r = build(plan, dims)
    m, fm = r.model, r.feature_map
    R = 6.498 / 2
    assert fm["bbox"] == pytest.approx([-R, -R, 0, R, R, 1.5], abs=1e-6)
    cb = [fm["holes"][f][0] for f in ("F002", "F003", "F004")]
    assert all(h["measured"] for h in cb)
    assert sorted((round(h["center"][0], 3), round(h["center"][1], 3)) for h in cb) == \
        [(-2.49, -1.438), (0.0, 2.875), (2.49, -1.438)]
    assert not m.contains(0, 2.875 + 0.19, 0.2)      # inside Ø.438 counterbore, .38 deep
    assert m.contains(0, 2.875 + 0.19, 0.6)          #   ... below it, only the Ø.281 drill
    assert not m.contains(0, 2.875, 1.4)             # drill goes through
    taps = [fm["holes"][f][0] for f in ("F005", "F006")]
    assert all(h["measured"] and h["depth"] == pytest.approx(1.0, abs=1e-6) for h in taps)
    assert m.contains(2.75, 0, 1.2)                  # tapped hole is blind (1.00 DP of 1.500)
    assert len(fm["edge_points"]["F007"]) == 4


# --- MTI audit 2026-10-26: SB14306 tapped THRU holes, 4C1229 slots through a revolve --- #
def _flange():
    from pipeline.ir.cq_runtime import Model
    m = Model("T", origin_kind="axis_end", units="inch", strict=True)
    m.revolve("F001", outer=[(0, 3.0), (0.5, 3.0)], inner=[(0, 0.5), (0.5, 0.5)], op="add")
    return m


def test_tapped_hole_with_null_depth_cuts_through():
    m = _flange()
    m.hole("F002", on="face(F001,+Z)", u=2.0, v=0, spec={"type": "tapped", "d": 0.3125, "depth": None,
                                                         "thread": ".375-16 UNC THRU"})
    assert not m.skipped
    assert not m.contains(2.0, 0, 0.05) and not m.contains(2.0, 0, 0.45)   # through the whole flange
    hole = m.feature_map()["holes"]["F002"][0]
    assert hole["measured"] and hole["depth"] == pytest.approx(0.5, abs=1e-6)


def test_holes_are_measured_after_slots_trim_the_bore():
    m = _flange()   # 4C1229: the slot cuts leave trimmed cylinder surfaces (no _geomAdaptor().Cylinder())
    m.prism("F002", on="face(F001,-Z)", offset=0, depth="thru", op="cut",
            profile={"shape": "slot", "length": 3.0, "width": 0.344, "angle": 90, "u": 0, "v": -1.5})
    m.hole("F003", on="face(F001,-Z)", u=0, v=1.125,
           spec={"type": "cbore", "d": 0.221, "cbore_d": 0.328, "cbore_depth": 0.19})
    fm = m.feature_map()
    assert fm["holes"]["F003"][0]["measured"]


def test_edge_query_never_selects_a_cylinder_seam():
    from pipeline.ir.cq_runtime import Model
    m = Model("T", origin_kind="axis_end", units="inch", strict=True)   # bore steps out through a cone
    m.revolve("F001", outer=[(0, 3.0), (0.5, 3.0)], inner=[(0, 0.5), (0.2, 0.5), (0.3, 0.7), (0.5, 0.7)], op="add")
    # 4C1229 F004: wall(F001) also matches the bore itself, and its seam is not an edge "between"
    m.edge_op("F002", operation="fillet", size=0.02, angle=45, edges=["edge_between(wall(F001,0.5),wall(F001))"])
    assert [round(p[2], 6) for p in m.edge_points["F002"]] == [0.2]     # the bore-to-cone circle only


def test_wall_radius_matches_a_cone_at_its_rim():
    from pipeline.ir.cq_runtime import Model
    m = Model("T", origin_kind="axis_end", units="inch", strict=True)   # SB14306 F003: tapered nose
    m.revolve("F001", outer=[(0, 3.0), (1.0, 2.8), (2.0, 2.8)], inner=[(0, 1.0), (2.0, 1.0)], op="add")
    m.edge_op("F002", operation="fillet", size=0.05, angle=45, edges=["edge_between(face(F001,-Z,0),wall(F001,3.0))"])
    assert [round(p[2], 6) for p in m.edge_points["F002"]] == [0.0]


def test_surface_deviation_reads_a_thin_wall_offset_in_mm():
    import cadquery as cq
    from pipeline.ir.score import aligned, iou, surface_deviation
    # A00161E: a 1.5 mm sheet offset by 0.9 mm has a poor IoU but a 0.9 mm deviation
    ring = lambda r: cq.Workplane().circle(r + 1.5).circle(r).extrude(100).val()
    a, b = ring(100.0), ring(100.9)
    value, key = iou(a, b)
    assert value < 0.6
    dev = surface_deviation(aligned(a, b, key), b)
    assert dev["max"] == pytest.approx(0.9, abs=0.05)


# --- A050211E (2026-10-26 official run): a slot trims a revolved face -> Geom_RectangularTrimmedSurface --- #
def test_feature_map_survives_trimmed_cylinder_faces(tmp_path):
    """The bench retainer plan crashed measure_holes: the slot cut leaves a cylinder whose
    _geomAdaptor() is a trimmed surface with no .Cylinder(). Holes must still be measured."""
    from pipeline.ir.cq_runtime import Model
    m = Model("RETAINER", origin_kind="axis_end", units="inch", strict=False)
    m.revolve("F001", outer=[(0, 3.375), (0.5, 3.375)], inner=[(0, 1.94), (0.5, 1.94)], op="add")
    m.hole("F002", on="face(F001,+Z)", u=-2.88, v=0, spec={"type": "thru", "d": 0.344})
    m.hole("F003", on="face(F001,+Z)", u=2.88, v=0, spec={"type": "thru", "d": 0.344})
    m.hole("F004", on="face(F001,+Z)", u=-1.44, v=-2.494, spec={"type": "thru", "d": 0.344})
    m.pattern("F005", seed="F004", mode="grid", count=2, pitch=2.88, dir="+X", count2=2, pitch2=4.988,
              dir2="+Y", axis="axis(part)", step="equal", skip=[], op="cut")
    m.prism("F006", on="face(F001,+Z)", offset=0, profile={"shape": "slot", "length": 7.99, "width": 1.24,
            "angle": 90, "u": 0, "v": -6.315}, depth="thru", op="cut")
    fm = m.finish(str(tmp_path))
    holes = [h for fid in ("F002", "F003", "F004", "F005") for h in fm["holes"].get(fid, [])]
    assert holes and all(h["measured"] for h in holes)
    assert all(abs(h["d"] - 0.344) < 1e-6 for h in holes)
    assert (tmp_path / "reference.step").is_file()


# --- Radial holes (spec 2026-10-28-radial-holes-design.md): SB12059, SB12095, 2N2664 --- #
def _tube():
    from pipeline.ir.cq_runtime import Model
    m = Model("T", origin_kind="axis_end", units="inch", strict=True)
    m.revolve("F001", outer=[(0, 2.0), (2.0, 2.0)], inner=[(0, 0.5), (2.0, 0.5)], op="add")
    return m


def _polar(r, deg, z):
    a = math.radians(deg)
    return r * math.cos(a), r * math.sin(a), z


def test_radial_blind_hole_at_an_angle():
    m = _tube()   # SB12059: .375-24 tap .38 deep at 45 deg, .75 from the end
    m.hole("F002", on="wall(F001,2.0)", u=45, v=0.75, spec={"type": "tapped", "d": 0.332, "depth": 0.5})
    assert not m.skipped
    assert not m.contains(*_polar(1.9, 45, 0.75))          # drilled near the surface at 45 deg
    assert not m.contains(*_polar(1.6, 45, 0.75))          # 0.4 deep: still inside the hole
    assert m.contains(*_polar(1.4, 45, 0.75))              # past the .5 depth: material
    assert m.contains(*_polar(1.9, -45, 0.75))             # the mirror angle is untouched
    assert m.contains(*_polar(1.9, 45, 0.3))               # other axial stations untouched
    assert m.starts["F002"]["radial"]


def test_radial_thru_hole_crosses_the_whole_diameter():
    m = _tube()
    m.hole("F002", on="wall(F001,2.0)", u=0, v=1.0, spec={"type": "thru", "d": 0.25})
    assert not m.contains(1.9, 0, 1.0) and not m.contains(-1.9, 0, 1.0)
    assert m.contains(0, 1.9, 1.0)


def test_radial_hole_pattern_about_the_part_axis():
    m = _tube()   # 4 radial holes, seed at 45 deg, every 90 deg
    m.hole("F002", on="wall(F001,2.0)", u=45, v=1.0, spec={"type": "blind", "d": 0.25, "depth": 0.5})
    m.pattern("F003", seed="F002", mode="circular", count=4, pitch=0, dir="+X", count2=1, pitch2=0, dir2="+Y",
              axis="axis(part)", step="equal", skip=[], op="cut")
    for deg in (45, 135, 225, 315):
        assert not m.contains(*_polar(1.9, deg, 1.0)), deg
    for deg in (0, 90, 180, 270):
        assert m.contains(*_polar(1.9, deg, 1.0)), deg


def test_radial_hole_needs_a_wall_radius():
    from pipeline.ir.cq_runtime import CompileError
    m = _tube()
    with pytest.raises(CompileError, match="wall radius"):
        m.hole("F002", on="wall(F001)", u=0, v=1.0, spec={"type": "thru", "d": 0.25})


def test_clocked_iou_forgives_rotation_about_the_axis_only():
    """4C1229: a slot pattern clocked differently from MTI's is the same part. Five slots 15 deg
    apart can't be lined up by the strict 90-deg / mirror alignments (those reach 18-deg steps)."""
    import cadquery as cq
    from pipeline.ir.score import clocked, iou, turned_axis

    def part(deg):
        disk = cq.Workplane().circle(50).extrude(10)
        for i in range(5):
            a = math.radians(deg + 72 * i)
            disk = disk.cut(cq.Workplane().center(40 * math.cos(a), 40 * math.sin(a)).circle(4).extrude(10))
        return disk.val()

    a, b = part(15), part(0)
    assert turned_axis(b) == 2
    assert iou(a, b)[0] < 0.99
    best, ang, _ = clocked(a, b)
    assert best > 0.999 and (ang + 15) % 72 == pytest.approx(0, abs=1e-6)


def test_face_query_on_a_pocket_selects_its_own_walls():
    """2N2664 F023: a cut's +X wall faces -X (into the pocket). face(F002,+X) must still find it."""
    from pipeline.ir.cq_runtime import Model
    m = Model("T", origin_kind="corner", units="inch", strict=True)
    m.prism("F001", on="plane(front)", offset=0, profile={"shape": "rect", "w": 4, "h": 4, "anchor": "corner", "u": 0, "v": 0},
            depth=1, op="add")
    m.prism("F002", on="face(F001,+Z)", offset=0, profile={"shape": "rect", "w": 1, "h": 2, "anchor": "corner", "u": 1, "v": 1},
            depth=0.5, op="cut")
    m.edge_op("F003", operation="fillet", size=0.1, angle=45,
              edges=["edge_between(face(F002,+X),face(F002,+Y))", "edge_between(face(F002,-X),face(F002,+Y))"])
    pts = m.edge_points["F003"]
    assert len(pts) == 2 and all(abs(p[1] - 3.0) < 1e-6 for p in pts)     # the two corners at the +Y end
