"""Hole Wizard failures as structured engineering findings (Stage 4, Slice J).

Everything that can go wrong between a hole callout and a verified native feature becomes one plain record that
``pipeline/findings.py`` turns into an ``EngineeringFinding`` and that the automatic markup places on the drawing:

* ``from_intent``        parse ambiguity / unresolved fields / conflicts of a ``HoleIntentV2`` ("Thread depth not specified")
* ``from_preflight``     the SOLIDWORKS 2025 environment gate ("Hole Wizard database 29.01 is incompatible with expected 28.00")
* ``from_catalog``       a catalog resolution code (``HW_CATALOG_*``, ``HW_STANDARD_UNKNOWN``, ``HW_SIZE_UNRESOLVED``, ...)
* ``from_outcome``       a native creation failure (``HoleOutcome``: ``HW_CREATE_NULL``, ``HW_INIT_REFUSED``, ...)
* ``from_verification``  a field/geometry/rebuild/persistence mismatch from ``hole_verify``
* ``from_substitution``  a Hole Wizard hole that became a plain cut (never reported as support)

A record is ``{code, severity, title, expected, actual, consequence, recommended_action, source_callouts, feature_ids}``: the
source callouts are what the locator searches for on the drawing, so no human ever positions the box. The text states the
problem and the manual action; it never claims the action was taken and never invents a SolidWorks command it cannot back.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

MAX_CALLOUTS = 12


def _u(units: str) -> str:
    return "in" if units == "inch" else "mm"


def fmt(v: Any, units: str = "inch") -> str:
    """'.123 in' for a number, the text itself otherwise. Engineering style: no leading zero for inches, trailing zeros trimmed."""
    if v is None:
        return "not specified"
    if isinstance(v, (int, float)):
        t = f"{v:.4f}".rstrip("0").rstrip(".")
        if units == "inch" and t.startswith("0."):
            t = t[1:]
        return f"{t} {_u(units)}"
    return str(v)


def record(code: str, title: str, *, expected: str, actual: str, consequence: str, action: str, severity: str = "error",
           callouts: Optional[Iterable[str]] = None, feature_ids: Optional[Iterable[str]] = None) -> dict:
    seen, cs = set(), []
    for c in callouts or []:
        c = " ".join(str(c).split())
        if c and c not in seen:
            seen.add(c)
            cs.append(c)
    return {"code": code, "severity": severity, "title": title, "expected": expected, "actual": actual, "consequence": consequence,
            "recommended_action": action, "source_callouts": cs[:MAX_CALLOUTS], "feature_ids": sorted(set(feature_ids or []))}


_UNRESOLVED_TITLES = {
    "thread.thread_depth": ("Thread depth not specified", "a stated thread depth"),
    "thread.class": ("Thread class not specified", "a stated thread class (for example 2B)"),
    "thread.tap_drill_depth": ("Tap drill depth not specified", "a stated tap drill depth"),
    "end_condition.main": ("End condition not specified", "THRU or a stated depth"),
    "end_condition.main_depth": ("Blind depth not specified", "a stated depth"),
    "standard": ("Hole Wizard standard not confirmed", "a standard confirmed against the installed catalog"),
    "quantity": ("Quantity not specified", "a stated quantity"),
    "geometry.main_diameter": ("Hole diameter not specified", "a stated diameter"),
    "geometry.counterbore_diameter": ("Counterbore diameter not specified", "a stated counterbore diameter"),
    "geometry.counterbore_depth": ("Counterbore depth not specified", "a stated counterbore depth"),
    "geometry.countersink_angle": ("Countersink angle not specified", "a stated countersink angle"),
    "slot_length_scheme": ("Slot length scheme not specified", "overall or center-to-center"),
}


def from_intent(intent: Mapping[str, Any]) -> list:
    """One record per unresolved field and per conflict of a ``HoleIntentV2`` dict. Never fills a value in."""
    units = intent.get("units", "inch")
    callouts = [" ".join(intent.get("source", {}).get("raw_lines") or [])]
    fid = [intent["feature_id"]] if intent.get("feature_id") else []
    out = []
    for f in intent.get("unresolved_fields") or []:
        if f.startswith("ambiguity:"):
            name = f.split(":", 1)[1]
            out.append(record("HW_CALLOUT_AMBIGUOUS", f"Callout is ambiguous: {name.replace('_', ' ')}", expected="one unambiguous reading of the callout",
                              actual=name.replace("_", " "), consequence="The pipeline asks instead of guessing, so this feature is not built as a native Hole Wizard feature.",
                              action="Clarify the callout on the drawing, or state the intended value, then re-run.", severity="warning",
                              callouts=callouts, feature_ids=fid))
            continue
        title, want = _UNRESOLVED_TITLES.get(f, (f"{f} not specified", f"a stated {f}"))
        out.append(record("HW_REQUIRED_FIELD_MISSING", title, expected=want, actual="not specified on the drawing",
                          consequence="The value is never invented, so the feature stays needs-review and is not created natively.",
                          action=f"Confirm {want.replace('a stated ', '')} with the design engineer and add it to the drawing or the plan.",
                          severity="warning", callouts=callouts, feature_ids=fid))
    for c in intent.get("conflicts") or []:
        out.append(record("HW_CALLOUT_AMBIGUOUS", f"Conflicting values in the callout ({c['code'].replace('_', ' ')})", expected="consistent values",
                          actual=c["detail"], consequence="Both values are kept; neither is chosen for the build.",
                          action="Resolve the contradiction on the drawing, then re-run.", callouts=callouts, feature_ids=fid))
    for t in intent.get("tolerances") or []:
        label = _PROP_NAMES.get(str(t.get("field", "")).split(".")[-1].title().replace("_", ""), str(t.get("field", "")).split(".")[-1].replace("_", " "))
        band = (f"±{fmt(t['plus'], units)}" if t.get("kind") == "bilateral" else f"+{fmt(t['plus'], units)} / -{fmt(t['minus'], units)}")
        out.append(record("HW_TOLERANCE_NOT_APPLIED", f"Tolerance on {label} ({band}) is a manufacturing requirement, not modeled",
                          expected=f"{label} {band}", actual="the native Hole Wizard definition has no verified tolerance storage; nominal value modeled",
                          consequence="The tolerance is retained on the intent but is not in the SOLIDWORKS feature.",
                          action="Add the tolerance to the drawing annotation or model note if it must travel with the part.", severity="info",
                          callouts=callouts, feature_ids=fid))
    if intent.get("creation_method") == "advanced_hole":
        out.append(record("HW_ADVANCED_HOLE_NOT_IMPLEMENTED", "Advanced Hole callout is not created natively",
                          expected="an Advanced Hole feature with near and far element stacks",
                          actual="Advanced Hole creation is not implemented; no basic hole was substituted",
                          consequence="The stacked near/far hole is missing from the model.",
                          action="Model this hole with SOLIDWORKS Advanced Hole manually.", callouts=callouts, feature_ids=fid))
    return out


def from_preflight(result: Mapping[str, Any], callouts: Iterable[str] = (), feature_ids: Iterable[str] = ()) -> list:
    """The environment gate. One record (all callouts attached): the problem is the configuration, not any one hole."""
    if result.get("status") == "ready":
        return []
    code = result.get("code") or "SW_ENVIRONMENT"
    have, want = result.get("database_version"), result.get("database_expected_version") or "28.x"
    if code == "HW_DATABASE_VERSION_MISMATCH":
        title = f"Hole Wizard database {have} is incompatible with expected {want}"
        actual = f"configured Hole Wizard database {have}"
        expected = f"Hole Wizard database {want} (SOLIDWORKS 2025)"
    elif code == "SW_VERSION_UNSUPPORTED":
        title = "SOLIDWORKS 2025 is required for native Hole Wizard features"
        expected, actual = "SOLIDWORKS 2025 (revision 33.x)", f"revision {result.get('application_revision') or 'unknown'}"
    else:
        title = result.get("message") or code
        expected, actual = "a ready SOLIDWORKS 2025 Hole Wizard environment", result.get("message") or code
    return [record(code, title, expected=expected, actual=actual,
                   consequence="No native Hole Wizard feature can be created or verified, so these holes were not built as Hole Wizard features.",
                   action=result.get("user_action") or "Point SOLIDWORKS 2025 to the company-approved 2025 Hole Wizard/Toolbox folder, then re-run.",
                   callouts=callouts, feature_ids=feature_ids)]


def from_catalog(code: str, detail: str, intent: Mapping[str, Any]) -> list:
    callouts = [" ".join(intent.get("source", {}).get("raw_lines") or [])]
    fid = [intent["feature_id"]] if intent.get("feature_id") else []
    designation = intent.get("size_designation") or "this size"
    titles = {"HW_CATALOG_MISSING": f"Installed catalog lacks the standard for {designation}",
              "HW_CATALOG_NO_MATCH": f"No installed catalog row matches {designation}",
              "HW_CATALOG_AMBIGUOUS": f"Several installed catalog rows match {designation}",
              "HW_STANDARD_UNKNOWN": "Hole Wizard standard is not installed",
              "HW_SIZE_UNRESOLVED": f"Hole Wizard size could not be resolved for {designation}",
              "HW_FASTENER_UNMAPPED": "No fastener type is known for this hole family",
              "HW_CATALOG_ENUMERATION_UNAVAILABLE": "The installed Hole Wizard catalog could not be enumerated",
              "HW_CATALOG_LOOKUP_FAILED": "The installed Hole Wizard catalog could not be read"}
    return [record(code, titles.get(code, f"Catalog resolution failed ({code})"), expected="one installed standard / fastener / size row",
                   actual=detail or code, consequence="No native feature was created: nothing is substituted for a missing catalog row.",
                   action="Check the standard and size against the installed Hole Wizard catalog, or choose the installed equivalent explicitly.",
                   callouts=callouts, feature_ids=fid)]


def from_outcome(outcome: Any, intent: Mapping[str, Any]) -> list:
    """A native creation failure (``hole_adapter.HoleOutcome``). No record when it succeeded."""
    if getattr(outcome, "ok", False):
        return []
    callouts = [" ".join(intent.get("source", {}).get("raw_lines") or [])]
    fid = [intent["feature_id"]] if intent.get("feature_id") else []
    what = intent.get("size_designation") or (intent.get("general_family") or "hole").replace("_", " ")
    if outcome.code == "HW_READBACK_MISMATCH":
        return from_verification({"checks": [{"name": "definition", "status": "fail", "mismatches": list(outcome.mismatches)}]}, intent)
    return [record(outcome.code or "HW_NATIVE_CREATE_FAILED", f"Expected native {what} feature; feature creation failed",
                   expected=f"a native Hole Wizard feature ({intent.get('specific_type') or intent.get('general_family')})",
                   actual=f"{outcome.code}: {outcome.detail}"[:300],
                   consequence="The feature was not created natively and nothing was substituted for it.",
                   action="Check the Hole Wizard setup in SOLIDWORKS 2025 and the callout, then re-run.", callouts=callouts, feature_ids=fid)]


_PROP_NAMES = {"CounterBoreDiameter": "Counterbore diameter", "CounterBoreDepth": "Counterbore depth", "Diameter": "Hole diameter",
               "Depth": "Hole depth", "ThreadDepth": "Thread depth", "TapDrillDepth": "Tap drill depth", "TapDrillDiameter": "Tap drill diameter",
               "CounterSinkDiameter": "Countersink diameter", "CounterSinkAngle": "Countersink angle", "ThreadClass": "Thread class",
               "Type": "Hole type", "Length": "Slot length"}
_ANGLE = ("CounterSinkAngle", "DrillAngle", "ThreadAngle")


def _read(prop: str, v: Any, units: str) -> str:
    """Property values arrive in meters/radians; show them in the drawing's units."""
    if isinstance(v, (int, float)) and prop not in ("Type",):
        import math
        if prop.endswith("Angle"):
            return f"{math.degrees(v):g} deg"
        return fmt(v / (0.0254 if units == "inch" else 0.001), units)
    return str(v)


