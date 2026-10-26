"""score_part: identity = 100; planted errors cost exactly what the curve and weights say."""
import random

import pytest

from bench.align import ROTATIONS, transform
from bench.credit import attr_credit
from bench.features import Feature, Key
from bench.score_config import load
from bench.scoring import score_part

C = load()


def _key():
    return Key(part="P", units="inch", source="s", envelope=[6.0, 4.0, 1.0], features=[
        Feature(id="K1", type="thru_hole", axis=[0, 0, 1], center=[1.0, 1.0, 0.0], d=0.5, depth=1.0, thru=True),
        Feature(id="K2", type="thru_hole", axis=[0, 0, 1], center=[5.0, 1.0, 0.0], d=0.5, depth=1.0, thru=True),
        Feature(id="K3", type="tapped_hole", axis=[1, 0, 0], center=[0.0, 3.0, 0.5], d=0.2, depth=0.6),
        Feature(id="K4", type="bore", axis=[0, 0, 1], center=[3.0, 2.5, 0.0], d=1.5, depth=1.0, thru=True)])


def test_identity_is_100_and_exact():
    s = score_part(_key(), _key(), C)
    assert s.score == pytest.approx(100.0) and s.exact
    assert s.row("BASE").status == "matched" and s.row("BASE").weight == 10


@pytest.mark.parametrize("i", range(24))
def test_identity_under_rotation(i):
    s = score_part(_key(), transform(_key(), ROTATIONS[i], (0.0, 0.0, 0.0)), C)
    assert s.score == pytest.approx(100.0) and s.exact


@pytest.mark.parametrize("k, credit", [(0.5, 1.0), (2.0, 0.40), (5.0, 0.20)])
def test_moved_hole_costs_exactly_the_curve(k, credit):
    gen = _key()
    gen.feature("K1").center[0] += k * 0.005            # fallback tol 0.005 in
    s = score_part(_key(), gen, C)
    row = s.row("K1")
    assert row.attr_credits["position"] == pytest.approx(credit, abs=0.005)
    assert row.attr_credits["position"] == pytest.approx(attr_credit(k * 0.005, 0.005, C), abs=1e-6)
    assert all(r.credit == pytest.approx(1.0) for r in s.rows if r.feature_id != "K1")
    W = sum(r.weight for r in s.rows)
    expected = 100 * (1 - row.weight * (1 - row.credit) / W)
    assert s.score == pytest.approx(expected, abs=1e-6)


def test_missing_feature_costs_its_weight_share():
    gen = _key()
    gen.features = [f for f in gen.features if f.id != "K4"]
    s = score_part(_key(), gen, C)
    W = sum(r.weight for r in s.rows)
    assert s.row("K4").status == "missing"
    assert s.score == pytest.approx(100 * (1 - s.row("K4").weight / W), abs=1e-6)


def test_extra_feature_penalty():
    gen = _key()
    gen.features.append(Feature(id="K9", type="thru_hole", axis=[0, 0, 1], center=[3.0, 0.5, 0.0], d=0.5, depth=1.0))
    s = score_part(_key(), gen, C)
    W = sum(r.weight for r in s.rows)
    assert s.extras and s.score == pytest.approx(100 * (1 - 0.5 * s.extras[0].weight / W), abs=1e-6)
    assert not s.exact


def test_type_error_costs_only_the_type_share():
    key, gen = _key(), _key()
    key.feature("K3").type = "blind_hole"
    gen.feature("K3").type = "thru_hole"
    s = score_part(key, gen, C)
    assert s.row("K3").attr_credits["type"] == 0.0
    assert set(s.row("K3").attr_credits) == {"position", "size", "depth", "type"}
    assert s.row("K3").credit == pytest.approx(1 - C.shares["type"])   # all four attributes present


@pytest.mark.parametrize("gtype", ["blind_hole", "thru_hole"])
def test_tapped_hole_read_from_geometry_as_a_plain_hole_is_not_a_type_error(gtype):
    """A STEP carries no thread (threads are cosmetic), so a geometric reader (keygen) reports a
    tapped hole as the plain hole at its tap drill. That is the right geometry, not a type error;
    the tap drill diameter is still scored as size. (Real data: every tapped hole of A050381E
    lost 0.15 against MTI's own model.)"""
    gen = _key()
    gen.feature("K3").type = gtype
    s = score_part(_key(), gen, C)
    assert s.row("K3").attr_credits["type"] == 1.0
    assert s.score == pytest.approx(100.0) and s.exact
    gen.feature("K3").d += 10 * 0.005                  # wrong drill size is still caught
    assert score_part(_key(), gen, C).row("K3").attr_credits["size"] < 1.0


def test_plain_key_hole_built_as_tapped_is_still_a_type_error():
    key, gen = _key(), _key()
    key.feature("K3").type = "blind_hole"
    s = score_part(key, gen, C)                        # gen K3 is tapped_hole
    assert s.row("K3").attr_credits["type"] == 0.0


