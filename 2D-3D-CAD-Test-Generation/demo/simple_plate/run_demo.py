"""Build DEMO-PLATE-001 from each extraction and score it against the ground truth.

Two readings of the SAME drawing go through the SAME build pipeline
(``run_models.resolve_unknowns`` -> verification gate -> COM build -> validator):

    no_api  extraction_no_api.json  read by hand in a Claude Code session (no API key)
    astra   extraction_astra.json   read by GPT-6 Astra through pipeline.extractor (API)

Scoring is geometric, measured from the built solid (not from the JSON):
every cylindrical face's center + diameter (placement), bbox, volume, completeness.

Windows + SolidWorks only. Run from 2D-3D-CAD-Test-Generation/:
    python demo/simple_plate/run_demo.py
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.model_validator import validate_model  # noqa: E402
from pipeline.solidworks_builder import _g, build_model, connect_to_solidworks  # noqa: E402
from pipeline.validator import run_verification  # noqa: E402
from run_models import resolve_unknowns  # noqa: E402

TRUTH = json.loads((HERE / "ground_truth.json").read_text(encoding="utf-8"))
ARMS = {"no_api": HERE / "extraction_no_api.json", "astra": HERE / "extraction_astra.json"}
POS_TOL_MM, DIA_TOL_MM = 0.1, 0.05


def measure(doc) -> dict:
    """Bbox, volume and every cylindrical face (center xy, diameter) in mm."""
    body = max(doc.GetBodies2(0, False), key=lambda b: b.GetMassProperties(1000.0)[3])
    bb = body.GetBodyBox()
    # The template's "Front Plane" is not necessarily model XY (on this SW 2025
    # install it maps to Y-Z, hole axes along X), so drop the axis coordinate and
    # keep the other two in order: those are the sketch-plane (drawing) coordinates.
    cyl = set()
    for face in _g(body, "GetFaces") or ():
        surf = _g(face, "GetSurface")
        if surf is not None and _g(surf, "IsCylinder"):
            p = _g(surf, "CylinderParams")  # [ox, oy, oz, ax, ay, az, r] meters
            axis = max(range(3), key=lambda i: abs(p[3 + i]))
            u, v = [p[i] * 1000 for i in range(3) if i != axis]
            cyl.add((round(u, 3), round(v, 3), round(2 * p[6] * 1000, 3)))
    return {
        "bbox_mm": sorted([round((bb[i + 3] - bb[i]) * 1000, 3) for i in range(3)], reverse=True),
        "volume_mm3": round(body.GetMassProperties(1000.0)[3] * 1e9, 1),
        "cylinders": [{"center": [x, y], "diameter": d} for x, y, d in sorted(cyl)],
    }


def score(m: dict) -> dict:
    """Best of the two in-plane axis orders (one global choice, never per hole)."""
    swapped = dict(m, cylinders=[dict(c, center=c["center"][::-1]) for c in m["cylinders"]])
    a, b = _score(m), _score(swapped)
    best = a if a["holes_placed"] >= b["holes_placed"] else b
    best["axis_order"] = "as-is" if best is a else "swapped"
    return best


def _score(m: dict) -> dict:
    exp = TRUTH["expected"]
    matched, errors = [], []
    for e in exp["cylinders"]:
        best = min(m["cylinders"], default=None, key=lambda c: math.dist(c["center"], e["center"])
                   + abs(c["diameter"] - e["diameter"]))
        if best is None:
            errors.append(f"missing Ø{e['diameter']} at {e['center']}")
            continue
        dpos = math.dist(best["center"], e["center"])
        ddia = abs(best["diameter"] - e["diameter"])
        ok = dpos <= POS_TOL_MM and ddia <= DIA_TOL_MM
        matched.append({"expected": e, "built": best, "pos_err_mm": round(dpos, 3),
                        "dia_err_mm": round(ddia, 3), "ok": ok})
        if not ok:
            errors.append(f"Ø{e['diameter']} at {e['center']}: built Ø{best['diameter']} at "
                          f"{best['center']} (pos err {dpos:.3f} mm)")
    bbox_ok = all(abs(a - b) <= 0.01 for a, b in zip(m["bbox_mm"], sorted(exp["bbox_mm"], reverse=True)))
    vol_err = (m["volume_mm3"] - exp["volume_mm3"]) / exp["volume_mm3"]
    return {"holes_placed": sum(x["ok"] for x in matched), "holes_expected": len(exp["cylinders"]),
            "bbox_ok": bbox_ok, "volume_err_pct": round(100 * vol_err, 3),
            "extra_cylinders": max(0, len(m["cylinders"]) - len(exp["cylinders"])),
            "matches": matched, "errors": errors}


def export_views(doc, out: Path, stem: str) -> list[str]:
    files = []
    try:
        doc.ShowNamedView2("*Isometric", 7)
        doc.ViewZoomtofit2()
    except Exception:
        pass
    def save(ext: str) -> bool:
        path = (out / f"{stem}.{ext}").resolve()
        try:
            doc.SaveAs3(str(path), 0, 1)
        except Exception:
            return False
        if path.exists():
            files.append(path.name)
        return path.exists()

    save("png") or save("jpg")   # an isometric picture of the part
    save("step")                 # neutral 3D file anyone can open
    return files


def run_arm(app, arm: str, src: Path) -> dict:
    out = HERE / f"out_{arm}"
    out.mkdir(exist_ok=True)
    data = json.loads(src.read_text(encoding="utf-8"))
    decisions, concerns = resolve_unknowns(data, "DEMO-PLATE-001")
    model, report = run_verification(data)
    if model is None or not report.ok:
        return {"arm": arm, "gate": "BLOCKED", "errors": report.errors}
    skipped: list = []
    path, doc = build_model(app, model, output_dir=out, template_path=os.getenv("SOLIDWORKS_TEMPLATE_PATH"),
                            strict=False, skipped_out=skipped)
    built = [f for f in model.build_order if f not in {s[0] for s in skipped}]
    v = validate_model(doc, model, built_feature_ids=built)
    m = measure(doc)
    files = export_views(doc, out, f"DEMO-PLATE-001_{arm}")
    return {"arm": arm, "gate": "READY", "sldprt": str(Path(path).relative_to(HERE)), "exports": files,
            "built": built, "skipped": skipped, "validator": "PASSED" if v["ok"] else "FAILED",
            "validator_failed": v["failed"], "measured": m, "score": score(m),
            "notes": [w for w in model.warnings if any(k in w for k in ("ASSUMED", "INFERRED", "realized"))],
            "decisions": decisions}


def main() -> int:
    app = connect_to_solidworks()
    results = [run_arm(app, arm, src) for arm, src in ARMS.items()]
    (HERE / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    for r in results:
        s = r.get("score", {})
        print(f"{r['arm']:7s} gate={r['gate']:7s} validator={r.get('validator')} "
              f"holes {s.get('holes_placed')}/{s.get('holes_expected')} bbox_ok={s.get('bbox_ok')} "
              f"vol_err={s.get('volume_err_pct')}% built={r.get('built')} skipped={r.get('skipped')}")
        for e in s.get("errors", []):
            print("   ", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
