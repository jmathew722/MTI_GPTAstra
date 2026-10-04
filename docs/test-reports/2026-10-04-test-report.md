# Test Report: 2026-10-04 — from "10 of 26 features" to verified parts from drawings

**Project:** mti-2d-3d (MTI 2D drawing → SolidWorks, iNDustry Labs / AILOT)
**Date:** 2026-10-04 (one working session) · **Operator:** ggould (MalteseWarrior), with Claude Code
**Branch:** `feat/openai-extractor-sw2025` (13 commits after `bd4a073`) · **Host:** Windows 11, SolidWorks 2025 SP5, Python 3.13
**Model under test:** OpenAI **GPT-6 Astra** (`gpt-6-astra`), the only model used (see Decisions)

> This report is the permanent record of what was run, what worked, what failed, and what it
> cost. Numbers come from the files named next to them. Live status lives in
> [STATE.md](../../STATE.md); the runtime failures are in the
> [error log](../solidworks-macro-error-log.md) (E011–E019).

---

## 1. Overall statement

At the start of the day the pipeline built **10 of 26** extracted features on its five finished
parts and reported **PASSED on all five**: incomplete parts were approved. By the end of the day:

- **All 9 dev parts go from drawing to a native SolidWorks part with every feature verified**
  against an independent CadQuery reference. That runs through the new Feature-IR path:
  GPT-6 Astra extracts and plans, then deterministic compilers build.
- On every part with a hand-checked answer, **the new path matches the drawing at least as well
  as the old pipeline**: aligned solid IoU **0.986–1.000**, against 0.960–1.000 for the old one.
  The old pipeline delivers a passing part on **1 of 9**.
- **Nothing ambiguous is guessed.** Every remaining gap is a written question for a person
  (9 questions across the 9 parts). Most are undimensioned corner radii or "R MAX" callouts.
- **False approvals: 0.** The validator now fails incomplete parts and caught a misplaced build.
- **Total API spend: $11.70** (47 GPT-6 Astra calls) against a hard **$20 cap** that was enforced
  throughout. A full drawing-to-part run costs about **$0.20–0.50 per part** to plan, plus about
  **$0.50** if the drawing hasn't been extracted yet.
- **Test suite: 188 → 340 passing** tests (23 test files).

---

## 2. Environment brought up today

| Item | State | Note |
|---|---|---|
| Python | 3.13.13 in `.venv` (via `uv`) | No Python existed on the machine (only the Store shim) |
| SolidWorks | **2025 SP5** (rev 33.5) at `D:\SOLIDWORKS` | The project targeted 2024; needed the E011 fix |
| CadQuery | 2.8.0 (OpenCascade) | New: reference compiler for the Feature IR |
| Model | GPT-6 Astra via the OpenAI **Responses API** | Chat Completions rejects function tools + reasoning on this model |
| Template | SW 2025 part template is **Z-up** (Front plane = model YZ) | Measured at runtime by `probe_plane_map` |
| Secrets | `.env` at the repo root, gitignored at any depth | Never read or committed by tooling |

---

## 3. Tests run today (in order)

### T1 · Environment and suite baseline
- 188/188 existing tests passed on the new venv.
- **Failure found:** the SolidWorks COM build could not start on 2025 (`Library not registered`).
  The constants type library was pinned to the 2024 version, and the registry stores it in hex
  (2025 = `21.0` = 33). Fixed by probing versions (**E011**). SB11033 then rebuilt identically to June.

### T2 · OpenAI extractor, first live call
- `gpt-6-astra` extracted SB11033: 19 dimensions, 8 features, READY 99%, 77 s, 6,813 in /
  4,923 out tokens.
- Two setup failures on the way, both fixed: the key name in `.env` (`OPEN_API_KEY`, now
  `OPENAI_API_KEY`), and a 400 because function tools + reasoning need the Responses API.

### T3 · Astra baseline extraction, 5 parts
- 3 READY, 2 BLOCKED (one dimension each). About $1.50.

### T4 · Old pipeline (v1) rebuilt with placement fixes, no API
Same June extractions, new builder and a strict validator ([STATE §2.1](../../STATE.md)):

| Part | June 2026 | After today's v1 fixes |
|---|---|---|
| SB11033 | 3/7, "PASSED" | 7/7, PASSED |
| SB11842 | 2/5, "PASSED" | 5/5, PASSED |
| A040911E | 2/5, "PASSED" | 5/5, FAILED (correctly: the disc was off-axis until F1) |
| A040921E | 2/4, "PASSED" | 3/4, FAILED (June misread an end slot as a boss) |
| SB11780 | 1/5, "PASSED" | 2/5, FAILED (turned shaft needs a revolve) |
| **Total** | **10/26, 5 false PASS** | **22/26, 0 false PASS** |

