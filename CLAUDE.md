# CLAUDE.md — mti-2d-3d

Guidance for Claude (and humans) working in this repo. Keep it current: when a
rule here turns out wrong, fix it here in the same change.

## What this project is

AI pipeline that turns a 2D engineering drawing (PDF/PNG, one or several
orthographic views) into a parametric **SolidWorks** part (written for 2024, verified on 2025 SP5) for MTI
(iNDustry Labs / AILOT). The hard problem is not reading dimensions — it is
**relative placement**: putting every feature in the right place, on the right
face, referenced from the right datum.

Current status, results, and open decisions live in [STATE.md](STATE.md).
Read it before starting non-trivial work.

## Repo layout

```
mti-2d-3d/
├── README.md, CLAUDE.md, STATE.md ← start here
├── 2D-3D-CAD-Test-Generation/     ← all code (run commands from this dir)
│   ├── main.py                    CLI: --drawing | --from-json | --batch | --views-folder
│   ├── run_models.py              end-to-end COM batch driver (auto-resolves ambiguities!)
│   ├── pipeline/                  extractor → schema → validator → macro_generator/solidworks_builder
│   ├── utils/                     image_prep, unit_converter, logger
│   ├── tests/                     pytest suite + golden macro snapshots
│   ├── output/<Part>/             generated packages (extraction, report, macros, .SLDPRT)
│   └── Deliverables/<Part>/       hand-off copies (.SLDPRT + design decisions)
├── DrawingPDFs/                   source drawings (PDF)
├── NewVerifiedDrawings/           source drawings, flat: <part>.png, <part>_front_view.png, <part>_side_view.png
├── ViewDefinedDrawings/           source drawings, one folder per part (<part>_front/_side/.png)
├── docs/
│   ├── PRD.md                          ← product requirements (goals, requirements, success targets)
│   ├── PRD-aws.md, PRD-azure.md        ← the two hosting options (same sections, compare side by side)
│   ├── solidworks-macro-error-log.md   ← every runtime failure + the generator rule it produced
│   └── superpowers/specs/              design specs (dated)
└── graphify-out/                  knowledge graph of the repo (GRAPH_REPORT.md, graph.html)
```

## Pipeline in one line

`image_prep → extractor (Claude vision, forced tool call) → schema (Pydantic) →
validator (READY/BLOCKED gate) → macro_generator (VBA, default) | solidworks_builder (COM)`

`pipeline/schema.py` is the contract every stage shares. Change it
deliberately, and update the extraction prompt, validator, and generator together.

## Commands

Run from `2D-3D-CAD-Test-Generation/`. On Windows **always** set `PYTHONUTF8=1`
(see error log E008).

```bash
python setup.py                                              # deps + .env
python main.py --drawing <file> --validate-only --debug      # extract + verify, no build
python main.py --from-json output/<P>/<P>_extraction.json    # regenerate macros, no API cost
python main.py --views-folder <dir> --output ./output        # multi-view parts
python run_models.py <folder> --output ./output              # COM build, Windows + SolidWorks only
python rebuild_from_json.py output/<P>/<P>_extraction.json   # rebuild saved extractions in SW, no API cost
python ir_build.py tests/golden/ir/*.json --solidworks       # Feature IR: CadQuery reference + native SW, verified per feature
python -m pytest tests/ -v                                   # tests (331 passing as of 2026-10-04)
UPDATE_GOLDEN=1 python -m pytest tests/test_golden_macros.py # accept an intended macro change
python -m pipeline.token_report ./output --html output/usage/usage_report.html  # token & cost report
```

API budget: every paid call is checked BEFORE it is sent against a hard cap
(`API_BUDGET_USD`, default **$20**, across all runs on the machine; ledger
`usage/budget_ledger.jsonl`). A call whose worst case would cross the cap raises
`BudgetExceeded` and the run stops with exit code 9 (`pipeline/budget.py`).
Unpriced models are charged at the highest listed rate, so the cap is conservative.

Token tracking: every model completion is appended to
`<output>/usage/usage_ledger.jsonl` (role, model, provider, part, arm, gate,
attempt, tokens, latency, cost). Prices live in `config/pricing.json` (per provider
and model, with `as_of` and `source`). A `null` price makes the row *unpriced*; it
is never guessed. Use `--reprice` after filling one in.

Env vars: `EXTRACTION_PROVIDER` (`openai` default | `anthropic`), `OPENAI_API_KEY`
(required for openai) / `ANTHROPIC_API_KEY` (required for anthropic), `EXTRACTION_MODEL`
(default `gpt-6-astra` / `claude-sonnet-4-6`), `EXTRACTION_CONFIDENCE_THRESHOLD`, `MAX_IMAGE_LONG_EDGE`
(2576), `MACRO_READINESS_THRESHOLD`, `SOLIDWORKS_TEMPLATE_PATH`. Never commit `.env`.

## Hard rules (learned the hard way — see docs/solidworks-macro-error-log.md)

