"""Render the demo drawing DEMO-PLATE-001 (a mounting plate) with a KNOWN answer.

The drawing is synthetic on purpose: every dimension and position is defined
in ``ground_truth.json``, so both build paths (hand-read JSON, no API; and
GPT-6 Astra extraction, API) can be scored exactly. Run from this folder:

    python make_drawing.py        -> drawing.png
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
TRUTH = json.loads((HERE / "ground_truth.json").read_text(encoding="utf-8"))

W, H = 2400, 1650
S = 9.0                      # pixels per mm
FX, FY = 430, 960           # front view: pixel of the plate's lower-left corner
SX = FX + 100 * S + 620      # side view (right of front, third-angle): left edge
INK, THIN = (0, 0, 0), (90, 90, 90)


def font(size, bold=False):
    return ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", size)


F_DIM, F_NOTE, F_TITLE = font(30), font(30), font(34, True)
img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)


def P(x_mm, y_mm):
    """Front-view point: drawing frame (lower-left corner origin, +y up)."""
    return FX + x_mm * S, FY - y_mm * S


def arrow(x, y, dx, dy, size=16):
    import math
    a = math.atan2(dy, dx)
    for s in (0.4, -0.4):
        d.line([(x, y), (x - size * math.cos(a + s), y - size * math.sin(a + s))], fill=INK, width=3)


def hdim(x1, x2, y, text, ext_from=None):
    """Horizontal dimension between pixel x1..x2 at pixel row y."""
    if ext_from is not None:
        for x in (x1, x2):
            d.line([(x, ext_from), (x, y + (8 if y > ext_from else -8))], fill=THIN, width=2)
    d.line([(x1, y), (x2, y)], fill=INK, width=2)
    arrow(x1, y, -1, 0)
    arrow(x2, y, 1, 0)
    tw = d.textlength(text, font=F_DIM)
    d.text(((x1 + x2) / 2 - tw / 2, y - 38), text, fill=INK, font=F_DIM)


def vdim(y1, y2, x, text, ext_from=None):
    if ext_from is not None:
        for y in (y1, y2):
            d.line([(ext_from, y), (x + (8 if x > ext_from else -8), y)], fill=THIN, width=2)
    d.line([(x, y1), (x, y2)], fill=INK, width=2)
    arrow(x, y1, 0, -1 if y1 < y2 else 1)
    arrow(x, y2, 0, 1 if y1 < y2 else -1)
    tmp = Image.new("RGBA", (int(d.textlength(text, font=F_DIM)) + 4, 40), (255, 255, 255, 0))
    ImageDraw.Draw(tmp).text((2, 0), text, fill=INK, font=F_DIM)
    tmp = tmp.rotate(90, expand=True)
    img.paste(tmp, (int(x - 42), int((y1 + y2) / 2 - tmp.height / 2)), tmp)


L, Wd, T = TRUTH["plate"]["length"], TRUTH["plate"]["width"], TRUTH["plate"]["thickness"]

# ---------------- FRONT VIEW ----------------
d.rectangle([P(0, Wd), P(L, 0)], outline=INK, width=4)
holes = TRUTH["corner_holes"]
for (hx, hy) in holes["positions"]:
    cx, cy = P(hx, hy)
    r = holes["diameter"] / 2 * S
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=INK, width=3)
    d.line([(cx - r - 12, cy), (cx + r + 12, cy)], fill=THIN, width=1)
    d.line([(cx, cy - r - 12), (cx, cy + r + 12)], fill=THIN, width=1)
bore = TRUTH["center_bore"]
cx, cy = P(*bore["position"])
for rr, w in ((bore["diameter"] / 2 * S, 3), ((bore["diameter"] / 2 + bore["chamfer"]) * S, 2)):
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=INK, width=w)
d.line([(cx - 120, cy), (cx + 120, cy)], fill=THIN, width=1)
d.line([(cx, cy - 120), (cx, cy + 120)], fill=THIN, width=1)

# overall dims
hdim(*[P(0, 0)[0], P(L, 0)[0]], FY + 150, f"{L:g}", ext_from=FY)
vdim(P(0, Wd)[1], P(0, 0)[1], FX - 150, f"{Wd:g}", ext_from=FX)
# hole positions from the lower-left edges
x1, y1 = holes["positions"][0]
x2, y2 = holes["positions"][3]
hdim(P(0, 0)[0], P(x1, 0)[0], FY + 70, f"{x1:g}", ext_from=FY)
hdim(P(0, 0)[0], P(x2, 0)[0], FY + 230, f"{x2:g}", ext_from=FY)
vdim(P(0, y1)[1], P(0, 0)[1], FX - 70, f"{y1:g}", ext_from=FX)
vdim(P(0, y2)[1], P(0, 0)[1], FX - 230, f"{y2:g}", ext_from=FX)
# bore position
bx, by = bore["position"]
hdim(P(0, Wd)[0], P(bx, Wd)[0], P(0, Wd)[1] - 90, f"{bx:g}", ext_from=P(0, Wd)[1])
vdim(P(L, by)[1], P(L, 0)[1], P(L, 0)[0] + 90, f"{by:g}", ext_from=P(L, 0)[0])

# callouts (leaders)
hx, hy = P(*holes["positions"][3])
d.line([(hx + 30, hy - 30), (hx + 150, hy - 150), (hx + 330, hy - 150)], fill=INK, width=2)
d.text((hx + 160, hy - 195), f"4X Ø{holes['diameter']:g} THRU", fill=INK, font=F_NOTE)
ex = FX + L * S + 150  # callout sits in the gap right of the front view
d.line([(cx + 70, cy - 70), (cx + 160, cy - 160), (ex + 260, cy - 160)], fill=INK, width=2)
d.text((ex, cy - 205), f"Ø{bore['diameter']:g} THRU", fill=INK, font=F_NOTE)
d.text((ex, cy - 150), f"C{bore['chamfer']:g} BOTH SIDES", fill=INK, font=F_NOTE)
d.text((FX + L * S / 2 - 90, FY + 300), "FRONT VIEW", fill=INK, font=F_TITLE)

# ---------------- SIDE VIEW (right) ----------------
top = P(0, Wd)[1]
d.rectangle([SX, top, SX + T * S, FY], outline=INK, width=4)
for (hx_, hy_) in holes["positions"][:2] + [bore["position"]]:
    pass
for y in {holes["positions"][0][1], holes["positions"][3][1]}:
    r = holes["diameter"] / 2 * S
    _, py = P(0, y)
    for yy in (py - r, py + r):
        d.line([(SX, yy), (SX + T * S, yy)], fill=THIN, width=2)  # hidden hole edges
r = bore["diameter"] / 2 * S
for yy in (cy - r, cy + r):
    d.line([(SX, yy), (SX + T * S, yy)], fill=THIN, width=2)
hdim(SX, SX + T * S, FY + 150, f"{T:g}", ext_from=FY)
d.text((SX - 60, FY + 300), "RIGHT VIEW", fill=INK, font=F_TITLE)

# ---------------- TITLE BLOCK ----------------
tb = (W - 680, H - 290, W - 40, H - 30)
d.rectangle(tb, outline=INK, width=3)
lines = [("PART: MOUNTING PLATE", True), ("DWG NO: DEMO-PLATE-001  REV A", False),
         ("UNITS: MILLIMETERS", False), ("MATERIAL: 6061-T6 ALUMINUM", False),
         ("TOL: ±0.1 UNLESS NOTED   SCALE 1:1", False)]
for i, (t, b) in enumerate(lines):
    d.text((tb[0] + 20, tb[1] + 18 + i * 46), t, fill=INK, font=F_TITLE if b else F_NOTE)

img.save(HERE / "drawing.png")
print("wrote", HERE / "drawing.png")
