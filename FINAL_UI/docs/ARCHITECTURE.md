# ARCHITECTURE.md: McAgent redesign implementation plan

Scope: a frontend and interaction redesign of `web/` and `server/` in vanilla HTML, CSS and JS. No framework, no CDN, no bundler. Backend routes, payloads and saved formats stay as they are. Companion doc: `FEATURE_INVENTORY.md` (old control → new location). All paths below are relative to `web/` and `server/` unless stated.

Facts this plan relies on, all read from the code:

- `app.py` already mounts `/static` (`StaticFiles(directory=web/static)`), `/vendor`, `/photoapp`, and serves `/`, `/bridge.js`, `/pdf.min.js`, `/pdf.worker.min.js`.
- Runs are subprocesses of `main.py`; state lives in the in-memory dict `RUNS[run_id]` (`lines`, `done`, `exit`, `started`, `finished`, `cancelled`, `delivered`, `delivered_downloads`). A server restart forgets every run id.
- `GET /api/runs/{id}/log` is SSE. Every connection replays all lines from index 0, then sends `event: done` with the exit code as data.
- Part runs (`POST /api/run-part`) execute `main.py --views-folder <part dir> --output <part dir>/output --no-export`. The output folder is reused between runs, so during a re-run `GET /api/runs/{id}/outputs` still returns the previous run's files until they are overwritten.
- Stage markers are printed as plain lines `[STAGE] <name>` by `main.py` (`_run_views_folder`) and `pipeline/batch.py` (`process_drawing_data`).
- Demo runs (`POST /api/demo`) execute `main.py --from-json`, which prints `[1-2/4]`, `[2.5/4]`, `[3/4]`, `[4/4]` lines and no `[STAGE]` markers.
- Exit codes. Part runs: `0` every part READY, `8` at least one part not READY (NOT READY, BLOCKED or ERROR), `2` bad folder. Demo and single runs: `0` ok, `2` or `3` input errors, `4` BLOCKED, `5` SolidWorks connection, `6` build failed, `7` built-model validation failed. `127` launch error (set by `_start_run`).
- `/api/status` returns `{live, samples}` only. `live` means `ANTHROPIC_API_KEY` is set; it is not a connectivity check. The model name is not exposed (`pipeline/extractor.py`: `os.getenv("EXTRACTION_MODEL") or DEFAULT_MODEL`).

## 1. File and module layout

```
webapp/
  index.html                  REWRITTEN: shell markup only (no inline CSS or JS beyond a 3-line boot guard)
  bridge.js                   UNCHANGED
  photoapp/index.html         UNCHANGED (restyled only through the shared tokens)
  static/
    design-tokens.css         RETOKENED (section 7); still the single token source for both documents
    css/
      base.css                reset, typography, focus, scrollbars, utilities (.sr-only, .grow, .mono)
      shell.css               app grid, sidebar, page header, toasts, dialogs
      workspace.css           tracker, split canvas, viewer panels, inspector, drawer, focus overlay
      results.css             results layout, section chrome, JSON tree, code view, tables, flags, console
      pages.css               home, projects, recent, help, settings
    js/
      core/util.js            McA.util: esc, el, fmtBytes, fmtElapsed, debounce, copyText, downloadURL
      core/store.js           McA.store: single state store (section 4)
      core/api.js             McA.api: one function per endpoint (section 5)
      core/router.js          McA.router: hash router (section 3)
      core/persist.js         McA.persist: localStorage keys (section 9.5)
      logic/stages.js         PURE: [STAGE] reducer, five-stage mapping, percent (section 6)
      logic/runstate.js       PURE: run state and verification verdict
      logic/selectors.js      PURE: derived values (run button reason, deliverables, drawing source)
      logic/logparse.js       PURE: console lines → structured events
      logic/jsontree.js       PURE: lossless JSON parser for the tree view
      logic/csv.js            PURE: minimal RFC 4180 parser for multiview_summary.csv
      logic/registry.js       PURE: results registry (section 11)
      features/run.js         run launch, SSE monitor, polling, cancel, batch queue, reconnect
      features/intake.js      upload, PDF rasterize, CAD convert, gallery, save part, notes
      features/markup.js      reference regions, datums, marked view (moved from index.html)
      features/cropper.js     focus overlay, iframe bridge wiring
      features/viewer2d.js    drawing pan, zoom, fit, fullscreen
      features/viewer3d.js    three.js STL viewer
      ui/sidebar.js  ui/tracker.js  ui/split.js  ui/inspector.js  ui/drawer.js
      ui/results.js  ui/dialog.js  ui/toast.js  ui/icons.js
      pages/home.js  pages/workspace.js  pages/projects.js  pages/recent.js
      pages/resultsPage.js  pages/help.js  pages/settings.js
      main.js                 boot sequence
  tests/unit/
    unit/*.test.js            node --test (section 14.1)
    fixtures/                 recorded console transcripts and outputs payloads
Meta_Nebula_UI/e2e/           Playwright project with its own package.json (section 14.2)
```

### 1.1 Script format: classic scripts, one namespace

Every file is a classic script loaded with `<script defer src="/static/js/...">` in dependency order. Each file is an IIFE that attaches to `window.McA`. ES modules are not used: browsers enforce a strict JavaScript MIME type for module scripts, and Python's `mimetypes` on Windows (the SolidWorks machine) can report `.js` as `text/plain` from the registry. Classic scripts are not subject to that check.

Files under `logic/` use this wrapper so node can `require` them:

```js
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).stages = factory();
})(typeof self !== 'undefined' ? self : this, function () { /* no DOM, no fetch */ return { ... }; });
```

Load order in `index.html`: `/pdf.min.js`, `/bridge.js`, `/vendor/three.min.js`, `/vendor/STLLoader.js`, `/vendor/OrbitControls.js`, then `core/*`, `logic/*`, `ui/*`, `features/*`, `pages/*`, `main.js`.

### 1.2 FastAPI static routes

**No new routes are needed.** The existing `/static` mount serves `static/css/*` and `static/js/*`. Do not add a second mount. `tests/unit/` is outside `static/` and is not served.

### 1.3 Backend deltas

One additive change is recommended (B1). Everything else works with `app.py` untouched.

| Id | Change | Why | Without it |
|---|---|---|---|
| B1 | In `status()`, add `"model": os.getenv("EXTRACTION_MODEL") or <DEFAULT_MODEL from pipeline.extractor, imported inside a try>` and `"provider": "anthropic"`. Existing keys unchanged. | Brief rule 5: engine name comes from the backend. | Engine chip shows the model from the last usage ledger row of the selected part, else "Not reported". |
| B2 (optional) | `GET /api/runs/active` → `[{id, part, started}]` for runs with `done == False`. | Find a run started in another tab. | Reconnect works only in the browser that started the run (gap G4). |

## 2. Shell markup (index.html)

```html
<body class="app" data-sidebar="expanded">
  <a class="skip-link" href="#main">Skip to content</a>
  <nav id="sidebar" class="sidebar" aria-label="Primary">…</nav>
  <main id="main" class="main" tabindex="-1">
    <section id="page-home"      class="page" data-page="home" hidden>…</section>
    <section id="page-workspace" class="page" data-page="workspace" hidden>…</section>
    <section id="page-projects"  class="page" data-page="projects" hidden>…</section>
    <section id="page-results"   class="page" data-page="results" hidden>…</section>
    <section id="page-recent"    class="page" data-page="recent" hidden>…</section>
    <section id="page-help"      class="page" data-page="help" hidden>…</section>
    <section id="page-settings"  class="page" data-page="settings" hidden>…</section>
  </main>
  <div id="focus" class="focus" role="dialog" aria-modal="true" aria-labelledby="focus-title" hidden>…</div>
  <div id="dialog-root"></div>
  <div id="toast-root" class="toasts" aria-live="polite"></div>
  <div id="status-live" class="sr-only" role="status" aria-live="polite"></div>
  <div id="alert-live"  class="sr-only" role="alert"></div>
</body>
```

All pages stay in the DOM and are toggled with `hidden`. The cropper iframe, the three.js canvas and the run monitor therefore survive navigation, and navigating never touches a running pipeline.

## 3. Hash router and pages

`McA.router`: `parse(hash) → {page, params}`, `go(page, params)`, `start()`. On `hashchange` it writes `store.route`, toggles `hidden`, sets `aria-current="page"` on the sidebar item, moves focus to the page `<h1>`, and sets `document.title` to `<Page> · McAgent`. Unknown hashes redirect to `#/home`.

| Hash | Page | Purpose | Data |
|---|---|---|---|
| `#/home` | Home | "What would you like to create?", one dropzone, one action | `server.samples`, `history.runs` (top 5) |
| `#/workspace` (`?part=<name>&session=<id>`) | Workspace | header, tracker, split canvas, inspector, drawer | everything |
| `#/projects` | Projects | parts of this session, batches, run history | `parts.list`, `history.runs`, `batch` |
| `#/results` (`?run=<session>\|<part>&sec=<id>`) | Pipeline Results | run selector, five groups | `outputs` |
| `#/recent` | Recent Files | run history newest first | `history.runs` |
| `#/help` | Help | workflow, formats, shortcuts, exit codes, output folders | static plus `server` |
| `#/settings` | Settings | server status, layout reset, data danger zone | `server`, `persist` |

"New Project" in the sidebar is an action, not a page: if `intake.items.length > 0` it asks to discard the draft; then it clears `intake`, clears `parts.selected`, and goes to `#/home`. It never cancels or resets `run`.

## 4. State store and event flow

### 4.1 Store API (`core/store.js`)

```js
McA.store.get()                        // current state (treat as read-only)
McA.store.set(patch)                   // shallow merge at top level, then notify
McA.store.update('run.track', fn)      // path update, then notify
McA.store.subscribe(selector, cb)      // cb(newValue, oldValue) only when selector output changes (===)
McA.store.dispatch(type, payload)      // named actions from 4.3; the only way features mutate state
```

Notifications are batched with `queueMicrotask`. Components never call each other; they dispatch actions and subscribe to selectors.

### 4.2 State shape

