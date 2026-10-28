"""Part score (spec 2026-10-24, 'Scoring').

score = max(0, 100 x (sum w_i c_i - extra_penalty x sum w_extra) / sum w_i) over the key's
features plus the synthetic base body (from the envelope) plus drawing-only instances that a
count override calls for. Exact part = every credit 1 and no extras.

The key is first made effective (bench.overrides.apply: value overrides applied, silent
attributes dropped, expected counts and drawing-only values listed). The generated key is posed
by bench.align.best_fit with this very score as the cost, so the pose is always the best-scoring
one (a symmetric part loses nothing to an equivalent pose)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from bench import align, overrides
from bench.credit import attr_credit, feature_credit
from bench.features import Feature, Key
from bench.match import match, position_error, same_type, size_error
from bench.score_config import Config
from bench.weights import BASE_ID, base_body, weight

_NOT_MATCHED = ("hole_pattern", "base_body")      # patterns: scored through members; base body: synthetic
_TYPE_SPECIFIC_SIZE = ("cbore_d", "csink_d")


@dataclass
class Row:
    feature_id: str
    type: str
    tier_weight: float
    weight: float
    status: str                       # matched | missing
    matched_id: Optional[str] = None
    errors: dict = field(default_factory=dict)        # attr -> (abs error, error / tol)
    attr_credits: dict = field(default_factory=dict)
    credit: float = 0.0
    points_lost: float = 0.0
    blame: str = ""
    reason: str = ""


@dataclass
class Extra:
    feature_id: str
    type: str
    weight: float
    points_lost: float = 0.0
    blame: str = ""


@dataclass
class PartScore:
    part: str
    score: float
    exact: bool
    rows: list
    extras: list
    drawing_only: list
    pose: object = None
    practices: Optional[float] = None    # spec 2b; weight 0 for now

    def row(self, fid: str) -> Row:
        return next(r for r in self.rows if r.feature_id == fid)


def _tol(f: Feature, attr: str, units: str, cfg: Config) -> float:
    return float((f.tol or {}).get(attr) or cfg.fallback_tol.get(units, cfg.fallback_tol["inch"]))


def _has_size(f: Feature) -> bool:
    return any(v is not None for v in (f.d, f.cbore_d, f.csink_d)) or bool(f.size)


def _attr_errors(k: Feature, g: Feature) -> dict:
    """Absolute error per scored attribute present on the key feature (inf = outright failure)."""
    out = {"type": 0.0 if same_type(k.type, g.type) else 1.0}
    if k.center is not None or k.normal is not None:
        out["position"] = position_error(k, g)
    if _has_size(k):
        se = size_error(k, g)
        if k.type == g.type and any(getattr(k, a) is not None and getattr(g, a) is None
                                    for a in _TYPE_SPECIFIC_SIZE):
            se = math.inf
        out["size"] = math.inf if se is None else se
    dp = []
    if k.thru is not None and g.thru is not None and k.thru != g.thru:
        dp.append(math.inf)                       # thru vs blind: a depth failure whatever the numbers
    elif k.thru and g.thru:
        dp.append(0.0)                            # thru on both: depth is not scored numerically
    elif k.depth is not None:                     # blind, or thru unknown on the generated side
        dp.append(abs(k.depth - g.depth) if g.depth is not None else math.inf)
    elif k.thru:                                  # thru key without a depth, generated unknown
        dp.append(math.inf)
    if k.cbore_depth is not None:
        if g.cbore_depth is not None:
            dp.append(abs(k.cbore_depth - g.cbore_depth))
        elif k.type == g.type:
            dp.append(math.inf)
    if dp:
        out["depth"] = max(dp)
    return out


def _credits(fid: str, errs: dict, tol_of, silent: set, cfg: Config) -> tuple[dict, dict]:
    credits, shown = {}, {}
    for attr, err in errs.items():
        if (fid, attr) in silent:
            continue
        if attr == "type":
            credits["type"] = 1.0 if err == 0.0 else 0.0
            continue
        t = tol_of(attr)
        credits[attr] = 0.0 if math.isinf(err) else attr_credit(err, t, cfg)
        shown[attr] = (err, err / t if t else math.inf)
    return credits, shown


def _base_row(k: Key, gen: Key, part_size: float, cfg: Config) -> Row:
    kb = base_body(k)
    w = weight(kb, part_size, cfg)
    tier = cfg.tiers.get("base_body", 0)
    if not gen.envelope or len(gen.envelope) != len(k.envelope):
        return Row(BASE_ID, "base_body", tier, w, "missing", reason="generated part has no envelope")
    # per axis (the pose is fixed); the body's size credit is the mean of the three axis credits, so
    # one extent slightly off (often a secondary cut such as a deep flat) costs a third, not the body
    t = _tol(kb, "size", k.units, cfg)
    errs = [abs(a - b) for a, b in zip(k.envelope, gen.envelope)]
    size = sum(attr_credit(e, t, cfg) for e in errs) / len(errs)
    err = max(errs)
    return Row(BASE_ID, "base_body", tier, w, "matched", BASE_ID, errors={"size": (err, err / t if t else math.inf)},
               attr_credits={"size": size}, credit=feature_credit({"size": size}, cfg))


def _evaluate(eff: overrides.Effective, gen: Key, cfg: Config) -> tuple[PartScore, float]:
    """Score an already-posed generated key. -> (PartScore, unclamped score)."""
    k = eff.key
    part_size = max(k.envelope, default=0.0)
    tol_of = lambda f, a: _tol(f, a, k.units, cfg)  # noqa: E731
    kf = [f for f in k.features if f.type not in _NOT_MATCHED]
    gf = [f for f in gen.features if f.type not in _NOT_MATCHED]
    pairs, missing, extra = match(kf, gf, part_size, tol_of, cfg)
    by_k = {f.id: f for f in kf}
    by_g = {f.id: f for f in gf}

    rows = [_base_row(k, gen, part_size, cfg)]
    # Count overrides: the drawing calls for n of a type the key has fewer of (shortfall). In the
    # metric-twin case the key holds those very holes as another hole type, so a generated
    # feature of the called-for type paired with such a key hole keeps its type credit and
    # fills one unit of the shortfall; only what is left becomes drawing-only (EXPECT) rows.
    shortfall = {typ: n - sum(1 for f in kf if f.type == typ) for typ, n in eff.expected_counts.items()}
    for kid, gid in pairs:
        f, g = by_k[kid], by_g[gid]
        errs = _attr_errors(f, g)
        reason = ""
        if not same_type(f.type, g.type) and shortfall.get(g.type, 0) > 0:
            shortfall[g.type] -= 1
            errs["type"] = 0.0
            reason = f"drawing calls for {g.type} (count override); key has {f.type}"
        credits, shown = _credits(kid, errs, lambda a, f=f: tol_of(f, a), eff.silent, cfg)
        rows.append(Row(kid, f.type, cfg.tiers.get(f.type, 0), weight(f, part_size, cfg), "matched", gid,
                        errors=shown, attr_credits=credits, credit=feature_credit(credits, cfg), reason=reason))
    for kid in missing:
        f = by_k[kid]
        rows.append(Row(kid, f.type, cfg.tiers.get(f.type, 0), weight(f, part_size, cfg), "missing"))

    # Drawing-only instances (count overrides): the drawing calls for more of a type than the key
    # has. Each is satisfied by an extra generated feature of that type and size; position is not
    # scored (the drawing does not place it relative to the model's features).
    extras_left = list(extra)
    for typ, short in sorted(shortfall.items()):
        proto = next((f for f in kf if f.type == typ), Feature(id="EXPECT", type=typ))
        for i in range(max(0, short)):
            fid = f"EXPECT-{typ}-{i + 1}"
            cand = next((gid for gid in extras_left if by_g[gid].type == typ
                         and (proto.d is None or by_g[gid].d is None
                              or abs(by_g[gid].d - proto.d) <= tol_of(proto, "size") * (1 + 1e-9))), None)
            w = weight(proto, part_size, cfg)
            if cand:
                extras_left.remove(cand)
                rows.append(Row(fid, typ, cfg.tiers.get(typ, 0), w, "matched", cand, credit=1.0,
                                reason="drawing-only instance (count override); position not scored"))
            else:
                rows.append(Row(fid, typ, cfg.tiers.get(typ, 0), w, "missing",
                                reason="drawing calls for it (count override)"))

    extras = [Extra(gid, by_g[gid].type, weight(by_g[gid], part_size, cfg)) for gid in extras_left]
    W = sum(r.weight for r in rows) or 1.0
    for r in rows:
        r.points_lost = 100.0 * r.weight * (1.0 - r.credit) / W
    for e in extras:
        e.points_lost = 100.0 * cfg.extra_penalty * e.weight / W
    raw = 100.0 - sum(r.points_lost for r in rows) - sum(e.points_lost for e in extras)
    exact = not extras and all(r.credit >= 1.0 - 1e-12 for r in rows)
    return PartScore(k.part, max(0.0, min(100.0, raw)), exact, rows, extras, list(eff.drawing_only)), raw


def score_part(key: Key, generated: Key, cfg: Config) -> PartScore:
    eff = overrides.apply(key)
    k = eff.key
    fit = align.best_fit(k, generated, cost=lambda g: -_evaluate(eff, g, cfg)[1],
                         tol=lambda f: _tol(f, "position", k.units, cfg))
    ps, _ = _evaluate(eff, fit.apply(generated), cfg)
    ps.pose = fit
    return ps


def add_extras(ps: PartScore, features: list, key: Key, cfg: Config) -> PartScore:
    """Count generated features that took no part in matching (e.g. the features of a second
    body in a multi-body part) as extras, and re-total the score. Changes and returns `ps`."""
    part_size = max(key.envelope, default=0.0)
    W = sum(r.weight for r in ps.rows) or 1.0
    for f in features:
        if f.type in _NOT_MATCHED:
            continue
        w = weight(f, part_size, cfg)
        ps.extras.append(Extra(f.id, f.type, w, 100.0 * cfg.extra_penalty * w / W))
    raw = 100.0 - sum(r.points_lost for r in ps.rows) - sum(e.points_lost for e in ps.extras)
    ps.score = max(0.0, min(100.0, raw))
    ps.exact = ps.exact and not ps.extras
    return ps
