"""Importance weights (spec 2026-10-24, 'Weights')."""
from __future__ import annotations

import math

from bench.features import HOLE_TYPES, Feature, Key
from bench.score_config import Config

BASE_ID = "BASE"


def base_body(key: Key) -> Feature:
    """Synthetic tier-1 feature: the envelope (plus, implicitly, the main profile) of the part."""
    return Feature(id=BASE_ID, type="base_body", size=[float(x) for x in key.envelope],
                   note="synthetic: part envelope")


def feature_size(f: Feature) -> float:
    """Largest characteristic dimension: diameters, planar extents and, for turned/other non-hole
    features, depth (length). A hole is sized by its diameter only: a long drill is no more
    important than a short one of the same size (calibration 2026-10-25)."""
    vals = [v for v in (f.d, f.cbore_d, f.csink_d) if v]
    if f.size:
        vals += [v for v in f.size if v]
    if f.type not in HOLE_TYPES and f.type != "base_body" and f.depth:
        vals.append(f.depth)
    return max(vals) if vals else 0.0


def weight(f: Feature, part_size: float, cfg: Config) -> float:
    tier = cfg.tiers.get(f.type, 0.0)
    if tier == 0.0:
        return 0.0                                   # e.g. hole_pattern: scored through its members
    if f.type == "base_body" or part_size <= 0:
        return float(tier)
    factor = math.sqrt(max(feature_size(f), 0.0) / part_size)
    return float(tier) * min(1.0, max(cfg.size_floor, factor))
