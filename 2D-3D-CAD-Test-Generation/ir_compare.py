"""Old pipeline (v1) vs Feature IR on the dev set, from the SAME extraction per part.

For each part already run by ``ir_run.py`` (output/ir_runs/<part>/ir_report.json):
* v1: resolve -> gate -> COM build -> validator, from the extraction the IR run used,
  exported to STEP;
* IR: the run's reference STEP, verified in SolidWorks per feature;
* where a hand-checked golden plan exists (tests/golden/ir/<part>.json), both STEPs are
  scored against it by aligned solid IoU (pipeline.ir.score.iou).
Writes output/ir_runs/v1_vs_ir.json and .md. Windows + SolidWorks. No API calls.

    python ir_compare.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RUNS = Path("output/ir_runs")
GOLD = Path("tests/golden/ir")


def extraction_used(part: str, report: dict) -> Path:
    src = report.get("extraction", "")
    for token in src.split():
        if token.endswith(".json") and Path(token).exists():
            return Path(token)
    p = RUNS / part / f"{part}_extraction.json"
    return p


def golden_solid(part: str):
    import cadquery  # noqa: F401
    from pipeline.ir.compile_cadquery import build
    from pipeline.ir.model import BuildPlan
    g = json.loads((GOLD / f"{part}.json").read_text(encoding="utf-8"))
    return build(BuildPlan.model_validate(g["plan"]), {k: float(v) for k, v in g["dims"].items()},
                 strict=False).model.solid


def step_solid(path: str):
    import cadquery as cq
    return cq.importers.importStep(path).val()


def main() -> int:
    from pipeline.ir.score import iou
    from pipeline.ir_pipeline import connect_sw
    from rebuild_from_json import rebuild

    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", nargs="*")
    args = ap.parse_args()
    app, _, _ = connect_sw()
    old = {r["part"]: r for r in json.loads((RUNS / "v1_vs_ir.json").read_text(encoding="utf-8"))}         if (RUNS / "v1_vs_ir.json").exists() else {}
    rows = []
    for rep_path in sorted(RUNS.glob("*/ir_report.json")):
        part = rep_path.parent.name
        if args.parts and part not in args.parts:
            if part in old:
                rows.append(old[part])
            continue
        ir = json.loads(rep_path.read_text(encoding="utf-8"))
        row = {"part": part, "ir_gate1": ir["gate1"], "ir_sw_ok": ir["sw_ok"], "ir_planned": ir["planned"],
               "ir_questions": len(ir["questions"]), "ir_error": ir["error"]}
        src = extraction_used(part, ir)
        try:
            try:
                v1 = rebuild(app, src, RUNS / "_v1", step=True, name=part)
            except Exception as e:  # SolidWorks crashed (RPC unavailable): reconnect once, retry
                if "RPC" not in str(e):
                    raise
                app, _, _ = connect_sw()
                v1 = rebuild(app, src, RUNS / "_v1", step=True, name=part)
            row.update(v1_gate=v1["gate"], v1_built=f"{v1.get('built', 0)}/{v1.get('expected', '-')}",
                       v1_validator=v1.get("validator", ""))
        except Exception as e:
            v1 = {}
            row["v1_error"] = f"{type(e).__name__}: {e}"[:200]
        if (GOLD / f"{part}.json").exists():
            g = golden_solid(part)
            if v1.get("step"):
                row["v1_iou"] = round(iou(step_solid(v1["step"]), g)[0], 4)
            if ir.get("reference_step"):
                row["ir_iou"] = round(iou(step_solid(ir["reference_step"]), g)[0], 4)
        rows.append(row)
        print(json.dumps(row))
    (RUNS / "v1_vs_ir.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    cols = ["part", "v1_gate", "v1_built", "v1_validator", "v1_iou", "ir_gate1", "ir_planned",
            "ir_questions", "ir_sw_ok", "ir_iou"]
    md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    md += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    (RUNS / "v1_vs_ir.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
