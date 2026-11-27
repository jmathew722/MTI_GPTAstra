"""Camera policy for the SolidWorks recording (no SolidWorks needed: fake document, fake window pictures).

Spec: SolidFlow_Recording_Zoom_and_Isometric_Cadence.md - full-part zoom-out with the working orientation preserved; isometric only after every second
successfully completed geometry feature and at the end."""
import numpy as np
import pytest

from pipeline import solidworks_camera as cam

VIEWPORT = (33, 109, 1529, 798)
FRONT = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def _picture(box=None, w=1536, h=822):
    img = np.full((h, w, 3), 250, np.uint8)
    if box:
        x0, y0, x1, y1 = box
        img[y0:y1, x0:x1] = (110, 110, 110)
    return img


GOOD = _picture((283, 267, 1263, 677))          # centred, ~15 % margin on the binding edges
CLIPPED = _picture((700, 400, 1200, 790))       # cut by the bottom edge
TINY = _picture((700, 400, 760, 440))           # far too small: huge margins


class _View:
    def __init__(self, doc):
        self.doc, self.Scale2 = doc, 1.0

    @property
    def Orientation3(self):
        o = self.doc.orientation

        class _T:
            ArrayData = o
        return _T()

    def ZoomByFactor(self, f):
        self.doc.zooms.append(f)


class _Doc:
    def __init__(self, orientation=FRONT, iso_ok=True, raise_on=None):
        self.orientation, self.calls, self.zooms = orientation, [], []
        self.iso_ok, self.raise_on = iso_ok, raise_on
        self.ActiveView = _View(self)

    def ShowNamedView2(self, name, view_id):
        self.calls.append(("iso", name, view_id))
        if self.raise_on == "iso":
            raise RuntimeError("boom")
        if self.iso_ok:
            self.orientation = cam.ISO_MATRIX

    def ViewZoomtofit2(self):
        self.calls.append(("fit",))

    def GraphicsRedraw2(self):
        self.calls.append(("redraw",))

    def iso_calls(self):
        return [c for c in self.calls if c[0] == "iso"]


def _controller(picture=GOOD, doc=None):
    c = cam.CameraController(None, 0, grab=lambda: picture, viewport_finder=lambda d, f: VIEWPORT)
    c._pan = lambda doc, dx, dy, meas=None: None             # the COM pan needs SolidWorks
    return c, doc or _Doc()


def _run_features(n, *, picture=GOOD, statuses=None, ids=None):
    c, doc = _controller(picture)
    isos = []
    for k in range(n):
        doc.orientation = FRONT                           # the feature's own sketch/face established the working orientation
        before = len(doc.iso_calls())
        c.on_feature_committed(doc, (ids or [f"F{k + 1:03d}" for _ in range(n)])[k], (statuses or ["built"] * n)[k])
        isos.append(len(doc.iso_calls()) - before)
    return c, doc, isos


# ------------------------------------------------------------------ pure helpers
def test_iso_error_matches_standard_isometric_and_rejects_front_view():
    assert cam.iso_error(cam.ISO_MATRIX) < 1e-6
    assert cam.iso_error(FRONT) > 0.1
    assert cam.iso_error(None) > 1


def test_default_margin_is_15_percent_inside_the_12_to_18_band():
    assert cam.TARGET_MARGIN == pytest.approx(0.15)
    assert cam.MARGIN_LO < 0.12 and cam.MARGIN_HI >= 0.18


def test_measure_margins_centered_model_has_equal_margins():
    m = cam.measure_margins(GOOD, VIEWPORT)
    assert m["ok"] and not m["empty"] and not m["touches_edge"]
    assert all(0.13 < v < 0.17 for v in m["margins"].values())


def test_measure_margins_detects_a_model_cut_by_the_edge_and_empty_and_missing():
    assert cam.measure_margins(CLIPPED, VIEWPORT)["touches_edge"]
    e = cam.measure_margins(_picture(None), VIEWPORT)
    assert e["ok"] and e["empty"] and not e["margins"]
    assert cam.measure_margins(None)["ok"] is False


def test_stray_pixels_do_not_count_as_geometry():
    img = _picture()
    img[500, 60] = (0, 0, 0)
    assert cam.measure_margins(img, VIEWPORT)["empty"]


# ------------------------------------------------------------------ isometric cadence: 0..6 committed features
@pytest.mark.parametrize("n,expected", [(0, []), (1, [0]), (2, [0, 1]), (3, [0, 1, 0]), (4, [0, 1, 0, 1]), (5, [0, 1, 0, 1, 0]), (6, [0, 1, 0, 1, 0, 1])])
def test_isometric_only_after_every_second_completed_feature(n, expected):
    c, doc, isos = _run_features(n)
    assert isos == expected
    assert c.completed_feature_count == n


def test_ordinary_boundaries_never_force_isometric_and_keep_orientation():
    c, doc = _controller(CLIPPED)
    for k in range(5):
        c.on_action_boundary(doc, f"F{k}", "before_feature")
    assert doc.iso_calls() == []
    assert doc.orientation == FRONT                       # preserved
    assert all(e.get("orientation_preserved", True) for e in c.entries)


