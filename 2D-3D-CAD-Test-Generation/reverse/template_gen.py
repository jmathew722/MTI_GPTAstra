"""Generate the real native default drawing templates (.drwdot + .slddrt) in SOLIDWORKS from the installed stock template as a seed.

ANSI B landscape (17 x 11 in) is the default; ANSI C and metric A3 are optional variants.  The sheet format holds a border, a title block, a notes
area and notes that LINK to drawing custom properties (SF_*), which the engine fills from the part: nothing is typed into the template.  Missing
information reads NOT SPECIFIED, never a plausible default.  All linework and text are on a black layer.  A template is only kept if SOLIDWORKS
creates a clean drawing from it (validated), and a blank preview PDF is exported next to it.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from reverse import planner, safety, templates, worker
from reverse.drawing import BLACK_LAYER, PAPER

log = logging.getLogger(__name__)

# the drawing custom properties the title block links to (SF_* so they never collide with the part's own properties)
PROPS = ("SF_Company", "SF_PartName", "SF_PartNumber", "SF_Material", "SF_Finish", "SF_Revision", "SF_Units", "SF_Projection", "SF_Status",
         "SF_DrawnBy", "SF_CheckedBy", "SF_Date", "SF_Source", "SF_Config")
VARIANTS = {"solidflow-ansi-b": ("ANSI_B", "Solid Flow ANSI B landscape (17x11 in), third angle"),
            "solidflow-ansi-c": ("ANSI_C", "Solid Flow ANSI C landscape (22x17 in), third angle"),
            "solidflow-a3": ("A3", "Solid Flow metric A3 landscape, third angle")}


def _line(mdl, x1, y1, x2, y2):
    return mdl.CreateLine2(x1, y1, 0, x2, y2, 0)


def _rect(mdl, r: planner.Rect):
    _line(mdl, r.x0, r.y0, r.x1, r.y0)
    _line(mdl, r.x1, r.y0, r.x1, r.y1)
    _line(mdl, r.x1, r.y1, r.x0, r.y1)
    _line(mdl, r.x0, r.y1, r.x0, r.y0)


TEXT_PT = 7.0        # title-block text size in points (caption and value together); readable on a 17x11 in print


def _note(s: worker.CadSession, mdl, text: str, x: float, y: float):
    mdl.ClearSelection2(True)            # a note made while geometry is selected grows a leader to it
    n = mdl.InsertNote(text)
    if n is None:
        return None
    tn = s.typed(n, "INote")
    an = s.typed(tn.GetAnnotation(), "IAnnotation")
    try:
        tf = an.GetTextFormat(0)
        tf.CharHeightInPts = TEXT_PT
        an.SetTextFormat(0, False, tf)
    except Exception as e:      # noqa: BLE001
        log.debug("text height: %s", e)
    an.SetPosition2(x, y, 0)
    return an


def build_sheet_format(s: worker.CadSession, mdl, drw, sheet_key: str) -> list[str]:
    """Border + title block + notes area inside template-edit mode. Returns warnings."""
    warns: list[str] = []
    reg = planner.sheet_regions(sheet_key)
    u, tb, notes = reg["usable"], reg["title_block"], reg["notes"]
    try:
        drw.CreateLayer2(BLACK_LAYER, "Solid Flow sheet format (black)", 0x000000, 0, 1, True, True)
        drw.SetCurrentLayer(BLACK_LAYER)
    except Exception as e:      # noqa: BLE001
        warns.append(f"layer: {e}")
    mdl.SketchManager.InsertSketch(True)
    mdl.SketchManager.AddToDB = True            # exact coordinates: no sketch inference / snapping onto neighbouring geometry
    _rect(mdl, u)                               # border
    _rect(mdl, tb)                              # title block
    _rect(mdl, notes)                           # notes area
    h = tb.h
    rows = [tb.y0 + h * 0.25, tb.y0 + h * 0.5, tb.y0 + h * 0.75]          # four rows
    for y in rows:
        _line(mdl, tb.x0, y, tb.x1, y)
    mid = tb.x0 + tb.w * 0.5
    _line(mdl, mid, rows[2], mid, tb.y1)                    # row 1: company | part name
    _line(mdl, mid, rows[1], mid, rows[2])                  # row 2: part number | material
    q = [tb.x0 + tb.w * f for f in (0.25, 0.5, 0.75)]
    for x in q:
        _line(mdl, x, rows[0], x, rows[1])                  # row 3: drawn | checked | finish | date
    c5 = [tb.x0 + tb.w * f for f in (0.2, 0.4, 0.6, 0.8)]
    for x in c5:
        _line(mdl, x, tb.y0, x, rows[0])                    # row 4: units | scale | sheet | revision | projection
    mdl.SketchManager.AddToDB = False
    mdl.SketchManager.InsertSketch(True)
    pad, dy = 0.0016, 0.0037

    def put(text, x, y):
        if _note(s, mdl, text, x, y) is None:
            warns.append(f"note not placed: {text[:24]}")
    put("COMPANY  $PRP:\"SF_Company\"", tb.x0 + pad, tb.y1 - dy - 0.001)
    put("TITLE  $PRP:\"SF_PartName\"", mid + pad, tb.y1 - dy - 0.001)
    put("PART NO  $PRP:\"SF_PartNumber\"", tb.x0 + pad, rows[2] - dy)
    put("MATERIAL  $PRP:\"SF_Material\"", mid + pad, rows[2] - dy)
    put("DRAWN  $PRP:\"SF_DrawnBy\"", tb.x0 + pad, rows[1] - dy)
    put("CHECKED  $PRP:\"SF_CheckedBy\"", q[0] + pad, rows[1] - dy)
    put("FINISH  $PRP:\"SF_Finish\"", q[1] + pad, rows[1] - dy)
    put("DATE  $PRP:\"SF_Date\"", q[2] + pad, rows[1] - dy)
    put("UNITS  $PRP:\"SF_Units\"", tb.x0 + pad, rows[0] - dy + 0.0008)
    put("SCALE  $PRP:\"SW-Sheet Scale\"", c5[0] + pad, rows[0] - dy + 0.0008)
    put("SHEET  $PRP:\"SW-Current Sheet\" OF $PRP:\"SW-Total Sheets\"", c5[1] + pad, rows[0] - dy + 0.0008)
    put("REV  $PRP:\"SF_Revision\"", c5[2] + pad, rows[0] - dy + 0.0008)
    put("$PRP:\"SF_Projection\"", c5[3] + pad, rows[0] - dy + 0.0008)
    put("$PRP:\"SF_Status\"", notes.x0 + pad, notes.y1 - dy - 0.001)
    put("NOTES:", notes.x0 + pad, notes.y1 - 0.012)
    return warns


def generate(s: worker.CadSession, out_dir: Path, key: str = "solidflow-ansi-b") -> dict:
    sheet_key, label = VARIANTS[key]
    stock = templates.stock_entry()
    if not stock:
        raise worker.CadError("The stock SOLIDWORKS drawing template was not found, so a template cannot be generated. Install SOLIDWORKS 2025 templates or upload your own .drwdot.")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    drwdot = (out_dir / f"{key}.drwdot").resolve()
    slddrt = (out_dir / f"{key}.slddrt").resolve()
    preview = (out_dir / f"{key}_preview.pdf").resolve()
    for p in (drwdot, slddrt, preview):
        p.unlink(missing_ok=True)
    paper, w, h = PAPER[sheet_key]
    T = s.typed
    model = T(s.app, "ISldWorks").NewDocument(stock["path"], paper, w, h)
    if model is None:
        raise worker.CadError("SOLIDWORKS could not create a drawing from the stock template.")
    mdl = T(model, "IModelDoc2")
    drw = T(model, "IDrawingDoc")
    title = str(mdl.GetTitle())
    warns: list[str] = []
    try:
        drw.SetupSheet5("Sheet1", paper, 13, 1.0, 1.0, False, "", w, h, "Default", True)       # third angle
        # drawing document properties the title block links to; the engine overwrites them per part
        mgr = T(mdl.Extension, "IModelDocExtension").CustomPropertyManager("")
        defaults = {"SF_Company": "NOT SPECIFIED", "SF_PartName": "NOT SPECIFIED", "SF_PartNumber": "NOT SPECIFIED", "SF_Material": "NOT SPECIFIED",
                    "SF_Finish": "NOT SPECIFIED", "SF_Revision": "NOT SPECIFIED", "SF_Units": "NOT SPECIFIED", "SF_Projection": "THIRD ANGLE",
                    "SF_Status": "PRELIMINARY / FOR REVIEW", "SF_DrawnBy": "NOT SPECIFIED", "SF_CheckedBy": "NOT SPECIFIED", "SF_Date": "NOT SPECIFIED",
                    "SF_Source": "", "SF_Config": ""}
        for k, v in defaults.items():
            mgr.Add3(k, 30, v, 2)
        drw.EditTemplate()
        warns += build_sheet_format(s, mdl, drw, sheet_key)
        drw.EditSheet()
        sheet = T(drw.GetCurrentSheet(), "ISheet")
        try:
            sheet.SetSheetFormatName(key)
        except Exception as e:      # noqa: BLE001
            warns.append(f"sheet format name: {e}")
        ok_fmt = sheet.SaveFormat(str(slddrt))
        ext = T(mdl.Extension, "IModelDocExtension")
        res = ext.SaveAs3(str(drwdot), 0, 1, None, None, 0, 0)
        ok_tpl = res[0] if isinstance(res, tuple) else res
        # a blank preview PDF of the template itself
        exp = s.app.GetExportFileData(1)
        if exp is not None:
            T(exp, "IExportPdfData").ViewPdfAfterSaving = False
            ext.SaveAs3(str(preview), 0, 1, exp, None, 0, 0)
    finally:
        try:
            s.app.CloseDoc(str(mdl.GetTitle()))       # re-read: SaveAs3 to .drwdot RENAMES the open document to the template itself
        except Exception:      # noqa: BLE001
            try:
                s.app.CloseDoc(title)
            except Exception:      # noqa: BLE001
                pass
    if not drwdot.is_file() or drwdot.stat().st_size == 0:
        raise worker.CadError("SOLIDWORKS did not write the .drwdot template.")
    check = templates.validate_template(s, drwdot)
    if not check["ok"]:
        drwdot.unlink(missing_ok=True)
        raise worker.CadError("The generated template failed validation: " + "; ".join(check["errors"]))
    entry = {"id": key, "name": label, "path": str(drwdot), "sheet_format_path": str(slddrt) if slddrt.is_file() else None,
             "preview_pdf": str(preview) if preview.is_file() else None, "sha256": safety.sha256_file(drwdot), "own_sheet_format": True, "source": "generated",
             "sheet": sheet_key, "paper": planner.SHEETS[sheet_key]["paper"], "properties": list(PROPS), "validation": check, "warnings": warns,
             "solidworks": s.info.as_dict(), "slddrt_saved": bool(ok_fmt) and slddrt.is_file()}
    (out_dir / f"{key}.manifest.json").write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return entry
