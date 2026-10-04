# SolidWorks Macro Error Log

A living log of every error hit while running pipeline-generated VBA macros in
SolidWorks, the root cause, the fix, and the **generator rule** adopted so the
same class of error never ships again. Add a new entry every time a macro
fails on a real machine.

How to use: when a macro errors, record it here FIRST, then fix
`pipeline/macro_generator.py` (never just the one generated file), add a
regression test in `tests/test_macro_generator.py`, and regenerate the package
with `python main.py --from-json <part>_extraction.json --output ./output`.

---

## E001 — "No default part template configured in SolidWorks"

- **Date:** 2026-06-12 · **Part:** 135-A · **Macro:** `00_setup.vba`
- **Symptom:** Macro stops immediately; no part is created.
- **Root cause:** `swApp.GetUserPreferenceStringValue(swDefaultTemplatePart)`
  returns "" on machines where Tools > Options > Default Templates was never
  set (fresh installs, school VDI images).
- **Fix:** `FindPartTemplate()` helper — search the configured Document
  Templates folders, then standard `C:\ProgramData\SOLIDWORKS\SOLIDWORKS
  20xx\templates` locations, for `Part.prtdot` (or any `.prtdot`).
- **Generator rule:** never trust a user preference to be set; always have a
  filesystem-discovery fallback.
- **Test:** `test_setup_discovers_template_when_default_unset`

## E002 — "Could not select Front Plane"

- **Date:** 2026-06-12 · **Part:** 135-A · **Macro:** `01_F001` (and all feature macros)
- **Symptom:** `SelectByID2("Front Plane", "PLANE", ...)` returns False.
- **Root cause:** Plane names are template- and language-dependent ("Front",
  "Plane1", localized names). Selecting by hard-coded name is brittle.
- **Fix:** `SelectRefPlane(name, index)` helper — tries name variants, then
  falls back to the index-th `RefPlane` in the feature tree (Front=1, Top=2,
  Right=3 in every standard template).
- **Generator rule:** never select reference geometry by a single hard-coded
  name; always provide a position-in-tree fallback.
- **Test:** `test_feature_macros_select_planes_robustly`

## E003 — Holes placed outside the material (caught in review, not at runtime)

- **Date:** 2026-06-12 · **Part:** 135-A · **Macro:** `01_F001` + `02_F002`
- **Symptom:** Plate sketched as a CENTERED rectangle at the origin
  (x: -1.5..+1.5) while hole positions from the drawing are edge-referenced
  (x = 0.5, 2.5) — one hole entirely outside the material.
- **Root cause:** Two coordinate frames mixed: drawings dimension feature
  positions from part edges; the generator modeled the base plate centered on
  the origin.
- **Fix:** DRAWING FRAME convention — base plate lower-left corner at the
  origin (`CreateCornerRectangle`), so edge-referenced positions are sketch
  coordinates directly. Unplaced holes center on the plate envelope, not the
  origin.
- **Generator rule:** one coordinate frame for everything: part corner at the
  origin, all positions edge-referenced, exactly like the drawing.
- **Test:** `test_base_plate_uses_drawing_frame_corner_rectangle`,
  `test_pattern_emits_qty_circles`

## E004 — Runtime error on `swModel.GetModelBoundingBox()`

