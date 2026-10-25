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
    flat-bottom blind hole from the top, optionally a counterbore (8 / 14 x 4) instead of the
    first thru hole."""
    top = cq.Workplane("XY").box(100, 60, 10, centered=False).faces(">Z").workplane(
        centerOption="ProjectedOrigin", origin=(0, 0, 0))
    plain = [p for p in thru if p != cbore_at]
    wp = top.pushPoints(plain).hole(8)
    if cbore_at is not None:
        wp = wp.faces(">Z").workplane(centerOption="ProjectedOrigin", origin=(0, 0, 0)) \
            .pushPoints([cbore_at]).cboreHole(8, 14, 4)
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
