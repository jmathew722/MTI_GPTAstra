# FEATURE_INVENTORY.md: McAgent redesign

Audit of the existing UI in `web/` and `server/` (`index.html`, `bridge.js`, `photoapp/index.html`, `static/design-tokens.css`, `app.py`) with every control, tab, output, endpoint use and state mapped to its place in the redesign. Nothing is dropped. Where the backend lacks a capability, the row says so and points to the gap id in `ARCHITECTURE.md` section 17.

Legend for the "New location" column:

- **Home**, **Workspace**, **Projects**, **Results** (Pipeline Results page), **Recent**, **Help**, **Settings** are the hash-routed pages.
- **Inspector** is the right panel in Workspace (Part Setup, Pipeline Actions, Corrections, Export). Below 1440 px the same DOM is shown in the drawer's **Tools** mode.
- **Drawer** is the bottom Pipeline Results drawer in Workspace.
- **Focus: Crop** and **Focus: Mark** are the two modes of the full-screen focus overlay.
- "Function" names are the existing functions in `index.html` whose logic must be carried over.

## 1. Old structure at a glance

| Old surface | Old id | Contents |
|---|---|---|
| Header title block | `header`, `.titleblock` | Brand, static engine text, static deliverables text, API key pill |
| Sheet 1 Drawing Crop | `#panel-crop` | Mode bar (Crop views, Mark regions), cropper iframe `#photoapp`, markup surface `#mark-view` |
| Sheet 2 Part Setup & 3D Model | `#panel-intake` | Intake strip (add images, assign view types, name and save, must-meet specs), status line, must-meet checklist, split Full Overview View and STL viewer |
| Sheet 3 Pipeline | `#panel-pipeline` | Saved parts list, run buttons, demo, status bar with stage strip and progress, run banner, Overview Analysis panel, inline console, correction bar |
| Sheet 4 Run Outputs | `#panel-outputs` | Run selector, Clear all models, ten sub-tabs |

## 2. Header

| # | Old control or output | Old id / function | Data source | New location | Notes |
|---|---|---|---|---|---|
| H1 | Logo glyph and title "MTI 2D→3D SolidWorks Pipeline" | `.brand`, `.logo` | static | Sidebar brand block: "McAgent" and subtitle "2D→3D SolidWorks Pipeline" | |
| H2 | Subtitle sentence (crop, set up, run) | `header .sub` | static | Help page, "Workflow" section | |
| H3 | "Extraction engine: Claude Opus 4.8" | `.tb-cell` (hard-coded text) | none (hard-coded) | Workspace header, Engine chip `#hdr-engine` | Must come from the backend. Source order: `status.model` (backend delta B1), else `usage.last_run.model` of the selected part, else "Not reported". See gap G1. |
| H4 | "Deliverables: .SLDPRT · .STL · VBA" | `.tb-cell` (hard-coded text) | none (hard-coded) | Workspace header, Deliverables chip `#hdr-deliv` | Three sub-chips driven by `categories.sldprt.present`, `categories.stl.present` plus `stl_source`, `categories.macros.present` of the selected part. "None yet" before a run. |
| H5 | API status pill (live or demo) | `#key-pill`, `#key-txt` | `GET /api/status` → `live` | Workspace header, API chip `#hdr-api`; also Settings › Server | Wording is "API key set" or "No API key", never "Connected" (gap G2). "Server unreachable" when the fetch fails. |

## 3. Top-level navigation

| # | Old | Old id / function | New location | Notes |
|---|---|---|---|---|
| N1 | Sheet tabs 1 to 4 | `#tabbar`, `showTab(name)` | Sidebar nav and hash router (`#/home`, `#/workspace`, `#/projects`, `#/results`, `#/recent`, `#/help`, `#/settings`) | Sheet 1 → focus overlay; Sheet 2 and 3 → Workspace; Sheet 4 → Results page and Drawer. |
| N2 | "Model ready" tick on the Sheet 2 tab | `setModelTabFilled` | 3D panel header chip (`Generated`, `Pre-validated (CadQuery)`, `Previous run`, none) | |
| N3 | Legacy tab names redirect to Sheet 4 sub-tab | `showTab` fallback | Router: `#/results?sec=<id>`; unknown hashes go to `#/home` | |
| N4 | Sub-tab filled ticks | `setTabFilled` | Status dot on each Results nav item and each Drawer section tab | States: present, absent, loading, error. |

