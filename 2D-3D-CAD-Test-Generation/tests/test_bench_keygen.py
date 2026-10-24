"""bench.keygen recovers the planned round features of the golden plans (CadQuery reference)."""
import itertools
import json
import math
from pathlib import Path

import pytest

cq = pytest.importorskip("cadquery")
from bench.keygen import extract  # noqa: E402
from pipeline.ir.compile_cadquery import build  # noqa: E402
from pipeline.ir.model import BuildPlan  # noqa: E402

GOLD = Path(__file__).resolve().parent / "golden" / "ir"


def _golden(part):
    g = json.loads((GOLD / f"{part}.json").read_text(encoding="utf-8"))
    m = build(BuildPlan.model_validate(g["plan"]), {k: float(v) for k, v in g["dims"].items()},
              strict=False).model
    return m.solid, g["plan"]["frame"]["units"]


def _of(key, t):
    return [f for f in key.features if f.type == t]


def _dist(a, b):
    return math.dist(a, b)


def test_demo_plate_holes():
    solid, units = _golden("demo_plate")
    key = extract(solid, units=units, part="demo_plate", source="memory")
    holes = _of(key, "thru_hole")
    assert sorted(round(h.d, 6) for h in holes) == [8.0, 8.0, 8.0, 8.0, 20.0]
    small = [h for h in holes if abs(h.d - 8) < 1e-6]
    # frame-free check: the 4 corner holes form an 80 x 40 rectangle (pairwise distances)
    ds = sorted(round(_dist(a.center[:2], b.center[:2]), 6) for a, b in itertools.combinations(small, 2))
    assert ds == pytest.approx([40.0, 40.0, 80.0, 80.0, math.hypot(80, 40), math.hypot(80, 40)], abs=1e-5)
    assert all(h.thru for h in holes)
    assert key.envelope == pytest.approx([100.0, 60.0, 10.0], abs=1e-6)
    pats = _of(key, "hole_pattern")
    assert len(pats) == 1 and pats[0].pattern["mode"] == "grid" and len(pats[0].members) == 4


def test_sb11033_bolt_circle():
    solid, units = _golden("SB11033")
    key = extract(solid, units=units, part="SB11033", source="memory")
    holes = [h for h in _of(key, "thru_hole") if abs(h.d - 0.218) < 1e-6]
    assert len(holes) == 4
    pats = [p for p in _of(key, "hole_pattern") if p.pattern["mode"] == "circle"]
    assert len(pats) == 1 and pats[0].pattern["radius"] == pytest.approx(0.781, abs=1e-5)
    assert _of(key, "turned_diameter"), "the flange OD is a turned diameter"


def test_a040911e_counterbores_blind_holes_bore():
    solid, units = _golden("A040911E")
    key = extract(solid, units=units, part="A040911E", source="memory")
    cb = _of(key, "counterbore")
    assert len(cb) == 3
    for f in cb:
        assert f.d == pytest.approx(0.281, abs=1e-5)
        assert f.cbore_d == pytest.approx(0.438, abs=1e-5)
        assert f.cbore_depth == pytest.approx(0.38, abs=1e-5)
        assert f.thru is True
    blind = _of(key, "blind_hole")
    assert sorted(round(f.d, 5) for f in blind) == [0.3125, 0.3125]
    assert all(f.depth == pytest.approx(1.0, abs=1e-5) for f in blind)
    assert [round(f.d, 4) for f in _of(key, "bore")] == [4.5]
    assert 6.498 in [round(f.d, 4) for f in _of(key, "turned_diameter")]


def _key(wp, units="mm"):
    shape = wp.val() if hasattr(wp, "val") else wp
    return extract(shape, units=units, part="t", source="memory")


def _plate(x=60, y=40, z=10):
    return cq.Workplane().box(x, y, z)


# --- plan Task 4 ------------------------------------------------------------------------------

def test_countersink_vs_chamfer():
    plate = (cq.Workplane().box(40, 30, 6)
             .faces(">Z").workplane().pushPoints([(-10, 0)]).cskHole(5.0, 10.0, 82)
             .faces(">Z").workplane().pushPoints([(10, 0)]).hole(5.0)
             .faces(">Z").edges("%CIRCLE").chamfer(0.3))
    key = extract(plate.val(), units="mm", part="t", source="memory")
    cs = [f for f in key.features if f.type == "countersink"]
    assert len(cs) == 1 and cs[0].csink_d == pytest.approx(10.0, abs=0.05)
    holes = [f for f in key.features if f.type == "thru_hole"]
    assert len(holes) == 1 and holes[0].d == pytest.approx(5.0)


