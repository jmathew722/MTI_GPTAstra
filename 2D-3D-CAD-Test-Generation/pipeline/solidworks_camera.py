"""Camera and workspace presentation for the SolidWorks build recording.

What it does (all through native SolidWorks 2025 APIs, never keystrokes):
  * prepare():  records the original state (FeatureManager design-tree visibility, window placement), maximises the OWNED SolidWorks window without
                activating it, hides the design tree (``IFeatureManager.EnableFeatureTree``, readable and writable), shows the standard isometric view.
  * frame():    called at every committed feature boundary: standard isometric (``IModelDoc2.ShowNamedView2("*Isometric", swIsometricView=7)``),
                ``ViewZoomtofit2``, a margin correction (``IModelView.ZoomByFactor``), ``GraphicsRedraw2``, then waits for a SETTLED rendered frame and
                verifies orientation (native ``IModelView.Orientation3`` vs the isometric matrix) and framing (the rendered picture: geometry must not touch the
                viewport edge, margins are measured). A command that was merely issued is never reported as proof of the visible result.
  * restore():  puts the tree and the window back exactly as found (called from the recorder's stop(), i.e. on completion, failure and cancellation).

Every step is recorded in ``camera_log.json`` next to the recording. A camera failure is flagged (``camera.ok = false``) and never touches geometry.
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from utils.logger import get_logger

log = get_logger(__name__)

SW_ISOMETRIC_VIEW = 7                     # swStandardViews_e.swIsometricView (verified against the installed swconst type library)
ISO_NAME = "*Isometric"
# rotation part of the standard isometric view as returned by IModelView.Orientation3 (row-major 3x3), measured on SolidWorks 2025 SP5
ISO_MATRIX = (0.70710678, -0.40824829, 0.57735027,
              0.0, 0.81649658, 0.57735027,
              -0.70710678, -0.40824829, 0.57735027)
TARGET_MARGIN = float(os.environ.get("GPTASTRA_CAMERA_MARGIN", "0.10"))   # per viewport edge, fraction of the viewport (8-12 % target band)
MARGIN_LO, MARGIN_HI = 0.06, 0.14
SETTLE_TIMEOUT_S = 2.0
CAMERA_LOG = "camera_log.json"


def iso_error(orientation) -> float:
    """Largest absolute difference between a rotation matrix (first 9 numbers) and the standard isometric one."""
    try:
        v = [float(x) for x in list(orientation)[:9]]
        return max(abs(a - b) for a, b in zip(v, ISO_MATRIX)) if len(v) == 9 else 9.9
    except Exception:                                    # noqa: BLE001
        return 9.9


def measure_margins(frame, rect=None) -> dict:
    """Margins of the rendered geometry inside the model viewport, from a BGR picture of the window.

    ``rect`` = (left, top, right, bottom) of the viewport in the picture (default: the picture minus a 9 % top band for the heads-up toolbar).
    Geometry = pixels clearly darker or more colourful than SolidWorks' light background gradient. Returns {ok, margins:{left,top,right,bottom},
    touches_edge, empty}. ``ok`` is False when the picture is unusable; ``empty`` when no geometry is visible."""
    import numpy as np
    out: dict = {"ok": False, "margins": {}, "touches_edge": False, "empty": False}
    if frame is None or getattr(frame, "ndim", 0) != 3:
        return out
    h, w = frame.shape[:2]
    l, t, r, b = rect if rect else (0, int(h * 0.09), w, h)
    l, t, r, b = max(0, int(l)) + 12, max(0, int(t)), min(w, int(r)) - 12, min(h, int(b)) - 34   # window border columns and the status bar are not viewport
    if r - l < 80 or b - t < 80:
        return out
    roi = frame[t:b, l:r].astype(np.int32)
    lum = (roi[..., 0] * 114 + roi[..., 1] * 587 + roi[..., 2] * 299) // 1000
    sat = roi.max(axis=2) - roi.min(axis=2)
    mask = (lum < 205) | (sat > 40)
    vh, vw = mask.shape
    mask[:70, :] = False                                              # heads-up view toolbar
    mask[:160, :340] = False                                          # feature breadcrumb (shown while a feature is selected)
    mask[int(vh * 0.86):, :90] = False                                # orientation triad (bottom-left)
    mask[:, :28] = False                                              # collapsed-tree handle / left toolbar edge
    mask[:, int(vw * 0.97):] = False                                  # task-pane grip
    if mask.sum() < 40:
        out.update(ok=True, empty=True)
        return out
    cols, rows = np.where(mask.sum(axis=0) >= 4)[0], np.where(mask.sum(axis=1) >= 4)[0]       # ignore stray pixels: a real edge spans several pixels
    if len(cols) == 0 or len(rows) == 0:
        out.update(ok=True, empty=True)
        return out
    x0, x1, y0, y1 = int(cols.min()), int(cols.max()), int(rows.min()), int(rows.max())
    ux0, uy0, ux1, uy1 = 28, 70, vw - int(vw * 0.03), vh - 1                  # the usable region: right of the left toolbar edge, below the HUD toolbar
    uw, uh = ux1 - ux0, uy1 - uy0
    m = {"left": round((x0 - ux0) / uw, 4), "right": round((ux1 - x1) / uw, 4), "top": round((y0 - uy0) / uh, 4), "bottom": round((uy1 - y1) / uh, 4)}
    edge = 0.012
    touches = min(m.values()) < edge
    out.update(ok=True, margins=m, touches_edge=bool(touches), bbox=[x0, y0, x1, y1], usable=[ux0, uy0, ux1, uy1])
    return out


SW_CMD_HIDESHOW_TREE_AREA = 2556          # swCommands_e.swCommands_Hideshow_Brwser_Tree ("Hide/Show Tree Area"), read from the installed swcommands type library


def tree_area_visible(hwnd: int) -> Optional[bool]:
    """Is the FeatureManager design-tree pane on screen? (the pane's container window is moved off-screen when hidden). None = cannot tell."""
    try:
        import win32gui
        found = []
        win32gui.EnumChildWindows(hwnd, lambda c, _: found.append(c) if win32gui.GetWindowText(c) == "Tree Container Wnd" else None, None)
        if not found:
            return None
        wl = win32gui.GetWindowRect(hwnd)[0]
        r = win32gui.GetWindowRect(found[0])
        return bool((r[2] - r[0]) > 50 and r[2] > wl + 60)
    except Exception:                                    # noqa: BLE001
        return None


def show_async(hwnd: int, cmd: int) -> bool:
    """ShowWindowAsync through user32 (pywin32's win32gui does not expose it). SW_MAXIMIZE=3, SW_SHOWNOACTIVATE=4, SW_RESTORE=9."""
    try:
        import ctypes
        return bool(ctypes.windll.user32.ShowWindowAsync(hwnd, cmd))
    except Exception:                                    # noqa: BLE001
        return False


def _zoomed(hwnd: int) -> bool:
    """Is the window maximised? (win32gui has no IsZoomed: read the show state from the window placement.)"""
    try:
        import win32gui
        return win32gui.GetWindowPlacement(hwnd)[1] == 3          # SW_SHOWMAXIMIZED
    except Exception:                                    # noqa: BLE001
        return False


def mdi_viewport(hwnd: int) -> Optional[tuple]:
    """The visible model area (swMdiClient) as a rectangle inside a picture of the SolidWorks main window."""
    try:
        import win32gui
        found = []
        win32gui.EnumChildWindows(hwnd, lambda c, _: found.append(win32gui.GetWindowRect(c)) if win32gui.GetClassName(c) == "swMdiClient" else None, None)
        if not found:
            return None
        wl, wt = win32gui.GetWindowRect(hwnd)[:2]
        r = found[0]
        return (r[0] - wl, r[1] - wt, r[2] - wl, r[3] - wt)
    except Exception:                                    # noqa: BLE001
        return None


class CameraController:
    """Drives the camera; ``grab`` is a callable returning a BGR picture of the SolidWorks window (the recorder's window-only capture)."""

    def __init__(self, sw_app, hwnd: int, *, grab: Optional[Callable[[], Any]] = None, out_dir: Optional[Path] = None,
                 viewport_finder: Optional[Callable[[Any, Any], Optional[tuple]]] = None, maximise: bool = True, hide_tree: bool = True):
        self.app, self.hwnd, self.grab, self.out = sw_app, hwnd, grab, Path(out_dir) if out_dir else None
        self._viewport_finder = viewport_finder
        self.want_max, self.want_hide = maximise, hide_tree
        self.entries: list[dict] = []
        self._orig: dict = {}
        self._doc = None
        self.failures: list[str] = []
        self.prepared = False

    # ---------------------------------------------------------------- helpers
    def _wait_settled(self, timeout: float = SETTLE_TIMEOUT_S):
        """Poll the window until two consecutive pictures are identical (a confirmed rendered frame). Returns (frame, settled, waited_s)."""
        import numpy as np
        t0 = time.time()
        if self.grab is None:
            time.sleep(0.25)
            return None, False, time.time() - t0
        prev, cur = None, None
        while time.time() - t0 < timeout:
            cur = self.grab()
            if cur is not None and prev is not None and cur.shape == prev.shape and np.array_equal(cur[::4, ::4], prev[::4, ::4]):
                return cur, True, time.time() - t0
            prev = cur
            time.sleep(0.12)
        return cur, False, time.time() - t0

    def _viewport(self, doc, frame):
        if self._viewport_finder is not None:
            try:
                return self._viewport_finder(doc, frame)
            except Exception:                            # noqa: BLE001
                return None
        return None

    def _pan(self, doc, dx_px: float, dy_px: float) -> None:
        """Pan the view by roughly (dx_px, dy_px) screen pixels with IModelView.Translation3 (gains measured on SolidWorks 2025 SP5, refined by the loop)."""
        from pipeline.solidworks_builder import com_doubles, typed
        mv = typed(doc.ActiveView, "IModelView")
        scale = float(mv.Scale2) or 1.0
        a = list(mv.Translation3.ArrayData)
        gx = 4000.0 * scale / 1.2184           # screen px per unit of Translation3.x, at the scale the gain was measured at
        gy = 2600.0 * scale / 1.2184           # (+y moved the model UP on screen)
        new = [a[0] + dx_px / gx, a[1] - dy_px / gy, a[2]]
        mu = typed(self.app.GetMathUtility, "IMathUtility")
        mv.Translation3 = mu.CreateVector(com_doubles(*new))

    def _model_view(self, doc):
        try:
            return doc.ActiveView
        except Exception:                                # noqa: BLE001
            return None

    # ---------------------------------------------------------------- lifecycle
    def prepare(self, doc) -> dict:
        """Record the original state, maximise the owned window (no activation), hide the design tree, isometric + fit. Never raises."""
        self._doc = doc
        info: dict = {"event": "prepare", "t": time.time()}
        try:
            import win32con
            import win32gui
            if self.hwnd and win32gui.IsWindow(self.hwnd):
                self._orig["placement"] = win32gui.GetWindowPlacement(self.hwnd)
                self._orig["rect"] = win32gui.GetWindowRect(self.hwnd)          # the exact visible rectangle, restored with SetWindowPos
                info["window_before"] = {"maximised": bool(_zoomed(self.hwnd)), "rect": list(win32gui.GetWindowRect(self.hwnd))}
                if self.want_max and not _zoomed(self.hwnd) and not win32gui.IsIconic(self.hwnd):
                    show_async(self.hwnd, win32con.SW_MAXIMIZE)       # does not activate: Chrome / VS Code keep the focus
                    time.sleep(1.2)
                    self._orig["maximised_by_us"] = True
                info["window_after"] = {"maximised": bool(_zoomed(self.hwnd)), "rect": list(win32gui.GetWindowRect(self.hwnd))}
        except Exception as e:                           # noqa: BLE001
            info["window_error"] = f"{type(e).__name__}: {e}"
        try:
            vis = tree_area_visible(self.hwnd)
            info["tree_visible_before"] = vis
            self._orig["tree_visible"] = vis
            if self.want_hide and vis:
                ok = self.app.RunCommand(SW_CMD_HIDESHOW_TREE_AREA, "")        # native command, no keystroke, no focus change
                time.sleep(1.0)
                info["tree_command_result"] = bool(ok)
                self._orig["tree_hidden_by_us"] = True
            info["tree_visible_after"] = tree_area_visible(self.hwnd)
            if self.want_hide and info["tree_visible_after"] is not False:
                self.failures.append("design tree could not be hidden" if info["tree_visible_after"] else "design tree state unverifiable")
        except Exception as e:                           # noqa: BLE001
            info["tree_error"] = f"{type(e).__name__}: {e}"
            self.failures.append(f"design tree: {e}")
        self.prepared = True
        self.entries.append(info)
        try:
            self.frame(doc, "initial", initial=True)
        except Exception as e:                           # noqa: BLE001
            log.warning("camera initial frame failed: %s", e)
        return info

    def restore(self) -> dict:
        """Put everything back as found. Safe to call twice; never raises."""
        res: dict = {"event": "restore", "t": time.time()}
        if not self.prepared:
            return res
        self.prepared = False
        try:
            if self._orig.get("tree_hidden_by_us") and tree_area_visible(self.hwnd) is False:
                self.app.RunCommand(SW_CMD_HIDESHOW_TREE_AREA, "")            # toggle back: only if WE hid it and it is still hidden
                time.sleep(0.8)
                res["tree_restored"] = bool(tree_area_visible(self.hwnd))
        except Exception as e:                           # noqa: BLE001
            res["tree_restore_error"] = f"{type(e).__name__}: {e}"
        try:
            import win32gui
            if self.hwnd and win32gui.IsWindow(self.hwnd) and "placement" in self._orig and self._orig.get("maximised_by_us"):
                show_async(self.hwnd, 9)                                          # SW_RESTORE (no activation)
                time.sleep(0.6)
                l, t_, r, b = self._orig["rect"]
                win32gui.SetWindowPos(self.hwnd, 0, l, t_, r - l, b - t_, 0x0004 | 0x0010)     # SWP_NOZORDER | SWP_NOACTIVATE
                time.sleep(0.4)
                res["window_restored"] = list(win32gui.GetWindowRect(self.hwnd)) == list(self._orig["rect"])
                res["window_rect_after"] = list(win32gui.GetWindowRect(self.hwnd))
        except Exception as e:                           # noqa: BLE001
            res["window_restore_error"] = f"{type(e).__name__}: {e}"
        self.entries.append(res)
        self.write_log()
        return res

    # ---------------------------------------------------------------- per feature
    def frame(self, doc, label: str, *, initial: bool = False, final: bool = False) -> dict:
        """Isometric + fit + margin + redraw for the CURRENT model; verify it. Called only at safe boundaries (a committed feature, no open sketch)."""
        e: dict = {"event": "final" if final else ("initial" if initial else "feature"), "feature": str(label), "t": time.time(), "ops": {}}
        try:
            doc.ShowNamedView2(ISO_NAME, SW_ISOMETRIC_VIEW)
            e["ops"]["isometric"] = "issued"
        except Exception as ex:                          # noqa: BLE001
            e["ops"]["isometric"] = f"failed: {type(ex).__name__}"
        try:
            doc.ViewZoomtofit2()
            e["ops"]["zoom_to_fit"] = "issued"
        except Exception as ex:                          # noqa: BLE001
            e["ops"]["zoom_to_fit"] = f"failed: {type(ex).__name__}"
        try:
            doc.GraphicsRedraw2()
            e["ops"]["redraw"] = "issued"
        except Exception as ex:                          # noqa: BLE001
            e["ops"]["redraw"] = f"failed: {type(ex).__name__}"
        frame, settled, waited = self._wait_settled()
        e["settled_frame"] = bool(settled)
        e["settle_wait_s"] = round(waited, 2)
        mv = self._model_view(doc)
        err = 9.9
        try:
            err = iso_error(mv.Orientation3.ArrayData) if mv is not None else 9.9
        except Exception:                                # noqa: BLE001
            pass
        e["isometric_error"] = round(err, 4)
        e["isometric_verified"] = bool(err < 0.01)
        meas = measure_margins(frame, self._viewport(doc, frame)) if frame is not None else {"ok": False}
        e["fit"] = meas
        corrected = False
        factors = []
        pans = []
        for _ in range(7):
            if not (meas.get("ok") and not meas.get("empty") and meas.get("margins")) or mv is None:
                break
            m = meas["margins"]
            binding = min(m.values())
            cx_off = (m["right"] - m["left"]) / 2                       # + : the model sits left of centre (fractions of the usable width)
            cy_off = (m["bottom"] - m["top"]) / 2
            uw = meas["usable"][2] - meas["usable"][0]
            uh = meas["usable"][3] - meas["usable"][1]
            bw = meas["bbox"][2] - meas["bbox"][0]
            bh = meas["bbox"][3] - meas["bbox"][1]
            used = max(bw / uw, bh / uh)
            want = 1 - 2 * TARGET_MARGIN
            centred = abs(cx_off) < 0.03 and abs(cy_off) < 0.03
            sized = MARGIN_LO <= binding and not meas.get("touches_edge") and abs(used - want) < 0.10
            if centred and sized:
                break
            # SolidWorks' own fit is computed for the whole view frame and can leave the model off-centre or partly outside the visible viewport.
            # Closed loop on the RENDERED picture: zoom to the target margin, pan to the centre of the usable region, re-measure.
            f = 1.0
            if meas.get("touches_edge") or binding < MARGIN_LO or abs(used - want) >= 0.10:
                f = max(0.6, min(1.5, want / max(used, 0.05)))
                if meas.get("touches_edge"):
                    f = min(f, 0.9)                                     # a clipped extent under-reads the real size
            try:
                if abs(f - 1) > 0.02:
                    mv.ZoomByFactor(float(f))
                    factors.append(round(f, 3))
                dxp, dyp = cx_off * uw, cy_off * uh               # pixels to move the model: right if it sits left, down if it sits high
                self._pan(doc, dxp, dyp)
                pans.append([round(dxp), round(dyp)])
                doc.GraphicsRedraw2()
                corrected = True
            except Exception as ex:                      # noqa: BLE001
                e["ops"]["margin_adjust"] = f"failed: {type(ex).__name__}: {ex}"
                break
            frame, settled2, waited2 = self._wait_settled()
            settled = settled and settled2
            meas = measure_margins(frame, self._viewport(doc, frame)) if frame is not None else {"ok": False}
            mv = self._model_view(doc)
        if factors or pans:
            e["ops"]["margin_zoom_factors"] = factors
            e["ops"]["pan_px"] = pans
            e["fit_after_margin"] = meas
        e["margin_corrected"] = corrected
        final_meas = meas
        e["geometry_visible"] = bool(final_meas.get("ok") and not final_meas.get("touches_edge"))
        e["empty_model"] = bool(final_meas.get("empty"))
        e["camera_ok"] = bool(e["isometric_verified"] and settled and (e["geometry_visible"] or e["empty_model"]))
        if not e["camera_ok"]:
            why = []
            if not e["isometric_verified"]:
                why.append("orientation is not the standard isometric")
            if not settled:
                why.append("no settled frame")
            if not (e["geometry_visible"] or e["empty_model"]):
                why.append("geometry touches or leaves the viewport edge, or the frame is unreadable")
            self.failures.append(f"{label}: " + "; ".join(why))
        self.entries.append(e)
        return e

    # ---------------------------------------------------------------- report
    def summary(self) -> dict:
        feats = [x for x in self.entries if x.get("event") in ("feature", "final", "initial")]
        return {"ok": not self.failures and bool(feats), "frames_checked": len(feats),
                "iso_verified": sum(1 for x in feats if x.get("isometric_verified")),
                "fit_verified": sum(1 for x in feats if x.get("geometry_visible") or x.get("empty_model")),
                "margin_corrections": sum(1 for x in feats if x.get("margin_corrected")),
                "failures": self.failures[:20], "target_margin": TARGET_MARGIN, "log": CAMERA_LOG}

    def write_log(self) -> None:
        if self.out is None:
            return
        try:
            tmp = self.out / (CAMERA_LOG + ".tmp")
            tmp.write_text(json.dumps({"summary": self.summary(), "entries": self.entries}, indent=1, default=str), encoding="utf-8")
            os.replace(tmp, self.out / CAMERA_LOG)
        except Exception:                                # noqa: BLE001
            pass
