"""Engineering findings: one evidence-linked contract for everything the pipeline flags (Stage 3).

A finding says what the drawing expects, what the model has, why it matters and what a person should
check, and links to the model feature(s), the drawing callout(s) and the evidence rows behind it. It
carries NO position: placing it on the drawing is the locator's job (``flag_locator.py``), always
automatic. Text is stored as plain text (engineering symbols such as Ø ± ° intact, control characters
removed); the UI escapes on render. Recommended actions are templated per known mismatch type: an
unknown repair says "review", it never invents a SolidWorks command.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

SCHEMA_VERSION = 1
SEVERITIES = ("error", "warning", "info")
CATEGORIES = (
    "feature_not_built", "feature_unresolved", "volume_mismatch", "bbox_mismatch", "plan_rejected",
    "hole_depth_mismatch", "hole_diameter_mismatch", "hole_position_mismatch",
    "geometry_extra_material", "geometry_missing_material", "hole_wizard_substituted", "practice_advisory", "extraction_review", "other",
)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX, _MAX_TITLE = 1000, 200
_FID = re.compile(r"\bF\d{3}\b")


def _clean(v: Any, limit: int = _MAX) -> str:
    return _CTRL.sub("", str(v if v is not None else "")).strip()[:limit]


def _clean_list(v: Optional[Iterable[Any]]) -> list[str]:
    seen, out = set(), []
    for x in v or []:
        s = _clean(x, 300)
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


@dataclass(frozen=True)
class Finding:
    finding_id: str
    part: str
    run_id: str
    severity: str
    category: str
    title: str
    expected: str
    actual: str
    consequence: str
    recommended_action: str
    feature_ids: list = field(default_factory=list)
    source_callouts: list = field(default_factory=list)
    evidence_ids: list = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(cls, *, part: str, run_id: str, severity: str, category: str, title: str, expected: str, actual: str,
               consequence: str, recommended_action: str, feature_ids=None, source_callouts=None, evidence_ids=None) -> "Finding":
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}, got {severity!r}")
        if not _clean(title):
            raise ValueError("title is required")
        evidence = _clean_list(evidence_ids)
        if not evidence:
            raise ValueError("a finding needs at least one evidence id")
        category = category if category in CATEGORIES else "other"
        fids = sorted(set(_clean_list(feature_ids)))
        exp, act = _clean(expected), _clean(actual)
        digest = hashlib.sha1("|".join([_clean(part), category, ",".join(fids), exp, act]).encode("utf-8")).hexdigest()[:12]
        return cls(finding_id="flag_" + digest, part=_clean(part, 80), run_id=_clean(run_id, 80), severity=severity,
                   category=category, title=_clean(title, _MAX_TITLE), expected=exp, actual=act,
                   consequence=_clean(consequence), recommended_action=_clean(recommended_action),
                   feature_ids=fids, source_callouts=_clean_list(source_callouts), evidence_ids=evidence)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Finding":
        f = cls.create(part=d.get("part", ""), run_id=d.get("run_id", ""), severity=d["severity"], category=d["category"],
                       title=d["title"], expected=d.get("expected", ""), actual=d.get("actual", ""),
                       consequence=d.get("consequence", ""), recommended_action=d.get("recommended_action", ""),
                       feature_ids=d.get("feature_ids"), source_callouts=d.get("source_callouts"), evidence_ids=d.get("evidence_ids"))
        return f


def validate(f: Finding) -> list[str]:
    """Problems with a finding (empty when valid). create() already refuses the worst ones."""
    bad = []
    if f.severity not in SEVERITIES:
        bad.append("severity")
    if f.category not in CATEGORIES:
        bad.append("category")
    if not f.title:
        bad.append("title")
    if not f.evidence_ids:
        bad.append("evidence")
    if not (f.expected or f.actual):
        bad.append("expected/actual")
    if not f.finding_id.startswith("flag_"):
        bad.append("finding_id")
    return bad


def dedupe(findings: Iterable[Finding]) -> list[Finding]:
    seen, out = set(), []
    for f in findings:
        if f.finding_id not in seen:
            seen.add(f.finding_id)
            out.append(f)
    return out


# --------------------------------------------------------------------------- #
# From a run's own artifacts
# --------------------------------------------------------------------------- #
def _load(p: Path) -> Optional[dict]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _plan_callouts(out: Path) -> dict[str, list[str]]:
    plan = (_load(out / "plan.json") or {}).get("plan") or {}
    return {f["id"]: list(f.get("source_callouts") or []) for f in plan.get("features", []) if isinstance(f, dict) and "id" in f}


def findings_from_run(out: Path, run_id: str) -> list[Finding]:
    """Findings from ``<out>/ir_report.json`` (+ plan.json for the source callouts, + discrepancies.json)."""
    out = Path(out)
    rep = _load(out / "ir_report.json")
    if rep is None:
        return []
    part = str(rep.get("part") or out.name)
    callouts = _plan_callouts(out)
    in_plan = set(callouts)
    found: list[Finding] = []

    def add(fid: Optional[str], *, severity: str, category: str, title: str, expected: str, actual: str, consequence: str,
            action: str, evidence: str) -> None:
        ev = [f"ir_report:{evidence}"] + ([f"plan:{fid}"] if fid in in_plan else [])
        found.append(Finding.create(part=part, run_id=run_id, severity=severity, category=category, title=title,
                                    expected=expected, actual=actual, consequence=consequence,
                                    recommended_action=action, feature_ids=[fid] if fid else [],
                                    source_callouts=callouts.get(fid or "", []), evidence_ids=ev))

    def callout_text(fid: str) -> str:
        c = callouts.get(fid)
        return "; ".join(c) if c else f"feature {fid} as planned"

    for fid, reason in sorted((rep.get("cq_skipped") or {}).items()):
        add(fid, severity="error", category="feature_not_built", title=f"Feature {fid} was not built",
            expected=callout_text(fid), actual=f"skipped: {reason}",
            consequence="The model is missing this feature.",
            action=f"Review the callout for {fid} against the drawing, then add the feature or correct the plan.",
            evidence=f"cq_skipped:{fid}")
    for q in rep.get("questions") or []:
        m = _FID.search(str(q))
        fid = m.group(0) if m else None
        add(fid, severity="warning", category="feature_unresolved",
            title=f"Feature {fid} needs an engineer's answer" if fid else "A feature needs an engineer's answer",
            expected=callout_text(fid) if fid else "a fully specified feature", actual=str(q).split(":", 1)[-1].strip() or str(q),
            consequence="The feature was not built: the pipeline asks instead of guessing.",
            action="Answer the open question on the drawing, then re-run.", evidence=f"questions:{fid or 'item'}")
    for fid, status in sorted((rep.get("sw_features") or {}).items()):
        word = str(status).split(" ", 1)[0].lower()
        if word in ("built", "skipped"):
            continue
        add(fid, severity="error" if word in ("failed", "error") else "warning", category="feature_not_built",
            title=f"SolidWorks could not verify {fid}", expected=callout_text(fid), actual=str(status),
            consequence="The SolidWorks model may not contain this feature as drawn.",
            action=f"Review {fid} in the SolidWorks feature tree against the drawing.", evidence=f"sw_features:{fid}")
    if rep.get("sw_ok") is False:
        add(None, severity="error", category="volume_mismatch", title="SolidWorks geometry does not match the reference",
            expected="the SolidWorks volume and bounding box equal the verified reference solid",
            actual="the SolidWorks build failed its volume or bounding-box check",
            consequence="The delivered part may differ from the drawing.",
            action="Review the features flagged above, then rebuild.", evidence="sw_ok")
    if rep.get("gate1") in ("REJECT", "NO PLAN"):
        add(None, severity="error", category="plan_rejected", title="The build plan was rejected",
            expected="a plan that passes Gate 1", actual=str(rep.get("error") or rep.get("gate1")),
            consequence="No model was generated from this plan.", action="Review the plan errors, then re-run.", evidence="gate1")
    for sub in rep.get("hole_wizard_substitutions") or []:
        fid = sub.get("fid")
        add(fid, severity="warning", category="hole_wizard_substituted",
            title=f"{fid} is a plain cut, not a Hole Wizard hole" if fid else "A hole is a plain cut, not Hole Wizard",
            expected="a Hole Wizard feature for this hole (MTI practice)",
            actual=f"{sub.get('code')}: {sub.get('detail')}",
            consequence="The geometry matches but the feature tree has no Hole Wizard feature, so hole callouts and hardware data are absent.",
            action="Check the Hole Wizard / Toolbox setup on this SolidWorks install (error log E037), then rebuild.",
            evidence=f"hole_wizard_substitutions:{fid}")
    for item in rep.get("mti_review") or []:
        m = re.match(r"\[(\w+)\]\s*(.*)", str(item))
        code, msg = (m.group(1), m.group(2)) if m else ("mti", str(item))
        found.append(Finding.create(part=part, run_id=run_id, severity="info", category="practice_advisory",
                                    title=f"Modeling practice: {code}", expected="MTI modeling practice", actual=msg,
                                    consequence="Advisory only: this never blocks a part.",
                                    recommended_action="Review the feature order and grouping if it matters for this part.",
                                    evidence_ids=[f"ir_report:mti_review:{code}"]))
    legacy = _load(out / "discrepancies.json")
    if legacy and legacy.get("pieces"):
        found += migrate_legacy(legacy, part=part, run_id=run_id, plan_callouts=callouts)
    return dedupe(found)


# --------------------------------------------------------------------------- #
# Legacy discrepancies.json (read-only migration)
# --------------------------------------------------------------------------- #
def migrate_legacy(report: Mapping[str, Any], *, part: str, run_id: str,
                   plan_callouts: Optional[Mapping[str, list]] = None) -> list[Finding]:
    """Findings from an old ``discrepancies.json`` payload. The file itself is never modified."""
    plan_callouts = plan_callouts or {}
    out = []
    for i, p in enumerate(report.get("pieces") or [], 1):
        cause = str(p.get("cause", ""))
        ours = p.get("side") == "ours"
        fids = _FID.findall(cause)
        callouts = [c for fid in fids for c in plan_callouts.get(fid, [])]
        if "general note" in cause:
            callouts.append("ALL CHAMFERS" if ours else "ALL RADII")
        share = float(p.get("share_of_union_pct") or 0)
        out.append(Finding.create(
            part=part, run_id=run_id, severity="error" if share >= 1.0 else "warning",
            category="geometry_extra_material" if ours else "geometry_missing_material",
            title=f"Our model has extra material ({p.get('kind', 'region')})" if ours else f"Our model lacks material ({p.get('kind', 'region')})",
            expected="MTI's own model has no material here" if ours else "MTI's own model keeps material here",
            actual=f"{share:.3f}% of the union volume differs: {cause}" if cause else f"{share:.3f}% of the union volume differs",
            consequence="The part's volume differs from MTI's own model.",
            recommended_action="Review this region against the drawing and the cause noted.",
            feature_ids=fids, source_callouts=callouts, evidence_ids=[f"discrepancy:piece:{i}"]))
    return dedupe(out)