## 4. Sheet 1: cropper (photoapp iframe, unmodified file)

All of these stay inside `photoapp/index.html`, which is not edited. The iframe moves into **Focus: Crop**.

| # | Control or behavior | photoapp id / function | New location | Notes |
|---|---|---|---|---|
| C1 | Open Drawing (file dialog) | `#openBtn`, `#fileInput`, `loadFile` | Focus: Crop (inside iframe) | Accept list is widened at runtime by `MTIBridge.hookCadIntake`. |
| C2 | Drag and drop a file onto the canvas | `#canvasWrap` drop | Focus: Crop | |
| C3 | Draw a crop rectangle, four corner handles, move | canvas mouse handlers, `hitH`, `normSel` | Focus: Crop | |
| C4 | Clear Selection, Escape | `#clearBtn`, `clearSel` | Focus: Crop | Escape inside the iframe keeps this meaning; see ARCHITECTURE 10.4. |
| C5 | Preset name (front, back, left, right, side, top, bottom, detail, section cut) | `#presetSel`, `PRESETS` | Focus: Crop | |
| C6 | Custom name | `#customName` | Focus: Crop | |
| C7 | Queue View, Ctrl/Cmd+S | `#saveViewBtn`, `queueView` | Focus: Crop | |
| C8 | Queued views list | `#savedList`, `savedCrops` | Focus: Crop; count mirrored on the overlay's "Pull queued crops" button after each pull | |
| C9 | Feature tally (feature, count, Add, list, Clear) | `#featSel`, `#countIn`, `#addBtn`, `#featList`, `#clearTallyBtn` | Focus: Crop | Tally is only used by the cropper's own ZIP. |
| C10 | Download ZIP (toolbar and sidebar) | `#dlZipBtn`, `#dlZipSideBtn`, `downloadZip` | Focus: Crop | |
| C11 | Reset (clears image, crops, tally) | `#resetBtn`, `resetApp` | Focus: Crop | Destructive inside the cropper only; unchanged. |
| C12 | Info chip, file label, status bar | `#infoChip`, `#fileLabel`, `#statusbar` | Focus: Crop | |
| C13 | PDF load (page 1 at 150 DPI) | `loadPDF` | Focus: Crop | Page 1 only (gap G9). Other pages come through Upload drawing (I1). |
| C14 | CAD file picked in the cropper is converted on the server | bridge `hookCadIntake` → `cad-open` message → `loadCadFile` | Same flow; handled by `intake.js` | |
| C15 | Mirror of the loaded drawing to the parent | bridge `src-open` message, `expectEcho` | Same flow; updates the 2D viewer and intake draft | |

## 5. Sheet 1: mode bar and Mark regions

