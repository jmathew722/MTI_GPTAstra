"""Writes a part output folder the fidelity scorer can grade: an extraction, a build record and a REAL exported mesh
(a CadQuery plate with four through holes exported to STL). No SolidWorks, no API.

    python make_scored_part.py <final_dir> <part> good|stale|badhole|nomesh

good    : the mesh matches the extraction (green)
stale   : the exported mesh is another part's (critical, red)
badhole : one hole is 0.05 in too large and one is 0.5 in out of pitch (hole and placement issues, not green)
nomesh  : the SolidWorks part exists but no STL was exported (incomplete)
"""
import json
import sys
from pathlib import Path

import cadquery as cq

IN = 25.4


def plate(size=(6.0, 4.0, 0.5), holes=((1.0, 1.0), (5.0, 1.0), (1.0, 3.0), (5.0, 3.0)), d=0.344, big=None):
    L, W, T = [v * IN for v in size]
    p = cq.Workplane("XY").box(L, W, T, centered=False)
    for k, (x, y) in enumerate(holes):
        dd = d + (0.05 if big == k else 0.0)
        p = p.faces(">Z").workplane(origin=(0, 0, T)).pushPoints([(x * IN, y * IN)]).hole(dd * IN)
    return p


def main() -> int:
    final, part, kind = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    out = final / part
    out.mkdir(parents=True, exist_ok=True)
    holes = ((1.0, 1.0), (5.0, 1.0), (1.0, 3.0), (5.0, 3.0))
    if kind == "stale":
        solid = plate(size=(4.375, 5.0, 2.25), holes=())
    elif kind == "badhole":
        solid = plate(holes=((1.0, 1.0), (5.0, 1.0), (1.0, 3.0), (4.5, 3.0)), big=0)
    else:
        solid = plate()
    (out / "x_ir.SLDPRT").write_bytes(b"sldprt")
    if kind != "nomesh":
        cq.exporters.export(solid, str(out / "x_ir.STL"), exportType="STL", tolerance=0.001, angularTolerance=0.05)
    ext = {"units": "inch", "confidence": 0.93, "warnings": [],
           "features": [{"id": "F001", "type": "extrude_boss", "description": "plate"}, {"id": "F002", "type": "hole", "description": "four 0.344 holes"}],
           "dimensions": [{"id": f"D00{i}", "type": "linear", "value": v, "applies_to": n, "feature_ref": "F001", "tolerance_plus": 0.01, "tolerance_minus": 0.01}
                          for i, (n, v) in enumerate(zip(("overall_length", "overall_width", "plate_thickness"), (6.0, 4.0, 0.5)), 1)],
           "hole_callouts": [{"id": "H001", "type": "thru", "diameter": 0.344, "thru": True, "depth": 0.0, "qty": 4, "position_known": True, "pattern": "linear",
                              "instance_positions": [list(h) for h in holes]}]}
    (out / f"{part}_extraction.json").write_text(json.dumps(ext))
    (out / "ir_report.json").write_text(json.dumps({"sw_ok": True, "sw_features": {"F001": "built", "F002": "built"}, "defaults": [], "questions": [], "flagged": []}))
    (out / "feature_map.json").write_text(json.dumps({"units": "inch", "bbox": [0, 0, 0, 6.0, 4.0, 0.5]}))
    print(json.dumps({"part": part, "kind": kind}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
