"""Plan dev parts with GPT-6 Astra and score each plan against its golden plan.

For each part: saved extraction (resolved like v1) + drawing images (FULL sheet first,
then view crops) -> planner -> plan.json, then the CadQuery reference + score vs
tests/golden/ir/<part>.json when one exists. Paid calls go through the $20 budget guard.

    python ir_plan.py SB11033 A040921E --extractions output/astra_2026-10-04 --output output/ir_plans
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def images_for(part: str) -> list[tuple[str, str]]:
    from utils.image_prep import prepare_image
    folder = next((p for p in (REPO / "ViewDefinedDrawings").glob(f"{part}*/{part}")), None)
    if folder is None:
        raise FileNotFoundError(f"no drawing folder for {part}")
    order = [(f"{part}.png", "FULL SHEET"), (f"{part}_front.png", "FRONT VIEW (crop)"),
             (f"{part}_side.png", "SIDE VIEW (crop)")]
    return [(label, prepare_image(folder / name)) for name, label in order if (folder / name).exists()]


def main() -> int:
    from pipeline.budget import BudgetExceeded, cap_usd, spent_usd
    from pipeline.ir.from_v1 import dims_of, reference_ids
    from pipeline.ir.model import BuildPlan
    from pipeline.planner import OpenAIPlanner
    from pipeline.schema import DrawingData
    from pipeline.token_tracker import LEDGER_NAME, TokenTracker, scope
    from run_models import resolve_unknowns

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parts", nargs="+")
    ap.add_argument("--extractions", type=Path, default=Path("output/astra_2026-10-04"))
    ap.add_argument("--output", type=Path, default=Path("output/ir_plans"))
    args = ap.parse_args()

    tracker = TokenTracker(args.output / "usage" / LEDGER_NAME)
    rows = []
    with tracker.activate():
        for part in args.parts:
            out = args.output / part
            out.mkdir(parents=True, exist_ok=True)
            raw = json.loads((args.extractions / part / f"{part}_extraction.json").read_text(encoding="utf-8"))
            resolve_unknowns(raw, part)
            m = DrawingData.model_validate(raw)
            dims, refs = dims_of(m), reference_ids(m)
            spent0 = spent_usd()
            try:
                with scope(part=part):
                    r = OpenAIPlanner().plan(m, images_for(part), dims, refs)
            except BudgetExceeded as e:
                print(f"*** STOPPED: {e}", file=sys.stderr)
                return 9
            row = {"part": part, "attempts": r.attempts, "error": r.error,
                   "cost_usd_budget_rate": round(spent_usd() - spent0, 4)}
            if r.plan is not None:
                (out / "plan.json").write_text(json.dumps({"dims": dims, "reference_ids": sorted(refs),
                                                           "plan": r.plan.model_dump(mode="json")}, indent=2),
                                               encoding="utf-8")
                row["findings"] = [f"{f.severity}:{f.code}:{f.feature}" for f in r.findings if f.severity != "warning"]
                gold = Path("tests/golden/ir") / f"{part}.json"
                if gold.exists():
                    from pipeline.ir.score import score
                    g = json.loads(gold.read_text(encoding="utf-8"))
                    row["score"] = score(r.plan, dims, BuildPlan.model_validate(g["plan"]),
                                         {k: float(v) for k, v in g["dims"].items()}, refs)
            rows.append(row)
            (out / "result.json").write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")
            print(json.dumps(row, default=str))
    (args.output / "summary.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print(f"spent ${spent_usd():.2f} of ${cap_usd():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
