"""Record the SolidWorks window while the pipeline builds the part ("Record Pipeline Run").

Design: docs/superpowers/specs/2026-11-19-solidworks-recording-design.md

* Only the SolidWorks window is captured, only for the SolidWorks build (``SolidWorksRecorder`` wraps ``compile_solidworks``).
* The recorder NEVER raises into the build. Every failure becomes a manifest ``status`` + ``code`` (the UI shows it).
* Backends: Windows Graphics Capture (records that one window even when covered) first; a screen-rectangle copy with a privacy gate
  (a covered frame is dropped, the last good frame is held) as the fallback.
* Win32 / OpenCV / encoder imports are lazy, so this module imports on any OS and the tests run without SolidWorks.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from utils.logger import get_logger

log = get_logger()

MANIFEST = "solidworks_recording.json"
POSTER = "solidworks_recording_poster.jpg"
VIDEO_STEM = "solidworks_recording"
VIDEO_EXTS = (".mp4", ".webm")
SCHEMA_VERSION = 1
STATUSES = ("recording", "ready", "partial", "failed", "skipped")
ENV_FLAG = "GPTASTRA_RECORD_SOLIDWORKS"

DEFAULT_FPS = 10
MAX_SECONDS = 20 * 60
MAX_BYTES = 500 * 1024 * 1024
MAX_W, MAX_H = 1600, 1000
HOLD_S = 0.6                       # paced build: let the viewport show each feature
BLACK_AFTER_S = 4.0                # all-black frames for this long = REC_CAPTURE_BLACK

CODES = {
    "REC_UNAVAILABLE": "Recording needs Windows.",
    "REC_NO_WINDOW": "The SolidWorks window was not found.",
    "REC_ENCODER_MISSING": "No video encoder is installed (pip install imageio-ffmpeg).",
    "REC_CAPTURE_BLACK": "The SolidWorks window captured as black.",
    "REC_NO_FRAMES": "No frames were captured.",
    "REC_COVERED": "Part of the recording is missing: another window covered SolidWorks.",
    "REC_LIMIT_REACHED": "The recording hit its time or size limit and stopped.",
    "REC_WRITE_FAILED": "The video could not be written.",
    "REC_NOT_REACHED": "The run never reached the SolidWorks build.",
}


def wanted() -> bool:
    return os.environ.get(ENV_FLAG, "").strip() in ("1", "true", "yes")


# ----------------------------------------------------------------------------------------------- capability

def capability() -> dict:
    """What this machine can do, without needing SolidWorks to be running. Shape: {available, backend, encoder, reason}."""
    import importlib.util as u
    if sys.platform != "win32":
        return {"available": False, "backend": None, "encoder": None, "reason": CODES["REC_UNAVAILABLE"]}
    have = lambda m: u.find_spec(m) is not None    # noqa: E731
    if not (have("numpy") and have("cv2")):
        return {"available": False, "backend": None, "encoder": None,
                "reason": "Recording needs numpy and opencv-python."}
    encoder = "imageio-ffmpeg" if have("imageio_ffmpeg") else "opencv-webm"
    backend = "wgc" if have("windows_capture") else ("gdi" if have("win32gui") and have("win32ui") else None)
    if backend is None:
        return {"available": False, "backend": None, "encoder": encoder,
                "reason": "No window-capture backend (pip install windows-capture, or pywin32)."}
    return {"available": True, "backend": backend, "encoder": encoder, "reason": ""}


# ----------------------------------------------------------------------------------------------- files

def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def clear_stale(out: Path) -> None:
    """Remove a previous run's recording so an old video is never shown for this run."""
    out = Path(out)
    for name in [MANIFEST, POSTER] + [VIDEO_STEM + e for e in VIDEO_EXTS] + [VIDEO_STEM + ".partial" + e for e in VIDEO_EXTS]:
        try:
            (out / name).unlink()
        except FileNotFoundError:
            pass
        except OSError as e:          # a locked file must not fail the run
            log.warning("could not remove stale recording file %s: %s", name, e)


