# mti-2d-3d — AI 2D Drawing → SolidWorks Part

Turns a 2D engineering drawing (PDF or PNG, one or several orthographic views)
into a parametric **SolidWorks 2024** part, using Claude vision for extraction and
a verified, deterministic build step. Built for MTI by the iNDustry Labs
AILOT team.

> **Status (2026-09-28):** the current pipeline works end to end, but it places
> features poorly. On the 5 parts built so far, 10 of 26 features were built, and
> hole patterns, fillets and chamfers are the main gaps.
>
> A next phase is **designed but not yet built**: a typed build plan, an auditor
> loop with retries, and a placement-aware benchmark of Claude Opus 5.5 vs GPT-6
> Astra. See [STATE.md](STATE.md) and the
> [roadmap spec](docs/superpowers/specs/2026-09-28-ai-cad-roadmap-design.md). The
> next phase is preliminary and still open for collaborator review.

## How it works

```
drawing → image prep → Claude extraction (forced tool call) → schema (Pydantic)
        → verification gate (READY / BLOCKED) → SolidWorks VBA macros  (default, runs on any SW machine)
                                              → direct COM build        (--engine com, Windows + SW2024)
```

Phase 1 (extraction and verification) runs on any OS. Phase 2 emits numbered VBA
macros that run inside SolidWorks with nothing to install. Alternatively, it
drives SolidWorks over COM on Windows.

## Repository layout

| Path | What's there |
|---|---|
| [`2D-3D-CAD-Test-Generation/`](2D-3D-CAD-Test-Generation/) | All code: `main.py` CLI, `pipeline/`, `utils/`, `tests/`, generated `output/` and hand-off `Deliverables/`. Detailed usage is in its [README](2D-3D-CAD-Test-Generation/README.md) |
| `DrawingPDFs/` | Source PDFs for 115-C, 116-C, 117-C and 135-A |
| `ViewDefinedDrawings/` | Clean multi-view drawings, one folder per part (A040911E, A040921E, SB11033, SB11780, SB11842) |
| `NewVerifiedDrawings/` | 12 more parts. ⚠️ Many `_front_view` / `_side_view` images are **not** views of the named part; label them by hand before use |
| [`docs/`](docs/) | [SolidWorks macro error log](docs/solidworks-macro-error-log.md) and design specs |
| [`graphify-out/`](graphify-out/) | Knowledge graph of the repo. Open `graph.html` in a browser; the summary is in [`GRAPH_REPORT.md`](graphify-out/GRAPH_REPORT.md) |

## Quick start

Requires Python 3.10+. For the COM path and for running the macros you also need
Windows with SolidWorks 2024.

```bash
cd 2D-3D-CAD-Test-Generation
python setup.py                  # checks Python, installs requirements, creates .env from .env.template
# edit .env and set ANTHROPIC_API_KEY
```

On Windows, set `PYTHONUTF8=1` before running (see error log E008).

```bash
python main.py --drawing path/to/drawing.pdf --validate-only --debug    # extract + verify only
python main.py --drawing path/to/drawing.pdf --output ./output          # full run → VBA macro package
python main.py --from-json output/<Part>/<Part>_extraction.json          # regenerate macros, no API cost
python main.py --views-folder ./ViewDefinedDrawings --output ./output   # multi-view parts
python -m pytest tests/ -v                                               # tests
```

Copy `output/<Part>/` to any SolidWorks machine and follow `macros/README.md`.

## Secrets

- The API key lives only in `2D-3D-CAD-Test-Generation/.env`, which is created from
  `.env.template`.
- Every `.env` and `.env.*` file is gitignored at any depth. Only `.env.template`
  is tracked, and it contains placeholders only.
- **Never commit a real key.** If one is ever committed, rotate it immediately.
  Removing it from git does not make it safe.

## Documentation

| Doc | Read it for |
|---|---|
| [STATE.md](STATE.md) | Where the project stands: results, gaps, open decisions |
| [CLAUDE.md](CLAUDE.md) | Working rules for humans and Claude: commands, hard rules, conventions |
| [docs/solidworks-macro-error-log.md](docs/solidworks-macro-error-log.md) | Every real SolidWorks failure and the generator rule it produced |
| [Roadmap](docs/superpowers/specs/2026-09-28-ai-cad-roadmap-design.md) | Next-phase decisions and architecture, plus specs for [A: Feature IR v2](docs/superpowers/specs/2026-09-28-feature-ir-v2-design.md), [B: auditor loop](docs/superpowers/specs/2026-09-28-auditor-loop-design.md) and [C: placement benchmark](docs/superpowers/specs/2026-09-28-placement-benchmark-design.md) |
| [June 2026 pipeline design](docs/superpowers/specs/2026-06-11-2d-to-3d-solidworks-pipeline-design.md) | Original design of the current pipeline |
| [docs/PRD.md](docs/PRD.md) | Product requirements: problem, goals, requirements, success targets, open questions for review |

## Knowledge graph

`graphify-out/` is committed on every branch so anyone can explore how the code,
docs and drawings connect. After meaningful changes, refresh it with `/graphify . --update`
in Claude Code and commit the updated `graph.json`, `graph.html` and
`GRAPH_REPORT.md`. The machine-local cache and interpreter paths are gitignored.

## Contributing

- Work on a branch and open a PR against `main`.
- When a macro fails on a real SolidWorks machine:
  1. Log it in the error log first.
  2. Fix `pipeline/macro_generator.py`; never hand-edit a generated `.vba`.
  3. Add a regression test.
  4. Regenerate with `--from-json`.
- New subsystems start with a design spec in `docs/superpowers/specs/`.

## Contributors

Joe Mathew (original pipeline) · Brad Sandberg (repository) · ggould / MalteseWarrior (next-phase research)
