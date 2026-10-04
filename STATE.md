# STATE.md — where mti-2d-3d stands

**Last updated:** 2026-10-04 · **Repo:** [INDL-AILOT/mti-2d-3d](https://github.com/INDL-AILOT/mti-2d-3d)
**Contributors to date:** Joe Mathew (original pipeline), Brad Sandberg (repo setup), ggould / MalteseWarrior (research direction)

> **Status: preliminary.** Everything in the next-phase sections (§4, §5) is design
> only. No pipeline code or infrastructure has changed yet. Review the
> [PRD](docs/PRD.md) and the specs before implementation starts.
>
> Update this file when a milestone lands, a part's status changes, or an open
> decision is made. Keep numbers sourced: link the file they came from.

---

## TL;DR

- A working **2D drawing → SolidWorks** pipeline exists (Claude vision extraction →
  arithmetic verification gate → VBA macros or direct COM build).
- **Dimension reading is good; feature placement is not.** Across the 5 parts
  built to `.SLDPRT`, only **10 of 26 extracted features were built** (38%).
  Holes on bolt circles/patterns, fillets and chamfers are the main losses.
- The model validator reports **PASSED on all 5** despite that, because it only
  checks bounding box / volume. There is currently **no check that fails an
  incomplete part** — this is the most important gap.
- Next phase is **designed, not built** (§4): a Feature IR with CadQuery +
  SolidWorks compilers, an **auditor agent with retries**, a **Jev decision
  layer**, and a **placement-aware benchmark** (Opus 5.5 vs GPT-6 Astra).

---

## 1. What works today

| Capability | Where | Status |
|---|---|---|
| Image/PDF prep (resize, contrast, invert, PDF→PNG) | `utils/image_prep.py` | Working |
| Single-image extraction (forced tool call, Pydantic repair retry, prompt + disk cache) | `pipeline/extractor.py` | Working |
| Multi-view extraction (front/top/side/…, one call, per-view plane assignment) | `pipeline/extractor.py`, `pipeline/view_ingest.py` | Working |
| Verification gate: dimensional closure, unit consistency, pattern feasibility, readiness score | `pipeline/validator.py` | Working |
| VBA macro package (00_setup … ZZ_final_verify, RUN_ALL, PASS/FAIL log, stop-on-fail) | `pipeline/macro_generator.py` | Working; exercised on real SW for 135-A |
| Static macro audit (banned APIs, structural defects) — fails generation | `pipeline/macro_audit.py` | Working |
| Direct COM build | `pipeline/solidworks_builder.py` | Working on Windows + SW2024 |
| End-to-end batch COM driver w/ auto-resolution of ambiguities + design-decision report | `run_models.py` | Working (see caveat §3.3) |
| Batch triage CSV | `pipeline/batch.py` | Working |
| Test suite (10 files, golden macro snapshots) | `tests/` | **188 passing** (2026-10-01, Windows, Python 3.13) |
| Per-completion token & cost tracking + report/dashboard | `pipeline/token_tracker.py`, `pipeline/token_report.py`, `config/pricing.json` | Working; wired into extraction. Planner/auditor/Jev record through the same API when built |

### Dev machine (2026-10-04)

Python 3.13 venv at `.venv` (via `uv`); **195 tests pass**. SolidWorks here is
**2025 SP5** (`D:\SOLIDWORKS`, rev 33.5), not 2024. The COM build works after fixing the
pinned constants typelib (error log E011): SB11033 rebuilt with the same result as in June.
Extraction now runs through `EXTRACTION_PROVIDER` (default **openai**, model `gpt-6-astra`)
via `pipeline/openai_adapter.py`; not yet exercised against the live OpenAI API.
Direct-OpenAI `gpt-6-astra` price in `config/pricing.json` is still `null` (rows show as unpriced).

## 2. Part inventory

### Built to `.SLDPRT` via `run_models.py` (COM, 2026-06-18)

Source: `2D-3D-CAD-Test-Generation/output/<Part>/<Part>_design_decisions.txt`

| Part | Readiness | Built | Skipped (tried, failed) | Not attempted | Validator |
|---|---|---|---|---|---|
| A040911E | 89% | 2 (F001, F002) | F005 chamfer | F003, F004 | PASSED |
| A040921E | 93% | 2 (F001, F002) | F004 chamfer | F003 | PASSED |
| SB11033 | 96% | 3 (F001, F003, F002) | F007 fillet, F005/F006 chamfer | F004 (4× bolt-circle holes) | PASSED |
| SB11780 | 90% | 1 (F001) | — | F002–F005 | PASSED |
| SB11842 | 94% | 2 (F001, F002) | F004 chamfer | F003, F005 | PASSED |

Copies for hand-off are in `2D-3D-CAD-Test-Generation/Deliverables/`.
Note: `output/multiview_summary.csv` still shows A040921E as **BLOCKED**
(closure failure D004 = D005). The later `run_models.py` run auto-resolved it by
dropping the chain. Both records exist; the CSV is stale.

### VBA macro packages (not built to `.SLDPRT` in-repo)

| Part | Status | Notes |
|---|---|---|
| 135-A | READY | Run on a real SolidWorks machine; source of error-log entries E001–E007 |
| 115-C RevB | READY | Extraction JSON hand-patched (E009); duplicate report file with a space in its name |
| 116-C Rev90B | READY | Hand-patched (E009, E010) |
| 117-C RevB | READY | Hand-patched (E009, E010); 14-hole callout collapses unless re-extracted with `instance_positions` |

Source drawings for these four are in `DrawingPDFs/`: A001131E = 117-C
(check valve adaptor), A001151E = 116-C (check valve eliminator), A001171E =
115-C (check bypass), A001351E = 135-A (key). The three 90B parts are one plate family.

### Drawings not yet processed

- `NewVerifiedDrawings/` — 12 parts (0014630E, 16247, A001211E, A001271E,
  A001291E, A001561E, A001581E, A001591E, A001601E, A001621E, A001821M, A001901E).
  Several are missing a front or side view.

> ⚠️ **Data-quality problem in `NewVerifiedDrawings/` — curate before use.**
> Files named `<part>_front_view` / `<part>_side_view` are often **not views of
> that part**. They look like separate detail components cropped from
> multi-detail sheets. Confirmed by eye (2026-09-28):
> - `A001291E_front_view` is a 6.00×3.50 three-hole plate. `A001291E_side_view`
>   is a 21.00×6.00 slotted plate, the same drawing as `A001581E_side_view`.
> - `A001601E` is a 7.000×4.500 notched plate with 13 holes.
>   `A001601E_side_view` is a Ø5.00 round flange.
>
> Flagged by the graph-extraction pass, not yet eyeballed:
> - `0014630E_front_view` ≈ `A001271E_side_view` (sheet-metal shroud).
> - `0014630E_side_view` contains a profile ≈ `16247`.
> - `A001621E_front_view` ≈ `A001821M_side_view`, and `A001621E_side_view` ≈ `A001821M`.
> - `A001591E_front_view` (small bushing) ≠ `A001591E` (long bar).
> - `A001901E`'s three images disagree with each other.
>
> Feeding these folders to `run_models.py` merges unrelated components into one
> part. Each image needs a manual label (which part, which view, or "separate
> detail") before it is extracted or used as benchmark data. `ViewDefinedDrawings/`
> (5 parts) did not show this problem.

**No ground-truth 3D models are in the repo.** Any benchmark needs reference
geometry or a hand-verified dimension/placement key per part (see §5).

## 3. Known gaps & failure modes

### 3.1 Placement (the core problem)
- Bolt-circle and circular patterns are never auto-placed: they're recorded as a
  note, and the holes are left for manual work (every SB/A04 part).
- Features not referenced from the origin get `POSITION ASSUMED`. Bosses are built
  coaxially with no axial offset modeled (SB11033 F003).
- Past extraction errors in this class: symmetric chains missing a term, 2×2 grids
  read as linear rows, wrong part number (E009).

### 3.2 Fillets & chamfers
- `FeatureFillet3` / `InsertFeatureChamfer` return `None` in the COM path (no edge
  selection). In VBA they're interactive (the user pre-selects edges). Neither path
  is automated yet.

### 3.3 Verification is too lenient
- `model_validator.validate_model` passes a part that is missing most of its
  features.
- `run_models.py` auto-accepts the best guess for `resolution_required` dimensions
  and drops non-closing chains so the build "never fails". Good for throughput,
  but it bypasses the READY/BLOCKED gate. Every such decision is only
  *logged* in the design-decisions file, never re-checked.

### 3.4 Unimplemented
- Revolves and feature-level patterns are TODO skeletons (`needs_review`).
- COM checkpoint resume.
- Open watch-list items in the error log (FullyDefineSketch arg shape, unit
  system application, cbore face).

### 3.5 Doc / repo drift

Fixed 2026-09-28:
- Added a root `README.md`.
- `.gitignore` now blocks every `.env` / `.env.*` at any depth. Verified that no
  `.env` or API key was ever committed.
- The error log's CI entry is annotated: `.github/workflows/tests.yml` does
  **not** exist, so there is **no CI yet**.
- The 2026-06-11 spec is annotated: its v1 body (`claude-opus-4-8` +
  `messages.parse`) is superseded by the v2 summary (`claude-sonnet-4-6` + forced
  tool call).

Still open (fix when touched):
- No CI yet. The suite is green locally (188 tests), so the workflow can be re-added.
- Stray code-root files `extraction_115C/116C/117C.json` duplicate the `output/` copies.
- `Deliverables/` duplicates `output/` for the 5 built parts.
- `.SLDPRT` binaries are committed to git (no LFS).
- Prices now live in `config/pricing.json` (Opus 5.5, Sonnet 5/5.5, Astra on
  Foundry, Jev, ...), and the new tracker marks unknown prices *unpriced* instead of
  guessing. Still open: the legacy `usage_log.record_run` summary keeps its Sonnet
  fallback for unknown models; the Bedrock and direct-OpenAI prices are `null` until
  confirmed; the `.env.template` model hint is still `claude-opus-4-8`.

## 4. Next phase — decided 2026-09-28 (designs written, no code yet)

Umbrella: [AI CAD roadmap](docs/superpowers/specs/2026-09-28-ai-cad-roadmap-design.md).
Build order A → B → C → D. Each gets an implementation plan before code.

| | Sub-project | Spec | Status |
|---|---|---|---|
| A | **Feature IR v2** + CadQuery (reference) & SolidWorks compilers. The LLM fills a typed build plan whose every coordinate is an expression over drawing dimension IDs | [feature-ir-v2](docs/superpowers/specs/2026-09-28-feature-ir-v2-design.md) | Design approved, next up |
| B | **Auditor loop + Jev.** Gate 1 (plan) + Gate 2 (measured geometry); deterministic checks can't be overruled; full rejection history in a JSONL ledger; 2 retries per gate, then escalate. Jev handles only discrete text decisions, never numbers | [auditor-loop](docs/superpowers/specs/2026-09-28-auditor-loop-design.md) | Design approved |
| C | **Benchmark: Opus 5.5 vs GPT-6 Astra**, scored against MTI reference STEP files on placement, relative placement, dimensions and completeness (IoU only for comparability). Arms: raw vs. audited, plus a fixed-read ablation | [placement-benchmark](docs/superpowers/specs/2026-09-28-placement-benchmark-design.md) | Design approved |
| D | **MCP connector** for the team's Claude IDE; core server on any OS + a SolidWorks worker on Windows | roadmap §D | Placeholder |

Key decisions:
- The deliverable is **both, staged**: a CadQuery/STEP reference, then native
  SolidWorks checked against it.
- The LLM output is a **constrained IR**, not free-form code.
- Ground truth is **MTI reference models**.
- The pipeline is **evolved in place**.
- **Hosting is still open:** [AWS](docs/PRD-aws.md) (Bedrock + AgentCore) vs
  [Azure](docs/PRD-azure.md) (Foundry + Azure Functions). Both clouds host Opus 5.5
  and GPT-6 Astra; the code stays the same apart from the provider backend.

Why BenchCAD isn't enough: Astra's 95.9% (Opus 5 82.1%, Fable 5.1 84.3%) is scored
by volume IoU and Chamfer distance, which barely penalize a misplaced hole.

## 5. Prerequisites the next phase needs

- ~~Install requirements and confirm the suite is green~~ Done 2026-10-01: 188 tests pass.
- A **ground-truth key** for a benchmark set: per part, the true dimensions and
  feature positions (hand-verified from the drawing, or measured from a reference
  `.SLDPRT` made by an engineer).
- API access: Anthropic (Opus 5.5) and OpenAI (`gpt-6-astra`), plus a Jev key.
- A Windows + SolidWorks 2024 machine for build-level scoring.

## 6. Where to look

| Question | Look at |
|---|---|
| How do I run it / what are the rules? | [CLAUDE.md](CLAUDE.md) |
| Why is the generator written this way? | [docs/solidworks-macro-error-log.md](docs/solidworks-macro-error-log.md) |
| Original design | [docs/superpowers/specs/2026-06-11-2d-to-3d-solidworks-pipeline-design.md](docs/superpowers/specs/2026-06-11-2d-to-3d-solidworks-pipeline-design.md) |
| Repo structure / cross-file connections | [graphify-out/GRAPH_REPORT.md](graphify-out/GRAPH_REPORT.md), `graphify-out/graph.html` |
| Schema (the contract) | `2D-3D-CAD-Test-Generation/pipeline/schema.py` |
