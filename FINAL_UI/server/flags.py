"""Engineering-flag artifacts on the server (Stage 3): validation, bounded payloads, review state.

Pure functions (no FastAPI). The pipeline writes ``engineering_findings.json`` and
``engineering_flag_overlays.json`` (see pipeline/flag_overlays.py); the server only *validates and serves*
them. It never accepts overlay geometry or HTML from a client. What a person decides about a flag
(acknowledge, corrected, dismissed) lives in a separate mutable file and never edits the pipeline's
findings.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 1
MAX_FLAGS = 300
FINDINGS, OVERLAYS, ANNOTATED, REVIEW = ("engineering_findings.json", "engineering_flag_overlays.json",
                                         "engineering_flags_annotated.pdf", "engineering_flag_review.json")
ALLOWED = {FINDINGS, OVERLAYS, ANNOTATED}
SEVERITIES = ("error", "warning", "info")
REVIEW_STATES = ("open", "acknowledged", "corrected_pending_rerun", "verified_corrected", "dismissed_with_reason")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FINDING_KEYS = ("finding_id", "part", "run_id", "severity", "category", "title", "expected", "actual", "consequence", "recommended_action")
_FINDING_LISTS = ("feature_ids", "source_callouts", "evidence_ids")
_OVERLAY_KEYS = ("overlay_id", "finding_id", "number", "severity", "label", "page_index", "shape", "rect_normalized",
                 "label_anchor_normalized", "mapping_method", "mapping_confidence", "matched_text", "rotation_degrees",
                 "source_callout", "provenance")
_UNLOC_KEYS = ("finding_id", "number", "severity", "label", "reason", "likely_page", "likely_view", "likely_region", "candidates")


def artifact_path(out: Path, name: str) -> Optional[Path]:
    """An allowlisted artifact inside ``out`` or None. Names are matched exactly: no separators, no traversal."""
    if name not in ALLOWED:
        return None
    out = Path(out).resolve()
    p = (out / name).resolve()
    return p if p.is_file() and p.parent == out else None


def _txt(v: Any, limit: int = 1000) -> str:
    return _CTRL.sub("", str(v if v is not None else "")).strip()[:limit]


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _finding(d: dict) -> Optional[dict]:
    if not isinstance(d, dict) or not _txt(d.get("finding_id")):
        return None
    out = {k: _txt(d.get(k), 200 if k == "title" else 1000) for k in _FINDING_KEYS}
    if out["severity"] not in SEVERITIES:
        out["severity"] = "info"
    for k in _FINDING_LISTS:
        out[k] = [_txt(x, 300) for x in (d.get(k) or [])[:50] if _txt(x, 300)] if isinstance(d.get(k), list) else []
    return out


def _rect_ok(r: Any) -> Optional[dict]:
    if not isinstance(r, dict):
        return None
    x, y, w, h = (_num(r.get(k)) for k in ("x", "y", "width", "height"))
    if None in (x, y, w, h) or w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1.0001 or y + h > 1.0001:
        return None
    return {"x": x, "y": y, "width": w, "height": h}


def _overlay(d: dict, n_pages: int) -> Optional[dict]:
    if not isinstance(d, dict):
        return None
    rect = _rect_ok(d.get("rect_normalized"))
    pi = d.get("page_index")
    if rect is None or isinstance(pi, bool) or not isinstance(pi, int) or not 0 <= pi < n_pages:
        return None
    out = {k: d.get(k) for k in _OVERLAY_KEYS if k in d}
    for k in ("overlay_id", "finding_id", "severity", "label", "shape", "mapping_method", "matched_text", "source_callout", "provenance"):
        if k in out:
            out[k] = _txt(out[k], 300)
    if out.get("severity") not in SEVERITIES:
        out["severity"] = "info"
    out["rect_normalized"] = rect
    anchor = d.get("label_anchor_normalized")
    ax, ay = (_num(anchor.get(k)) for k in ("x", "y")) if isinstance(anchor, dict) else (None, None)
    out["label_anchor_normalized"] = {"x": min(1.0, max(0.0, ax)), "y": min(1.0, max(0.0, ay))} if ax is not None and ay is not None else {"x": rect["x"], "y": rect["y"]}
    out["mapping_confidence"] = min(1.0, max(0.0, _num(d.get("mapping_confidence")) or 0.0))
    out["rotation_degrees"] = d.get("rotation_degrees") if d.get("rotation_degrees") in (0, 90, 180, 270) else 0
    out["number"] = d.get("number") if isinstance(d.get("number"), int) and not isinstance(d.get("number"), bool) else 0
    return out


def _read(p: Path) -> Optional[dict]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def load_flags(out: Path, *, current_sha: Optional[str], latest_run_id: Optional[str]) -> dict:
    """Validated, bounded flags for an output folder. ``current_sha`` is the SHA-256 of the drawing the
    UI would display now (None if it cannot be determined); ``latest_run_id`` the newest run of this part."""
    out = Path(out)
    fp, op = out / FINDINGS, out / OVERLAYS
    if not fp.exists() and not op.exists():
        return {"present": False, "reason": "none"}
    if not (fp.exists() and op.exists()):
        return {"present": False, "reason": "incomplete"}
    fd, ov = _read(fp), _read(op)
    if fd is None or ov is None:
        return {"present": False, "reason": "unreadable"}
    if fd.get("schema_version") != SCHEMA_VERSION or ov.get("schema_version") != SCHEMA_VERSION:
        return {"present": False, "reason": "unsupported_schema"}
    raw_findings = fd.get("findings") if isinstance(fd.get("findings"), list) else []
    all_findings = [f for f in (_finding(x) for x in raw_findings) if f]
    findings = all_findings[:MAX_FLAGS]
    ids = {f["finding_id"] for f in findings}
    pages = [{"page_index": p.get("page_index"), "width": _num(p.get("width")), "height": _num(p.get("height")),
              "rotation": p.get("rotation") if p.get("rotation") in (0, 90, 180, 270) else 0, "text_source": _txt(p.get("text_source"), 20)}
             for p in (ov.get("pages") or []) if isinstance(p, dict)]
    overlays = [o for o in (_overlay(x, len(pages)) for x in (ov.get("overlays") or [])) if o and o.get("finding_id") in ids][:MAX_FLAGS]
    located_ids = {o["finding_id"] for o in overlays}
    run_id = _txt(ov.get("run_id"), 80)
    sha = _txt(ov.get("source_pdf_sha256"), 64)
    stale, reason, verified = False, None, True
    if current_sha is None:
        verified, reason = False, "drawing_unavailable"
    elif current_sha != sha:
        stale, reason = True, "drawing_revision_changed"
    elif latest_run_id and latest_run_id != run_id:
        stale, reason = True, "older_run"
    withheld = 0
    if stale or not verified:
        withheld, overlays = len(overlays), []
    unloc = [{k: u.get(k) for k in _UNLOC_KEYS if k in u} for u in (ov.get("unlocated_findings") or []) if isinstance(u, dict) and u.get("finding_id") in ids]
    for u in unloc:
        for k in ("finding_id", "severity", "label", "reason", "likely_view"):
            if k in u:
                u[k] = _txt(u[k], 300)
    seen_unloc = {u["finding_id"] for u in unloc}
    placed = located_ids if not (stale or not verified) else set()
    for f in findings:
        if f["finding_id"] not in placed and f["finding_id"] not in seen_unloc:
            unloc.append({"finding_id": f["finding_id"], "reason": reason or "invalid_geometry"})
    review = get_review(out)
    current_ids = {f["finding_id"] for f in all_findings}
    history = _reconcile(out, review, current_ids, run_id)
    res = {"present": True, "schema_version": SCHEMA_VERSION, "run_id": run_id, "source_sha256": sha,
           "source_name": _txt(ov.get("source_name"), 200), "hash_verified": verified, "stale": stale,
           "counts": {"findings": len(all_findings), "located": len(located_ids), "unlocated": len(all_findings) - len(located_ids)},
           "findings": findings, "overlays": overlays, "unlocated": unloc, "pages": pages, "withheld_overlays": withheld,
           "truncated": len(all_findings) > MAX_FLAGS,
           "review": {k: v for k, v in review.items() if k in ids}, "resolved_history": history,
           "artifacts": {"findings": FINDINGS, "overlays": OVERLAYS,
                         "annotated_pdf": ANNOTATED if (out / ANNOTATED).is_file() else None}}
    if reason:
        res["reason"] = reason
    return res


# --------------------------------------------------------------------------- #
# Review state: what a person decided. Separate from, and never edits, the pipeline's findings.
# --------------------------------------------------------------------------- #
def get_review(out: Path) -> dict:
    d = _read(Path(out) / REVIEW)
    return {k: v for k, v in (d or {}).items() if isinstance(v, dict) and v.get("state") in REVIEW_STATES}


def _write_review(out: Path, review: dict) -> None:
    Path(out, REVIEW).write_text(json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8")


def set_review(out: Path, finding_id: str, state: Any, reason: str = "", *, system: bool = False) -> dict:
    """Record a human decision. Raises ValueError for an unknown state or finding, a dismissal with no reason, or a
    user trying to mark a finding ``verified_corrected`` (only a re-run that no longer produces it can)."""
    out = Path(out)
    if state not in REVIEW_STATES:
        raise ValueError(f"state must be one of {REVIEW_STATES}")
    if state == "verified_corrected" and not system:
        raise ValueError("verified_corrected is set only when a re-run no longer produces the finding")
    fd = _read(out / FINDINGS) or {}
    if finding_id not in {f.get("finding_id") for f in fd.get("findings", []) if isinstance(f, dict)}:
        raise ValueError("unknown finding")
    reason = _txt(reason, 500)
    if state == "dismissed_with_reason" and not reason:
        raise ValueError("a dismissal needs a reason")
    review = get_review(out)
    rec = {"state": state, "reason": reason, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    review[finding_id] = rec
    _write_review(out, review)
    return rec


def _reconcile(out: Path, review: dict, current_ids: set, run_id: str) -> list:
    """A flag a person marked 'corrected' disappears only when the new run no longer produces it: record that
    as verified_corrected and keep it as history linked to the run that verified it."""
    history, changed = [], False
    for fid, rec in review.items():
        if fid in current_ids:
            continue
        if rec["state"] == "corrected_pending_rerun":
            rec = {**rec, "state": "verified_corrected", "verified_in_run": run_id,
                   "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            review[fid] = rec
            changed = True
        if rec["state"] == "verified_corrected":
            history.append({"finding_id": fid, "state": rec["state"], "verified_in_run": rec.get("verified_in_run", run_id)})
    if changed:
        _write_review(out, review)
    return history
