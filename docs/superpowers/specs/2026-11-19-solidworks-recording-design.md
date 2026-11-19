# SolidWorks build recording ("Record Pipeline Run") - design (2026-11-19)

Status: approved by the user 2026-11-19 (all six recommended decisions). Branch `Improvements_2`.

## Goal
A checkbox under "Force fresh extraction" records the SolidWorks window - only that window, only during the SolidWorks build - to an MP4 that
plays in the part's Pipeline Results.

## Flow
`#record-run` -> `api.runPart({record:true})` -> `POST /api/run-part` (`record` form field) -> `_pipeline_cmd(record=True)` adds
`--record-solidworks` -> `main.py` sets `GPTASTRA_RECORD_SOLIDWORKS=1` -> `ir_pipeline.run_part` wraps `compile_solidworks` in a
`SolidWorksRecorder` -> `<Part>/solidworks_recording.mp4|.webm`, `.json` manifest, `_poster.jpg` -> server category `recording` -> Results
section "SolidWorks recording" (Build & Verification, after Model Check).

## Recorder (`pipeline/solidworks_recorder.py`)
* Window: found by the SolidWorks process id (`sw_app.GetProcessID()`), title fallback. Restored if minimised.
* Backends: **Windows Graphics Capture** (`windows-capture`) is primary: it records one window even when covered, including the OpenGL
  viewport (verified live on SolidWorks 2025 SP5, 2026-11-19). Fallback: copy the window rectangle from the screen with a **privacy gate**:
  a frame is dropped (last good frame held) when another process's window covers the SolidWorks window at 5 sample points.
* Frames are resampled to a fixed fps (WGC only delivers on change), fixed even output size, letterboxed, caption burned in
  ("F005 hole: built | step 3"). Streaming H.264 via `imageio-ffmpeg` (`+faststart`); fallback WebM via OpenCV. Limits: 20 min, 500 MB.
* Never raises into the build. Every failure becomes a manifest `status` + code.
* Manifest `solidworks_recording.json` (schema_version 1): `status` `recording | ready | partial | failed | skipped`, `run_id`, `part`,
  `source_sha256`, `video`, `poster`, `backend`, `fps`, `width`, `height`, `frames`, `dropped_frames`, `duration_s`, `bytes`, `chapters`
  `[{id,label,status,t}]`, `code`, `reason`, `generation_key`.
* Codes: `REC_UNAVAILABLE`, `REC_NO_WINDOW`, `REC_ENCODER_MISSING`, `REC_CAPTURE_BLACK`, `REC_NO_FRAMES`, `REC_COVERED`,
  `REC_LIMIT_REACHED`, `REC_WRITE_FAILED`, `REC_NOT_REACHED`.
* Paced build (only while recording): after each feature, zoom-to-fit + redraw + 0.6 s hold so the viewport shows the result.
* Stale: cleared at the start of every run; the server flags a recording `stale` when its drawing hash differs from the current drawing.

## Server
`record` form field on `/api/run-part`; `_pipeline_cmd(record=)`; `GET /api/recording/capability`; `GET /api/parts/{s}/{p}/recording`
(manifest, ETag); `.../recording.video` (MP4 or WebM by the manifest; Range support; `?download=true`); `.../recording-poster.jpg`. Allowlisted names, no client-built paths.

## UI
Checkbox "Record pipeline run" in Run options (disabled with a reason when unavailable; sent only when ticked; not remembered). Results
section with states: not recorded, recording, ready (player, 1x/2x/4x, chapters that seek, download), partial, failed, skipped, stale.

## Git
`*.mp4`, `*.webm` under `FINAL_OUTPUTs/` are gitignored (local demo artifacts).

## Out of scope (v1)
Live streaming while the build runs; audio; recording phases other than the SolidWorks build.

## Findings while building (2026-11-19)
* Windows Graphics Capture delivers a frame only when the window changes, so the recorder resamples to a fixed fps (repeats the last frame).
* Playwright's bundled Chromium has no H.264 decoder: the browser tests use WebM fixtures; real Chrome/Edge/Firefox play the MP4.
* The UI runs in `FINAL_UI/.venv`, a separate environment from the system Python: `opencv-python`, `imageio-ffmpeg` and `windows-capture` must be
  installed there (the launcher installs the repo's `requirements.txt`, which now lists them).
* Only the manifest, poster and video are produced by the recorder; all three are gitignored together (`**/solidworks_recording*`).
