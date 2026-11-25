"""Scoring tab backend: methodology, worked example, persisted evaluations.

The score itself is computed ONLY by the pipeline repo's scorer (``python -m bench.score``, free: no
API calls). This module never grades anything. It (1) reads the scorer's own config to describe the
rubric, (2) recomputes an illustrative worked example from that same config, and (3) stores every
evaluation the scorer produced, append-only, so a later rubric change never rewrites a stored score.

Pure functions, no FastAPI and no pipeline import (the server runs ANY pipeline repo). The credit,
share and weight formulas below mirror ``bench/credit.py`` and ``bench/weights.py`` (documented in
scoring.md part B) and are cross-checked against them by tests/server/test_scoring_hub.py.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CONFIG_REL = Path("bench") / "score_config.yaml"
NOT_SCORED = {
    "not scored (no key)": "There is no signed answer key for this drawing, so there is nothing to grade against.",
    "not scored (unsigned key)": "The answer key still has open flags nobody resolved.",
    "not scored (needs SolidWorks export)": "The generated part has not been exported to STEP yet and SolidWorks was not used.",
}
CRITERIA = ("position", "size", "depth", "type")


# ── rubric (read from the scorer's own config) ───────────────────────────────────────────────
def load_config(repo: Path) -> dict:
    import yaml
    return yaml.safe_load((Path(repo) / CONFIG_REL).read_text(encoding="utf-8"))


def rubric_version(repo: Path) -> str:
    """A short fingerprint of the scorer config. It changes whenever any rubric number changes."""
    try:
        data = (Path(repo) / CONFIG_REL).read_bytes()
    except OSError:
        return "unknown"
    return "cfg-" + hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()[:10]


def attr_credit(error: float, tol: float, cfg: dict) -> float:
    """1 within tolerance; drop * exp(-(e-1)/k) beyond it (e = |error| / tol)."""
    c = cfg["credit"]
    error = abs(error)
    if tol <= 1e-12:
        return 1.0 if error <= 1e-12 else c["drop"] * math.exp(-1.0 / c["k"])
    e = error / tol
    return 1.0 if e <= 1.0 + 1e-9 else c["drop"] * math.exp(-(e - 1.0) / c["k"])


def feature_credit(attr_credits: dict, cfg: dict) -> float:
    present = {a: v for a, v in attr_credits.items() if a in cfg["shares"]}
    total = sum(cfg["shares"][a] for a in present)
    return 1.0 if total <= 0 else sum(cfg["shares"][a] * v for a, v in present.items()) / total


def feature_weight(ftype: str, feature_size: float, part_size: float, cfg: dict) -> float:
    tier = float(cfg["tiers"].get(ftype, 0.0))
    if tier == 0.0:
        return 0.0
    if ftype == "base_body" or part_size <= 0:
        return tier
    return tier * min(1.0, max(cfg["size_floor"], math.sqrt(max(feature_size, 0.0) / part_size)))


def methodology(repo: Path) -> dict:
    """Everything the Methodology panel shows, taken from the scorer's config (no invented numbers)."""
    cfg = load_config(repo)
    c = cfg["credit"]
    curve = [{"e": e, "credit": round(attr_credit(e, 1.0, cfg), 3)} for e in (1, 1.5, 2, 5, 10, 20)]
    shares = cfg["shares"]
    return {
        "version": rubric_version(repo),
        "source": "scoring.md part B, with every number read from bench/score_config.yaml",
        "total_possible": 100,
        "formula": "score = clamp(100 x (sum(weight x credit) - extra_penalty x sum(extra weights)) / W, 0, 100); "
                   "W = sum of every key feature's weight. exact = every credit is 1 and nothing extra.",
        "feature_formula": "credit = sum(share x attribute credit) over the attributes that apply (shares renormalised); "
                           "weight = tier x clamp(sqrt(feature size / part size), size_floor, 1); base body weight = its tier.",
        "credit_formula": f"credit = 1 if e <= 1, else {c['drop']} x exp(-(e - 1) / {c['k']}), where e = |error| / tolerance",
        "credit_curve": curve,
        "criteria": [
            {"id": "position", "share": shares["position"], "method": "Where the feature is: distance across the axis for through holes, 3D start-point distance for blind ones, across the edge for chamfers.", "deduction": "Credit fades past the drawing tolerance (0.5 just over it)."},
            {"id": "size", "share": shares["size"], "method": "Diameter, counterbore/countersink diameter, slot width, chamfer legs, extents (the worst one counts).", "deduction": "Same fade, against the size tolerance."},
            {"id": "depth", "share": shares["depth"], "method": "How far into the material. Through vs through is full credit; through vs blind is 0.", "deduction": "Same fade; a through/blind mismatch is 0."},
            {"id": "type", "share": shares["type"], "method": "1 if the feature type is right, else 0.", "deduction": "A wrong type loses its whole share."},
        ],
        "tiers": [{"type": t, "weight": w} for t, w in sorted(cfg["tiers"].items(), key=lambda kv: -kv[1])],
        "thresholds": {
            "tolerance_fallback": cfg["fallback_tol"], "size_floor": cfg["size_floor"], "extra_penalty": cfg["extra_penalty"],
            "match_gate": f"a pair only matches when position error < min({cfg['gate']['tol_multiple']} x tolerance, {int(cfg['gate']['part_fraction'] * 100)}% of the part's largest dimension)",
            "missing_feature": "credit 0", "extra_feature": f"costs {cfg['extra_penalty']} x its own weight",
        },
        "unsupported_types": list(cfg.get("unsupported_types") or []),
        "rounding": "Scores are stored unrounded and shown to one decimal place; the 0 to 100 range is enforced.",
        "practices": {"note": "A separate 0 to 100 MTI practices score from the feature tree. It is never blended into the geometry score.",
                      "checks": ["C1 origin centered", "C2 base on Top plane, Mid Plane extrude", "C3 sketches fully defined",
                                 "C4 fillets and chamfers last", "C5 Hole Wizard from 2D sketches", "C6 one Hole Wizard feature per size per face",
                                 "C7 no avoided features"]},
    }


