# PROGRESS

Task list for the Nebula CAD build. Updated at every milestone. The last task is always verification.

## Task list

| # | Task | Status |
|---|---|---|
| 0.1 | Verify every repo link, maintenance status, current version | done |
| 0.2 | Study reference sites, write research notes | done (limited, see DESIGN_SPEC "Research notes") |
| 0.3 | Pipeline improvement: save an STL beside every generated `.sldprt` | done |
| 1.1 | `docs/ARCHITECTURE.md` | done |
| 1.2 | `docs/DESIGN_SPEC.md` | done |
| 1.3 | `docs/API_CONTRACT.md` | done |
| 1.4 | `docs/QA_CHECKLIST.md` | done |
| 2.1 | Scaffold, tokens, fonts, nebula background, glass system | pending |
| 2.2 | App shell: TopNav, Sidebar, ContextRail, routing | pending |
| 2.3 | Command palette, toasts, shortcuts dialog | pending |
| 2.4 | Schemas, adapter (mock + http), seeded sample data, generated sample drawing PDFs and STLs | pending |
| 3.1 | Dashboard (hero, KPIs, viewer, pipeline, workspace tabs, quick actions, rail) | pending |
| 3.2 | Workstation: drawing/model compare, viewer tools, extraction review, build plan | pending |
| 3.3 | Tabs: Parameters, Features, Validation, Cost, Logs, Rubric | pending |
| 3.4 | Automation wizard, Pipelines, Models, Projects, Library, Docs, Settings, Viewer | pending |
| 3.5 | Extras: notifications, audit trail, revisions, comments, export center, onboarding | pending |
| 4.1 | Motion system | pending |
| 4.2 | Polish passes 1–6 | pending |
| 5.1 | Unit tests (cost, rubric), e2e smoke, axe, screenshots at 3 viewports | pending |
| 5.2 | Reviewer subagent audit, fixes | pending |
| 5.3 | Final verification: build, typecheck, lint, tests; docs final | pending |

## Milestone log

### M0 — Research, setup, pipeline change
- Brief files were not in `Thee_UI/`. Copied `CLAUDE.md` (master brief), `CLAUDE_NEBULA_PRIME.md`, `NEBULA_PRIME_STACK.md` from `~/Downloads`. The mockup was found as `~/Downloads/a_detailed_high_contrast_dark_sci_fi_ui_for_a_cad.png` and copied to `reference/nebula-mockup.png`.
- The earlier pipeline-UI guidance that lived at `Thee_UI/CLAUDE.md` is kept as `PIPELINE_UI_CONTRACT.md`.
- Work happens on branch `feat/nebula-cad-ui` of the existing repo (see ARCHITECTURE decision D2).
- Pipeline: `export_stl()` added to `pipeline/solidworks_builder.py`, called after both COM save sites. 3 new tests pass. Not run against SolidWorks (this machine is macOS).
