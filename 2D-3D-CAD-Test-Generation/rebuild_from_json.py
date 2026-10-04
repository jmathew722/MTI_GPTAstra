"""Rebuild parts in SolidWorks from saved extraction JSON: no API call, no cost.

Runs exactly the run_models.py path after extraction:
    resolve_unknowns -> verification gate -> COM build (non-strict) -> validate_model

Use it to re-measure every saved extraction after a builder/resolver change
(this is how STATE.md 2.1-2.2 are produced). Windows + SolidWorks only.

    python rebuild_from_json.py output/SB11033/SB11033_extraction.json [more.json ...] --output ./output/rebuild
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pipeline.model_validator import validate_model
from pipeline.validator import run_verification
from run_models import resolve_unknowns


def rebuild(sw_app, src: Path, out_root: Path) -> dict:
    from pipeline.solidworks_builder import build_model

    name = src.stem.replace("_extraction", "")
    data = json.loads(src.read_text(encoding="utf-8"))
    decisions, concerns = resolve_unknowns(data, name)
    model, report = run_verification(data)
    row = {"part": name, "source": str(src), "gate": "READY" if (model and report.ok) else "BLOCKED"}
    if row["gate"] == "BLOCKED":
        row["errors"] = report.errors
        return row
    skipped: list = []
    path, doc = build_model(sw_app, model, output_dir=out_root / name,
                            template_path=os.getenv("SOLIDWORKS_TEMPLATE_PATH") or None,
                            strict=False, skipped_out=skipped)
    built = [f for f in model.build_order if f not in {s[0] for s in skipped}]
    v = validate_model(doc, model, built_feature_ids=built)
    row.update(sldprt=path, built=len(built), expected=len(model.features), skipped=skipped,
               validator="PASSED" if v["ok"] else "FAILED", failed=v["failed"],
               flags=[w for w in model.warnings if any(k in w for k in
                      ("ASSUMED", "INFERRED", "CORRECTED", "PATTERN FROM", "realized", "UNSUPPORTED"))],
               escalate=[c for c in concerns if c.startswith("ESCALATE")])
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("extractions", nargs="+", type=Path)
    ap.add_argument("--output", type=Path, default=Path("output/rebuild"))
    args = ap.parse_args()
    from pipeline.solidworks_builder import connect_to_solidworks

    app = connect_to_solidworks()
    rows = [rebuild(app, src, args.output) for src in args.extractions]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "rebuild_summary.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    total_b = sum(r.get("built", 0) for r in rows)
    total_e = sum(r.get("expected", 0) for r in rows)
    for r in rows:
        print(f"{r['part']:10s} {r['gate']:7s} {r.get('built', 0)}/{r.get('expected', '-')} "
              f"{r.get('validator', '')}")
    print(f"TOTAL {total_b}/{total_e} features built; "
          f"{sum(r.get('validator') == 'PASSED' for r in rows)}/{len(rows)} parts PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