def from_verification(report: Mapping[str, Any], intent: Mapping[str, Any]) -> list:
    """Records for every failed check of a ``hole_verify`` report (definition readback, geometry, rebuild, save/reopen)."""
    units = intent.get("units", "inch")
    callouts = [" ".join(intent.get("source", {}).get("raw_lines") or [])]
    fid = [intent["feature_id"]] if intent.get("feature_id") else []
    out = []
    for chk in report.get("checks", []):
        if chk.get("status") != "fail":
            continue
        name = chk["name"]
        if name == "definition":
            for m in chk.get("mismatches", []):
                prop = m.get("property", "")
                label = _PROP_NAMES.get(prop, prop)
                exp = _read(prop, m.get("wanted", m.get("expected")), units)
                got = _read(prop, m.get("got", m.get("actual")), units)
                out.append(record("HW_READBACK_MISMATCH", f"{label} expected {exp}; read back {got}", expected=exp, actual=got,
                                  consequence="The native feature does not match the drawing; it was removed rather than kept wrong.",
                                  action=f"Edit the Hole Wizard feature and set {label.lower()} to {exp}.", callouts=callouts, feature_ids=fid))
        elif name == "geometry":
            out.append(record("HW_GEOMETRY_MISMATCH", "Removed volume does not match the reference", expected=str(chk.get("expected")),
                              actual=str(chk.get("actual")), consequence="The feature's geometry differs from what the callout describes.",
                              action="Review the hole against the drawing in the feature tree.", callouts=callouts, feature_ids=fid))
        elif name == "rebuild":
            out.append(record("HW_REBUILD_FAILED", "Feature errors after rebuild", expected="no feature errors", actual=str(chk.get("actual")),
                              consequence="The model does not rebuild cleanly with this feature.", action="Open the feature in SOLIDWORKS and fix the reported error.",
                              callouts=callouts, feature_ids=fid))
        elif name == "persistence":
            out.append(record("HW_SAVE_REOPEN_FAILED", "Feature changed after save and reopen", expected=str(chk.get("expected")),
                              actual=str(chk.get("actual")), consequence="The delivered file does not keep this feature as built.",
                              action="Review the saved part; rebuild the feature.", callouts=callouts, feature_ids=fid))
    return out


