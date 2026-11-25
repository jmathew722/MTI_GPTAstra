"""Extraction-to-Model Fidelity (EMF): grade what the drawing's EXTRACTION asked for against the ACTUAL SolidWorks part.

The part is measured on the STL that SolidWorks exported from the SLDPRT (the same file the viewer shows), never on the plan
or on the CadQuery reference, so a wrong, stale or half-built model cannot score well. No answer key is needed, so every
built part can be scored. Free: no API calls, no SolidWorks session.

    python -m bench.fidelity <part_dir> [--out file.json]      one part (writes fidelity_score.json beside the outputs by default)
    python -m bench.fidelity --all <run_dir>                    every part folder under a run directory

Six categories (weights in bench/fidelity_config.yaml): build integrity, overall size, feature coverage, hole and bore
accuracy, placement and patterns, extraction reliability. A category with nothing checkable is dropped and the rest are
rescaled (coverage is reported). Critical issues cap the total. Spec: docs/scoring-rubric-emf.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "fidelity_config.yaml"
MM_PER_IN = 25.4
CAT_ORDER = ("model_integrity", "envelope", "feature_coverage", "hole_accuracy", "placement", "extraction_trust")


# ── config ───────────────────────────────────────────────────────────────────────────────────
def load_config(path: Optional[Path] = None) -> dict:
    return yaml.safe_load(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def fingerprint(path: Optional[Path] = None) -> str:
    data = Path(path or CONFIG_PATH).read_bytes().replace(b"\r\n", b"\n")
    return "emf-" + hashlib.sha256(data).hexdigest()[:10]


def band_of(score: Optional[float], cfg: dict) -> dict:
    if score is None:
        return {"id": "none", "label": "Not scored", "glyph": "dash"}
    for b in sorted(cfg["bands"], key=lambda b: -b["min"]):
        if score >= b["min"]:
            return {"id": b["id"], "label": b["label"], "glyph": b["glyph"]}
    return {"id": "red", "label": cfg["bands"][-1]["label"], "glyph": cfg["bands"][-1]["glyph"]}


def credit(error: float, tol: float, cfg: dict) -> float:
    """1 within tolerance; drop * exp(-(e - 1) / k) beyond it, with e = |error| / tolerance."""
    c = cfg["credit"]
    error = abs(error)
    if tol <= 1e-12:
        return 1.0 if error <= 1e-12 else c["drop"] * math.exp(-1.0 / c["k"])
    e = error / tol
    return 1.0 if e <= 1.0 + 1e-9 else c["drop"] * math.exp(-(e - 1.0) / c["k"])


# ── mesh ─────────────────────────────────────────────────────────────────────────────────────
def load_stl(path: Path) -> Optional[np.ndarray]:
    """(n, 3, 3) float64 triangles from a binary or ASCII STL, or None when unreadable."""
    try:
        b = Path(path).read_bytes()
    except OSError:
        return None
    if len(b) >= 84:
        n = struct.unpack("<I", b[80:84])[0]
        if 84 + n * 50 == len(b) and n > 0:
            d = np.frombuffer(b[84:84 + n * 50], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))
            return d["v"].reshape(-1, 3, 3).astype(np.float64)
    if b[:5].lower() == b"solid":
        v = [[float(x) for x in m.groups()] for m in re.finditer(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", b)]
        if v and len(v) % 3 == 0:
            return np.array(v, dtype=np.float64).reshape(-1, 3, 3)
    return None


def mesh_stats(t: np.ndarray) -> dict:
    pts = t.reshape(-1, 3)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    vol = float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6.0)
    # watertight: every undirected edge belongs to exactly two triangles
    ids = np.unique(np.round(pts, 4), axis=0, return_inverse=True)[1].reshape(-1, 3)
    e = np.sort(np.concatenate([ids[:, [0, 1]], ids[:, [1, 2]], ids[:, [2, 0]]]), axis=1)
    _, counts = np.unique(e, axis=0, return_counts=True)
    closed = float((counts == 2).sum() / max(1, len(counts)))
    return {"triangles": int(len(t)), "bbox_lo": lo, "bbox_hi": hi, "dims": hi - lo, "volume": abs(vol), "closed_fraction": closed}


def _normals(t: np.ndarray) -> np.ndarray:
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    ln = np.linalg.norm(n, axis=1)
    ln[ln < 1e-15] = 1.0
    return n / ln[:, None]


def _components(tri_vertex_ids: np.ndarray) -> np.ndarray:
    """Connected components of triangles that share a vertex (union-find over vertex ids)."""
    n = len(tri_vertex_ids)
    parent = np.arange(n)

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first: dict[int, int] = {}
    for i in range(n):
        for v in tri_vertex_ids[i]:
            j = first.setdefault(int(v), i)
            if j != i:
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    return np.array([find(i) for i in range(n)])


def _fit_circle(xy: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Algebraic (Kasa) circle fit. Returns (center, radius, rms residual)."""
    x, y = xy[:, 0], xy[:, 1]
    A = np.column_stack([2 * x, 2 * y, np.ones(len(x))])
    b = x * x + y * y
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = sol[:2]
    r = math.sqrt(max(sol[2] + c @ c, 0.0))
    res = np.sqrt(np.mean((np.linalg.norm(xy - c, axis=1) - r) ** 2))
    return c, r, float(res)


def find_cylinders(t: np.ndarray) -> list[dict]:
    """Full-circle cylindrical faces whose axis is a principal axis, in mesh units.
    kind: 'hole' (surface faces the axis: material outside) or 'boss' (surface faces away)."""
    n = _normals(t)
    pts = t.reshape(-1, 3)
    vid = np.unique(np.round(pts, 4), axis=0, return_inverse=True)[1].reshape(-1, 3)
    out: list[dict] = []
    for axis in range(3):
        o = [a for a in range(3) if a != axis]
        idx = np.where(np.abs(n[:, axis]) < 0.02)[0]
        if len(idx) < 6:
            continue
        comp = _components(vid[idx])
        for cid in np.unique(comp):
            sel = idx[comp == cid]
            if len(sel) < 6:
                continue
            vs = t[sel].reshape(-1, 3)
            uv = np.unique(np.round(vs, 4), axis=0)
            xy = uv[:, o]
            c, r, rms = _fit_circle(xy)
            if r < 1e-4 or rms > 0.01 * r + 1e-3:
                continue
            ang = np.sort(np.arctan2(xy[:, 1] - c[1], xy[:, 0] - c[0]))
            gaps = np.diff(np.concatenate([ang, [ang[0] + 2 * math.pi]]))
            if gaps.max() > math.radians(110):
                continue                                           # an arc (slot end, fillet), not a full hole
            z0, z1 = float(uv[:, axis].min()), float(uv[:, axis].max())
            cen = t[sel].mean(axis=1)
            radial = c - cen[:, o]
            facing = float(np.mean(np.einsum("ij,ij->i", n[sel][:, o], radial)))
            center = np.zeros(3)
            center[o[0]], center[o[1]], center[axis] = c[0], c[1], (z0 + z1) / 2
            out.append({"axis": axis, "center": center, "r": float(r), "d": float(2 * r), "z0": z0, "z1": z1,
                        "length": z1 - z0, "kind": "hole" if facing > 0 else "boss", "rms": rms, "tris": int(len(sel))})
    return out


