"""Typed loader for bench/score_config.yaml (defaults + optional override file)."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent / "score_config.yaml"


@dataclass(frozen=True)
class Credit:
    drop: float
    k: float


@dataclass(frozen=True)
class Config:
    credit: Credit
    shares: dict
    tiers: dict
    size_floor: float
    extra_penalty: float
    type_mismatch_cost: float
    gate_tol_multiple: float
    gate_part_fraction: float
    fallback_tol: dict
    unsupported_types: tuple


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path: Optional[Path] = None) -> Config:
    raw = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    if path is not None:
        raw = _merge(raw, yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
    return Config(credit=Credit(drop=float(raw["credit"]["drop"]), k=float(raw["credit"]["k"])),
                  shares=dict(raw["shares"]), tiers=dict(raw["tiers"]),
                  size_floor=float(raw["size_floor"]), extra_penalty=float(raw["extra_penalty"]),
                  type_mismatch_cost=float(raw["type_mismatch_cost"]),
                  gate_tol_multiple=float(raw["gate"]["tol_multiple"]),
                  gate_part_fraction=float(raw["gate"]["part_fraction"]),
                  fallback_tol=dict(raw["fallback_tol"]), unsupported_types=tuple(raw["unsupported_types"]))
