# Recording camera and isolation (v6): implementation and verification

Code: `pipeline/solidworks_camera.py` (new), `pipeline/solidworks_recorder.py` (integration). Evidence: `docs/solidflow-upgrades/recording-evidence-v6/`.
Tests: `tests/test_solidworks_camera.py` (12), `tests/test_solidworks_recorder.py` (22); full Python suite 1466 passed, 67 skipped.

## What it does (SolidWorks 2025 SP5, native calls only, no keystrokes, no focus change)
| Step | Call | Verified how |
|---|---|---|
| One session, one document | existing hooks (`on_ready` / `on_built`); no close/reopen until after the video ends | manifest `session` (pid, doc at start/end) |
| Maximize the owned window | `ShowWindowAsync(SW_MAXIMIZE)` (no activation) on the validated SolidWorks HWND | `camera_log.json` `window_after` (1536x816 maximized) |
| Hide the FeatureManager design tree | `ISldWorks.RunCommand(swCommands_Hideshow_Brwser_Tree = 2556)` (id read from the installed `swcommands.tlb`) | the tree container window is measured on screen before/after (`tree_visible_before: true`, `tree_visible_after: false`); toggled back only if we hid it |
| Standard isometric | `IModelDoc2.ShowNamedView2("*Isometric", swIsometricView = 7)` | native `IModelView.Orientation3` compared with the isometric matrix (error < 0.01) at EVERY frame |
| Zoom to fit | `ViewZoomtofit2`, `GraphicsRedraw2` | rendered picture, see below |
| Margin and centring | `IModelView.ZoomByFactor` + `IModelView.Translation3` (closed loop) | geometry bounding box measured in a window-only picture: margins per edge, none touching the edge |
| Settled frame | two identical consecutive window pictures before the frame is accepted | `settled_frame` per entry |
| Final presentation | isometric + fit after the final save, held 3.2 s, then the recording stops BEFORE STL export / close | chapter `final`, measured hold 3.18-3.23 s |
| Restore | tree toggled back, exact window rectangle restored with `SetWindowPos` (finally: completion, failure, cancel) | `restore` entry: `tree_restored`, `window_restored: true`, rect identical |

Finding: SolidWorks' own `ViewZoomtofit2` is computed for the whole view frame and, in this setup, left the model off-centre and cut off at the bottom/right edge (see `BEFORE_tree_visible_model_clipped.png`). A requested camera command is therefore never taken as proof: the loop measures the rendered picture, zooms to a ~10 % margin per edge and pans to the centre of the usable viewport (typically 4 adjustments per feature).
During those adjustments the video holds the previous picture and then jumps to the settled one, so the video never shows the intermediate zoom steps. Each chapter has `t` (commit) and `t_settled`.

## Live results (real builds, no API cost)
- A001151E (5 features): 6/6 frames isometric-verified and fit-verified, maximized, tree hidden, restored. `A001151E_maximized_tree_hidden.mp4`, contact sheet included.
- A001171E (10 features, stepped counterbores): 8/8 verified, 109 s video, with Chrome (red page "LEAK MARKER CHROME"), VS Code and Explorer maximized TOPMOST over SolidWorks in turn (`A001171E_window_switch_log.json`). All 1633 frames scanned: 0 contain the red marker or large dark regions; frame size constant (1536x822). Backend `printwindow` (window-specific; windows covering SolidWorks do not appear).
- Cancel/failure: a simulated cancel after the 2nd feature produced a verified (245 frames) recording with `build_outcome: failed`, design tree restored, SolidWorks still running.
- Geometry unaffected: the per-feature volume checks (SolidWorks volume vs reference) passed in every run; camera calls touch only the view.

## Bugs found and fixed during this work (all from live runs)
1. `win32gui.IsZoomed` / `ShowWindowAsync` do not exist in pywin32: the maximize step and the recorder's no-activation restore silently did nothing. Replaced with window placement and user32 `ShowWindowAsync`.
2. The first margin measure overflowed (int16) and reported constant margins; fixed (int32) and made robust to stray pixels.
3. `EnableFeatureTree` only hides the tree contents (the pane stays); the real "Hide/Show Tree Area" command is used instead.
4. `SetWindowPlacement` restored a different rectangle than the one found; now the exact rectangle is restored.

## Not verified / limitations
- Run-time cost: the camera loop makes a recorded 5-feature build take about 50 s (was about 26 s).
- Failure injection was done by interrupting the build (cancel path); SolidWorks minimized/closed mid-recording, an encoder failure and a batch of several parts were not exercised live in v6 (unit-tested with fake sources / earlier v5 runs only).
- Fixtures: only parts with a drawing in `DrawingPDFs` could be built: block with holes, plate with counterbores. A long slender part, a wide flange and a multi-body part were not available, so framing of those shapes is unverified (the loop is shape-independent: it measures the picture).
- Pan gains were calibrated on this machine and screen; the loop corrects residual error, but another display size has not been tried.
- If a selected feature shows the feature breadcrumb in the top-left of the viewport, that area is excluded from the measurement.
- Playback in the Pipeline Results recording tab was not re-opened in a browser after these changes (manifest/file names are unchanged; new manifest field `camera` and file `camera_log.json` added).

