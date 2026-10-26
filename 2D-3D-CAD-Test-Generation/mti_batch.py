#!/usr/bin/env python3
"""Run MTI audit parts end to end: drawing PDF -> GPT-6 Astra extract + plan -> CadQuery
reference -> native SolidWorks part (MTI conventions), one folder per part.

Inputs are downloaded copies in ``<out>/<part>/source/`` (see mti_groundtruth.py and
CLAUDE.md "MTI test files"); results go to ``<out>/<part>/``. Every paid call goes through
the $20 budget guard; a stop ends the batch with exit code 9.

    python mti_batch.py --out <output dir> A00115E SB12006 ... [--no-solidworks]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("parts", nargs="+")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--no-solidworks", action="store_true")
    ap.add_argument("--reuse-plans", action="store_true", help="rebuild from saved plan.json (no API call)")
    args = ap.parse_args()

    from pipeline import budget
    from pipeline.budget import BudgetExceeded
    from pipeline.ir_pipeline import PartSpec, connect_sw, run_part

    sw = connect_sw() if not args.no_solidworks else (None, None, None)
    rows = []
    try:
        for part in args.parts:
            src = args.out / part / "source"
            pdfs = sorted(p for p in src.iterdir() if p.suffix.lower() == ".pdf") if src.is_dir() else []
            if not pdfs:
                print(f"{part}: no PDF drawing in {src}")
                continue
            res = run_part(PartSpec(part, pdfs[0]), args.out, [args.out], *sw, reuse_plan=args.reuse_plans)
            row = {k: getattr(res, k, None) for k in ("part", "gate1", "planned", "sw_ok", "cost_usd", "error",
                                                       "questions", "conventions")}
            rows.append(row)
            print(json.dumps(row, default=str), flush=True)
    except BudgetExceeded as e:
        print(f"BUDGET STOP: {e}", flush=True)
        return 9
    finally:
        (args.out / "mti_batch_summary.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        print(f"spent ${budget.spent_usd():.2f} of ${budget.cap_usd():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
