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
