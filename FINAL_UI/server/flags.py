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


# --------------------------------------------------------------------------- #
# Engineering Markup (post-run marked PDF + page previews): validated summary and safe artifact paths
# --------------------------------------------------------------------------- #
MARKUP_MANIFEST, MARKUP_PAGES = "engineering_markup.json", "engineering_markup_pages"
MARKUP_STATUSES = ("not_needed", "ready", "partial", "failed")
MARKUP_LOCATION = ("located", "page_only", "unlocated")
_PAGE_FILE = re.compile(r"^page-(\d{4})\.png$")


def _markup_manifest(out: Path) -> Optional[dict]:
    d = _read(Path(out) / MARKUP_MANIFEST)
    return d if isinstance(d, dict) and d.get("schema_version") == 1 and d.get("status") in MARKUP_STATUSES else None


def markup_pdf_path(out: Path) -> Optional[Path]:
    """The marked PDF named by the manifest, only if it sits directly inside ``out`` and is a *_engineering_markup.pdf."""
    m = _markup_manifest(out)
    if not m or m["status"] not in ("ready", "partial"):
        return None
    name = str(m.get("marked_pdf") or "")
    if not name.endswith("_engineering_markup.pdf") or "/" in name or "\\" in name or name.startswith("."):
        return None
    out_r = Path(out).resolve()
    p = (out_r / name).resolve()
    return p if p.is_file() and p.parent == out_r else None


def markup_page_path(out: Path, page: int) -> Optional[Path]:
    """Preview PNG for a 1-based page the manifest lists; never a path built from client text."""
    m = _markup_manifest(out)
    if not m or m["status"] not in ("ready", "partial") or not isinstance(page, int) or page < 1:
        return None
    listed = {p.get("page") for p in m.get("pages", []) if isinstance(p, dict)}
    if page not in listed:
        return None
    d = (Path(out) / MARKUP_PAGES).resolve()
    p = d / f"page-{page:04d}.png"
    return p if p.is_file() and p.parent == d and _PAGE_FILE.match(p.name) else None


def _rect4(v: Any) -> Optional[list]:
    if not isinstance(v, list) or len(v) != 4:
        return None
    nums = [_num(x) for x in v]
    return nums if all(n is not None for n in nums) else None


def load_markup(out: Path, *, current_sha: Optional[str] = None) -> dict:
    """Bounded, validated summary of ``engineering_markup.json`` for the part payload. Never contains an absolute
    path. A manifest computed for a different drawing revision is reported ``stale`` and its artifacts are withheld."""
    out = Path(out)
    m = _markup_manifest(out)
    if m is None:
        return {"present": False, "status": "none"}
    status = m["status"]
    sha = _txt(m.get("source_sha256"), 80)
    stale = bool(current_sha and sha and sha != current_sha)
    res = {"present": True, "status": "stale" if stale else status, "manifest_status": status, "stale": stale,
           "part": _txt(m.get("part"), 80), "run_id": _txt(m.get("run_id"), 80),
           "generation_key": _txt(m.get("generation_key"), 40), "generated_at": _txt(m.get("generated_at"), 40),
           "generator_version": _txt(m.get("generator_version"), 40),
           "finding_count": int(m.get("finding_count") or 0), "located_count": int(m.get("located_count") or 0),
           "unlocated_count": int(m.get("unlocated_count") or 0), "report_pages": int(m.get("report_pages") or 0),
           "source_name": _txt(m.get("source_pdf"), 200), "warnings": [], "findings": [], "pages": [],
           "has_pdf": False}
    f = m.get("failure")
    if isinstance(f, dict):
        res["failure"] = {"code": _txt(f.get("code"), 60), "detail": _txt(f.get("detail"), 300)}
    for w in (m.get("warnings") or [])[:10]:
        if isinstance(w, dict):
            res["warnings"].append({"code": _txt(w.get("code"), 60), "detail": _txt(w.get("detail"), 300)})
    if stale or status not in ("ready", "partial"):
        return res
    res["has_pdf"] = markup_pdf_path(out) is not None
    for p in (m.get("pages") or [])[:200]:
        if not isinstance(p, dict) or not isinstance(p.get("page"), int):
            continue
        res["pages"].append({"page": p["page"], "width_pt": _num(p.get("width_pt")), "height_pt": _num(p.get("height_pt")),
                             "drawing_width_pt": _num(p.get("drawing_width_pt")), "rail_width_pt": _num(p.get("rail_width_pt")),
                             "finding_ids": [_txt(x, 20) for x in (p.get("finding_ids") or [])[:100]],
                             "has_preview": markup_page_path(out, p["page"]) is not None})
    for r in (m.get("findings") or [])[:MAX_FLAGS]:
        if not isinstance(r, dict):
            continue
        loc = r.get("location_status") if r.get("location_status") in MARKUP_LOCATION else "unlocated"
        res["findings"].append({
            "id": _txt(r.get("id"), 20), "number": int(r.get("number") or 0), "finding_id": _txt(r.get("finding_id"), 80),
            "severity": _txt(r.get("severity"), 20), "code": _txt(r.get("code"), 60), "title": _txt(r.get("title"), 200),
            "explanation": _txt(r.get("explanation"), 1500), "manual_action": _txt(r.get("manual_action"), 600),
            "location_status": loc, "location_method": _txt(r.get("location_method"), 60),
            "confidence": _num(r.get("confidence")) or 0.0,
            "page": r.get("page") if isinstance(r.get("page"), int) else None,
            "rect_pdf_points": _rect4(r.get("rect_pdf_points")), "rect_normalized": _rect4(r.get("rect_normalized")),
            "card": ({"page": r["card"].get("page"), "rect": _rect4(r["card"].get("rect"))}
                     if isinstance(r.get("card"), dict) and isinstance(r["card"].get("page"), int) else None),
            "regions": [{"page": g.get("page"), "rect_pdf_points": _rect4(g.get("rect_pdf_points")),
                         "rect_normalized": _rect4(g.get("rect_normalized")),
                         "rect_marked_pt": _rect4(g.get("rect_marked_pt"))}
                        for g in (r.get("regions") or [])[:20] if isinstance(g, dict) and isinstance(g.get("page"), int)],
            "source_callout": _txt(r.get("source_callout"), 400),
            "feature_ids": [_txt(x, 40) for x in (r.get("feature_ids") or [])[:30]]})
    return res


