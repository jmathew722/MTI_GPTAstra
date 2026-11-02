#!/usr/bin/env python3
"""Explain the gap between our part and MTI's own model (spec 2026-11-02-discrepancy-markup-design.md).

For each part folder (reference.step, ground_truth.step, plan.json, ir_report.json):
align ours onto MTI's model, split the difference into pieces (material only we have, material only
MTI has), classify each piece (edge-treatment ring, pocket, slab), attribute it to a cause (an open
question, a general note, a skipped feature) and write <part>/discrepancies.json. With several
parts, causes are ranked by the overlap they cost: <out>/discrepancy_summary.json. No API cost.

    python mti_discrepancy.py --out <output dir> 2N2664 A00122E ...
    python mti_discrepancy.py --out <output dir> --all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MIN_PIECE_IN3 = 0.0005      # ignore slivers below this
# MTI's model differs from its own drawing, or the files are swapped (docs/mti-questions/):
# their gaps are data questions for MTI, not pipeline causes, so they stay out of the ranking.
MODEL_MISMATCH = {"SB12009", "SB14306", "A00161E", "SB12050", "SB12051"}
RING_THIN_IN = 0.1          # a ring is thin in one direction...
RING_ROUND_TOL = 0.01       # ...and round in the other two (extents within 1%)
FUZZY_MM = 0.01             # fuzzy booleans (E033)
GENERAL_NOTE = re.compile(r"\bALL\s+(CHAMFERS|RADII|FILLETS|SHARP|EDGES)\b|\bBREAK\b.*\b(EDGES|CORNERS)\b|"
                          r"UNLESS\s+OTHERWISE\s+SPECIFIED", re.I)


def classify(piece, k: float) -> dict:
    bb = piece.BoundingBox()
    ext = [bb.xlen / k, bb.ylen / k, bb.zlen / k]
    order = sorted(range(3), key=lambda i: ext[i])
    thin, a, b = ext[order[0]], ext[order[1]], ext[order[2]]
    row = {"volume_in3": round(piece.Volume() / k ** 3, 5),
           "size_in": [round(e, 3) for e in ext],
           "center_in": [round((lo + hi) / 2 / k, 3) for lo, hi in
                         ((bb.xmin, bb.xmax), (bb.ymin, bb.ymax), (bb.zmin, bb.zmax))]}
    if thin <= RING_THIN_IN and abs(a - b) <= RING_ROUND_TOL * b and b > 4 * thin:
        row.update(kind="ring", diameter_in=round(b, 3), thickness_in=round(thin, 3), axis="XYZ"[order[0]])
    elif max(ext) <= 3 * min(ext) + 0.2:
        row.update(kind="pocket")
    else:
        row.update(kind="slab")
    return row


def general_notes(out: Path, part: str) -> list[str]:
    """Drawing-wide notes that apply to unnamed edges, from the plan's callouts and the extraction."""
    texts = []
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))["plan"]
    for f in plan["features"]:
        texts += f.get("source_callouts", [])
    ex = out / f"{part}_extraction.json"
    if ex.exists():
        x = json.loads(ex.read_text(encoding="utf-8"))
        texts += [d.get("notes", "") for d in x.get("dimensions", [])] + list(x.get("warnings", []))
    seen, out_notes = set(), []
    for t in texts:
        if t and GENERAL_NOTE.search(t) and t not in seen:
            seen.add(t)
            out_notes.append(t)
    return out_notes


def attribute(row: dict, side: str, notes: list[str], questions: list[str], skipped: dict) -> str:
    """Best-guess cause of one piece. 'ours' = material only we have, 'mti' = only MTI has."""
    if row["kind"] == "ring":
        what = ("an edge break / chamfer MTI has and we don't" if side == "ours"
                else "an inside fillet MTI has and we don't")
        size = f"~{row['thickness_in']:.3f} at dia {row['diameter_in']:.3f}"
        chamfer = [n for n in notes if re.search(r"CHAMFER|BREAK", n, re.I)]
        radius = [n for n in notes if re.search(r"RADI|FILLET", n, re.I)]
        note = (chamfer if side == "ours" else radius) or notes
        return f"{what} ({size})" + (f"; general note: \"{note[0][:70]}\"" if note else "")
    if side == "ours" and questions:
        return f"material where MTI cut something we didn't; open question(s): {'; '.join(q[:90] for q in questions[:2])}"
    if side == "ours" and skipped:
        return f"material where MTI cut something we didn't; skipped: {', '.join(list(skipped)[:3])}"
    if side == "mti" and skipped:
        return f"material MTI has that we cut away; check skipped/changed: {', '.join(list(skipped)[:3])}"
    return "unattributed: compare the drawing at this location"