def _closed_end(t: np.ndarray, n: np.ndarray, cyl: dict, end: str) -> bool:
    """True when a floor (flat or drill-point cone) closes the hole at this end."""
    axis, r = cyl["axis"], cyl["r"]
    o = [a for a in range(3) if a != axis]
    cen = t.mean(axis=1)
    inplane = np.linalg.norm(cen[:, o] - cyl["center"][o], axis=1)
    z = cen[:, axis]
    zend = cyl["z0"] if end == "lo" else cyl["z1"]
    reach = 1.6 * r + 1e-3
    zone = (z >= zend - reach - 1e-3) & (z <= zend + 1e-3) if end == "lo" else (z >= zend - 1e-3) & (z <= zend + reach + 1e-3)
    return bool(np.any(zone & (inplane < 0.95 * r) & (np.abs(n[:, axis]) > 0.3)))


def find_holes(t: np.ndarray) -> list[dict]:
    """Holes with through/blind, depth and counterbore, in mesh units."""
    cyls = find_cylinders(t)
    n = _normals(t)
    holes = [c for c in cyls if c["kind"] == "hole"]
    for h in holes:
        lo, hi = _closed_end(t, n, h, "lo"), _closed_end(t, n, h, "hi")
        h["through"] = not (lo or hi)
        h["floor"] = "lo" if lo else "hi" if hi else None
        h["cbore"] = None
    used: set[int] = set()
    for i, a in enumerate(holes):                      # a counterbore: a larger coaxial hole touching a smaller one
        for j, b in enumerate(holes):
            if i == j or j in used or b["axis"] != a["axis"] or b["r"] <= a["r"] * 1.05:
                continue
            o = [x for x in range(3) if x != a["axis"]]
            off = float(np.linalg.norm(a["center"][o] - b["center"][o]))
            touching = a["z0"] - 1e-2 <= b["z1"] and b["z0"] <= a["z1"] + 1e-2
            if off < 0.02 * a["r"] + 0.02 and touching and a["cbore"] is None:
                a["cbore"] = {"d": b["d"], "depth": b["length"], "offset": off}
                used.add(j)
    return [h for k, h in enumerate(holes) if k not in used]


# ── issues ───────────────────────────────────────────────────────────────────────────────────
def _issue(sev: str, cat: str, code: str, msg: str, evidence: str = "", points: float = 0.0, ref: str = "") -> dict:
    return {"severity": sev, "category": cat, "code": code, "message": msg, "evidence": evidence, "points": round(points, 2), "ref": ref}


def _item(cat: str, iid: str, label: str, weight: float, cr: Optional[float], **kw) -> dict:
    d = {"id": iid, "label": label, "weight": weight, "credit": None if cr is None else round(float(cr), 4)}
    d.update(kw)
    return d


def _fmt(v: Optional[float], units: str) -> str:
    if v is None:
        return "-"
    return f"{v:.4g} {'in' if units.startswith('in') else 'mm'}"


def _units(ext: dict) -> str:
    u = str(ext.get("units") or "inch").lower()
    return "mm" if u.startswith("mm") or "milli" in u else "inch"


def _tol_of(dim: Optional[dict], units: str, cfg: dict) -> float:
    if dim:
        t = max(abs(float(dim.get("tolerance_plus") or 0)), abs(float(dim.get("tolerance_minus") or 0)))
        if t > 0:
            return max(t, cfg["mesh_floor"][units])
    return max(cfg["fallback_tol"][units], cfg["mesh_floor"][units])


# ── expectations from the extraction ─────────────────────────────────────────────────────────
_EXCL = re.compile(r"hub|step|relief|recess|reduced|minimum|inside|inner|hole|tap|thread|bolt|pitch|from|to_|spacing|row|column|pattern|bore|counterbore|chamfer|fillet|radius|runout|tolerance|ball|derived|notch|slot", re.I)
_OVR = re.compile(r"overall|plate[_ ]thickness|block[_ ]thickness|sheet[_ ]thickness|stock", re.I)   # explicit overall sizes only: sub-feature dimensions are not the envelope


def expected_envelope(ext: dict) -> tuple[list[dict], str]:
    """Expected sorted overall dimensions [{value, id, label, tol_dim}] from the extraction's base-feature dimensions."""
    feats = ext.get("features") or []
    base = next((f["id"] for f in feats if f.get("type") in ("extrude_boss", "revolve")), feats[0]["id"] if feats else "")
    dims = [d for d in ext.get("dimensions") or [] if (d.get("feature_ref") in (base, "") ) and not d.get("is_reference") and not d.get("value_unclear")
            and float(d.get("value") or 0) > 0]
    diam = [d for d in dims if d.get("type") == "diameter" and re.search(r"outside|outer|maximum|flange_outside", d.get("applies_to", ""), re.I)
            and not _EXCL.search(re.sub(r"outside|outer|maximum", "", d.get("applies_to", ""), flags=re.I))]
    lin = [d for d in dims if d.get("type") in ("linear",) and _OVR.search(d.get("applies_to", "")) and not _EXCL.search(d.get("applies_to", ""))]
    out: list[dict] = []
    seen: set[float] = set()
    if diam:
        D = max(diam, key=lambda d: float(d["value"]))
        out += [{"value": float(D["value"]), "id": D["id"], "label": D.get("applies_to", "diameter"), "dim": D}] * 2
        lin = [d for d in lin if abs(float(d["value"]) - float(D["value"])) > 1e-9]
        if lin:
            L = max(lin, key=lambda d: float(d["value"]))
            out.append({"value": float(L["value"]), "id": L["id"], "label": L.get("applies_to", "length"), "dim": L})
        return sorted(out, key=lambda x: x["value"]), "extraction"
    for d in sorted(lin, key=lambda d: -float(d["value"])):
        v = round(float(d["value"]), 6)
        if v in seen or len(out) >= 3:
            continue
        seen.add(v)
        out.append({"value": float(d["value"]), "id": d["id"], "label": d.get("applies_to", ""), "dim": d})
    return sorted(out, key=lambda x: x["value"]), "extraction"


