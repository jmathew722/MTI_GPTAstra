#!/usr/bin/env python3
"""Export MTI's existing models (the answer key) to STEP and summarize them.

For every part folder given, opens ``<out>/<part>/source/*.SLDPRT`` (a downloaded COPY;
the Google Drive original is never touched) READ-ONLY, saves ``ground_truth.step`` and
``ground_truth.json`` (volume, bounding box, feature tree) next to it, and closes it.

    python mti_groundtruth.py --out ../../mti-2d-3d/2D-3D-CAD-Test-Generation/output A00115E SB12006 ...

WINDOWS + SOLIDWORKS ONLY.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SW_DOC_PART = 1
OPEN_SILENT_READONLY = 1       # swOpenDocOptions_Silent. NOT ReadOnly (2): SolidWorks crashed opening
                               # MTI models read-only (2026-10-26). These are downloaded copies anyway.


def summarize(app, model: Path, out_dir: Path) -> dict:
    from pipeline.solidworks_builder import _g, _total_volume, typed
    # Typed OpenDoc6 (late binding can't pass its by-ref errors/warnings). It crashed
    # SolidWorks only when called right after this script LAUNCHED SolidWorks (add-ins
    # still loading); in a warmed-up session it opens MTI models with errors=0 (E025).
    path = str(model.resolve())   # SolidWorks resolves relative paths from ITS cwd (error 2)
    res = typed(app, "ISldWorks").OpenDoc6(path, SW_DOC_PART, OPEN_SILENT_READONLY, "", 0, 0)
    doc = res[0] if isinstance(res, tuple) else res
    if doc is None and isinstance(res, tuple) and res[1] == 65536:   # swFileWithSameTitleAlreadyOpen
        doc = app.GetOpenDocumentByName(path)
    if doc is None:
        return {"error": f"could not open {model.name}: {res}"}
    from win32com.client.dynamic import Dispatch
    doc = Dispatch(doc._oleobj_)   # late-bound again: GetBodies2 etc. live on IPartDoc, not IModelDoc2
    try:
        row: dict = {"model": model.name}
        bodies = doc.GetBodies2(0, False) or ()
        row["bodies"] = len(bodies)
        row["volume_mm3"] = round(_total_volume(doc) * 1e9, 3)
        if bodies:
            bb = list(bodies[0].GetBodyBox())
            row["bbox_mm"] = [round(v * 1000, 4) for v in bb]
            row["size_mm"] = sorted(round((bb[i + 3] - bb[i]) * 1000, 4) for i in range(3))
            row["center_mm"] = [round((bb[i] + bb[i + 3]) * 500, 4) for i in range(3)]
        feats, f = [], _g(doc, "FirstFeature")
        while f is not None:
            tf = typed(f, "IFeature")
            feats.append([tf.Name, tf.GetTypeName2()])
            f = tf.GetNextFeature()
        skip = {"HistoryFolder", "SensorFolder", "DocsFolder", "DetailCabinet", "SurfaceBodyFolder",
                "SolidBodyFolder", "CommentsFolder", "FavoriteFolder", "SelectionSetFolder",
                "EqnFolder", "MaterialFolder", "RefPlane", "OriginProfileFeature", "MateReferenceGroupFolder",
                "InkMarkupFolder", "LiveSectionFolder", "MarkupCommentFolder", "BlockFolder",
                "EnvFolder", "ProfileFeature", "RefAxis", "RefPoint", "AttributeFeature"}
        row["features"] = [n for n, t in feats if t not in skip]
        row["feature_types"] = [t for n, t in feats if t not in skip]
        step = (out_dir / "ground_truth.step").resolve()
        doc.SaveAs3(str(step), 0, 1)
        row["step"] = str(step) if step.exists() else ""
        return row
    finally:
        app.CloseDoc(_g(doc, "GetTitle"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("parts", nargs="+")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    from pipeline.solidworks_builder import connect_to_solidworks
    app = connect_to_solidworks()
    for part in args.parts:
        d = args.out / part
        models = sorted((d / "source").glob("*.SLDPRT")) + sorted((d / "source").glob("*.sldprt"))
        if not models:
            print(f"{part}: no SLDPRT in {d / 'source'}")
            continue
        try:
            row = summarize(app, models[0], d)
        except Exception as e:  # keep going: one bad model must not stop the batch
            row = {"error": f"{type(e).__name__}: {e}"[:300]}
        row["part"] = part
        (d / "ground_truth.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        print(json.dumps({k: row.get(k) for k in ("part", "volume_mm3", "size_mm", "center_mm", "feature_types", "error")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
