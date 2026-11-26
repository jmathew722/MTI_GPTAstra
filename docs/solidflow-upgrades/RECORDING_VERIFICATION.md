# SolidWorks build recording: window-only capture (verification report, 2026-11-26)

## What changed
- `pipeline/solidworks_recorder.py`: the desktop/screen-rectangle (GDI) frame source is **deleted**. Backends are window-specific only:
  1. `PrintWindowSource` (default): `PrintWindow(hwnd, PW_RENDERFULLCONTENT)` asks the one validated SolidWorks window to paint itself.
  2. `WgcSource` (Windows Graphics Capture, fallback only if PrintWindow returns no usable picture) with an overlap privacy gate (`is_occluded`) that never encodes a frame captured while another application overlapped the window.
  No desktop, monitor, foreground-window or screen-rect path exists. Failure produces an explicit code (`REC_NO_WGC`, `REC_NO_FRAMES`, `REC_WINDOW_IDENTITY`, `REC_WINDOW_LOST`, ...) and never affects the build result.
- Window identity: PID == `sw_app.GetProcessID`, exe `SLDWORKS.exe`, visible, top-level, unowned, `Afx:` class. Recorded in the manifest (`target`).
- Lifecycle: `compile_solidworks(on_ready, on_built)`; recording starts once the new part is open, before the first feature, and finishes (final model, 1.5 s hold) right after the save, BEFORE STL export / close / material reopen. One SolidWorks session and the same part stay open for the whole build.
- Output: H.264 MP4, written to a temp file, read back with OpenCV, then atomically published (`verified`, `probe` in the manifest). Manifest fields: run/part id, capture method, PID/HWND, times, frames, dropped, resolution, duration, status, error code.

## Defect found by the live test (and fixed)
Windows Graphics Capture of SolidWorks' OpenGL viewport is NOT occlusion-proof: with Notepad / VS Code over the SolidWorks window, the covering window's pixels appeared inside the viewport of the video (`recording-evidence/BEFORE_wgc_leak_notepad_in_viewport.png`), and Explorer produced black viewport frames. The gate fixed leaks but froze the video whenever any window overlapped, so the default backend became PrintWindow, which was verified to render the viewport correctly while VS Code and Explorer cover the window.

## Acceptance run (real SolidWorks 2025 SP5, real multi-feature build of A001151E, no API cost)
`tools/window_chaos.py` opened Chrome (throw-away profile, solid red page), VS Code, Explorer and Notepad, each with a loud "LEAK MARKER", then maximized each one TOPMOST over SolidWorks in turn (3 cycles) plus a Notepad window dragged over the viewport. Evidence in `docs/solidflow-upgrades/recording-evidence/`:
- `solidworks_only_demo.mp4`: 285 frames, 28.5 s, 822x780, H.264, `verified: true`, backend `printwindow`, PID/HWND in `manifest.json`.
- `contact_sheet_during_app_switching.png`: frames sampled at every logged switch (`window_switch_log.json`): SolidWorks only in all of them.
- Automated scan of all 285 frames: 0 frames with red (Chrome marker) or large dark (Notepad/VS Code/Explorer) regions.
- Python suite: 1454 passed, 67 skipped (22 recorder tests incl. new window-only guarantees).

## Not verified / limitations (stated honestly)
- Frame rate is 10 fps (not 30); most frames are repeats of the last picture ("held": 246 of 285 in this build, SolidWorks was mostly computing).
- Not run live: SolidWorks minimized/closed mid-recording, window resize, encoder failure, second consecutive part, batch, cancellation, build-error recording. The code paths exist (`REC_MINIMIZED`, `REC_WINDOW_LOST`, letterboxing, `REC_WRITE_FAILED`, `stop(outcome="failed"/"cancelled")`) and are unit-tested with fake sources only.
- Playback in the Pipeline Results recording tab and per-run cache invalidation were not re-checked after the backend change (manifest/file names are unchanged).
- PrintWindow does not work on a minimized window; the recorder restores it without activation.
- The WGC fallback path with the privacy gate was exercised live only in the failing intermediate runs.
- Pipeline Results drawer: see `FINAL_UI/docs/verification/v5/DRAWER_LAYOUT_REPORT.md` (commit 9aa0020).
