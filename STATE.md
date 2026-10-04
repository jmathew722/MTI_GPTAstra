# STATE.md — where mti-2d-3d stands

**Last updated:** 2026-10-04 · **Repo:** [INDL-AILOT/mti-2d-3d](https://github.com/INDL-AILOT/mti-2d-3d)
**Contributors to date:** Joe Mathew (original pipeline), Brad Sandberg (repo setup), ggould / MalteseWarrior (research direction)

> **Status: preliminary.** Everything in the next-phase sections (§4, §5) is design
> only. The current pipeline was hardened on 2026-10-04 (§1, §2.1), but the Feature
> IR, auditor loop and benchmark are not built. Review the
> [PRD](docs/PRD.md) and the specs before implementation starts.
>
> Update this file when a milestone lands, a part's status changes, or an open
> decision is made. Keep numbers sourced: link the file they came from.

---

## TL;DR

- A working **2D drawing → SolidWorks** pipeline exists (Claude vision extraction →
  arithmetic verification gate → VBA macros or direct COM build).
- **2026-10-04: placement + completeness fixes landed.** Rebuilding the same 5
  parts from their June extractions now builds **22 of 26 features (85%)**, up from
  10 of 26 (38%). Bolt-circle holes, stacked bosses, fillets and chamfers now build
  in the COM path (§2.1).
- The model validator now **fails any part missing an extracted feature**, and it
  checks overall dims at 1%. 2 of the 5 parts PASS; the other 3 FAIL for real,
  listed reasons (§2.1). In June all 5 "passed" at 38%.
- **Extraction runs on GPT-6 Astra** (OpenAI Responses API) behind a **hard $20 API
  budget guard**. A simple demo part built from Astra's reading matches the ground
  truth exactly ([demo](2D-3D-CAD-Test-Generation/demo/simple_plate/README.md)).
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
| Direct COM build | `pipeline/solidworks_builder.py` | Working on SW 2025 SP5: holes at drawing positions / bolt circles, stacked bosses, fillets + chamfers with inferred edges (E012–E013) |
| Hard API spend cap (default $20, preflight worst case, stops the run) | `pipeline/budget.py` | Working |
| Extraction on OpenAI (`gpt-6-astra`) | `pipeline/openai_adapter.py` | Working (Responses API) |
| End-to-end batch COM driver w/ auto-resolution of ambiguities + design-decision report | `run_models.py` | Working (see caveat §3.3) |
| Batch triage CSV | `pipeline/batch.py` | Working |
| Test suite (golden macro snapshots, budget, placement, completeness) | `tests/` | **228 passing** (2026-10-04, Windows, Python 3.13) |
| Per-completion token & cost tracking + report/dashboard | `pipeline/token_tracker.py`, `pipeline/token_report.py`, `config/pricing.json` | Working; wired into extraction. Planner/auditor/Jev record through the same API when built |

### Dev machine (2026-10-04)

Python 3.13 venv at `.venv` (via `uv`). SolidWorks here is **2025 SP5**
(`D:\SOLIDWORKS`, rev 33.5), not 2024. The COM build needed the constants-typelib fix (E011).
Extraction runs on `gpt-6-astra` (`EXTRACTION_PROVIDER=openai`). The direct-OpenAI price is
still `null` in `config/pricing.json`: the token report shows those rows as *unpriced*, and the
budget guard charges them at the Azure Standard rate ($10/$50 per 1M) to stay conservative.
Live API spend so far: see `usage/budget_ledger.jsonl` (gitignored).

## 2. Part inventory

### 2.1 Rebuilt 2026-10-04 (same June extractions, new builder + strict validator)

No API cost: built from `output/<Part>/<Part>_extraction.json` through
`run_models.resolve_unknowns` → gate → COM build (SW 2025) → `validate_model`.

| Part | June built | Now built | Validator | Why it still fails |
|---|---|---|---|---|
| SB11033 | 3/7 | **7/7** | PASSED | — (bbox now 1.971" long: boss stacked on flange) |
| SB11842 | 2/5 | **5/5** | PASSED | — (embedded boss reversed, E013) |
| A040911E | 2/5 | 5/5 *but wrong* | FAILED (correctly) | disc built off-center (frame bug R1), so the bore breaks through the rim; see §3.0 |
| A040921E | 2/4 | 3/4 | FAILED | June **misread** a 1.062 end slot as a "hub boss" (Astra reads it right); see §3.0 |
| SB11780 | 1/5 | 2/5 | FAILED | turned shaft: built as a bounding cylinder; necks and keyway need grooves or a revolve |
| **Total** | **10/26** | **22/26** | 2 PASS / 3 FAIL | |

### 2.2 Same 5 parts end to end on GPT-6 Astra (2026-10-04)

`run_models.py ../ViewDefinedDrawings` with `gpt-6-astra` extraction. Outputs, reports and
the token ledger are in `2D-3D-CAD-Test-Generation/output/astra_2026-10-04/`. Cost: **≈ $2.50**
for 9 calls, at the conservative budget rate (see §1). Re-queries and schema repairs added calls:
A040911E alone took 4.

| Part | Astra features | Built | Validator | What blocked the rest |
|---|---|---|---|---|
| SB11033 | 8 | **8/8** | PASSED | — |
| A040921E | 4 | 3/4 | FAILED | side-plane rectangular end slot: cut found no material |
| A040911E | 6 | 3/6 | FAILED | counterbores as separate cuts (no profile); holes with no diameter link; cropped callout |
| SB11780 | 6 | 2/6 | FAILED | keyway and necks need revolve/side-plane sketches the builder lacks |
| SB11842 | 6 | 2/6 | FAILED | thru bore cut found no material; bolt holes not grounded; cbores as separate cuts |
| **Total** | **30** | **18/30** | 1 PASS | |

**Reading vs. building.** Astra's extractions are *richer* than June's: 30 features vs
26, with keyways, necks, separate counterbore cuts and edge breaks. The builder can't
express most of those yet. So June JSON + new builder = 22/26, while Astra JSON + the
same builder = 18/30. The bottleneck is now the **build/IR side**, not reading. That is
the argument for Feature IR v2 (§4 A). Counterbores, keyways, revolves and side-plane cuts
are the concrete gap list.

On a simple synthetic plate with a known answer, both a hand-read (no API) extraction
and Astra's build a part that matches the ground truth exactly
([demo](2D-3D-CAD-Test-Generation/demo/simple_plate/README.md)).

Still flagged as assumptions in each build (never silent): `EDGES INFERRED` for every
fillet/chamfer, `ANGLE ASSUMED` for bolt circles without explicit positions, and
`DIRECTION ASSUMED` for reversed bosses. Stepped bores (SB11033 F002) are cut at one diameter only.

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

### 3.0 Failure deep dive (2026-10-04)

Every failure from §2.1 and §2.2 was traced to its root cause from the extraction
JSON, the build report and, where the two readings disagreed, the drawing itself.
Each one falls into one of six root causes.

**Root causes**

| # | Root cause | Kind | Seen in |
|---|---|---|---|
| R1 | **Two coordinate frames on round parts.** An unplaced circle is centered on the "envelope" (length/width dims), while a placed one sits at the origin. On a round part the envelope is meaningless, so the base lands off-axis. The extraction already says these features are coaxial (`concentric_groups`), but the builder ignores it. Astra also mixes frames *inside one callout*: `x/y_position` (0, 0) center-based, `instance_positions` [2.5, 2.5] corner-based. | builder + schema (PRD "Schema" gap) | A040911E (June: bore breaks out of the disc), SB11780 (shaft at x = 38.44"), SB11842 Astra (bore cut at (2.5, 2.5), outside the disc, so it hits nothing), A040921E Astra (bore callout at (5.25, 5.25)) |
| R2 | **The builder can't express the feature.** Counterbores, keyways, circumferential necks/grooves, through-wall slots and revolves have no profile the current schema can carry (e.g. "slot from the bore to the OD" is `D002/2 .. D001/2`, an expression). | IR gap | A040911E F004, SB11842 F004 (cbores as separate cuts), SB11780 F002–F004, A040921E F003 (slot), SB11780 (base should be a revolve) |
| R3 | **Required data is not on the callout.** "DR. & C'BORE FOR .250 SOC. HD. CAP SCR." gives the screw, not the drill or cbore size; those come from the standard fastener table. Astra correctly marked them UNKNOWN (June's Sonnet guessed .272 / .3438). | missing standard lookup | A040911E F003/F004, SB11842 F003/F004 |
| R4 | **Hole data not linked.** Astra put bolt-circle data on the *feature* (pitch-circle dim, quantity, positions in the description) but emitted no `hole_callout` for it, so the resolver sees "no grounded position" and drops it. | resolver | SB11842 F003, A040911E F003 |
| R5 | **Builder left a sketch open on failure.** When a feature fails after `InsertSketch`, the sketch stays open, and the next feature's `InsertSketch` *closes* it, so the next feature fails too ("Failed to enter sketch mode"). One failure cascades. | builder bug | SB11780 Astra F003 (after F002 failed) |
| R6 | **Genuinely unknown or ambiguous on the drawing.** A cropped callout (A040911E F005, 2 holes) or an unspecified size ("edge breaks", "R .125 MAX"). The correct outcome is an escalation with a specific question, not a guess. | escalate (PRD B1/B4) | A040911E F005, SB11842 F006, SB11780 F005 |

Reading errors are a separate class. June's Sonnet extraction **misread** A040921E's
1.062 × .75 end slot as a "hub boss" and labeled A040911E's ±2.75 equatorial hole
offset as `overall_width`. Astra read both correctly. The strict validator caught
both downstream; the old one passed them.

**Per failure**

| Part · feature | Run | Symptom | Root cause | Fix |
|---|---|---|---|---|
| A040911E F001/F002 | June | bbox 165 × 150.7 (disc not round) | R1 + mislabeled 2.75 | concentric-group frame (F1) |
| A040911E F003/F004 | Astra | "no diameter" / cbore cut without profile | R3 + R4 + R2 | fastener table (F4), callout synthesis (F3), counterbore in hole builder (F5) |
| A040911E F005 | Astra | 2 holes, callout cropped | R6 | escalate: correct as-is; needs a better scan |
| A040921E F003 | June | hub boss dropped | reading error | Astra already right; prompt + overlay review (B6) |
| A040921E F003 | Astra | slot cut hits no material | R2 (`planar_extents` paired slot width with an *axial* 2.25) | IR v2 through-wall slot (A1/A3) |
| SB11780 base | both | single cylinder at x = 38.44" | R1 + R2 | F1 now; revolve in IR v2 |
| SB11780 F002 keyway | Astra | no rectangle profile | R2 | IR v2 slot/keyway |
| SB11780 F003/F004 necks | Astra | "Failed to enter sketch mode" | R5 (cascade) + R2 | F2 now; groove = annulus cut with start offset |
| SB11842 F002 bore | Astra | cut found no material | R1 (bore at (2.5, 2.5)) | F1 + in-part position check (F6) |
| SB11842 F003/F004 | Astra | holes "not grounded", cbores no profile | R4 + R3 + R2 | F3 + F4 + F5 |
| SB11842 F006, SB11780 F005 | Astra | size unspecified | R6 | escalate (B1/B4) |

**Fix plan**

Fixes F1–F6 work on today's pipeline. F7–F8 need the PRD sub-projects.

| Fix | What | Root causes | Effort | PRD |
|---|---|---|---|---|
| F1 | **One frame per round part.** If the base is a circle, the part center is the origin. Features in a `concentric_group` with the base take its center. Never center a circle on length/width dims of a round part. | R1 | S | A2 |
| F2 | **Close any open sketch when a feature fails** so one failure can't cascade. | R5 | XS | A5 |
| F3 | **Synthesize a hole callout from the feature** (pitch/bolt-circle dim + quantity, or offsets) when the extractor gave none. | R4 | S | A3 |
| F4 | **Fastener clearance table** (drill, cbore Ø, cbore depth for SHCS sizes; ASME B18.3 / Machinery's Handbook). Values are marked `STANDARD-DERIVED` and cited, never silent. | R3 | S | A1 (a cited table is a grounded source) |
| F5 | **Counterbore in the hole builder:** a second blind cut at the cbore Ø. Merge a cbore-only `extrude_cut` (coaxial, depth only) into its parent hole. | R2 (part) | M | A3 |
| F6 | **Gate check: every hole instance must lie inside the base profile.** On failure, try the other frame (center vs corner); if neither fits, BLOCK with a finding. | R1 | S | B1 |
| F7 | **Feature IR v2:** profiles as expressions (slot `D002/2..D001/2`), start face + into-material direction, revolves, grooves, keyways, edges by query. | R2 | L | A1–A5 |
| F8 | **Escalation, not guessing,** for R6 cases, with the question pre-written ("2-hole callout is cropped: diameter?"). | R6 | M | B1, B4, D3 |

Prompt changes (both models): state the frame rule for round parts (center = origin;
`instance_positions` in the same frame as `x/y_position`); sketch an end slot on the plane
where its outline is drawn; keep a counterbore on its hole callout, not as a separate cut.

### 3.1 Placement
- Bolt circles now place automatically from instance positions or a bolt-circle dim
  (2026-10-04). Stacked bosses follow dimension chains.
- The remaining placement bugs are R1 (frames on round parts) and R4 (unlinked hole data).

### 3.2 Fillets & chamfers
- COM: built on edges inferred from `parent_feature` (E012), flagged `EDGES INFERRED`.
  It can't pick ONE side when only one is meant (SB11033 F006). That needs edge
  queries (A3/A5).
- VBA: still interactive (the user pre-selects edges).

### 3.3 Verification
- Fixed 2026-10-04: the validator fails missing features and checks overall dims at 1%.
- Still open: `run_models.py` auto-accepts best guesses for `resolution_required` dims.
  That is useful for throughput but bypasses the gate. Each such decision is logged, not
  re-checked. The R6 cases should escalate instead (F8).

### 3.4 Unimplemented
- Revolves, grooves, keyways, slots defined by expressions (IR v2, F7).
- COM checkpoint resume.
- The VBA generator does not yet use the COM path's new placement and edge logic.

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
- No CI yet. The suite is green locally (228 tests), so the workflow can be re-added.
- Stray code-root files `extraction_115C/116C/117C.json` duplicate the `output/` copies.
- `Deliverables/` duplicates `output/` for the 5 built parts.
- `.SLDPRT` binaries are committed to git (no LFS).
- Prices now live in `config/pricing.json` (Opus 5.5, Sonnet 5/5.5, Astra on
  Foundry, Jev, ...), and the new tracker marks unknown prices *unpriced* instead of
  guessing. Still open: the legacy `usage_log.record_run` summary keeps its Sonnet
  fallback for unknown models; the Bedrock and direct-OpenAI prices are `null` until
  confirmed. (The `.env.template` model hint was fixed 2026-10-04.)

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