def test_counterbore_built_as_plain_hole_loses_only_type():
    key = _key()
    cb = key.feature("K1")
    cb.type, cb.cbore_d, cb.cbore_depth = "counterbore", 0.8, 0.25
    s = score_part(key, _key(), C)
    r = s.row("K1")
    assert r.attr_credits["type"] == 0.0
    assert all(c == 1.0 for a, c in r.attr_credits.items() if a != "type")


def test_thru_mismatch_is_a_depth_failure():
    gen = _key()
    gen.feature("K1").thru = False                     # same depth number, but blind
    s = score_part(_key(), gen, C)
    assert s.row("K1").attr_credits["depth"] == 0.0
    assert s.row("K1").attr_credits["position"] == 1.0


def test_thru_depth_is_not_scored_numerically():
    gen = _key()
    gen.feature("K1").depth = 0.9                      # both thru: the number does not matter
    assert score_part(_key(), gen, C).row("K1").attr_credits["depth"] == 1.0


def test_silent_attribute_not_scored_and_value_override_used():
    key = _key()
    key.overrides = [{"feature": "K4", "attr": "depth", "silent": True},
                     {"feature": "K1", "attr": "d", "value": 0.6}]
    gen = _key()
    gen.feature("K4").depth = 0.3
    gen.feature("K1").d = 0.6
    s = score_part(key, gen, C)
    assert "depth" not in s.row("K4").attr_credits and s.row("K1").credit == pytest.approx(1.0)


def test_expected_count_adds_drawing_only_instances():
    key = _key()
    key.overrides = [{"type": "thru_hole", "expected_count": 3}]
    s_missing = score_part(key, _key(), C)                        # generated has 2 thru holes too
    assert any(r.status == "missing" and r.feature_id.startswith("EXPECT") for r in s_missing.rows)
    gen = _key()
    gen.features.append(Feature(id="G9", type="thru_hole", axis=[0, 0, 1], center=[3, 3.5, 0], d=0.5, depth=1.0))
    s_found = score_part(key, gen, C)
    assert s_found.score > s_missing.score and not s_found.extras
    assert s_found.row("EXPECT-thru_hole-1").matched_id == "G9"


def test_score_bounds():
    gen = _key()
    gen.features = [Feature(id=f"X{i}", type="thru_hole", axis=[0, 0, 1], center=[0.1 * i, 3.9, 0], d=0.1,
                            depth=1.0) for i in range(40)]
    s = score_part(_key(), gen, C)
    assert 0.0 <= s.score <= 100.0


def test_empty_generated_part_scores_only_the_base_body():
    gen = Key(part="P", units="inch", source="s", envelope=[6.0, 4.0, 1.0], features=[])
    s = score_part(_key(), gen, C)
    W = sum(r.weight for r in s.rows)
    assert s.score == pytest.approx(100 * 10 / W) and not s.exact
    assert {r.status for r in s.rows if r.feature_id != "BASE"} == {"missing"}


def test_no_envelope_scores_zero_without_raising():
    gen = Key(part="P", units="inch", source="s", envelope=[], features=[])
    s = score_part(_key(), gen, C)
    assert s.score == 0.0 and s.row("BASE").status == "missing"


def test_half_tolerance_noise_is_still_100():
    rnd = random.Random(7)
    gen = _key()
    for f in gen.features:
        f.center = [c + rnd.uniform(-0.5, 0.5) * 0.005 / 1.8 for c in f.center]   # |offset| <= 0.5 tol
        f.d += rnd.uniform(-0.5, 0.5) * 0.005
    s = score_part(_key(), gen, C)
    assert s.score == pytest.approx(100.0) and s.exact


def test_feature_order_is_irrelevant():
    gen = _key()
    gen.feature("K1").center[0] += 0.02
    gen.feature("K4").d += 0.03
    a = score_part(_key(), gen, C).score
    gen.features.reverse()
    key = _key()
    key.features.reverse()
    assert score_part(key, gen, C).score == pytest.approx(a, abs=1e-9)


def test_larger_error_never_raises_the_score():
    prev = 101.0
    for k in (0, 0.5, 1, 1.5, 2, 5, 10, 15):
        gen = _key()
        gen.feature("K2").center[1] += k * 0.005
        s = score_part(_key(), gen, C).score
        assert s <= prev + 1e-9
        prev = s


def test_uniform_shift_with_equal_envelope_costs_every_hole():
    gen = _key()
    for f in gen.features:
        f.center[1] += 0.02                         # 4 x tol; K3 (axis x) moves across its axis too
    s = score_part(_key(), gen, C)
    assert s.score < 100.0 and not s.exact
    for fid in ("K1", "K2", "K3", "K4"):
        assert s.row(fid).attr_credits["position"] < 1.0


