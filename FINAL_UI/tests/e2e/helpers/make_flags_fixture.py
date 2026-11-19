"""Deterministic acceptance fixture for automatic engineering flags (Stage 3, task 3.7).

Builds a drawing PDF with known callouts, a synthetic run folder describing known model mismatches tied to
those callouts, then runs the REAL pipeline stage (``pipeline.flag_overlays.write_flags``). Nothing here
positions a flag: there is no coordinate for any overlay in this file. It only reports where the callout
pixels really are in the rendered image, so the test can check the automatic result independently.

    python make_flags_fixture.py --out <FINAL_OUTPUTs> --part NAME --rotation 0|90|180|270 --variant main|ambiguous
Prints one JSON object: paths, the drawing's SHA-256 and the callout pixel boxes in the rendered PNG.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4] / "2D-3D-CAD-Test-Generation"
sys.path.insert(0, str(REPO))

import pymupdf  # noqa: E402

from pipeline.flag_overlays import sha256_file, write_flags  # noqa: E402

BLUE = (0.0, 0.0, 1.0)
CALLOUT_TAP = "M6 X 1 - 12 DEEP"                 # flag 1: the tapped hole depth mismatch from the architecture example
CALLOUT_EDGE = "BREAK ALL EDGES .02 MAX"          # flag 2
CALLOUT_DUP = "2X Ø.250 THRU"               # appears twice: the pipeline must refuse to guess
CALLOUT_MISSING = "NOT ON THE DRAWING <img src=x onerror=alert(1)>"   # hostile text that is on no sheet
CALLOUT_P2 = "2X Ø.500 CBORE .12 DEEP"                                  # sheet 2 only (the --markup variants)


def build_pdf(path: Path, rotation: int, variant: str, pages: int = 1) -> None:
    doc = pymupdf.open()
    pg = doc.new_page(width=600, height=400)
    pg.draw_rect(pymupdf.Rect(20, 20, 580, 380), color=(0, 0, 0), width=1)
    pg.insert_text((40, 50), "SAMPLE PART  REV A   SCALE 1:1", fontsize=11)          # black title block text
    pg.insert_text((40, 360), "UNLESS OTHERWISE SPECIFIED", fontsize=9)
    pg.insert_text((60, 120), CALLOUT_TAP, fontsize=14, color=BLUE)
    pg.insert_text((330, 300), CALLOUT_EDGE, fontsize=14, color=BLUE)
    if variant == "ambiguous":
        pg.insert_text((60, 210), CALLOUT_DUP, fontsize=14, color=BLUE)
        pg.insert_text((330, 210), CALLOUT_DUP, fontsize=14, color=BLUE)
    pg.set_rotation(rotation)
    for n in range(2, pages + 1):                      # further sheets: the issue on sheet 2 must open sheet 2
        p2 = doc.new_page(width=600, height=400)
        p2.draw_rect(pymupdf.Rect(20, 20, 580, 380), color=(0, 0, 0), width=1)
        p2.insert_text((40, 50), f"SAMPLE PART  SHEET {n}", fontsize=11)
        p2.insert_text((200, 250), CALLOUT_P2, fontsize=14, color=BLUE)
    doc.save(path)


def blue_boxes(png_pixmap, n_expected):
    """Bounding boxes of the blue callout text in the rendered page, one per text line (rows grouped by gaps)."""
    w, h = png_pixmap.width, png_pixmap.height
    pts = []
    for y in range(h):
        for x in range(w):
            r, g, b = png_pixmap.pixel(x, y)[:3]
            if b > 180 and r < 90 and g < 90:
                pts.append((x, y))
    return pts


def cluster(points, gap=12):
    """Group blue pixels into text blocks (connected by < gap px)."""
    blocks = []
    for x, y in sorted(points, key=lambda p: (p[1], p[0])):
        for b in blocks:
            if b[0] - gap <= x <= b[2] + gap and b[1] - gap <= y <= b[3] + gap:
                b[0], b[1], b[2], b[3] = min(b[0], x), min(b[1], y), max(b[2], x), max(b[3], y)
                break
        else:
            blocks.append([x, y, x, y])
    merged = True
    while merged:                                      # merge blocks that grew into each other
        merged = False
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                a, c = blocks[i], blocks[j]
                if a[0] - gap <= c[2] and c[0] - gap <= a[2] and a[1] - gap <= c[3] and c[1] - gap <= a[3]:
                    blocks[i] = [min(a[0], c[0]), min(a[1], c[1]), max(a[2], c[2]), max(a[3], c[3])]
                    del blocks[j]
                    merged = True
                    break
            if merged:
                break
    return sorted(blocks, key=lambda b: (b[1], b[0]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--part", required=True)
    ap.add_argument("--rotation", type=int, default=0)
    ap.add_argument("--variant", choices=("main", "ambiguous"), default="main")
    ap.add_argument("--workdir", type=Path, required=True)
    ap.add_argument("--markup", choices=("none", "main", "clean", "fail"), default="none",
                    help="also run the REAL post-run Engineering Markup stage (main: two sheets, one unlocated flag; clean: no flags; fail: generator forced to fail)")
    ap.add_argument("--alt", action="store_true", help="also write a different revision of the drawing (for the stale test)")
    a = ap.parse_args()
    a.workdir.mkdir(parents=True, exist_ok=True)
    pdf = a.workdir / f"{a.part}.pdf"
    build_pdf(pdf, a.rotation, a.variant, pages=2 if a.markup == "main" else 1)
    pix = pymupdf.open(pdf)[0].get_pixmap(dpi=100)
    png = a.workdir / f"{a.part}.png"
    pix.save(png)

    run = a.out / a.part
    run.mkdir(parents=True, exist_ok=True)
    feats = [{"id": "F003", "kind": "hole", "source_callouts": [CALLOUT_TAP]},
             {"id": "F005", "kind": "chamfer", "source_callouts": [CALLOUT_EDGE]},
             {"id": "F006", "kind": "hole", "source_callouts": [CALLOUT_MISSING]}]
    report = {"part": a.part, "gate1": "OK", "planned": 3, "sw_ok": None, "error": "",
              "cq_skipped": {"F003": "no thread depth was extracted", "F005": "edge break not applied", "F006": "callout unreadable"},
              "questions": [], "sw_features": {}, "mti_review": []}
    if a.variant == "ambiguous":
        feats.append({"id": "F004", "kind": "hole", "source_callouts": [CALLOUT_DUP]})
        report["questions"] = ["F004: hole diameter unreadable"]
    (run / "plan.json").write_text(json.dumps({"plan": {"features": feats}}), encoding="utf-8")
    (run / "ir_report.json").write_text(json.dumps(report), encoding="utf-8")
    for stale in run.glob("markup_positions*.json"):          # the production path never reads these; make sure none exist
        stale.unlink()
    if a.markup == "clean":
        report = {"part": a.part, "gate1": "OK", "planned": 1, "sw_ok": True, "error": "", "cq_skipped": {}, "questions": [],
                  "sw_features": {}, "mti_review": []}
        (run / "ir_report.json").write_text(json.dumps(report), encoding="utf-8")
    if a.markup == "main":
        feats.append({"id": "F007", "kind": "hole", "source_callouts": [CALLOUT_P2]})
        report["cq_skipped"]["F007"] = "counterbore depth reads .10, drawing says .12"
        (run / "plan.json").write_text(json.dumps({"plan": {"features": feats}}), encoding="utf-8")
        (run / "ir_report.json").write_text(json.dumps(report), encoding="utf-8")
    summary = write_flags(run, pdf, run_id="run_fixture_" + a.part)
    if a.markup != "none":
        sys.path.insert(0, str(REPO))
        from pipeline import engineering_markup as em
        if a.markup == "fail":
            def _boom(*_a, **_k):
                raise RuntimeError("forced generator failure for the acceptance test")
            em.render_marked_pdf = _boom
        summary["markup"] = em.finalize_markup(run, pdf, run_id="run_fixture_" + a.part, part=a.part)

    blocks = cluster(blue_boxes(pix, 2))
    # An independent oracle for where each callout is in the rendered image: PyMuPDF's own text search (not the
    # pipeline's locator), taken through the page rotation into the 100 dpi raster.
    page = pymupdf.open(pdf)[0]
    expected_px = {}
    for key, text in (("tap", CALLOUT_TAP), ("edge", CALLOUT_EDGE)):
        r = (page.search_for(text)[0] * page.rotation_matrix).normalize()
        expected_px[key] = [r.x0 * 100 / 72, r.y0 * 100 / 72, r.x1 * 100 / 72, r.y1 * 100 / 72]
    out = {"pdf": str(pdf), "png": str(png), "sha256": sha256_file(pdf), "png_size": [pix.width, pix.height],
           "blue_blocks": blocks, "expected_px": expected_px, "summary": summary, "run_dir": str(run)}
    if a.alt:
        alt = a.workdir / f"{a.part}_rev_b.pdf"
        d = pymupdf.open()
        d.new_page(width=600, height=400).insert_text((60, 120), "A DIFFERENT REVISION", fontsize=14)
        d.save(alt)
        out["alt_pdf"] = str(alt)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
