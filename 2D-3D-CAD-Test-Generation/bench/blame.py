"""Stage blame (spec 2026-10-24, 'Stage blame'): the first stage at fault for each lost point.

For each key row with credit < 1 (and each extra generated feature), in order:
  ground_truth -> unsupported -> extraction -> planner / cadquery -> solidworks.
The CadQuery reference is scored by the same score_part against the same key, so "the
reference already has this error" is a direct comparison of the two PartScores."""
from __future__ import annotations

from dataclasses import dataclass

from bench import overrides
from bench.features import Key
from bench.score_config import Config

STAGES = ("ground_truth", "unsupported", "extraction", "planner", "cadquery", "solidworks")
_FULL = 1.0 - 1e-12
_EPS = 1e-9
_CALLOUT_FIELDS = ("diameter", "depth", "cbore_diameter", "cbore_depth", "csink_diameter",
                   "x_position", "y_position", "pattern_spacing")


@dataclass
class Blame:
    stage: str
    reason: str
    points: float


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > _EPS else None


def extracted_values(extraction) -> list[float]:
    """Every positive number the extraction states (pipeline/schema.py DrawingData): dimension
    values and their candidate readings (a radius also states its diameter and vice versa),
    and the hole callouts' sizes, depths, positions and pattern spacings."""
    vals: list[float] = []
    ext = extraction or {}
    for d in ext.get("dimensions") or []:
        kind = str(d.get("type") or "")
        for raw in [d.get("value"), *(d.get("possible_values") or [])]:
            v = _num(raw)
            if v is None:
                continue
            vals.append(v)
            if kind == "radial":
                vals.append(2 * v)
            elif kind == "diameter":
                vals.append(v / 2)
    for h in ext.get("hole_callouts") or []:
        for name in _CALLOUT_FIELDS:
            v = _num(h.get(name))
            if v is not None:
                vals.append(v)
        for p in h.get("instance_positions") or []:
            vals.extend(v for v in map(_num, p) if v is not None)
    return vals


def _tol(f, attr: str, units: str, cfg: Config) -> float:
    return float((f.tol or {}).get(attr) or cfg.fallback_tol.get(units, cfg.fallback_tol["inch"]))


def _lossy(r) -> set:
    """Scored attributes that lost credit. A missing row lost everything (None = all)."""
    if r.status == "missing" or not r.attr_credits:
        return None
    return {a for a, c in r.attr_credits.items() if c < _FULL}


def _groups(f, attr: str, vals: list, t: float) -> list[list[float]]:
    """Linked values of one attribute are alternatives (any one stated is enough), except size:
    the drill d and the cbore_d / csink_d are separate quantities, each needing one value.
    Feature.links does not record which field a value explains, so a size value is assigned to
    every size field it is within tolerance of; values near no field form one more group."""
    if attr != "size":
        return [list(vals)]
    fields = [x for x in (f.d, f.cbore_d, f.csink_d) if x is not None]
    groups = [[v for v in vals if abs(v - x) <= t + _EPS] for x in fields]
    rest = [v for v in vals if not any(abs(v - x) <= t + _EPS for x in fields)]
    return [g for g in groups if g] + ([rest] if rest else [])


def _missing_links(f, units: str, extracted: list[float], cfg: Config, attrs) -> list[float]:
    """Drawing values for the lossy attributes (attrs; None = all) of which no alternative is in
    the extraction within the feature's tolerance for that attribute."""
    miss = set()
    for attr, vals in (f.links or {}).items():
        if attrs is not None and attr not in attrs:
            continue
        t = _tol(f, attr, units, cfg)
        for g in _groups(f, attr, vals, t):
            if not any(abs(v - e) <= t + _EPS for v in g for e in extracted):
                miss.update(g)
    return sorted(miss)


def _overridden(key: Key, r) -> bool:
    """ground_truth: a drawing-only instance (count override), or an override (explicit or
    derived from a resolution) on an attribute that lost credit. A missing row counts when the
    feature has a value override (a changed key value can push the pair past the match gate)."""
    if r.feature_id.startswith("EXPECT"):
        return True
    touched = overrides.override_attrs(key, r.feature_id)
    lossy = _lossy(r)
    if lossy is None:
        return any(o.get("feature") == r.feature_id and "value" in o for o in key.overrides)
    return bool(touched & lossy)


# plan feature kind -> key feature types it can produce (bench.features.FEATURE_TYPES)
_HOLES = {"thru_hole", "blind_hole", "tapped_hole", "counterbore", "countersink", "bore"}
_KIND_TYPES = {
    "hole": _HOLES,
    "prism:add": {"base_body", "boss", "flat", "pocket_step", "slot"},
    "prism:cut": {"pocket_step", "slot", "flat", "bore"},
    "revolve": {"base_body", "turned_diameter", "bore", "boss", "flat"},
    "edge_op:fillet": {"fillet"},
    "edge_op:chamfer": {"chamfer"},
}


