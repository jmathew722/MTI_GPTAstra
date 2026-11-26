"""Record the SolidWorks window while the pipeline builds the part ("Record Pipeline Run").

Design: docs/superpowers/specs/2026-11-19-solidworks-recording-design.md

* Only the SolidWorks window is captured, only for the SolidWorks build (``SolidWorksRecorder`` wraps ``compile_solidworks``).
* The recorder NEVER raises into the build. Every failure becomes a manifest ``status`` + ``code`` (the UI shows it).
* Backend: Windows Graphics Capture of ONE validated top-level SolidWorks window (records that window even when other applications cover it).
  There is NO desktop, monitor, screen-rectangle or foreground-window fallback: if Windows Graphics Capture cannot deliver frames of the SolidWorks
  window, the recording FAILS with an explicit code (the part build is unaffected).
* Win32 / OpenCV / encoder imports are lazy, so this module imports on any OS and the tests run without SolidWorks.
"""
from __future__ import annotations

import collections
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

DEFAULT_FPS = int(os.environ.get("GPTASTRA_RECORD_FPS", "30"))   # 30 fps; set GPTASTRA_RECORD_FPS=10 for smaller files
MAX_SECONDS = 20 * 60
MAX_BYTES = 500 * 1024 * 1024
MAX_W, MAX_H = 1600, 1000
HOLD_S = 0.6                       # paced build: let the viewport show each feature
FINAL_HOLD_S = 1.5                 # the finished model stays on screen this long before the recording stops (env GPTASTRA_RECORD_HOLD_S)
FIRST_FRAME_S = 10.0               # how long to wait for the first real frame, nudging a repaint through the COM API (no input simulation)
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
    "REC_NO_WGC": "Windows Graphics Capture could not capture the SolidWorks window (no desktop fallback is used).",
    "REC_WINDOW_IDENTITY": "The window is not the main window of the SolidWorks session that is building the part.",
    "REC_WINDOW_LOST": "The SolidWorks window was closed or replaced during the recording; the recording stopped (no other window is captured).",
    "REC_MINIMIZED": "SolidWorks was minimized during the recording; frames are missing for that time.",
    "REC_UNVERIFIED": "The finished video could not be read back.",
}


def wanted() -> bool:
    return os.environ.get(ENV_FLAG, "").strip() in ("1", "true", "yes")


# ----------------------------------------------------------------------------------------------- capability

def capability() -> dict:
    """What this machine can do, without needing SolidWorks to be running. Shape: {available, backend, encoder, reason}.
    The only backend is Windows Graphics Capture of a single window; there is deliberately no desktop-capture fallback."""
    import importlib.util as u
    if sys.platform != "win32":
        return {"available": False, "backend": None, "encoder": None, "reason": CODES["REC_UNAVAILABLE"]}
    have = lambda m: u.find_spec(m) is not None    # noqa: E731
    if not (have("numpy") and have("cv2")):
        return {"available": False, "backend": None, "encoder": None, "reason": "Recording needs numpy and opencv-python."}
    encoder = "imageio-ffmpeg" if have("imageio_ffmpeg") else "opencv-webm"
    if have("win32gui") and have("win32ui") and have("win32process"):
        return {"available": True, "backend": "printwindow", "encoder": encoder, "reason": ""}
    if not (have("windows_capture") and have("win32gui") and have("win32process")):
        return {"available": False, "backend": None, "encoder": encoder,
                "reason": "Window-only recording needs Windows Graphics Capture: pip install windows-capture pywin32 (no desktop fallback is used)."}
    return {"available": True, "backend": "wgc", "encoder": encoder, "reason": ""}


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
    """Restore a minimized window WITHOUT activating it (no focus theft)."""
    try:
        import win32con
        import win32gui
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
            time.sleep(0.8)
    except Exception:                                   # noqa: BLE001
        pass


