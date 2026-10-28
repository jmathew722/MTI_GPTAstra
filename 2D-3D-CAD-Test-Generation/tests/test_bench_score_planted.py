"""Scorer identity and planted errors on real geometry (spec 2026-10-24, 'Testing' 2-4).

Synthetic parts: CadQuery plates, edited with bench.plant, written to STEP and read back with
keygen exactly like a generated part. Real parts (skipped without MTI_BENCH_DATA): each MTI
reference STEP scores 100 against its own key, also rotated and translated, and planted errors
cost what the curve and the weights say. Feature-level versions of these checks (exact to 1e-6)
are in test_bench_score_part.py; here the bound is the STEP round trip."""
import copy
import math
import random
from pathlib import Path

import pytest
import yaml

cq = pytest.importorskip("cadquery")
from bench import config, keygen, plant, split  # noqa: E402
from bench.align import ROTATIONS, transform  # noqa: E402
from bench.credit import attr_credit, feature_credit  # noqa: E402
from bench.features import Feature, Key  # noqa: E402
from bench.score_config import load  # noqa: E402
from bench.scoring import score_part  # noqa: E402
from bench.weights import weight  # noqa: E402

C = load()
TOL_MM = C.fallback_tol["mm"]                       # 0.1 mm
THRU = [(20.0, 15.0), (80.0, 15.0), (35.0, 40.0)]   # chiral: no mirror plane
BLIND = (25.0, 48.0)


def _plate(thru=THRU, blind=BLIND, cbore_at=None):
    """100 x 60 x 10 mm plate, origin at its bbox minimum: 8 mm thru holes, one 6 mm x 5 mm
    flat-bottom blind hole from the top, optionally a counterbore (8 / 14 x 6, deeper than half the plate) instead of the
    first thru hole."""
    top = cq.Workplane("XY").box(100, 60, 10, centered=False).faces(">Z").workplane(
        centerOption="ProjectedOrigin", origin=(0, 0, 0))
    plain = [p for p in thru if p != cbore_at]
    wp = top.pushPoints(plain).hole(8)
    if cbore_at is not None:
        wp = wp.faces(">Z").workplane(centerOption="ProjectedOrigin", origin=(0, 0, 0)) \
            .pushPoints([cbore_at]).cboreHole(8, 14, 6)
    if blind is not None:
        wp = wp.faces(">Z").workplane(centerOption="ProjectedOrigin", origin=(0, 0, 0)) \
            .pushPoints([blind]).hole(6, depth=5)
    return wp.val()


def _key_of(solid, part="SYN"):
    return keygen.extract(solid, units="mm", part=part, source="synthetic")


def _round_trip(solid, tmp_path, name="gen.step"):
    """Write the solid to STEP and read it back with keygen (as the scorer reads a part)."""
    out = plant.write_solid(solid, tmp_path / name)
    return keygen.from_step(out, units="mm", part="SYN")


def _hole_at(key, xy, typ=None):
    return next(f for f in key.features if f.center is not None and f.type != "hole_pattern"
                and (typ is None or f.type == typ)
                and math.dist(f.center[:2], xy) < 1e-6)


def _weights(s):
    return sum(r.weight for r in s.rows)


# --- identity ----------------------------------------------------------------------------------

def test_plate_key_has_the_planted_features():
    key = _key_of(_plate())
    assert sorted(f.type for f in key.features if f.type != "hole_pattern") == \
        ["blind_hole", "thru_hole", "thru_hole", "thru_hole"]
    b = _hole_at(key, BLIND)
    assert b.center[2] == pytest.approx(10.0) and b.depth == pytest.approx(5.0)   # starts on the top face


def _posed(solid, rot, trans):
    for axis, angle in rot:
        solid = solid.rotate((0, 0, 0), axis, angle)
    return solid.translate(cq.Vector(*trans))


