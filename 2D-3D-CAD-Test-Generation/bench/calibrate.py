"""Calibration table: planted errors on real benchmark parts, scored with the current score_config.

    python -m bench.calibrate [--config FILE]

Hole moves / fills / extras are real geometry edits (bench.plant, re-read by keygen). Size, type
and body edits are applied to the generated feature list (the STEP round-trip is covered by
tests/test_bench_score_planted.py). Keys are used without drawing overrides (model vs model), so
every lost point comes from the planted edit. No API calls, no SolidWorks; reads MTI_BENCH_DATA.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import numpy as np

from bench import config, keygen, plant
from bench.features import Key
from bench.score_config import load
from bench.scoring import score_part

PARTS = ("A050211E", "A050381E", "A050471E")


def _neutral(key: Key) -> Key:
    k = copy.deepcopy(key)
    k.overrides = []
    for fl in k.flags:
        fl.resolution = None
    return k


def _tol(f, key, cfg, attr="position"):
    return (f.tol or {}).get(attr) or cfg.fallback_tol[key.units]


def _perp(f, t):
    ax = np.asarray(f.axis, float)
    p = np.cross(ax, [1.0, 0.0, 0.0] if abs(ax[0]) < 0.9 else [0.0, 1.0, 0.0])
    return p / np.linalg.norm(p) * t


def _extra(solid, key: Key, h):
    """An extra thru hole like h, parallel to it, at the grid point (in the plane across its axis)
    that removes the most material and keeps clear of every existing centred feature."""
    ax = [i for i, a in enumerate(h.axis) if abs(a) > 0.9][0]
    others = [i for i in range(3) if i != ax]
    me = (h.cbore_d or h.d or 0.1)
    # keep-out radius around each centred cut feature: its own radius plus this hole's size
    taken = [(np.asarray(f.center, float), (f.cbore_d or f.csink_d or f.d or 0.0) / 2 + me)
             for f in key.features if f.center is not None and f.type not in ("turned_diameter", "boss", "chamfer",
                                                                                "fillet", "base_body")]
    best, best_cut = None, 0.0
    for fu in np.linspace(0.12, 0.88, 9):
        for fv in np.linspace(0.12, 0.88, 9):
            p = list(h.center)
            p[others[0]], p[others[1]] = fu * key.envelope[others[0]], fv * key.envelope[others[1]]
            if any(np.linalg.norm((np.asarray(p) - c)[others]) < r for c, r in taken):
                continue
            cut = solid.Volume() - plant.add(solid, key, p, h.d, h.axis).Volume()
            if cut > best_cut:
                best, best_cut = p, cut
    if best is None:
        raise plant.PlantError(f"{key.part}: no clear spot for an extra hole")
    return plant.add(solid, key, best, h.d, h.axis)


def variants(part: str, key: Key, solid, cfg):
    """Yield (edit label, generated key)."""
    gen0 = keygen.extract(solid, units=key.units, part=part, source="calib")
    holes = [f for f in key.features if f.type in plant.PLAIN]
    if holes:
        h = next((f for f in holes if f.thru), holes[0])
        t = _tol(h, key, cfg)
        for k in (1.5, 5.0):
            yield (f"{h.id} {h.type} moved {k:g}x tol ({k * t:.4f})",
                   keygen.extract(plant.move(solid, key, h.id, _perp(h, k * t)), units=key.units, part=part,
                                  source="calib"))
        yield f"{h.id} {h.type} missing", keygen.extract(plant.fill(solid, key, h.id), units=key.units,
                                                          part=part, source="calib")
        try:
            yield f"extra thru hole d={h.d:g}", keygen.extract(_extra(solid, key, h), units=key.units, part=part,
                                                                 source="calib")
        except plant.PlantError as e:
            print(f"{part:10} (extra hole skipped: {e})")
    big = max((f for f in gen0.features if f.type in ("bore", "turned_diameter") and f.d), key=lambda f: f.d,
              default=None)
    if big is not None:
        g = copy.deepcopy(gen0)
        kf = next(f for f in key.features if f.id == big.id) if key.feature(big.id) else big
        g.feature(big.id).d = big.d + 3 * _tol(kf, key, cfg, "size")
        yield f"{big.id} {big.type} d={big.d:g} made 3x tol oversize", g
    cb = next((f for f in gen0.features if f.type == "counterbore"), None)
    if cb is not None:
        g = copy.deepcopy(gen0)
        f = g.feature(cb.id)
        f.type, f.cbore_d, f.cbore_depth = ("thru_hole" if f.thru else "blind_hole"), None, None
        yield f"{cb.id} counterbore built as plain hole", g
    g = copy.deepcopy(gen0)
    ax = int(np.argmin(g.envelope))
    g.envelope[ax] += 3 * cfg.fallback_tol[key.units]
    yield f"body {['X', 'Y', 'Z'][ax]} extent {key.envelope[ax]:g} made 3x tol too big", g


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--parts", nargs="*", default=list(PARTS))
    args = ap.parse_args(argv)
    cfg = load(args.config)
    root = config.data_root(required=True)
    print(f"{'part':10} {'edit':52} {'score':>6} {'lost':>6}  worst feature (credit)")
    for part in args.parts:
        d = root / part
        key = _neutral(Key.load(d / "key.json"))
        solid = plant.read_solid(d / "reference.step")
        for label, gen in variants(part, key, solid, cfg):
            s = score_part(key, gen, cfg)
            worst = min(s.rows, key=lambda r: r.credit)
            ex = "".join(f" +extra {e.type} w={e.weight:.2f}" for e in s.extras)
            if worst.credit >= 1.0 and s.extras:
                worst = s.rows[0]
            ex = f" w={worst.weight:.2f}/W={sum(r.weight for r in s.rows):.1f}{ex}"
            print(f"{part:10} {label[:52]:52} {s.score:6.1f} {100 - s.score:6.1f}  "
                  f"{worst.feature_id} {worst.type} ({worst.credit:.2f}){ex}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
