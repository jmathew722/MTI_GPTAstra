# mti-2d-3d — AI 2D Drawing → SolidWorks Part

Turns a 2D engineering drawing (PDF or PNG, one or several orthographic views)
into a native **SolidWorks** part (verified on SolidWorks 2025 SP5), using
**GPT-6 Astra** to read and plan, and deterministic compilers to build. Built for
MTI by the iNDustry Labs AILOT team.

> **Status (2026-10-04):** all 9 dev parts go drawing → GPT-6 Astra extraction +
> build plan → CadQuery reference (STEP) → native SolidWorks part, **with every
> feature verified against the reference**. Against hand-checked answers the parts
> match at IoU 0.986–1.000, and anything the drawing doesn't settle comes back as a
> written question rather than a guess. Full record of the test day:
> [docs/test-reports/2026-10-04-test-report.md](docs/test-reports/2026-10-04-test-report.md).
> Live status: [STATE.md](STATE.md).
>
> **2026-10-11:** parts are now modeled to **MTI's own standards**: origin centered on the
> base body, base sketch on the Top plane, and Up To Next through holes. Hole Wizard sizes are
> proposed from MTI's hole standard. See [docs/mti-modeling-standards.md](docs/mti-modeling-standards.md).

## How it works

**Feature-IR path (recommended, `--ir`):**

```
drawing → GPT-6 Astra extraction → GPT-6 Astra build plan (every number an expression over drawing dims)
        → Gate 1 checks → CadQuery reference (STEP + measured feature map)
        → native SolidWorks part over COM, each feature's volume checked against the reference
        → report: open questions for a human, flagged standard-derived values, cost
```

**Original path (v1):** extraction → verification gate → numbered VBA macros (any SolidWorks
machine) or a direct COM build. It is still available; the IR path matches or beats it on
every dev part.

Extraction, planning, the CadQuery reference and all tests run on any OS. Native builds need
Windows + SolidWorks. Every paid model call goes through a hard **$20 budget guard**.

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

Requires Python 3.10+ (developed on 3.13). For native builds you also need Windows with
SolidWorks (2024, 2025 or 2026).

> **On a fresh clone, one thing is missing on purpose: your API key.** `.env` is gitignored,
> so it is in no commit and no clone. Copy `.env.template` to `.env` and set `OPENAI_API_KEY`.
> Everything that costs nothing — the 1018 tests, `--from-json`, `ir_build.py`, and
> `ir_run.py --reuse-plans` — runs without it.
>
> Set `SOLIDWORKS_TEMPLATE_PATH` to the template matching **your installed SolidWorks year**.
> A newer template silently fails with `NewDocument returned None`; check the version with
> `RevisionNumber` (33.x = 2025, 34.x = 2026) rather than the folder name.

```bash
cd 2D-3D-CAD-Test-Generation
python setup.py                  # checks Python, installs requirements, creates .env from .env.template
# edit .env and set OPENAI_API_KEY (GPT-6 Astra)
```

On Windows, set `PYTHONUTF8=1` before running (see error log E008).

```bash
python main.py --drawing path/to/drawing.pdf --ir --engine com          # IR path: drawing -> verified SolidWorks part
python ir_run.py --split dev --solidworks                               # IR path on all dev parts (bench/manifest.yaml)
python ir_run.py --split dev --solidworks --reuse-plans                 # rebuild from saved plans, no API cost
python main.py --drawing path/to/drawing.pdf --validate-only --debug    # extract + verify only
python main.py --drawing path/to/drawing.pdf --output ./output          # full run → VBA macro package
python main.py --from-json output/<Part>/<Part>_extraction.json          # regenerate macros, no API cost
python main.py --views-folder ./ViewDefinedDrawings --output ./output   # multi-view parts
python -m pytest tests/ -v                                               # tests

# Build into FINAL_OUTPUTs/ with per-part cost tracking (see FINAL_OUTPUTs/costs.txt).
# Refreshes costs after every part and stops the run if one part exceeds $5.
python make_part.py "../Simple Parts/A001151E.PDF"
python make_part.py "../Simple Parts/A001151E.PDF" "../Simple Parts/A001821E.PDF"
python final_costs.py                                                    # rewrite costs.txt only
```

Copy `output/<Part>/` to any SolidWorks machine and follow `macros/README.md`.

## Token & cost tracking

Every model completion (extractor today; planner, auditor and Jev as they're
built) is appended to `output/usage/usage_ledger.jsonl`. Each row records role,
model, provider, part, benchmark arm, gate, retry attempt, tokens, latency and
cost. To see what runs cost:

```bash
cd 2D-3D-CAD-Test-Generation
python -m pipeline.token_report ./output                                  # terminal tables
python -m pipeline.token_report ./output --html output/usage/usage_report.html --csv output/usage/usage.csv
python -m pipeline.token_report ./output --role planner --since 2026-10-01 --reprice
```

The report shows total spend, average cost per part, cost by role (builder vs.
auditor), by model and provider, by benchmark arm, and the cost of retries. The
HTML dashboard is a single offline file.

Prices live in `config/pricing.json`, per provider and model, each with a source
and date. A price that isn't confirmed is `null`, and those rows show as
**unpriced** rather than being guessed. Fill the price in, then re-run with
`--reprice`. The ledger and the generated reports are gitignored.

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
| [docs/test-reports/](docs/test-reports/) | Dated test-day records: every run, success, failure, cost and decision |
| [docs/mti-modeling-standards.md](docs/mti-modeling-standards.md) | MTI's modeling practices and feature guide, and what the pipeline does about each |
| [docs/demo-guide.md](docs/demo-guide.md) | Live meeting demo: checklist, talking points, fallbacks (`demo.py`) |
| [CLAUDE.md](CLAUDE.md) | Working rules for humans and Claude: commands, hard rules, conventions |
| [docs/solidworks-macro-error-log.md](docs/solidworks-macro-error-log.md) | Every real SolidWorks failure and the generator rule it produced |
| [Roadmap](docs/superpowers/specs/2026-09-28-ai-cad-roadmap-design.md) | Next-phase decisions and architecture, plus specs for [A: Feature IR v2](docs/superpowers/specs/2026-09-28-feature-ir-v2-design.md), [B: auditor loop](docs/superpowers/specs/2026-09-28-auditor-loop-design.md) and [C: placement benchmark](docs/superpowers/specs/2026-09-28-placement-benchmark-design.md) |
| [June 2026 pipeline design](docs/superpowers/specs/2026-06-11-2d-to-3d-solidworks-pipeline-design.md) | Original design of the current pipeline |
| [docs/PRD.md](docs/PRD.md) | Product requirements: problem, goals, requirements, success targets, open questions for review |
| [docs/PRD-aws.md](docs/PRD-aws.md) · [docs/PRD-azure.md](docs/PRD-azure.md) | The two hosting options for the MCP connector and model access (Bedrock + AgentCore vs Foundry + Azure Functions) |

## Knowledge graph

`graphify-out/` is committed on every branch so anyone can explore how the code,
docs and drawings connect. After meaningful changes, refresh it with `/graphify . --update`
in Claude Code and commit the updated `graph.json`, `graph.html` and
`GRAPH_REPORT.md`. Where that skill isn't available, `python graphify-out/ast_update.py`
refreshes the code layer deterministically (no LLM). The machine-local cache and interpreter paths are gitignored.

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