@pytest.mark.parametrize("rot", [
    [],
    [((1, 0, 0), 90)],
    [((0, 1, 0), 180)],
    [((0, 0, 1), 90), ((1, 0, 0), -90)],
    [((0, 1, 0), 90), ((0, 0, 1), 270)],
])
def test_identity_after_moving_the_solid(rot, tmp_path):
    """The solid itself turned (90 degree steps) and moved off-axis, written to STEP, read back."""
    key = _key_of(_plate())
    gen = _round_trip(_posed(_plate(), rot, (13.7, -42.1, 5.3)), tmp_path)
    s = score_part(key, gen, C)
    assert s.score == pytest.approx(100.0, abs=1e-9) and s.exact


def _turned():
    """Turned part on Z: OD 40 x 60 with a 25 x 20 spigot on top, OD chamfer at the bottom, a
    6 mm cross hole at z = 20, a flat on the OD and an 8 x 15 blind centre hole in the spigot."""
    body = (cq.Workplane("XY").circle(20).extrude(60).faces(">Z").workplane().circle(12.5).extrude(20)
            .faces("<Z").chamfer(1.5))
    body = body.cut(cq.Workplane("YZ").workplane(offset=-30).center(0, 20).circle(3).extrude(60))
    body = body.cut(cq.Workplane("XY").box(40, 10, 30).translate((0, 23, 45)))      # flat at y = 18
    body = body.faces(">Z").workplane(centerOption="ProjectedOrigin", origin=(0, 0, 0)).hole(8, depth=15)
    return body.val()


