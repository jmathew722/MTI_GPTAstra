# SolidWorks build recording ("Record Pipeline Run"): test report (2026-11-19)

Branch `Improvements_2`. Design: `docs/superpowers/specs/2026-11-19-solidworks-recording-design.md`. Evidence: `docs/test-reports/recording-evidence/`.

## What was built
Checkbox "Record Pipeline Run" under "Force fresh extraction" -> `record=true` on `/api/run-part` -> `main.py --record-solidworks` -> the recorder wraps only
`compile_solidworks` -> `solidworks_recording.mp4/.json/_poster.jpg` in the part's output -> Pipeline Results -> Build & Verification -> "SolidWorks recording".

## Live results (SolidWorks 2025 SP5, this machine)
| Check | Result |
|---|---|
| Windows Graphics Capture records the SolidWorks window incl. the OpenGL viewport | yes (spike frame shows ribbon, tree, 3D view) |
| Replay of the saved SB10009_SHT_3 plan with recording (no API cost) | ready, 33 s, 330 frames, 0 dropped, 1.0 MB, 5 chapters |
| Real UI-path run (`POST /api/run-part record=true`, run `f0871dca3d0b`) | ready, 85.6 s, 856 frames, 0 dropped, 1.98 MB H.264, 5 chapters; build `sw_ok` true, cost $1.23 |
| Served by the UI API | 200 `video/mp4`; Range request 206 (seekable); poster 200 |
| Captured area | the SolidWorks window only (frames show no other window) |

## Automated tests
- Python: 1307 passed, 66 skipped (was 1291). New: `tests/test_solidworks_recorder.py` (16), `FINAL_UI/tests/server/test_app_recording.py` (11); server suite 68 passed.
- JS unit: `tests/unit/recordingview.test.js` (12) pass; the 3 pre-existing failures (missing `part_full.log` fixture) unchanged.
- Playwright: new `24-solidworks-recording.spec.ts` 5/5 pass (axe found and we fixed a 4.42:1 timestamp contrast). Full suite 43 passed, 13 failed, 6 skipped;
  the 13 are the same pre-existing failures as before this change.

## Limits
- Window must not be minimized (it is restored automatically once). The primary backend records it even when covered; the fallback drops covered frames.
- If the SolidWorks window is resized during the build, the video letterboxes (a black bar can appear at one side).
- Playwright's Chromium cannot decode H.264, so browser tests use WebM fixtures; Chrome, Edge and Firefox play the MP4.
- Recordings are local and gitignored. No live "watch while it builds" panel (v1 is the saved video).
- The UI venv (`FINAL_UI/.venv`) needed `imageio-ffmpeg` and `windows-capture`; installed there and listed in `requirements.txt`.
