"""SolidWorks steps of benchmark prep (Windows + SolidWorks only; win32com imported lazily).

DWG -> PDF: import at 1:1, centered, on a 4.5 m user-defined sheet (the paper/scale that
SolidWorks picks itself broke 9 of 21 drawings on 2026-10-12), export black & white, crop
to content.
SLDPRT -> STEP: open a COPY read-only, export STEP AP214 and a PNG picture.

SaveAs3 returns an error code (0 = success; error log E025): never test it for truthiness,
and require the output file to be new or rewritten (a stale file must not pass as success).
Outputs are written to a temp name next to the target (same extension, so SolidWorks picks
the right exporter) and moved into place only after every check passed, so a failure or an
interrupt never leaves a partial file that a resumed run would skip.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

SHEET_M = 4.5
PDF_COLOR, PDF_HIGH_QUALITY, STEP_AP = 323, 325, 75
SW_DOC_PART = 1
OPEN_SILENT, OPEN_READONLY = 1, 2
IMPORT_TO_DRAWING, PAPER_USER, POS_CENTERED = 1, 12, 1
DISPATCH_METHOD, DISPATCH_PROPERTYPUT = 1, 4   # pythoncom values; kept here so no import is needed


class SwUnavailable(RuntimeError):
    pass


def _late_bound(obj):
    """Always use late binding. If a makepy cache for sldworks.tlb exists (%TEMP%\\gen_py),
    pywin32 hands back typed wrappers whose [in,out] parameters reject the byref VARIANTs
    passed to LoadFile4/OpenDoc6 ("int() argument must be ... not 'VARIANT'"). Error log E026."""
    import win32com.client.dynamic as dynamic
    return dynamic.Dispatch(obj._oleobj_)


def connect(retries: int = 6, wait_s: float = 5.0):
    """Attach to the running SolidWorks.

    Only retries GetActiveObject. A hung SolidWorks (not responding) blocks every later
    COM call and there is no watchdog here, so a stuck session must be restarted by hand.
    """
    import pythoncom
    import win32com.client as w
    pythoncom.CoInitialize()
    last = None
    for i in range(retries):
        try:
            return _late_bound(w.GetActiveObject("SldWorks.Application"))
        except Exception as e:        # "Operation unavailable": COM registration dropped
            last = e
            if i < retries - 1:
                time.sleep(wait_s)
    raise SwUnavailable(f"SolidWorks is not reachable over COM ({last}). Start SLDWORKS.exe, "
                        "wait ~25 s, and run again (COM drops after idle minutes on this machine).")


def _cleanup(steps, what: str) -> None:
    """Run every cleanup step. If an exception is already propagating, a cleanup failure is
    logged and the original wins; otherwise the first cleanup failure is raised."""
    original = sys.exc_info()[0] is not None
    first = None
    for fn in steps:
        try:
            fn()
        except Exception as e:
            log.warning("cleanup failed (%s): %s", what, e)
            first = first or e
    if first is not None and not original:
        raise first


@contextmanager
def temporary_prefs(app, prefs: dict[int, bool]):
    saved = {k: app.GetUserPreferenceToggle(k) for k in prefs}
    try:
        for k, v in prefs.items():
            app.SetUserPreferenceToggle(k, v)
        yield
    finally:
        _cleanup([lambda k=k, v=v: app.SetUserPreferenceToggle(k, v) for k, v in saved.items()],
                 "restore toggles")


def _g(obj, name):
    a = getattr(obj, name)
    return a() if callable(a) else a


def _invoke(obj, name, kind, *args):
    o = obj._oleobj_
    return o.Invoke(o.GetIDsOfNames(name), 0, kind, kind != DISPATCH_PROPERTYPUT, *args)


def _byref_long():
    import pythoncom
    import win32com.client as w
    return w.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)


def _mtime(p: Path):
    return p.stat().st_mtime_ns if p.exists() else None


def _fresh(p: Path, before) -> bool:
    now = _mtime(p)
    return now is not None and now != before


def _tmp(p: Path) -> Path:
    """drawing.pdf -> drawing.tmp.pdf (the extension stays last for SolidWorks)."""
    return p.with_name(f"{p.stem}.tmp{p.suffix}")


@contextmanager
def _atomic(out: Path):
    """Yield a temp path; on success os.replace it onto out, on any failure remove it."""
    tmp = _tmp(out)
    tmp.unlink(missing_ok=True)
    try:
        yield tmp
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)


def _close(app, doc) -> None:
    app.CloseDoc(_g(doc, "GetTitle"))


def crop_to_content(pdf: Path, margin_pt: float = 18.0) -> None:
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    pdf = Path(pdf)
    tmp = pdf.with_suffix(".tmp.pdf")
    doc = fitz.open(pdf)
    try:
        empty = []
        for page in doc:
            pw, ph = page.rect.width, page.rect.height
            # skip page-sized rectangles (border frames)
            rects = [d["rect"] for d in page.get_drawings()
                     if d["rect"].width < pw * 0.99 and d["rect"].height < ph * 0.99]
            rects += [fitz.Rect(b[:4]) for b in page.get_text("blocks")
                      if "Educational Product" not in b[4]]
            if not rects:
                empty.append(page.number)
                continue
            box = rects[0]
            for r in rects[1:]:
                box |= r
            page.set_cropbox((box + (-margin_pt, -margin_pt, margin_pt, margin_pt)) & page.rect)
        if len(empty) == len(doc):
            raise ValueError(f"no drawing content in {pdf}")
        if empty:
            doc.delete_pages(empty)
        doc.save(tmp, garbage=3, deflate=True)
    finally:
        doc.close()
    tmp.replace(pdf)


def _configure_import(data) -> None:
    """Apply 1:1 / centred / user-defined sheet to the import data and check every setting.

    A False return means SolidWorks rejected the setting (the failure that broke 9 of 21
    drawings), so it raises. The "Model" sheet is the exception: a rejection there may only
    mean the DWG has no sheet of that name, so it is a warning (the "" default sheet, which
    is processed first, has already been accepted by then).
    """
    settings = (
        ("ImportMethod", DISPATCH_PROPERTYPUT, (IMPORT_TO_DRAWING,)),
        ("SetPaperSize", DISPATCH_METHOD, (PAPER_USER, SHEET_M, SHEET_M)),
        ("SetSheetScale", DISPATCH_METHOD, (1.0, 1.0)),
        ("SetPosition", DISPATCH_METHOD, (POS_CENTERED, 0.0, 0.0)),
    )
    for sheet in ("", "Model"):
        for name, kind, args in settings:
            if _invoke(data, name, kind, sheet, *args) is False:
                msg = f"SolidWorks rejected {name} for sheet {sheet!r}"
                if sheet == "":
                    raise RuntimeError(msg)
                log.warning("%s (DWG may have no such sheet)", msg)


def dwg_to_pdf(app, dwg: Path, out_pdf: Path) -> None:
    # SolidWorks resolves relative paths against its own working directory
    dwg, out_pdf = Path(dwg).resolve(), Path(out_pdf).resolve()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_pdf.unlink(missing_ok=True)
    with _atomic(out_pdf) as tmp:
        before = _mtime(tmp)
        with temporary_prefs(app, {PDF_COLOR: False, PDF_HIGH_QUALITY: True}):
            data = app.GetImportFileData(str(dwg))
            _configure_import(data)
            err = _byref_long()
            doc = app.LoadFile4(str(dwg), "", data, err)
            if doc is None:
                raise RuntimeError(f"LoadFile4 failed for {dwg} (error {err.value})")
            try:
                code = doc.SaveAs3(str(tmp), 0, 1)
                if code != 0 or not _fresh(tmp, before):
                    raise RuntimeError(f"PDF export failed for {dwg} (SaveAs3 {code})")
            finally:
                _cleanup([lambda: _close(app, doc)], "close drawing")
        crop_to_content(tmp)


def sldprt_to_step(app, sldprt: Path, out_step: Path, out_png: Path) -> None:
    """Open a copy read-only, export STEP AP214 (+ a picture). Never saves the part."""
    sldprt, out_step, out_png = Path(sldprt).resolve(), Path(out_step).resolve(), Path(out_png).resolve()
    out_step.parent.mkdir(parents=True, exist_ok=True)
    out_step.unlink(missing_ok=True)
    out_png.unlink(missing_ok=True)
    err, warn = _byref_long(), _byref_long()
    doc = app.OpenDoc6(str(sldprt), SW_DOC_PART, OPEN_SILENT | OPEN_READONLY, "", err, warn)
    if doc is None:
        raise RuntimeError(f"OpenDoc6 failed for {sldprt} (error {err.value})")
    try:
        with _atomic(out_step) as tmp:
            before = _mtime(tmp)
            old_ap = app.GetUserPreferenceIntegerValue(STEP_AP)
            try:
                app.SetUserPreferenceIntegerValue(STEP_AP, 214)
                code = doc.SaveAs3(str(tmp), 0, 1)
            finally:
                _cleanup([lambda: app.SetUserPreferenceIntegerValue(STEP_AP, old_ap)], "restore STEP AP")
            if code != 0 or not _fresh(tmp, before):
                raise RuntimeError(f"STEP export failed for {sldprt} (SaveAs3 {code})")
        try:
            doc.ShowNamedView2("*Isometric", 7)
            doc.ViewZoomtofit2()
            doc.SaveAs3(str(out_png), 0, 1)
        except Exception:
            pass                      # the picture is best effort (review sheet only)
    finally:
        _cleanup([lambda: _close(app, doc)], "close part")
