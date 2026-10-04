"""Planner: a vision LLM writes a Feature-IR BuildPlan from DrawingData + the drawing images.

IR v2 Task 7 (spec: docs/superpowers/specs/2026-09-28-feature-ir-v2-design.md, Planner).

* One tool, ``submit_build_plan``, whose input is a :class:`pipeline.ir.model.BuildPlan`.
* **Model: GPT-6 Astra (OpenAI) only** (project decision 2026-10-04: no model
  benchmark). It goes through :mod:`pipeline.openai_adapter` (Responses API, non-strict
  function tool), the same path the extractor uses. The ``Planner`` base class keeps the
  repair loop provider-neutral if another backend is ever needed.
* **Deterministic repair loop (Gate-1 lite):** a plan that fails Pydantic validation, or
  whose ``BuildPlan.check`` has structural errors (bad expression, dangling ref,
  ungrounded literal, duplicate id), goes back with the findings, up to
  ``MAX_REPAIRS`` times. ``unresolved`` features are allowed: they are the honest answer
  for things a drawing doesn't settle.
* Every completion goes through the $20 budget guard and the token ledger (role "planner").
Model IDs come from ``config/models.json``; nothing is hard-coded at a call site.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from pipeline import budget
from pipeline.ir.model import BuildPlan, Finding
from pipeline.schema import DrawingData
from pipeline.token_tracker import current_scope, record_completion, scope
from utils.logger import get_logger

log = get_logger()

CONFIG = Path(__file__).resolve().parent.parent / "config" / "models.json"
TOOL_NAME = "submit_build_plan"
MAX_REPAIRS = 2
STRUCTURAL = {"bad_expr", "dangling_ref", "ungrounded_literal", "duplicate_id"}
GOLDEN_EXAMPLE = Path(__file__).resolve().parent.parent / "tests" / "golden" / "ir" / "demo_plate.json"


def pinned(provider: str) -> tuple[str, dict]:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    return cfg["planner"][provider], cfg.get("planner_settings", {}).get(provider, {})


SYSTEM_PROMPT = """\
You are a senior manufacturing engineer turning a 2D engineering drawing into a typed CAD \
build plan (Feature IR v2). You get the drawing images (the FULL sheet first, then view \
crops) and a prior machine extraction (DrawingData) whose dimension IDs (D###) you must use. \
Deterministic code builds your plan in CadQuery and SolidWorks, so geometry must be exact.

Submit the plan by calling the submit_build_plan tool exactly once.

FRAME (one per part, drawing units):
- Turned/round parts: origin_kind "axis_end". The part axis is +Z, z = 0 at one end face.
- Prismatic parts: origin_kind "corner". The envelope min corner is at the origin, built toward +X, +Y, +Z.
- Sketch coordinates (u, v) are GLOBAL in-plane coordinates: front/±Z faces -> (x, y),
  top/±Y -> (x, z), right/±X -> (y, z). Never use a local frame.

REFS (strings): plane(front|top|right); face(F###,±X|±Y|±Z) or face(F###,±Z,<z expr>) to pick one of
several parallel faces of a stepped body; wall(F###) or wall(F###,<radius expr>) for curved faces;
axis(part) or axis(F###). Edge queries: edge_between(<ref>,<ref>).

DIRECTION: from a face, op "add" goes outward and op "cut" goes into the material. From a base
plane, both go +normal; "offset" moves the start plane. Holes start at "on" and go into the
material; depth "thru" cuts through everything.

FEATURES: prism (rect/circle/slot/polygon profile), revolve (outer/inner (z, r) stations; a
turned part's necks, grooves and shoulders are steps in the stations, not separate cuts), hole
(thru/blind/cbore/tapped; threads are cosmetic: give the tap drill as d), pattern
(linear/grid/circular about axis(part)), edge_op (fillet/chamfer on edge queries).

NUMBERS ARE EXPRESSIONS over the D-IDs: "D003", "D001 / 2", "(D001 - D002) / 2". 1 and 2 are
free only as scale factors. Any other literal, or any added/subtracted constant, needs a
"justification" on that feature that cites its source: a value printed on the drawing but missing
from the extraction ("1.000 DIA. read from section A-A"), or a named standard ("drill .281 for a
.250 SHCS, standard counterbore chart"). Counts ("4X") and angles may be literal.

THE EXTRACTION CAN BE WRONG. Trust the drawing: re-read every value against the images, prefer the
full sheet over crops (crops can hide callouts), and use section views to tell bores from solid.

CUTS MUST OVERSHOOT. A cut meant to break through a surface must extend PAST it, never end exactly
on it: SolidWorks rejects zero-thickness (coincident or tangent) geometry. Size the profile or depth
with a larger existing dimension (e.g. reach the OD with "D001", not "D001 / 2"; run a full-length
keyway from "-D004" to "D002 + D004"), or use depth "thru". Only the overshoot leaves the part, so the
geometry is unchanged. A cut that must STOP inside the material (a blind slot) uses the exact dimension.

GROUNDED IS NOT THE SAME AS PRINTED. These are PLANNED (status "planned") with a justification,
never "unresolved"; the report flags them for review:
- Sizes a named standard fixes: the clearance drill and counterbore for a named socket-head cap
  screw (use the SHCS TABLE below), or the tap drill for a named thread (e.g. 5/16 for 3/8-16 UNC).
- Symmetry the drawing shows: holes drawn mirror-image about a centerline with one side
  dimensioned (e.g. "2-HLS" at +-2.75, or a 3-hole pattern given as 2.875 / 2.490 / 1.438) are
  placed symmetrically.
- Extents the views show: a keyway or slot runs exactly as far as its lines run in the views.
- Blind drilled holes: a printed drill depth is to the FULL DIAMETER (standard drafting
  convention; ASME Y14.5). Model a flat-bottom blind hole of that depth; the drill point is
  cosmetic. Plan it; the drill-point angle is not a question for a human.
Use "unresolved" only when the drawing gives NO basis.

NEVER GUESS. If the drawing does not settle something (an edge break given only as "TYP" without
clear edges, a radius given only as a MAX, "C/R" chamfer-or-radius, an unreadable callout), add the
feature with status "unresolved" and a one-line rationale stating the question for a human.
Use "unsupported" for features outside the IR (threads beyond cosmetic, lofts, ...).
Give every feature a short rationale and the verbatim callout text in source_callouts.
"""


def _tool() -> dict:
    return {"name": TOOL_NAME,
            "description": "Submit the complete Feature IR v2 build plan for this drawing.",
            "input_schema": BuildPlan.model_json_schema()}


def drawing_payload(m: DrawingData) -> str:
    """Compact DrawingData for the prompt: what the planner needs to cite D-IDs."""
    dims = [{k: v for k, v in d.model_dump(mode="json").items()
             if k in ("id", "type", "value", "unit", "applies_to", "feature_ref", "view", "is_reference",
                      "tolerance_plus", "tolerance_minus", "notes", "value_unclear")}
            for d in m.dimensions]
    return json.dumps({
        "part": m.part_number or m.part_name, "units": m.units.value,
        "general_tolerance": m.general_tolerance, "dimensions": dims,
        "hole_callouts": [h.model_dump(mode="json") for h in m.hole_callouts],
        "features_read": [{"id": f.id, "type": f.type.value, "description": f.description} for f in m.features],
        "warnings": m.warnings,
    }, separators=(",", ":"))


@dataclass
class PlanResult:
    plan: Optional[BuildPlan]
    findings: list[Finding] = field(default_factory=list)
    attempts: int = 0
    error: str = ""
    model: str = ""
    provider: str = ""


class Planner:
    provider = ""

    def __init__(self, model: Optional[str] = None, client: Any = None):
        pm, settings = pinned(self.provider)
        self.model = model or pm
        self.settings = settings
        self._client = client

    # provider hook: one completion -> Anthropic-shaped response (content blocks, usage, stop_reason)
    def _complete(self, system: str, messages: list[dict]) -> Any:
        raise NotImplementedError

    def plan(self, drawing: DrawingData, images: list[tuple[str, str]], dims: dict[str, float],
             reference_ids: frozenset[str] = frozenset(), history: Optional[list[str]] = None) -> PlanResult:
        """images: [(label, base64 png)], full sheet first."""
        example = json.loads(GOLDEN_EXAMPLE.read_text(encoding="utf-8"))
        content: list[dict] = []
        for label, b64 in images:
            content.append({"type": "text", "text": f"=== {label} ==="})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}})
        from pipeline.fasteners import SHCS_INCH, SOURCE
        shcs = "SHCS TABLE (" + SOURCE + "): nominal -> (drill, cbore dia, cbore depth): " + "; ".join(
            f"{k:g} -> {v}" for k, v in SHCS_INCH.items())
        content.append({"type": "text", "text":
                        shcs + "\n\n"
                        "EXAMPLE of a correct plan for a different, synthetic part (format reference only):\n"
                        + json.dumps({"dims": example["dims"], "plan": example["plan"]}, separators=(",", ":"))
                        + "\n\nDrawingData for THIS part (cite these D-IDs):\n" + drawing_payload(drawing)
                        + ("\n\nPrevious attempt findings to fix:\n" + "\n".join(history) if history else "")
                        + f"\n\nCall {TOOL_NAME} with the complete plan."})
        messages: list[dict] = [{"role": "user", "content": content}]
        res = PlanResult(None, model=self.model, provider=self.provider)
        for attempt in range(1, MAX_REPAIRS + 2):
            res.attempts = attempt
            with scope(role="planner", attempt=attempt):
                response = self._complete(SYSTEM_PROMPT, messages)
            if getattr(response, "stop_reason", None) == "refusal":
                res.error = f"refusal: {getattr(response, 'stop_details', None)}"
                return res
            call = next((b for b in response.content if getattr(b, "type", None) == "tool_use"
                         and getattr(b, "name", "") == TOOL_NAME), None)
            if call is None:
                feedback = f"You did not call {TOOL_NAME}. Call it now with the complete plan."
                messages += [{"role": "assistant", "content": response.content},
                             {"role": "user", "content": [{"type": "text", "text": feedback}]}]
                res.error = "no tool call"
                continue
            try:
                plan = BuildPlan.model_validate(call.input)
            except ValidationError as e:
                feedback = f"The plan failed schema validation:\n{e}\nFix it and call {TOOL_NAME} again."
                res.error = "schema"
            else:
                res.plan = plan
                res.findings = plan.check(dims, reference_ids)
                bad = [f for f in res.findings if f.severity == "error" and f.code in STRUCTURAL]
                if not bad:
                    res.error = ""
                    return res
                feedback = ("Deterministic Gate-1 checks rejected the plan. Fix ONLY these, keep everything else:\n"
                            + "\n".join(f"- [{f.code}] {f.feature}: {f.message}" for f in bad)
                            + f"\nCall {TOOL_NAME} again with the full corrected plan.")
                res.error = "gate1"
            messages += [{"role": "assistant", "content": response.content},
                         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": call.id,
                                                       "content": feedback, "is_error": True}]}]
        return res


class OpenAIPlanner(Planner):
    provider = "openai"

    def _complete(self, system, messages):
        from pipeline.openai_adapter import OpenAIAnthropicShim

        key = os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_KEY")
        if self._client is None and not key:
            raise EnvironmentError("OPENAI_API_KEY not found.")
        client = self._client or OpenAIAnthropicShim(key, 3)
        max_tokens = int(self.settings.get("max_tokens", 16000))
        budget.preflight(self.provider, self.model, budget.estimate_input_tokens(system, messages), max_tokens)
        started = time.perf_counter()
        response = client.messages.create(model=self.model, max_tokens=max_tokens, system=system,
                                          messages=messages, tools=[_tool()],
                                          tool_choice={"type": "tool", "name": TOOL_NAME})
        record_completion(response, model=self.model, provider=self.provider, role="planner",
                          latency_ms=(time.perf_counter() - started) * 1000)
        budget.charge(response, self.provider, self.model, role="planner",
                      part=str(current_scope().get("part") or ""))
        return response


PLANNERS = {"openai": OpenAIPlanner}