def _is_placeholder(h: dict, warnings: list[str]) -> Optional[str]:
    hid = h.get("id", "")
    if float(h.get("diameter") or 0) <= 0:
        return "no diameter was read from the drawing"
    for w in warnings:
        if hid and re.search(rf"\b{re.escape(hid)}\b", w) and re.search(r"placeholder|unknown|not the specified|must not drive|unresolved|cannot be built", w, re.I):
            return "the extraction marks this callout's size as a placeholder or unknown"
    return None


# ── main evaluation ──────────────────────────────────────────────────────────────────────────
def _jload(p: Optional[Path]) -> Optional[dict]:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8")) if p and Path(p).is_file() else None
    except (OSError, ValueError):
        return None


def _first(d: Path, pats: list[str]) -> Optional[Path]:
    for pat in pats:
        for p in sorted(d.glob(pat)):
            return p
    return None


def aggregate(cats: dict[str, list[dict]], issues: list[dict], cfg: dict, *, force_status: Optional[str] = None) -> dict:
    """Items per category -> category scores, total, gates, band. Pure: also drives the worked example."""
    out_cats = []
    wsum = checked_w = 0.0
    acc = 0.0
    for cid in CAT_ORDER:
        meta = cfg["categories"][cid]
        items = cats.get(cid) or []
        scorable = [i for i in items if i.get("credit") is not None]
        tw = sum(i["weight"] for i in scorable)
        w = float(meta["weight"])
        wsum += w
        if tw <= 0:
            out_cats.append({"id": cid, "label": meta["label"], "question": meta["question"], "weight": w, "checked": False,
                             "score": None, "pct": None, "earned": None, "items": items, "n_checked": 0, "n_total": len(items), "band": band_of(None, cfg)})
            continue
        pct = 100.0 * sum(i["weight"] * i["credit"] for i in scorable) / tw
        checked_w += w
        acc += w * pct / 100.0
        out_cats.append({"id": cid, "label": meta["label"], "question": meta["question"], "weight": w, "checked": True, "score": round(pct, 1),
                         "pct": round(pct, 1), "earned": None, "items": items, "n_checked": len(scorable), "n_total": len(items), "band": band_of(pct, cfg)})
    raw = None if checked_w <= 0 else 100.0 * acc / checked_w
    for c in out_cats:                     # points earned out of the weight, after rescaling to the checked weight
        if c["checked"] and checked_w > 0:
            c["earned"] = round(c["weight"] * c["pct"] / 100.0 * (wsum / checked_w), 2)
            c["max"] = round(c["weight"] * (wsum / checked_w), 2)
        else:
            c["max"] = 0.0
    total, caps = raw, []
    sev = {i["severity"] for i in issues}
    if raw is not None and "critical" in sev and raw > cfg["gates"]["critical_cap"]:
        total = cfg["gates"]["critical_cap"]
        caps.append(f"A critical issue caps the score at {cfg['gates']['critical_cap']:.0f}: the breakdown above is not enough to trust this model.")
    # points lost per issue, scaled to the rescaled 100
    scale = (wsum / checked_w) if checked_w else 1.0
    cw = {c["id"]: (sum(it["weight"] for it in c["items"] if it.get("credit") is not None), c["weight"]) for c in out_cats}
    for i in issues:
        tw, w = cw.get(i["category"], (0.0, 0.0))
        i["points"] = round(w * min(1.0, i["points"] / tw) * scale, 2) if tw > 0 else 0.0
    return {"score": None if total is None else round(total, 1), "raw_score": None if raw is None else round(raw, 1), "caps": caps,
            "coverage": round(checked_w / wsum, 3) if wsum else 0.0, "categories": out_cats, "band": band_of(total, cfg)}


