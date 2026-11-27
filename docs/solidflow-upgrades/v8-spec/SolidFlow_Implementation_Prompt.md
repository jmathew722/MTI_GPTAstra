# SolidFlow — Mandatory Implementation and UI Update

## 0. Execution directive
Act as the senior full-stack and CAD automation engineer responsible for SolidFlow. Implement every requirement below in the existing repository. Do not merely provide recommendations, mockups, pseudocode, or a plan. Inspect the repository, identify the actual frontend, backend, pipeline, storage, scoring and launch entry points, and modify the appropriate files. Preserve existing user changes and avoid destructive resets. Use the existing framework, dependencies and design system wherever practical.

Before editing, inspect the repository instructions, current git status, README, configuration, pipeline interfaces and supplied scoring.MD (including case variants or the SCORER directory). Establish the existing launch and test commands. Track all requirements through implementation and verification. Do not stop after the first successful change.

Preserve the existing dark SolidFlow theme, Champagne Gold (#D6AF6B) primary actions, typography, sidebar behavior, drawing viewer, STL viewer, Pipeline Results and existing SolidWorks generation/export behavior. Do not introduce unrelated redesigns or duplicate screens.

## 1. Run All Parts — PDF and mixed-folder support
- Update the existing Run All Parts control and backend batch ingestion so a selected folder can contain PDF, JPG, JPEG and PNG inputs, including mixed folders and uppercase extensions. Use the existing folder-selection mechanism or a platform-compatible folder picker/upload fallback. Do not require manual conversion to JPEG.
- Validate actual file types, handle spaces and Unicode filenames, ignore unsupported files with a visible summary, and prevent path traversal and output collisions. Use stable per-input identifiers. Default to the selected folder's immediate files; expose recursive scanning only if supported explicitly.
- Route PDF inputs through the existing PDF extraction/rendering pipeline. Preserve original PDFs and page order. Render at a resolution appropriate for engineering annotations; retain vector/text extraction when available. Treat a multi-page drawing as one input job unless the existing pipeline explicitly defines a different grouping. Never silently discard pages.
- Display a preflight list with filenames, supported-file count, page counts where available, and estimated batch time/cost. Disable execution for empty or invalid selections and prevent accidental duplicate runs.
- Execute all eligible inputs using the existing pipeline and safe concurrency limits, particularly for SolidWorks/COM. Track queued, running, succeeded, failed and cancelled states where cancellation is supported. Isolate failures so one invalid drawing does not stop the remaining batch. Allow failed jobs to be retried without rerunning successful jobs.
- Preserve per-part output directories, SLDPRT/STL generation, project records, logs and scoring results. Verify that generated STL corresponds to the actual SLDPRT rather than a stale artifact.

Acceptance: PDF-only, image-only and mixed folders work end to end; uppercase extensions and multi-page PDFs are handled; empty folders and corrupt PDFs produce actionable errors; all eligible jobs are accounted for.

## 2. Scoring — dedicated left-sidebar tab
Add a top-level navigation item named **Scoring**. Integrate it with the existing router and active navigation styles. If a legacy Scoring Rubric screen exists, consolidate it into this tab rather than maintaining competing implementations.

### Source of truth
Read the supplied `scoring.MD` completely before implementing scoring. Use its exact criteria, weights, formulas, deductions, thresholds, rounding, eligibility rules and terminology. Do not invent or silently normalize a rubric. If the document is missing or contradictory, implement the nondependent UI and integration boundaries, clearly identify the blocker, and do not fabricate grades. Continue all other requirements.

### Scoring engine
- Integrate the existing scorer if available; otherwise implement a reusable, testable scoring module based strictly on scoring.MD. Use one authoritative calculation path for single-part and batch runs.
- Evaluate each completed part using the required evidence and persist the score, criterion breakdown, deductions, evidence references, evaluation status, run ID and rubric version. Missing evidence must follow the rubric; if unspecified, mark evaluation incomplete rather than assigning a misleading zero or full score.
- Expose the final score on a 0–100 scale according to the rubric. Validate boundaries and rounding; flag inconsistent results rather than hiding them. Failed generation and failed scoring must be distinguishable.
- Reuse persisted scores across navigation and reloads. Do not silently overwrite historical scores when the rubric changes. Support explicit reevaluation where appropriate.

### UI layout
Build a professional, responsive engineering dashboard using the existing visual system:
1. Overview: scored parts, pending evaluations, average score (completed valid scores only), and rubric version.
2. Part results: searchable table with drawing/part name, run timestamp, final score /100, status and access to detailed criterion breakdown. Show every batch input, including failures and pending results.
3. Scoring methodology: criterion, maximum points or weight, evaluation method, deductions and applicable thresholds, using the exact source document. Include total possible points and formula.
4. Worked example: one clearly labeled illustrative part, with criterion-level values, arithmetic, deductions and final score derived from the actual rubric. Do not present example data as measured results.
5. Part detail: actual evidence, awarded points, maximum points, reasons for deductions and evaluation errors. Use restrained status colors, readable tables and consistent spacing.

Acceptance: all rubric rules are covered by tests; worked example recomputes correctly; perfect, minimum, boundary, missing-evidence and deduction cases are tested where applicable; single and batch runs expose consistent persisted results. No fabricated grades.

## 3. Projects — drawing thumbnails and chronological ordering
- Replace generic blank PDF icons with actual first-page drawing previews generated from the original source PDF. For image inputs, use the source image. Preserve aspect ratio and avoid cropping engineering dimensions or title blocks. Use a neutral drawing canvas and existing card styling.
- Generate thumbnails using existing PDF rendering infrastructure or a compatible maintained renderer. Cache by stable source identity and content/version fingerprint; regenerate stale previews. Generate lazily or asynchronously to avoid blocking the project list. Provide loading, unavailable-source and rendering-error states. A fallback icon is acceptable only when a real preview cannot be produced.
- Use authorized source access and existing project storage; do not expose arbitrary local filesystem paths through public endpoints.
- Display the filename/project name and real persisted timestamp on every card or row. Default ordering must be newest activity first, not alphabetical. Define activity as the latest recorded project creation or run/update event, not thumbnail generation or page viewing. If the existing data model has a canonical recent-activity timestamp, reuse it. Preserve creation time separately.
- Store timestamps consistently (prefer UTC), display them in local time with date and time, and sort numerically by timestamp descending with a stable tie-breaker. Missing historical timestamps must be marked unknown or backfilled only from trustworthy metadata; do not invent dates.
- Ensure new or rerun projects appear in the correct order immediately and after reload. Clicking a preview must open the correct project using existing navigation.

Acceptance: actual PDF previews appear for valid sources, mixed input thumbnails work, newest activity appears first, timestamps survive reload, and missing/corrupt sources do not break the Projects page.

## 4. Workspace — Run Pipeline cost and time estimates
Place a compact, clearly labeled estimate area directly within the existing Workspace Run Pipeline section, adjacent to the existing run controls. Preserve the primary Champagne Gold Run Pipeline button.

Before execution display:
- Estimated runtime (range when uncertainty warrants it).
- Estimated cost in USD (range when appropriate).
- Input count and estimate availability; batch totals when Run All Parts is selected.

During execution display elapsed time, estimated remaining time when supported by reliable data, incurred cost where measurable, and existing stage progress. On completion display actual elapsed time and actual measured cost, keeping estimates distinguishable from actuals.

Implementation requirements:
- Trace the existing estimation, model usage, billing/pricing and timing logic. Fix incorrect units, stale state, missing bindings and inconsistent totals rather than adding decorative static values.
- Derive cost from actual configured model/provider pricing, expected or measured token usage, and other known billable operations. Respect cached-token and retry accounting where applicable. Do not invent prices or label estimated charges as actual billed amounts. Exclude unpriced local compute explicitly; if no pricing is available show unavailable, not $0.00. Use sufficient decimal precision for small charges.
- Derive time from relevant historical stage/run durations or documented configured assumptions, accounting for input/page count and actual concurrency. If no credible estimate exists, show insufficient history rather than fake precision. Do not treat CAD work as parallel if SolidWorks is serialized.
- Recompute estimates on input, batch, model or pipeline configuration changes. Prevent stale asynchronous responses from replacing newer estimates. Use one backend source of truth and consistent units (seconds internally, USD or precise decimal monetary units).
- Persist run start/end times and available usage records. Handle retries, failures, cancellation, refresh and reconnection without resetting elapsed time or double-counting costs. Keep unknown values distinct from zero.
- Example display format only: Estimated time: 2–4 min | Estimated cost: $0.12–$0.20. These numbers are illustrative, never hardcoded production estimates.

Acceptance: estimates update with selection changes; batch totals reconcile with the execution strategy; live values update correctly; actual values persist after completion; unavailable data is clearly labeled; zero, small-cost, failed and retried cases are tested.

## 5. Integration, verification and launch
- Implement any required API contracts, schema migrations, shared types, state management, loading/error states and documentation. Keep existing records backward compatible. Do not delete existing projects or generated CAD files.
- Run the repository's actual formatter, lint, type checks, unit tests, integration tests and production build where available. Add targeted tests for all four requirements. Fix regressions caused by your changes. Clearly distinguish automated tests, mocked tests and real CAD execution.
- Exercise the UI in a browser using available tooling: sidebar navigation, folder selection, batch progress, scoring details, thumbnail display, ordering, estimate changes, refresh and failure states. Check desktop and narrower layouts. Capture screenshots of the four updated areas if tooling permits, saving them in an appropriate verification folder.
- Use supplied or existing safe test fixtures for PDF-only, image-only and mixed batches. Do not run a large paid batch without approval; use mocks or bounded approved tests and disclose the distinction. If SolidWorks, API credentials, scoring.MD or a required runtime is unavailable, finish independent work and report precisely which real execution could not be verified.
- Verify that existing Home, Workspace, Projects, Pipeline Results, Corrections, drawing viewer and CAD/STL workflows remain functional wherever present. Preserve existing configuration and secrets; never print credentials.
- Update the README or existing project documentation with exact setup, migration, test and launch commands. Do not create a parallel application.
- Start the updated frontend and required backend using the repository's actual supported launch commands. Verify service health and that the updated UI loads. Report the real local URL and whether services remain running. If launch is impossible, provide the exact error and commands needed to resolve it; never claim a successful launch without evidence.

## 6. Definition of done and final report
Do not declare completion until every requirement is implemented and verified or explicitly marked blocked with evidence. Provide a concise final report containing:
- Requirement-by-requirement status: implemented and verified, implemented but unverified, or blocked.
- Changed files and migrations; scoring.MD source/version and any ambiguities.
- Actual test/build commands and results, real versus mocked execution, and screenshots if captured.
- Remaining issues, assumptions, and decisions made without explicit guidance.
- Exact launch command, verified local URL, and service status.

Begin by inspecting the repository and supplied rubric, then implement, test, fix and launch. Do not return only an implementation plan. Complete all independent work before reporting blockers.
