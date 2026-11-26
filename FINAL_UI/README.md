# McAgent UI (FINAL_UI)

Vanilla HTML/CSS/JS front end plus a FastAPI server for the MTI 2D to 3D SolidWorks pipeline. It runs any pipeline repo unchanged: a folder that has `main.py` and a `pipeline/` package.

## Run (one command)

```bash
./run.sh --repo /path/to/2D-3D-CAD-Test-Generation      # http://127.0.0.1:8200
PORT=8210 ./run.sh --repo /path/to/repo
```
Windows: `.\run.ps1 -Repo C:\path\repo` or double-click `run.bat`. Needs Python 3.10-3.12 (a `.venv` is created here and the repo's `requirements.txt` plus `server/requirements-ui.txt` are installed). `MCAGENT_PYTHON=<python>` reuses an existing interpreter and skips installs.

## Pointing at a repo

`--repo <path>` or env `MCAGENT_REPO`. With neither, the launcher walks up from this folder looking for a directory (or its direct child) with `main.py` and `pipeline/`. None found, several found, or an invalid path: it prints what to do and exits. It never guesses. The repo's CLI must accept `--drawing | --from-json | --views-folder`, `--output` and `--no-export` (a warning is printed if `--no-export` is missing).

`MCAGENT_DATA` (default `FINAL_UI/data/`, gitignored) holds `parts/`, `runs/`, `UI_Output/` and the conversion cache. The repo is not written to by the UI itself.

The single change vs the original `webapp/app.py`: the project directory comes from `MCAGENT_REPO` (plus the data and static paths above). Routes and payloads are identical. See the header of `server/app.py`.

## Layout

`server/` FastAPI app. `web/` the whole frontend (`index.html`, `static/`, `photoapp/`, `vendor/`, `bridge.js`, `pdf.min.js`, `pdf.worker.min.js`). `tests/unit`, `tests/e2e`. `docs/` (ARCHITECTURE, FEATURE_INVENTORY, DESIGN_SPEC, PROGRESS, QA_RESULTS, screenshots, reference).

## Tests

```bash
node --test "tests/unit/*.test.js"                                  # 116 unit tests
cd tests/e2e && npm install && npx playwright install chromium
PORT=8210 ../../run.sh --repo <repo> &                              # server under test
npx playwright test                                                 # 26 tests incl. axe; BASE_URL overrides http://127.0.0.1:8210
E2E_REPO=<repo> MCAGENT_PYTHON=<python> npx playwright test 20-home   # also runs the launcher test
SHOTS=1 npx playwright test screenshots                              # docs/screenshots/final-*.png
```
The suite never starts a live run; teardown removes every session and demo run it created.

## Honesty rules

No inert buttons, fake percentages, fake "Connected", fake success or fabricated STL. A missing capability is disabled with a short reason. Demo runs replay a saved extraction, carry a Demo badge and stay out of Projects and Recent. Gold is only for Run Pipeline and the current stage; warnings are amber. Engine name comes from the backend. Nothing starts a paid run without Run Pipeline.

## Mock vs real

Nothing is mocked in the UI. Demo runs are real backend calls (no API). 3D shows only a real `model.stl`. Live extraction and SolidWorks builds were not exercised (no API key, no SolidWorks here).

## Gaps

G1-G17 from `docs/ARCHITECTURE.md` section 17 (no model name in `/api/status`, no learning-loop endpoint, no active-run listing, no structured progress API, no part delete/rename, batch is a client loop, and so on). Also: Upload parts uses page 1 / the first image as Front; a repo whose `main.py` lacks `--no-export` cannot run demos or live runs.

## v4 (branch `Improvementsv4`): batch folders, Scoring tab, project previews, run estimates

Setup, migration, tests and launch for the four v4 areas. Nothing here makes a paid API call except Run Pipeline itself.

- **Setup:** `cd FINAL_UI && ./run.sh --repo ../2D-3D-CAD-Test-Generation` (or `run.ps1` / `run.bat`). The launcher installs the repo
  `requirements.txt`; `pymupdf` (PDF page counts and previews) and `pyyaml` (scoring methodology) must be importable by the server.
- **Migration:** none. New parts get a `.meta.json` (UTC `created_at`, `last_run_at`). Older parts fall back to the upload file time and, when
  there is none, show "Date unknown" (never invented). Scores are stored append-only in `<data>/scoring/<part>.jsonl`.
- **Batch folders (Home > Upload folder, Projects > Upload parts folder):** every PDF / JPG / JPEG / PNG directly in the folder is one input
  (any letter case; a multi-page PDF is one input, kept whole, page 1 is read by the pipeline). A subfolder of view images is still one multi-view
  part. Subfolders are scanned for files only by `McA.folderplan.plan(entries, {recursive:true})`. Real file content is checked, not just the
  extension. Unsupported, empty and corrupt files are named in the preflight summary. Run All Parts shows page counts and the batch estimate,
  runs parts one at a time (SolidWorks is serialized), keeps going after a failure, and **Retry failed** re-runs only the failed parts.
- **Scoring (sidebar):** reads the pipeline's own scorer (`python -m bench.score`, free) and its `bench/score_config.yaml`. Methodology and the
  worked example (labelled illustrative) are computed from that config. A part with no signed answer key is **Incomplete**, never 0.
  Without `MTI_BENCH_DATA` (the confidential keys) most UI parts will be Incomplete: that is the honest result.
- **Projects:** real first-page previews of the original PDF/image (`GET /api/parts/{s}/{p}/preview.png`, cached by content fingerprint),
  newest activity first, local date and time on every card.
- **Run estimates (Workspace > Run Pipeline):** `GET /api/estimate` from finished runs (`run_events.jsonl` + the priced ledger). Unknown is
  "insufficient history" or "unavailable", never $0.00. Actual time and measured cost persist via `GET /api/parts/{s}/{p}/last-run`.
- **Tests:** `node --test "tests/unit/*.test.js"`; `python -m pytest tests/server -q`; Playwright
  `STAGE2_OUT=<tmp>/final BASE_URL=http://127.0.0.1:8210 npx playwright test` (start a test server with `MCAGENT_FINAL_OUTPUTS=$STAGE2_OUT`).
  Evidence screenshots: `docs/verification/v4/`.

### Scoring: Extraction-to-Model Fidelity (v4)

The Scoring tab grades what the drawing's extraction asked for against the **real SolidWorks part**, out of 100, colour banded
(green 90+, amber 75+, orange 60+, red below), with a list of issues and warnings by severity. It is measured on the STL that SolidWorks exported
from the SLDPRT, needs **no answer key**, and is free. Spec: `docs/scoring-rubric-emf.md`. Engine: `2D-3D-CAD-Test-Generation/bench/fidelity.py`
(`python -m bench.fidelity <part_dir>`); the pipeline writes `fidelity_score.json` after every run. The answer-key benchmark (`bench.score`) is an
optional second measure shown separately. A part with no STL is Incomplete, a failed build is its own state, and neither is ever scored 0.

### Build Plan and colour coding (v4)

The Build Plan section reads the Feature-IR `plan.json` (`{dims, plan:{features}}`) as well as the legacy `steps` plan: each operation shows the status
SolidWorks reported for it (`ir_report.sw_features`), its numbers resolved from the dimension table, its drawing callouts, flags and defaults. Pipeline
Results sections carry a health colour (navigation dot, status chip with a word, accent bar) computed by `logic/resulttone.js`; the Scoring tab uses band
colours plus six category accents. Colour is never the only cue: every verdict has a word or glyph.

### Grading spectrum (v4)

All 0-100 scores use one grading utility (`web/static/js/logic/grade.js`, tokens `--grade-*`): 0-39 Poor `#D95763`, 40-59 Below Average `#D98B55`, 60-79 Fair `#D6AF6B`,
80-89 Good `#B5C76B`, 90-99 Excellent `#8DD49A`, 100 Perfect `#4CB782`; missing scores are neutral grey `#92949E`. The colour follows the actual number (99.99 is Excellent and shows
as 99.9). To change a threshold or colour, edit `grade.js` and the matching `--grade-*` token (a test fails if they differ).

### Always-fresh UI and action buttons (v4)

The server stamps every `/static/...` URL in `index.html` with `?v=<fingerprint>` and sends the UI files with `Cache-Control: no-cache`, so a browser can never run new scripts against an old cached stylesheet. If a colour or
layout looks old after an update, hard-refresh once (Ctrl+F5). Action buttons use `.btn.act` with `act-open` (solid violet), `act-violet` (violet tint) and `act-gold` (gold tint).