1. **No invented SolidWorks APIs.** Every API call must be verified against the
   SW API docs or a recorded macro. `macro_audit.py` bans known offenders
   (`GetModelBoundingBox`, by-name sketch reselection); add new offenders there.
2. **Mirror the macro recorder.** Call `FeatureExtrusion3`/`FeatureCut4` on the
   still-active sketch; never close-then-reselect a sketch by name (E005/E006).
3. **One coordinate frame: the drawing frame.** Base-plate lower-left corner at
   the origin; all positions edge-referenced exactly like the drawing (E003).
4. **Never select reference geometry by a single hard-coded name.** Always
   provide a position-in-tree fallback (E002).
5. **Cuts are direction-proof** (`ThroughAllBoth`, flip-and-retry) (E005).
6. **Never invent positions.** A position not grounded in extracted data is
   flagged `POSITION ASSUMED`, never guessed silently.
7. **Prohibited features** (loft, sweep, boundary, shell, draft, surfacing,
   helical threads) are never generated. Threads are cosmetic only.
8. **Units:** SW API is meters. Python path: every value through `to_meters()`
   + `assert_meters()`. VBA path: `<drawing value> * UNIT_FACTOR`.
9. **A paid extraction is never lost:** extraction JSON is written for every
   run, READY or BLOCKED. Fix BLOCKED parts by patching JSON + `--from-json`.
10. **Strict structured outputs reject this schema** — keep the forced tool
    call + Pydantic repair retry in `extractor.py`. **Caveat:** forced
    `tool_choice` (`any` / named tool) returns a 400 on Claude Opus 5.5,
    Sonnet 5.5 and Fable 5.1. It works only because extraction runs on
    `claude-sonnet-4-6`. Code on those models (the IR planner, any extractor
    model upgrade) must use `tool_choice: auto` + `strict: true` on the tool
    and an explicit instruction to call it, and keep the Pydantic repair retry.
11. **Every model call is recorded.** Call
    `pipeline.token_tracker.record_completion(response, model=..., provider=..., role=...)`
    right after each completion (roles: `extractor`, `planner`, `auditor_reviewer`,
    `jev`, `other`), inside `scope(gate=..., attempt=...)` where relevant. With no
    active tracker it does nothing, so it's always safe to call.
12. **Every paid call goes through the budget guard:** `budget.preflight(...)`
    before the request, `budget.charge(...)` after. Never catch `BudgetExceeded`
    in a per-item loop; it must stop the whole run.
13. **"Built" means it changed the part.** Check volume after bosses (E013).
    Never call a selection-based feature (fillet/chamfer) without a verified
    selection (E012). The validator FAILS a part missing any extracted feature.

## When a macro fails on a real SolidWorks machine

1. Log it in `docs/solidworks-macro-error-log.md` FIRST (next E-number, symptom,
   root cause, fix, generator rule, test name).
2. Fix `pipeline/macro_generator.py` — never hand-edit a generated `.vba`.
3. Add a regression test in `tests/test_macro_generator.py`.
4. Regenerate with `--from-json`; update golden snapshots only if intended.

## Working conventions

- **Tests:** the non-SolidWorks half (extraction logic w/ mocked API, schema,
  validator, macro generation) must pass on any OS. SolidWorks-only code
  imports `win32com` lazily inside functions — keep it that way.
- **Determinism:** generated macros contain no timestamps or absolute paths;
  golden tests depend on it.
- **Specs before code** for new subsystems: write
  `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`, get it reviewed.
- **Update STATE.md** whenever a milestone lands, a part's status changes, or
  an open decision gets made.
- **Knowledge graph:** `graphify-out/GRAPH_REPORT.md` summarizes structure; for
  "how does X connect to Y" questions run `graphify query "<question>"`. After
  large changes, refresh with `/graphify . --update`.

## Next phase (designed 2026-09-28 — read before building)

Roadmap: `docs/superpowers/specs/2026-09-28-ai-cad-roadmap-design.md`, with one spec
each for A (Feature IR v2), B (auditor loop + Jev) and C (placement benchmark).
Rules that already apply to new code:

- **IR numbers are expressions over dimension IDs** (`"D003 / 2"`), never free
  floats. A literal other than 0/1/2 needs a justification.
- **One part frame; global coordinates.** `on:` only picks the start face and
  the into-material direction. No per-face local sketch frames.
- **Deterministic audit findings can't be overruled** by Jev or the LLM reviewer.
  Those two can only add findings.
- **Jev is text-in, discrete-out.** Never ask it for or about numbers.
- **The benchmark split is fixed in `bench/manifest.yaml`.** Never tune prompts or
  the IR on held-out parts.
- **Model IDs are pinned in `config/models.json`** (`gpt-6-astra`), never hard-coded
  at call sites. **Decision 2026-10-04: GPT-6 Astra only.** No Anthropic/Opus path and no
  model benchmark.