| # | Control or behavior | Old id / function | New location | Notes |
|---|---|---|---|---|
| M1 | Mode switch: Crop views, Mark regions | `#crop-mode-crop`, `#crop-mode-mark`, `setCropMode` | Segmented control in the focus overlay header; entry points: 2D toolbar buttons "Crop" and "Mark", and Inspector › Part Setup › Views | |
| M2 | Mode hint text | `#crop-mode-hint` | Focus overlay header subtitle | |
| M3 | Draw tool toggle | `#mark-toggle`, `markOn`, `syncMarkTool` | Focus: Mark toolbar | |
| M4 | Place datum tool toggle | `#origin-toggle`, `originOn` | Focus: Mark toolbar | |
| M5 | Datum kind (Origin, Datum A, B, C, Datum hole) | `#datum-kind` | Focus: Mark toolbar | |
| M6 | Origin lock or unlock | `#origin-lock`, `updateOriginControls` | Focus: Mark toolbar | Lock glyph becomes an SVG icon; text "Locked" or "Unlocked" stays. |
| M7 | Group color and swatch (15-color palette) | `#mark-color`, `#mark-swatch`, `REGION_PALETTE` | Focus: Mark toolbar | Palette is persisted data, kept as a JS constant. |
| M8 | Role for next box | `#mark-role`, `REGION_ROLES` | Focus: Mark toolbar | |
| M9 | Tool hint | `#mark-hint` | Focus: Mark toolbar | |
| M10 | Add to Part Setup (marked drawing becomes a "Marked View" item) | `#mark-addview`, `composeMarkedDataURL`, `addIntakeItems` | Focus: Mark toolbar; after adding, the overlay closes and Inspector › Part Setup › Views opens | |
| M11 | Clear regions (confirm) | `#mark-clear` | Focus: Mark toolbar, danger button with confirm dialog | |
| M12 | Markup canvas: draw box, resize handle, delete, pan, zoom, double-click reset | `#mk-box`, `#mk-img`, `#ov-mark-layer`, `renderMarkBoxes`, `beginResize`, `deleteRegion`, `__mkReset`, `__mkSyncLayer` | Focus: Mark, left pane | |
| M13 | Origin crosshair and datum markers with delete | `.origin-mark`, `.datum-mark` | Focus: Mark, left pane | |
| M14 | Region sidebar: origin note, datum rows with value, groups with role, value, coordinates, delete | `#regions-body`, `renderRegionsPanel`, `patchRegion` | Focus: Mark, right pane (360 px) | |
| M15 | Region count | `#regions-count` | Focus: Mark, right pane header | |
| M16 | Empty state | `#mk-empty` | Focus: Mark, left pane | |
| M17 | Autosave of regions (600 ms debounce) | `scheduleRegionSave`, `saveRegionsNow` → `POST /api/parts/{s}/{p}/regions` | Same, in `markup.js` | "Saved" or "Save failed, retrying on next change" indicator in the overlay header. |
| M18 | Composite marked view upload | `saveMarkedViewNow`, `buildMarkedCanvas` → `POST /api/parts/{s}/{p}/marked-view` | Same, in `markup.js` | |
| M19 | Load regions for a part | `loadRegionsFor` → `GET /api/parts/{s}/{p}/regions` | Same | |
| M20 | Regions drawn before the part is saved move to the part on save | `INTAKE_REGION_KEY` handling in the save handler | Same | |
| M21 | Marked view image (server copy) | `GET /api/parts/{s}/{p}/marked-view.jpg` (not used by the old UI) | 2D viewer source switch "Overview / Marked" when `has_marked` is true | New use of an existing endpoint. |

## 6. Sheet 2: intake strip

| # | Control or behavior | Old id / function | Endpoint | New location | Notes |
|---|---|---|---|---|---|
| I1 | Upload drawing (PDF, JPG, PNG, WEBP, BMP, TIF, DWG, DXF, EDRW, EPRT, EASM) | `#intake-file` change handler | none for PDF and images (client side); `POST /api/convert-dwg` for CAD | Home dropzone and "Create 3D Model"; Inspector › Part Setup "Upload drawing"; 2D viewer empty state | PDF: every page up to 12 at 200 DPI becomes an item. Never starts a run. |
| I2 | Upload parts folder | `#batch-folder` | `POST /api/parts/upload-batch` | Home link "Upload parts folder"; Projects page button; Inspector › Part Setup | |
| I3 | Pull queued crops | `#pull-crops-btn`, `MTIBridge.collect` | none | Focus overlay header button "Pull queued crops"; Inspector › Part Setup › Views | |
| I4 | Source format badge | `#src-format`, `updateSourceBadges` | `parts[].source_format` or `intake.format` | 2D panel header badge | |
| I5 | Multi-sheet picker for DWG/DXF | `#sheet-picker`, `#sheet-select`, `#sheet-load`, `pendingCad` | `POST /api/convert-dwg` with `layout` | Modal dialog "Choose a sheet" opened wherever the upload started | |
| I6 | eDrawings static preview labeling | `X-Static-Preview` header | `POST /api/convert-dwg` | 2D panel header badge "eDrawings (static preview)" | |
| I7 | Converted CAD image also opens in the cropper | `MTIBridge.sendImage` | none | Same | |
| I8 | View gallery cards | `#orient-gallery`, `renderGallery` | none | Inspector › Part Setup › Views | |
| I9 | View type dropdown per image (Front, Back, Left, Right, Top, Bottom, Full Overview View, Marked View) | `.oselect`, `ORIENTATIONS` | none | Views card | This is where view assignment lives; there is no permanent View Appearance card. |
| I10 | Rotate 90° per image | `.ibtn ⟳`, `rotateDataURL` | none | Views card | |
| I11 | Remove image | `.ibtn ✕` | none | Views card | |
| I12 | Duplicate orientation badge and confirm on save | `.dupbadge`, `dupOrientations` | none | Views card; confirm dialog | |
| I13 | Orientation guess from crop name | `guessOrientation` | none | Same, in `intake.js` | |
| I14 | Validation message (front plus one more orthographic view, name) | `#req-warn`, `validateIntake`, `ORTHO_SET` | none | Views card footer | Client-side rule inherited from the old UI; the backend itself requires only that the part has images (gap G7). |
| I15 | Part name | `#part-name` | none | Inspector › Part Setup "Part Name" | |
| I16 | Save part | `#save-part-btn` | `POST /api/parts` | Inspector › Part Setup "Save part" (violet) | Adds a warning before overwriting an existing part's saved views. |
| I17 | Unassigned images confirm on save | save handler | none | Confirm dialog | |
| I18 | Must-Meet Specifications textarea | `#part-notes` | sent with `POST /api/parts` as `notes` | Inspector › Part Setup › Must-meet specs | Amber "authoritative" label kept. |
| I19 | Update specs for selected part | `#save-notes-btn` | `POST /api/parts/{s}/{p}/notes` | Inspector › Part Setup › Must-meet specs | |
| I20 | Empty and placeholder hints | `#intake-empty`, `#save-placeholder` | none | Views card empty state | |
| I21 | Intake status line | `#intake-status`, `setStatus` | none | Global status region `#status-live` (toast plus tracker caption) | One message source, as today. |
| I22 | Session creation | `POST /api/session` on every load | `POST /api/session` | `api.js` boot | Now reused across refreshes (key `mca.session`), so saved parts stay listed. |