def _plan_features(plan) -> dict:
    p = (plan or {}).get("plan", plan) or {}
    return {f.get("id"): f for f in (p.get("features") or []) if isinstance(f, dict)}


def _kind_types(f: dict, feats: dict, depth: int = 0) -> set:
    kind = f.get("kind")
    if kind == "pattern" and depth < 5 and f.get("seed") in feats:
        return _kind_types(feats[f["seed"]], feats, depth + 1)
    for k in (f"{kind}:{f.get('op') or f.get('operation')}", kind):
        if k in _KIND_TYPES:
            return _KIND_TYPES[k]
    return set()


def _compatible_skips(typ: str, skipped: dict, plan) -> dict:
    """The skipped plan features that could have produced a key feature of type `typ`. Without
    the plan a skip's kind is unknown, so none counts (real runs mostly skip unrelated fillets)."""
    feats = _plan_features(plan)
    return {fid: why for fid, why in skipped.items() if fid in feats and typ in _kind_types(feats[fid], feats)}


def blame_part(sw, cq, key: Key, extraction: dict, ir_report: dict, cfg: Config, plan=None) -> dict:
    """-> {feature_id or 'extra:<id>': Blame} for every row with credit < 1 and every SW extra.
    Also writes Row.blame / Row.reason and Extra.blame on `sw`.

    An empty extraction (no JSON saved) gives no evidence either way, so the extraction check
    is skipped rather than blaming every linked feature. `plan` is plan.json (or its "plan"):
    it tells which skipped plan features (ir_report cq_skipped) could be this key row.

    Order: ground_truth, then a correct CadQuery reference -> solidworks (it proves the
    extraction and plan sufficed), unsupported, extraction, cadquery, planner."""
    out: dict = {}
    extracted = extracted_values(extraction)
    cq_rows = {r.feature_id: r for r in cq.rows}
    skipped = (ir_report or {}).get("cq_skipped") or {}
    feats = {f.id: f for f in key.features}
    for r in sw.rows:
        if r.credit >= _FULL:
            continue
        f = feats.get(r.feature_id)
        c = cq_rows.get(r.feature_id)
        typ = f.type if f is not None else r.type
        if _overridden(key, r):
            b = Blame("ground_truth", "drawing override / model-drawing difference", r.points_lost)
        elif c is not None and c.credit >= _FULL:
            b = Blame("solidworks", "CadQuery reference correct; SolidWorks part differs", r.points_lost)
        elif typ in cfg.unsupported_types:
            b = Blame("unsupported", f"{typ} cannot be expressed in the IR", r.points_lost)
        elif f is not None and extraction and (miss := _missing_links(f, key.units, extracted, cfg, _lossy(r))):
            b = Blame("extraction", f"drawing value(s) {miss} not in the extraction (within tolerance)",
                      r.points_lost)
        elif r.status == "missing" and (sk := _compatible_skips(typ, skipped, plan)):
            b = Blame("cadquery", "reference skipped " + "; ".join(f"{k}: {v}" for k, v in sorted(sk.items())),
                      r.points_lost)
        else:
            b = Blame("planner", "the plan's CadQuery reference already has this error", r.points_lost)
        out[r.feature_id] = b
        r.blame, r.reason = b.stage, (r.reason + "; " if r.reason else "") + b.reason
    cq_extra_types = [e.type for e in cq.extras]
    for e in sw.extras:
        stage = "planner" if e.type in cq_extra_types else "solidworks"
        if stage == "planner":
            cq_extra_types.remove(e.type)
            reason = "extra feature not on the drawing; the CadQuery reference has it too"
        else:
            reason = "extra feature not on the drawing; only the SolidWorks part has it"
        out[f"extra:{e.feature_id}"] = Blame(stage, reason, e.points_lost)
        e.blame = stage
    return out


def rollup(parts: list) -> dict:
    """parts: [(PartScore, {id: Blame})] -> points lost by stage, by feature type, by tier."""
    by_stage: dict = {}
    by_type: dict = {}
    by_tier: dict = {}

    def add(d, k, v):
        d[k] = d.get(k, 0.0) + v

    for ps, bl in parts:
        rows = {r.feature_id: r for r in ps.rows}
        extras = {f"extra:{e.feature_id}": e for e in ps.extras}
        for fid, b in bl.items():
            add(by_stage, b.stage, b.points)
            r, e = rows.get(fid), extras.get(fid)
            add(by_type, r.type if r else (e.type if e else "extra"), b.points)
            add(by_tier, f"{r.tier_weight:g}" if r else "extra", b.points)
    return {"by_stage": by_stage, "by_type": by_type, "by_tier": by_tier}
