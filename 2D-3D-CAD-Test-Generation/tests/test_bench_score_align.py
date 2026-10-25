"""align: 24 proper rotations; transforming a key keeps it in a bbox-min frame; best fit recovers the pose."""
import numpy as np
import pytest

from bench.align import ROTATIONS, best_fit, transform
from bench.features import Feature, Key


def _key():
    return Key(part="P", units="inch", source="s", envelope=[6.0, 4.0, 1.0], features=[
        Feature(id="K1", type="thru_hole", axis=[0, 0, 1], center=[1.0, 1.0, 0.0], d=0.25, depth=1.0),
        Feature(id="K2", type="thru_hole", axis=[0, 0, 1], center=[5.0, 1.0, 0.0], d=0.25, depth=1.0),
        Feature(id="K3", type="blind_hole", axis=[1, 0, 0], center=[0.0, 3.0, 0.5], d=0.2, depth=0.6),
        Feature(id="K4", type="pocket_step", normal=[0, 0, 1], offset=0.7, size=[2.0, 1.0, 0.0])])


def test_24_proper_rotations():
    assert len(ROTATIONS) == 24
    assert all(round(np.linalg.det(R)) == 1 for R in ROTATIONS)
    assert np.allclose(ROTATIONS[0], np.eye(3))


@pytest.mark.parametrize("i", range(24))
def test_best_fit_recovers_every_rotation(i):
    key = _key()
    moved = transform(key, ROTATIONS[i])
    fit = best_fit(key, moved)
    back = fit.apply(moved)
    for f in key.features:
        g = next(x for x in back.features if x.id == f.id)
        if f.center:
            assert np.allclose(g.center, f.center, atol=1e-9)
        if f.axis:
            assert np.allclose(np.abs(g.axis), np.abs(f.axis), atol=1e-9)
        if f.normal:
            assert np.allclose(g.normal, f.normal, atol=1e-9) and g.offset == pytest.approx(f.offset)
            assert np.allclose(g.size, f.size, atol=1e-9)
    assert np.allclose(back.envelope, key.envelope)


@pytest.mark.parametrize("i", range(24))
def test_transform_keeps_bbox_min_frame_and_planes(i):
    R = ROTATIONS[i]
    moved = transform(_key(), R)
    assert all(v > 0 for v in moved.envelope)
    for f in moved.features:
        if f.center:
            assert all(-1e-9 <= c <= e + 1e-9 for c, e in zip(f.center, moved.envelope))
        if f.axis:          # canonical sign: first non-zero component positive
            assert next(c for c in f.axis if abs(c) > 1e-9) > 0
    k4 = moved.feature("K4")
    # the plane z = 0.7 of the original passes through the rotated image of (0, 0, 0.7)
    p = transform(Key(part="P", units="inch", source="s", envelope=[6.0, 4.0, 1.0], features=[
        Feature(id="Q", type="chamfer", axis=[0, 0, 1], center=[2.0, 3.0, 0.7])]), R).feature("Q").center
    assert np.dot(k4.normal, p) == pytest.approx(k4.offset)
    assert next(c for c in k4.normal if abs(c) > 1e-9) > 0


def test_translated_generated_part_is_shifted_back():
    key = _key()
    gen = _key()
    gen.envelope = [6.1, 4.0, 1.0]                 # extra material on the min-x side: every feature moves +0.1
    for f in gen.features:
        if f.center:
            f.center[0] += 0.1
    fit = best_fit(key, gen)
    back = fit.apply(gen)
    for fid in ("K1", "K2"):
        assert np.allclose(back.feature(fid).center, key.feature(fid).center, atol=1e-9)


def test_one_moved_hole_does_not_drag_the_translation():
    key = _key()
    gen = _key()
    gen.feature("K1").center[0] += 0.05
    back = best_fit(key, gen).apply(gen)
    for fid in ("K2", "K3"):
        assert np.allclose(back.feature(fid).center, key.feature(fid).center, atol=1e-12)


def test_empty_generated_key_does_not_raise():
    key = _key()
    empty = Key(part="P", units="inch", source="s", envelope=[6.0, 4.0, 1.0], features=[])
    fit = best_fit(key, empty)
    assert np.allclose(fit.R, np.eye(3)) and np.allclose(fit.t, 0)
    no_env = Key(part="P", units="inch", source="s", envelope=[], features=[])
    fit = best_fit(key, no_env)
    assert np.allclose(fit.R, np.eye(3))
    assert fit.apply(no_env).features == []


def test_custom_cost_picks_the_pose():
    key = _key()
    want = transform(key, ROTATIONS[7]).envelope            # [6, 1, 4]: a pose the default would never pick
    fit = best_fit(key, key, cost=lambda g: 0.0 if np.allclose(g.envelope, want) else 1.0)
    assert fit.cost == 0.0 and np.allclose(fit.apply(key).envelope, want)


def test_uniform_shift_on_an_unchanged_envelope_is_not_hidden():
    # positions are referenced from the part's own body: with equal envelopes nothing justifies a shift
    key = _key()
    gen = _key()
    for f in gen.features:
        if f.center:
            f.center[1] += 0.02
    fit = best_fit(key, gen)
    assert np.allclose(fit.t, 0.0, atol=0.005 + 1e-12)
    back = fit.apply(gen)
    for fid in ("K1", "K2"):
        assert back.feature(fid).center[1] - key.feature(fid).center[1] > 0.014


def test_shift_is_bounded_by_the_envelope_difference():
    key = _key()
    gen = _key()
    gen.envelope = [6.1, 4.0, 1.0]
    for f in gen.features:
        if f.center:
            f.center[0] += 0.3                      # more than the 0.1 of extra stock
    fit = best_fit(key, gen)
    assert -0.1 - 0.005 - 1e-12 <= fit.t[0] <= 0.005 + 1e-12
