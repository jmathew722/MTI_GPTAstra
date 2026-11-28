# Archive manifest

Nothing was deleted. Files below were moved out of active locations; each is still in git history.

| Item | Original location | Now | Why |
|---|---|---|---|
| `jid.txt` | repo root | `archive/misc/jid.txt` | stray 21-byte job id; gitignored |

## Removed from version control only

18 tracked SolidWorks lock and autosave files (`~$*.SLDPRT`, `AUTOSAVE_*.SLDPRT`) under `2D-3D-CAD-Test-Generation/output/` and `demo/`. They are produced by an open SolidWorks session and have no value; the files remain on disk and `.gitignore` now excludes them.

## Considered and left in place

- `2D-3D-CAD-Test-Generation/extraction_115C/116C/117C.json`: first moved to the archive, then restored. The UI's no-API Demo (`FINAL_UI/server/app.py::_samples`, `POST /api/demo`) scans the code folder for `extraction_*.json`; the browser specs `06-08-demo` and `20-home` caught the regression. Lesson: a file with no Python import can still be loaded by name.

- `FINAL_OUTPUTs/` (69 MB, 442 tracked files): live output root of the UI; stored records and native drawing-to-part links use these paths.
- `2D-3D-CAD-Test-Generation/output/` and `Deliverables/`: run packages and hand-offs referenced by STATE.md and the test reports.
- `docs/phase1-evidence/`, `docs/phase2-evidence/`, `docs/solidflow-upgrades/*-evidence/`: historical evidence, referenced by reports.
- `graphify-out/`: output directory of the graphify tool.
