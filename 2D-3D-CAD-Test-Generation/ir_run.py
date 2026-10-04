"""Drawing -> native SolidWorks part through the Feature IR, for the dev set or named parts.

    python ir_run.py --split dev --solidworks                  # all 9 dev parts (bench/manifest.yaml)
    python ir_run.py --parts SB11033 135-A --solidworks
    python ir_run.py --parts SB11033                            # reference STEP only (any OS)

Saved extractions are reused at no cost (--reuse, default output/astra_2026-10-04); parts
without one are extracted with GPT-6 Astra. Planning is always fresh (GPT-6 Astra). Every
paid call goes through the $20 budget guard; a stop ends the run with exit code 9.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    from pipeline.budget import BudgetExceeded, cap_usd, spent_usd
    from pipeline.ir_pipeline import connect_sw, dev_parts, run_part
    from pipeline.token_tracker import LEDGER_NAME, TokenTracker

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--parts", nargs="*", help="subset of the split's parts")
    ap.add_argument("--solidworks", action="store_true")
    ap.add_argument("--reuse-plans", action="store_true", help="rebuild from saved plan.json (no API call)")
    ap.add_argument("--output", type=Path, default=Path("output/ir_runs"))
    ap.add_argument("--reuse", type=Path, nargs="*",
                    default=[Path("output/astra_2026-10-04"), Path("output/ir_runs")])
    args = ap.parse_args()

    specs = dev_parts(split=args.split)
    if args.parts:
        specs = [s for s in specs if s.part in args.parts]
    sw = connect_sw() if args.solidworks else (None, None, None)
    rows = []
    with TokenTracker(args.output / "usage" / LEDGER_NAME).activate():
        for spec in specs:
            print(f"=== {spec.part}")
            try:
                r = run_part(spec, args.output, args.reuse, *sw, reuse_plan=args.reuse_plans)
            except BudgetExceeded as e:
                print(f"\n*** STOPPED: {e}", file=sys.stderr)
                return 9
            rows.append(r.__dict__)
            print(json.dumps({k: r.__dict__[k] for k in ("part", "gate1", "planned", "sw_ok", "cost_usd", "error")}))
            for q in r.questions:
                print("   QUESTION", q[:160])
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "ir_run_summary.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print(f"spent ${spent_usd():.2f} of ${cap_usd():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