def analyse(out: Path, part: str) -> dict:
    import cadquery as cq
    from pipeline.ir.score import aligned, boolean, clocked, iou

    k = 25.4
    ours, gt = out / "reference.step", out / "ground_truth.step"
    if not ours.exists() or not gt.exists():
        return {"part": part, "error": "missing reference.step or ground_truth.step"}
    a = cq.importers.importStep(str(ours)).val()
    b = cq.importers.importStep(str(gt)).val()
    value, key = iou(a, b)
    if key is None:
        return {"part": part, "error": "no alignment (sizes differ by more than 5%: a model-vs-drawing mismatch?)",
                "iou": round(value, 4)}
    c = aligned(a, b, key)
    cv, ang, c = clocked(c, b, base=value)
    rep = json.loads((out / "ir_report.json").read_text(encoding="utf-8")) if (out / "ir_report.json").exists() else {}
    questions, skipped = rep.get("questions", []), rep.get("cq_skipped", {})
    notes = general_notes(out, part)
    gap = 100 * (1 - cv)
    # The pieces must add up to the gap: a boolean that fails quietly returns whole parts as
    # "differences" (SB12006: pieces "explaining" 99.998% of a 0.003% gap). Try modes in turn (E034).
    modes = ((boolean, FUZZY_MM), (boolean, None),
             (lambda kind, x, y, tol: {"cut": x.cut, "fuse": x.fuse}[kind](y, tol=tol), FUZZY_MM))
    pieces, explained, reliable = [], 0.0, False
    for op, tol in modes:
        try:
            union = op("fuse", c, b, tol).Volume()
            diffs = (("ours", op("cut", c, b, tol)), ("mti", op("cut", b, c, tol)))
        except Exception:
            continue
        pieces = []
        for side, diff in diffs:
            for s in diff.Solids():
                if s.Volume() / k ** 3 < MIN_PIECE_IN3:
                    continue
                row = classify(s, k)
                row["side"] = side
                row["share_of_union_pct"] = round(s.Volume() / union * 100, 3)
                row["cause"] = attribute(row, side, notes, questions, skipped)
                pieces.append(row)
        explained = sum(p["share_of_union_pct"] for p in pieces)
        if abs(explained - gap) <= 0.25 * abs(gap) + 0.01 and 0 <= cv <= 1.0001:
            reliable = True
            break
    pieces.sort(key=lambda r: -r["volume_in3"])
    return {"part": part, "iou": round(cv, 5), "gap_pct": round(gap, 3), "clock_deg": ang,
            "explained_pct": round(explained, 3), "reliable": reliable, "general_notes": notes,
            "questions": questions, "defaults": rep.get("defaults", []), "skipped": skipped,
            "pieces": pieces if reliable else []}


def bucket(p: dict) -> str:
    if p["kind"] == "ring":
        return "edge treatment on unnamed edges (general note)" if "general note" in p["cause"] else "edge treatment"
    if "open question" in p["cause"]:
        return "open question (feature not built)"
    if "skipped" in p["cause"]:
        return "skipped feature"
    return "unattributed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("parts", nargs="*")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--all", action="store_true", help="every <out>/<part> with both STEP files")
    ap.add_argument("--max-iou", type=float, default=0.99995, help="skip parts already this close")
    args = ap.parse_args()
    parts = args.parts or ([d.name for d in sorted(args.out.iterdir())
                            if (d / "reference.step").exists() and (d / "ground_truth.step").exists()]
                           if args.all else [])
    rows, causes = [], {}
    for part in parts:
        try:
            r = analyse(args.out / part, part)
        except Exception as e:      # one bad part never stops the batch
            r = {"part": part, "error": f"{type(e).__name__}: {e}"[:200]}
        if "pieces" in r:
            (args.out / part / "discrepancies.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
            if r["iou"] < args.max_iou and part not in MODEL_MISMATCH:
                for p in r["pieces"]:
                    causes.setdefault(bucket(p), [0.0, set()])
                    causes[bucket(p)][0] += p["share_of_union_pct"]
                    causes[bucket(p)][1].add(part)
        rows.append({k: r.get(k) for k in ("part", "iou", "gap_pct", "explained_pct", "reliable", "error")})
        print(json.dumps(rows[-1]), flush=True)
    ranked = sorted(([c, round(v[0], 3), sorted(v[1])] for c, v in causes.items()), key=lambda x: -x[1])
    (args.out / "discrepancy_summary.json").write_text(json.dumps({"parts": rows, "ranked_causes": [
        {"cause": c, "total_share_pct": t, "parts": p} for c, t, p in ranked]}, indent=2), encoding="utf-8")
    for c, t, p in ranked:
        print(f"  {t:7.3f}%  {c}  ({len(p)} parts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
