"""Camera / presentation logic for the SolidWorks recording (no SolidWorks needed: fake document and fake picture source)."""
import numpy as np
import pytest

from pipeline import solidworks_camera as cam


def _picture(box=None, w=1536, h=822):
    """A light viewport picture with an optional dark rectangle (x0, y0, x1, y1) standing in for the model."""
    img = np.full((h, w, 3), 250, np.uint8)
    if box:
        x0, y0, x1, y1 = box
        img[y0:y1, x0:x1] = (110, 110, 110)
    return img


VIEWPORT = (33, 109, 1529, 798)


def test_iso_error_matches_standard_isometric_and_rejects_front_view():
    assert cam.iso_error(cam.ISO_MATRIX) < 1e-6
    front = (1, 0, 0, 0, 1, 0, 0, 0, 1)
    assert cam.iso_error(front) > 0.1
    assert cam.iso_error(None) > 1


def test_measure_margins_centered_model_has_equal_margins():
    m = cam.measure_margins(_picture((560, 330, 980, 640)), VIEWPORT)
    assert m["ok"] and not m["empty"] and not m["touches_edge"]
    assert abs(m["margins"]["left"] - m["margins"]["right"]) < 0.05
    assert m["margins"]["top"] > 0.05 and m["margins"]["bottom"] > 0.05


def test_measure_margins_detects_a_model_cut_by_the_bottom_edge():
    m = cam.measure_margins(_picture((700, 400, 1200, 790)), VIEWPORT)
    assert m["ok"] and m["touches_edge"]


def test_measure_margins_reports_empty_viewport_without_inventing_a_fit():
    m = cam.measure_margins(_picture(None), VIEWPORT)
    assert m["ok"] and m["empty"] and not m["margins"]


def test_measure_margins_rejects_a_missing_picture():
    assert cam.measure_margins(None)["ok"] is False


def test_stray_pixels_do_not_count_as_geometry():
    img = _picture()
    img[500, 60] = (0, 0, 0)
    img[300, 1500] = (0, 0, 0)
    assert cam.measure_margins(img, VIEWPORT)["empty"]


class _View:
    def __init__(self, doc):
        self.doc = doc
        self.Scale2 = 1.0

    @property
    def Orientation3(self):
        class _T:
            ArrayData = cam.ISO_MATRIX if self.doc.iso else (1, 0, 0, 0, 1, 0, 0, 0, 1)
        return _T()

    def ZoomByFactor(self, f):
        self.doc.zooms.append(f)


class _Doc:
    def __init__(self, iso_ok=True, raise_on=None):
        self.iso, self.calls, self.zooms = False, [], []
        self.iso_ok, self.raise_on = iso_ok, raise_on
        self.ActiveView = _View(self)

    def ShowNamedView2(self, name, view_id):
        self.calls.append(("iso", name, view_id))
        if self.raise_on == "iso":
            raise RuntimeError("boom")
        self.iso = self.iso_ok

    def ViewZoomtofit2(self):
        self.calls.append(("fit",))

    def GraphicsRedraw2(self):
        self.calls.append(("redraw",))


def _controller(frames, doc=None):
    it = iter(frames)
    last = {"f": frames[-1]}

    def grab():
        try:
            last["f"] = next(it)
        except StopIteration:
            pass
        return last["f"]
    c = cam.CameraController(None, 0, grab=grab, viewport_finder=lambda d, f: VIEWPORT)
    return c, doc or _Doc()


def test_frame_uses_native_isometric_and_fit_and_verifies_the_picture(monkeypatch):
    good = _picture((560, 330, 980, 640))
    c, doc = _controller([good] * 6)
    e = c.frame(doc, "F001")
    assert ("iso", "*Isometric", 7) in doc.calls and ("fit",) in doc.calls and ("redraw",) in doc.calls
    assert e["isometric_verified"] and e["settled_frame"] and e["geometry_visible"] and e["camera_ok"]
    assert c.summary()["ok"] is True


def test_not_isometric_is_flagged_not_assumed():
    good = _picture((560, 330, 980, 640))
    c, doc = _controller([good] * 6, _Doc(iso_ok=False))
    e = c.frame(doc, "F002")
    assert e["isometric_verified"] is False and e["camera_ok"] is False
    s = c.summary()
    assert s["ok"] is False and any("isometric" in f for f in s["failures"])


def test_a_failing_camera_command_is_logged_and_never_raises():
    good = _picture((560, 330, 980, 640))
    c, doc = _controller([good] * 6, _Doc(raise_on="iso"))
    e = c.frame(doc, "F003")
    assert e["ops"]["isometric"].startswith("failed")
    assert e["camera_ok"] is False


def test_clipped_model_triggers_zoom_correction_attempts():
    clipped = _picture((700, 400, 1200, 790))
    c, doc = _controller([clipped] * 30)
    c.frame(doc, "F004")
    assert doc.zooms, "a clipped model must be zoomed out"


def test_empty_model_is_a_valid_no_geometry_case():
    c, doc = _controller([_picture(None)] * 6)
    e = c.frame(doc, "initial", initial=True)
    assert e["empty_model"] and e["camera_ok"]


def test_restore_is_safe_without_prepare_and_writes_a_log(tmp_path):
    c = cam.CameraController(None, 0, grab=None, out_dir=tmp_path)
    assert c.restore()["event"] == "restore"
    c.write_log()
    assert (tmp_path / cam.CAMERA_LOG).exists()
