"""Native associative drawing creation: new SLDDRW from a validated template, model views at the planned scale and position, black annotation layer,
explicit dimension precision, SLDDRW + vector PDF output.  Every API call here was probed on SOLIDWORKS 2025 SP5 (33.5.0); see api_validation.md.
The part is only ever referenced by its path: no geometry is traced from the STL or from raster images.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from reverse import planner
from reverse.worker import CadError, CadSession

log = logging.getLogger(__name__)

IN = 0.0254
# swDwgPaperSizes_e (type library): A=0 B=2 C=3 ... A3=8 ; swDwgTemplateNone = 13
PAPER = {"ANSI_B": (2, 17 * IN, 11 * IN), "ANSI_C": (3, 22 * IN, 17 * IN), "A3": (8, 0.420, 0.297)}
TEMPLATE_NONE = 13
CRLF, LF = chr(13) + chr(10), chr(10)
SW_PAPER_USER_DEFINED = 12                # swDwgPapersUserDefined
SW_PREF_LINEAR_DIM_PRECISION = 24          # swDetailingLinearDimPrecision
SW_PREF_ANGULAR_DIM_PRECISION = 28         # swDetailingAngularDimPrecision
SW_DISP_HIDDEN_REMOVED = 2                 # swViewDisplayMode_HiddenLinesRemoved
SW_DISP_HIDDEN_GRAYED = 3
BLACK_LAYER = "SF_BLACK"
SW_EXPORT_PDF = 1                          # swExportPdfData
SW_EXPORT_ALL_SHEETS = 1                   # swExportData_ExportAllSheets


def com_doubles(*v):
    from pipeline.solidworks_builder import com_doubles as cd
    return cd(*v)


class DrawingDoc:
    def __init__(self, s: CadSession, part_path: Path, plan: dict, template: Path, units: str = "inch", config: str = "", own_sheet_format: bool = False):
        self.s = s
        self.part = Path(part_path).resolve()
        self.plan = plan
        self.template = Path(template).resolve()      # SOLIDWORKS resolves relative paths against ITS OWN working directory
        self.units = units
        self.config = config
        self.own_sheet_format = own_sheet_format     # True for our generated template: its sheet format (border, title block) is kept as is
        self.mdl = None
        self.drw = None
        self.ext = None
        self.title = ""
        self.views: dict[str, object] = {}        # role -> typed IView
        self.warnings: list[str] = []
        self.sheet_scale_record: dict = {}
        self.sheet_scales: dict = {}
        self.note_boxes: list[tuple[float, float, float, float]] = []      # (x0, y0, x1, y1) of every label we placed

    # ------------------------------------------------------------ lifecycle
    def create(self) -> None:
        T = self.s.typed
        if not self.template.is_file():
            raise CadError("The drawing template was not found. Generate or select a template first.")
        paper, w, h = PAPER[self.plan["sheet_size"]]
        if self.plan.get("sheet_custom"):         # replication: the sheet has the SOURCE page's physical size (standard size when it matches one), not the nearest template size
            paper, w, h = SW_PAPER_USER_DEFINED, float(self.plan["sheet_custom"]["w_m"]), float(self.plan["sheet_custom"]["h_m"])
        self.paper_args = (paper, w, h)
        model = T(self.s.app, "ISldWorks").NewDocument(str(self.template), paper, w, h)
        if model is None:
            raise CadError("SOLIDWORKS could not create a drawing from the template.")
        self.mdl = T(model, "IModelDoc2")
        self.drw = T(model, "IDrawingDoc")
        self.ext = T(self.mdl.Extension, "IModelDocExtension")
        self.title = str(self.mdl.GetTitle())
        first = self.plan["projection"] == "first"
        sc = self.plan["scale"]
        if not self.own_sheet_format:
            try:
                self.drw.SetupSheet5("Sheet1", paper, TEMPLATE_NONE, sc["num"] / sc["den"], 1.0, first, "", w, h, "Default", True)
            except Exception as e:      # noqa: BLE001
                self.warnings.append(f"SetupSheet5: {type(e).__name__}: {e}")
        self._document_options()
        self._black_layer()

    def set_properties(self, props: dict) -> list[str]:
        """Drawing custom properties the title block links to ($PRP:"SF_*"). Values are facts from the part or NOT SPECIFIED; never a guess."""
        errs = []
        mgr = self.ext.CustomPropertyManager("")
        for k, v in props.items():
            try:
                mgr.Add3(k, 30, str(v), 2)       # swCustomInfoText, swCustomPropertyReplaceValue
            except Exception as e:      # noqa: BLE001
                errs.append(f"{k}: {e}")
        return errs

    def set_sheet_scale(self, sc=None) -> dict:
        """The title block's SCALE field reads the SHEET scale (views carry their own). Root cause of the v7 "2:1 on a 1:2 sheet" defect, found live in v8:
        ISheet.SetScale(num, den) drives the field correctly, but creating a drawing view afterwards silently resets the sheet scale (observed: 1:2 -> 1:5), so it
        must be (re)applied AFTER the views exist and again just before every save / export. The value is read back with ISheet.GetProperties2 (items 2, 3).
        ``sc`` = (num, den) for the CURRENT sheet (additional sheets); default = the plan's scale for sheet 1."""
        sc_ = sc or (self.plan["scale"]["num"], self.plan["scale"]["den"])
        want = (float(sc_[0]), float(sc_[1]))
        rec = {"wanted": [sc_[0], sc_[1]], "applied": False, "readback": None}
        try:
            sh = self.s.typed(self.drw.GetCurrentSheet(), "ISheet")
            name = str(sh.GetName())
            self.sheet_scales[name] = (sc_[0], sc_[1])
            sh.SetScale(sc_[0], sc_[1], False, False)
            props = sh.GetProperties2()
            rec["readback"] = [props[2], props[3]]
            rec["applied"] = (abs(props[2] - want[0]) < 1e-9 and abs(props[3] - want[1]) < 1e-9)
            if not rec["applied"]:
                self.warnings.append(f"sheet scale read back {props[2]:g}:{props[3]:g}, wanted {want[0]:g}:{want[1]:g}")
        except Exception as e:      # noqa: BLE001
            self.warnings.append(f"sheet scale: {e}")
            rec["error"] = str(e)
        if sc is None:
            self.sheet_scale_record = rec
        return rec

    def reassert_sheet_scales(self) -> None:
        """Every sheet's scale again (a view created on any sheet can reset it); ends on Sheet1."""
        for name, sc_ in list(self.sheet_scales.items()):
            try:
                self.drw.ActivateSheet(name)
                self.set_sheet_scale(sc_)
            except Exception as e:      # noqa: BLE001
                self.warnings.append(f"reassert scale {name}: {e}")
        try:
            self.drw.ActivateSheet("Sheet1")
        except Exception:      # noqa: BLE001
            pass

    def activate_sheet(self, name: str) -> bool:
        try:
            return bool(self.drw.ActivateSheet(name))
        except Exception as e:      # noqa: BLE001
            self.warnings.append(f"activate {name}: {e}")
            return False

    def add_sheet(self, name: str, w_m: float, h_m: float, sc, first_angle: bool) -> None:
        """A further sheet of the source page's physical size (user-defined paper), blank (no sheet format), made current. NewSheet4 verified live on 2025 SP5."""
        ok = self.drw.NewSheet4(name, SW_PAPER_USER_DEFINED, TEMPLATE_NONE, float(sc[0]), float(sc[1]), bool(first_angle), "", float(w_m), float(h_m), "Default", 0, 0, 0, 0, 0, 0)
        if not ok:
            raise CadError(f"SOLIDWORKS could not add sheet {name}.")
        self.sheet_scales[name] = (sc[0], sc[1])
        self.s.typed(self.drw.GetCurrentSheet(), "ISheet")

    def add_view_on_sheet(self, sw_view: str, center: tuple[float, float], scale: float):
        v = self.drw.CreateDrawViewFromModelView3(str(self.part), sw_view, center[0], center[1], 0)
        if v is None:
            raise CadError(f"SOLIDWORKS could not create the {sw_view} view of the part.")
        return self._finish_view(v, scale, center)

    def _has_sheet_format(self) -> bool:
        try:
            return bool(T_sheet_format(self))
        except Exception:      # noqa: BLE001
            return False

    def _document_options(self) -> None:
        prec = 3 if self.units == "inch" else 2
        for pref, val in ((SW_PREF_LINEAR_DIM_PRECISION, prec), (SW_PREF_ANGULAR_DIM_PRECISION, 1)):
            try:
                self.ext.SetUserPreferenceInteger(pref, 0, val)
            except Exception as e:      # noqa: BLE001
                self.warnings.append(f"dimension precision {pref}: {e}")

    def _black_layer(self) -> None:
        """A dedicated layer whose colour is black, current while annotations are created: dimensions, notes and labels print black."""
        try:
            self.drw.CreateLayer2(BLACK_LAYER, "Solid Flow annotations (black)", 0x000000, 0, 1, True, True)
            self.drw.SetCurrentLayer(BLACK_LAYER)
        except Exception as e:      # noqa: BLE001
            self.warnings.append(f"black layer: {type(e).__name__}: {e}")

    # ------------------------------------------------------------ views
    def _select_view(self, view) -> bool:
        return bool(self.ext.SelectByID2(self.s.typed(view, "IView").GetName2(), "DRAWINGVIEW", 0, 0, 0, False, 0, None, 0))

    def _finish_view(self, v, scale: Optional[float], center: Optional[tuple[float, float]]):
        tv = self.s.typed(v, "IView")
        if scale:
            tv.ScaleDecimal = float(scale)
        if center:
            tv.Position = com_doubles(*center)
        try:
            tv.SetDisplayMode3(False, SW_DISP_HIDDEN_REMOVED, False, False)
        except Exception as e:      # noqa: BLE001
            self.warnings.append(f"display mode: {e}")
        return tv

    def add_base(self, role: str, sw_view: str, center: tuple[float, float], scale: float):
        v = self.drw.CreateDrawViewFromModelView3(str(self.part), sw_view, center[0], center[1], 0)
        if v is None:
            raise CadError(f"SOLIDWORKS could not create the {sw_view} view of the part.")
        self.views[role] = self._finish_view(v, scale, center)
        return self.views[role]

    def add_projected(self, role: str, parent_role: str, center: tuple[float, float], scale: float):
        if not self._select_view(self.views[parent_role]):
            raise CadError(f"Could not select the {parent_role} view to project from.")
        v = self.drw.CreateUnfoldedViewAt3(center[0], center[1], 0, False)
        if v is None:
            raise CadError(f"SOLIDWORKS could not project the {role} view.")
        self.views[role] = self._finish_view(v, None, None)       # keeps the parent's scale and alignment
        return self.views[role]

    def build_plan_views(self, extra: list[dict]) -> dict:
        """front (base) -> top / right projected -> isometric -> extra views (opposite-side holes). Returns {role: outline}."""
        r = self.plan["rects_m"]
        sc = self.plan["scale"]["num"] / self.plan["scale"]["den"]
        views = self.plan["views"]

        def ctr(k):
            x0, y0, x1, y1 = r[k]
            return ((x0 + x1) / 2, (y0 + y1) / 2)

        own = {k: v[0] / v[1] for k, v in (self.plan.get("view_scales") or {}).items()}       # replication: views that print their own scale
        self.add_base("front", views["front"], ctr("front"), own.get("front", sc))
        for role in ("top", "right"):
            if role in r:                    # replication: a projected view the source does not show is not created
                self.add_projected(role, "front", ctr(role), sc)
                if role in own:
                    tv = self.s.typed(self.views[role], "IView")
                    tv.ScaleDecimal = float(own[role])
                    tv.Position = com_doubles(*ctr(role))
        if "iso" in r and views.get("iso"):
            iso_sc = float(self.plan.get("iso_scale") or sc)
            self.add_base("iso", views["iso"], ctr("iso"), iso_sc)
            if abs(iso_sc - sc) > 1e-9:       # a view at a different scale is labelled, per drafting practice
                x0, y0, x1, y1 = r["iso"]
                self.note(f"ISOMETRIC  SCALE {_ratio(iso_sc)}", x0 + 0.003, y0 + 0.003)
        for ev in extra:
            self.add_base(ev["role"], ev["sw_view"], ev["center"], float(ev.get("scale") or sc))
        try:
            self.mdl.ViewZoomtofit2()
        except Exception:      # noqa: BLE001
            pass
        return {k: [round(x, 6) for x in self.s.typed(v, "IView").GetOutline()] for k, v in self.views.items()}

    def view_outline(self, role: str) -> list[float]:
        return [float(x) for x in self.s.typed(self.views[role], "IView").GetOutline()]

    def note(self, text: str, x: float, y: float):
        """A plain text note at a sheet position, on the black layer."""
        n = self.mdl.InsertNote(text)
        if n is None:
            return None
        tn = self.s.typed(n, "INote")
        an = self.s.typed(tn.GetAnnotation(), "IAnnotation")
        an.SetPosition2(x, y, 0)
        self.note_boxes.append((x, y - 0.002, x + 0.0026 * len(text) + 0.004, y + 0.007))
        return an

    def add_note(self, text: str, x: float, y: float, height_pt: Optional[float] = None, bold: bool = False):
        """A native, editable note (verbatim text; newline becomes a line break) on the black layer at a sheet position. Returns the IAnnotation or None."""
        self.mdl.ClearSelection2(True)            # a note made while geometry is selected grows a leader to it
        n = self.mdl.InsertNote(CRLF.join(text.replace(CRLF, LF).split(LF)))
        if n is None:
            return None
        tn = self.s.typed(n, "INote")
        an = self.s.typed(tn.GetAnnotation(), "IAnnotation")
        if height_pt:
            try:
                tf = an.GetTextFormat(0)
                tf.CharHeightInPts = float(height_pt)
                an.SetTextFormat(0, False, tf)
            except Exception as e:      # noqa: BLE001
                self.warnings.append(f"note text height: {e}")
        an.SetPosition2(x, y, 0)
        return an

    def sheet_lines(self, segments: list[tuple[float, float, float, float]], scale=None) -> int:
        """Native sheet geometry (border / title-block grid): straight sketch segments on the sheet at exact coordinates (no inference). Returns the count drawn."""
        n = 0
        # measured live (v8): sketch geometry on the sheet is multiplied by the SHEET SCALE when it is displayed (1:2 drew everything at half size and half the
        # offset), so coordinates are divided by the scale to land on the requested sheet position. Verified by registered overlay.
        sc = scale or (self.plan["scale"]["num"] / self.plan["scale"]["den"])
        segments = [(a / sc, b / sc, c / sc, d / sc) for a, b, c, d in segments]
        self.mdl.ClearSelection2(True)
        self.mdl.SketchManager.InsertSketch(True)
        self.mdl.SketchManager.AddToDB = True
        try:
            for x1, y1, x2, y2 in segments:
                if self.mdl.CreateLine2(x1, y1, 0, x2, y2, 0) is not None:
                    n += 1
        finally:
            self.mdl.SketchManager.AddToDB = False
            self.mdl.SketchManager.InsertSketch(True)
        return n

    # ------------------------------------------------------------ outputs
    def save_drawing(self, path: Path) -> None:
        self.reassert_sheet_scales()          # a view created since the last call may have reset it
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        self.mdl.ForceRebuild3(False)
        res = self.ext.SaveAs3(str(path), 0, 1, None, None, 0, 0)
        ok = res[0] if isinstance(res, tuple) else res
        if not ok or not path.is_file() or path.stat().st_size == 0:
            raise CadError(f"The drawing could not be saved ({res}).")

    def export_pdf(self, path: Path) -> None:
        """Vector PDF of ALL sheets."""
        self.reassert_sheet_scales()
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        exp = self.s.app.GetExportFileData(SW_EXPORT_PDF)
        if exp is None:
            raise CadError("SOLIDWORKS did not provide PDF export options.")
        e = self.s.typed(exp, "IExportPdfData")
        try:
            e.ViewPdfAfterSaving = False
        except Exception:      # noqa: BLE001
            pass
        try:
            ok = e.SetSheets(SW_EXPORT_ALL_SHEETS, None)
            if not ok:
                self.warnings.append("IExportPdfData.SetSheets(all) returned False; the default (all sheets) was used.")
        except Exception as ex:      # noqa: BLE001
            self.warnings.append(f"SetSheets: {ex}")
        res = self.ext.SaveAs3(str(path), 0, 1, exp, None, 0, 0)
        ok = res[0] if isinstance(res, tuple) else res
        if not ok or not path.is_file() or path.stat().st_size == 0:
            raise CadError(f"The PDF could not be exported ({res}).")

    def sheet_count(self) -> int:
        try:
            return int(self.drw.GetSheetCount())
        except Exception:      # noqa: BLE001
            return 1

    def close(self) -> None:
        if self.title:
            try:
                self.s.app.CloseDoc(self.title)
            except Exception as e:      # noqa: BLE001
                log.warning("closing drawing %s: %s", self.title, e)
            self.title = ""


def T_sheet_format(d: DrawingDoc):
    sh = d.s.typed(d.drw.GetCurrentSheet(), "ISheet")
    return sh.GetSheetFormatName() if hasattr(sh, "GetSheetFormatName") else ""


def _ratio(s: float) -> str:
    """0.5 -> '1:2', 2 -> '2:1', 0.25 -> '1:4'."""
    return f"{s:g}:1" if s >= 1 else f"1:{1 / s:g}"
