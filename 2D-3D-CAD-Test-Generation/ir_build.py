"""Build Feature-IR plans: CadQuery reference (STEP + feature map), then SolidWorks.

Input files are golden-plan JSON ({"dims": {...}, "plan": {...}}) or a v1 extraction
(converted with plan_from_v1). No API calls.

    python ir_build.py tests/golden/ir/SB11033.json --output output/ir_build            # reference only
    python ir_build.py tests/golden/ir/*.json --solidworks --output output/ir_build    # + native part
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pipeline.ir.compile_cadquery import emit_script, run_script
from pipeline.ir.model import BuildPlan


def load(path: Path) -> tuple[BuildPlan, dict[str, float], frozenset[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "plan" in data:
        return (BuildPlan.model_validate(data["plan"]), {k: float(v) for k, v in data["dims"].items()},
                frozenset(data.get("reference_ids", [])))
    from pipeline.ir.from_v1 import dims_of, plan_from_v1, reference_ids
    from pipeline.schema import DrawingData
    from run_models import resolve_unknowns
    resolve_unknowns(data, path.stem.replace("_extraction", ""))
    m = DrawingData.model_validate(data)
    return plan_from_v1(m), dims_of(m), reference_ids(m)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plans", nargs="+", type=Path)
    ap.add_argument("--output", type=Path, default=Path("output/ir_build"))
    ap.add_argument("--solidworks", action="store_true", help="also build natively (Windows + SolidWorks)")
    ap.add_argument("--convention", choices=("mti", "drawing"), default="mti",
                    help="SolidWorks modeling convention (default: MTI's centered origin, Top-plane base)")
    args = ap.parse_args()

    sw_app = pmap = None
    if args.solidworks:
        from pipeline.ir.compile_solidworks import probe_plane_map
        from pipeline.solidworks_builder import connect_to_solidworks
        sw_app = connect_to_solidworks()
        pmap = probe_plane_map(sw_app, os.getenv("SOLIDWORKS_TEMPLATE_PATH") or None)

    rows = []
    for path in args.plans:
        plan, dims, refs = load(path)
        out = args.output / plan.part
        findings = plan.check(dims, refs)
        errors = [f for f in findings if f.severity == "error" and f.code != "unresolved"]
        if errors:
            print(f"{plan.part}: Gate-1 errors, not built: {[f.message for f in errors]}")
            rows.append({"part": plan.part, "gate1": "REJECT", "errors": [f.message for f in errors]})
            continue
        cq = run_script(emit_script(plan, dims, strict=False), out)
        from pipeline.ir.mti_review import review
        row = {"part": plan.part, "gate1": "OK", "unresolved": [f.feature for f in findings if f.code == "unresolved"],
               "mti_review": [f"[{f.code}] {f.message}" for f in review(plan, dims)],
               "reference_step": str(cq.step_path), "volume": cq.feature_map["volume"],
               "cq_skipped": cq.feature_map["skipped"]}
        if sw_app is not None:
            from pipeline.ir.compile_solidworks import compile_solidworks
            rep = compile_solidworks(sw_app, plan, dims, cq.feature_map, out,
                                     os.getenv("SOLIDWORKS_TEMPLATE_PATH") or None, pmap,
                                     convention=args.convention)
            row.update(sw_ok=rep.ok, sldprt=rep.sldprt, sw_bbox_ok=rep.bbox_ok, sw_volume_ok=rep.volume_ok,
                       convention=rep.convention, origin_centered=rep.origin_ok, conventions=rep.conventions,
                       sw_features={f.fid: f"{f.status}{' (' + f.note + ')' if f.note else ''}" for f in rep.features})
        rows.append(row)
        print(json.dumps(row, indent=1, default=str))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "ir_build_summary.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