# ----------------------------------------------------------------------------------------------------------------------
# SolidWorks build recording ("Record Pipeline Run"): manifest + video + poster written by pipeline/solidworks_recorder.py.
REC_MANIFEST, REC_POSTER = "solidworks_recording.json", "solidworks_recording_poster.jpg"
REC_STATUSES = ("recording", "ready", "partial", "failed", "skipped")
REC_VIDEOS = {"solidworks_recording.mp4": "video/mp4", "solidworks_recording.webm": "video/webm"}


def _rec_manifest(out: Path) -> Optional[dict]:
    d = _read(Path(out) / REC_MANIFEST)
    return d if isinstance(d, dict) and d.get("schema_version") == 1 and d.get("status") in REC_STATUSES else None


def recording_video_path(out: Path) -> Optional[Path]:
    """The video named by the manifest: only an allowlisted name that sits directly inside ``out``."""
    m = _rec_manifest(out)
    if not m or m["status"] not in ("ready", "partial"):
        return None
    name = str(m.get("video") or "")
    if name not in REC_VIDEOS:
        return None
    out_r = Path(out).resolve()
    p = (out_r / name).resolve()
    return p if p.is_file() and p.parent == out_r else None


def recording_poster_path(out: Path) -> Optional[Path]:
    m = _rec_manifest(out)
    if not m or m["status"] not in ("ready", "partial") or m.get("poster") != REC_POSTER:
        return None
    out_r = Path(out).resolve()
    p = (out_r / REC_POSTER).resolve()
    return p if p.is_file() and p.parent == out_r else None


def load_recording(out: Path, *, current_sha: Optional[str] = None, run_active: bool = False) -> dict:
    """Bounded, validated summary of ``solidworks_recording.json``. Never contains an absolute path. A recording made for
    a different drawing revision is ``stale`` (video withheld); a ``recording`` manifest with no live run is ``interrupted``."""
    out = Path(out)
    m = _rec_manifest(out)
    if m is None:
        return {"present": False, "status": "none"}
    status = m["status"]
    sha = _txt(m.get("source_sha256"), 80)
    stale = bool(current_sha and sha and sha != current_sha)
    shown = "stale" if stale else status
    code, reason = _txt(m.get("code"), 40), _txt(m.get("reason"), 300)
    if status == "recording" and not run_active and not stale:
        shown, code, reason = "interrupted", "REC_INTERRUPTED", "The run ended before the recording was finished."
    res = {"present": True, "status": shown, "manifest_status": status, "stale": stale,
           "part": _txt(m.get("part"), 80), "run_id": _txt(m.get("run_id"), 80),
           "generation_key": _txt(m.get("generation_key"), 40), "code": code, "reason": reason,
           "backend": _txt(m.get("backend"), 20), "fps": int(_num(m.get("fps")) or 0),
           "width": int(_num(m.get("width")) or 0), "height": int(_num(m.get("height")) or 0),
           "frames": int(_num(m.get("frames")) or 0), "dropped_frames": int(_num(m.get("dropped_frames")) or 0),
           "duration_s": _num(m.get("duration_s")) or 0.0, "bytes": int(_num(m.get("bytes")) or 0),
           "paced": bool(m.get("paced")), "build_outcome": _txt(m.get("build_outcome"), 20),
           "has_video": False, "has_poster": False, "media_type": "", "chapters": []}
    if stale or status not in ("ready", "partial"):
        return res
    v = recording_video_path(out)
    res["has_video"] = v is not None
    res["media_type"] = REC_VIDEOS.get(v.name, "") if v else ""
    res["has_poster"] = recording_poster_path(out) is not None
    for c in (m.get("chapters") or [])[:200]:
        if isinstance(c, dict) and _num(c.get("t")) is not None:
            res["chapters"].append({"id": _txt(c.get("id"), 40), "label": _txt(c.get("label"), 80),
                                    "status": _txt(c.get("status"), 20), "t": _num(c.get("t"))})
    return res
