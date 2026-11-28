"""End-to-end material check in the REAL pipeline and REAL SolidWorks, with no API cost (saved extraction + plan are reused).

    python tools/material_e2e.py --part A001151E --out <scratch dir> [--scenarios steel copper pla none unmatched]

Each scenario copies the part's saved extraction.json + plan.json, sets ``material_extraction`` as a drawing would, runs ``run_part`` (resolve ->
build -> native assignment -> save -> read-back -> cost -> appearance) and writes ``summary.json`` / ``summary.md`` under --out.
Nothing is claimed unless SolidWorks actually did it: a scenario that did not reach SolidWorks says so.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))

SCENARIOS = {
    "steel": {"status": "specified", "raw_text": "MATERIAL: STEEL", "normalized_candidate": "STEEL",
              "evidence": [{"page": 1, "region": "title_block", "quote": "MATERIAL: STEEL"}]},
    "copper": {"status": "specified", "raw_text": "MATERIAL: COPPER", "normalized_candidate": "COPPER",
               "evidence": [{"page": 1, "region": "title_block", "quote": "MATERIAL: COPPER"}]},
    "pla": {"status": "specified", "raw_text": "MATERIAL: PLA", "normalized_candidate": "PLA",
            "evidence": [{"page": 1, "region": "title_block", "quote": "MATERIAL: PLA"}]},
    "none": {"status": "not_specified", "raw_text": None, "normalized_candidate": None, "evidence": []},
    "unmatched": {"status": "specified", "raw_text": "MATERIAL: AISI 4140 STEEL", "normalized_candidate": "AISI 4140 steel",
                  "evidence": [{"page": 1, "region": "title_block", "quote": "MATERIAL: AISI 4140 STEEL"}]},
    "failassign": {"status": "specified", "raw_text": "MATERIAL: COMPANY ALLOY X", "normalized_candidate": "Company Alloy X",
                   "evidence": [{"page": 1, "region": "title_block", "quote": "MATERIAL: COMPANY ALLOY X"}]},
    "standard": {"status": "specified", "raw_text": "MATERIAL: PLAIN CARBON STEEL", "normalized_candidate": "Plain Carbon Steel",
                 "evidence": [{"page": 1, "region": "title_block", "quote": "MATERIAL: PLAIN CARBON STEEL"}]},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="A001151E")
    ap.add_argument("--src", type=Path, default=CODE.parent / "FINAL_OUTPUTs", help="folder holding <part>/<part>_extraction.json and plan.json")
    ap.add_argument("--drawing", type=Path, default=None, help="drawing PDF/PNG (images are only used for the saved-plan path's prompts)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scenarios", nargs="*", default=list(SCENARIOS))
    a = ap.parse_args()

    from pipeline.ir_pipeline import PartSpec, connect_sw, run_part
    drawing = a.drawing or (CODE.parent / "data" / "inputs" / "drawing_pdfs" / f"{a.part}.PDF")
    sw = connect_sw()
    app = sw[0] if isinstance(sw, tuple) else sw
    rows = []
    for name in a.scenarios:
        root = a.out / name
        pd = root / a.part
        if pd.exists():
            shutil.rmtree(pd)
        pd.mkdir(parents=True)
        ex = json.loads((a.src / a.part / f"{a.part}_extraction.json").read_text(encoding="utf-8"))
        ex["material_extraction"] = SCENARIOS[name]
        (pd / f"{a.part}_extraction.json").write_text(json.dumps(ex, indent=2), encoding="utf-8")
        shutil.copyfile(a.src / a.part / "plan.json", pd / "plan.json")
        t0 = time.time()
        row = {"scenario": name}
        import os
        os.environ.pop("SOLIDFLOW_MATERIAL_SETTINGS", None)
        if name == "failassign":     # a company catalog whose native database does not exist: the assignment must FAIL and the geometry must survive
            lib = root / "company_lib"
            lib.mkdir(parents=True, exist_ok=True)
            (lib / "materials.json").write_text(json.dumps({"schema_version": 1, "catalog_id": "co", "currency": "USD", "price_basis": "quote", "materials": [
                {"id": "alloy-x", "label": "Company Alloy X", "aliases": [], "density_kg_m3": 8000, "price_per_kg": 5.0,
                 "sw_database": "missing.sldmat", "sw_material_name": "Alloy X"}]}), encoding="utf-8")
            (lib / "missing.sldmat").write_bytes(b"")          # present but empty -> the native assignment cannot succeed
            sf = root / "settings.json"
            sf.write_text(json.dumps({"catalog_path": str(lib), "use_demo": False, "use_standard": False}), encoding="utf-8")
            os.environ["SOLIDFLOW_MATERIAL_SETTINGS"] = str(sf)
        try:
            r = run_part(PartSpec(a.part, drawing), root, [root], *( [app] if not isinstance(sw, tuple) else list(sw)), reuse_plan=True)
            row.update(sw_ok=r.sw_ok, sldprt=bool(r.sldprt), stl=bool(r.stl), error=r.error, material=r.material, secs=round(time.time() - t0, 1))
            for f in ("material_resolution.json", "material_native.json", "material_costing.json", "appearance.json"):
                p = pd / f
                row[f] = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
        except Exception as e:      # noqa: BLE001
            row.update(error=f"{type(e).__name__}: {e}", secs=round(time.time() - t0, 1))
        rows.append(row)
        m = row.get("material") or {}
        print(f"[{name}] sw_ok={row.get('sw_ok')} material={m.get('status')} cost={m.get('net_material_cost')} err={row.get('error')}", flush=True)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    lines = ["| scenario | SolidWorks built | material status | native material | density kg/m3 | mass kg | cost | note |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        nat = r.get("material_native.json") or {}
        cst = r.get("material_costing.json") or {}
        lines.append(f"| {r['scenario']} | {r.get('sw_ok')} | {(r.get('material') or {}).get('status')} | {(nat.get('actual') or {}).get('name')} | "
                     f"{nat.get('density_kg_m3')} | {cst.get('mass_kg')} | {cst.get('display', {}).get('net_material_cost') or 'unavailable'} | "
                     f"{(cst.get('reason') or r.get('error') or '')[:90]} |")
    (a.out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if all(r.get("sw_ok") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