## 7. Sheet 2: must-meet checklist and split viewers

| # | Control or output | Old id / function | Data source | New location | Notes |
|---|---|---|---|---|---|
| V1 | Must-Meet Check strip (pass, fail, measured vs required) | `#mm-checklist`, `paintMustMeet` | `categories.must_meet` | Results › Build & Verification › Verification (checks list); condensed count in the Drawer header verdict | |
| V2 | Stage label "verified against the SolidWorks build" or "pre-validated (CadQuery)" | `paintMustMeet` | `must_meet.stage` | Verification section source line | |
| V3 | Full Overview View image | `#ov-img`, `updateOverviewBox`, `paintOverviewImage` | `GET /api/parts/{s}/{p}/overview.jpg`, or the intake draft image | Workspace 2D Drawing panel | |
| V4 | Overview caption with part name | `#viewer-part` | state | 2D panel header (name chip) and Workspace header title | |
| V5 | Overview pan, wheel zoom, double-click reset | `__ovReset` IIFE | none | 2D panel; plus toolbar buttons Fit, Zoom in, Zoom out, Reset, Fullscreen, Maximize, and keyboard control | |
| V6 | Overview empty state | `#ov-empty` | none | 2D panel empty state with Upload action | |
| V7 | "Most recent action wins" preview rule | `previewOverride`, `showSourcePreview` | none | `selectors.drawingSource(state)` | Same rule. |
| V8 | STL viewer (orbit, zoom, pan, grid, auto frame) | `viewer` IIFE (`init`, `load`, `clear`, `frame`, `onShow`) | `GET /api/parts/{s}/{p}/model.stl?t=<stl_mtime>` | Workspace 3D Model (STL) panel | Adds Fit, Reset, view presets, Fullscreen, Maximize. |
| V9 | PRE-VALIDATED (CadQuery) badge | `#stl-badge` | `stl_source === 'prevalidation'` | 3D panel header chip | |
| V10 | STL empty state | `#stl-empty` | none | 3D panel "No model generated yet" with the SolidWorks note | |
| V11 | Select Model dropdown | `#model-select`, `fillRunSelect` | `GET /api/run-history` | Workspace header part selector `#part-switch` (parts of this session plus "Other runs"); also Projects and Recent | Switching updates drawing, model, tracker and results together. |
| V12 | STL load error (console warning only) | `viewer.load` error callback | none | 3D panel error state with Retry | |

## 8. Sheet 3: pipeline

