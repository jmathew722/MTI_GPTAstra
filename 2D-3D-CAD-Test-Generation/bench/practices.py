"""MTI practices score (spec docs/superpowers/specs/2026-10-25-practices-score-design.md, 2b).

``check_part(tree, ir_report, plan, cfg) -> PracticeScore``: pure, no SolidWorks. A separate
0-100 number per part, reported next to the geometry score and never blended into it.

Inputs:
* ``tree``: the feature-tree record (``bench/sw_tree.py``; ``feature_tree.json``), a list in
  tree order of ``{"name", "type", "index", "status", "subs": [{"name", "type", "status"}]}``.
  ``None`` means the SLDPRT was not read: C3, C4, C5 and C7 are then "not checked".
* ``ir_report``: ``ir_report.json`` (``conventions``, ``mti_review``, ``sw_features``, ``cq_skipped``).
* ``plan``: ``plan.json`` (``{"dims": ..., "plan": {"features": [...]}}``).
* ``cfg``: a ``score_config.Config`` (its ``practices`` section) or that section as a dict.

Checks C1 and C2 read the compiler's own report (*self-reported*): an independent SLDPRT check
would need SolidWorks APIs this repo has not verified (spec, hard rule 1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

CHECK_IDS = ("C1", "C2", "C3", "C4", "C5", "C6", "C7")
NAMES = {
    "C1": "origin centered",
    "C2": "base sketch on Top plane, Mid Plane extrude",
    "C3": "sketches fully defined",
    "C4": "fillets and chamfers last",
    "C5": "Hole Wizard placed from 2D sketches",
    "C6": "one Hole Wizard feature per hole per face",
    "C7": "no avoided features",
}
DEFAULTS = {
    "weights": {c: 1 for c in CHECK_IDS},
    "edge_ops": ["Fillet", "Chamfer"],
    "solid_ops": ["Extrusion", "ICE", "Cut", "HoleWzd", "Revolution", "RevCut", "LPattern", "CirPattern"],
    "avoid": ["Sweep", "SweepCut", "Blend", "BlendCut", "Shell", "Draft", "Rib", "MoveFace", "MoveCopyBody",
              "Boundary", "BoundaryCut"],
    "three_d_sketch": "3DProfileFeature",
}
FULLY_DEFINED = 3          # swConstrainedStatus_e (the IR compiler's mapping, error log E023)
SKETCH = "ProfileFeature"
HOLE_WIZARD = "HoleWzd"
# SolidWorks type -> the IR kind (pipeline/ir/mti_review.AVOID_KINDS) that would have planned it
AVOID_KIND = {"Sweep": "sweep", "SweepCut": "sweep", "Blend": "loft", "BlendCut": "loft", "Shell": "shell",
              "Draft": "draft", "Rib": "rib", "MoveFace": "move_face", "MoveCopyBody": "move_copy_body",
              "Boundary": "boundary", "BoundaryCut": "boundary"}
NOT_CHECKED = "not checked (no feature tree: SLDPRT not read)"


@dataclass
class Check:
    id: str
    name: str
    credit: Optional[float]
    applicable: bool
    source: str                    # sldprt | self-reported | plan | proxy
    stage: Optional[str] = None    # blame stage when the check lost credit
    reason: str = ""


@dataclass
class PracticeScore:
    score: Optional[float]         # None when no check applies
    rows: list = field(default_factory=list)
    checked: bool = False          # the SLDPRT feature tree was read


def _settings(cfg) -> dict:
    p = cfg if isinstance(cfg, dict) else (getattr(cfg, "practices", None) or {})
    out = {**DEFAULTS, **p}
    out["weights"] = {**DEFAULTS["weights"], **(p.get("weights") or {})}
    return out


def _row(cid: str, source: str, credit: Optional[float] = None, reason: str = "", stage: Optional[str] = None,
         applicable: bool = True) -> Check:
    if not applicable:
        return Check(cid, NAMES[cid], None, False, source, None, reason)
    return Check(cid, NAMES[cid], float(credit), True, source, stage if credit < 1.0 else None, reason)


def _na(cid: str, source: str, reason: str) -> Check:
    return _row(cid, source, reason=reason, applicable=False)


# --- C1, C2: the compiler's own conventions report -----------------------------------------

def c1_origin(ir: dict) -> Check:
    conv = (ir or {}).get("conventions")
    if not conv:
        return _na("C1", "self-reported", "no ir_report conventions")
    for s in conv:
        if "origin centered:" in s:
            if "True" in s:
                return _row("C1", "self-reported", 1.0, s)
            if "False" in s:
                return _row("C1", "self-reported", 0.0, "base body not centered on the origin", "solidworks")
    return _na("C1", "self-reported", "origin not checked by the compiler")


def c2_mid_plane(ir: dict) -> Check:
    conv = (ir or {}).get("conventions")
    if not conv:
        return _na("C2", "self-reported", "no ir_report conventions")
    for s in conv:
        if "Mid Plane did not match" in s:
            return _row("C2", "self-reported", 0.0, s, "solidworks")
    for s in conv:
        if "Top plane" in s and "Mid Plane" in s:
            return _row("C2", "self-reported", 1.0, s)
    return _na("C2", "self-reported", "no Top-plane / Mid Plane base reported (e.g. a revolved base)")


# --- C3, C4, C5, C7: the SLDPRT feature tree ----------------------------------------------

def _sketches(tree: list) -> list[dict]:
    seen, out = set(), []
    for f in tree:
        for s in ([f] if f.get("type") == SKETCH else []) + [x for x in f.get("subs") or []
                                                              if x.get("type") == SKETCH]:
            if s.get("status") is None or s.get("name") in seen:
                continue
            seen.add(s.get("name"))
            out.append(s)
    return out


def c3_sketches(tree: list) -> Check:
    sk = _sketches(tree)
    if not sk:
        return _na("C3", "sldprt", "no sketches")
    under = [s for s in sk if s["status"] != FULLY_DEFINED]
    credit = 1.0 - len(under) / len(sk)
    reason = (f"{len(sk) - len(under)}/{len(sk)} fully defined" if not under else
              "; ".join(f"{s['name']} not fully defined (status {s['status']})" for s in under))
    return _row("C3", "sldprt", credit, reason, "solidworks")


def c4_edge_ops_last(tree: list, st: dict) -> Check:
    edge, solid = set(st["edge_ops"]), set(st["solid_ops"])
    if not any(f.get("type") in edge for f in tree):
        return _na("C4", "sldprt", "no fillets or chamfers")
    for i, f in enumerate(tree):
        if f.get("type") in edge:
            later = next((g for g in tree[i + 1:] if g.get("type") in solid), None)
            if later is not None:
                return _row("C4", "sldprt", 0.0, f"{f['name']} before {later['name']}", "planner")
    return _row("C4", "sldprt", 1.0, "fillets and chamfers after every solid feature")


def c5_hole_wizard_2d(tree: list, st: dict) -> Check:
    hw = [f for f in tree if f.get("type") == HOLE_WIZARD]
    if not hw:
        return _na("C5", "sldprt", "no Hole Wizard features")
    bad = [f["name"] for f in hw if any(s.get("type") == st["three_d_sketch"] for s in f.get("subs") or [])]
    if bad:
        return _row("C5", "sldprt", 0.0, f"3D sketch under {', '.join(bad)}", "solidworks")
    return _row("C5", "sldprt", 1.0, f"{len(hw)} Hole Wizard feature(s), 2D sketches")


def _plan_features(plan: dict) -> list[dict]:
    p = (plan or {}).get("plan", plan) or {}
    return [f for f in (p.get("features") or []) if isinstance(f, dict)]


def c7_avoid(tree: list, st: dict, plan: dict) -> Check:
    avoid = set(st["avoid"])
    bad = [f for f in tree if f.get("type") in avoid]
    if not bad:
        return _row("C7", "sldprt", 1.0, "none")
    kinds = {f.get("kind") for f in _plan_features(plan)}
    stage = "planner" if any(AVOID_KIND.get(f["type"]) in kinds for f in bad) else "solidworks"
    return _row("C7", "sldprt", 0.0, ", ".join(f"{f['name']} ({f['type']})" for f in bad), stage)


# --- C6: hole grouping (plan.json, with the compiler's own hole_signature) ------------------

def _signature(f: dict, dims: dict) -> tuple:
    """pipeline.ir.compile_solidworks.hole_signature (importable without win32com), with a
    fallback over the raw expressions when the hole doesn't validate or evaluate."""
    try:
        from pipeline.ir.compile_solidworks import hole_signature
        from pipeline.ir.model import Hole
        return hole_signature(Hole.model_validate(f), dims or {})
    except Exception:
        sp = f.get("spec") or {}
        return (str(f.get("on", "")).replace(" ", ""), sp.get("type"),
                *(str(sp.get(k)) for k in ("d", "depth", "cbore_d", "cbore_depth", "csink_d", "csink_angle")),
                sp.get("thread", ""))


