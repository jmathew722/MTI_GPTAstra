"""SolidWorks build recorder: manifest, failure codes, stale clearing, limits. No SolidWorks needed (synthetic frame source)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from pipeline import solidworks_recorder as rec

cv2 = pytest.importorskip("cv2")
imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")


class FakeSource(rec.FrameSource):
    name = "fake"

    def __init__(self, frame=None, covered=False, black=False):
        self.frame = np.full((120, 200, 3), 0 if black else 140, np.uint8) if frame is None else frame
        self.covered, self.started, self.stopped = covered, False, False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def latest(self):
        return (None, True) if self.covered else (self.frame, False)


class FlipSource(FakeSource):
    """Every other poll is covered (a window in the way)."""
    n = 0

    def latest(self):
        FlipSource.n += 1
        return (None, True) if FlipSource.n % 2 else (self.frame, False)


def make(out, source=None, **kw):
    kw.setdefault("fps", 10)
    kw.setdefault("paced", False)
    kw.setdefault("hold_s", 0)
    return rec.SolidWorksRecorder(out, part="P", run_id="run1", source_sha256="abc",
                                  source_factory=lambda hwnd: source or FakeSource(), **kw)


def test_capability_shape():
    c = rec.capability()
    assert set(c) == {"available", "backend", "encoder", "reason"}
    assert isinstance(c["available"], bool)
    if not c["available"]:
        assert c["reason"]


def test_wanted_reads_env(monkeypatch):
    monkeypatch.delenv(rec.ENV_FLAG, raising=False)
    assert rec.wanted() is False
    monkeypatch.setenv(rec.ENV_FLAG, "1")
    assert rec.wanted() is True


def test_records_a_playable_video_with_chapters(tmp_path):
    r = make(tmp_path)
    assert r.start() is True
    assert json.loads((tmp_path / rec.MANIFEST).read_text())["status"] == "recording"   # visible while it runs
    time.sleep(0.4)
    r.after_feature("F001", "prism", "built")
    time.sleep(0.4)
    r.after_feature("F002", "hole", "built")
    time.sleep(0.3)
    m = r.stop(outcome="completed")
    assert m["status"] == "ready" and m["code"] == ""
    assert m["video"].endswith((".mp4", ".webm")) and (tmp_path / m["video"]).stat().st_size > 0
    assert m["frames"] >= 8 and m["dropped_frames"] == 0 and m["backend"] == "fake"
    assert m["bytes"] == (tmp_path / m["video"]).stat().st_size
    assert [c["id"] for c in m["chapters"]] == ["F001", "F002"]
    assert m["chapters"][0]["t"] <= m["chapters"][1]["t"]
    assert m["build_outcome"] == "completed" and m["schema_version"] == 1 and m["generation_key"]
    assert (tmp_path / rec.POSTER).is_file()
    assert not list(tmp_path.glob("*.partial*")), "the temporary partial file is renamed away"
    v = cv2.VideoCapture(str(tmp_path / m["video"]))
    assert v.isOpened() and v.get(cv2.CAP_PROP_FRAME_COUNT) >= 8
    ok, frame = v.read()
    assert ok and frame.shape[1] % 2 == 0 and frame.shape[0] % 2 == 0


def test_covered_window_is_dropped_not_recorded(tmp_path):
    FlipSource.n = 0
    r = make(tmp_path, FlipSource())
    r.start()
    time.sleep(0.8)
    m = r.stop()
    assert m["status"] == "partial" and m["code"] == "REC_COVERED" and m["dropped_frames"] > 0
    assert m["video"]


def test_only_covered_frames_is_a_failure_not_a_blank_video(tmp_path):
    r = make(tmp_path, FakeSource(covered=True))
    r.start()
    time.sleep(0.5)
    m = r.stop()
    assert m["status"] == "failed" and m["code"] == "REC_NO_FRAMES" and not m["video"]
    assert not list(tmp_path.glob("solidworks_recording.*mp4")) and not list(tmp_path.glob("*.partial*"))


def test_black_capture_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "BLACK_AFTER_S", 0.2)
    r = make(tmp_path, FakeSource(black=True))
    r.start()
    time.sleep(0.8)
    m = r.stop()
    assert m["code"] == "REC_CAPTURE_BLACK" and m["status"] in ("partial", "failed")


def test_time_limit_stops_cleanly(tmp_path):
    r = make(tmp_path, max_seconds=0.5)
    r.start()
    time.sleep(1.2)
    m = r.stop()
    assert m["status"] == "partial" and m["code"] == "REC_LIMIT_REACHED" and m["video"]
    assert m["duration_s"] <= 1.5


def test_encoder_failure_is_a_code_not_an_exception(tmp_path):
    def boom(out, size, fps):
        raise RuntimeError("no encoder")
    r = make(tmp_path, encoder_factory=boom)
    r.start()
    time.sleep(0.4)
    m = r.stop()                                   # must not raise
    assert m["status"] == "failed" and m["code"] == "REC_WRITE_FAILED" and not m["video"]


def test_no_window_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "capability", lambda: {"available": True, "backend": "wgc", "encoder": "x", "reason": ""})
    r = rec.SolidWorksRecorder(tmp_path, part="P", run_id="r", window_finder=lambda app: None)
    assert r.start() is False
    m = r.read_manifest()
    assert m["status"] == "failed" and m["code"] == "REC_NO_WINDOW" and m["reason"]
    assert r.stop()["code"] == "REC_NO_WINDOW"        # stop after a failed start is a harmless no-op
    r.after_feature("F1", "hole", "built")            # and so is a late hook


def test_unavailable_platform_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "capability", lambda: {"available": False, "backend": None, "encoder": None, "reason": "nope"})
    r = rec.SolidWorksRecorder(tmp_path, part="P", run_id="r")
    assert r.start() is False and r.read_manifest()["code"] == "REC_UNAVAILABLE"


def test_clear_stale_and_skipped(tmp_path):
    for n in (rec.MANIFEST, rec.POSTER, "solidworks_recording.mp4", "solidworks_recording.partial.mp4"):
        (tmp_path / n).write_bytes(b"x")
    rec.clear_stale(tmp_path)
    assert not any(tmp_path.iterdir())
    rec.write_skipped(tmp_path, run_id="r9", part="P", source_sha256="s", reason="Extraction failed")
    m = json.loads((tmp_path / rec.MANIFEST).read_text())
    assert m["status"] == "skipped" and m["code"] == "REC_NOT_REACHED" and m["reason"] == "Extraction failed" and m["run_id"] == "r9"


def test_stop_is_idempotent_and_context_manager_marks_a_failed_build(tmp_path):
    with pytest.raises(ValueError):
        with make(tmp_path) as r:
            time.sleep(0.3)
            raise ValueError("compile blew up")
    m = r.read_manifest()
    assert m["build_outcome"] == "failed" and "compile blew up" in m["build_error"] and m["video"]
    assert r.stop() == m                              # second stop changes nothing


def test_caption_is_ascii_and_bounded():
    assert rec._ascii("F1 · café") == "F1  |  caf?"
    assert len(rec._ascii("x" * 500)) == 90


def test_output_size_is_even_and_capped():
    w, h = rec._fit_size(3840, 2160)
    assert w <= rec.MAX_W and h <= rec.MAX_H and w % 2 == 0 and h % 2 == 0
    assert rec._fit_size(1521, 857) == (1520, 856)


def test_cli_flag_turns_on_recording_for_the_run(monkeypatch):
    """main.py --record-solidworks -> GPTASTRA_RECORD_SOLIDWORKS=1 -> pipeline.solidworks_recorder.wanted()."""
    import main
    monkeypatch.delenv(rec.ENV_FLAG, raising=False)
    monkeypatch.setattr(main, "_run", lambda args: 0)
    monkeypatch.setattr("sys.argv", ["main.py", "--drawing", "x.pdf", "--record-solidworks"])
    assert main.main() == 0
    assert rec.wanted() is True
    monkeypatch.delenv(rec.ENV_FLAG, raising=False)
    monkeypatch.setattr("sys.argv", ["main.py", "--drawing", "x.pdf"])
    assert main.main() == 0
    assert rec.wanted() is False


def test_run_part_accepts_record_and_clears_stale_recordings():
    import inspect
    from pipeline import ir_pipeline
    sig = inspect.signature(ir_pipeline.run_part)
    assert "record" in sig.parameters and sig.parameters["record"].default is None


# ------------------------------------------------------------------ window-only capture guarantees (v5 recording fixes)

def test_no_desktop_capture_code_remains():
    src = Path(rec.__file__).read_text(encoding="utf-8")
    for banned in ("GdiSource", "BitBlt", "GetDesktopWindow", "ImageGrab", "mss(", "SRCCOPY", "GetDC(0)"):
        assert banned not in src, banned


def test_is_occluded_fails_closed_for_a_non_window():
    assert rec.is_occluded(0) is True
    assert rec.is_occluded(123456789) is True


def test_validate_window_rejects_non_window_and_reports_reason():
    v = rec.validate_window(0)
    assert v["ok"] is False and v["reason"]


def test_window_state_lost_for_missing_handle():
    assert rec.window_state(987654321, 1) == "lost"


def test_capability_has_no_desktop_backend():
    cap = rec.capability()
    assert cap["backend"] in (None, "printwindow", "wgc")


def test_frame_sources_are_window_only():
    assert rec.PrintWindowSource.name == "printwindow"
    assert rec.WgcSource.name == "wgc"