def from_substitution(sub: Mapping[str, Any], callouts: Iterable[str] = ()) -> list:
    fid = sub.get("fid")
    return [record(sub.get("code") or "HW_NATIVE_CREATE_FAILED",
                   f"{fid} is a plain cut, not a Hole Wizard hole" if fid else "A hole is a plain cut, not Hole Wizard",
                   expected="a native Hole Wizard feature", actual=f"{sub.get('code')}: {sub.get('detail')}"[:300],
                   consequence="The geometry matches but the feature tree has no Hole Wizard feature, so hole callouts and hardware data are absent.",
                   action="Fix the Hole Wizard environment (see the preflight finding), then rebuild.", severity="warning",
                   callouts=callouts, feature_ids=[fid] if fid else [])]


def to_findings(records: Iterable[Mapping[str, Any]], *, part: str, run_id: str) -> list:
    """Records -> ``pipeline.findings.Finding`` objects (evidence id ``hole_wizard:<code>``)."""
    from pipeline.findings import Finding
    out = []
    for n, r in enumerate(records):
        out.append(Finding.create(
            part=part, run_id=run_id, severity=r.get("severity", "error"), category=_category(r["code"]), title=r["title"],
            expected=r.get("expected", ""), actual=r.get("actual", ""), consequence=r.get("consequence", ""),
            recommended_action=r.get("recommended_action", ""), feature_ids=r.get("feature_ids"),
            source_callouts=r.get("source_callouts"), evidence_ids=[f"hole_wizard:{r['code']}"]))
    return out


