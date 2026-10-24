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


def test_rejects_multi_solid():
    a = cq.Workplane().box(1, 1, 1).val()
    b = cq.Workplane().box(1, 1, 1).translate((5, 0, 0)).val()
    from bench.keygen import KeygenError
    with pytest.raises(KeygenError, match="2 solids"):
        extract(cq.Compound.makeCompound([a, b]), units="mm", part="x", source="memory")
