"""Credit: full inside tolerance, a 0.5 drop just past it, then exponential decay."""
import pytest

from bench.credit import attr_credit, feature_credit
from bench.score_config import load

C = load()


@pytest.mark.parametrize("e, expected", [(0, 1.0), (0.5, 1.0), (1.0, 1.0), (2, 0.40), (5, 0.20), (10, 0.067)])
def test_curve_points(e, expected):
    assert attr_credit(e * 0.005, 0.005, C) == pytest.approx(expected, abs=0.005)


def test_drop_just_past_tolerance():
    assert attr_credit(0.005 * 1.0001, 0.005, C) == pytest.approx(0.5, abs=1e-3)


def test_monotone_non_increasing():
    vals = [attr_credit(x / 1000, 0.005, C) for x in range(0, 200)]
    assert all(a >= b - 1e-12 for a, b in zip(vals, vals[1:]))
    assert all(0.0 <= v <= 1.0 for v in vals)


def test_zero_tolerance_is_guarded():
    assert attr_credit(0.0, 0.0, C) == 1.0 and attr_credit(1e-9, 0.0, C) < 1.0


def test_feature_credit_renormalises_missing_attributes():
    # only size and type present: their shares renormalise over the two
    s, t = C.shares["size"], C.shares["type"]
    assert feature_credit({"size": 0.5, "type": 1.0}, C) == pytest.approx((0.5 * s + t) / (s + t))
    assert feature_credit({}, C) == 1.0
    assert feature_credit({"position": 1.0, "size": 1.0, "depth": 1.0, "type": 1.0}, C) == 1.0