def worked_example(repo: Path) -> dict:
    """Illustrative plate (NOT a measured part): a base body plus four 0.344 in through holes on a 6 in part,
    position tolerance 0.005 in. Every number is computed from the live config."""
    cfg = load_config(repo)
    part_size, hole_d, tol = 6.0, 0.344, 0.005
    w_body = feature_weight("base_body", part_size, part_size, cfg)
    w_hole = feature_weight("thru_hole", hole_d, part_size, cfg)
    W = w_body + 4 * w_hole

    def hole_row(label, errors, missing=False):
        if missing:
            return {"case": label, "credits": {a: 0.0 for a in CRITERIA}, "credit": 0.0}
        cr = {"position": attr_credit(errors.get("position", 0), tol, cfg), "size": 1.0,
              "depth": 0.0 if errors.get("depth_wrong") else 1.0, "type": 1.0}
        return {"case": label, "credits": cr, "credit": feature_credit(cr, cfg)}

    cases = [
        ("Nothing wrong", hole_row("Nothing wrong", {}), 0, 0),
        ("One hole 0.0025 in off (0.5x tolerance)", hole_row("", {"position": 0.0025}), 0, 0),
        ("One hole 0.010 in off (2x tolerance)", hole_row("", {"position": 0.010}), 0, 0),
        ("One through hole built blind", hole_row("", {"depth_wrong": True}), 0, 0),
        ("One hole missing", hole_row("", {}, missing=True), 0, 0),
        ("One extra hole", {"credits": {}, "credit": 1.0}, 1, 0),
    ]
    out = []
    for label, row, extras, _ in cases:
        lost_feature = w_hole * (1 - row["credit"])
        extra_cost = cfg["extra_penalty"] * w_hole * extras
        score = max(0.0, min(100.0, 100 * (W - lost_feature - extra_cost) / W))
        out.append({"case": label, "attribute_credits": {k: round(v, 4) for k, v in row["credits"].items()},
                    "feature_credit": round(row["credit"], 4), "points_lost": round(100 * (lost_feature + extra_cost) / W, 3),
                    "score": round(score, 2), "exact": row["credit"] >= 1 - 1e-9 and extras == 0})
    return {"illustrative": True, "label": "Illustrative example, not a measured part", "version": rubric_version(repo),
            "part": {"base_body_weight": w_body, "through_hole_weight": round(w_hole, 4), "holes": 4, "total_weight_W": round(W, 4),
                     "part_size_in": part_size, "hole_diameter_in": hole_d, "position_tolerance_in": tol},
            "arithmetic": f"W = {w_body:g} + 4 x {w_hole:.2f} = {W:.2f}; points lost = 100 x weight x (1 - credit) / W",
            "cases": out}


