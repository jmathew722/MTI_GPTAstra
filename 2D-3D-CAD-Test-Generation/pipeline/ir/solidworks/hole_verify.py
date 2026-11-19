"""Independent verification of a created native hole feature (Stage 4, Slice H).

A COM feature object coming back is not success. A feature is verified only when ALL of these pass and are recorded:

1. ``definition``   every applicable ``IWizardHoleFeatureData2`` property read back equals the normalized intent/catalog value
2. ``geometry``     removed volume equals the independent CadQuery reference within tolerance
3. ``rebuild``      no feature error after a forced rebuild
4. ``persistence``  after save / close / reopen / rebuild the same definition and volume are read back
5. ``callout``      the drawing Hole Callout round trip (NOT implemented: a drawing document and the Hole Callout API are required)

``VerificationReport.internal_status`` can say ``verified`` only when all five pass; because ``callout`` is not implemented it
cannot today, which is deliberate. Failures feed ``pipeline/hole_findings.from_verification`` so the automatic drawing markup
states the mismatch. This module is pure logic over values the live harness reads; the COM reads live in
``tools/run_hole_wizard_matrix.py``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional

PASS, FAIL, NOT_RUN, NOT_IMPLEMENTED = "pass", "fail", "not_run", "not_implemented"
REQUIRED = ("definition", "geometry", "rebuild", "persistence", "callout")


@dataclass
class Check:
    name: str
    status: str = NOT_RUN
    expected: Any = None
    actual: Any = None
    mismatches: list = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerificationReport:
    feature_id: str = ""
    checks: list = field(default_factory=list)

    def check(self, name: str) -> Optional[Check]:
        return next((c for c in self.checks if c.name == name), None)

    @property
    def failed(self) -> list:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def ok(self) -> bool:
        """Every REQUIRED check is present and passed."""
        return all((self.check(n) is not None and self.check(n).status == PASS) for n in REQUIRED)

    def internal_status(self) -> str:
        """``hole_capabilities.STATUSES`` vocabulary. ``verified`` needs all five checks to pass."""
        if self.failed:
            return "failed_verification"
        return "verified" if self.ok else "implemented_not_live_verified"

    def to_dict(self) -> dict:
        return {"feature_id": self.feature_id, "status": self.internal_status(), "checks": [c.to_dict() for c in self.checks]}


def verify_definition(expected: Mapping[str, Any], readback: Mapping[str, Any]) -> Check:
    """Definition readback vs. expected properties (same tolerances as the adapter's own readback)."""
    from pipeline.ir.solidworks.hole_adapter import compare
    mism = compare(dict(expected), dict(readback))
    return Check("definition", FAIL if mism else PASS, expected=dict(expected), actual=dict(readback), mismatches=mism)


def verify_geometry(removed: float, reference: float, rel: float = 1e-3, abs_tol: float = 1e-12) -> Check:
    ok = abs(removed - reference) <= rel * abs(reference) + abs_tol
    return Check("geometry", PASS if ok else FAIL, expected=reference, actual=removed,
                 detail=f"removed {removed:.6g} vs reference {reference:.6g} (relative tolerance {rel:g})")


def verify_rebuild(feature_errors: list) -> Check:
    return Check("rebuild", FAIL if feature_errors else PASS, expected=[], actual=list(feature_errors))


def verify_persistence(before: Mapping[str, Any], after: Optional[Mapping[str, Any]], vol_before: Optional[float] = None,
                       vol_after: Optional[float] = None, rel: float = 1e-6) -> Check:
    """Definition (and volume, when both are given) must be unchanged after save / close / reopen / rebuild."""
    if after is None:
        return Check("persistence", FAIL, expected=dict(before), actual=None, detail="the feature was not found after reopen")
    from pipeline.ir.solidworks.hole_adapter import compare
    mism = compare(dict(before), dict(after))
    vol_bad = vol_before is not None and vol_after is not None and abs(vol_before - vol_after) > rel * max(abs(vol_before), 1e-12)
    if vol_bad:
        mism = mism + [{"property": "volume", "wanted": vol_before, "got": vol_after}]
    return Check("persistence", FAIL if mism else PASS, expected=dict(before), actual=dict(after), mismatches=mism)


def callout_check() -> Check:
    return Check("callout", NOT_IMPLEMENTED, detail="the drawing Hole Callout round trip needs a drawing document and the Hole Callout API; not implemented")


def build_report(feature_id: str, *, expected: Mapping[str, Any], readback: Optional[Mapping[str, Any]], removed: Optional[float] = None,
                 reference: Optional[float] = None, feature_errors: Optional[list] = None, reopened: Optional[Mapping[str, Any]] = None,
                 reopened_requested: bool = False, vol_before: Optional[float] = None, vol_after: Optional[float] = None) -> VerificationReport:
    """Assemble the five checks from what the live run measured. A measurement that was not taken is ``not_run``, never a pass."""
    r = VerificationReport(feature_id)
    r.checks.append(verify_definition(expected, readback) if readback is not None else Check("definition", NOT_RUN))
    r.checks.append(verify_geometry(removed, reference) if removed is not None and reference is not None else Check("geometry", NOT_RUN))
    r.checks.append(verify_rebuild(feature_errors) if feature_errors is not None else Check("rebuild", NOT_RUN))
    if readback is not None and reopened_requested:
        r.checks.append(verify_persistence(readback, reopened, vol_before, vol_after))
    else:
        r.checks.append(Check("persistence", NOT_RUN))
    r.checks.append(callout_check())
    return r
