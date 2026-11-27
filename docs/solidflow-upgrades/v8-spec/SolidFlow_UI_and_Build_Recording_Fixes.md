# Solid Flow — Pipeline Results Layout and SolidWorks Build Recording Fixes

## Master directive

Continue from the current Solid Flow repository state. Implement both fixes below in the same session. Inspect the existing frontend, backend, recording implementation, and SolidWorks 2025 automation before changing code. Reuse existing architecture and design tokens; do not introduce a parallel UI or recording pipeline unnecessarily. Preserve both CAD conversion workflows, material handling, scoring, existing outputs, and user changes. Do not stop at a plan: implement, run, debug, and verify. Treat the symptoms below as observed behavior, not a confirmed diagnosis.

## 1. Fix Pipeline Results expanded height and layout

### Observed defect

The Pipeline Results panel collapses correctly, but when expanded it remains a shallow strip with a very small scrollable content area while substantial unused workspace remains below it. The screenshot shows its header, a partially visible navigation list and Engineering Flags content, then a large empty dark area. The panel does not use the available vertical space.

### Required behavior

- Preserve the currently working collapse behavior: the header remains accessible and the content is hidden without leaving a large blank reserved area.
- On expand, restore a useful, responsive panel height that fills the available workspace below the drawing/STL viewers. If the parent workspace is taller than the viewport, manage the layout so the panel can be reached and expanded without artificial dead space.
- Keep the header and results navigation visible; let the navigation and results content scroll independently only when their contents exceed the available space.
- Keep the existing resize handle, if present, functional. Clamp drag resizing to the actual available space and a usable minimum height; preserve the last valid expanded height where appropriate, recalculating on viewport changes. Do not restore a stale collapsed height on expand.
- Preserve the existing Fit, Maximize, Results, Open full page, and collapse/expand controls. Fit should size to available space; Maximize should make the results area the primary workspace view and restore the prior layout when exited. Verify existing semantics before changing them.
- Avoid clipping, overlapping colored severity borders, double scrollbars, horizontal overflow, and inaccessible tabs. Keep the existing Solid Flow visual styling.
- Apply the fix wherever the same shared Pipeline Results component is used, including both directions of conversion if applicable.

### Implementation guidance

1. Reproduce the issue in the live application and inspect computed heights, flex/grid tracks, parent constraints, scroll containers, collapse state, resize state, and any persisted layout values. Trace the component from the workspace root down to its content.
2. Fix the controlling layout rather than adding arbitrary fixed pixel heights or blank spacers. Where compatible with the existing stack, use a bounded workspace flex/grid layout with `min-height: 0` on shrinkable descendants, a non-shrinking header, and an expanded body that consumes the remaining space (`flex: 1 1 auto` or equivalent). Use `min-width: 0` on content columns and `overflow: auto` only on intended scrolling regions. A grid layout may use `minmax(0, 1fr)` for flexible tracks. Ensure the root has an actual available height; do not assume `height: 100%` works without a bounded parent.
3. Model collapsed, expanded, and maximized states explicitly. Keep the expanded height separate from the collapsed header height. Recompute available space on resize or layout change (e.g., with ResizeObserver if appropriate), and clean up listeners. Avoid competing inline heights, CSS max-height rules, or persisted split-pane values that defeat expansion.
4. Preserve keyboard access, focus, accessible expanded state, and existing scroll position where useful; reveal content without scrolling it unexpectedly. On smaller screens, allow a purposeful workspace scroll or stacked layout rather than compressing results into an unusable strip.

### Acceptance tests

- Expand from the screenshot-like state: the panel uses available space below the viewers, with no large unnecessary blank area.
- Collapse and re-expand repeatedly; each expansion restores a usable height and collapse remains correct.
- Test Fit, Maximize, restore, Open full page, drag-resize (if present), tab switching, and navigation with long Engineering Flags content.
- Test empty, short, and long results; run in progress and completed runs; reload with persisted state; switch projects and pipeline directions.
- Test at 1920×1080, 1440×900, 1280×720 and common browser zoom levels, with sidebar expanded/collapsed. Check actual computed bounding boxes and overflow, not screenshots alone.
- Capture before/after screenshots and add regression tests for the state and layout behavior using the existing test framework.

