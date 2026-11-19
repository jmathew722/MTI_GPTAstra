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
    # mti_bench entries have no in-repo views (files live under MTI_BENCH_DATA); skip them here.
    return [PartSpec(p["part"], REPO / p["views"], p.get("units", ""))
            for p in m["splits"].get(split) or [] if p.get("source") != "mti_bench"]


def external_parts(split: str = "dev", manifest: Path = CODE_ROOT / "bench" / "manifest.yaml") -> list[str]:
    """mti_bench parts in a split: skipped by dev_parts() (files live under MTI_BENCH_DATA)."""
    import yaml
    m = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    return [p["part"] for p in m["splits"].get(split) or [] if p.get("source") == "mti_bench"]


BENCH_DRAWING = "drawing.pdf"     # rendered by image_prep at 300 dpi; drawing.png is only a review preview


def bench_part_specs(split: str = "dev", manifest: Path = CODE_ROOT / "bench" / "manifest.yaml",
                     root: Optional[Path] = None) -> tuple[list[PartSpec], list[str]]:
    """mti_bench parts of a split whose drawing is in MTI_BENCH_DATA: (runnable specs, missing part ids).
    Drawings stay outside git (confidential); without MTI_BENCH_DATA every part is missing."""
    import yaml
    if root is None:
        from bench import config
        try:
            root = config.data_root(required=False)
        except config.BenchConfigError:
            root = None
    m = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    specs, missing = [], []
    for p in m["splits"].get(split) or []:
        if p.get("source") != "mti_bench":
            continue
        drawing = Path(root) / p["part"] / BENCH_DRAWING if root else None
        if drawing is not None and drawing.is_file():
            specs.append(PartSpec(p["part"], drawing, p.get("units", "")))
        else:
            missing.append(p["part"])
    return specs, missing


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
    defaults: list[str] = field(default_factory=list)       # callout defaults applied (pipeline/ir/defaults.py)
    reference_step: str = ""
    volume: Optional[float] = None
    cq_skipped: dict = field(default_factory=dict)
    sw_ok: Optional[bool] = None
    sldprt: str = ""
    stl: str = ""                          # SolidWorks mesh of the built part ("" when not exported)
    prevalidation_stl: str = ""            # CadQuery mesh of the reference solid
    sw_features: dict = field(default_factory=dict)
    conventions: list[str] = field(default_factory=list)
    hole_wizard_substitutions: list[dict] = field(default_factory=list)   # Hole Wizard -> plain cut, with codes
    mti_review: list[str] = field(default_factory=list)     # advisory MTI modeling-practice findings    # MTI modeling conventions applied / fallen back
    cost_usd: float = 0.0
    error: str = ""


def _tracker_run_id(tracker) -> str:
    return getattr(tracker, "run_id", "") or "run_untracked"