def evaluate_dir(part_dir: Path, cfg: Optional[dict] = None) -> dict:
    cfg = cfg or load_config()
    d = Path(part_dir)
    part = d.name
    ext = _jload(_first(d, ["*_extraction.json"]))
    rep = _jload(d / "ir_report.json") or {}
    fmap = _jload(d / "feature_map.json") or {}
    eng = _jload(d / "engineering_findings.json") or {}
    sldprt = _first(d, ["*_ir.SLDPRT", "*.SLDPRT", "*.sldprt"])
    stlp = _first(d, ["*_ir.STL", "*_ir.stl"])
    base = {"rubric": {"id": cfg["id"], "name": cfg["name"], "version": cfg["version"], "fingerprint": fingerprint()}, "part": part,
            "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": None,
            "evidence": {"sldprt": sldprt.name if sldprt else None, "stl": stlp.name if stlp else None,
                         "extraction": bool(ext), "ir_report": bool(rep), "feature_map": bool(fmap)}}
    if not ext:
        return {**base, "state": "incomplete", "score": None, "band": band_of(None, cfg), "reason": "no_extraction",
                "explanation": "There is no extraction JSON for this part, so there is nothing to compare the model to.", "categories": [], "issues": []}
    if sldprt and not stlp:
        expl = "The SolidWorks part exists but no STL was exported from it, so its geometry could not be measured. Re-run the part (or export an STL) to score it."
        return {**base, "state": "incomplete", "score": None, "band": band_of(None, cfg), "reason": "no_mesh", "explanation": expl, "categories": [],
                "issues": [_issue("high", "model_integrity", "NO_MESH", expl, f"{sldprt.name} has no matching *_ir.STL")]}
    if not sldprt or not rep.get("sw_ok"):
        expl = ("SolidWorks did not produce a part for this run." if rep and not rep.get("sw_ok") else
                "No SolidWorks part was found beside the outputs: the part has not been built.")
        return {**base, "state": "no_model", "score": None, "band": band_of(None, cfg), "reason": "no_model", "explanation": expl, "categories": [],
                "issues": [_issue("critical", "model_integrity", "NO_MODEL", expl, "ir_report.sw_ok=%s sldprt=%s stl=%s" % (rep.get("sw_ok"), bool(sldprt), bool(stlp)))]}

    units = _units(ext)
    ul = "in" if units == "inch" else "mm"      # unit label for messages
    tris = load_stl(stlp)
    cats: dict[str, list[dict]] = {k: [] for k in CAT_ORDER}
    issues: list[dict] = []
    notes: list[str] = []
    measured: dict[str, Any] = {}
    ic = cfg["integrity_checks"]

    # mesh ------------------------------------------------------------------------------------
    if tris is None or len(tris) < 4:
        issues.append(_issue("high", "model_integrity", "MESH_UNREADABLE", "The exported STL could not be read, so the real part could not be measured.", stlp.name, ic["mesh_valid"]))
        cats["model_integrity"].append(_item("model_integrity", "mesh_valid", "Exported mesh is readable and closed", ic["mesh_valid"], 0.0, expected="readable closed mesh", measured="unreadable"))
        res = aggregate(cats, issues, cfg)
        return {**base, "state": "incomplete", "reason": "mesh_unreadable", "explanation": "The exported STL could not be read.", **res, "issues": issues, "notes": notes, "measured": measured}
    ms = mesh_stats(tris)

    # scale: SolidWorks exports millimetres; the build record's bounding box confirms it
    bb_rec = fmap.get("bbox")
    rec_dims = sorted([abs(bb_rec[i + 3] - bb_rec[i]) for i in range(3)]) if bb_rec and len(bb_rec) == 6 else None
    scale = (1.0 / MM_PER_IN) if units == "inch" else 1.0
    if rec_dims:
        mdims = sorted(ms["dims"].tolist())
        best = min((1.0 / MM_PER_IN, 1.0, 1.0 / 1000.0, 1.0 / (MM_PER_IN * 12)), key=lambda s: max(abs(a * s - b) / max(b, 1e-9) for a, b in zip(mdims, rec_dims)))
        if abs(best - scale) > 1e-12 and max(abs(a * best - b) / max(b, 1e-9) for a, b in zip(mdims, rec_dims)) < 0.02:
            issues.append(_issue("low", "model_integrity", "STL_UNITS", f"The STL looks like it is not in millimetres (scale {best:g} matches the build record).", "", 0))
            scale = best
    dims_u = sorted((ms["dims"] * scale).tolist())
    vol_u = ms["volume"] * scale ** 3
    measured.update({"units": units, "stl_dims": [round(v, 4) for v in dims_u], "stl_volume": round(vol_u, 4), "triangles": ms["triangles"], "closed_fraction": round(ms["closed_fraction"], 4)})

    # 1. build integrity ----------------------------------------------------------------------
    sw_ok = bool(rep.get("sw_ok")) and bool(sldprt)
    cats["model_integrity"].append(_item("model_integrity", "sw_build", "SolidWorks build completed", ic["sw_build"], 1.0 if sw_ok else 0.0, expected="build ok", measured="ok" if sw_ok else "failed"))
    statuses = rep.get("sw_features") or {}
    n_built = sum(1 for v in statuses.values() if str(v).lower().startswith("built"))
    planned = max(len(statuses), 1)
    frac = n_built / planned if statuses else 0.0
    cats["model_integrity"].append(_item("model_integrity", "features_built", "Every planned feature was built", ic["features_built"], frac if statuses else 0.0,
                                         expected=f"{len(statuses)} planned", measured=f"{n_built} built"))
    for fid, v in statuses.items():
        if not str(v).lower().startswith("built"):
            issues.append(_issue("high", "model_integrity", "FEATURE_NOT_BUILT", f"{fid} was planned but not built: {v}.", str(v), ic["features_built"] / planned, fid))
    subs = rep.get("hole_wizard_substitutions") or []
    fallbacks = [fid for fid, v in statuses.items() if re.search(r"fallback|substitut|plain cut", str(v), re.I)] + list(subs)
    cats["model_integrity"].append(_item("model_integrity", "no_fallbacks", "No fallback or substituted features", ic["no_fallbacks"], max(0.0, 1 - 0.5 * len(fallbacks)),
                                         expected="no fallbacks", measured=f"{len(fallbacks)} fallback(s)"))
    if fallbacks:
        issues.append(_issue("medium", "model_integrity", "FALLBACK_USED", f"{len(fallbacks)} feature(s) used a fallback instead of the intended SolidWorks feature.", ", ".join(map(str, fallbacks[:6])), ic["no_fallbacks"] * 0.5 * len(fallbacks)))
    closed_ok = ms["closed_fraction"] >= 0.99 and vol_u > 0
    cats["model_integrity"].append(_item("model_integrity", "mesh_valid", "Exported mesh is a closed solid", ic["mesh_valid"], 1.0 if closed_ok else 0.5 if ms["closed_fraction"] >= 0.9 else 0.0,
                                         expected="closed mesh", measured=f"{ms['closed_fraction'] * 100:.1f}% of edges closed"))
    if not closed_ok:
        issues.append(_issue("medium", "model_integrity", "MESH_OPEN", f"The exported mesh is only {ms['closed_fraction'] * 100:.1f}% closed; measurements may be off.", stlp.name, ic["mesh_valid"] * 0.5))
    mm_credit, mm_note = 1.0, "matches the build record"
    stale = bool(sldprt and stlp and stlp.stat().st_mtime < sldprt.stat().st_mtime - 30)
    if rec_dims:
        rel = max(abs(a - b) / max(b, 1e-9) for a, b in zip(dims_u, rec_dims))
        vol_rec = fmap.get("volume") or rep.get("volume")
        vrel = abs(vol_u - float(vol_rec)) / max(float(vol_rec), 1e-9) if vol_rec else None
        if rel > cfg["gates"]["mesh_vs_build_fraction"] or stale:
            mm_credit, mm_note = 0.0, f"size differs from the build record by {rel * 100:.1f}%" + (", and the STL is older than the SLDPRT" if stale else "")
            issues.append(_issue("critical", "model_integrity", "STL_NOT_THIS_BUILD",
                                 "The exported STL is not the model that was built: " + mm_note + ". It is probably a stale or wrong export, so every measurement below describes the wrong shape.",
                                 f"STL dims {[round(v, 3) for v in dims_u]} vs build record {[round(v, 3) for v in rec_dims]} ({ul})", ic["mesh_matches_build"], stlp.name))
        elif vrel is not None and vrel > 0.05:
            mm_credit, mm_note = 0.5, f"volume differs from the build record by {vrel * 100:.1f}%"
            issues.append(_issue("high", "model_integrity", "VOLUME_MISMATCH", f"The exported mesh volume differs from the build record by {vrel * 100:.1f}%.",
                                 f"{vol_u:.4g} vs {float(vol_rec):.4g} {ul}^3", ic["mesh_matches_build"] * 0.5))
        cats["model_integrity"].append(_item("model_integrity", "mesh_matches_build", "Exported mesh belongs to this build", ic["mesh_matches_build"], mm_credit,
                                             expected=f"{[round(v, 3) for v in rec_dims]} {ul}", measured=f"{[round(v, 3) for v in dims_u]} {ul}", note=mm_note))
    else:
        notes.append("There is no build record (feature_map.json), so the exported mesh could not be cross-checked against the build.")
        cats["model_integrity"].append(_item("model_integrity", "mesh_matches_build", "Exported mesh belongs to this build", ic["mesh_matches_build"], None, note="no build record to compare with"))

    # 2. overall size -------------------------------------------------------------------------
    exp, src = expected_envelope(ext)
    if len(exp) >= 2:
        pool = list(dims_u)
        for e in sorted(exp, key=lambda x: -x["value"]):
            j = min(range(len(pool)), key=lambda k: abs(pool[k] - e["value"]))
            m = pool.pop(j)
            tol = _tol_of(e.get("dim"), units, cfg)
            cr = credit(m - e["value"], tol, cfg)
            rel = abs(m - e["value"]) / max(e["value"], 1e-9)
            cats["envelope"].append(_item("envelope", e["id"], e["label"].replace("_", " "), 1.0, cr, expected=round(e["value"], 4), measured=round(m, 4), unit=units,
                                          error=round(m - e["value"], 4), tol=round(tol, 4), e=round(abs(m - e["value"]) / tol, 2)))
            if rel > cfg["gates"]["envelope_off_fraction"]:
                issues.append(_issue("critical", "envelope", "ENVELOPE_OFF", f"The real part's {e['label'].replace('_', ' ')} is {m:.4g} {ul} but the drawing says {e['value']:.4g} {ul} ({rel * 100:.0f}% off).",
                                     f"{e['id']} expected {e['value']:.4g}, measured {m:.4g}", (1 - cr), e["id"]))
            elif cr < 1:
                sev = "high" if abs(m - e["value"]) / tol > 5 else "medium"
                issues.append(_issue(sev, "envelope", "SIZE_DEVIATION", f"{e['label'].replace('_', ' ')} measures {m:.4g} {ul}, drawing {e['value']:.4g} {ul} (tolerance {tol:.3g}).",
                                     f"{e['id']}", (1 - cr), e["id"]))
    else:
        notes.append("The extraction has fewer than two overall dimensions on its base feature, so the overall size could not be checked against the drawing.")
        issues.append(_issue("info", "envelope", "ENVELOPE_NOT_CHECKABLE", "The overall size could not be checked: the extraction gives fewer than two overall dimensions for the base feature.", "", 0))

    # 3. feature coverage ---------------------------------------------------------------------
    tiers = cfg["tiers"]
    questions = " ".join(rep.get("questions") or [])
    flagged = " ".join(rep.get("flagged") or [])
    for f in ext.get("features") or []:
        fid, ftype = f.get("id"), f.get("type", "")
        if ftype == "thread":
            continue                                           # cosmetic annotation: follows its hole
        w = float(tiers.get(ftype, tiers["default"]))
        if w <= 0:
            continue
        st = str(statuses.get(fid, "")).lower()
        skipped = fmap.get("skipped") or {}
        if st.startswith("built"):
            cr, state = 1.0, "built"
            if re.search(r"fallback|substitut|plain cut", st):
                cr, state = 0.8, "built with a fallback"
        elif fid in skipped or "skipped" in st:
            cr, state = 0.0, "skipped"
            issues.append(_issue("high", "feature_coverage", "FEATURE_SKIPPED", f"{fid} ({ftype}) was in the extraction but is not in the model: {skipped.get(fid, st) or 'skipped'}.", f.get("description", "")[:140], w, fid))
        elif re.search(rf"\b{re.escape(str(fid))}\b", questions):
            cr, state = 0.0, "needs a decision"
            issues.append(_issue("medium", "feature_coverage", "FEATURE_UNRESOLVED", f"{fid} ({ftype}) was not built: the planner asked a question instead of guessing.", "", w, fid))
        else:
            cr, state = 0.0, "missing"
            issues.append(_issue("high", "feature_coverage", "FEATURE_MISSING", f"{fid} ({ftype}) is in the extraction but no build status exists for it.", f.get("description", "")[:140], w, fid))
        cats["feature_coverage"].append(_item("feature_coverage", fid, f"{fid} {ftype.replace('_', ' ')}", w, cr, expected="in the model", measured=state, note=(f.get("description") or "")[:120]))

    # 4 + 5. holes ----------------------------------------------------------------------------
    holes = find_holes(tris)
    for h in holes:
        for k in ("d", "length"):
            h[k + "_u"] = h[k] * scale
        h["depth_u"] = h["length"] * scale
        if h["cbore"]:
            h["cbore"] = {**h["cbore"], "d_u": h["cbore"]["d"] * scale, "depth_u": h["cbore"]["depth"] * scale, "offset_u": h["cbore"]["offset"] * scale}
    measured["holes"] = [{"axis": "XYZ"[h["axis"]], "d": round(h["d_u"], 4), "depth": round(h["depth_u"], 4), "through": h["through"],
                          "cbore": None if not h["cbore"] else {"d": round(h["cbore"]["d_u"], 4), "depth": round(h["cbore"]["depth_u"], 4)}} for h in holes]
    claimed: set[int] = set()
    warns = [str(w) for w in ext.get("warnings") or []]
    callouts = ext.get("hole_callouts") or []
    mt = cfg["match"]
    placeholder_ids = []
    for hc in sorted(callouts, key=lambda c: (c.get("type") == "tapped", -float(c.get("diameter") or 0))):
        hid = hc.get("id", "H?")
        qty = int(hc.get("qty") or len(hc.get("instance_positions") or []) or 1)
        why = _is_placeholder(hc, warns)
        if why:
            placeholder_ids.append(hid)
            issues.append(_issue("medium", "hole_accuracy", "CALLOUT_NOT_SCORABLE", f"{hid} could not be scored: {why}.", f"diameter field = {hc.get('diameter')}", 0, hid))
            continue
        dn = float(hc["diameter"])
        tapped = hc.get("type") == "tapped" or bool(hc.get("thread_spec"))
        lo_d, hi_d = (dn * mt["tapped_range"][0], dn * mt["tapped_range"][1]) if tapped else (dn * (1 - mt["diameter_fraction"]), dn * (1 + mt["diameter_fraction"]))
        cand = [(abs(h["d_u"] - dn), i) for i, h in enumerate(holes) if i not in claimed and lo_d <= h["d_u"] <= hi_d]
        # prefer same-axis groups: take the axis with the most candidates, nearest first
        by_axis: dict[int, list] = {}
        for dd, i in sorted(cand):
            by_axis.setdefault(holes[i]["axis"], []).append((dd, i))
        pick = max(by_axis.values(), key=lambda v: (len(v), -v[0][0]))[:qty] if by_axis else []
        tol_d = _tol_of({"tolerance_plus": 0, "tolerance_minus": 0}, units, cfg)
        cb_d = float(hc.get("cbore_diameter") or 0)
        n_m = len(pick)
        inst_items = []
        for dd, i in pick:
            h = holes[i]
            claimed.add(i)
            if tapped:
                dcr = 1.0 if lo_d <= h["d_u"] <= hi_d else credit(min(abs(h["d_u"] - lo_d), abs(h["d_u"] - hi_d)), tol_d, cfg)
            else:
                dcr = credit(h["d_u"] - dn, tol_d, cfg)
            parts = [dcr]
            if dcr < 1:
                issues.append(_issue("high" if dcr < 0.3 else "medium", "hole_accuracy", "HOLE_DIAMETER",
                                     f"{hid} diameter is {h['d_u']:.4g} {ul} but the drawing calls for {dn:.4g} {ul}" + (" (tapped: a tap-drill size is expected)" if tapped else "") + ".",
                                     f"error {h['d_u'] - dn:+.4g} {ul}", 0.5 * (1 - dcr), hid))
            want_thru = bool(hc.get("thru"))
            depth = float(hc.get("depth") or 0)
            if want_thru:
                parts.append(1.0 if h["through"] else 0.0)
                if not h["through"]:
                    issues.append(_issue("high", "hole_accuracy", "HOLE_NOT_THROUGH", f"{hid} should go through but the real hole is blind ({h['depth_u']:.4g} {ul} deep).", "", 0.5, hid))
            elif depth > 0:
                dcr2 = credit(h["depth_u"] - depth, _tol_of(None, units, cfg), cfg)
                if h["through"]:
                    dcr2 = 0.0
                    issues.append(_issue("high", "hole_accuracy", "HOLE_THROUGH_BUT_BLIND", f"{hid} should be blind ({depth:.4g} {ul}) but the real hole goes all the way through.", "", 0.5, hid))
                elif dcr2 < 1:
                    issues.append(_issue("medium" if dcr2 > 0.3 else "high", "hole_accuracy", "HOLE_DEPTH", f"{hid} depth is {h['depth_u']:.4g} {ul}, drawing {depth:.4g} {ul}.", "", 0.5 * (1 - dcr2), hid))
                parts.append(dcr2)
            cb_d = float(hc.get("cbore_diameter") or 0)
            if cb_d > 0:
                if h["cbore"]:
                    c1 = credit(h["cbore"]["d_u"] - cb_d, _tol_of(None, units, cfg), cfg)
                    parts.append(c1)
                    cbd = float(hc.get("cbore_depth") or 0)
                    if cbd > 0:
                        parts.append(credit(h["cbore"]["depth_u"] - cbd, _tol_of(None, units, cfg), cfg))
                    if c1 < 1:
                        issues.append(_issue("medium", "hole_accuracy", "CBORE_DIAMETER", f"{hid} counterbore is {h['cbore']['d_u']:.4g} {ul}, drawing {cb_d:.4g} {ul}.", "", 0.5 * (1 - c1), hid))
                else:
                    parts.append(0.0)
                    issues.append(_issue("high", "hole_accuracy", "CBORE_MISSING", f"{hid} should have a {cb_d:.4g} {ul} counterbore but the real hole has none.", "", 0.5, hid))
            cr_i = float(np.mean(parts))
            inst_items.append(cr_i)
            cats["hole_accuracy"].append(_item("hole_accuracy", f"{hid}#{len(inst_items)}", f"{hid} {hc.get('type', 'hole')} hole", 1.0, cr_i, expected=f"d {_fmt(dn, units)}" + (" through" if want_thru else f" depth {depth:g}" if depth > 0 else ""),
                                               measured=f"d {_fmt(h['d_u'], units)}, " + ("through" if h["through"] else f"blind {h['depth_u']:.4g}") + (f", cbore d {_fmt(h['cbore']['d_u'], units)}" if h["cbore"] else ""),
                                               unit=units, error=round(h["d_u"] - dn, 4), tol=round(tol_d, 4)))
        for k in range(n_m, qty):                           # called out but not found in the real part
            cats["hole_accuracy"].append(_item("hole_accuracy", f"{hid}#{k + 1}", f"{hid} {hc.get('type', 'hole')} hole", 1.0, 0.0, expected=f"d {_fmt(dn, units)}", measured="not found in the real part", unit=units))
        if n_m < qty:
            issues.append(_issue("high", "hole_accuracy", "HOLE_MISSING", f"{hid}: the drawing calls for {qty} hole(s) of about {dn:.4g} {ul} but only {n_m} exist in the real part.",
                                 f"{qty - n_m} missing", float(qty - n_m), hid))
        # placement: pattern spacing, frame free (distance from each hole to its nearest neighbour)
        pos = hc.get("instance_positions") or []
        if hc.get("position_known", True) and len(pos) >= 2 and n_m >= 2:
            P = np.array(pos, dtype=float)
            D = np.linalg.norm(P[:, None] - P[None], axis=2) + np.eye(len(P)) * 1e9
            exp_nn = np.sort(D.min(axis=1))
            C = np.array([holes[i]["center"] * scale for _, i in pick])
            axis_set = {holes[i]["axis"] for _, i in pick}
            if len(axis_set) == 1:
                ax = axis_set.pop()
                C2 = C[:, [a for a in range(3) if a != ax]]
                Dm = np.linalg.norm(C2[:, None] - C2[None], axis=2) + np.eye(len(C2)) * 1e9
                got_nn = np.sort(Dm.min(axis=1))
                m = min(len(exp_nn), len(got_nn))
                err = float(np.max(np.abs(exp_nn[:m] - got_nn[:m])))
                tol_p = max(cfg["fallback_tol"][units], 1e-6)
                cr_p = credit(err, tol_p, cfg) * (n_m / qty)
                cats["placement"].append(_item("placement", f"{hid}-spacing", f"{hid} pattern spacing", float(qty), cr_p, expected=f"nearest-neighbour {[round(float(v), 4) for v in exp_nn[:3]]}", measured=f"{[round(float(v), 4) for v in got_nn[:3]]}",
                                               unit=units, error=round(err, 4), tol=round(tol_p, 4), e=round(err / tol_p, 2)))
                if cr_p < 1:
                    issues.append(_issue("high" if err / tol_p > 5 else "medium", "placement", "PATTERN_SPACING", f"{hid} hole spacing is off by up to {err:.4g} {ul} compared with the drawing's positions.", f"{err / tol_p:.1f}x tolerance", float(qty) * (1 - cr_p), hid))
        elif not hc.get("position_known", True):
            issues.append(_issue("low", "placement", "POSITION_UNKNOWN", f"{hid}: the extraction does not know where these holes are, so their placement was not scored.", "position_known = false", 0, hid))
        # concentricity of the counterbore
        if cb_d > 0:
            for _, i in pick:
                h = holes[i]
                if h["cbore"]:
                    off = h["cbore"]["offset_u"]
                    tol_c = max(cfg["fallback_tol"][units] / 2, cfg["mesh_floor"][units])
                    cr_c = credit(off, tol_c, cfg)
                    cats["placement"].append(_item("placement", f"{hid}-concentric", f"{hid} counterbore concentric with its hole", 1.0, cr_c, expected="0", measured=_fmt(off, units), unit=units, error=round(off, 4), tol=round(tol_c, 4)))
                    if cr_c < 1:
                        issues.append(_issue("medium", "placement", "CBORE_OFFSET", f"{hid} counterbore is {off:.4g} {ul} off the hole's axis.", "", (1 - cr_c), hid))
    extra = [h for i, h in enumerate(holes) if i not in claimed and h["d_u"] > 0]
    tolerated = sum(int(c.get("qty") or 1) for c in callouts if c.get("id") in placeholder_ids)   # holes behind a callout whose size was not read are expected
    extra = extra[: max(0, len(extra) - tolerated)]
    if extra and callouts:
        pen = min(0.25, 0.05 * len(extra))
        for it in cats["hole_accuracy"]:
            it["credit"] = round(it["credit"] * (1 - pen), 4) if it["credit"] is not None else None
        issues.append(_issue("medium", "hole_accuracy", "HOLE_EXTRA", f"{len(extra)} hole(s) in the real part match no hole callout on the drawing.",
                             ", ".join(f"d {_fmt(h['d_u'], units)}" for h in extra[:5]), pen * len(cats["hole_accuracy"])))
    if not callouts:
        notes.append("The extraction has no hole callouts, so hole accuracy was not checked.")
    if callouts and not cats["hole_accuracy"] and not holes:
        issues.append(_issue("high", "hole_accuracy", "NO_HOLES_FOUND", "The extraction calls out holes but none were found in the real part.", "", 1.0))
        cats["hole_accuracy"].append(_item("hole_accuracy", "all", "Called-out holes exist", 1.0, 0.0, expected=f"{sum(int(c.get('qty') or 1) for c in callouts)} hole(s)", measured="none found"))
    if placeholder_ids:
        notes.append("Not scored because the drawing's size was not read: " + ", ".join(placeholder_ids) + ".")

    # 6. extraction reliability ---------------------------------------------------------------
    tc = cfg["trust_checks"]
    conf = float(ext.get("confidence") or 0)
    ccr = max(0.0, min(1.0, (conf - 0.5) / 0.45))
    cats["extraction_trust"].append(_item("extraction_trust", "confidence", "Extraction confidence", tc["confidence"], ccr, expected=">= 95%", measured=f"{conf * 100:.0f}%"))
    if conf < 0.7:
        issues.append(_issue("medium", "extraction_trust", "LOW_CONFIDENCE", f"The extraction's own confidence is {conf * 100:.0f}%, so the drawing may have been misread.", "", tc["confidence"] * (1 - ccr)))
    dims = ext.get("dimensions") or []
    bad_d = [x for x in dims if x.get("value_unclear") or x.get("resolution_required")]
    bad_h = [h for h in callouts if not h.get("position_known", True)] + [h for h in callouts if h.get("id") in placeholder_ids]
    ratio = (len(bad_d) + len(bad_h)) / max(len(dims) + len(callouts), 1)
    acr = max(0.0, 1 - 2 * ratio)
    cats["extraction_trust"].append(_item("extraction_trust", "ambiguity", "Unclear dimensions and unknown positions", tc["ambiguity"], acr, expected="none",
                                          measured=f"{len(bad_d)} unclear dimension(s), {len(bad_h)} unknown callout(s)"))
    if bad_d:
        issues.append(_issue("medium" if len(bad_d) > 2 else "low", "extraction_trust", "AMBIGUOUS_DIMENSIONS", f"{len(bad_d)} dimension(s) were unclear on the drawing.", ", ".join(x.get("id", "?") for x in bad_d[:6]), tc["ambiguity"] * (1 - acr) * 0.5))
    assumed = len(re.findall(r"POSITION ASSUMED", flagged + " " + " ".join(warns)))
    defaults = len(rep.get("defaults") or [])
    n_q = len(rep.get("questions") or [])
    ef = [f for f in (eng.get("findings") or []) if f.get("severity") in ("critical", "high") and f.get("category") != "practice_advisory"]
    acr2 = max(0.0, 1 - 0.15 * (assumed + defaults + n_q) - 0.25 * len(ef))
    cats["extraction_trust"].append(_item("extraction_trust", "assumptions", "Assumed positions, defaults, open questions, engineering flags", tc["assumptions"], acr2, expected="none",
                                          measured=f"{assumed} assumed, {defaults} default(s), {n_q} question(s), {len(ef)} engineering flag(s)"))
    if assumed:
        issues.append(_issue("medium", "extraction_trust", "POSITION_ASSUMED", f"{assumed} position(s) were assumed, not read from the drawing.", "", tc["assumptions"] * 0.15 * assumed))
    if defaults:
        issues.append(_issue("low", "extraction_trust", "DEFAULTS_APPLIED", f"{defaults} default value(s) were applied where the drawing was vague.", "; ".join(str(x)[:90] for x in (rep.get("defaults") or [])[:3]), tc["assumptions"] * 0.15 * defaults))
    if n_q:
        issues.append(_issue("medium", "extraction_trust", "OPEN_QUESTIONS", f"{n_q} question(s) were left open for a person to answer.", "; ".join(str(x)[:90] for x in rep["questions"][:3]), tc["assumptions"] * 0.15 * n_q))
    for f in ef[:5]:
        issues.append(_issue(f["severity"], "extraction_trust", "ENGINEERING_FLAG", f"Engineering flag: {f.get('title', 'flag')} - {str(f.get('actual', ''))[:120]}", f.get("finding_id", ""), tc["assumptions"] * 0.25))
    for h in rep.get("mti_review") or []:
        issues.append(_issue("info", "model_integrity", "MTI_PRACTICE", str(h)[:200], "advisory only, never blocks a part", 0))

    res = aggregate(cats, issues, cfg)
    issues.sort(key=lambda i: (cfg["severities"][i["severity"]]["rank"], -i["points"]))
    state = "scored" if res["score"] is not None else "incomplete"
    if state == "scored" and res["coverage"] < cfg.get("min_coverage", 0.5):
        issues.append(_issue("info", "model_integrity", "LOW_COVERAGE", f"Only {res['coverage'] * 100:.0f}% of the rubric could be checked, which is too little for an honest score.", "", 0))
        res = {**res, "score": None, "band": band_of(None, cfg), "raw_score": res["raw_score"]}
        state = "incomplete"
        base = {**base, "reason": "low_coverage", "explanation": f"Only {res['coverage'] * 100:.0f}% of the rubric could be checked (the extraction gives too few overall dimensions or hole callouts). The partial result is shown, but no score is given."}
    return {**base, "state": state, **res, "issues": issues, "notes": notes, "measured": measured,
            "counts": {s: sum(1 for i in issues if i["severity"] == s) for s in cfg["severities"]}}


