# McAgent (2D to 3D SolidWorks Pipeline UI)

A vanilla HTML/CSS/JS front end (no framework, no CDN, no build step) for the MTI 2D to 3D pipeline. It replaces the old four-sheet "BLUEPRINT ROOM" UI with a sidebar, a Home page, a Workspace (five-stage tracker, drawing and 3D split canvas, inspector, results drawer), Projects, Pipeline Results, Recent Files, Help and Settings. The FastAPI backend (`pipeline_app/webapp/app.py`), `bridge.js` and `photoapp/` are unchanged.

Docs: `CLAUDE.md` (brief), `docs/ARCHITECTURE.md`, `docs/FEATURE_INVENTORY.md`, `docs/PROGRESS.md`, `docs/QA_RESULTS.md`.

## Run

Use a Python 3.12 venv (3.15 breaks scipy).

```bash
cd pipeline_app/webapp
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r ../requirements.txt -r requirements-ui.txt
PORT=8200 ./run.sh            # http://127.0.0.1:8200  (run.sh reuses .venv and installs missing deps)
```

Without `ANTHROPIC_API_KEY` the UI runs in demo-only mode: Run Pipeline is disabled with the reason, and Run Demo works (no API call).

## Test

```bash
# Unit tests (pure logic, no dependencies): 111 tests
cd pipeline_app/webapp && node --test "tests-ui/unit/*.test.js"

# End to end + axe (Playwright, chromium) against the running server
cd e2e && npm install && npx playwright install chromium
npx playwright test                      # 18 tests (scenarios 1-16 of ARCH 14.2 + keyboard, honesty, stale-response)
SHOTS=1 npx playwright test screenshots  # re-shoot docs/screenshots/final-*.png
BASE_URL=http://127.0.0.1:8191 npx playwright test   # another port
```

The suite never starts a live run and never confirms Run All or Clear all models. Global teardown deletes every session folder and demo-run folder the tests created.

## Mock vs real

Nothing is mocked in the UI: every value comes from the backend or from browser state. Demo runs (`POST /api/demo`) are real backend calls that replay a saved extraction, carry a Demo badge, and are kept out of Projects, Recent and the part switcher. 3D shows only bytes from a `model.stl` endpoint. Live extraction and SolidWorks builds were not exercised (no API key, no SolidWorks on this machine); the code paths are covered by unit tests, fixtures and review only.

## Backend integration gaps (full table: ARCH section 17)

G1 no model name in `/api/status` (Engine shows "Not reported" unless a last-run usage row has it). G2 `live` only means a key is set (chip says "API key set", never "Connected"). G3 no learning-loop endpoint (button disabled with reason). G4 no active-run listing (reconnect only from the starting browser). G5 no structured progress API (tracker parses `[STAGE]` lines). G6 history has no duration, exit code or per-run revisions. G7 no required-views validation endpoint. G8 originals not served. G9 cropper renders PDF page 1 only. G10 no delete, rename or duplicate for parts. G11 batch is a client loop. G12 no concurrent-run guard. G13 zip only for runs tracked this server lifetime. G14 Clear all is all-or-nothing. G15 cost table lives in the backend (labeled Estimated). G16 demo runs have no drawing, generation or verification. G17 TIFF may not decode in browsers.

## Migration map (old to new)

| Old | New |
|---|---|
| Header title block, engine and deliverables text, API pill | Sidebar brand; Workspace header chips (Engine, Deliverables, API) driven by backend data |
| Sheet 1 Drawing Crop (cropper, Mark regions) | Focus overlay (Crop / Mark modes) opened from the 2D toolbar and Part Setup |
| Sheet 2 intake strip, gallery, must-meet specs | Home dropzone; Inspector, Part Setup (Views, Save part, Must-meet specs) |
| Sheet 2 overview image and STL viewer | Workspace split canvas: 2D Drawing and 3D Model (STL) |
| Sheet 3 saved parts, Run, Run All, demo, stage strip, progress, console, corrections | Projects cards and part switcher; gold Run Pipeline in the tracker; Inspector, Pipeline Actions and Corrections; five-stage tracker; drawer Console |
| Sheet 4 ten output tabs, Select Run, Clear all models | Pipeline Results page and drawer (13 sections in five groups); Projects and Settings danger action |
| `index.html` monolith | `static/css/*.css`, `static/js/{core,logic,ui,pages,features}/*.js` under one `McA` namespace; `design-tokens.css` stays the single token source |

`index.legacy.html` was removed after every row of `docs/FEATURE_INVENTORY.md` was verified (see QA_RESULTS.md).
