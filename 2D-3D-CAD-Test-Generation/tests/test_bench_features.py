"""bench.features: answer-key model round-trips through JSON; counts and sign-off state."""
from bench.features import FEATURE_TYPES, Feature, Flag, Key


def _key():
    return Key(part="P1", units="inch", source="reference.step", envelope=[4.0, 3.0, 1.0],
               features=[Feature(id="K001", type="thru_hole", axis=[0, 0, 1], center=[1, 1, 0], d=0.25,
                                 depth=1.0, thru=True),
                         Feature(id="K002", type="thru_hole", axis=[0, 0, 1], center=[3, 1, 0], d=0.25,
                                 depth=1.0, thru=True),
                         Feature(id="K003", type="hole_pattern", members=["K001", "K002"],
                                 pattern={"mode": "line", "count": 2})],
               flags=[Flag(kind="unexplained_key_value", detail="d 0.25", feature="K001")])


def test_roundtrip(tmp_path):
    k = _key()
    p = tmp_path / "key.json"
    k.save(p)
    assert Key.load(p) == k


def test_counts_exclude_nothing_and_types_are_known():
    c = _key().counts()
    assert c == {"thru_hole": 2, "hole_pattern": 1}
    assert set(c) <= set(FEATURE_TYPES)


def test_signed_and_open_flags():
    k = _key()
    assert not k.signed and k.open_flags() == k.flags
    k.flags[0].resolution = "accepted: drawing gives tap size"
    assert k.open_flags() == []
    k.signoff = {"kind": "human", "by": "smcanuff", "date": "2026-10-24"}
    assert k.signed


def test_unknown_type_rejected():
    import pytest
    with pytest.raises(ValueError):
        Feature(id="K9", type="spline_thing")