# ── worked example (same aggregate(), synthetic items) ───────────────────────────────────────
def worked_example(cfg: Optional[dict] = None) -> dict:
    """An illustrative plate: three overall sizes, four 0.344 in through holes. NOT a measured part."""
    cfg = cfg or load_config()
    tol = 0.005

    def hole(i, d_err, thru_ok=True):
        parts = [credit(d_err, tol, cfg), 1.0 if thru_ok else 0.0]
        return _item("hole_accuracy", f"H001#{i}", f"H001 hole {i}", 1.0, sum(parts) / len(parts))
    scenarios = []

    def run(label, env_err, holes_cr, pitch_err, conf, issues=None):
        c = {k: [] for k in CAT_ORDER}
        ic = cfg["integrity_checks"]
        c["model_integrity"] = [_item("model_integrity", k, k, w, 1.0) for k, w in ic.items()]
        c["envelope"] = [_item("envelope", f"D{n}", f"dimension {n}", 1.0, credit(e, tol, cfg)) for n, e in enumerate(env_err, 1)]
        c["feature_coverage"] = [_item("feature_coverage", "F001", "base block", 10, 1.0), _item("feature_coverage", "F002", "hole", 5, 1.0)]
        c["hole_accuracy"] = [_item("hole_accuracy", f"H{i}", f"hole {i}", 1.0, cr) for i, cr in enumerate(holes_cr, 1)]
        c["placement"] = [_item("placement", "spacing", "pattern spacing", 4.0, credit(pitch_err, tol, cfg))]
        tc = cfg["trust_checks"]
        c["extraction_trust"] = [_item("extraction_trust", "confidence", "confidence", tc["confidence"], max(0, min(1, (conf - 0.5) / 0.45))),
                                 _item("extraction_trust", "ambiguity", "ambiguity", tc["ambiguity"], 1.0), _item("extraction_trust", "assumptions", "assumptions", tc["assumptions"], 1.0)]
        r = aggregate(c, list(issues or []), cfg)
        scenarios.append({"case": label, "score": r["score"], "band": r["band"], "raw_score": r["raw_score"], "caps": r["caps"],
                          "categories": [{"id": x["id"], "label": x["label"], "weight": x["weight"], "score": x["score"], "earned": x["earned"], "max": x["max"], "band": x["band"]} for x in r["categories"]]})

    run("Everything matches the drawing", [0, 0, 0], [1, 1, 1, 1], 0.0, 0.97)
    run("One hole 0.015 in too small (3x tolerance)", [0, 0, 0], [1, 1, 1, credit(0.015, tol, cfg) * 0.5 + 0.5], 0.0, 0.97)
    run("Hole pattern 0.010 in off pitch (2x tolerance)", [0, 0, 0], [1, 1, 1, 1], 0.010, 0.97)
    run("One hole missing", [0, 0, 0], [1, 1, 1, 0.0], 0.0, 0.97)
    run("Plate 0.06 in too long (12x tolerance) and low extraction confidence", [0.06, 0, 0], [1, 1, 1, 1], 0.0, 0.62)
    run("Exported mesh is not this build (critical gate)", [0, 0, 0], [1, 1, 1, 1], 0.0, 0.97, [_issue("critical", "model_integrity", "STL_NOT_THIS_BUILD", "demo", "", 3)])
    return {"illustrative": True, "label": "Illustrative example, not a measured part", "version": cfg["version"], "fingerprint": fingerprint(),
            "assumptions": "Plate with three overall dimensions, four through holes and one hole pattern; tolerance 0.005 in; every other check passes.", "cases": scenarios}