```js
{
  route:   { page, params },
  server:  { loaded, reachable, live, samples: [], model: null, provider: null },
  session: { id },
  parts:   { list: [], selected: null /* {session, part} */, loading, error },
  intake:  { items: [] /* {id,dataURL,orientation,label} */, source, originalFile, stem, format,
             nameDraft, notesDraft, previewOverride, pendingCad, expectEcho },
  markup:  { regionsByKey: {}, originByKey: {}, datumsByKey: {}, dirty: [], tool: 'draw' /* draw|datum|pan */,
             color, role, datumKind, saveState: 'idle' /* idle|saving|saved|error */ },
  run:     { id, kind /* 'part'|'demo' */, session, part, state /* 4.4 */, startedAt, finishedAt,
             exit, cancelled, cancelPending, lines: [], track /* stages.js output */, summary /* csv row */, error },
  batch:   { active, queue: [], index, results: {} /* part → {state, exit, error} */ },
  history: { runs: [], loaded, error },
  outputs: { ctx /* {kind:'part',session,part} | {kind:'run',runId} */, payload, loading, error, fetchedAt },
  viewer3d:{ status /* empty|loading|ready|error */, url, source, previousRun, error },
  ui:      { sidebarCollapsed, inspectorCollapsed, inspectorOpen: {setup,actions,corrections,export},
             drawerOpen, drawerHeight, drawerMode /* results|tools */, drawerSection,
             splitRatio, maximized /* null|'2d'|'3d' */, narrowTab /* '2d'|'3d' */,
             focusMode /* null|'crop'|'mark' */, resultsSection, raw: {}, flagsFilter: [], consoleFilter, corrDraft: {} }
}
```

### 4.3 Actions and flow

| Action | Fired by | Effect |
|---|---|---|
| `server/status` | boot, 30 s timer, window focus | `api.status()` → `server` |
| `parts/loaded`, `parts/select` | boot, save, upload-batch, run end, selector | select sets `parts.selected`, `outputs.ctx`, then `outputs/load`, `markup/load`, viewer refresh |
| `intake/add`, `intake/update`, `intake/remove`, `intake/reset` | intake.js | draft edits; `selectors.intakeValidation` recomputes |
| `run/launch` | Run Pipeline, Re-run, batch loop, demo | sets `run` to `queued`, calls the API, on id → `running`, persists `mca.activeRun`, starts monitor |
| `run/line` | SSE message | pushes to `run.lines`, `run.track = stages.reduce(run.track, line)` |
| `run/poll` | 1.2 s poll of `GET /api/runs/{id}/outputs` | updates `outputs.payload` when `outputs.ctx` matches the run's part |
| `run/done` | poll sees `done` | section 6.6 finalize |
| `run/cancel` | Cancel | `cancelPending = true`, `api.cancel(id)` |
| `batch/start`, `batch/next`, `batch/stop` | Run All Parts | sequential loop (section 12) |
| `outputs/load` | part or run selection, run end | `api.partOutputs` or `api.runOutputs` → `outputs` |
| `history/load` | boot, run end, clear | `api.runHistory()` |
| `ui/*` | layout controls | updates `ui`, persisted by `persist.js` |

Stale-response rule: every async action captures a token (`run.id`, or `outputs.ctx` identity) before awaiting and drops the result if the token changed. SSE handlers check `store.get().run.id === id` before dispatching.

### 4.4 Run state (`logic/runstate.js`)

`deriveRunState({hasId, done, exit, cancelled, launching})`:

| State | Condition |
|---|---|
| `idle` | no run |
| `queued` | launch request sent and no id yet, or the part is waiting in `batch.queue` |
| `running` | id known and `done` false |
| `cancelled` | `done` and `cancelled` true |
| `succeeded` | `done`, `exit === 0`, not cancelled |
| `succeeded_with_warnings` | `done`, `exit === 8`, not cancelled, and the summary row status is `NOT READY` (or the summary is unavailable) |
| `failed` | `done` and any other exit; also `exit === 8` when the summary row status is `BLOCKED` or `ERROR` |

`deriveVerdict({summary, mustMeet, stlSource, stlFresh, kind, exit})` returns the verification verdict shown separately from the run state:

| Verdict | Label | Condition |
|---|---|---|
| `passed` | Passed | summary status `READY`, and a SolidWorks STL from this run exists (`stlSource === 'solidworks'` and `stlFresh`) |
| `passed_unbuilt` | Checks passed, model not built | summary status `READY` and no fresh SolidWorks STL; also demo runs with exit 0 |
| `flags` | Review flags | summary status `NOT READY` |
| `failed` | Failed | summary status `BLOCKED` or `ERROR`; or `mustMeet.stage === 'post_build'` and `mustMeet.ok === false`; or demo exit 4, 6, 7 |
| `unknown` | Not available | run cancelled, or no summary and no must-meet data |

The summary row comes from `GET /api/parts/{s}/{p}/file/multiview_summary.csv` (columns `source, part, status, macro_readiness, geometry_completeness, dimension_completeness, consistency, feature_confidence, n_macros, n_needs_review, n_skipped, detail`), fetched once in finalize. If the fetch fails, fall back to the last `(\d+)/(\d+) READY` match in the console lines; if that is also absent the verdict is `unknown`.

`stlFresh` is `payload.stl_mtime >= Math.floor(payload.started)`.

## 5. API client (`core/api.js`)

One function per endpoint. Each returns parsed JSON or throws `ApiError {status, detail}` (FastAPI errors carry `detail`).

| Function | Request | Response fields used |
|---|---|---|
| `status()` | `GET /api/status` | `live`, `samples[]`, `model?`, `provider?` |
| `newSession()` | `POST /api/session` | `session` |
| `listParts(session)` | `GET /api/parts?session=` | `parts[]`: `name, n_views, views[], has_output, has_overview, has_marked, source_format, notes` |
| `savePart(fd)` | `POST /api/parts` form: `session, part, source_format, notes, source?, original?, crops[]` | `part`, `parts[]` |
| `uploadBatch(fd)` | `POST /api/parts/upload-batch` form: `session, paths[], files[]` | `added[]`, `n_files`, `n_skipped`, `parts[]` |
| `saveNotes(s,p,notes)` | `POST /api/parts/{s}/{p}/notes` form: `notes` | `parts[]` |
| `getRegions(s,p)` / `saveRegions(s,p,body)` | `GET` / `POST /api/parts/{s}/{p}/regions` JSON `{regions, origin, datums}` | `regions[]`, `featureGroups[]`, `origin`, `datums[]`; save returns `saved` |
| `saveMarkedView(s,p,blob)` | `POST /api/parts/{s}/{p}/marked-view` form: `file` | `saved`, `bytes` |
| `partOutputs(s,p)` | `GET /api/parts/{s}/{p}/outputs` | `has_any, stl_mtime, stl_source, categories{…}, part, ran, delivered, delivered_downloads` |
| `runPart({session, part, feedback?, no_cache?})` | `POST /api/run-part` form | `id`, `part` |
| `demo(sample?)` | `POST /api/demo` JSON `{sample}` | `id` |
| `runOutputs(id)` | `GET /api/runs/{id}/outputs` | as `partOutputs` plus `done, exit, started, finished, cancelled` |
| `runFiles(id)` | `GET /api/runs/{id}/files` | `files[]`: `name, size, category`; `report` |
| `cancel(id)` | `POST /api/runs/{id}/cancel` | `ok`, `already_done?` |
| `openLog(id, handlers)` | `EventSource /api/runs/{id}/log` | `message` data = one line; `done` data = exit code |
| `runHistory()` | `GET /api/run-history` | `runs[]`: `session, part, key, label, epoch, timestamp, output, present{…}` |
| `clearHistory()` | `POST /api/run-history/clear` | `removed`, `errors[]` |
| `convertCad(file, layout?)` | `POST /api/convert-dwg` form | PNG blob with headers `X-Source-Format, X-Static-Preview, X-Conversion-Tool, X-Layout`, or JSON `{layouts[], source_format}` |
| URL builders | `thumbURL`, `overviewURL`, `markedViewURL`, `partStlURL(s,p,mtime)`, `partFileURL(s,p,rel)`, `runStlURL`, `runDownloadURL(id,rel)`, `runZipURL(id)` | |

`categories` keys: `extraction, resolved, build_plan, verification, model_check` (each `{present, name, text}`; `text` is `null` above 400 KB), `review {present, items[], text}`, `usage {present, rows[], last_run, total_cost_usd, text, session_total_cost_usd?}`, `macros {present, files[{name, text}]}`, `sldprt {present}`, `stl {present, name, source}`, `must_meet {present, stage, ok, results[], constraints[], failed[], macro_results[]}`, `overview_analysis {present, name, data}`, `console {present, name, text}`, `files {present, list[{name, size}]}`.

`name` in the five text categories is a basename. To build a download URL, find the entry in `files.list` whose path ends with that basename (`registry.resolveFile(payload, basename)`).

## 6. Stage tracker

### 6.1 Sub-steps (the real work units)

Markers, in emission order, exactly as printed after `[STAGE] `. Match by longest prefix (`Verifying must-meet constraints` must not match `Verifying`).

| k | Marker prefix | Printed by | Always printed? | Presentation stage |
|---|---|---|---|---|
| 0 | `Overview analysis` | `main.py:597` | only when the part has an overview image | Extraction |
| 1 | `Extracting` | `main.py:616` | yes | Extraction |
| 2 | `Spec reconciliation` | `batch.py:278` | only with must-meet specs | Resolution |
| 3 | `Resolving` | `batch.py:309` | unless `--no-resolve` (the UI never passes it) | Resolution |
| 4 | `Verifying` | `batch.py:333` | yes | Build Plan |
| 5 | `Building macros` | `batch.py:408` | unless BLOCKED | Build Plan |
| 6 | `Pre-validating (CadQuery)` | `batch.py:426` | yes after macros | Generation |
| 7 | `Building .sldprt` | `batch.py:459` | only when SolidWorks is connected | Generation |
| 8 | `Verifying must-meet constraints` | `batch.py:477` | only with constraints and a built STL | Verification |
| 9 | `Final checks` | `batch.py:494` | yes | Verification |
| 10 | `Exporting` | `main.py:673` | yes | Verification |
| 11 | `Done` | `main.py:675` | yes | terminal |

