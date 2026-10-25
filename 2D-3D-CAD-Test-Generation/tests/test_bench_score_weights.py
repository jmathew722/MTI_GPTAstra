"""Importance = tier x clamp(sqrt(feature size / part size), floor, 1); base body synthesised from the key."""
import pytest

from bench.features import Feature, Key
from bench.score_config import load
from bench.weights import BASE_ID, base_body, feature_size, weight

C = load()
KEY = Key(part="P", units="inch", source="s", envelope=[6.0, 4.0, 0.5], features=[
    Feature(id="K1", type="thru_hole", d=0.25, depth=0.5),
    Feature(id="K2", type="bore", d=3.0, depth=0.5),
    Feature(id="K3", type="tapped_hole", d=0.2, depth=0.4),
    Feature(id="K4", type="hole_pattern", members=["K1"])])


def test_base_body_from_envelope():
    b = base_body(KEY)
    assert b.id == BASE_ID and b.type == "base_body" and b.size == [6.0, 4.0, 0.5]


def test_sizes():
    assert feature_size(KEY.feature("K2")) == 3.0
    assert feature_size(base_body(KEY)) == 6.0


def test_weights_tier_times_size_with_floor():
    part = 6.0
    assert weight(base_body(KEY), part, C) == pytest.approx(10.0)
    assert weight(KEY.feature("K2"), part, C) == pytest.approx(3 * (3.0 / 6.0) ** 0.5)
    assert weight(KEY.feature("K1"), part, C) == pytest.approx(3 * 0.3)       # floored
    assert weight(KEY.feature("K3"), part, C) == pytest.approx(1 * 0.3)


def test_patterns_have_no_weight():
    assert weight(KEY.feature("K4"), 6.0, C) == 0.0
