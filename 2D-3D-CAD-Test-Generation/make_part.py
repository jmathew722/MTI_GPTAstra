#!/usr/bin/env python
"""Build one or more drawings into FINAL_OUTPUTs, refreshing costs.txt after each part.

    python make_part.py "../data/inputs/simple_parts/A001151E.PDF"
    python make_part.py "../data/inputs/simple_parts/A001151E.PDF" "../data/inputs/drawing_pdfs/A001171E.PDF"
    python make_part.py --no-solidworks <drawing>      # stop after the CadQuery reference
    python make_part.py --validate-only <drawing>      # paid extraction, no build

Each drawing runs through the Feature-IR path (main.py --ir --engine com), which is
the recommended pipeline: extraction -> build plan -> Gate 1 -> CadQuery reference
-> native SolidWorks part with every feature volume-checked.

costs.txt is rewritten after EVERY part, so an interrupted batch still leaves an
accurate record of what the API key was charged. Exit code 9 means the $20 budget
guard stopped the run (CLAUDE.md rule 12: never swallow it, the whole run stops).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
FINAL = PROJECT / "FINAL_OUTPUTs"
BUDGET_EXIT = 9
MAX_PER_PART_USD = 5.00          # user cap: never let one part cost more than this


def refresh_costs() -> None:
    env = {**os.environ, "PYTHONUTF8": "1"}
    subprocess.run([sys.executable, str(HERE / "final_costs.py"), "--out", str(FINAL)],
                   cwd=HERE, env=env, check=False)


def spent_so_far() -> float:
    """Total priced spend across every ledger under FINAL_OUTPUTs and output/."""
    sys.path.insert(0, str(HERE))
    import importlib
    fc = importlib.import_module("final_costs")
    importlib.reload(fc)
    rows = fc.usage_rows([FINAL, HERE / "output"])
    prices = fc._prices()
    return sum(c for c in (fc.row_cost(r, prices) for r in rows) if c is not None)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build drawings into FINAL_OUTPUTs with cost tracking.")
    ap.add_argument("drawings", nargs="+", help="drawing files (.pdf/.png/.jpg/.tif/.bmp)")
    ap.add_argument("--no-solidworks", action="store_true",
                    help="stop after the CadQuery reference (no native SolidWorks build)")
    ap.add_argument("--validate-only", action="store_true",
                    help="paid extraction + verification only; no build")
    ap.add_argument("--max-per-part", type=float, default=MAX_PER_PART_USD,
                    help=f"stop the run if any one part costs more than this (default ${MAX_PER_PART_USD:.2f})")
    args = ap.parse_args()

    FINAL.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONUTF8": "1"}      # Windows: error log E008

    failed: list[str] = []
    for i, raw in enumerate(args.drawings, 1):
        path = Path(raw)
        if not path.is_absolute():
            path = (HERE / raw).resolve()
        if not path.is_file():
            print(f"[{i}/{len(args.drawings)}] SKIP (not a file): {path}")
            failed.append(str(path))
            continue

        cmd = [sys.executable, "main.py", "--drawing", str(path), "--output", str(FINAL)]
        if args.validate_only:
            cmd.append("--validate-only")
        else:
            cmd.append("--ir")
            if not args.no_solidworks:
                cmd += ["--engine", "com"]

        before = spent_so_far()
        print(f"\n{'=' * 78}\n[{i}/{len(args.drawings)}] {path.name}\n{'=' * 78}")
        rc = subprocess.run(cmd, cwd=HERE, env=env).returncode

        refresh_costs()          # after EVERY part, success or not

        this_part = spent_so_far() - before
        print(f"  this part cost ${this_part:,.4f}  (cap ${args.max_per_part:,.2f})")
        if this_part > args.max_per_part:
            print(f"\nPER-PART CAP EXCEEDED: {path.name} cost ${this_part:,.4f} "
                  f"> ${args.max_per_part:,.2f}. Stopping before the next part.")
            print(f"See {FINAL / 'costs.txt'}")
            return 8

        if rc == BUDGET_EXIT:
            print(f"\nBUDGET GUARD tripped (exit {rc}). Stopping the whole run.")
            print(f"See {FINAL / 'costs.txt'}")
            return rc
        if rc != 0:
            print(f"[{i}/{len(args.drawings)}] FAILED (exit {rc}): {path.name}")
            failed.append(path.name)

    print(f"\n{'=' * 78}")
    done = len(args.drawings) - len(failed)
    print(f"{done}/{len(args.drawings)} part(s) completed. Costs: {FINAL / 'costs.txt'}")
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