Why `Verifying` (k=4) sits in Build Plan: it is the pre-build data gate that decides whether a build plan can be produced, and `Building macros` writes `build_plan.json`. The fifth stage is reserved for checks that run after generation.

### 6.2 Reducer (`logic/stages.js`)

```js
stages.initial(kind)              // kind: 'part' | 'demo'
stages.reduce(track, line)        // pure; returns a new track
stages.finalize(track, facts)     // facts: {exit, cancelled, summary, payload, startedAt}
stages.percent(track)             // integer 0-100 or null
stages.view(track)                // [{id,label,state,detail,substeps:[{label,state}]}] × 5, plus currentIndex, caption
```

`track = { kind, k: -1, seen: Set<number>, signals: {extractFailed, processFailed, resolveWarn, extractWarn}, done: false, final: null }`.

`reduce` rules for part runs:

- A `[STAGE]` line with index `i > track.k` sets `k = i` and adds `i` to `seen`. Lower or equal indices are ignored, so the tracker never moves backward.
- Line contains `Extraction failed:` → `signals.extractFailed`. Line contains `Processing failed:` → `signals.processFailed`.
- Line matches `^\[SPEC\] (CRITICAL|HIGH):` → `signals.resolveWarn`. Line contains `Overview analysis unavailable` or `Could not classify view` or `No FRONT view found` → `signals.extractWarn`.
- Lines starting with `[launch error]` or `[reader error]` set `signals.processFailed`.

Demo runs: sub-steps are the bracket lines `[1-2/4]` (Extraction, caption "Loaded saved extraction"), `[2.5/4]` (Resolution), `[3/4]` (Build Plan), `[4/4]` (Build Plan). Generation and Verification are `skipped` with detail "Demo runs stop after the macro package".

### 6.3 Stage state rules

While running (`track.done` false), for presentation stage S with sub-step indices `S.ks`:

| State | Condition |
|---|---|
| `pending` | `k < min(S.ks)` |
| `running` | `k` is in `S.ks` |
| `succeeded` | `k > max(S.ks)` and at least one of `S.ks` is in `seen`, no warning signal for S |
| `warning` | as succeeded, with a warning signal for S (`extractWarn`, `resolveWarn`) |
| `skipped` | `k > max(S.ks)` and none of `S.ks` in `seen` |
| `failed` | `extractFailed` and S is Extraction |

After `finalize` (the run is done), apply these in order; the first match wins:

1. Cancelled: the stage that was `running` becomes `skipped` with detail "Cancelled"; later stages `skipped`.
2. Hard failure (exit not 0 and not 8): the stage that was `running` becomes `failed` with detail "Exited with code N"; later stages `skipped` with detail "Not reached".
3. Extraction: `failed` if `extractFailed` or summary status is `ERROR` with `k <= 1`.
4. Build Plan: `failed` if summary status is `BLOCKED` (detail = `summary.detail`) or `ERROR` after k=4; `warning` if `summary.n_needs_review > 0` or `summary.n_skipped > 0`; else `succeeded`.
5. Generation:
   - `succeeded` when sub-step 7 was seen, `payload.stl_source === 'solidworks'` and the STL is fresh (`stl_mtime >= floor(started)`).
   - `failed` when sub-step 7 was seen and there is no fresh SolidWorks STL (detail from `summary.detail` if it contains `sldprt build failed`).
   - `warning` when sub-step 7 was not seen and a fresh pre-validation STL exists (detail "SolidWorks not available on this machine; CadQuery pre-validation model only").
   - `skipped` otherwise.
6. Verification: `failed` when `must_meet.stage === 'post_build'` and `must_meet.ok === false`; `warning` when summary status is `NOT READY`; `succeeded` when `READY`; `skipped` when sub-step 9 was never seen.
7. Stages after a failed stage that have no seen sub-step are `skipped` ("Not reached").

### 6.4 What is derivable and what is not

| Item | Derivable? | Source |
|---|---|---|
| Which sub-step is running | yes | `[STAGE]` markers |
| Sub-step skipped | yes, once a later marker arrives | marker order |
| Extraction failure | yes | `Extraction failed:` line, summary status `ERROR` |
| BLOCKED gate | yes, at the end | summary CSV `status` |
| SolidWorks build success | yes, at the end | marker 7 plus fresh `stl_source === 'solidworks'` |
| Must-meet pass or fail | yes | `[MM]` lines live, `categories.must_meet` |
| READY or NOT READY | yes, at the end | summary CSV, fallback console `N/M READY` |
| Progress inside a sub-step (for example percent of the extraction call) | **no** | not emitted; the ring shows no intermediate value |
| Time remaining | **no** | never shown |
| Queue position on the server | **no** | the backend has no queue; "queued" is client-side only |
| Run state after a server restart | **no** | `RUNS` is in memory; the UI says the run is no longer tracked and shows what is on disk |
| Demo Generation and Verification | **no** | the demo path does not perform them; shown as skipped |
| Stage status during a re-run from artifact presence | **no** | old files remain in the output folder; live state uses log markers only |

### 6.5 Percent rule

- Units: the 11 sub-steps k = 0…10 for part runs; the 4 bracket lines for demo runs.
- `percent = floor(100 * k / 11)` where `k` is the index of the latest marker seen. A unit counts as complete only when a later marker has arrived; sub-steps the pipeline skipped count as resolved because the pipeline has passed them.
- Before the first marker `percent` is `null`: the ring is indeterminate and shows no number.
- The value is capped at 99 until the SSE `done` event. It becomes 100 only when the run is done, not cancelled, and exit is 0 or 8.
- On failure or cancel the number is removed and the ring shows the state icon. The last value is never rounded up.
- `percent` never decreases: `reduce` ignores lower indices.
- Nothing time-based feeds the percent. Elapsed time is displayed separately as a clock.
- Batch: the ring follows the selected part. The aggregate is text only: "N of M parts complete" from `batch.results`.

### 6.6 Monitor, finalize and reconnect (`features/run.js`)

Launch (`run/launch`): guard `if (selectors.isRunning(state)) return`. Disable the button before the request is sent. Set `run.state = 'queued'`, POST, then on `{id}` store `mca.activeRun = {id, kind, session, part, startedAt: Date.now()}` and call `monitor(id)`.

`monitor(id)`:

1. `received = 0`. Open `EventSource`. On each message: `received++`; if `received <= run.lines.length` drop it (this is a replay after an automatic reconnect), otherwise dispatch `run/line`.
2. On `error`: reset `received = 0` and let the browser reconnect; the server replays from index 0 and step 1 removes duplicates.
3. On `done`: close the source.
4. Poll `runOutputs(id)` every 1200 ms. Update `outputs.payload` only when `outputs.ctx` is the run's part. When `done` is true, stop and call `finalizeRun`.

`finalizeRun(id, d)` runs once per id (guard with a `finalized` set): fetch the summary CSV, call `stages.finalize`, set `run.state` and verdict, refresh `listParts`, `runHistory` and `partOutputs`, remove `mca.activeRun`, announce the result, resolve the batch promise.

Reconnect on boot: if `mca.activeRun` exists, call `runOutputs(id)`.

- 404: the server no longer tracks it. Remove the key, toast "The previous run is no longer tracked by the server (it restarted). Results on disk are shown if any.", set `run` to idle.
- 200 and not done: restore `run` from the stored record with `lines = []`, call `monitor(id)`. No new run is started.
- 200 and done: restore, replay the log once through the SSE endpoint to rebuild the tracker, then `finalizeRun`.

## 7. Token migration (`static/design-tokens.css`)

Every existing token name stays defined, so `photoapp/index.html` (which uses `--well --bg --bg-raised --surface --input-bg --ink --ink-3 --ink-4 --line --line-strong --copper --copper-bright --copper-text --on-copper --ok-text --warn --sans --mono --fs-caption --fs-small --sp-1..4 --r-sm --r-md` and the `.btn` recipes) restyles without edits.

| Token | Old | New | Use |
|---|---|---|---|
| `--well` | `#0A0F16` | `#0D0E11` | canvas wells, console |
| `--bg` | `#0D131C` | `#101114` | page background |
| `--bg-raised` | `#111927` | `#191B20` | sidebar, toolbars, panel headers |
| `--surface` | `#16202F` | `#191B20` | cards, chips, secondary buttons |
| `--surface-2` | `#1B2738` | `#24262D` | hover |
| `--input-bg` | `#090E15` | `#0D0E11` | inputs |
| `--ink` | `#E7EDF5` | `#F2F2F4` | primary text |
| `--ink-2` | `#AEBACB` | `#C5C6CE` | secondary text |
| `--ink-3` | `#7D8A9E` | `#92949E` | muted text, placeholders |
| `--ink-4` | `#4E5A6C` | `#6C6E79` | disabled and decorative only (below AA for body text) |
| `--line` | `rgba(185,212,240,.10)` | `#30323A` | borders |
| `--line-soft` | `rgba(185,212,240,.06)` | `#25272E` | row rules |
| `--line-strong` | `rgba(185,212,240,.20)` | `#444752` | emphasized borders |
| `--ring` | `rgba(95,191,228,.50)` | `#9B8AFB` | focus ring (2 px, offset 2 px) |
| `--accent` (new) | | `#9B8AFB` | navigation, selection, focus, primary non-run actions |
| `--accent-bright` (new) | | `#B1A3FF` | hover |
| `--accent-text` (new) | | `#B9AEFF` | accent as text |
| `--accent-dim` (new) | | `rgba(155,138,251,.16)` | selected fills |
| `--on-accent` (new) | | `#14121F` | text on violet fills |
| `--blueprint`, `--blueprint-bright`, `--blueprint-text`, `--blueprint-dim`, `--on-blueprint` | cyan family | `var(--accent…)` aliases | legacy |
| `--copper`, `--copper-bright`, `--copper-text`, `--copper-dim`, `--on-copper` | aliases of blueprint | aliases of `--accent…` | **photoapp binds to these; keep** |
| `--steel`, `--steel-text`, `--steel-dim` | gray-blue | `#6E7385`, `#A9AEBF`, `rgba(146,148,158,.14)` | neutral informational |
| `--teal`, `--teal-text`, `--teal-dim` | aliases of steel | unchanged aliases | legacy |
| `--gold` (new) | | `#D6AF6B` | Run Pipeline button and current stage only |
| `--gold-bright` (new) | | `#E2C083` | hover |
| `--gold-dim` (new) | | `rgba(214,175,107,.16)` | current stage halo |
| `--on-gold` (new) | | `#1A1408` | text on gold |
| `--ok`, `--ok-text`, `--err`, `--err-text`, `--warn` | | unchanged | semantic status |
| `--datum`, `--datum-dim` | | unchanged | origin and datum markers |
| `--sev-*`, `--on-sev-*` | | unchanged | severity ladder |
| `--scroll-thumb`, `--scroll-thumb-hover` (new) | inline rgba | `#3A3D47`, `#4A4E5A` | scrollbars |
| `--model-mesh`, `--model-grid`, `--model-grid-2` (new) | literals in JS | `#B4B7C2`, `#30323A`, `#1E2026` | three.js scene |
| `--fs-body` | `13px` | `14px` | body |
| `--fs-control` | `14px` | `14px` | controls |
| `--fs-h2` | `16px` | `16px` | panel titles |
| `--fs-h1` (new) | | `20px` | page titles |
| `--fs-caption`, `--fs-small`, `--fs-stat`, `--fs-display` | | unchanged | |
| `--ctl-h` (new) | | `38px` | control height |
| `--r-sm`, `--r-md`, `--r-lg` | `2 / 4 / 6px` | `4 / 8 / 12px` | radii |
| `--sp-1..6` | | unchanged | spacing |
| `--centerline-v`, `--centerline-h`, `--ruler` | drafting signatures | removed (not used by photoapp) | |

