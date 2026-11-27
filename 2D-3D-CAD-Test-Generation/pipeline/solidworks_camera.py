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
TARGET_MARGIN = float(os.environ.get("GPTASTRA_CAMERA_MARGIN", "0.15"))   # clear margin per viewport edge (12-18 % band, default 15 %)
MARGIN_LO, MARGIN_HI = 0.11, 0.20                                         # accepted binding margin (the target band with a small tolerance, to avoid hunting)
ISO_EVERY = int(os.environ.get("GPTASTRA_CAMERA_ISO_EVERY", "2"))         # isometric after every N completed features
SETTLE_TIMEOUT_S = 1.5
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
    ys_, xs_ = np.where(mask)
    out.update(ok=True, margins=m, touches_edge=bool(touches), bbox=[x0, y0, x1, y1], usable=[ux0, uy0, ux1, uy1],
               centroid=[round(float(xs_.mean()), 1), round(float(ys_.mean()), 1)])
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
        self.completed_feature_count = 0
        self._seen_ops: set = set()
        self._iso_pending_final = True
        self._pan_cal: dict = {}

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

    def _translation(self, doc):
        from pipeline.solidworks_builder import typed
        mv = typed(doc.ActiveView, "IModelView")
        return mv, [float(x) for x in list(mv.Translation3.ArrayData)[:3]], float(mv.Scale2) or 1.0

    def _set_translation(self, mv, vec) -> None:
        from pipeline.solidworks_builder import com_doubles, typed
        mu = typed(self.app.GetMathUtility, "IMathUtility")
        mv.Translation3 = mu.CreateVector(com_doubles(*vec))

    def _calibrate_pan(self, doc, meas0: dict):
        """Screen pixels moved per unit of IModelView.Translation3 along X/Y/Z for the CURRENT orientation (the mapping depends on the view), measured by
        three tiny probe moves of the rendered picture; cached per orientation and normalised by the view scale."""
        import numpy as np
        key = tuple(round(x, 2) for x in (self._orientation(doc) or ()))
        if key in self._pan_cal:
            return self._pan_cal[key]
        mv, base, scale = self._translation(doc)
        c0 = meas0.get("centroid")
        if not c0:
            return None
        eps = 0.012 * 1.2184 / scale
        cols = []
        for ax in range(3):
            v = list(base)
            v[ax] += eps
            self._set_translation(mv, v)
            doc.GraphicsRedraw2()
            fr, _s, _w = self._wait_settled(1.0)
            m1 = measure_margins(fr, self._viewport(doc, fr)) if fr is not None else {}
            c1 = m1.get("centroid")
            cols.append([(c1[0] - c0[0]) / eps, (c1[1] - c0[1]) / eps] if c1 else [0.0, 0.0])
        self._set_translation(mv, base)
        doc.GraphicsRedraw2()
        G = np.array(cols).T / scale                    # 2x3, px per unit at scale 1 (gain is proportional to the scale)
        self._pan_cal[key] = G
        return G

    def _pan(self, doc, dx_px: float, dy_px: float, meas: Optional[dict] = None) -> None:
        """Move the model by (dx_px, dy_px) screen pixels with IModelView.Translation3, using a mapping calibrated for the current orientation."""
        import numpy as np
        G = self._calibrate_pan(doc, meas or {})
        if G is None or not np.isfinite(G).all() or np.linalg.matrix_rank(G, tol=1e-6) < 2:
            raise RuntimeError("pan calibration failed")
        mv, base, scale = self._translation(doc)
        Gs = G * scale
        u = Gs.T @ np.linalg.solve(Gs @ Gs.T, np.array([dx_px, dy_px]))           # minimum-norm translation giving the wanted screen move
        self._set_translation(mv, [base[k] + float(u[k]) for k in range(3)])

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
            self.on_action_boundary(doc, "initial", "initial")      # full-part view if geometry exists, otherwise waits for geometry (no forced isometric)
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
    # ---------------------------------------------------------------- camera policy (SolidFlow_Recording_Zoom_and_Isometric_Cadence)
    def _orientation(self, doc):
        try:
            return [float(x) for x in list(doc.ActiveView.Orientation3.ArrayData)[:9]]
        except Exception:                                # noqa: BLE001
            return None

    @staticmethod
    def _same_orientation(a, b, tol: float = 0.01) -> Optional[bool]:
        if a is None or b is None:
            return None
        return max(abs(x - y) for x, y in zip(a, b)) < tol

    def _in_band(self, meas: dict) -> bool:
        if not (meas.get("ok") and meas.get("margins")) or meas.get("empty"):
            return False
        m = meas["margins"]
        binding = min(m.values())
        centred = abs(m["right"] - m["left"]) / 2 < 0.05 and abs(m["bottom"] - m["top"]) / 2 < 0.05
        return bool(not meas.get("touches_edge") and MARGIN_LO <= binding <= MARGIN_HI and centred)

    def _fit(self, doc, op_id: str, event: str, orientation: str = "keep") -> dict:
        e = self._fit_impl(doc, op_id, event, orientation)
        e["t_end"] = time.time()                                     # lets the frames around this event be located in the video
        return e

    def _fit_impl(self, doc, op_id: str, event: str, orientation: str = "keep") -> dict:
        """Fit the whole current part in the actual model viewport, with the configured margin.

        orientation 'keep'      : the camera orientation is preserved (verified against native IModelView.Orientation3), nothing is moved when the picture already
                                  shows the whole part with the margin (no jitter).
        orientation 'isometric' : the standard isometric view is established first (only if it is not already the current one), then fit.
        Absolute fit (``ViewZoomtofit2``) is always the starting point; the margin loop then measures the rendered picture, so zoom never accumulates."""
        e: dict = {"event": event, "op_id": str(op_id), "feature_count": self.completed_feature_count, "requested_orientation": orientation,
                   "t": time.time(), "ops": {}}
        before = self._orientation(doc)
        frame, settled, waited = self._wait_settled()
        meas = measure_margins(frame, self._viewport(doc, frame)) if frame is not None else {"ok": False}
        e["margins_before"] = meas.get("margins")
        if meas.get("ok") and meas.get("empty") and (self.completed_feature_count > 0 or event in ("feature_committed", "isometric_checkpoint", "build_completed")):
            # a completed feature exists but nothing is in the picture: the part is out of view (e.g. after the next sketch changed the view): absolute fit first
            try:
                doc.ViewZoomtofit2()
                doc.GraphicsRedraw2()
                e["ops"]["recover_fit"] = "issued (part not in view)"
            except Exception as ex:                      # noqa: BLE001
                e["ops"]["recover_fit"] = f"failed: {type(ex).__name__}"
            frame, settled, waited = self._wait_settled()
            meas = measure_margins(frame, self._viewport(doc, frame)) if frame is not None else {"ok": False}
        if meas.get("ok") and meas.get("empty"):
            e.update(outcome="no_geometry_yet", empty_model=True, camera_ok=True, settled_frame=bool(settled), deferred_reason="no solid or sketch geometry to frame yet")
            e["actual_orientation"] = "unchanged"
            self.entries.append(e)
            return e
        err0 = iso_error(before) if before else 9.9
        need_iso = orientation == "isometric" and err0 >= 0.01
        if orientation == "keep" and self._in_band(meas):
            e.update(outcome="no_move", settled_frame=bool(settled), geometry_visible=True, margins=meas["margins"], camera_ok=True, orientation_preserved=True,
                     actual_orientation="iso" if err0 < 0.01 else "unchanged")
            self.entries.append(e)
            return e
        if orientation == "isometric" and not need_iso and self._in_band(meas):
            e.update(outcome="already_isometric_in_frame", settled_frame=bool(settled), geometry_visible=True, margins=meas["margins"], camera_ok=True,
                     isometric_verified=True, actual_orientation="iso")
            self.entries.append(e)
            return e
        try:
            if need_iso:
                doc.ShowNamedView2(ISO_NAME, SW_ISOMETRIC_VIEW)
                e["ops"]["isometric"] = "issued"
            doc.ViewZoomtofit2()
            e["ops"]["zoom_to_fit"] = "issued"
            doc.GraphicsRedraw2()
        except Exception as ex:                          # noqa: BLE001
            e["ops"]["fit"] = f"failed: {type(ex).__name__}: {ex}"
        frame, settled, waited = self._wait_settled()
        e["settled_frame"] = bool(settled)
        meas = measure_margins(frame, self._viewport(doc, frame)) if frame is not None else {"ok": False}
        mv = self._model_view(doc)
        corrected, factors, pans = False, [], []
        pan_ok = True

        def score(m_: dict) -> float:
            """0 = perfect. Penalises touching the edge, a margin below the band, and an off-centre model."""
            if not (m_.get("ok") and m_.get("margins")) or m_.get("empty"):
                return 99.0
            mm = m_["margins"]
            return (5.0 if m_.get("touches_edge") else 0.0) + max(0.0, MARGIN_LO - min(mm.values())) + abs(mm["right"] - mm["left"]) / 2 + abs(mm["bottom"] - mm["top"]) / 2

        for _ in range(9):
            if mv is None or not meas.get("ok"):
                break
            if meas.get("empty"):                                       # the part left the picture: absolute fit again, then continue
                try:
                    doc.ViewZoomtofit2()
                    doc.GraphicsRedraw2()
                    e["ops"]["recover_fit"] = "issued (part left the picture)"
                except Exception:                        # noqa: BLE001
                    break
                frame, settled2, _w = self._wait_settled()
                meas = measure_margins(frame, self._viewport(doc, frame)) if frame is not None else {"ok": False}
                mv = self._model_view(doc)
                pan_ok = False                                          # whatever moved it away is not repeated
                continue
            if self._in_band(meas):
                break
            m = meas["margins"]
            uw = meas["usable"][2] - meas["usable"][0]
            uh = meas["usable"][3] - meas["usable"][1]
            used = max((meas["bbox"][2] - meas["bbox"][0]) / uw, (meas["bbox"][3] - meas["bbox"][1]) / uh)
            want = 1 - 2 * TARGET_MARGIN
            binding = min(m.values())
            before_score, base_tr = score(meas), None
            try:
                if meas.get("touches_edge"):
                    # a clipped extent under-reads the real size and its centroid is unreliable: ONLY zoom out until the whole part is inside, then centre
                    mv.ZoomByFactor(0.85)
                    factors.append(0.85)
                else:
                    f = max(0.6, min(1.5, want / max(used, 0.05))) if (binding < MARGIN_LO or binding > MARGIN_HI) else 1.0
                    if abs(f - 1) > 0.02:
                        mv.ZoomByFactor(float(f))
                        factors.append(round(f, 3))
                    if pan_ok:
                        dxp, dyp = (m["right"] - m["left"]) / 2 * uw, (m["bottom"] - m["top"]) / 2 * uh
                        if abs(dxp) > 8 or abs(dyp) > 8:
                            _mv, base_tr, _sc = self._translation(doc)
                            self._pan(doc, dxp, dyp, meas)
                            pans.append([round(dxp), round(dyp)])
                doc.GraphicsRedraw2()
                corrected = True
            except Exception as ex:                      # noqa: BLE001
                e["ops"]["margin_adjust"] = f"failed: {type(ex).__name__}: {ex}"
                pan_ok = False
                break
            frame, settled2, _w = self._wait_settled()
            settled = settled and settled2
            new_meas = measure_margins(frame, self._viewport(doc, frame)) if frame is not None else {"ok": False}
            if base_tr is not None and score(new_meas) > before_score + 0.02:
                try:                                              # the pan made it worse: undo it, keep the zoom, and stop panning
                    self._set_translation(self._translation(doc)[0], base_tr)
                    doc.GraphicsRedraw2()
                    e["ops"]["pan_reverted"] = True
                    frame, settled2, _w = self._wait_settled()
                    new_meas = measure_margins(frame, self._viewport(doc, frame)) if frame is not None else {"ok": False}
                except Exception:                        # noqa: BLE001
                    pass
                pan_ok = False
            meas = new_meas
            mv = self._model_view(doc)
        e["settled_frame"] = bool(settled)
        e["ops"]["margin_zoom_factors"], e["ops"]["pan_px"] = factors, pans
        after = self._orientation(doc)
        e["margins"] = meas.get("margins")
        e["geometry_visible"] = bool(meas.get("ok") and not meas.get("touches_edge") and not meas.get("empty"))
        e["margin_in_band"] = self._in_band(meas)
        if orientation == "isometric":
            e["isometric_error"] = round(iso_error(after), 4) if after else None
            e["isometric_verified"] = bool(after and iso_error(after) < 0.01)
            e["actual_orientation"] = "iso" if e["isometric_verified"] else "not isometric"
            orient_ok = e["isometric_verified"]
        else:
            e["orientation_preserved"] = self._same_orientation(before, after)
            e["actual_orientation"] = "preserved" if e["orientation_preserved"] else "changed"
            orient_ok = e["orientation_preserved"] is not False
        e["margin_corrected"] = corrected
        e["camera_ok"] = bool(orient_ok and settled and e["geometry_visible"])
        e["outcome"] = "moved" if e["camera_ok"] else "failed"
        if not e["camera_ok"]:
            why = []
            if not orient_ok:
                why.append("orientation not as requested")
            if not settled:
                why.append("no settled frame")
            if not e["geometry_visible"]:
                why.append("geometry touches or leaves the viewport edge, or the frame is unreadable")
            e["reason"] = "; ".join(why)
            self.failures.append(f"{op_id} ({event}): {e['reason']}")
        self.entries.append(e)
        return e

    def on_action_boundary(self, doc, op_id: str, event: str = "action_boundary") -> dict:
        """Before/after a meaningful action at a safe boundary (nothing open): keep the orientation, show the whole part, only move when needed."""
        return self._fit(doc, op_id, event, "keep")

    def on_feature_committed(self, doc, op_id: str, status: str) -> dict:
        """A feature operation finished. Counts toward the isometric cadence only when it is a distinct, successfully built feature."""
        op_id = str(op_id)
        if status != "built":
            self.entries.append({"event": "feature_not_counted", "op_id": op_id, "feature_count": self.completed_feature_count, "status": status,
                                 "reason": "failed / mismatch: not a completed feature", "t": time.time()})
            return self.on_action_boundary(doc, op_id, "after_failed_feature")
        if op_id in self._seen_ops:
            self.entries.append({"event": "feature_not_counted", "op_id": op_id, "feature_count": self.completed_feature_count,
                                 "reason": "duplicate operation id (retry of the same logical operation)", "t": time.time()})
            return self.on_action_boundary(doc, op_id, "after_duplicate_feature")
        self._seen_ops.add(op_id)
        self.completed_feature_count += 1
        res = self._fit(doc, op_id, "feature_committed", "keep")
        self._iso_pending_final = True
        if ISO_EVERY > 0 and self.completed_feature_count % ISO_EVERY == 0:
            res = self._fit(doc, op_id, "isometric_checkpoint", "isometric")
            self._iso_pending_final = False                           # the last picture is already the full-part isometric view
        return res

    def on_build_completed(self, doc) -> dict:
        """Final presentation: always the whole part in isometric. Coalesced with an even-feature checkpoint that already produced it."""
        coalesced = not self._iso_pending_final and self.completed_feature_count > 0
        res = self._fit(doc, "final", "build_completed", "isometric")
        res["coalesced_with_checkpoint"] = bool(coalesced and res.get("outcome") in ("already_isometric_in_frame", "no_move"))
        res["final"] = True
        return res

    def frame(self, doc, label: str, *, initial: bool = False, final: bool = False) -> dict:
        """Compatibility entry point (older callers): initial/ordinary -> action boundary, final -> build completed."""
        return self.on_build_completed(doc) if final else self.on_action_boundary(doc, label, "initial" if initial else "action_boundary")

    # ---------------------------------------------------------------- report
    def summary(self) -> dict:
        evs = [x for x in self.entries if x.get("event") in ("feature_committed", "isometric_checkpoint", "build_completed", "action_boundary",
                                                                 "initial", "after_failed_feature", "after_duplicate_feature")]
        iso = [x for x in evs if x.get("event") in ("isometric_checkpoint", "build_completed")]
        return {"ok": not self.failures and bool(evs), "events_checked": len(evs), "completed_features": self.completed_feature_count,
                "isometric_events": len(iso), "isometric_verified": sum(1 for x in iso if x.get("isometric_verified")),
                "no_move_events": sum(1 for x in evs if x.get("outcome") == "no_move"),
                "fit_verified": sum(1 for x in evs if x.get("geometry_visible") or x.get("empty_model")),
                "orientation_preserved": sum(1 for x in evs if x.get("orientation_preserved")),
                "margin_corrections": sum(1 for x in evs if x.get("margin_corrected")),
                "failures": self.failures[:20], "target_margin": TARGET_MARGIN, "iso_every": ISO_EVERY, "log": CAMERA_LOG}

    def write_log(self) -> None:
        if self.out is None:
            return
        try:
            tmp = self.out / (CAMERA_LOG + ".tmp")
            tmp.write_text(json.dumps({"summary": self.summary(), "entries": self.entries}, indent=1, default=str), encoding="utf-8")
            os.replace(tmp, self.out / CAMERA_LOG)
        except Exception:                                # noqa: BLE001
            pass