| # | Control or output | Old id / function | Endpoint | New location | Notes |
|---|---|---|---|---|---|
| P1 | Saved parts cards (thumbnail, name, view count, overview and marked chips, "ran", "selected") | `#parts-list`, `renderParts`, `selectPart` | `GET /api/parts?session=`, `GET /api/parts/{s}/{p}/thumb.jpg` | Projects page (cards); Workspace header part selector (list with the same chips) | |
| P2 | Parts empty state | `.parts-list .empty` | none | Projects empty state; Workspace 2D empty state | |
| P3 | Pull & Run Pipeline | `#run-btn` | `POST /api/run-part` (`session`, `part`) | Tracker bar, gold button `#run-btn` "Run Pipeline" | The only gold control. Disabled with a stated reason. |
| P4 | Run All Parts | `#run-all-btn`, `runAllActive` | sequential `POST /api/run-part` | Inspector › Pipeline Actions (secondary); Projects page | Confirm dialog first. Aggregate "N of M parts complete" in the tracker. |
| P5 | Cancel | `#cancel-btn` | `POST /api/runs/{id}/cancel` | Tracker bar, next to the running indicator; Inspector › Pipeline Actions | |
| P6 | Demo sample select | `#demo-sample` | `GET /api/status` → `samples` | Inspector › Pipeline Actions; Home "Run demo" | |
| P7 | Run demo | `#demo-btn` | `POST /api/demo` | Inspector › Pipeline Actions (secondary, "Demo" tag); Home link | Demo outputs carry a Demo badge and never enter Projects or Recent. |
| P8 | Run status text | `#run-status`, `setStatus` | none | Tracker caption `#trk-caption` and toast; `aria-live` region | |
| P9 | Stage strip, 12 chips | `#stage-strip`, `STAGE_LIST`, `stageFromLine`, `paintStages`, `finishStages` | `[STAGE]` lines on `GET /api/runs/{id}/log` | Five-stage tracker; the 12 sub-steps appear in each stage's tooltip and in Results › Diagnostics › Run Log / Events | Mapping in ARCHITECTURE section 6. |
| P10 | Progress bar and percent | `#progress-fill`, `progressFromLine`, `setProgress` | log lines | Tracker percent ring `#trk-pct` | Recomputed from completed work units only. The old 2% starting value is removed. |
| P11 | Elapsed timer | `#elapsed-txt` | client clock; `started` and `finished` in `GET /api/runs/{id}/outputs` | Drawer header "Runtime" and tracker caption | A clock, never used for percent. |
| P12 | Log toggle | `#log-toggle` | none | Drawer section "Console" | |
| P13 | Inline live console | `#inline-console` | SSE | Drawer › Console and Results › Diagnostics › Console (same buffer) | |
| P14 | Run banner (READY, N/M READY, NOT READY, FAILED, must-meet failure text) | `#run-banner`, `bannerFromRun`, `__mmFailed` | console text, `must_meet.failed`, exit code | Drawer header (run state chip plus verification verdict chip) and Results › Overview | Verdict now also reads `multiview_summary.csv`. |
| P15 | Overview Analysis panel (shape, views detected, conflicts, correspondences, global notes, symmetry, marked regions list, badges) | `#ovan-panel`, `renderOvanPanel`, `regionsSubsectionHTML` | `categories.overview_analysis` | Results › Extraction › Overview Analysis; conflict count in Results › Overview "Needs attention" | Opens automatically in the Drawer when conflicts arrive during a live run. |
| P16 | Correction text | `#feedback-text` | none | Inspector › Corrections (two-line input, expands on focus, "Open editor" dialog) | Draft kept per part (`mca.corr.<session>.<part>`). |
| P17 | Re-run with correction | `#rerun-feedback-btn` | `POST /api/run-part` with `feedback` and `no_cache=true` | Inspector › Corrections (violet secondary) | Draft is cleared only after the server returns a run id. |
| P18 | Correction hint | `#fb-hint` | none | Corrections card helper text | |
| P19 | Final status messages (finished with delivered paths, exit 8 review flags, failed with exit code, cancelled) | `monitorRun` done branch | `GET /api/runs/{id}/outputs` | Toast, tracker caption, Results › Overview | |
| P20 | Parts list refresh and history refresh after a run | `monitorRun` done branch | `GET /api/parts`, `GET /api/run-history` | Same, in `run.js` `finalizeRun` | |

## 9. Sheet 4: run outputs