Recipe changes in the same file: `.btn` height `var(--ctl-h)`; `.btn.sm` 30 px; new `.btn.gold` (`background: var(--gold); color: var(--on-gold)`), used by exactly one element; `.tab-c.active` underline uses `--accent`; scrollbar rules use the new tokens; `:focus-visible` uses `--ring` with 2 px offset.

Color discipline:

- Gold appears on `#run-btn` and on the current tracker stage. Nowhere else.
- Warning is always amber with a triangle icon and the word; verified is always green with a check icon and the word. Gold never carries a status meaning.
- No color literals in `css/*.css` or `js/*`. JS that needs a color (three.js scene, `buildMarkedCanvas`) reads it with `getComputedStyle(document.documentElement).getPropertyValue('--token')`.
- Two documented exceptions: `REGION_PALETTE` (15 marking colors, persisted in `reference_regions.json`) and the canvas drawing colors inside the unmodified `photoapp/index.html`.

## 8. Components

Icons are inline SVG from `ui/icons.js` (`McA.icons.get(name)` returns an `<svg aria-hidden="true">`). No emoji in chrome.

### 8.1 Sidebar (`ui/sidebar.js`)

```html
<nav id="sidebar" class="sidebar">
  <div class="sb-brand"><span class="sb-logo"></span>
    <div class="sb-names"><span class="sb-title">McAgent</span><span class="sb-sub">2D→3D SolidWorks Pipeline</span></div>
    <button id="sb-toggle" class="ibtn" aria-expanded="true" aria-controls="sidebar" aria-label="Collapse sidebar"></button></div>
  <button id="sb-new" class="btn sb-new">New Project</button>
  <ul class="sb-nav"><li><a class="sb-item" href="#/home" data-page="home"><svg/><span class="sb-label">Home</span></a></li>… Workspace, Projects, Pipeline Results, Recent Files</ul>
  <ul class="sb-nav sb-bottom">… Help, Settings</ul>
</nav>
```

A running pipeline shows a small spinner dot on the Workspace item (`.sb-item.is-running`).

### 8.2 Workspace header

```html
<header class="ws-head">
  <div class="ws-title"><h1 id="ws-part">No part selected</h1><span class="ws-crumb">Workspace</span>
    <button id="part-switch" class="btn secondary sm" aria-haspopup="listbox" aria-expanded="false">Switch part</button></div>
  <div class="ws-chips">
    <div class="chip" id="hdr-engine"><span class="chip-k">Engine</span><span class="chip-v"></span></div>
    <div class="chip" id="hdr-deliv"><span class="chip-k">Deliverables</span><span class="chip-v"><span class="dv" data-k="sldprt">SLDPRT</span><span class="dv" data-k="stl">STL</span><span class="dv" data-k="vba">VBA</span></span></div>
    <div class="chip" id="hdr-api"><span class="dot"></span><span class="chip-k">API</span><span class="chip-v"></span></div>
  </div>
</header>
```

`.dv.is-present` is solid; absent is muted with `title="Not produced yet"`. `#hdr-api` values: "API key set" (`.is-ok`), "No API key (demo only)" (`.is-warn`), "Server unreachable" (`.is-err`), "Checking…".

`#part-switch` opens a listbox with two groups: "This session" (`parts.list`, with view count, overview and marked chips, "ran") and "Other runs" (`history.runs` from other sessions).

### 8.3 Tracker (`ui/tracker.js`)

```html
<section class="tracker" aria-label="Pipeline progress">
  <div class="trk-run">
    <button id="run-btn" class="btn gold" aria-describedby="run-reason">Run Pipeline</button>
    <button id="cancel-btn" class="btn danger sm" hidden>Cancel</button>
    <span id="run-reason" class="trk-reason"></span></div>
  <ol class="trk-steps" role="list">
    <li class="trk-step" data-stage="extraction" data-state="pending"><span class="trk-node"></span><span class="trk-label">Extraction</span><span class="sr-only trk-state">Pending</span></li>
    … resolution, build_plan, generation, verification
  </ol>
  <div class="trk-meta"><span id="trk-stage">Stage 3 of 5</span><span id="trk-caption">Building macros…</span><span id="trk-batch" hidden>2 of 5 parts complete</span></div>
  <div class="trk-pct" id="trk-pct" role="progressbar" aria-valuemin="0" aria-valuemax="100"><svg class="ring"/><span class="trk-pct-n"></span></div>
</section>
```

`data-state` values and visuals: `pending` hollow gray; `running` gold ring with gold label and `aria-current="step"`; `succeeded` green check; `warning` amber triangle; `failed` red cross; `skipped` dashed gray with a dash icon. Each step has a tooltip (and `aria-describedby`) listing its sub-steps with their states and the detail string. Connector segments are colored by the state of the step on their left.

Indeterminate ring: remove `aria-valuenow`, set `aria-valuetext="Starting"`.

Run button label by state: idle "Run Pipeline"; running "Running…" with spinner, disabled; `#cancel-btn` shown while running (the backend supports cancel). `#run-reason` text comes from `selectors.runDisabledReason(state)`, first match:

1. `!server.reachable` → "Server unreachable."
2. running or queued → "A run is in progress."
3. `intake.items.length > 0` and no part selected → "Save the part first (Part Setup)."
4. no part selected → "Select or create a part."
5. `!server.live` → "No ANTHROPIC_API_KEY on the server. Live extraction is unavailable; use Run Demo."
6. selected part `n_views < 1` → "This part has no saved views."
7. otherwise enabled. If no saved view filename contains `front`, show a non-blocking amber note "No FRONT view found; the base profile cannot be built without it."

### 8.4 Split canvas and viewer panels

```html
<div class="canvas" id="canvas" data-max="">
  <div class="canvas-tabs" role="tablist" hidden><button role="tab" id="tab-2d">Drawing</button><button role="tab" id="tab-3d">3D Model</button></div>
  <section class="vpanel" id="vp-2d" aria-labelledby="vp-2d-title">
    <header class="vp-head"><h2 id="vp-2d-title">2D Drawing</h2><span class="vp-file" id="vp-2d-file"></span><span class="badge-c" id="vp-2d-state"></span><span class="badge-c" id="vp-2d-fmt"></span>
      <div class="vp-tools" role="toolbar" aria-label="Drawing tools">
        <button data-act="crop">Crop</button><button data-act="mark">Mark</button><button data-act="zoom-out"></button><button data-act="zoom-in"></button><button data-act="fit"></button><button data-act="max"></button><button data-act="fullscreen"></button></div></header>
    <div class="vp-body" id="ov-box" tabindex="0"><img id="ov-img" alt=""><div class="vp-empty" id="ov-empty"></div></div>
    <footer class="vp-foot" id="vp-2d-pages" hidden></footer>
  </section>
  <div class="splitter" id="splitter" role="separator" aria-orientation="vertical" aria-controls="vp-2d vp-3d" aria-valuemin="20" aria-valuemax="80" aria-valuenow="50" tabindex="0"></div>
  <section class="vpanel" id="vp-3d" aria-labelledby="vp-3d-title">
    <header class="vp-head"><h2 id="vp-3d-title">3D Model (STL)</h2><span class="badge-c" id="vp-3d-state"></span>
      <div class="vp-tools" role="toolbar" aria-label="Model tools"><button data-act="fit"></button><button data-act="reset"></button><select id="vp-3d-view" aria-label="View"><option>Isometric</option><option>Front</option><option>Top</option><option>Right</option></select><button data-act="max"></button><button data-act="fullscreen"></button></div></header>
    <div class="vp-body"><div id="stl-canvas-wrap"></div><div class="vp-empty" id="stl-empty"></div></div>
  </section>
</div>
```

2D viewer (`features/viewer2d.js`): `selectors.drawingSource(state)` keeps the old rule (`updateOverviewBox`): a draft with `previewOverride` wins, else the selected part's `overviewURL`, else the draft, else empty. `#vp-2d-file` shows `intake.originalFile.name` for a draft; for a saved part it shows the part name (gap G8). `#vp-2d-state`: "Unsaved draft" or "Saved". When `has_marked`, a small "Overview / Marked" switch appears. Multi-page drafts show a page strip in `#vp-2d-pages` (one thumbnail per `intake.items` entry labeled `page N`). Pan by drag, zoom by wheel, double-click or `0` to fit, arrow keys pan, `+` and `-` zoom. Empty state: "No drawing loaded" with an Upload drawing button.

3D viewer (`features/viewer3d.js`), carried over from the `viewer` IIFE with these changes:

