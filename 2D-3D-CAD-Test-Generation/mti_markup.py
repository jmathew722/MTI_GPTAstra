#!/usr/bin/env python3
"""Mark up a COPY of MTI's drawing with the discrepancies (spec 2026-11-02-discrepancy-markup-design.md).

Reads <out>/<part>/discrepancies.json (from mti_discrepancy.py) and, if present,
<out>/<part>/markup_positions.json (precise boxes on the sheet, in PDF points). Writes
<out>/<part>/<part>_discrepancy_markup.pdf:

* page 1: the drawing, unchanged, with a summary panel in a strip added to its right (so nothing on
  the sheet is covered) and numbered boxes/rings where positions are known;
* page 2: the full report (pieces, causes, open questions, default rules applied).

The output is MTI's drawing: local only, never committed. No API cost.

    python mti_markup.py --out <output dir> 2N2664 ...

markup_positions.json:
    {"items": [{"n": 1, "label": "...", "rect": [x0, y0, x1, y1], "shape": "box"|"ring", "color": "red"|"blue"}]}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path

PANEL_W = 620          # points added to the right of the sheet
COLORS = {"red": (0.85, 0.05, 0.05), "blue": (0.0, 0.3, 0.8), "green": (0.0, 0.5, 0.2)}


def drawing_pdf(d: Path) -> Path | None:
    src = d / "source"
    pdfs = sorted(p for p in src.glob("*") if p.suffix.lower() == ".pdf") if src.is_dir() else []
    return pdfs[0] if pdfs else None


def panel_lines(r: dict) -> list[str]:
    lines = [f"{r['part']} vs MTI's own model",
             f"Overlap {r['iou'] * 100:.2f}% - gap {r['gap_pct']:.2f}% ({r['explained_pct']:.2f}% explained below)", ""]
    for i, p in enumerate(r["pieces"], 1):
        who = "we have extra" if p["side"] == "ours" else "we lack"
        lines.append(f"{i}. {p['share_of_union_pct']:.3f}%  {p['kind']}, {who}: {p['cause']}")
    if r.get("questions"):
        lines += ["", "Open questions (not built, asked instead of guessed):"] + [f"- {q}" for q in r["questions"]]
    if r.get("defaults"):
        lines += ["", "Default rules applied:"] + [f"- {d}" for d in r["defaults"]]
    return lines


def wrap(lines: list[str], width: int) -> str:
    out = []
    for ln in lines:
        out += textwrap.wrap(ln, width, subsequent_indent="   ") or [""]
    return "\n".join(out)


def auto_positions(d: Path, r: dict, pdf: Path) -> dict:
    """Positions from OCR (pipeline/ocr_locate.py) for the callouts behind each discrepancy:
    open questions and skipped features (their source callouts), general-note rings (the note).
    Numbers match the panel. Saved as markup_positions.auto.json for review."""
    from pipeline.ocr_locate import locate, ocr_boxes
    boxes = ocr_boxes(pdf, d / "ocr.json")
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))["plan"] if (d / "plan.json").exists() else {"features": []}
    callouts = {f["id"]: f.get("source_callouts", []) for f in plan["features"]}
    items, done = [], set()
    for i, p in enumerate(r["pieces"], 1):
        if p["kind"] == "ring" and "general note" in p["cause"]:
            keys = ["ALL CHAMFERS" if p["side"] == "ours" else "ALL RADII"]
            color = "red"
        else:
            fids = re.findall(r"\bF\d{3}\b", p["cause"])
            keys = [c for fid in fids for c in callouts.get(fid, [])]
            color = "red" if "question" in p["cause"] else "blue"
        for c, rect in locate(keys, boxes).items():
            if c in done:
                continue
            done.add(c)
            items.append({"n": i, "label": f"{i}: {c}", "rect": [rect[0] - 3, rect[1] - 3, rect[2] + 3, rect[3] + 3],
                          "shape": "box", "color": color})
    out = {"source": "rapidocr (automatic; check before sharing)", "items": items}
    (d / "markup_positions.auto.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def markup(d: Path, part: str, ocr: bool = True, developer_override_positions: bool = False) -> Path:
    import pymupdf as fitz
    r = json.loads((d / "discrepancies.json").read_text(encoding="utf-8"))
    pdf = drawing_pdf(d)
    if pdf is None:
        raise FileNotFoundError(f"no drawing PDF in {d / 'source'}")
    src = fitz.open(pdf)
    W, H = src[0].rect.width, src[0].rect.height
    doc = fitz.open()
    page = doc.new_page(width=W + PANEL_W, height=H)
    page.show_pdf_page(fitz.Rect(0, 0, W, H), src, 0)
    fs = max(9.0, min(14.0, H / 110))
    page.draw_rect(fitz.Rect(W, 0, W + PANEL_W, H), color=None, fill=(1, 0.98, 0.93))
    page.draw_line(fitz.Point(W, 0), fitz.Point(W, H), color=COLORS["red"], width=2)
    page.insert_textbox(fitz.Rect(W + 18, 18, W + PANEL_W - 18, H - 18),
                        wrap(panel_lines(r), int((PANEL_W - 36) / (fs * 0.52))),
                        fontsize=fs, fontname="helv", color=(0.15, 0.0, 0.0))
    # A hand-authored positions file is a DEVELOPER diagnostic only. The production path places every
    # box automatically (pipeline/flag_overlays.py); it never reads this file (Stage 3).
    pos = d / "markup_positions.json"
    if developer_override_positions and pos.exists():
        spec = json.loads(pos.read_text(encoding="utf-8"))
        spec["provenance"] = "developer_override"
    else:
        spec = auto_positions(d, r, pdf) if ocr else {"items": []}
    if spec.get("items"):
        for it in spec["items"]:
            rect, col = fitz.Rect(*it["rect"]), COLORS.get(it.get("color", "red"), COLORS["red"])
            a = page.add_circle_annot(rect) if it.get("shape") == "ring" else page.add_rect_annot(rect)
            a.set_colors(stroke=col)
            a.set_border(width=2.2)
            a.set_info(content=it.get("label", ""))
            a.update()
            if it.get("n") and not it.get("label", "").startswith("_"):
                page.insert_text(fitz.Point(rect.x1 + 3, rect.y0 + fs), str(it["n"]), fontsize=fs * 1.3,
                                 fontname="hebo", color=col)
    rep = doc.new_page(width=612, height=792)
    body = wrap(panel_lines(r) + ["", "General notes found on the drawing:"] +
                [f"- {n}" for n in r.get("general_notes", [])] +
                ["", "Each piece is material that differs after aligning our part on MTI's model (fuzzy "
                 "booleans, 0.01 mm). 'we have extra' = MTI removed it and we didn't; 'we lack' = MTI kept "
                 "it and we removed it (or MTI added a fillet). Shares are of the union volume, so they add "
                 "up to the overlap gap."], 98)
    rep.insert_textbox(fitz.Rect(40, 40, 572, 752), body, fontsize=8.5, fontname="helv")
    out = d / f"{part}_discrepancy_markup.pdf"
    doc.save(out, garbage=3, deflate=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("parts", nargs="+")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--no-ocr", action="store_true", help="no automatic positions (panel and report only)")
    ap.add_argument("--developer-override-positions", action="store_true",
                    help="DEVELOPER ONLY: use a hand-authored markup_positions.json instead of automatic placement "
                         "(labeled provenance 'developer_override'; never used by the pipeline)")
    args = ap.parse_args()
    for part in args.parts:
        try:
            print(part, markup(args.out / part, part, ocr=not args.no_ocr,
                               developer_override_positions=args.developer_override_positions), flush=True)
        except Exception as e:
            print(part, "FAILED", f"{type(e).__name__}: {e}"[:200], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
