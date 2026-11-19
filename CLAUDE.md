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
│   ├── test-reports/                   ← dated test-day records (results, failures, costs, decisions)
│   ├── PRD.md                          ← product requirements (goals, requirements, success targets)
│   ├── PRD-aws.md, PRD-azure.md        ← the two hosting options (same sections, compare side by side)
│   ├── solidworks-macro-error-log.md   ← every runtime failure + the generator rule it produced
│   ├── mti-modeling-standards.md       ← MTI's modeling practices + feature guide, and pipeline status
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
python ir_run.py --split dev --solidworks                    # drawing -> Astra extract+plan -> reference -> SW (paid, budget-guarded)
python ir_run.py --split held_out --solidworks --output <new dir> --reuse  # official benchmark run: MTI parts read drawing.pdf from MTI_BENCH_DATA (paid)
python main.py --drawing <file> --ir --engine com            # same, one drawing
python main.py --drawing <file> --ir --engine com --record-solidworks   # also record the SolidWorks window during the build (Windows; UI: Run options -> Record Pipeline Run)
python ir_compare.py                                         # v1 vs IR on the dev set (no API)
python mti_discrepancy.py --out ./output --all              # why each part differs from MTI's model; ranked causes (no API)
python mti_markup.py --out ./output <part> ...               # marked-up COPY of MTI's drawing (OCR positions; local only, never commit)
python -m pytest tests/ -v                                   # tests (1018 passing, 66 skipped, as of 2026-11-02)
python -m bench.prep status                                  # benchmark data (needs MTI_BENCH_DATA + ODA_CONVERTER in .env)
python -m bench.prep <copy|dxf|pdf|step|keys|check|link|review|accept|signoff|profile>  # benchmark prep (no API cost)
python -m bench.score <run_dir> [--keys-dir DIR] [--no-sw]   # geometry score 0-100 + stage blame, plus a separate MTI practices score -> scores.json, report.html (no API cost)
python -m bench.calibrate                                    # planted-error table on real parts; tune bench/score_config.yaml
UPDATE_GOLDEN=1 python -m pytest tests/test_golden_macros.py # accept an intended macro change
python -m pipeline.token_report ./output --html output/usage/usage_report.html  # token & cost report
```

API budget: every paid call is checked BEFORE it is sent against a hard cap
(`API_BUDGET_USD`, default **$20**, across all runs on the machine; ledger
`~/.mti-2d-3d/budget_ledger.jsonl`, outside the repo). A call whose worst case would cross the cap raises
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
(2576), `MACRO_READINESS_THRESHOLD`, `SOLIDWORKS_TEMPLATE_PATH`, `MTI_CALLOUT_DEFAULTS` (`1` default;
`0` leaves vague callouts unresolved, see `pipeline/ir/defaults.py`). Never commit `.env`.

## Hard rules (learned the hard way — see docs/solidworks-macro-error-log.md)

1. **No invented SolidWorks APIs.** Every API call must be verified against the
   SW API docs or a recorded macro. `macro_audit.py` bans known offenders
   (`GetModelBoundingBox`, by-name sketch reselection); add new offenders there.
2. **Mirror the macro recorder.** Call `FeatureExtrusion3`/`FeatureCut4` on the
   still-active sketch; never close-then-reselect a sketch by name (E005/E006).
3. **Plan in the drawing frame; model in MTI's frame.** Plans (IR, v1 JSON) keep
   the drawing frame: positions edge-referenced exactly like the drawing (E003).
   The IR SolidWorks compiler then maps the plan *rigidly* (rotation + translation,
   never a mirror) into MTI's convention: base body **centered on the origin**,
   base sketch on the **Top plane**, Mid Plane base, **Up To Next** through cuts,
   each verified by volume with a logged fallback (`convention="mti"`, default).
   The VBA path still uses the lower-left-corner origin. See
   `docs/mti-modeling-standards.md`.
4. **Never select reference geometry by a single hard-coded name.** Always
   provide a position-in-tree fallback (E002; `select_ref_plane`, MTI's
   `SelectPlane` macro pattern).
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
  large changes, refresh with `/graphify . --update`; where that skill isn't
  available, `python graphify-out/ast_update.py` refreshes the code layer (no LLM).
- **Test days:** record each one in `docs/test-reports/YYYY-MM-DD-test-report.md`
  (what ran, successes, failures, costs from `~/.mti-2d-3d/budget_ledger.jsonl`, decisions, next steps).

## MTI modeling standards (2026-10-11)

MTI's own practices: `docs/mti-modeling-standards.md`; design and phases:
`docs/superpowers/specs/2026-10-11-mti-modeling-standards-design.md`.

- **"General best practices, not hard and fast rules."** Apply what the compiler
  can verify. Report the rest as advisory `mti_*` findings
  (`pipeline/ir/mti_review.py`). Never block a part over a practice.
- **MTI Std 202.02.0003 is confidential.** It lives only in
  `config/mti/*.local.json` (gitignored; a test checks this) and is read by
  `pipeline/mti_standards.py`. Never commit it, never put it in a model prompt, and
  never copy its values into tests or docs (tests use a synthetic table). Without
  it, the pipeline falls back to the generic chart in `fasteners.py`.
- **Hole Wizard for bolt holes, cut-extrude for the rest, Up To Next for through
  holes** (`swEndCondUpToNext` = 11, never 2; E021). Hole Wizard holes are always
  volume-verified and fall back to a plain cut. Use `solidworks_builder.typed()` for
  members late binding can't reach, and `com_doubles()` for double arrays.
  Tapped holes: Hole Wizard tap with a **cosmetic** thread (`Value7`), never real
  threads. Blind Hole Wizard holes keep the 118° drill point, credited exactly in
  the volume check. Hole + pattern = one feature on construction geometry (E022).
  **Programmatic sketches never rely on inference** (E020–E022): set coordinates
  explicitly and read them back. Every sketch is fully defined (`define_sketch`,
  E023): model-edge datums, then an origin anchor. Never an anchor in a Hole Wizard
  sketch. Batch builds close each part after saving (E024). Never generate MTI's "generally avoid" features (sweep, loft, shell,
  draft, ribs, splines, real threads, ...).

## MTI test files: "[MTI] Parts + Drawings Audit" (Google Drive, added 2026-10-26)

**Where.** Google Drive folder **[MTI] Parts + Drawings Audit**
(folder id `10wfwK0XK_IjcvvU84tfB7NDq0WqhpaKw`, owner account ggould@nd.edu).

- **Local sync.** It is meant to sync to `G:\My Drive\[MTI] Parts + Drawings Audit` or
  `G:\Shared drives\[MTI] Parts + Drawings Audit`. As of 2026-10-26 **Google Drive for
  desktop is not installed on this PC** (no G:, no DriveFS).
- **Composio.** Access goes through the Composio Google Drive connection instead:
  `GOOGLEDRIVE_FIND_FILE` with `'<id>' in parents` to list, `GOOGLEDRIVE_DOWNLOAD_FILE` to
  fetch by file id.
- **If it ever syncs locally,** check both G: paths first. The folder name contains square
  brackets, so quote every path and use `-LiteralPath` in PowerShell.

**Layout.**

- `A-Series\<PartNumber>\`, `SB-Series\<PartNumber>\` and `Other-Series\<PartNumber>\`: one
  folder per part, holding the 2D drawing (`.PDF` scan or `.DWG`) and, if one exists, the 3D
  model (`.SLDPRT`/`.SLDASM`).
- `_Needs Review\`: old revisions and unrecognized names. **Skip it.**
- **Scan of 2026-10-26, excluding `_Needs Review`:** 301 part folders (242 A, 56 SB, 3 Other),
  443 files (186 PDF, 142 DWG, 114 SLDPRT, 1 SLDASM).
- **Test set: 63 parts with both a drawing and a model** (34 A, 27 SB, 2 Other; 39 PDF and 24
  DWG drawings). The drawing is the input; the existing SLDPRT is the ground truth.
  - Listed in **`2D-3D-CAD-Test-Generation/bench/mti_test_set.csv`** (identical copy at the repo root,
    `test_set.csv`): series, part number, drawing format,
    Drive paths, Drive file ids, notes.
  - 2 folders have a model but no drawing: A00687E and A09126 (an assembly).

**Naming rules.**

- **A-Series:** A + 5-digit part number + sheet digit + E/M suffix, e.g. `A001151E` = part
  A00115, sheet 1, E. **E and M are separate parts.** Models named `MTI0xxxxx` belong to part
  `A0xxxx` (`MTI004039E.SLDPRT` ↔ `A040391E.DWG`).
- **SB-Series:** SB + 5-digit number, with -dash detail numbers. Old 7-digit names are the same
  parts (`1367402E` = SB13674-02).
- **Family folders hold many details:** SB13674 has 12 sheets and 45 models, SB01783 2 and 5,
  SB12052 2 and 3, SB18461 5 sheets and 1 model. These need drawing-to-model pairing by
  detail number before they can be scored.

**Rules.**

- **The Drive folder is READ-ONLY.** Never modify, move, rename, upload to or save into it.
- Write every generated part and test result to `output/<PartNumber>/` in this project.
- **Macros:** run SolidWorks VBA macros over COM (`SldWorks.Application`, pywin32) with
  `RunMacro2` on MTI's `.swp` files. **They are not in this repo yet; ask the user where they
  are.** Ask before running any macro on the test set.
- **Tools:** `mti_batch.py` (drawing PDF → verified SolidWorks part, budget-guarded),
  `mti_groundtruth.py` (MTI's SLDPRT → `ground_truth.step`; open only in a SolidWorks
  session that is already up, E025), `mti_score.py` (IoU vs MTI's model). First batch:
  `docs/test-reports/2026-10-26-test-report.md`.

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
