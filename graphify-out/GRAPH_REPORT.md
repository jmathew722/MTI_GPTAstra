# Graph Report - mti-2d-3d  (2026-09-28, AST update 2026-10-04)

## Update 2026-10-04 (AST layer only, `graphify-out/ast_update.py`)

The semantic graph below was built on 2026-09-28 at the initial-code commit. The `/graphify`
skill isn't available on the current dev host, so the **code layer** was refreshed
deterministically with Python `ast` (no LLM): 51 changed or new Python files re-extracted,
following graphify's id and label conventions. Every refreshed node and edge is tagged
`"_update": "ast-2026-10-04"`. The semantic nodes (rationale, concepts, drawings) are unchanged.
Run the full semantic refresh (`/graphify . --update`) when the skill is available.

- **1,184 nodes · 2,787 edges** (was 813 · 1,792). `built_at_commit` = `7b099b3`.
- **New communities:** Feature IR v2 (plans, compilers) · GPT-6 Astra Planner · API Budget
  Guard ($20 cap) · Placement & Root-Cause Fixes · Demo Plate (known answer) · Benchmark Split ·
  Graph Tooling. The token tracker files (added after the semantic build) joined Token Cost Ledger.
- **Main new paths:**
  `ir_pipeline.run_part` → `planner.OpenAIPlanner` → `ir.model.BuildPlan.check` →
  `ir.compile_cadquery.emit_script/run_script` → `ir.compile_solidworks.compile_solidworks`;
  the extractor and planner → `budget.preflight/charge` → `token_tracker.record_completion`;
  `run_models.resolve_unknowns` → `fasteners` / `macro_generator._hole_positions` →
  `solidworks_builder.build_hole`.
- **Highest-degree refreshed nodes:** `run_verification()` (70), `solidworks_builder.py` (63),
  `macro_generator.py` (62), `main.py` (48), `generate_macro_package()` (46), `run_models.py`
  (41), `resolve_unknowns()` (40), `extract_drawing_data()` (36).
- Test record for the day: `docs/test-reports/2026-10-04-test-report.md`.

## Corpus Check
- Large corpus: 121 files · ~514,936 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder.

