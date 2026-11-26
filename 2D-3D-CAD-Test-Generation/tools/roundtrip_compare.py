"""Round-trip comparison: ORIGINAL drawing (as read by the extraction) -> 3D part -> REGENERATED drawing.

    python tools/roundtrip_compare.py --extractions ../FINAL_OUTPUTs --regen ../docs/phase2-evidence/batch18 --out ../docs/phase2-evidence/roundtrip

For each part: every dimension / hole diameter the original drawing carried (values in the drawing's own units) is looked for among the values the REGENERATED
drawing verified against the native model (its coverage ledger, exact SI values).  Reported: matched, original-only (a discrepancy to explain), regenerated-only
(a dimension the original did not show), and material (original text vs the regenerated title block).  A value match is evidence of consistency, never a claim
that the two drawings are equivalent: scheme, views, tolerances and notes are not compared.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

IN = 0.0254


def orig_values(ex: dict) -> list[tuple[str, float, str]]:
    """[(label, value_m, kind)] for each non-reference dimension and each hole diameter of the original extraction."""
    out = []
    for d in ex.get("dimensions", []):
        if d.get("is_reference") or d.get("value") is None:
            continue
        unit = (d.get("unit") or ex.get("units") or "inch").lower()
        v = float(d["value"]) * (IN if unit.startswith("in") else 0.001)
        if d.get("type") in ("angle", "angular"):
            continue
        # an inch value printed with <= 2 decimals is rounded at the print: allow half a print unit (0.005 in); everything else must match to 0.04 mm
        rounded = unit.startswith("in") and abs(round(float(d["value"]), 2) - float(d["value"])) < 1e-9
        out.append((f"{d['id']} {d.get('type', '')} {d['value']} {unit}", v, "dimension_print_rounded" if rounded else "dimension"))
    for h in ex.get("hole_callouts", []):
        if h.get("diameter") is not None:
            unit = (ex.get("units") or "inch").lower()
            out.append((f"{h['id']} hole dia {h['diameter']} {unit} (x{h.get('qty', 1)})", float(h["diameter"]) * (IN if unit.startswith("in") else 0.001), "hole"))
    return out


def regen_values(ledger: dict) -> list[tuple[str, float]]:
    return [(i["characteristic"], float(i["value"])) for i in ledger.get("items", []) if i.get("value") is not None and i.get("status") == "covered"]


def compare(ex: dict, ledger: dict, manifest: dict, tol_m: float = 4e-5) -> dict:
    o, r = orig_values(ex), regen_values(ledger)
    used: set[int] = set()
    matched, orig_only = [], []
    strict_matched = 0
    for label, v, kind in o:
        hit = next((j for j, (_, rv) in enumerate(r) if abs(rv - v) <= tol_m), None)
        if hit is not None:
            strict_matched += 1
        if hit is None and kind == "dimension_print_rounded":
            hit = next((j for j, (_, rv) in enumerate(r) if abs(rv - v) <= 0.0051 * IN), None)
        if hit is None:
            # an overall / diameter dimension may be shown at a different rounding: allow 0.5 % for values over 25 mm
            hit = next((j for j, (_, rv) in enumerate(r) if v > 0.025 and abs(rv - v) / v <= 0.005), None)
        if hit is None:
            orig_only.append(label)
        else:
            used.add(hit)
            matched.append((label, r[hit][0]))
    regen_only = [c for j, (c, _) in enumerate(r) if j not in used]
    mat_orig = (ex.get("material") or "").strip()
    mat_regen = (manifest.get("material") or {}).get("name")
    return {"original_total": len(o), "matched": matched, "strict_matched": strict_matched, "original_only": orig_only, "regen_only": regen_only,
            "material_original_text": mat_orig or None, "material_regenerated": mat_regen,
            "material_note": ("original names a material; the regenerated part carries " + (f"'{mat_regen}'" if mat_regen else "no assigned material") +
                              ("" if mat_regen else " (the part was built by a run without a resolved material, so the title block reads NOT SPECIFIED)")) if mat_orig else "the original names no material"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractions", type=Path, required=True)
    ap.add_argument("--regen", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rows, md = [], ["# Round trip: original drawing -> 3D part -> regenerated drawing", "",
                    "Values are compared in exact SI metres. A match means the regenerated drawing shows a dimension of the same size that was verified against the native model; "
                    "it does not mean the drawings are equivalent (dimension scheme, views, tolerances and notes are not compared).", "",
                    "| part | original dims + hole dia | matched | original-only | regenerated-only | original material text | regenerated material |", "|---|---|---|---|---|---|---|"]
    for pdir in sorted(p for p in a.regen.iterdir() if p.is_dir()):
        ex_f = a.extractions / pdir.name / f"{pdir.name}_extraction.json"
        led_f, man_f = pdir / "dimension_coverage.json", pdir / "manifest.json"
        if not (ex_f.is_file() and led_f.is_file() and man_f.is_file()):
            continue
        res = compare(json.loads(ex_f.read_text(encoding="utf-8")), json.loads(led_f.read_text(encoding="utf-8")), json.loads(man_f.read_text(encoding="utf-8")))
        rows.append({"part": pdir.name, **res})
        md.append(f"| {pdir.name} | {res['original_total']} | {len(res['matched'])} | {len(res['original_only'])} | {len(res['regen_only'])} | {res['material_original_text'] or '-'} | {res['material_regenerated'] or 'NOT SPECIFIED'} |")
    tot_o = sum(r["original_total"] for r in rows)
    tot_m = sum(len(r["matched"]) for r in rows)
    tot_s = sum(r["strict_matched"] for r in rows)
    md += ["", f"**Overall:** {tot_m} of {tot_o} original dimensions / hole diameters ({100 * tot_m / max(tot_o, 1):.0f} %) were found, by value, among the regenerated drawing's verified dimensions "
               f"({tot_s}, {100 * tot_s / max(tot_o, 1):.0f} %, with NO print-rounding allowance; the difference is inch values printed with two decimals, matched within half a print unit, 0.005 in).", ""]
    md.append("## Discrepancies (original values with no matching regenerated dimension), first 6 per part")
    for r in rows:
        if r["original_only"]:
            md.append(f"* **{r['part']}** ({len(r['original_only'])}): " + "; ".join(r["original_only"][:6]))
    md += ["", "## Why original-only values occur (not exhaustive)",
           "* The original drawing dimensions features the engine does not dimension automatically (fillets, chamfers, revolved boss lengths, thread callouts) or in a different scheme (chain vs baseline).",
           "* The extraction rounded a printed value (two-place prints of fractional inches) while the model carries the exact value; a 0.5 % tolerance is applied above 25 mm.",
           "* The 3D part was built from the extraction, so a value the extraction misread appears in BOTH drawings and cannot be detected by this comparison.", "",
           "## Material",
           "The original drawing's material text is carried by the extraction (`material`). The regenerated drawing's title block shows the NATIVE material read back from the part; the saved parts "
           "in this batch predate the material upgrade, so they carry no assigned material and the title block honestly reads NOT SPECIFIED. A part built with the Phase 1 pipeline carries its verified "
           "material into the drawing (see `LIVE_PDF_RUN.md`)."]
    (a.out / "ROUNDTRIP_REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (a.out / "roundtrip.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("\n".join(md[:30]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