| # | Control or output | Old id / function | Data source | New location | Notes |
|---|---|---|---|---|---|
| O1 | Select Run dropdown | `#run-select`, `syncOutputsToRun` | `GET /api/run-history` | Results page run selector `#res-run` and breadcrumb; Recent page rows | |
| O2 | Clear all models (confirm) | `#clear-runs-btn` | `POST /api/run-history/clear` | Settings › Data (danger zone) and Projects page overflow menu | Scoped confirm dialog with the count; disabled during a run. |
| O3 | Dock collapse | `#dock-toggle`, `setDockOpen` | none | Drawer collapse, expand, resize | |
| O4 | Extraction JSON | `#panel-extraction`, `paintText`, `prettyJSON` | `categories.extraction` `{present,name,text}` | Results › Extraction › Extraction JSON | Tree and raw, search, copy, download; numbers shown as written. |
| O5 | Resolved Extraction | `#panel-resolved` | `categories.resolved` | Results › Extraction › Resolved Extraction | |
| O6 | Build Plan | `#panel-buildplan` | `categories.build_plan` | Results › Build & Verification › Build Plan | Expandable operations plus raw. |
| O7 | Verification report | `#panel-verification` | `categories.verification` | Results › Build & Verification › Verification | Verdict, checks (V1), report text. |
| O8 | Engineering Flags (summary counts, ranked items, Overview Verification group, Human-Specified Requirements group, status chips) | `#panel-flags`, `paintReview` | `categories.review` `{items,text}` | Results › Build & Verification › Engineering Flags | Adds severity filters and a raw text toggle. "Save all to Learning Loop" is shown disabled (gap G3). |
| O9 | Model Check | `#panel-modelcheck` | `categories.model_check` | Results › Build & Verification › Model Check | Kept separate from Verification. Empty state keeps the "requires Windows + SolidWorks" text. |
| O10 | VBA Macros (file tabs, code) | `#panel-macros`, `paintMacros`, `#macro-tabs` | `categories.macros.files[] {name,text}` | Results › Automation & Files › VBA Macros | Adds copy and download per file. |
| O11 | Token / Cost (cards and ledger text) | `#panel-cost`, `paintUsage` | `categories.usage` | Results › Diagnostics › Token / Cost | Adds per-call table; tokens labeled measured, cost labeled estimated. |
| O12 | Files (table with download links, delivered paths) | `#panel-files`, `paintFiles` | `categories.files.list[]`, `delivered`, `delivered_downloads` | Results › Automation & Files › Files | |
| O13 | Console (live or persisted transcript) | `#panel-console`, `#console-pre` | SSE, or `categories.console.text` (`ui_console.log`) | Results › Diagnostics › Console | Adds filter, search, copy, auto-scroll toggle. |
| O14 | Output loading and empty messages | `resetOutputs` | none | Per-section loading, empty and error states | |
| O15 | (not in the old UI) Run log as structured events | none | same lines as O13 | Results › Diagnostics › Run Log / Events | New rendering of existing data. |
| O16 | (not in the old UI) Overview summary | none | computed from the above | Results › Overview | |

## 10. Endpoints: old use and new use

| Endpoint | Old UI use | New UI use |
|---|---|---|
| `GET /` | serves `index.html` | same file path, new content |
| `GET /bridge.js` | script tag | same |
| `GET /pdf.min.js`, `GET /pdf.worker.min.js` | script tag, worker | same |
| `GET /photoapp/` | iframe | iframe inside the focus overlay |
| `GET /vendor/*` | three.js, STLLoader, OrbitControls | same |
| `GET /static/*` | `design-tokens.css` | tokens plus new `css/*.css` and `js/*.js` (same mount, no new route) |
| `GET /api/status` | API pill, demo samples | header API chip, engine (with B1), demo samples, Run button gating; polled every 30 s and on window focus |
| `GET /api/samples` | unused | Home "Open sample" refresh (same data as status) |
| `POST /api/session` | every load | only when `mca.session` is absent |
| `POST /api/parts` | Save part | same |
| `GET /api/parts?session=` | after runs, after clear | boot, after save, after runs, Projects page |
| `POST /api/parts/upload-batch` | Upload parts folder | same |
| `GET /api/parts/{s}/{p}/thumb.jpg` | part cards | Projects cards, part selector, Recent rows |
| `POST /api/parts/{s}/{p}/notes` | Update specs | same |
| `GET` and `POST /api/parts/{s}/{p}/regions` | markup load and autosave | same |
| `POST /api/parts/{s}/{p}/marked-view` | composite upload | same |
| `GET /api/parts/{s}/{p}/marked-view.jpg` | unused | 2D viewer "Marked" source |
| `GET /api/parts/{s}/{p}/overview.jpg` | overview panel, markup image | 2D viewer, markup image |
| `GET /api/parts/{s}/{p}/outputs` | outputs for selected part or history run | single source for Results, Drawer, header chips, verdict |
| `GET /api/parts/{s}/{p}/file/{name}` | Files tab links | Files, per-section downloads, Export Selected, `multiview_summary.csv` fetch |
| `GET /api/parts/{s}/{p}/model.stl` | STL viewer | same |
| `GET /api/run-history` | both dropdowns | part selector, Projects, Recent, Results run selector |
| `POST /api/run-history/clear` | Clear all models | Settings and Projects danger action |
| `POST /api/run-part` | Run, Run All, Re-run with correction | same three uses; optional `no_cache` checkbox |
| `POST /api/demo` | Run demo | same |
| `GET /api/runs/{id}/log` (SSE) | live console, stage strip, progress | run monitor (tracker, console, events), with replay de-duplication |
| `POST /api/runs/{id}/cancel` | Cancel | same |
| `GET /api/runs/{id}/outputs` | live polling every 1.2 s | live polling; reconnect probe after refresh |
| `GET /api/runs/{id}/files` | unused | Demo runs: Files section |
| `GET /api/runs/{id}/download/{name}` | unused | Demo runs: file downloads |
| `GET /api/runs/{id}/zip` | unused | "Download all (.zip)" for the run tracked in this server lifetime |
| `GET /api/runs/{id}/model.stl` | unused | Demo runs: 3D viewer (when a demo produces an STL) |
| `GET /api/runs/{id}/source.jpg` | unused | not used (only `/api/run-views` writes it) |
| `POST /api/convert-dwg` | CAD intake | same |
| `POST /api/run` | unused | not used (single-image run without views; superseded by the part flow). Listed in Help as backend-only. |
| `POST /api/run-views` | unused | not used (superseded by `POST /api/parts` plus `POST /api/run-part`). |