Fixes behind this: bolt circles placed, stacked bosses, fillets and chamfers on inferred edges
(they had never worked over COM, **E012**), embedded bosses reversed (**E013**), and a validator
that fails missing features and checks overall size to 1%.

### T5 · Demo plate built two ways (known answer)
A synthetic drawing (`demo/simple_plate/`) with an exact answer, built from a hand-read
extraction (no API) and from Astra's extraction:
- **Both 5/5 holes at 0.000 mm, exact bbox, 0.0% volume error.** Astra cost about $0.31.
- **Failures found:** the gate blocked a correct 2×2 grid as a "240 mm row" (**E014**), and the
  resolver dropped a plate labeled width/height (**E015**). Both fixed.

### T6 · Astra end to end through v1, 5 parts
- 18/30 features (Astra extracts *more* than June: 30 vs 26). About $2.50. After the root-cause
  fixes (T7): **23/30**.

### T7 · Failure deep dive: every failure traced to one of 6 root causes
R1 two coordinate frames on round parts · R2 geometry the schema can't express · R3 sizes named
only by fastener · R4 unlinked hole data · R5 one failure cascading (an open sketch, **E016**) ·
R6 information missing from the drawing. Fixes F1–F6 landed: one frame per round part (**E017**),
a cited fastener table (`pipeline/fasteners.py`), counterbores, callout synthesis, an in-part
gate check, and refusing to fake turned features. Full table in [STATE §3.0](../../STATE.md).

### T8 · Feature IR v2: golden plans built in CadQuery and SolidWorks
Hand-written plans, each read from the full drawing sheet:
`demo_plate`, `A040921E`, `SB11780`, `SB11033`, `A040911E`.
- **A040921E's end slot and SB11780's turned necks + keyway built correctly for the first
  time.** Neither was expressible in v1.
- **All 5 build natively in SolidWorks with every feature's volume matching the reference.**
- New SolidWorks APIs verified live: revolve, start offsets, edge-by-nearest-point. Two traps
  found and fixed (**E018**): coordinate selection is a view ray pick (it picked a hidden edge),
  and *Through All – Both* from a plane that misses the body returns nothing.

### T9 · GPT-6 Astra planner on the dev parts
Astra writes the plan from the drawing images plus its extraction, scored against the golden
plans (aligned IoU):

| Part | 1st run | After policy fixes | Holes | Calls |
|---|---|---|---|---|
| SB11033 | 0.9996 | — | 4/4 | 1 |
| A040921E | 0.997 | 0.997 | — | 1 |
| A040911E | 0.982 (1/5 holes, 4 unresolved) | **0.9989** (5/5, 0 unresolved) | 5/5 | 2 |
| SB11780 | 0.986 | 0.986 (keyway length: open question) | — | 1 |

- **Policy fixes learned on dev parts:** standard sizes and drawn symmetry count as grounded,
  and through-cuts must overshoot the surface (**E019**: SolidWorks rejects cuts that end exactly
  on a surface).

### T10 · Drawing → verified part on all 9 dev parts, compared with v1
`python ir_run.py --split dev --solidworks`, then `python ir_compare.py`, with the same extraction
for both paths:

| Part | v1 built / validator / IoU | IR questions / SolidWorks / IoU |
|---|---|---|
| A040911E | 5/6 · FAILED · 0.992 | 0 · ✅ verified · **1.000** |
| A040921E | 3/4 · FAILED · 0.988 | 1 · ✅ · **0.997** |
| SB11033 | 8/8 · PASSED · 1.000 | 1 · ✅ · 0.9996 (tie) |
| SB11780 | 2/6 · FAILED · 0.960 | 2 · ✅ · **0.986** |
| SB11842 | 5/6 · FAILED · — | 1 · ✅ · — |
| 115-C | 4/7 · FAILED · — | 1 · ✅ · — |
| 116-C | 2/5 · FAILED · — | 1 · ✅ · — |
| 117-C | 7/9 · FAILED · — | 1 · ✅ · — |
| 135-A | 1/3 · FAILED · — | 0 · ✅ · — |

- A drill-depth policy (a depth is to full diameter, per the ASME convention) cut the plate
  questions from 12 to 3.