# ── persisted evaluations (append-only) ──────────────────────────────────────────────────────
def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name) or "part"


def store_path(store_dir: Path, part: str) -> Path:
    return Path(store_dir) / f"{_safe(part)}.jsonl"


def history(store_dir: Path, part: str) -> list[dict]:
    p = store_path(store_dir, part)
    out = []
    if p.is_file():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def latest(store_dir: Path, part: str) -> Optional[dict]:
    h = history(store_dir, part)
    return h[-1] if h else None


def append(store_dir: Path, part: str, rec: dict) -> dict:
    Path(store_dir).mkdir(parents=True, exist_ok=True)
    with store_path(store_dir, part).open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def consistency_flags(rec: dict) -> list[str]:
    """Inconsistencies are flagged, never hidden."""
    flags = []
    s = rec.get("score")
    if s is not None and not (0 <= s <= 100):
        flags.append(f"score {s} is outside 0 to 100")
    rows = rec.get("rows") or []
    if s is not None and rows:
        lost = sum(r.get("points_lost") or 0 for r in rows) + sum(x.get("points_lost") or 0 for x in rec.get("extras") or [])
        if abs((100 - lost) - s) > 0.5 and not (s == 0 and lost >= 100):
            flags.append(f"score {s:.1f} does not equal 100 minus the points lost ({lost:.1f})")
    if rec.get("exact") and s is not None and s < 100 - 1e-6:
        flags.append("marked exact but the score is below 100")
    return flags


def record_from_scorer(part: dict, *, run_id: Optional[str], version: str, summary_err: str = "") -> dict:
    """One persisted evaluation from one ``scores.json`` part row. Missing evidence stays incomplete, never 0."""
    status = part.get("status")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    base = {"evaluated_at": now, "rubric_version": version, "run_id": run_id, "part": part.get("part"),
            "key_kind": part.get("key_kind"), "generated": part.get("generated"), "warnings": part.get("warnings") or []}
    if part.get("error"):
        return {**base, "state": "scoring_failed", "score": None, "error": part["error"]}
    if status:
        return {**base, "state": "incomplete", "score": None, "reason": status, "explanation": NOT_SCORED.get(status, status)}
    rec = {**base, "state": "scored", "score": part.get("score"), "exact": bool(part.get("exact")),
           "reference_score": part.get("reference_score"), "rows": part.get("rows") or [], "extras": part.get("extras") or [],
           "blame": part.get("blame") or {}, "unresolved": part.get("unresolved") or [],
           "drawing_only": part.get("drawing_only") or [], "practices": part.get("practices"),
           "evidence": {"generated_step": part.get("generated"), "extraction_found": part.get("extraction_found"),
                        "pose_rotation": part.get("pose_rotation"), "pose_translation": part.get("pose_translation")}}
    rec["consistency_flags"] = consistency_flags(rec)
    return rec