- `load(url, meta)` sets `viewer3d.status = 'loading'` and keeps the current mesh on screen. The mesh is swapped only in the loader's success callback. On error the old mesh stays, status becomes `error`, and the panel shows "The model file could not be loaded" with Retry.
- `#vp-3d-state` chip: "Generated" (green, `stl_source === 'solidworks'` and fresh or no run active), "Pre-validated (CadQuery)" (amber), "Previous run" (neutral) when a run for this part is active or just finished and `stl_mtime < floor(run.startedAt / 1000)`.
- Empty state: "No model generated yet", plus the existing note that the SolidWorks STL appears after a build on a SolidWorks machine.
- Fit reruns `frame`. Reset restores the framed camera. View presets set the camera on the bounding sphere. All scene colors come from tokens.
- Demo runs load `runStlURL(id)` only when `categories.stl.present`.

Fullscreen uses the Fullscreen API on the `.vpanel`; the button is hidden when `document.fullscreenEnabled` is false. Maximize sets `canvas[data-max="2d"|"3d"]` and hides the other panel and the splitter; Escape or the same button restores.

### 8.5 Inspector (`ui/inspector.js`)

```html
<aside id="inspector" class="inspector" aria-label="Tools">
  <section class="acc" data-acc="setup"><h2><button class="acc-btn" aria-expanded="true" aria-controls="acc-setup">Part Setup</button></h2><div id="acc-setup" class="acc-body">…</div></section>
  <section class="acc" data-acc="actions">… Pipeline Actions</section>
  <section class="acc" data-acc="corrections">… Corrections</section>
  <section class="acc" data-acc="export">… Export</section>
</aside>
```

Any number of accordion sections may be open. Contents:

- **Part Setup**: Part Name (`#part-name`); "Upload drawing" (`#intake-file`, accept list from the old input); "Upload parts folder" (`#batch-folder`, `webkitdirectory`); sub-section **Views** with "Open cropper", "Mark regions", "Pull queued crops", the gallery (`#orient-gallery`: thumbnail, view type select, rotate, remove, duplicate badge), validation text (`#req-warn`), "Save part" (`#save-part-btn`, violet); sub-section **Must-meet specs** (`#part-notes`, `#save-notes-btn`). The mockup's "Parts Folder" path field is replaced by the folder upload button because the backend has no folder path concept.
- **Pipeline Actions**: "Run All Parts" (`#run-all-btn`), sample select (`#demo-sample`) and "Run Demo" (`#demo-btn`, with a Demo tag), checkbox "Force fresh extraction" (sends `no_cache=true`; off by default, helper text "Ignores the extraction cache; makes new API calls"), "Cancel" mirror. No gold here.
- **Corrections**: `#feedback-text` (2 rows; grows to 6 on focus), "Open editor" (dialog with a large textarea bound to the same draft), "Re-run with correction" (`#rerun-feedback-btn`), helper text. Disabled reasons: no part, part has no output yet, run in progress, empty text, no API key.
- **Export**: checkboxes SLDPRT, STL, VBA, each enabled only when present in `outputs.payload`; "Export Selected" downloads each matching file through `partFileURL` (SLDPRT: entries of `files.list` ending `.sldprt`; STL: the entry whose basename is `categories.stl.name` when `stl.source === 'solidworks'`; VBA: every `.vba` entry), one hidden anchor click per file, 300 ms apart; "Download all (.zip)" uses `runZipURL(run.id)` and is enabled only when `run.id` is tracked for this part; delivered folder paths (`delivered`, `delivered_downloads`) as copyable text.

### 8.6 Drawer (`ui/drawer.js`)

```html
<section id="drawer" class="drawer" data-open="false" aria-label="Pipeline Results">
  <div class="dr-resize" id="dr-resize" role="separator" aria-orientation="horizontal" aria-controls="dr-body" tabindex="0"></div>
  <header class="dr-head">
    <button id="dr-toggle" class="dr-toggle" aria-expanded="false" aria-controls="dr-body">Pipeline Results</button>
    <span class="dr-chip" id="dr-state"></span>
    <span class="dr-kv" id="dr-verdict"><span class="k">Verification</span><span class="v"></span></span>
    <span class="dr-kv" id="dr-flags"><span class="k">Engineering Flags</span><span class="v"></span></span>
    <span class="dr-kv" id="dr-runtime"><span class="k">Runtime</span><span class="v mono"></span></span>
    <div class="dr-modes" role="tablist"><button role="tab" id="dr-mode-results">Results</button><button role="tab" id="dr-mode-tools">Tools</button></div>
    <a class="btn ghost sm" id="dr-open-page" href="#/results">Open full page</a>
  </header>
  <div id="dr-body" class="dr-body" hidden>
    <div class="dr-results"><nav class="dr-secs" role="tablist"></nav><div class="dr-pane" role="tabpanel"></div></div>
    <div class="dr-tools" hidden></div>
  </div>
</section>
```

Header height 48 px. `#dr-state` shows the run state (4.4) with its icon. `#dr-verdict` shows the verdict (4.4). `#dr-flags` shows counts from `categories.review.items` by severity ("1 critical, 2 high" or "None"). `#dr-runtime` is `finished - started` for a finished tracked run, a live clock while running, and "Not recorded" for history runs (gap G6). The Tools tab exists only below 1440 px; in that mode `#inspector` is moved (same node, `appendChild`) into `.dr-tools`, so there is one inspector DOM and one set of ids.

The Results mode renders the same registry sections as the Results page through `ui/results.js` with `{condensed: true}`.

### 8.7 Results page and sections (`ui/results.js`, `pages/resultsPage.js`)

```html
<header class="res-head"><nav class="crumb" aria-label="Breadcrumb"><a href="#/projects">Projects</a> / <span id="res-part"></span> / <span id="res-sec"></span></nav>
  <label for="res-run">Run</label><select id="res-run"></select><span class="badge-c" id="res-demo" hidden>Demo</span></header>
<div class="res-body"><nav class="res-nav" aria-label="Result sections">
    <div class="res-group"><h3>Overview</h3><a data-sec="overview"></a></div> … five groups
  </nav><article class="res-pane" id="res-pane" tabindex="-1"></article></div>
```

Every section is wrapped by `results.frame(section, payload)`:

```html
<section class="rsec" data-sec="extraction" data-state="present">
  <header class="rsec-head"><h2></h2><span class="rsec-status"></span><span class="rsec-src mono"></span>
    <div class="rsec-tools"><!-- search, tree/raw toggle, copy, download, as declared by the registry --></div></header>
  <div class="rsec-body"></div>
</section>
```