- Prism patterns were added to the SolidWorks compiler (117-C).
- **The acceptance rule ("replace v1 where not worse") is met.** `--ir` stays opt-in until the
  team flips the default.

### T11 · Unit tests
188 → **340** passing. New test files cover the budget guard, model validator completeness,
placement, root-cause fixes, IR expressions, the IR model, both compilers, the v1→IR baseline,
the planner loop and scorer, the pipeline, and the benchmark manifest. Every test runs on any OS
with no API calls; SolidWorks behaviour is verified live and recorded in the error log.

---

## 4. Successes

1. **Verified native SolidWorks parts for all 9 dev parts**, up from one correct part. Each
   feature is checked against an independent reference, so a "built" feature that went the wrong
   way is caught and retried rather than reported as success.
2. **Geometry v1 could never express:** turned shafts with necks (revolve), through-wall slots,
   keyways, counterbores, tapped holes, bolt circles, stacked bosses, and fillets and chamfers
   with no manual edge picking (PRD A5).
3. **Placement is traceable.** Every coordinate in a plan is an expression over drawing
   dimension IDs (`D001 / 2`), or a literal with a written justification (PRD A1).
4. **Honest gaps.** Unclear callouts become specific human questions instead of guesses. The
   validator went from 5 false approvals to 0.
5. **Cost control.** A hard $20 guard reserves each call's worst case before sending it. It was
   never tripped, and spend is $11.70.
6. **Model quality.** GPT-6 Astra read the drawings well. It recovered callouts that crops hid,
   used standard fastener tables when told how, and its plans match the hand-checked answers at
   IoU 0.986–1.000.
7. **A one-command workflow:** `ir_run.py`, `main.py --drawing X --ir --engine com`, and free
   rebuilds with `--reuse-plans`.

## 5. Failures, mistakes and corrections (kept on purpose)

| What | Impact | Resolution |
|---|---|---|
| E011 SolidWorks 2025 typelib pinned to 2024 | No COM build at all | Version probing |
| E012 Fillets/chamfers never selected edges; wrong array arg types | Every fillet/chamfer skipped since June | Inferred edges, 14-arg fillet with empty Variants |
| E013 Boss embedded in the body, "built" with no material | Silent failure | Volume check, undo, reverse |
| E014 2×2 grid blocked as a 240 mm row | Correct extraction BLOCKED | Real instance extents |
| E015 Width/height plate labels dropped the base | Part not buildable | Label-pair mapping |
| E016 An open sketch cascaded one failure into the next | Extra failures | Close sketch on failure |
| E017 Round parts built off-axis; a bore cut outside the part | Wrong geometry reported as built | One frame per round part, in-part gate |
| E018 View ray pick selected a hidden edge; Through-All-Both from an empty plane | Wrong or missing IR features | Nearest-edge selection; cut from the resolved face |
| E019 Cuts ending exactly on a surface | SolidWorks rejected them | Overshoot rule in the planner |
| SolidWorks crashed once (RPC unavailable) during v1's 135-A build | Comparison run interrupted | Comparison reconnects and retries |
| **Analyst error:** I first wrote that *both* extractions misread SB11033 | Wrong claim in STATE.md | Corrected: only June's Sonnet extraction did; Astra's was right |
| **Analyst error:** A040911E first diagnosed as "mislabeled width only" | Missed a real frame bug | The deep dive found R1 |
| A turned "neck" briefly "built" as a sideways hole after the cascade fix | Fake geometry | The builder now refuses it ("needs a revolve") |
| Graphify can't run on this host | Graph stale since the initial commit | Incremental AST update (`graphify-out/ast_update.py`); full semantic refresh pending |

## 6. Pricing and cost

Source: `2D-3D-CAD-Test-Generation/usage/budget_ledger.jsonl` (gitignored, local), plus per-run
ledgers committed under `output/*/usage/`.

> **Rate basis:** the direct-OpenAI price for `gpt-6-astra` isn't confirmed in
> `config/pricing.json`, so every figure here uses the budget guard's conservative rate (the
> Azure Standard list price, **$10 input / $50 output per 1M tokens**, with cached input counted
> at the full input rate). The actual invoice may be lower. Check the OpenAI usage dashboard and
> add the real rate to `config/pricing.json` (then run `token_report --reprice`).

| Role | Calls | Input tokens | Output tokens | Cached input | Cost |
|---|---|---|---|---|---|
| Extraction | 22 | 86,030 | 90,516 | 113,491 | **$6.52** |
| Planning | 25 | 244,465 | 34,885 | 99,148 | **$5.18** |
| **Total** | **47** | **330,495** | **125,401** | **212,639** | **$11.70** |