## Summary
- 813 nodes · 1792 edges · 45 communities (35 shown, 9 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 159 edges (avg confidence: 0.89)
- Token cost: 838,917 input · 0 output

## Community Hubs (Navigation)
- Claude Vision Extractor
- Built Parts & Macro Hardening
- Drawing Schema Contract
- View Ingest & Batch COM Driver
- Setup & Dependencies
- VBA Package Parts (115-135)
- Verification Gate Checks
- Validator Tests
- VBA Feature Emitters
- COM Feature Builders
- Macro Robustness Tests
- Batch Triage
- Post-Build Model Validator
- CLI Entry Point
- Static Macro Audit
- Units & Chamfer Tests
- Macro Package Assembly
- Token Cost Ledger
- Report Formatting & Gen Tests
- Mismatched Views 0014630E/16247/A001211E/A001271E
- Readiness Score & Hardening Tests
- Bronze Bearing & Spacer Drawings
- COM Boss/Cut/Fillet Builders
- Bracket Drawings A001621E/A001821M/A001901E
- SolidWorks Session & Save
- Check Valve Plate Family
- Hole Position Tests
- Slotted Plate Duplicates
- RUN_ALL & Setup Macros
- Bolt Circle Flanges
- Hole Placement Logic
- Macro Generation Errors
- Package Structure Tests
- Prohibited Feature Tests
- RUN_ALL Tests
- SB-11033 Work Backup
- Hole Generation Tests
- Platform Errors
- A001591E Bar vs Bushing
- Pytest Config
- Utils Package
- Key 135-A
- Extraction Cache
- Multi-View Input

## God Nodes (most connected - your core abstractions)
1. `DrawingData` - 62 edges
2. `run_verification()` - 62 edges
3. `generate_macro_package()` - 52 edges
4. `format_verification_report()` - 32 edges
5. `extract_drawing_data()` - 31 edges
6. `Feature` - 30 edges
7. `SolidWorks Macro Error Log` - 27 edges
8. `SolidWorksError` - 22 edges
9. `build_model()` - 21 edges
10. `valid_drawing()` - 21 edges

## Surprising Connections (you probably didn't know these)
- `Static Macro Self-Validation` --semantically_similar_to--> `Dimensional Closure Check`  [INFERRED] [semantically similar]
  docs/solidworks-macro-error-log.md → 2D-3D-CAD-Test-Generation/Deliverables/A040911E/A040911E_design_decisions.txt
- `A040911E - Bronze Flanged Bearing (dwg 4091-B)` --conceptually_related_to--> `Counterbore / Spot-Face Feature`  [INFERRED]
  ViewDefinedDrawings/A040911E-20260618T093212Z-3-001/A040911E/A040911E.png → DrawingPDFs/A001151E.PDF
- `SB11842 – Spindle Back-Up (Box) (Part)` --conceptually_related_to--> `Counterbore / Spot-Face Feature`  [INFERRED]
  ViewDefinedDrawings/SB11842-20260618T093328Z-3-001/SB11842/SB11842.png → DrawingPDFs/A001151E.PDF
- `SolidWorks Macro Error Log` --references--> `canonicalize_applies_to()`  [EXTRACTED]
  docs/solidworks-macro-error-log.md → 2D-3D-CAD-Test-Generation/pipeline/schema.py
- `E010: Base Plate Unscriptable — Verbose applies_to Labels` --rationale_for--> `canonicalize_applies_to()`  [EXTRACTED]
  docs/solidworks-macro-error-log.md → 2D-3D-CAD-Test-Generation/pipeline/schema.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Two-Phase Extraction/Verification → Build Pipeline** — 2d_3d_cad_test_generation_readme, concept_two_phase_pipeline, concept_verification_gate, 2d_3d_cad_test_generation_pipeline_extractor, 2d_3d_cad_test_generation_pipeline_validator, 2d_3d_cad_test_generation_pipeline_macro_generator [EXTRACTED 1.00]
- **Error-Driven Generator Hardening Loop (log → fix generator → regression test → regenerate)** — docs_solidworks_macro_error_log, error_e001_no_default_part_template, error_e004_getmodelboundingbox_invalid_api, error_e006_could_not_select_profile_sketch, 2d_3d_cad_test_generation_pipeline_macro_generator, 2d_3d_cad_test_generation_tests_test_macro_generator [INFERRED 0.85]
- **Ambiguous Dimension → Best-Guess → Human-Review Loop** — concept_ambiguous_dimension_flagging, concept_verification_gate, 2d_3d_cad_test_generation_deliverables_a040911e_a040911e_design_decisions, 2d_3d_cad_test_generation_deliverables_a040921e_a040921e_design_decisions, 2d_3d_cad_test_generation_deliverables_sb11780_sb11780_design_decisions [INFERRED 0.70]
- **Automated Pipeline Cannot Auto-Place Bolt-Circle/Patterned Holes** — 2d_3d_cad_test_generation_output_concepts_hole_auto_placement_limitation, 2d_3d_cad_test_generation_output_a040911e_part, 2d_3d_cad_test_generation_output_sb11033_part, 2d_3d_cad_test_generation_output_sb11842_part [INFERRED 0.85]
- **Chamfer/Fillet Features Skipped Across Automated Builds** — 2d_3d_cad_test_generation_output_concepts_chamfer_fillet_automated_build_skip, 2d_3d_cad_test_generation_output_a040911e_part, 2d_3d_cad_test_generation_output_a040921e_part, 2d_3d_cad_test_generation_output_sb11033_part, 2d_3d_cad_test_generation_output_sb11842_part [INFERRED 0.85]
- **Dimension Chains Treated as Step-Within-Overall Across Parts** — 2d_3d_cad_test_generation_output_concepts_dimension_chain_removed_as_step_not_loop, 2d_3d_cad_test_generation_output_a040911e_part, 2d_3d_cad_test_generation_output_a040921e_part, 2d_3d_cad_test_generation_output_sb11780_part, 2d_3d_cad_test_generation_output_sb11842_part [INFERRED 0.85]
- **Check Valve Mounting Plate Family (Model 90B)** — drawingpdfs_a001131e_part, drawingpdfs_a001151e_part, drawingpdfs_a001171e_part [INFERRED 0.75]
- **Duplicated Oval Shroud Drawing Sheet** — newverifieddrawings_0014630e_front_view_1_image, newverifieddrawings_a001271e_side_view_1_image, concept_sheet_metal_fabrication [INFERRED 0.65]
- **Threaded Fastener Hole Family** — newverifieddrawings_a001211e_front_view_1_image, newverifieddrawings_a001271e_1_image, concept_threaded_hole [EXTRACTED 1.00]
- **Patterned Through-Hole Drilling Family** — newverifieddrawings_0014630e_image, newverifieddrawings_16247_front_view_1_image, newverifieddrawings_a001211e_front_view_1_image [INFERRED 0.75]
- **Slotted Mounting Plate Family (Possible Duplicate Drawing)** — newverifieddrawings_a001291e_part, newverifieddrawings_a001561e_part, newverifieddrawings_a001581e_part [INFERRED 0.75]
- **A001291E Bolt Pattern with Position Tolerance** — newverifieddrawings_a001291e_front_view_image, concept_bolt_circle, concept_positional_tolerance [EXTRACTED 1.00]
- **Round Flange Bolt-Circle Family** — newverifieddrawings_a001621e_side_view__1__image, newverifieddrawings_a001821m__1__image, concept_bolt_circle [INFERRED 0.75]
- **Notched Bracket Family** — newverifieddrawings_a001621e_front_view__1__image, newverifieddrawings_a001821m_side_view__1__image, concept_sheet_metal_bracket [INFERRED 0.75]
- **Counterbored Screw Features** — newverifieddrawings_a001621e__1__image, newverifieddrawings_a001621e_side_view__1__image, concept_counterbore [EXTRACTED 1.00]
- **A040911E Drawing View Set** — viewdefineddrawings_a040911e_20260618t093212z_3_001_a040911e_a040911e_image, viewdefineddrawings_a040911e_20260618t093212z_3_001_a040911e_a040911e_front_image, viewdefineddrawings_a040911e_20260618t093212z_3_001_a040911e_a040911e_side_image [EXTRACTED 1.00]
- **A040921E Drawing View Set** — viewdefineddrawings_a040921e_20260618t093224z_3_001_a040921e_a040921e_image, viewdefineddrawings_a040921e_20260618t093224z_3_001_a040921e_a040921e_front_image, viewdefineddrawings_a040921e_20260618t093224z_3_001_a040921e_a040921e_side_image [EXTRACTED 1.00]
- **SB-11033 Drawing View Set** — viewdefineddrawings_sb11033_20260618t093243z_3_001_sb11033_sb11033_image, viewdefineddrawings_sb11033_20260618t093243z_3_001_sb11033_sb11033_front_image, viewdefineddrawings_sb11033_20260618t093243z_3_001_sb11033_sb11033_side_image [EXTRACTED 1.00]
- **SB11780 Tie Rod Drawing Views** — viewdefineddrawings_sb11780_part, viewdefineddrawings_sb11780_20260618t093317z_3_001_sb11780_sb11780_image, viewdefineddrawings_sb11780_20260618t093317z_3_001_sb11780_sb11780_front_image [EXTRACTED 1.00]
- **SB11842 Spindle Back-Up Drawing Views** — viewdefineddrawings_sb11842_part, viewdefineddrawings_sb11842_20260618t093328z_3_001_sb11842_sb11842_image, viewdefineddrawings_sb11842_20260618t093328z_3_001_sb11842_sb11842_front_image [EXTRACTED 1.00]

## Communities (45 total, 9 thin omitted)

### Community 0 - "Claude Vision Extractor"
Cohesion: 0.06
Nodes (53): _accumulate_usage(), _build_client(), _cache_key(), _cache_lookup(), _cache_store(), _call(), _confidence_threshold(), _drawing_data_tool() (+45 more)

### Community 1 - "Built Parts & Macro Hardening"
Cohesion: 0.05
Nodes (50): A040911E Design Decision & Verification Report, A040921E Design Decision & Verification Report, SB-11033 Design Decision & Verification Report, SB11780 Design Decision & Verification Report, SB11842 Design Decision & Verification Report, .github/workflows/tests.yml (CI), _force_utf8_console(), _save_extraction() (+42 more)

### Community 2 - "Drawing Schema Contract"
Cohesion: 0.07
Nodes (32): canonicalize_applies_to(), ConcentricGroup, Dimension, DimensionChain, DimensionType, FeatureType, GeometricTolerance, HoleCallout (+24 more)

### Community 3 - "View Ingest & Batch COM Driver"
Cohesion: 0.09
Nodes (36): classify_view(), _collect_part(), discover_parts(), PartViews, Path, Discover per-part, per-view drawing images from a folder. Input model (separate…, Discover all parts and their view images under ``folder``. Each immediate…, (view_type, path) pairs in canonical VIEW_ORDER, present ones only. (+28 more)

### Community 4 - "Setup & Dependencies"
Cohesion: 0.07
Nodes (43): 2D→3D SolidWorks Pipeline README, Python Requirements (requirements.txt), check_and_install_packages(), check_poppler(), check_python(), check_pywin32_makepy(), ensure_env_file(), main() (+35 more)

### Community 5 - "VBA Package Parts (115-135)"
Cohesion: 0.10
Nodes (39): 115 C-RevB Verification Report, 115 C-RevB Macros README, Part 115 C-RevB, 116-C-Rev90B Verification Report, 116-C-Rev90B Macros README, Part 116-C-Rev90B, 117-C-RevB Verification Report, 117-C-RevB Macros README (+31 more)

### Community 6 - "Verification Gate Checks"
Cohesion: 0.12
Nodes (31): DrawingData, Top-level structured representation of one engineering drawing., Best available name for files/folders: part_number > part_name > 'part'., _check_ambiguity(), _check_build_order(), _check_completeness(), _check_dependencies(), _check_dimensional_closure() (+23 more)

### Community 7 - "Validator Tests"
Cohesion: 0.12
Nodes (17): DrawingValidationError, Exception, Validate extracted data for build readiness (raising wrapper). Kept for the COM…, Raised when extracted data fails build-readiness validation., validate_drawing_data(), Tests for pipeline.validator build-readiness checks., A minimal but fully build-ready drawing: extruded block with a hole., TestBaseFeature (+9 more)

### Community 8 - "VBA Feature Emitters"
Cohesion: 0.18
Nodes (24): _cut4(), _depth_of(), _dims_map(), _extrusion3(), _fail_block(), _feature_check_and_name(), _macro_extrude(), _macro_fillet_chamfer() (+16 more)

### Community 9 - "COM Feature Builders"
Cohesion: 0.14
Nodes (22): Feature, build_hole(), build_model(), build_pattern(), check_rebuild_errors(), _coerce(), dispatch_feature_builder(), get_feature_by_id() (+14 more)

### Community 10 - "Macro Robustness Tests"
Cohesion: 0.09
Nodes (10): bracket_drawing(), A small bracket: base plate + 4-hole pattern + fillet + a prohibited shell., Macros must survive machines with no default template / renamed planes., Recorded-macro pattern: feature calls consume the ACTIVE sketch. No closing…, A pattern whose instances were already cut by the parent hole feature must not…, Quotes/unicode in model-supplied text must not break VBA literals., TestMachineRobustness, TestNeedsReview (+2 more)

### Community 11 - "Batch Triage"
Cohesion: 0.13
Nodes (20): BatchRow, iter_inputs(), process_drawing_data(), Path, Batch processing for many drawings (scale-to-thousands triage). Walks a…, Process every input in ``directory`` and write ``batch_summary.csv``.…, Write a list of BatchRow to ``<output_dir>/<name>`` and return the path., Return ``(path, is_json)`` for every processable input in ``directory``.… (+12 more)

### Community 12 - "Post-Build Model Validator"
Cohesion: 0.14
Nodes (11): _coerce(), _dims_in_meters(), _matches_any(), Any, Post-build model validation. After SolidWorks builds the part, confirm it…, All dimension values (in meters) whose applies_to matches., Verify the built model matches the drawing's dimensions. Args: sw_doc: The live…, validate_model() (+3 more)

### Community 13 - "CLI Entry Point"
Cohesion: 0.16
Nodes (21): _extract_cache_dir(), _extract_one_drawing(), _extract_part_views(), _force_utf8_console(), main(), _prepare_and_extract(), Path, 2D -> 3D SolidWorks Pipeline — entry point. Phase 1 (any OS): prepare image ->… (+13 more)

### Community 14 - "Static Macro Audit"
Cohesion: 0.15
Nodes (11): audit_package(), audit_text(), AuditReport, BannedApi, Finding, Path, Static self-validation of generated VBA macros (Phase 7 + Phase 10). Every…, Audit a single macro's source text. Returns all findings for it. (+3 more)

### Community 15 - "Units & Chamfer Tests"
Cohesion: 0.15
Nodes (12): build_chamfer(), get_dimensions_for_feature(), Resolve a feature's dimensions to METERS, keyed by ``applies_to``. Every value…, Apply a chamfer. FRAGILE — wrapped by the orchestrator like fillet., Tests for utils.unit_converter — the most safety-critical module., TestAssertMeters, TestToRadians, assert_meters() (+4 more)

### Community 16 - "Macro Package Assembly"
Cohesion: 0.13
Nodes (19): BuildStep, _final_verify_macro(), generate_macro_package(), _macro_pattern_covered(), MacroPackage, _pattern_covered_by(), Any, Path (+11 more)

### Community 17 - "Token Cost Ledger"
Cohesion: 0.17
Nodes (9): estimate_cost(), Path, Token-usage and Claude API cost ledger. Appends one row per extraction run to a…, USD cost of one run's token usage. Cache hits (no tokens) cost $0., Append one run to the ledger and rewrite the human-readable total. Returns the…, record_run(), Tests for the token/cost ledger (pipeline.usage_log)., TestEstimateCost (+1 more)

### Community 18 - "Report Formatting & Gen Tests"
Cohesion: 0.15
Nodes (8): format_verification_report(), Render the human-readable VERIFICATION REPORT (spec format)., package(), fixture, Tests for pipeline.macro_generator — VBA package generation., TestAmbiguity, TestDimensionalClosure, TestVerificationReportFormat

### Community 19 - "Mismatched Views 0014630E/16247/A001211E/A001271E"
Cohesion: 0.16
Nodes (18): Heat Treatment Specification, Linear/Patterned Through-Hole Array, Sheet Metal Fabrication, 0014630E Front View - Oval Shroud (mismatched content), 0014630E Rectangular Mounting Plate Drawing, Part 0014630E, 0014630E Side View - Long Drilled Bar + Post Detail (mismatched content), 16247 Full Drawing - Post/Blade Profile (+10 more)

### Community 20 - "Readiness Score & Hardening Tests"
Cohesion: 0.15
Nodes (9): compute_readiness(), Phase-4 drawing-completeness score (0..1 sub-scores + overall). Advisory and…, fixture, Regression tests for the reliability-hardening pass. Covers four failure…, A plate whose applies_to labels are verbose, view-qualified free text — exactly…, TestExtractionPersistence, TestReadiness, TestVerboseLabelsStillBuild (+1 more)

### Community 21 - "Bronze Bearing & Spacer Drawings"
Cohesion: 0.21
Nodes (17): Center Hole / Center-Drill Feature, Edge Chamfer, Datum Reference / GD&T Control, Surface Finish / Coating Callout, Tapped (Threaded) Hole, A040911E Bearing - Front View, A040911E Bearing - Full Drawing, A040911E Bearing - Side Section View (+9 more)

### Community 22 - "COM Boss/Cut/Fillet Builders"
Cohesion: 0.16
Nodes (14): build_extrude_boss(), build_extrude_cut(), build_fillet(), _null_dispatch(), _origin_relation_for_rectangle(), Select the named reference plane for the next sketch., Verify the active sketch is fully defined before extruding. An under-defined…, Best-effort: relate the sketch to the origin so it's anchored. (+6 more)

### Community 23 - "Bracket Drawings A001621E/A001821M/A001901E"
Cohesion: 0.23
Nodes (13): GD&T Positional Tolerance, Sheet Metal Bracket (12 GA), Through-Hole Drill Pattern, A001621E Main View, A001621E Front View, A001621E Part, A001821M Front View, A001821M Part (+5 more)

### Community 24 - "SolidWorks Session & Save"
Cohesion: 0.20
Nodes (11): _const(), _constants(), create_new_part(), Path, Create a new part document. Raises: SolidWorksError: if the template is missing…, Raised on any SolidWorks build failure. Carries the partial-save path., Save the part as a .sldprt and return the absolute path. Raises:…, Return the win32com SolidWorks constants namespace (requires makepy/gencache). (+3 more)

### Community 25 - "Check Valve Plate Family"
Cohesion: 0.24
Nodes (12): C56815 Assembly (referenced part), C5G-805 Check Valve (referenced part), Counterbore / Spot-Face Feature, Dowel Pin Locating Feature, NPTF Tapered Pipe Thread Port, Threaded Hole Feature, Check Valve Adaptor (117-C), Check Valve Eliminator (116-C) (+4 more)

### Community 26 - "Hole Position Tests"
Cohesion: 0.29
Nodes (4): _equal_spacing_drawing(), A plate with 3 holes whose spacing comes ONLY from a structured equal_spacing…, TestExplicitInstancePositions, TestPositionFromEqualSpacing

### Community 27 - "Slotted Plate Duplicates"
Cohesion: 0.33
Nodes (10): Positional (GD&T) Tolerance, Slotted Hole, Stock Material Tolerance, A001291E Front View (Plate w/ 3 Holes), Part A001291E, A001291E Side View (Slotted 21x6 Plate), Part A001561E, A001561E Side View (Slotted 21x6 Plate) (+2 more)

### Community 28 - "RUN_ALL & Setup Macros"
Cohesion: 0.29
Nodes (7): _build_run_all(), _final_verify_body(), Body of the setup step (create part, set units, save) — header-free so it can…, Body of the final-verify step (header-free; reused by RUN_ALL)., Assemble RUN_ALL.vba: one self-contained macro that runs every step in order in…, _safe_name(), _setup_body()

### Community 29 - "Bolt Circle Flanges"
Cohesion: 0.43
Nodes (7): Bolt Hole Pattern (BSC), A001621E Side View, A001821M Main View, SB11842 Spindle Back-Up - Bolt Circle View (Front), SB11842 Spindle Back-Up (Box) - Full Drawing Sheet, SB11842 Spindle Back-Up - Profile View (Side), SB11842 – Spindle Back-Up (Box) (Part)

### Community 30 - "Hole Placement Logic"
Cohesion: 0.33
Nodes (6): _effective_spacing(), _envelope(), _hole_positions(), The part's length/width envelope in drawing units (None when not extracted)., Best available (spacing, qty) for a callout, in drawing units. Prefer the…, Instance centers in the DRAWING FRAME (base plate lower-left corner at origin).…

### Community 31 - "Macro Generation Errors"
Cohesion: 0.40
Nodes (5): MacroGenerationError, _profile_vba(), Exception, Raised when macro generation cannot proceed (e.g. BLOCKED data)., VBA to draw a circle (centered at cx, cy) or rectangle (lower-left corner at…

### Community 35 - "SB-11033 Work Backup"
Cohesion: 0.40
Nodes (5): Equally Spaced Hole Pattern, SB-11033 Work Backup - End View, SB-11033 Work Backup - Full Drawing, SB-11033 Work Backup - Section A-A View, SB-11033 - Work Backup Tool (AMF Welder)

### Community 37 - "Platform Errors"
Cohesion: 0.67
Nodes (3): PlatformError, Raised when SolidWorks/COM functionality is used off Windows., RuntimeError

### Community 38 - "A001591E Bar vs Bushing"
Cohesion: 0.67
Nodes (3): A001591E Long Bar (12 GA, End Holes), A001591E Front View (Small Bushing/Washer), Part A001591E

## Ambiguous Edges - Review These
- `Forced Tool Call Extraction Pattern` → `Structured Outputs via messages.parse`  [AMBIGUOUS]
  docs/superpowers/specs/2026-06-11-2d-to-3d-solidworks-pipeline-design.md · relation: conceptually_related_to
- `A001291E Side View (Slotted 21x6 Plate)` → `Part A001291E`  [AMBIGUOUS]
  NewVerifiedDrawings/A001291E_side_view (1).png · relation: references
- `A001591E Front View (Small Bushing/Washer)` → `Part A001591E`  [AMBIGUOUS]
  NewVerifiedDrawings/A001591E_front_view (1).png · relation: references
- `A001601E Side View (Cylindrical Sleeve)` → `Part A001601E`  [AMBIGUOUS]
  NewVerifiedDrawings/A001601E_side_view (1).png · relation: references
- `SB11780 Tie Rod - Full Drawing Sheet` → `Surface Finish / Coating Callout`  [AMBIGUOUS]
  ViewDefinedDrawings/SB11780-20260618T093317Z-3-001/SB11780/SB11780.png · relation: conceptually_related_to

## Knowledge Gaps
- **38 isolated node(s):** `BannedApi`, `_NoFeature`, `.github/workflows/tests.yml (CI)`, `Two-Phase Pipeline (Extraction+Verification / Build)`, `Multi-View Per-Part Input Pipeline` (+33 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 255 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Forced Tool Call Extraction Pattern` and `Structured Outputs via messages.parse`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `A001291E Side View (Slotted 21x6 Plate)` and `Part A001291E`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **What is the exact relationship between `A001591E Front View (Small Bushing/Washer)` and `Part A001591E`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **What is the exact relationship between `A001601E Side View (Cylindrical Sleeve)` and `Part A001601E`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **What is the exact relationship between `SB11780 Tie Rod - Full Drawing Sheet` and `Surface Finish / Coating Callout`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `DrawingData` connect `Verification Gate Checks` to `Claude Vision Extractor`, `Drawing Schema Contract`, `View Ingest & Batch COM Driver`, `Validator Tests`, `VBA Feature Emitters`, `COM Feature Builders`, `Post-Build Model Validator`, `Units & Chamfer Tests`, `Macro Package Assembly`, `Report Formatting & Gen Tests`, `Readiness Score & Hardening Tests`, `RUN_ALL & Setup Macros`, `Hole Placement Logic`?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Why does `run_verification()` connect `Verification Gate Checks` to `Claude Vision Extractor`, `Built Parts & Macro Hardening`, `View Ingest & Batch COM Driver`, `Validator Tests`, `Macro Robustness Tests`, `Batch Triage`, `CLI Entry Point`, `Static Macro Audit`, `Report Formatting & Gen Tests`, `Readiness Score & Hardening Tests`, `Hole Position Tests`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._