def _category(code: str) -> str:
    if code in ("HW_READBACK_MISMATCH", "HW_GEOMETRY_MISMATCH"):
        return "hole_readback_mismatch"
    if code in ("HW_CALLOUT_AMBIGUOUS", "HW_REQUIRED_FIELD_MISSING", "HW_TOLERANCE_NOT_APPLIED"):
        return "hole_callout_unresolved"
    if code in ("SW_VERSION_UNSUPPORTED", "HW_DATABASE_VERSION_MISMATCH", "HW_DATABASE_MISSING", "SW_MODAL_DIALOG_BLOCKED",
                "SW_JOB_TIMEOUT", "HW_CATALOG_LOOKUP_FAILED"):
        return "hole_wizard_environment"
    return "hole_wizard_failure"


SIDECAR = "hole_wizard_findings.json"


def records_for_build(report: Any, plan: Any) -> list:
    """Records for one SolidWorks build (``SwBuildReport`` + ``BuildPlan``): the environment problem once (all affected callouts
    attached), and every other Hole Wizard -> plain-cut substitution individually."""
    callouts = {f.id: list(getattr(f, "source_callouts", None) or []) for f in getattr(plan, "features", [])}
    subs = list(getattr(report, "hole_wizard_substitutions", []) or [])
    pre = getattr(report, "hole_wizard_preflight", None) or {}
    out: list = []
    env_codes = set()
    if pre and pre.get("status") == "failed":
        env_codes = {pre.get("code")}
        affected = [s["fid"] for s in subs if s.get("code") == pre.get("code")]
        out += from_preflight(pre, [c for fid in affected for c in callouts.get(fid, [])], affected)
    for s in subs:
        if s.get("code") in env_codes:
            continue
        out += from_substitution(s, callouts.get(s.get("fid"), []))
    return out


def write_sidecar(out_dir, records: list) -> Optional[str]:
    """Write ``hole_wizard_findings.json`` beside the run's artifacts (only when there is something to say). Returns its path."""
    import json
    from pathlib import Path
    p = Path(out_dir) / SIDECAR
    if not records:
        if p.exists():
            p.unlink()                       # never leave a stale sidecar from an earlier attempt
        return None
    p.write_text(json.dumps({"schema_version": 1, "records": records}, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(p)