def _exe_name(pid: int) -> str:
    """Base name of the executable of a process ('' when it cannot be read)."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)             # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = wintypes.DWORD(1024)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                return os.path.basename(buf.value)
        finally:
            k32.CloseHandle(h)
    except Exception:                                   # noqa: BLE001
        pass
    return ""


def validate_window(hwnd: int, sw_app=None) -> dict:
    """Prove that ``hwnd`` is the main modeling window of the SolidWorks session that is building the part. Window titles are never used to choose
    the window; the title is only reported (first word) as evidence. Returns {ok, reason, hwnd, pid, exe, class, title_prefix, checks}."""
    out: dict = {"ok": False, "reason": "", "hwnd": int(hwnd or 0), "pid": None, "exe": "", "class": "", "title_prefix": "", "checks": {}}
    try:
        import win32con
        import win32gui
        import win32process
    except Exception as e:                              # noqa: BLE001
        out["reason"] = f"window APIs unavailable: {e}"
        return out
    if not hwnd or not win32gui.IsWindow(hwnd):
        out["reason"] = "not a window"
        return out
    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
    exp = None
    if sw_app is not None:
        for getter in (lambda: int(sw_app.GetProcessID()), lambda: int(sw_app.GetProcessID)):
            try:
                exp = getter()
                break
            except Exception:                           # noqa: BLE001
                continue
    cls = win32gui.GetClassName(hwnd)
    exe = _exe_name(pid)
    title = win32gui.GetWindowText(hwnd) or ""
    checks = {"visible": bool(win32gui.IsWindowVisible(hwnd)), "top_level": not win32gui.GetParent(hwnd),
              "unowned": not win32gui.GetWindow(hwnd, win32con.GW_OWNER), "solidworks_exe": exe.lower() == "sldworks.exe",
              "same_session": (exp is None) or pid == exp, "main_window_class": cls.startswith("Afx:")}
    out.update(pid=pid, exe=exe, **{"class": cls}, title_prefix=(title.split(" ")[0] if title else "")[:20], checks=checks)
    failed = [k for k, v in checks.items() if not v]
    out["ok"] = not failed
    out["reason"] = "" if not failed else "failed checks: " + ", ".join(failed)
    return out


def is_occluded(hwnd: int) -> bool:
    """True when ANY other application's visible window sits above ``hwnd`` in the z-order and overlaps it.

    Why this exists: Windows Graphics Capture of a window is correct for the window's own surface, but SolidWorks' OpenGL model viewport is composed from the
    screen, so a window dragged over it shows up INSIDE the capture (verified live: a Notepad/VS Code window appeared in the viewport region of the video).
    The recorder therefore never encodes a frame that was captured while another application overlapped the window. Fails CLOSED: an error means occluded."""
    try:
        import ctypes
        from ctypes import wintypes
        import win32con
        import win32gui
        import win32process
        if not win32gui.IsWindow(hwnd):
            return True
        own_pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        dwm = ctypes.windll.dwmapi

        def rect(h):
            r = wintypes.RECT()
            if dwm.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:       # DWMWA_EXTENDED_FRAME_BOUNDS
                return r.left, r.top, r.right, r.bottom
            return win32gui.GetWindowRect(h)
        l, t, rr, b = rect(hwnd)
        h = win32gui.GetWindow(hwnd, win32con.GW_HWNDPREV)
        guard = 0
        while h and guard < 2000:
            guard += 1
            nxt = win32gui.GetWindow(h, win32con.GW_HWNDPREV)
            try:
                if win32gui.IsWindowVisible(h) and not win32gui.IsIconic(h):
                    cloaked = ctypes.c_int(0)
                    dwm.DwmGetWindowAttribute(h, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))      # DWMWA_CLOAKED
                    ex = win32gui.GetWindowLong(h, win32con.GWL_EXSTYLE)
                    click_through = bool(ex & win32con.WS_EX_TRANSPARENT) and bool(ex & win32con.WS_EX_LAYERED)
                    if not cloaked.value and not click_through and win32process.GetWindowThreadProcessId(h)[1] != own_pid:
                        a, c, d, e = rect(h)
                        if min(rr, d) - max(l, a) > 0 and min(b, e) - max(t, c) > 0:
                            return True
            except Exception:                           # noqa: BLE001
                return True
            h = nxt
        return False
    except Exception:                                   # noqa: BLE001
        return True


def window_state(hwnd: int, expected_pid: Optional[int]) -> str:
    """'ok' | 'minimized' | 'lost' (closed, or the handle now belongs to another process)."""
    try:
        import win32gui
        import win32process
        if not win32gui.IsWindow(hwnd):
            return "lost"
        if expected_pid and win32process.GetWindowThreadProcessId(hwnd)[1] != expected_pid:
            return "lost"
        return "minimized" if win32gui.IsIconic(hwnd) else "ok"
    except Exception:                                   # noqa: BLE001
        return "lost"


# ----------------------------------------------------------------------------------------------- frame sources

class FrameSource:
    """latest() -> (BGR ndarray | None, covered). start()/stop(). ``name`` is the backend label."""
    name = "source"

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def latest(self) -> tuple[Any, bool]:
        return None, False

    def history(self) -> list:
        """[(arrival time, frame)] newest last; the base class has no history."""
        return []


class WgcSource(FrameSource):
    """Windows Graphics Capture of one window. Delivers a frame only when the window changes; the recorder resamples."""
    name = "wgc"

    def __init__(self, hwnd: int):
        self.hwnd, self._lock, self._frame, self._ctl = hwnd, threading.Lock(), None, None
        self.count = 0                                   # frames actually delivered by Windows Graphics Capture
        self.closed = False
        self._hist: collections.deque = collections.deque(maxlen=8)      # (arrival time, frame): lets the privacy gate judge a frame after the fact

    def start(self) -> None:
        from windows_capture import WindowsCapture
        # cursor_capture False: the mouse pointer (possibly over another app) is never drawn; draw_border False: no yellow capture border
        cap = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=self.hwnd)

        @cap.event
        def on_frame_arrived(frame, _ctl):               # noqa: ANN001
            try:
                buf = frame.frame_buffer
                bgr = buf[..., :3].copy()
                with self._lock:
                    self._frame = bgr
                    self.count += 1
                    self._hist.append((time.time(), bgr))
            except Exception:                            # noqa: BLE001
                pass

        @cap.event
        def on_closed():                                 # noqa: ANN202
            self.closed = True

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

    def history(self) -> list:
        with self._lock:
            return list(self._hist)


class PrintWindowSource(FrameSource):
    """Window-only capture with ``PrintWindow(hwnd, PW_RENDERFULLCONTENT)``: Windows asks the SolidWorks window to paint ITSELF (model viewport included)
    into a private bitmap. Unlike a screen copy it never contains another application, and, verified live, it is unaffected by other windows covering
    SolidWorks (Windows Graphics Capture of SolidWorks' OpenGL viewport shows the covering window inside the viewport, so it is only the fallback)."""
    name = "printwindow"

    def __init__(self, hwnd: int, hz: float = 30.0):
        self.hwnd, self.hz = hwnd, hz
        self._lock, self._frame, self._stop = threading.Lock(), None, threading.Event()
        self.count = 0
        self.closed = False
        self._thread: Optional[threading.Thread] = None
        self._last_small = None

    def _grab(self):
        import ctypes
        import numpy as np
        import win32gui
        import win32ui
        l, t_, r, b = win32gui.GetWindowRect(self.hwnd)
        w, h = r - l, b - t_
        if w < 64 or h < 64 or win32gui.IsIconic(self.hwnd):
            return None
        hdc = win32gui.GetWindowDC(self.hwnd)
        mdc = win32ui.CreateDCFromHandle(hdc)
        mem = mdc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        try:
            bmp.CreateCompatibleBitmap(mdc, w, h)
            mem.SelectObject(bmp)
            if not ctypes.windll.user32.PrintWindow(self.hwnd, mem.GetSafeHdc(), 2):       # 2 = PW_RENDERFULLCONTENT
                return None
            raw = bmp.GetBitmapBits(True)
            return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)[..., :3].copy()
        finally:
            try:
                win32gui.DeleteObject(bmp.GetHandle())
                mem.DeleteDC()
                mdc.DeleteDC()
                win32gui.ReleaseDC(self.hwnd, hdc)
            except Exception:                            # noqa: BLE001
                pass

    def _run(self) -> None:
        import numpy as np
        while not self._stop.is_set():
            try:
                import win32gui
                if not win32gui.IsWindow(self.hwnd):
                    self.closed = True
                    break
                f = self._grab()
                if f is not None:
                    small = f[::16, ::16]
                    changed = self._last_small is None or small.shape != self._last_small.shape or not np.array_equal(small, self._last_small)
                    with self._lock:
                        self._frame = f
                        if changed:
                            self.count += 1               # a frame that differs from the previous one (a repeated picture is a 'held' frame)
                    self._last_small = small
            except Exception:                            # noqa: BLE001
                pass
            self._stop.wait(1.0 / self.hz)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="sw-printwindow", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def latest(self):
        with self._lock:
            return self._frame, False