**Per part** (all runs today, including repeats and policy iterations): A040911E $1.33 ·
117-C $1.15 · 115-C $0.92 · SB11780 $0.81 · 135-A $0.78 · 116-C $0.73 · SB11033 $0.73 ·
A040921E $0.52 · SB11842 $0.43 · untagged (early runs, before part tagging) $4.29.

**Unit economics:** extraction ≈ **$0.30 per call**; planning ≈ **$0.21 per call**; a typical
part needs 1–2 planning calls. **A new drawing → verified part costs about $0.50–1.00**, and a
rebuild of an existing plan costs $0. The whole 9-part dev run (T10) cost **$4.39**.

**Budget guard:** `pipeline/budget.py`, cap `API_BUDGET_USD` (default $20). The worst case of each
call is reserved *before* it is sent, a stop ends the run with exit code 9, and the ledger is
shared across runs. Never tripped today; **$8.30 remains**.

## 7. Decisions made today

1. **Dev/held-out split:** all 9 parts are **dev** (used for diagnosis and fixes). The held-out
   set is pending: fresh parts with MTI reference STEP, frozen by PR (`bench/manifest.yaml`).
2. **GPT-6 Astra only.** No Opus path and no model benchmark (published CAD benchmarks already
   favour Astra). PRD Goal 5 and C3/C5 are dropped; the benchmark machinery stays for measuring
   *this* pipeline.
3. **Planner policies:** trust the drawing over the extraction; full sheet before crops; standard
   sizes and drawn symmetry are grounded; through-cuts overshoot; a drill depth is to full
   diameter; never guess anything else (write a question).
4. **The IR path replaces v1 only where it isn't worse.** That is now met; flipping the default
   is a team decision.

## 8. Open questions for MTI / an engineer

| Part | Question |
|---|---|
| 115-C, 116-C, 117-C | Radius of the four rounded outline corners (drawn, not dimensioned) |
| SB11033 | Pilot-root radius to model (".015 MAX R") |
| SB11780 | Neck-root radius (".125 R MAX TYP"); ".06 C/R": chamfer or radius?; **keyway: end to end, or only along the body between the necks?** |
| A040921E | Size and form of the remaining edge breaks ("BREAK ALL SHARP CORNERS") |
| SB11842 | Size of the two bore-entrance edge breaks; does the outside chamfer callout cover them? |
| All | Confirm `pipeline/fasteners.py` (SHCS drill / counterbore chart) against MTI's shop standard |
| All | Reference STEP files, needed to score placement on held-out parts (PRD C1) |

## 9. Next steps (recommended order)

1. **Resolve-and-resume** (PRD B4/D3): turn the 9 questions into an answer file per part. An
   answer is recorded in the ledger and the part rebuilds with no API call (`--reuse-plans`).
2. **Gate 2, the auditor** (PRD B2): measure each built part against the drawing's tolerances
   (hole centers, diameters, depths from the feature map), and retry the planner with specific
   findings (≤ 2 retries).
3. **Flip the default** to the IR path in `main.py` once the team agrees.
4. **More parts:** curate `NewVerifiedDrawings/` (mislabeled views) and get MTI reference STEP to
   freeze a held-out set.
5. **Housekeeping:** confirm the OpenAI price; finish the full `/graphify` semantic refresh; emit
   VBA from the IR; compile slot/polygon profiles and circular prism patterns in SolidWorks; add CI.

## 10. Where everything is

| What | Where |
|---|---|
| Live status, root causes, results tables | `STATE.md` (§2.1, §3.0, §4.1, §4.2) |
| Runtime failures and the rules they produced | `docs/solidworks-macro-error-log.md` (E011–E019) |
| Feature IR plan and status | `docs/superpowers/plans/2026-10-04-feature-ir-v2.md` |
| Golden plans (hand-checked answers) | `2D-3D-CAD-Test-Generation/tests/golden/ir/` |
| End-to-end outputs per part (extraction, plan, STEP, SLDPRT, report) | `output/ir_runs/<part>/` |
| v1 vs IR comparison | `output/ir_runs/v1_vs_ir.md` |
| Astra's v1-path run (extractions, builds, ledger) | `output/astra_2026-10-04/` |
| Demo plate (known answer) | `demo/simple_plate/` |
| Knowledge graph (AST update today) | `graphify-out/` (`ast_update.py`, `GRAPH_REPORT.md`) |
