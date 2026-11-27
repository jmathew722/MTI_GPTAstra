"""Source-coordinate transforms for drawing replication (v8, SolidFlow_Drawing_Replication.md section 3).

Three coordinate spaces, never mixed implicitly:

* ``raw``       PDF user space: origin lower-left of the MediaBox, y up, page rotation NOT applied (what vector paths and content streams use).
* ``displayed`` the page as viewed: origin top-left of the CropBox, y down, rotation applied, units PDF points (what PyMuPDF text boxes and renders use).
* ``sheet``     SOLIDWORKS sheet coordinates: origin lower-left of the sheet, y up, metres.

``displayed -> sheet`` is  X = ox + kx * x,  Y = oy + H_sheet - ky * y  (Y inversion). ``k`` is the page-point-to-sheet-metre factor: 0.0254 / 72 when the sheet
has the page's physical size (engineering PDFs are printed 1:1), otherwise a uniform fit factor with centring, recorded so a deviation is never silent.
Pure functions, no SOLIDWORKS: unit-tested for all four rotations and crop offsets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

PT_TO_M = 0.0254 / 72.0
VALID_ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class PageBox:
    """Everything needed to move between raw and displayed space. ``media``/``crop`` are [x0, y0, x1, y1] in raw PDF user space (y up)."""
    media: tuple[float, float, float, float]
    crop: tuple[float, float, float, float]
    rotation: int = 0

    def __post_init__(self):
        if self.rotation % 360 not in VALID_ROTATIONS:
            raise ValueError(f"unsupported page rotation {self.rotation}")

    @property
    def rot(self) -> int:
        return self.rotation % 360

    @property
    def unrotated_size(self) -> tuple[float, float]:
        return (self.crop[2] - self.crop[0], self.crop[3] - self.crop[1])

    @property
    def displayed_size(self) -> tuple[float, float]:
        w, h = self.unrotated_size
        return (h, w) if self.rot in (90, 270) else (w, h)

    # ---- raw (y up, unrotated) <-> displayed (top-left, rotated)
    def raw_to_displayed(self, x: float, y: float) -> tuple[float, float]:
        W, H = self.unrotated_size
        ux, uy = x - self.crop[0], self.crop[3] - y           # unrotated, top-left, y down
        r = self.rot
        if r == 0:
            return ux, uy
        if r == 90:        # clockwise: the unrotated top-left corner becomes the top-right corner
            return H - uy, ux
        if r == 180:
            return W - ux, H - uy
        return uy, W - ux  # 270

    def displayed_to_raw(self, dx: float, dy: float) -> tuple[float, float]:
        W, H = self.unrotated_size
        r = self.rot
        if r == 0:
            ux, uy = dx, dy
        elif r == 90:
            ux, uy = dy, H - dx
        elif r == 180:
            ux, uy = W - dx, H - dy
        else:
            ux, uy = W - dy, dx
        return ux + self.crop[0], self.crop[3] - uy

    @staticmethod
    def from_fitz_page(pg) -> "PageBox":
        """Raw MediaBox/CropBox (y up) read from the page dictionary, falling back to PyMuPDF's boxes (top-left, converted)."""
        def raw(key):
            try:
                t, v = pg.parent.xref_get_key(pg.xref, key)
                if t == "array":
                    nums = [float(x) for x in v.strip("[] ").split()]
                    if len(nums) == 4:
                        return (min(nums[0], nums[2]), min(nums[1], nums[3]), max(nums[0], nums[2]), max(nums[1], nums[3]))
            except Exception:      # noqa: BLE001
                pass
            return None
        media = raw("MediaBox")
        if media is None:
            mb = pg.mediabox
            media = (mb.x0, mb.y0, mb.x1, mb.y1)
        crop = raw("CropBox") or media
        return PageBox(media, crop, int(pg.rotation))