## 11. Client state: old globals and their new home

| Old global | Meaning | New store path |
|---|---|---|
| `sessionId` | parts session | `session.id` (persisted `mca.session`) |
| `liveKey` | API key present | `server.live` |
| `partsData` | parts of the session | `parts.list` |
| `selectedPart` | selected part name | `parts.selected` `{session, part}` |
| `isRunning` | a run is active | `selectors.isRunning(state)` from `run.state` |
| `currentRunId` | active run id | `run.id` (persisted `mca.activeRun`) |
| `runAllActive` | batch loop active | `batch.active`, `batch.queue`, `batch.index`, `batch.results` |
| `runHistory` | run history | `history.runs` |
| `outputsCtx` | which outputs are shown | `outputs.ctx` |
| `intake` | unsaved draft | `intake` |
| `previewOverride` | draft claims the 2D panel | `intake.previewOverride` |
| `pendingCad`, `expectEcho` | CAD sheet pick, echo suppression | `intake.pendingCad`, `intake.expectEcho` |
| `regionsByKey`, `originByKey`, `datumsByKey`, `regionsDirty` | markup | `markup.*` |
| `markOn`, `originOn`, `window.__markOn` | markup tool | `markup.tool` |
| `lastOvanData` | overview analysis | `outputs.payload.categories.overview_analysis` |
| `window.__mmFailed` | must-meet failures | `outputs.payload.categories.must_meet.failed` |
| `stageIdx`, `progressPct` | stage and percent | `run.track` (reducer output) |
| `runStartedMs`, `elapsedTimer` | elapsed clock | `run.startedAt`, `run.finishedAt` |
| `lastMacroCount` | macro repaint guard | removed (render is keyed on payload identity) |
| `es`, `pollTimer` | SSE and poll handles | private to `run.js` |

## 12. Items the brief asks for that do not exist today

| Item | Status | Where it shows |
|---|---|---|
| Sidebar, Home, Projects, Recent Files, Help, Settings | new shell around existing data | sections 3 and 5 of ARCHITECTURE |
| Five-stage tracker | new presentation of the existing 12 `[STAGE]` markers | Tracker |
| Splitter, maximize, fullscreen for the two viewers | new | Workspace canvas |
| Export card with deliverable checkboxes | new; uses the existing file endpoint | Inspector › Export |
| Results Overview | new; computed from existing payloads | Results › Overview |
| Run Log / Events | new rendering of console lines | Results › Diagnostics |
| Save all to Learning Loop | no backend endpoint | disabled button with reason (gap G3) |
| Engine name from backend | not exposed | backend delta B1, honest fallback (gap G1) |
| Reconnect after refresh | no active-run listing | client persistence of the run id (gap G4) |