def test_three_of_four_moved_charges_only_the_moved():
    gen = _key()
    for fid in ("K1", "K2", "K4"):
        gen.feature(fid).center[1] += 0.1 * 0.2     # 0.02: inside the gate, 4 x tol
    s = score_part(_key(), gen, C)
    for fid in ("K1", "K2", "K4"):
        assert s.row(fid).attr_credits["position"] < 1.0
    assert s.row("K3").attr_credits["position"] == 1.0


def _chiral():
    holes = [(1.0, 1.0), (5.0, 1.0), (1.0, 3.0)]
    return Key(part="C", units="inch", source="s", envelope=[6.0, 4.0, 1.0], features=[
        Feature(id=f"K{i}", type="blind_hole", axis=[0, 0, 1], center=[x, y, 1.0], d=0.25, depth=0.5, thru=False)
        for i, (x, y) in enumerate(holes, 1)])


def test_blind_hole_from_the_opposite_face_loses_credit():
    # (On _key() this edit is the same solid turned over: K1/K2/K4 are symmetric, so use _chiral.)
    gen = _chiral()
    gen.feature("K1").center[2] = 0.0                # same axis line, drilled from the bottom face
    s = score_part(_chiral(), gen, C)
    assert s.score < 100.0 and not s.exact
    assert s.row("K1").status == "missing" or s.row("K1").attr_credits["position"] < 1.0
    assert all(s.row(f).credit == 1.0 for f in ("K2", "K3"))


def test_chiral_mirror_is_not_a_perfect_score():
    gen = _chiral()
    for f in gen.features:                            # mirror x -> 6 - x: not a proper rotation
        f.center[0] = 6.0 - f.center[0]
    s = score_part(_chiral(), gen, C)
    assert s.score < 100.0 and not s.exact
    assert score_part(_chiral(), _chiral(), C).score == pytest.approx(100.0)


@pytest.mark.parametrize("gdepth, ok", [(1.0, True), (0.5, False)])
def test_unknown_generated_thru_falls_back_to_numeric_depth(gdepth, ok):
    gen = _key()
    gen.feature("K1").thru, gen.feature("K1").depth = None, gdepth
    c = score_part(_key(), gen, C).row("K1").attr_credits["depth"]
    assert (c == 1.0) if ok else (c < 1.0)


def _twin():
    """Metric-twin case (A050031E/M): the model has plain holes where the drawing calls TAP, so
    the key has 0 tapped holes and a count override for 2."""
    k = Key(part="T", units="inch", source="s", envelope=[6.0, 4.0, 1.0], features=[
        Feature(id="K1", type="thru_hole", axis=[0, 0, 1], center=[1.0, 1.0, 0.0], d=0.5, depth=1.0, thru=True),
        Feature(id="K2", type="thru_hole", axis=[0, 0, 1], center=[5.0, 1.0, 0.0], d=0.5, depth=1.0, thru=True),
        Feature(id="K3", type="bore", axis=[0, 0, 1], center=[2.0, 3.0, 0.0], d=1.5, depth=1.0, thru=True)])
    k.overrides = [{"type": "tapped_hole", "expected_count": 2, "note": "callout says 2, key has 0"}]
    return k


def test_metric_twin_tapped_holes_are_not_double_counted():
    gen = _twin()
    gen.overrides = []
    for fid in ("K1", "K2"):
        gen.feature(fid).type = "tapped_hole"        # built as the drawing says
    s = score_part(_twin(), gen, C)
    assert s.score == pytest.approx(100.0) and s.exact
    assert not any(r.feature_id.startswith("EXPECT") for r in s.rows)
    assert s.row("K1").attr_credits["type"] == 1.0 and "drawing calls for tapped_hole" in s.row("K1").reason


def test_metric_twin_waiver_is_limited_to_the_shortfall():
    key = _twin()
    key.overrides = [{"type": "tapped_hole", "expected_count": 1}]
    gen = _twin()
    gen.overrides = []
    for fid in ("K1", "K2"):
        gen.feature(fid).type = "tapped_hole"
    s = score_part(key, gen, C)
    waived = [r for r in s.rows if r.feature_id in ("K1", "K2") and r.attr_credits["type"] == 1.0]
    assert len(waived) == 1 and not any(r.feature_id.startswith("EXPECT") for r in s.rows)


def test_base_body_credit_is_the_mean_of_its_axis_credits():
    from bench.credit import attr_credit
    gen = _key()
    tol = C.fallback_tol["inch"]
    gen.envelope = [gen.envelope[0], gen.envelope[1], gen.envelope[2] + 3 * tol]
    row = score_part(_key(), gen, C).row("BASE")
    assert row.credit == pytest.approx((2 + attr_credit(3 * tol, tol, C)) / 3)