- **Date:** 2026-06-12 · **Part:** 135-A · **Macro:** `01_F001` (VerifySolidBody), `ZZ_final_verify`
- **Symptom:** VBA runtime error 438 (object doesn't support this method)
  right after the extrude succeeded.
- **Root cause:** `GetModelBoundingBox` does not exist on `IModelDoc2` — it
  was an invented API. The Python COM path had the same bug, silently masked
  by try/except.
- **Fix:** read the box from the solid body itself: `IBody2::GetBodyBox`
  (documented, stable). Fixed in `VerifySolidBody`, `ZZ_final_verify`, and
  `pipeline/model_validator.py`.
- **Generator rule:** every API call in generated VBA must be verified against
  documentation or a recorded macro — "sounds right" methods are banned. A
  regression test fails the build if `GetModelBoundingBox` reappears.
- **Test:** `test_no_nonexistent_bounding_box_api`

## E005 — "Feature creation returned Nothing - check the sketch" (FeatureCut4)

- **Date:** 2026-06-12 · **Part:** 135-A · **Macro:** `02_F002`
- **Symptom:** `FeatureCut4` returns `Nothing`; both hole circles sketched fine.
- **Root causes (any of):**
  1. Through-All cut aimed away from the material — body extruded to the other
     side of the sketch plane, so the cut traverses empty space and SolidWorks
     refuses the feature.
  2. Relying on the *implicit* selection of the just-closed sketch for the
     feature call instead of selecting it explicitly.
  3. Mixed old/new macro state: part built with the old centered-plate `01`
     plus the new corner-frame `02` puts a circle fully outside the material
     (see E003). Always rebuild from `00` with one consistent macro set.
- **Fix:**
  - Capture the sketch name before closing; explicitly
    `SelectByID2(sketchName, "SKETCH", ...)` before every feature call.
  - Thru cuts use `swEndCondThroughAllBoth` (reaches material on either side).
  - If a cut still returns Nothing, reselect the sketch and retry once with
    the direction flipped.
- **Generator rule:** cuts must be direction-proof and selection-explicit;
  never depend on which side of the sketch plane the body happens to be.
- **Test:** `test_cuts_are_direction_proof`

## E006 — "Could not select the profile sketch" (01 and 02)

- **Date:** 2026-06-12 · **Part:** 135-A · **Macro:** `01_F001`, `02_F002`
- **Symptom:** After closing the sketch, `SelectByID2(sketchName, "SKETCH", ...)`
  returns False — the E005 fix's name-based reselection was itself unreliable
  (`ISketch` name lookup is not a dependable way to re-find a closed sketch).
- **Root cause:** Fighting the API instead of following it. SolidWorks' own
  macro recorder NEVER closes and reselects a sketch — it calls the feature
  method while the sketch is still ACTIVE, and the feature call consumes it.
- **Fix:** Adopt the recorded-macro pattern: draw, `ClearSelection2`, call
  `FeatureExtrusion3`/`FeatureCut4` directly on the active sketch. No closing
  `InsertSketch`, no name lookup anywhere. The cut-retry fallback re-finds the
  sketch by feature-tree type (`GetTypeName2 = "ProfileFeature"`), by object,
  never by name.
- **Generator rule:** generated VBA mirrors what the macro recorder emits —
  when a workaround needs a name lookup, that's the wrong workaround.
- **Test:** `test_features_consume_active_sketch`, `test_cuts_are_direction_proof`

## E007 — F003 pattern demanded manual work it didn't need

- **Date:** 2026-06-12 · **Part:** 135-A · **Macro:** `03_F003`
- **Symptom:** MsgBox "apply manually if not already covered" — but `02_F002`
  had already cut both instances, so there was never anything to do.
- **Root cause:** The generator emitted the manual-pattern skeleton without
  checking whether the parent hole feature's cut already produced every
  instance (qty circles in one sketch).
- **Fix:** `_pattern_covered_by()` — when the pattern's parent feature has a
  hole callout with qty >= pattern quantity, emit a verified no-op macro that
  logs PASS and requires no clicks. Manual skeleton only remains for patterns
  that genuinely aren't covered.
- **Generator rule:** never ask the user to do something the build plan can
  prove is already done.
- **Test:** `test_pattern_covered_by_hole_cut_is_a_noop_pass`

## E008 — Pipeline crash printing the verification report (Windows console)

- **Date:** 2026-06-12 · **Part:** 117-C · **Stage:** Phase 1 (not a macro error)
- **Symptom:** `UnicodeEncodeError: 'charmap' codec can't encode '→'` —
  the extraction succeeded (and was paid for) but the run died printing "→"
  to a cp1252 console, before macros were generated.
- **Fix/workaround:** run with `PYTHONUTF8=1`. The extraction was lost because
  `debug_extraction.json` is only written with `--debug` (and is overwritten
  by every run).
- **Rule:** always run the pipeline with `PYTHONUTF8=1` and `--debug` on
  Windows; copy `debug_extraction.json` to a per-part name immediately after
  each run. TODO (code): save the extraction into the output folder even when
  BLOCKED, and force UTF-8 in main.py.

## E009 — Verification BLOCKED on all three remaining drawings

- **Date:** 2026-06-12 · **Parts:** 115-C, 116-C, 117-C · **Stage:** Phase 1 gate
- **Symptoms & resolutions (by human review of the actual PDFs):**
  1. *Incomplete symmetric chains* (115-C, 117-C): extractor wrote
     `total = offset + span`, omitting the second (symmetric) edge offset.
     Fixed: `offset + span + offset` (e.g. .625 + 3.190 + .625 = 4.44).
  2. *Bogus "chains"* (116-C): single-component containment relations
     (`2.38 contains 1.88`) emitted as dimension chains. Removed.
  3. *2×2 grids misread as linear patterns* (116-C, 117-C): "4 holes, spacing
     1.88" — actually a rectangular 2×2 pattern; a linear row of 4 would span
     past the plate. Removed the equal-spacing note.
  4. *Illegible text resolved from the drawing* (117-C): D024 "C7/4N or 7/16"
     is the handwritten "¼ RM. PF." callout → 0.25; D031 → 7/16 (0.4375).
  5. *Wrong part number* (117-C): extractor took MODEL NO. box ("90 B")
     instead of the part number ("117-C").
- **Rule:** BLOCKED is workable — patch the saved extraction JSON against the
  real drawing and regenerate with `--from-json` (no API cost). Always verify
  hole-pattern notes against the envelope and chains against symmetry.

## E010 — Base plate unscriptable: verbose `applies_to` labels

- **Date:** 2026-06-12 · **Parts:** 116-C, 117-C · **Stage:** macro generation
- **Symptom:** `01_F001: profile needs a diameter or length+width; got
  ['overall_height', 'overall_width', 'part_thickness']` — the generator
  matches `applies_to` exactly ("length"/"width"/"thickness"); the extractor
  emitted free-text labels. 116-C's F001 was also wired to the hole-pattern
  dim (2.38) instead of the plate envelope (3.25 × 2.75 × 1.5).
- **Fix:** normalized `applies_to` on the envelope dims and rewired F001's
  `related_dimensions`/`depth_dimension_id` in the extraction JSONs.
- **Rule:** envelope dims must carry canonical `applies_to` values. TODO
  (code): tighten the extraction prompt/schema to enforce canonical labels,
  or add fuzzy key normalization in `_dims_map` (careful: "cbore_depth"
  contains "depth").

---

## v3 hardening — resolved code TODOs & new institutional guards (2026-06-16)

These close the open code TODOs from E008/E010 and turn the per-error "generator
rules" into automated guards that run on **every** package, not just on test
fixtures.

- **E008 resolved (code):** `main.py` now forces UTF-8 on stdout/stderr
  (`_force_utf8_console`) and **always** persists the extraction into
  `output/<part>/<part>_extraction.json` — READY or BLOCKED — via
  `_save_extraction`. A paid extraction can no longer be lost to a console crash,
  and any BLOCKED part is re-runnable with `--from-json` at no API cost.
- **E010 resolved (code):** `pipeline/schema.canonicalize_applies_to()` maps the
  verbose, view-qualified `applies_to` labels the extractor really emits
  (e.g. `"width (top view, overall horizontal)"`, `"thru hole diameter (4 places)"`)
  to canonical tokens, most-specific-first so `"counterbore depth"` resolves to
  `cbore_depth`, not `depth`. `is_envelope_label()` accepts only OVERALL envelope
  dims and rejects feature-local decoys like `"width (front view, small feature)"`,
  so hole-centering and feasibility checks use the true envelope. Wired into
  `_dims_map`, `_envelope`, the final-verify envelope, and the validator's
  pattern-feasibility check. Test: `tests/test_reliability_hardening.py`.
- **Static self-validation (Phase 7 / Phase 10):** `pipeline/macro_audit.py`
  scans every generated `.vba` for banned/nonexistent APIs (E004
  `GetModelBoundingBox`, E006 by-name sketch reselection) and structural defects
  (unbalanced `Sub`/`End Sub` and `Function`/`End Function`, missing
  `Option Explicit`, feature macros with no `LogResult` trail). `generate_macro_package`
  **raises** on any error-severity finding, and writes `<part>_audit_report.json`
  (also embedded in the build plan under `"audit"`). A known failure mode can no
  longer ship even if a future generator change reintroduces it.
- **Position reconstruction (safe subset):** `_hole_positions` now lays out a
  multi-instance hole callout as a centered row when a spacing can be GROUNDED in
  extracted data — the callout's `pattern_spacing` or a structured
  `equal_spacing` relationship keyed by feature_ref. With no such evidence it
  falls back to the single flagged `POSITION ASSUMED` instance exactly as before;
  positions are never invented from free-text descriptions. Verified byte-identical
  on 116-C/117-C/135-A (none carry structured spacing for the affected holes).
  The broader multi-hole placement for those parts needs the extractor to emit
  structured per-instance positions (now implemented — see below).
- **Explicit per-instance positions:** `HoleCallout.instance_positions` carries the
  `[x, y]` center of every instance (edge-referenced, drawing frame). When present,
  `_hole_positions` emits exactly those circles — the most reliable placement,
  bypassing all spacing/centering heuristics — and the extraction prompt now asks
  for it on every qty>1 callout. The validator advises (non-fatal) when the count
  disagrees with `qty` or a position falls outside the envelope. Existing
  extractions (empty list) are byte-identical; this lifts the 117-C-style
  "14 holes collapse to stacked points" failure once a drawing is re-extracted.
- **CI** *(correction 2026-09-28: this workflow file is **not** in the repository.
  It wasn't part of the uploaded code, so there is currently no CI. Re-add it
  before relying on this guard.)*: `.github/workflows/tests.yml` runs the full pytest suite on every push and
  PR (Ubuntu, Python 3.11; pywin32 is Windows-guarded so the non-SolidWorks half
  runs cleanly), so a regression can never merge silently.
- **Batch mode (scale):** `--batch <dir>` (`pipeline/batch.py`) runs the full
  pipeline over every drawing / `*_extraction.json` in a folder and writes
  `batch_summary.csv` (part, status, readiness sub-scores, macro counts, blocking
  reason) for triage at thousands-of-drawings scale. One bad input never sinks the
  batch.
- **Golden snapshot tests:** `tests/test_golden_macros.py` snapshots the full text
  of every generated file for a frozen fixture (generation is deterministic — no
  baked-in timestamps/paths). Any unintended change to macro output fails the test;
  `UPDATE_GOLDEN=1` accepts an intended change for PR review.
- **Drawing completeness score (Phase 4):** the verification report now prints
  geometry/dimension/consistency/feature sub-scores and an overall *macro
  readiness* percentage (`compute_readiness`). Advisory by default; set
  `MACRO_READINESS_THRESHOLD` (e.g. `0.95`) to hard-gate low-readiness drawings.

## E011 — COM connect fails on SolidWorks 2025: constants type library pinned to 2024

- **Date:** 2026-10-04 · **Part:** SB11033 (smoke test) · **Stage:** COM build, `connect_to_solidworks`
- **Symptom:** `SolidWorksError: ... 'Library not registered.'` before any part is created.
- **Root cause:** `_SW_CONST_TYPELIB` hard-coded major version 20. The constants
  typelib registers one version per release, keyed in **hex** (SolidWorks 2025 =
  `21.0` = 33 decimal), so the 2024 value does not exist on a 2025 install.
- **Fix:** `_ensure_constants_typelib` tries majors (34, 33, 32, 20) newest first.
- **Rule:** never pin a SolidWorks type-library version; probe for it.
- **Result:** after the fix SB11033 builds on SW 2025 (33.5) identically to the
  2026-06-18 run: F001/F002/F003 built, F005/F006 chamfer and F007 fillet skipped (known, §3.2).
- **Test:** none (needs a live SolidWorks); verified by the smoke build above.

## E012 — COM fillets/chamfers never built: no edges selected, wrong fillet arg types

- **Date:** 2026-10-04 · **Parts:** every COM run since 2026-06-18 · **Stage:** COM build
- **Symptom:** `FeatureFillet3 returned None` / `InsertFeatureChamfer returned None` on
  every part. All fillets and chamfers were "skipped".
- **Root cause:** (1) the builders called `ClearSelection2` and then the feature API
  with nothing selected; (2) `FeatureFillet3`'s 7 array arguments were passed as null
  dispatches, which is a COM *Type mismatch*. They must be EMPTY Variants (`VT_EMPTY`).
  The 14-argument form (Options, R1, Dist2, Rho, Ftyp, OverflowType, ConicRhoType + 7
  arrays) matches the macro recorder.
- **Fix:** `_infer_edges` selects edges from `parent_feature`: edges where the parent
  meets earlier features, else the parent's own rims. They are selected with
  `Edge.Select4(True, SelectData)`. Every inference is flagged `EDGES INFERRED`, because
  the schema has no edge ids. Late binding exposes zero-argument members (`GetFaces`,
  `GetEdges`, `CreateSelectData`, ...) as properties OR methods, and a returned
  dispatch object is also "callable": use `_g()`.
- **Rule:** never call a selection-based feature API without verifying a selection.
  Array args for COM feature calls are `VARIANT(VT_EMPTY)`, never `None`/null dispatch.
- **Result:** SB11033 F005/F006/F007 and DEMO-PLATE-001 C1 now build on SW 2025.
- **Tests:** live only (needs SolidWorks); edge rule documented in `_infer_edges`.

## E013 — Boss "built" but added no material (embedded in the base)

- **Date:** 2026-10-04 · **Part:** SB11842 F002 · **Stage:** COM build
- **Symptom:** F002 reported complete, then its chamfer F004 failed with "no candidate
  edges". The boss was extruded into the flange from the same sketch plane and added
  zero volume, so it had no faces.
- **Fix:** `build_extrude_boss` compares total volume before and after. If nothing was
  added, it runs `EditUndo2(1)`, reselects the sketch by tree walk, and extrudes reversed.
  The result is flagged `DIRECTION ASSUMED`. A boss whose depth is in a dimension chain
  with earlier bosses now starts where they end (`_start_offset`, `swStartOffset`). This
  fixed SB11033's boss, which overlapped its flange (length 1.781 vs 1.971 overall).
- **Rule:** a feature that returns an object is not proof it changed the part. Check
  the volume.

## E014 — Verification BLOCKED a correct 2x2 hole grid as a 240 mm row

- **Date:** 2026-10-04 · **Part:** DEMO-PLATE-001 (GPT-6 Astra extraction) · **Stage:** gate
- **Symptom:** `Pattern infeasible: H001 spans 240 mm (4 x 80 spacing)` on a 100 x 60
  plate. The extraction had the exact four `instance_positions`.
- **Root cause:** `_check_pattern_envelopes` assumed every pattern is ONE straight row
  (`(qty-1) x spacing`).
- **Fix:** when a callout has instance positions, check their real x/y extents instead.
- **Tests:** `test_validator.py::test_grid_with_instance_positions_is_feasible_even_with_row_style_spacing`,
  `::test_instance_positions_outside_envelope_still_blocked`.

## E015 — Base plate dropped: labeled width/height instead of length/width

- **Date:** 2026-10-04 · **Part:** DEMO-PLATE-001 (Astra) · **Stage:** `run_models.resolve_unknowns`
- **Symptom:** "First feature F002 is 'hole'". The resolver removed F001 as an
  "ambiguous profile" because its dims were `overall_width` 100 / `overall_height` 60.
- **Fix:** `solidworks_builder.planar_extents` maps length/width, width/height or
  length/height pairs to sketch (x, y) by canonical label, with height always vertical.
  The resolver and builder share it. Same family as E010.
- **Tests:** `test_placement.py::test_planar_extents_maps_both_label_styles_to_100_by_60`,
  `::test_resolver_keeps_width_height_labeled_base`.

## E016 — One failed feature made the next one fail too (sketch left open)

- **Date:** 2026-10-04 · **Part:** SB11780 (Astra extraction) · **Stage:** COM build
- **Symptom:** F002 failed (no profile), then F003 failed with "Failed to enter
  sketch mode", even though F003 was fine.
- **Root cause:** F002's builder raised after `InsertSketch(True)` had opened a sketch.
  F003's `InsertSketch(True)` then *toggled that sketch closed*, so `ActiveSketch` was
  `None`.
- **Fix:** `build_model` calls `_close_open_sketch` in its failure handler, before the
  skip-or-abort decision.
- **Rule:** every failure path must leave SolidWorks out of sketch mode.

## E017 — Round parts built off-axis; a bore cut outside the part

- **Date:** 2026-10-04 · **Parts:** A040911E, SB11780 (June JSON); SB11842, A040921E
  (Astra JSON) · **Stage:** COM build
- **Symptom:** A040911E "built 5/5", but the bbox was 165 × 150.7 mm for a Ø6.498 disc:
  the Ø4.5 bore broke through the rim. SB11842's bore "found no material".
- **Root cause:** two frames. An unplaced circle was centered on the length/width
  "envelope" (A040911E's mislabeled 2.75 → (0, 1.375")). A placed feature sat at the
  origin. Astra also wrote one callout in both frames: `x/y_position` (0, 0) but
  `instance_positions` [[2.5, 2.5]].
- **Fix:** a circular base defines the part center (`round_base`/`part_center`).
  Features in a `concentric_group` with a placed feature take its center.
  Instance positions outside the part are re-framed when the shifted points all fit
  (`FRAME CORRECTED`). Otherwise the gate BLOCKS.
- **Tests:** `tests/test_root_cause_fixes.py` (F1, F6).

**Also noted (not a failure):** on the SW 2025 default part template, a sketch on "Front
Plane" maps to model Y-Z (extrusion along X). Geometry relative to the sketch is
correct. Scorers must project along each hole's axis rather than assume model XY.

## Open watch-list (not yet seen at runtime)

- `FullyDefineSketch` argument shape varies by SW version — currently wrapped
  in `On Error Resume Next`; verify on SW2024.
- VBA `NN_fillets_chamfers.vba` is still interactive (user pre-selects edges); the
  COM path now infers edges (E012). Port `_infer_edges` to the VBA generator.
- Edge inference picks every matching edge. "C1 both sides" works, but a chamfer
  meant for ONE side of a flange (SB11033 F006) gets all 4 rim edges. It needs edge
  ids in the IR (Feature IR v2).
- `swUnitSystem` change after `NewDocument` — confirm it applies to the
  document and not just detailing options.
- Counterbore second cut is blind from the same sketch plane — depth direction
  follows the retry logic, but verify the cbore lands on the correct face.
