#!/usr/bin/env python3
"""Score MTI audit parts: our CadQuery reference (``reference.step``) vs MTI's existing model
(``ground_truth.step``, from mti_groundtruth.py), per part folder.

Aligned IoU (pipeline/ir/score.py: best of the 48 signed axis permutations, centered by
bounding box), surface deviation in mm (max and mean; fairer than IoU on thin sheet parts),
plus volume and size ratios. No API cost, no SolidWorks.

    python mti_score.py --out <output dir> A00115E ...
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
    args = ap.parse_args()
    import cadquery as cq
    from pipeline.ir.score import aligned, iou, surface_deviation

    rows = []
    for part in args.parts:
        d = args.out / part
        ours, gt = d / "reference.step", d / "ground_truth.step"
        row = {"part": part}
        if not ours.exists() or not gt.exists():
            row["error"] = "missing " + ", ".join(p.name for p in (ours, gt) if not p.exists())
        else:
            a, b = cq.importers.importStep(str(ours)).val(), cq.importers.importStep(str(gt)).val()
            va, vb = a.Volume(), b.Volume()
            sa = sorted((a.BoundingBox().xlen, a.BoundingBox().ylen, a.BoundingBox().zlen))
            sb = sorted((b.BoundingBox().xlen, b.BoundingBox().ylen, b.BoundingBox().zlen))
            value, key = iou(a, b)
            dev = surface_deviation(aligned(a, b, key), b) if key else None
            row.update(iou=round(value, 4), volume_ratio=round(va / vb, 4),
                       deviation_mm=({k: round(v, 3) for k, v in dev.items()} if dev else None),
                       size_ratio=[round(x / y, 4) for x, y in zip(sa, sb)],
                       ours_mm=[round(x, 2) for x in sa], mti_mm=[round(x, 2) for x in sb])
        rows.append(row)
        print(json.dumps(row), flush=True)
    (args.out / "mti_score.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
