"""match: families, tolerance-scaled cost, gate, optimal one-to-one assignment."""
import math

from bench.features import Feature
from bench.match import family, match, position_error, size_error
from bench.score_config import load

C = load()


def _h(i, x, y, d=0.25, t="thru_hole", axis=(0, 0, 1)):
    return Feature(id=i, type=t, axis=list(axis), center=[x, y, 0.0], d=d, depth=0.5)


def test_families():
    assert family("counterbore") == family("thru_hole") == "hole"
    assert family("bore") == family("turned_diameter") == "round"
    assert family("flat") == family("pocket_step") == "planar"
    assert family("hole_pattern") is None and family("base_body") is None


def test_optimal_assignment_beats_greedy():
    # Greedy in key order takes K1-G1 (0.45) and then cannot place K2 (G2 is 1.5 away, beyond the
    # 1.0 gate). The optimal assignment pairs both: K1-G2 (0.5) + K2-G1 (0.55).
    key = [_h("K1", 0, 0), _h("K2", 1.0, 0)]
    gen = [_h("G1", 0.45, 0), _h("G2", -0.5, 0)]
    pairs, missing, extra = match(key, gen, part_size=10.0, tol_of=lambda f, a: 0.05, cfg=C)
    assert sorted(pairs) == [("K1", "G2"), ("K2", "G1")]
    assert missing == [] and extra == []


def test_gate_makes_far_features_missing_and_extra():
    key = [_h("K1", 0, 0)]
    gen = [_h("G1", 5.0, 0)]                     # 5" away on a 10" part: beyond min(20*0.005, 1.0)
    pairs, missing, extra = match(key, gen, part_size=10.0, tol_of=lambda f, a: 0.005, cfg=C)
    assert pairs == [] and missing == ["K1"] and extra == ["G1"]


def test_type_mismatch_still_pairs_within_family():
    pairs, _, _ = match([_h("K1", 0, 0, t="counterbore")], [_h("G1", 0, 0)], 10.0, lambda f, a: 0.005, C)
    assert pairs == [("K1", "G1")]


def test_type_mismatch_cost_prefers_same_type():
    key = [_h("K1", 0, 0, t="counterbore")]
    gen = [_h("G1", 0.001, 0), _h("G2", 0.002, 0, t="counterbore")]
    pairs, _, extra = match(key, gen, 10.0, lambda f, a: 0.005, C)
    assert pairs == [("K1", "G2")] and extra == ["G1"]


def test_different_families_never_pair():
    pairs, missing, extra = match([_h("K1", 0, 0, t="bore")], [_h("G1", 0, 0)], 10.0, lambda f, a: 0.005, C)
    assert pairs == [] and missing == ["K1"] and extra == ["G1"]


def test_patterns_and_base_body_are_not_matched_here():
    pairs, missing, extra = match([Feature(id="K9", type="hole_pattern", members=["K1"])],
                                  [Feature(id="G9", type="hole_pattern", members=["G1"])], 10.0,
                                  lambda f, a: 0.005, C)
    assert pairs == [] and missing == [] and extra == []


def test_position_error_ignores_offset_along_the_axis():
    a = _h("K1", 1.0, 1.0)
    b = Feature(id="G1", type="thru_hole", axis=[0, 0, 1], center=[1.0, 1.003, 1.0], d=0.25)
    assert math.isclose(position_error(a, b), 0.003, abs_tol=1e-12)


def test_crossed_axes_or_normals_never_pair():
    a = _h("K1", 1.0, 1.0)
    b = _h("G1", 1.0, 1.0, axis=(1, 0, 0))
    assert position_error(a, b) == math.inf
    pa = Feature(id="K2", type="pocket_step", normal=[0, 0, 1], offset=0.5, size=[1, 1, 0])
    pb = Feature(id="G2", type="pocket_step", normal=[1, 0, 0], offset=0.5, size=[0, 1, 1])
    assert position_error(pa, pb) == math.inf
    assert match([pa], [pb], 10.0, lambda f, a: 0.005, C) == ([], ["K2"], ["G2"])


def test_planar_position_is_offset_difference():
    pa = Feature(id="K2", type="flat", normal=[0, 0, 1], offset=0.5, size=[1, 1, 0])
    pb = Feature(id="G2", type="flat", normal=[0, 0, 1], offset=0.503, size=[1, 1, 0])
    assert math.isclose(position_error(pa, pb), 0.003, abs_tol=1e-12)


def test_size_error_uses_attributes_present_on_both():
    cb = Feature(id="K1", type="counterbore", axis=[0, 0, 1], center=[0, 0, 0], d=0.25, cbore_d=0.4)
    plain = Feature(id="G1", type="thru_hole", axis=[0, 0, 1], center=[0, 0, 0], d=0.26)
    assert math.isclose(size_error(cb, plain), 0.01, abs_tol=1e-12)