def test_flat_on_turned_shaft_and_pocket_on_plate():
    shaft = cq.Workplane("XY").circle(10).extrude(50).cut(
        cq.Workplane("XY").box(30, 30, 20).translate((0, 24, 25)))  # flat at y = 9
    key = extract(shaft.val(), units="mm", part="s", source="memory")
    flats = [f for f in key.features if f.type == "flat"]
    assert len(flats) == 1 and abs(abs(flats[0].normal[1]) - 1) < 1e-6
    plate = cq.Workplane().box(50, 30, 10).cut(cq.Workplane().box(20, 10, 4).translate((0, 0, 3)))
    k2 = extract(plate.val(), units="mm", part="p", source="memory")
    assert any(f.type == "pocket_step" for f in k2.features)


# --- review fixes -----------------------------------------------------------------------------

def _flatted_disc():
    """Ø100 x 10 disc, flat on the OD at y = 45 (on the bounding box), Ø20 centre bore,
    4 x Ø6 on a r = 30 bolt circle (a square: also a rectangle)."""
    return (cq.Workplane().circle(50).extrude(10)
            .cut(cq.Workplane().box(120, 20, 30).translate((0, 55, 0)))
            .faces(">Z").workplane(centerOption="ProjectedOrigin").hole(20)
            .faces(">Z").workplane(centerOption="ProjectedOrigin")
            .pushPoints([(30, 0), (0, 30), (-30, 0), (0, -30)]).hole(6))


def test_turned_axis_survives_a_flat_on_the_od():
    key = _key(_flatted_disc())
    assert [round(f.d, 6) for f in _of(key, "bore")] == [20.0]
    od = _of(key, "turned_diameter")
    assert [round(f.d, 6) for f in od] == [100.0] and "interrupted" in od[0].note
    pats = _of(key, "hole_pattern")
    assert len(pats) == 1 and pats[0].pattern["mode"] == "circle"
    assert pats[0].pattern["radius"] == pytest.approx(30.0, abs=1e-6)


def test_flat_on_the_bounding_box_is_reported():
    flats = _of(_key(_flatted_disc()), "flat")
    assert len(flats) == 1 and flats[0].normal == pytest.approx([0.0, 1.0, 0.0])


def test_large_partial_convex_is_a_boss_not_dropped():
    # obround plate: two half-cylinder ends (span pi), not a turned part
    ob = cq.Workplane().slot2D(80, 30).extrude(8)
    key = _key(ob)
    assert not _of(key, "turned_diameter")
    bosses = _of(key, "boss")
    assert len(bosses) == 2 and all(b.d == pytest.approx(30.0) and "partial" in b.note for b in bosses)


def test_chamfered_counterbore_mouth_is_not_a_countersink():
    wp = _plate().faces(">Z").workplane().cboreHole(6, 11, 4).faces(">Z").edges("%CIRCLE").chamfer(1)
    key = _key(wp)
    cb = _of(key, "counterbore")
    assert len(cb) == 1 and cb[0].csink_d is None
    assert cb[0].cbore_d == pytest.approx(11.0) and cb[0].d == pytest.approx(6.0)
    assert cb[0].center[2] == pytest.approx(10.0)          # the open (top) face
    ch = _of(key, "chamfer")
    assert [round(c.d, 6) for c in ch] == [13.0]
    assert not _of(key, "countersink")


def test_countersinks_at_both_ends_are_not_silently_overwritten():
    wp = (_plate(40, 30, 10).faces(">Z").workplane().cskHole(5.0, 10.0, 82)
          .faces("<Z").workplane().cskHole(5.0, 10.0, 82))
    cs = _of(_key(wp), "countersink")
    assert len(cs) == 1 and cs[0].csink_d == pytest.approx(10.0, abs=0.05)
    assert "other end" in cs[0].note