## 2. Record only the SolidWorks window throughout the part build

### Observed defect

The build recording sometimes shows Chrome or other windows when foreground focus changes. The desired recording is a clean, uninterrupted view of the actual SolidWorks part being built, with SolidWorks kept open throughout the build rather than repeatedly launched and closed.

### Required behavior

- Record the specific native SolidWorks 2025 application window associated with the active build, never the full desktop, primary monitor, active foreground window, or a desktop rectangle cropped to the SolidWorks bounds.
- Switching focus to Chrome, VS Code, File Explorer, the Solid Flow browser, or another unrelated application must not introduce any frames of those applications into the video.
- Keep one persistent SolidWorks application session for the entire part build (and reuse across batch parts where safe). Open/create the part once per build attempt, keep it open while features are created and rebuilt, then save and verify it. Do not repeatedly launch/quit SolidWorks or close/reopen the active part between feature operations. If post-save reopen verification is required, perform it after the recording has finished or in a separate controlled verification step.
- The recording must start once the target SolidWorks window and initial part document are ready, before the first geometry-building operation; capture the actual feature creation sequence, rebuilds, and final model view. Hold the final model briefly (configurable, e.g. 1–2 seconds) and stop recording before closing documents, opening another part, or switching to post-build cleanup.
- Keep the CAD application visible and non-minimized during recording where required by the capture backend. Do not repeatedly steal keyboard focus or force unrelated windows closed. If minimized, unavailable, or capture is lost, report a recording gap/failure and recover safely where possible; never fall back to capturing the desktop.
- Suppress avoidable native modal dialogs through documented silent API operations and controlled preferences; retain actionable diagnostics for real errors. Never dismiss arbitrary dialogs or hide important failures. Capture only intended SolidWorks content; do not broaden the capture target to the desktop to include a dialog.
- Produce one correctly associated video per part/run, not a mixture of multiple projects. No unrelated windows, desktop wallpaper, taskbar, notifications from other apps, or accidental screen exposure.

### Recommended Windows capture architecture

Inspect the existing implementation first. Prefer Windows Graphics Capture (WGC) targeting the exact SolidWorks top-level HWND, using `IGraphicsCaptureItemInterop::CreateForWindow` (where supported) and a compatible native capture/encoding helper. Resolve HWND from the owned/attached SolidWorks session using verified API/window enumeration and process identity; do not hardcode window titles or select the current foreground window. Validate the HWND belongs to the expected SolidWorks process and is the intended main modeling window. Track the window identity and detect closure or replacement. Do not silently retarget another window.

A WGC implementation is a recommended design, not a confirmed capability of the current machine. Validate Windows version, graphics support, encoder availability, and actual SolidWorks 2025 capture behavior, including DirectX viewport rendering and occlusion. Use existing dependencies if they meet the same isolation and quality contract. A window-specific fallback is acceptable only after proving it cannot capture unrelated applications and captures real CAD frames; legacy GDI/PrintWindow capture may yield black or stale GPU-rendered content and must not be assumed reliable. FFmpeg may encode frames, but desktop capture (`gdigrab desktop`, monitor capture, screen crops) is prohibited. Never enable a full-screen fallback. Do not circumvent OS capture restrictions.

Use an explicit recording lifecycle, adapted to the existing worker architecture:

```text
Resolve or start persistent SolidWorks session
  -> Open/create the active part
  -> Resolve and validate SolidWorks HWND
  -> Initialize window-only capture and encoder
  -> Confirm first valid CAD frame
  -> Start recording before feature generation
  -> Execute build operations in same SolidWorks session/document
  -> Rebuild and save native part; show final isometric view
  -> Record final hold
  -> Stop and finalize video
  -> Verify recording artifact
  -> Export/verify other outputs and clean up owned documents
```

