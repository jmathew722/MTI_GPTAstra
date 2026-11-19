"""Hole Series as its own capability domain (Stage 4, Slice I).

Hole Series is an ASSEMBLY feature (a fastener hole through a stack of components), not a part-level Hole Wizard hole. This
module keeps its intent and reports a structured status; it never degrades to a basic hole.

The status is ``BLOCKED_BY_CONFIRMED_SOLIDWORKS_2025_LIMITATION`` because the installed 2025 type library offers no creation
entry point: ``swFeatureNameID_e`` has no Hole Series member (so ``CreateDefinition`` cannot make one), and no creation method
named for Hole Series exists on ISldWorks, IModelDoc2, IModelDocExtension, IAssemblyDoc or IFeatureManager. ``IHoleSeriesFeatureData(2)``
exists to READ an existing feature. ``tests/test_advanced_hole_and_series.py`` re-checks this claim against the installed library
whenever it is present, so the status cannot silently go stale.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

DOMAIN = "hole_series"
CODE = "HW_HOLE_SERIES_NOT_CREATABLE"
EVIDENCE = {"source": "tools/read_sw_typelib.py against the installed SOLIDWORKS 2025 type libraries",
            "checked": ["swFeatureNameID_e (no Hole Series member)", "ISldWorks", "IModelDoc2", "IModelDocExtension", "IAssemblyDoc",
                        "IFeatureManager (no method named for Hole Series)"],
            "read_only_object": "IHoleSeriesFeatureData2"}


@dataclass
class HoleSeriesIntent:
    standard: Optional[str] = None
    fastener_type: Optional[str] = None
    size_designation: Optional[str] = None
    start_face: Optional[str] = None
    end_face: Optional[str] = None
    components: list = field(default_factory=list)
    centers: list = field(default_factory=list)
    source_text: str = ""
    unresolved: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def status() -> dict:
    return {"domain": DOMAIN, "status": "BLOCKED_BY_CONFIRMED_SOLIDWORKS_2025_LIMITATION", "code": CODE, "evidence": EVIDENCE,
            "reason": "the installed SOLIDWORKS 2025 API has no entry point that creates a Hole Series feature (only a reader object)",
            "substitute_allowed": False}


def plan(intent: HoleSeriesIntent) -> dict:
    return {**status(), "intent": intent.to_dict(), "feature_created": False}