def run_scorer(repo: Path, part_dir: Path, work_root: Path, part: str, *, export: bool, timeout: int = 900) -> tuple[dict, str]:
    """Copy the part's small evidence files into a scratch run folder (so scores.json/report.html never land in
    the deliverables) and run ``python -m bench.score``. Returns (that part's scores.json row, scorer output tail)."""
    run_dir = Path(work_root) / "work"
    dst = run_dir / part
    dst.mkdir(parents=True, exist_ok=True)
    for f in Path(part_dir).iterdir():
        if f.is_file() and f.suffix.lower() not in (".mp4", ".webm", ".pdf", ".png", ".jpg") and f.stat().st_size < 60_000_000:
            if not (dst / f.name).exists() or f.stat().st_mtime > (dst / f.name).stat().st_mtime + 1:
                shutil.copy2(f, dst / f.name)
    cmd = [sys.executable, "-m", "bench.score", str(run_dir), "--parts", part] + ([] if export else ["--no-sw"])
    env = {**os.environ, "PYTHONUTF8": "1"}
    p = subprocess.run(cmd, cwd=str(repo), env=env, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    tail = ((p.stdout or "") + (p.stderr or ""))[-1500:]
    sp = run_dir / "scores.json"
    if p.returncode == 3:
        return {"part": part, "status": "not scored (needs SolidWorks export)"}, tail
    if not sp.is_file():
        return {"part": part, "error": f"The scorer wrote no scores.json (exit {p.returncode}). {tail[-300:]}"}, tail
    data = json.loads(sp.read_text(encoding="utf-8"))
    for row in data.get("parts") or []:
        if row.get("part") == part:
            return row, tail
    if part in (data.get("no_key") or []):
        return {"part": part, "status": "not scored (no key)"}, tail
    if any((u == part or (isinstance(u, dict) and u.get("part") == part)) for u in data.get("skipped_unsigned") or []):
        return {"part": part, "status": "not scored (unsigned key)"}, tail
    return {"part": part, "status": "not scored (no key)"}, tail


def summarize(latest_by_part: dict[str, Optional[dict]], all_parts: list[str]) -> dict:
    """Overview numbers. The average counts only completed, valid (0..100) scores."""
    valid = [r["score"] for r in latest_by_part.values() if r and r.get("state") == "scored" and r.get("score") is not None
             and 0 <= r["score"] <= 100]
    scored = len(valid)
    failed = sum(1 for r in latest_by_part.values() if r and r.get("state") == "scoring_failed")
    incomplete = sum(1 for r in latest_by_part.values() if r and r.get("state") == "incomplete")
    pending = sum(1 for p in all_parts if not latest_by_part.get(p))
    return {"parts": len(all_parts), "scored": scored, "pending": pending, "incomplete": incomplete, "scoring_failed": failed,
            "average": round(sum(valid) / scored, 2) if scored else None}


# ══ Extraction-to-Model Fidelity (EMF): the primary rubric. Computed by the pipeline repo's bench.fidelity (free) ══════════
FIDELITY_CONFIG_REL = Path("bench") / "fidelity_config.yaml"
_method_cache: dict[str, dict] = {}


def _py_env() -> dict:
    return {**os.environ, "PYTHONUTF8": "1"}


def fidelity_methodology(repo: Path) -> dict:
    """{methodology, example} from the pipeline's own engine, cached by the config fingerprint."""
    try:
        key = hashlib.sha256((Path(repo) / FIDELITY_CONFIG_REL).read_bytes()).hexdigest()
    except OSError as e:
        raise RuntimeError(f"fidelity_config.yaml not found in {repo}: {e}")
    if key not in _method_cache:
        p = subprocess.run([sys.executable, "-m", "bench.fidelity", "--methodology"], cwd=str(repo), env=_py_env(), capture_output=True,
                           text=True, timeout=120, encoding="utf-8", errors="replace")
        if p.returncode != 0 or not p.stdout.strip():
            raise RuntimeError("bench.fidelity --methodology failed: " + (p.stderr or p.stdout)[-300:])
        _method_cache.clear()
        _method_cache[key] = json.loads(p.stdout.strip().splitlines()[-1])
    return _method_cache[key]


def run_fidelity(repo: Path, part_dir: Path, timeout: int = 180) -> dict:
    """Score one part folder with bench.fidelity. Returns the engine's record (a failure is a scoring_failed record)."""
    try:
        p = subprocess.run([sys.executable, "-m", "bench.fidelity", str(part_dir), "--stdout"], cwd=str(repo), env=_py_env(), capture_output=True,
                           text=True, timeout=timeout, encoding="utf-8", errors="replace")
        line = (p.stdout or "").strip().splitlines()[-1] if (p.stdout or "").strip() else ""
        rec = json.loads(line) if line else None
    except Exception as e:  # noqa: BLE001
        return {"rubric_id": "emf", "state": "scoring_failed", "score": None, "error": f"The fidelity scorer could not run: {str(e)[:200]}"}
    if not rec:
        return {"rubric_id": "emf", "state": "scoring_failed", "score": None, "error": ("The fidelity scorer wrote nothing. " + (p.stderr or "")[-300:]).strip()}
    return rec


def is_fidelity(rec: dict) -> bool:
    return bool(rec) and (rec.get("rubric_id") == "emf" or (isinstance(rec.get("rubric"), dict) and rec["rubric"].get("id") == "emf"))


def fidelity_history(store_dir: Path, part: str) -> list[dict]:
    return [r for r in history(store_dir, part) if is_fidelity(r)]


def fidelity_latest(store_dir: Path, part: str) -> Optional[dict]:
    h = fidelity_history(store_dir, part)
    return h[-1] if h else None


def benchmark_latest(store_dir: Path, part: str) -> Optional[dict]:
    h = [r for r in history(store_dir, part) if not is_fidelity(r)]
    return h[-1] if h else None


def append_fidelity(store_dir: Path, part: str, rec: dict, run_id: Optional[str] = None) -> dict:
    rec = {**rec, "rubric_id": "emf", "run_id": run_id or rec.get("run_id")}
    return append(store_dir, part, rec)


def ingest_fidelity_file(store_dir: Path, part: str, path: Path, run_id: Optional[str] = None) -> bool:
    """Persist a pipeline-written fidelity_score.json once (matched by its evaluated_at). True when it was new."""
    try:
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not is_fidelity(rec):
        return False
    if any(r.get("evaluated_at") == rec.get("evaluated_at") for r in fidelity_history(store_dir, part)):
        return False
    append_fidelity(store_dir, part, rec, run_id)
    return True


def fidelity_row(rec: Optional[dict]) -> dict:
    """The compact, UI-ready summary of one stored fidelity evaluation."""
    if not rec:
        return {}
    cats = {c["id"]: {"score": c.get("score"), "band": (c.get("band") or {}).get("id"), "checked": c.get("checked"), "weight": c.get("weight")} for c in rec.get("categories") or []}
    return {"state": rec.get("state"), "score": rec.get("score"), "band": rec.get("band"), "reason": rec.get("reason"), "explanation": rec.get("explanation"),
            "error": rec.get("error"), "evaluated_at": rec.get("evaluated_at"), "fingerprint": (rec.get("rubric") or {}).get("fingerprint"),
            "coverage": rec.get("coverage"), "caps": rec.get("caps") or [], "counts": rec.get("counts") or {}, "categories": cats,
            "top_issue": (rec.get("issues") or [{}])[0].get("message") if rec.get("issues") else None}


def summarize_fidelity(rows: list[dict], eligible: list[str], bands: list[dict]) -> dict:
    """Overview numbers over each part's latest fidelity evaluation. The average counts scored parts only."""
    valid = [r["score"] for r in rows if r.get("state") == "scored" and isinstance(r.get("score"), (int, float)) and 0 <= r["score"] <= 100]
    dist = {b["id"]: 0 for b in bands}
    for r in rows:
        if r.get("state") == "scored" and (r.get("band") or {}).get("id") in dist:
            dist[r["band"]["id"]] += 1
    crit = sum(1 for r in rows if (r.get("counts") or {}).get("critical"))
    return {"parts": len(eligible), "scored": len(valid), "average": round(sum(valid) / len(valid), 1) if valid else None, "distribution": dist,
            "incomplete": sum(1 for r in rows if r.get("state") == "incomplete"), "no_model": sum(1 for r in rows if r.get("state") == "no_model"),
            "scoring_failed": sum(1 for r in rows if r.get("state") == "scoring_failed"),
            "pending": sum(1 for p in eligible if not any(r.get("part") == p for r in rows)), "parts_with_critical": crit}
