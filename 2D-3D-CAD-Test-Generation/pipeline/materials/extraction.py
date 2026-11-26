"""The ``material_extraction`` object of an extraction result (Phase 1, section 2 of the material spec).

Evidence is kept apart from inference.  A drawing that names no material is ``not_specified``: no candidate, no evidence, and the
UI says "No material specified on drawing".  Nothing here ever guesses a material from geometry, colour, weight or part name.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

STATUSES = ("specified", "not_specified", "ambiguous", "conflicting", "unreadable")
Status = Literal["specified", "not_specified", "ambiguous", "conflicting", "unreadable"]
# a blank / dash / N/A material field is evidence of absence, never a grade
_ABSENT_TOKENS = {"", "-", "--", "---", "n/a", "na", "none", "not specified", "see note", "tbd", "tba", "x", "xxx"}


class MaterialEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, description="1-based drawing page the text was read from")
    region: str = Field(default="", description="title_block | general_notes | bom | detail_callout | other")
    quote: str = Field(default="", description="the exact text on the drawing, copied character for character")
    bbox_normalized: Optional[list[float]] = Field(default=None, description="[x0,y0,x1,y1] in 0..1 page coordinates, or null")


class MaterialExtraction(BaseModel):
    """What the drawing says about the base material. Coating, plating, heat treatment, finish, hardness and stock form are
    separate fields, never folded into the base material."""

    model_config = ConfigDict(extra="forbid")

    status: Status = Field(description="specified | not_specified | ambiguous | conflicting | unreadable")
    raw_text: Optional[str] = Field(default=None, description="exact drawing text of the material field, or null when none")
    normalized_candidate: Optional[str] = Field(
        default=None, description="the material as written, tidied only (keep the exact grade, condition and temper, e.g. 6061-T6); null when none")
    evidence: list[MaterialEvidence] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list, description="other materials the drawing names for the same part (conflicts / ambiguity)")
    confidence: Optional[float] = Field(default=None, description="heuristic only, 0..1, or null; never proof")
    review_reason: Optional[str] = Field(default=None, description="why an engineer must look at this, or null")
    specification: Optional[str] = Field(default=None, description="a material specification named, e.g. ASTM A36, AMS 4027; null if none")
    condition_or_temper: Optional[str] = Field(default=None, description="e.g. T6, annealed, cold drawn; null if none")
    coating: Optional[str] = Field(default=None, description="plating / anodize / paint / coating note, kept out of the base material")
    heat_treatment: Optional[str] = Field(default=None)
    finish: Optional[str] = Field(default=None)
    hardness: Optional[str] = Field(default=None)
    stock_form: Optional[str] = Field(default=None, description="bar, plate, sheet, tube... if stated")
    body_scope: Optional[str] = Field(default=None, description="which body/feature the material applies to when several materials are named; null = the whole part")


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def is_absent_text(text: Optional[str]) -> bool:
    return _squash(text or "").strip(" .:;_").lower() in _ABSENT_TOKENS


def not_specified(reason: Optional[str] = None) -> MaterialExtraction:
    return MaterialExtraction(status="not_specified", review_reason=reason)


def from_legacy_text(text: str) -> MaterialExtraction:
    """Wrap the old free-text ``material`` field (extractions saved before this upgrade) without inventing evidence."""
    t = _squash(text)
    if is_absent_text(t):
        return not_specified()
    return MaterialExtraction(status="specified", raw_text=t, normalized_candidate=t,
                              evidence=[MaterialEvidence(page=1, region="title_block", quote=t)],
                              review_reason="Read from the pre-upgrade material field; the original drawing text was not re-verified.")


def normalize(me: Optional[MaterialExtraction], legacy_text: str = "") -> MaterialExtraction:
    """Enforce the contract's invariants. Never upgrades a status; only downgrades what the evidence cannot support."""
    if me is None:
        return from_legacy_text(legacy_text)
    me = me.model_copy(deep=True)
    if me.confidence is not None and not (0.0 <= me.confidence <= 1.0):
        me.confidence = None
    if me.status == "not_specified":
        me.raw_text = None
        me.normalized_candidate = None
        me.evidence = []
        me.alternatives = []
        return me
    if me.status == "unreadable":
        me.normalized_candidate = None
        return me
    if me.status == "specified":
        if is_absent_text(me.raw_text) and is_absent_text(me.normalized_candidate):
            return not_specified("The material field was blank or a placeholder (dash / N/A).")
        if not me.evidence or not any(_squash(e.quote) for e in me.evidence):
            me.review_reason = (me.review_reason + " " if me.review_reason else "") + "No drawing text was cited for this material."
        if not me.normalized_candidate:
            me.normalized_candidate = _squash(me.raw_text or "")
    if me.status in ("ambiguous", "conflicting") and not me.review_reason:
        me.review_reason = "The drawing names more than one material." if me.status == "conflicting" else "The material callout is ambiguous."
    return me


def validate_citations(me: MaterialExtraction, page_texts: dict[int, str]) -> MaterialExtraction:
    """Check each quoted evidence string against the drawing's own text (OCR / PDF text layer) when we have it. A quote that is not
    found is flagged, never silently trusted; a model that cites text that is not on the page is hallucinating a material."""
    if not page_texts or me.status in ("not_specified", "unreadable") or not me.evidence:
        return me
    me = me.model_copy(deep=True)
    flat = {p: re.sub(r"[^a-z0-9]+", "", t.lower()) for p, t in page_texts.items()}
    allflat = "".join(flat.values())
    bad = []
    for e in me.evidence:
        q = re.sub(r"[^a-z0-9]+", "", (e.quote or "").lower())
        if not q:
            continue
        hay = flat.get(e.page, allflat)
        if q not in hay and q not in allflat:
            bad.append(e.quote)
    if bad:
        note = "The quoted text was not found in the drawing text: " + "; ".join(repr(b) for b in bad[:3]) + "."
        me.review_reason = (me.review_reason + " " if me.review_reason else "") + note
        me.confidence = None
        if me.status == "specified":
            me.status = "ambiguous"
    return me


def summary_line(me: MaterialExtraction) -> str:
    if me.status == "not_specified":
        return "No material specified on drawing"
    if me.status == "unreadable":
        return "Material text is unreadable on the drawing"
    return me.normalized_candidate or me.raw_text or "Material needs review"