def write_manifest(out: Path, data: dict) -> None:
    data = dict(data)
    data["schema_version"] = SCHEMA_VERSION
    key = f"{data.get('run_id', '')}|{data.get('status', '')}|{data.get('frames', 0)}|{data.get('bytes', 0)}"
    import hashlib
    data["generation_key"] = hashlib.sha1(key.encode()).hexdigest()[:12]
    _atomic_write(Path(out) / MANIFEST, json.dumps(data, indent=2))


def write_skipped(out: Path, *, run_id: str, part: str, source_sha256: str = "", reason: str = "") -> None:
    """Recording was requested but the run never reached the SolidWorks build."""
    try:
        write_manifest(out, {"status": "skipped", "run_id": run_id, "part": part, "source_sha256": source_sha256,
                             "code": "REC_NOT_REACHED", "reason": (reason or CODES["REC_NOT_REACHED"])[:300],
                             "frames": 0, "dropped_frames": 0, "duration_s": 0, "bytes": 0, "chapters": []})
    except Exception as e:      # noqa: BLE001
        log.warning("could not write the skipped recording manifest: %s", e)


# ----------------------------------------------------------------------------------------------- window

def find_solidworks_window(sw_app=None) -> Optional[int]:
    """hwnd of the SolidWorks main window: by process id when the app object can say it, else by title."""
    try:
        import win32gui
        import win32process
    except Exception:                                   # noqa: BLE001
        return None
    pid = None
    if sw_app is not None:
        try:
            pid = int(sw_app.GetProcessID())
        except Exception:                               # noqa: BLE001
            try:
                pid = int(sw_app.GetProcessID)
            except Exception:                           # noqa: BLE001
                pid = None
    found: list[tuple[int, int]] = []

    def cb(h, _):
        try:
            if not win32gui.IsWindowVisible(h) or win32gui.GetParent(h):
                return
            title = win32gui.GetWindowText(h)
            _tid, wpid = win32process.GetWindowThreadProcessId(h)
            if (pid and wpid == pid and title) or (not pid and title.startswith("SOLIDWORKS")):
                l, t, r, b = win32gui.GetWindowRect(h)
                found.append(((r - l) * (b - t), h))
        except Exception:                               # noqa: BLE001
            return
    win32gui.EnumWindows(cb, None)
    if not found:
        return None
    return max(found)[1]                                # the largest top-level window of the process


def _restore_if_minimised(hwnd: int) -> None:
    try:
        import win32con
        import win32gui
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.8)
    except Exception:                                   # noqa: BLE001
        pass


# ----------------------------------------------------------------------------------------------- frame sources

class FrameSource:
    """latest() -> (BGR ndarray | None, covered). start()/stop(). ``name`` is the backend label."""
    name = "source"

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def latest(self) -> tuple[Any, bool]:
        return None, False


class WgcSource(FrameSource):
    """Windows Graphics Capture of one window. Delivers a frame only when the window changes; the recorder resamples."""
    name = "wgc"

    def __init__(self, hwnd: int):
        self.hwnd, self._lock, self._frame, self._ctl = hwnd, threading.Lock(), None, None

    def start(self) -> None:
        from windows_capture import WindowsCapture
        cap = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=self.hwnd)

        @cap.event
        def on_frame_arrived(frame, _ctl):               # noqa: ANN001
            try:
                buf = frame.frame_buffer
                bgr = buf[..., :3].copy()
                with self._lock:
                    self._frame = bgr
            except Exception:                            # noqa: BLE001
                pass

        @cap.event
        def on_closed():                                 # noqa: ANN202
            return None

        self._ctl = cap.start_free_threaded()

    def stop(self) -> None:
        try:
            if self._ctl is not None:
                self._ctl.stop()
        except Exception:                                # noqa: BLE001
            pass

    def latest(self):
        with self._lock:
            return self._frame, False