`data-state`: `loading` (skeleton lines), `absent` (designed empty state with the registry's reason text), `error` (message plus Retry), `present`. `rsec-src` shows the source file name or endpoint.

Shared renderers: `renderJsonTree` (`.jt`, `.jt-node`, `.jt-key`, `.jt-val`, `<button aria-expanded>` per container, search highlights with `<mark>`), `renderCode` (`.code` with line numbers), `renderTable` (`.tbl`), `renderFlags` (`.flag-item.sev-<SEVERITY>` using `.badge-sev`), `renderConsole` (`.console-c`, windowed to the last 5,000 lines with "Show earlier").

### 8.8 Pages

- **Home** (`pages/home.js`): `<h1>What would you like to create?</h1>`; dropzone `#home-drop` (a `<label>` wrapping a file input, drag and drop, keyboard activatable) with the format line "PDF, JPG, PNG, WEBP, BMP, TIFF, DWG, DXF, eDrawings (EDRW, EPRT, EASM)"; one violet button `#home-create` "Create 3D Model", disabled until a file is loaded, which opens `#/workspace` with Part Setup › Views expanded and never starts a run; small links "Open sample / Run demo" (opens a dialog with the sample list, a Demo label, and the note "Uses a saved extraction; no API call"), "Upload parts folder", "Recent projects" (top 5 of `history.runs`).
- **Projects** (`pages/projects.js`): "Parts in this session" grid (`.pcard`: thumbnail, name, views, overview and marked chips, status chip from `has_output` and `batch.results`; actions Open, Run, Download outputs when present); "Upload parts folder"; "Run All Parts"; "All runs" table from `history.runs` (part, timestamp, presence ticks from `present`, actions Open, Results, Re-run). Overflow menu: "Clear all models".
- **Recent Files** (`pages/recent.js`): `history.runs` newest first with `timestamp`; actions Open in Workspace, Open results, Download STL when `present.stl`.
- **Help**: workflow, supported formats, keyboard shortcuts, tracker legend, exit code table, where outputs go (`UI_Output/<part>/`, `~/Downloads/SolidWorksModel_Parts/<part>/`), list of backend-only endpoints.
- **Settings**: Server (reachable, API key state, engine, samples count), Session (id, copy), Layout ("Reset layout" clears the `mca.ui.*` keys), Data danger zone ("Clear all models").

### 8.9 Dialog and toast

`McA.dialog.open({title, body, actions, danger})` renders `<div class="dlg-backdrop"><div class="dlg" role="dialog" aria-modal="true" aria-labelledby>`; traps focus, closes on Escape, returns focus to the opener, resolves a promise with the chosen action. It replaces every `confirm()` call. `McA.toast.show(text, kind)` appends to `#toast-root` and mirrors the text into `#status-live` (or `#alert-live` for errors).

## 9. Splitter, drawer and sidebar behavior

### 9.1 Splitter

- Pointer drag on `#splitter` sets `ui.splitRatio` (left share), clamped 0.20 to 0.80; applied as `grid-template-columns: <r>fr 6px <1-r>fr` on `#canvas`.
- Keyboard: Left and Right move 2%; Shift moves 10%; Home 20%; End 80%; Enter or double-click resets to 50%.
- `aria-valuenow` mirrors the percent. The 3D renderer resizes through its existing `ResizeObserver`.

### 9.2 Drawer

- Collapsed: header only (48 px). Open: `ui.drawerHeight` px, default 320, clamped 160 to 70% of the viewport height.
- `#dr-resize`: pointer drag; Up and Down move 16 px; Shift 64 px; Enter toggles between default and maximum.
- `#dr-toggle` flips `ui.drawerOpen` and `aria-expanded`. The drawer opens automatically once when a run ends with state `failed` or `succeeded_with_warnings`, and when overview conflicts arrive during a live run.

### 9.3 Sidebar

- Expanded 240 px; collapsed 64 px icon rail where labels are visually hidden and each item gets a tooltip and keeps its accessible name.
- 1100 to 1439 px: collapsed by default; expanding overlays the content (no reflow) and closes on Escape or outside click.
- Below 800 px: off-canvas, opened by a menu button in the page header.

### 9.4 Inspector

Docked at 300 px (max 310) at 1440 px and wider; `ui.inspectorCollapsed` hides it and shows a slim reopen tab. Below 1440 px it is not docked and lives in the drawer's Tools mode.

### 9.5 Persistence keys (`core/persist.js`, all `localStorage`)

| Key | Value |
|---|---|
| `mca.session` | parts session id |
| `mca.activeRun` | `{id, kind, session, part, startedAt}` |
| `mca.batch` | `{queue, index, results}` (used only to offer a resume, never to auto-run) |
| `mca.selected` | `{session, part}` |
| `mca.ui.sidebar` | `expanded` or `collapsed` (user choice at 1440 px and wider) |
| `mca.ui.inspector` | `{collapsed, open: {setup, actions, corrections, export}}` |
| `mca.ui.drawer` | `{open, height, section}` |
| `mca.ui.split` | number 0.20 to 0.80 |
| `mca.ui.results` | last section id |
| `mca.corr.<session>.<part>` | correction draft text |

All reads go through `persist.get(key, fallback)` with try/catch and schema checks; invalid values fall back. No secrets and no file contents are stored.

## 10. Cropper embedding (focus overlay)

### 10.1 Structure

```html
<div id="focus" class="focus" role="dialog" aria-modal="true" aria-labelledby="focus-title" hidden>
  <header class="focus-head"><h2 id="focus-title">Crop views</h2><span class="focus-file" id="focus-file"></span>
    <div class="seg-c" role="tablist"><button id="crop-mode-crop" role="tab">Crop views</button><button id="crop-mode-mark" role="tab">Mark regions</button></div>
    <span class="focus-hint" id="crop-mode-hint"></span><span class="focus-save" id="mark-save-state"></span>
    <button id="pull-crops-btn" class="btn">Pull queued crops</button><button id="focus-close" class="btn secondary">Done</button></header>
  <div id="crop-view" class="focus-body"><iframe id="photoapp" src="/photoapp/" title="Drawing cropper"></iframe></div>
  <div id="mark-view" class="focus-body" hidden><!-- .mark-bar, .mark-split, #mk-box, #mk-img, #ov-mark-layer, .mark-side: moved verbatim from the old Sheet 1 --></div>
</div>
```

`.focus { position: fixed; inset: 0; z-index: 50; background: var(--bg); display: flex; flex-direction: column; }`

### 10.2 Rules

- The iframe exists from boot and is never removed or reloaded; the overlay is only shown and hidden. Queued crops (`savedCrops` inside the iframe) survive closing the overlay and page navigation.
- `photoapp/index.html` is not edited. Communication stays exactly as in `bridge.js`:
  - `MTIBridge.hookCadIntake(iframe)` at boot (widens the accept list, wraps `loadFile`, posts `cad-open` and `src-open`).
  - `MTIBridge.collect(iframe)` for "Pull queued crops" → `{stem, source, crops: [{name, dataURL}]}` → `intake/add` with `guessOrientation(name)`.
  - `MTIBridge.sendImage(iframe, dataURL, name)` after a CAD conversion, with `intake.expectEcho` set to drop the echo.
  - One `window.addEventListener('message')` in `features/cropper.js` handling `cad-open` and `src-open`; it checks `ev.source === iframe.contentWindow` before acting.
- Pulling crops appends to `intake.items`. It never clears existing items.
- A new upload while a draft exists opens a dialog: "Add to current draft", "Start a new draft", "Cancel". Saved parts are not affected by uploads.
- Saving with a name that matches an existing part shows: "Saving replaces the saved views of <part>. Its outputs are kept." (this is what `POST /api/parts` does).
- Opening: "Crop" in the 2D toolbar or Part Setup → `ui.focusMode = 'crop'`; "Mark" → `'mark'` (calls `updateMarkImage()` and `syncMarkTool()`). If the cropper has no image and a draft `originalFile` exists (PDF or image), the overlay offers "Load this drawing into the cropper"; it does not load it silently.
- Closing ("Done", or Escape per 10.4) hides the overlay and returns focus to the opener. If "Add to Part Setup" was used, the inspector's Views section is expanded.

### 10.3 Feature coverage

Crop handles, per-view crops, preset and custom names, the queue, feature tally and ZIP are inside the cropper. Rotation (per image, 90° steps) and view types are in Part Setup › Views. Origin and datums are in Mark regions. Multi-page PDFs: the upload path rasterizes up to 12 pages into the draft; the cropper itself opens page 1 (gap G9).

### 10.4 Keyboard inside the overlay

Focus is trapped among the header controls, the iframe and the markup pane. Escape closes the overlay when focus is in the parent document. When focus is inside the iframe, Escape belongs to the cropper (clear selection); a same-origin listener added by the parent on `iframe.contentDocument` closes the overlay on Shift+Escape. Both are listed in Help.

## 11. Results registry (`logic/registry.js`)

`registry.sections` is the single ordered list used by the Results page, the drawer and the tests. Each entry: `{id, group, label, source(payload), status(payload), tools, emptyText, render}`. Every `categories` key maps to exactly one section; `registry.coverage()` returns the mapping and a unit test asserts no key is unmapped or mapped twice.

Download URLs: part context → `partFileURL(session, part, rel)`; demo context → `runDownloadURL(id, rel)`.

| Section id | Group | Payload source | Endpoint | Rendering | Tools | Empty text |
|---|---|---|---|---|---|---|
| `overview` | Overview | computed: run state, verdict, summary CSV row, `must_meet`, `review.items`, `overview_analysis.data.cross_view_conflicts`, `stl`, `sldprt`, `macros` | outputs endpoint plus `…/file/multiview_summary.csv` | Three blocks: "Did it build?" (SLDPRT, STL and source, macro count), "Does it match?" (verdict, must-meet pass and fail counts, summary scores as reported), "What needs attention?" (critical and high flags, failed constraints, conflicts; each links to its section) | none | "Run the pipeline to see a summary." |
| `extraction` | Extraction | `categories.extraction` | outputs | JSON tree (lossless) or raw text | search, tree/raw, copy, download | "No extraction yet." |
| `resolved` | Extraction | `categories.resolved` | outputs | JSON tree or raw | search, tree/raw, copy, download | "No resolved extraction. Resolution did not run or the part was not run." |
| `overview_analysis` | Extraction | `categories.overview_analysis.data`, plus `markup` regions of the part | outputs, `GET …/regions` | Carried over from `renderOvanPanel`: shape, views detected, conflicts, correspondences, global notes, symmetry, marked regions | raw, copy | "No overview analysis for this run." |
| `build_plan` | Build & Verification | `categories.build_plan` | outputs | Expandable operation list (one `<details>` per step of the plan's step array, showing each step's fields as written); raw JSON | search, list/raw, copy, download | "No build plan. The part was blocked before planning or has not run." |
| `verification` | Build & Verification | `categories.verification` (text), `categories.must_meet` | outputs | Verdict line; must-meet checks table (`id`, `status`, `required`, `measured`, `detail`) with the stage label; `failed[]` list; report text | copy, download | "No verification report yet." |
| `flags` | Build & Verification | `categories.review` | outputs | Counts by severity; filter chips CRITICAL, HIGH, MEDIUM, LOW; ranked items (`severity, id, source, status?, what, decision, why, affects`); groups "Overview Verification" (`source === 'overview'`) and "Human-Specified Requirements" (`source === 'requirement'`); raw text toggle (`review.text`); disabled "Save all to Learning Loop" | filter, raw, copy | "No assumptions or manual steps were recorded." when `present` with zero items; "No engineering review yet." otherwise |
| `model_check` | Build & Verification | `categories.model_check` | outputs | Report text | copy, download | "Model check requires Windows and SolidWorks; it was not produced for this run." |
| `macros` | Automation & Files | `categories.macros.files[]` | outputs | File tabs, code view with line numbers | copy, download (per file) | "No macros generated yet." |
| `files` | Automation & Files | `categories.files.list[]`, `sldprt`, `stl`, `delivered`, `delivered_downloads` (demo: `runFiles(id)`) | outputs; download endpoints | Deliverables rows first (SLDPRT, STL with source, VBA count), then the table (path, size, download link), then delivered folders | download per row, zip when available | "No output files yet." |
| `cost` | Diagnostics | `categories.usage` | outputs | Cards: part total (`total_cost_usd`, labeled "all ledger entries for this part"), session total when present, last call tokens and model; table of `rows[]` (`timestamp, stage, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, api_calls, cache_hit, cost_usd`); ledger text. Tokens are labeled "Measured"; cost is labeled "Estimated by the backend price table", and "Estimated (fallback rate)" when `model_priced` is false | raw, copy | "No token usage recorded. Demo runs make no API calls." |
| `console` | Diagnostics | live `run.lines`, else `categories.console.text` | SSE; outputs | Monospace transcript | filter (all, stage, warnings, errors), search, copy, auto-scroll toggle, download when `ui_console.log` exists | "No console output for this run." |
| `events` | Diagnostics | `logparse.events(lines)` over the same lines | same as console | Table: index, kind (`stage`, `spec`, `preval`, `mm`, `overview`, `delivered`, `cancel`, `error`, `exit`), text | filter by kind, copy | "No events for this run." |

Rules for all sections:

- Text is inserted with `textContent` or through `util.esc`. Payload strings never reach `innerHTML` unescaped. Class names built from payload values (`sev-…`, `st-…`) pass through a whitelist.
- Raw views show `text` exactly as received. The JSON tree is built by `jsontree.parse(text)`, which keeps each number's original lexeme; nothing is reformatted or rounded. The old `prettyJSON` (parse then stringify) is not used.
- When `text` is `null` (over 400 KB): "Too large to preview. Download the file."
- Copy uses `navigator.clipboard.writeText` with a hidden-textarea fallback, and announces "Copied".
- Demo context: every section shows the Demo badge; demo data is kept in `outputs` under `ctx.kind === 'run'` and is never written into `parts`, `history`, Projects or Recent.

## 12. Batch

- **Upload parts folder**: same request as today (`paths` = `webkitRelativePath`, `files`). The result toast and a Projects banner show `added.length` parts, `n_files`, `n_skipped`. Grouping is the server's (subfolder = part).
- **Run All Parts**: dialog "Run N parts? Each part makes paid API calls and runs one at a time." listing the parts with `n_views >= 1`. On confirm: `batch = {active: true, queue, index: 0, results: {}}`, then for each part: `parts/select`, `run/launch`, await finalize, record `results[part] = {state, exit, error}`. A launch error or a cancel stops the loop (`batch/stop`). A failed part does not stop it (same as today, where only a cancel or a launch failure breaks the loop).
- **Tracker**: follows the selected part. `#trk-batch` shows "N of M parts complete". Selecting another part during a batch shows that part's last known results and a note "Batch is running <current part>".
- **Per-part status** on Projects cards: queued, running, succeeded, review flags, failed, cancelled (from `batch.results`), else "ran" or "not run" from `has_output`.
- **Refresh during a batch**: the current run reconnects (6.6). The remaining queue is in `mca.batch`; the UI offers "Resume batch (K parts left)" and never resumes on its own.

## 13. Responsive and accessibility

### 13.1 Breakpoints

| Width | Layout |
|---|---|
| ≥ 1440 px | sidebar expanded (240), inspector docked (300), split canvas, drawer |
| 1100 to 1439 px | sidebar collapsed to the rail, inspector in the drawer's Tools mode, split canvas |
| < 1100 px | split replaced by tabs Drawing and 3D (`.canvas-tabs`), tracker labels shorten to icons with the current stage named in `#trk-stage`, header chips wrap under the title |
| < 800 px | sidebar off-canvas, drawer opens to 60% height, Results nav becomes a select |

App grid: `grid-template-columns: var(--sb-w) minmax(0,1fr)`; Workspace: rows `auto auto minmax(0,1fr) auto` (header, tracker, canvas plus inspector, drawer). Minimum canvas height 280 px; below that the page scrolls. Test at 1920×1080, 1440×900, 1366×768, 1024×768 and 390×844.

Conflict noted in the brief: one line hides the inspector below 1100 px, another moves it to the drawer between 1100 and 1439 px. Resolution: docked only at 1440 px and wider; in the drawer below that.

### 13.2 Accessibility plan

- Landmarks: `nav` (sidebar), `main`, `aside` (inspector), labeled `section`s. One `h1` per page; panel titles are `h2`.
- Disclosure controls (sidebar toggle, accordion buttons, drawer toggle, part switcher, tree nodes) carry `aria-expanded` and `aria-controls`.
- Tabs (canvas tabs, drawer modes and sections, macro files, focus modes) follow the tablist pattern with roving `tabindex` and arrow keys.
- Splitter and drawer resizer are `role="separator"` with value attributes and the key bindings in section 9.
- Tracker: ordered list; each step has visible text plus a screen-reader state word; the current step has `aria-current="step"`. State is never conveyed by color alone (icon and text accompany it).
- Live regions: `#status-live` announces stage changes ("Stage 3 of 5, Build Plan, running"), run end, saves; `#alert-live` announces failures. Announcements are throttled to one per stage change, not per log line.
- Dialogs and the focus overlay trap focus, close on Escape (10.4), and return focus to the opener.
- Disabled controls that need an explanation use `aria-disabled="true"` plus `aria-describedby` pointing at visible reason text, so the reason is reachable by keyboard. Native `disabled` is used only when the reason is shown next to the control.
- Focus ring: 2 px `--ring`, 2 px offset, on every interactive element.
- Contrast: body text `--ink` on `--bg` and `--bg-raised`; muted text `--ink-3` (at least 4.5:1 on `--bg-raised`); `--ink-4` only for disabled and decorative content; `--on-gold` on `--gold` and `--on-accent` on `--accent` both exceed 7:1. Verify with the e2e axe scan.
- Target sizes: controls 36 to 40 px high; icon buttons 32 px with 4 px spacing.
- Reduced motion: the existing `prefers-reduced-motion` rule stays; the tracker spinner becomes a static ring with the text "Running".
- Canvas alternatives: the 2D image has `alt` "Drawing of <part>"; the 3D canvas has `role="img"` and a label that includes the model state.

## 14. Test plan

### 14.1 Unit tests (node, no dependencies)

Run: `node --test tests/unit/unit/`. Tests `require` the files in `static/js/logic/`.

| File | Cases |
|---|---|
| `stages.test.js` | longest-prefix match (`Verifying must-meet constraints` vs `Verifying`); markers with a part-name suffix (`Extracting 117C`); out-of-order and duplicate markers do not move backward; full transcript replay gives the same track as a single pass; skipped sub-steps (no overview, no specs, no SolidWorks); percent is `null` before the first marker, `floor(100*k/11)` after, 99 cap, 100 only for exit 0 or 8, removed on failure and cancel; finalize rules 1 to 7 with fixture payloads (fresh SolidWorks STL, stale STL, pre-validation only, BLOCKED, ERROR, must-meet failure); demo transcript maps to Extraction, Resolution, Build Plan and skips the rest |
| `runstate.test.js` | every exit code in the table; cancelled wins; exit 8 with `BLOCKED` or `ERROR` is failed; all verdict rows, including `READY` without a built model |
| `selectors.test.js` | `runDisabledReason` order; deliverables chips; `drawingSource` precedence; `intakeValidation` (front required, one more orthographic view, duplicates, name) |
| `logparse.test.js` | `[STAGE]`, `[SPEC]`, `[PREVAL]`, `[MM]`, `[OVERVIEW]`, `[delivered outputs to]`, `[cancel requested by user]`, `[launch error]`, exit line |
| `jsontree.test.js` | number lexemes preserved (`1.50`, `1e-7`, 20-digit integers); nested structures; escapes; invalid JSON returns an error node and the raw view still works |
| `csv.test.js` | quoted fields with commas and newlines; header mapping; empty file |
| `registry.test.js` | every `categories` key maps to exactly one section; five groups in the required order; `resolveFile` finds nested paths |
| `util.test.js` | `esc` neutralizes `<script>` and attribute breaks; `fmtBytes`; `fmtElapsed` |

Fixtures: real transcripts copied from `ui_console.log` of a demo run and of a part run (when one is available), plus hand-trimmed variants for the skip and failure cases. Fixture payloads are captured from `GET /api/parts/{s}/{p}/outputs`.

### 14.2 End-to-end smoke (Playwright against the running server)

Setup: `cd FINAL_UI/tests/e2e && npm init -y && npm i -D @playwright/test @axe-core/playwright && npx playwright install chromium`. Server: `cd pipeline_app/webapp && PORT=8191 ./run.sh`. `baseURL: http://127.0.0.1:8191`. The suite never clicks Run Pipeline when `/api/status` reports `live: true`, so it cannot spend API budget.

| # | Scenario | Assertions |
|---|---|---|
| 1 | Boot | no console errors; sidebar items present; Home heading visible; exactly one `.btn.gold` exists in the document |
| 2 | Routing | each hash shows its page and sets `aria-current`; unknown hash goes Home |
| 3 | Status honesty | header API chip text matches `/api/status`; the string "Connected" does not appear; engine chip is not a hard-coded name when the backend reports none |
| 4 | Upload and save a part | upload two generated PNGs, assign Front and Top, name, Save; the part appears in the part switcher and Projects; refresh; it is still listed (session reuse) |
| 5 | Run button gating | with no part: disabled and the reason text is visible; with `live: false`: reason mentions the API key |
| 6 | Demo run | start a demo from Home; tracker reaches Build Plan; Generation and Verification show skipped; percent ends at 100; Results sections Extraction JSON, Build Plan, VBA Macros, Files are present; Demo badge visible; nothing added to Recent |
| 7 | Refresh during a demo run | reload mid-run; the tracker reattaches; `POST /api/demo` is called once in total (request count) |
| 8 | Cancel | start a demo, cancel; run state Cancelled; no percent shown; no success chip |
| 9 | Splitter and drawer | keyboard resize changes `aria-valuenow`; values persist after reload; drawer `aria-expanded` toggles |
| 10 | Focus overlay | opens from the 2D toolbar; iframe loaded; Done returns focus to the opener; the iframe element is the same node after reopening |
| 11 | Markup persistence | draw one region on a saved part; `POST …/regions` returns `saved: 1`; reload; the region is drawn again |
| 12 | Batch upload | upload a fixture folder with two part subfolders; both listed; Run All Parts opens the confirm dialog (then cancel it) |
| 13 | XSS | save a part note and a region value containing `<img src=x onerror=…>`; no dialog fires; text is shown literally |
| 14 | Clear all models | dialog shows the count; cancel leaves history intact |
| 15 | Responsive | at 1366×768 the inspector is in the drawer Tools mode; at 1024×768 the canvas shows tabs; screenshots at 1920×1080, 1440×900, 1366×768, 390×844 |
| 16 | Accessibility | axe scan on Home, Workspace, Results with no serious or critical violations |

A live part run (real extraction) is a manual check on a machine with an API key and SolidWorks; record its result in `docs/PROGRESS.md`.

## 15. Build sequence

Each step ends in a working app and a local commit. Keep `index.html` loading at every step.

| # | Step | Exit criteria |
|---|---|---|
| 1 | Save the current `index.html` as `index.legacy.html` (reference only, not served). Retoken `design-tokens.css` per section 7. | Old UI still works with the new palette; the cropper renders in the new palette; no missing-variable warnings |
| 2 | Add `core/util.js`, `core/store.js`, `core/persist.js`, `core/api.js` and the `logic/*` files with their unit tests. | `node --test` passes |
| 3 | New `index.html` shell, `base.css`, `shell.css`, sidebar, router, empty pages, dialog, toast. | All seven routes navigate; sidebar collapse persists; one `h1` per page |
| 4 | Boot sequence in `main.js`: status, session reuse, parts, history, selection restore. Workspace header chips. | Header chips show backend values; refresh keeps the session and selection |
| 5 | Workspace layout: tracker (static), split canvas, splitter, maximize, narrow tabs, inspector accordion, drawer shell with resize. | Layout matches the mockup at 1440×900; keys and persistence in section 9 work |
| 6 | `viewer2d.js` and `viewer3d.js` wired to the selected part. | Drawing and STL of a history run load; empty and error states render; model swaps only after load |
| 7 | `intake.js`: upload (PDF, image, CAD with sheet picker), gallery, validation, save, notes; Home dropzone. | A part can be created from Home and from the inspector; e2e 4 passes |
| 8 | `cropper.js` and `markup.js`: focus overlay with both modes, pull crops, region autosave, marked view. | Every row of inventory sections 4 and 5 works; e2e 10 and 11 pass |
| 9 | `run.js`: launch, monitor, cancel, finalize, reconnect; tracker live; run button reasons. | Demo run drives the tracker; e2e 5 to 8 pass |
| 10 | `ui/results.js` and the Results page with all registry sections; drawer Results mode. | All 13 sections render present, absent, loading and error states from fixtures; inventory section 9 fully covered |
| 11 | Corrections and Export cards; Force fresh extraction. | Re-run sends `feedback` and `no_cache`; the draft survives a failed launch; exports download real files only |
| 12 | Batch: upload folder, Run All Parts with confirm, aggregate, resume offer. | e2e 12 passes; batch loop matches the old stop conditions |
| 13 | Projects, Recent, Help, Settings; Clear all models. | Lists come only from `/api/parts` and `/api/run-history`; e2e 14 passes |
| 14 | Responsive pass and accessibility pass. | e2e 15 and 16 pass; keyboard-only walkthrough of Workspace completed |
| 15 | Optional backend delta B1; hardening (XSS test, stale-response tests, no color literals check: `grep -nE "#[0-9a-fA-F]{3,6}|rgba?\(" static/css static/js` returns only the documented exceptions). | e2e 3 and 13 pass; grep is clean |
| 16 | Remove `index.legacy.html`; walk `FEATURE_INVENTORY.md` row by row; write `docs/PROGRESS.md` and the final report. | Every inventory row checked off; all tests pass |

## 16. Honesty rules for implementers

- A control that cannot work is rendered disabled with a visible reason, or not rendered. It is never a no-op.
- No value is invented: no placeholder part names, no default percent, no "Connected", no success state without the conditions in 4.4 and 6.3.
- The 3D panel shows only bytes served by a `model.stl` endpoint.
- Demo data shows a Demo badge and stays out of Projects, Recent and the part switcher.
- The engine name is never written in source.

## 17. Integration gaps

Each gap is shown in the UI as stated and listed in the final report.

| Id | Missing backend capability | UI behavior |
|---|---|---|
| G1 | `/api/status` does not expose the model or provider | Engine chip uses B1 when present, else the model in the part's last usage row, else "Not reported" |
| G2 | No connectivity or key-validity check; `live` only means the key is set | Chip says "API key set"; never "Connected" |
| G3 | No endpoint to save engineering flags to a learning loop (the pipeline only appends `lessons_learned.jsonl` on its own during must-meet handling) | "Save all to Learning Loop" is disabled with "Not available: the server has no learning-loop endpoint"; `lessons_learned.jsonl` is downloadable from Files when it exists |
| G4 | No list of active runs; `RUNS` is in memory and lost on restart | Reconnect only from the browser that started the run; after a restart the UI says the run is no longer tracked |
| G5 | No structured progress or stage API; no progress inside a sub-step | Tracker parses `[STAGE]` lines; indeterminate ring where no unit boundary exists |
| G6 | Run history has no duration, exit code or verdict per run, and one output folder per part (no per-run revisions) | History rows show timestamp and artifact presence only; runtime "Not recorded"; a re-run replaces the previous outputs, and the UI says so before a re-run |
| G7 | No endpoint that validates required views before a run | The save rule (Front plus one orthographic view) stays client-side as inherited; the Run button only enforces what `run_part` enforces (at least one saved image) and warns when no front view is found |
| G8 | The original upload's file name and file are not exposed for saved parts (`.originals/` is not served) | 2D panel shows the part name and `source_format`; no "download original" control |
| G9 | The cropper renders only page 1 of a PDF and cannot be changed without editing the vendored file | Other pages are available through Upload drawing (up to 12 pages); stated in Help |
| G10 | No delete, rename or duplicate for a part; no listing of parts in other sessions unless they have outputs | Those controls are not rendered; Projects explains that unrun parts from earlier sessions are not listed |
| G11 | No server-side batch or queue | Run All Parts is a client loop; closing the tab stops the queue after the current part; a resume is offered |
| G12 | No server-side guard against concurrent runs | The client blocks a second launch; a run started from another tab is not detected (see G4) |
| G13 | No zip endpoint for a part's outputs; `/api/runs/{id}/zip` works only for a run tracked in the current server lifetime | "Download all (.zip)" is enabled only then; otherwise disabled with the reason, and per-file downloads remain |
| G14 | "Clear all models" is all-or-nothing | One global action with a counted confirmation; no per-part delete |
| G15 | Cost is computed from a price table inside `pipeline/usage_log.py`; unpriced models use a fallback rate | Cost labeled "Estimated"; "fallback rate" shown when `model_priced` is false; the UI holds no prices |
| G16 | Demo runs perform no generation or verification and have no drawing image | Those stages show skipped; the 2D panel shows "Demo runs have no drawing" |
| G17 | TIFF images may not decode in the browser | Load failure shows an error state suggesting PNG or PDF |

## 18. Decisions log

| # | Decision | Reason |
|---|---|---|
| D1 | Classic scripts under one `window.McA` namespace, not ES modules | Module scripts need a strict JS MIME type; Windows registry MIME mappings can break that. Also keeps the no-build rule |
| D2 | New files live under the existing `/static` mount; no new FastAPI routes | Smallest and safest backend surface |
| D3 | Pure logic in `logic/*` with a UMD-style wrapper | Testable with `node --test`, no dependencies |
| D4 | All pages stay in the DOM; routing toggles `hidden` | The cropper iframe, WebGL context and run monitor survive navigation |
| D5 | One store, action dispatch, selector subscriptions | The drawer and the Results page render from the same state |
| D6 | The parts session id is reused across refreshes | The old UI created a session per load and lost the parts list on refresh |
| D7 | Selection is a `{session, part}` pair | History runs from other sessions can be opened and re-run through the same endpoints |
| D8 | Stage state during a run comes from log markers only | The output folder still holds the previous run's files during a re-run |
| D9 | `Verifying` (pre-build data gate) belongs to Build Plan; Verification holds only post-generation checks | Keeps "completed" and "verified" distinct |
| D10 | Percent is `floor(100*k/11)` over the 11 real sub-steps; `null` before the first marker | Real work units only; removes the old 2% start and the `[n/m]` fraction that could exceed 1 in views mode |
| D11 | Run state `succeeded_with_warnings` is tied to exit 8 with a `NOT READY` row; `BLOCKED` and `ERROR` rows are failures | Exit 8 alone does not distinguish them; the summary CSV does |
| D12 | Verdict "Passed" requires a SolidWorks STL from this run; READY without a build is "Checks passed, model not built" | A READY status on a machine without SolidWorks was never compared to a model |
| D13 | The gold Run Pipeline button sits in the tracker bar; the inspector holds only secondary actions | The inspector is not visible below 1440 px, and only one gold control may exist |
| D14 | The inspector is docked at 1440 px and wider, and moves into the drawer's Tools mode below that | Resolves the two breakpoint statements in the brief |
| D15 | `photoapp/index.html` and `bridge.js` are not edited | Preserves cropping behavior; the retokened aliases restyle the cropper |
| D16 | Markup (Mark regions) shares the focus overlay with the cropper | It was the second mode of the old Sheet 1 and needs the full screen |
| D17 | The mockup's "Parts Folder" path field becomes an "Upload parts folder" button | The backend accepts uploaded files, not a server path |
| D18 | "Overview Analysis" is added as a third subsection under Extraction | It is an existing output that the brief's list does not name; it must not be dropped |
| D19 | Must-meet results are part of the Verification section; Model Check stays separate | Each output has one home; the brief requires Model Check to be distinct |
| D20 | Run Log / Events is a structured view of the same console lines | The backend has no separate event stream |
| D21 | The JSON tree uses a lossless parser | "No rounding": `JSON.parse` followed by `stringify` rewrites number text |
| D22 | Export Selected downloads existing files one by one through the file endpoint | No export endpoint exists; nothing is fabricated |
| D23 | "Force fresh extraction" exposes the existing `no_cache` form field | Real capability; off by default because it costs API calls |
| D24 | `confirm()` calls become accessible dialogs | Focus management and consistent styling |
| D25 | `REGION_PALETTE` and the cropper's canvas colors are the only color literals outside the token file | The palette is persisted data; the cropper file is treated as vendored |
| D26 | Radii move to 4, 8, 12 px and body text to 14 px | Matches the mockup and the brief's control sizes |
| D27 | `/api/run` and `/api/run-views` stay unused | The old UI did not use them; the part flow supersedes them; they remain available on the backend |
| D28 | The e2e suite never starts a live run | Protects the API budget; live runs are a recorded manual check |


## Decisions: FINAL_UI packaging (addendum)

- D-F1 Repo selection: `--repo`/`MCAGENT_REPO`, else auto-detect (walk up from FINAL_UI, test each directory and its direct children for `main.py` + `pipeline/`); several matches or none is an error, never a guess. `app.py` re-validates and refuses to start otherwise.
- D-F2 Data under `MCAGENT_DATA` (default `FINAL_UI/data/`, gitignored), including `UI_Output/`.
- D-F3 `MCAGENT_PYTHON` reuses an interpreter and skips venv and installs; otherwise `.venv` is created with python3.12/3.11/3.10 and installs are stamped by a checksum of the two requirements files.
- D-F4 CLI contract the repo must satisfy: `main.py --drawing|--from-json|--views-folder ... --output ... --no-export`.