- Coordinate capture with the existing SolidWorks COM worker; keep COM calls on the appropriate STA thread and keep frame collection/encoding asynchronous so recording does not block geometry operations or create COM threading violations.
- Prefer API-based modeling and camera control over simulated keystrokes or foreground-dependent automation. Preserve application/session ownership; never close a user's unrelated documents or terminate their existing SolidWorks process. Restore any changed application-wide preferences on exit.
- Keep frame dimensions consistent; handle target window resizing with frame-pool recreation and letterboxing or other deterministic normalization. Preserve aspect ratio. Use a practical configurable frame rate (e.g. 30 fps), H.264 MP4 if supported, and no microphone/system audio by default. Use monotonic timestamps and bounded queues; log dropped frames. Do not invent frames or mask a failed capture with a fake success.
- Finalize the encoder on success, cancellation and recoverable errors. Write to a temporary filename, verify the result is readable/nonempty and has plausible duration, then atomically publish the completed MP4. Mark partial/failed recordings explicitly and retain diagnostic evidence. A recording failure must be separately reported from CAD build failure; do not mislabel a successful part build as a successful recording.
- Store recording metadata with the existing run manifest: run ID, part ID, capture method, target process/window identity, start/end times, frame count, dropped frames, resolution, duration, output path, status and error details. Avoid sensitive full desktop imagery in logs or diagnostics.
- Integrate the completed MP4 with the existing Pipeline Results recording tab/player. Ensure cache invalidation and per-run artifact selection so stale recordings are never displayed for a new build. No audio capture unless explicitly enabled in a future feature.

### Acceptance tests

1. Run an authorized multi-feature part build in SolidWorks 2025 and record from before first feature creation through final rebuilt model. Verify a single SolidWorks session and continuous active part document in the automation logs.
2. During the build, deliberately switch to Chrome, VS Code and File Explorer, including moving an unrelated window over the SolidWorks window. Review the resulting video and sampled frames around every focus change. The recording must contain only SolidWorks content; no desktop/browser flashes are acceptable.
3. Test window resize, focus loss, minimization/restoration, target closure, and capture backend initialization failure. Verify the defined recovery or explicit failure behavior without desktop fallback. Check GPU viewport is not black/frozen during normal feature generation.
4. Test a second consecutive part and batch generation, cancellation, SolidWorks build errors, and encoder errors. Verify no orphan encoder processes, recording handles, mixed-part videos, or unintended SolidWorks shutdown.
5. Verify MP4 playback in the application's actual recording viewer and through an independent media probe/player. Compare recording duration against build timestamps and inspect first, intermediate, focus-switch, and final frames.
6. Record evidence: capture backend, PID/HWND/session continuity, video path, duration, frame statistics, observed isolation results, and any unresolved limitations. Automated checks alone do not prove visual isolation; inspect real footage.

## 3. Final integration and completion

- Work through both fixes in order; preserve unrelated work and existing Git changes. Use the project's normal checkpoint process without pushing or overwriting unrelated files.
- Run frontend layout tests, backend/recording tests, and relevant existing CAD regression tests. Launch the real updated UI and inspect the results.
- Save before/after UI screenshots, an actual SolidWorks-only demonstration MP4, and a concise implementation/verification report in the existing project output structure. Document modified files, root causes, implementation choices, tests actually run, and known limitations.
- If the current environment lacks a licensed SolidWorks 2025 session, Windows window-capture capability, or test fixtures, complete all independent work and state exactly which live tests remain blocked. Do not claim native automation or video isolation has been verified without evidence.
- Provide exact commands to launch the updated application. Do not stop at planning, placeholder capture, or CSS changes that have not been exercised.
