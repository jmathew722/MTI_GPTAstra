# Solid Flow — Recording Camera Cadence Upgrade

## Objective and precedence
Update the existing SOLIDWORKS 2025 build recorder in place. This specification supersedes earlier instructions to force isometric after every feature, sketch, or click. Preserve all other recording and pipeline requirements. Default to full-part zoom-out while retaining the current working-face orientation; restore isometric only after every two successfully completed geometry features and at final completion.

## 1. Camera behavior
- At recording initialization, use a full-part isometric view if geometry exists; otherwise wait for geometry to exist.
- Before and after each meaningful automation action (face selection, sketch entry/exit, feature edit, creation, or completed modeling click), request a framing check. At the earliest safe boundary, fit and zoom out to show the entire current part while preserving the current camera orientation, including the normal-to-face orientation when working on a face. Do not force isometric on ordinary clicks or after odd-numbered features.
- Use a configurable target of 12–18% clear margin on each viewport edge where practical (default 15%); measure against the actual graphics viewport, not the whole application window. Fit the union of visible intended solid bodies, not merely selected entities. During the initial sketch/no-solid stage, fit the relevant sketch geometry if available. Avoid excessive whitespace for small parts.
- Keep the selected face or active feature visible in context. Do not clear selections, exit sketches, change model state, or lose selection marks merely to reframe. If native fit would disrupt an active command or screen-coordinate selection, defer until the earliest safe boundary and log the reason. Recompute projected bounds after geometry grows, is cut, or changes orientation.
- Use absolute fit/scale calculations rather than repeatedly multiplying the existing zoom level. Only move the camera when needed; avoid jitter, repeated zoom animations, flicker, or artificial pauses. Coalesce redundant requests while preserving checks at each meaningful action. Prefer native API selection by geometry over screen-coordinate clicks; invalidate/recompute screen coordinates after camera changes.

## 2. Isometric cadence and feature counting
Maintain a per-part integer `completed_feature_count`, initialized to zero. Increment exactly once for each distinct successful committed geometry-changing feature operation, after rebuild and verification. Examples: extrusion, cut, revolve, hole, fillet, chamfer, pattern, or a committed feature modification. Do not increment for face selections, sketch-only actions, camera changes, save/rebuild alone, failed attempts, retries of the same logical operation, or UI clicks. Use stable operation IDs for deduplication. Reset between parts and restore the counter from a checkpoint on resume if applicable.

After every successful feature, first frame the whole part in the current orientation. If the count is even (2, 4, 6, ...), then restore standard isometric orientation, fit the whole part again, apply the configured margin, redraw, and allow a short configurable settling period if needed for capture. Otherwise retain the working orientation. The next modeling action may establish its required orientation. If an even-feature checkpoint coincides with the final presentation, coalesce the two isometric transitions into one. Always finish a successful build with a full-part isometric view, even if the feature count is odd, held for at least three seconds.

| Event | Default action |
|---|---|
| Face selection / modeling click | Check framing; zoom out as needed; retain orientation |
| Sketch editing | Retain required sketch orientation; fit at safe boundaries |
| Feature 1 completed | Full-part zoom-out; no forced isometric |
| Feature 2 completed | Full-part zoom-out, then isometric and fit |
| Feature 3 completed | Full-part zoom-out; no forced isometric |
| Feature 4 completed | Full-part zoom-out, then isometric and fit |
| Final feature / build completion | Final full-part isometric view; hold 3 seconds |

## 3. Implementation
1. Inspect the existing recorder, macro/COM execution loop, camera helper, feature lifecycle and previous recording specifications. Find and replace conflicting unconditional isometric hooks; do not introduce parallel competing camera controllers.
2. Implement a centralized camera policy with `on_action_boundary`, `on_feature_committed`, and `on_build_completed` or equivalent. Use a per-run state machine and serialized access to the existing SOLIDWORKS COM thread. Ensure the active document/view belongs to the current part before changing it.
3. Validate native API methods and signatures against the installed SOLIDWORKS 2025 type library and official API help before using them. Candidate methods include `IModelDoc2.ShowNamedView2`, `IModelDoc2.ViewZoomtofit2`, and `IModelDoc2.GraphicsRedraw2`; use a verified model-view scale/translation or equivalent for extra framing. Do not guess enumeration values, scale units, or COM return contracts. For non-isometric fits preserve orientation and verify it has not changed.
4. Prefer deterministic geometry bounds and projection into the actual viewport; validate with captured frames. If bounds/framing cannot be reliably computed for a given state, use verified native fit and report the limitation. Log camera failures and retry only at safe boundaries; never silently claim full visibility.
5. Preserve window-specific capture targeting the correct SolidWorks HWND; never fall back to desktop or foreground capture. Keep SolidWorks and the active part open throughout construction, hide the FeatureManager panel for recording, and restore original UI state after completion, failure, or cancellation. Do not send global keystrokes to Chrome or other applications.
6. Keep recording real and continuous; do not hide failed framing by deleting frames or fabricating a video. Preserve current geometry, material assignment, STL export, and both pipeline workflows.

## 4. Tests and acceptance
- Unit test event sequences with 0, 1, 2, 3, 4, 5 and 6 committed features. Assert periodic isometric transitions only at 2, 4, 6; initial and final views are explicit exceptions. Verify duplicate/retried/failed/sketch events do not increment counts. Test odd final feature and final/even checkpoint coalescing.
- Test safe deferral during active sketches and selections; verify camera orientation is preserved for normal zoom-out operations, and selection state remains usable.
- Test batch runs with counters reset, resumed jobs, cancellation, camera API failure and recorder failure. Check no cumulative zoom drift.
- Run actual SOLIDWORKS 2025 builds for authorized compact, long/thin, wide, off-center and (where supported) multibody fixtures with at least five features. Include features on different faces and geometry that expands beyond the prior bounds.
- Inspect real MP4 frames around each meaningful action and feature checkpoint; verify entire current part is visible, framing margin is reasonable, no unnecessary isometric flips occur, and final isometric holds for at least 3 seconds. Document any unavoidable transient during active operations; do not mark it as passed if it violates the intended visibility requirement.
- Deliberately switch to Chrome during a test recording; verify no unrelated application pixels appear. Verify native geometry and outputs match expected results; run regression tests for existing workflows.
- Save MP4s, annotated screenshots or frame timestamps, and camera event logs (operation ID, event, feature count, requested/actual orientation, bounds/margin where available, deferred reason, outcome). Record exact commands, fixture names, test results, changed files and known limitations.

## 5. Completion directive
Implement in the existing repository, run tests, debug failures and repeat until acceptance criteria are met where the environment permits. Do not stop at a plan or mock. Clearly distinguish static/unit tests from actual SolidWorks integration and visual recording acceptance. If native execution is blocked, document the exact blocker, complete independent work, and give reproducible local validation commands. Provide updated application launch instructions. No unrelated UI redesign is required.
