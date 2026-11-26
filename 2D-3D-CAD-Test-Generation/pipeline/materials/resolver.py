"""Deterministic catalog resolution (Phase 1, section 4).

Exact id / name / specification / approved alias matches only.  Fuzzy matches are *suggestions*: they are listed, never assigned, and
a suggestion with a different grade or temper is labelled as such.  A company entry always beats a demo or standard entry.  A part with
no material on the drawing stays unassigned; a manual override is allowed but is labelled as an override, with who/when/why.
"""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone
from typing import Optional

from pipeline.materials.catalog import Catalog, MaterialRecord
from pipeline.materials.extraction import MaterialExtraction, normalize, summary_line

STATUSES = ("matched", "not_specified", "unmatched", "ambiguous", "override_pending", "assigned_verified", "assignment_failed")
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_GRADE_TOKEN = re.compile(r"\b(?:[a-z]{0,2}\d{2,5}[a-z]?(?:\.\d+)?|t\d{1,4}|h\d{2}|o|sae|aisi|astm)\b")
_NUM_TOKEN = re.compile(r"\d{2,5}(?:\.\d+)?")
_TEMPER = re.compile(r"\b(t\d{1,4}|h\d{2}|o|annealed|normalized|quenched|tempered|cold drawn|hot rolled)\b")


def norm(s: str) -> str:
    """Conservative normalisation: case, whitespace, unicode dashes and stray punctuation. Grade and temper tokens are preserved."""
    s = (s or "").translate(_DASHES).lower()
    s = re.sub(r"^\s*(material|mat'?l)\s*[:=\-]\s*", "", s)
    s = re.sub(r"\s*([,;])\s*", r"\1 ", s)
    s = re.sub(r"[^a-z0-9.+/,;\- ()]+", " ", s)
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s+", " ", s).strip(" .,;")
    return s


def _keys(rec: MaterialRecord) -> set[str]:
    ks = {norm(rec.id), norm(rec.label), norm(rec.sw_material_name or ""), norm(rec.spec)} | {norm(a) for a in rec.aliases}
    # SOLIDWORKS names carry a "(SS)"/"(SN)" suffix that marks the SimulationXpress library, not the alloy
    ks |= {re.sub(r"\s*\((ss|sn)\)$", "", k).strip() for k in list(ks)}
    ks.discard("")
    return ks


def _grade_sig(s: str) -> tuple[frozenset, frozenset]:
    n = norm(s)
    return frozenset(_NUM_TOKEN.findall(n)), frozenset(m.group(1) for m in _TEMPER.finditer(n))


def exact_matches(query: str, catalog: Catalog) -> list[MaterialRecord]:
    q = norm(query)
    if not q:
        return []
    qs = re.sub(r"\s*\((ss|sn)\)$", "", q).strip()
    return [r for r in catalog.records if q in _keys(r) or qs in _keys(r)]


def suggestions(query: str, catalogs: list[Catalog], limit: int = 5) -> list[dict]:
    """Fuzzy candidates for a human to approve. Never auto-assigned."""
    q = norm(query)
    if not q:
        return []
    qnums, qtemp = _grade_sig(query)
    scored: list[tuple[float, MaterialRecord]] = []
    for cat in catalogs:
        for r in cat.records:
            best = max((difflib.SequenceMatcher(None, q, k).ratio() for k in _keys(r)), default=0.0)
            if best >= 0.55 or (qnums and qnums <= _grade_sig(r.label)[0]):
                scored.append((best, r))
    scored.sort(key=lambda t: -t[0])
    out = []
    for score, r in scored[: limit * 3]:
        rn, rt = _grade_sig(r.label + " " + r.spec)
        same_grade = (not qnums) or qnums <= rn
        same_temper = (not qtemp) or qtemp <= rt
        out.append({"id": r.id, "label": r.label, "catalog_id": next((c.catalog_id for c in catalogs if r in c.records), ""), "source": r.source,
                    "similarity": round(score, 3), "different_grade": not same_grade, "different_temper_or_condition": not same_temper,
                    "auto_assignable": False})
    out.sort(key=lambda d: (d["different_grade"], d["different_temper_or_condition"], -d["similarity"]))
    return out[:limit]


def _chosen(rec: MaterialRecord, cat: Catalog) -> dict:
    return {"material_id": rec.id, "label": rec.label, "catalog_id": cat.catalog_id, "catalog_source": cat.source, "catalog_path": cat.path,
            "catalog_sha256": cat.sha256, "density_kg_m3": rec.density_kg_m3, "price_per_kg": rec.price_per_kg, "currency": rec.currency,
            "price_basis": rec.price_basis, "sw_material_name": rec.sw_material_name, "sw_database": rec.sw_database,
            "appearance": rec.appearance, "classification": rec.classification}