@dataclass
class SheetFrame:
    """displayed page space (points, top-left) -> SOLIDWORKS sheet space (metres, lower-left). Built once per sheet."""
    page_w_pt: float
    page_h_pt: float
    sheet_w_m: float
    sheet_h_m: float
    k: float = PT_TO_M          # metres of sheet per page point (uniform)
    ox: float = 0.0             # centring offset when the sheet is larger than the scaled page
    oy: float = 0.0
    notes: list[str] = field(default_factory=list)

    @staticmethod
    def physical(page_w_pt: float, page_h_pt: float, sheet_w_m: Optional[float] = None, sheet_h_m: Optional[float] = None, tol: float = 0.02) -> "SheetFrame":
        """The frame for a sheet of the page's own physical size (default), or a given sheet: uniform fit + centring when the sizes differ by more than ``tol``."""
        pw, ph = page_w_pt * PT_TO_M, page_h_pt * PT_TO_M
        if sheet_w_m is None or sheet_h_m is None:
            return SheetFrame(page_w_pt, page_h_pt, pw, ph, PT_TO_M, 0.0, 0.0, ["sheet has the page's physical size (1 pt = 1/72 in)"])
        if abs(sheet_w_m - pw) / pw <= tol and abs(sheet_h_m - ph) / ph <= tol:
            # standard sheets differ from the scan by a few percent: stretch nothing, centre the page on the sheet and say so
            f = SheetFrame(page_w_pt, page_h_pt, sheet_w_m, sheet_h_m, PT_TO_M, (sheet_w_m - pw) / 2, (sheet_h_m - ph) / 2,
                           [f"page {pw * 1000:.1f} x {ph * 1000:.1f} mm centred on sheet {sheet_w_m * 1000:.1f} x {sheet_h_m * 1000:.1f} mm at true size"])
            return f
        k = min(sheet_w_m / page_w_pt, sheet_h_m / page_h_pt)
        return SheetFrame(page_w_pt, page_h_pt, sheet_w_m, sheet_h_m, k, (sheet_w_m - page_w_pt * k) / 2, (sheet_h_m - page_h_pt * k) / 2,
                          [f"page scaled by {k / PT_TO_M:.4f} to fit the sheet (uniform, centred): positions are not at physical size"])

    def to_sheet(self, x_pt: float, y_pt: float) -> tuple[float, float]:
        return (self.ox + self.k * x_pt, self.oy + (self.page_h_pt - y_pt) * self.k)

    def to_page(self, X_m: float, Y_m: float) -> tuple[float, float]:
        return ((X_m - self.ox) / self.k, self.page_h_pt - (Y_m - self.oy) / self.k)

    def norm_to_sheet(self, nx: float, ny: float) -> tuple[float, float]:
        """Normalised top-left (0..1 of the displayed page) -> sheet metres."""
        return self.to_sheet(nx * self.page_w_pt, ny * self.page_h_pt)

    def box_to_sheet(self, box_pt) -> tuple[float, float, float, float]:
        """[x0, y0, x1, y1] displayed points (top-left) -> (xmin, ymin, xmax, ymax) sheet metres (lower-left)."""
        a = self.to_sheet(box_pt[0], box_pt[3])
        b = self.to_sheet(box_pt[2], box_pt[1])
        return (a[0], a[1], b[0], b[1])

    def box_from_sheet(self, box_m) -> list[float]:
        a = self.to_page(box_m[0], box_m[3])
        b = self.to_page(box_m[2], box_m[1])
        return [a[0], a[1], b[0], b[1]]

    def mm(self, d_pt: float) -> float:
        return d_pt * self.k * 1000.0


def sheet_dims_mm(width_pt: float, height_pt: float) -> tuple[float, float]:
    return width_pt * PT_TO_M * 1000.0, height_pt * PT_TO_M * 1000.0


# Standard sheet sizes (width, height in mm, landscape) used only to NAME a sheet whose physical size matches within tolerance; never to resize it.
STANDARD_SHEETS_MM = {"ANSI A": (279.4, 215.9), "ANSI B": (431.8, 279.4), "ANSI C": (558.8, 431.8), "ANSI D": (863.6, 558.8), "ANSI E": (1117.6, 863.6),
                      "A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0), "A1": (841.0, 594.0), "A0": (1189.0, 841.0)}


def name_sheet(width_mm: float, height_mm: float, tol: float = 0.03) -> Optional[str]:
    """The standard sheet this physical size matches (either orientation) within ``tol``, else None (a non-standard sheet is reported, not snapped)."""
    a, b = max(width_mm, height_mm), min(width_mm, height_mm)
    for name, (w, h) in STANDARD_SHEETS_MM.items():
        if abs(a - w) / w <= tol and abs(b - h) / h <= tol:
            return name
    return None


def fitz_displayed_rect(pg, rect) -> list[float]:
    """PyMuPDF returns text/word/drawing boxes in UNROTATED page space (verified by tests/test_v8_srcmap.py); this maps one to the displayed (rotated,
    top-left) space every other coordinate in the pipeline uses. Identity for rotation 0."""
    import fitz
    r = fitz.Rect(rect) * pg.rotation_matrix
    r.normalize()
    return [r.x0, r.y0, r.x1, r.y1]