def test_drill_point_blind_hole():
    prof = (cq.Workplane("XZ").polyline([(0, 10), (3, 10), (3, 4), (0, 4 - 3 * 0.6)]).close()
            .revolve(360, (0, 0, 0), (0, 1, 0)))
    key = _key(_plate().translate((0, 0, 5)).cut(prof))
    blind = _of(key, "blind_hole")
    assert len(blind) == 1 and blind[0].d == pytest.approx(6.0) and blind[0].depth == pytest.approx(6.0)
    assert blind[0].thru is False and "drill point" in blind[0].note
    assert not _of(key, "chamfer") and not _of(key, "thru_hole")


def test_flat_bottom_blind_hole_and_cbore_shoulder_are_not_pocket_steps():
    key = _key(_plate().faces(">Z").workplane().pushPoints([(-15, 0)]).hole(6, 5)
               .faces(">Z").workplane().pushPoints([(15, 0)]).cboreHole(6, 11, 4))
    assert len(_of(key, "blind_hole")) == 1 and len(_of(key, "counterbore")) == 1
    assert not _of(key, "pocket_step")


def test_fillets():
    key = _key(_plate().edges("|Z").fillet(3))
    f = _of(key, "fillet")
    assert len(f) == 4 and all(x.d == pytest.approx(6.0) for x in f)


def test_slot_ends():
    key = _key(_plate().faces(">Z").workplane().slot2D(20, 8).cutThruAll())
    s = _of(key, "slot")
    assert len(s) == 2 and all(x.d == pytest.approx(8.0) for x in s)
    assert not _of(key, "boss") and not _of(key, "thru_hole")


def test_line_and_set_patterns():
    wp = (_plate(100, 40).faces(">Z").workplane().pushPoints([(-30, 10), (0, 10), (30, 10)]).hole(5)
          .faces(">Z").workplane().pushPoints([(-20, -10), (25, -12)]).hole(7))
    modes = sorted((p.pattern["mode"], p.pattern["count"]) for p in _of(_key(wp), "hole_pattern"))
    assert modes == [("line", 3), ("set", 2)]


def test_square_grid_on_a_plate_stays_grid():
    wp = _plate().faces(">Z").workplane().rect(20, 20, forConstruction=True).vertices().hole(4)
    pats = _of(_key(wp), "hole_pattern")
    assert len(pats) == 1 and pats[0].pattern["mode"] == "grid"


def _approx_equal(a, b):
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_approx_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_approx_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, float):
        return b == pytest.approx(a, abs=1e-6)
    return a == b


def test_translated_input_gives_the_same_key():
    wp = _flatted_disc()
    a = _key(wp).to_dict()
    b = _key(wp.val().translate(cq.Vector(123.4, -56.7, 8.9))).to_dict()
    assert _approx_equal(a, b)


def test_from_step_round_trip(tmp_path):
    from bench.keygen import from_step
    wp = _flatted_disc()
    step = tmp_path / "disc.step"
    cq.exporters.export(wp, str(step))
    a = _key(wp).to_dict()
    b = from_step(step, units="mm", part="t").to_dict()
    assert b["source"] == "disc.step"
    a.pop("source"), b.pop("source")
    assert _approx_equal(a, b)


def test_from_step_sees_every_solid(tmp_path):
    from bench.keygen import KeygenError, from_step
    two = cq.Workplane().box(1, 1, 1).union(cq.Workplane().box(1, 1, 1).translate((5, 0, 0)))
    step = tmp_path / "two.step"
    cq.exporters.export(two, str(step))
    with pytest.raises(KeygenError, match="2 solids"):
        from_step(step, units="mm", part="x")


def test_arc_union_does_not_double_count_overlapping_arcs():
    from bench.keygen import _arc_union
    assert _arc_union([(0.0, math.pi), (0.0, math.pi)]) == pytest.approx(math.pi)
    assert _arc_union([(0.0, math.pi), (math.pi, math.pi)]) == pytest.approx(2 * math.pi)
    assert _arc_union([(1.5 * math.pi, math.pi), (0.25 * math.pi, 0.5 * math.pi)]) == \
        pytest.approx(1.25 * math.pi)


def test_rejects_multi_solid():
    a = cq.Workplane().box(1, 1, 1).val()
    b = cq.Workplane().box(1, 1, 1).translate((5, 0, 0)).val()
    from bench.keygen import KeygenError
    with pytest.raises(KeygenError, match="2 solids"):
        extract(cq.Compound.makeCompound([a, b]), units="mm", part="x", source="memory")
