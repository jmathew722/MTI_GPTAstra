"""Attribute error -> credit (spec 2026-10-24, 'Credit')."""
from __future__ import annotations

import math

from bench.score_config import Config

_EPS = 1e-12


def attr_credit(error: float, tol: float, cfg: Config) -> float:
    """1 within tolerance; drop * exp(-(e - 1) / k) beyond it, with e = |error| / tol."""
    error = abs(error)
    if tol <= _EPS:
        return 1.0 if error <= _EPS else cfg.credit.drop * math.exp(-1.0 / cfg.credit.k)
    e = error / tol
    if e <= 1.0 + 1e-9:
        return 1.0
    return cfg.credit.drop * math.exp(-(e - 1.0) / cfg.credit.k)


def feature_credit(attr_credits: dict, cfg: Config) -> float:
    """Weighted mix of the attributes present; shares renormalise over them."""
    present = {a: c for a, c in attr_credits.items() if a in cfg.shares}
    total = sum(cfg.shares[a] for a in present)
    if total <= 0:
        return 1.0
    return sum(cfg.shares[a] * c for a, c in present.items()) / total