# (There is intentionally no GDI / screen-rectangle / desktop frame source: capturing a rectangle of the screen shows whatever application is on top.)


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
        self._identity: dict = {}
        self._pid: Optional[int] = None
        self._started_at = self._ended_at = ""
        self._occ_times: collections.deque = collections.deque(maxlen=4000)   # times at which another application overlapped the window
        self._occ_stop = threading.Event()
        self._occluded_ticks = 0
        self._occ_fn: Optional[Callable[[int], bool]] = None
        self._held = 0                       # encoded frames that repeated the previous capture (WGC sends a frame only when the window repaints)
        self._minimized = 0
        self._resizes = 0
        self._last_shape: Optional[tuple] = None
        self._final_held = False
        self._verify: dict = {}
        self._session: dict = {}

    # ---- lifecycle
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, et, ev, tb):
        self.stop(outcome="failed" if et else "completed", error=f"{et.__name__}: {ev}" if et else "")
        return False

    def start(self) -> bool:
        """Start recording once the target SolidWorks window and the initial part document are ready. Never raises. Refuses (with an explicit code)
        when the window cannot be proven to be the SolidWorks session's main window; never captures anything else."""
        try:
            cap = capability() if self._source_factory is None else {"available": True}
            if not cap["available"]:
                return self._fail("REC_NO_WGC" if "Graphics Capture" in str(cap.get("reason", "")) else "REC_UNAVAILABLE", cap.get("reason", ""))
            self.out.mkdir(parents=True, exist_ok=True)
            clear_stale(self.out)
            hwnd = None
            if self._source_factory is None:
                hwnd = self._finder(self.sw_app)
                if not hwnd:
                    return self._fail("REC_NO_WINDOW")
                ident = validate_window(hwnd, self.sw_app)
                self._identity = ident
                if not ident["ok"]:
                    return self._fail("REC_WINDOW_IDENTITY", f"{ident['reason']} (pid {ident.get('pid')}, exe {ident.get('exe')})")
                self._pid = ident["pid"]
                _restore_if_minimised(hwnd)
            self._hwnd = hwnd
            self._session = self._session_snapshot()
            self._source = self._open_source(hwnd)
            if self._source is None:
                return self._fail(self._code or "REC_NO_WGC", self._reason)
            self._t0 = time.time()
            self._started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            self._started = True
            self._manifest("recording")
            if self._occ_fn is None and isinstance(self._source, WgcSource):
                self._occ_fn = is_occluded                                    # the privacy gate guards every real Windows Graphics Capture recording
            if self._occ_fn is not None:
                threading.Thread(target=self._occ_loop, name="sw-recorder-occlusion", daemon=True).start()
            self._thread = threading.Thread(target=self._loop, name="sw-recorder", daemon=True)
            self._thread.start()
            log.info("[stage] recording_start: recording ONE window (%s, pid %s) for %s", self._source.name, self._pid, self.part)
            return True
        except Exception as e:                           # noqa: BLE001 - recording must never fail the build
            return self._fail("REC_WRITE_FAILED", f"{type(e).__name__}: {e}")

    def _session_snapshot(self) -> dict:
        """Evidence of ONE continuous session: SolidWorks pid and the active document when recording began (compared again at the end)."""
        snap: dict = {"sw_pid": self._pid, "doc_at_start": "", "docs_open": None}
        try:
            if self.sw_app is not None:
                d = self.sw_app.ActiveDoc
                snap["doc_at_start"] = str(d.GetTitle()) if d is not None else ""
        except Exception:                                # noqa: BLE001
            pass
        return snap

    def _nudge(self) -> None:
        """Ask SolidWorks for a repaint through the API (no keystrokes, no focus change) so Windows Graphics Capture has a frame to deliver."""
        try:
            doc = self.sw_app.ActiveDoc if self.sw_app is not None else None
            if doc is not None:
                doc.GraphicsRedraw2()
        except Exception:                                # noqa: BLE001
            pass

    def _open_source(self, hwnd) -> Optional[FrameSource]:
        if self._source_factory is not None:
            s = self._source_factory(hwnd)
            s.start()
            return s
        pref = (os.environ.get("GPTASTRA_RECORD_BACKEND") or self._backend_pref or "auto").lower()
        if pref in ("auto", "printwindow"):
            try:
                s = PrintWindowSource(hwnd)
                s.start()
                t_end = time.time() + 4.0
                while time.time() < t_end:
                    f = s.latest()[0]
                    if f is not None and 2.0 < float(f.mean()) < 253.0 and float(f.std()) > 3.0:
                        return s                                  # a real, non-blank picture of the window
                    time.sleep(0.1)
                s.stop()
                log.warning("PrintWindow did not return a usable picture; trying Windows Graphics Capture (with the overlap privacy gate)")
            except Exception as e:                       # noqa: BLE001
                log.warning("PrintWindow capture unavailable: %s", e)
        try:
            s = WgcSource(hwnd)
            s.start()
            deadline = time.time() + FIRST_FRAME_S
            nudged = 0.0
            while time.time() < deadline:
                if s.latest()[0] is not None:
                    return s
                if time.time() - nudged > 1.0:
                    nudged = time.time()
                    self._nudge()
                time.sleep(0.1)
            s.stop()
            self._code, self._reason = "REC_NO_FRAMES", f"Windows Graphics Capture delivered no frame in {int(FIRST_FRAME_S)} s (no desktop fallback is used)."
        except Exception as e:                           # noqa: BLE001
            self._code, self._reason = "REC_NO_WGC", f"{type(e).__name__}: {e}"
            log.warning("Windows Graphics Capture unavailable: %s", e)
        return None

    def _fail(self, code: str, reason: str = "") -> bool:
        self._code, self._reason = code, reason or CODES.get(code, code)
        self._started = False
        try:
            self._done = True
            write_manifest(self.out, {"status": "failed", "run_id": self.run_id, "part": self.part, "source_sha256": self.sha,
                                      "capture_method": "wgc-window", "target": self._target(),
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

    def finish_build(self, hold_s: Optional[float] = None) -> dict:
        """The part is built, rebuilt and saved: show the final isometric model, hold it, then stop the recording. Called BEFORE any document is closed,
        exported or re-opened, so the video ends on the finished model."""
        if self._done or not self._started:
            return self.read_manifest()
        try:
            h = hold_s if hold_s is not None else float(os.environ.get("GPTASTRA_RECORD_HOLD_S", FINAL_HOLD_S))
        except ValueError:
            h = FINAL_HOLD_S
        try:
            self.caption("Final model")
            self._iso_done = False
            self._redraw()
            self.chapters.append({"id": "final", "label": "Final model", "status": "built", "t": round(max(0.0, time.time() - self._t0), 2)})
            time.sleep(max(0.0, h))
            self._final_held = True
        except Exception:                                # noqa: BLE001
            pass
        return self.stop(outcome="completed")

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

    OCC_DELAY_S = 0.15        # a frame is judged this long after it arrived, so an overlap that began just after it is still caught
    OCC_MARGIN_S = 0.20       # ... and a frame is rejected when an overlap was seen this long before it arrived

    def _occ_loop(self) -> None:
        while not self._occ_stop.is_set() and self._hwnd:
            try:
                if self._occ_fn(self._hwnd):
                    self._occ_times.append(time.time())
            except Exception:                                # noqa: BLE001
                self._occ_times.append(time.time())          # fail closed
            self._occ_stop.wait(0.02)

    def _clean_frame(self, now: float):
        """The newest frame that arrived at least OCC_DELAY_S ago and was never overlapped by another application; None when there is none."""
        hist = self._source.history()
        occ = list(self._occ_times)
        for ts, fr in reversed(hist):
            if ts > now - self.OCC_DELAY_S:
                continue
            if not any(ts - self.OCC_MARGIN_S <= o <= ts + self.OCC_DELAY_S for o in occ):
                return fr
            return None                                          # the newest judged frame was overlapped: keep the last clean one
        return None

    def _loop(self) -> None:
        period = 1.0 / self.fps
        written = 0
        last_size_check = last_win_check = 0.0
        last_restore = 0.0
        prev_count = -1
        try:
            while not self._stop_evt.is_set():
                now = time.time()
                t = now - self._t0
                if t > self.max_seconds:
                    self._code, self._reason = "REC_LIMIT_REACHED", f"stopped after {int(self.max_seconds)} s"
                    break
                if self._hwnd and now - last_win_check > 0.5:       # the target must stay the SAME SolidWorks window; never retarget another one
                    last_win_check = now
                    st = window_state(self._hwnd, self._pid)
                    if st == "lost" or getattr(self._source, "closed", False):
                        self._code, self._reason = "REC_WINDOW_LOST", CODES["REC_WINDOW_LOST"]
                        break
                    if st == "minimized":
                        self._dropped += 1
                        if self._code == "":
                            self._code, self._reason = "REC_MINIMIZED", CODES["REC_MINIMIZED"]
                        if now - last_restore > 2.0:
                            last_restore = now
                            self._minimized += 1
                            try:
                                import win32con
                                import win32gui
                                win32gui.ShowWindowAsync(self._hwnd, win32con.SW_SHOWNOACTIVATE)      # restore WITHOUT taking focus
                            except Exception:                        # noqa: BLE001
                                pass
                if self._occ_fn is not None:
                    frame, covered = self._clean_frame(now), False
                    if frame is None and any(o >= now - 0.5 for o in list(self._occ_times)[-5:]):
                        self._occluded_ticks += 1
                else:
                    frame, covered = self._source.latest()
                if covered:
                    self._dropped += 1
                    if self._code == "":
                        self._code, self._reason = "REC_COVERED", CODES["REC_COVERED"]
                if frame is not None and not covered:
                    if self._last_shape is not None and tuple(frame.shape) != self._last_shape:
                        self._resizes += 1                           # window resized: the new frames are letterboxed into the fixed output size
                    self._last_shape = tuple(frame.shape)
                    self._last_good = self._compose(frame)
                    self._poster_frame = self._last_good
                    if float(frame.mean()) < 2.0:                          # black window?
                        self._black_since = self._black_since or now
                    else:
                        self._black_since = None
                if self._last_good is not None:
                    target = int(t * self.fps) + 1                         # constant frame rate: a frame without a new capture repeats the previous one
                    cnt = getattr(self._source, "count", None)
                    while written < target:
                        if self._enc is None:
                            h, w = self._last_good.shape[:2]
                            self._enc = (self._encoder_factory or make_encoder)(self.out, (w, h), self.fps)
                        self._enc.write(self._overlay(self._last_good.copy(), written / self.fps))
                        if cnt is not None and cnt == prev_count:
                            self._held += 1
                        prev_count = cnt if cnt is not None else prev_count
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
            if not self._final_held:
                time.sleep(min(1.0, self.hold_s))             # a short tail so the final feature is on screen
            self._ended_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            self._stop_evt.set()
            self._occ_stop.set()
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
                self._verify = self._probe(part_path)                  # read the finished file back BEFORE it is published
                if self._verify.get("ok"):
                    final = self.out / f"{VIDEO_STEM}{self._enc.ext}"
                    os.replace(part_path, final)                       # atomic publish
                    video, size = final.name, final.stat().st_size
                else:
                    self._code, self._reason = "REC_UNVERIFIED", f"{CODES['REC_UNVERIFIED']} {self._verify.get('reason', '')}"
                    try:
                        os.replace(part_path, self.out / f"{VIDEO_STEM}.unverified{self._enc.ext}")    # kept as diagnostic evidence, never shown as the recording
                    except OSError:
                        pass
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

    def _probe(self, path: Path) -> dict:
        """Independent read-back with OpenCV: frame count, fps, duration, first and last frame readable, duration close to what was written."""
        try:
            import cv2
            cap = cv2.VideoCapture(str(path))
            n, fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0), float(cap.get(cv2.CAP_PROP_FPS) or 0)
            ok1, _ = cap.read()
            if n > 1:
                cap.set(cv2.CAP_PROP_POS_FRAMES, n - 1)
            ok2, _ = cap.read()
            cap.release()
            dur = (n / fps) if fps else 0.0
            expect = self._frames / self.fps if self.fps else 0.0
            good = bool(ok1 and ok2 and n > 0 and abs(dur - expect) <= max(1.0, 0.15 * expect))
            return {"ok": good, "frames": n, "fps": round(fps, 2), "duration_s": round(dur, 2), "first_frame": bool(ok1), "last_frame": bool(ok2),
                    "reason": "" if good else f"frames={n} duration={dur:.2f}s expected={expect:.2f}s"}
        except Exception as e:                           # noqa: BLE001
            return {"ok": False, "reason": f"{type(e).__name__}: {e}"}

    def _target(self) -> dict:
        i = self._identity or {}
        return {"pid": i.get("pid"), "hwnd": i.get("hwnd"), "exe": i.get("exe"), "window_class": i.get("class"), "title_prefix": i.get("title_prefix"),
                "identity_ok": i.get("ok"), "identity_checks": i.get("checks")}

    def _manifest(self, status: str, *, video: str = "", size: int = 0, outcome: str = "", error: str = "") -> None:
        w, h = self._size or (0, 0)
        captured = getattr(self._source, "count", None)
        session = dict(self._session)
        try:
            if self.sw_app is not None:
                d = self.sw_app.ActiveDoc
                session["doc_at_end"] = str(d.GetTitle()) if d is not None else ""
                session["same_document"] = bool(session.get("doc_at_start")) and session.get("doc_at_start") == session["doc_at_end"]
                session["same_session"] = (self._pid is None) or window_state(self._hwnd, self._pid) != "lost"
        except Exception:                                # noqa: BLE001
            pass
        write_manifest(self.out, {
            "status": status, "run_id": self.run_id, "part": self.part, "source_sha256": self.sha,
            "video": video, "poster": POSTER if (self.out / POSTER).exists() else "",
            "backend": self._source.name if self._source else "", "capture_method": (("printwindow-window (PrintWindow PW_RENDERFULLCONTENT of one validated window; unaffected by covering windows; no desktop capture)" if (self._source and self._source.name == "printwindow") else "wgc-window (Windows Graphics Capture, one validated window, overlap privacy gate; no desktop capture)")),
            "target": self._target(), "session": session, "started_at": self._started_at, "ended_at": self._ended_at,
            "captured_frames": captured, "held_frames": self._held, "occluded_seconds": round(self._occluded_ticks / max(self.fps, 1), 1),
            "privacy_gate": "overlap-by-other-windows frames are never encoded" if self._occ_fn is not None else "off", "minimized_events": self._minimized, "resize_events": self._resizes,
            "verified": bool(self._verify.get("ok")), "probe": self._verify, "fps": self.fps, "width": w, "height": h,
            "frames": self._frames, "dropped_frames": self._dropped,
            "duration_s": round(self._frames / self.fps, 2) if self.fps else 0, "bytes": size,
            "paced": self.paced, "build_outcome": outcome, "build_error": error[:300],
            "chapters": list(self.chapters), "code": self._code, "reason": (self._reason or "")[:300]})

    def read_manifest(self) -> dict:
        try:
            return json.loads((self.out / MANIFEST).read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            return {}