def resolve(extraction: Optional[MaterialExtraction], *, company: Optional[Catalog] = None, demo: Optional[Catalog] = None,
            standard: Optional[Catalog] = None, override: Optional[dict] = None, legacy_text: str = "") -> dict:
    """Return the material resolution record (JSON-serialisable). ``override`` = {"material_id", "catalog_id"?, "reason", "user"?}."""
    me = normalize(extraction, legacy_text)
    catalogs = [c for c in (company, demo, standard) if c is not None]
    res: dict = {
        "status": "unmatched", "drawing": {"status": me.status, "raw_text": me.raw_text, "normalized_candidate": me.normalized_candidate,
                                           "evidence": [e.model_dump() for e in me.evidence], "alternatives": me.alternatives,
                                           "confidence": me.confidence, "review_reason": me.review_reason, "specification": me.specification,
                                           "condition_or_temper": me.condition_or_temper, "coating": me.coating, "heat_treatment": me.heat_treatment,
                                           "finish": me.finish, "hardness": me.hardness, "stock_form": me.stock_form, "body_scope": me.body_scope},
        "label": summary_line(me), "chosen": None, "selection_source": None, "suggestions": [], "standard_candidates": [],
        "override": None, "review_required": False, "review_reasons": [], "assignable": False,
        "catalogs": [c.snapshot() for c in catalogs], "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    reasons: list[str] = res["review_reasons"]

    # ----- manual override: allowed, always labelled, never presented as a drawing-derived match
    if override and override.get("material_id"):
        rec, cat = None, None
        for c in catalogs:
            if override.get("catalog_id") and c.catalog_id != override["catalog_id"]:
                continue
            rec = c.by_id(override["material_id"])
            if rec is not None:
                cat = c
                break
        if rec is None:
            res["status"] = "unmatched"
            reasons.append(f"Override material {override['material_id']!r} is not in the active catalogs.")
            res["review_required"] = True
            return res
        reason = str(override.get("reason") or "").strip()
        if not reason:
            res["status"] = "unmatched"
            reasons.append("A manual override needs a reason.")
            res["review_required"] = True
            return res
        drawing_txt = me.normalized_candidate or ""
        diverges = me.status != "specified" or (norm(drawing_txt) not in _keys(rec))
        res.update(status="override_pending", chosen=_chosen(rec, cat), selection_source="manual_override", assignable=True,
                   override={"material_id": rec.id, "reason": reason, "user": override.get("user") or "unknown",
                             "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "diverges_from_drawing": diverges,
                             "drawing_text": me.raw_text})
        if diverges:
            res["review_required"] = True
            reasons.append("Manual override: this is not what the drawing says" +
                           (f" (drawing: {me.raw_text})" if me.raw_text else " (the drawing names no material)") + ".")
        return res

    if me.status == "not_specified":
        res["status"] = "not_specified"
        res["label"] = "No material specified on drawing"
        return res
    if me.status in ("conflicting", "ambiguous", "unreadable") or me.body_scope or len(me.alternatives) > 0:
        res["status"] = "ambiguous"
        res["review_required"] = True
        if me.status == "unreadable":
            reasons.append("The material text on the drawing could not be read; this is not the same as no material.")
        elif me.body_scope or any(a for a in me.alternatives):
            reasons.append("The drawing names more than one material or a body-specific material; a body mapping is needed, and no single "
                           "material is applied over it.")
        else:
            reasons.append(me.review_reason or "The material callout is ambiguous.")
        q = me.normalized_candidate or me.raw_text or " ".join(me.alternatives)
        res["suggestions"] = suggestions(q, catalogs)
        return res

    query = me.normalized_candidate or me.raw_text or ""
    # ----- exact match, company first
    if company is not None:
        hits = exact_matches(query, company)
        if len(hits) == 1:
            res.update(status="matched", chosen=_chosen(hits[0], company), selection_source="drawing", assignable=True)
            return res
        if len(hits) > 1:
            res.update(status="ambiguous", review_required=True)
            reasons.append("More than one company catalog entry matches exactly: " + ", ".join(h.id for h in hits[:5]) + ".")
            return res
        # the company library has no match: offer standard candidates for approval, never substitute silently
        res.update(status="unmatched", review_required=True)
        reasons.append("The company library has no entry for this material; choose one explicitly or fix the library.")
        for c in (standard, demo):
            if c is None:
                continue
            for h in exact_matches(query, c):
                res["standard_candidates"].append({"id": h.id, "label": h.label, "catalog_id": c.catalog_id, "source": c.source,
                                                   "density_kg_m3": h.density_kg_m3, "needs_explicit_approval": True})
        res["suggestions"] = suggestions(query, [c for c in (company, standard, demo) if c is not None])
        return res
    for cat in (demo, standard):
        if cat is None:
            continue
        hits = exact_matches(query, cat)
        if len(hits) == 1:
            res.update(status="matched", chosen=_chosen(hits[0], cat), selection_source="drawing", assignable=True)
            if cat.source == "demo":
                reasons.append("Matched a generic demo entry (illustrative prices); not an approved company material.")
            return res
        if len(hits) > 1:
            res.update(status="ambiguous", review_required=True)
            reasons.append("More than one catalog entry matches exactly: " + ", ".join(h.id for h in hits[:5]) + ".")
            return res
    res.update(status="unmatched", review_required=True)
    reasons.append("No catalog entry matches this material exactly; fuzzy candidates are suggestions only.")
    res["suggestions"] = suggestions(query, catalogs)
    return res