def run_part(spec: PartSpec, out_root: Path, reuse: list[Path], sw_app=None, pmap=None,
             template: Optional[str] = None, reuse_plan: bool = False, telemetry=None) -> IRResult:
    from pipeline import budget
    from pipeline.ir.compile_cadquery import emit_script, run_script
    from pipeline.ir.from_v1 import dims_of, reference_ids
    from pipeline.planner import OpenAIPlanner
    from pipeline.schema import DrawingData
    from pipeline.progress import Op, Phase
    from pipeline.telemetry import RunTelemetry
    from pipeline.token_tracker import scope
    from run_models import resolve_unknowns

    out = out_root / spec.part
    out.mkdir(parents=True, exist_ok=True)
    tel = telemetry if telemetry is not None else RunTelemetry.from_env(spec.part, out)
    tel.start()
    from pipeline.telemetry import attach_cost_events
    from pipeline.token_tracker import current_tracker
    _tracker = current_tracker()
    detach_cost = attach_cost_events(tel, _tracker, spec.part) if _tracker else (lambda: None)
    run_tags = {"run_id": tel.run_id, "run_attempt": tel.attempt} if tel.run_id else {}
    res = IRResult(spec.part)
    spent0 = budget.spent_usd()
    try:
        images = images_for(spec)
        tel.plan(Phase.INGEST, 1, 1, "drawings")
        tel.plan(Phase.EXTRACTION, len(images), 1, "views")
        tel.plan(Phase.RESOLUTION, 1, 1, "passes")
        tel.plan(Phase.BUILD_PLAN, 1, 1, "plans")
        tel.plan(Phase.REFERENCE_BUILD, 1, 1, "reference solids")
        tel.plan(Phase.ARTIFACT_FINALIZATION, 5, 1, "artifacts")   # report + 4 engineering-markup stages
        tel.complete(Phase.INGEST, Op.INGEST_DRAWING, label=f"Prepared {len(images)} drawing image(s)")
        log.info("[stage] extraction: reading %d image(s) for %s", len(images), spec.part)
        with scope(part=spec.part, **run_tags):
            tel.begin(Phase.EXTRACTION, Op.EXTRACT_VIEW, "Reading the drawing")
            raw, res.extraction = get_extraction(spec, images, out, reuse)
            for i in range(len(images)):   # the extraction call returned: every view is read
                tel.complete(Phase.EXTRACTION, Op.EXTRACT_VIEW, unit_id=f"view_{i}")
            log.info("[stage] resolution: resolving ambiguous references for %s", spec.part)
            resolve_unknowns(raw, spec.part)
            tel.complete(Phase.RESOLUTION, Op.RESOLVE_AMBIGUITY, label="Resolved ambiguous references")
            m = DrawingData.model_validate(raw)
            dims, refs = dims_of(m), reference_ids(m)
            saved = out / "plan.json"
            log.info("[stage] build_plan_start: planning %s%s", spec.part,
                     " (reusing saved plan, no API call)" if (reuse_plan and saved.exists()) else "")
            if reuse_plan and saved.exists():   # rebuild after a compiler change: no API call
                from pipeline.ir.model import BuildPlan
                from pipeline.planner import PlanResult
                pr = PlanResult(BuildPlan.model_validate(json.loads(saved.read_text(encoding="utf-8"))["plan"]))
            else:
                pr = OpenAIPlanner().plan(m, [(label, b64) for label, _, b64 in images], dims, refs)
        res.plan_attempts = pr.attempts
        tel.complete(Phase.BUILD_PLAN, Op.BUILD_PLAN, label="Build plan ready")
        if pr.plan is None:
            res.gate1, res.error = "NO PLAN", pr.error
            return res
        plan = pr.plan
        (out / "plan.json").write_text(json.dumps({"dims": dims, "reference_ids": sorted(refs),
                                                   "plan": plan.model_dump(mode="json")}, indent=2), encoding="utf-8")
        from pipeline.ir.defaults import apply_defaults, nominal_fractions   # after saving: plan.json stays the planner's own
        plan, res.defaults = apply_defaults(plan, dims)
        dims, fractions = nominal_fractions(plan, dims, raw)   # D9: two-place prints of 1/16 fractions
        res.defaults += fractions
        findings = plan.check(dims, refs)
        hard = [f for f in findings if f.severity == "error" and f.code != "unresolved"]
        res.gate1 = "REJECT" if hard else "OK"
        res.planned = sum(1 for f in plan.features if f.status == "planned")
        res.questions = [f"{f.id}: {f.rationale}" for f in plan.features if f.status == "unresolved"]
        res.flagged = [f"{f.id}: {f.justification}" for f in plan.features
                       if f.status == "planned" and f.justification]
        log.info("[stage] build_plan_gate1: gate1=%s planned=%d questions=%d",
                 res.gate1, res.planned, len(res.questions))
        if hard:
            res.error = "; ".join(f"{f.code}:{f.feature}" for f in hard)
            return res
        from pipeline.ir.mti_review import review
        res.mti_review = [f"[{f.code}] {f.message}" for f in review(plan, dims)]
        log.info("[stage] generation_start: building the CadQuery reference for %s", spec.part)
        cq = run_script(emit_script(plan, dims, strict=False), out)
        res.reference_step, res.volume, res.cq_skipped = str(cq.step_path), cq.feature_map["volume"], cq.feature_map["skipped"]
        tel.complete(Phase.REFERENCE_BUILD, Op.REFERENCE_FEATURE, label="Reference solid built")
        log.info("[stage] generation_reference: reference built, volume=%s", res.volume)
        preval = out / "prevalidation.stl"
        res.prevalidation_stl = str(preval) if preval.is_file() else ""
        if sw_app is not None:
            from pipeline.ir.compile_solidworks import compile_solidworks
            tel.plan(Phase.SOLIDWORKS_GENERATION, len(plan.features), 2, "features")   # creation + readback
            tel.plan(Phase.VERIFICATION, 3, 1, "checks")

            def _on_feature(f, r):
                if r.status == "failed":
                    tel.operation_failed(Phase.SOLIDWORKS_GENERATION, Op.CREATE_FEATURE, f.id, r.note)
                tel.complete(Phase.SOLIDWORKS_GENERATION, Op.CREATE_FEATURE, unit_id=f.id,
                             label=f"{f.id} {f.kind}: {r.status}")
            rep = compile_solidworks(sw_app, plan, dims, cq.feature_map, out, template, pmap,
                                     progress=_on_feature)
            tel.complete_remaining(Phase.SOLIDWORKS_GENERATION, Op.CREATE_FEATURE,
                                   "Merged and skipped features accounted")
            for name in ("origin", "bbox", "volume"):
                tel.complete(Phase.VERIFICATION, Op.VERIFY_CHECK, unit_id=name, label=f"Verified {name}")
            res.sw_ok, res.sldprt, res.stl = rep.ok, rep.sldprt or "", rep.stl or ""
            res.conventions = [f"origin centered: {rep.origin_ok}"] + rep.conventions
            res.hole_wizard_substitutions = list(rep.hole_wizard_substitutions)
            res.sw_features = {f.fid: f.status + (f" ({f.note})" if f.note else "") for f in rep.features}
            log.info("[stage] verification: sw_ok=%s bbox_ok=%s volume_ok=%s",
                     res.sw_ok, rep.bbox_ok, rep.volume_ok)
    except Exception as e:
        from pipeline.budget import BudgetExceeded
        if isinstance(e, BudgetExceeded):
            raise
        res.error = f"{type(e).__name__}: {e}"[:400]
        log.error("IR run failed for %s: %s", spec.part, res.error)
    finally:
        res.cost_usd = round(budget.spent_usd() - spent0, 4)
        (out / "ir_report.json").write_text(json.dumps(res.__dict__, indent=2, default=str), encoding="utf-8")
        from pipeline.engineering_markup import finalize_markup    # automatic marked PDF, before the terminal event
        _ops = {"collect": Op.MARKUP_COLLECT, "localize": Op.MARKUP_LOCALIZE,
                "render": Op.MARKUP_RENDER, "publish": Op.MARKUP_PUBLISH}

        def _tick(stage: str) -> None:
            try:
                tel.complete(Phase.ARTIFACT_FINALIZATION, _ops[stage], unit_id=f"markup_{stage}",
                             label=f"Engineering markup: {stage}")
            except Exception:   # noqa: BLE001 - progress bookkeeping must never fail a run
                pass
        try:
            finalize_markup(out, spec.views, run_id=tel.run_id or _tracker_run_id(_tracker), part=spec.part, tick=_tick)
        except Exception as e:   # noqa: BLE001 - finalize_markup reports through its manifest; this is belt and braces
            log.warning("engineering markup stage raised for %s: %s", spec.part, e)
        if res.error or res.gate1 in ("REJECT", "NO PLAN"):
            tel.fail(res.error or res.gate1)
        else:
            tel.complete(Phase.ARTIFACT_FINALIZATION, Op.FINALIZE_ARTIFACT, label="Report written")
            tel.finish()
        detach_cost()
        tel.close()
    return res


def connect_sw():
    from pipeline.ir.compile_solidworks import probe_plane_map
    from pipeline.solidworks_builder import connect_to_solidworks
    template = os.getenv("SOLIDWORKS_TEMPLATE_PATH") or None
    app = connect_to_solidworks()
    return app, probe_plane_map(app, template), template