class GdiSource(FrameSource):
    """Copy the window rectangle from the screen. Fallback: needs SolidWorks on top, so a covered frame is DROPPED (privacy gate)."""
    name = "gdi"

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:                                # noqa: BLE001
            pass
        self._pid = None
        try:
            import win32process
            self._pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        except Exception:                                # noqa: BLE001
            pass

    def _rect(self) -> tuple[int, int, int, int]:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        try:   # DWMWA_EXTENDED_FRAME_BOUNDS: the visible frame, without the invisible resize border
            if ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(self.hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:
                return r.left, r.top, r.right, r.bottom
        except Exception:                                # noqa: BLE001
            pass
        import win32gui
        return win32gui.GetWindowRect(self.hwnd)

    def _covered(self, l: int, t: int, r: int, b: int) -> bool:
        import win32con
        import win32gui
        import win32process
        if win32gui.IsIconic(self.hwnd):
            return True
        pad = 12
        pts = [((l + r) // 2, (t + b) // 2), (l + pad, t + pad), (r - pad, t + pad), (l + pad, b - pad), (r - pad, b - pad)]
        for x, y in pts:
            h = win32gui.WindowFromPoint((x, y))
            if not h:
                return True
            root = win32gui.GetAncestor(h, win32con.GA_ROOT)
            if root == self.hwnd:
                continue
            try:
                if self._pid and win32process.GetWindowThreadProcessId(root)[1] == self._pid:
                    continue                                # a SolidWorks dialog/popup is still SolidWorks
            except Exception:                            # noqa: BLE001
                pass
            return True
        return False

    def latest(self):
        import numpy as np
        import win32con
        import win32gui
        import win32ui
        l, t, r, b = self._rect()
        w, h = r - l, b - t
        if w < 32 or h < 32:
            return None, True
        covered = self._covered(l, t, r, b)
        if covered:
            return None, True
        hdesk = win32gui.GetDesktopWindow()
        wdc = win32gui.GetWindowDC(hdesk)
        src = win32ui.CreateDCFromHandle(wdc)
        mem = src.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        try:
            bmp.CreateCompatibleBitmap(src, w, h)
            mem.SelectObject(bmp)
            mem.BitBlt((0, 0), (w, h), src, (l, t), win32con.SRCCOPY)
            arr = np.frombuffer(bmp.GetBitmapBits(True), np.uint8).reshape(h, w, 4)[..., :3].copy()
        finally:
            try:
                win32gui.DeleteObject(bmp.GetHandle())
            except Exception:                            # noqa: BLE001
                pass
            mem.DeleteDC()
            src.DeleteDC()
            win32gui.ReleaseDC(hdesk, wdc)
        return arr, False


# ----------------------------------------------------------------------------------------------- encoders

class _FfmpegEncoder:
    ext = ".mp4"
    name = "h264"

    def __init__(self, path: Path, size: tuple[int, int], fps: int):
        import imageio_ffmpeg
        self.path = path
        self._w = imageio_ffmpeg.write_frames(str(path), size, pix_fmt_in="bgr24", pix_fmt_out="yuv420p", fps=fps, quality=6,
                                              codec="libx264", macro_block_size=2,
                                              output_params=["-movflags", "+faststart", "-preset", "veryfast"])
        self._w.send(None)

    def write(self, frame) -> None:
        self._w.send(frame.tobytes())

    def close(self) -> None:
        self._w.close()


class _CvWebmEncoder:
    ext = ".webm"
    name = "vp8"

    def __init__(self, path: Path, size: tuple[int, int], fps: int):
        import cv2
        self.path = path
        self._v = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"VP80"), fps, size)
        if not self._v.isOpened():
            raise RuntimeError("OpenCV cannot write VP8 WebM on this machine")

    def write(self, frame) -> None:
        self._v.write(frame)

    def close(self) -> None:
        self._v.release()


def make_encoder(out: Path, size: tuple[int, int], fps: int):
    """H.264 MP4 via imageio-ffmpeg, else VP8 WebM via OpenCV. Returns an encoder or raises RuntimeError."""
    errs = []
    for cls in (_FfmpegEncoder, _CvWebmEncoder):
        path = Path(out) / f"{VIDEO_STEM}.partial{cls.ext}"
        try:
            return cls(path, size, fps)
        except Exception as e:                           # noqa: BLE001
            errs.append(f"{cls.name}: {e}")
    raise RuntimeError("; ".join(errs))


# ----------------------------------------------------------------------------------------------- recorder

def _ascii(s: str) -> str:
    return "".join(c if 32 <= ord(c) < 127 else " | " if c == "·" else "?" for c in str(s))[:90]


def _fit_size(w: int, h: int) -> tuple[int, int]:
    s = min(1.0, MAX_W / w, MAX_H / h)
    ow, oh = max(2, int(w * s)), max(2, int(h * s))
    return ow - ow % 2, oh - oh % 2


class SolidWorksRecorder:
    """Context manager around the SolidWorks build. ``stop()`` always writes the manifest and never raises."""

    def __init__(self, out: Path, *, part: str, run_id: str, source_sha256: str = "", sw_app=None, fps: int = DEFAULT_FPS,
                 max_seconds: float = MAX_SECONDS, max_bytes: int = MAX_BYTES, paced: bool = True, hold_s: float = HOLD_S,
                 total_features: int = 0, window_finder: Optional[Callable] = None,
                 source_factory: Optional[Callable] = None, encoder_factory: Optional[Callable] = None,
                 backend: str = "auto"):
        self.out, self.part, self.run_id, self.sha = Path(out), part, run_id, source_sha256
        self.sw_app, self.fps, self.max_seconds, self.max_bytes = sw_app, fps, max_seconds, max_bytes
        self.paced, self.hold_s, self.total = paced, hold_s, total_features
        self._finder = window_finder or find_solidworks_window
        self._source_factory, self._encoder_factory, self._backend_pref = source_factory, encoder_factory, backend
        self._lock = threading.Lock()
        self._caption, self.chapters = "SolidWorks build", []
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._source: Optional[FrameSource] = None
        self._enc = None
        self._t0 = 0.0
        self._frames = self._dropped = 0
        self._last_good = None
        self._poster_frame = None
        self._size: Optional[tuple[int, int]] = None
        self._black_since: Optional[float] = None
        self._code, self._reason = "", ""
        self._started = False
        self._done = False
        self._hwnd: Optional[int] = None
        self._count = 0
        self._iso_done = False

    # ---- lifecycle
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, et, ev, tb):
        self.stop(outcome="failed" if et else "completed", error=f"{et.__name__}: {ev}" if et else "")
        return False

    def start(self) -> bool:
        try:
            cap = capability() if self._source_factory is None else {"available": True}
            if not cap["available"]:
                return self._fail("REC_UNAVAILABLE", cap.get("reason", ""))
            self.out.mkdir(parents=True, exist_ok=True)
            clear_stale(self.out)
            hwnd = None
            if self._source_factory is None:
                hwnd = self._finder(self.sw_app)
                if not hwnd:
                    return self._fail("REC_NO_WINDOW")
                _restore_if_minimised(hwnd)
            self._hwnd = hwnd
            self._source = self._open_source(hwnd)
            if self._source is None:
                return self._fail(self._code or "REC_NO_WINDOW", self._reason)
            self._t0 = time.time()
            self._started = True
            self._manifest("recording")
            self._thread = threading.Thread(target=self._loop, name="sw-recorder", daemon=True)
            self._thread.start()
            log.info("[stage] recording_start: recording the SolidWorks window (%s) for %s", self._source.name, self.part)
            return True
        except Exception as e:                           # noqa: BLE001 - recording must never fail the build
            return self._fail("REC_WRITE_FAILED", f"{type(e).__name__}: {e}")

    def _open_source(self, hwnd) -> Optional[FrameSource]:
        if self._source_factory is not None:
            s = self._source_factory(hwnd)
            s.start()
            return s
        order = ["wgc", "gdi"] if self._backend_pref == "auto" else [self._backend_pref]
        for b in order:
            try:
                s = WgcSource(hwnd) if b == "wgc" else GdiSource(hwnd)
                s.start()
                deadline = time.time() + 3.0              # a backend that gives no first frame is not usable
                while time.time() < deadline:
                    if b == "gdi" or s.latest()[0] is not None:
                        return s
                    time.sleep(0.1)
                s.stop()
                log.warning("recording backend %s produced no frame; trying the next one", b)
            except Exception as e:                       # noqa: BLE001
                log.warning("recording backend %s unavailable: %s", b, e)
        self._code, self._reason = "REC_NO_FRAMES", "No capture backend produced a frame."
        return None

    def _fail(self, code: str, reason: str = "") -> bool:
        self._code, self._reason = code, reason or CODES.get(code, code)
        self._started = False
        try:
            self._done = True
            write_manifest(self.out, {"status": "failed", "run_id": self.run_id, "part": self.part, "source_sha256": self.sha,
                                      "code": self._code, "reason": self._reason[:300], "frames": 0, "dropped_frames": 0,
                                      "duration_s": 0, "bytes": 0, "chapters": []})
        except Exception:                                # noqa: BLE001
            pass
        log.warning("[stage] recording_failed: %s %s", self._code, self._reason)
        return False

    # ---- build hooks
    def caption(self, text: str) -> None:
        with self._lock:
            self._caption = _ascii(text)

    def after_feature(self, fid: str, kind: str, status: str) -> None:
        """Called after each feature: caption + chapter, then (paced) a redraw and a short hold so the viewport shows it."""
        if not self._started:
            return
        try:
            self._count += 1
            label = f"{fid} {kind}: {status}"
            with self._lock:
                self._caption = _ascii(f"{label} | step {self._count}")
                self.chapters.append({"id": str(fid), "label": str(label)[:80], "status": str(status),
                                      "t": round(max(0.0, time.time() - self._t0), 2)})
            if self.paced and self._started:
                self._redraw()
                time.sleep(self.hold_s)
        except Exception:                                # noqa: BLE001
            pass

    def _redraw(self) -> None:
        try:
            doc = self.sw_app.ActiveDoc if self.sw_app is not None else None
            if doc is None:
                return
            if not self._iso_done:
                doc.ShowNamedView2("*Isometric", 7)
                self._iso_done = True
            doc.ViewZoomtofit2()
            doc.GraphicsRedraw2()
        except Exception:                                # noqa: BLE001
            pass

    # ---- capture loop
    def _compose(self, frame):
        import cv2
        import numpy as np
        h, w = frame.shape[:2]
        if self._size is None:
            self._size = _fit_size(w, h)
        ow, oh = self._size
        s = min(ow / w, oh / h)
        nw, nh = max(2, int(w * s)), max(2, int(h * s))
        img = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        canvas = np.full((oh, ow, 3), 24, np.uint8)
        x0, y0 = (ow - nw) // 2, (oh - nh) // 2
        canvas[y0:y0 + nh, x0:x0 + nw] = img
        return canvas

    def _overlay(self, canvas, t: float):
        import cv2
        oh, ow = canvas.shape[:2]
        bar = 30
        roi = canvas[oh - bar:oh, 0:ow]
        roi[:] = (roi * 0.35).astype(roi.dtype)
        with self._lock:
            cap = self._caption
        mm, ss = divmod(int(t), 60)
        cv2.putText(canvas, cap, (10, oh - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 1, cv2.LINE_AA)
        stamp = f"{mm:02d}:{ss:02d}"
        (tw, _), _ = cv2.getTextSize(stamp, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.putText(canvas, stamp, (ow - tw - 10, oh - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (107, 175, 214), 1, cv2.LINE_AA)
        return canvas

    def _loop(self) -> None:
        period = 1.0 / self.fps
        written = 0
        last_size_check = 0.0
        try:
            while not self._stop_evt.is_set():
                now = time.time()
                t = now - self._t0
                if t > self.max_seconds:
                    self._code, self._reason = "REC_LIMIT_REACHED", f"stopped after {int(self.max_seconds)} s"
                    break
                frame, covered = self._source.latest()
                if covered:
                    self._dropped += 1
                    if self._code == "":
                        self._code, self._reason = "REC_COVERED", CODES["REC_COVERED"]
                if frame is not None and not covered:
                    self._last_good = self._compose(frame)
                    self._poster_frame = self._last_good
                    if float(frame.mean()) < 2.0:                          # black window?
                        self._black_since = self._black_since or now
                    else:
                        self._black_since = None
                if self._last_good is not None:
                    target = int(t * self.fps) + 1                         # catch up: repeat the held frame for any gap
                    while written < target:
                        if self._enc is None:
                            h, w = self._last_good.shape[:2]
                            self._enc = (self._encoder_factory or make_encoder)(self.out, (w, h), self.fps)
                        self._enc.write(self._overlay(self._last_good.copy(), written / self.fps))
                        written += 1
                    self._frames = written
                if now - last_size_check > 3.0:
                    last_size_check = now
                    p = getattr(self._enc, "path", None)
                    if p and Path(p).exists() and Path(p).stat().st_size > self.max_bytes:
                        self._code, self._reason = "REC_LIMIT_REACHED", "stopped at the file size limit"
                        break
                self._stop_evt.wait(period)
        except Exception as e:                           # noqa: BLE001
            self._code, self._reason = "REC_WRITE_FAILED", f"{type(e).__name__}: {e}"

    # ---- finish
    def stop(self, *, outcome: str = "completed", error: str = "") -> dict:
        """Finish the video and write the manifest. ``outcome``: completed | failed | cancelled (the BUILD's outcome)."""
        if self._done:
            return self.read_manifest()
        self._done = True
        try:
            if not self._started:
                return self.read_manifest()
            time.sleep(min(1.0, self.hold_s))                 # a short tail so the final feature is on screen
            self._stop_evt.set()
            if self._thread:
                self._thread.join(timeout=10)
            try:
                if self._source:
                    self._source.stop()
            except Exception:                            # noqa: BLE001
                pass
            return self._finalize(outcome, error)
        except Exception as e:                           # noqa: BLE001
            self._code, self._reason = "REC_WRITE_FAILED", f"{type(e).__name__}: {e}"
            try:
                self._manifest("failed")
            except Exception:                            # noqa: BLE001
                pass
            return self.read_manifest()

    def _finalize(self, outcome: str, error: str) -> dict:
        video = ""
        size = 0
        if self._enc is not None:
            try:
                self._enc.close()
            except Exception as e:                       # noqa: BLE001
                self._code, self._reason = "REC_WRITE_FAILED", f"{type(e).__name__}: {e}"
            part_path = Path(self._enc.path)
            if part_path.exists() and part_path.stat().st_size > 0 and self._code != "REC_WRITE_FAILED":
                final = self.out / f"{VIDEO_STEM}{self._enc.ext}"
                os.replace(part_path, final)
                video, size = final.name, final.stat().st_size
            else:
                try:
                    part_path.unlink()
                except OSError:
                    pass
        if self._poster_frame is not None:
            try:
                import cv2
                cv2.imwrite(str(self.out / POSTER), self._overlay(self._poster_frame.copy(), self._frames / self.fps),
                            [cv2.IMWRITE_JPEG_QUALITY, 85])
            except Exception:                            # noqa: BLE001
                pass
        if not video:
            if self._black_since:
                self._code, self._reason = "REC_CAPTURE_BLACK", CODES["REC_CAPTURE_BLACK"]
            elif self._code in ("", "REC_COVERED"):
                self._code, self._reason = "REC_NO_FRAMES", CODES["REC_NO_FRAMES"]
            status = "failed"
        elif self._black_since and time.time() - self._black_since >= BLACK_AFTER_S:
            self._code, self._reason, status = "REC_CAPTURE_BLACK", CODES["REC_CAPTURE_BLACK"], "partial"
        elif self._code in ("REC_COVERED", "REC_LIMIT_REACHED") or self._dropped:
            status = "partial"
        else:
            status = "ready"
        self._manifest(status, video=video, size=size, outcome=outcome, error=error)
        log.info("[stage] recording_%s: %s (%d frames, %d dropped)", status, video or self._code, self._frames, self._dropped)
        return self.read_manifest()

    def _manifest(self, status: str, *, video: str = "", size: int = 0, outcome: str = "", error: str = "") -> None:
        w, h = self._size or (0, 0)
        write_manifest(self.out, {
            "status": status, "run_id": self.run_id, "part": self.part, "source_sha256": self.sha,
            "video": video, "poster": POSTER if (self.out / POSTER).exists() else "",
            "backend": self._source.name if self._source else "", "fps": self.fps, "width": w, "height": h,
            "frames": self._frames, "dropped_frames": self._dropped,
            "duration_s": round(self._frames / self.fps, 2) if self.fps else 0, "bytes": size,
            "paced": self.paced, "build_outcome": outcome, "build_error": error[:300],
            "chapters": list(self.chapters), "code": self._code, "reason": (self._reason or "")[:300]})

    def read_manifest(self) -> dict:
        try:
            return json.loads((self.out / MANIFEST).read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            return {}