def _rotated(solid, R):
    """The solid turned by the proper rotation matrix R about the origin."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf
    t = gp_Trsf()
    t.SetValues(*(float(R[r][c]) if c < 3 else 0.0 for r in range(3) for c in range(4)))
    return cq.Shape.cast(BRepBuilderAPI_Transform(solid.wrapped, t, True).Shape())


def _same(a: Feature, b: Feature) -> bool:
    """Equal fields; a thru feature's centre only across its axis (its offset along the axis is
    not scored when both are thru, and keygen samples it from the face)."""
    if a.thru and b.thru and a.center and b.center and a.axis == b.axis:
        d = [p - q for p, q in zip(a.center, b.center)]
        along = sum(x * y for x, y in zip(d, a.axis))
        if math.dist(d, [along * x for x in a.axis]) >= 1e-6:
            return False
        a = copy.copy(a)
        a.center = b.center

    def close(x, y):
        if x is None or y is None:
            return x is y
        if isinstance(x, list):
            return len(x) == len(y) and all(abs(p - q) < 1e-6 for p, q in zip(x, y))
        return abs(x - y) < 1e-6
    return a.type == b.type and all(close(getattr(a, n), getattr(b, n))
                                    for n in ("axis", "center", "d", "depth", "normal", "offset", "size"))


@pytest.mark.parametrize("i", range(24))
def test_transform_agrees_with_keygen_of_the_rotated_solid(i):
    """align.transform(key, R) must be what keygen reports for the solid turned by R, so a
    generated part in any of the 24 orientations is posed exactly. Features keygen locates at the
    low end of their (canonical) axis -- turned diameters, chamfers, ... -- change ends when R
    reverses that axis."""
    import numpy as np
    solid = _turned()
    k0 = _key_of(solid)
    R = ROTATIONS[i]
    rotated = _key_of(_rotated(solid, R))
    expected = transform(k0, R)
    assert np.allclose(rotated.envelope, expected.envelope)
    got = [f for f in rotated.features if f.type != "hole_pattern"]
    for f in (f for f in expected.features if f.type != "hole_pattern"):
        assert any(_same(f, g) for g in got), (f, [g for g in got if g.type == f.type])


# --- planted errors ----------------------------------------------------------------------------

@pytest.mark.parametrize("k", [0.5, 0.99, 1.5, 2, 5, 10])
def test_moved_thru_hole_costs_the_curve(k, tmp_path):
    key = _key_of(_plate())
    h = _hole_at(key, THRU[0])
    gen = _round_trip(plant.move(_plate(), key, h.id, (k * TOL_MM, 0.0, 0.0)), tmp_path)
    s = score_part(key, gen, C)
    row = s.row(h.id)
    assert row.status == "matched"
    assert row.attr_credits["position"] == pytest.approx(attr_credit(k * TOL_MM, TOL_MM, C), abs=0.01)
    assert all(c == 1.0 for a, c in row.attr_credits.items() if a != "position")
    assert all(r.credit == 1.0 for r in s.rows if r.feature_id != h.id)
    assert not s.extras
    expected = 100 * (1 - row.weight * (1 - row.credit) / _weights(s))
    assert s.score == pytest.approx(expected, abs=1e-6)


def test_moved_blind_hole_keeps_its_start_face_and_depth(tmp_path):
    key = _key_of(_plate())
    h = _hole_at(key, BLIND)
    gen = _round_trip(plant.move(_plate(), key, h.id, (0.0, -2 * TOL_MM, 0.0)), tmp_path)
    g = next(f for f in gen.features if f.type == "blind_hole")
    assert g.center[2] == pytest.approx(10.0, abs=1e-6) and g.depth == pytest.approx(5.0, abs=1e-6)
    row = score_part(key, gen, C).row(h.id)
    assert row.attr_credits["position"] == pytest.approx(attr_credit(2 * TOL_MM, TOL_MM, C), abs=0.01)
    assert row.attr_credits["depth"] == 1.0


def test_filled_hole_costs_its_weight_share(tmp_path):
    key = _key_of(_plate())
    h = _hole_at(key, THRU[1])
    gen = _round_trip(plant.fill(_plate(), key, h.id), tmp_path)
    assert sum(1 for f in gen.features if f.type == "thru_hole") == 2
    s = score_part(key, gen, C)
    assert s.row(h.id).status == "missing" and not s.extras
    assert all(r.credit == 1.0 for r in s.rows if r.feature_id != h.id)
    assert s.score == pytest.approx(100 * (1 - s.row(h.id).weight / _weights(s)), abs=1e-6)


def test_filling_a_drill_point_blind_hole_leaves_nothing_behind(tmp_path):
    """A drilled blind hole ends in a cone; the plug fills it too (no stray chamfer/step)."""
    key = _key_of(_drilled())
    h = next(f for f in key.features if f.type == "blind_hole" and f.center[0] < 30)
    assert "drill point" in h.note
    gen = _round_trip(plant.fill(_drilled(), key, h.id), tmp_path)
    s = score_part(key, gen, C)
    assert s.row(h.id).status == "missing" and not s.extras
    assert s.score == pytest.approx(100 * (1 - s.row(h.id).weight / _weights(s)), abs=1e-6)


def _drilled():
    """60 x 40 x 20 block with two 6 mm x 12 mm blind holes from the top, 118 degree drill points."""
    body = cq.Workplane("XY").box(60, 40, 20, centered=False)
    for x in (15.0, 45.0):
        r = 3.0
        tip = r / math.tan(math.radians(59))
        drill = (cq.Workplane("XZ").polyline([(0, 20), (r, 20), (r, 8), (0, 8 - tip)]).close()
                 .revolve(360, (0, 0, 0), (0, 1, 0)).translate((x, 20, 0)))
        body = body.cut(drill)
    return body.val()


def test_moved_counterbore_keeps_its_counterbore(tmp_path):
    key = _key_of(_plate(cbore_at=THRU[0]))
    cb = _hole_at(key, THRU[0], "counterbore")
    gen = _round_trip(plant.move(_plate(cbore_at=THRU[0]), key, cb.id, (0.0, 2 * TOL_MM, 0.0)), tmp_path)
    s = score_part(key, gen, C)
    row = s.row(cb.id)
    assert row.attr_credits["position"] == pytest.approx(attr_credit(2 * TOL_MM, TOL_MM, C), abs=0.01)
    assert all(c == 1.0 for a, c in row.attr_credits.items() if a != "position") and not s.extras


def test_extra_hole_costs_exactly_the_extra_penalty(tmp_path):
    key = _key_of(_plate())
    gen = _round_trip(plant.add(_plate(), key, (60.0, 45.0, 0.0), 5.0, (0, 0, 1)), tmp_path)
    s = score_part(key, gen, C)
    assert [e.type for e in s.extras] == ["thru_hole"]
    w = weight(Feature(id="X", type="thru_hole", d=5.0, depth=10.0), max(key.envelope), C)
    assert s.extras[0].weight == pytest.approx(w, abs=1e-9)
    assert all(r.credit == 1.0 for r in s.rows)
    assert s.score == pytest.approx(100 * (1 - C.extra_penalty * w / _weights(s)), abs=1e-6)


def test_counterbore_built_as_a_plain_hole_loses_only_the_type_share(tmp_path):
    key = _key_of(_plate(cbore_at=THRU[0]))
    cb = _hole_at(key, THRU[0], "counterbore")
    gen = _round_trip(_plate(), tmp_path)                 # same plate, plain 8 mm hole there
    s = score_part(key, gen, C)
    row = s.row(cb.id)
    assert row.attr_credits["type"] == 0.0
    assert all(c == 1.0 for a, c in row.attr_credits.items() if a != "type")
    assert row.credit == pytest.approx(1 - C.shares["type"], abs=1e-9)        # 0.85
    assert all(r.credit == 1.0 for r in s.rows if r.feature_id != cb.id) and not s.extras


def test_half_tolerance_noise_on_every_hole_is_still_100(tmp_path):
    rnd = random.Random(20261025)
    key = _key_of(_plate())
    solid = _plate()
    for f in [f for f in key.features if f.type in ("thru_hole", "blind_hole")]:
        a = rnd.uniform(0, 2 * math.pi)
        r = rnd.uniform(0.2, 0.5) * TOL_MM
        solid = plant.move(solid, key, f.id, (r * math.cos(a), r * math.sin(a), 0.0))
    gen = _round_trip(solid, tmp_path)
    assert gen.features != key.features                    # it did move
    s = score_part(key, gen, C)
    assert s.score == pytest.approx(100.0, abs=1e-9) and s.exact


def test_mirrored_symmetric_plate_is_100(tmp_path):
    sym = [(20.0, 15.0), (80.0, 15.0), (20.0, 45.0), (80.0, 45.0)]
    key = _key_of(_plate(thru=sym, blind=(50.0, 30.0)))
    gen = _round_trip(_plate(thru=sym, blind=(50.0, 30.0)).mirror("YZ"), tmp_path)
    s = score_part(key, gen, C)
    assert s.score == pytest.approx(100.0, abs=1e-9) and s.exact


def test_mirrored_chiral_plate_is_not_100(tmp_path):
    key = _key_of(_plate())
    gen = _round_trip(_plate().mirror("YZ"), tmp_path)
    s = score_part(key, gen, C)
    assert s.score < 100.0 - 1.0 and not s.exact


# --- properties (feature-level keys, seeded) ---------------------------------------------------

def _random_key(rnd: random.Random, i: int) -> Key:
    env = [rnd.uniform(2, 10), rnd.uniform(2, 8), rnd.uniform(0.5, 2)]
    feats = []
    for j in range(rnd.randint(2, 8)):
        typ = rnd.choice(["thru_hole", "blind_hole", "tapped_hole", "bore", "counterbore"])
        d = rnd.uniform(0.1, 0.8)
        f = Feature(id=f"K{j}", type=typ, axis=[0.0, 0.0, 1.0],
                    center=[rnd.uniform(0.5, env[0] - 0.5), rnd.uniform(0.5, env[1] - 0.5), env[2]], d=d)
        if typ in ("thru_hole", "bore"):
            f.thru, f.depth = True, env[2]
        else:
            f.thru, f.depth = False, rnd.uniform(0.1, env[2] * 0.8)
        if typ == "counterbore":
            f.cbore_d, f.cbore_depth = d * 1.6, 0.1
        feats.append(f)
    return Key(part=f"R{i}", units="inch", source="random", envelope=env, features=feats)


def _cases():
    rnd = random.Random(20261024)
    return [(_random_key(rnd, i), rnd) for i in range(50)]


def test_property_larger_error_never_raises_the_score():
    for key, rnd in _cases():
        fid = rnd.choice(key.features).id
        attr = rnd.choice(["x", "y", "d", "depth"])
        if attr == "depth" and key.feature(fid).thru:
            attr = "d"                                    # thru depth is not scored numerically
        sign = rnd.choice([-1, 1])
        prev = math.inf
        for k in (0, 0.5, 1, 1.5, 2, 3, 5, 8, 12, 20, 40):
            gen = copy.deepcopy(key)
            f = gen.feature(fid)
            e = sign * k * 0.005
            if attr == "x":
                f.center[0] += e
            elif attr == "y":
                f.center[1] += e
            elif attr == "d":
                f.d = max(0.01, f.d + e)
            else:
                f.depth = max(0.01, f.depth + e)
            s = score_part(key, gen, C).score
            assert s <= prev + 1e-9, (key.part, fid, attr, k)
            prev = s


def test_property_feature_order_is_irrelevant_and_score_is_bounded():
    for key, rnd in _cases():
        gen = copy.deepcopy(key)
        for f in gen.features:
            f.center = [c + rnd.uniform(-3, 3) * 0.005 for c in f.center]
            f.d += rnd.uniform(-3, 3) * 0.005
        for j in range(rnd.randint(0, 4)):          # some extras
            gen.features.append(Feature(id=f"X{j}", type="thru_hole", axis=[0.0, 0.0, 1.0],
                                        center=[rnd.uniform(0, key.envelope[0]), rnd.uniform(0, key.envelope[1]),
                                                key.envelope[2]], d=0.2, depth=key.envelope[2], thru=True))
        if rnd.random() < 0.3:
            gen.features = gen.features[1:]          # and a missing one
        a = score_part(key, gen, C).score
        assert 0.0 <= a <= 100.0
        k2, g2 = copy.deepcopy(key), copy.deepcopy(gen)
        rnd.shuffle(k2.features)
        rnd.shuffle(g2.features)
        assert score_part(k2, g2, C).score == pytest.approx(a, abs=1e-9), key.part


# --- real MTI parts (skipped without MTI_BENCH_DATA; read only) --------------------------------



def _data_root():
    try:
        return config.data_root(required=False)
    except config.BenchConfigError:          # set but pointing nowhere: skip, the config tests cover it
        return None


ROOT = _data_root()
_MANIFEST = Path(__file__).resolve().parent.parent / "bench" / "manifest.yaml"
PARTS = split.bench_parts(yaml.safe_load(_MANIFEST.read_text(encoding="utf-8")))
real = pytest.mark.skipif(ROOT is None, reason="MTI_BENCH_DATA not set (confidential benchmark data)")
INCH = 25.4

# keygen picks by an order that depends on the axis direction, so in the 12 orientations that
# reverse the part's axis it reports these parts differently (not a scorer issue; fixing keygen
# changes the signed keys, so it waits for a re-key). ROTATIONS[1] reverses it for both.
_KEYGEN_ORIENTATION = {
    "A050071E": "keygen._cones_and_partials takes a cone's host as the first hole on its axis line, "
                "not the hole whose end it touches; the rod's two coaxial end holes (0.5312 and 0.3125 tap "
                "drills) swap which one gets the drill point and which cone becomes a chamfer (97.02)",
    "A050061E": "keygen._hole_chain picks the drill as min(chain, key=radius); the bore has two equal "
                "2.501 segments (split by a 2.74 groove) and the tie goes to the first along the canonical "
                "axis, so the thru bore and the 'further step' swap (one bore missing + one extra: 89.39)",
}

_cache: dict = {}


def _real(part):
    """(key with no overrides and no resolutions, reference solid, keygen of the reference STEP)."""
    if part not in _cache:
        d = ROOT / part
        key = Key.load(d / "key.json")
        k = copy.deepcopy(key)
        k.overrides = []                     # identity is model vs model: drawing overrides off,
        for fl in k.flags:                   # including those derived from flag resolutions
            fl.resolution = None
        _cache[part] = (k, plant.read_solid(d / "reference.step"),
                        keygen.from_step(d / "reference.step", units=key.units, part=part))
    return _cache[part]


@real
@pytest.mark.parametrize("part", PARTS)
def test_real_reference_scores_100_against_its_own_key(part):
    key, _, gen = _real(part)
    s = score_part(key, gen, C)
    assert s.score == pytest.approx(100.0, abs=1e-9) and s.exact, \
        [(r.feature_id, r.status, r.attr_credits) for r in s.rows if r.credit < 1] + s.extras


@real
@pytest.mark.parametrize("part", PARTS)
def test_real_identity_under_seeded_rotations(part):
    key, _, gen = _real(part)
    rnd = random.Random(f"rot-{part}")
    for i in rnd.sample(range(1, 24), 3):
        s = score_part(key, transform(gen, ROTATIONS[i]), C)
        assert s.score == pytest.approx(100.0, abs=1e-9) and s.exact, i


def _posed_params():
    out = []
    for p in PARTS:
        if p in _KEYGEN_ORIENTATION:
            out.append(pytest.param(p, 1, marks=pytest.mark.xfail(strict=True, reason=_KEYGEN_ORIENTATION[p])))
        else:
            out.append(pytest.param(p, random.Random(f"pose-{p}").randrange(1, 24)))
    return out


@real
@pytest.mark.parametrize("part, i", _posed_params())
def test_real_identity_with_the_solid_turned_and_moved(part, i):
    """The honest version: the reference solid itself turned by ROTATIONS[i] and moved off-axis
    by (0.37, -1.2, 0.05) in, then read by keygen."""
    key, solid, _ = _real(part)
    posed = _rotated(solid, ROTATIONS[i]).translate(cq.Vector(0.37 * INCH, -1.2 * INCH, 0.05 * INCH))
    s = score_part(key, keygen.extract(posed, units=key.units, part=part, source="posed"), C)
    assert s.score == pytest.approx(100.0, abs=1e-9) and s.exact


# Planted on real parts: A050211E thru holes; A050381E has no thru hole, so a blind tapped hole
# (start face kept); A050471E thru counterbores.
PLANTED = ("A050211E", "A050381E", "A050471E")


def _planted_hole(key):
    holes = [f for f in key.features if f.type in plant.PLAIN]
    return next((f for f in holes if f.thru), holes[0])


def _tol(f, key):
    return (f.tol or {}).get("position") or C.fallback_tol[key.units]


@real
@pytest.mark.parametrize("part", PLANTED)
def test_real_filled_hole_costs_its_weight_share(part):
    key, solid, _ = _real(part)
    h = _planted_hole(key)
    s = score_part(key, keygen.extract(plant.fill(solid, key, h.id), units=key.units, part=part, source="p"), C)
    assert s.row(h.id).status == "missing" and not s.extras
    assert s.score == pytest.approx(100 * (1 - s.row(h.id).weight / _weights(s)), abs=0.5)


@real
@pytest.mark.parametrize("part", PLANTED)
def test_real_hole_moved_two_tolerances(part):
    import numpy as np
    key, solid, _ = _real(part)
    h = _planted_hole(key)
    t = _tol(h, key)
    ax = np.asarray(h.axis, float)
    perp = np.cross(ax, [1.0, 0.0, 0.0] if abs(ax[0]) < 0.9 else [0.0, 1.0, 0.0])
    delta = perp / np.linalg.norm(perp) * 2 * t
    s = score_part(key, keygen.extract(plant.move(solid, key, h.id, delta), units=key.units, part=part,
                                       source="p"), C)
    row = s.row(h.id)
    assert row.status == "matched" and not s.extras
    assert row.attr_credits["position"] == pytest.approx(attr_credit(2 * t, t, C), abs=0.01)
    credit = feature_credit({**{a: 1.0 for a in row.attr_credits}, "position": attr_credit(2 * t, t, C)}, C)
    assert s.score == pytest.approx(100 * (1 - row.weight * (1 - credit) / _weights(s)), abs=0.5)
