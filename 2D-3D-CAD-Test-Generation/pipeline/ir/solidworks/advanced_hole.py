"""Advanced Hole as its own capability domain (Stage 4, Slice I).

Advanced Hole (stacked NEAR-side and FAR-side elements, ``IFeatureManager.AdvancedHole2`` with
``IAdvancedHoleElementData``) is a different native feature from a Hole Wizard hole. This module keeps its intent (the
near and far element stacks, straight from the callout) and reports an EXPLICIT status. It never degrades to a basic hole:
``plan`` returns the retained intent and a structured unsupported result, and there is no code path to
``HoleWizardAdapter`` from here.

Status today: the API surface exists in the installed 2025 type library (``IFeatureManager.AdvancedHole2``) but no
creation code is implemented and no live feature has been created, so the status is ``UNSUPPORTED_WITH_REASON``.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional

DOMAIN = "advanced_hole"
CODE = "HW_ADVANCED_HOLE_NOT_IMPLEMENTED"
API_SURFACE = "IFeatureManager.AdvancedHole2(NearElementArray, FarElementArray, UseBaselineDimensions, IsCustomCallout, IsDepthUptoTip)"


@dataclass
class AdvancedElement:
    kind: str = "hole"                      # hole | counterbore | countersink (as the callout states)
    diameter: Optional[float] = None
    depth: Optional[float] = None
    cbore_diameter: Optional[float] = None
    cbore_depth: Optional[float] = None
    csink_diameter: Optional[float] = None
    csink_angle: Optional[float] = None
    source_text: str = ""


@dataclass
class AdvancedHoleIntent:
    units: str = "mm"
    near: list = field(default_factory=list)
    far: list = field(default_factory=list)
    source_text: str = ""
    unresolved: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _element(text: str) -> AdvancedElement:
    from pipeline.hole_callouts import parse
    pc = parse(text)
    e = AdvancedElement(source_text=text.strip(" ,;\n"))
    if pc.cbore_diameter:
        e.kind, e.cbore_diameter = "counterbore", pc.cbore_diameter.value
        e.cbore_depth = pc.cbore_depth.value if pc.cbore_depth else None
    if pc.csink_angle or pc.csink_diameter:
        e.kind = "countersink"
        e.csink_diameter = pc.csink_diameter.value if pc.csink_diameter else None
        e.csink_angle = pc.csink_angle.value if pc.csink_angle else None
    e.diameter = pc.diameter.value if pc.diameter else None
    e.depth = pc.depth.value if pc.depth else None
    return e


def from_callout_text(text: str, units: str = "mm") -> AdvancedHoleIntent:
    """Split ``NEAR SIDE ... FAR SIDE ...`` into the two element stacks. A side the text does not state stays empty."""
    i = AdvancedHoleIntent(units=units, source_text=text)
    parts = re.split(r"\b(NEAR\s+SIDE|FAR\s+SIDE)\b", text, flags=re.I)
    side = None
    for chunk in parts:
        if re.fullmatch(r"NEAR\s+SIDE", chunk.strip(), re.I):
            side = "near"
        elif re.fullmatch(r"FAR\s+SIDE", chunk.strip(), re.I):
            side = "far"
        elif side and chunk.strip(" ,;\n"):
            (i.near if side == "near" else i.far).append(_element(chunk))
    for name, stack in (("near", i.near), ("far", i.far)):
        for k, e in enumerate(stack):
            if e.diameter is None and e.cbore_diameter is None and e.csink_diameter is None:
                i.unresolved.append(f"{name}[{k}].diameter")
    if not i.near and not i.far:
        i.unresolved.append("near_or_far_elements")
    return i


def status() -> dict:
    return {"domain": DOMAIN, "status": "UNSUPPORTED_WITH_REASON", "code": CODE, "api_surface": API_SURFACE,
            "reason": "Advanced Hole is a separate native feature; its element stacks are parsed and kept, but no creation adapter is "
                      "implemented and no live feature has been created or verified.",
            "substitute_allowed": False}


def plan(intent: AdvancedHoleIntent) -> dict:
    """Structured result for an Advanced Hole request: the retained intent plus the unsupported status. Never a basic hole."""
    return {**status(), "intent": intent.to_dict(), "feature_created": False}
