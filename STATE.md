# STATE.md — where mti-2d-3d stands

**Last updated:** 2026-11-18 · **Repo:** [jmathew722/MTI_GPTAstra](https://github.com/jmathew722/MTI_GPTAstra)
(independent copy, forked from the original `INDL-AILOT/mti-2d-3d` at `eea7e45` on 2026-11-15)
**Contributors to date:** Joe Mathew (original pipeline), Brad Sandberg (repo setup), ggould / MalteseWarrior (research direction)

> **2026-11-18: four-stage reliability program (branch `Improvements`)** — gate reports in `docs/test-reports/2026-11-18-stage{1,2,3}-gate-report.md`.
> - **Stage 1, truthful telemetry (done, tested):** versioned `[gptastra-event]` stream + `run_events.jsonl`, progress from
>   observable work units (never time, never backward), per-run/part/session cost scopes from the pipeline ledger, server and UI reducers.
> - **Stage 2, UI (done, tested):** exact backend percent + operation/unit count, **Part cost** chip in the top bar, full cost Results
>   (attempts, cache, pricing status), drawer sized from real measurements (no 70% cap), standalone Results without caps.
>   Real parts are **unpriced** because `gpt-6-astra` has no rate in `config/pricing.json`; the UI says so instead of showing $0.00.
> - **Stage 3, automatic flags (done, tested; one limit):** findings -> automatic locator (text layer / OCR, calibrated threshold, honest
>   "not located") -> overlay artifact + annotated PDF -> linked viewer/Results with review state. No human positions anything. Limit: the
>   viewer shows page 1 of the saved overview only.
> - **Stage 4, Hole Wizard (partial, NOT verified):** provenance review, registry of all **9 families / 81 variants** pinned to the installed
>   type library, callout parser (+ corpus inventory). **No variant is `verified`.** Hole Wizard creation does not work through the API in
>   this SolidWorks session (E037: `HoleWizard5` refused, `InitializeHole` blocks, `IHoleStandardsData` empty; Student Edition, cause
>   unconfirmed). Not done: IR + migration, catalog resolver, creation adapters, placement policy, readback, callout round trip, matrix.
>   See `docs/hole-wizard/support-status.md`.
> - Tests: Python 1162 passed / 66 skipped (baseline 1019); FINAL_UI server 48; UI unit 150/153 and Playwright 31 pass / 13 fail, both
>   with the **same pre-existing failures as the pre-change commit** (missing `part_full.log` fixture; stale tests after the rebrand).
>
> **2026-11-05: every sketch is fully defined, Hole Wizard placement sketches included** (E035).
> They are tied to the origin without adding a hole point, then dimensioned.
> - All 37 audit builds rebuilt: every part verifies, 145/145 sketches fully defined. $0.
>
> **2026-11-02 (later): fine-tuning started.**
> - **Automatic discrepancy analysis** (`mti_discrepancy.py`) explains each part's gap to MTI's
>   model.
> - **Drawing markups** with OCR-placed boxes (`mti_markup.py`, rapidocr) for 21 parts; local only.
> - **Two measured rules:**
>   - D9: two-place prints of 1/16" fractions on plates. **A00122E 0.9865 → 1.0000**; A00121E →
>     0.99999.
>   - D8: general notes on every eligible edge. **2N2664 → 0.9980.**
> - **E034:** checked, serial booleans make scores trustworthy.
> - $0. Tests 1018 passed. Test report `docs/test-reports/2026-11-02-test-report.md`.
>
> **2026-11-02: MTI demo ready** (`docs/demo/2026-11-02-mti-demo-runbook.md`, $0 replay).
> - Hero: the 2N2664 re-plan, a turned hub with Hole Wizard taps, a radial cross-hole at 240°
>   and one honest question. IoU **0.9957** vs MTI's own model.
> - Backup: A00122E (19/19 built, 0.21 mm max).
> - E033: the reference now uses a fuzzy boolean (exact OpenCascade over-cut a radial hole);
>   neutral on all other references.
> - Ledger $47.54 of $50.
>
> **2026-10-28 (free fixes):** taps and their pilot drills are now merged into ONE Hole Wizard tap
> (SB12006/07/09/10/11, 2N2664; all verify). `mti_score` reports `iou_clocked` for turned parts.
> **All 23 DWG audit drawings are converted to PDF** (bench `dwg_to_pdf`) and MTI's models
> exported: ready to run, ~$17 of extraction needed. 4C1229's 0.938 is not clocking (corrected).
> $0. Test report §10.
>
> **2026-10-28 (radial holes): holes drilled into the outside of turned parts now build** in the
> reference and in SolidWorks (`wall(F, r)` start, `u` = angle; spec
> `2026-10-28-radial-holes-design.md`; E032).
> - Verified live, including handedness: a chiral test part gives IoU 1.000 under proper
>   rotations only.
> - SB12095's radial taps are now built (vs MTI 0.9985).
> - SB12059, SB12054 and 2N2664 need a re-plan to use the angle. $0. Test report §9.
>
> **2026-10-28 (all PDF parts): all 38 PDF audit parts run, all build and verify** ($7.52; ledger $46.68 of $50).
> - New parts SB12011, SB12055, SB12053, SB12054 and SB12059 match MTI at IoU 0.990–0.9999.
> - **MTI's SB12050 and SB12051 models are swapped in Drive:** each of our parts matches the other
>   folder's model at IoU 1.000 / 0.996.
> - SB12059 is four collet pads by design; the final check now covers every body (E031).
> - The SB11488 re-plan builds all holes, but its central profile is still unread (noisy scan).
> - Test report 2026-10-28 §8.
>
> **2026-10-28 (later): callout defaults.** Vague callouts are now built by documented rules instead of
> being skipped (`pipeline/ir/defaults.py`; values measured from MTI's own models; switch:
> `MTI_CALLOUT_DEFAULTS=0`).
> - Covers ".030 R MAX", "C/R", "BREAK ALL SHARP CORNERS" and a tap with a thread depth only.
> - Unresolved features: **36 → 16**; 11 parts fully resolved.
> - All 11 rebuilt parts verify; no score went down (SB12006 → 1.000, 2N2664 → 0.993). $0.
> - Test report 2026-10-28 §7.
>
> **2026-10-28: the two worst audit scores are MTI model-vs-drawing differences, not pipeline
> errors.** SB14306: MTI's model uses bores that aren't on the drawing (a Ø10 web bore where the
> drawing has Ø6.00); ours matches the drawing. A00161E: MTI's end radius is 3.036 where the drawing
> has 3.00 R; a 0.9 mm offset on a 1.5 mm sheet reads as IoU 0.29. Fixed on the way:
> - the cone-rim fillet query (SB14306 F003);
> - the loose `GetBodyBox` in the final check, now `GetExtremePoint` (E030);
> - `mti_score.py` now reports surface deviation in mm.
>
> **SB14306 now builds with 26/28 features.** Merged smcanuff's benchmark scorer from `main`; this
> branch's error-log entries were renumbered E028/E029. $0. Tests 976 passed, 66 skipped. Test report
> [2026-10-28](docs/test-reports/2026-10-28-test-report.md).
>
> **2026-10-26 (latest): all 31 audit parts run now build and verify.** E029 fixed three CadQuery
> reference bugs (through-tapped holes, trimmed cylinders, seam edges): 4C1229 builds (IoU 0.938 vs
> MTI) and SB14306 gets its 8 tapped holes. $0. Test report §9.
>
> **2026-10-26 (later): slots and circular prism patterns now compile (E028), so 30 of 31 audit
> parts build and verify** (A00155E and SB14306 fixed, $0). Test report §8.
>
> **2026-10-26 (batch 2, $40 cap): 31 audit parts run; 28 build and verify; 23 of 28 match MTI's
> own models at IoU ≥ 0.979.** Two misses are MTI drawing-vs-model mismatches (SB12050, SB12009).
> Next fixes, all free: slot profiles, circular prism patterns, 4C1229. **Budget: $39.16 of $40.**
> Test report §7.
>
> **New (2026-10-26): MTI's parts audit as an answer key.** MTI's Drive holds 63 parts with both a
> drawing and MTI's own model (`bench/mti_test_set.csv`). First batch of 10: **all 8 that ran build
> and verify; 7 of 8 match MTI's model at IoU ≥ 0.985** (two at 1.000). The 8th, SB12050, matches its
> drawing (2.12") but MTI's model is 3.5", a question for MTI. Polygon base outlines fixed. MTI's
> turned parts put the origin at an end face, not the center (to change). **API budget: $19.35 of $20;
> raise it to continue** (~$40 for the remaining 53). Record:
> [docs/test-reports/2026-10-26-test-report.md](docs/test-reports/2026-10-26-test-report.md).
>
> **2026-10-25: Benchmark scorer + stage blame built (sub-project 2 of 3).** `python -m bench.score
> <run_dir>` (spec [2026-10-24-benchmark-scorer-design](docs/superpowers/specs/2026-10-24-benchmark-scorer-design.md))
> exports the SolidWorks part to STEP, reads its features and scores it 0-100 against the signed key,
> with the drawing as ground truth. How it works:
> - **Matching:** best of 24 orientations; the shift is bounded by the envelope difference, so a uniformly
>   shifted hole set is an error; Hungarian matching.
> - **Credit:** full within tolerance, 0.5 just past it, then decay.
> - **Weights:** tier x size. Base body 10; thru holes 5; bores, turned diameters and planar features 3;
>   small holes 2; edges 1.
> - **Penalties:** extras cost half their weight. Drawing-wins overrides apply.
> - **Blame:** every lost point goes to ground_truth / unsupported / extraction / **unresolved** (planner
>   left it unbuilt as uncertain) / planner / cadquery / solidworks.
> - **Report:** `scores.json` + `report.html`; each part also lists what the pipeline left unbuilt as uncertain.
>
> Tests, all $0:
> - 978 tests; all 19 real parts score exactly 100 against their own model, under rotation and translation.
> - Planted errors (moved / filled / extra holes, cbore→plain, mirror) cost exactly what the curve predicts.
> - 2 strict xfails: keygen reads A050071E / A050061E differently upside down; fixing it needs a re-key.
>
> Calibrated with the user (`python -m bench.calibrate`):
> - A hole 5x out of tolerance costs about 1.5-3 points; a missing hole about 3-7.
> - One body extent 3x off costs about 6-16 points.
>
> Trial run on the 4 golden parts (SW 2025 parts, $0):
> - A040911E, A040921E and SB11033 score 100; SB11780 scores 81.6 (the planner ran its flats the full bar
>   length, 78.64 vs 73.093 in).
> - SolidWorks reproduced every plan exactly.
> - Lesson: golden plans skip features marked unresolved, so they are not complete answer keys. The A040921E
>   and SB11033 keys had to be corrected against the drawings.
>
> Keys: A050481E (inner step 0.098), A050031E (.500-13) and A050031M (M12) now carry drawing-wins value
> overrides; `bench.prep link` recorded drawing values + tolerances on all 19.
>
> **2026-10-25 (later): MTI practices score (spec 2b) built.**
> - **What:** a separate 0-100 practices column, never blended with geometry. It covers checks C1-C7: origin
>   centered, Top/Mid Plane base, fully defined sketches, edge ops last, 2D Hole Wizard sketches, one Hole Wizard
>   per size per face, and no avoided features. Each failed check is blamed on the planner or SolidWorks.
> - **Where it reads:** the SLDPRT feature tree (`bench/sw_tree.py`, cached as `feature_tree.json`, existing
>   APIs only), plus `ir_report.json` (C1/C2, self-reported) and `plan.json` (C6).
> - **Big problems:** the five practices the pipeline breaks by design are kept out of the score and recorded in
>   [docs/mti-practices-big-problems.md](docs/mti-practices-big-problems.md).
> - **Golden parts:** mean practices score 84.6. Three of the four put a fillet or chamfer before a cut (C4).
> - **Validation on MTI's own models was limited.** The 15 simple-part SLDPRTs MTI delivered have **no feature
>   history** (one body; the tree is material, planes and origin only; last saved in SW 2025). Only the 3
>   complex models could be checked: 1801901 100, 1807408 100, 1901001E 83 (2 of 6 sketches under-defined).
>   So MTI doesn't always fully define its own sketches.
> - **Ask MTI** for native models with history for the simple parts.
>
> Next: sub-project 3 (paid official run on the 15 held-out parts). Branch `feat/mti-benchmark`, local only.
>
> **2026-10-24: Benchmark dataset built (sub-project 1 of 3).** MTI's 2026-10-11 delivery of
> 150 legacy DWGs and 26 models gave 21 drawing-model pairs. `bench/` (spec
> [2026-10-23-benchmark-dataset-design](docs/superpowers/specs/2026-10-23-benchmark-dataset-design.md))
> converted them into PDFs, DXFs and reference STEPs, generated an answer key per part, cross-checked
> each key against its drawing, and signed it off. **19 benchmark parts: 4 format dev
> (A050311E, A050381E, A050381M, A050511E) and 15 held-out.** The original dev set was all plates, so
> a seeded swap (seed 20261024) traded round part A050311E into dev for plate A050291E. All 19 are signed: 10 auto, 9 by
> smcanuff. 2 are parked: 1801901E (MTI model is 4 solids) and 1807408E (model differs from the
> drawing). **Policy (user): the drawing is the ground truth.** Model-vs-drawing differences are
> kept and recorded as `drawing-wins` / `drawing-silent` flag resolutions that the scorer must
> honour (e.g. A050411E draws 12 countersinks, model has 8). Data lives outside git in
> `MTI_BENCH_DATA` (`.env`). Feature profile: no type above 30%. After the swap, format dev has
> holes, taps, counterbores, a bore and a turned diameter, but no slots, pockets, flats, chamfers,
> fillets or countersinks (4 parts can't cover every type). New error log entries: E026 (silent save) and E027 (a
> makepy cache broke COM byref calls). Next: sub-project 2 (placement-aware scorer + stage blame),
> then 3 (the official run). Branch `bench/dataset`, local commits only.
>
> **2026-10-12 (later): Phase 2c. Sketches are fully defined** with SolidWorks' Fully Define Sketch,
> dimensioned from model edges, with exact relations only: **29/30 dev-set sketches fully defined**,
> 9/9 dev parts verified, 405 tests (error log E023). The golden re-run was cut short by SolidWorks
> (86 parts left open, E024; fixed: parts now close after saving). **Re-run the golden plans in a
> fresh SolidWorks session.** Test report §8–9.
>
> **2026-10-12: MTI Phase 2b. Every bolt hole MTI's way.** Tapped holes are Hole Wizard
> taps with **cosmetic threads**. Blind ones end in the real 118° drill point, credited exactly
> in the check. **A hole and its pattern are one feature** on a construction bolt circle, line or
> rectangle (7 Hole Wizard features, 17 holes on the dev set). Still 9/9 dev and 5/5 golden
> verified, $0, 403 tests. Record:
> [docs/test-reports/2026-10-12-test-report.md](docs/test-reports/2026-10-12-test-report.md),
> error log E022. Next: fully defined sketches (last Phase 2 item).
>
> **2026-10-11: MTI's modeling standards are in the workflow.** After the demo, MTI's
> lead engineer sent their modeling practices, feature guide, macros and hole standard
> (Std 202.02.0003). Every SolidWorks part now has its base body **centered on the origin**,
> its base sketch on the **Top plane** (Mid Plane for plates), and **Up To Next** through
> holes. All 9 dev parts and 5 golden plans still build and verify ($0). A deterministic
> review proposes Hole Wizard sizes from MTI's own table, which is kept local because it is
> confidential. What MTI asked for, item by item, with status:
> [docs/mti-modeling-standards.md](docs/mti-modeling-standards.md). Record:
> [docs/test-reports/2026-10-11-test-report.md](docs/test-reports/2026-10-11-test-report.md).
> **Phase 2a, same day:** bolt holes (clearance and SHCS counterbore) are now real **Hole Wizard**
> features sized from MTI's standard (13 features, 25 holes on the dev set). Identical holes on a
> face share one feature, and the result is still 9/9 verified ($0; test report §8, error log E021).
> Next: tapped holes with cosmetic threads, and fully defined sketches (rest of Phase 2 in the
> [design](docs/superpowers/specs/2026-10-11-mti-modeling-standards-design.md)), and 6 questions for MTI
> (test report §6).
>
> **Status (2026-10-05):** sub-project A (Feature IR v2) is **built and running end to end**
> on all 9 dev parts (§4.2). The v1 pipeline was also hardened (§2.1, §3.0). Not built yet:
> sub-project B's Gate 2 auditor and its resolve-and-resume loop, a held-out benchmark set
> (needs MTI reference STEP), and D (the MCP connector). Work is on branch
> `feat/openai-extractor-sw2025` (pushed; not yet merged to `main`). The full record of the
> 2026-10-04 test day: [docs/test-reports/2026-10-04-test-report.md](docs/test-reports/2026-10-04-test-report.md).
>
> Update this file when a milestone lands, a part's status changes, or an open
> decision is made. Keep numbers sourced: link the file they came from.

---

## TL;DR

> **Full record of the 2026-10-04 test day** (every test run, success, failure, cost and
> decision): [docs/test-reports/2026-10-04-test-report.md](docs/test-reports/2026-10-04-test-report.md).
>
> **As of end of day 2026-10-04:** all 9 dev parts go drawing → GPT-6 Astra extraction + plan →
> CadQuery reference → native SolidWorks with every feature verified (§4.2). IR ≥ v1 on every
> scored part (IoU 0.986–1.000); 9 open human questions; 340 tests pass; API spend $11.70 of
> the $20 cap. Model: GPT-6 Astra only.

- A working **2D drawing → SolidWorks** pipeline exists (Claude vision extraction →
  arithmetic verification gate → VBA macros or direct COM build).
- **2026-10-04: placement + completeness fixes landed.** The same 5 parts now build
  **22/26 (85%)** from the June extractions and **23/30 (77%)** from GPT-6 Astra's,
  up from 10/26 (38%) in June. Every remaining failure is either geometry the schema
  can't express (→ Feature IR v2) or information missing from the drawing (→ escalate).
  See §2.1 and the deep dive in §3.0.
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
| Test suite (golden macro snapshots, budget, placement, completeness, root-cause fixes) | `tests/` | **243 passing** (2026-10-04, Windows, Python 3.13) |
| Per-completion token & cost tracking + report/dashboard | `pipeline/token_tracker.py`, `pipeline/token_report.py`, `config/pricing.json` | Working; wired into extraction. Planner/auditor/Jev record through the same API when built |

### Dev machine (2026-10-04)

Python 3.13 venv at `.venv` (via `uv`). SolidWorks here is **2025 SP5**
(`D:\SOLIDWORKS`, rev 33.5), not 2024. The COM build needed the constants-typelib fix (E011).
Extraction runs on `gpt-6-astra` (`EXTRACTION_PROVIDER=openai`). The direct-OpenAI price is
still `null` in `config/pricing.json`: the token report shows those rows as *unpriced*, and the
budget guard charges them at the Azure Standard rate ($10/$50 per 1M) to stay conservative.
Live API spend so far: see `~/.mti-2d-3d/budget_ledger.jsonl` (outside the repo; moved 2026-10-05 after the in-repo copy was wiped, then restored exactly from the per-run ledgers: 47 calls, $11.70).

## 2. Part inventory

### 2.1 Current results (2026-10-04, after fixes F1–F6)

No API cost: every saved extraction is rebuilt with
`python rebuild_from_json.py <extraction.json ...>` (resolve, gate, COM build on
SW 2025, strict validator). Two readings of the same 5 parts:

| Part | June read: built | Validator | Astra read: built | Validator | What is left (root cause, §3.0) |
|---|---|---|---|---|---|
| SB11033 | **7/7** | PASSED | **8/8** | PASSED | — |
| SB11842 | **5/5** | PASSED | 5/6 | FAILED | Astra: bore-edge chamfer size not on the drawing (R6, escalate) |
| A040911E | 5/5 | FAILED | 5/6 | FAILED | June: mislabeled `overall_width` 2.75 (reading error, caught by validator). Astra: 2-hole callout cropped on the scan (R6, escalate) |
| A040921E | 3/4 | FAILED | 3/4 | FAILED | end slot through the ring wall needs expression profiles (R2, IR v2). June also misread it as a boss |
| SB11780 | 2/5 | FAILED | 2/6 | FAILED | turned shaft: necks, keyway and journals need revolve/grooves (R2, IR v2); refused rather than faked (F6b) |
| **Total** | **22/26 (85%)** | 2 PASS | **23/30 (77%)** | 1 PASS | every remaining gap is R2 (IR) or R6 (human) |

Progress on the same 5 parts: June 2026 built **10/26** and "PASSED" all 5. Earlier today,
Astra's read built 18/30. Fixing R1/R3/R4/R5 took it to 23/30, and one gate-blocked part
(A040911E) now builds. The geometry also got *more correct*, which completeness alone
doesn't show: A040911E's disc is round again (bbox 165 × 165, was 165 × 150.7).

**Reading vs. building.** Astra's extractions are richer (30 vs 26 features). It got two
things right that June's Sonnet misread, and it writes UNKNOWN instead of guessing. The
builder, not the reading, is the limit. Astra cost ≈ $2.50 for 9 calls on these 5 parts
(conservative rate); the outputs are in `output/astra_2026-10-04/`.

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

**False PASS found 2026-10-04 (IR golden-plan work).** SB11033 "PASSED" in v1 from
**June's (Sonnet) extraction**, which misread the part. It had a Ø.781 "pilot boss" (.781
is the bolt-circle *radius*) and a Ø.686 through bore (the section is fully hatched: there
is no bore; Ø.686 is a pilot). That extraction was internally consistent, so completeness,
bbox and the gate all passed it. **Only a reference model can catch a self-consistent
misread.** That makes MTI reference STEP (PRD C1) a hard requirement, not a nice-to-have.
*Correction (later the same day):* this section first said both extractions misread it.
**GPT-6 Astra's extraction read SB11033 correctly**, and v1 built from it scores IoU 1.0
against the golden plan.

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

| Fix | What | Root causes | PRD | Status |
|---|---|---|---|---|
| F1 | **One frame per round part.** A circular base defines the part center. Features in a `concentric_group` take a placed member's center. Never center a circle on the length/width dims of a round part. | R1 | A2 | ✅ done (E017) |
| F2 | **Close any open sketch when a feature fails** so one failure can't cascade. | R5 | A5 | ✅ done (E016) |
| F3 | **Synthesize a hole callout from the feature** when the extractor gave none. Only with a known diameter; otherwise `ESCALATE`. Also: n holes through ONE placed hole when the other instances reproduce the drawing's own dims (`_circle_from_seed`). | R4 | A3 | ✅ done |
| F4 | **Fastener table** (`pipeline/fasteners.py`: SHCS drill, cbore Ø, cbore depth). Values are marked `STANDARD-DERIVED` and cited. A value read from the drawing is never overwritten. | R3 | A1 | ✅ done; **verify table vs MTI shop standard** |
| F5 | **Counterbore in the hole builder** (second blind cut). A cbore-only `extrude_cut` is folded into its parent hole. The cbore face is flagged `CBORE FACE ASSUMED`. | R2 (part) | A3 | ✅ done |
| F6 | **Gate: every hole instance must lie inside the base profile.** Positions written in the other frame are corrected (`FRAME CORRECTED`). If neither frame fits, BLOCK. | R1 | B1 | ✅ done |
| F6b | **Refuse, don't fake:** a large circular cut on a side plane of a turned part is a neck/groove. The builder refuses it ("needs a revolved cut"); extruding it would drill a sideways hole. | R2 | A3 | ✅ done |
| F7 | **Feature IR v2:** profiles as expressions (slot `D002/2..D001/2`), start face + into-material direction, revolves, grooves, keyways, edges by query. | R2 | A1–A5 | next (sub-project A) |
| F8 | **Escalation with a pre-written question** for R6 cases. Today these are `ESCALATE` lines in the design-decisions report. | R6 | B1, B4, D3 | partial |

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
- No CI yet. The suite is green locally (243 tests), so the workflow can be re-added.
- Stray code-root files `extraction_115C/116C/117C.json` duplicate the `output/` copies.
- `Deliverables/` duplicates `output/` for the 5 built parts.
- `.SLDPRT` binaries are committed to git (no LFS).
- Prices now live in `config/pricing.json` (Opus 5.5, Sonnet 5/5.5, Astra on
  Foundry, Jev, ...), and the new tracker marks unknown prices *unpriced* instead of
  guessing. Still open: the legacy `usage_log.record_run` summary keeps its Sonnet
  fallback for unknown models; the Bedrock and direct-OpenAI prices are `null` until
  confirmed. (The `.env.template` model hint was fixed 2026-10-04.)

## 4. Next phase — designed 2026-09-28; A built 2026-10-04

### 4.2 End to end on all 9 dev parts: IR vs v1 (2026-10-04, Task 8)

One command per part: `python ir_run.py --split dev --solidworks` (or `main.py --drawing X --ir
--engine com`). Same extraction for both paths. v1 was exported to STEP and both were scored
against the golden plans where they exist (`ir_compare.py` → `output/ir_runs/v1_vs_ir.md`).

| Part | v1 built | v1 validator | v1 IoU | IR Gate 1 | IR planned | IR questions | IR SolidWorks | IR IoU |
|---|---|---|---|---|---|---|---|---|
| A040911E | 5/6 | FAILED | 0.992 | OK | 7 | 0 | ✅ verified | **1.000** |
| A040921E | 3/4 | FAILED | 0.988 | OK | 3 | 1 | ✅ | **0.997** |
| SB11033 | 8/8 | PASSED | 1.000 | OK | 6 | 1 | ✅ | 0.9996 (tie) |
| SB11780 | 2/6 | FAILED | 0.960 | OK | 2 | 2 | ✅ | **0.986** |
| SB11842 | 5/6 | FAILED | — | OK | 5 | 1 | ✅ | — |
| 115-C | 4/7 | FAILED | — | OK | 6 | 1 | ✅ | — |
| 116-C | 2/5 | FAILED | — | OK | 5 | 1 | ✅ | — |
| 117-C | 7/9 | FAILED | — | OK | 13 | 1 | ✅ | — |
| 135-A | 1/3 | FAILED | — | OK | 3 | 0 | ✅ | — |

- **IR is never worse** (SB11033 is a tie within 0.0004) **and is the only path that delivers a
  verified part for all 9.** v1 passes 1 of 9. Every remaining IR gap is a written question for
  a human: undimensioned corner radii, "R MAX", "C/R", "TYP" edges.
- **The plan's acceptance rule ("replace v1 where not worse") is met.** `--ir` stays opt-in until
  the team agrees to flip the default.
- **Cost:** a full drawing → part run is about $0.2–0.5 per part (planning), plus about $0.5 for a
  part not yet extracted. The whole dev set cost $4.39; total API spend is **$11.70 of $20**.
- **Policy added from the plates:** a blind drill depth is to full diameter (ASME convention),
  so it's planned, not asked. This cut plate questions from 12 to 3.
- SolidWorks crashed once mid-comparison on v1's 135-A build. `ir_compare.py` now reconnects.

### 4.1 Feature IR v2 status (2026-10-04)

**Model decision: GPT-6 Astra only. No Opus-vs-Astra benchmark** (user decision, PRD updated).

Astra *plans* each dev part from the drawing images plus its extraction, and the plan is
compiled to a CadQuery reference and then to native SolidWorks (`python ir_plan.py <parts>`,
`python ir_build.py output/ir_plans*/<P>/plan.json --solidworks`):

| Dev part | IoU vs golden plan | Holes | Unresolved (human questions) | SolidWorks (verified per feature) | Planner cost |
|---|---|---|---|---|---|
| SB11033 | **0.9996** | 4/4 | 1 (.015 MAX R) | ✅ | $0.22 |
| A040911E | **0.9989** | 5/5 | 0 | ✅ | $0.45 |
| A040921E | **0.997** | — | 1 (.09 TYP edges) | ✅ | $0.17 |
| SB11780 | 0.986 | — | 2 (R MAX, C/R) | ✅ | $0.21 |

- SB11033: Astra's extraction was already correct (solid pilot, Ø1.000 shaft). The misread
  extraction was June's Sonnet one (see §3.0).
- **Open drawing question for MTI:** does SB11780's keyway run end to end (Astra) or only along the
  body between the necks (golden plan)? That one call is the whole IoU gap.
- **Prompt policy learned on dev parts:** standard fastener and tap-drill sizes and drawn symmetry are
  *grounded*, so they're planned and flagged, not unresolved; through-cuts overshoot (E019).
- **API spend to date:** $6.66 of the $20 cap.

### 4.0 What today's results mean for the PRD (2026-10-04, for discussion)

1. **Held-out contamination (C4). Needs a decision.** The PRD's *proposed* held-out set
   is exactly the 5 parts we developed against today. The fixes are general rules
   (frames, fastener standards, counterbores), not per-part prompt tuning. Even so,
   these parts are no longer clean held-out data. **Recommendation:** make these 5 the
   **dev** set (they already have the most diagnostics). Choose the held-out set from
   parts MTI can supply reference STEP for, and fix the split in `bench/manifest.yaml`
   *before* any prompt work. The prompt changes in §3.0 are proposed, **not applied**,
   for this reason.
2. **Targets vs. today.** Measured on these 5 parts with no reference STEP, so
   completeness and false approvals only:

   | PRD metric | Target | Today |
   |---|---|---|
   | Feature completeness | ≥ 95% | 85% (June read) · 77% (Astra read) |
   | False approvals | 0 | 0 on these 5 (the validator caught a misplaced build) |
   | Fillets/chamfers without manual picking | ≥ 90% | built on *inferred* edges where a parent exists; not yet "by edge query" (A3/A5) |
   | Placement / relative placement / exact-part | 90% / 90% / 60% | **not measurable** without reference STEP (C1). The scorer itself works: the demo plate scores 5/5 at 0.000 mm |

3. **What's left is now cleanly split:** every remaining failure is either geometry
   the schema can't express (R2: slot, keyway, necks/revolve, one-sided edges) or
   something not on the drawing (R6: cropped callout, unspecified sizes). That is the
   case for **sub-project A**, and it gives A a data-driven scope: revolve + groove,
   through-wall slot as expressions, keyway, start face (counterbore face), edge
   queries. **R6 is the case for B's escalation path:** the questions already exist as
   `ESCALATE` lines; B4/D3 turn them into a resolve-and-resume loop.
4. **Model evidence so far (anecdotal, not the benchmark).** Astra reads more (30 vs 26
   features). It got A040921E's slot and A040911E's ±2.75 holes right where June's Sonnet
   misread them. It writes UNKNOWN instead of guessing (R3). Cost: ≈ $0.19–0.33 per call
   (conservative rate), up to 4 calls on a hard part. **Opus 5.5 has not been run yet.**
   It needs `tool_choice: auto` (CLAUDE.md rule 10), and C3 needs both models.
5. **PRD edits to propose:** platform text says "SolidWorks 2024", but the dev host is
   2025 SP5 and works (E011). The retry-cap open question now has data (4 calls on
   A040911E; the $20 guard bounds the total). C2 should also count *refused* features
   (F6b) separately from missing ones, since a refused feature is honest and a fake one isn't.

Umbrella: [AI CAD roadmap](docs/superpowers/specs/2026-09-28-ai-cad-roadmap-design.md).
Build order A → B → C → D. Each gets an implementation plan before code.

| | Sub-project | Spec | Status |
|---|---|---|---|
| A | **Feature IR v2** + CadQuery (reference) & SolidWorks compilers. The LLM fills a typed build plan whose every coordinate is an expression over drawing dimension IDs | [feature-ir-v2](docs/superpowers/specs/2026-09-28-feature-ir-v2-design.md) · [plan](docs/superpowers/plans/2026-10-04-feature-ir-v2.md) | **In progress (2026-10-04).** Done: expressions, BuildPlan + Gate-1 checks, CadQuery reference compiler, `plan_from_v1` baseline, and the SolidWorks compiler, checked against the reference feature by feature. **5 golden dev plans (demo plate, A040921E, SB11780, SB11033, A040911E) build in CadQuery AND natively in SolidWorks with every feature matching**; ambiguous callouts stay unresolved for a human. `python ir_build.py tests/golden/ir/*.json --solidworks`. Next: the planner (Task 7, first API spend), then the dev-set comparison (Task 8) |
| B | **Auditor loop + Jev.** Gate 1 (plan) + Gate 2 (measured geometry); deterministic checks can't be overruled; full rejection history in a JSONL ledger; 2 retries per gate, then escalate. Jev handles only discrete text decisions, never numbers | [auditor-loop](docs/superpowers/specs/2026-09-28-auditor-loop-design.md) | Design approved. Gate 1 (deterministic checks + repair retries) is **built** into the planner. Gate 2, Jev and the resolve-and-resume loop are **next** |
| C | **Benchmark**, scored against MTI reference STEP files on placement, relative placement, dimensions and completeness. ~~Opus 5.5 vs GPT-6 Astra arms~~: **dropped 2026-10-04**, GPT-6 Astra only. The benchmark now measures *this pipeline* | [placement-benchmark](docs/superpowers/specs/2026-09-28-placement-benchmark-design.md) | Split fixed in `bench/manifest.yaml` (9 dev parts; held-out pending MTI STEP). Dev-set scorer built (`pipeline/ir/score.py`) |
| D | **MCP connector** for the team's Claude IDE; core server on any OS + a SolidWorks worker on Windows | roadmap §D | Placeholder |

Key decisions:
- The deliverable is **both, staged**: a CadQuery/STEP reference, then native
  SolidWorks checked against it.
- The LLM output is a **constrained IR**, not free-form code.
- Ground truth is **MTI reference models**.
- The pipeline is **evolved in place**.
- **Model: GPT-6 Astra only** (decided 2026-10-04; published CAD benchmarks favour it).
- **Hosting is still open:** [AWS](docs/PRD-aws.md) (Bedrock + AgentCore) vs
  [Azure](docs/PRD-azure.md) (Foundry + Azure Functions). Both host GPT-6 Astra; the code
  stays the same apart from the provider backend.

Why BenchCAD isn't enough: Astra's 95.9% (Opus 5 82.1%, Fable 5.1 84.3%) is scored
by volume IoU and Chamfer distance, which barely penalize a misplaced hole.

## 5. Prerequisites the next phase needs

- ~~Install requirements and confirm the suite is green~~ Done: 405 tests pass (2026-10-12).
- ~~API access~~ Done: OpenAI (`gpt-6-astra`) key in `.env`; $20 budget guard ($8.30 left).
  A Jev key is still needed for B7.
- ~~A Windows + SolidWorks machine~~ Done: SolidWorks 2025 SP5 on the dev host.
- ~~Hand-checked answers for dev parts~~ Done: 5 golden plans in `tests/golden/ir/`.
- **Still needed: MTI reference STEP** for a held-out set (PRD C1), answers to the 9 open
  engineering questions (test report §8), and confirmation of the OpenAI price.
- ~~A check of the fastener table against MTI's shop standard~~ MTI supplied Std 202.02.0003
  (2026-10-11). It is used locally from `config/mti/*.local.json`, which is gitignored and confidential.
  **Still needed:** the source document, to verify our screenshot transcription, plus answers to the
  6 MTI questions (2026-10-11 test report §6).

## 6. Where to look

| Question | Look at |
|---|---|
| How do I run it / what are the rules? | [CLAUDE.md](CLAUDE.md) |
| How does MTI want parts modeled? | [docs/mti-modeling-standards.md](docs/mti-modeling-standards.md) |
| Why is the generator written this way? | [docs/solidworks-macro-error-log.md](docs/solidworks-macro-error-log.md) |
| Original design | [docs/superpowers/specs/2026-06-11-2d-to-3d-solidworks-pipeline-design.md](docs/superpowers/specs/2026-06-11-2d-to-3d-solidworks-pipeline-design.md) |
| Repo structure / cross-file connections | [graphify-out/GRAPH_REPORT.md](graphify-out/GRAPH_REPORT.md), `graphify-out/graph.html` |
| Schema (the contract) | `2D-3D-CAD-Test-Generation/pipeline/schema.py` |


## Stage 4 update (2026-11-18)

Offline chain built and tested (1208 passed): hole-intent IR + migration, catalog resolver, typed adapter with readback, placement policy,
CadQuery reference, acceptance-matrix generator/runner, loud (not silent) plain-cut substitution. 47 of 81 variants are
`implemented_not_live_verified`, 34 `not_implemented` (10 legacy, 24 slots). **No variant is `verified`**: the live matrix is blocked at preflight
(`InitializeHole` never returns on this SolidWorks 2025 Student session; E037), and the Hole Callout round trip is not implemented.
See `docs/hole-wizard/support-status.md` and `matrix-results.json`.

## Stage 4 update, SOLIDWORKS 2025 gate (2026-11-18, branch Improvements_2)

* **Root cause of E037 found (E038):** the running SOLIDWORKS 2025 SP5 (33.5) is configured to use the **2026** Hole Wizard data root
  (database **29.01**, Toolbox 34.3.2); 2025 expects **28.00**, and a 2025 root (`SOLIDWORKS Data (2)`, database 28.00) exists unused. The causal
  link to the `InitializeHole` hang is inferred, not demonstrated (not tested by repointing: that changes SOLIDWORKS configuration).
* **Environment gate** (`pipeline/ir/solidworks/sw_preflight.py`, `tools/sw_preflight.py`): revision 33.x, database version, Toolbox index family, modal
  dialogs, catalog, timeout. Live result `docs/hole-wizard/preflight-result.json`: **`HW_DATABASE_VERSION_MISMATCH`**. The compiler no longer calls
  `HoleWizard5` in that state (loud plain cut / strict failure); the live matrix starts no child process.
* **`HoleIntentV2`**, multi-line callout grouping, tolerances, NPT/decimal threads, the five regression fixtures (`tests/test_hole_callouts_fixtures.py`),
  catalog cache + ranked matching, 2025 status vocabulary (47 `SUPPORTED_BY_ADAPTER_NOT_INSTALLED`, 34 `UNSUPPORTED_WITH_REASON`, 0 verified),
  Advanced Hole / Hole Series as separate domains (Hole Series: `BLOCKED_BY_CONFIRMED_SOLIDWORKS_2025_LIMITATION`, re-checked against the type library),
  `hole_verify.py`, and Hole Wizard findings (`hole_findings.py`) that the automatic drawing markup places from their source callouts.
* **Owner action to unblock live verification:** select the 2025 data root in SOLIDWORKS 2025 (Tools > Options > System Options > Hole Wizard/Toolbox), restart,
  then `python tools/sw_preflight.py` and `python tools/run_hole_wizard_matrix.py --live`. Still not implemented: the drawing Hole Callout round trip,
  slot creation, Advanced Hole creation.

## Stage 3 fix: automatic Engineering Markup (2026-11-18, branch `Improvements_2`)

`run_part` now ends with `pipeline/engineering_markup.py::finalize_markup` (before the terminal run event): findings, page-aware
localization, a flattened multi-page marked PDF with a label rail, PNG previews and `engineering_markup.json` (`not_needed | ready |
partial | failed`). The API serves it at `/api/parts/{s}/{p}/engineering-markup[.pdf|/page/{n}.png]`; the viewer opens
`Engineering Markup` automatically and links every flag card to its page and region. Distinct from the human `full_marked_view.jpg`.
Evidence: `docs/test-reports/2026-11-18-stage3-markup-gate-report.md`. Python 1279 passed / 66 skipped; markup e2e 6/6.


## Stage 4 live verification on SOLIDWORKS 2025 (2026-11-19, branch `Improvements_2`)

With the user's go-ahead the Hole Wizard folder preference was repointed to the 2025 data root (error log E039); preflight is `ready` and the
live matrix ran. **13 of 81 variants are `SUPPORTED_AND_LIVE_VERIFIED`** (creation, definition readback, volume against an independent reference,
save/reopen, drawing Hole Callout round trip): hole blind/thru, counterbore blind/thru, countersink without head clearance blind/thru, cosmetic taps
blind/thru, counterbore slot blind/thru, plain slot blind, countersink slot blind/thru. 2 pipe taps are created and read back but their tapered
geometry has no reference yet. 56 are `failed_verification` with the exact mismatch recorded (near/mid/far countersink treatments, head-clearance
countersinks, plain taps, plain through slot); 10 legacy have no adapter. Advanced Hole: element data and face selection work, `AdvancedHole2` still
reports incorrect parameters; Hole Series: no creation API. See `docs/hole-wizard/support-status.md` and `matrix-results.json`.

## SolidWorks build recording: "Record Pipeline Run" (2026-11-19, branch `Improvements_2`)

Design: `docs/superpowers/specs/2026-11-19-solidworks-recording-design.md`; report: `docs/test-reports/2026-11-19-solidworks-recording-report.md`.
A checkbox under "Force fresh extraction" (Run options) records only the SolidWorks window, only during the native build, to
`<part>/solidworks_recording.mp4` (+ `.json` manifest, `_poster.jpg`), shown in Pipeline Results -> Build & Verification -> "SolidWorks recording"
(player, 1x/2x/4x, feature chapters that seek, download; partial/failed/skipped/stale/interrupted states say why). Backend: Windows Graphics Capture
(records the one window even when covered); fallback: screen rectangle with a privacy gate (covered frames are dropped). CLI: `--record-solidworks`.
Recordings are gitignored. Tests: `tests/test_solidworks_recorder.py` (16), `FINAL_UI/tests/server/test_app_recording.py` (11),
`tests/unit/recordingview.test.js`, `tests/e2e/tests/24-solidworks-recording.spec.ts` (5).