def methodology(cfg: Optional[dict] = None) -> dict:
    cfg = cfg or load_config()
    c = cfg["credit"]
    return {"id": cfg["id"], "name": cfg["name"], "version": cfg["version"], "fingerprint": fingerprint(), "total_possible": 100,
            "categories": [{"id": k, **cfg["categories"][k]} for k in CAT_ORDER],
            "integrity_checks": cfg["integrity_checks"], "trust_checks": cfg["trust_checks"], "tiers": cfg["tiers"],
            "credit": c, "credit_curve": [{"e": e, "credit": round(credit(e, 1.0, cfg), 3)} for e in (1, 1.5, 2, 5, 10, 20)],
            "fallback_tol": cfg["fallback_tol"], "mesh_floor": cfg["mesh_floor"], "gates": cfg["gates"], "bands": cfg["bands"], "severities": cfg["severities"],
            "match": cfg["match"], "limits": cfg.get("limits", []), "min_coverage": cfg.get("min_coverage", 0.5),
            "formula": "category % = 100 x sum(item weight x item credit) / sum(item weight); score = 100 x sum(category weight x category %) / sum(weights of the categories that could be checked); a critical issue caps the score.",
            "credit_formula": f"item credit = 1 if e <= 1, else {c['drop']} x exp(-(e - 1) / {c['k']}), where e = |measured - drawing| / tolerance"}


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", type=Path, nargs="?", help="a part output folder, or with --all a run folder of part folders")
    ap.add_argument("--methodology", action="store_true", help="print the rubric description, worked example and config fingerprint as JSON")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", type=Path, help="write the JSON here (single part only); default: <part>/fidelity_score.json")
    ap.add_argument("--stdout", action="store_true", help="print the JSON and write nothing")
    a = ap.parse_args(argv)
    if a.methodology:
        print(json.dumps({"methodology": methodology(), "example": worked_example()}))
        return 0
    if a.path is None:
        ap.error("a part folder is required")
    dirs = sorted(p for p in a.path.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name != "usage") if a.all else [a.path]
    rc = 0
    for d in dirs:
        r = evaluate_dir(d)
        if a.stdout:
            print(json.dumps(r))
            continue
        out = a.out if (a.out and not a.all) else d / "fidelity_score.json"
        out.write_text(json.dumps(r, indent=2), encoding="utf-8")
        s = r.get("score")
        print(f"{r['part']:<16} {('%.1f' % s) if s is not None else '-':>6}  {r['band']['label']:<26} {r.get('state')}  issues={len(r.get('issues') or [])}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
