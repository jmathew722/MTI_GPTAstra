"""Builds a mixed batch folder for the v4 e2e tests: real PDFs (one multi-page), images with upper/lower-case extensions,
and the bad inputs a batch has to survive. No pipeline, no API.

    python make_batch_folder.py <dir>      prints one JSON object describing what was written
"""
import json
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw


def pdf(path: Path, pages: int, label: str):
    doc = fitz.open()
    for i in range(pages):
        pg = doc.new_page(width=842, height=595)
        pg.insert_text((60, 60), f"{label} page {i + 1}", fontsize=22)
        pg.draw_rect(fitz.Rect(70, 100, 770, 520))
        pg.draw_circle(fitz.Point(420, 310), 60)
    doc.save(str(path))
    doc.close()


def img(path: Path, fmt: str, label: str):
    im = Image.new("RGB", (800, 560), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((60, 80, 740, 480), outline="black", width=3)
    d.text((70, 40), label, fill="black")
    im.save(path, fmt)


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    pdf(out / "Alpha Bracket (rev 2).pdf", 2, "ALPHA")
    pdf(out / "BETA.PDF", 1, "BETA")
    img(out / "gamma.PNG", "PNG", "GAMMA")
    img(out / "delta.JPG", "JPEG", "DELTA")
    img(out / "epsilon.jpeg", "JPEG", "EPSILON")
    (out / "corrupt.pdf").write_bytes(b"%PDF-1.4\nthis is not really a pdf, it is garbage\n" * 3)
    img(out / "renamed.pdf", "PNG", "PNG IN A PDF NAME")
    (out / "empty.pdf").write_bytes(b"")
    (out / "notes.docx").write_bytes(b"PK\x03\x04 not a drawing")
    (out / ".DS_Store").write_bytes(b"x")
    print(json.dumps({"dir": str(out), "valid": ["Alpha_Bracket_rev_2", "BETA", "gamma", "delta", "epsilon"],
                      "pages": {"Alpha_Bracket_rev_2": 2, "BETA": 1}, "bad": ["corrupt.pdf", "renamed.pdf"],
                      "skipped": ["empty.pdf", "notes.docx"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