_MERGED = re.compile(r"\(in (F\d+) \(one feature\)\)")


def _merged_into(ir: dict) -> dict:
    out = {}
    for fid, s in ((ir or {}).get("sw_features") or {}).items():
        m = _MERGED.search(str(s))
        if m:
            out[fid] = m.group(1)
    return out


def _built(ir: dict, fid: str) -> bool:
    s = ((ir or {}).get("sw_features") or {}).get(fid)
    return s is None or str(s).startswith("built")


def _credit_c6(n_features: int, groups: dict) -> tuple[float, str]:
    dups = [ids for ids in groups.values() if len(ids) > 1]
    credit = 1.0 - (n_features - len(groups)) / n_features
    if not dups:
        return credit, f"{n_features} hole feature(s), one per hole and face"
    return credit, "; ".join(f"{', '.join(ids)}: same hole on the same face, {len(ids)} features" for ids in dups)


def c6_hole_grouping(ir: dict, plan: dict) -> Check:
    ir = ir or {}
    feats = _plan_features(plan)
    holes = [f for f in feats if f.get("kind") == "hole"]
    merged = _merged_into(ir)
    skipped = set((ir.get("cq_skipped") or {}))
    if holes:
        dims = (plan or {}).get("dims") or {}
        groups: dict = {}
        prev_sig = None              # the compiler merges consecutive identical holes (sw_features absent)
        n = 0
        for f in feats:
            if f.get("status", "planned") != "planned" or f["id"] in skipped or not _built(ir, f["id"]):
                prev_sig = None
                continue
            if f.get("kind") != "hole":
                prev_sig = None
                continue
            sig = _signature(f, dims)
            if ir.get("sw_features"):
                one = f["id"] in merged
            else:
                one = sig == prev_sig
            prev_sig = sig
            if one:
                continue
            n += 1
            groups.setdefault(sig, []).append(f["id"])
        if not n:
            return _na("C6", "plan", "no hole features built")
        credit, reason = _credit_c6(n, groups)
        return _row("C6", "plan", credit, reason, "planner")
    lines = [s for s in (ir.get("mti_review") or []) if str(s).startswith("[mti_hole_grouping]")]
    if lines:                     # no plan: the planner review's own grouping findings
        groups, n = {}, 0
        for i, s in enumerate(lines):
            ids = re.findall(r"F\d+", str(s).split(":", 1)[0])
            for fid in ids:
                if fid not in merged:
                    n += 1
                    groups.setdefault(i, []).append(fid)
        credit, reason = _credit_c6(n, groups)
        return _row("C6", "self-reported", credit, reason, "planner")
    return _na("C6", "plan", "no hole features")


# --- the score ------------------------------------------------------------------------------

def check_part(tree: Optional[list], ir_report: Optional[dict], plan: Optional[dict], cfg) -> PracticeScore:
    st = _settings(cfg)
    ir = ir_report or {}
    rows = [c1_origin(ir), c2_mid_plane(ir)]
    if tree is None:
        rows += [_na(c, "sldprt", NOT_CHECKED) for c in ("C3", "C4", "C5")]
    else:
        rows += [c3_sketches(tree), c4_edge_ops_last(tree, st), c5_hole_wizard_2d(tree, st)]
    rows.append(c6_hole_grouping(ir, plan or {}))
    rows.append(_na("C7", "sldprt", NOT_CHECKED) if tree is None else c7_avoid(tree, st, plan or {}))
    w = st["weights"]
    app = [r for r in rows if r.applicable and float(w.get(r.id, 0)) > 0]
    total = sum(float(w[r.id]) for r in app)
    score = 100.0 * sum(float(w[r.id]) * r.credit for r in app) / total if total else None
    return PracticeScore(score=score, rows=rows, checked=tree is not None)
