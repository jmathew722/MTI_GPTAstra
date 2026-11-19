"""The SOLIDWORKS 2025 external status vocabulary and its mapping from the internal matrix statuses (Stage 4, Slice E/K).

External states (the only ones a report may use):

* ``SUPPORTED_AND_LIVE_VERIFIED``                 live creation + definition readback + geometry + drawing callout + save/reopen/rebuild.
* ``SUPPORTED_BY_ADAPTER_NOT_INSTALLED``          an adapter and selection/resolution/reference exist and pass fake-COM tests, but the
                                                  installed 2025 catalog could not be used (preflight failed, catalog not enumerable, or the
                                                  standard/fastener is not installed). It is NOT a verification claim.
* ``UNSUPPORTED_WITH_REASON``                     recognized but no adapter (legacy types, slot families, ...), with the reason.
* ``NOT_APPLICABLE_TO_INSTALLED_CATALOG``         the catalog was enumerated and genuinely lacks the standard/fastener/size.
* ``BLOCKED_BY_CONFIRMED_SOLIDWORKS_2025_LIMITATION``  the installed 2025 API provably cannot do it (evidence required in the row).

Mapping from the internal statuses (``hole_capabilities.STATUSES``):

    verified                         -> SUPPORTED_AND_LIVE_VERIFIED
    implemented_not_live_verified    -> SUPPORTED_BY_ADAPTER_NOT_INSTALLED   (with ``environment_reason`` = the preflight/live code)
    unsupported_by_installed_catalog -> NOT_APPLICABLE_TO_INSTALLED_CATALOG
    not_implemented / ambiguous_source / failed_verification -> UNSUPPORTED_WITH_REASON  (failed_verification keeps its detail)

An environment problem (wrong Hole Wizard database configured, modal dialog, catalog unreadable) is a configuration state,
never a "confirmed SOLIDWORKS limitation": it is reported through ``environment_reason`` and the preflight record.
"""
from __future__ import annotations

from typing import Optional

STATUSES_2025 = ("SUPPORTED_AND_LIVE_VERIFIED", "SUPPORTED_BY_ADAPTER_NOT_INSTALLED", "UNSUPPORTED_WITH_REASON",
                 "NOT_APPLICABLE_TO_INSTALLED_CATALOG", "BLOCKED_BY_CONFIRMED_SOLIDWORKS_2025_LIMITATION")

_MAP = {"verified": "SUPPORTED_AND_LIVE_VERIFIED",
        "implemented_not_live_verified": "SUPPORTED_BY_ADAPTER_NOT_INSTALLED",
        "unsupported_by_installed_catalog": "NOT_APPLICABLE_TO_INSTALLED_CATALOG",
        "not_implemented": "UNSUPPORTED_WITH_REASON", "ambiguous_source": "UNSUPPORTED_WITH_REASON",
        "failed_verification": "UNSUPPORTED_WITH_REASON"}


def map_status(internal: str) -> str:
    """Fail closed: an internal status this table does not know is UNSUPPORTED_WITH_REASON, never a support claim."""
    return _MAP.get(internal, "UNSUPPORTED_WITH_REASON")


def reason_for(row: dict, preflight: Optional[dict] = None) -> str:
    """One honest sentence for a matrix row's external status."""
    ext = map_status(row.get("status", ""))
    if row.get("legacy"):
        return "legacy hole type: created only under an explicit compatibility policy, which has no adapter"
    if ext == "SUPPORTED_AND_LIVE_VERIFIED":
        return "live creation, readback, geometry, drawing callout and save/reopen/rebuild all passed"
    if ext == "SUPPORTED_BY_ADAPTER_NOT_INSTALLED":
        code = (preflight or {}).get("code")
        env = f"; live run blocked by the environment ({code})" if code else "; no live run recorded"
        return "adapter, selection, catalog resolution and reference geometry exist and pass fake-COM tests" + env
    if row.get("family", "").endswith("slot") or row.get("family") == "slot":
        return row.get("note") or "slot families: no fastener type is documented for slots; creation is not implemented"
    return row.get("note") or row.get("reference_detail") or "recognized, no adapter"
