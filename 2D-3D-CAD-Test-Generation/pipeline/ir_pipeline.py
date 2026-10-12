"""The Feature-IR path end to end (IR v2, Task 8):

    drawing -> extraction (GPT-6 Astra) -> plan (GPT-6 Astra) -> Gate 1 -> CadQuery reference
            -> native SolidWorks part (verified per feature) -> report

One function per part (``run_part``), so the CLI (``ir_run.py``, ``main.py --ir``) and a
future MCP tool (PRD D1) share it. Rules carried over from v1:
* a paid extraction is saved before anything else can fail (CLAUDE.md rule 9);
* every paid call goes through the $20 budget guard; a stop ends the whole run;
* nothing ambiguous is guessed: ``unresolved`` features become explicit human questions.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from utils.logger import get_logger

log = get_logger()

CODE_ROOT = Path(__file__).resolve().parent.parent
REPO = CODE_ROOT.parent


@dataclass
class PartSpec:
    part: str
    views: Path            # a folder of view PNGs or a single PDF/PNG
    units: str = ""


def dev_parts(manifest: Path = CODE_ROOT / "bench" / "manifest.yaml", split: str = "dev") -> list[PartSpec]:
    import yaml
    m = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    return [PartSpec(p["part"], REPO / p["views"], p.get("units", "")) for p in m["splits"].get(split) or []]


def images_for(spec: PartSpec) -> list[tuple[str, str, str]]:
    """[(label, view_type, base64 png)] with the FULL sheet first (crops can hide callouts)."""
    from utils.image_prep import prepare_image
    v = spec.views
    if v.is_file():
        return [("FULL SHEET", "full", prepare_image(v))]
    out = []
    for name, label, vt in ((f"{spec.part}.png", "FULL SHEET", "full"),
                            (f"{spec.part}_front.png", "FRONT VIEW (crop)", "front"),
                            (f"{spec.part}_side.png", "SIDE VIEW (crop)", "side")):
        if (v / name).exists():
            out.append((label, vt, prepare_image(v / name)))
    if not out:
        raise FileNotFoundError(f"no view images for {spec.part} in {v}")
    return out


def get_extraction(spec: PartSpec, images, out_dir: Path, reuse: list[Path]) -> tuple[dict, str]:
    """Saved extraction if one exists (no cost), else a fresh GPT-6 Astra extraction."""
    for d in reuse:
        for cand in (d / spec.part / f"{spec.part}_extraction.json", d / f"{spec.part}_extraction.json"):
            if cand.exists():
                return json.loads(cand.read_text(encoding="utf-8")), f"reused {cand}"
    from pipeline.extractor import extract_drawing_data, extract_drawing_data_multiview
    cache = CODE_ROOT / "output" / ".extraction_cache"
    if len(images) == 1:
        data = extract_drawing_data(images[0][2], "image/png", cache_dir=cache)
    else:
        data = extract_drawing_data_multiview([(vt, b64, "image/png") for _, vt, b64 in images], cache_dir=cache)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{spec.part}_extraction.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")   # rule 9: saved first
    return data, f"extracted with GPT-6 Astra -> {path}"


@dataclass
class IRResult:
    part: str
    extraction: str = ""
    plan_attempts: int = 0
    gate1: str = ""                        # OK | REJECT | NO PLAN
    planned: int = 0
    questions: list[str] = field(default_factory=list)      # unresolved features, as human questions
    flagged: list[str] = field(default_factory=list)        # planned with a justification -> review
    reference_step: str = ""
    volume: Optional[float] = None
    cq_skipped: dict = field(default_factory=dict)
    sw_ok: Optional[bool] = None
    sldprt: str = ""
    sw_features: dict = field(default_factory=dict)
    conventions: list[str] = field(default_factory=list)
    mti_review: list[str] = field(default_factory=list)     # advisory MTI modeling-practice findings    # MTI modeling conventions applied / fallen back
    cost_usd: float = 0.0
    error: str = ""


def run_part(spec: PartSpec, out_root: Path, reuse: list[Path], sw_app=None, pmap=None,
             template: Optional[str] = None, reuse_plan: bool = False) -> IRResult:
    from pipeline import budget
    from pipeline.ir.compile_cadquery import emit_script, run_script
    from pipeline.ir.from_v1 import dims_of, reference_ids
    from pipeline.planner import OpenAIPlanner
    from pipeline.schema import DrawingData
    from pipeline.token_tracker import scope
    from run_models import resolve_unknowns

    out = out_root / spec.part
    out.mkdir(parents=True, exist_ok=True)
    res = IRResult(spec.part)
    spent0 = budget.spent_usd()
    try:
        images = images_for(spec)
        with scope(part=spec.part):
            raw, res.extraction = get_extraction(spec, images, out, reuse)
            resolve_unknowns(raw, spec.part)
            m = DrawingData.model_validate(raw)
            dims, refs = dims_of(m), reference_ids(m)
            saved = out / "plan.json"
            if reuse_plan and saved.exists():   # rebuild after a compiler change: no API call
                from pipeline.ir.model import BuildPlan
                from pipeline.planner import PlanResult
                pr = PlanResult(BuildPlan.model_validate(json.loads(saved.read_text(encoding="utf-8"))["plan"]))
            else:
                pr = OpenAIPlanner().plan(m, [(label, b64) for label, _, b64 in images], dims, refs)
        res.plan_attempts = pr.attempts
        if pr.plan is None:
            res.gate1, res.error = "NO PLAN", pr.error
            return res
        plan = pr.plan
        (out / "plan.json").write_text(json.dumps({"dims": dims, "reference_ids": sorted(refs),
                                                   "plan": plan.model_dump(mode="json")}, indent=2), encoding="utf-8")
        findings = plan.check(dims, refs)
        hard = [f for f in findings if f.severity == "error" and f.code != "unresolved"]
        res.gate1 = "REJECT" if hard else "OK"
        res.planned = sum(1 for f in plan.features if f.status == "planned")
        res.questions = [f"{f.id}: {f.rationale}" for f in plan.features if f.status == "unresolved"]
        res.flagged = [f"{f.id}: {f.justification}" for f in plan.features
                       if f.status == "planned" and f.justification]
        if hard:
            res.error = "; ".join(f"{f.code}:{f.feature}" for f in hard)
            return res
        from pipeline.ir.mti_review import review
        res.mti_review = [f"[{f.code}] {f.message}" for f in review(plan, dims)]
        cq = run_script(emit_script(plan, dims, strict=False), out)
        res.reference_step, res.volume, res.cq_skipped = str(cq.step_path), cq.feature_map["volume"], cq.feature_map["skipped"]
        if sw_app is not None:
            from pipeline.ir.compile_solidworks import compile_solidworks
            rep = compile_solidworks(sw_app, plan, dims, cq.feature_map, out, template, pmap)
            res.sw_ok, res.sldprt = rep.ok, rep.sldprt or ""
            res.conventions = [f"origin centered: {rep.origin_ok}"] + rep.conventions
            res.sw_features = {f.fid: f.status + (f" ({f.note})" if f.note else "") for f in rep.features}
    except Exception as e:
        from pipeline.budget import BudgetExceeded
        if isinstance(e, BudgetExceeded):
            raise
        res.error = f"{type(e).__name__}: {e}"[:400]
        log.error("IR run failed for %s: %s", spec.part, res.error)
    finally:
        res.cost_usd = round(budget.spent_usd() - spent0, 4)
        (out / "ir_report.json").write_text(json.dumps(res.__dict__, indent=2, default=str), encoding="utf-8")
    return res


def connect_sw():
    from pipeline.ir.compile_solidworks import probe_plane_map
    from pipeline.solidworks_builder import connect_to_solidworks
    template = os.getenv("SOLIDWORKS_TEMPLATE_PATH") or None
    app = connect_to_solidworks()
    return app, probe_plane_map(app, template), template