## UI end-to-end (final check)
One recorded run started through the UI API (`/api/run-part`, record=true) finished with the recording reported ready by `/api/parts/.../recording` (backend printwindow, 15 fps, 1536x816, has_video, has_poster; video endpoint 200). The SolidWorks window and design tree were restored afterwards. Browser playback in the Results recording tab was not driven.

---
# Cadence update (SolidFlow_Recording_Zoom_and_Isometric_Cadence.md) - supersedes "isometric after every feature"

## Implemented (`pipeline/solidworks_camera.py`, hooks in `pipeline/ir/compile_solidworks.py`, `pipeline/ir_pipeline.py`, `pipeline/solidworks_recorder.py`)
- One camera policy per run/part: `on_action_boundary`, `on_feature_committed`, `on_build_completed`; the old unconditional isometric hooks are gone (without the camera controller the recorder only uses SolidWorks' own fit and a final isometric).
- Default = whole-part zoom-out with the working orientation kept (verified with native `IModelView.Orientation3` before/after); margin target 15 % (band 12-18 %, `GPTASTRA_CAMERA_MARGIN`), measured in the model viewport (swMdiClient), not the window; nothing moves when the picture is already in the band (no jitter).
- Per-part `completed_feature_count`: +1 only for a distinct, successfully built feature (stable operation id; failed/mismatch/duplicate/retry/sketch/camera events never count). Isometric + fit only after features 2, 4, 6...; final build always ends isometric (coalesced into the checkpoint when it already happened), held >= 3.17 s in every run (measured on the video clock).
- Safe boundaries wired into the compile: before each feature, after each sketch is fully defined (before the extrusion), after each committed feature. Selections in the compile are model-space (`SelectByID2`, `SelectByRay`), so a view change cannot invalidate them; no sketch is exited and no selection is cleared for framing. Camera/zoom state is never multiplied blindly: each fit starts from the absolute `ViewZoomtofit2`, then a measured closed loop (zoom + `Translation3` pan, mapping calibrated per orientation, reverted when it makes the picture worse).
- Log per event: operation id, event, feature count, requested vs actual orientation, margins before/after, outcome, reason (`camera_log.json`); manifest `camera` summary.

## Tests
- Unit (no SolidWorks): `tests/test_solidworks_camera.py` 29 tests: isometric cadence for 0-6 features, ordinary boundaries never force isometric, failed/mismatch/duplicate ids do not count, counter reset per part, odd final feature, even-feature/final coalescing, no-move when in band, zoom-in/out, camera API failure and not-isometric flagged, log fields. Recorder tests 22.
- Live, real SolidWorks 2025 SP5 (no API cost), evidence in `recording-evidence-v6-cadence/`: A001611E (6 features, prism with an off-centre end), A001651E (5 features: revolved flange + holes; wide thin part), A040161E (5 features incl. edge operations), A001821E (7 features, long build) with Chrome (red LEAK page), VS Code and Explorer maximized over SolidWorks during the build.
  - Isometric checkpoints at feature 2, 4, 6 only (A001611E: 2,4,6; A001651E and A040161E: 2,4; A001821E: 2,4,6), orientation preserved on every ordinary boundary, final isometric hold 3.17-3.20 s, 0 frames with the leak marker or an application window (all frames scanned).
  - Cancel (simulated after the 2nd feature): verified recording, `build_outcome: failed`, tree and window restored. Batch (two consecutive builds in one process): `completed_features` 4 and 4, no drift.

## NOT met / honest limitations
- **The whole part is NOT visible during every operation.** Framing is enforced at the boundaries above. Between them SolidWorks changes the view itself (sketch entry rotates and zooms to the sketch, extrusion previews, Hole Wizard), and those states are recorded as they happen. A strict picture scan (`clip_scan.txt`) counts 39-61 % of the video time with geometry touching the viewport edge (it also counts sketch dimension annotations placed outside the part, so it overstates solid clipping; the frames are real and visibly show zoomed-in sketch/extrude states for several seconds, e.g. A001611E at 6 s, 20 s, 45 s).
- Camera events inside a sketch (`sketch_defined`) are flagged failed in several runs (geometry or annotations touch the edge, or thin sketch lines are not detected): `camera.ok` is `false` in A001611E, A001651E and A001821E for that reason; every `feature_committed`, `isometric_checkpoint` and `build_completed` event in those logs passed. A040161E is fully `ok`.
- A hook at sketch entry (face selection) was tried and removed: it tripled the recording time and was unstable. A cached "last successful correction" was tried and removed (oscillated).
- Recorded builds are slow: about 60-190 s for 5-7 features (an unrecorded build takes about 26 s). Camera boundaries are the cost.
- One run (A001651E, first attempt) was cut by the 20-minute recording limit because the PC was asleep for hours; it was repeated and passed.
- Bounds are measured from the rendered picture (colour/edge detection), not projected from B-rep bounds; a part with the same colour as the background would not be detected. Multi-body parts and a long thin shaft were not available as fixtures (A001651E is the thin/wide part, A001611E the off-centre one).
- Camera API failure was tested only with fake documents (unit tests), not by breaking SolidWorks live; SolidWorks minimized/closed mid-recording, encoder failure and resume-from-checkpoint were not exercised live.