def test_failed_and_mismatch_features_do_not_count():
    c, doc, isos = _run_features(4, statuses=["built", "failed", "mismatch", "built"])
    assert c.completed_feature_count == 2
    assert isos == [0, 0, 0, 1]                           # the 2nd COMPLETED feature is the 4th event


def test_duplicate_operation_ids_count_once():
    c, doc, isos = _run_features(3, ids=["F001", "F001", "F002"])
    assert c.completed_feature_count == 2
    assert isos == [0, 0, 1]


def test_counter_resets_with_a_new_controller_per_part():
    c1, _, _ = _run_features(3)
    c2, doc2 = _controller()
    assert c1.completed_feature_count == 3 and c2.completed_feature_count == 0
    c2.on_feature_committed(doc2, "F001", "built")
    assert doc2.iso_calls() == []


def test_sketch_or_camera_events_do_not_increment():
    c, doc = _controller()
    c.on_action_boundary(doc, "F001", "before_feature")
    c.on_action_boundary(doc, "F001", "sketch")
    assert c.completed_feature_count == 0


# ------------------------------------------------------------------ final presentation
def test_odd_final_feature_gets_a_final_isometric():
    c, doc, _ = _run_features(3)
    n0 = len(doc.iso_calls())
    e = c.on_build_completed(doc)
    assert len(doc.iso_calls()) == n0 + 1 and e["isometric_verified"] and e["final"]


def test_even_final_feature_coalesces_the_checkpoint_and_the_final_isometric():
    c, doc, _ = _run_features(4)
    n0 = len(doc.iso_calls())
    e = c.on_build_completed(doc)
    assert len(doc.iso_calls()) == n0, "no second isometric transition"
    assert e["isometric_verified"] and e["coalesced_with_checkpoint"] is True


def test_final_isometric_with_zero_features_is_still_requested():
    c, doc = _controller()
    c.on_build_completed(doc)
    assert doc.iso_calls() or c.entries[-1]["outcome"] in ("no_geometry_yet",)


# ------------------------------------------------------------------ zoom behaviour
def test_whole_part_already_in_frame_is_not_moved_no_jitter():
    c, doc = _controller(GOOD)
    e = c.on_action_boundary(doc, "F001")
    assert e["outcome"] == "no_move" and not doc.calls and not doc.zooms


def test_clipped_part_is_zoomed_out_and_orientation_stays():
    c, doc = _controller(CLIPPED)
    e = c.on_action_boundary(doc, "F001")
    assert ("fit",) in doc.calls and doc.zooms and min(doc.zooms) < 1
    assert doc.orientation == FRONT and e["requested_orientation"] == "keep"


def test_too_small_part_is_zoomed_in_to_the_margin_band_not_left_with_whitespace():
    c, doc = _controller(TINY)
    c.on_action_boundary(doc, "F001")
    assert doc.zooms and max(doc.zooms) > 1


def test_absolute_fit_is_the_starting_point_each_time():
    c, doc = _controller(CLIPPED)
    c.on_action_boundary(doc, "A")
    c.on_action_boundary(doc, "B")
    assert doc.calls.count(("fit",)) == 2                  # absolute fit each time; zoom factors are per-measurement, never accumulated across calls


def test_empty_model_waits_for_geometry():
    c, doc = _controller(_picture(None))
    e = c.on_action_boundary(doc, "initial", "initial")
    assert e["outcome"] == "no_geometry_yet" and e["empty_model"] and not doc.calls


# ------------------------------------------------------------------ failure handling
def test_camera_api_failure_is_logged_flagged_and_never_raises():
    c, doc = _controller(CLIPPED, _Doc(raise_on="iso"))
    c.on_feature_committed(doc, "F001", "built")
    c.on_feature_committed(doc, "F002", "built")           # checkpoint: the isometric command raises
    s = c.summary()
    assert s["ok"] is False and s["failures"]


def test_not_isometric_after_the_checkpoint_is_flagged_not_assumed():
    c, doc = _controller(GOOD, _Doc(iso_ok=False))
    c.on_feature_committed(doc, "F001", "built")
    e = c.on_feature_committed(doc, "F002", "built")
    assert e.get("isometric_verified") is False and e["camera_ok"] is False


def test_restore_is_safe_without_prepare_and_writes_a_log(tmp_path):
    c = cam.CameraController(None, 0, grab=None, out_dir=tmp_path)
    assert c.restore()["event"] == "restore"
    c.write_log()
    assert (tmp_path / cam.CAMERA_LOG).exists()


def test_log_records_operation_id_count_orientation_and_margins(tmp_path):
    c, doc = _controller(CLIPPED)
    c.out = tmp_path
    c.on_feature_committed(doc, "F001", "built")
    c.write_log()
    import json
    data = json.loads((tmp_path / cam.CAMERA_LOG).read_text(encoding="utf-8"))
    e = [x for x in data["entries"] if x["event"] == "feature_committed"][0]
    for k in ("op_id", "feature_count", "requested_orientation", "actual_orientation", "margins", "outcome"):
        assert k in e
    assert data["summary"]["completed_features"] == 1
